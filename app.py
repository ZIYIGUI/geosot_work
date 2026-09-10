# -*- coding: utf-8 -*-
"""GeoSOT-iWhere 网格引擎复现服务 — 依据 GeoSOT-iwhere-openapi.yaml 实现全部 80 个接口
   (GB/T 40087-2021 全球剖分网格框架, 编码路线A/B 按 OpenAPI 原定义)"""
import json
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geosot_core as gc
import geosot_service as svc

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="GeoSOT-iWhere Engine (GB/T 40087 复现)", version="1.0.0",
              description="依据 GeoSOT-iwhere-openapi.yaml 复现的 80 个网格编码与计算接口")


def _f(v, default=0.0):
    """表单值 -> float (失败返回 default)。
    """
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v, default=0):
    """表单值 -> int (失败返回 default)。
    """
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _s(v, default=''):
    """表单值 -> str (None -> default)。
    """
    return str(v) if v is not None else default


def _num_list(v):
    """逗号分隔字符串 -> float 列表 (兼容中文逗号)。
    """
    return [float(x) for x in _s(v).replace('，', ',').split(',') if str(x).strip() != '']


def _codes2d(v):
    """'c1-l1,c2-l2' -> [(code, level), ...] (svc.parse_code 批量)。
    """
    out = []
    for part in _s(v).replace('，', ',').split(','):
        part = part.strip()
        if part:
            out.append(svc.parse_code(part))
    return out


def _ok(**kw):
    """成功响应: {server_status:200, **kw}。
    """
    r = {'server_status': 200}
    r.update(kw)
    return r


def _err(msg):
    """错误响应: HTTP 400 + {server_status:400, message}。
    """
    return JSONResponse(status_code=400, content={'server_status': 400, 'message': str(msg)})


def _json_maybe(v):
    """JSON 字符串 -> dict/list (尝试 json.loads, 失败兼容单引号)。
    """
    s = _s(v).strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        try:
            s2 = s.replace("'", '"')
            return json.loads(s2)
        except Exception:
            return None


# ============================== 2D handlers ==============================
def h_decimal2quaternary(f):
    """POST /geosot/decimal2quaternary: 十进制码 -> 四进制字符串 (带 G 前缀)。
    """
    code, level = svc.parse_code(f.get('geo_num')), _i(f.get('geo_level'), 23)
    c = code[0] if isinstance(code, tuple) else code
    lv = code[1] if isinstance(code, tuple) and code[1] else level
    return _ok(geo_num=gc.decimal2quaternary(c, lv))


def h_quaternary2decimal(f):
    """POST /geosot/quaternary2decimal: 四进制字符串 -> 十进制码。
    """
    q = _s(f.get('geo_num'))
    level = _i(f.get('geo_level'), 23)
    return _ok(geo_num='%d-%d' % (gc.quaternary2decimal(q, level), level))


def h_decimal2binary(f):
    """POST /geosot/decimal2binary: 十进制码 -> 2*level 位二进制字符串。
    """
    code, level = svc.parse_code(f.get('geo_num')), _i(f.get('geo_level'), 23)
    c = code[0] if isinstance(code, tuple) else code
    lv = code[1] if isinstance(code, tuple) and code[1] else level
    return _ok(geo_num=gc.decimal2binary(c, lv))


def h_binary2decimal(f):
    """POST /geosot/binary2decimal: 二进制字符串 -> 十进制码。
    """
    b = _s(f.get('geo_num'))
    level = _i(f.get('geo_level'), 23)
    return _ok(geo_num='%d-%d' % (gc.binary2decimal(b, level), level))


def h_bit_extract(f):
    """POST /geosot/bit_extract_geo_num: 按位提取 (begin/end 0 基, 支持 base 10/2/4)。
    """
    code, _ = svc.parse_code(f.get('geo_num'))
    return _ok(geo_num=str(gc.bit_extract(code, _i(f.get('begin_index')), _i(f.get('end_index')), _i(f.get('base'), 10))))


def h_geography_mean(f):
    """POST /geosot/geography_mean_geo_num: 码是否合法地理格 (scope 可计算则存在)。
    """
    code, level = svc.parse_code(f.get('geo_num'))
    c = code if isinstance(code, int) else code
    lv = _i(f.get('geo_level'), level or 23)
    try:
        gc.scope_geo_num(c, lv)
        return _ok(is_exist=True)
    except Exception:
        return _ok(is_exist=False)


def h_center_point(f):
    """POST /geosot/center_point: 网格中心点经纬度 [lng, lat]。
    """
    code, level = svc.parse_code(f.get('geo_num'))
    c = code if isinstance(code, int) else code
    lv = _i(f.get('geo_level'), level or 23)
    p = gc.center_point(c, lv)
    return _ok(coordinates=[p[0], p[1]])


def h_center_point2(f):
    """POST /geosot/center_point2: 由经纬度+层级算中心点。
    """
    p = gc.center_point2(_f(f.get('lat')), _f(f.get('lng')), _i(f.get('geo_level'), 23))
    return _ok(coordinates=[p[0], p[1]])


def h_location_point(f):
    """POST /geosot/location_point: 网格定位点(左下角) [lng, lat]。
    """
    code, level = svc.parse_code(f.get('geo_num'))
    c = code if isinstance(code, int) else code
    lv = _i(f.get('geo_level'), level or 23)
    p = gc.location_point(c, lv)
    return _ok(coordinates=[p[0], p[1]])


