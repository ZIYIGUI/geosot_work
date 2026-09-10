# -*- coding: utf-8 -*-
"""
GeoSOT 地理信息文件读取与编码映射模块
========================================
支持读取常见地理信息文件格式, 提取几何要素并映射为 GeoSOT 网格编码:

  | 格式        | 扩展名          | 支持几何类型                                      | 解析方式          |
  |-------------|-----------------|--------------------------------------------------|-------------------|
  | GeoJSON     | .geojson/.json  | Point/MultiPoint/LineString/MultiLineString/     | json (标准库)     |
  |             |                 | Polygon/MultiPolygon/Feature/FeatureCollection   |                   |
  | Shapefile   | .shp (+.dbf)    | Point/PolyLine/Polygon/MultiPoint (+Z/M)         | 纯标准库二进制解析|
  | CSV         | .csv/.txt       | 点表 (lon/lat 列) 或 WKT 列                      | csv (标准库)      |
  | WKT         | .wkt/.txt       | Point/LineString/Polygon/Multi*                  | 手写解析器        |
  | KML         | .kml            | Placemark 的 Point/LineString/Polygon            | xml.etree         |
  | GPX         | .gpx            | wpt/trkpt/rtept 轨迹点与线段                     | xml.etree         |

编码映射 (route):
  - route='B' (默认): 连续网格码, 点/线/面分别调用 geosot_core.geo_num_routeB /
    geosot_service.line_cells / polygon_cells, 输出 64 位十进制码
  - route='A': 路线A DMS 十进制码 (geosot_core.geo_num_routeA)

CLI 用法:
  python geofile.py input.geojson --level 15 [--route B|A] [--out result.json]
  python geofile.py input.shp --level 20 --route B

返回结构 (encode_file):
  {'format': 'geojson', 'level': 15, 'route': 'B', 'count': N,
   'features': [{'type': 'Point', 'code': '...', 'code_level': 15,
                 'binary128': '...', 'bytes16_hex': '...', 'props': {...}}, ...]}
"""
import csv
import io
import json
import math
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geosot_core as gc
import geosot_service as svc

# ------------------------------------------------------------------ 格式识别
_EXT_FORMAT = {
    '.geojson': 'geojson', '.json': 'geojson',
    '.shp': 'shp', '.shx': 'shp',
    '.csv': 'csv', '.txt': 'csv',
    '.wkt': 'wkt',
    '.kml': 'kml',
    '.gpx': 'gpx',
}


def detect_format(path):
    """按扩展名识别文件格式: geojson / shp / csv / wkt / kml / gpx。"""
    ext = os.path.splitext(str(path).lower())[1]
    fmt = _EXT_FORMAT.get(ext)
    if fmt is None:
        raise ValueError('不支持的文件格式: %s (支持 %s)' % (ext, sorted(set(_EXT_FORMAT.values()))))
    return fmt


# ------------------------------------------------------------------ GeoJSON
def read_geojson(path):
    """读取 GeoJSON 文件 -> 要素列表。
    每个要素: {'type': 几何类型, 'coords': [(lng,lat),...], 'props': {...}}。
    支持 FeatureCollection / Feature / Geometry / GeometryCollection。"""
    with io.open(path, encoding='utf-8') as f:
        gj = json.load(f)
    features = []
    if isinstance(gj, dict):
        t = gj.get('type')
        if t == 'FeatureCollection':
            for ft in gj.get('features', []):
                features.extend(_geojson_feature(ft))
        elif t == 'Feature':
            features.extend(_geojson_feature(gj))
        elif t == 'GeometryCollection':
            for geom in gj.get('geometries', []):
                features.extend(_geometry_to_feature(geom))
        else:
            features.extend(_geometry_to_feature(gj))
    elif isinstance(gj, list):
        for item in gj:
            if isinstance(item, dict) and item.get('type') == 'Feature':
                features.extend(_geojson_feature(item))
            elif isinstance(item, dict):
                features.extend(_geometry_to_feature(item))
    return features


