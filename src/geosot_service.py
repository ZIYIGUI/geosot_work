# -*- coding: utf-8 -*-
"""GeoSOT-iWhere 服务层几何算法 (补充: 几何覆盖/集合/缓冲/叠加/热力/视频建模/3D 体积)"""
import math
import geosot_core as gc

R0 = gc.R0
THETA0 = gc.THETA0


# ---------------------------- 解析辅助 ----------------------------
def parse_code(s):
    """'412869894958481408-23' -> (code:int, level:int|None); 无后缀时 level=None。
    """
    s = str(s).strip()
    if '-' in s:
        a, b = s.rsplit('-', 1)
        return int(a), int(b)
    return int(s), None


def parse_codes(s):
    """'c1-l1,c2-l2' 字符串 -> [(code, level), ...] 列表。
    """
    out = []
    for part in str(s).split(','):
        part = part.strip()
        if part:
            out.append(parse_code(part))
    return out


def num_list(s):
    """逗号分隔数字串 -> float 列表 (兼容中文逗号)。
    """
    return [float(x) for x in str(s).replace('，', ',').split(',') if x.strip() != '']


def f_num(v):
    """字符串 -> int (失败则 float)。
    """
    try:
        return int(v)
    except (TypeError, ValueError):
        return float(v)


def _routeB_code(r, c, level):
    """行列号 + 层级 -> 路线B 64 位码: morton(r,c,level)<<(64-2*level)。
    """
    return gc.morton(r, c, level) << (64 - 2 * level)


def _row_col_bounds(lat0, lat1, lng0, lng1, level):
    """经纬度对角 -> (r0, r1, c0, c1) 行列范围。
    """
    c = gc.cells_per_deg(level)
    r0, c0 = int(math.floor(min(lat0, lat1) * c + 1e-9)), int(math.floor(min(lng0, lng1) * c + 1e-9))
    r1, c1 = int(math.floor(max(lat0, lat1) * c + 1e-9)), int(math.floor(max(lng0, lng1) * c + 1e-9))
    return r0, r1, c0, c1


# ---------------------------- 几何覆盖 (routeB) ----------------------------
def rect_cells(lat_lt, lng_lt, lat_rb, lng_rb, level):
    """矩形覆盖的路线B 网格编码列表 (行×列遍历)。
    """
    r0, r1, c0, c1 = _row_col_bounds(lat_rb, lat_lt, lng_lt, lng_rb, level)
    out = []
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            out.append(_routeB_code(r, c, level))
    return out


def point_cells(lat, lng, level):
    """点所在路线B 网格编码 (单元素列表)。
    """
    r, c = gc.row_col(lat, lng, level)
    return [_routeB_code(r, c, level)]


def multi_point_cells(lats, lngs, level):
    """多点去重后的路线B 网格编码列表。
    """
    out = []
    for la, lo in zip(lats, lngs):
        r, c = gc.row_col(la, lo, level)
        code = _routeB_code(r, c, level)
        if code not in out:
            out.append(code)
    return out


def _line_sample(la0, lo0, la1, lo1, level, n=64):
    """线段均匀采样 -> routeB 码 (去重保序), 采样密度按层级自适应。
    """
    c = gc.cells_per_deg(level)
    seen = []
    n_steps = max(2, int(n * max(abs(la1 - la0), abs(lo1 - lo0)) * c / 2 + 2))
    for i in range(n_steps + 1):
        t = i / n_steps
        la = la0 + (la1 - la0) * t
        lo = lo0 + (lo1 - lo0) * t
        r, cc = gc.row_col(la, lo, level)
        code = _routeB_code(r, cc, level)
        if not seen or seen[-1] != code:
            seen.append(code)
    return seen


def _line_dda(la0, lo0, la1, lo1, level):
    """线段 DDA 网格遍历 (绝对参数 t 无累积误差):
        中途对角先列后行双输出; 起点对角单出; 终点对角双出去重; t>1 终止。
    """
    c = gc.cells_per_deg(level)
    x0, y0 = la0 * c, lo0 * c
    x1, y1 = la1 * c, lo1 * c
    r, cc = int(math.floor(x0)), int(math.floor(y0))
    r1, cc1 = int(math.floor(x1)), int(math.floor(y1))
    out = [(r, cc)]
    if r == r1 and cc == cc1:
        return out
    dr = 1 if r1 >= r else -1
    dc = 1 if cc1 >= cc else -1
    dx, dy = x1 - x0, y1 - y0
    EPS = 1e-12
    if abs(dx) < 1e-15 and abs(dy) < 1e-15:
        return out

    def trow():
        if abs(dx) < 1e-15:
            return float('inf')
        xb = r + 1 if dr > 0 else r
        return (xb - x0) / dx

    def tcol():
        if abs(dy) < 1e-15:
            return float('inf')
        yb = cc + 1 if dc > 0 else cc
        return (yb - y0) / dy

    while True:
        tr = trow()
        tc = tcol()
        if tr > 1.0 + EPS and tc > 1.0 + EPS:
            break
        if abs(tr - tc) <= EPS:
            if tr <= EPS:
                # 起点对角: 只输出对角格
                r += dr
                cc += dc
                out.append((r, cc))
                if (r, cc) == (r1, cc1):
                    break
            elif tr >= 1.0 - EPS:
                # 终点对角: 终点列格 + 终点格 (去重)
                g = (r, cc1)
                if g != out[-1]:
                    out.append(g)
                g2 = (r1, cc1)
                if g2 != out[-1]:
                    out.append(g2)
                break
            else:
                cc += dc
                out.append((r, cc))
                r += dr
                out.append((r, cc))
        elif tr < tc:
            r += dr
            out.append((r, cc))
        else:
            cc += dc
            out.append((r, cc))
    return out


