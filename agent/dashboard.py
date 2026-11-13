"""Local dashboard server. Browser actions here prepare offline only."""

import json
import secrets
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Lock, Thread
from urllib.parse import parse_qs, urlsplit

from . import core, workbench, form_diagnostics


def server_for(cfg, port):
    token = secrets.token_urlsafe(32)
    template = (core.ROOT / 'agent' / 'dashboard.html').read_text(encoding='utf-8')
    worker_lock = Lock()
    worker = None

    def start_worker():
        nonlocal worker
        with worker_lock:
            if worker is None or not worker.is_alive():
                worker = Thread(target=workbench.prepare_selected, args=(cfg,), daemon=True)
                worker.start()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, code, data, content_type='application/json'):
            body = json.dumps(data, ensure_ascii=False) if content_type == 'application/json' else data
            content = body.encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; "
                             "style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(content)

        def local(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def do_GET(self):
            if not self.local():
                return self.send(403, {'error': 'Local access only.'})
            address = urlsplit(self.path)
            if address.path == '/':
                return self.send(200, template.replace('__SESSION_TOKEN__', token), 'text/html')
            with closing(core.connect()) as con:
                if address.path == '/api/jobs':
                    return self.send(200, workbench.all_jobs(con))
                if address.path == '/api/detail':
                    job = parse_qs(address.query).get('id', [''])[0]
                    result = workbench.explain_job(con, job, cfg)
                    return self.send(200 if result else 404, result or {})
                if address.path == '/api/form-audit':
                    return self.send(200, form_diagnostics.summarize(con))
                if address.path == '/api/history':
                    runs = [dict(row) for row in con.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 50')]
                    attempts = [dict(row) for row in con.execute(
                        'SELECT job_id,at,outcome FROM attempts ORDER BY id DESC LIMIT 100')]
                    return self.send(200, {'runs': runs, 'attempts': attempts})
            self.send(404, {'error': 'Unknown view.'})

        def do_POST(self):
            if (not self.local() or self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}'
                    or not secrets.compare_digest(self.headers.get('X-Workbench-Token', ''), token)):
                return self.send(403, {'error': 'This request did not come from the local dashboard.'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 65536:
                    raise ValueError('Invalid payload size.')
                data = json.loads(self.rfile.read(size))
                if self.path == '/api/select':
                    ids, selected = data.get('ids'), data.get('selected')
                    if not isinstance(ids, list) or len(ids) > 500 or not isinstance(selected, bool):
                        raise ValueError('Invalid selection.')
                    if any(not isinstance(value, str) or len(value) > 200 for value in ids):
                        raise ValueError('Invalid job ID.')
                    workbench.select_jobs(ids, selected)
                elif self.path == '/api/override':
                    job_id, enabled = data.get('id'), data.get('enabled')
                    if not isinstance(job_id, str) or len(job_id) > 200 or not isinstance(enabled, bool):
                        raise ValueError('Invalid override.')
                    workbench.override_job(job_id, enabled)
                elif self.path == '/api/prepare':
                    workbench.queue_selected()
                    start_worker()
                else:
                    return self.send(404, {'error': 'Unknown action.'})
            except (ValueError, TypeError, AttributeError):
                return self.send(400, {'error': 'Invalid request.'})
            self.send(200, {'ok': True})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    return server, start_worker


def serve(cfg, port):
    server, start_worker = server_for(cfg, port)
    stopped = Event()

    def recover():
        while not stopped.is_set():
            start_worker()
            stopped.wait(60)

    with server:
        Thread(target=recover, daemon=True).start()
        print(f'Open http://127.0.0.1:{server.server_port}/ in Edge. Press Ctrl+C here to stop.', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stopped.set()
