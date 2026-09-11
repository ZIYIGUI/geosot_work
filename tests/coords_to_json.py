# -*- coding: utf-8 -*-
"""
非单元测试: 输入坐标 -> 与 HTTP 接口格式一致的 JSON 响应
============================================================
绕过 HTTP 传输层, 直接调用 app.py 中的 FastAPI handler (传入表单式 dict),
得到与 HTTP 接口返回完全一致的响应体 (server_status:200 + 各接口字段),
按 [{"path","method","status","body"}, ...] 组装并:
  1. 打印全部响应 (JSON, ensure_ascii=False)
  2. 保存到 out/http_like_response.json
  3. 内置非单元校验: 往返一致性 / 邻域数量 / 3D 高度还原 (输出 PASS/FAIL)

用法:
  python coords_to_json.py --lat 39.9102778 --lng 116.3152778 --height 500 --level 21
  python coords_to_json.py                              # 使用默认坐标
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))   # tests/
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'src'))  # src/ 目录
import app as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'out', 'http_like_response.json')


def call(handler, params):
    """调用 handler, 返回 (status, body)。与 HTTP 一致: dict -> 200 body, JSONResponse -> 其状态码/body。"""
    ret = handler(params)
    if isinstance(ret, dict):
        return 200, ret
    try:
        return ret.status_code, json.loads(ret.body)
    except Exception:
        return 500, {'server_status': 500, 'message': 'invalid response'}


def run(lat, lng, height, level):
    """按依赖顺序执行坐标相关接口, 返回结果列表与校验结论。"""
    results = []
    checks = []

    def add(path, handler, params):
        status, body = call(handler, params)
        results.append({'path': path, 'method': 'POST', 'status': status, 'body': body})
        return body

    # 1) 2D 编码: 坐标 -> 网格码 (routeB, point 接口)
    r = add('/geosot/point', A.h_point, {'lat': lat, 'lng': lng, 'geo_level': level})
    code2d = r.get('geo_num')                       # '码-21' (routeB)
    num2d = int(code2d.split('-')[0])
    checks.append(('point 返回 geo_num', bool(code2d)))

    # routeA 码 (center_point/location_point/geo_num2row_col/北斗 期望 routeA 语义)
    routeA_code = A.gc.geo_num_routeA(lat, lng)     # 23 级 routeA 码

    # 2) 码 -> 中心点 / 定位点: 应还原到输入坐标附近 (21 级 1" 格 ~30.9m)
    r = add('/geosot/center_point', A.h_center_point, {'geo_num': routeA_code, 'geo_level': level})
    c = r.get('coordinates')
    d2 = ((c[0] - lng) ** 2 + (c[1] - lat) ** 2) ** 0.5
    checks.append(('center_point 距输入 < 0.001° (21级格内)', d2 < 0.001))
    r = add('/geosot/location_point', A.h_location_point, {'geo_num': routeA_code, 'geo_level': level})
    checks.append(('location_point 左下角存在', bool(r.get('coordinates'))))
    r = add('/geosot/center_point2', A.h_center_point2, {'lat': lat, 'lng': lng, 'geo_level': level})
    checks.append(('center_point2 与 center_point 一致', r.get('coordinates') == c))

    # 3) 行列互转
    r = add('/geosot/lng_lat2row_col', A.h_lng_lat2row_col, {'lat': lat, 'lng': lng, 'geo_level': level})
    row, col = r.get('row'), r.get('col')
    checks.append(('lng_lat2row_col 行列存在', row is not None and col is not None))
    r = add('/geosot/geo_num2row_col', A.h_geo_num2row_col, {'geo_num': routeA_code, 'geo_level': level})
    checks.append(('geo_num2row_col 与经纬度行列一致', (r.get('row'), r.get('col')) == (row, col)))
    r = add('/geosot/row_col2geo_num', A.h_row_col2geo_num, {'row': row, 'col': col, 'geo_level': level})
    checks.append(('row_col2geo_num 还原 routeB 码', int(r.get('geo_num').split('-')[0]) == num2d))
    r = add('/geosot/row_col2lng_lat', A.h_row_col2lng_lat, {'row': row, 'col': col, 'geo_level': level})
    checks.append(('row_col2lng_lat 输出经纬度', r.get('lat') is not None and r.get('lng') is not None))

    # 4) 层级: 子/父 (routeB 码)
    cl = level + 2
    r = add('/geosot/child_geo_num', A.h_child, {'geo_num': code2d, 'geo_level': level, 'child_level': cl})
    kids = r.get('geo_num_list') or []
    checks.append(('child 数量 = 4^(child_level-level)', len(kids) == 4 ** (cl - level)))
    r = add('/geosot/parent_geo_num', A.h_parent, {'geo_num': kids[0], 'geo_level': cl, 'parent_level': level})
    checks.append(('parent 回到 21 级父码', int(r.get('geo_num').split('-')[0]) == num2d))

    # 5) 邻域 (routeB 码)
    r = add('/geosot/adjoin4_geo_num', A.h_adjoin4, {'geo_num': code2d, 'geo_level': level})
    checks.append(('adjoin4 数量=4', len(r.get('geo_num_list') or []) == 4))
    r = add('/geosot/adjoin8_geo_num', A.h_adjoin8, {'geo_num': code2d, 'geo_level': level})
    checks.append(('adjoin8 数量=8', len(r.get('geo_num_list') or []) == 8))

    # 6) 北斗互转 (routeA 码)
    r = add('/geosot/geo_num2beidou_grid_code', A.h_geo_num2beidou, {'geo_num': routeA_code, 'geo_level': 23})
    bcode = r.get('beidou_grid_code')
    checks.append(('geo_num2beidou 输出北斗码', bool(bcode)))
    r = add('/geosot/beidou_grid_code2geo_num', A.h_beidou2geo_num, {'beidou_grid_code': bcode})
    checks.append(('beidou2geo_num 输出 23 级码', r.get('geo_level') == 23))

    # 7) 3D: 经纬高 -> 3D 码 -> 中心点 (高度应还原)
    r = add('/geosot3d/point3d', A.h3_point, {'lat': lat, 'lng': lng, 'height': height, 'geo_level': level})
    code3d = r.get('geo_num')
    checks.append(('point3d 输出 24 位 hex', bool(code3d) and len(code3d) == 24))
    r = add('/geosot3d/center_point3d', A.h3_center_point, {'geo_num': code3d, 'geo_level': level})
    h3 = r.get('height')
    checks.append(('3D 高度还原偏差 < 高度格 (21级≈30.9m)', abs(h3 - height) < 60))
    r = add('/geosot3d/extract_geo_num_2d', A.h3_extract_2d, {'geo_num': code3d, 'geo_level': level})
    checks.append(('3D -> 2D 码存在', bool(r.get('geo_num_2d'))))
    r = add('/geosot3d/adjoin6_geo_num', A.h3_adjoin6, {'geo_num': code3d, 'geo_level': level})
    checks.append(('3D adjoin6 数量=6', len(r.get('geo_num_list') or []) == 6))
    r = add('/geosot3d/adjoin26_geo_num', A.h3_adjoin26, {'geo_num': code3d, 'geo_level': level})
    checks.append(('3D adjoin26 数量=26', len(r.get('geo_num_list') or []) == 26))

    payload = {'request': {'lat': lat, 'lng': lng, 'height': height, 'geo_level': level},
               'count': len(results),
               'results': results}
    return payload, checks


def main(argv=None):
    ap = argparse.ArgumentParser(description='输入坐标 -> 与 HTTP 格式一致的 JSON (非单元测试)')
    ap.add_argument('--lat', type=float, default=39.9102778, help='纬度 (默认 39.9102778)')
    ap.add_argument('--lng', type=float, default=116.3152778, help='经度 (默认 116.3152778)')
    ap.add_argument('--height', type=float, default=500.0, help='高度米 (默认 500)')
    ap.add_argument('--level', type=int, default=21, help='网格层级 (默认 21, 1")')
    ap.add_argument('--out', default=OUT, help='JSON 输出路径')
    args = ap.parse_args(argv)

    payload, checks = run(args.lat, args.lng, args.height, args.level)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    print('== 输入坐标: lat=%.7f lng=%.7f height=%.1fm level=%d' % (args.lat, args.lng, args.height, args.level))
    print('== 非单元校验 (%d 项):' % len(checks))
    for name, ok in checks:
        print('   [%s] %s' % ('PASS' if ok else 'FAIL', name))
    print('== 全部响应已输出 (与 HTTP 返回格式一致, 含 server_status): %s' % args.out)
    for r in payload['results']:
        print('   %-38s -> %s' % (r['path'], json.dumps(r['body'], ensure_ascii=False)[:110]))
    failed = [n for n, ok in checks if not ok]
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
