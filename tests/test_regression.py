"""Regression tests for actual defects and the explicitly partial geometry profile."""
import json
import math
from pathlib import Path
import random
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'src'))
import geosot_core as gc
import geosot_service as svc
import gbt40087_partial as partial
from offline_api import call_api, make_server
import test_all
import encode_data as ed

CTX={'crs':partial.CRS,'height_reference':partial.HEIGHT_REFERENCE}


class TestPartialProfile(unittest.TestCase):
    def test_real_minutes_are_not_stretched(self):
        key=partial.encode(39.5,116.5,100,15,**CTX)
        result=partial.describe(key,**CTX)
        self.assertEqual(result['bounds']['lat_min'],39.5)
        self.assertAlmostEqual(result['bounds']['lat_max'],39+31/60)

    def test_point_containment_all_levels(self):
        rnd=random.Random(40087)
        for lv in range(9,33):
            for _ in range(30):
                lat,lng,h=rnd.uniform(0.01,87.9),rnd.uniform(0.01,179.9),rnd.uniform(1,19999)
                b=partial.describe(partial.encode(lat,lng,h,lv,**CTX),**CTX)['bounds']
                self.assertLessEqual(b['lat_min'],lat);self.assertLess(lat,b['lat_max'])
                self.assertLessEqual(b['lng_min'],lng);self.assertLess(lng,b['lng_max'])
                self.assertLessEqual(b['height_min'],h);self.assertLess(h,b['height_max'])

    def test_lower_corner_roundtrip_all_levels(self):
        for lv in range(9,33):
            for lat,lng in [(39.9,116.31234),(0.1234567,0.7654321),(87.9,179.9999)]:
                key=partial.encode(lat,lng,100,lv,**CTX)
                b=partial.describe(key,**CTX)['bounds']
                self.assertEqual(partial.encode(b['lat_min'],b['lng_min'],b['height_min'],lv,**CTX),key)

    def test_height_uses_exponential_inverse(self):
        for lv in (15,21,28,32):
            for height in (0,100,10000,20000):
                n=partial.height_index(height,lv)
                self.assertLessEqual(partial.height_boundary(n,lv),height+1e-8)
                self.assertGreater(partial.height_boundary(n+1,lv),height-1e-8)
                self.assertEqual(partial.height_index(partial.height_boundary(n,lv),lv),n)

    def test_boundary_tolerance_is_explicit_and_bounded(self):
        n,lv=100,21
        boundary=partial.height_boundary(n,lv)
        self.assertEqual(partial.height_index(math.nextafter(boundary,-math.inf),lv),n)
        self.assertEqual(partial.height_index(boundary-1e-6,lv),n-1)
        self.assertEqual(partial.height_index(boundary+1e-6,lv),n)
        key=partial.encode(39.9,116.31234,100,20,**CTX)
        b=partial.describe(key,**CTX)['bounds']
        self.assertNotEqual(partial.encode(b['lat_min']-1e-9,b['lng_min'],100,20,**CTX),key)
        self.assertEqual(partial.encode(math.nextafter(b['lat_min'],-math.inf),b['lng_min'],100,20,**CTX),key)

    def test_invalid_domain_and_bool_rejected(self):
        for lat,lng,h in [(-1,116,100),(88,116,100),(39,-1,100),(39,180,100),(39,116,-1),(39,116,20001),(True,116,100),(39,116,False),(math.nan,116,100)]:
            with self.subTest(lat=lat,lng=lng,h=h),self.assertRaises(ValueError):
                partial.encode(lat,lng,h,21,**CTX)

    def test_no_datum_conversion_or_legacy_key_coercion(self):
        with self.assertRaises(ValueError):
            partial.encode(39,116,100,21,crs='WGS84',height_reference='AGL')
        with self.assertRaises(ValueError):
            partial.describe('00b21825260a0024002cb043',**CTX)

    def test_padding_and_noncanonical_keys_rejected(self):
        row=((39<<23)|(60<<17))>>(32-15)
        with self.assertRaises(ValueError):
            partial.describe('%s:15:%d:100:0'%(partial.PROFILE,row),**CTX)
        with self.assertRaises(ValueError):
            partial.describe(partial.PROFILE+':09:0001:0002:00',**CTX)

    def test_exact_tick_metadata(self):
        result=partial.describe(partial.encode(39.9,116.31234,100,21,**CTX),**CTX)
        self.assertEqual(result['coordinate_tick_degrees'],'1/7372800')
        for key,value in result['bounds_ticks'].items():
            self.assertAlmostEqual(value/7372800,result['bounds'][key])


