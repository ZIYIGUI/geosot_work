# -*- coding: utf-8 -*-
"""
CPSI (Cardinality PSI) 交集基数计算测试
========================================
在空域可用性计算基础上，使用 CPSI 协议仅获取交集基数（交集大小），
不返回具体交集元素，结果直接输出在终端而不存储到文件。

用法:
    python tests/test_cpsi_cardinality.py
    python -m unittest tests.test_cpsi_cardinality -v
"""
import os
import sys
import time
import unittest
import subprocess
import re

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

import geosot_core as gc

# 输出目录
OUT_DIR = os.path.join(PROJECT_ROOT, 'out', 'airspace_availability')
PSI_EXE = os.path.join(PROJECT_ROOT, 'psi', 'frontend.exe')

# 网格参数
LEVEL = 21  # 1" 网格, ~31m

# ============================================================
# 区域定义 (与 test_airspace_availability.py 相同)
# ============================================================
# 城市总区域: ~3km × 3km
CITY_LNG_MIN = 120.000
CITY_LNG_MAX = 120.028
CITY_LAT_MIN = 30.540
CITY_LAT_MAX = 30.567
CITY_H_MIN = 0
CITY_H_MAX = 500

# 占用区域 1: 建筑群
OCC1_LNG_MIN = 120.020
OCC1_LNG_MAX = 120.025
OCC1_LAT_MIN = 30.558
OCC1_LAT_MAX = 30.562
OCC1_H_MIN = 0
OCC1_H_MAX = 100

# 占用区域 2: 禁飞区
OCC2_LNG_MIN = 120.008
OCC2_LNG_MAX = 120.014
OCC2_LAT_MIN = 30.545
OCC2_LAT_MAX = 30.550
OCC2_H_MIN = 0
OCC2_H_MAX = 500

# 占用区域 3: 通信塔区域
OCC3_LNG_MIN = 120.003
OCC3_LNG_MAX = 120.005
OCC3_LAT_MIN = 30.560
OCC3_LAT_MAX = 30.562
OCC3_H_MIN = 0
OCC3_H_MAX = 300

# 查询空域
QUERY_LNG_MIN = 120.006
QUERY_LNG_MAX = 120.018
QUERY_LAT_MIN = 30.544
QUERY_LAT_MAX = 30.554
QUERY_H_MIN = 50
QUERY_H_MAX = 200


def generate_rect_grids(lng_min, lat_min, lng_max, lat_max, h_min, h_max, level):
    """生成矩形区域内的所有 3D 网格编码。"""
    cd = gc.cell_deg(level)
    hc = gc.height_cell(level)

    codes = set()
    lat = lat_min
    while lat < lat_max:
        lng = lng_min
        while lng < lng_max:
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


