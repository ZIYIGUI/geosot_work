# -*- coding: utf-8 -*-
"""
低空导航规划器集成测试
======================
测试起降场选址、空域容量、轨迹冲突检测三大能力的整合。

测试场景:
1. 空域容量计算
2. 轨迹冲突检测（带安全距离）
3. 端到端飞行规划（选址 → 容量 → 冲突检测）
"""
import os
import sys
import unittest

# 项目根目录
_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTS_DIR = os.path.dirname(_HERE)
_PROJECT_ROOT = os.path.dirname(_TESTS_DIR)

# 确保 src 在路径最前面，避免导入 tests/low_altitude_planner/ 包
sys.path.insert(0, os.path.join(_PROJECT_ROOT, 'src'))

from low_altitude_planner import (
    airspace_capacity,
    expand_trajectory_to_spheres,
    detect_trajectory_conflicts,
    LowAltitudePlanner
)


# 测试数据路径
DATA_DIR = os.path.join(_PROJECT_ROOT, 'data')
TRAJ_1_PATH = os.path.join(DATA_DIR, 'uav_conflict_1.csv')
TRAJ_2_PATH = os.path.join(DATA_DIR, 'uav_conflict_2.csv')

# 测试空域（北京附近）
TEST_LOWER_POLYGON = [
    (116.28, 39.89),
    (116.32, 39.89),
    (116.32, 39.93),
    (116.28, 39.93)
]

TEST_UPPER_POLYGON = [
    (116.285, 39.895),
    (116.315, 39.895),
    (116.315, 39.925),
    (116.285, 39.925)
]


class TestAirspaceCapacity(unittest.TestCase):
    """空域容量计算测试"""

    def test_basic_capacity(self):
        """测试基本容量计算"""
        result = airspace_capacity(
            TEST_LOWER_POLYGON, TEST_UPPER_POLYGON,
            h_min=100, h_max=500,
            level=17  # 使用较低层级避免内存问题
        )

        # 应有返回结构
        self.assertIn('total_grids', result)
        self.assertIn('available_grids', result)
        self.assertIn('single_uav_grids', result)
        self.assertIn('capacity', result)
        self.assertIn('volume_km3', result)

        # 总网格数应大于 0
        self.assertGreater(result['total_grids'], 0)

        # 可用网格数应 <= 总网格数
        self.assertLessEqual(result['available_grids'], result['total_grids'])

        # 容量应为非负整数
        self.assertGreaterEqual(result['capacity'], 0)

        print(f"\n空域容量测试:")
        print(f"  总网格数: {result['total_grids']:,}")
        print(f"  可用网格数: {result['available_grids']:,}")
        print(f"  单架无人机占用: {result['single_uav_grids']} 个网格")
        print(f"  最大容量: {result['capacity']} 架")
        print(f"  空域体积: {result['volume_km3']:.4f} km³")

    def test_capacity_with_no_fly_zones(self):
        """测试带禁飞区的容量计算"""
        # 定义一个小禁飞区
        no_fly_zones = [{
            'polygon': [
                (116.295, 39.905),
                (116.305, 39.905),
                (116.305, 39.915),
                (116.295, 39.915)
            ],
            'h_min': 100,
            'h_max': 500
        }]

        result = airspace_capacity(
            TEST_LOWER_POLYGON, TEST_UPPER_POLYGON,
            h_min=100, h_max=500,
            level=17,
            no_fly_zones=no_fly_zones
        )

        # 可用网格应少于总网格
        self.assertLess(result['available_grids'], result['total_grids'])

        print(f"\n带禁飞区容量测试:")
        print(f"  禁飞区占用: {result['total_grids'] - result['available_grids']} 个网格")

    def test_capacity_with_obstacles(self):
        """测试带障碍物的容量计算"""
        # 定义一个障碍物
        obstacles = [{
            'center': (116.30, 39.91, 300),
            'radius': 100.0  # 100m 半径
        }]

        result = airspace_capacity(
            TEST_LOWER_POLYGON, TEST_UPPER_POLYGON,
            h_min=100, h_max=500,
            level=17,
            obstacles=obstacles
        )

        # 可用网格应少于总网格
        self.assertLess(result['available_grids'], result['total_grids'])

        print(f"\n带障碍物容量测试:")
        print(f"  障碍物占用: {result['total_grids'] - result['available_grids']} 个网格")


