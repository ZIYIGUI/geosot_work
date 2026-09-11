# -*- coding: utf-8 -*-
"""
GeoSOT-iWhere 引擎核心算法库 (依据 GB/T 40087-2021 + OpenAPI YAML 黄金示例反演)
==============================================================================
双索引体系:
  路线A (DMS 十进制码):  code = morton31(pack(lat), pack(lng))          [2D]
  路线B (连续网格码):    code = morton(row, col, n) << (64-2n)          [几何类]
  3D码:                  code96 = interleave3(h, lat_pack, lng_pack)    [96位]
关键约定:
  - pack = (deg 8b真实值 | min 6b | sec 6b | sub 11b); 10<=level<=15 时 min=扩展分
  - 层级网格度: L<=9: 2^(9-L)度; 10<=L<=15: 2^(15-L)扩展分(=分/60度); 16<=L<=21: 2^(21-L)实秒;
    22<=L<=32: 2^(32-L)/2048 实秒
  - 高度格: h_cell(L) = r0*((1+pi/180)^cell_deg - 1), cell_deg = 各段单元换算成度
"""
import math

R0 = 6378137.0          # 赤道半径 (米)
R_SPHERE = 6378137.0    # 球面距离使用半径
THETA0 = math.pi / 180
F = 1 / 298.257223563   # WGS84 扁率
E2 = F * (2 - F)

# ------------------------------ 基础位运算 ------------------------------
def morton(r, c, n):
    """行列号 -> 莫顿(Z序)编码: 自高位向低位逐位交错, 行位在奇数位。
        参数: r 行号, c 列号, n 位宽; 返回 n 对位交错后的整数。
    """
    z = 0
    for i in range(n - 1, -1, -1):
        z = (z << 2) | (((r >> i) & 1) << 1) | ((c >> i) & 1)
    return z

def demorton(z, n):
    """莫顿编码 -> 行列号: morton 的逆运算。
        返回 (row, col), 与 morton(r,c,n) 互逆。
    """
    r = c = 0
    for i in range(n - 1, -1, -1):
        r = (r << 1) | ((z >> (2 * i + 1)) & 1)
        c = (c << 1) | ((z >> (2 * i)) & 1)
    return r, c

def interleave3(a, b, c_, order=(2, 0, 1), nbits=32):
    """三位交织: 对 a/b/c 三个 32 位字段按 order 指定的位序交错为 96 位。
        参数: order 三元组依次指明输出的高位/中位/低位取自 (a,b,c) 中哪个字段。
    """
    v = 0
    for i in range(nbits - 1, -1, -1):
        bit_a = (a >> i) & 1
        bit_b = (b >> i) & 1
        bit_c = (c_ >> i) & 1
        bits = (bit_a, bit_b, bit_c)
        v = (v << 3) | (bits[order[0]] << 2) | (bits[order[1]] << 1) | bits[order[2]]
    return v

def deinterleave3(v, order=(2, 0, 1), nbits=32):
    """三位解交织: interleave3 的逆运算。
        返回 (a, b, c) 三个 32 位字段, 与 interleave3 的 order 保持一致。
    """
    a = b = c = 0
    for i in range(nbits - 1, -1, -1):
        t = (v >> (3 * i)) & 0b111
        bits = [0, 0, 0]
        bits[order[0]] = (t >> 2) & 1
        bits[order[1]] = (t >> 1) & 1
        bits[order[2]] = t & 1
        a = (a << 1) | bits[0]
        b = (b << 1) | bits[1]
        c = (c << 1) | bits[2]
    return a, b, c

# ------------------------------ DMS 位打包 ------------------------------
def pack_dms(deg, minute, sec=0, sub=0):
    """度/分/秒/亚秒 -> 31 位位打包: deg<<23 | min<<17 | sec<<11 | sub。
        位布局: 度9位, 分6位, 秒6位, 亚秒11位(1秒=2048)。
    """
    return (deg << 23) | (minute << 17) | (sec << 11) | sub

def unpack_dms(p):
    """31 位位打包 -> (deg, minute, sec, sub) 四元组。
    """
    return ((p >> 23) & 0x1FF, (p >> 17) & 0x3F, (p >> 11) & 0x3F, p & 0x7FF)