def _geojson_feature(ft):
    props = ft.get('properties') or {}
    geom = ft.get('geometry')
    if geom is None:
        return []
    feats = _geometry_to_feature(geom)
    for fe in feats:
        fe['props'].update(props)
    return feats


def _geometry_to_feature(geom):
    t = geom.get('type', '')
    coords = geom.get('coordinates', [])
    if t == 'Point':
        return [{'type': 'Point', 'coords': [(coords[0], coords[1])], 'props': {}}]
    if t == 'MultiPoint':
        return [{'type': 'MultiPoint', 'coords': [(p[0], p[1]) for p in coords], 'props': {}}]
    if t == 'LineString':
        return [{'type': 'LineString', 'coords': [(p[0], p[1]) for p in coords], 'props': {}}]
    if t == 'MultiLineString':
        return [{'type': 'MultiLineString', 'coords': [[(p[0], p[1]) for p in line] for line in coords], 'props': {}}]
    if t == 'Polygon':
        ring = coords[0] if coords else []
        return [{'type': 'Polygon', 'coords': [(p[0], p[1]) for p in ring], 'props': {}}]
    if t == 'MultiPolygon':
        polys = []
        for poly in coords:
            ring = poly[0] if poly else []
            polys.append([(p[0], p[1]) for p in ring])
        return [{'type': 'MultiPolygon', 'coords': polys, 'props': {}}]
    return []


# ------------------------------------------------------------------ Shapefile
def read_shp(path):
    """读取 Shapefile (.shp) -> 要素列表 (纯标准库解析主文件 + 可选 .dbf 属性)。
    Shape 类型: 1/11/21 Point, 3/13/23 PolyLine, 5/15/25 Polygon, 8/18/28 MultiPoint。"""
    with open(path, 'rb') as f:
        data = f.read()
    if len(data) < 100:
        raise ValueError('SHP 文件过短: %d 字节' % len(data))
    file_code = struct.unpack('>i', data[0:4])[0]
    if file_code != 9994:
        raise ValueError('非法 SHP 文件头 (file code=%d)' % file_code)
    n_records = struct.unpack('>i', data[24:28])[0]
    shape_type = struct.unpack('<i', data[32:36])[0]
    if shape_type == 0:
        raise ValueError('SHP 无几何类型 (Null shape)')

    props = _read_dbf(os.path.splitext(path)[0] + '.dbf')
    features = []
    pos = 100
    rec_no = 0
    while pos + 8 <= len(data):
        rec_no += 1
        rec_len = struct.unpack('>i', data[pos + 4:pos + 8])[0] * 2  # 记录长度(字)->字节
        body = data[pos + 8: pos + 8 + rec_len]
        pos += 8 + rec_len
        if len(body) < 4:
            continue
        st = struct.unpack('<i', body[0:4])[0]
        p = 4
        feat = None
        if st in (1, 11, 21):                      # Point
            x, y = struct.unpack('<dd', body[p:p + 16])
            feat = {'type': 'Point', 'coords': [(x, y)], 'props': {}}
        elif st in (8, 18, 28):                    # MultiPoint
            x0, y0, x1, y1 = struct.unpack('<dddd', body[p:p + 32])
            p += 32
            num = struct.unpack('<i', body[p:p + 4])[0]
            p += 4
            pts = [(struct.unpack('<d', body[p + 16 * i:p + 16 * i + 8])[0],
                    struct.unpack('<d', body[p + 16 * i + 8:p + 16 * i + 16])[0]) for i in range(num)]
            feat = {'type': 'MultiPoint', 'coords': pts, 'props': {}}
        elif st in (3, 5, 13, 15, 23, 25):         # PolyLine / Polygon
            x0, y0, x1, y1 = struct.unpack('<dddd', body[p:p + 32])
            p += 32
            nparts = struct.unpack('<i', body[p:p + 4])[0]
            p += 4
            npoints = struct.unpack('<i', body[p:p + 4])[0]
            p += 4
            parts = list(struct.unpack('<%di' % nparts, body[p:p + 4 * nparts]))
            p += 4 * nparts
            coords = []
            for i in range(nparts):
                start = parts[i]
                end = parts[i + 1] if i + 1 < nparts else npoints
                pts = []
                for j in range(start, end):
                    o = p + j * 16
                    x = struct.unpack('<d', body[o:o + 8])[0]
                    y = struct.unpack('<d', body[o + 8:o + 16])[0]
                    pts.append((x, y))
                coords.append(pts)
            if st in (3, 13, 23):
                gtype = 'MultiLineString'
            else:
                gtype = 'MultiPolygon'
            feat = {'type': gtype, 'coords': coords, 'props': {}}
        if feat is not None:
            feat['props']['shp_record'] = rec_no
            if props and rec_no - 1 < len(props):
                feat['props'].update(props[rec_no - 1])
            features.append(feat)
    return features


