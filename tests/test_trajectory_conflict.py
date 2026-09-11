# -*- coding: utf-8 -*-
"""
无人机轨迹冲突检测测试
========================
读取两份有交叉的无人机轨迹文件，生成轨迹点的网格编码后计算两个编码集合的交集，
将交集编码以 128bit 二进制形式保存到 out 目录。

用法:
    python tests/test_trajectory_conflict.py
    # 或作为 unittest 运行:
    python -m unittest tests.test_trajectory_conflict -v
"""
import os
import sys
import unittest

# 项目根目录自动解析
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

import geosot_core as gc
import geosot_service as svc
from geofile import read_csv, encode_features


# 轨迹文件路径
TRAJ_1_PATH = os.path.join(PROJECT_ROOT, 'data', 'uav_conflict_1.csv')
TRAJ_2_PATH = os.path.join(PROJECT_ROOT, 'data', 'uav_conflict_2.csv')
OUT_DIR = os.path.join(PROJECT_ROOT, 'out')
OUT_BIN_PATH = os.path.join(OUT_DIR, 'conflict_codes_128.bin')


def read_trajectory_codes(csv_path, level=21, route='B'):
    """
    读取无人机轨迹 CSV 文件，返回该轨迹所有点的网格编码集合。

    参数:
        csv_path: CSV 文件路径
        level: 网格层级，默认 21 级 (约 30m 网格)
        route: 编码路线，默认 'B' (连续网格码)

    返回:
        dict: {code_int: [(lng, lat), ...]} 编码到坐标点的映射
    """
    features = read_csv(csv_path)
    codes_map = {}

    for feat in features:
        if feat['type'] != 'Point':
            continue
        lng, lat = feat['coords'][0]
        # 使用路线B编码
        r, c = gc.row_col(lat, lng, level)
        code = svc._routeB_code(r, c, level)

        if code not in codes_map:
            codes_map[code] = []
        codes_map[code].append((lng, lat))

    return codes_map


def compute_conflict_codes(codes_map_1, codes_map_2):
    """
    计算两条轨迹的冲突编码集合（交集）。

    参数:
        codes_map_1: 轨迹1的编码映射 {code: [(lng, lat), ...]}
        codes_map_2: 轨迹2的编码映射 {code: [(lng, lat), ...]}

    返回:
        set: 冲突编码集合
    """
    set_1 = set(codes_map_1.keys())
    set_2 = set(codes_map_2.keys())
    return set_1 & set_2


