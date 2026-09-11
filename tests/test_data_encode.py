# -*- coding: utf-8 -*-
"""
data/ -> out/ 数据编码流水线测试 (非 HTTP)
============================================
验证:
  1. data/ 下无人机轨迹与封闭区域文件均可解析且要素数量符合预期
  2. encode_all 提取的编码结构完整 (code/binary128/bytes16_hex 均存在)
  3. out/ 产物结构正确: bin 大小 = 16×N, csv 行数 = N+1, 与 json 条数一致
  4. 编码往返: 从 bin/csv 还原的码与原始码一致 (128 位二进制 / 16 字节无损)

运行: python -m unittest tests.test_data_encode -v
"""
import csv
import io
import json
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)  # for encode_data
sys.path.insert(0, os.path.join(BASE, 'src'))  # for geofile, geosot_core
import encode_data as ed
import geofile as gf
import geosot_core as gc


def _clean_out():
    out = ed.OUT_DIR
    for fn in ('codes.json', 'codes_128.bin', 'codes_16bytes.csv'):
        p = os.path.join(out, fn)
        if os.path.exists(p):
            os.remove(p)


class TestDataFiles(unittest.TestCase):
    """data/ 文件可解析且类型正确"""

    def test_inputs_exist(self):
        for fn in ('uav_track.geojson', 'uav_points.csv', 'uav_track3d.csv',
                   'closed_area.geojson'):
            self.assertTrue(os.path.exists(os.path.join(ed.DATA_DIR, fn)), fn)

    def test_uav_track_parses(self):
        feats = gf.read_geojson(os.path.join(ed.DATA_DIR, 'uav_track.geojson'))
        self.assertEqual(len(feats), 2)                    # 2 条轨迹
        self.assertTrue(all(f['type'] == 'LineString' for f in feats))
        self.assertEqual(len(feats[0]['coords']), 10)      # 每条 10 个点

    def test_uav_points_parses(self):
        feats = gf.read_csv(os.path.join(ed.DATA_DIR, 'uav_points.csv'))
        self.assertEqual(len(feats), 10)                   # 10 个航点
        self.assertTrue(all(f['type'] == 'Point' for f in feats))
        self.assertIn('drone_id', feats[0]['props'])       # 属性列保留

    def test_uav_track3d_parses(self):
        with io.open(os.path.join(ed.DATA_DIR, 'uav_track3d.csv'),
                     encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 10)                    # 10 个 3D 航点
        self.assertIn('alt_m', rows[0])                    # 含高度列
        self.assertIn('drone_id', rows[0])

    def test_closed_area_parses(self):
        feats = gf.read_geojson(os.path.join(ed.DATA_DIR, 'closed_area.geojson'))
        self.assertEqual(len(feats), 2)                    # 2 个禁飞区
        self.assertTrue(all(f['type'] == 'Polygon' for f in feats))
        self.assertEqual(feats[0]['coords'][0], feats[0]['coords'][-1])  # 闭合


class TestEncodeAll(unittest.TestCase):
    """编码提取结构完整"""

    @classmethod
    def setUpClass(cls):
        cls.results = ed.encode_all(21, 'B')

    def test_count(self):
        self.assertGreater(len(self.results), 100)         # 线/面网格化后应远多于航点数

    def test_sources_covered(self):
        srcs = {r['source'] for r in self.results}
        self.assertIn('uav_track.geojson', srcs)
        self.assertIn('uav_points.csv', srcs)
        self.assertIn('uav_track3d.csv', srcs)
        self.assertIn('closed_area.geojson', srcs)

    def test_fields(self):
        for r in self.results[:50]:
            self.assertTrue(r['code'].endswith('-21'))
            self.assertEqual(len(r['binary128']), 128)
            self.assertEqual(len(r['bytes16_hex']), 32)   # 16 字节 -> 32 个 hex
            self.assertIn(r['dim'], (2, 3))

    def test_types(self):
        types = {r['type'] for r in self.results}
        self.assertIn('Point', types)
        self.assertIn('LineString', types)
        self.assertIn('Polygon', types)
        self.assertIn('Point3D', types)                   # 3D 航线

    def test_3d_records(self):
        threed = [r for r in self.results if r['dim'] == 3]
        self.assertEqual(len(threed), 10)                 # 10 个 3D 航点
        for r in threed:
            self.assertEqual(r['type'], 'Point3D')
            self.assertEqual(r['source'], 'uav_track3d.csv')
            code = int(r['code'].split('-')[0])
            self.assertLessEqual(code.bit_length(), 96)   # 3D 码 96 位
            # 3D: 96 位二进制右对齐 -> 前 32 位为 0
            self.assertEqual(r['binary128'][:32], '0' * 32)


class TestOutputs(unittest.TestCase):
    """out/ 产物结构正确且可往返还原"""

    @classmethod
    def setUpClass(cls):
        _clean_out()
        cls.results = ed.encode_all(21, 'B')
        cls.paths = ed.write_outputs(cls.results, 21, 'B')
        cls.n = len(cls.results)

    def test_files_exist(self):
        for k in ('json', 'bin', 'csv'):
            self.assertTrue(os.path.exists(self.paths[k]), k)

    def test_json_count(self):
        with io.open(self.paths['json'], encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data['count'], self.n)
        self.assertEqual(data['level'], 21)
        self.assertEqual(len(data['codes']), self.n)

    def test_bin_size(self):
        self.assertEqual(os.path.getsize(self.paths['bin']), 16 * self.n)

    def test_csv_rows(self):
        with io.open(self.paths['csv'], encoding='utf-8') as f:
            rows = list(csv.reader(f))
        self.assertEqual(len(rows), self.n + 1)            # 含表头
        self.assertEqual(rows[0], ['bytes16_hex'])         # 仅一列
        for row in rows[1:]:
            self.assertEqual(len(row), 1)                  # 每行只有 hex
            self.assertEqual(len(row[0]), 32)              # 16 字节 -> 32 个 hex

    def test_bin_roundtrip(self):
        with open(self.paths['bin'], 'rb') as f:
            blob = f.read()
        for i, r in enumerate(self.results):
            buf = blob[i * 16:(i + 1) * 16]
            code = int(r['code'].split('-')[0])
            restored_code, _level, _dim = gc.from_bytes16(buf)
            self.assertEqual(restored_code, code,
                             'bin 第 %d 条 (dim=%d)' % (i, r['dim']))

    def test_csv_roundtrip(self):
        with io.open(self.paths['csv'], encoding='utf-8') as f:
            rows = list(csv.reader(f))[1:]
        for i, row in enumerate(rows):
            r = self.results[i]
            code = int(r['code'].split('-')[0])
            expected_level = r['code_level']
            expected_dim = r['dim']
            # 从 hex 解码 16 字节
            buf = bytes.fromhex(row[0])
            restored_code, restored_level, restored_dim = gc.from_bytes16(buf)
            self.assertEqual(restored_code, code, 'csv 第 %d 条 code' % i)
            self.assertEqual(restored_level, expected_level, 'csv 第 %d 条 level' % i)
            self.assertEqual(restored_dim, expected_dim, 'csv 第 %d 条 dim' % i)
            self.assertEqual(gc.from_binary128(r['binary128'], dim=r['dim']), code)


if __name__ == '__main__':
    unittest.main()
