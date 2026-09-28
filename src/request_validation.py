"""Strict request checks over local OpenAPI-derived schemas, with documented fixes."""
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

_SCHEMAS = {item['path']: item for item in json.loads(
    (Path(__file__).resolve().parent / 'schemas.json').read_text(encoding='utf-8'))}
_EXTRA_REQUIRED = {
    '/geosot3d/child_geo_num': {'geo_num'},
    '/geosot3d/sphere': {'center_lat','center_lng','center_height','radius','geo_level'},
    '/geosot3d/cylinder': {'radius'},
    '/geosot3d/rcuboid_buffer': {'geo_level'},
}


def validate_form(path, form):
    schema = _SCHEMAS.get(path)
    if schema is None:
        return
    required = set(schema.get('required', [])) | _EXTRA_REQUIRED.get(path, set())
    missing = sorted(key for key in required if key not in form or form[key] is None)
    if missing:
        raise ValueError('missing required fields: ' + ','.join(missing))
    for key, value in form.items():
        spec = schema.get('props', {}).get(key, {})
        kind = spec.get('type')
        if key in ('geo_level','child_level','parent_level','gather_level','layer_off_set'):
            kind = 'integer'
        if kind not in ('integer','number'):
            continue
        if isinstance(value, bool):
            raise ValueError(key + ': boolean is not a number')
        # OpenAPI marks some comma-separated coordinate lists as number.
        # Normalize only these explicit list fields; reject malformed members.
        list_field = key in ('lats','lngs','heights','center_lat','center_lng','center_height') or (path == '/geosot3d/sphere' and key == 'radius')
        if list_field:
            pieces = str(value).replace('，', ',').split(',')
            try:
                if not pieces or any(not piece.strip() or not Decimal(piece.strip()).is_finite() for piece in pieces):
                    raise ValueError(key + ': finite numeric list required')
            except InvalidOperation as exc:
                raise ValueError(key + ': invalid numeric list') from exc
            continue
        try:
            number = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(key + ': invalid number') from exc
        if not number.is_finite():
            raise ValueError(key + ': finite number required')
        if kind == 'integer' and number != number.to_integral_value():
            raise ValueError(key + ': integer required')
        if key in ('geo_level','child_level','parent_level','gather_level','layer_off_set') and not 1 <= number <= 32:
            raise ValueError(key + ': supported level range is 1..32')
