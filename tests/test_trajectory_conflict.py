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

# 添加 PSI 辅助工具路径
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'tests', 'uav_siting'))
from psi_helpers import run_pairwise_psi, set_to_csv, csv_to_set


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


def expand_point_to_sphere(lng, lat, height, radius_m, level=21):
    """将单个轨迹点扩展为球体内所有网格编码。

    参数:
        lng, lat: 经纬度
        height: 高度（米）
        radius_m: 安全距离（米）
        level: 网格层级，默认 21

    返回:
        set: 球体内所有 3D 网格编码集合
    """
    codes = gc.sphere3d(lat, lng, height, radius_m, level)
    return set(codes)


def expand_trajectory_to_spheres(csv_path, radius_m, height=0, level=21):
    """将整条轨迹的所有点扩展为球体，返回去重后的占用网格集合。

    参数:
        csv_path: 轨迹 CSV 文件路径
        radius_m: 安全距离（米）
        height: 默认高度（米），若 CSV 无高度列则使用
        level: 网格层级

    返回:
        dict: {
            'codes': set,              # 去重后的占用网格编码集合
            'code_to_points': dict,    # {code: [(lng, lat, height), ...]}
        }
    """
    features = read_csv(csv_path)
    all_codes = set()
    code_to_points = {}

    for feat in features:
        if feat['type'] != 'Point':
            continue
        lng, lat = feat['coords'][0]
        h = feat.get('height', height)

        # 扩展为球体
        sphere_codes = expand_point_to_sphere(lng, lat, h, radius_m, level)
        all_codes.update(sphere_codes)

        # 记录每个编码对应的原始轨迹点
        for code in sphere_codes:
            if code not in code_to_points:
                code_to_points[code] = []
            code_to_points[code].append((lng, lat, h))

    return {
        'codes': all_codes,
        'code_to_points': code_to_points,
    }


def detect_conflicts_with_psi(traj1_data, traj2_data, port=12120, timeout=60):
    """使用 PSI 检测两条轨迹的冲突网格。

    参数:
        traj1_data: expand_trajectory_to_spheres() 返回的字典
        traj2_data: expand_trajectory_to_spheres() 返回的字典
        port: PSI 端口号
        timeout: 超时秒数

    返回:
        dict: {
            'conflict_codes': set,      # 冲突网格编码集合
            'traj1_conflict_points': list,  # 轨迹1中与冲突网格关联的坐标
            'traj2_conflict_points': list,  # 轨迹2中与冲突网格关联的坐标
        }
    """
    # 调用 PSI 求交
    result = run_pairwise_psi(
        traj1_data['codes'],
        traj2_data['codes'],
        port=port,
        card_only=False,
        timeout=timeout
    )
    conflict_codes = result['intersection']

    # 找到冲突网格对应的轨迹坐标
    traj1_points = set()
    traj2_points = set()

    for code in conflict_codes:
        # 轨迹1中与冲突网格关联的点
        if code in traj1_data['code_to_points']:
            for pt in traj1_data['code_to_points'][code]:
                traj1_points.add(pt)

        # 轨迹2中与冲突网格关联的点
        if code in traj2_data['code_to_points']:
            for pt in traj2_data['code_to_points'][code]:
                traj2_points.add(pt)

    return {
        'conflict_codes': conflict_codes,
        'traj1_conflict_points': sorted(traj1_points),
        'traj2_conflict_points': sorted(traj2_points),
    }


def find_nearest_trajectory_point(conflict_code, code_to_points, level=21):
    """找到冲突网格编码的中心点，并返回最近的轨迹坐标。

    参数:
        conflict_code: 冲突网格编码
        code_to_points: {code: [(lng, lat, height), ...]}
        level: 网格层级

    返回:
        tuple: (nearest_lng, nearest_lat, nearest_height, distance_m)
    """
    if conflict_code not in code_to_points:
        return None

    # 获取网格中心点
    center_lat, center_lng, center_h = gc.center_point3d(conflict_code, level)

    # 找到最近的轨迹点
    min_dist = float('inf')
    nearest = None

    for (lng, lat, h) in code_to_points[conflict_code]:
        dist = gc._haversine_atan2(center_lat, center_lng, lat, lng)
        if dist < min_dist:
            min_dist = dist
            nearest = (lng, lat, h)

    return (*nearest, min_dist) if nearest else None


