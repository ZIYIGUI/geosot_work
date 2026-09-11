# -*- coding: utf-8 -*-
"""
非 HTTP 形式的核心单元测试
============================
直接 import geosot_core / geosot_service 调用函数断言, 不经过 HTTP 服务。
覆盖: 位运算往返、路线A/B 编码、子/父/邻域、3D、进制转换、
      128 位/16 字节扩展、距离方位, 以及 geosot_examples.json 中的黄金样例直测。

运行: python -m unittest tests.test_unit -v
"""
import json
import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))
import geosot_core as gc
import geosot_service as svc


EX_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'geosot_examples.json')


def _golden(path, key):
    with open(EX_PATH, encoding='utf-8') as f:
        d = json.load(f)
    item = d.get(path, {})
    return item.get('example', {}).get(key)


class TestBitOps(unittest.TestCase):
    def test_morton_roundtrip(self):
        for n in (5, 10, 15, 20, 23, 31):
            for _ in range(20):
                r = random.randrange(2 ** n)
                c = random.randrange(2 ** n)
                self.assertEqual(gc.demorton(gc.morton(r, c, n), n), (r, c))

    def test_interleave3_roundtrip(self):
        for _ in range(20):
            a = random.getrandbits(32)
            b = random.getrandbits(32)
            c = random.getrandbits(32)
            v = gc.interleave3(a, b, c, order=(2, 0, 1), nbits=32)
            self.assertEqual(gc.deinterleave3(v, order=(2, 0, 1), nbits=32), (a, b, c))

    def test_pack_dms_roundtrip(self):
        for _ in range(50):
            d = random.randrange(180)
            m = random.randrange(60)
            s = random.randrange(60)
            sub = random.randrange(2048)
            self.assertEqual(gc.unpack_dms(gc.pack_dms(d, m, s, sub)), (d, m, s, sub))


class TestRouteA(unittest.TestCase):
    def test_roundtrip(self):
        lat, lng = 39.91027777777778, 116.31527777777778
        code = gc.geo_num_routeA(lat, lng)
        lp, np_ = gc.decode_routeA(code)
        self.assertEqual(gc.unpack_dms(lp), gc.unpack_dms(gc._coord_to_pack(lat)))
        self.assertEqual(gc.unpack_dms(np_), gc.unpack_dms(gc._coord_to_pack(lng)))

    def test_location_point(self):
        code = gc.geo_num_routeA(39.91027777777778, 116.31527777777778)
        p = gc.location_point(code, 15)
        self.assertAlmostEqual(p[1], 39.0, delta=1.0)   # 左下角纬度在 39°~40°
        self.assertAlmostEqual(p[0], 116.0, delta=1.0)

    def test_center_point(self):
        # 黄金: /geosot/center_point 请求 (geo_num=412869894958481408, geo_level=23)
        p = gc.center_point(412869894958481408, 23)
        self.assertAlmostEqual(p[0], 105.38107638888889, delta=1e-9)
        self.assertAlmostEqual(p[1], 31.528506944444445, delta=1e-9)


class TestRouteB(unittest.TestCase):
    def test_known_point(self):
        # 黄金: /geosot/point 请求 (lat=31, lng=131, geo_level=5)
        code = gc.geo_num_routeB(31, 131, 5)[0]
        self.assertEqual(code, 1188950301625810944)

    def test_row_col_roundtrip(self):
        lat, lng, level = 39.91, 116.31, 15
        r, c = gc.row_col(lat, lng, level)
        code = gc.row_col2geo_num(r, c, level)
        self.assertEqual(gc.row_col_of_code_routeB(code, level), (r, c))

    def test_routeB_zero_lowbits(self):
        code = gc.geo_num_routeB(39.91, 116.31, 15)[0]
        self.assertEqual(code & ((1 << (64 - 2 * 15)) - 1), 0)


class TestHierarchy(unittest.TestCase):
    def test_child_count(self):
        code = gc.geo_num_routeA(31.5, 105.3)
        kids = gc.child_geo_num(code, 10, 13)
        self.assertEqual(len(kids), 4 ** 3)

    def test_child_parent(self):
        code = gc.geo_num_routeB(39.91, 116.31, 10)[0]
        kids = gc.child_geo_num(code, 10, 12)
        for k in kids:
            self.assertEqual(gc.parent_geo_num(k, 12, 10), code)

    def test_adjoin4_count(self):
        code = gc.geo_num_routeA(31.5, 105.3)
        self.assertEqual(len(gc.adjoin4_geo_num(code, 10)), 4)

    def test_adjoin8_center(self):
        code = gc.geo_num_routeA(31.5, 105.3)
        cells = gc.adjoin8_geo_num(code, 10)
        self.assertEqual(len(cells), 8)