def _read_dbf(dbf_path):
    """读取 .dbf 属性表 -> [{字段: 值}, ...] (不存在则返回 [])。"""
    if not os.path.exists(dbf_path):
        return []
    with open(dbf_path, 'rb') as f:
        d = f.read()
    if len(d) < 33:
        return []
    n_records = struct.unpack('<I', d[4:8])[0]
    header_len = struct.unpack('<H', d[8:10])[0]
    rec_len = struct.unpack('<H', d[10:12])[0]
    if header_len < 33 or rec_len < 1:
        return []
    fields = []
    off = 32
    while off + 32 <= header_len - 1:
        fname = d[off:off + 11].split(b'\x00')[0].decode('ascii', 'ignore')
        ftype = chr(d[off + 11])
        flen = d[off + 16]
        fields.append((fname, ftype, flen))
        off += 32
        if d[off] == 0x0D:
            break
    rows = []
    rec_start = header_len
    for i in range(n_records):
        if rec_start + rec_len > len(d):
            break
        rec = d[rec_start:rec_start + rec_len]
        rec_start += rec_len
        if not rec or rec[0] == 0x2A:            # 0x2A = 已删除
            continue
        row = {}
        p = 1
        for fname, ftype, flen in fields:
            raw = rec[p:p + flen].decode('ascii', 'ignore').strip()
            p += flen
            if ftype in 'NFC':
                try:
                    row[fname] = int(raw) if raw.lstrip('-').isdigit() else float(raw)
                except ValueError:
                    row[fname] = raw
            elif ftype == 'D':
                row[fname] = raw
            else:
                row[fname] = raw
        rows.append(row)
    return rows


# ------------------------------------------------------------------ CSV
_LNG_NAMES = {'lon', 'lng', 'long', 'longitude', 'x', 'east', 'easting', '经度', '经'}
_LAT_NAMES = {'lat', 'latitude', 'y', 'north', 'northing', '纬度', '纬'}
_WKT_NAMES = {'wkt', 'geom', 'geometry', 'shape', 'geojson'}


def read_csv(path):
    """读取 CSV -> 要素列表。识别方式 (按优先级):
      1. WKT/geometry 列 -> 解析 WKT
      2. lon/lat 列 (支持中文列名)
      3. 每行单列 "lng,lat" / "POINT(lng lat)" 文本"""
    with io.open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return []
    header = [c.strip().lower() for c in rows[0]]
    features = []
    data_rows = rows[1:]

    # 1) WKT 列
    for wname in _WKT_NAMES:
        if wname in header:
            idx = header.index(wname)
            for row in data_rows:
                if len(row) <= idx or not row[idx].strip():
                    continue
                for feat in read_wkt_text(row[idx]):
                    feat['props']['csv_row'] = row
                    features.append(feat)
            return features

    # 2) lon/lat 列
    lon_i = lat_i = None
    for i, h in enumerate(header):
        if h in _LNG_NAMES and lon_i is None:
            lon_i = i
        if h in _LAT_NAMES and lat_i is None:
            lat_i = i
    if lon_i is not None and lat_i is not None:
        for row in data_rows:
            if len(row) <= max(lon_i, lat_i):
                continue
            try:
                lng = float(row[lon_i])
                lat = float(row[lat_i])
            except ValueError:
                continue
            feat = {'type': 'Point', 'coords': [(lng, lat)], 'props': {}}
            for i, h in enumerate(header):
                if i not in (lon_i, lat_i) and i < len(row):
                    feat['props'][rows[0][i]] = row[i]
            features.append(feat)
        return features

    # 3) 单列文本
    for row in data_rows:
        if not row or not row[0].strip():
            continue
        text = row[0].strip()
        if text.upper().startswith('POINT'):
            features.extend(read_wkt_text(text))
        else:
            parts = re.split(r'[,;\s]+', text)
            if len(parts) >= 2:
                try:
                    lng, lat = float(parts[0]), float(parts[1])
                except ValueError:
                    continue
                features.append({'type': 'Point', 'coords': [(lng, lat)], 'props': {}})
    return features