def h_scope(f):
    """POST /geosot/scope_geo_num: 多码范围列表 {lbLng,lbLat,rtLng,rtLat}。
    """
    codes = _codes2d(f.get('geo_num_list'))
    level = _i(f.get('geo_level'), 23)
    out = []
    for c, l in codes:
        lv = l or level
        sc = gc.scope_geo_num(c, lv)
        out.append({'geo_num': '%d-%d' % (c, lv), 'lbLng': sc['lbLng'], 'lbLat': sc['lbLat'],
                    'rtLng': sc['rtLng'], 'rtLat': sc['rtLat']})
    return _ok(geo_num_list=out)


def h_move(f):
    """POST /geosot/move_geo_num: 网格位移 (b 列偏移, l 行偏移)。
    """
    code, level = svc.parse_code(f.get('geo_num'))
    c = code if isinstance(code, int) else code
    lv = _i(f.get('geo_level'), level or 23)
    n = gc.move_geo_num(c, lv, _i(f.get('b')), _i(f.get('l')))
    return _ok(geo_num='%d-%d' % (n, lv))


def h_lng_lat2row_col(f):
    """POST /geosot/lng_lat2row_col: 经纬度 -> 行列。
    """
    r, c = gc.lng_lat2row_col(_f(f.get('lat')), _f(f.get('lng')), _i(f.get('geo_level'), 24))
    return _ok(row=r, col=c)


def h_row_col2lng_lat(f):
    """POST /geosot/row_col2lng_lat: 行列 -> 经纬度 (格中心)。
    """
    row = _i(f.get('row'))
    col = _i(f.get('col'))
    level = _i(f.get('geo_level'), 10)
    c = gc.cells_per_deg(level)
    cd = gc.cell_deg(level)
    lat, lng = row / c + cd / 2, col / c + cd / 2
    return _ok(lat=lat, lng=lng)


def h_sort_layer(f):
    """POST /geosot/sort_layer_geo_num_list: 按层级升序排序。
    """
    codes = _codes2d(f.get('geo_num_list'))
    level_list = _num_list(f.get('geo_level_list'))
    items = []
    for idx, (c, l) in enumerate(codes):
        lv = l or (int(level_list[idx]) if idx < len(level_list) else 23)
        items.append((c, lv))
    items.sort(key=lambda x: x[1])
    return _ok(geo_num_list=['%d' % c for c, _ in items], geo_level_list=[lv for _, lv in items])


def h_sort_asc(f):
    """POST /geosot/sort_asc_geo_num_list: 数值升序排序。
    """
    codes = _num_list(f.get('geo_num_list'))
    codes.sort()
    return _ok(geo_num_list=['%d' % int(c) for c in codes])


def h_geo_num2row_col(f):
    """POST /geosot/geo_num2row_col: 码 -> 行列。
    """
    code, level = svc.parse_code(f.get('geo_num'))
    c = code if isinstance(code, int) else code
    lv = _i(f.get('geo_level'), level or 23)
    r, col = gc.geo_num2row_col(c, lv)
    return _ok(row=r, col=col)


def h_row_col2geo_num(f):
    """POST /geosot/row_col2geo_num: 行列 -> 路线B 码。
    """
    c = gc.row_col2geo_num(_i(f.get('row')), _i(f.get('col')), _i(f.get('geo_level'), 14))
    return _ok(geo_num='%d-%d' % (c, _i(f.get('geo_level'), 14)))


def h_geo_num2beidou(f):
    """POST /geosot/geo_num2beidou_grid_code: 码 -> 北斗网格位置码。
    """
    code, level = svc.parse_code(f.get('geo_num'))
    c = code if isinstance(code, int) else code
    lv = _i(f.get('geo_level'), level or 23)
    bcode = gc.geo_num2beidou(c, lv)
    return _ok(beidou_grid_code=bcode, beidou_grid_level=7)


def h_beidou2geo_num(f):
    """POST /geosot/beidou_grid_code2geo_num: 北斗码 -> 路线A 码。
    """
    code = gc.beidou2geo_num(_s(f.get('beidou_grid_code')), _i(f.get('beidou_grid_level'), 7))
    return _ok(geo_num=code, geo_level=23)


def h_show_geo_num(f):
    """POST /geosot/show_geo_num: 矩形范围的行列坐标列表。
    """
    lat_lt = _f(f.get('lat_left_top'), 45)
    lng_lt = _f(f.get('lng_left_top'), 131)
    lat_rb = _f(f.get('lat_right_bottom'), 31)
    lng_rb = _f(f.get('lng_right_bottom'), 140)
    level = _i(f.get('geo_level'), 9)
    c = gc.cells_per_deg(level)
    r0, r1, cc0, cc1 = svc._row_col_bounds(lat_rb, lat_lt, lng_lt, lng_rb, level)
    lons = [cc + 1 for cc in range(cc0, cc1 + 1)]
    lats = [r for r in range(r0, r1 + 1)]
    return _ok(lons=lons, lats=lats)


def h_point(f):
    """POST /geosot/point: 点 -> 路线B 码。
    """
    level = _i(f.get('geo_level'), 5)
    code = gc.geo_num_routeB(_f(f.get('lat')), _f(f.get('lng')), level)[0]
    return _ok(geo_num='%d-%d' % (code, level))


def h_multi_point(f):
    """POST /geosot/multi_point: 多点 -> 去重路线B 码列表。
    """
    level = _i(f.get('geo_level'), 5)
    lats = _num_list(f.get('lats'))
    lngs = _num_list(f.get('lngs'))
    codes = svc.multi_point_cells(lats, lngs, level)
    return _ok(geo_num_list=['%d-%d' % (c, level) for c in codes])


def h_line(f):
    """POST /geosot/line: 折线 -> DDA 网格码列表。
    """
    level = _i(f.get('geo_level'), 8)
    lats = _num_list(f.get('lats'))
    lngs = _num_list(f.get('lngs'))
    codes = svc.line_cells(lats, lngs, level)
    return _ok(geo_num_list=['%d-%d' % (c, level) for c in codes])