def line_cells(lats, lngs, level):
    """折线网格编码: 每段 DDA, 从"未访问端点"出发, 全局去重保序 (黄金口径)。
    """
    out = []
    seen = set()
    for i in range(len(lats) - 1):
        a = (lats[i], lngs[i])
        b = (lats[i + 1], lngs[i + 1])
        ra, ca = gc.row_col(a[0], a[1], level)
        if (ra, ca) in seen:
            a, b = b, a
        for (r, cc) in _line_dda(a[0], a[1], b[0], b[1], level):
            if (r, cc) not in seen:
                out.append(_routeB_code(r, cc, level))
                seen.add((r, cc))
    return out


def multi_line_cells(coords_list, level):
    """多折线网格编码: 逐线 line_cells 后合并去重 (保序)。
    """
    out = []
    for line in coords_list:
        lats = [p[1] for p in line]
        lngs = [p[0] for p in line]
        for code in line_cells(lats, lngs, level):
            if not out or out[-1] != code:
                out.append(code)
    return out


def _point_in_poly(lat, lng, lats, lngs):
    """射线法判断点是否在多边形内。
    """
    inside = False
    n = len(lats)
    j = n - 1
    for i in range(n):
        yi, xi = lats[i], lngs[i]
        yj, xj = lats[j], lngs[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _polygon_cells_set(lats, lngs, level):
    """多边形覆盖格集合: 每条边 DDA + 顶点格修剪(到达边lat减则删floor格) + 行填充。
    """
    n = len(lats)
    c = gc.cells_per_deg(level)
    EPS = 1e-12
    drop = set()
    for v in range(n):
        a_lat = lats[(v - 1) % n]
        if lats[v] < a_lat - EPS:
            drop.add((int(lats[v] * c), int(lngs[v] * c)))
    bound = set()
    for i in range(n):
        a = (lats[i], lngs[i])
        b = (lats[(i + 1) % n], lngs[(i + 1) % n])
        for g in _line_dda(a[0], a[1], b[0], b[1], level):
            if g not in drop:
                bound.add(g)
    rows = {}
    for r, cc in bound:
        rows.setdefault(r, []).append(cc)
    out = set()
    for r, ccs in rows.items():
        for cc in range(min(ccs), max(ccs) + 1):
            out.add((r, cc))
    return out


def polygon_cells(lats, lngs, level, ordered=True):
    """多边形覆盖格列表 (按行升序、行内列升序, ordered=True 时)。
    """
    n = len(lats)
    c = gc.cells_per_deg(level)
    EPS = 1e-12
    # 顶点格修剪: 到达边 lat 减则删 floor 格
    drop = set()
    for v in range(n):
        a_lat = lats[(v - 1) % n]
        if lats[v] < a_lat - EPS:
            drop.add((int(lats[v] * c), int(lngs[v] * c)))
    bound = set()
    for i in range(n):
        a = (lats[i], lngs[i])
        b = (lats[(i + 1) % n], lngs[(i + 1) % n])
        for g in _line_dda(a[0], a[1], b[0], b[1], level):
            if g not in drop:
                bound.add(g)
    rows = {}
    for r, cc in bound:
        rows.setdefault(r, []).append(cc)
    out = []
    for r in sorted(rows):
        for cc in range(min(rows[r]), max(rows[r]) + 1):
            out.append(_routeB_code(r, cc, level))
    return out


def circle_cells(lat, lng, radius_m, level):
    """点缓冲区圆覆盖的 routeB 单元: 网格四角任一距圆心 <= 半径即选中。
    """
    c = gc.cells_per_deg(level)
    r_deg = radius_m / (THETA0 * R0)
    lat_c = r_deg / math.cos(math.radians(lat)) if abs(lat) < 89.9 else r_deg / 0.02
    r0 = int(math.floor((lat - r_deg) * c + 1e-9))
    r1 = int(math.floor((lat + r_deg) * c + 1e-9))
    c0 = int(math.floor((lng - lat_c) * c + 1e-9))
    c1 = int(math.floor((lng + lat_c) * c + 1e-9))
    out = []
    for r in range(r0, r1 + 1):
        for cc in range(c0, c1 + 1):
            # 网格四角任一到圆心距离 <= 半径 -> 网格与圆相交
            hit = False
            for dr in (0.0, 1.0):
                for dc in (0.0, 1.0):
                    la = (r + dr) / c
                    lo = (cc + dc) / c
                    if gc._haversine_atan2(lat, lng, la, lo) <= radius_m:
                        hit = True
                        break
                if hit:
                    break
            if hit:
                out.append(_routeB_code(r, cc, level))
    return out


def line_buffer_cells(lats, lngs, radius_m, level):
    """线缓冲区: 网格四角到线段距离 <= 半径的单元集合 (无序)。
    """
    out = set()
    for i in range(len(lats) - 1):
        la0, lo0, la1, lo1 = lats[i], lngs[i], lats[i + 1], lngs[i + 1]
        c = gc.cells_per_deg(level)
        r_deg = radius_m / (THETA0 * R0)
        lat0, lat1 = min(la0, la1) - r_deg, max(la0, la1) + r_deg
        lng0, lng1 = min(lo0, lo1) - r_deg, max(lo0, lo1) + r_deg
        r0 = max(0, int(math.floor(lat0 * c + 1e-9)))
        r1 = int(math.floor(lat1 * c + 1e-9))
        c0 = max(0, int(math.floor(lng0 * c + 1e-9)))
        c1 = int(math.floor(lng1 * c + 1e-9))
        for r in range(r0, r1 + 1):
            for cc in range(c0, c1 + 1):
                hit = False
                for dr in (0.0, 1.0):
                    for dc in (0.0, 1.0):
                        la = (r + dr) / c
                        lo = (cc + dc) / c
                        if _dist_to_seg(la, lo, la0, lo0, la1, lo1) <= radius_m:
                            hit = True
                            break
                    if hit:
                        break
                if hit:
                    out.add(_routeB_code(r, cc, level))
    return list(out)


def _dist_to_seg(lat, lng, la0, lo0, la1, lo1):
    """点(经纬度)到线段的最短球面距离: 投影参数 t 截断后 Haversine。
    """
    x, y = lng, lat
    x1, y1, x2, y2 = lo0, la0, lo1, la1
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return gc._haversine_atan2(lat, lng, la0, lo0)
    t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    px, py = x1 + t * dx, y1 + t * dy
    return gc._haversine_atan2(lat, lng, py, px)


def _point_on_seg(lat, lng, p, q):
    """点是否在线段 p->q 上 (含端点, 参数 t ∈ [0,1])。
    """
    dlat = q[0] - p[0]
    dlng = q[1] - p[1]
    if abs(dlat) < 1e-15 and abs(dlng) < 1e-15:
        return abs(lat - p[0]) < 1e-12 and abs(lng - p[1]) < 1e-12
    t = None
    if abs(dlat) > 1e-15:
        t = (lat - p[0]) / dlat
    if abs(dlng) > 1e-15:
        t2 = (lng - p[1]) / dlng
        if t is None:
            t = t2
        elif abs(t - t2) > 1e-9:
            return False
    return t is not None and -1e-12 <= t <= 1 + 1e-12


def polygon_buffer_cells(lats, lngs, radius_m, level):
    """面缓冲区域(GB/T 40087):
        内部(正交集/顶点/lat增边零长度擦角) + 谷底水平边下方行扩展, 输出升序 routeB 码。
    """
    n = len(lats)
    c = gc.cells_per_deg(level)
    EPS = 1e-12
    r_min = int(math.floor(min(lats) * c))
    r_max = int(math.floor(max(lats) * c))
    cc_min = int(math.floor(min(lngs) * c))
    cc_max = int(math.floor(max(lngs) * c))
    got = set()
    for r in range(r_min - 1, r_max + 1):
        la_min, la_max = r / c, (r + 1) / c
        for cc in range(cc_min - 1, cc_max + 1):
            lo_min, lo_max = cc / c, (cc + 1) / c
            if _cell_intersects_poly(r, cc, lats, lngs, level):
                got.add((r, cc))
                continue
            # 顶点判据: 多边形任一顶点落在格内(闭区间)
            vertex_hit = False
            for v in range(n):
                la, lo = lats[v], lngs[v]
                if la_min - EPS <= la <= la_max + EPS and lo_min - EPS <= lo <= lo_max + EPS:
                    vertex_hit = True
                    break
            if vertex_hit:
                got.add((r, cc))
                continue
            # lat 增边零长度擦角: 格角在 lat 增边上且边不穿过格内部
            for i in range(n):
                p = (lats[i], lngs[i])
                q = (lats[(i + 1) % n], lngs[(i + 1) % n])
                if q[0] <= p[0] + EPS:
                    continue
                hit = False
                for (corner_la, corner_lo) in ((la_min, lo_min), (la_min, lo_max), (la_max, lo_min), (la_max, lo_max)):
                    if _point_on_seg(corner_la, corner_lo, p, q) and not _seg_through_cell(p, q, la_min, la_max, lo_min, lo_max):
                        hit = True
                        break
                if hit:
                    got.add((r, cc))
                    break
    # 谷底水平边扩展: 多边形最小 lat 顶点组(底边), 其下方行加 [min(cols)-1, max(cols)]
    min_lat = min(lats)
    cols = [int(lngs[v] * c) for v in range(n) if lats[v] < min_lat + EPS]
    if cols:
        rv = int(min_lat * c)
        for cc in range(min(cols) - 1, max(cols) + 1):
            got.add((rv - 1, cc))
    return sorted([_routeB_code(r, cc, level) for r, cc in got])


# ---------------------------- 网格集合 ----------------------------
def son_range_geo_num(code, level):
    """子级(level+1)网格编码范围 (4 个)。
    """
    out = []
    for code in gc.child_geo_num(code, level, level + 1):
        out.append(code)
    return out


def aggregation_geo_num(codes_levels, target_level=None):
    """聚合: 同层 4 兄弟可合并为父格 (迭代至无法合并或达到目标层)。
        NOTE: 该接口与 iwhere 黄金口径存在差异(黄金为跨层 routeA 编码), 见 test_all INFO。
    """
    items = [(c, l) for c, l in codes_levels]
    changed = True
    while changed:
        changed = False
        by_parent = {}
        order = []
        for c, l in items:
            key = (l, c >> (64 - 2 * l) >> 2)  # 父级索引 (高 2l 位去掉最低 2 位)
            # 父级索引 = morton 高 (l-1) 位
            m = c >> (64 - 2 * l)
            pidx = m >> 2
            by_parent.setdefault((l, pidx), []).append((c, l))
            order.append((l, pidx))
        new_items = []
        merged = set()
        for l, pidx in by_parent:
            kids = by_parent[(l, pidx)]
            if len(kids) == 4:
                # 提升为父
                pm = pidx << 2
                pc = pm << (64 - 2 * (l - 1))
                new_items.append((pc, l - 1))
                merged.add((l, pidx))
                changed = True
            else:
                new_items.extend(kids)
        items = new_items
    return items


def area_geo_num_list(codes_levels):
    """网格列表总面积: 各格 area_geo_num 之和。
    """
    total = 0.0
    for c, l in codes_levels:
        total += gc.area_geo_num(c, l)
    return total


def avg_distance_geo_num_list(list_a, list_b):
    """两网格列表间最小球面距离 (逐对取 min)。
    """
    dists = []
    for c1, l1 in list_a:
        for c2, l2 in list_b:
            dists.append(gc.sphere_distance_geo_num(c1, l1, c2, l2))
    return min(dists) if dists else 0.0


def _centroid(codes_levels):
    """网格列表质心: 各格中心点经纬度均值。
    """
    la = lo = 0.0
    for c, l in codes_levels:
        p = gc.center_point(c, l)
        la += p[1]
        lo += p[0]
    n = len(codes_levels)
    return la / n, lo / n


def orientation_direction(list_a, list_b):
    """两网格集合质心连线方位 -> 0~7 方向 (北起顺时针)。
    """
    lat_a, lng_a = _centroid(list_a)
    lat_b, lng_b = _centroid(list_b)
    az = gc.bearing(lat_a, lng_a, lat_b, lng_b)
    az_deg = math.degrees(az)
    idx = int(round(az_deg / 45.0)) % 8
    return idx


def orientation_azimuth(list_a, list_b):
    """两网格集合质心连线方位角 (弧度)。
    """
    lat_a, lng_a = _centroid(list_a)
    lat_b, lng_b = _centroid(list_b)
    return gc.bearing(lat_a, lng_a, lat_b, lng_b)


def topological_relation_list(list_a, list_b):
    """两网格集合拓扑: 0相离 1A含B 2B含A 3相等 4相邻 5相交。
    """
    set_a = set((c, l) for c, l in list_a)
    set_b = set((c, l) for c, l in list_b)
    if set_a == set_b:
        return 3
    inter = set_a & set_b
    if inter:
        return 5 if inter != set_a and inter != set_b else (1 if inter == set_b else 2)
    for c1, l1 in list_a:
        for c2, l2 in list_b:
            if gc.topological_relation_geo_num(c1, l1, c2, l2) == 4:
                return 4
    return 0


def outer_rectangle_geo_num_list(codes_levels):
    """外包矩形面片(引擎口径黄金逆向): 输入码低 (64-2L) 位清零标准化后按码升序。
    """
    level = codes_levels[0][1]
    shift = 64 - 2 * level
    out = sorted((c >> shift) << shift for c, _ in codes_levels)
    return out, [level] * len(out)


def path_geo_num(begin_code, begin_level, end_code, end_level, obstacles, level):
    """路径查询: 直线 DDA 采样, 遇障碍 BFS 绕行 (统一映射到目标层级)。
    """
    from collections import deque
    r0, c0 = gc.row_col_of_code_routeB(begin_code, begin_level)
    r1, c1 = gc.row_col_of_code_routeB(end_code, end_level)
    c = gc.cells_per_deg(level)
    obs = set()
    for oc, ol in obstacles:
        m = oc >> (64 - 2 * ol)
        # 障碍可能在不同层, 统一映射到 level
        if ol <= level:
            mr, mc = gc.demorton(m, ol)
            mr <<= (level - ol)
            mc <<= (level - ol)
        else:
            mr, mc = gc.demorton(m, ol)
            mr >>= (ol - level)
            mc >>= (ol - level)
        obs.add((mr, mc))
    # 直线采样
    steps = max(abs(r1 - r0), abs(c1 - c0))
    straight = []
    for i in range(steps + 1):
        r = r0 + round((r1 - r0) * i / steps)
        cc = c0 + round((c1 - c0) * i / steps)
        straight.append((r, cc))
    if not any(p in obs for p in straight):
        return [_routeB_code(r, cc, level) for r, cc in straight]
    # BFS 绕行
    q = deque([(r0, c0)])
    prev = {(r0, c0): None}
    while q:
        r, cc = q.popleft()
        if (r, cc) == (r1, c1):
            break
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, cc + dc
                if (nr, nc) in obs or (nr, nc) in prev:
                    continue
                prev[(nr, nc)] = (r, cc)
                q.append((nr, nc))
    path = []
    cur = (r1, c1)
    while cur is not None:
        path.append(_routeB_code(cur[0], cur[1], level))
        cur = prev.get(cur)
    path.reverse()
    return path


def _seg_through_cell(p, q, la_min, la_max, lo_min, lo_max):
    """线段 p->q 是否以正长度穿过格 (开区间内部)。
    """
    dlat = q[0] - p[0]
    dlng = q[1] - p[1]
    t_lo, t_hi = 0.0, 1.0
    for d, p0, mn, mx in ((dlat, p[0], la_min, la_max), (dlng, p[1], lo_min, lo_max)):
        if abs(d) < 1e-15:
            if not (mn < p0 < mx):
                return False
        else:
            t1 = (mn - p0) / d
            t2 = (mx - p0) / d
            if t1 > t2:
                t1, t2 = t2, t1
            t_lo = max(t_lo, t1)
            t_hi = min(t_hi, t2)
    return t_hi > t_lo + 1e-12


def _cell_intersects_poly(r, cc, lats, lngs, level):
    """格 (r,cc) 与多边形交集是否有正长度/正面积。
    """
    c = gc.cells_per_deg(level)
    if _point_in_poly((r + 0.5) / c, (cc + 0.5) / c, lats, lngs):
        return True
    la_min, la_max = r / c, (r + 1) / c
    lo_min, lo_max = cc / c, (cc + 1) / c
    n = len(lats)
    for i in range(n):
        p = (lats[i], lngs[i])
        q = (lats[(i + 1) % n], lngs[(i + 1) % n])
        if _seg_through_cell(p, q, la_min, la_max, lo_min, lo_max):
            return True
    return False


def traversal_geo_num(lats, lngs, level):
    """多边形范围网格遍历: 从上到下、从左到右输出二维数组 (每行长度可不同),
        判据 = 格与多边形正交集 + 谷底顶点下方行扩展。
    """
    n = len(lats)
    c = gc.cells_per_deg(level)
    EPS = 1e-12
    rows = {}
    r_min = int(math.floor(min(lats) * c))
    r_max = int(math.floor(max(lats) * c))
    cc_min = int(math.floor(min(lngs) * c))
    cc_max = int(math.floor(max(lngs) * c))
    for r in range(r_min, r_max + 1):
        for cc in range(cc_min, cc_max + 1):
            if _cell_intersects_poly(r, cc, lats, lngs, level):
                rows.setdefault(r, []).append(cc)
    # 谷底扩展: 到达边 lat 减的顶点, 其下方行 r-1 加入 [min(vc)-1, max(vc)]
    valley = []
    for v in range(n):
        a_lat = lats[(v - 1) % n]
        if lats[v] < a_lat - EPS:
            valley.append((int(lats[v] * c), int(lngs[v] * c)))
    if valley:
        rv = valley[0][0]
        vc = [cv for _, cv in valley]
        rows.setdefault(rv - 1, []).extend(range(min(vc) - 1, max(vc) + 1))
    layers = []
    for r in sorted(rows):
        ccs = sorted(set(rows[r]))
        layers.append([_routeB_code(r, cc, level) for cc in range(min(ccs), max(ccs) + 1)])
    return layers


# ---------------------------- 视频建模 ----------------------------
def _solve_dlt(pixel_pts, geo_pts):
    """8 参数透视变换求解 (像素->地理): 8x8 线性方程组高斯消元 (手写, 精度优于 lstsq)。
    """
    A = []
    b = []
    for (px, py), (gx, gy) in zip(pixel_pts, geo_pts):
        A.append([px, py, 1, 0, 0, 0, -px * gx, -py * gx])
        b.append(gx)
        A.append([0, 0, 0, px, py, 1, -px * gy, -py * gy])
        b.append(gy)
    # 高斯消元
    n = 8
    M = [row[:] + [bv] for row, bv in zip(A, b)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        M[col], M[piv] = M[piv], M[col]
        if abs(M[col][col]) < 1e-15:
            continue
        for r in range(col + 1, n):
            f = M[r][col] / M[col][col]
            for c2 in range(col, n + 1):
                M[r][c2] -= f * M[col][c2]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        s = M[r][n] - sum(M[r][c2] * x[c2] for c2 in range(r + 1, n))
        x[r] = s / M[r][r] if abs(M[r][r]) > 1e-15 else 0.0
    return x + [1.0]


def _apply_h(h, x, y):
    """应用单应矩阵 h: (h0x+h1y+h2, h3x+h4y+h5)/(h6x+h7y+1)。
    """
    den = h[6] * x + h[7] * y + 1
    return (h[0] * x + h[1] * y + h[2]) / den, (h[3] * x + h[4] * y + h[5]) / den


def _invert_h(h):
    """3x3 单应矩阵求逆 (最后一元素固定 1, 高斯-约当)。
    """
    m = [[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1.0]]
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(3)] for i, row in enumerate(m)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(aug[r][col]))
        aug[col], aug[piv] = aug[piv], aug[col]
        if abs(aug[col][col]) < 1e-15:
            continue
        inv_piv = 1.0 / aug[col][col]
        aug[col] = [v * inv_piv for v in aug[col]]
        for r in range(3):
            if r == col:
                continue
            f = aug[r][col]
            aug[r] = [a - f * b for a, b in zip(aug[r], aug[col])]
    inv = [row[3:] for row in aug]
    flat = [inv[0][0], inv[0][1], inv[0][2], inv[1][0], inv[1][1], inv[1][2], inv[2][0], inv[2][1], inv[2][2]]
    return flat


