import argparse
import json
import mimetypes
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from reconstruct import process

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent/'data'
DATA.mkdir(exist_ok=True)
LOCK = threading.Lock()
JOBS = {}
PROCESS_LOCK = threading.Lock()


def worker(identifier, archive):
    def progress(percent, message):
        with LOCK:
            JOBS[identifier].update(progress=percent, message=message)
    try:
        with PROCESS_LOCK:
            report = process(archive, DATA/identifier, progress)
        with LOCK:
            JOBS[identifier].update(state='done', report=report)
    except Exception as error:
        with LOCK:
            JOBS[identifier].update(state='error', message=str(error))


class Handler(BaseHTTPRequestHandler):
    def json_response(self, obj, status=200):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/api/jobs':
            with LOCK:
                result = [dict(id=k, **v) for k, v in JOBS.items()]
            return self.json_response(result)
        if path.startswith('/data/'):
            target = DATA/path.removeprefix('/data/')
            base = DATA
        else:
            target = ROOT/'web'/('index.html' if path == '/' else path.lstrip('/'))
            base = ROOT/'web'
        target = target.resolve()
        if not target.is_relative_to(base.resolve()) or not target.is_file():
            return self.json_response({'error': 'Не найдено'}, 404)
        # Original archives are accessible through local Files, not through the viewer.
        if target.suffix.lower() not in {'.html', '.css', '.js', '.json', '.glb', '.ply'}:
            return self.json_response({'error': 'Недоступно'}, 404)
        self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(target.stat().st_size))
        self.end_headers()
        with target.open('rb') as source:
            while chunk := source.read(1024*1024):
                self.wfile.write(chunk)

    def do_POST(self):
        if self.path != '/api/import':
            return self.json_response({'error': 'Не найдено'}, 404)
        if self.headers.get('Origin') not in {None, f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}:
            return self.json_response({'error': 'Недопустимый источник'}, 403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.json_response({'error': 'Некорректная длина'}, 400)
        if not 0 < length <= 2*1024**3:
            return self.json_response({'error': 'Максимальный размер ZIP: 2 ГБ'}, 413)
        with LOCK:
            if any(v['state'] == 'running' for v in JOBS.values()):
                return self.json_response({'error': 'Дождись обработки предыдущего скана'}, 409)
            identifier = uuid.uuid4().hex
            JOBS[identifier] = {'state': 'running', 'progress': 0, 'message': 'Принимаю архив'}
        folder = DATA/identifier
        folder.mkdir()
        archive = folder/'source.zip'
        try:
            with archive.open('wb') as out:
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(1024*1024, remaining))
                    if not chunk:
                        raise ValueError('Передача архива оборвалась')
                    out.write(chunk)
                    remaining -= len(chunk)
        except Exception as error:
            with LOCK:
                JOBS[identifier].update(state='error', message=str(error))
            return self.json_response({'error': str(error)}, 400)
        threading.Thread(target=worker, args=(identifier, archive), daemon=True).start()
        self.json_response({'id': identifier}, 202)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=4318)
    args = parser.parse_args()
    for report in DATA.glob('*/report.json'):
        JOBS[report.parent.name] = {'state': 'done', 'progress': 100, 'message': 'Готово',
                                  'report': json.loads(report.read_text(encoding='utf-8'))}
    print(f'Floor Copy: http://127.0.0.1:{args.port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
