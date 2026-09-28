# -*- coding: utf-8 -*-
"""
无人机起降场选址算法测试
========================
测试基于网格的无人机选址算法完整流程:
1. 构建时空网格
2. 硬约束过滤 (8位掩码)
3. 软约束风险评分
4. DBSCAN 聚类 + 风险加权质心
5. 时间窗口可用性检查
6. 输出候选起降场

用法:
    python tests/test_uav_siting.py
    python -m unittest tests.test_uav_siting -v
"""
import os
import sys
import unittest
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from uav_siting import (
    GridMask,
    build_spatiotemporal_grids,
    hard_constraint_filter,
    compute_risk_scores,
    filter_by_risk_threshold,
    cluster_and_centroids,
    time_window_availability,
    uav_siting
)
import geosot_core as gc


# ============================================================================
# 测试数据: 德清县整个区域
# ============================================================================
# 下边界多边形 (德清县全域, 约 60km × 30km)
LOWER_POLYGON = [
    (119.75, 30.433),
    (120.35, 30.433),
    (120.35, 30.700),
    (119.75, 30.700)
]

# 上边界多边形 (略内缩)
UPPER_POLYGON = [
    (119.76, 30.443),
    (120.34, 30.443),
    (120.34, 30.690),
    (119.76, 30.690)
]

# 高度范围
H_MIN = 0
H_MAX = 500  # 500米 (低空导航典型高度)

# 网格层级 (Level 17 约 44m 精度, 适合县域级别)
# 注: Level 19 在德清县全域会产生约 580 万网格, 超出内存限制
LEVEL = 17

# 时间范围
TIME_START = 0
TIME_END = 10  # 10个时间步
DT = 1


def create_mock_mask_provider():
    """创建模拟掩码提供函数

    模拟场景:
    - 某些网格在特定时间步有禁飞区 (b0)
    - 某些网格有障碍物 (b1)
    - 某些网格在特定时间步有临时空管 (b4)
    """
    # 预先定义一些有问题的网格编码 (用哈希模拟)
    def mask_provider(code, time_step):
        # 使用编码的低位作为伪随机种子
        seed = code % 100

        mask = 0

        # 10% 的网格有禁飞区标记
        if seed < 10:
            mask |= GridMask.NO_FLY

        # 5% 的网格有障碍物
        if 10 <= seed < 15:
            mask |= GridMask.OBSTACLE

        # 在时间步 5-7, 某些网格有临时空管
        if 5 <= time_step <= 7 and seed % 3 == 0:
            mask |= GridMask.ATC_CONTROL

        # 20% 的网格标记为城市场景 (不参与硬约束)
        if seed < 20:
            mask |= GridMask.SCENE_LABEL

        return mask

    return mask_provider


def create_mock_risk_factors(grids):
    """创建模拟风险因子数据

    模拟 5 个风险因子:
    1. 土地利用适宜度 (land_use)
    2. 人口密度规避程度 (population)
    3. 电力设施接近性 (power_facility)
    4. 建设成本 (construction_cost)
    5. 噪声社会适宜性 (noise)
    """
    risk_factors = {
        'land_use': {},
        'population': {},
        'power_facility': {},
        'construction_cost': {},
        'noise': {}
    }

    # 为每个网格生成随机风险因子值 [0, 1]
    unique_codes = set(grid['code'] for grid in grids)

    for code in unique_codes:
        # 使用编码作为伪随机种子
        np.random.seed(code % 10000)

        risk_factors['land_use'][code] = np.random.uniform(0.1, 0.9)
        risk_factors['population'][code] = np.random.uniform(0.0, 0.8)
        risk_factors['power_facility'][code] = np.random.uniform(0.0, 0.5)
        risk_factors['construction_cost'][code] = np.random.uniform(0.2, 0.7)
        risk_factors['noise'][code] = np.random.uniform(0.1, 0.6)

    return risk_factors