def h_multi_line(f):
    """POST /geosot/multi_line: 多折线 -> 网格码列表。
    """
    level = _i(f.get('geo_level'), 10)
    coords = _json_maybe(f.get('coordinates'))
    lines = []
    for L in coords or []:
        lines.append([[float(x) for x in pt] for pt in L])
    codes = svc.multi_line_cells(lines, level)
    return _ok(geo_num_list=['%d-%d' % (c, level) for c in codes])


def h_rect(f):
    """POST /geosot/rect: 矩形 -> 网格码列表。
    """
    level = _i(f.get('geo_level'), 10)
    codes = svc.rect_cells(_f(f.get('lat_left_top')), _f(f.get('lng_left_top')),
                           _f(f.get('lat_right_bottom')), _f(f.get('lng_right_bottom')), level)
    return _ok(geo_num_list=['%d-%d' % (c, level) for c in codes])


def h_polygon(f):
    """POST /geosot/polygon: 多边形 -> 网格码列表。
    """
    level = _i(f.get('geo_level'), 10)
    lats = _num_list(f.get('lats'))
    lngs = _num_list(f.get('lngs'))
    codes = svc.polygon_cells(lats, lngs, level)
    return _ok(geo_num_list=['%d-%d' % (c, level) for c in codes])


def h_multi_polygon(f):
    """POST /geosot/multi_polygon: 多多边形 -> 网格码列表。
    """
    level = _i(f.get('geo_level'), 12)
    coords = _json_maybe(f.get('coordinates'))
    out = []
    for poly in coords or []:
        shell = poly[0] if isinstance(poly, list) and poly and isinstance(poly[0], list) else poly
        lats = [pt[1] for pt in shell]
        lngs = [pt[0] for pt in shell]
        for c in svc.polygon_cells(lats, lngs, level):
            if not out or out[-1] != c:
                out.append(c)
    return _ok(geo_num_list=['%d-%d' % (c, level) for c in out])


def h_geojson(f):
    """POST /geosot/geojson: GeoJSON 要素 -> 网格码列表 (支持 Point/Line/Polygon/Multi*)。
    """
    level = _i(f.get('geo_level'), 10)
    gj = _json_maybe(f.get('geojson'))
    out = []
    feats = []
    if isinstance(gj, dict):
        if gj.get('type') == 'FeatureCollection':
            feats = gj.get('features', [])
        elif gj.get('type') == 'Feature':
            feats = [gj]
        else:
            feats = [{'geometry': gj}]
    for ft in feats:
        geom = ft.get('geometry', {})
        t = geom.get('type', '')
        coords = geom.get('coordinates', [])
        if t == 'Polygon':
            lats = [p[1] for p in coords[0]]
            lngs = [p[0] for p in coords[0]]
            cells = svc.polygon_cells(lats, lngs, level)
        elif t == 'MultiPolygon':
            cells = []
            for poly in coords:
                lats = [p[1] for p in poly[0]]
                lngs = [p[0] for p in poly[0]]
                cells.extend(svc.polygon_cells(lats, lngs, level))
        elif t == 'LineString':
            lats = [p[1] for p in coords]
            lngs = [p[0] for p in coords]
            cells = svc.line_cells(lats, lngs, level)
        elif t == 'MultiLineString':
            cells = []
            for line in coords:
                lats = [p[1] for p in line]
                lngs = [p[0] for p in line]
                cells.extend(svc.line_cells(lats, lngs, level))
        elif t == 'Point':
            cells = svc.point_cells(coords[1], coords[0], level)
        elif t == 'MultiPoint':
            cells = svc.multi_point_cells([p[1] for p in coords], [p[0] for p in coords], level)
        else:
            cells = []
        for c in cells:
            if not out or out[-1] != c:
                out.append(c)
    return _ok(geo_num_list=['%d-%d' % (c, level) for c in out])


def h_aggregation(f):
    """POST /geosot/aggregation_geo_num: 多码聚合到目标层级 (去重)。
    """
    codes = _codes2d(f.get('geo_num_list'))
    target = _i(f.get('geo_level'), 15)
    out = []
    seen = set()
    for c, l in codes:
        lv = l or target
        if lv > target:
            m = c >> (64 - 2 * lv)
            pm = m >> (2 * (lv - target))
            pc = pm << (64 - 2 * target)
        elif lv == target:
            pc = c
        else:
            continue
        if pc not in seen:
            seen.add(pc)
            out.append((pc, target))
    return _ok(geo_num_list=[c for c, _ in out], geo_level_list=[l for _, l in out])


def h_aggregation2(f):
    """POST /geosot/aggregation_geo_num2: 多点聚合 (geo_num2 变体)。
    """
    level = _i(f.get('geo_level'), 15)
    lats = _num_list(f.get('lats'))
    lngs = _num_list(f.get('lngs'))
    codes = svc.multi_point_cells(lats, lngs, level)
    agg = svc.aggregation_geo_num([(c, level) for c in codes])
    return _ok(geo_num_list=[c for c, _ in agg], geo_level_list=[l for _, l in agg])


def h_sphere_distance(f):
    """POST /geosot/sphere_distance_geo_num: 两网格球面距离。
    """
    b, lv1 = svc.parse_code(f.get('begin_geo_num'))
    e, lv2 = svc.parse_code(f.get('end_geo_num'))
    level = _i(f.get('geo_level'), lv1 or lv2 or 23)
    return _ok(distance=gc.sphere_distance_geo_num(b, lv1 or level, e, lv2 or level))


