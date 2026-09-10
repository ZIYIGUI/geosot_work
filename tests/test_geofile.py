# -*- coding: utf-8 -*-
"""
geofile.py 地理信息文件读取与编码映射测试 (非 HTTP)
=====================================================
为每种支持格式构造临时样本文件, 验证解析与 GeoSOT 编码映射结果。

运行: python -m unittest tests.test_geofile -v
"""
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import geofile as gf


def _tmp(name, content=None, binary=False):
    p = os.path.join(tempfile.gettempdir(), name)
    if binary:
        with open(p, 'wb') as f:
            f.write(content)
    else:
        with io.open(p, 'w', encoding='utf-8') as f:
            f.write(content or '')
    return p


class TestDetect(unittest.TestCase):
    def test_detect(self):
        for fn, fmt in [('a.geojson', 'geojson'), ('a.json', 'geojson'),
                        ('a.shp', 'shp'), ('a.csv', 'csv'), ('a.txt', 'csv'),
                        ('a.wkt', 'wkt'), ('a.kml', 'kml'), ('a.gpx', 'gpx')]:
            self.assertEqual(gf.detect_format(_tmp(fn)), fmt)


class TestWKT(unittest.TestCase):
    def test_point_line_polygon(self):
        p = _tmp('t1.wkt',
                 'POINT(116.315 39.910)\n'
                 'LINESTRING(116.3 39.9, 116.4 40.0)\n'
                 'POLYGON((116.3 39.9, 116.4 39.9, 116.4 40.0, 116.3 39.9))')
        feats = gf.read_wkt(p)
        types = [f['type'] for f in feats]
        self.assertIn('Point', types)
        self.assertIn('LineString', types)
        self.assertIn('MultiPolygon', types)
        self.assertEqual(feats[0]['coords'][0], (116.315, 39.910))

    def test_multi(self):
        p = _tmp('t2.wkt',
                 'MULTIPOINT((1 2), (3 4))\n'
                 'MULTILINESTRING((0 0, 1 1), (2 2, 3 3))\n'
                 'MULTIPOLYGON(((0 0, 1 0, 1 1, 0 0)), ((2 2, 3 2, 3 3, 2 2)))')
        feats = gf.read_wkt(p)
        self.assertEqual(len(feats), 3)
        self.assertEqual(feats[0]['type'], 'MultiPoint')
        self.assertEqual(len(feats[0]['coords']), 2)
        self.assertEqual(feats[1]['type'], 'MultiLineString')
        self.assertEqual(len(feats[1]['coords']), 2)
        self.assertEqual(feats[2]['type'], 'MultiPolygon')
        self.assertEqual(len(feats[2]['coords']), 2)

    def test_encode(self):
        p = _tmp('t3.wkt', 'POINT(116.3152778 39.9102778)')
        r = gf.encode_file(p, 15)
        self.assertEqual(r['format'], 'wkt')
        self.assertEqual(r['count'], 1)
        fe = r['features'][0]
        self.assertEqual(fe['type'], 'Point')
        self.assertTrue(fe['code'].endswith('-15'))
        self.assertEqual(len(fe['binary128']), 128)
        self.assertEqual(len(fe['bytes16_hex']), 32)


class TestGeoJSON(unittest.TestCase):
    def test_fc(self):
        gj = {'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'properties': {'name': 'A'},
             'geometry': {'type': 'Point', 'coordinates': [116.315, 39.91]}},
            {'type': 'Feature', 'properties': {},
             'geometry': {'type': 'LineString',
                          'coordinates': [[116.3, 39.9], [116.4, 40.0]]}}]}
        p = _tmp('t.geojson', json.dumps(gj))
        feats = gf.read_geojson(p)
        self.assertEqual(len(feats), 2)
        self.assertEqual(feats[0]['type'], 'Point')
        self.assertEqual(feats[0]['props']['name'], 'A')

    def test_encode_routeA(self):
        gj = {'type': 'Feature',
              'geometry': {'type': 'Point', 'coordinates': [116.315, 39.91]}}
        p = _tmp('t2.geojson', json.dumps(gj))
        r = gf.encode_file(p, 15, 'A')
        self.assertEqual(r['route'], 'A')
        self.assertTrue(r['features'][0]['code'].endswith('-23'))