def save_conflict_to_bin(conflict_codes, output_path):
    """
    将冲突编码以 128bit 二进制形式保存到文件。

    每条编码 16 字节 (128 位)，大端序，高位对齐，低位补零。
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'wb') as f:
        for code in sorted(conflict_codes):
            # 转换为 16 字节大端序
            buf = gc.to_bytes16(code, dim=2)
            f.write(buf)

    return len(conflict_codes) * 16  # 返回写入字节数


class TestTrajectoryConflict(unittest.TestCase):
    """无人机轨迹冲突检测测试用例"""

    def test_read_trajectory_files(self):
        """测试读取轨迹文件"""
        self.assertTrue(os.path.exists(TRAJ_1_PATH), f"轨迹文件1不存在: {TRAJ_1_PATH}")
        self.assertTrue(os.path.exists(TRAJ_2_PATH), f"轨迹文件2不存在: {TRAJ_2_PATH}")

        feats_1 = read_csv(TRAJ_1_PATH)
        feats_2 = read_csv(TRAJ_2_PATH)

        # 每条轨迹应有 10000 个航点
        self.assertEqual(len(feats_1), 10000, "轨迹1应有10000个航点")
        self.assertEqual(len(feats_2), 10000, "轨迹2应有10000个航点")

    def test_generate_codes(self):
        """测试生成轨迹点编码"""
        codes_1 = read_trajectory_codes(TRAJ_1_PATH, level=21)
        codes_2 = read_trajectory_codes(TRAJ_2_PATH, level=21)

        # 每条轨迹应有约 5000-8000 个不重复编码
        self.assertGreater(len(codes_1), 1000, "轨迹1应有足够多的不同编码")
        self.assertGreater(len(codes_2), 1000, "轨迹2应有足够多的不同编码")

        # 编码应为正整数
        for code in codes_1:
            self.assertIsInstance(code, int)
            self.assertGreater(code, 0)

    def test_conflict_detection(self):
        """测试冲突检测：两条轨迹应有交叉点"""
        codes_1 = read_trajectory_codes(TRAJ_1_PATH, level=21)
        codes_2 = read_trajectory_codes(TRAJ_2_PATH, level=21)

        conflicts = compute_conflict_codes(codes_1, codes_2)

        # 两条设计好的轨迹应有约 5000 个交叉点
        self.assertGreater(len(conflicts), 4000, "应有至少4000个冲突点")
        self.assertLessEqual(len(conflicts), 6000, "冲突点不应超过6000个")

        print(f"\n轨迹1编码数: {len(codes_1)}")
        print(f"轨迹2编码数: {len(codes_2)}")
        print(f"冲突编码数: {len(conflicts)}")

    def test_save_conflict_bin(self):
        """测试保存冲突编码到二进制文件"""
        codes_1 = read_trajectory_codes(TRAJ_1_PATH, level=21)
        codes_2 = read_trajectory_codes(TRAJ_2_PATH, level=21)
        conflicts = compute_conflict_codes(codes_1, codes_2)

        # 保存冲突编码
        bytes_written = save_conflict_to_bin(conflicts, OUT_BIN_PATH)

        # 验证文件大小
        self.assertEqual(bytes_written, len(conflicts) * 16)
        self.assertTrue(os.path.exists(OUT_BIN_PATH))

        file_size = os.path.getsize(OUT_BIN_PATH)
        self.assertEqual(file_size, len(conflicts) * 16)

        # 验证可从二进制还原编码
        with open(OUT_BIN_PATH, 'rb') as f:
            data = f.read()

        restored_codes = []
        for i in range(0, len(data), 16):
            buf = data[i:i+16]
            code = gc.from_bytes16(buf, dim=2)
            restored_codes.append(code)

        self.assertEqual(set(restored_codes), conflicts)

        print(f"\n已保存 {len(conflicts)} 个冲突编码到: {OUT_BIN_PATH}")
        print(f"文件大小: {file_size} 字节")


def main():
    """独立运行时执行完整流程并输出耗时统计"""
    import time

    print("=" * 60)
    print("无人机轨迹冲突检测")
    print("=" * 60)

    # 读取轨迹文件并计时
    print(f"\n轨迹文件1: {TRAJ_1_PATH}")
    print(f"轨迹文件2: {TRAJ_2_PATH}")

    t0 = time.perf_counter()
    feats_1 = read_csv(TRAJ_1_PATH)
    feats_2 = read_csv(TRAJ_2_PATH)
    read_time = time.perf_counter() - t0
    print(f"\n[1] 读取轨迹文件耗时: {read_time:.4f} 秒")
    print(f"    轨迹1航点数: {len(feats_1)}, 轨迹2航点数: {len(feats_2)}")

    # 生成编码并计时
    t1 = time.perf_counter()
    codes_1 = read_trajectory_codes(TRAJ_1_PATH, level=21)
    codes_2 = read_trajectory_codes(TRAJ_2_PATH, level=21)
    encode_time = time.perf_counter() - t1
    print(f"\n[2] 轨迹编码耗时: {encode_time:.4f} 秒")
    print(f"    轨迹1编码数: {len(codes_1)}, 轨迹2编码数: {len(codes_2)}")

    # 计算交集并计时
    t2 = time.perf_counter()
    conflicts = compute_conflict_codes(codes_1, codes_2)
    intersect_time = time.perf_counter() - t2
    print(f"\n[3] 计算交集耗时: {intersect_time:.4f} 秒")

    # 保存到二进制文件并计时
    t3 = time.perf_counter()
    bytes_written = save_conflict_to_bin(conflicts, OUT_BIN_PATH)
    save_time = time.perf_counter() - t3

    # 汇总
    total_time = time.perf_counter() - t0
    print(f"\n[4] 保存二进制文件耗时: {save_time:.4f} 秒")
    print(f"\n{'=' * 60}")
    print(f"交集大小: {len(conflicts)} 个编码")
    print(f"输出文件: {OUT_BIN_PATH} ({bytes_written} 字节)")
    print(f"总耗时: {total_time:.4f} 秒")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='无人机轨迹冲突检测')
    parser.add_argument('--test', action='store_true', help='运行 unittest')
    args = parser.parse_args()

    if args.test:
        unittest.main(argv=[''], exit=False)
    else:
        main()