class TestTrajectoryConflictDetection(unittest.TestCase):
    """轨迹冲突检测测试"""

    def test_expand_trajectory(self):
        """测试轨迹球体扩展"""
        if not os.path.exists(TRAJ_1_PATH):
            self.skipTest(f"轨迹文件不存在: {TRAJ_1_PATH}")

        traj_data = expand_trajectory_to_spheres(
            TRAJ_1_PATH, radius_m=50.0, height=100.0, level=21
        )

        # 应有返回结构
        self.assertIn('codes', traj_data)
        self.assertIn('code_to_points', traj_data)

        # 占用网格数应大于 0
        self.assertGreater(len(traj_data['codes']), 0)

        # code_to_points 应有映射
        self.assertGreater(len(traj_data['code_to_points']), 0)

        print(f"\n轨迹球体扩展:")
        print(f"  占用网格数: {len(traj_data['codes']):,}")
        print(f"  关联坐标数: {len(traj_data['code_to_points']):,}")

    def test_detect_conflicts_plaintext(self):
        """测试明文冲突检测"""
        if not os.path.exists(TRAJ_1_PATH) or not os.path.exists(TRAJ_2_PATH):
            self.skipTest("轨迹文件不存在")

        # 扩展两条轨迹
        traj1_data = expand_trajectory_to_spheres(
            TRAJ_1_PATH, radius_m=50.0, height=100.0, level=21
        )
        traj2_data = expand_trajectory_to_spheres(
            TRAJ_2_PATH, radius_m=50.0, height=100.0, level=21
        )

        # 明文冲突检测
        conflicts = detect_trajectory_conflicts(
            traj1_data, traj2_data,
            use_psi=False
        )

        # 应有返回结构
        self.assertIn('conflict_codes', conflicts)
        self.assertIn('traj1_conflict_points', conflicts)
        self.assertIn('traj2_conflict_points', conflicts)

        # 两条重叠轨迹应有冲突
        self.assertGreater(len(conflicts['conflict_codes']), 0)

        print(f"\n明文冲突检测:")
        print(f"  冲突网格数: {len(conflicts['conflict_codes']):,}")
        print(f"  轨迹1冲突点: {len(conflicts['traj1_conflict_points']):,}")
        print(f"  轨迹2冲突点: {len(conflicts['traj2_conflict_points']):,}")

    def test_detect_conflicts_psi(self):
        """测试 PSI 冲突检测"""
        if not os.path.exists(TRAJ_1_PATH) or not os.path.exists(TRAJ_2_PATH):
            self.skipTest("轨迹文件不存在")

        # 扩展两条轨迹
        traj1_data = expand_trajectory_to_spheres(
            TRAJ_1_PATH, radius_m=50.0, height=100.0, level=21
        )
        traj2_data = expand_trajectory_to_spheres(
            TRAJ_2_PATH, radius_m=50.0, height=100.0, level=21
        )

        # PSI 冲突检测
        conflicts = detect_trajectory_conflicts(
            traj1_data, traj2_data,
            use_psi=True,
            psi_port=12170,
            timeout=120
        )

        # 应有返回结构
        self.assertIn('conflict_codes', conflicts)

        # 两条重叠轨迹应有冲突
        self.assertGreater(len(conflicts['conflict_codes']), 0)

        print(f"\nPSI 冲突检测:")
        print(f"  冲突网格数: {len(conflicts['conflict_codes']):,}")


