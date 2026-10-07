"""BATCH07 owned, synthetic fixtures only; never bind/contact installed services."""
import copy
import json
import os
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import v213_model_profile as profile

PROFILE = dict(schema_version=1, model='batch07-synthetic', enable_thinking=False,
               reasoning_effort='none', max_output_tokens=1024, smoke_output_tokens=128, timeout_ms=5000)
INTENT_KEYS = ('V213_RUNTIME_BINDING_JSON', 'V213_MODEL_PROFILE_JSON', 'II_LLAMA_BASE_URL',
               'II_LOCAL_LLM_MODEL', 'II_CAPABILITY_METADATA_URL')


def binding(base, settings=None):
    settings = settings or PROFILE
    return dict(schema_version=1, engine='strata', base_url=base, model=settings['model'],
                model_profile_sha256=profile.profile_sha256(settings), qualification='UNQUALIFIED')


@contextmanager
def isolated_intent():
    with tempfile.TemporaryDirectory(prefix='batch07-') as directory, patch.dict(os.environ):
        for key in INTENT_KEYS:
            os.environ.pop(key, None)
        os.environ['LOCALAPPDATA'] = directory
        yield Path(directory)


def save(base, settings=None):
    return profile.save_binding(str(ROOT), dict(root=str(ROOT), base_url=base,
                               model=(settings or PROFILE)['model'], profile=settings or PROFILE))


class FakeStrata:
    """Real HTTP on a newly owned ephemeral port; synthetic metadata and answers."""
    def __init__(self):
        self.calls = []
        self.mode = 'valid'
        self.post_hook = None
        # External schema's boolean auth flag is synthetic data, not a credential.
        self.health = json.loads((Path(__file__).parent / 'fixtures' / 'batch07-strata-health.json').read_bytes())
        self.catalog = {'data': [dict(id=PROFILE['model'], status={'value': 'loaded'}, meta={'n_ctx': 262144})]}
        self.response = dict(model=PROFILE['model'], choices=[dict(finish_reason='stop',
                             message={'content': 'synthetic complete answer'})])
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                owner.calls.append(('GET', self.path, None))
                self.reply(owner.health if self.path == '/health' else owner.catalog)

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.calls.append(('POST', self.path, payload))
                if owner.post_hook:
                    owner.post_hook(payload)
                value = copy.deepcopy(owner.response)
                if 'response_format' in payload:
                    value['choices'][0]['message']['content'] = '{"fixture":true}'
                self.reply(value)

            def reply(self, value):
                if owner.mode == 'redirect':
                    self.send_response(302)
                    self.send_header('Location', '/must-not-follow')
                    self.end_headers()
                    return
                raw = (b'x' * 262145 if owner.mode == 'oversize' else b'\xff' if owner.mode == 'utf8'
                       else json.dumps(value).encode('utf-8'))
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        assert self.server.server_port not in {5000, 8000, 8080, 8081, 8814}
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        assert not self.thread.is_alive()
