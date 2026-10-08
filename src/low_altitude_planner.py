# -*- coding: utf-8 -*-
"""
低空导航规划器
==============
整合起降场选址、空域容量、轨迹冲突检测三大能力，形成完整的低空导航规划闭环。

核心流程:
1. 选址 (uav_siting): 确定起降场位置
2. 容量 (airspace_capacity): 确定空域能飞多少架
3. 冲突检测 (trajectory_conflict): 确定航线是否安全

技术基础:
- GeoSOT 3D 网格编码: 统一的空间语言
- PSI 隐私集合交集: 多方协作的信任桥梁
- 时间窗机制: 动态调度的核心机制
"""
import math
from typing import List, Dict, Tuple, Optional
import geosot_core as gc
import uav_siting
from geofile import read_csv


# ============================================================================
# 1. 空域容量计算
# ============================================================================
def airspace_capacity(
    lower_polygon: List[Tuple[float, float]],
    upper_polygon: List[Tuple[float, float]],
    h_min: float,
    h_max: float,
    level: int,
    no_fly_zones: Optional[List[Dict]] = None,
    obstacles: Optional[List[Dict]] = None
) -> Dict:
    """计算空域容量：该空域最多能容纳多少架无人机。

    容量 = 可用网格数 / 单架无人机占用网格数
    其中单架无人机占用网格数 = 安全距离球体扩展后的网格数

    参数:
        lower_polygon: 下边界多边形 [(lng, lat), ...]
        upper_polygon: 上边界多边形 [(lng, lat), ...]
        h_min, h_max: 高度范围 (米)
        level: 网格层级
        no_fly_zones: 禁飞区列表 [{'polygon': [...], 'h_min': ..., 'h_max': ...}]
        obstacles: 障碍物列表 [{'center': (lng, lat, h), 'radius': ...}]

    返回:
        {
            'total_grids': int,           # 空域总网格数
            'available_grids': int,       # 可用网格数（扣除禁飞区/障碍物）
            'single_uav_grids': int,      # 单架无人机占用网格数
            'capacity': int,              # 最大容纳无人机数量
            'volume_km3': float,          # 空域总体积 (立方公里)
            'available_volume_km3': float # 可用体积 (立方公里)
        }
    """
    # 1. 计算空域总网格
    all_grids = gc.airspace_grids(lower_polygon, upper_polygon, h_min, h_max, level)
    total_grids = len(all_grids)

    if total_grids == 0:
        return {
            'total_grids': 0,
            'available_grids': 0,
            'single_uav_grids': 0,
            'capacity': 0,
            'volume_km3': 0.0,
            'available_volume_km3': 0.0
        }

    # 2. 扣除禁飞区
    available_grids_set = set(all_grids)

    if no_fly_zones:
        for zone in no_fly_zones:
            zone_grids = gc.airspace_grids(
                zone['polygon'], zone['polygon'],
                zone['h_min'], zone['h_max'], level
            )
            available_grids_set -= set(zone_grids)

    # 3. 扣除障碍物
    if obstacles:
        for obs in obstacles:
            lng, lat, h = obs['center']
            radius = obs['radius']
            obs_grids = gc.sphere3d(lat, lng, h, radius, level)
            available_grids_set -= set(obs_grids)

    available_grids = len(available_grids_set)

    # 4. 计算单架无人机占用网格数（默认安全距离 50m）
    # 假设无人机在空域中心飞行，计算球体扩展网格数
    center_lat = sum(p[1] for p in lower_polygon) / len(lower_polygon)
    center_lng = sum(p[0] for p in lower_polygon) / len(lower_polygon)
    center_h = (h_min + h_max) / 2
    safety_distance = 50.0  # 默认安全距离 50m

    single_uav_grids_set = set(gc.sphere3d(center_lat, center_lng, center_h, safety_distance, level))
    single_uav_grids = len(single_uav_grids_set)

    # 5. 计算容量
    capacity = available_grids // single_uav_grids if single_uav_grids > 0 else 0

    # 6. 计算体积
    ref_lat = center_lat
    vol_info = gc.airspace_available_volume(total_grids, level, ref_lat)
    avail_vol_info = gc.airspace_available_volume(available_grids, level, ref_lat)

    return {
        'total_grids': total_grids,
        'available_grids': available_grids,
        'single_uav_grids': single_uav_grids,
        'capacity': capacity,
        'volume_km3': vol_info['total_volume_km3'],
        'available_volume_km3': avail_vol_info['total_volume_km3']
    }


