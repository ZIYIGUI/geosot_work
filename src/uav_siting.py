# -*- coding: utf-8 -*-
"""
基于网格的无人机起降场选址算法
==============================
实现论文《基于网格的无人机选址算法》中的完整流程：
1. 构建时空网格 (DQG-4D, 用 GeoSOT 3D + 时间步替代)
2. 8位掩码硬约束过滤 (一票否决)
3. 软约束风险评分 (加权求和)
4. DBSCAN 聚类 + 风险加权质心
5. 时间窗口可用性检查
6. 输出候选起降场

公式对应：
- 公式1: DQG-4D 编码 (我们用 geo_num3d + time_step)
- 公式2: h(g,t) = mask(g,t) & HARD_MASK, filter = (h != 0)
- 公式3: R(g) = Σ w_i(s) * f_i(g), 保留 R(g) < R_threshold
- 公式4: c_k = Σ(w_g * p_g) / (Σ(w_g) + ε), w_g = 1 - R(g)
- 公式5: A(c) = (1/|W|) * Σ I(hard_pass ∧ soft_pass)
"""
import math
import numpy as np
from collections import defaultdict
from typing import List, Dict, Tuple, Optional

import geosot_core as gc


# ============================================================================
# 1. 网格掩码系统 (8位状态掩码)
# ============================================================================
class GridMask:
    """8位网格状态掩码定义

    位定义 (从低到高):
        b0: 禁飞区标记
        b1: 净空障碍物冲突标记
        b2: 强电磁干扰标记
        b3: 恶劣气象标记
        b4: 临时空管管控标记
        b5: 飞行流量超限标记
        b6: 场景类型标签 (城市/郊区, 不参与硬约束)
        b7: 预留扩展位 (不参与硬约束)

    硬约束掩码: HARD_MASK = 0b00111111 (b0~b5)
    只有 b0~b5 中任一位为 1 时, 该网格被一票否决剔除。
    """
    # 各位定义
    NO_FLY          = 0b00000001  # b0: 禁飞区
    OBSTACLE        = 0b00000010  # b1: 障碍物冲突
    EM_INTERFERENCE = 0b00000100  # b2: 电磁干扰
    WEATHER         = 0b00001000  # b3: 恶劣气象
    ATC_CONTROL     = 0b00010000  # b4: 临时空管
    OVERLOAD        = 0b00100000  # b5: 流量超限
    SCENE_LABEL     = 0b01000000  # b6: 场景标签
    RESERVED        = 0b10000000  # b7: 预留扩展

    # 硬约束掩码: b0~b5 参与一票否决
    HARD_MASK = 0b00111111

    @staticmethod
    def check_hard_constraint(mask_value: int) -> bool:
        """检查网格是否通过硬约束过滤

        按位与运算: h = mask & HARD_MASK
        - h != 0: 存在致命硬约束, 网格被剔除 (返回 False)
        - h == 0: 全部硬约束通过, 网格保留 (返回 True)

        Args:
            mask_value: 8位掩码值

        Returns:
            True: 通过硬约束, 保留; False: 未通过, 剔除
        """
        return (mask_value & GridMask.HARD_MASK) == 0

    @staticmethod
    def describe_mask(mask_value: int) -> List[str]:
        """描述掩码中置位的项"""
        labels = []
        if mask_value & GridMask.NO_FLY:
            labels.append("禁飞区")
        if mask_value & GridMask.OBSTACLE:
            labels.append("障碍物")
        if mask_value & GridMask.EM_INTERFERENCE:
            labels.append("电磁干扰")
        if mask_value & GridMask.WEATHER:
            labels.append("恶劣气象")
        if mask_value & GridMask.ATC_CONTROL:
            labels.append("临时空管")
        if mask_value & GridMask.OVERLOAD:
            labels.append("流量超限")
        if mask_value & GridMask.SCENE_LABEL:
            labels.append("城市场景")
        return labels