class TestGridMask(unittest.TestCase):
    """测试网格掩码系统"""

    def test_hard_constraint_pass(self):
        """测试通过硬约束的情况"""
        # 只有 b6 (场景标签) 置位, 不参与硬约束
        mask = GridMask.SCENE_LABEL
        self.assertTrue(GridMask.check_hard_constraint(mask))

        # 全部为 0, 通过
        mask = 0
        self.assertTrue(GridMask.check_hard_constraint(mask))

    def test_hard_constraint_fail(self):
        """测试未通过硬约束的情况"""
        # b0 (禁飞区) 置位, 一票否决
        mask = GridMask.NO_FLY
        self.assertFalse(GridMask.check_hard_constraint(mask))

        # b1 (障碍物) 置位
        mask = GridMask.OBSTACLE
        self.assertFalse(GridMask.check_hard_constraint(mask))

        # b0 + b6 (禁飞区 + 场景标签)
        mask = GridMask.NO_FLY | GridMask.SCENE_LABEL
        self.assertFalse(GridMask.check_hard_constraint(mask))

    def test_describe_mask(self):
        """测试掩码描述"""
        mask = GridMask.NO_FLY | GridMask.WEATHER | GridMask.SCENE_LABEL
        labels = GridMask.describe_mask(mask)
        self.assertIn("禁飞区", labels)
        self.assertIn("恶劣气象", labels)
        self.assertIn("城市场景", labels)


class TestSpatiotemporalGrids(unittest.TestCase):
    """测试时空网格构建"""

    def test_build_grids(self):
        """测试构建时空网格"""
        grids = build_spatiotemporal_grids(
            LOWER_POLYGON, UPPER_POLYGON,
            H_MIN, H_MAX, LEVEL,
            TIME_START, TIME_END, DT
        )

        self.assertGreater(len(grids), 0, "应生成至少一个网格")

        # 检查网格结构
        grid = grids[0]
        self.assertIn('code', grid)
        self.assertIn('time_step', grid)
        self.assertIn('mask', grid)
        self.assertIn('lat', grid)
        self.assertIn('lng', grid)
        self.assertIn('h', grid)
        self.assertIn('level', grid)

        # 检查时间步覆盖
        time_steps = set(grid['time_step'] for grid in grids)
        self.assertEqual(time_steps, set(range(TIME_START, TIME_END)))

    def test_build_grids_with_mask(self):
        """测试带掩码的时空网格"""
        mask_provider = create_mock_mask_provider()

        grids = build_spatiotemporal_grids(
            LOWER_POLYGON, UPPER_POLYGON,
            H_MIN, H_MAX, LEVEL,
            TIME_START, TIME_END, DT,
            mask_provider
        )

        # 检查掩码值
        masks = [grid['mask'] for grid in grids]
        self.assertTrue(any(m > 0 for m in masks), "应有非零掩码")


class TestHardConstraintFilter(unittest.TestCase):
    """测试硬约束过滤"""

    def test_filter(self):
        """测试硬约束过滤"""
        # 构建带掩码的网格
        mask_provider = create_mock_mask_provider()
        grids = build_spatiotemporal_grids(
            LOWER_POLYGON, UPPER_POLYGON,
            H_MIN, H_MAX, LEVEL,
            TIME_START, TIME_END, DT,
            mask_provider
        )

        total = len(grids)
        surviving = hard_constraint_filter(grids)

        self.assertLess(len(surviving), total, "应有部分网格被过滤")
        self.assertGreater(len(surviving), 0, "应有网格幸存")

        # 验证所有幸存网格都通过硬约束
        for grid in surviving:
            self.assertTrue(
                GridMask.check_hard_constraint(grid['mask']),
                f"幸存网格应通过硬约束: {grid['mask']:08b}"
            )


class TestRiskScoring(unittest.TestCase):
    """测试风险评分"""

    def test_compute_risk(self):
        """测试风险评分计算"""
        # 构建网格
        grids = build_spatiotemporal_grids(
            LOWER_POLYGON, UPPER_POLYGON,
            H_MIN, H_MAX, LEVEL,
            TIME_START, TIME_END, DT
        )

        # 过滤硬约束
        surviving = hard_constraint_filter(grids)

        # 生成风险因子
        risk_factors = create_mock_risk_factors(surviving)

        # 定义权重 (和为1)
        weights = {
            'land_use': 0.3,
            'population': 0.25,
            'power_facility': 0.15,
            'construction_cost': 0.2,
            'noise': 0.1
        }

        # 计算风险评分
        risk_scores = compute_risk_scores(
            surviving, risk_factors, weights, scene='urban'
        )

        self.assertGreater(len(risk_scores), 0, "应有风险评分")

        # 验证评分在 [0, 1] 范围内
        for code, score in risk_scores.items():
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)

    def test_weight_validation(self):
        """测试权重验证"""
        grids = build_spatiotemporal_grids(
            LOWER_POLYGON, UPPER_POLYGON,
            H_MIN, H_MAX, LEVEL,
            TIME_START, TIME_END, DT
        )

        risk_factors = create_mock_risk_factors(grids)

        # 权重和不为1
        bad_weights = {
            'land_use': 0.3,
            'population': 0.3  # 和为 0.6, 不是 1
        }

        with self.assertRaises(ValueError):
            compute_risk_scores(grids, risk_factors, bad_weights)