def video_model(pixel_points, geographic_points, is_show, geo_level,
                plane_pixel_x=None, plane_pixel_y=None):
    """视频空间建模: 返回变换矩阵 + 网格编码 + 网格像素矩形"""
    px = num_list(pixel_points)
    py = [float(x) for x in str(plane_pixel_y or '').replace('，', ',').split(',') if str(x).strip() != ''] if is_show else []
    geo = num_list(geographic_points)
    pixel_pts = [(px[i], px[i + 1]) for i in range(0, len(px), 2)]
    geo_pts = [(geo[i + 1], geo[i]) for i in range(0, len(geo), 2)]  # geo 纬度在前
    geo_trans = _solve_dlt(pixel_pts, geo_pts)          # 像素 -> 地理
    pixel_trans = _invert_h(geo_trans)                   # 地理 -> 像素
    # 引擎口径: pixel_trans_matrix = 像素->地理 DLT 解交换行 (先 y 后 x);
    # geographic_trans_matrix = 逆矩阵(地理->像素) 归一化后交换行
    gt = geo_trans
    pixel_trans = [gt[3], gt[4], gt[5], gt[0], gt[1], gt[2], gt[6], gt[7], gt[8]]
    inv = _invert_h(gt)
    if abs(inv[8]) > 1e-15:
        inv = [v / inv[8] for v in inv]
    geographic_trans = [inv[1], inv[0], inv[2], inv[4], inv[3], inv[5], inv[7], inv[6], inv[8]]
    resp = {'pixel_trans_matrix': pixel_trans, 'geographic_trans_matrix': geographic_trans}
    if is_show:
        plane_x = num_list(plane_pixel_x)
        plane_y = num_list(plane_pixel_y)
        # 平面可见区域 4 角点(像素) -> 像素->地理变换 -> 地理 (geo_trans 输出 lng, lat)
        g_corners = [_apply_h(geo_trans, x, y) for x, y in zip(plane_x, plane_y)]
        lats = [p[1] for p in g_corners]
        lngs = [p[0] for p in g_corners]
        # 地理外包 -> 整分网格(1' x 1')
        la_min = math.floor(min(lats) * 60) / 60.0
        la_max = math.ceil(max(lats) * 60) / 60.0
        lo_min = math.floor(min(lngs) * 60) / 60.0
        lo_max = math.ceil(max(lngs) * 60) / 60.0

        # 网格编码: 度*64 + 分 (引擎口径: 整分网格左下角, 1 分当作 1 格)
        def _dms_to_grid(v):
            tot = int(round(v * 60))
            deg, mn = divmod(tot, 60)
            return deg * 64 + mn

        r0 = _dms_to_grid(la_min)
        c0 = _dms_to_grid(lo_min)
        code = gc.morton(r0, c0, geo_level) << (64 - 2 * geo_level)
        resp['geo_num_list'] = ['%d-%d' % (code, geo_level)]

        # 网格像素矩形: 整分网格 4 角 -> 地理->像素变换
        rect = {}
        for name, (la, lo) in zip(('lb', 'rb', 'rt', 'lt'),
                                  ((la_min, lo_min), (la_max, lo_min),
                                   (la_max, lo_max), (la_min, lo_max))):
            pxy = _apply_h(geographic_trans, la, lo)
            rect[name + 'x'] = pxy[0]
            rect[name + 'y'] = pxy[1]
        resp['rect_pixel_list'] = [rect]
    return resp


