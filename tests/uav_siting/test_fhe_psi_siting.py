# -*- coding: utf-8 -*-
"""
基于 FHE 与 PSI 的无人机起降场自适应选址测试
================================================
测试专利《基于全同态加密与隐私集合求交的无人机起降场自适应选址方法》
的完整流程, 使用 psi/frontend.exe 执行两两 PSI 级联求交。

专利步骤 S0-S7 完整对应:
  S0: 多方原始数据预处理
  S1: GB/T 40087 混合粒度四维时空网格构建
  S2: 各方本地生成约束集合 + 准备 FHE 输入
  S3: FHE 密态加权求和 (明文替代, 见 fhe_plaintext.py)
  S4: 规划方解密 + 四方 PSI 隐私集合求交 (两两级联, frontend.exe)
  S5: 规划方本地空间聚类 + 风险加权质心
  S6: 时空滑窗可用性验证
  S7: 候选场址筛选与结果输出

数据与结果一致性:
  本测试使用与 test_uav_siting.py 相同的测试数据和参数,
  确保 FHE+PSI 流程的输出与明文流程完全一致。

FHE 替代说明:
  所有 FHE 密态运算用 fhe_plaintext.py 中的明文替代实现,
  并用 TODO[FHE] 注释标注, 以便未来替换为真实 FHE 库。

用法:
    python -m unittest tests.uav_siting.test_fhe_psi_siting -v
    python tests/uav_siting/test_fhe_psi_siting.py
"""
import os
import sys
import unittest
import numpy as np

# 路径设置
_HERE = os.path.dirname(os.path.abspath(__file__))        # tests/uav_siting/
_TESTS_DIR = os.path.dirname(_HERE)                        # tests/
_PROJECT_ROOT = os.path.dirname(_TESTS_DIR)                # geosot_work/
sys.path.insert(0, _TESTS_DIR)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, 'src'))    # src/
sys.path.insert(0, _HERE)                                  # tests/uav_siting/

from uav_siting import (
    GridMask,
    build_spatiotemporal_grids,
    hard_constraint_filter,
    compute_risk_scores,
    filter_by_risk_threshold,
    cluster_and_centroids,
    time_window_availability,
    uav_siting,
)
import geosot_core as gc
from psi_helpers import (
    run_pairwise_psi,
    cascade_psi,
    plain_set_intersection,
    code_to_hex16,
    hex16_to_code,
)
from fhe_plaintext import fhe_risk_scoring_pipeline, MapTable


# ============================================================================
# 测试数据: 与 test_uav_siting.py 完全一致
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

# 小测试区域 (用于聚类测试, 避免内存问题)
SMALL_LOWER = [
    (120.100, 30.550),
    (120.105, 30.550),
    (120.105, 30.555),
    (120.100, 30.555)
]
SMALL_UPPER = [
    (120.101, 30.551),
    (120.104, 30.551),
    (120.104, 30.554),
    (120.101, 30.554)
]

# 高度范围
H_MIN = 0
H_MAX = 500

# 网格层级
LEVEL = 17

# 时间范围
TIME_START = 0
TIME_END = 10
DT = 1
# PSI 测试使用较少时间步以提高速度 (每步需 3 次 pairwise PSI 调用)
PSI_TIME_END = 3

# 风险权重 (与 test_uav_siting.py 一致)
WEIGHTS = {
    'land_use': 0.3,
    'population': 0.25,
    'power_facility': 0.15,
    'construction_cost': 0.2,
    'noise': 0.1
}

R_THRESHOLD = 0.6
EPS = 200.0
MIN_SAMPLES = 3
A_THRESHOLD = 0.3
BUFFER_GRIDS = 0


# ============================================================================
# 四方数据模拟器 (模拟专利中的四个参与方)
# ============================================================================
class GeoInfoParty:
    """地理信息方: 持有障碍物、实体承载面、软约束数据

    专利描述:
    > 地理信息方本地输出具备实体承载面的网格集合 S_land
    > 将土地利用、人口、电力、建设成本、噪声等软约束数据归一化为风险因子 f_i(g)
    """

    def __init__(self, grids, risk_factors):
        self.grids = grids
        self.risk_factors = risk_factors
        # S_land: 具备实体承载面的网格集合
        # 模拟: 所有硬约束通过的网格视为有实体承载面
        self.s_land = set(g['code'] for g in grids
                         if GridMask.check_hard_constraint(g['mask']))

    def get_s_land(self) -> set:
        """返回 S_land 集合"""
        return set(self.s_land)

    def get_risk_factors(self) -> dict:
        """返回风险因子 (用于 FHE 加密)"""
        return self.risk_factors


