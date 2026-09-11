# -*- coding: utf-8 -*-
"""
16 字节自描述格式演示
====================
展示新的 16 字节格式如何存储 geo_num + level + dim 信息，
以及如何从二进制文件完整恢复所有信息。

用法:
    python tests/demo_16byte_format.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import geosot_core as gc


def main():
    print("=" * 70)
    print("16 字节自描述格式演示")
    print("=" * 70)
    print()

    # 示例坐标: 德清县中心
    lat, lng = 30.55, 120.05
    height = 500  # 米
    level = 19

    print(f"坐标: {lat}N, {lng}E, 高度 {height}m, 层级 {level}")
    print()

    # 1. 2D 编码
    print("-" * 70)
    print("1. 2D 编码 (Route B)")
    print("-" * 70)
    code_2d, r, c = gc.geo_num_routeB(lat, lng, level)
    print(f"   geo_num: {code_2d}")
    print(f"   level:   {level}")
    print(f"   dim:     2")

    # 编码为 16 字节
    buf_2d = gc.to_bytes16(code_2d, dim=2, level=level)
    print(f"   16 bytes: {buf_2d.hex()}")
    print()

    # 字节布局解析
    print("   字节布局:")
    print(f"     Byte 0-7  (geo_num low):  {buf_2d[0:8].hex()}")
    print(f"     Byte 8-11 (geo_num high): {buf_2d[8:12].hex()}")
    print(f"     Byte 12   (level):        {buf_2d[12]}")
    print(f"     Byte 13   (dim):          {buf_2d[13]}")
    print(f"     Byte 14-15 (reserved):    {buf_2d[14:16].hex()}")
    print()

    # 从 16 字节恢复
    restored_code, restored_level, restored_dim = gc.from_bytes16(buf_2d)
    print(f"   恢复结果:")
    print(f"     geo_num: {restored_code}")
    print(f"     level:   {restored_level}")
    print(f"     dim:     {restored_dim}")
    print(f"     匹配: {restored_code == code_2d and restored_level == level and restored_dim == 2}")
    print()

    # 2. 3D 编码
    print("-" * 70)
    print("2. 3D 编码 (geo_num3d)")
    print("-" * 70)
    code_3d = gc.geo_num3d(lat, lng, height, level)
    print(f"   geo_num: {code_3d}")
    print(f"   level:   {level}")
    print(f"   dim:     3")

    # 编码为 16 字节
    buf_3d = gc.to_bytes16(code_3d, dim=3, level=level)
    print(f"   16 bytes: {buf_3d.hex()}")
    print()

    # 字节布局解析
    print("   字节布局:")
    print(f"     Byte 0-7  (geo_num low):  {buf_3d[0:8].hex()}")
    print(f"     Byte 8-11 (geo_num high): {buf_3d[8:12].hex()}")
    print(f"     Byte 12   (level):        {buf_3d[12]}")
    print(f"     Byte 13   (dim):          {buf_3d[13]}")
    print(f"     Byte 14-15 (reserved):    {buf_3d[14:16].hex()}")
    print()

    # 从 16 字节恢复
    restored_code, restored_level, restored_dim = gc.from_bytes16(buf_3d)
    print(f"   恢复结果:")
    print(f"     geo_num: {restored_code}")
    print(f"     level:   {restored_level}")
    print(f"     dim:     {restored_dim}")
    print(f"     匹配: {restored_code == code_3d and restored_level == level and restored_dim == 3}")
    print()

    # 3. 保存和读取二进制文件
    print("-" * 70)
    print("3. 二进制文件存储演示")
    print("-" * 70)

    # 生成多个编码
    codes = []
    for i in range(5):
        code, _, _ = gc.geo_num_routeB(lat + i * 0.01, lng + i * 0.01, level)
        codes.append((code, level, 2))

    # 保存到文件
    bin_path = os.path.join(os.path.dirname(__file__), '..', 'out', 'demo_16byte.bin')
    os.makedirs(os.path.dirname(bin_path), exist_ok=True)

    with open(bin_path, 'wb') as f:
        for code, lvl, dim in codes:
            buf = gc.to_bytes16(code, dim=dim, level=lvl)
            f.write(buf)

    print(f"   已保存 {len(codes)} 个编码到: {bin_path}")
    print(f"   文件大小: {os.path.getsize(bin_path)} 字节 ({len(codes)} x 16)")
    print()

    # 从文件读取并恢复
    print("   从文件读取并恢复:")
    with open(bin_path, 'rb') as f:
        data = f.read()

    for i in range(0, len(data), 16):
        buf = data[i:i+16]
        restored_code, restored_level, restored_dim = gc.from_bytes16(buf)
        print(f"     [{i//16}] geo_num={restored_code}, level={restored_level}, dim={restored_dim}")

    print()
    print("=" * 70)
    print("总结")
    print("=" * 70)
    print()
    print("新的 16 字节格式包含:")
    print("  - geo_num 编码值 (8-12 字节)")
    print("  - level 层级信息 (1 字节, 0-32)")
    print("  - dim 维度信息 (1 字节, 2 或 3)")
    print("  - reserved 保留位 (2 字节)")
    print()
    print("优势:")
    print("  - 自描述: 从二进制文件可完整恢复所有信息")
    print("  - 无需额外元数据: 层级信息内置于 16 字节中")
    print("  - 向后兼容: 提供 from_bytes16_legacy() 函数")


if __name__ == '__main__':
    main()