# ---------------------------- 热力汇聚 ----------------------------
def grid_heat_gather(geo_num_list, geo_data_list, geo_level, gather_level):
    """热力汇聚: 各码按 gather_level 父格分组累加数值, 输出升序编码与汇总值。
    """
    groups = {}
    for code_str, data_str in zip(geo_num_list, geo_data_list):
        code, _ = parse_code(code_str)
        m = code >> (64 - 2 * geo_level)
        # 映射到 gather_level 的父网格
        if gather_level <= geo_level:
            pm = m >> (2 * (geo_level - gather_level))
        else:
            pm = m << (2 * (gather_level - geo_level))
        pc = pm << (64 - 2 * gather_level)
        groups.setdefault(pc, 0.0)
        groups[pc] += float(data_str)
    out_codes = []
    out_data = []
    for pc in sorted(groups):
        val = groups[pc]
        out_codes.append('%d-%d' % (pc, gather_level))
        out_data.append(int(val) if float(val).is_integer() else round(val, 6))
    return out_codes, out_data


# ---------------------------- 3D 体积 ----------------------------
def _h_range(h0, h1, level):
    """高度区间 [h0,h1] -> 层级索引列表 (按 height_cell 取整)。
    """
    hc = gc.height_cell(level)
    a = max(0, int(math.floor(min(h0, h1) / hc + 1e-9)))
    b = max(a, int(math.floor(max(h0, h1) / hc + 1e-9)))
    return list(range(a, b + 1))


