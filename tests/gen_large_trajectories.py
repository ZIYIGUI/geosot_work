# -*- coding: utf-8 -*-
"""
生成大规模无人机轨迹数据
========================
生成两条各有 10000 个航点的轨迹文件，两条轨迹有约 5000 个交叉点。

轨迹设计:
  - 轨迹1: 在区域A内锯齿形飞行，覆盖约 5000 个网格
  - 轨迹2: 在区域B内锯齿形飞行（与区域A部分重叠），覆盖约 5000 个网格
  - 两区域重叠部分产生约 5000 个交叉点

用法:
    python tests/gen_large_trajectories.py
"""
import os
import sys
import math

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

DATA_DIR = os.path.join(PROJECT_ROOT, 'data')


def generate_sawtooth_trajectory(center_lon, center_lat, width, height,
                                  rows, total_points, direction=1, drone_id='DRONE-01',
                                  start_alt=100, alt_step=0.01, time_step=1):
    """
    生成锯齿形轨迹
    """
    points = []

    lon_start = center_lon - width / 2
    lon_end = center_lon + width / 2
    lat_start = center_lat - height / 2
    lat_step = height / rows

    t = 0
    alt = start_alt
    pts_per_row = max(1, total_points // rows)

    for row in range(rows):
        lat = lat_start + row * lat_step

        if (row % 2 == 0) == (direction == 1):
            lon_range = (lon_start, lon_end)
        else:
            lon_range = (lon_end, lon_start)

        for i in range(pts_per_row):
            frac = i / max(1, pts_per_row - 1)
            lon = lon_range[0] + frac * (lon_range[1] - lon_range[0])
            points.append((lon, lat, alt, t, drone_id))
            t += time_step
            alt += alt_step

    return points


def generate_large_trajectories(points_per_traj=10000, rows=100):
    """
    生成两条大规模轨迹，预期交集约 5000 个

    轨迹1: 在区域A (中心偏西) 飞行
    轨迹2: 在区域B (中心偏东) 飞行，与区域A有约 50% 重叠
    """
    # 区域参数（北京附近）
    # 区域A: 中心 (116.30, 39.91), 宽 0.04度 (约 3.4km)
    # 区域B: 中心 (116.32, 39.91), 宽 0.04度
    # 两区域中心相距 0.02度，各有 0.02度半宽，重叠 0.02度 (约 75%)

    width = 0.04   # 约 3.4km
    height = 0.03  # 约 3km

    # 轨迹1: 在区域A飞行
    center_lon_1 = 116.300
    center_lat_1 = 39.910
    traj1 = generate_sawtooth_trajectory(
        center_lon_1, center_lat_1, width, height, rows, total_points=points_per_traj,
        direction=1, drone_id='UAV-ALPHA',
        start_alt=100, alt_step=0.005, time_step=1
    )

    # 轨迹2: 在区域B飞行（偏东，约 95% 重叠）
    center_lon_2 = 116.303
    center_lat_2 = 39.910
    traj2 = generate_sawtooth_trajectory(
        center_lon_2, center_lat_2, width, height, rows, total_points=points_per_traj,
        direction=-1, drone_id='UAV-BETA',
        start_alt=120, alt_step=0.005, time_step=1
    )

    # 确保每条轨迹正好有 points_per_traj 个点
    if len(traj1) > points_per_traj:
        traj1 = traj1[:points_per_traj]
    while len(traj1) < points_per_traj:
        traj1.append(traj1[-1])

    if len(traj2) > points_per_traj:
        traj2 = traj2[:points_per_traj]
    while len(traj2) < points_per_traj:
        traj2.append(traj2[-1])

    return traj1, traj2


def save_trajectory_csv(points, filepath):
    """保存轨迹点到 CSV 文件"""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('lon,lat,alt_m,time_s,drone_id\n')
        for lon, lat, alt, t, drone_id in points:
            f.write(f'{lon:.6f},{lat:.6f},{alt:.1f},{int(t)},{drone_id}\n')
    print(f'已保存: {filepath} ({len(points)} 个航点)')


def main():
    print('=' * 60)
    print('生成大规模无人机轨迹数据')
    print('=' * 60)

    traj1, traj2 = generate_large_trajectories(points_per_traj=10000, rows=100)

    path1 = os.path.join(DATA_DIR, 'uav_conflict_1.csv')
    path2 = os.path.join(DATA_DIR, 'uav_conflict_2.csv')

    save_trajectory_csv(traj1, path1)
    save_trajectory_csv(traj2, path2)

    print(f'\n轨迹1中心: (116.300, 39.910), 覆盖区域约 3.4km x 3km')
    print(f'轨迹2中心: (116.303, 39.910), 覆盖区域约 3.4km x 3km')
    print(f'两区域水平重叠约 3.7km (约 95%)')


if __name__ == '__main__':
    main()
