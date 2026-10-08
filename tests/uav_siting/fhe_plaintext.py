# -*- coding: utf-8 -*-
"""
FHE 明文替代模块
================
专利步骤 S3 中 FHE 服务器密态加权求和的明文替代实现。

在真实部署中, 以下步骤应在 FHE 密域内执行:
  - 地理信息方将风险因子 f_i(g) 加密后发送至 FHE 服务器
  - 规划方将场景权重 w_i 加密后发送至 FHE 服务器
  - FHE 服务器在密域内计算 R(g,tj) = Σ w_i · f_i(g)
  - FHE 服务器将密文结果返回规划方解密

本模块用明文运算替代, 但保持相同的接口和数据结构,
以便未来替换为真实 FHE 实现时只需替换本模块。

TODO[FHE]: 以下标记为 FHE_REPLACEMENT 的函数需要用真实 FHE 库替换
           (如 SEAL/PySEAL, OpenFHE, TenSEAL 等)
"""
import numpy as np
from typing import Dict, List, Tuple, Optional


# ============================================================================
# FHE_REPLACEMENT: mapTable 映射表 (规划方本地维护)
# ============================================================================
class MapTable:
    """网格 ID 与 FHE 序列下标的映射表

    专利描述:
    > 规划方本地维护网格ID与FHE输入输出序列下标的映射表mapTable,
    > 映射表仅保存在规划方本地。

    TODO[FHE]: 真实实现中, mapTable 仅在规划方本地维护,
               FHE 服务器只能看到有序密文序列, 无法获知网格 ID。
    """

    def __init__(self, codes: list):
        """
        Args:
            codes: 网格编码列表 (按确定顺序排列)
        """
        self._code_to_idx = {}
        self._idx_to_code = {}
        for idx, code in enumerate(sorted(set(codes))):
            self._code_to_idx[code] = idx
            self._idx_to_code[idx] = code

    @property
    def size(self) -> int:
        return len(self._code_to_idx)

    def code_to_index(self, code: int) -> int:
        return self._code_to_idx[code]

    def index_to_code(self, idx: int) -> int:
        return self._idx_to_code[idx]

    def codes(self) -> list:
        return [self._idx_to_code[i] for i in range(self.size)]


# ============================================================================
# FHE_REPLACEMENT: 地理信息方本地加密风险因子
# ============================================================================
def encrypt_risk_factors(
    risk_factors: Dict[str, Dict[int, float]],
    map_table: MapTable
) -> list:
    """地理信息方: 将风险因子按 mapTable 顺序编码

    专利步骤 S2:
    > 地理信息方本地将软约束数据归一化为风险因子 f_i(g),
    > 按mapTable顺序加密生成有序密文因子序列发送至FHE服务器

    TODO[FHE]: 真实实现中, 每个 f_i(g) 应使用 FHE 公钥加密。
               当前用明文浮点数替代。

    Args:
        risk_factors: {factor_name: {code: value}}
        map_table: 映射表

    Returns:
        有序因子序列: [[f_1(g_0), f_2(g_0), ...], [f_1(g_1), ...], ...]
        每行对应一个网格, 每列对应一个因子
    """
    factor_names = sorted(risk_factors.keys())
    encrypted = []

    for idx in range(map_table.size):
        code = map_table.index_to_code(idx)
        row = []
        for fname in factor_names:
            val = risk_factors.get(fname, {}).get(code, 0.0)
            # FHE_REPLACEMENT: 真实实现中此处应调用 fhe_encrypt(val, public_key)
            row.append(float(np.clip(val, 0.0, 1.0)))
        encrypted.append(row)

    return encrypted


# ============================================================================
# FHE_REPLACEMENT: 规划方本地加密权重矩阵
# ============================================================================
def encrypt_weights(
    weights: Dict[str, float],
) -> list:
    """规划方: 将场景权重编码

    专利步骤 S2:
    > 规划方本地加密场景权重矩阵 w_i 发送至FHE服务器

    TODO[FHE]: 真实实现中, w_i 应使用 FHE 公钥加密。
               当前用明文浮点数替代。

    Args:
        weights: {factor_name: weight}, 和为 1

    Returns:
        权重向量 [w_1, w_2, ...]
    """
    factor_names = sorted(weights.keys())
    encrypted = []
    for fname in factor_names:
        w = weights[fname]
        # FHE_REPLACEMENT: 真实实现中此处应调用 fhe_encrypt(w, public_key)
        encrypted.append(float(w))
    return encrypted