def rect3d_cells(lat_lt, lng_lt, lat_rb, lng_rb, h0, h1, level):
    """3D 长方体覆盖: 每高度层的 rect_cells 提升为 3D 码。
    """
    codes = []
    for h in _h_range(h0, h1, level):
        for code in rect_cells(lat_lt, lng_lt, lat_rb, lng_rb, level):
            la, ln = gc.demorton(code >> (64 - 2 * level), level)
            la = la << (32 - level)
            ln = ln << (32 - level)
            codes.append(gc.interleave3(la, ln, h, order=(2, 0, 1), nbits=32))
    return codes


def polygon3d_cells(lats, lngs, h0, h1, level):
    """3D 棱柱覆盖: 每高度层的 polygon_cells 提升为 3D 码。
    """
    codes = []
    for h in _h_range(h0, h1, level):
        for code in polygon_cells(lats, lngs, level):
            la, ln = gc.demorton(code >> (64 - 2 * level), level)
            la = la << (32 - level)
            ln = ln << (32 - level)
            codes.append(gc.interleave3(la, ln, h, order=(2, 0, 1), nbits=32))
    return codes


def polyline3d_cells(lats, lngs, heights, level):
    """3D 折线覆盖: 高度范围逐层 line_cells 提升为 3D 码。
    """
    codes = []
    for h in _h_range(min(heights), max(heights), level):
        for code in line_cells(lats, lngs, level):
            la, ln = gc.demorton(code >> (64 - 2 * level), level)
            la = la << (32 - level)
            ln = ln << (32 - level)
            codes.append(gc.interleave3(la, ln, h, order=(2, 0, 1), nbits=32))
    return codes