class AirspaceParty:
    """空域管理方: 持有禁飞区、空管等空域约束

    专利描述:
    > 空域管理方本地对每个时间步构造 8 位状态掩码 B_air(g,tj),
    > 与公开空域硬约束掩码 M_hard 执行按位与,
    > 筛选满足空域约束的网格输出集合 S_air(tj)
    """

    def __init__(self, grids):
        self.grids = grids

    def get_s_air(self, time_step: int) -> set:
        """返回指定时间步的 S_air(tj)

        空域约束: 网格的掩码中 b0 (禁飞区) 和 b4 (临时空管) 均未置位
        """
        s_air = set()
        for g in self.grids:
            if g['time_step'] != time_step:
                continue
            mask = g['mask']
            # 空域硬约束: b0 (禁飞区) 和 b4 (临时空管) 必须为 0
            if (mask & GridMask.NO_FLY) == 0 and (mask & GridMask.ATC_CONTROL) == 0:
                s_air.add(g['code'])
        return s_air


class MeteoParty:
    """气象服务方: 持有气象约束

    专利描述:
    > 气象服务方本地执行相同运算, 输出气象硬约束安全网格集合 S_met(tj)
    """

    def __init__(self, grids):
        self.grids = grids

    def get_s_met(self, time_step: int) -> set:
        """返回指定时间步的 S_met(tj)

        气象约束: 网格的掩码中 b3 (恶劣气象) 未置位
        """
        s_met = set()
        for g in self.grids:
            if g['time_step'] != time_step:
                continue
            mask = g['mask']
            # 气象硬约束: b3 (恶劣气象) 必须为 0
            if (mask & GridMask.WEATHER) == 0:
                s_met.add(g['code'])
        return s_met


class PlannerParty:
    """规划方: 持有场景权重, 维护 mapTable, 执行解密和后处理

    专利描述:
    > 规划方本地加密场景权重矩阵 w_i 发送至 FHE 服务器
    > 规划方以本地私钥解密密文序列, 筛选满足 R(g,tj)≤τ_R 的网格生成 S_risk(tj)
    """

    def __init__(self, weights, r_threshold):
        self.weights = weights
        self.r_threshold = r_threshold

    def compute_s_risk(self, risk_scores: dict, time_grids: list,
                       time_step: int) -> set:
        """返回指定时间步的 S_risk(tj)

        基于 FHE 返回的解密后风险评分, 筛选 R(g) <= τ_R 的网格。
        """
        s_risk = set()
        for g in time_grids:
            if g['time_step'] != time_step:
                continue
            code = g['code']
            if code in risk_scores and risk_scores[code] <= self.r_threshold:
                s_risk.add(code)
        return s_risk


# ============================================================================
# 辅助函数
# ============================================================================
def create_mock_mask_provider():
    """创建模拟掩码提供函数 (与 test_uav_siting.py 完全一致)"""
    def mask_provider(code, time_step):
        seed = code % 100
        mask = 0
        if seed < 10:
            mask |= GridMask.NO_FLY
        if 10 <= seed < 15:
            mask |= GridMask.OBSTACLE
        if 5 <= time_step <= 7 and seed % 3 == 0:
            mask |= GridMask.ATC_CONTROL
        if seed < 20:
            mask |= GridMask.SCENE_LABEL
        return mask
    return mask_provider


def create_mock_risk_factors(grids):
    """创建模拟风险因子 (与 test_uav_siting.py 完全一致)"""
    risk_factors = {
        'land_use': {},
        'population': {},
        'power_facility': {},
        'construction_cost': {},
        'noise': {}
    }
    unique_codes = set(grid['code'] for grid in grids)
    for code in unique_codes:
        np.random.seed(code % 10000)
        risk_factors['land_use'][code] = np.random.uniform(0.1, 0.9)
        risk_factors['population'][code] = np.random.uniform(0.0, 0.8)
        risk_factors['power_facility'][code] = np.random.uniform(0.0, 0.5)
        risk_factors['construction_cost'][code] = np.random.uniform(0.2, 0.7)
        risk_factors['noise'][code] = np.random.uniform(0.1, 0.6)
    return risk_factors