class Test3D(unittest.TestCase):
    INPUT = 0x92fb3e924924924924804120   # level 8 (黄金样例输入)

    def test_3d_roundtrip(self):
        code = gc.geo_num3d(39.9, 116.3, 1000, 15)
        h, la, ln = gc.decode_geo_num3d(code, 15)
        self.assertEqual(gc.interleave3(la, ln, h, order=(2, 0, 1), nbits=32), code)

    def test_adjoin6_golden(self):
        # 黄金: /geosot3d/adjoin6_geo_num 输出 6 项
        cells = gc.adjoin6_geo_num3d(self.INPUT, 8)
        self.assertEqual(len(cells), 6)
        gold = _golden('/geosot3d/adjoin6_geo_num', 'geo_num_list') or []
        if gold:
            self.assertEqual([format(x, '024x') for x in cells], gold)

    def test_adjoin26_golden(self):
        cells = gc.adjoin26_geo_num3d(self.INPUT, 8)
        self.assertEqual(len(cells), 26)
        gold = _golden('/geosot3d/adjoin26_geo_num', 'geo_num_list') or []
        if gold:
            self.assertEqual([format(x, '024x') for x in cells], gold)

    def test_child3d_golden(self):
        cells = gc.child_geo_num3d(self.INPUT, 8, 9)
        self.assertEqual(len(cells), 8)
        gold = _golden('/geosot3d/child_geo_num', 'geo_num_list') or []
        if gold:
            self.assertEqual([format(x, '024x') for x in cells], gold)

    def test_parent3d_golden(self):
        p = gc.parent_geo_num3d(self.INPUT, 8, 7)
        gold = _golden('/geosot3d/parent_geo_num', 'geo_num') or ''
        if gold:
            self.assertEqual(format(p, '024x'), gold)


class TestEncoding(unittest.TestCase):
    def test_binary_roundtrip(self):
        code = gc.geo_num_routeA(39.91, 116.31)
        b = gc.decimal2binary(code, 15)
        self.assertEqual(len(b), 30)
        self.assertEqual(gc.binary2decimal(b, 15), gc.parent_geo_num(code, 23, 15))

    def test_quaternary_roundtrip(self):
        code = gc.geo_num_routeA(39.91, 116.31)
        q = gc.decimal2quaternary(code, 15)
        self.assertTrue(q.startswith('G'))
        self.assertEqual(gc.quaternary2decimal(q, 15),
                         gc.parent_geo_num(code, 23, 15))

    def test_beidou_golden(self):
        # 黄金: /geosot/beidou_grid_code2geo_num -> 412869894958481400
        code = gc.beidou2geo_num('N48H67171CA372')
        self.assertEqual(code, 412869894958481400)


class TestBinary128(unittest.TestCase):
    def test_roundtrip_2d(self):
        code = gc.geo_num_routeB(39.91, 116.31, 15)[0]
        b = gc.to_binary128(code, 15)
        self.assertEqual(len(b), 128)
        self.assertEqual(gc.from_binary128(b), code)

    def test_roundtrip_3d(self):
        code = gc.geo_num3d(39.9, 116.3, 1000, 15)
        b = gc.to_binary128(code, 15, dim=3)
        self.assertEqual(len(b), 128)
        self.assertEqual(gc.from_binary128(b, dim=3), code)

    def test_bytes16_2d(self):
        code = gc.geo_num_routeB(39.91, 116.31, 15)[0]
        buf = gc.to_bytes16(code, level=15)
        self.assertEqual(len(buf), 16)
        restored_code, level, dim = gc.from_bytes16(buf)
        self.assertEqual(restored_code, code)
        self.assertEqual(level, 15)
        self.assertEqual(dim, 2)

    def test_bytes16_3d(self):
        code = gc.geo_num3d(39.9, 116.3, 1000, 15)
        buf = gc.to_bytes16(code, dim=3, level=15)
        self.assertEqual(len(buf), 16)
        restored_code, level, dim = gc.from_bytes16(buf)
        self.assertEqual(restored_code, code)
        self.assertEqual(level, 15)
        self.assertEqual(dim, 3)


class TestMeasure(unittest.TestCase):
    def test_haversine_1deg(self):
        d = gc.hav(0, 0, 0, 1)
        self.assertAlmostEqual(d, 6378137.0 * math.pi / 180, delta=1e-6)

    def test_area_positive(self):
        code = gc.geo_num_routeA(31.5, 105.3)
        self.assertGreater(gc.area_geo_num(code, 10), 0)

    def test_azimuth_east(self):
        # 自赤道 (0,0) 向东 1° (15 级格), 方位应约为 π/2
        az = gc.azimuth_geo_num(gc.geo_num_routeA(0, 0), 15,
                                gc.geo_num_routeA(0, 1), 15)
        self.assertAlmostEqual(az, math.pi / 2, delta=1e-3)


class TestService(unittest.TestCase):
    def test_line_cells(self):
        cells = svc.line_cells([39.9, 40.0], [116.3, 116.4], 15)
        self.assertGreater(len(cells), 1)

    def test_polygon_cells(self):
        lats = [39.9, 39.95, 39.95, 39.9]
        lngs = [116.3, 116.3, 116.35, 116.35]
        cells = svc.polygon_cells(lats, lngs, 15)
        self.assertGreater(len(cells), 0)

    def test_rect_cells_count(self):
        # 黄金: /geosot/rect 请求 (35,131)-(23,135) level 10 -> 225 项 (15x15)
        cells = svc.rect_cells(35, 131, 23, 135, 10)
        self.assertEqual(len(cells), 225)

    def test_outer_rect(self):
        codes = [(gc.geo_num_routeB(39.9, 116.3, 15)[0], 15),
                 (gc.geo_num_routeB(39.91, 116.31, 15)[0], 15)]
        out, lvls = svc.outer_rectangle_geo_num_list(codes)
        self.assertEqual(len(out), 2)
        self.assertEqual(lvls, [15, 15])


if __name__ == '__main__':
    unittest.main()