def rcuboid_buffer(lat_lt, lng_lt, lat_lb, lng_lb, height_start, height, level):
    """3D 缓冲长方体: rect3d_cells 的便捷封装 (height_start 起 height 高)。
    """
    return rect3d_cells(lat_lt, lng_lt, lat_lb, lng_lb, height_start, height_start + height, level)


def _boxes(code, level):
    """3D 码 -> (latMin, lngMin, latMax, lngMax, hMin, hMax) 六元组。
    """
    h, la, ln = gc.decode_geo_num3d(code, level)
    (d, m, s, sub), (d2, m2, s2, sub2) = gc.unpack_dms(la), gc.unpack_dms(ln)
    lb_lat = gc.dms2deg(d, m, s, sub, level)
    lb_lng = gc.dms2deg(d2, m2, s2, sub2, level)
    cd = gc.cell_deg(level)
    hc = gc.height_cell(level)
    return (lb_lat, lb_lng, lb_lat + cd, lb_lng + cd, h * hc, (h + 1) * hc)


def _boxes_overlap(b1, b2):
    """两 3D 盒是否相交 (开区间)。
    """
    return not (b1[2] <= b2[0] or b2[2] <= b1[0] or b1[3] <= b2[1] or b2[3] <= b1[1]
                or b1[5] <= b2[4] or b2[5] <= b1[4])