class TestDefectRegression(unittest.TestCase):
    def test_same_point_route_and_blocked_endpoint(self):
        code=gc.geo_num_routeB(39.91,116.31,21)[0]
        self.assertEqual(svc.path_geo_num(code,21,code,21,[],21),[code])
        self.assertEqual(svc.path_geo_num(code,21,code,21,[(code,21)],21),[])

    def test_vertical_visibility_uses_full_height(self):
        a=gc.geo_num3d(39.91,116.31,100,21)
        b=gc.geo_num3d(39.91,116.31,1000,21)
        obstacle=gc.geo_num3d(39.91,116.31,500,21)
        high=gc.geo_num3d(39.91,116.31,2000,21)
        self.assertEqual(svc.visual_analysis(a,21,b,21,[],21),1)
        self.assertEqual(svc.visual_analysis(a,21,b,21,[(obstacle,21)],21),0)
        self.assertEqual(svc.visual_analysis(a,21,b,21,[(high,21)],21),1)

    def test_set_intersection_uses_both_inputs(self):
        status,body=call_api('/geosot/overlay_analysis_intersection',
              {'geo_level':'20','geo_num_list_a':'1-20,2-20','geo_num_list_b':'2-20,3-20'})
        self.assertEqual(status,200);self.assertEqual(body['geo_num_list'],['2-20'])
        status,_=call_api('/geosot/overlay_analysis_intersection',
              {'geo_level':'20','geo_num_list_a':'1-19','geo_num_list_b':'1-20'})
        self.assertEqual(status,400)

    def test_required_and_numeric_validation(self):
        path='/geosot3d/point3d'
        good={'lat':'39.91','lng':'116.31','height':'100','geo_level':'21'}
        self.assertEqual(call_api(path,{})[0],400)
        for key,bad in [('height','abc'),('height','NaN'),('geo_level','10.9'),('geo_level','33')]:
            self.assertEqual(call_api(path,dict(good,**{key:bad}))[0],400)

    def test_legacy_negative_domain_is_not_folded(self):
        for args in [(-39,116,100,21),(39,-116,100,21),(39,116,-1,21)]:
            with self.assertRaises(ValueError):gc.geo_num3d(*args)

    def test_nested_comparison_does_not_ignore_values(self):
        self.assertTrue(test_all.compare({'x':[{'n':2}]},{'x':[{'n':1}]}))
        self.assertTrue(test_all.compare({'x':['2']},{'x':[2]}))
        self.assertFalse(test_all.compare({'x':[1.0]},{'x':[1]}))

    def test_fixed_width_serialization_rejects_lossy_inputs(self):
        for code,dim in [(-1,2),(1<<64,2),(1<<96,3),(True,2),(1,4)]:
            with self.assertRaises(ValueError):gc.to_bytes16(code,dim)
        with self.assertRaises(ValueError):gc.from_bytes16(b'\x00'*15)
        with self.assertRaises(ValueError):gc.from_bytes16((1<<64).to_bytes(16,'big'),2)
        with self.assertRaises(ValueError):gc.from_binary128('0'*127,2)
        with self.assertRaises(ValueError):gc.from_binary128('1'+'0'*127,3)

    def test_output_directory_resolved_at_call_time(self):
        with tempfile.TemporaryDirectory() as scratch:
            old=ed.OUT_DIR
            try:
                ed.OUT_DIR=scratch
                paths=ed.write_outputs([])
                self.assertEqual(Path(paths['json']).parent,Path(scratch))
            finally:ed.OUT_DIR=old


class TestLocalHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=make_server()
        cls.worker=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.worker.start()
        cls.base='http://127.0.0.1:%d'%cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.worker.join(timeout=5)

    def post(self,path,form):
        req=urllib.request.Request(self.base+path,data=urllib.parse.urlencode(form).encode(),method='POST')
        try:
            with urllib.request.urlopen(req,timeout=5) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as exc:return exc.code,json.load(exc)

    def test_local_legacy_contract(self):
        code,body=self.post('/geosot3d/point3d',{'lat':39.91,'lng':116.31,'height':100,'geo_level':21})
        self.assertEqual(code,200);self.assertEqual(len(body['geo_num']),24)

    def test_partial_contract_and_profile_separation(self):
        code,body=self.post('/gbt40087_partial/point3d',dict(CTX,lat=39.91,lng=116.31,height=100,geo_level=21))
        self.assertEqual(code,200);self.assertEqual(body['profile'],partial.PROFILE)
        self.assertIn('engineering-key',body['key_format'])
        code,result=self.post('/gbt40087_partial/describe',dict(CTX,cell_key=body['cell_key']))
        self.assertEqual(code,200);self.assertEqual(result['bounds'],body['bounds'])

    def test_bad_request_and_unknown_path(self):
        self.assertEqual(self.post('/geosot3d/point3d',{})[0],400)
        self.assertEqual(self.post('/unknown/path',{})[0],404)
