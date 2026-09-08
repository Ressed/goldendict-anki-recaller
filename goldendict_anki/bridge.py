"""Loopback transport for GoldenDict; all Anki operations use AnkiConnect APIs."""
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

from .cli import BridgeError, Client, promote_card

IDLE_SECONDS = 1800
ROOT = Path(__file__).resolve().parents[1]


class Server(HTTPServer):
    def __init__(self, config, token):
        super().__init__(('127.0.0.1', 0), Handler)
        self.token = token
        self.config = config
        self.client = Client(config)
        self.last_used = time.monotonic()
        self.timeout = 1


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, result=None, error=None):
        body = json.dumps(dict(result=result, error=error), ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        # GoldenDict rewrites the outgoing Origin to the destination. The browser
        # still expects its original origin in the response. A random bearer token
        # authorizes this narrow endpoint; AnkiConnect's CORS settings stay intact.
        self.send_header('Access-Control-Allow-Origin', 'gdlookup://localhost')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.connection.settimeout(5)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16384:
                self.reply(400, error='无效的请求长度。')
                return
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict) or not isinstance(data.get('token'), str) or not secrets.compare_digest(data['token'], self.server.token):
                self.reply(403, error='页面授权已失效，请重新查词。')
                return
            self.server.last_used = time.monotonic()
            if self.path == '/health':
                self.reply(200, result=True)
            elif self.path == '/promote':
                params = data.get('params', {})
                if not isinstance(params, dict) or set(params) != {'card_id', 'word', 'deck', 'unsuspend'}:
                    raise BridgeError('无效的提队参数。')
                message = promote_card(self.server.client, self.server.config, **params)
                self.reply(200, result={'message': message})
            else:
                self.reply(404, error='未知操作。')
        except (BridgeError, ValueError, KeyError, TypeError) as exc:
            self.reply(200, error=str(exc))
        except OSError:
            # The caller may have disconnected after a successful write. Never retry.
            pass


def alive(info):
    if not isinstance(info, dict) or not isinstance(info.get('token'), str):
        return False
    try:
        url = urllib.parse.urlsplit(info['url'])
        if url.scheme != 'http' or url.hostname != '127.0.0.1' or url.username or url.password or url.path or url.query or url.fragment:
            return False
        body = json.dumps({'token': info['token']}).encode()
        request = urllib.request.Request(info['url'] + '/health', body, {'Content-Type': 'text/plain'})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=2) as response:
            return json.load(response).get('result') is True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def ensure_bridge(config):
    config = dict(config, api_key=os.environ.get('ANKICONNECT_API_KEY') or config.get('api_key'))
    # Reuse one process per configuration and code revision. Never expose the
    # AnkiConnect key in the generated dictionary HTML or process command line.
    revision = hashlib.sha256(Path(__file__).read_bytes() + (ROOT / 'goldendict_anki/cli.py').read_bytes()).hexdigest()
    identity = json.dumps([str(ROOT), config, revision], sort_keys=True).encode()
    directory = Path(tempfile.gettempdir()) / 'goldendict-anki-bridge'
    directory.mkdir(exist_ok=True, mode=0o700)
    state = directory / (hashlib.sha256(identity).hexdigest() + '.json')
    try:
        info = json.loads(state.read_text(encoding='utf-8'))
        if alive(info):
            return info
    except (OSError, ValueError, TypeError):
        pass
    token = secrets.token_urlsafe(32)
    kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
    process = subprocess.Popen([sys.executable, '-m', 'goldendict_anki.bridge'], cwd=ROOT,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, encoding='utf-8', **kwargs)
    try:
        process.stdin.write(json.dumps({'config': config, 'token': token}))
        process.stdin.close()
        ready = queue.Queue()
        threading.Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True).start()
        info = json.loads(ready.get(timeout=10))
        if info.get('token') != token or not alive(info):
            raise ValueError('bridge startup failed')
        temp = state.with_suffix('.' + secrets.token_hex(8) + '.tmp')
        temp.write_text(json.dumps(info), encoding='utf-8')
        temp.replace(state)
        return info
    except (OSError, ValueError, queue.Empty) as exc:
        process.terminate()
        raise BridgeError('本地按钮服务启动失败；可重新查词或使用命令行 --promote。') from exc
    finally:
        process.stdout.close()


def main():
    data = json.load(sys.stdin)
    with Server(data['config'], data['token']) as server:
        print(json.dumps({'url': f'http://127.0.0.1:{server.server_port}', 'token': data['token']}), flush=True)
        while time.monotonic() - server.last_used < IDLE_SECONDS:
            server.handle_request()


if __name__ == '__main__':
    main()