# ------------------------------------------------------------------ WKT
_WKT_TOKEN = re.compile(r'POINT|LINESTRING|POLYGON|MULTIPOINT|MULTILINESTRING|MULTIPOLYGON|GEOMETRYCOLLECTION|EMPTY|[(),]|\s+|[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', re.I)


def read_wkt_text(text):
    """WKT 文本 -> 要素列表 (手写递归下降解析, 支持 Z/M 坐标与 EMPTY)。"""
    tokens = [t for t in _WKT_TOKEN.findall(text) if t.strip()]
    feats = []
    i = 0
    while i < len(tokens):
        t = tokens[i].upper()
        if t in ('POINT', 'LINESTRING', 'POLYGON', 'MULTIPOINT', 'MULTILINESTRING', 'MULTIPOLYGON'):
            if i + 1 < len(tokens) and tokens[i + 1].upper() in ('Z', 'M', 'ZM'):
                i += 1
            if i + 1 < len(tokens) and tokens[i + 1].upper() == 'EMPTY':
                i += 2
                continue
            if i + 1 < len(tokens) and tokens[i + 1] == '(':
                tree, _ = _parse_coord_tree(tokens, i + 1)
                fe = _build_wkt_feature(t, tree)
                if fe:
                    feats.append(fe)
        i += 1
    return feats


def _parse_coord_tree(tokens, i):
    """递归下降解析 tokens[i] 起的坐标体 -> (tree, 下一索引)。
    tree 结构: 坐标点用 (x, y) 元组, 嵌套括号用 list 表达。"""
    tree = []
    cur = []
    i += 1
    while i < len(tokens):
        tk = tokens[i]
        if tk == '(':
            sub, i = _parse_coord_tree(tokens, i)
            tree.append(sub)
        elif tk == ')':
            if cur:
                tree.append(tuple(cur))
            return tree, i + 1
        elif tk == ',':
            if cur:
                tree.append(tuple(cur))
                cur = []
            i += 1
        elif re.match(r'[+-]?\d', tk):
            cur.append(float(tk))
            i += 1
        else:
            i += 1
    return tree, i


def _walk_pts(node, out):
    """递归收集坐标树中所有坐标点。"""
    if isinstance(node, tuple):
        if len(node) >= 2:
            out.append((node[0], node[1]))
    elif isinstance(node, list):
        for n in node:
            _walk_pts(n, out)
    return out


def _build_wkt_feature(gtype, tree):
    """按几何类型从坐标树构建要素。"""
    if gtype == 'POINT':
        pts = _walk_pts(tree, [])
        return {'type': 'Point', 'coords': pts[:1], 'props': {}} if pts else None
    if gtype == 'MULTIPOINT':
        return {'type': 'MultiPoint', 'coords': _walk_pts(tree, []), 'props': {}}
    if gtype == 'LINESTRING':
        return {'type': 'LineString', 'coords': _walk_pts(tree, []), 'props': {}}
    if gtype == 'MULTILINESTRING':
        lines = []
        for node in tree:
            if isinstance(node, list):
                lines.append(_walk_pts(node, []))
        return {'type': 'MultiLineString', 'coords': lines, 'props': {}}
    if gtype == 'POLYGON':
        rings = []
        for node in tree:
            if isinstance(node, list):
                rings.append(_walk_pts(node, []))
        return {'type': 'MultiPolygon', 'coords': rings, 'props': {}} if rings else None
    if gtype == 'MULTIPOLYGON':
        polys = []
        for node in tree:
            if isinstance(node, list):
                polys.append(_walk_pts(node, []))
        return {'type': 'MultiPolygon', 'coords': polys, 'props': {}} if polys else None
    return None