def _boxes_adjoin(b1, b2):
    """两 3D 盒是否面相邻 (共享一面且其他两维区间重叠)。
    """
    eps = 1e-9
    # 面相邻 (共享一面, 高度区间或经纬区间相接)
    if abs(b1[2] - b2[0]) < eps or abs(b2[2] - b1[0]) < eps:
        return _int_overlap(b1[1], b1[3], b2[1], b2[3]) and _int_overlap(b1[4], b1[5], b2[4], b2[5])
    if abs(b1[3] - b2[1]) < eps or abs(b2[3] - b1[1]) < eps:
        return _int_overlap(b1[0], b1[2], b2[0], b2[2]) and _int_overlap(b1[4], b1[5], b2[4], b2[5])
    if abs(b1[5] - b2[4]) < eps or abs(b2[5] - b1[4]) < eps:
        return _int_overlap(b1[0], b1[2], b2[0], b2[2]) and _int_overlap(b1[1], b1[3], b2[1], b2[3])
    return False


def _int_overlap(a0, a1, b0, b1):
    """区间 [a0,a1] 与 [b0,b1] 是否重叠。
    """
    return max(a0, b0) < min(a1, b1) + 1e-9


def aggregation_intersect(list_a, list_b):
    """3D 集合求交: 返回 list_a 中与 list_b 任一盒相交的编码。
    """
    boxes_b = [_boxes(c, l) for c, l in list_b]
    out = []
    for c, l in list_a:
        b1 = _boxes(c, l)
        if any(_boxes_overlap(b1, b2) for b2 in boxes_b):
            out.append(c)
    return out


