# -*- coding: utf-8 -*-
"""
data/ 地理数据 -> GeoSOT 网格编码提取 -> out/ 产物生成
========================================================
输入: data/ 目录下的地理信息文件 (GeoJSON/CSV 等)
  - uav_track.geojson   无人机飞行轨迹 (LineString, 2 架次)
  - uav_points.csv      无人机轨迹航点表 (lon/lat 列, 10 个航点)
  - uav_track3d.csv     3D 航线数据 (lon/lat/alt_m, 10 个航点, 文件名含 '3d')
  - closed_area.geojson 空间封闭区域 (Polygon, 2 个禁飞区)
编码: 路线B (route B) 连续网格码, 默认 21 级 (1" 网格, 赤道约 30.9 m);
      3D 文件按 geo_num3d 96 位编码 (经/纬/高), binary128/16 字节按 dim=3。

输出: out/ 目录
  - codes.json          全部提取编码 (含类型/码/层级/维度/128位二进制/16字节hex/属性)
  - codes_128.bin       每条编码 16 字节(128 位) 大端连续写入 (2D 低 8 字节, 3D 低 12 字节)
  - codes_16bytes.csv   CSV 仅一列 bytes16_hex (32 个 hex 字符), 与 bin 逐条对应

用法: python encode_data.py [--level 21] [--route B]
"""
import argparse
import csv
import io
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))   # tests/
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))           # 项目根 (geosot_work/)
import geofile as gf
import geosot_core as gc

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根
DATA_DIR = os.path.join(BASE, 'data')
OUT_DIR = os.path.join(BASE, 'out')


def collect_input_files(data_dir=DATA_DIR):
    """收集 data/ 下所有非隐藏文件 (按名称排序保证确定性)。"""
    files = []
    if not os.path.isdir(data_dir):
        return files
    for fn in sorted(os.listdir(data_dir)):
        if fn.startswith('.'):
            continue
        p = os.path.join(data_dir, fn)
        if os.path.isfile(p):
            files.append(p)
    return files


def is_3d_file(path):
    """文件名含 '3d' 视为 3D 数据 (带高度维度, 96 位 3D 网格码)。"""
    return '3d' in os.path.basename(path).lower()


def encode_3d_csv(path, level=21):
    """3D 航线 CSV (lon,lat,alt_m,...) -> 每航点一条 3D 网格码。
    3D 码 = geo_num3d(lat, lng, alt, level), 96 位;
    binary128/bytes16 按 dim=3 (96 位置于 128 位/16 字节末尾 12 字节)。"""
    results = []
    with io.open(path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    for i, row in enumerate(rows):
        try:
            lng = float(row['lon'])
            lat = float(row['lat'])
            alt = float(row['alt_m'])
        except (KeyError, ValueError):
            continue
        code = gc.geo_num3d(lat, lng, alt, level)
        results.append({
            'source': os.path.basename(path),
            'type': 'Point3D',
            'code': '%d-%d' % (code, level),
            'code_level': level,
            'dim': 3,
            'binary128': gc.to_binary128(code, level, dim=3),
            'bytes16_hex': gc.to_bytes16(code, dim=3).hex(),
            'props': dict(row),
        })
    return results


def encode_all(level=21, route='B', data_dir=DATA_DIR):
    """读取 data/ 全部文件并映射为 GeoSOT 网格编码。
    2D 文件经 geofile.encode_file; 文件名含 '3d' 的 CSV 按 3D 航线编码。
    返回: [{'source','type','code','code_level','dim','binary128','bytes16_hex','props'}, ...]"""
    results = []
    for p in collect_input_files(data_dir):
        if is_3d_file(p):
            results.extend(encode_3d_csv(p, level))
            continue
        res = gf.encode_file(p, level, route, with_128=True)
        for fe in res['features']:
            results.append({
                'source': os.path.basename(p),
                'type': fe['type'],
                'code': fe['code'],
                'code_level': fe['code_level'],
                'dim': 2,
                'binary128': fe['binary128'],
                'bytes16_hex': fe['bytes16_hex'],
                'props': fe['props'],
            })
    return results


def write_outputs(results, level=21, route='B', out_dir=OUT_DIR):
    """将编码结果写入 out/: codes.json / codes_128.bin / codes_16bytes.csv。
    返回产物文件路径 dict。
    - codes.json: 完整信息 (含 dim)
    - codes_128.bin: 每条 16 字节大端, 2D 码占低 8 字节, 3D 码占低 12 字节
    - codes_16bytes.csv: 仅一列 bytes16_hex (32 个 hex 字符), 与 bin 逐条对应"""
    os.makedirs(out_dir, exist_ok=True)

    # 1) codes.json
    jpath = os.path.join(out_dir, 'codes.json')
    with io.open(jpath, 'w', encoding='utf-8') as f:
        json.dump({'level': level, 'route': route, 'count': len(results),
                   'codes': results}, f, ensure_ascii=False, indent=1)

    # 2) codes_128.bin: 每条 16 字节大端 (dim 决定码位宽, 高位补 0)
    bpath = os.path.join(out_dir, 'codes_128.bin')
    with open(bpath, 'wb') as f:
        for r in results:
            f.write(gc.to_bytes16(int(r['code'].split('-')[0]), dim=r['dim']))

    # 3) codes_16bytes.csv: 仅一列 bytes16_hex, 与 bin 顺序一一对应
    cpath = os.path.join(out_dir, 'codes_16bytes.csv')
    with io.open(cpath, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['bytes16_hex'])
        for r in results:
            w.writerow([r['bytes16_hex']])
    return {'json': jpath, 'bin': bpath, 'csv': cpath}


def main(argv=None):
    ap = argparse.ArgumentParser(description='data/ 地理数据 -> GeoSOT 网格编码 -> out/')
    ap.add_argument('--level', type=int, default=21, help='目标网格层级 (默认 21, 1" 网格)')
    ap.add_argument('--route', choices=['B', 'A'], default='B', help='编码路线 (默认 B)')
    args = ap.parse_args(argv)
    results = encode_all(args.level, args.route)
    paths = write_outputs(results, args.level, args.route)
    print('已提取 %d 条网格编码 (level=%d, route=%s) -> %s' % (len(results), args.level, args.route, OUT_DIR))
    for fn in sorted(os.listdir(OUT_DIR)):
        fp = os.path.join(OUT_DIR, fn)
        print('  %-22s %10d bytes' % (fn, os.path.getsize(fp)))
    return paths


if __name__ == '__main__':
    main()
