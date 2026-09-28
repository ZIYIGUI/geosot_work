"""Verified-formula subset, explicitly NOT a full GB/T 40087 wire-code implementation.

Profile gbt40087_partial_v1 supports NE, nonpolar coordinates, levels 9..32,
0..20 km ellipsoidal height. Keys are engineering identifiers and cannot be
mixed with iWhere legacy 96-bit codes. No coordinate/datum transformation.
"""
import math
from decimal import Decimal
import geosot_core as gc

PROFILE = 'gbt40087_partial_v1'
CRS = 'CGCS2000-geodetic'
HEIGHT_REFERENCE = 'ellipsoidal_m'
MAX_HEIGHT = 20000.0


def _level(level):
    if isinstance(level, bool) or not isinstance(level, int) or not 9 <= level <= 32:
        raise ValueError('partial profile supports integer levels 9..32')
    return level


def _context(crs, height_reference):
    if crs != CRS or height_reference != HEIGHT_REFERENCE:
        raise ValueError('explicit CGCS2000-geodetic and ellipsoidal_m required; no datum conversion is performed')


def _coord_pack(value):
    # True DMS, padded bit fields; no 64/60 stretching and no rounding up.
    # Snap only representational roundoff, <= four input-coordinate ULPs.
    # Returned decimal-degree lower bounds may not have exact float encodings.
    ticks_decimal = Decimal(str(value)) * Decimal(3600 * 2048)
    nearest = ticks_decimal.to_integral_value()
    tolerance = Decimal(str(4 * math.ulp(float(value)) * 3600 * 2048))
    if abs(ticks_decimal - nearest) <= tolerance:
        ticks_decimal = nearest
    ticks = int(ticks_decimal)
    degree, rem = divmod(ticks, 3600 * 2048)
    minute, rem = divmod(rem, 60 * 2048)
    second, sub = divmod(rem, 2048)
    return (degree << 23) | (minute << 17) | (second << 11) | sub



def _coord_bounds(index, level):
    if not isinstance(index, int) or index < 0:
        raise ValueError('nonnegative coordinate index required')
    packed = index << (32 - level)
    if packed >= (1 << 31):
        raise ValueError('coordinate index exceeds NE domain')
    degree, minute, second, sub = gc.unpack_dms(packed)
    if minute >= 60 or second >= 60:
        raise ValueError('virtual DMS padding cells have no geographic meaning')
    lower = degree + minute / 60 + second / 3600 + sub / (2048 * 3600)
    if level <= 9:
        upper = lower + 2 ** (9 - level)
    elif level <= 15:
        upper = degree + min(60, minute + 2 ** (15 - level)) / 60
    elif level <= 21:
        upper = degree + minute / 60 + min(60, second + 2 ** (21 - level)) / 3600
    else:
        upper = lower + 2 ** (32 - level) / (2048 * 3600)
    return lower, upper


def height_boundary(index, level):
    """GB/T 40087 Appendix B formula, theta/theta0 = cell_deg(level)."""
    _level(level)
    if not isinstance(index, int) or index < 0:
        raise ValueError('negative/unknown height coding is outside this partial profile')
    return gc.R0 * math.expm1(index * gc.cell_deg(level) * math.log1p(gc.THETA0))


def height_index(height, level):
    _level(level)
    if isinstance(height, bool):
        raise ValueError('boolean height is not a number')
    height = float(height)
    if not math.isfinite(height) or not 0 <= height <= MAX_HEIGHT:
        raise ValueError('partial profile supports finite 0..20000 m ellipsoidal height')
    raw = math.log1p(height / gc.R0) / math.log1p(gc.THETA0) / gc.cell_deg(level)
    # Only compensate floating-point roundoff at an exact analytical boundary.
    nearest = round(raw)
    if abs(raw - nearest) <= 8 * math.ulp(max(1.0, abs(raw))):
        raw = float(nearest)
    return int(math.floor(raw))


def encode(lat, lng, height, level, *, crs, height_reference):
    _context(crs, height_reference)
    _level(level)
    if isinstance(lat, bool) or isinstance(lng, bool) or isinstance(height, bool):
        raise ValueError('boolean coordinates/height are not accepted')
    lat, lng = float(lat), float(lng)
    if not (math.isfinite(lat) and math.isfinite(lng) and 0 <= lat < 88 and 0 <= lng < 180):
        raise ValueError('partial profile supports NE nonpolar coordinates only: 0<=lat<88, 0<=lng<180')
    row = _coord_pack(lat) >> (32 - level)
    col = _coord_pack(lng) >> (32 - level)
    h = height_index(height, level)
    return '%s:%d:%d:%d:%d' % (PROFILE, level, row, col, h)


def describe(key, *, crs, height_reference):
    _context(crs, height_reference)
    parts = str(key).split(':')
    if len(parts) != 5 or parts[0] != PROFILE:
        raise ValueError('wrong profile/key format; legacy 96-bit codes cannot be decoded by this profile')
    level, row, col, h = map(int, parts[1:])
    if str(key) != '%s:%d:%d:%d:%d' % (PROFILE, level, row, col, h):
        raise ValueError('noncanonical engineering key rejected')
    _level(level)
    lat0, lat1 = _coord_bounds(row, level)
    lng0, lng1 = _coord_bounds(col, level)
    if not (0 <= lat0 < 88 and lat1 <= 88 and 0 <= lng0 < 180 and lng1 <= 180):
        raise ValueError('cell is outside the supported NE nonpolar domain')
    h0, h1 = height_boundary(h, level), height_boundary(h + 1, level)
    if h0 > MAX_HEIGHT:
        raise ValueError('cell is outside the supported low-altitude height domain')
    return {
        'profile': PROFILE, 'cell_key': str(key), 'level': level,
        'key_format': 'engineering-key-not-standard-or-iwhere-wire-code',
        'crs': crs, 'height_reference': height_reference,
        'bounds': {'lat_min': lat0, 'lat_max': lat1, 'lng_min': lng0,
                   'lng_max': lng1, 'height_min': h0, 'height_max': h1},
        'center': {'lat': (lat0 + lat1) / 2, 'lng': (lng0 + lng1) / 2,
                   'height': (h0 + h1) / 2},
        'boundary_policy': 'NE lower faces included, upper faces excluded; coordinate input snapped within four ULPs at integer subsecond ticks; height index snapped within eight ULPs at analytical boundaries',
        'coordinate_tick_degrees': '1/7372800',
        'bounds_ticks': {'lat_min': round(lat0 * 7372800), 'lat_max': round(lat1 * 7372800),
                         'lng_min': round(lng0 * 7372800), 'lng_max': round(lng1 * 7372800)},
        'limitations': ['not a complete GB/T 40087 encoding certification',
                        'not compatible with iWhere legacy binary codes',
                        'no polar, negative-height, other-hemisphere or datum conversion support']}


def point_handler(form):
    key = encode(float(form['lat']), float(form['lng']), float(form['height']),
                 int(form['geo_level']), crs=form.get('crs'),
                 height_reference=form.get('height_reference'))
    return {'server_status': 200, **describe(key, crs=form.get('crs'),
                                            height_reference=form.get('height_reference'))}


def describe_handler(form):
    return {'server_status': 200, **describe(form['cell_key'], crs=form.get('crs'),
                                            height_reference=form.get('height_reference'))}


HANDLERS = {'/gbt40087_partial/point3d': point_handler,
            '/gbt40087_partial/describe': describe_handler}