def aggregation_adjoin(list_a, list_b):
    """3D 集合邻接: 返回 list_a 中与 list_b 任一盒面相邻的编码。
    """
    boxes_b = [_boxes(c, l) for c, l in list_b]
    out = []
    for c, l in list_a:
        b1 = _boxes(c, l)
        if any(_boxes_adjoin(b1, b2) for b2 in boxes_b):
            out.append(c)
    return out


def aggregation_relationship(list_a, list_b):
    """3D 集合关系: 0相离 1相交 2相邻。
    """
    boxes_a = [_boxes(c, l) for c, l in list_a]
    boxes_b = [_boxes(c, l) for c, l in list_b]
    for b1 in boxes_a:
        for b2 in boxes_b:
            if _boxes_overlap(b1, b2):
                return 1
    for b1 in boxes_a:
        for b2 in boxes_b:
            if _boxes_adjoin(b1, b2):
                return 2
    return 0


def visual_analysis(begin_code, begin_level, end_code, end_level, obstacles, level):
    """可视域分析: 起点->终点连线采样, 穿过障碍网格(高度0层近似)则不可视。
    """
    b_lat, b_lng = gc.center_point(begin_code, begin_level)[::-1] if False else None
    p1 = gc.center_point(begin_code, begin_level)
    p2 = gc.center_point(end_code, end_level)
    c = gc.cells_per_deg(level)
    obs = set()
    for oc, ol in obstacles:
        h, la, ln = gc.decode_geo_num3d(oc, ol)
        (d, m, s, sub), (d2, m2, s2, sub2) = gc.unpack_dms(la), gc.unpack_dms(ln)
        lb_lat = gc.dms2deg(d, m, s, sub, ol)
        lb_lng = gc.dms2deg(d2, m2, s2, sub2, ol)
        r = int(math.floor(lb_lat * c + 1e-9))
        cc = int(math.floor(lb_lng * c + 1e-9))
        obs.add((r, cc, h))
    steps = max(8, int(abs(p2[1] - p1[1]) * c + abs(p2[0] - p1[0]) * c) * 4)
    for i in range(steps + 1):
        t = i / steps
        la = p1[1] + (p2[1] - p1[1]) * t
        lo = p1[0] + (p2[0] - p1[0]) * t
        hgt = gc.center_point3d(begin_code, begin_level)[2] if False else 0
        r = int(math.floor(la * c + 1e-9))
        cc = int(math.floor(lo * c + 1e-9))
        # 高度: 用 0 层近似
        if (r, cc, 0) in obs:
            return 1
    return 0
