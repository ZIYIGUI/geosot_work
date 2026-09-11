# -*- coding: utf-8 -*-
"""
空域网格计算测试
================
测试 airspace_grids 功能: 给定上下两个封闭多边形和高度范围,
计算空域包含的 3D 网格编码, 并可保存为 128 位二进制文件。

用法:
    python tests/test_airspace_grids.py
    # 或作为 unittest 运行:
    python -m unittest tests.test_airspace_grids -v
"""
import os
import sys
import time
import unittest

# 项目根目录自动解析
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

import geosot_core as gc

OUT_DIR = os.path.join(PROJECT_ROOT, 'out')


class TestPointInPolygon(unittest.TestCase):
    """测试点在多边形内判断"""

    def test_point_inside_square(self):
        """测试点在正方形内"""
        square = [(0, 0), (10, 0), (10, 10), (0, 10)]
        self.assertTrue(gc._point_in_polygon(5, 5, square))

    def test_point_outside_square(self):
        """测试点在正方形外"""
        square = [(0, 0), (10, 0), (10, 10), (0, 10)]
        self.assertFalse(gc._point_in_polygon(15, 5, square))

    def test_point_inside_triangle(self):
        """测试点在三角形内"""
        triangle = [(0, 0), (10, 0), (5, 10)]
        self.assertTrue(gc._point_in_polygon(5, 3, triangle))

    def test_point_outside_triangle(self):
        """测试点在三角形外"""
        triangle = [(0, 0), (10, 0), (5, 10)]
        # 点 (1, 11) 在三角形上方，明确在外部
        self.assertFalse(gc._point_in_polygon(1, 11, triangle))


class TestPolygonCells2D(unittest.TestCase):
    """测试多边形 2D 网格覆盖计算"""

    def test_square_coverage(self):
        """测试正方形覆盖的网格数量"""
        # 定义一个约 0.02 度 x 0.02 度的正方形 (在 15 级约 2km x 2km)
        square = [(116.30, 39.90), (116.32, 39.90), (116.32, 39.92), (116.30, 39.92)]
        cells = gc._polygon_cells_2d(square, level=15)
        self.assertGreater(len(cells), 0)

    def test_triangle_coverage(self):
        """测试三角形覆盖的网格"""
        triangle = [(116.30, 39.90), (116.34, 39.90), (116.32, 39.94)]
        cells = gc._polygon_cells_2d(triangle, level=15)
        self.assertGreater(len(cells), 0)


class TestAirspaceGrids(unittest.TestCase):
    """测试空域网格计算"""

    def test_basic_airspace(self):
        """测试基本空域计算"""
        # 定义一个矩形空域
        # 下边界: 大矩形
        lower = [(116.30, 39.90), (116.34, 39.90), (116.34, 39.94), (116.30, 39.94)]
        # 上边界: 小矩形 (完全在下边界内)
        upper = [(116.31, 39.91), (116.33, 39.91), (116.33, 39.93), (116.31, 39.93)]

        codes = gc.airspace_grids(lower, upper, h_min=100, h_max=500, level=15)

        self.assertGreater(len(codes), 0, "应该返回至少一个网格编码")

        # 验证所有编码都是正整数
        for code in codes:
            self.assertIsInstance(code, int)
            self.assertGreaterEqual(code, 0)

    def test_no_overlap(self):
        """测试两个多边形无重叠的情况"""
        # 两个不相交的多边形
        lower = [(116.30, 39.90), (116.31, 39.90), (116.31, 39.91), (116.30, 39.91)]
        upper = [(116.40, 39.90), (116.41, 39.90), (116.41, 39.91), (116.40, 39.91)]

        codes = gc.airspace_grids(lower, upper, h_min=100, h_max=500, level=15)

        self.assertEqual(len(codes), 0, "无重叠时应返回空列表")

    def test_height_range(self):
        """测试高度范围影响"""
        lower = [(116.30, 39.90), (116.32, 39.90), (116.32, 39.92), (116.30, 39.92)]
        upper = [(116.30, 39.90), (116.32, 39.90), (116.32, 39.92), (116.30, 39.92)]

        # 较窄的高度范围 (仅 50m)
        codes_narrow = gc.airspace_grids(lower, upper, h_min=100, h_max=150, level=15)
        # 较宽的高度范围 (5000m，覆盖多个高度层)
        codes_wide = gc.airspace_grids(lower, upper, h_min=100, h_max=5000, level=15)

        self.assertGreater(len(codes_wide), len(codes_narrow),
                          "高度范围越大, 网格数量应越多")

    def test_different_levels(self):
        """测试不同层级的影响"""
        lower = [(116.30, 39.90), (116.32, 39.90), (116.32, 39.92), (116.30, 39.92)]
        upper = [(116.30, 39.90), (116.32, 39.90), (116.32, 39.92), (116.30, 39.92)]

        codes_10 = gc.airspace_grids(lower, upper, h_min=100, h_max=500, level=10)
        codes_15 = gc.airspace_grids(lower, upper, h_min=100, h_max=500, level=15)

        # 层级越高, 网格越小, 数量应该越多
        self.assertGreater(len(codes_15), len(codes_10),
                          "层级越高, 网格数量应越多")

    def test_save_to_binary(self):
        """测试保存为 128 位二进制文件"""
        lower = [(116.30, 39.90), (116.32, 39.90), (116.32, 39.92), (116.30, 39.92)]
        upper = [(116.31, 39.91), (116.315, 39.91), (116.315, 39.915), (116.31, 39.915)]

        codes = gc.airspace_grids(lower, upper, h_min=100, h_max=300, level=15)

        if codes:
            # 保存到二进制文件
            bin_path = os.path.join(OUT_DIR, 'airspace_grids.bin')
            os.makedirs(OUT_DIR, exist_ok=True)

            level = 15  # 测试使用的层级
            with open(bin_path, 'wb') as f:
                for code in codes:
                    # 3D 码使用 dim=3, 并保存层级信息
                    buf = gc.to_bytes16(code, dim=3, level=level)
                    f.write(buf)

            # 验证文件大小
            file_size = os.path.getsize(bin_path)
            self.assertEqual(file_size, len(codes) * 16,
                           f"文件大小应为 {len(codes) * 16} 字节")

            # 验证可以读回
            with open(bin_path, 'rb') as f:
                data = f.read()

            restored_codes = []
            for i in range(0, len(data), 16):
                buf = data[i:i+16]
                code, restored_level, dim = gc.from_bytes16(buf)
                restored_codes.append(code)
                # 验证层级和维度
                self.assertEqual(restored_level, level)
                self.assertEqual(dim, 3)

            self.assertEqual(set(restored_codes), set(codes),
                           "读回的编码应与原编码一致")