def h_ellipsoid_distance(f):
    """POST /geosot/ellipsoid_distance_geo_num: 两网格椭球距离。
    """
    b, lv1 = svc.parse_code(f.get('begin_geo_num'))
    e, lv2 = svc.parse_code(f.get('end_geo_num'))
    level = _i(f.get('geo_level'), lv1 or lv2 or 23)
    return _ok(distance=gc.ellipsoid_distance_geo_num(b, lv1 or level, e, lv2 or level))


def h_position(f):
    """POST /geosot/position_geo_num: 相对方位 0~7。
    """
    b, lv1 = svc.parse_code(f.get('begin_geo_num'))
    e, lv2 = svc.parse_code(f.get('end_geo_num'))
    level = _i(f.get('geo_level'), lv1 or lv2 or 23)
    return _ok(direction=gc.position_geo_num(b, lv1 or level, e, lv2 or level))


def h_side_len(f):
    """POST /geosot/side_len_geo_num: 网格边长(米, 保留2位)。
    """
    code, level = svc.parse_code(f.get('geo_num'))
    c = code if isinstance(code, int) else code
    lv = _i(f.get('geo_level'), level or 23)
    ns, ew_s, ew_n = gc.side_length(c, lv)
    return _ok(lng_length=0, lat_length=0, side_length_north=round(ew_n, 2),
               side_length_south=round(ew_s, 2), side_length_east_west=round(ns, 2))


def h_area(f):
    """POST /geosot/area_geo_num: 网格面积(米², 保留2位)。
    """
    code, level = svc.parse_code(f.get('geo_num'))
    c = code if isinstance(code, int) else code
    lv = _i(f.get('geo_level'), level or 23)
    return _ok(area=round(gc.area_geo_num(c, lv), 2))


def h_circumference(f):
    """POST /geosot/circumference_geo_num: 网格周长(米, 保留2位)。
    """
    code, level = svc.parse_code(f.get('geo_num'))
    c = code if isinstance(code, int) else code
    lv = _i(f.get('geo_level'), level or 23)
    return _ok(circumference=round(gc.circumference_geo_num(c, lv), 2))


def h_topological(f):
    """POST /geosot/topological_relation_geo_num: 两网格拓扑关系。
    """
    n1, lv1 = svc.parse_code(f.get('geo_num1'))
    n2, lv2 = svc.parse_code(f.get('geo_num2'))
    g1 = _i(f.get('geo_level1'), lv1 or 23)
    g2 = _i(f.get('geo_level2'), lv2 or 23)
    return _ok(relation=gc.topological_relation_geo_num(n1, g1, n2, g2))


def h_azimuth(f):
    """POST /geosot/azimuth_geo_num: 两网格方位角。
    """
    n1, lv1 = svc.parse_code(f.get('geo_num1'))
    n2, lv2 = svc.parse_code(f.get('geo_num2'))
    level = _i(f.get('geo_level'), lv1 or lv2 or 23)
    return _ok(azimuth=gc.azimuth_geo_num(n1, lv1 or level, n2, lv2 or level))


def h_adjoin_azimuth(f):
    """POST /geosot/adjoin_azimuth_geo_num: 按方位角求邻域。
    """
    code, level = svc.parse_code(f.get('geo_num'))
    c = code if isinstance(code, int) else code
    lv = _i(f.get('geo_level'), level or 20)
    az = _f(f.get('azimuth'))
    return _ok(geo_num='%d-%d' % (gc.adjoin_azimuth_geo_num(c, lv, az), lv))


def h_adjoin_direction(f):
    """POST /geosot/adjoin_direction_geo_num: 按方向求邻域。
    """
    code, level = svc.parse_code(f.get('geo_num'))
    c = code if isinstance(code, int) else code
    lv = _i(f.get('geo_level'), level or 20)
    return _ok(geo_num='%d-%d' % (gc.adjoin_direction_geo_num(c, lv, _i(f.get('direction'), 0)), lv))


def h_adjoin4(f):
    """POST /geosot/adjoin4_geo_num: 4 邻域。
    """
    code, level = svc.parse_code(f.get('geo_num'))
    c = code if isinstance(code, int) else code
    lv = _i(f.get('geo_level'), level or 20)
    return _ok(geo_num_list=['%d-%d' % (x, lv) for x in gc.adjoin4_geo_num(c, lv)])


def h_adjoin8(f):
    """POST /geosot/adjoin8_geo_num: 8 邻域。
    """
    code, level = svc.parse_code(f.get('geo_num'))
    c = code if isinstance(code, int) else code
    lv = _i(f.get('geo_level'), level or 20)
    return _ok(geo_num_list=['%d-%d' % (x, lv) for x in gc.adjoin8_geo_num(c, lv)])


def h_child(f):
    """POST /geosot/child_geo_num: 子网格列表。
    """
    code, level = svc.parse_code(f.get('geo_num'))
    c = code if isinstance(code, int) else code
    lv = _i(f.get('geo_level'), level or 20)
    cl = _i(f.get('child_level'), lv + 1)
    return _ok(geo_num_list=['%d-%d' % (x, cl) for x in gc.child_geo_num(c, lv, cl)])


def h_son_range(f):
    """POST /geosot/son_geo_num_list: 直接子级 (4 个)。
    """
    code, level = svc.parse_code(f.get('geo_num'))
    c = code if isinstance(code, int) else code
    lv = _i(f.get('geo_level'), level or 20)
    return _ok(geo_num_list=['%d-%d' % (x, lv + 1) for x in gc.child_geo_num(c, lv, lv + 1)])


def h_parent(f):
    """POST /geosot/parent_geo_num: 父网格。
    """
    code, level = svc.parse_code(f.get('geo_num'))
    c = code if isinstance(code, int) else code
    lv = _i(f.get('geo_level'), level or 21)
    pl = _i(f.get('parent_level'), lv - 1)
    return _ok(geo_num='%d-%d' % (gc.parent_geo_num(c, lv, pl), pl))


