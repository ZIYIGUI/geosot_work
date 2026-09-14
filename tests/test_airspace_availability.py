# -*- coding: utf-8 -*-
"""
空域可用性计算测试
=================
场景: 某城市低空监管系统将城市网格化, 标记建筑物/禁飞区等占用网格,
      给定查询空域, 计算空域内哪些网格可用。

流程:
  1. 构建城市网格, 标记占用区域, 可用网格集合为 Y
  2. 定义查询空域, 计算包含的网格集合 X
  3. 明文计算 X ∩ Y (空域内可用网格)
  4. PSI 计算 X ∩ Y, 与明文结果对比

网格参数: Level 21 (1" 网格, ~31m × 27m × 31m)

用法:
    python tests/test_airspace_availability.py
    python -m unittest tests.test_airspace_availability -v
"""
import os
import sys
import time
import unittest
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

import geosot_core as gc

# 输出目录
OUT_DIR = os.path.join(PROJECT_ROOT, 'out', 'airspace_availability')
PSI_EXE = os.path.join(PROJECT_ROOT, 'psi', 'frontend.exe')

# 网格参数
LEVEL = 21  # 1" 网格, ~31m

# ============================================================
# 区域定义 (德清县附近)
# ============================================================
# 城市总区域: ~3km × 3km
CITY_LNG_MIN = 120.000   # 西边界
CITY_LNG_MAX = 120.028   # 东边界 (~3km)
CITY_LAT_MIN = 30.540    # 南边界
CITY_LAT_MAX = 30.567    # 北边界 (~3km)
CITY_H_MIN = 0           # 地面
CITY_H_MAX = 500         # 500m

# 占用区域 1: 建筑群 (城市东北部, ~500m × 400m)
OCC1_LNG_MIN = 120.020
OCC1_LNG_MAX = 120.025
OCC1_LAT_MIN = 30.558
OCC1_LAT_MAX = 30.562
OCC1_H_MIN = 0
OCC1_H_MAX = 100    # 建筑物高度 100m

# 占用区域 2: 禁飞区 (城市中部偏南, ~600m × 500m)
OCC2_LNG_MIN = 120.008
OCC2_LNG_MAX = 120.014
OCC2_LAT_MIN = 30.545
OCC2_LAT_MAX = 30.550
OCC2_H_MIN = 0
OCC2_H_MAX = 500    # 全高度禁飞

# 占用区域 3: 通信塔区域 (~200m × 200m)
OCC3_LNG_MIN = 120.003
OCC3_LNG_MAX = 120.005
OCC3_LAT_MIN = 30.560
OCC3_LAT_MAX = 30.562
OCC3_H_MIN = 0
OCC3_H_MAX = 300

# 查询空域: ~1.2km × 1.0km (覆盖部分占用区域)
QUERY_LNG_MIN = 120.006
QUERY_LNG_MAX = 120.018
QUERY_LAT_MIN = 30.544
QUERY_LAT_MAX = 30.554
QUERY_H_MIN = 50
QUERY_H_MAX = 200


def _rect_polygon(lng_min, lat_min, lng_max, lat_max):
    """矩形区域转为多边形顶点列表 [(lng, lat), ...]"""
    return [
        (lng_min, lat_min),
        (lng_max, lat_min),
        (lng_max, lat_max),
        (lng_min, lat_max),
    ]


def generate_rect_grids(lng_min, lat_min, lng_max, lat_max, h_min, h_max, level):
    """生成矩形区域内的所有 3D 网格编码。"""
    cd = gc.cell_deg(level)
    hc = gc.height_cell(level)

    codes = set()

    # 计算行列范围
    lat = lat_min
    while lat < lat_max:
        lng = lng_min
        while lng < lng_max:
            # 计算高度层范围
            h = h_min
            while h < h_max:
                code = gc.geo_num3d(lat, lng, h, level)
                codes.add(code)
                h += hc
            lng += cd
        lat += cd

    return codes