def summarize_conflicts(conflict_result, max_output=20):
    """输出冲突摘要信息。

    参数:
        conflict_result: detect_conflicts_with_psi() 返回的字典
        max_output: 最多输出的冲突点数量
    """
    print(f"\n冲突网格数量: {len(conflict_result['conflict_codes'])}")
    print(f"轨迹1涉及冲突的坐标点: {len(conflict_result['traj1_conflict_points'])}")
    print(f"轨迹2涉及冲突的坐标点: {len(conflict_result['traj2_conflict_points'])}")

    if conflict_result['traj1_conflict_points']:
        n = min(max_output, len(conflict_result['traj1_conflict_points']))
        print(f"\n轨迹1前 {n} 个冲突坐标:")
        for pt in conflict_result['traj1_conflict_points'][:max_output]:
            print(f"  ({pt[0]:.6f}, {pt[1]:.6f}, {pt[2]:.1f}m)")


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
            code, _level, _dim = gc.from_bytes16(buf)
            restored_codes.append(code)

        self.assertEqual(set(restored_codes), conflicts)

        print(f"\n已保存 {len(conflicts)} 个冲突编码到: {OUT_BIN_PATH}")
        print(f"文件大小: {file_size} 字节")

    def test_expand_point_to_sphere(self):
        """测试单点球体扩展"""
        # 测试点: (116.3, 39.91), 高度100m, 半径50m
        lng, lat, height = 116.3, 39.91, 100.0
        radius = 50.0
        level = 21

        codes = expand_point_to_sphere(lng, lat, height, radius, level)

        # 球体应包含多个网格编码
        self.assertGreater(len(codes), 1, "球体应包含多个网格编码")
        self.assertLess(len(codes), 1000, "球体编码数应合理")

        # 所有编码应为正整数
        for code in codes:
            self.assertIsInstance(code, int)
            self.assertGreater(code, 0)

        print(f"\n单点球体扩展: {len(codes)} 个网格编码")

    def test_expand_trajectory_to_spheres(self):
        """测试整条轨迹球体扩展"""
        radius = 50.0
        height = 100.0
        level = 21

        traj_data = expand_trajectory_to_spheres(
            TRAJ_1_PATH, radius, height, level
        )

        # 应返回字典结构
        self.assertIn('codes', traj_data)
        self.assertIn('code_to_points', traj_data)

        # 占用网格数应大于原始航点数（因为每个点扩展为多个网格）
        self.assertGreater(len(traj_data['codes']), 1000, "占用网格数应足够多")

        # code_to_points 应有映射
        self.assertGreater(len(traj_data['code_to_points']), 0)

        print(f"\n轨迹1球体扩展: {len(traj_data['codes'])} 个占用网格")

    def test_detect_conflicts_with_psi(self):
        """测试 PSI 冲突检测"""
        radius = 50.0
        height = 100.0
        level = 21

        # 扩展两条轨迹
        traj1_data = expand_trajectory_to_spheres(
            TRAJ_1_PATH, radius, height, level
        )
        traj2_data = expand_trajectory_to_spheres(
            TRAJ_2_PATH, radius, height, level
        )

        # 使用 PSI 检测冲突
        conflict_result = detect_conflicts_with_psi(
            traj1_data, traj2_data, port=12130, timeout=60
        )

        # 应返回字典结构
        self.assertIn('conflict_codes', conflict_result)
        self.assertIn('traj1_conflict_points', conflict_result)
        self.assertIn('traj2_conflict_points', conflict_result)

        # 两条重叠轨迹应有冲突
        self.assertGreater(
            len(conflict_result['conflict_codes']), 0,
            "两条重叠轨迹应有冲突网格"
        )

        # 冲突网格应对应轨迹坐标
        self.assertGreater(
            len(conflict_result['traj1_conflict_points']), 0,
            "轨迹1应有冲突坐标"
        )
        self.assertGreater(
            len(conflict_result['traj2_conflict_points']), 0,
            "轨迹2应有冲突坐标"
        )

        print(f"\nPSI 冲突检测:")
        print(f"  冲突网格数: {len(conflict_result['conflict_codes'])}")
        print(f"  轨迹1冲突点: {len(conflict_result['traj1_conflict_points'])}")
        print(f"  轨迹2冲突点: {len(conflict_result['traj2_conflict_points'])}")

    def test_find_nearest_trajectory_point(self):
        """测试最近轨迹坐标查找"""
        radius = 50.0
        height = 100.0
        level = 21

        # 扩展轨迹
        traj_data = expand_trajectory_to_spheres(
            TRAJ_1_PATH, radius, height, level
        )

        # 取第一个冲突网格测试
        if len(traj_data['code_to_points']) > 0:
            test_code = next(iter(traj_data['code_to_points'].keys()))
            result = find_nearest_trajectory_point(
                test_code, traj_data['code_to_points'], level
            )

            # 应返回四元组
            self.assertIsNotNone(result)
            self.assertEqual(len(result), 4)

            lng, lat, h, dist = result
            self.assertIsInstance(lng, float)
            self.assertIsInstance(lat, float)
            self.assertIsInstance(h, (int, float))
            self.assertIsInstance(dist, float)
            self.assertGreaterEqual(dist, 0)

            print(f"\n最近轨迹点: ({lng:.6f}, {lat:.6f}, {h:.1f}m), 距离: {dist:.2f}m")