class TestClustering(unittest.TestCase):
    """测试 DBSCAN 聚类"""

    def test_cluster(self):
        """测试聚类和质心计算"""
        # 使用较小的测试区域以避免内存问题
        test_lower = [
            (120.100, 30.550),
            (120.105, 30.550),
            (120.105, 30.555),
            (120.100, 30.555)
        ]
        test_upper = [
            (120.101, 30.551),
            (120.104, 30.551),
            (120.104, 30.554),
            (120.101, 30.554)
        ]

        # 构建网格
        grids = build_spatiotemporal_grids(
            test_lower, test_upper,
            H_MIN, H_MAX, LEVEL,
            TIME_START, TIME_END, DT
        )

        surviving = hard_constraint_filter(grids)
        risk_factors = create_mock_risk_factors(surviving)

        weights = {
            'land_use': 0.3,
            'population': 0.25,
            'power_facility': 0.15,
            'construction_cost': 0.2,
            'noise': 0.1
        }

        risk_scores = compute_risk_scores(surviving, risk_factors, weights)

        # 按风险阈值过滤
        filtered = filter_by_risk_threshold(surviving, risk_scores, R_threshold=0.6)

        if len(filtered) > 0:
            # 聚类
            centroids = cluster_and_centroids(
                filtered, risk_scores, eps=200.0, min_samples=3
            )

            # 可能有 0 个或多个聚类
            for centroid in centroids:
                self.assertIn('cluster_id', centroid)
                self.assertIn('lng', centroid)
                self.assertIn('lat', centroid)
                self.assertIn('h', centroid)
                self.assertIn('grid_count', centroid)
                self.assertIn('avg_risk', centroid)

                # 验证质心坐标在合理范围内 (德清县区域)
                self.assertGreaterEqual(centroid['lng'], 119.0)
                self.assertLessEqual(centroid['lng'], 121.0)
                self.assertGreaterEqual(centroid['lat'], 30.0)
                self.assertLessEqual(centroid['lat'], 31.0)


class TestTimeWindowAvailability(unittest.TestCase):
    """测试时间窗口可用性"""

    def test_availability(self):
        """测试时间窗口可用性检查"""
        # 构建完整流程数据
        mask_provider = create_mock_mask_provider()
        grids = build_spatiotemporal_grids(
            LOWER_POLYGON, UPPER_POLYGON,
            H_MIN, H_MAX, LEVEL,
            TIME_START, TIME_END, DT,
            mask_provider
        )

        surviving = hard_constraint_filter(grids)
        risk_factors = create_mock_risk_factors(surviving)

        weights = {
            'land_use': 0.3,
            'population': 0.25,
            'power_facility': 0.15,
            'construction_cost': 0.2,
            'noise': 0.1
        }

        risk_scores = compute_risk_scores(surviving, risk_factors, weights)
        filtered = filter_by_risk_threshold(surviving, risk_scores, R_threshold=0.6)

        if len(filtered) > 0:
            centroids = cluster_and_centroids(
                filtered, risk_scores, eps=200.0, min_samples=3
            )

            if len(centroids) > 0:
                qualified = time_window_availability(
                    centroids, surviving, risk_scores, R_threshold=0.6,
                    time_window=(TIME_START, TIME_END),
                    A_threshold=0.3,  # 降低阈值以便测试
                    buffer_grids=0  # 不检查缓冲, 简化测试
                )

                # 验证通过的候选点有 availability 字段
                for c in qualified:
                    self.assertIn('availability', c)
                    self.assertGreaterEqual(c['availability'], 0.5)