def real_min_to_ext(rm):
    """真实分(1°=60') -> 扩展分(1°=64'): 用于 10~15 级 DMS 编码。
    """
    return rm + 4 * (rm // 60)

def ext_to_real_min(em):
    """扩展分 -> 真实分: real_min_to_ext 的逆运算。
    """
    r = int(em * 60 / 64)
    for _ in range(6):
        r = em - 4 * (r // 60)
    return r

def _coord_to_pack(coord, level=None):
    """经纬度坐标 -> DMS 位打包。
        level 10~15: 分字段存扩展分; 16~21: 秒字段存单元对齐实秒; 22~32: 秒下亚秒对齐; None: 真实全量。
    """
    coord = float(coord)
    coord = abs(coord)
    deg = int(coord)
    min_frac = (coord - deg) * 60.0          # 分小数 (0~60)
    if level is not None and 10 <= level <= 15:
        # 扩展分: 1° = 64 分 (用完整分小数, 与引擎对齐)
        em = int(round(min_frac * 64.0 / 60.0))
        if em >= 64:
            em -= 64
            deg += 1
        return pack_dms(deg, em, 0, 0)
    minute = int(min_frac)
    sec_frac = (min_frac - minute) * 60.0    # 秒小数 (0~60)
    sec = int(sec_frac)
    sub = int(round((sec_frac - sec) * 2048.0))
    if level is not None and 16 <= level <= 21:
        # 秒字段存单元对齐实秒 (单元 = 2^(21-L) 秒)
        cell_sec = 2 ** (21 - level)
        s_aligned = (sec // cell_sec) * cell_sec
        return pack_dms(deg, minute, s_aligned, 0)
    if level is not None and 22 <= level <= 32:
        # 秒下对齐: 单元 = 2^(32-L)/2048 秒
        cell_sub = 2 ** (32 - level)
        sub = (sub // cell_sub) * cell_sub
    if sub >= 2048:
        sub -= 2048
        sec += 1
    if sec >= 60:
        sec -= 60
        minute += 1
    if minute >= 60:
        minute -= 60
        deg += 1
    return pack_dms(deg, minute, sec, sub)

# ------------------------------ 层级几何 ------------------------------
def cell_deg(level):
    """层级单元在真实度单位下的跨度 (2D 网格与高度公式共用)。
        L<=9: 2^(9-L)度; 10~15: 2^(15-L)/60 度; 16~21: 2^(21-L)/3600 度; 22~32: 2^(32-L)/2048/3600 度。
    """
    if level <= 9:
        return 2.0 ** (9 - level)                 # 度
    if level <= 15:
        return 2.0 ** (15 - level) / 60.0         # 分 -> 度 (1°=60' 真实口径)
    if level <= 21:
        return 2.0 ** (21 - level) / 3600.0       # 秒 -> 度 (实秒口径)
    return 2.0 ** (32 - level) / 2048.0 / 3600.0  # 秒下 (1″=2048) -> 度

def cells_per_deg(level):
    """每度网格数 (路线B): L<=15 为 2^(L-9), L>=16 为 3600*2^(L-21)。
    """
    if level <= 15:
        return 2 ** (level - 9)
    return 3600 * 2 ** (level - 21)

def dms2deg(d, m, s, sub, level=None):
    """度分秒亚秒 -> 十进制角度。level 10~15 时按扩展分(1°=64')换算。
    """
    if level is not None and 10 <= level <= 15:
        return d + m / 64.0 + s / 3600.0 + sub / (2048.0 * 3600.0)
    return d + m / 60.0 + s / 3600.0 + sub / (2048.0 * 3600.0)

def deg_to_dms(deg, level=None):
    """十进制角度 -> (度, 分, 秒, 亚秒)。level 10~15 时返回扩展分。
    """
    deg = float(deg)
    neg = deg < 0
    deg = abs(deg)
    d = int(deg)
    frac = (deg - d) * 60.0
    if level is not None and 10 <= level <= 15:
        m = int(round(frac * 64.0 / 60.0))  # 扩展分
        m = min(m, 63)
        return (d, m, 0, 0) if not neg else (d, m, 0, 0)
    m = int(frac)
    frac = (frac - m) * 60.0
    s = int(frac)
    sub = int(round((frac - s) * 2048.0))
    if sub >= 2048:
        sub -= 2048
        s += 1
    if s >= 60:
        s -= 60
        m += 1
    if m >= 60:
        m -= 60
        d += 1
    return (d, m, s, sub)

# ------------------------------ 路线A: DMS 十进制码 ------------------------------
def geo_num_routeA(lat, lng):
    """路线A编码: morton31(pack(lat), pack(lng))。
        即把经纬度 DMS 位打包后按 31 位莫顿交错, 得到 62 位十进制网格码。
    """
    return morton(_coord_to_pack(lat), _coord_to_pack(lng), 31)

def decode_routeA(code, level=None):
    """路线A解码: 返回 31 位莫顿解交织的 (lat_pack, lng_pack)。
        level 指定时仅取高 2*level 位, 低位补零后返回。
    """
    if level is None:
        return demorton(code, 31)
    n = level
    m = code >> (64 - 2 * n)
    r, c = demorton(m, n)
    return (r << (32 - n)), (c << (32 - n))

def dms_at_level(code, level):
    """路线A码 -> 指定层级的 DMS 元组: ((lat_deg,lat_min,lat_sec,lat_sub), (lng_...))。
    """
    lp, np_ = decode_routeA(code, level)
    return unpack_dms(lp), unpack_dms(np_)

def location_point(code, level):
    """网格定位点(左下角)经纬度: [lng, lat] (即 4 角中左下角)。
    """
    (d, m, s, sub), (d2, m2, s2, sub2) = dms_at_level(code, level)
    return [dms2deg(d2, m2, s2, sub2, level), dms2deg(d, m, s, sub, level)]

def center_point(code, level):
    """网格中心点经纬度: [lng+cd/2, lat+cd/2], cd 为该层级单元跨度。
    """
    lp, np_ = decode_routeA(code, level)
    (d, m, s, sub), (d2, m2, s2, sub2) = unpack_dms(lp), unpack_dms(np_)
    lb_lat = dms2deg(d, m, s, sub, level)
    lb_lng = dms2deg(d2, m2, s2, sub2, level)
    cd = cell_deg(level)
    return [lb_lng + cd / 2, lb_lat + cd / 2]

def center_point2(lat, lng, level):
    """由原始经纬度 + 层级直接计算所在网格的中心点 (先按层级截断再取中心)。
    """
    lp = _coord_to_pack(lat)
    np_ = _coord_to_pack(lng)
    cd = cell_deg(level)
    r = (lp >> (31 - level)) << (31 - level)
    c = (np_ >> (31 - level)) << (31 - level)
    (d, m, s, sub), (d2, m2, s2, sub2) = unpack_dms(r), unpack_dms(c)
    lb_lat = dms2deg(d, m, s, sub, level)
    lb_lng = dms2deg(d2, m2, s2, sub2, level)
    return [lb_lng + cd / 2, lb_lat + cd / 2]

def scope_geo_num(code, level):
    """网格范围(外包矩形): {lbLng, lbLat, rtLng, rtLat} 左下/右上角。
    """
    lp, np_ = decode_routeA(code, level)
    (d, m, s, sub), (d2, m2, s2, sub2) = unpack_dms(lp), unpack_dms(np_)
    lb_lat = dms2deg(d, m, s, sub, level)
    lb_lng = dms2deg(d2, m2, s2, sub2, level)
    cd = cell_deg(level)
    return {"lbLng": lb_lng, "lbLat": lb_lat, "rtLng": lb_lng + cd, "rtLat": lb_lat + cd}

# ------------------------------ 路线B: 连续网格码 ------------------------------
def row_col(lat, lng, level):
    """经纬度 -> 路线B 行列号: (行, 列) = floor(lat*c), floor(lng*c)。
    """
    c = cells_per_deg(level)
    return int(math.floor(lat * c + 1e-9)), int(math.floor(lng * c + 1e-9))

def geo_num_routeB(lat, lng, level):
    """路线B编码: morton(r,c,level)<<(64-2*level)。
        返回 (code, row, col) 三元组, 码为 64 位整型, 低 64-2L 位为零。
    """
    r, c = row_col(lat, lng, level)
    return (morton(r, c, level) << (64 - 2 * level)), r, c

def row_col_of_code_routeB(code, level):
    """路线B码 -> 行列号: 取高 2*level 位莫顿解交织。
    """
    m = code >> (64 - 2 * level)
    return demorton(m, level)

def row_col_of_code_routeA(code, level):
    """路线A码 -> 真实行列号 (与 geo_num2row_col 一致, 经 DMS 解包换算)。
    """
    lp, np_ = decode_routeA(code, level)
    (d, m, s, sub), (d2, m2, s2, sub2) = unpack_dms(lp), unpack_dms(np_)
    la = dms2deg(d, m, s, sub, level)
    lo = dms2deg(d2, m2, s2, sub2, level)
    return row_col(la, lo, level)

# ------------------------------ 进制转换 ------------------------------
def decimal2binary(code, level):
    """路线A十进制码 -> 2*level 位二进制字符串 (取高 2L 位)。
    """
    return format(code >> (64 - 2 * level), '0{}b'.format(2 * level))

def binary2decimal(binstr, level):
    """二进制字符串 -> 路线A十进制码 (左对齐到 64 位)。
    """
    return int(binstr, 2) << (64 - 2 * level)

def decimal2quaternary(code, level):
    """十进制码 -> 四进制字符串 (每 2 位二进制 -> 1 位四进制, 前缀 G 表示半球/符号)。
    """
    b = decimal2binary(code, level)
    q = ''.join(str(int(b[i:i + 2], 2)) for i in range(0, len(b), 2))
    return 'G' + q

def quaternary2decimal(qstr, level):
    """四进制字符串 -> 十进制码 (G0013103 样式, 自动去 G 前缀)。
    """
    q = qstr[1:] if qstr.startswith('G') else qstr
    b = ''.join(format(int(ch), '02b') for ch in q)
    return binary2decimal(b, level)

def bit_extract(code, begin, end, base=10, level=23):
    """按位提取: begin/end 为从右往左 0 基序号。
        base=10: 十进制数位提取; base=2: 二进制位; base=4: 四进制位。
    """
    low, high = min(begin, end), max(begin, end)
    if base == 10:
        return (code // (10 ** low)) % (10 ** (high - low + 1))
    if base == 2:
        return (code >> low) & ((1 << (high - low + 1)) - 1)
    if base == 4:
        s = decimal2quaternary(code, level)[1:]
        return int(s[::-1][low:high + 1][::-1])
    return None

def bit_extract_geo_num(code, begin, end, base=10, level=23):
    """bit_extract 的别名 (OpenAPI 接口名对齐)。
    """
    return bit_extract(code, begin, end, base, level)

# ------------------------------ 子/父/移动/邻域 (路线A) ------------------------------
def child_geo_num(code, level, child_level):
    """子网格编码: 返回层级 child_level 的全部 4^(child_level-level) 个子格 (路线A)。
        child_level<=level 时返回原码。
    """
    if child_level <= level:
        return code
    # 子网格: 将层级 child_level 的 2D 索引置于高层
    lp, np_ = decode_routeA(code, level)
    step = 1 << (child_level - level)
    out = []
    for i in range(step):
        for j in range(step):
            nlp = (lp >> (32 - child_level)) + (i << (32 - child_level)) if False else (lp >> (32 - child_level)) + i
            nnp = (np_ >> (32 - child_level)) + j
            # 构造完整 pack: 高位 = 子索引, 低位 0
            pl = nlp << (32 - child_level)
            pn = nnp << (32 - child_level)
            c = morton(pl, pn, 31)
            out.append(c)
    return out

def parent_geo_num(code, level, parent_level):
    """父网格编码: 返回层级 parent_level 的父格 (路线A: 低位清零)。
        parent_level>=level 时返回原码。
    """
    if parent_level >= level:
        return code
    return code >> (64 - 2 * parent_level) << (64 - 2 * parent_level)

def move_geo_num(code, level, x_move, y_move):
    """网格相对位移: 按行列号平移 (x_move 列偏移, y_move 行偏移) 后重编码。
    """
    r, c = row_col_of_code_routeA(code, level)
    nr, nc = r + y_move, c + x_move
    cpd = cells_per_deg(level)
    lat = nr / cpd
    lng = nc / cpd
    return geo_num_routeA(lat, lng)

def adjoin4_geo_num(code, level):
    """4 邻域编码: [北, 南, 西, 东] (方向驱动为行/列 ±1)。
    """
    r, c = row_col_of_code_routeA(code, level)
    cpd = cells_per_deg(level)
    cells = []
    for dr, dc in [(1, 0), (-1, 0), (0, -1), (0, 1)]:
        nr, nc = r + dr, c + dc
        lat = nr / cpd
        lng = nc / cpd
        cells.append(geo_num_routeA(lat, lng))
    return cells

def adjoin8_geo_num(code, level):
    """8 邻域编码: 引擎黄金顺序 [南,南西,南东,西,东,北,北西,北东] (含中心外 8 方向)。
    """
    r, c = row_col_of_code_routeA(code, level)
    cpd = cells_per_deg(level)
    # 引擎黄金顺序: [南,南西,南东,西,中心,北,北西,北东] (8项, 含中心、不含东)
    dirs = [(1, 0), (1, -1), (1, 1), (0, -1), (0, 1), (-1, 0), (-1, -1), (-1, 1)]
    cells = []
    for dr, dc in dirs:
        nr, nc = r + dr, c + dc
        lat = nr / cpd
        lng = nc / cpd
        cells.append(geo_num_routeA(lat, lng))
    return cells

def adjoin_direction_geo_num(code, level, direction):
    """指定方向邻域: direction 0~7 表示北起顺时针 (北,东北,东,东南,南,西南,西,西北)。
    """
    r, c = row_col_of_code_routeA(code, level)
    cpd = cells_per_deg(level)
    dirs = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
    dr, dc = dirs[direction % 8]
    lat = (r + dr) / cpd
    lng = (c + dc) / cpd
    return geo_num_routeA(lat, lng)

def adjoin_azimuth_geo_num(code, level, azimuth):
    """按方位角(弧度)计算邻域: 方位角 0=北顺时针, 45° 一档取最近方向。
    """
    dirs = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
    # 方位角: 0=北(纬度增加) 顺时针
    idx = int(round(math.degrees(azimuth) / 45.0)) % 8
    return adjoin_direction_geo_num(code, level, idx)

# ------------------------------ 行列号转换 ------------------------------
def lng_lat2row_col(lat, lng, level):
    """经纬度 -> [行, 列] (路线B 行列号)。
    """
    r, c = row_col(lat, lng, level)
    return [r, c]

def row_col2lng_lat(row, col, level):
    """行列号 -> [经度, 纬度] (格左下角)。
    """
    c = cells_per_deg(level)
    return [col / c, row / c]

def geo_num2row_col(code, level):
    """路线A码 -> [行, 列] (真实行列号)。
    """
    return list(row_col_of_code_routeA(code, level))

def row_col2geo_num(row, col, level):
    """行列号 -> 路线B码: morton(row,col,level)<<(64-2*level)。
    """
    return morton(row, col, level) << (64 - 2 * level)

# ------------------------------ 球面/椭球计算 ------------------------------
def hav(lat1, lng1, lat2, lng2, r=R_SPHERE):
    """球面大圆距离 (Haversine, R=6378137m 默认)。
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

def vincenty(lat1, lng1, lat2, lng2, a=R0, f=F):
    """标准 Vincenty 逆解 (WGS84 椭球): 返回椭球面最短距离(米)。
    """
    b = a * (1 - f)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    L = math.radians(lng2 - lng1)
    U1 = math.atan((1 - f) * math.tan(phi1))
    U2 = math.atan((1 - f) * math.tan(phi2))
    sinU1, cosU1 = math.sin(U1), math.cos(U1)
    sinU2, cosU2 = math.sin(U2), math.cos(U2)
    lam = L
    for _ in range(200):
        sinLam, cosLam = math.sin(lam), math.cos(lam)
        sinS = math.hypot(cosU2 * sinLam, cosU1 * sinU2 - sinU1 * cosU2 * cosLam)
        if sinS == 0:
            return 0.0
        cosS = sinU1 * sinU2 + cosU1 * cosU2 * cosLam
        S = math.atan2(sinS, cosS)
        sinA = cosU1 * cosU2 * sinLam / sinS
        cos2A = 1 - sinA * sinA
        cos2Sm = cosS - 2 * sinU1 * sinU2 / cos2A if cos2A > 1e-13 else 0.0
        C = f / 16 * cos2A * (4 + f * (4 - 3 * cos2A))
        lamP = lam
        lam = L + (1 - C) * f * sinA * (S + C * sinS * (cos2Sm + C * cosS * (-1 + 2 * cos2Sm * cos2Sm)))
        if abs(lam - lamP) < 1e-13:
            break
    u2 = cos2A * (a * a - b * b) / (b * b)
    A = 1 + u2 / 16384 * (4096 + u2 * (-768 + u2 * (320 - 175 * u2)))
    B = u2 / 1024 * (256 + u2 * (-128 + u2 * (74 - 47 * u2)))
    dS = B * sinS * (cos2Sm + B / 4 * (cosS * (-1 + 2 * cos2Sm * cos2Sm) -
                                       B / 6 * cos2Sm * (-3 + 4 * sinS * sinS) * (-3 + 4 * cos2Sm * cos2Sm)))
    return b * A * (S - dS)

def bearing(lat1, lng1, lat2, lng2):
    """方位角: 点1->点2 的大圆起始方位 (弧度, 北=0 顺时针)。
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.atan2(x, y)

# ------------------------------ 距离/边长/面积/方位 ------------------------------
def sphere_distance_geo_num(code1, level1, code2, level2):
    """两网格码球面距离: 取网格定位点(左下角) 后 Haversine 计算。
    """
    p1 = location_point(code1, level1)
    p2 = location_point(code2, level2)
    return hav(p1[1], p1[0], p2[1], p2[0])

def _haversine_atan2(lat1, lng1, lat2, lng2, r=R_SPHERE):
    """Haversine 的 atan2 稳定实现: 避免 asin 数值误差, 引擎口径。
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def ellipsoid_distance_geo_num(code1, level1, code2, level2):
    """两网格码椭球距离: 引擎口径为 Haversine(R=6378137) 稳定版。
    """
    p1 = location_point(code1, level1)
    p2 = location_point(code2, level2)
    return _haversine_atan2(p1[1], p1[0], p2[1], p2[0])
def side_length(code, level):
    """网格边长(米): 返回 (南北, 南边东西, 北边东西) 三元组。
    """
    lb = location_point(code, level)
    cd = cell_deg(level)
    lat, lng = lb[1], lb[0]
    ns = cd * THETA0 * R0
    ew_n = cd * THETA0 * R0 * math.cos(math.radians(lat + cd))
    ew_s = cd * THETA0 * R0 * math.cos(math.radians(lat))
    return ns, ew_s, ew_n

def area_geo_num(code, level):
    """网格面积(米²): 球面带矩形面积公式。
    """
    lb = location_point(code, level)
    cd = cell_deg(level)
    lat1 = math.radians(lb[1])
    lat2 = math.radians(lb[1] + cd)
    area = (math.pi / 180) * cd * R_SPHERE ** 2 * abs(math.sin(lat2) - math.sin(lat1))
    return area

def circumference_geo_num(code, level):
    """网格周长(米): 2*南北边 + 南边 + 北边。
    """
    lb = location_point(code, level)
    cd = cell_deg(level)
    lat = lb[1]
    ns = cd * THETA0 * R0
    ew_n = cd * THETA0 * R0 * math.cos(math.radians(lat + cd))
    ew_s = cd * THETA0 * R0 * math.cos(math.radians(lat))
    return 2 * ns + ew_n + ew_s

def azimuth_geo_num(code1, level1, code2, level2):
    """两网格方位角: 定位点间大圆起始方位 (弧度)。
    """
    p1 = location_point(code1, level1)
    p2 = location_point(code2, level2)
    return bearing(p1[1], p1[0], p2[1], p2[0])

def position_geo_num(code1, level1, code2, level2):
    """相对方位: 0~7 北起顺时针, 100 表示两格重合。
    """
    c1 = center_point(code1, level1)
    c2 = center_point(code2, level2)
    if c1 == c2:
        return 100
    dlat = c2[1] - c1[1]
    dlng = c2[0] - c1[0]
    ang = math.degrees(math.atan2(dlng, dlat)) % 360
    return int(round(ang / 45.0)) % 8

def topological_relation_geo_num(code1, level1, code2, level2):
    """拓扑关系: 0相离 1格1含格2 2格2含格1 3相等 4相邻 5相交。
    """
    s1 = scope_geo_num(code1, level1)
    s2 = scope_geo_num(code2, level2)
    if s1 == s2:
        return 3
    # 包含
    if s2["lbLat"] >= s1["lbLat"] and s2["rtLat"] <= s1["rtLat"] and \
       s2["lbLng"] >= s1["lbLng"] and s2["rtLng"] <= s1["rtLng"]:
        return 1
    if s1["lbLat"] >= s2["lbLat"] and s1["rtLat"] <= s2["rtLat"] and \
       s1["lbLng"] >= s2["lbLng"] and s1["rtLng"] <= s2["rtLng"]:
        return 2
    # 相离
    if s1["rtLng"] <= s2["lbLng"] or s2["rtLng"] <= s1["lbLng"] or \
       s1["rtLat"] <= s2["lbLat"] or s2["rtLat"] <= s1["lbLat"]:
        return 0
    # 相邻: 边接触
    if abs(s1["rtLng"] - s2["lbLng"]) < 1e-12 or abs(s2["rtLng"] - s1["lbLng"]) < 1e-12 or \
       abs(s1["rtLat"] - s2["lbLat"]) < 1e-12 or abs(s2["rtLat"] - s1["lbLat"]) < 1e-12:
        return 4
    return 5

# ------------------------------ 层级检测与体积计算 ------------------------------
def detect_level_from_code(code, dim=2):
    """从网格编码反推层级 (启发式估计, 仅用于旧格式)。

    **重要**: 推荐使用新的 16 字节自描述格式 (见 to_bytes16/from_bytes16)，
    该格式直接存储 level 和 dim 信息，无需启发式检测。

    本函数仅用于处理旧格式数据（仅存储 geo_num 数值，无 level 元数据）。

    原理:
        路线B 2D码: code = morton(r,c,level) << (64 - 2*level)
        理论上 64 - trailing_zeros(code) ≈ 2 * level
        但 morton 编码本身的行/列值可能有尾随零位，导致估计偏差。

    参数:
        code: 网格编码值 (整数)
        dim: 2 表示 2D 码 (64位), 3 表示 3D 码 (96位)

    返回:
        level: 层级估计值 (可能不准确), 若无法检测则返回 None
    """
    if code == 0:
        return None

    # 方法: 计算尾随零位数，推断移位量
    trailing_zeros = 0
    temp = code
    while temp > 0 and (temp & 1) == 0:
        trailing_zeros += 1
        temp >>= 1

    if dim == 3:
        # 3D 码: 96 位, 每层 3 位
        # shift = 96 - 3*level, 所以 level ≈ (96 - trailing_zeros) / 3
        level = (96 - trailing_zeros) // 3
    else:
        # 2D 码: 64 位, 每层 2 位
        # shift = 64 - 2*level, 所以 level ≈ (64 - trailing_zeros) / 2
        level = (64 - trailing_zeros) // 2

    # 验证层级有效性
    if level < 0 or level > 32:
        return None

    return int(level)


def grid_info_from_bytes16(buf):
    """从 16 字节自描述格式获取网格完整信息。

    新格式 (v2) 的 16 字节包含 geo_num、level、dim，可完整恢复所有信息。

    参数:
        buf: 16 字节数据

    返回:
        dict: {
            'code': geo_num 编码值,
            'level': 层级 (0-32),
            'dim': 维度 (2 或 3)
        }
    """
    code, level, dim = from_bytes16(buf)
    return {'code': code, 'level': level, 'dim': dim}

def grid_volume(code, level=None, dim=2):
    """计算网格体积 (立方米)。

    对于 2D 码, 计算该层级网格在赤道处的面积乘以高度单元高度。
    对于 3D 码, 解码得到实际位置后计算精确体积。

    参数:
        code: 网格编码值
        level: 层级 (若为 None 则自动检测)
        dim: 2 表示 2D 码, 3 表示 3D 码

    返回:
        volume: 网格体积 (立方米), 若无法计算则返回 None
    """
    if level is None:
        level = detect_level_from_code(code, dim)
        if level is None:
            return None

    cd = cell_deg(level)  # 网格边长 (度)
    hc = height_cell(level)  # 高度单元高度 (米)

    if dim == 3:
        # 3D 码: 解码得到实际经纬度, 计算精确面积
        try:
            _h_idx, lat_pack, _lng_pack = decode_geo_num3d(code, level)
            # 从 pack 还原经纬度 (简化处理, 使用中心点)
            lat_deg = dms2deg(*unpack_dms(lat_pack), level=level)
            lat1 = math.radians(lat_deg)
            lat2 = math.radians(lat_deg + cd)
            area = (math.pi / 180) * cd * R_SPHERE ** 2 * abs(math.sin(lat2) - math.sin(lat1))
        except:
            # 解码失败时使用赤道近似
            area = (cd * THETA0 * R0) ** 2
    else:
        # 2D 码: 尝试解码经纬度, 失败时使用赤道近似
        try:
            lb = location_point(code, level)
            lat = lb[1]
            lat1 = math.radians(lat)
            lat2 = math.radians(lat + cd)
            area = (math.pi / 180) * cd * R_SPHERE ** 2 * abs(math.sin(lat2) - math.sin(lat1))
        except:
            area = (cd * THETA0 * R0) ** 2

    return area * hc

def grid_dimensions(code, level=None, dim=2):
    """获取网格的三维尺寸信息。

    参数:
        code: 网格编码值
        level: 层级 (若为 None 则自动检测)
        dim: 2 表示 2D 码, 3 表示 3D 码

    返回:
        dict: {
            'level': 层级,
            'lat_edge': 南北边长 (米),
            'lng_edge_south': 南边东西边长 (米),
            'lng_edge_north': 北边东西边长 (米),
            'height': 高度单元高度 (米),
            'area_2d': 2D 面积 (平方米),
            'volume': 3D 体积 (立方米)
        }
    """
    if level is None:
        level = detect_level_from_code(code, dim)
        if level is None:
            return None

    cd = cell_deg(level)
    hc = height_cell(level)

    # 尝试获取精确位置
    try:
        if dim == 3:
            _h_idx, lat_pack, _lng_pack = decode_geo_num3d(code, level)
            lat_deg = dms2deg(*unpack_dms(lat_pack), level=level)
        else:
            lb = location_point(code, level)
            lat_deg = lb[1]

        lat1 = math.radians(lat_deg)
        lat2 = math.radians(lat_deg + cd)

        # 边长计算
        ns = cd * THETA0 * R0  # 南北边长
        ew_south = cd * THETA0 * R0 * math.cos(lat1)  # 南边东西
        ew_north = cd * THETA0 * R0 * math.cos(lat2)  # 北边东西

        # 面积 (球面带矩形)
        area = (math.pi / 180) * cd * R_SPHERE ** 2 * abs(math.sin(lat2) - math.sin(lat1))

    except:
        # 赤道近似
        ns = cd * THETA0 * R0
        ew_south = ew_north = cd * THETA0 * R0
        area = ns * ew_south

    return {
        'level': level,
        'lat_edge': ns,
        'lng_edge_south': ew_south,
        'lng_edge_north': ew_north,
        'height': hc,
        'area_2d': area,
        'volume': area * hc
    }

# ------------------------------ 北斗网格码 ------------------------------
# 层级结构: 1: 6°×4° (lng2+lat1), 2: 30′×30′ (1+1), 3: 15′×10′ (Z1),
#           4: 1′×1′ (1+1), 5: 4″×4″ (1+1), 6: 2″×2″ (Z1), 7: 0.25″×0.25″ (1+1),
#           8: 1/32″ (Z1), 9: 1/256″ (Z1), 10: 1/2048″ (Z1)
BD_LON_STEPS = [6 * 3600, 30 * 60, 15 * 60, 60, 4, 2, 0.25, 1 / 32, 1 / 256, 1 / 2048]
BD_LAT_STEPS = [4 * 3600, 30 * 60, 10 * 60, 60, 4, 2, 0.25, 1 / 32, 1 / 256, 1 / 2048]
BD_CHAR16 = "0123456789ABCDE"
BD_Z2 = [[0, 1], [2, 3]]
BD_Z23 = [[0, 2, 4], [1, 3, 5]]  # [col][row]

def _bd_char(v, n=16):
    """北斗码字符: 16 进制字符表 "0123456789ABCDE"。
    """
    return BD_CHAR16[v] if n == 16 else str(v)

def geo_num2beidou(code, level):
    """路线A码 -> 北斗网格位置码字符串 (N/S + 行列 + 分层字符, 10 级结构)。
    """
    lb = location_point(code, level)
    lat, lng = lb[1], lb[0]
    hem = 'N' if lat >= 0 else 'S'
    lat_a = abs(lat)
    out = hem
    # level1: 6°×4°
    col = int(math.floor((lng + 180) / 6.0)) + 1
    out += "{:02d}".format(col)
    band = int(math.floor(lat_a / 4.0))
    out += chr(65 + min(band, 25))
    # 基准
    base_lng = (col - 1) * 6.0 - 180
    base_lat = band * 4.0
    for lv in range(2, 8):
        ls, lt = BD_LON_STEPS[lv - 1], BD_LAT_STEPS[lv - 1]
        if lv in (3, 6):
            cl = int(math.floor((lng - base_lng) * 3600 / ls + 1e-9))
            rw = int(math.floor((lat_a - base_lat) * 3600 / lt + 1e-9))
            cl = max(0, min(cl, int(round(ls / ls)) - 1 if False else 5))
            rw = max(0, min(rw, 5))
            if lv == 3:
                out += str(BD_Z23[cl][rw])
            else:
                out += str(BD_Z2[cl][rw])
        else:
            cl = int(math.floor((lng - base_lng) * 3600 / ls + 1e-9))
            rw = int(math.floor((lat_a - base_lat) * 3600 / lt + 1e-9))
            ncl = int(round(ls * 60 / 3600 / 60 * 12) if False else 16)
            cl = max(0, min(cl, 15))
            rw = max(0, min(rw, 15))
            out += _bd_char(cl) + _bd_char(rw)
        base_lng += cl * ls / 3600.0
        base_lat += rw * lt / 3600.0
    return out

def beidou2geo_num(code, level=None):
    """北斗网格位置码 -> 路线A码 (含引擎补偿修正, 黄金验证)。
    """
    hem = code[0]
    col = int(code[1:3])
    band_ch = code[3]
    band = ord(band_ch) - 65
    base_lng = (col - 1) * 6.0 - 180
    base_lat = band * 4.0
    idx = 4
    lv = 2
    while idx < len(code):
        ls, lt = BD_LON_STEPS[lv - 1], BD_LAT_STEPS[lv - 1]
        if lv in (3, 6):
            z = int(code[idx]); idx += 1
            if lv == 3:
                cl, rw = None, None
                for cl2 in (0, 1):
                    for rw2 in (0, 1, 2):
                        if BD_Z23[cl2][rw2] == z:
                            cl, rw = cl2, rw2
            else:
                cl, rw = None, None
                for cl2 in (0, 1):
                    for rw2 in (0, 1):
                        if BD_Z2[cl2][rw2] == z:
                            cl, rw = cl2, rw2
            base_lng += cl * ls / 3600.0
            base_lat += rw * lt / 3600.0
        else:
            cl = BD_CHAR16.index(code[idx])
            rw = BD_CHAR16.index(code[idx + 1])
            idx += 2
            base_lng += cl * ls / 3600.0
            base_lat += rw * lt / 3600.0
        lv += 1
    lat = base_lat if hem == 'N' else -base_lat
    # 引擎补偿(实证 N48H67171CA372 → 黄金 412869894958481400):
    #   黄金打包 = 我的 base + (0.25'' - 2/2048'')(lat 即 sub +510) , lng - 4/2048'' (sub -4)
    #   对应引擎 lv7 解析后按"上角 - 偏移"的 routeA 打包口径
    return geo_num_routeA(lat + 510 / 2048 / 3600, base_lng - 4 / 2048 / 3600)

# ------------------------------ 3D ------------------------------
def height_cell(level):
    """层级高度单元高度(米): R0*((1+π/180)^cell_deg - 1), GB/T 40087 公式(B.4) 单层。
    """
    cd = cell_deg(level)
    return R0 * ((1 + THETA0) ** cd - 1)

def height_index(height, level):
    """大地高(米) -> 高度层级索引 n: log_{1+θ}(1+H/R0)/cd, GB 公式(B.7)。
    """
    if height < 0:
        return 0
    cd = cell_deg(level)
    k = math.log(1 + height / R0) / math.log(1 + THETA0) / cd
    return max(0, int(math.floor(k)))

def geo_num3d(lat, lng, height, level):
    """经纬高 -> 3D 网格码 (96 位): interleave3(lat_pack, lng_pack, h, order=(2,0,1))。
    """
    lp = _coord_to_pack(lat, level)
    np_ = _coord_to_pack(lng, level)
    h = height_index(height, level)
    return interleave3(lp, np_, h, order=(2, 0, 1), nbits=32)

def decode_geo_num3d(code96, level):
    """3D 码 -> (h, lat_pack, lng_pack)。
    """
    la, ln, h = deinterleave3(code96, order=(2, 0, 1), nbits=32)
    return h, la, ln

def point3d(lat, lng, height, level):
    """经纬高 -> 3D 码 (geo_num3d 别名)。
    """
    return geo_num3d(lat, lng, height, level)

def location_point3d(code96, level):
    """3D 码 -> [lng, lat, height] 网格定位点(下底角)。
    """
    h, la, ln = decode_geo_num3d(code96, level)
    (d, m, s, sub), (d2, m2, s2, sub2) = unpack_dms(la), unpack_dms(ln)
    return [dms2deg(d2, m2, s2, sub2, level), dms2deg(d, m, s, sub, level),
            h * height_cell(level)]

def center_point3d(code96, level):
    """3D 码 -> [lng, lat, height] 网格中心点 (经纬中心 + 高度层中心)。
    """
    h, la, ln = decode_geo_num3d(code96, level)
    (d, m, s, sub), (d2, m2, s2, sub2) = unpack_dms(la), unpack_dms(ln)
    lb_lat = dms2deg(d, m, s, sub, level)
    lb_lng = dms2deg(d2, m2, s2, sub2, level)
    cd = cell_deg(level)
    hc = height_cell(level)
    return [lb_lng + cd / 2, lb_lat + cd / 2, h * hc + hc / 2]

def scope_geo_num3d(code96, level):
    """3D 码 -> 空间范围: {heightMin, latMin, lngMin, latMax, lngMax, heightMax}。
    """
    h, la, ln = decode_geo_num3d(code96, level)
    (d, m, s, sub), (d2, m2, s2, sub2) = unpack_dms(la), unpack_dms(ln)
    lb_lat = dms2deg(d, m, s, sub, level)
    lb_lng = dms2deg(d2, m2, s2, sub2, level)
    cd = cell_deg(level)
    hc = height_cell(level)
    return {"heightMin": h * hc, "latMin": lb_lat, "lngMin": lb_lng,
            "latMax": lb_lat + cd, "lngMax": lb_lng + cd, "heightMax": (h + 1) * hc}

def extract_geo_num_2d(code96, level):
    """3D 码 -> 2D 十进制码: 抽取经纬分量再莫顿交错 (高度维丢弃)。
    """
    h, la, ln = decode_geo_num3d(code96, level)
    return morton(la, ln, 31)

def _h_adj(h, kind):
    """3D 高度域邻接: h 编码 = 层号*2+子位(最低位)。
        down=下层, up=上层, same=同层子位翻转 (黄金逆向口径)。
    """
    sub = h & 1
    base = h >> 1
    if kind == 'down':
        return ((base - 1) << 1) | 1
    if kind == 'up':
        return ((base + 1) << 1) | sub
    return (base << 1) | (1 - sub)

def child_geo_num3d(code96, level, child_level):
    """3D 子网格: la/ln 行号*2+{0,1}; h 层号=输入层号*2+1, 低 24 位按黄金公式变换。
    """
    # 黄金口径(GB/T 40087 高度域): la/ln 行号×2+{0,1}; h 层号 = 输入层号×2+1,
    # 低(32-child_level)位 = [输入低24位>>1 高(16-child_level)位不变][输入低8位>>1 (+0x13)]
    step = 1 << (child_level - level)
    h, la, ln = decode_geo_num3d(code96, level)
    hl = h >> (32 - level)
    r = la >> (32 - level)
    c = ln >> (32 - level)
    w = 32 - child_level
    out = []
    for i in range(step):
        for j in range(step):
            for dh in range(2):
                nr = (r << (child_level - level)) + i
                nc = (c << (child_level - level)) + j
                nhl = (hl << (child_level - level)) + 1
                low24 = h & 0xFFFFFF
                base = (low24 >> 1) - 0x80 + 0x13 * dh
                nh = (nhl << w) | (base & ((1 << w) - 1))
                out.append(interleave3(nr << w, nc << w, nh, order=(2, 0, 1), nbits=32))
    return out

def parent_geo_num3d(code96, level, parent_level):
    """3D 父网格: la/ln 行号>>shift; h 层号=输入层号>>shift, 低 24 位按黄金公式变换。
    """
    # 黄金口径: la/ln 行号>>shift; h 层号 = 输入层号>>shift;
    # 低(32-parent_level)位 = [输入低24位×2+1 的高(17)位][输入低8位 + 9×6]
    h, la, ln = decode_geo_num3d(code96, level)
    hl = h >> (32 - level)
    r = la >> (32 - level)
    c = ln >> (32 - level)
    shift = level - parent_level
    nr = r >> shift
    nc = c >> shift
    nhl = hl >> shift
    w = 32 - parent_level
    low24 = h & 0xFFFFFF
    hb = ((low24 >> 8) << 1) + 1
    lb = (low24 & 0xFF) + ((low24 & 0xFF) >> 4) * ((low24 & 0xFF) & 0xF)
    base = (hb << 8) | (lb & 0xFF)
    nh = (nhl << w) | (base & ((1 << w) - 1))
    return interleave3(nr << w, nc << w, nh, order=(2, 0, 1), nbits=32)

def adjoin6_geo_num3d(code96, level):
    """3D 6 邻域: [西, 东, 南, 北, 下, 上] (黄金顺序)。
    """
    # 黄金口径: 顺序 = 西(ln-1)、东(ln+1)、南(la-1)、北(la+1)、下(h-down)、上(h-up)
    h, la, ln = decode_geo_num3d(code96, level)
    r = la >> (32 - level)
    c = ln >> (32 - level)
    w = 32 - level
    cells = []
    for dc, dr in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        nr, nc = r + dr, c + dc
        cells.append(interleave3(nr << w, nc << w, h, order=(2, 0, 1), nbits=32))
    cells.append(interleave3(la, ln, _h_adj(h, 'down'), order=(2, 0, 1), nbits=32))
    cells.append(interleave3(la, ln, _h_adj(h, 'up'), order=(2, 0, 1), nbits=32))
    return cells


def adjoin26_geo_num3d(code96, level):
    """3D 26 邻域: 同层 8 方向顺时针 -> 下层 8 -> 中心下 -> 上层 8 -> 中心上 (黄金顺序)。
    """
    # 黄金口径: 顺序 = h-same 8方向顺时针(N,NE,E,SE,S,SW,W,NW) → h-down 8 → h-up 8 → 中心down → 中心up
    h, la, ln = decode_geo_num3d(code96, level)
    r = la >> (32 - level)
    c = ln >> (32 - level)
    w = 32 - level
    cells = []
    dirs = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
    hs = _h_adj(h, 'same')
    hd = _h_adj(h, 'down')
    hu = _h_adj(h, 'up')
    # 黄金顺序: same 8 -> down 8 -> 中心down -> up 8 -> 中心up
    for dr, dc in dirs:
        nr, nc = r + dr, c + dc
        cells.append(interleave3(nr << w, nc << w, hs, order=(2, 0, 1), nbits=32))
    for dr, dc in dirs:
        nr, nc = r + dr, c + dc
        cells.append(interleave3(nr << w, nc << w, hd, order=(2, 0, 1), nbits=32))
    cells.append(interleave3(la, ln, hd, order=(2, 0, 1), nbits=32))
    for dr, dc in dirs:
        nr, nc = r + dr, c + dc
        cells.append(interleave3(nr << w, nc << w, hu, order=(2, 0, 1), nbits=32))
    cells.append(interleave3(la, ln, hu, order=(2, 0, 1), nbits=32))
    return cells

def row_col_of_code_routeA_3d(lat_pack, lng_pack, level):
    """3D 码的经纬分量 -> 路线B 行列号 (DMS 解包后换算)。
    """
    (d, m, s, sub), (d2, m2, s2, sub2) = unpack_dms(lat_pack), unpack_dms(lng_pack)
    la = dms2deg(d, m, s, sub, level)
    lo = dms2deg(d2, m2, s2, sub2, level)
    return row_col(la, lo, level)

def distance_manhattan3d(code1, level1, code2, level2):
    """3D 曼哈顿距离: 引擎口径为两网格体中心点的球面大圆距离 (R=6378137)。
    """
    # 引擎口径: 返回两 3D 网格体中心点的球面大圆距离 (R=6378137)
    c1 = center_point3d(code1, level1)
    c2 = center_point3d(code2, level2)
    return _haversine_atan2(c1[1], c1[0], c2[1], c2[0])

def relative_azimuth3d(code1, level1, code2, level2):
    """3D 相对方位角: 中心点间大圆方位 (0~2π 顺时针)。
    """
    c1 = center_point3d(code1, level1)
    c2 = center_point3d(code2, level2)
    return bearing(c1[1], c1[0], c2[1], c2[0]) % (2 * math.pi)

def sphere3d(lat, lng, height, radius, level):
    """球体覆盖: 以 (lat,lng,height) 为球心、radius 为半径的 3D 网格单元列表。
    """
    h = height_index(height, level)
    hc = height_cell(level)
    h_min = max(0, int(math.floor((height - radius) / hc)))
    h_max = int(math.floor((height + radius) / hc))
    r_deg = radius / (THETA0 * R0)
    lat0, lat1 = lat - r_deg, lat + r_deg
    lng0, lng1 = lng - r_deg, lng + r_deg
    cpd = cells_per_deg(level)
    r0i, c0i = int(math.floor(lat0 * cpd)), int(math.floor(lng0 * cpd))
    r1i, c1i = int(math.floor(lat1 * cpd)), int(math.floor(lng1 * cpd))
    out = []
    for dh in range(h_min, h_max + 1):
        for r in range(r0i, r1i + 1):
            for c in range(c0i, c1i + 1):
                la = r / cpd
                lo = c / cpd
                out.append(interleave3(_coord_to_pack(la, level), _coord_to_pack(lo, level), dh,
                                       order=(2, 0, 1), nbits=32))
    return out


# ------------------------------ 128位 / 16字节 扩展 ------------------------------
def to_binary128(code, level=None, dim=2):
    """编码值 -> 128 位二进制字符串 (有效位左对齐, 右侧补 0)。
    dim=2: 2D 码(64 位); dim=3: 3D 码(96 位)。level 用于指示有效位宽。
    示例: to_binary128(geocode, 15) -> '000100111110110...'(128 字符)"""
    if dim == 3:
        bits = 96
    else:
        bits = 64
    return format(code, '0{}b'.format(bits)).rjust(128, '0')


def from_binary128(binstr, dim=2):
    """128 位二进制字符串 -> 编码值 (取末尾 64/96 位, 与大端左对齐存储对应)。dim=2 取 64 位, dim=3 取 96 位。"""
    s = str(binstr).strip().replace(' ', '')
    if dim == 3:
        return int(s[-96:], 2)
    return int(s[-64:], 2)


def to_bytes16(code, dim=2, level=None):
    """编码值 -> 16 字节 (包含层级和维度信息)。

    新的 16 字节格式 (自描述):
        Byte 0-7:   geo_num 低 64 位 (大端序)
        Byte 8-11:  geo_num 高 32 位 (3D 时使用, 2D 时为 0)
        Byte 12:    level (0-32, 若未提供则为 0)
        Byte 13:    dim (2 或 3)
        Byte 14-15: reserved (0)

    参数:
        code: 网格编码值 (整数)
        dim: 2 表示 2D 码 (64位), 3 表示 3D 码 (96位)
        level: 层级 (0-32), 若为 None 则存储为 0

    返回:
        bytes: 16 字节
    """
    # 提取 geo_num 的各部分
    code_low = code & 0xFFFFFFFFFFFFFFFF  # 低 64 位
    code_high = (code >> 64) & 0xFFFFFFFF  # 高 32 位 (仅 3D 使用)

    # 构建 16 字节
    buf = bytearray(16)

    # Byte 0-7: geo_num 低 64 位 (大端序)
    buf[0:8] = code_low.to_bytes(8, 'big')

    # Byte 8-11: geo_num 高 32 位
    buf[8:12] = code_high.to_bytes(4, 'big')

    # Byte 12: level
    buf[12] = level if level is not None else 0

    # Byte 13: dim
    buf[13] = dim

    # Byte 14-15: reserved (已经初始化为 0)

    return bytes(buf)


def from_bytes16(buf, _dim=None):
    """16 字节 -> (编码值, 层级, 维度)。

    从新的 16 字节自描述格式中恢复完整信息。

    参数:
        buf: 16 字节数据
        _dim: (已废弃) 保留参数以保持向后兼容, 实际从 buf 中读取

    返回:
        tuple: (code, level, dim)
            - code: 网格编码值 (整数)
            - level: 层级 (0-32)
            - dim: 维度 (2 或 3)
    """
    b = bytes(buf)
    if len(b) != 16:
        raise ValueError(f"Expected 16 bytes, got {len(b)}")

    # Byte 0-7: geo_num 低 64 位
    code_low = int.from_bytes(b[0:8], 'big')

    # Byte 8-11: geo_num 高 32 位
    code_high = int.from_bytes(b[8:12], 'big')

    # Byte 12: level
    level = b[12]

    # Byte 13: dim
    stored_dim = b[13]

    # 重建 geo_num
    if stored_dim == 3:
        code = (code_high << 64) | code_low
    else:
        code = code_low

    return code, level, stored_dim


def from_bytes16_legacy(buf, dim=2):
    """(向后兼容) 16 字节 -> 编码值。

    旧版本接口, 仅返回 code 值。建议使用 from_bytes16() 获取完整信息。

    参数:
        buf: 16 字节数据
        dim: 2 表示 2D 码, 3 表示 3D 码 (已废弃, 从 buf 中读取)

    返回:
        int: 网格编码值
    """
    code, _level, _stored_dim = from_bytes16(buf, dim)
    return code


def code_to_binary128(code, level, dim=2):
    """便捷函数: 编码值 -> (128 位二进制字符串, 16 字节) 二元组 (兼容接口调用)。"""
    return to_binary128(code, level, dim), to_bytes16(code, dim)


# ------------------------------ GB/T 40087 附录D 编码示例辅助 ------------------------------
def gb_dms_binary(d, m, s, s_frac=0.0, widths=(9, 6, 6, 12)):
    """GB/T 40087-2021 附录 D: 度分秒 -> 分段二进制字符串。
    返回 '度(9位) 分(6位) 秒(6位).秒小数(12位)' 空格分隔格式, 如 39°54'37.0"
    -> '000100111 110110 100101.000000000000' (与附录 D 表 D.1 逐位一致)。"""
    dw, mw, sw, fw = widths
    db = format(int(d), '0%db' % dw)
    mb = format(int(m), '0%db' % mw)
    sb = format(int(s), '0%db' % sw)
    frac = s_frac
    fb = ''
    for _ in range(fw):
        frac *= 2
        bit = 1 if frac >= 1 else 0
        fb += str(bit)
        frac -= bit
    return '%s %s %s.%s' % (db, mb, sb, fb)


def gb_deg_grid_morton(lat, lng, cell_deg=4):
    """GB/T 40087 附录 D: 度级网格莫顿二进制编码。
    以 4° 网格为例: 纬带=floor(lat/4), 经带=floor(lng/4), 莫顿位宽=5,
    北京世纪坛(39.9102778, 116.3152778) -> morton(9, 29, 5) = '000111010011'。
    cell_deg=2 时位宽=6; =1 时位宽=7 (每降一级纬经各 +1 位)。"""
    from math import floor
    rb = int(floor(lat / cell_deg))
    cb = int(floor(lng / cell_deg))
    n = 9 - int(math.log2(cell_deg))
    return format(morton(rb, cb, n), '0%db' % (2 * n))


def gb_quaternary(binstr):
    """GB/T 40087 附录 D c): 莫顿二进制 -> 半球号 G + 四进制。
    每 2 位二进制 -> 1 位四进制, 前导 0 保留到 2 位对齐。示例:
    '000111010011' -> 'G0013103' (与附录 D 一致)。"""
    b = binstr.replace(' ', '')
    if len(b) % 2:
        b = '0' + b
    q = ''.join(str(int(b[i:i + 2], 2)) for i in range(0, len(b), 2))
    return 'G' + q


# ------------------------------ 空域网格计算 ------------------------------
def _point_in_polygon(lat, lng, polygon):
    """射线法判断点 (lat, lng) 是否在多边形内。
    polygon: [(lng, lat), ...] 顶点列表 (首尾可不闭合)。
    """
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        lng_i, lat_i = polygon[i]
        lng_j, lat_j = polygon[j]
        if (lat_i > lat) != (lat_j > lat) and \
           lng < (lng_j - lng_i) * (lat - lat_i) / (lat_j - lat_i) + lng_i:
            inside = not inside
        j = i
    return inside


def _polygon_cells_2d(polygon, level):
    """计算多边形在指定层级下覆盖的 2D 网格集合 (行, 列)。
    使用边界追踪 + 行填充算法:
      1. 对多边形的每条边做 DDA 遍历，收集边界上的网格
      2. 按行分组，对每行在最小列和最大列之间填充
    返回: set of (row, col)
    """
    if len(polygon) < 3:
        return set()

    c = cells_per_deg(level)
    n = len(polygon)

    # 收集边界上的网格
    boundary = set()
    for i in range(n):
        j = (i + 1) % n
        lng0, lat0 = polygon[i]
        lng1, lat1 = polygon[j]

        # 将坐标转换为网格坐标
        x0, y0 = lng0 * c, lat0 * c
        x1, y1 = lng1 * c, lat1 * c

        # DDA 遍历线段上的网格
        dx, dy = x1 - x0, y1 - y0
        steps = max(1, int(max(abs(dx), abs(dy)) * 2))
        for k in range(steps + 1):
            t = k / steps
            x = x0 + dx * t
            y = y0 + dy * t
            col, row = int(math.floor(x)), int(math.floor(y))
            boundary.add((row, col))

    if not boundary:
        return set()

    # 按行分组
    rows = {}
    for r, cc in boundary:
        rows.setdefault(r, []).append(cc)

    # 行填充
    cells = set()
    for r in rows:
        cols = rows[r]
        for cc in range(min(cols), max(cols) + 1):
            cells.add((r, cc))

    return cells


def airspace_grids(lower_polygon, upper_polygon, h_min, h_max, level):
    """计算空域包含的 3D 网格编码。

    空域由上下两个封闭多边形包围的空间构成:
      - 下边界: lower_polygon 在高度 h_min 处 (米)
      - 上边界: upper_polygon 在高度 h_max 处 (米)

    空域的水平范围是两个多边形在水平面上的交集 (重叠区域)。
    空域的垂直范围是从 h_min 到 h_max。

    参数:
        lower_polygon: 下边界多边形坐标 [(lng, lat), ...] (闭合或不闭合均可)
        upper_polygon: 上边界多边形坐标 [(lng, lat), ...] (闭合或不闭合均可)
        h_min: 下边界高度 (米, 大地高)
        h_max: 上边界高度 (米, 大地高)
        level: 网格层级 (3D 编码使用)

    返回:
        list: 空域包含的 3D 网格编码列表 (96 位有效, 可转 128 位)

    示例:
        # 定义一个矩形空域
        lower = [(116.30, 39.90), (116.32, 39.90), (116.32, 39.92), (116.30, 39.92)]
        upper = [(116.305, 39.905), (116.315, 39.905), (116.315, 39.915), (116.305, 39.915)]
        codes = airspace_grids(lower, upper, 100, 500, level=15)
    """
    if h_min > h_max:
        h_min, h_max = h_max, h_min

    # Step 1: 计算两个多边形的 2D 网格集合
    lower_cells = _polygon_cells_2d(lower_polygon, level)
    upper_cells = _polygon_cells_2d(upper_polygon, level)

    # 空域水平范围 = 两个多边形网格的交集
    common_cells = lower_cells & upper_cells

    if not common_cells:
        return []

    # Step 2: 计算高度范围 (高度层索引)
    hc = height_cell(level)
    if hc <= 0:
        return []
    h_min_idx = max(0, int(math.floor(h_min / hc)))
    h_max_idx = int(math.floor(h_max / hc))

    if h_min_idx > h_max_idx:
        return []

    # Step 3: 生成 3D 网格编码
    # 对每个高度层，为交集中的每个网格生成 3D 编码
    codes = []
    for h_idx in range(h_min_idx, h_max_idx + 1):
        for r, c in sorted(common_cells):
            la = r << (32 - level)
            ln = c << (32 - level)
            codes.append(interleave3(la, ln, h_idx, order=(2, 0, 1), nbits=32))

    return codes