def main():
    """独立运行时执行完整流程并输出耗时统计"""
    import time

    # 配置参数
    SAFETY_DISTANCE = 50.0  # 安全距离 50 米
    DEFAULT_HEIGHT = 100.0  # 默认高度 100 米
    LEVEL = 21
    PSI_PORT = 12140

    print("=" * 60)
    print("无人机轨迹冲突检测（安全距离球体扩展）")
    print("=" * 60)
    print(f"\n安全距离: {SAFETY_DISTANCE} 米")
    print(f"默认高度: {DEFAULT_HEIGHT} 米")
    print(f"网格层级: {LEVEL}")

    # 读取轨迹文件并计时
    print(f"\n轨迹文件1: {TRAJ_1_PATH}")
    print(f"轨迹文件2: {TRAJ_2_PATH}")

    t0 = time.perf_counter()
    feats_1 = read_csv(TRAJ_1_PATH)
    feats_2 = read_csv(TRAJ_2_PATH)
    read_time = time.perf_counter() - t0
    print(f"\n[1] 读取轨迹文件耗时: {read_time:.4f} 秒")
    print(f"    轨迹1航点数: {len(feats_1)}, 轨迹2航点数: {len(feats_2)}")

    # 球体扩展并计时
    t1 = time.perf_counter()
    traj1_data = expand_trajectory_to_spheres(
        TRAJ_1_PATH, SAFETY_DISTANCE, DEFAULT_HEIGHT, LEVEL
    )
    traj2_data = expand_trajectory_to_spheres(
        TRAJ_2_PATH, SAFETY_DISTANCE, DEFAULT_HEIGHT, LEVEL
    )
    expand_time = time.perf_counter() - t1
    print(f"\n[2] 球体扩展耗时: {expand_time:.4f} 秒")
    print(f"    轨迹1占用网格: {len(traj1_data['codes'])}")
    print(f"    轨迹2占用网格: {len(traj2_data['codes'])}")

    # PSI 冲突检测并计时
    t2 = time.perf_counter()
    conflict_result = detect_conflicts_with_psi(
        traj1_data, traj2_data, port=PSI_PORT, timeout=120
    )
    psi_time = time.perf_counter() - t2
    print(f"\n[3] PSI 冲突检测耗时: {psi_time:.4f} 秒")

    # 输出冲突摘要
    summarize_conflicts(conflict_result, max_output=10)

    # 汇总
    total_time = time.perf_counter() - t0
    print(f"\n{'=' * 60}")
    print(f"冲突网格数: {len(conflict_result['conflict_codes'])}")
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