class TestCSV(unittest.TestCase):
    def test_lonlat(self):
        p = _tmp('t.csv', 'lon,lat,name\n116.315,39.91,A\n116.5,39.5,B\n')
        feats = gf.read_csv(p)
        self.assertEqual(len(feats), 2)
        self.assertEqual(feats[0]['coords'][0], (116.315, 39.91))
        self.assertEqual(feats[0]['props']['name'], 'A')

    def test_chinese_cols(self):
        p = _tmp('t2.csv', '经度,纬度\n116.315,39.91\n')
        feats = gf.read_csv(p)
        self.assertEqual(len(feats), 1)

    def test_wkt_col(self):
        p = _tmp('t3.csv', 'wkt,id\n"POINT(116.315 39.91)",1\n')
        feats = gf.read_csv(p)
        self.assertEqual(len(feats), 1)
        self.assertEqual(feats[0]['coords'][0], (116.315, 39.91))


class TestKML(unittest.TestCase):
    def test_placemark(self):
        kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Placemark><name>P1</name>
    <Point><coordinates>116.315,39.91,0</coordinates></Point>
  </Placemark>
  <Placemark><name>L1</name>
    <LineString><coordinates>116.3,39.9,0 116.4,40.0,0</coordinates></LineString>
  </Placemark>
</kml>"""
        p = _tmp('t.kml', kml)
        feats = gf.read_kml(p)
        self.assertEqual(len(feats), 2)
        self.assertEqual(feats[0]['type'], 'Point')
        self.assertEqual(feats[0]['props']['name'], 'P1')
        self.assertEqual(feats[1]['type'], 'LineString')


class TestGPX(unittest.TestCase):
    def test_trk_wpt(self):
        gpx = """<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <wpt lat="39.91" lon="116.315"><name>W</name></wpt>
  <trk><name>T</name><trkseg>
    <trkpt lat="39.9" lon="116.3"/><trkpt lat="40.0" lon="116.4"/>
  </trkseg></trk>
</gpx>"""
        p = _tmp('t.gpx', gpx)
        feats = gf.read_gpx(p)
        self.assertEqual(len(feats), 2)
        self.assertEqual(feats[0]['type'], 'Point')
        self.assertEqual(feats[1]['type'], 'LineString')
        self.assertEqual(len(feats[1]['coords']), 2)


class TestSHP(unittest.TestCase):
    def _shp_point(self):
        # 构造含 2 个 Point 记录的 shp (shape type 1), 完整 100 字节文件头
        body = struct.pack('<i', 1) + struct.pack('<dd', 116.315, 39.91)
        rec1 = struct.pack('>ii', 1, len(body) // 2) + body
        body2 = struct.pack('<i', 1) + struct.pack('<dd', 116.5, 39.5)
        rec2 = struct.pack('>ii', 2, len(body2) // 2) + body2
        header = struct.pack('>i', 9994) + b'\x00' * 20          # 0-23
        header += struct.pack('>i', (100 + len(rec1) + len(rec2)) // 2)  # 24-27 文件长度(字)
        header += struct.pack('>i', 1000)                        # 28-31 版本
        header += struct.pack('<i', 1)                           # 32-35 形状类型
        header += struct.pack('<dddd', 116.3, 39.4, 116.6, 40.0)  # 36-67 bbox
        header += struct.pack('<dddd', 0, 0, 0, 0)               # 68-99 z/m 范围
        return header + rec1 + rec2

    def test_points(self):
        p = _tmp('t.shp', self._shp_point(), binary=True)
        feats = gf.read_shp(p)
        self.assertEqual(len(feats), 2)
        self.assertEqual(feats[0]['type'], 'Point')
        self.assertEqual(feats[0]['coords'][0], (116.315, 39.91))
        self.assertEqual(feats[0]['props']['shp_record'], 1)

    def test_encode(self):
        p = _tmp('t2.shp', self._shp_point(), binary=True)
        r = gf.encode_file(p, 15)
        self.assertEqual(r['format'], 'shp')
        self.assertEqual(r['count'], 2)


class TestCLI(unittest.TestCase):
    def test_cli_summary(self):
        p = _tmp('t.cli.geojson', json.dumps(
            {'type': 'Point', 'coordinates': [116.315, 39.91]}))
        out = os.path.join(tempfile.gettempdir(), 't.cli.out.json')
        res = gf.main([p, '--level', '15', '--out', out])
        self.assertEqual(res['count'], 1)
        self.assertTrue(os.path.exists(out))
        with io.open(out, encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data['count'], 1)


if __name__ == '__main__':
    unittest.main()