# ============================================================================
# 2. 轨迹冲突检测（带安全距离）
# ============================================================================
def expand_trajectory_to_spheres(
    csv_path: str,
    radius_m: float,
    height: float = 0,
    level: int = 21
) -> Dict:
    """将整条轨迹的所有点扩展为球体，返回去重后的占用网格集合。

    参数:
        csv_path: 轨迹 CSV 文件路径
        radius_m: 安全距离（米）
        height: 默认高度（米），若 CSV 无高度列则使用
        level: 网格层级

    返回:
        {
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
        sphere_codes = gc.sphere3d(lat, lng, h, radius_m, level)
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


def detect_trajectory_conflicts(
    traj1_data: Dict,
    traj2_data: Dict,
    use_psi: bool = True,
    psi_port: int = 12150,
    timeout: int = 60
) -> Dict:
    """检测两条轨迹的冲突网格。

    参数:
        traj1_data: expand_trajectory_to_spheres() 返回的字典
        traj2_data: expand_trajectory_to_spheres() 返回的字典
        use_psi: 是否使用 PSI（否则用明文交集）
        psi_port: PSI 端口号
        timeout: 超时秒数

    返回:
        {
            'conflict_codes': set,              # 冲突网格编码集合
            'traj1_conflict_points': list,      # 轨迹1中与冲突网格关联的坐标
            'traj2_conflict_points': list,      # 轨迹2中与冲突网格关联的坐标
        }
    """
    if use_psi:
        # 使用 PSI 求交
        from tests.uav_siting.psi_helpers import run_pairwise_psi
        result = run_pairwise_psi(
            traj1_data['codes'],
            traj2_data['codes'],
            port=psi_port,
            card_only=False,
            timeout=timeout
        )
        conflict_codes = result['intersection']
    else:
        # 明文交集
        conflict_codes = traj1_data['codes'] & traj2_data['codes']

    # 找到冲突网格对应的轨迹坐标
    traj1_points = set()
    traj2_points = set()

    for code in conflict_codes:
        if code in traj1_data['code_to_points']:
            for pt in traj1_data['code_to_points'][code]:
                traj1_points.add(pt)

        if code in traj2_data['code_to_points']:
            for pt in traj2_data['code_to_points'][code]:
                traj2_points.add(pt)

    return {
        'conflict_codes': conflict_codes,
        'traj1_conflict_points': sorted(traj1_points),
        'traj2_conflict_points': sorted(traj2_points),
    }


# ============================================================================
# 3. 低空导航规划器（编排层）
# ============================================================================
class LowAltitudePlanner:
    """低空导航规划器：整合选址、容量、冲突检测三大能力。"""

    def __init__(self, level: int = 21, safety_distance: float = 50.0):
        """
        参数:
            level: 网格层级（默认 21，约 30m 分辨率）
            safety_distance: 安全距离（米）
        """
        self.level = level
        self.safety_distance = safety_distance

        # 已注册的起降场
        self.sites: List[Dict] = []

        # 已批准的航线（轨迹数据）
        self.approved_routes: List[Dict] = []

        # 空域容量缓存
        self.capacity_cache: Dict[str, Dict] = {}

    def register_site(
        self,
        name: str,
        lower_polygon: List[Tuple[float, float]],
        upper_polygon: List[Tuple[float, float]],
        h_min: float,
        h_max: float,
        time_window: Tuple[int, int] = (0, 10),
        candidates: Optional[List[Dict]] = None
    ) -> Dict:
        """注册起降场：登记空域范围和参数。

        轻量级注册，不执行选址算法。如需执行完整选址流程，
        请调用 run_siting() 方法。

        参数:
            name: 起降场名称
            lower_polygon, upper_polygon: 空域边界 [(lng, lat), ...]
            h_min, h_max: 高度范围 (米)
            time_window: 时间窗口 (start, end)
            candidates: 已知的候选起降场坐标列表（可选）

        返回:
            注册的起降场信息
        """
        site_info = {
            'name': name,
            'candidates': candidates or [],
            'lower_polygon': lower_polygon,
            'upper_polygon': upper_polygon,
            'h_min': h_min,
            'h_max': h_max,
            'time_window': time_window
        }
        self.sites.append(site_info)
        return site_info

    def run_siting(
        self,
        site_name: str,
        risk_factors: Optional[Dict] = None,
        weights: Optional[Dict] = None,
        R_threshold: float = 0.6,
        eps: float = 200.0,
        min_samples: int = 3,
        A_threshold: float = 0.3,
        buffer_grids: int = 0,
        mask_provider: Optional[callable] = None
    ) -> Dict:
        """对已注册的起降场执行完整选址算法。

        调用 uav_siting.uav_siting() 执行完整的选址流程:
        1. 构建时空网格
        2. 硬约束过滤
        3. 软约束风险评分
        4. DBSCAN 聚类
        5. 时间窗口可用性检查

        参数:
            site_name: 已注册的起降场名称
            risk_factors: 风险因子 {name: {code: value}}
            weights: 权重 {name: weight}, 和为 1
            R_threshold: 风险阈值
            eps: DBSCAN 邻域半径 (米)
            min_samples: DBSCAN 最小样本数
            A_threshold: 时间窗口可用性阈值
            buffer_grids: 安全缓冲网格数
            mask_provider: 掩码提供函数

        返回:
            选址结果
        """
        site = next((s for s in self.sites if s['name'] == site_name), None)
        if not site:
            raise ValueError(f"起降场 '{site_name}' 未注册")

        if risk_factors is None:
            risk_factors = {}
        if weights is None:
            weights = {'land_use': 1.0}

        result = uav_siting.uav_siting(
            site['lower_polygon'], site['upper_polygon'],
            site['h_min'], site['h_max'], self.level,
            site['time_window'][0], site['time_window'][1], 1,
            risk_factors, weights,
            R_threshold=R_threshold,
            eps=eps,
            min_samples=min_samples,
            A_threshold=A_threshold,
            buffer_grids=buffer_grids,
            mask_provider=mask_provider
        )

        # 更新起降场的候选位置
        site['candidates'] = result['candidates']

        return result

    def check_capacity(
        self,
        site_name: str,
        no_fly_zones: Optional[List[Dict]] = None,
        obstacles: Optional[List[Dict]] = None
    ) -> Dict:
        """检查起降场周边空域的容量。

        参数:
            site_name: 起降场名称
            no_fly_zones: 禁飞区列表
            obstacles: 障碍物列表

        返回:
            容量信息
        """
        # 查找起降场
        site = next((s for s in self.sites if s['name'] == site_name), None)
        if not site:
            raise ValueError(f"起降场 '{site_name}' 未注册")

        # 计算容量
        capacity = airspace_capacity(
            site['lower_polygon'], site['upper_polygon'],
            site['h_min'], site['h_max'], self.level,
            no_fly_zones, obstacles
        )

        # 缓存
        self.capacity_cache[site_name] = capacity

        return capacity

    def validate_route(
        self,
        route_csv: str,
        use_psi: bool = True,
        psi_port: int = 12160
    ) -> Dict:
        """验证新航线是否与已有航线冲突。

        参数:
            route_csv: 新航线轨迹 CSV 文件路径
            use_psi: 是否使用 PSI
            psi_port: PSI 端口

        返回:
            {
                'approved': bool,           # 是否批准
                'conflicts': dict,          # 冲突详情
                'conflict_count': int,      # 冲突网格数
                'suggestion': str           # 建议
            }
        """
        # 扩展新航线
        new_route_data = expand_trajectory_to_spheres(
            route_csv, self.safety_distance, height=100.0, level=self.level
        )

        # 与所有已批准航线检测冲突
        all_conflicts = []
        for idx, approved in enumerate(self.approved_routes):
            conflict_result = detect_trajectory_conflicts(
                new_route_data, approved['data'],
                use_psi=use_psi, psi_port=psi_port + idx
            )
            if conflict_result['conflict_codes']:
                all_conflicts.append({
                    'route_index': idx,
                    'conflict': conflict_result
                })

        # 汇总
        total_conflicts = sum(len(c['conflict']['conflict_codes']) for c in all_conflicts)

        if total_conflicts == 0:
            return {
                'approved': True,
                'conflicts': [],
                'conflict_count': 0,
                'suggestion': '航线安全，可以批准飞行'
            }
        else:
            return {
                'approved': False,
                'conflicts': all_conflicts,
                'conflict_count': total_conflicts,
                'suggestion': f'检测到 {total_conflicts} 个冲突网格，建议改航或调整时间窗口'
            }

    def approve_route(self, route_csv: str, route_name: str = None):
        """批准并注册新航线。

        参数:
            route_csv: 轨迹 CSV 文件路径
            route_name: 航线名称
        """
        route_data = expand_trajectory_to_spheres(
            route_csv, self.safety_distance, height=100.0, level=self.level
        )

        self.approved_routes.append({
            'name': route_name or f"Route-{len(self.approved_routes)}",
            'csv': route_csv,
            'data': route_data
        })

    def plan_flight(
        self,
        origin_site: str,
        dest_site: str,
        route_csv: str,
        time_window: Tuple[int, int] = (0, 10),
        no_fly_zones: Optional[List[Dict]] = None,
        obstacles: Optional[List[Dict]] = None,
        use_psi: bool = True
    ) -> Dict:
        """端到端飞行规划：选址 → 容量 → 冲突检测。

        参数:
            origin_site: 起飞场名称
            dest_site: 降落场名称
            route_csv: 候选航线 CSV
            time_window: 时间窗口
            no_fly_zones: 禁飞区
            obstacles: 障碍物
            use_psi: 是否使用 PSI

        返回:
            {
                'approved': bool,
                'origin_capacity': dict,
                'dest_capacity': dict,
                'route_validation': dict,
                'summary': str
            }
        """
        # 1. 检查起降场容量
        origin_cap = self.check_capacity(origin_site, no_fly_zones, obstacles)
        dest_cap = self.check_capacity(dest_site, no_fly_zones, obstacles)

        # 2. 容量校验
        if origin_cap['capacity'] <= 0:
            return {
                'approved': False,
                'origin_capacity': origin_cap,
                'dest_capacity': dest_cap,
                'route_validation': None,
                'summary': f'起飞场 {origin_site} 空域容量不足'
            }

        if dest_cap['capacity'] <= 0:
            return {
                'approved': False,
                'origin_capacity': origin_cap,
                'dest_capacity': dest_cap,
                'route_validation': None,
                'summary': f'降落场 {dest_site} 空域容量不足'
            }

        # 3. 航线冲突检测
        validation = self.validate_route(route_csv, use_psi=use_psi)

        # 4. 汇总
        if validation['approved']:
            summary = (
                f"飞行计划批准: "
                f"起飞场容量 {origin_cap['capacity']} 架, "
                f"降落场容量 {dest_cap['capacity']} 架, "
                f"航线无冲突"
            )
        else:
            summary = (
                f"飞行计划拒绝: "
                f"检测到 {validation['conflict_count']} 个冲突网格, "
                f"建议改航或调整时间窗口"
            )

        return {
            'approved': validation['approved'],
            'origin_capacity': origin_cap,
            'dest_capacity': dest_cap,
            'route_validation': validation,
            'summary': summary
        }
