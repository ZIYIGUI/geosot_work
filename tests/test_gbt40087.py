# -*- coding: utf-8 -*-
"""
GB/T 40087-2021《地球空间网格编码规则》标准符合性测试
=====================================================
覆盖标准中可直接核验的编码示例与公式:
  1. 附录 D 表 D.1: 北京世纪坛中心 (39°54'37.0"N, 116°18'54.8"E)
     经纬度度分秒 -> 二进制转换、度级网格编码、莫顿交叉、四进制代码
  2. 附录 A 表 A.1: 地球参考椭球面网格规格 (各级单元跨度、赤道尺度)
  3. 附录 B: 大地高方向不等距剖分公式 (B.3)-(B.7) 特征值

运行: python -m unittest tests.test_gbt40087 -v
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))
import geosot_core as gc

R0 = gc.R0
THETA0 = gc.THETA0


class TestAppendixD_Binary(unittest.TestCase):
    """附录 D a): 经纬度度分秒小数 -> 二进制字符串"""

    def test_lat_binary(self):
        # 39°54'37.0"N -> 000100111°110110'100101.000000000000″
        self.assertEqual(gc.gb_dms_binary(39, 54, 37, 0.0),
                         '000100111 110110 100101.000000000000')

    def test_lng_binary(self):
        # 116°18'54.8"E -> 001110100°010010'110110.11001100110″
        # (秒小数按 12 位输出, 标准原文末位 0 被省略)
        self.assertEqual(gc.gb_dms_binary(116, 18, 54, 0.8),
                         '001110100 010010 110110.110011001100')


class TestAppendixD_DegGrid(unittest.TestCase):
    """附录 D 表 D.1: 度级网格编码 (度数二进制截断)"""

    def test_4deg_lat(self):
        # 4°网格纬度编码 = 39 的 9 位二进制前 8 位 = 00010011
        self.assertEqual(format(39, '09b')[:8], '00010011')

    def test_4deg_lng(self):
        # 4°网格经度编码 = 116 的 9 位二进制前 8 位 = 00111010
        self.assertEqual(format(116, '09b')[:8], '00111010')

    def test_1deg_lat(self):
        # 1°网格纬度编码 = 39 的 9 位二进制 = 000100111
        self.assertEqual(format(39, '09b'), '000100111')

    def test_1deg_lng(self):
        # 1°网格经度编码 = 116 的 9 位二进制 = 001110100
        self.assertEqual(format(116, '09b'), '001110100')


class TestAppendixD_Morton(unittest.TestCase):
    """附录 D b)/c): 莫顿交叉 + 四进制代码"""

    LAT = 39 + 54 / 60 + 37.0 / 3600
    LNG = 116 + 18 / 60 + 54.8 / 3600

    def test_4deg_morton(self):
        # 4°级: morton(纬带9, 经带29, 7对) = 00000111010011
        self.assertEqual(gc.gb_deg_grid_morton(self.LAT, self.LNG, 4),
                         '00000111010011')

    def test_4deg_quaternary(self):
        # 4°级四进制代码 = G0013103 (附录 D c) 句)
        self.assertEqual(gc.gb_quaternary('00000111010011'), 'G0013103')

    def test_2deg_morton(self):
        # 2°级: morton(纬带19, 经带58, 8对) = 0000011101001110
        self.assertEqual(gc.gb_deg_grid_morton(self.LAT, self.LNG, 2),
                         '0000011101001110')

    def test_2deg_quaternary(self):
        # 2°级四进制代码 = G00131032 (附录 D c) 句)
        self.assertEqual(gc.gb_quaternary('0000011101001110'), 'G00131032')

    def test_morton_impl(self):
        # 莫顿交叉实现与标准一致: 纬度前置、经度后置, 行位在奇数位
        self.assertEqual(gc.morton(9, 29, 7), 0b00000111010011)
        self.assertEqual(gc.morton(19, 58, 8), 0b0000011101001110)


class TestAppendixA_GridSpec(unittest.TestCase):
    """附录 A 表 A.1: 地球参考椭球面网格规格"""

    def test_cell_deg(self):
        # 单元跨度: 度级 2^(9-L) / 分级 2^(15-L)/60 / 秒级 2^(21-L)/3600 / 秒下
        self.assertAlmostEqual(gc.cell_deg(0), 512.0)
        self.assertAlmostEqual(gc.cell_deg(9), 1.0)
        self.assertAlmostEqual(gc.cell_deg(10), 32.0 / 60.0)     # 32'网格
        self.assertAlmostEqual(gc.cell_deg(15), 1.0 / 60.0)      # 1'网格
        self.assertAlmostEqual(gc.cell_deg(16), 32.0 / 3600.0)   # 32"网格
        self.assertAlmostEqual(gc.cell_deg(21), 1.0 / 3600.0)    # 1"网格
        self.assertAlmostEqual(gc.cell_deg(22), 0.5 / 3600.0)    # 1/2"网格
        self.assertAlmostEqual(gc.cell_deg(32), 1.0 / 2048.0 / 3600.0)

    def test_equator_scale(self):
        # 赤道附近大致尺度 ≈ R0*θ*单元跨度
        cases = [(9, 111.3e3), (15, 1.8e3), (16, 989.5), (21, 30.9),
                 (25, 1.9), (32, 0.015)]
        for level, std_m in cases:
            scale = R0 * THETA0 * gc.cell_deg(level)
            self.assertTrue(abs(scale - std_m) / std_m < 0.05,
                            'level %d 尺度 %.4f vs 标准 %.4f' % (level, scale, std_m))

    def test_cells_per_deg(self):
        self.assertEqual(gc.cells_per_deg(9), 1)
        self.assertEqual(gc.cells_per_deg(10), 2)
        self.assertEqual(gc.cells_per_deg(15), 64)          # 扩展分体系
        self.assertAlmostEqual(gc.cells_per_deg(16), 3600.0 / 32)
        self.assertEqual(gc.cells_per_deg(17), 225)         # 16"网格


class TestAppendixB_Height(unittest.TestCase):
    """附录 B: 大地高方向不等距剖分公式 (B.3)-(B.7)"""

    def test_height_cell_level9(self):
        # 1°网格单层高度 = R0*((1+θ0)-1) = R0*θ0 ≈ 111.319 km
        self.assertAlmostEqual(gc.height_cell(9), R0 * THETA0, delta=1e-6)

    def test_H_255(self):
        # 公式(B.4): H_n = (1+θ0)^n·r0 - r0, n=255
        H255 = (1 + THETA0) ** 255 * R0 - R0
        self.assertAlmostEqual(H255, 519501834.1582395, delta=0.01)   # 标准值 (m)

    def test_r_255(self):
        r255 = (1 + THETA0) ** 255 * R0
        self.assertAlmostEqual(r255, 525879971.1582395, delta=0.01)   # 标准 r255 (m)

    def test_H_minus_256(self):
        # 地下第 256 层下底面: H_{-256} = -6302.106722602182 km
        Hm = (1 + THETA0) ** (-256) * R0 - R0
        self.assertAlmostEqual(Hm, -6302106.722602182, delta=0.01)

    def test_height_range(self):
        # 地球空域高度范围: -6302.107 km ~ 528680.171 km
        H256 = (1 + THETA0) ** 256 * R0 - R0
        self.assertAlmostEqual(H256, 528680171.1252437, delta=0.01)

    def test_n_255(self):
        # 公式(B.7): n = (θ0/θ)·log_{1+θ0}(1+H/r0), 对 H_{255} 应回到 255
        n = math.log(1 + 519501834.1582395 / R0) / math.log(1 + THETA0)
        self.assertTrue(abs(n - 255.0) < 1e-6)


if __name__ == '__main__':
    unittest.main()