# ============================================================================
# 2. 时空网格构建 (公式1: DQG-4D 编码)
# ============================================================================
def build_spatiotemporal_grids(
    lower_polygon: List[Tuple[float, float]],
    upper_polygon: List[Tuple[float, float]],
    h_min: float,
    h_max: float,
    level: int,
    time_start: int,
    time_end: int,
    dt: int = 1,
    mask_provider: Optional[callable] = None
) -> List[dict]:
    """构建带掩码的 4D 时空网格集合

    对应公式1: DQG-4D 位交错编码
    我们用 GeoSOT 3D 编码 (geo_num3d) 作为空间索引, 时间步单独处理。

    Args:
        lower_polygon: 下边界多边形 [(lng, lat), ...]
        upper_polygon: 上边界多边形 [(lng, lat), ...]
        h_min, h_max: 高度范围 (米)
        level: 网格层级
        time_start: 起始时间步
        time_end: 结束时间步 (不含)
        dt: 时间步长 (默认1)
        mask_provider: 掩码提供函数 f(code, time_step) -> mask_value
            若为 None, 则所有网格掩码为 0 (全部通过)

    Returns:
        List of dict, 每个包含:
        {
            'code': int,          # GeoSOT 3D 编码
            'time_step': int,     # 时间步
            'mask': int,          # 8位掩码
            'lat': float,         # 网格中心纬度
            'lng': float,         # 网格中心经度
            'h': float,           # 网格中心高度
            'level': int          # 网格层级
        }
    """
    # 生成空间网格 (使用 airspace_grids)
    spatial_codes = gc.airspace_grids(
        lower_polygon, upper_polygon, h_min, h_max, level
    )

    # 为每个空间网格计算中心点坐标
    code_centers = {}
    cd = gc.cell_deg(level)
    hc = gc.height_cell(level)

    for code in spatial_codes:
        try:
            # center_point3d 返回 [lng, lat, height]
            lng, lat, h = gc.center_point3d(code, level)
            code_centers[code] = (lat, lng, h)
        except:
            # 如果 center_point3d 不可用, 尝试手动计算
            # 简化处理: 使用多边形中心作为近似
            lat = sum(p[1] for p in lower_polygon) / len(lower_polygon)
            lng = sum(p[0] for p in lower_polygon) / len(lower_polygon)
            h = (h_min + h_max) / 2
            code_centers[code] = (lat, lng, h)

    # 构建时空网格
    spatiotemporal_grids = []
    for code in spatial_codes:
        lat, lng, h = code_centers[code]
        for t in range(time_start, time_end, dt):
            mask = mask_provider(code, t) if mask_provider else 0
            spatiotemporal_grids.append({
                'code': code,
                'time_step': t,
                'mask': mask,
                'lat': lat,
                'lng': lng,
                'h': h,
                'level': level
            })

    return spatiotemporal_grids


# ============================================================================
# 3. 硬约束过滤 (公式2)
# ============================================================================
def hard_constraint_filter(
    grids: List[dict],
    global_mask: int = GridMask.HARD_MASK
) -> List[dict]:
    """硬约束过滤 (一票否决)

    对应公式2: h(g,t) = mask(g,t) & HARD_MASK
    - 若 h(g,t) != 0: 存在致命硬约束, 剔除该网格
    - 若 h(g,t) == 0: 全部硬约束通过, 保留

    Args:
        grids: 时空网格列表
        global_mask: 全局硬约束掩码 (默认 0b00111111)

    Returns:
        过滤后的幸存网格列表
    """
    surviving = []
    for grid in grids:
        h = grid['mask'] & global_mask
        if h == 0:
            surviving.append(grid)
    return surviving