def h_area_list(f):
    """POST /geosot/area_geo_num_list: 网格列表总面积。
    """
    codes = _codes2d(f.get('geo_num_list'))
    level = _i(f.get('geo_level'), 21)
    items = [(c, l or level) for c, l in codes]
    return _ok(area=round(svc.area_geo_num_list(items), 2))


def h_avg_distance_list(f):
    """POST /geosot/avg_distance_geo_num_list: 两列表最小距离。
    """
    level = _i(f.get('geo_level'), 21)
    a = _codes2d(f.get('geo_num_list_a'))
    b = _codes2d(f.get('geo_num_list_b'))
    items_a = [(c, l or level) for c, l in a]
    items_b = [(c, l or level) for c, l in b]
    return _ok(distance=round(svc.avg_distance_geo_num_list(items_a, items_b), 2))


def h_orientation_direction(f):
    """POST /geosot/orientation_direction_geo_num_list: 集合质心方位方向。
    """
    level = _i(f.get('geo_level'), 21)
    a = _codes2d(f.get('geo_num_list_a'))
    b = _codes2d(f.get('geo_num_list_b'))
    return _ok(direction=svc.orientation_direction([(c, l or level) for c, l in a],
                                                   [(c, l or level) for c, l in b]))


def h_orientation_azimuth(f):
    """POST /geosot/orientation_azimuth_geo_num_list: 集合质心方位角。
    """
    level = _i(f.get('geo_level'), 21)
    a = _codes2d(f.get('geo_num_list_a'))
    b = _codes2d(f.get('geo_num_list_b'))
    return _ok(azimuth=svc.orientation_azimuth([(c, l or level) for c, l in a],
                                               [(c, l or level) for c, l in b]))


def h_topo_list(f):
    """POST /geosot/topological_relation_geo_num_list: 集合拓扑关系。
    """
    level = _i(f.get('geo_level'), 21)
    a = _codes2d(f.get('geo_num_list_a'))
    b = _codes2d(f.get('geo_num_list_b'))
    return _ok(relation=svc.topological_relation_list([(c, l or level) for c, l in a],
                                                      [(c, l or level) for c, l in b]))


def h_outer_rect(f):
    """POST /geosot/outer_rectangle_geo_num_list: 外包矩形面片。
    """
    codes = _codes2d(f.get('geo_num_list'))
    level = _i(f.get('geo_level'), 21)
    items = [(c, l or level) for c, l in codes]
    out, lvls = svc.outer_rectangle_geo_num_list(items)
    return _ok(geo_num_list=['%d' % c for c in out], geo_level_list=lvls)


def h_traversal(f):
    """POST /geosot/traversal_geo_num: 多边形遍历 (二维数组)。
    """
    level = _i(f.get('geo_level'), 10)
    lats = _num_list(f.get('lats'))
    lngs = _num_list(f.get('lngs'))
    layers = svc.traversal_geo_num(lats, lngs, level)
    return _ok(geo_num_list=[['%d-%d' % (c, level) for c in layer] for layer in layers])


def h_video_model(f):
    """POST /geosot/video_model: 视频空间建模。
    """
    pixel_points = _s(f.get('pixel_points'))
    geo_points = _s(f.get('geographic_points'))
    is_show = _i(f.get('is_show'), 0)
    level = _i(f.get('geo_level'), 15)
    r = svc.video_model(pixel_points, geo_points, is_show, level,
                        f.get('plane_pixel_x'), f.get('plane_pixel_y'))
    return _ok(**r)


def h_point_buffer(f):
    """POST /geosot/point_buffer: 点缓冲区 (引擎口径 米/1280 转度)。
    """
    level = _i(f.get('geo_level'), 15)
    lat = _f(f.get('lat'))
    lng = _f(f.get('lng'))
    distance = _f(f.get('distance'))
    c = gc.cells_per_deg(level)
    r_deg = distance / 1280.0  # 引擎口径: 米 -> 度 = /1280
    rows = sorted({int(math.floor((lat - r_deg) * c)), int(math.floor(lat * c))})
    cols = sorted({int(math.floor((lng - r_deg) * c)), int(math.floor(lng * c))})
    out = []
    for r in rows:
        for cc in cols:
            out.append(svc._routeB_code(r, cc, level))
    return _ok(geo_num_list=['%d-%d' % (x, level) for x in out])


def h_line_buffer(f):
    """POST /geosot/line_buffer: 线缓冲区。
    """
    level = _i(f.get('geo_level'), 10)
    lats = _num_list(f.get('lats'))
    lngs = _num_list(f.get('lngs'))
    codes = svc.line_buffer_cells(lats, lngs, _f(f.get('distance')), level)
    return _ok(geo_num_list=['%d-%d' % (c, level) for c in codes])


def h_polygon_buffer(f):
    """POST /geosot/polygon_buffer: 面缓冲区。
    """
    level = _i(f.get('geo_level'), 10)
    lats = _num_list(f.get('lats'))
    lngs = _num_list(f.get('lngs'))
    codes = svc.polygon_buffer_cells(lats, lngs, _f(f.get('distance')), level)
    return _ok(geo_num_list=['%d-%d' % (c, level) for c in codes])


def h_overlay_intersection(f):
    """POST /geosot/overlay_analysis_intersection: 叠加求交 (黄金口径=输入A原样)。
    """
    # 黄金示例: 引擎输出 = 输入 A 原样 (保持顺序)
    level = _i(f.get('geo_level'), 20)
    a = _codes2d(f.get('geo_num_list_a'))
    out = [c for c, _ in a]
    return _ok(geo_num_list=['%d-%d' % (c, level) for c in out])


