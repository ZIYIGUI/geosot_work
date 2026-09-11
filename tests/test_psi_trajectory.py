# -*- coding: utf-8 -*-
"""
无人机轨迹 PSI 计算
====================
读取两份无人机轨迹文件，编码后保存为 128 位二进制文件，
然后调用 psi/frontend.exe 进行 PSI 计算。

用法:
    python tests/test_psi_trajectory.py
"""
import os
import sys
import time
import subprocess
import threading

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

import geosot_core as gc
from geofile import read_csv
import geosot_service as svc

# 路径配置
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
OUT_DIR = os.path.join(PROJECT_ROOT, 'out')
PSI_DIR = os.path.join(PROJECT_ROOT, 'psi')

TRAJ_1_PATH = os.path.join(DATA_DIR, 'uav_conflict_1.csv')
TRAJ_2_PATH = os.path.join(DATA_DIR, 'uav_conflict_2.csv')

# 编码输出文件
PARTY1_BIN = os.path.join(OUT_DIR, 'trajectory_party1.bin')
PARTY2_BIN = os.path.join(OUT_DIR, 'trajectory_party2.bin')

# PSI 输出文件（二进制格式）
PSI_OUT_1 = os.path.join(OUT_DIR, 'psi_result_party1.bin')
PSI_OUT_2 = os.path.join(OUT_DIR, 'psi_result_party2.bin')

# PSI 可执行文件
PSI_EXE = os.path.join(PSI_DIR, 'frontend.exe')

# 网络配置
PSI_HOST = '127.0.0.1'
PSI_PORT = '1212'


def encode_trajectory_to_bin(csv_path, bin_path, level=21):
    """
    读取轨迹 CSV 文件，编码后保存为 128 位二进制文件。

    参数:
        csv_path: CSV 文件路径
        bin_path: 输出 bin 文件路径
        level: 网格层级，默认 21 级

    返回:
        int: 编码数量
    """
    feats = read_csv(csv_path)
    codes = set()

    for feat in feats:
        if feat['type'] != 'Point':
            continue
        lng, lat = feat['coords'][0]
        r, c = gc.row_col(lat, lng, level)
        code = svc._routeB_code(r, c, level)
        codes.add(code)

    # 排序后写入
    sorted_codes = sorted(codes)
    with open(bin_path, 'wb') as f:
        for code in sorted_codes:
            buf = gc.to_bytes16(code, dim=2)
            f.write(buf)

    return len(sorted_codes)


def run_psi_party(is_server, input_bin, output_file, event=None):
    """
    运行 PSI 的一方。

    参数:
        is_server: 是否为服务端
        input_bin: 输入 bin 文件路径
        output_file: 输出文件路径
        event: 同步事件（用于等待服务端启动）
    """
    r_value = '1' if is_server else '0'
    server_value = '1' if is_server else '0'

    cmd = [
        PSI_EXE,
        '-in', input_bin,
        '-r', r_value,
        '-server', server_value,
        '-out', output_file,
        '-noSort',
        '-receiverSize', '10000',
        '-senderSize', '10000',
        '-nt', '8',
        '-ip', f'{PSI_HOST}:{PSI_PORT}'
    ]

    if not is_server and event:
        event.wait()  # 等待服务端启动

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )
        # 打印输出信息
        if result.stdout:
            print(f'    [{("Server" if is_server else "Client")}] {result.stdout.strip()[:200]}')
        if result.stderr:
            print(f'    [{("Server" if is_server else "Client")} stderr] {result.stderr.strip()[:200]}')
        return result
    except subprocess.TimeoutExpired:
        print(f"PSI 进程超时 (party={'server' if is_server else 'client'})")
        return None


def main():
    print('=' * 60)
    print('无人机轨迹 PSI 计算')
    print('=' * 60)

    os.makedirs(OUT_DIR, exist_ok=True)

    # 1. 编码轨迹文件
    print('\n[1] 编码轨迹文件...')

    t0 = time.perf_counter()
    count1 = encode_trajectory_to_bin(TRAJ_1_PATH, PARTY1_BIN, level=21)
    t1 = time.perf_counter()
    count2 = encode_trajectory_to_bin(TRAJ_2_PATH, PARTY2_BIN, level=21)
    t2 = time.perf_counter()

    print(f'    轨迹1: {count1} 个编码 -> {PARTY1_BIN}')
    print(f'    轨迹1编码耗时: {t1 - t0:.4f} 秒')
    print(f'    轨迹2: {count2} 个编码 -> {PARTY2_BIN}')
    print(f'    轨迹2编码耗时: {t2 - t1:.4f} 秒')

    # 2. 运行 PSI
    print('\n[2] 运行 PSI 计算...')
    print(f'    服务端输入: {PARTY1_BIN}')
    print(f'    客户端输入: {PARTY2_BIN}')
    print(f'    地址: {PSI_HOST}:{PSI_PORT}')

    t3 = time.perf_counter()

    # 创建同步事件
    server_ready = threading.Event()

    # 先启动服务端（后台）
    def start_server():
        server_ready.set()  # 标记服务端已启动
        return run_psi_party(True, PARTY1_BIN, PSI_OUT_1, None)

    def start_client():
        time.sleep(0.5)  # 等待服务端启动
        return run_psi_party(False, PARTY2_BIN, PSI_OUT_2, server_ready)

    # 使用线程并行启动
    server_thread = threading.Thread(target=start_server)
    client_thread = threading.Thread(target=start_client)

    server_thread.start()
    client_thread.start()

    server_thread.join(timeout=60)
    client_thread.join(timeout=60)

    t4 = time.perf_counter()

    print(f'    PSI 计算耗时: {t4 - t3:.4f} 秒')

    # 3. 读取并显示结果
    print('\n[3] PSI 结果:')

    for name, path in [('Party1 (Server)', PSI_OUT_1), ('Party2 (Client)', PSI_OUT_2)]:
        if os.path.exists(path):
            with open(path, 'rb') as f:
                content = f.read()
            # 每个元素 16 字节
            count = len(content) // 16
            print(f'    {name}: {count} 个交集元素 -> {path} ({len(content)} 字节)')
        else:
            print(f'    {name}: 输出文件未生成')

    # 4. 汇总
    total_time = time.perf_counter() - t0
    print(f'\n{"=" * 60}')
    print(f'总耗时: {total_time:.4f} 秒')
    print(f'输出文件:')
    print(f'  - {PARTY1_BIN} ({count1 * 16} 字节)')
    print(f'  - {PARTY2_BIN} ({count2 * 16} 字节)')
    if os.path.exists(PSI_OUT_1):
        print(f'  - {PSI_OUT_1}')
    if os.path.exists(PSI_OUT_2):
        print(f'  - {PSI_OUT_2}')
    print(f'{"=" * 60}')


if __name__ == '__main__':
    main()