# ============================================================================
# 4. 软约束风险评分 (公式3)
# ============================================================================
def compute_risk_scores(
    grids: List[dict],
    risk_factors: Dict[str, Dict[int, float]],
    weights: Dict[str, float],
    scene: str = 'urban'
) -> Dict[int, float]:
    """计算软约束风险评分

    对应公式3: R(g) = Σ w_i(s) * f_i(g)

    Args:
        grids: 网格列表 (已过滤硬约束)
        risk_factors: 风险因子字典
            {factor_name: {grid_code: normalized_value}}
            normalized_value ∈ [0, 1], 越大风险越高
        weights: 权重字典 {factor_name: weight}
            所有权重之和应等于 1
        scene: 场景类型 ('urban' / 'suburban')

    Returns:
        {grid_code: risk_score}
    """
    # 验证权重和为1
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > 1e-6:
        raise ValueError(f"权重之和必须为1, 当前为 {total_weight}")

    # 收集所有唯一的网格编码
    unique_codes = set(grid['code'] for grid in grids)

    # 计算每个网格的风险评分
    risk_scores = {}
    for code in unique_codes:
        score = 0.0
        for factor_name, weight in weights.items():
            if factor_name in risk_factors and code in risk_factors[factor_name]:
                f_i = risk_factors[factor_name][code]
                # 确保因子值在 [0, 1] 范围内
                f_i = max(0.0, min(1.0, f_i))
                score += weight * f_i
        risk_scores[code] = score

    return risk_scores


def filter_by_risk_threshold(
    grids: List[dict],
    risk_scores: Dict[int, float],
    R_threshold: float = 0.5
) -> List[dict]:
    """按风险阈值过滤网格

    只保留 R(g) < R_threshold 的网格, 用于后续聚类。

    Args:
        grids: 网格列表
        risk_scores: 风险评分字典
        R_threshold: 风险阈值

    Returns:
        过滤后的网格列表
    """
    return [
        grid for grid in grids
        if risk_scores.get(grid['code'], 1.0) < R_threshold
    ]


# ============================================================================
# 5. DBSCAN 聚类 + 风险加权质心 (公式4)
# ============================================================================
def cluster_and_centroids(
    grids: List[dict],
    risk_scores: Dict[int, float],
    eps: float = 50.0,
    min_samples: int = 5,
    epsilon: float = 1e-8
) -> List[dict]:
    """DBSCAN 聚类 + 风险加权质心计算

    对应公式4: c_k = Σ(w_g * p_g) / (Σ(w_g) + ε)
    其中 w_g = 1 - R(g), 风险越低权重越高

    Args:
        grids: 幸存网格列表 (已过滤硬约束 + 风险阈值)
        risk_scores: 风险评分字典
        eps: DBSCAN 邻域半径 (米)
        min_samples: DBSCAN 最小样本数
        epsilon: 分母防零常数

    Returns:
        候选起降场列表:
        [
            {
                'cluster_id': int,
                'lng': float,
                'lat': float,
                'h': float,
                'grid_count': int,
                'avg_risk': float
            },
            ...
        ]
    """
    if not grids:
        return []

    # 提取网格中心坐标 (经纬度高度)
    coords = np.array([
        [grid['lng'], grid['lat'], grid['h']]
        for grid in grids
    ])

    # DBSCAN 聚类
    try:
        from sklearn.cluster import DBSCAN
        clustering = DBSCAN(eps=eps, min_samples=min_samples).fit(coords)
        labels = clustering.labels_
    except ImportError:
        # 如果 sklearn 不可用, 使用简化版聚类
        # 这里实现一个简单的基于距离的聚类
        labels = _simple_cluster(coords, eps, min_samples)

    # 计算每个聚类的风险加权质心
    unique_labels = set(labels)
    unique_labels.discard(-1)  # 排除噪声点

    centroids = []
    for cluster_id in unique_labels:
        # 获取该聚类内的网格
        cluster_grids = [
            grids[i] for i, label in enumerate(labels)
            if label == cluster_id
        ]

        # 计算风险加权质心 (公式4)
        # c_k = Σ(w_g * p_g) / (Σ(w_g) + ε)
        # w_g = 1 - R(g)
        weighted_sum = np.zeros(3)
        weight_total = 0.0
        risk_sum = 0.0

        for grid in cluster_grids:
            code = grid['code']
            r_g = risk_scores.get(code, 0.5)
            w_g = 1.0 - r_g  # 风险越低, 权重越高

            p_g = np.array([grid['lng'], grid['lat'], grid['h']])
            weighted_sum += w_g * p_g
            weight_total += w_g
            risk_sum += r_g

        # 计算质心
        centroid = weighted_sum / (weight_total + epsilon)

        centroids.append({
            'cluster_id': cluster_id,
            'lng': centroid[0],
            'lat': centroid[1],
            'h': centroid[2],
            'grid_count': len(cluster_grids),
            'avg_risk': risk_sum / len(cluster_grids) if cluster_grids else 0.0
        })

    return centroids