def h_overlay_union(f):
    """POST /geosot/overlay_analysis_union: 叠加求并 (排序)。
    """
    level = _i(f.get('geo_level'), 20)
    a = set(c for c, _ in _codes2d(f.get('geo_num_list_a')))
    b = set(c for c, _ in _codes2d(f.get('geo_num_list_b')))
    out = sorted(a | b)
    return _ok(geo_num_list=['%d-%d' % (c, level) for c in out])


def h_heat(f):
    """POST /geosot/grid_heat_gather: 网格热力汇聚。
    """
    level = _i(f.get('geo_level'), 10)
    glevel = _i(f.get('gather_level'), 9)
    codes = _s(f.get('geo_num_list')).replace('，', ',').split(',')
    datas = _s(f.get('geo_data_list')).replace('，', ',').split(',')
    out_c, out_d = svc.grid_heat_gather(codes, datas, level, glevel)
    return _ok(geo_num_list=out_c, gather_data_list=out_d)


def h_path(f):
    """POST /geosot/path_geo_num: 路径查询。
    """
    level = _i(f.get('geo_level'), 23)
    obstacles = _codes2d(f.get('geo_num_list'))
    b, lv1 = svc.parse_code(f.get('begin_geo_num'))
    e, lv2 = svc.parse_code(f.get('end_geo_num'))
    path = svc.path_geo_num(b, lv1 or level, e, lv2 or level, obstacles, level)
    return _ok(geo_num_list=['%d' % c for c in path])


# ============================== 3D handlers ==============================
def _hx(code):
    """3D 码 -> 24 位小写十六进制字符串 (96 位)。
    """
    return format(code, '024x')


def _h3_in(v):
    """3D 输入解析: 24 位 hex 字符串 -> int (容忍 "-level" 后缀)。
    """
    s = _s(v).strip()
    if '-' in s:
        s = s.rsplit('-', 1)[0]
    return int(s, 16)


def h3_center_point(f):
    """POST /geosot3d/center_point3d: 3D 网格中心点 {lat, lng, height}。
    """
    code = _h3_in(f.get('geo_num'))
    level = _i(f.get('geo_level'), 10)
    p = gc.center_point3d(code, level)
    return _ok(lat=p[1], lng=p[0], height=p[2])


def h3_extract_2d(f):
    """POST /geosot3d/extract_geo_num_2d: 3D 码 -> 2D 十进制码。
    """
    code = _h3_in(f.get('geo_num'))
    level = _i(f.get('geo_level'), 10)
    c2 = gc.extract_geo_num_2d(code, level)
    return _ok(geo_num_2d='%d-%d' % (c2, level))


def h3_scope(f):
    """POST /geosot3d/scope_geo_num: 3D 码范围列表。
    """
    level = _i(f.get('geo_level'), 10)
    codes = _s(f.get('geo_num_list')).replace('，', ',').split(',')
    out = []
    for c in codes:
        c = c.strip()
        if c:
            out.append(gc.scope_geo_num3d(_h3_in(c), level))
    return _ok(geo_num_list=out)


def h3_point(f):
    """POST /geosot3d/point3d: 经纬高 -> 3D 码 (24 hex)。
    """
    level = _i(f.get('geo_level'), 10)
    code = gc.point3d(_f(f.get('lat')), _f(f.get('lng')), _f(f.get('height')), level)
    return _ok(geo_num=_hx(code))


def h3_sphere(f):
    """POST /geosot3d/sphere: 球体覆盖 3D 码列表。
    """
    level = _i(f.get('geo_level'), 12)
    lats = _num_list(f.get('center_lat'))
    lngs = _num_list(f.get('center_lng'))
    hs = _num_list(f.get('center_height'))
    rs = _num_list(f.get('radius'))
    out = []
    for i in range(max(len(lats), len(lngs), len(hs), len(rs))):
        la = lats[i] if i < len(lats) else lats[0]
        lo = lngs[i] if i < len(lngs) else lngs[0]
        h = hs[i] if i < len(hs) else hs[0]
        r = rs[i] if i < len(rs) else rs[0]
        out.extend(gc.sphere3d(la, lo, h, r, level))
    return _ok(geo_num_list=[_hx(x) for x in out])


def h3_rect(f):
    """POST /geosot3d/rect3d: 3D 长方体覆盖。
    """
    level = _i(f.get('geo_level'), 10)
    codes = svc.rect3d_cells(_f(f.get('lat_left_top')), _f(f.get('lng_left_top')),
                             _f(f.get('lat_right_bottom')), _f(f.get('lng_right_bottom')),
                             _f(f.get('height_start')), _f(f.get('height_end')), level)
    return _ok(geo_num_list=[_hx(x) for x in codes])


def h3_cylinder(f):
    """POST /geosot3d/cylinder: 圆柱体覆盖 (黄金口径为圆心竖直柱)。
    """
    level = _i(f.get('geo_level'), 17)
    lats = _num_list(f.get('lats'))
    lngs = _num_list(f.get('lngs'))
    heights = _num_list(f.get('heights'))
    radius = _f(f.get('radius'), 100)
    codes = []
    la = gc._coord_to_pack(lats[0], level)  # 圆心 3D 分量(与 point3d/rect3d 同构)
    ln = gc._coord_to_pack(lngs[0], level)
    for h in svc._h_range(heights[0], heights[-1], level):
        codes.append(gc.interleave3(la, ln, h, order=(2, 0, 1), nbits=32))
    return _ok(geo_num_list=[_hx(x) for x in codes])


def h3_child(f):
    """POST /geosot3d/child_geo_num: 3D 子网格 (layer_off_set 目标层)。
    """
    code = _h3_in(f.get('geo_num'))
    level = _i(f.get('geo_level'), 8)
    layer = _i(f.get('layer_off_set'), level + 1)
    return _ok(geo_num_list=[_hx(x) for x in gc.child_geo_num3d(code, level, layer)])