class TestAirspaceGridsPerformance(unittest.TestCase):
    """测试空域网格计算性能"""

    def test_large_airspace(self):
        """测试德清县区域空域 (约 100 万网格) 的计算时间"""
        # 德清县区域: 约 936 平方公里
        lower = [(119.75, 30.433), (120.35, 30.433), (120.35, 30.700), (119.75, 30.700)]
        upper = [(119.76, 30.443), (120.34, 30.443), (120.34, 30.690), (119.76, 30.690)]

        t0 = time.perf_counter()
        codes = gc.airspace_grids(lower, upper, h_min=0, h_max=1000, level=19)
        elapsed = time.perf_counter() - t0

        print(f"\n德清县区域空域计算 (Level 19, 0-1000m):")
        print(f"  网格数量: {len(codes):,}")
        print(f"  计算耗时: {elapsed:.3f} 秒")

        self.assertGreater(len(codes), 900000, "网格数量应接近 100 万")
        self.assertLess(elapsed, 30.0, "计算应在 30 秒内完成")


def main():
    """独立运行时执行完整测试并输出结果"""
    print("=" * 60)
    print("空域网格计算测试")
    print("=" * 60)

    # 示例: 德清县区域空域 (约 936 平方公里)
    print("\n示例: 德清县区域空域网格计算 (约 100 万网格)")
    print("-" * 60)

    # 下边界: 浙江省湖州市德清县范围
    # 东经 119°45′ ～ 120°21′ (119.75° ～ 120.35°)
    # 北纬 30°26′ ～ 30°42′ (30.433° ～ 30.700°)
    lower = [
        (119.75, 30.433),   # 西南角
        (120.35, 30.433),   # 东南角
        (120.35, 30.700),   # 东北角
        (119.75, 30.700),   # 西北角
    ]

    # 上边界: 略小于下边界 (内缩)
    upper = [
        (119.76, 30.443),
        (120.34, 30.443),
        (120.34, 30.690),
        (119.76, 30.690),
    ]

    h_min = 0     # 地面
    h_max = 1000  # 1000 米 (低空导航典型高度)
    level = 19    # 19 级网格 (约 11m x 11m)

    print(f"下边界: {lower}")
    print(f"上边界: {upper}")
    print(f"高度范围: {h_min}m - {h_max}m")
    print(f"网格层级: {level}")

    # 计算空域网格
    t0 = time.perf_counter()
    codes = gc.airspace_grids(lower, upper, h_min, h_max, level)
    elapsed = time.perf_counter() - t0

    print(f"\n计算结果:")
    print(f"  空域包含网格数: {len(codes)}")
    print(f"  计算耗时: {elapsed:.4f} 秒")

    # 保存为二进制文件
    if codes:
        bin_path = os.path.join(OUT_DIR, 'airspace_grids.bin')
        os.makedirs(OUT_DIR, exist_ok=True)

        with open(bin_path, 'wb') as f:
            for code in codes:
                # 3D 码使用 dim=3, 并保存层级信息
                buf = gc.to_bytes16(code, dim=3, level=level)
                f.write(buf)

        file_size = os.path.getsize(bin_path)
        print(f"\n已保存到: {bin_path}")
        print(f"  文件大小: {file_size} 字节 ({len(codes)} × 16)")

        # 显示前几个编码
        print(f"\n前 5 个网格编码:")
        for i, code in enumerate(codes[:5]):
            binary_128 = gc.to_binary128(code, level=level)
            print(f"  {i+1}. {code} -> {binary_128[:40]}...")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='空域网格计算测试')
    parser.add_argument('--test', action='store_true', help='运行 unittest')
    args = parser.parse_args()

    if args.test:
        unittest.main(argv=[''], exit=False)
    else:
        main()
