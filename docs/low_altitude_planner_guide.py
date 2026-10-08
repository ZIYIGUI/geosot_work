# -*- coding: utf-8 -*-
"""
低空导航规划器使用示例
======================
演示如何使用 low_altitude_planner 模块进行完整的低空导航规划。

场景: 在北京某区域规划无人机配送航线
"""
import sys
import os

# 添加 src 路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from low_altitude_planner import LowAltitudePlanner, airspace_capacity


def example_1_airspace_capacity():
    """示例 1: 计算空域容量"""
    print("=" * 70)
    print("示例 1: 计算空域容量")
    print("=" * 70)

    # 定义空域边界（北京某区域，约 4km × 4km）
    lower_polygon = [
        (116.28, 39.89),
        (116.32, 39.89),
        (116.32, 39.93),
        (116.28, 39.93)
    ]

    upper_polygon = [
        (116.285, 39.895),
        (116.315, 39.895),
        (116.315, 39.925),
        (116.285, 39.925)
    ]

    # 计算基本容量（使用 level 17 以减少网格数量）
    result = airspace_capacity(
        lower_polygon, upper_polygon,
        h_min=100, h_max=500,
        level=17
    )

    print(f"\n空域基本信息:")
    print(f"  总网格数: {result['total_grids']:,}")
    print(f"  可用网格数: {result['available_grids']:,}")
    print(f"  单架无人机占用: {result['single_uav_grids']} 个网格")
    print(f"  最大容量: {result['capacity']} 架")
    print(f"  空域体积: {result['volume_km3']:.4f} km³")
    print(f"  可用体积: {result['available_volume_km3']:.4f} km³")

    # 添加禁飞区
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

    result_with_nfz = airspace_capacity(
        lower_polygon, upper_polygon,
        h_min=100, h_max=500,
        level=17,
        no_fly_zones=no_fly_zones
    )

    print(f"\n添加禁飞区后:")
    print(f"  可用网格数: {result_with_nfz['available_grids']:,}")
    print(f"  最大容量: {result_with_nfz['capacity']} 架")
    print(f"  容量下降: {result['capacity'] - result_with_nfz['capacity']} 架")


def example_2_flight_planning():
    """示例 2: 端到端飞行规划"""
    print("\n" + "=" * 70)
    print("示例 2: 端到端飞行规划")
    print("=" * 70)

    # 创建规划器（使用 level 17 以减少网格数量，避免内存问题）
    planner = LowAltitudePlanner(level=17, safety_distance=50.0)

    # 定义空域边界（北京某区域，约 4km × 4km）
    lower_polygon = [
        (116.28, 39.89),
        (116.32, 39.89),
        (116.32, 39.93),
        (116.28, 39.93)
    ]

    upper_polygon = [
        (116.285, 39.895),
        (116.315, 39.895),
        (116.315, 39.925),
        (116.285, 39.925)
    ]

    # 注册起降场（轻量级注册，不执行选址算法）
    print("\n[1] 注册起降场...")
    planner.register_site(
        name="Origin",
        lower_polygon=lower_polygon,
        upper_polygon=upper_polygon,
        h_min=100,
        h_max=500,
        time_window=(0, 10)
    )
    print(f"  已注册起降场: {planner.sites[0]['name']}")

    planner.register_site(
        name="Dest",
        lower_polygon=lower_polygon,
        upper_polygon=upper_polygon,
        h_min=100,
        h_max=500,
        time_window=(0, 10)
    )
    print(f"  已注册起降场: {planner.sites[1]['name']}")

    # 检查容量
    print("\n[2] 检查空域容量...")
    origin_cap = planner.check_capacity("Origin")
    dest_cap = planner.check_capacity("Dest")
    print(f"  起飞场容量: {origin_cap['capacity']} 架")
    print(f"  降落场容量: {dest_cap['capacity']} 架")

    # 批准第一条航线
    print("\n[3] 批准第一条航线...")
    traj_1_path = os.path.join(PROJECT_ROOT, 'data', 'uav_conflict_1.csv')
    if os.path.exists(traj_1_path):
        planner.approve_route(traj_1_path, "Route-1")
        print(f"  已批准航线: {planner.approved_routes[0]['name']}")
        print(f"  占用网格数: {len(planner.approved_routes[0]['data']['codes']):,}")

        # 验证第二条航线（会冲突）
        print("\n[4] 验证第二条航线（与 Route-1 冲突）...")
        traj_2_path = os.path.join(PROJECT_ROOT, 'data', 'uav_conflict_2.csv')
        if os.path.exists(traj_2_path):
            validation = planner.validate_route(traj_2_path, use_psi=False)
            print(f"  批准: {validation['approved']}")
            print(f"  冲突网格数: {validation['conflict_count']:,}")
            print(f"  建议: {validation['suggestion']}")

            # 端到端规划
            print("\n[5] 端到端飞行规划...")
            result = planner.plan_flight(
                origin_site="Origin",
                dest_site="Dest",
                route_csv=traj_2_path,
                time_window=(0, 10),
                use_psi=False
            )

            print(f"  批准: {result['approved']}")
            print(f"  起飞场容量: {result['origin_capacity']['capacity']} 架")
            print(f"  降落场容量: {result['dest_capacity']['capacity']} 架")
            if result['route_validation']:
                print(f"  航线冲突数: {result['route_validation']['conflict_count']:,}")
            print(f"  摘要: {result['summary']}")
    else:
        print(f"  轨迹文件不存在: {traj_1_path}")


def example_3_capacity_with_obstacles():
    """示例 3: 带障碍物的容量计算"""
    print("\n" + "=" * 70)
    print("示例 3: 带障碍物的容量计算")
    print("=" * 70)

    # 定义空域边界
    lower_polygon = [
        (116.28, 39.89),
        (116.32, 39.89),
        (116.32, 39.93),
        (116.28, 39.93)
    ]

    upper_polygon = [
        (116.285, 39.895),
        (116.315, 39.895),
        (116.315, 39.925),
        (116.285, 39.925)
    ]

    # 定义障碍物（如高楼、塔等）
    obstacles = [
        {'center': (116.30, 39.91, 300), 'radius': 100.0},  # 障碍物 1
        {'center': (116.31, 39.92, 250), 'radius': 80.0},   # 障碍物 2
    ]

    # 计算带障碍物的容量（使用 level 17 以减少网格数量）
    result = airspace_capacity(
        lower_polygon, upper_polygon,
        h_min=100, h_max=500,
        level=17,
        obstacles=obstacles
    )

    print(f"\n空域容量（含 2 个障碍物）:")
    print(f"  总网格数: {result['total_grids']:,}")
    print(f"  可用网格数: {result['available_grids']:,}")
    print(f"  障碍物占用: {result['total_grids'] - result['available_grids']:,} 个网格")
    print(f"  最大容量: {result['capacity']} 架")


if __name__ == '__main__':
    print("\n低空导航规划器使用示例")
    print("=" * 70)

    # 运行示例
    example_1_airspace_capacity()
    example_2_flight_planning()
    example_3_capacity_with_obstacles()

    print("\n" + "=" * 70)
    print("示例运行完成")
    print("=" * 70)