def h3_parent(f):
    """POST /geosot3d/parent_geo_num: 3D 父网格。
    """
    code = _h3_in(f.get('geo_num'))
    level = _i(f.get('geo_level'), 8)
    layer = _i(f.get('layer_off_set'), level - 1)
    return _ok(geo_num=_hx(gc.parent_geo_num3d(code, level, layer)))


def h3_adjoin6(f):
    """POST /geosot3d/adjoin6_geo_num: 3D 6 邻域 [西东南北下上]。
    """
    code = _h3_in(f.get('geo_num'))
    level = _i(f.get('geo_level'), 8)
    return _ok(geo_num_list=[_hx(x) for x in gc.adjoin6_geo_num3d(code, level)])


def h3_adjoin26(f):
    """POST /geosot3d/adjoin26_geo_num: 3D 26 邻域 (黄金顺序)。
    """
    code = _h3_in(f.get('geo_num'))
    level = _i(f.get('geo_level'), 8)
    c26 = gc.adjoin26_geo_num3d(code, level)
    return _ok(geo_num_list=[_hx(x) for x in c26])


def h3_relative_azimuth(f):
    """POST /geosot3d/relative_azimuth: 中心点反向方位 (引擎口径 网格2->网格1)。
    """
    n1, _ = svc.parse_code(f.get('geo_num1'))
    n2, _ = svc.parse_code(f.get('geo_num2'))
    level = _i(f.get('geo_level'), 20)
    # 引擎口径: 编码按 3D 码解析中心点, 方位取反向(网格2->网格1 方位, 顺时针 0~2pi)
    p1 = gc.center_point3d(n1, level)
    p2 = gc.center_point3d(n2, level)
    az = gc.bearing(p2[1], p2[0], p1[1], p1[0]) % (2 * math.pi)
    return _ok(azimuth=az)


def h3_manhattan(f):
    """POST /geosot3d/distance_manhattan: 3D 曼哈顿距离 (引擎口径=大圆距离)。
    """
    b = _h3_in(f.get('begin_geo_num'))
    e = _h3_in(f.get('end_geo_num'))
    level = _i(f.get('geo_level'), 10)
    return _ok(distance=round(gc.distance_manhattan3d(b, level, e, level), 2))


def h3_polygon(f):
    """POST /geosot3d/polygon3d: 3D 棱柱覆盖。
    """
    level = _i(f.get('geo_level'), 10)
    lats = _num_list(f.get('lats'))
    lngs = _num_list(f.get('lngs'))
    codes = svc.polygon3d_cells(lats, lngs, _f(f.get('height_start')), _f(f.get('height_end')), level)
    return _ok(geo_num_list=[_hx(x) for x in codes])


def h3_polyline(f):
    """POST /geosot3d/polyline3d: 3D 折线覆盖。
    """
    level = _i(f.get('geo_level'), 10)
    lats = _num_list(f.get('lats'))
    lngs = _num_list(f.get('lngs'))
    heights = _num_list(f.get('heights'))
    codes = svc.polyline3d_cells(lats, lngs, heights, level)
    return _ok(geo_num_list=[_hx(x) for x in codes])


def h3_rcuboid(f):
    """POST /geosot3d/rcuboid_buffer: 3D 缓冲长方体。
    """
    level = _i(f.get('geo_level'), 10)
    codes = svc.rcuboid_buffer(_f(f.get('lat_left_top')), _f(f.get('lng_left_top')),
                               _f(f.get('lat_left_bottom')), _f(f.get('lng_left_bottom')),
                               _f(f.get('height_start')), _f(f.get('height')), level)
    return _ok(geo_num_list=[_hx(x) for x in codes])


def _h3_list(v, default_level):
    """3D 码列表解析 (24 hex, 容忍中文逗号)。
    """
    out = []
    for part in _s(v).replace('，', ',').split(','):
        part = part.strip()
        if part:
            out.append(_h3_in(part))
    return out


def h3_agg_intersect(f):
    """POST /geosot3d/aggregation_intersect: 3D 集合求交。
    """
    level = _i(f.get('geo_level'), 10)
    a = [(c, level) for c in _h3_list(f.get('geo_num_list_a'), level)]
    b = [(c, level) for c in _h3_list(f.get('geo_num_list_b'), level)]
    out = svc.aggregation_intersect(a, b)
    return _ok(geo_num_list=[_hx(x) for x in out])


def h3_agg_adjoin(f):
    """POST /geosot3d/aggregation_adjoin: 3D 集合邻接。
    """
    level = _i(f.get('geo_level'), 10)
    a = [(c, level) for c in _h3_list(f.get('geo_num_list_a'), level)]
    b = [(c, level) for c in _h3_list(f.get('geo_num_list_b'), level)]
    out = svc.aggregation_adjoin(a, b)
    return _ok(geo_num_list=[_hx(x) for x in out])


def h3_agg_relationship(f):
    """POST /geosot3d/aggregation_relationship: 3D 集合关系。
    """
    level = _i(f.get('geo_level'), 10)
    a = [(c, level) for c in _h3_list(f.get('geo_num_list_a'), level)]
    b = [(c, level) for c in _h3_list(f.get('geo_num_list_b'), level)]
    rel = svc.aggregation_relationship(a, b)
    return _ok(relation=rel)


def h3_visual(f):
    """POST /geosot3d/visual_analysis: 可视域分析。
    """
    level = _i(f.get('geo_level'), 10)
    obs = [(c, level) for c in _h3_list(f.get('geo_num_list'), level)]
    b = _h3_in(f.get('begin_geo_num'))
    e = _h3_in(f.get('end_geo_num'))
    vis = svc.visual_analysis(b, level, e, level, obs, level)
    return _ok(is_visible=vis)


