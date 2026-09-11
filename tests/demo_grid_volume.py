# -*- coding: utf-8 -*-
"""
网格体积计算演示
================
展示如何根据网格编码和层级计算网格的三维尺寸和体积。

用法:
    python tests/demo_grid_volume.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import geosot_core as gc


def main():
    print("=" * 70)
    print("网格体积计算演示 - 根据网格编码和层级计算三维尺寸")
    print("=" * 70)
    print()

    # 示例坐标: 德清县中心
    lat, lng = 30.55, 120.05
    height = 500  # 米

    print(f"坐标: {lat}°N, {lng}°E, 高度 {height}m")
    print()

    # 不同层级的网格尺寸
    print("-" * 70)
    print(f"{'层级':<6} {'编码':<20} {'南北边长':<12} {'东西边长':<12} {'高度':<10} {'体积':<16}")
    print(f"{'Level':<6} {'Code':<20} {'N-S(m)':<12} {'E-W(m)':<12} {'H(m)':<10} {'Volume(m3)':<16}")
    print("-" * 70)

    for level in [13, 15, 17, 19, 21]:
        # 2D 编码
        code_2d, r, c = gc.geo_num_routeB(lat, lng, level)
        info_2d = gc.grid_dimensions(code_2d, level, dim=2)

        # 3D 编码
        code_3d = gc.geo_num3d(lat, lng, height, level)
        info_3d = gc.grid_dimensions(code_3d, level, dim=3)

        print(f"{level:<6} {code_2d:<20} {info_2d['lat_edge']:<12.2f} {info_2d['lng_edge_south']:<12.2f} {info_2d['height']:<10.2f} {info_2d['volume']:<16,.0f}")

    print()
    print("-" * 70)
    print("说明:")
    print("  - 南北边长: 网格在南北方向的边长 (米)")
    print("  - 东西边长: 网格在南边的东西方向边长 (米)")
    print("  - 高度: 该层级的高度单元高度 (米)")
    print("  - 体积: 网格的三维体积 (立方米)")
    print()

    # 层级检测示例
    print("=" * 70)
    print("层级检测示例 (启发式估计，仅供参考)")
    print("=" * 70)
    print()
    print("注意: GeoSOT 编码的层级信息并未直接编码在码值中，")
    print("      而是作为元数据存储 (如 '506516226273443840-21' 中的 '-21')。")
    print("      因此从纯数值反推层级是启发式的，可能不准确。")
    print()

    for level in [15, 19, 21]:
        code_2d, _, _ = gc.geo_num_routeB(lat, lng, level)
        detected = gc.detect_level_from_code(code_2d, dim=2)
        status = "[OK]" if detected == level else "[approx]"
        print(f"  Level {level:2d}: code={code_2d}, detected={detected} {status}")

    print()
    print("建议在存储或传输网格编码时，始终保存层级信息。")


if __name__ == '__main__':
    main()