class TestLowAltitudePlanner(unittest.TestCase):
    """低空导航规划器集成测试"""

    def setUp(self):
        """初始化规划器"""
        self.planner = LowAltitudePlanner(level=17, safety_distance=50.0)

    def test_register_site(self):
        """测试注册起降场"""
        result = self.planner.register_site(
            name="TestSite",
            lower_polygon=TEST_LOWER_POLYGON,
            upper_polygon=TEST_UPPER_POLYGON,
            h_min=100,
            h_max=500,
            time_window=(0, 5)
        )

        # 应有返回结构
        self.assertIn('name', result)
        self.assertIn('candidates', result)
        self.assertIn('lower_polygon', result)

        # 应注册成功
        self.assertEqual(len(self.planner.sites), 1)
        self.assertEqual(self.planner.sites[0]['name'], "TestSite")

        print(f"\n注册起降场:")
        print(f"  名称: {result['name']}")
        print(f"  候选起降场: {len(result['candidates'])} 个")

    def test_check_capacity(self):
        """测试检查容量"""
        # 先注册起降场
        self.planner.register_site(
            name="TestSite",
            lower_polygon=TEST_LOWER_POLYGON,
            upper_polygon=TEST_UPPER_POLYGON,
            h_min=100,
            h_max=500,
            time_window=(0, 5)
        )

        # 检查容量
        capacity = self.planner.check_capacity("TestSite")

        # 应有返回结构
        self.assertIn('capacity', capacity)
        self.assertGreaterEqual(capacity['capacity'], 0)

        print(f"\n检查容量:")
        print(f"  最大容量: {capacity['capacity']} 架")

    def test_validate_route(self):
        """测试验证航线"""
        if not os.path.exists(TRAJ_1_PATH) or not os.path.exists(TRAJ_2_PATH):
            self.skipTest("轨迹文件不存在")

        # 先批准一条航线
        self.planner.approve_route(TRAJ_1_PATH, "Route-1")

        # 验证新航线（与已批准航线冲突）
        validation = self.planner.validate_route(
            TRAJ_2_PATH, use_psi=False
        )

        # 应有返回结构
        self.assertIn('approved', validation)
        self.assertIn('conflict_count', validation)
        self.assertIn('suggestion', validation)

        # 应检测到冲突
        self.assertFalse(validation['approved'])
        self.assertGreater(validation['conflict_count'], 0)

        print(f"\n验证航线:")
        print(f"  批准: {validation['approved']}")
        print(f"  冲突数: {validation['conflict_count']}")
        print(f"  建议: {validation['suggestion']}")

    def test_approve_route(self):
        """测试批准航线"""
        if not os.path.exists(TRAJ_1_PATH):
            self.skipTest("轨迹文件不存在")

        # 批准航线
        self.planner.approve_route(TRAJ_1_PATH, "Route-1")

        # 应注册成功
        self.assertEqual(len(self.planner.approved_routes), 1)
        self.assertEqual(self.planner.approved_routes[0]['name'], "Route-1")

        print(f"\n批准航线:")
        print(f"  已批准航线数: {len(self.planner.approved_routes)}")

    def test_plan_flight_approved(self):
        """测试端到端飞行规划（批准场景）"""
        if not os.path.exists(TRAJ_1_PATH):
            self.skipTest("轨迹文件不存在")

        # 注册起降场
        self.planner.register_site(
            name="Origin",
            lower_polygon=TEST_LOWER_POLYGON,
            upper_polygon=TEST_UPPER_POLYGON,
            h_min=100,
            h_max=500,
            time_window=(0, 5)
        )

        self.planner.register_site(
            name="Dest",
            lower_polygon=TEST_LOWER_POLYGON,
            upper_polygon=TEST_UPPER_POLYGON,
            h_min=100,
            h_max=500,
            time_window=(0, 5)
        )

        # 规划飞行（无冲突航线）
        result = self.planner.plan_flight(
            origin_site="Origin",
            dest_site="Dest",
            route_csv=TRAJ_1_PATH,
            time_window=(0, 5),
            use_psi=False
        )

        # 应有返回结构
        self.assertIn('approved', result)
        self.assertIn('origin_capacity', result)
        self.assertIn('dest_capacity', result)
        self.assertIn('route_validation', result)
        self.assertIn('summary', result)

        # 应批准（无已批准航线，无冲突）
        self.assertTrue(result['approved'])

        print(f"\n端到端飞行规划（批准）:")
        print(f"  批准: {result['approved']}")
        print(f"  起飞场容量: {result['origin_capacity']['capacity']} 架")
        print(f"  降落场容量: {result['dest_capacity']['capacity']} 架")
        print(f"  摘要: {result['summary']}")

    def test_plan_flight_rejected(self):
        """测试端到端飞行规划（拒绝场景）"""
        if not os.path.exists(TRAJ_1_PATH) or not os.path.exists(TRAJ_2_PATH):
            self.skipTest("轨迹文件不存在")

        # 注册起降场
        self.planner.register_site(
            name="Origin",
            lower_polygon=TEST_LOWER_POLYGON,
            upper_polygon=TEST_UPPER_POLYGON,
            h_min=100,
            h_max=500,
            time_window=(0, 5)
        )

        self.planner.register_site(
            name="Dest",
            lower_polygon=TEST_LOWER_POLYGON,
            upper_polygon=TEST_UPPER_POLYGON,
            h_min=100,
            h_max=500,
            time_window=(0, 5)
        )

        # 先批准一条航线
        self.planner.approve_route(TRAJ_1_PATH, "Existing-Route")

        # 规划飞行（与已批准航线冲突）
        result = self.planner.plan_flight(
            origin_site="Origin",
            dest_site="Dest",
            route_csv=TRAJ_2_PATH,
            time_window=(0, 5),
            use_psi=False
        )

        # 应拒绝（有冲突）
        self.assertFalse(result['approved'])
        self.assertGreater(result['route_validation']['conflict_count'], 0)

        print(f"\n端到端飞行规划（拒绝）:")
        print(f"  批准: {result['approved']}")
        print(f"  冲突数: {result['route_validation']['conflict_count']}")
        print(f"  摘要: {result['summary']}")


def main():
    """独立运行完整测试流程"""
    import time

    print("=" * 70)
    print("低空导航规划器集成测试")
    print("=" * 70)

    t0 = time.perf_counter()

    # 运行所有测试
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    total_time = time.perf_counter() - t0

    print(f"\n{'=' * 70}")
    print(f"测试总数: {result.testsRun}")
    print(f"成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")
    print(f"跳过: {len(result.skipped)}")
    print(f"总耗时: {total_time:.2f} 秒")
    print(f"{'=' * 70}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='低空导航规划器测试')
    parser.add_argument('--test', action='store_true', help='运行 unittest')
    args = parser.parse_args()

    if args.test:
        unittest.main(argv=[''], exit=False)
    else:
        main()