def _simple_cluster(coords: np.ndarray, eps: float, min_samples: int) -> np.ndarray:
    """简化版 DBSCAN 聚类 (sklearn 不可用时的备选)

    基于距离的聚类: 两个点距离小于 eps 则属于同一聚类。
    """
    n = len(coords)
    labels = np.full(n, -1, dtype=int)
    cluster_id = 0

    for i in range(n):
        if labels[i] != -1:
            continue

        # 查找 i 的邻域
        neighbors = []
        for j in range(n):
            dist = np.linalg.norm(coords[i] - coords[j])
            if dist <= eps:
                neighbors.append(j)

        if len(neighbors) < min_samples:
            continue

        # 扩展聚类
        labels[i] = cluster_id
        queue = [j for j in neighbors if j != i]

        while queue:
            point = queue.pop(0)
            if labels[point] != -1:
                continue

            labels[point] = cluster_id

            # 查找 point 的邻域
            point_neighbors = []
            for j in range(n):
                dist = np.linalg.norm(coords[point] - coords[j])
                if dist <= eps:
                    point_neighbors.append(j)

            if len(point_neighbors) >= min_samples:
                queue.extend([j for j in point_neighbors if labels[j] == -1])

        cluster_id += 1

    return labels


# ============================================================================
# 6. 时间窗口可用性 (公式5)
# ============================================================================
def time_window_availability(
    centroids: List[dict],
    spatiotemporal_grids: List[dict],
    risk_scores: Dict[int, float],
    R_threshold: float,
    time_window: Tuple[int, int],
    A_threshold: float = 0.8,
    buffer_grids: int = 1
) -> List[dict]:
    """时间窗口可用性检查

    对应公式5: A(c) = (1/|W|) * Σ I(hard_pass ∧ soft_pass)

    对于每个候选起降场, 检查其在时间窗口内的可用性:
    - 在每个时间步, 检查候选点及其安全缓冲网格是否全部通过硬约束
    - 同时检查软约束风险是否满足阈值
    - 计算可用性占比 A(c)
    - 只保留 A(c) >= A_threshold 的候选点

    Args:
        centroids: 候选起降场列表
        spatiotemporal_grids: 完整的时空网格集合 (含所有时间步)
        risk_scores: 风险评分字典
        R_threshold: 风险阈值
        time_window: (start, end) 时间窗口范围
        A_threshold: 可用性阈值
        buffer_grids: 安全缓冲网格数 (默认1, 即检查周围1圈网格)

    Returns:
        通过时间窗口检查的候选起降场列表
    """
    # 构建时空网格索引: {(code, time_step): grid}
    grid_index = {
        (g['code'], g['time_step']): g
        for g in spatiotemporal_grids
    }

    # 构建每个候选点的空间网格集合 (用于查找缓冲网格)
    # 简化处理: 使用候选点最近的网格及其邻域
    qualified_centroids = []

    for centroid in centroids:
        # 查找最近的网格编码
        nearest_code = _find_nearest_code(
            centroid['lng'], centroid['lat'], centroid['h'],
            spatiotemporal_grids
        )

        if nearest_code is None:
            continue

        # 获取该网格的邻域 (安全缓冲)
        buffer_codes = _get_buffer_codes(
            nearest_code, centroid['lat'], centroid['lng'],
            buffer_grids, spatiotemporal_grids[0]['level'] if spatiotemporal_grids else 21
        )

        # 计算时间窗口内的可用性
        time_steps = range(time_window[0], time_window[1])
        total_steps = len(time_steps)
        available_steps = 0

        for t in time_steps:
            # 检查条件1: 候选点及其缓冲网格全部硬约束通过
            hard_pass = True
            for code in buffer_codes:
                key = (code, t)
                if key in grid_index:
                    grid = grid_index[key]
                    if not GridMask.check_hard_constraint(grid['mask']):
                        hard_pass = False
                        break

            # 检查条件2: 软约束风险满足阈值
            soft_pass = True
            for code in buffer_codes:
                if code in risk_scores:
                    if risk_scores[code] >= R_threshold:
                        soft_pass = False
                        break

            # 两个条件必须同时成立
            if hard_pass and soft_pass:
                available_steps += 1

        # 计算可用性占比
        A_c = available_steps / total_steps if total_steps > 0 else 0.0

        # 只保留满足阈值的候选点
        if A_c >= A_threshold:
            centroid_copy = centroid.copy()
            centroid_copy['availability'] = A_c
            qualified_centroids.append(centroid_copy)

    return qualified_centroids