def read_wkt(path):
    """读取 WKT 文件 (.wkt/.txt) -> 要素列表 (整文件按语句切分解析)。"""
    with io.open(path, encoding='utf-8') as f:
        text = f.read()
    return read_wkt_text(text)


# ------------------------------------------------------------------ KML / GPX
def read_kml(path):
    """读取 KML -> 要素列表 (Placemark 的 Point/LineString/Polygon)。"""
    tree = ET.parse(path)
    feats = []
    for pm in tree.iter('{http://www.opengis.net/kml/2.2}Placemark'):
        name = pm.findtext('{http://www.opengis.net/kml/2.2}name') or ''
        for tag in ('Point', 'LineString', 'Polygon'):
            node = pm.find('.//{http://www.opengis.net/kml/2.2}%s' % tag)
            if node is None:
                continue
            coords_node = node.find('{http://www.opengis.net/kml/2.2}coordinates')
            if coords_node is None or not coords_node.text:
                continue
            raw = [tuple(float(v) for v in c.split(',')) for c in coords_node.text.strip().split()]
            pts = [(c[0], c[1]) for c in raw]
            if tag == 'Point':
                feats.append({'type': 'Point', 'coords': [pts[0]] if pts else [], 'props': {'name': name}})
            elif tag == 'LineString':
                feats.append({'type': 'LineString', 'coords': pts, 'props': {'name': name}})
            else:
                feats.append({'type': 'MultiPolygon', 'coords': [pts], 'props': {'name': name}})
    return feats


def read_gpx(path):
    """读取 GPX -> 要素列表 (wpt 点, 每条 trk 的轨迹线)。"""
    ns = {'g': 'http://www.topografix.com/GPX/1/1'}
    tree = ET.parse(path)
    feats = []
    for wpt in tree.findall('.//g:wpt', ns):
        lat = float(wpt.get('lat'))
        lon = float(wpt.get('lon'))
        name = (wpt.findtext('g:name', '', ns) or '')
        feats.append({'type': 'Point', 'coords': [(lon, lat)], 'props': {'name': name}})
    for trk in tree.findall('.//g:trk', ns):
        pts = []
        for seg in trk.findall('.//g:trkseg', ns):
            for trkpt in seg.findall('g:trkpt', ns):
                pts.append((float(trkpt.get('lon')), float(trkpt.get('lat'))))
        if pts:
            name = (trk.findtext('g:name', '', ns) or '')
            feats.append({'type': 'LineString', 'coords': pts, 'props': {'name': name}})
    return feats


