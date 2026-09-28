"""Explicit stdlib-only local HTTP adapter and in-process call interface.

Vendor paths keep iwhere_legacy_v1 behavior. /gbt40087_partial/* is a separate
non-wire-compatible profile. No remote vendor endpoints are contacted.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
import app as legacy
import gbt40087_partial as partial
from request_validation import validate_form


def call_api(path, params):
    if path.startswith('/gbt40087_partial/'):
        handler = partial.HANDLERS.get(path)
    else:
        handler = legacy.HANDLERS.get(path)
    if handler is None:
        return 404, {'server_status': 404, 'message': 'unknown interface'}
    try:
        validate_form(path, params)
        result = handler(params)
        if hasattr(result, 'body'):
            return result.status_code, json.loads(result.body)
        return (200 if result.get('server_status') == 200 else 400), result
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        return 400, {'server_status': 400, 'message': str(exc)}
    except Exception as exc:
        return 500, {'server_status': 500, 'message': type(exc).__name__ + ': ' + str(exc)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, body):
        payload = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if urlsplit(self.path).path != '/':
            return self._send(404, {'server_status': 404})
        self._send(200, {'server_status': 200, 'transport': 'stdlib-local-http',
                        'legacy_registered_paths': len(legacy.HANDLERS),
                        'partial_profile_paths': len(partial.HANDLERS),
                        'compatibility': 'partial; see verification report'})

    def do_POST(self):
        if self.headers.get_content_type() != 'application/x-www-form-urlencoded':
            return self._send(415, {'server_status': 415, 'message': 'form encoding required'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 <= size <= 1048576:
                return self._send(413, {'server_status': 413, 'message': 'request too large'})
            values = parse_qs(self.rfile.read(size).decode('utf-8'), keep_blank_values=True)
            if any(len(v) != 1 for v in values.values()):
                return self._send(400, {'server_status': 400, 'message': 'duplicate form fields rejected'})
            params = {k: v[0] for k, v in values.items()}
        except (ValueError, UnicodeError):
            return self._send(400, {'server_status': 400, 'message': 'invalid form body'})
        status, body = call_api(urlsplit(self.path).path, params)
        self._send(status, body)


def make_server(port=0):
    # Loopback only; not a production multi-tenant server.
    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    with make_server(args.port) as server:
        print('local stdlib adapter listening on http://127.0.0.1:%d' % server.server_port, flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
