# -*- coding: utf-8 -*-
"""
PSI 辅助工具
============
封装 frontend.exe 的输入输出、进程编排与集合级联求交。

输入格式: 32 字符 hex CSV (每行一个 16 字节编码元素)
输出格式: 同输入格式

用法:
    from psi_helpers import set_to_csv, run_pairwise_psi, cascade_psi
"""
import csv
import io
import os
import subprocess
import sys
import tempfile
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONTEND_EXE = os.path.join(PROJECT_ROOT, 'psi', 'frontend.exe')

# 默认端口范围, 每对 PSI 使用不同端口以避免冲突
DEFAULT_BASE_PORT = 12120


def code_to_hex16(code: int) -> str:
    """将整数编码转为 32 字符 hex 字符串 (16 字节 big-endian, 右对齐)"""
    if code < 0:
        raise ValueError('code must be non-negative')
    # 使用 128 位 (16 字节), 高 32 位补 0, 低 96 位为编码值
    return '%032x' % code


def hex16_to_code(hex_str: str) -> int:
    """将 32 字符 hex 字符串转回整数编码"""
    return int(hex_str.strip(), 16)


def set_to_csv(codes: set, path: str):
    """将编码集合写入 CSV 文件 (每行一个 32 字符 hex)

    Args:
        codes: 整数编码集合
        path: 输出文件路径 (.csv)
    """
    sorted_codes = sorted(codes)
    with io.open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        for code in sorted_codes:
            w.writerow([code_to_hex16(code)])


def csv_to_set(path: str) -> set:
    """从 CSV 文件读取编码集合

    Args:
        path: CSV 文件路径

    Returns:
        整数编码集合
    """
    if not os.path.exists(path):
        return set()
    result = set()
    with io.open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and len(line) >= 32:
                result.add(hex16_to_code(line[:32]))
    return result


def run_pairwise_psi(set_a: set, set_b: set, port: int = None,
                     card_only: bool = False, timeout: int = 30) -> dict:
    """运行两方 PSI 求交

    启动两个 frontend.exe 进程:
    - Party A (sender, r=0): 发送方
    - Party B (receiver, r=1): 接收方, 同时作为 server

    Args:
        set_a: 参与方 A 的编码集合
        set_b: 参与方 B 的编码集合
        port: TCP 端口号 (默认自动分配)
        card_only: 若为 True, 运行 CPSI 仅返回交集基数
        timeout: 超时秒数

    Returns:
        {
            'intersection': set,       # 交集编码 (card_only=False 时)
            'cardinality': int,        # 交集基数 (card_only=True 时)
            'size_a': int,
            'size_b': int,
        }
    """
    global DEFAULT_BASE_PORT
    if port is None:
        port = DEFAULT_BASE_PORT
        DEFAULT_BASE_PORT += 1

    tmpdir = tempfile.mkdtemp(prefix='psi_')
    try:
        in_a = os.path.join(tmpdir, 'party_a.csv')
        in_b = os.path.join(tmpdir, 'party_b.csv')
        out_b = os.path.join(tmpdir, 'party_b.csv.out')

        set_to_csv(set_a, in_a)
        set_to_csv(set_b, in_b)

        ip_addr = 'localhost:%d' % port

        # Party B: receiver + server (先启动, 监听端口)
        cmd_b = [
            FRONTEND_EXE,
            '-in', in_b,
            '-r', '1',
            '-out', out_b,
            '-ip', ip_addr,
            '-server', '1',
            '-quiet',
        ]
        if card_only:
            cmd_b.append('-card')

        # Party A: sender (连接到 B)
        cmd_a = [
            FRONTEND_EXE,
            '-in', in_a,
            '-r', '0',
            '-out', os.path.join(tmpdir, 'party_a.csv.out'),
            '-ip', ip_addr,
            '-server', '0',
            '-quiet',
        ]
        if card_only:
            cmd_a.append('-card')

        # 启动 B (server) 先, 然后 A
        proc_b = subprocess.Popen(cmd_b, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(0.3)  # 等待 server 启动
        proc_a = subprocess.Popen(cmd_a, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # 等待两个进程完成
        stdout_a, stderr_a = proc_a.communicate(timeout=timeout)
        stdout_b, stderr_b = proc_b.communicate(timeout=timeout)

        if proc_a.returncode != 0:
            raise RuntimeError('PSI sender failed (rc=%d): %s' % (
                proc_a.returncode, stderr_a.decode('utf-8', errors='replace')))
        if proc_b.returncode != 0:
            raise RuntimeError('PSI receiver failed (rc=%d): %s' % (
                proc_b.returncode, stderr_b.decode('utf-8', errors='replace')))

        if card_only:
            # CPSI: receiver 输出基数到 stdout
            out_text = stdout_b.decode('utf-8', errors='replace')
            card = 0
            for line in out_text.splitlines():
                if 'cardinality' in line.lower() or 'intersection' in line.lower():
                    parts = line.strip().split()
                    for p in parts:
                        try:
                            card = int(p)
                        except ValueError:
                            pass
            return {
                'intersection': set(),
                'cardinality': card,
                'size_a': len(set_a),
                'size_b': len(set_b),
            }
        else:
            # 标准 PSI: 从 receiver 的输出文件读取交集
            intersection = csv_to_set(out_b)
            return {
                'intersection': intersection,
                'cardinality': len(intersection),
                'size_a': len(set_a),
                'size_b': len(set_b),
            }

    finally:
        # 清理临时文件
        for fn in os.listdir(tmpdir):
            try:
                os.remove(os.path.join(tmpdir, fn))
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass


def cascade_psi(sets: list, ports: list = None, timeout: int = 30) -> dict:
    """多轮两两 PSI 级联求交

    按照专利替代方案一: 多轮两两 PSI 级联实现多方 PSI。
    例如 4 方: S_land, S_air, S_met, S_risk
    -> temp1 = PSI(S_land, S_air)
    -> temp2 = PSI(temp1, S_met)
    -> final = PSI(temp2, S_risk)

    Args:
        sets: 各方编码集合列表 [set_a, set_b, set_c, ...]
        ports: 每轮的端口号列表 (可选)
        timeout: 每轮超时秒数

    Returns:
        {
            'intersection': set,           # 最终交集
            'intermediate': [set, ...],     # 各轮中间结果
            'rounds': int,                  # 级联轮数
        }
    """
    if len(sets) < 2:
        raise ValueError('cascade_psi requires at least 2 sets')

    base_port = DEFAULT_BASE_PORT
    intermediate = []
    current = sets[0]

    for i in range(1, len(sets)):
        port = (ports[i - 1] if ports and i - 1 < len(ports)
                else base_port + i - 1)
        result = run_pairwise_psi(current, sets[i], port=port, timeout=timeout)
        current = result['intersection']
        intermediate.append(current)

    return {
        'intersection': current,
        'intermediate': intermediate,
        'rounds': len(sets) - 1,
    }


def plain_set_intersection(sets: list) -> set:
    """明文集合求交 (FHE/PSI 的明文替代, 用于验证)

    直接计算所有集合的交集, 无需网络通信。
    用于与 PSI 结果对比验证正确性。

    Args:
        sets: 编码集合列表 [set_a, set_b, ...]

    Returns:
        交集
    """
    if not sets:
        return set()
    result = set(sets[0])
    for s in sets[1:]:
        result &= s
    return result