def save_codes_to_bin(codes, filepath, level):
    """将编码集合保存为 16 字节自描述格式二进制文件。"""
    sorted_codes = sorted(codes)
    with open(filepath, 'wb') as f:
        for code in sorted_codes:
            buf = gc.to_bytes16(code, dim=3, level=level)
            f.write(buf)
    return sorted_codes


def load_codes_from_bin(filepath):
    """从 16 字节自描述格式二进制文件读取编码集合。"""
    codes = set()
    with open(filepath, 'rb') as f:
        data = f.read()
    for i in range(0, len(data), 16):
        buf = data[i:i+16]
        code, level, dim = gc.from_bytes16(buf)
        codes.add(code)
    return codes


class TestAirspaceAvailability(unittest.TestCase):
    """空域可用性计算测试"""

    @classmethod
    def setUpClass(cls):
        """生成所有测试数据"""
        os.makedirs(OUT_DIR, exist_ok=True)

        print("\n" + "=" * 70)
        print("空域可用性计算 - 数据生成")
        print("=" * 70)

        # 1. 生成城市全部网格
        print("\n[1/5] 生成城市全部网格 (3km x 3km, Level 21)...")
        t0 = time.perf_counter()
        cls.all_city_grids = generate_rect_grids(
            CITY_LNG_MIN, CITY_LAT_MIN, CITY_LNG_MAX, CITY_LAT_MAX,
            CITY_H_MIN, CITY_H_MAX, LEVEL
        )
        print(f"  城市总网格数: {len(cls.all_city_grids):,}")
        print(f"  耗时: {time.perf_counter() - t0:.3f}s")

        # 2. 生成占用区域网格
        print("\n[2/5] 生成占用区域网格...")
        t0 = time.perf_counter()

        occ1 = generate_rect_grids(
            OCC1_LNG_MIN, OCC1_LAT_MIN, OCC1_LNG_MAX, OCC1_LAT_MAX,
            OCC1_H_MIN, OCC1_H_MAX, LEVEL
        )
        print(f"  占用区1 (建筑群): {len(occ1):,} 个网格")

        occ2 = generate_rect_grids(
            OCC2_LNG_MIN, OCC2_LAT_MIN, OCC2_LNG_MAX, OCC2_LAT_MAX,
            OCC2_H_MIN, OCC2_H_MAX, LEVEL
        )
        print(f"  占用区2 (禁飞区): {len(occ2):,} 个网格")

        occ3 = generate_rect_grids(
            OCC3_LNG_MIN, OCC3_LAT_MIN, OCC3_LNG_MAX, OCC3_LAT_MAX,
            OCC3_H_MIN, OCC3_H_MAX, LEVEL
        )
        print(f"  占用区3 (通信塔): {len(occ3):,} 个网格")

        cls.occupied_grids = occ1 | occ2 | occ3
        # 只保留在城市范围内的占用网格
        cls.occupied_grids = cls.occupied_grids & cls.all_city_grids
        print(f"  占用网格总数: {len(cls.occupied_grids):,}")
        print(f"  耗时: {time.perf_counter() - t0:.3f}s")

        # 3. 计算可用网格 (集合 Y)
        print("\n[3/5] 计算可用网格 (Y = 全部 - 占用)...")
        cls.available_grids = cls.all_city_grids - cls.occupied_grids
        print(f"  可用网格数 (|Y|): {len(cls.available_grids):,}")

        # 保存 Y
        cls.y_path = os.path.join(OUT_DIR, 'available_grids_Y.bin')
        save_codes_to_bin(cls.available_grids, cls.y_path, LEVEL)
        print(f"  已保存: {cls.y_path}")

        # 4. 生成查询空域网格 (集合 X)
        print("\n[4/5] 生成查询空域网格 (X)...")
        t0 = time.perf_counter()
        cls.query_grids = generate_rect_grids(
            QUERY_LNG_MIN, QUERY_LAT_MIN, QUERY_LNG_MAX, QUERY_LAT_MAX,
            QUERY_H_MIN, QUERY_H_MAX, LEVEL
        )
        print(f"  查询空域网格数 (|X|): {len(cls.query_grids):,}")
        print(f"  耗时: {time.perf_counter() - t0:.3f}s")

        # 保存 X
        cls.x_path = os.path.join(OUT_DIR, 'query_airspace_X.bin')
        save_codes_to_bin(cls.query_grids, cls.x_path, LEVEL)
        print(f"  已保存: {cls.x_path}")

        # 5. 统计查询空域中的占用情况
        cls.query_occupied = cls.query_grids & cls.occupied_grids
        cls.query_available = cls.query_grids & cls.available_grids
        print(f"\n[5/5] 查询空域统计:")
        print(f"  空域内占用网格: {len(cls.query_occupied):,}")
        print(f"  空域内可用网格: {len(cls.query_available):,}")
        print(f"  占用比例: {len(cls.query_occupied)/len(cls.query_grids)*100:.1f}%")

    def test_data_generation(self):
        """测试数据生成正确性"""
        self.assertGreater(len(self.all_city_grids), 10000, "城市网格应超过 1 万")
        self.assertGreater(len(self.occupied_grids), 100, "占用网格应超过 100")
        self.assertGreater(len(self.available_grids), 10000, "可用网格应超过 1 万")
        self.assertEqual(
            len(self.available_grids) + len(self.occupied_grids),
            len(self.all_city_grids),
            "可用 + 占用 = 全部"
        )

    def test_query_airspace(self):
        """测试查询空域包含占用网格"""
        self.assertGreater(len(self.query_grids), 100, "查询空域应超过 100 个网格")
        self.assertGreater(len(self.query_occupied), 0,
                          "查询空域应包含部分占用网格")
        self.assertGreater(len(self.query_available), 0,
                          "查询空域应包含部分可用网格")

    def test_plaintext_intersection(self):
        """测试明文交集计算"""
        print("\n" + "=" * 70)
        print("明文交集计算 (X ∩ Y)")
        print("=" * 70)

        t0 = time.perf_counter()
        plaintext_result = self.query_grids & self.available_grids
        elapsed = time.perf_counter() - t0

        print(f"  |X| = {len(self.query_grids):,}")
        print(f"  |Y| = {len(self.available_grids):,}")
        print(f"  |X ∩ Y| = {len(plaintext_result):,}")
        print(f"  计算耗时: {elapsed:.6f}s")

        # 验证结果
        self.assertEqual(plaintext_result, self.query_available)

        # 保存明文交集
        self.plaintext_path = os.path.join(OUT_DIR, 'plaintext_intersection.bin')
        save_codes_to_bin(plaintext_result, self.plaintext_path, LEVEL)
        print(f"  已保存: {self.plaintext_path}")

        # 验证从文件读回
        restored = load_codes_from_bin(self.plaintext_path)
        self.assertEqual(restored, plaintext_result, "文件往返应一致")
        print(f"  文件往返验证: PASS")

        # 保存明文结果
        self.plaintext_result = plaintext_result

    def test_psi_intersection(self):
        """测试 PSI 隐私集合交集"""
        print("\n" + "=" * 70)
        print("PSI 隐私集合交集计算")
        print("=" * 70)

        if not os.path.exists(PSI_EXE):
            self.skipTest(f"PSI 可执行文件不存在: {PSI_EXE}")

        # 确保 X 和 Y 文件已保存
        x_path = os.path.join(OUT_DIR, 'query_airspace_X.bin')
        y_path = os.path.join(OUT_DIR, 'available_grids_Y.bin')

        psi_out_path = os.path.join(OUT_DIR, 'psi_intersection.bin')

        x_size = len(self.query_grids)
        y_size = len(self.available_grids)

        # Receiver (X 方) - 获得交集结果
        cmd_receiver = [
            PSI_EXE,
            '-in', x_path,
            '-r', '1',
            '-server', '1',
            '-out', psi_out_path,
            '-noSort',
            '-receiverSize', str(x_size),
            '-senderSize', str(y_size),
            '-nt', '8'
        ]

        # Sender (Y 方) - 不获得结果
        cmd_sender = [
            PSI_EXE,
            '-in', y_path,
            '-r', '0',
            '-server', '0',
            '-noSort',
            '-receiverSize', str(x_size),
            '-senderSize', str(y_size),
            '-nt', '8'
        ]

        print(f"  X (查询空域): {x_size:,} 个编码")
        print(f"  Y (可用网格): {y_size:,} 个编码")
        print(f"\n  启动 PSI 协议...")

        # 启动 Sender (后台)
        t0 = time.perf_counter()
        sender_proc = subprocess.Popen(
            cmd_sender,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # 启动 Receiver (前台等待)
        receiver_proc = subprocess.Popen(
            cmd_receiver,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        receiver_stdout, receiver_stderr = receiver_proc.communicate(timeout=300)
        sender_stdout, sender_stderr = sender_proc.communicate(timeout=300)
        elapsed = time.perf_counter() - t0

        print(f"  PSI 计算耗时: {elapsed:.3f}s")

        # 读取 PSI 结果
        psi_result = load_codes_from_bin(psi_out_path)
        print(f"  PSI 交集大小: {len(psi_result):,}")

        # 与明文结果对比
        print(f"\n  === 结果对比 ===")
        print(f"  明文交集大小: {len(self.query_available):,}")
        print(f"  PSI 交集大小: {len(psi_result):,}")

        if psi_result == self.query_available:
            print(f"  一致性验证: PASS (完全一致)")
        else:
            missing = self.query_available - psi_result
            extra = psi_result - self.query_available
            print(f"  一致性验证: DIFF")
            if missing:
                print(f"    明文有但 PSI 无: {len(missing)} 个")
            if extra:
                print(f"    PSI 有但明文无: {len(extra)} 个")

        self.assertEqual(psi_result, self.query_available,
                        "PSI 结果应与明文交集完全一致")


def main():
    """独立运行: 完整流程演示"""
    print("=" * 70)
    print("城市低空空域可用性计算演示")
    print("=" * 70)
    print(f"\n网格层级: Level {LEVEL} (1\" 网格, ~31m × 27m × 31m)")
    print(f"城市区域: ({CITY_LNG_MIN}, {CITY_LAT_MIN}) - "
          f"({CITY_LNG_MAX}, {CITY_LAT_MAX})")
    print(f"高度范围: {CITY_H_MIN}m - {CITY_H_MAX}m")

    # 生成数据
    os.makedirs(OUT_DIR, exist_ok=True)

    # 1. 城市全部网格
    print(f"\n[1] 生成城市全部网格...")
    t0 = time.perf_counter()
    all_grids = generate_rect_grids(
        CITY_LNG_MIN, CITY_LAT_MIN, CITY_LNG_MAX, CITY_LAT_MAX,
        CITY_H_MIN, CITY_H_MAX, LEVEL
    )
    print(f"    城市总网格: {len(all_grids):,} (耗时 {time.perf_counter()-t0:.2f}s)")

    # 2. 占用区域
    print(f"\n[2] 标记占用区域...")
    occ1 = generate_rect_grids(OCC1_LNG_MIN, OCC1_LAT_MIN, OCC1_LNG_MAX, OCC1_LAT_MAX,
                               OCC1_H_MIN, OCC1_H_MAX, LEVEL)
    occ2 = generate_rect_grids(OCC2_LNG_MIN, OCC2_LAT_MIN, OCC2_LNG_MAX, OCC2_LAT_MAX,
                               OCC2_H_MIN, OCC2_H_MAX, LEVEL)
    occ3 = generate_rect_grids(OCC3_LNG_MIN, OCC3_LAT_MIN, OCC3_LNG_MAX, OCC3_LAT_MAX,
                               OCC3_H_MIN, OCC3_H_MAX, LEVEL)
    occupied = (occ1 | occ2 | occ3) & all_grids
    print(f"    建筑群:   {len(occ1):,} 个网格 ({OCC1_H_MAX}m 以下)")
    print(f"    禁飞区:   {len(occ2):,} 个网格 (全高度)")
    print(f"    通信塔:   {len(occ3):,} 个网格 ({OCC3_H_MAX}m 以下)")
    print(f"    占用合计: {len(occupied):,} 个网格")

    # 3. 可用网格 (Y)
    available = all_grids - occupied
    y_path = os.path.join(OUT_DIR, 'available_grids_Y.bin')
    save_codes_to_bin(available, y_path, LEVEL)
    print(f"\n[3] 可用网格集合 Y: {len(available):,}")
    print(f"    已保存: {y_path}")

    # 4. 查询空域 (X)
    print(f"\n[4] 查询空域 ({QUERY_LNG_MIN}-{QUERY_LNG_MAX}, "
          f"{QUERY_LAT_MIN}-{QUERY_LAT_MAX}, {QUERY_H_MIN}-{QUERY_H_MAX}m)...")
    query = generate_rect_grids(
        QUERY_LNG_MIN, QUERY_LAT_MIN, QUERY_LNG_MAX, QUERY_LAT_MAX,
        QUERY_H_MIN, QUERY_H_MAX, LEVEL
    )
    x_path = os.path.join(OUT_DIR, 'query_airspace_X.bin')
    save_codes_to_bin(query, x_path, LEVEL)
    print(f"    查询空域网格 X: {len(query):,}")
    print(f"    已保存: {x_path}")

    # 5. 明文交集
    print(f"\n[5] 明文交集计算 (X ∩ Y)...")
    t0 = time.perf_counter()
    plaintext = query & available
    elapsed = time.perf_counter() - t0
    plain_path = os.path.join(OUT_DIR, 'plaintext_intersection.bin')
    save_codes_to_bin(plaintext, plain_path, LEVEL)

    query_occ = query & occupied
    print(f"    |X| = {len(query):,}")
    print(f"    |Y| = {len(available):,}")
    print(f"    |X ∩ Y| = {len(plaintext):,} (可用网格)")
    print(f"    X 中被占用: {len(query_occ):,} ({len(query_occ)/len(query)*100:.1f}%)")
    print(f"    耗时: {elapsed:.6f}s")
    print(f"    已保存: {plain_path}")

    # 6. PSI 计算
    if os.path.exists(PSI_EXE):
        print(f"\n[6] PSI 隐私集合交集...")
        psi_out = os.path.join(OUT_DIR, 'psi_intersection.bin')

        x_size = len(query)
        y_size = len(available)

        cmd_sender = [PSI_EXE, '-in', y_path, '-r', '0', '-server', '0',
                      '-noSort', '-receiverSize', str(x_size),
                      '-senderSize', str(y_size), '-nt', '8']
        cmd_receiver = [PSI_EXE, '-in', x_path, '-r', '1', '-server', '1',
                        '-out', psi_out, '-noSort',
                        '-receiverSize', str(x_size),
                        '-senderSize', str(y_size), '-nt', '8']

        t0 = time.perf_counter()
        sender = subprocess.Popen(cmd_sender, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        receiver = subprocess.Popen(cmd_receiver, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        receiver.communicate(timeout=300)
        sender.communicate(timeout=300)
        elapsed_psi = time.perf_counter() - t0

        psi_result = load_codes_from_bin(psi_out)
        print(f"    PSI 交集大小: {len(psi_result):,}")
        print(f"    PSI 耗时: {elapsed_psi:.3f}s")

        # 对比
        match = psi_result == plaintext
        print(f"\n{'='*70}")
        print(f"结果对比:")
        print(f"  明文交集: {len(plaintext):,} 个可用网格")
        print(f"  PSI 交集: {len(psi_result):,} 个可用网格")
        print(f"  一致性:   {'PASS [OK]' if match else 'FAIL [X]'}")
        print(f"{'='*70}")
    else:
        print(f"\n[6] PSI 可执行文件不存在, 跳过: {PSI_EXE}")

    # 输出文件列表
    print(f"\n输出文件 ({OUT_DIR}):")
    for fn in sorted(os.listdir(OUT_DIR)):
        fp = os.path.join(OUT_DIR, fn)
        size = os.path.getsize(fp)
        print(f"  {fn:<40} {size:>12,} bytes")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='空域可用性计算测试')
    parser.add_argument('--test', action='store_true', help='运行 unittest')
    args = parser.parse_args()

    if args.test:
        unittest.main(argv=[''], exit=False, verbosity=2)
    else:
        main()