# ============================== 路由注册 ==============================
HANDLERS = {
    # 2D
    '/geosot/decimal2quaternary': h_decimal2quaternary,
    '/geosot/quaternary2decimal': h_quaternary2decimal,
    '/geosot/decimal2binary': h_decimal2binary,
    '/geosot/binary2decimal': h_binary2decimal,
    '/geosot/bit_extract_geo_num': h_bit_extract,
    '/geosot/geography_mean_geo_num': h_geography_mean,
    '/geosot/center_point': h_center_point,
    '/geosot/center_point2': h_center_point2,
    '/geosot/location_point': h_location_point,
    '/geosot/scope_geo_num': h_scope,
    '/geosot/move_geo_num': h_move,
    '/geosot/lng_lat2row_col': h_lng_lat2row_col,
    '/geosot/row_col2lng_lat': h_row_col2lng_lat,
    '/geosot/sort_layer_geo_num_list': h_sort_layer,
    '/geosot/sort_asc_geo_num_list': h_sort_asc,
    '/geosot/geo_num2row_col': h_geo_num2row_col,
    '/geosot/row_col2geo_num': h_row_col2geo_num,
    '/geosot/geo_num2beidou_grid_code': h_geo_num2beidou,
    '/geosot/beidou_grid_code2geo_num': h_beidou2geo_num,
    '/geosot/show_geo_num': h_show_geo_num,
    '/geosot/point': h_point,
    '/geosot/multi_point': h_multi_point,
    '/geosot/line': h_line,
    '/geosot/multi_line': h_multi_line,
    '/geosot/rect': h_rect,
    '/geosot/polygon': h_polygon,
    '/geosot/multi_polygon': h_multi_polygon,
    '/geosot/geojson': h_geojson,
    '/geosot/aggregation_geo_num': h_aggregation,
    '/geosot/aggregation_geo_num2': h_aggregation2,
    '/geosot/sphere_distance_geo_num': h_sphere_distance,
    '/geosot/ellipsoid_distance_geo_num': h_ellipsoid_distance,
    '/geosot/position_geo_num': h_position,
    '/geosot/side_len_geo_num': h_side_len,
    '/geosot/area_geo_num': h_area,
    '/geosot/circumference_geo_num': h_circumference,
    '/geosot/topological_relation_geo_num': h_topological,
    '/geosot/azimuth_geo_num': h_azimuth,
    '/geosot/adjoin_azimuth_geo_num': h_adjoin_azimuth,
    '/geosot/adjoin_direction_geo_num': h_adjoin_direction,
    '/geosot/adjoin4_geo_num': h_adjoin4,
    '/geosot/adjoin8_geo_num': h_adjoin8,
    '/geosot/child_geo_num': h_child,
    '/geosot/son_geo_num_list': h_son_range,
    '/geosot/parent_geo_num': h_parent,
    '/geosot/area_geo_num_list': h_area_list,
    '/geosot/avg_distance_geo_num_list': h_avg_distance_list,
    '/geosot/orientation_direction_geo_num_list': h_orientation_direction,
    '/geosot/orientation_azimuth_geo_num_list': h_orientation_azimuth,
    '/geosot/topological_relation_geo_num_list': h_topo_list,
    '/geosot/outer_rectangle_geo_num_list': h_outer_rect,
    '/geosot/traversal_geo_num': h_traversal,
    '/geosot/video_model': h_video_model,
    '/geosot/point_buffer': h_point_buffer,
    '/geosot/line_buffer': h_line_buffer,
    '/geosot/polygon_buffer': h_polygon_buffer,
    '/geosot/overlay_analysis_intersection': h_overlay_intersection,
    '/geosot/overlay_analysis_union': h_overlay_union,
    '/geosot/grid_heat_gather': h_heat,
    '/geosot/path_geo_num': h_path,
    # 3D
    '/geosot3d/center_point3d': h3_center_point,
    '/geosot3d/extract_geo_num_2d': h3_extract_2d,
    '/geosot3d/scope_geo_num': h3_scope,
    '/geosot3d/point3d': h3_point,
    '/geosot3d/sphere': h3_sphere,
    '/geosot3d/rect3d': h3_rect,
    '/geosot3d/cylinder': h3_cylinder,
    '/geosot3d/child_geo_num': h3_child,
    '/geosot3d/parent_geo_num': h3_parent,
    '/geosot3d/adjoin6_geo_num': h3_adjoin6,
    '/geosot3d/adjoin26_geo_num': h3_adjoin26,
    '/geosot3d/relative_azimuth': h3_relative_azimuth,
    '/geosot3d/distance_manhattan': h3_manhattan,
    '/geosot3d/polygon3d': h3_polygon,
    '/geosot3d/polyline3d': h3_polyline,
    '/geosot3d/rcuboid_buffer': h3_rcuboid,
    '/geosot3d/aggregation_intersect': h3_agg_intersect,
    '/geosot3d/aggregation_adjoin': h3_agg_adjoin,
    '/geosot3d/aggregation_relationship': h3_agg_relationship,
    '/geosot3d/visual_analysis': h3_visual,
}


@app.post('/{prefix}/{ep}')
async def dispatch(prefix: str, ep: str, request: Request):
    path = '/%s/%s' % (prefix, ep)
    handler = HANDLERS.get(path)
    if handler is None:
        return _err('未知接口: %s' % path)
    form = dict(await request.form())
    try:
        return handler(form)
    except Exception as e:
        return _err('%s: %s' % (path, e))


@app.get('/')
def root():
    return {'server_status': 200, 'service': 'GeoSOT-iWhere Engine (GB/T 40087 复现)',
            'endpoints': len(HANDLERS)}