def _find_nearest_code(lng: float, lat: float, h: float,
                       grids: List[dict]) -> Optional[int]:
    """查找距离给定点最近的网格编码"""
    min_dist = float('inf')
    nearest_code = None

    # 只检查第一个时间步的网格 (空间位置相同)
    seen_codes = set()
    for grid in grids:
        if grid['code'] in seen_codes:
            continue
        seen_codes.add(grid['code'])

        dist = math.sqrt(
            (grid['lng'] - lng) ** 2 +
            (grid['lat'] - lat) ** 2 +
            (grid['h'] - h) ** 2
        )
        if dist < min_dist:
            min_dist = dist
            nearest_code = grid['code']

    return nearest_code


def _get_buffer_codes(code: int, lat: float, lng: float,
                      buffer_size: int, level: int) -> List[int]:
    """获取网格的安全缓冲邻域编码

    返回 code 本身及其周围 buffer_size 圈的网格编码。
    """
    buffer_codes = [code]

    if buffer_size <= 0:
        return buffer_codes

    # 使用 26 邻域 (3D) 获取缓冲网格
    try:
        adjoins = gc.adjoin26_geo_num(code, level)
        buffer_codes.extend(adjoins)

        # 如果需要更大的缓冲范围, 递归获取
        for _ in range(buffer_size - 1):
            new_adjoins = []
            for adj_code in adjoins:
                try:
                    new_adjoins.extend(gc.adjoin26_geo_num(adj_code, level))
                except:
                    pass
            buffer_codes.extend(new_adjoins)
            adjoins = new_adjoins
    except:
        # 如果邻域函数不可用, 只返回中心网格
        pass

    # 去重
    return list(set(buffer_codes))