class TestUAVSiting(unittest.TestCase):
    """测试完整选址流程"""

    def test_full_pipeline(self):
        """测试端到端流程"""
        mask_provider = create_mock_mask_provider()
        risk_factors = None  # 将在流程中生成

        # 定义权重
        weights = {
            'land_use': 0.3,
            'population': 0.25,
            'power_facility': 0.15,
            'construction_cost': 0.2,
            'noise': 0.1
        }

        # 先构建网格以生成风险因子
        temp_grids = build_spatiotemporal_grids(
            LOWER_POLYGON, UPPER_POLYGON,
            H_MIN, H_MAX, LEVEL,
            TIME_START, TIME_END, DT,
            mask_provider
        )
        surviving = hard_constraint_filter(temp_grids)
        risk_factors = create_mock_risk_factors(surviving)

        # 运行完整流程
        result = uav_siting(
            LOWER_POLYGON, UPPER_POLYGON,
            H_MIN, H_MAX, LEVEL,
            TIME_START, TIME_END, DT,
            risk_factors, weights,
            R_threshold=0.6,
            eps=200.0,  # 县域级别使用更大聚类半径
            min_samples=3,  # 增加最小样本数以过滤噪声
            A_threshold=0.3,  # 降低阈值以便测试
            buffer_grids=0,
            mask_provider=mask_provider,
            scene='urban'
        )

        # 验证结果结构
        self.assertIn('total_grids', result)
        self.assertIn('surviving_grids', result)
        self.assertIn('risk_filtered_grids', result)
        self.assertIn('num_clusters', result)
        self.assertIn('candidates', result)

        # 验证数值关系
        self.assertGreater(result['total_grids'], 0)
        self.assertLessEqual(result['surviving_grids'], result['total_grids'])
        self.assertLessEqual(result['risk_filtered_grids'], result['surviving_grids'])

        print(f"\n=== 选址结果 ===")
        print(f"总时空网格: {result['total_grids']:,}")
        print(f"硬约束幸存: {result['surviving_grids']:,}")
        print(f"风险阈值过滤后: {result['risk_filtered_grids']:,}")
        print(f"聚类数: {result['num_clusters']}")
        print(f"最终候选起降场: {len(result['candidates'])}")

        if result['candidates']:
            print(f"\n候选起降场详情:")
            for i, c in enumerate(result['candidates'], 1):
                print(f"  [{i}] 经度={c['lng']:.6f}, 纬度={c['lat']:.6f}, "
                      f"高度={c['h']:.1f}m, 可用性={c['availability']:.2f}")


def main():
    """独立运行: 完整演示"""
    print("=" * 70)
    print("无人机起降场选址算法演示")
    print("=" * 70)
    print(f"\n区域: 德清县全域 (~60km × 30km)")
    print(f"网格层级: Level {LEVEL} (~44m)")
    print(f"高度范围: {H_MIN}m - {H_MAX}m")
    print(f"时间步: {TIME_START} - {TIME_END}")

    # 创建掩码和风险因子
    mask_provider = create_mock_mask_provider()

    # 先构建临时网格以生成风险因子
    temp_grids = build_spatiotemporal_grids(
        LOWER_POLYGON, UPPER_POLYGON,
        H_MIN, H_MAX, LEVEL,
        TIME_START, TIME_END, DT,
        mask_provider
    )
    surviving = hard_constraint_filter(temp_grids)
    risk_factors = create_mock_risk_factors(surviving)

    # 定义权重
    weights = {
        'land_use': 0.3,
        'population': 0.25,
        'power_facility': 0.15,
        'construction_cost': 0.2,
        'noise': 0.1
    }

    # 运行完整流程
    result = uav_siting(
        LOWER_POLYGON, UPPER_POLYGON,
        H_MIN, H_MAX, LEVEL,
        TIME_START, TIME_END, DT,
        risk_factors, weights,
        R_threshold=0.6,
        eps=200.0,  # 县域级别使用更大聚类半径
        min_samples=3,  # 增加最小样本数以过滤噪声
        A_threshold=0.3,
        buffer_grids=0,
        mask_provider=mask_provider,
        scene='urban'
    )

    print(f"\n{'='*70}")
    print(f"选址结果汇总")
    print(f"{'='*70}")
    print(f"总时空网格数: {result['total_grids']:,}")
    print(f"硬约束过滤后: {result['surviving_grids']:,} ({result['surviving_grids']/result['total_grids']*100:.1f}%)")
    print(f"风险阈值过滤后: {result['risk_filtered_grids']:,}")
    print(f"聚类数: {result['num_clusters']}")
    print(f"最终候选起降场: {len(result['candidates'])}")

    if result['candidates']:
        print(f"\n候选起降场列表:")
        for i, c in enumerate(result['candidates'], 1):
            print(f"  [{i}] 坐标: ({c['lng']:.6f}, {c['lat']:.6f}, {c['h']:.1f}m)")
            print(f"      聚类网格数: {c['grid_count']}, 平均风险: {c['avg_risk']:.3f}")
            print(f"      时间可用性: {c['availability']:.2f}")
    else:
        print(f"\n未找到满足条件的候选起降场")
        print(f"建议: 降低 R_threshold 或 A_threshold, 或增大 eps")

    print(f"{'='*70}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='无人机选址算法测试')
    parser.add_argument('--test', action='store_true', help='运行 unittest')
    args = parser.parse_args()

    if args.test:
        unittest.main(argv=[''], exit=False, verbosity=2)
    else:
        main()