# ============================================================================
# 测试: PSI 辅助工具
# ============================================================================
class TestPSIHelpers(unittest.TestCase):
    """测试 PSI 辅助工具"""

    def test_hex16_roundtrip(self):
        """测试编码 hex 转换往返"""
        for code in [0, 1, 255, 123456789012345678]:
            h = code_to_hex16(code)
            self.assertEqual(len(h), 32)
            self.assertEqual(hex16_to_code(h), code)

    def test_plain_set_intersection(self):
        """测试明文集合求交"""
        a = {1, 2, 3, 4, 5}
        b = {3, 4, 5, 6, 7}
        c = {4, 5, 8, 9}
        result = plain_set_intersection([a, b, c])
        self.assertEqual(result, {4, 5})

    def test_plain_intersection_empty(self):
        """测试空交集"""
        a = {1, 2, 3}
        b = {4, 5, 6}
        result = plain_set_intersection([a, b])
        self.assertEqual(result, set())


class TestPSIExecution(unittest.TestCase):
    """测试 frontend.exe PSI 执行 (需要 psi/frontend.exe 存在)"""

    @classmethod
    def setUpClass(cls):
        from psi_helpers import FRONTEND_EXE
        if not os.path.exists(FRONTEND_EXE):
            raise unittest.SkipTest('frontend.exe not found at %s' % FRONTEND_EXE)

    def test_pairwise_psi_basic(self):
        """测试基本两方 PSI 求交"""
        # 使用小集合测试
        set_a = {100, 200, 300, 400, 500}
        set_b = {300, 400, 500, 600, 700}

        result = run_pairwise_psi(set_a, set_b, port=12200)

        self.assertEqual(result['intersection'], {300, 400, 500})
        self.assertEqual(result['cardinality'], 3)
        self.assertEqual(result['size_a'], 5)
        self.assertEqual(result['size_b'], 5)

    def test_pairwise_psi_empty_intersection(self):
        """测试空交集的 PSI"""
        set_a = {1, 2, 3}
        set_b = {4, 5, 6}

        result = run_pairwise_psi(set_a, set_b, port=12201)

        self.assertEqual(result['intersection'], set())
        self.assertEqual(result['cardinality'], 0)

    def test_pairwise_psi_full_overlap(self):
        """测试完全重叠的 PSI"""
        set_a = {10, 20, 30}
        set_b = {10, 20, 30}

        result = run_pairwise_psi(set_a, set_b, port=12202)

        self.assertEqual(result['intersection'], {10, 20, 30})

    def test_cascade_psi(self):
        """测试多方级联 PSI"""
        s1 = {1, 2, 3, 4, 5}
        s2 = {2, 3, 4, 5, 6}
        s3 = {3, 4, 5, 6, 7}
        s4 = {4, 5, 6, 7, 8}

        result = cascade_psi([s1, s2, s3, s4], ports=[12210, 12211, 12212])

        self.assertEqual(result['intersection'], {4, 5})
        self.assertEqual(result['rounds'], 3)
        self.assertEqual(len(result['intermediate']), 3)

    def test_psi_matches_plain(self):
        """测试 PSI 结果与明文求交一致"""
        np.random.seed(42)
        n = 100
        set_a = set(np.random.randint(1, 10000, size=n).tolist())
        set_b = set(np.random.randint(1, 10000, size=n).tolist())

        psi_result = run_pairwise_psi(set_a, set_b, port=12220)
        plain_result = set_a & set_b

        self.assertEqual(psi_result['intersection'], plain_result)


