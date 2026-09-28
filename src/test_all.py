# -*- coding: utf-8 -*-
"""Offline 80-path audit; strict recursive comparison, no vendor requests.

MATCH means only this recorded fixture matches, not general vendor conformity.
SMOKE means local request/response only; DIFF and untested cases remain visible.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import threading
import urllib.request
import urllib.parse
import urllib.error
import app
import geosot_core as gc
from offline_api import call_api, make_server

ROOT = Path(__file__).resolve().parent
EXAMPLES = json.loads((ROOT / 'geosot_examples.json').read_text(encoding='utf-8'))
SCHEMAS = {x['path']: x for x in json.loads((ROOT / 'schemas.json').read_text(encoding='utf-8'))}
# These fixtures were never paired with the request; use a separate local smoke.
UNPAIRED = {'/geosot/geojson', '/geosot/multi_line', '/geosot/multi_polygon',
            '/geosot/multi_point', '/geosot/line_buffer'}


def build_request(path):
    return {k: v['example'] for k, v in SCHEMAS[path].get('props', {}).items()
            if v.get('example') is not None}


def smoke_requests():
    lv = 21
    c = gc.geo_num3d(39.91, 116.31, 100, lv)
    h = format(c, '024x')
    code2 = str(gc.geo_num_routeB(39.91, 116.31, lv)[0]) + '-' + str(lv)
    geometry = {'lats': '39.9100,39.9103,39.9100',
                'lngs': '116.3100,116.3103,116.3100', 'geo_level': lv}
    return {
      '/geosot/geojson': {'geojson': json.dumps({'type': 'Point', 'coordinates': [116.31,39.91]}), 'geo_level': lv},
      '/geosot/multi_line': {'coordinates': json.dumps([[[116.31,39.91],[116.3103,39.9103]]]), 'geo_level': lv},
      '/geosot/multi_polygon': {'coordinates': json.dumps([[[[116.31,39.91],[116.3103,39.91],[116.3103,39.9103],[116.31,39.91]]]]), 'geo_level': lv},
      '/geosot/multi_point': geometry,
      '/geosot/line_buffer': dict(geometry, distance=2),
      '/geosot/aggregation_geo_num2': dict(geometry, geo_num_list=code2),
      '/geosot/path_geo_num': {'begin_geo_num': code2, 'end_geo_num': code2, 'geo_num_list': '', 'geo_level': lv},
      '/geosot3d/polygon3d': dict(geometry, height_start=100,height_end=110),
      '/geosot3d/polyline3d': dict(geometry, heights='100,110,100'),
      '/geosot3d/rcuboid_buffer': {'lat_left_top':39.9103,'lng_left_top':116.31,'lat_left_bottom':39.91,'lng_left_bottom':116.3103,'height_start':100,'height':10,'geo_level':lv},
      '/geosot3d/aggregation_intersect': {'geo_num_list_a':h,'geo_num_list_b':h,'geo_level':lv},
      '/geosot3d/aggregation_adjoin': {'geo_num_list_a':h,'geo_num_list_b':h,'geo_level':lv},
      '/geosot3d/aggregation_relationship': {'geo_num_list_a':h,'geo_num_list_b':h,'geo_level':lv},
      '/geosot3d/visual_analysis': {'geo_num_list':'','begin_geo_num':h,'end_geo_num':h,'geo_level':lv},
    }


def compare(actual, expected, path='$'):
    """Compare every nested value; no float conversion of integer code strings."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [path + ': wrong type']
        if set(actual) != set(expected):
            return [path + ': keys differ: actual=' + repr(sorted(actual)) + ', expected=' + repr(sorted(expected))]
        return [e for key in expected for e in compare(actual[key], expected[key], path + '.' + key)]
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return [path + ': list type/length differs']
        return [e for i, (a, b) in enumerate(zip(actual, expected))
                for e in compare(a, b, path + '[' + str(i) + ']')]
    if isinstance(expected, float):
        return [] if isinstance(actual,(float,int)) and math.isclose(actual,expected,rel_tol=1e-5,abs_tol=1e-6) else [path + ': numeric mismatch']
    if isinstance(expected, int) and not isinstance(expected, bool) and isinstance(actual, float) and abs(expected) < 2**53:
        return [] if actual == expected else [path + ': numeric mismatch']
    return [] if type(actual) is type(expected) and actual == expected else [path + ': ' + repr(actual) + ' != ' + repr(expected)]


def audit(call=call_api):
    rows = []
    smokes = smoke_requests()
    for path in sorted(app.HANDLERS):
        has_paired_golden = path in EXAMPLES and path not in UNPAIRED
        request = smokes.get(path, build_request(path))
        if not request:
            rows.append({'path':path,'status':'UNTESTED','reason':'no executable local fixture'})
            continue
        status, response = call(path, {k:str(v) for k,v in request.items()})
        if status != 200 or response.get('server_status') != 200:
            rows.append({'path':path,'status':'ERROR','response':response})
        elif has_paired_golden:
            differences = compare(response, EXAMPLES[path]['example'])
            rows.append({'path':path,'status':'DIFF' if differences else 'MATCH',
                         'differences':differences[:8]})
        else:
            rows.append({'path':path,'status':'SMOKE','reason':'no paired vendor golden; only local execution verified'})
    return {'registered_paths':len(app.HANDLERS),'golden_paths':len(EXAMPLES),
            'counts':dict(Counter(x['status'] for x in rows)), 'results':rows,
            'claims':'Recorded sample compatibility and local smoke only; not full iWhere or GB/T conformity.'}


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--transport', choices=['inprocess','http'],default='inprocess')
    parser.add_argument('--json-report', type=Path)
    args=parser.parse_args(argv)
    server=worker=None
    try:
        if args.transport == 'http':
            server=make_server()
            worker=threading.Thread(target=server.serve_forever,daemon=True)
            worker.start()
            def call(path,params):
                req=urllib.request.Request('http://127.0.0.1:%d%s' % (server.server_port,path),
                    data=urllib.parse.urlencode(params).encode('utf-8'),method='POST')
                try:
                    with urllib.request.urlopen(req,timeout=30) as response:
                        return response.status,json.load(response)
                except urllib.error.HTTPError as exc:
                    return exc.code,json.load(exc)
            report=audit(call)
        else:
            report=audit()
    finally:
        if server:
            server.shutdown(); server.server_close(); worker.join(timeout=5)
    report['transport']=args.transport
    print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False))
    for row in report['results']:
        if row['status'] not in ('MATCH','SMOKE'):
            print(json.dumps(row,ensure_ascii=False))
    if args.json_report:
        args.json_report.parent.mkdir(parents=True,exist_ok=True)
        args.json_report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    # Nonzero deliberately preserves known incompatibilities as visible audit failures.
    return int(any(x['status'] in ('DIFF','ERROR','UNTESTED') for x in report['results']))


if __name__ == '__main__':
    raise SystemExit(main())