# ------------------------------------------------------------------ 编码映射
def encode_features(features, level, route='B', with_128=True):
    """要素列表 -> GeoSOT 编码结果列表。
    route='B': 连续网格码 (点/线/面分别映射, 多部件逐部件合并);
    route='A': 路线A DMS 十进制码 (仅点)。
    返回: [{'type', 'code', 'code_level', 'binary128', 'bytes16_hex', 'props'}, ...]"""
    out = []
    for fe in features:
        t = fe['type']
        cds = fe['coords']
        props = fe.get('props') or {}
        if t == 'Point' and cds:
            lng, lat = cds[0]
            if route.upper() == 'A':
                code = gc.geo_num_routeA(lat, lng)
                lv = 23
            else:
                code = svc.point_cells(lat, lng, level)[0]
                lv = level
            out.append(_mk(code, lv, t, props, with_128))
        elif t == 'MultiPoint' and cds:
            if route.upper() == 'A':
                for lng, lat in cds:
                    out.append(_mk(gc.geo_num_routeA(lat, lng), 23, 'Point', props, with_128))
            else:
                lats = [p[1] for p in cds]
                lngs = [p[0] for p in cds]
                for code in svc.multi_point_cells(lats, lngs, level):
                    out.append(_mk(code, level, 'Point', props, with_128))
        elif t == 'LineString' and len(cds) >= 2:
            lats = [p[1] for p in cds]
            lngs = [p[0] for p in cds]
            if route.upper() == 'A':
                for lng, lat in cds:
                    out.append(_mk(gc.geo_num_routeA(lat, lng), 23, 'Point', props, with_128))
            else:
                for code in svc.line_cells(lats, lngs, level):
                    out.append(_mk(code, level, t, props, with_128))
        elif t == 'MultiLineString':
            lines = [[(p[1], p[0]) for p in line] for line in cds]
            for line in lines:
                for code in svc.line_cells([p[0] for p in line], [p[1] for p in line], level):
                    out.append(_mk(code, level, 'LineString', props, with_128))
        elif t == 'MultiPolygon':
            for ring in cds:
                if not ring:
                    continue
                lats = [p[1] for p in ring]
                lngs = [p[0] for p in ring]
                if route.upper() == 'A':
                    for lng, lat in ring:
                        out.append(_mk(gc.geo_num_routeA(lat, lng), 23, 'Point', props, with_128))
                else:
                    for code in svc.polygon_cells(lats, lngs, level):
                        out.append(_mk(code, level, 'Polygon', props, with_128))
        elif t == 'Polygon' and cds:
            lats = [p[1] for p in cds]
            lngs = [p[0] for p in cds]
            if route.upper() == 'A':
                for lng, lat in cds:
                    out.append(_mk(gc.geo_num_routeA(lat, lng), 23, 'Point', props, with_128))
            else:
                for code in svc.polygon_cells(lats, lngs, level):
                    out.append(_mk(code, level, 'Polygon', props, with_128))
    return out


def _mk(code, level, gtype, props, with_128):
    item = {'type': gtype, 'code': '%d-%d' % (code, level),
            'code_level': level, 'props': dict(props)}
    if with_128:
        item['binary128'] = gc.to_binary128(code, level)
        item['bytes16_hex'] = gc.to_bytes16(code).hex()
    return item


def encode_file(path, level=15, route='B', with_128=True):
    """读取地理信息文件并映射为 GeoSOT 编码。
    参数: path 文件路径; level 目标层级(默认15); route 'B'/'A'; with_128 附加128位/16字节。
    返回: {'format', 'level', 'route', 'count', 'features': [...]}"""
    fmt = detect_format(path)
    if fmt == 'geojson':
        features = read_geojson(path)
    elif fmt == 'shp':
        features = read_shp(path)
    elif fmt == 'csv':
        features = read_csv(path)
    elif fmt == 'wkt':
        features = read_wkt(path)
    elif fmt == 'kml':
        features = read_kml(path)
    elif fmt == 'gpx':
        features = read_gpx(path)
    else:
        raise ValueError('无法识别的格式: %s' % fmt)
    enc = encode_features(features, level, route, with_128)
    return {'format': fmt, 'level': level, 'route': route,
            'count': len(enc), 'features': enc}


# ------------------------------------------------------------------ CLI
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description='地理信息文件 -> GeoSOT 网格编码映射')
    ap.add_argument('input', help='输入文件 (.geojson/.shp/.csv/.wkt/.kml/.gpx)')
    ap.add_argument('--level', type=int, default=15, help='目标网格层级 (默认 15)')
    ap.add_argument('--route', choices=['B', 'A'], default='B', help='编码路线 (B=连续网格码, A=DMS码)')
    ap.add_argument('--out', default=None, help='输出 JSON 文件 (默认打印摘要)')
    ap.add_argument('--no128', action='store_true', help='不输出 128 位二进制/16 字节')
    args = ap.parse_args(argv)
    res = encode_file(args.input, args.level, args.route, not args.no128)
    if args.out:
        with io.open(args.out, 'w', encoding='utf-8') as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print('已写入 %s (%d 个编码)' % (args.out, res['count']))
    else:
        print('格式=%s 层级=%d 路线=%s 编码数=%d' % (res['format'], res['level'], res['route'], res['count']))
        for fe in res['features'][:10]:
            print('  %-12s %s' % (fe['type'], fe['code']))
        if res['count'] > 10:
            print('  ... 其余 %d 条省略' % (res['count'] - 10))
    return res


if __name__ == '__main__':
    main()