# ============================================================================
# 7. 主流程
# ============================================================================
def uav_siting(
    lower_polygon: List[Tuple[float, float]],
    upper_polygon: List[Tuple[float, float]],
    h_min: float,
    h_max: float,
    level: int,
    time_start: int,
    time_end: int,
    dt: int,
    risk_factors: Dict[str, Dict[int, float]],
    weights: Dict[str, float],
    R_threshold: float = 0.5,
    eps: float = 50.0,
    min_samples: int = 5,
    A_threshold: float = 0.8,
    buffer_grids: int = 1,
    mask_provider: Optional[callable] = None,
    scene: str = 'urban'
) -> Dict:
    """端到端无人机起降场选址流程

    完整实现论文中的算法流程:
    1. 构建时空网格 (公式1)
    2. 硬约束过滤 (公式2)
    3. 软约束风险评分 (公式3)
    4. 按风险阈值过滤
    5. DBSCAN 聚类 + 风险加权质心 (公式4)
    6. 时间窗口可用性检查 (公式5)
    7. 输出候选起降场

    Args:
        lower_polygon: 下边界多边形 [(lng, lat), ...]
        upper_polygon: 上边界多边形 [(lng, lat), ...]
        h_min, h_max: 高度范围 (米)
        level: 网格层级
        time_start, time_end, dt: 时间步参数
        risk_factors: 风险因子 {name: {code: value}}
        weights: 权重 {name: weight}, 和为1
        R_threshold: 风险阈值
        eps: DBSCAN 邻域半径 (米)
        min_samples: DBSCAN 最小样本数
        A_threshold: 时间窗口可用性阈值
        buffer_grids: 安全缓冲网格数
        mask_provider: 掩码提供函数 f(code, time_step) -> mask
        scene: 场景类型

    Returns:
        {
            'total_grids': int,           # 总时空网格数
            'surviving_grids': int,       # 硬约束过滤后幸存数
            'risk_filtered_grids': int,   # 风险阈值过滤后数
            'num_clusters': int,          # 聚类数
            'candidates': List[dict],     # 最终候选起降场
            'details': dict               # 中间过程详情
        }
    """
    # 步骤1: 构建时空网格
    print(f"[1/6] 构建时空网格...")
    spatiotemporal_grids = build_spatiotemporal_grids(
        lower_polygon, upper_polygon, h_min, h_max, level,
        time_start, time_end, dt, mask_provider
    )
    total_grids = len(spatiotemporal_grids)
    print(f"    总时空网格数: {total_grids:,}")

    # 步骤2: 硬约束过滤
    print(f"[2/6] 硬约束过滤...")
    surviving_grids = hard_constraint_filter(spatiotemporal_grids)
    print(f"    幸存网格数: {len(surviving_grids):,}")
    print(f"    过滤率: {(1 - len(surviving_grids)/total_grids)*100:.1f}%")

    # 步骤3: 软约束风险评分
    print(f"[3/6] 计算风险评分...")
    risk_scores = compute_risk_scores(
        surviving_grids, risk_factors, weights, scene
    )
    avg_risk = sum(risk_scores.values()) / len(risk_scores) if risk_scores else 0
    print(f"    平均风险评分: {avg_risk:.3f}")

    # 步骤4: 按风险阈值过滤
    print(f"[4/6] 风险阈值过滤 (R < {R_threshold})...")
    risk_filtered = filter_by_risk_threshold(
        surviving_grids, risk_scores, R_threshold
    )
    print(f"    过滤后网格数: {len(risk_filtered):,}")

    # 步骤5: DBSCAN 聚类 + 风险加权质心
    print(f"[5/6] DBSCAN 聚类 (eps={eps}m, min_samples={min_samples})...")
    centroids = cluster_and_centroids(
        risk_filtered, risk_scores, eps, min_samples
    )
    print(f"    聚类数: {len(centroids)}")

    # 步骤6: 时间窗口可用性检查
    print(f"[6/6] 时间窗口可用性检查 (A >= {A_threshold})...")
    qualified = time_window_availability(
        centroids, surviving_grids, risk_scores, R_threshold,
        (time_start, time_end), A_threshold, buffer_grids
    )
    print(f"    通过检查的候选起降场: {len(qualified)}")

    return {
        'total_grids': total_grids,
        'surviving_grids': len(surviving_grids),
        'risk_filtered_grids': len(risk_filtered),
        'num_clusters': len(centroids),
        'candidates': qualified,
        'details': {
            'risk_scores': risk_scores,
            'all_centroids': centroids,
            'surviving_grids_list': surviving_grids,
            'spatiotemporal_grids': spatiotemporal_grids
        }
    }