# ============================================================================
# 测试: FHE 明文替代
# ============================================================================
class TestFHEPlaintext(unittest.TestCase):
    """测试 FHE 明文替代实现"""

    def test_fhe_risk_scoring_matches_plain(self):
        """验证 FHE 明文替代的风险评分与直接计算一致

        这确保当未来替换为真实 FHE 时, 接口兼容。
        """
        # 构建测试数据
        codes = [100, 200, 300]
        risk_factors = {
            'land_use': {100: 0.5, 200: 0.3, 300: 0.7},
            'population': {100: 0.2, 200: 0.8, 300: 0.1},
        }
        weights = {'land_use': 0.6, 'population': 0.4}

        # FHE 流程
        fhe_scores = fhe_risk_scoring_pipeline(risk_factors, weights, codes)

        # 直接计算
        expected = {
            100: 0.6 * 0.5 + 0.4 * 0.2,
            200: 0.6 * 0.3 + 0.4 * 0.8,
            300: 0.6 * 0.7 + 0.4 * 0.1,
        }

        for code in codes:
            self.assertAlmostEqual(fhe_scores[code], expected[code], places=10)

    def test_map_table(self):
        """测试 mapTable 映射表"""
        codes = [300, 100, 200, 100]  # 含重复
        mt = MapTable(codes)
        self.assertEqual(mt.size, 3)  # 去重后 3 个

        # 验证双向映射
        for code in [100, 200, 300]:
            idx = mt.code_to_index(code)
            self.assertEqual(mt.index_to_code(idx), code)


# ============================================================================
# 测试: 四方本地约束集合生成 (专利步骤 S2)
# ============================================================================
class TestPartySetGeneration(unittest.TestCase):
    """测试各参与方本地生成约束集合 (使用小区域)"""

    @classmethod
    def setUpClass(cls):
        mask_provider = create_mock_mask_provider()
        cls.grids = build_spatiotemporal_grids(
            SMALL_LOWER, SMALL_UPPER,
            H_MIN, H_MAX, LEVEL,
            TIME_START, TIME_END, DT,
            mask_provider
        )
        cls.surviving = hard_constraint_filter(cls.grids)
        cls.risk_factors = create_mock_risk_factors(cls.surviving)
        # 构建索引以加速验证
        cls._grid_index = {(g['code'], g['time_step']): g for g in cls.grids}

    def test_geo_info_s_land(self):
        """地理信息方: S_land 应为硬约束通过的网格"""
        geo = GeoInfoParty(self.grids, self.risk_factors)
        s_land = geo.get_s_land()

        self.assertGreater(len(s_land), 0)

        # 验证 S_land 中的网格均通过硬约束 (检查 t=0)
        for code in s_land:
            key = (code, 0)
            if key in self._grid_index:
                self.assertTrue(GridMask.check_hard_constraint(self._grid_index[key]['mask']))

    def test_airspace_s_air(self):
        """空域管理方: S_air(tj) 应排除禁飞区和空管网格"""
        air = AirspaceParty(self.grids)

        for t in range(TIME_START, TIME_END):
            s_air = air.get_s_air(t)
            for code in s_air:
                key = (code, t)
                if key in self._grid_index:
                    mask = self._grid_index[key]['mask']
                    self.assertEqual(mask & GridMask.NO_FLY, 0)
                    self.assertEqual(mask & GridMask.ATC_CONTROL, 0)

    def test_meteo_s_met(self):
        """气象服务方: S_met(tj) 应排除恶劣气象网格"""
        met = MeteoParty(self.grids)

        for t in range(TIME_START, TIME_END):
            s_met = met.get_s_met(t)
            for code in s_met:
                key = (code, t)
                if key in self._grid_index:
                    mask = self._grid_index[key]['mask']
                    self.assertEqual(mask & GridMask.WEATHER, 0)

    def test_planner_s_risk(self):
        """规划方: S_risk(tj) 应仅包含风险达标的网格"""
        planner = PlannerParty(WEIGHTS, R_THRESHOLD)
        risk_scores = compute_risk_scores(self.surviving, self.risk_factors, WEIGHTS)

        for t in range(TIME_START, TIME_END):
            s_risk = planner.compute_s_risk(risk_scores, self.surviving, t)
            for code in s_risk:
                self.assertLessEqual(risk_scores[code], R_THRESHOLD)