class TestCPSICardinality(unittest.TestCase):
    """CPSI 交集基数测试"""

    @classmethod
    def setUpClass(cls):
        """生成测试数据"""
        os.makedirs(OUT_DIR, exist_ok=True)

        print("\n" + "=" * 70)
        print("CPSI 交集基数计算 - 数据准备")
        print("=" * 70)

        # 1. 生成城市全部网格
        print("\n[1/3] 生成城市全部网格...")
        t0 = time.perf_counter()
        cls.all_city_grids = generate_rect_grids(
            CITY_LNG_MIN, CITY_LAT_MIN, CITY_LNG_MAX, CITY_LAT_MAX,
            CITY_H_MIN, CITY_H_MAX, LEVEL
        )
        print(f"  城市总网格数: {len(cls.all_city_grids):,}")
        print(f"  耗时: {time.perf_counter() - t0:.3f}s")

        # 2. 生成占用区域网格
        print("\n[2/3] 生成占用区域网格...")
        t0 = time.perf_counter()

        occ1 = generate_rect_grids(
            OCC1_LNG_MIN, OCC1_LAT_MIN, OCC1_LNG_MAX, OCC1_LAT_MAX,
            OCC1_H_MIN, OCC1_H_MAX, LEVEL
        )
        occ2 = generate_rect_grids(
            OCC2_LNG_MIN, OCC2_LAT_MIN, OCC2_LNG_MAX, OCC2_LAT_MAX,
            OCC2_H_MIN, OCC2_H_MAX, LEVEL
        )
        occ3 = generate_rect_grids(
            OCC3_LNG_MIN, OCC3_LAT_MIN, OCC3_LNG_MAX, OCC3_LAT_MAX,
            OCC3_H_MIN, OCC3_H_MAX, LEVEL
        )

        cls.occupied_grids = (occ1 | occ2 | occ3) & cls.all_city_grids
        cls.available_grids = cls.all_city_grids - cls.occupied_grids
        print(f"  占用网格数: {len(cls.occupied_grids):,}")
        print(f"  可用网格数: {len(cls.available_grids):,}")
        print(f"  耗时: {time.perf_counter() - t0:.3f}s")

        # 3. 生成查询空域网格
        print("\n[3/3] 生成查询空域网格...")
        t0 = time.perf_counter()
        cls.query_grids = generate_rect_grids(
            QUERY_LNG_MIN, QUERY_LAT_MIN, QUERY_LNG_MAX, QUERY_LAT_MAX,
            QUERY_H_MIN, QUERY_H_MAX, LEVEL
        )
        cls.query_available = cls.query_grids & cls.available_grids
        print(f"  查询空域网格数: {len(cls.query_grids):,}")
        print(f"  空域内可用网格: {len(cls.query_available):,}")
        print(f"  耗时: {time.perf_counter() - t0:.3f}s")

        # 保存 X 和 Y
        cls.y_path = os.path.join(OUT_DIR, 'available_grids_Y.bin')
        cls.x_path = os.path.join(OUT_DIR, 'query_airspace_X.bin')
        save_codes_to_bin(cls.available_grids, cls.y_path, LEVEL)
        save_codes_to_bin(cls.query_grids, cls.x_path, LEVEL)
        print(f"\n已保存:")
        print(f"  X (查询空域): {cls.x_path}")
        print(f"  Y (可用网格): {cls.y_path}")

        # 计算明文交集基数
        cls.plaintext_cardinality = len(cls.query_available)
        print(f"\n明文交集基数: {cls.plaintext_cardinality:,}")

    def test_cpsi_cardinality(self):
        """测试 CPSI 协议获取交集基数"""
        print("\n" + "=" * 70)
        print("CPSI 交集基数计算")
        print("=" * 70)

        if not os.path.exists(PSI_EXE):
            self.skipTest(f"PSI 可执行文件不存在: {PSI_EXE}")

        # Receiver (X 方) - 获得交集基数
        cmd_receiver = [
            PSI_EXE,
            '-in', self.x_path,
            '-r', '1',
            '-server', '1',
            '-card',  # CIRCUIT PSI cardinality 模式：仅返回交集基数，不写输出文件
            '-v'      # verbose 输出
        ]

        # Sender (Y 方) - 不获得结果
        cmd_sender = [
            PSI_EXE,
            '-in', self.y_path,
            '-r', '0',
            '-server', '0',
            '-card'   # CIRCUIT PSI cardinality 模式
        ]

        print(f"  X (查询空域): {len(self.query_grids):,} 个编码")
        print(f"  Y (可用网格): {len(self.available_grids):,} 个编码")
        print(f"\n  启动 CPSI 协议...")

        # 启动 Receiver (后台，作为服务器等待连接)
        t0 = time.perf_counter()
        receiver_proc = subprocess.Popen(
            cmd_receiver,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # 等待 Receiver 启动并监听
        time.sleep(1)

        # 启动 Sender (前台等待，作为客户端连接)
        sender_proc = subprocess.Popen(
            cmd_sender,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        sender_stdout, sender_stderr = sender_proc.communicate(timeout=300)
        receiver_stdout, receiver_stderr = receiver_proc.communicate(timeout=300)
        elapsed = time.perf_counter() - t0

        print(f"  CPSI 计算耗时: {elapsed:.3f}s")

        # 解析输出
        receiver_output = receiver_stdout.decode('utf-8', errors='ignore')
        receiver_stderr_str = receiver_stderr.decode('utf-8', errors='ignore')
        sender_output = sender_stdout.decode('utf-8', errors='ignore')
        sender_stderr_str = sender_stderr.decode('utf-8', errors='ignore')

        print(f"\n  === Sender stdout ===")
        if sender_output.strip():
            for line in sender_output.strip().split('\n'):
                if line.strip():
                    print(f"    {line}")
        if sender_stderr_str.strip():
            print(f"\n  === Sender stderr ===")
            for line in sender_stderr_str.strip().split('\n'):
                if line.strip():
                    print(f"    {line}")

        print(f"\n  === Receiver stdout ===")
        if receiver_output.strip():
            for line in receiver_output.strip().split('\n'):
                if line.strip():
                    print(f"    {line}")
        else:
            print(f"    (空)")

        if receiver_stderr_str.strip():
            print(f"\n  === Receiver stderr ===")
            for line in receiver_stderr_str.strip().split('\n'):
                if line.strip():
                    print(f"    {line}")

        # 尝试从输出中提取交集基数
        # 输出格式: "cardinality = 5940"
        cardinality = None
        combined_output = receiver_output + '\n' + receiver_stderr_str
        for line in combined_output.split('\n'):
            if 'cardinality' in line.lower():
                # 匹配 "cardinality = 5940" 或 "cardinality: 5940"
                match = re.search(r'cardinality\s*[=:]\s*(\d+)', line, re.IGNORECASE)
                if match:
                    cardinality = int(match.group(1))
                    break

        print(f"\n  === 结果对比 ===")
        print(f"  明文交集基数: {self.plaintext_cardinality:,}")

        if cardinality is not None:
            print(f"  CPSI 交集基数: {cardinality:,}")
            match = cardinality == self.plaintext_cardinality
            print(f"  一致性验证: {'PASS [OK]' if match else 'FAIL [X]'}")
            self.assertEqual(cardinality, self.plaintext_cardinality,
                           "CPSI 交集基数应与明文交集大小一致")
        else:
            print(f"  [警告] 无法从输出中解析交集基数")
            print(f"  请检查 frontend.exe 的 CPSI 输出格式")
            # 至少验证程序正常退出
            self.assertEqual(receiver_proc.returncode, 0, "Receiver 应正常退出")


def main():
    """独立运行: CPSI 演示"""
    print("=" * 70)
    print("CPSI (Cardinality PSI) 交集基数计算演示")
    print("=" * 70)
    print(f"\n网格层级: Level {LEVEL} (1\" 网格, ~31m × 27m × 31m)")

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
    available = all_grids - occupied
    print(f"    占用网格: {len(occupied):,}")
    print(f"    可用网格 (Y): {len(available):,}")

    # 3. 查询空域
    print(f"\n[3] 生成查询空域网格...")
    query = generate_rect_grids(
        QUERY_LNG_MIN, QUERY_LAT_MIN, QUERY_LNG_MAX, QUERY_LAT_MAX,
        QUERY_H_MIN, QUERY_H_MAX, LEVEL
    )
    query_available = query & available
    print(f"    查询空域网格 (X): {len(query):,}")
    print(f"    空域内可用网格: {len(query_available):,}")

    # 保存 X 和 Y
    y_path = os.path.join(OUT_DIR, 'available_grids_Y.bin')
    x_path = os.path.join(OUT_DIR, 'query_airspace_X.bin')
    save_codes_to_bin(available, y_path, LEVEL)
    save_codes_to_bin(query, x_path, LEVEL)

    # 明文交集基数
    plaintext_card = len(query_available)
    print(f"\n明文交集基数: {plaintext_card:,}")

    # CPSI 计算
    if not os.path.exists(PSI_EXE):
        print(f"\n[!] PSI 可执行文件不存在: {PSI_EXE}")
        return

    print(f"\n[4] CPSI 交集基数计算...")
    print(f"    (仅返回交集大小，不返回具体元素)")

    cmd_sender = [PSI_EXE, '-in', y_path, '-r', '0', '-server', '0',
                  '-card']
    cmd_receiver = [PSI_EXE, '-in', x_path, '-r', '1', '-server', '1',
                    '-card', '-v']

    t0 = time.perf_counter()
    sender = subprocess.Popen(cmd_sender, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(1)  # 等待 Sender 启动
    receiver = subprocess.Popen(cmd_receiver, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    receiver_stdout, receiver_stderr = receiver.communicate(timeout=300)
    sender.communicate(timeout=300)
    elapsed = time.perf_counter() - t0

    print(f"    CPSI 耗时: {elapsed:.3f}s")

    # 解析输出
    receiver_output = receiver_stdout.decode('utf-8', errors='ignore')
    receiver_stderr_str = receiver_stderr.decode('utf-8', errors='ignore')

    print(f"\n  === Receiver 输出 ===")
    combined = receiver_output + receiver_stderr_str
    if combined.strip():
        for line in combined.strip().split('\n'):
            if line.strip():
                print(f"    {line}")
    else:
        print(f"    (无输出)")

    # 提取交集基数
    # 输出格式: "cardinality = 5940"
    cardinality = None
    for line in combined.split('\n'):
        if 'cardinality' in line.lower():
            match = re.search(r'cardinality\s*[=:]\s*(\d+)', line, re.IGNORECASE)
            if match:
                cardinality = int(match.group(1))
                break

    print(f"\n{'='*70}")
    print(f"结果对比:")
    print(f"  明文交集基数: {plaintext_card:,}")
    if cardinality is not None:
        print(f"  CPSI 交集基数: {cardinality:,}")
        match = cardinality == plaintext_card
        print(f"  一致性: {'PASS [OK]' if match else 'FAIL [X]'}")
    else:
        print(f"  [提示] 无法从输出中解析交集基数")
        print(f"  请检查 frontend.exe 的 CPSI 输出格式")
    print(f"{'='*70}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='CPSI 交集基数计算测试')
    parser.add_argument('--test', action='store_true', help='运行 unittest')
    args = parser.parse_args()

    if args.test:
        unittest.main(argv=[''], exit=False, verbosity=2)
    else:
        main()