# ============================================================================
# FHE_REPLACEMENT: FHE 服务器密态加权求和
# ============================================================================
def fhe_weighted_sum(
    encrypted_factors: list,
    encrypted_weights: list,
) -> list:
    """FHE 服务器: 在密域内逐网格执行加权求和

    专利步骤 S3:
    > FHE服务器接收有序密文风险因子序列与密文权重矩阵,
    > 在密域内逐网格、逐时间步计算 R(g,tj)=Σ w_i(s(g))·f_i(g),
    > 输出与mapTable下标严格对齐的有序密文R(g,tj)序列

    TODO[FHE]: 真实实现中, 所有运算在密域内执行:
               encrypted_R[i] = Σ (encrypted_weights[j] * encrypted_factors[i][j])
               FHE 服务器全程不获取任何明文网格 ID。
               当前用明文加权求和替代。

    Args:
        encrypted_factors: 有序因子序列 (N_grid × N_factor)
        encrypted_weights: 权重向量 (N_factor,)

    Returns:
        有序风险评分序列 [R(g_0), R(g_1), ...]
    """
    results = []
    for row in encrypted_factors:
        score = 0.0
        for j, w in enumerate(encrypted_weights):
            # FHE_REPLACEMENT: 真实实现中此处为 fhe_multiply + fhe_add
            score += w * row[j]
        results.append(score)
    return results


# ============================================================================
# FHE_REPLACEMENT: 规划方本地解密
# ============================================================================
def decrypt_risk_scores(
    encrypted_scores: list,
    map_table: MapTable,
) -> Dict[int, float]:
    """规划方: 解密密文风险评分并关联至网格 ID

    专利步骤 S4:
    > 规划方以本地私钥解密密文序列,
    > 依据mapTable将明文风险评分关联至网格ID

    TODO[FHE]: 真实实现中, 应使用规划方私钥解密:
               plaintext_R[i] = fhe_decrypt(encrypted_scores[i], private_key)
               当前直接返回明文值。

    Args:
        encrypted_scores: 有序密文风险评分序列
        map_table: 映射表

    Returns:
        {grid_code: risk_score}
    """
    risk_scores = {}
    for idx, enc_score in enumerate(encrypted_scores):
        code = map_table.index_to_code(idx)
        # FHE_REPLACEMENT: 真实实现中此处应调用 fhe_decrypt(enc_score, private_key)
        risk_scores[code] = float(enc_score)
    return risk_scores


# ============================================================================
# FHE_REPLACEMENT: 完整的 FHE 风险评分流程 (端到端)
# ============================================================================
def fhe_risk_scoring_pipeline(
    risk_factors: Dict[str, Dict[int, float]],
    weights: Dict[str, float],
    codes: list,
) -> Dict[int, float]:
    """端到端 FHE 风险评分流程 (明文替代)

    完整模拟专利中地理信息方 → FHE 服务器 → 规划方的数据流:
    1. 规划方构建 mapTable (本地)
    2. 地理信息方加密风险因子并发送
    3. 规划方加密权重并发送
    4. FHE 服务器密态计算加权求和
    5. 规划方解密并关联网格 ID

    TODO[FHE]: 整个流程中, 步骤 2-4 的数据传输应全部为密文。
               当前模块为明文替代, 仅用于验证流程正确性。
               替换时只需替换 encrypt_risk_factors, encrypt_weights,
               fhe_weighted_sum, decrypt_risk_scores 四个函数。

    Args:
        risk_factors: 风险因子 {name: {code: value}}
        weights: 权重 {name: weight}, 和为 1
        codes: 网格编码列表

    Returns:
        {grid_code: risk_score}
    """
    # 步骤 1: 规划方构建 mapTable
    map_table = MapTable(codes)

    # 步骤 2: 地理信息方加密风险因子
    # TODO[FHE]: 真实实现中, 加密后的因子序列发送至 FHE 服务器
    enc_factors = encrypt_risk_factors(risk_factors, map_table)

    # 步骤 3: 规划方加密权重
    # TODO[FHE]: 真实实现中, 加密后的权重发送至 FHE 服务器
    enc_weights = encrypt_weights(weights)

    # 步骤 4: FHE 服务器密态加权求和
    # TODO[FHE]: 真实实现中, 此步骤在 FHE 密域内执行
    enc_scores = fhe_weighted_sum(enc_factors, enc_weights)

    # 步骤 5: 规划方解密并关联网格 ID
    # TODO[FHE]: 真实实现中, 使用私钥解密
    risk_scores = decrypt_risk_scores(enc_scores, map_table)

    return risk_scores