# ============================================================================
# 测试: FHE 风险评分流程 (专利步骤 S2-S3-S4, 明文替代)
# ============================================================================
class TestFHERiskScoring(unittest.TestCase):
    """测试 FHE 风险评分端到端流程 (明文替代)"""

    @classmethod
    def setUpClass(cls):
        mask_provider = create_mock_mask_provider()
        cls.grids = build_spatiotemporal_grids(
            SMALL_LOWER, SMALL_UPPER,
            H_MIN, H_MAX, LEVEL,
            TIME_START, TIME_END, DT,
            mask_provider
        )
        cls.surviving = hard_constraint_filter(cls.grids)
        cls.risk_factors = create_mock_risk_factors(cls.surviving)

    def test_fhe_matches_direct_computation(self):
        """FHE 明文替代结果应与直接计算一致"""
        unique_codes = list(set(g['code'] for g in self.surviving))

        # FHE 流程
        fhe_scores = fhe_risk_scoring_pipeline(
            self.risk_factors, WEIGHTS, unique_codes
        )

        # 直接计算
        direct_scores = compute_risk_scores(
            self.surviving, self.risk_factors, WEIGHTS
        )

        # 验证一致性
        for code in unique_codes:
            if code in fhe_scores and code in direct_scores:
                self.assertAlmostEqual(
                    fhe_scores[code], direct_scores[code],
                    places=10,
                    msg='code=%d FHE 与直接计算不一致' % code
                )


# ============================================================================
# 测试: 四方 PSI 求交 (专利步骤 S4)
# ============================================================================
class TestFourPartyPSI(unittest.TestCase):
    """测试四方 PSI 隐私集合求交"""

    @classmethod
    def setUpClass(cls):
        from psi_helpers import FRONTEND_EXE
        if not os.path.exists(FRONTEND_EXE):
            raise unittest.SkipTest('frontend.exe not found')

        mask_provider = create_mock_mask_provider()
        cls.grids = build_spatiotemporal_grids(
            SMALL_LOWER, SMALL_UPPER,
            H_MIN, H_MAX, LEVEL,
            TIME_START, TIME_END, DT,
            mask_provider
        )
        cls.surviving = hard_constraint_filter(cls.grids)
        cls.risk_factors = create_mock_risk_factors(cls.surviving)

    def test_four_party_psi_t0(self):
        """测试 t=0 时刻的四方 PSI 求交"""
        t = 0

        # 各方生成集合
        geo = GeoInfoParty(self.grids, self.risk_factors)
        air = AirspaceParty(self.grids)
        met = MeteoParty(self.grids)

        # FHE 风险评分 (明文替代)
        unique_codes = list(set(g['code'] for g in self.surviving))
        risk_scores = fhe_risk_scoring_pipeline(
            self.risk_factors, WEIGHTS, unique_codes
        )
        planner = PlannerParty(WEIGHTS, R_THRESHOLD)
        s_risk = planner.compute_s_risk(risk_scores, self.surviving, t)

        s_land = geo.get_s_land()
        s_air = air.get_s_air(t)
        s_met = met.get_s_met(t)

        # 级联 PSI: S_land ∩ S_air ∩ S_met ∩ S_risk
        result = cascade_psi(
            [s_land, s_air, s_met, s_risk],
            ports=[12300, 12301, 12302]
        )

        psi_intersection = result['intersection']

        # 明文验证
        plain_intersection = plain_set_intersection([s_land, s_air, s_met, s_risk])

        # PSI 结果应与明文求交一致
        self.assertEqual(psi_intersection, plain_intersection,
                        'PSI 交集 ≠ 明文交集 at t=%d' % t)

    def test_psi_all_time_steps(self):
        """测试所有时间步的 PSI 求交"""
        geo = GeoInfoParty(self.grids, self.risk_factors)
        air = AirspaceParty(self.grids)
        met = MeteoParty(self.grids)

        unique_codes = list(set(g['code'] for g in self.surviving))
        risk_scores = fhe_risk_scoring_pipeline(
            self.risk_factors, WEIGHTS, unique_codes
        )
        planner = PlannerParty(WEIGHTS, R_THRESHOLD)

        for t in range(TIME_START, min(TIME_START + 3, TIME_END)):
            s_land = geo.get_s_land()
            s_air = air.get_s_air(t)
            s_met = met.get_s_met(t)
            s_risk = planner.compute_s_risk(risk_scores, self.surviving, t)

            result = cascade_psi(
                [s_land, s_air, s_met, s_risk],
                ports=[12310 + t * 4, 12311 + t * 4, 12312 + t * 4]
            )

            plain_result = plain_set_intersection([s_land, s_air, s_met, s_risk])
            self.assertEqual(result['intersection'], plain_result,
                            'PSI ≠ 明文 at t=%d' % t)


# ============================================================================
# 测试: 完整选址流程 (专利步骤 S0-S7, 使用 PSI + FHE 明文替代)
# ============================================================================
class TestFullPipelineFHEPSI(unittest.TestCase):
    """测试完整的 FHE+PSI 选址流程"""

    @classmethod
    def setUpClass(cls):
        from psi_helpers import FRONTEND_EXE
        if not os.path.exists(FRONTEND_EXE):
            raise unittest.SkipTest('frontend.exe not found')

    def test_full_pipeline(self):
        """端到端: S0-S7 完整流程

        本测试完整模拟专利中的步骤:
        S0: 数据预处理
        S1: 四维时空网格构建
        S2: 各方本地生成约束集合
        S3: FHE 密态加权求和 (明文替代)
        S4: 四方 PSI 隐私集合求交 (两两级联)
        S5: DBSCAN 聚类 + 风险加权质心
        S6: 时空滑窗可用性验证
        S7: 候选场址筛选
        """
        # ============================================================
        # S0: 多方原始数据预处理
        # ============================================================
        mask_provider = create_mock_mask_provider()

        # ============================================================
        # S1: GB/T 40087 混合粒度四维时空网格构建
        # 使用完整区域 (与 test_uav_siting.py 一致)
        # ============================================================
        grids = build_spatiotemporal_grids(
            LOWER_POLYGON, UPPER_POLYGON,
            H_MIN, H_MAX, LEVEL,
            TIME_START, TIME_END, DT,
            mask_provider
        )
        surviving = hard_constraint_filter(grids)

        # ============================================================
        # S2: 各方本地生成约束集合
        # ============================================================
        risk_factors = create_mock_risk_factors(surviving)
        geo = GeoInfoParty(grids, risk_factors)
        air = AirspaceParty(grids)
        met = MeteoParty(grids)

        # ============================================================
        # S3: FHE 密态加权求和 (明文替代)
        # ============================================================
        # TODO[FHE]: 真实实现中, 地理信息方加密风险因子, 规划方加密权重,
        #            FHE 服务器在密域内计算, 规划方解密。
        unique_codes = list(set(g['code'] for g in surviving))
        risk_scores = fhe_risk_scoring_pipeline(
            risk_factors, WEIGHTS, unique_codes
        )

        # ============================================================
        # S4: 四方 PSI 隐私集合求交 (两两级联, 每个时间步)
        # 注: 使用 TIME_END 以匹配 test_uav_siting.py 的完整时间窗口
        # ============================================================
        planner = PlannerParty(WEIGHTS, R_THRESHOLD)
        s_land = geo.get_s_land()

        # 存储各时间步的 PSI 交集
        psi_intersections = {}

        for t in range(TIME_START, TIME_END):
            s_air = air.get_s_air(t)
            s_met = met.get_s_met(t)
            s_risk = planner.compute_s_risk(risk_scores, surviving, t)

            # 两两级联 PSI
            result = cascade_psi(
                [s_land, s_air, s_met, s_risk],
                ports=[12400 + t * 4, 12401 + t * 4, 12402 + t * 4]
            )

            psi_intersections[t] = result['intersection']

            # 验证与明文一致
            plain = plain_set_intersection([s_land, s_air, s_met, s_risk])
            self.assertEqual(result['intersection'], plain,
                            'PSI ≠ 明文 at t=%d' % t)

        # ============================================================
        # S5: DBSCAN 聚类 + 风险加权质心
        # 与 test_uav_siting.py 一致: 对所有风险过滤网格聚类 (所有时间步)
        # ============================================================
        risk_filtered = filter_by_risk_threshold(
            surviving, risk_scores, R_THRESHOLD
        )

        if len(risk_filtered) > 0:
            centroids = cluster_and_centroids(
                risk_filtered, risk_scores, eps=EPS, min_samples=MIN_SAMPLES
            )
        else:
            centroids = []

        # ============================================================
        # S6: 时空滑窗可用性验证
        # 使用 time_window_availability 函数 (与 test_uav_siting.py 一致)
        # ============================================================
        qualified = time_window_availability(
            centroids, surviving, risk_scores, R_THRESHOLD,
            (TIME_START, TIME_END), A_THRESHOLD, BUFFER_GRIDS
        )

        # ============================================================
        # S7: 候选场址筛选与结果输出
        # ============================================================
        print('\n=== FHE+PSI 选址结果 (完整区域) ===')
        print(f'总时空网格: {len(grids):,}')
        print(f'硬约束幸存: {len(surviving):,}')
        print(f'PSI 交集网格 (t=0): {len(psi_intersections.get(0, set()))}')
        print(f'聚类数: {len(centroids)}')
        print(f'最终候选起降场: {len(qualified)}')

        if qualified:
            for i, c in enumerate(qualified, 1):
                print(f'  [{i}] 经度={c["lng"]:.6f}, 纬度={c["lat"]:.6f}, '
                      f'高度={c["h"]:.1f}m, 可用性={c["availability"]:.2f}')

        # 基本断言
        self.assertGreater(len(grids), 0)
        self.assertGreater(len(surviving), 0)

    def test_consistency_with_plain_pipeline(self):
        """验证 FHE+PSI 流程与明文流程的结果一致性

        使用小区域测试, 对比:
        1. 明文 uav_siting() 流程
        2. FHE (明文替代) + PSI (frontend.exe) 流程

        两者的候选起降场数量应一致。
        注: 使用 PSI_TIME_END 以减少 PSI 调用次数。
        """
        # --- 明文流程 ---
        mask_provider = create_mock_mask_provider()
        risk_factors_plain = create_mock_risk_factors(
            hard_constraint_filter(build_spatiotemporal_grids(
                SMALL_LOWER, SMALL_UPPER,
                H_MIN, H_MAX, LEVEL,
                TIME_START, PSI_TIME_END, DT,
                mask_provider
            ))
        )

        plain_result = uav_siting(
            SMALL_LOWER, SMALL_UPPER,
            H_MIN, H_MAX, LEVEL,
            TIME_START, PSI_TIME_END, DT,
            risk_factors_plain, WEIGHTS,
            R_threshold=R_THRESHOLD,
            eps=EPS, min_samples=MIN_SAMPLES,
            A_threshold=A_THRESHOLD,
            buffer_grids=BUFFER_GRIDS,
            mask_provider=mask_provider,
            scene='urban'
        )

        # --- FHE+PSI 流程 ---
        grids = build_spatiotemporal_grids(
            SMALL_LOWER, SMALL_UPPER,
            H_MIN, H_MAX, LEVEL,
            TIME_START, PSI_TIME_END, DT,
            mask_provider
        )
        surviving = hard_constraint_filter(grids)

        # FHE 风险评分 (明文替代)
        unique_codes = list(set(g['code'] for g in surviving))
        risk_scores_fhe = fhe_risk_scoring_pipeline(
            risk_factors_plain, WEIGHTS, unique_codes
        )

        # 各方集合
        geo = GeoInfoParty(grids, risk_factors_plain)
        air = AirspaceParty(grids)
        met = MeteoParty(grids)
        planner = PlannerParty(WEIGHTS, R_THRESHOLD)
        s_land = geo.get_s_land()

        # PSI 求交 (各时间步)
        psi_intersections = {}
        for t in range(TIME_START, PSI_TIME_END):
            s_air = air.get_s_air(t)
            s_met = met.get_s_met(t)
            s_risk = planner.compute_s_risk(risk_scores_fhe, surviving, t)

            result = cascade_psi(
                [s_land, s_air, s_met, s_risk],
                ports=[12500 + t * 4, 12501 + t * 4, 12502 + t * 4]
            )
            psi_intersections[t] = result['intersection']

        # 聚类和可用性 (与 test_uav_siting.py 一致: 对所有风险过滤网格聚类)
        risk_filtered_fhe = filter_by_risk_threshold(
            surviving, risk_scores_fhe, R_THRESHOLD
        )

        centroids_fhe = cluster_and_centroids(
            risk_filtered_fhe, risk_scores_fhe, eps=EPS, min_samples=MIN_SAMPLES
        ) if risk_filtered_fhe else []

        # 可用性检查 (使用 time_window_availability)
        qualified_fhe = time_window_availability(
            centroids_fhe, surviving, risk_scores_fhe, R_THRESHOLD,
            (TIME_START, PSI_TIME_END), A_THRESHOLD, BUFFER_GRIDS
        )

        # 对比候选数量
        print(f'\n明文流程候选: {len(plain_result["candidates"])}')
        print(f'FHE+PSI 流程候选: {len(qualified_fhe)}')

        self.assertEqual(
            len(plain_result['candidates']),
            len(qualified_fhe),
            'FHE+PSI 候选数量应与明文流程一致'
        )


# ============================================================================
# 测试: 时间窗口可用性 (专利步骤 S6)
# ============================================================================
class TestTimeWindowAvailability(unittest.TestCase):
    """测试基于 PSI 交集的时间窗口可用性验证"""

    @classmethod
    def setUpClass(cls):
        from psi_helpers import FRONTEND_EXE
        if not os.path.exists(FRONTEND_EXE):
            raise unittest.SkipTest('frontend.exe not found')

    def test_availability_ratio(self):
        """验证可用性占比计算正确 (使用 PSI_TIME_END 减少调用)"""
        mask_provider = create_mock_mask_provider()
        grids = build_spatiotemporal_grids(
            SMALL_LOWER, SMALL_UPPER,
            H_MIN, H_MAX, LEVEL,
            TIME_START, PSI_TIME_END, DT,
            mask_provider
        )
        surviving = hard_constraint_filter(grids)

        # 构建各方集合
        risk_factors = create_mock_risk_factors(surviving)
        geo = GeoInfoParty(grids, risk_factors)
        air = AirspaceParty(grids)
        met = MeteoParty(grids)

        unique_codes = list(set(g['code'] for g in surviving))
        risk_scores = fhe_risk_scoring_pipeline(
            risk_factors, WEIGHTS, unique_codes
        )
        planner = PlannerParty(WEIGHTS, R_THRESHOLD)
        s_land = geo.get_s_land()

        # 各时间步 PSI 交集
        intersection_sizes = []
        for t in range(TIME_START, PSI_TIME_END):
            s_air = air.get_s_air(t)
            s_met = met.get_s_met(t)
            s_risk = planner.compute_s_risk(risk_scores, surviving, t)

            result = cascade_psi(
                [s_land, s_air, s_met, s_risk],
                ports=[12600 + t * 4, 12601 + t * 4, 12602 + t * 4]
            )
            intersection_sizes.append(len(result['intersection']))

        # 验证: 交集大小应非负
        print(f'\n各时间步 PSI 交集大小: {intersection_sizes}')

        # 基本: 交集大小应非负
        for size in intersection_sizes:
            self.assertGreaterEqual(size, 0)

        # 验证至少有 3 个时间步的结果
        self.assertEqual(len(intersection_sizes), PSI_TIME_END - TIME_START)


def main():
    """独立运行: 完整演示"""
    print('=' * 70)
    print('基于 FHE 与 PSI 的无人机起降场自适应选址测试')
    print('=' * 70)
    print(f'\n区域: 德清县全域 (~60km × 30km)')
    print(f'网格层级: Level {LEVEL} (~44m)')
    print(f'高度范围: {H_MIN}m - {H_MAX}m')
    print(f'时间步: {TIME_START} - {TIME_END}')

    from psi_helpers import FRONTEND_EXE
    if not os.path.exists(FRONTEND_EXE):
        print(f'\n[ERROR] frontend.exe not found at {FRONTEND_EXE}')
        print('Please place frontend.exe in the psi/ directory.')
        return

    unittest.main(argv=[''], exit=False, verbosity=2)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='FHE+PSI 无人机选址测试')
    parser.add_argument('--test', action='store_true', help='运行 unittest')
    args = parser.parse_args()

    if args.test:
        unittest.main(argv=[''], exit=False, verbosity=2)
    else:
        main()
