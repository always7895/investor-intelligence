"""Bounded Gateway -> Pi SDK child transport. No direct-HTTP fallback.

Operator-configured SDK/Node paths only, never taken from HTTP request data.
The existing deployed backend remains unchanged until a qualified cutover.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading

ROOT = Path(__file__).resolve().parents[1]
PROFILE = json.loads((ROOT / 'config/v213-pi-inference-v1.json').read_text(encoding='utf-8'))
MODE = 'pi_public_v1'
SLOTS = threading.BoundedSemaphore(1)

class PiTransportError(RuntimeError):
    pass


def validate_body(body: dict, selected: str) -> dict:
    if selected != PROFILE['model_id'] or body.get('model') != selected:
        raise PiTransportError('PI_CANONICAL_MODEL_REQUIRED')
    if set(body) != {'model', 'messages', 'ii_context_mode'} or body.get('ii_context_mode') != MODE:
        raise PiTransportError('PI_PROTOCOL_INVALID')
    messages = body.get('messages')
    if (not isinstance(messages, list) or len(messages) != 1 or not isinstance(messages[0], dict)
            or set(messages[0]) != {'role', 'content'} or messages[0].get('role') != 'user'):
        raise PiTransportError('PI_MESSAGES_INVALID')
    query = messages[0].get('content')
    if not isinstance(query, str) or not query.strip() or len(query.encode('utf-16-le')) // 2 > PROFILE['max_query_chars']:
        raise PiTransportError('PI_QUERY_INVALID')
    return {'query': query}


def validate_result(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise PiTransportError('PI_RESULT_INVALID')
    if (raw.get('model') != PROFILE['model_id'] or raw.get('provider') != PROFILE['provider']
            or raw.get('thinking_level') != 'xhigh' or raw.get('finish_reason') != 'stop'
            or raw.get('xhigh_payload_validated') is not True
            or type(raw.get('tools_executed')) is not int or raw['tools_executed'] != 0
            or raw.get('production_ready') is not False):
        raise PiTransportError('PI_RESULT_PROOF_INVALID')
    answer = raw.get('content')
    if not isinstance(answer, str) or not answer.strip() or len(answer.encode('utf-16-le')) // 2 > PROFILE['max_answer_chars']:
        raise PiTransportError('PI_RESULT_CONTENT_INVALID')
    # Return only the allowlisted answer/proof; never proxy arbitrary child fields.
    return {'model': raw['model'], 'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': answer}}],
            'ii_pi': {'provider': raw['provider'], 'thinking_level': 'xhigh', 'xhigh_payload_validated': True,
                      'tools_executed': 0, 'production_ready': False}}


def child_environment() -> dict[str, str]:
    allowed = {'systemroot', 'windir', 'path', 'pathext', 'comspec', 'temp', 'tmp', 'lang', 'lc_all'}
    env = {k: v for k, v in os.environ.items() if k.casefold() in allowed}
    env.update({'LLAMA_BASE_URL': 'http://127.0.0.1:8080', 'PI_SKIP_VERSION_CHECK': '1',
                'NO_PROXY': '127.0.0.1,localhost', 'PYTHONUTF8': '1'})
    return env


def _bounded_child(argv: list[str], request: dict, timeout: float) -> bytes:
    data = json.dumps(request, ensure_ascii=True).encode('utf-8')
    if len(data) > 8192:
        raise PiTransportError('PI_REQUEST_TOO_LARGE')
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               cwd=ROOT, env=child_environment(), shell=False)
    output: list[bytes] = []
    overflow = threading.Event()
    def drain(stream, limit, collect):
        size = 0
        try:
            while chunk := stream.read(4096):
                size += len(chunk)
                if size > limit:
                    overflow.set()
                    process.kill()
                    break
                if collect:
                    output.append(chunk)
        finally:
            stream.close()
    def feed():
        try:
            process.stdin.write(data)
            process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            process.stdin.close()
    threads = [threading.Thread(target=drain, args=(process.stdout, 32768, True), daemon=True),
               threading.Thread(target=drain, args=(process.stderr, 8192, False), daemon=True),
               threading.Thread(target=feed, daemon=True)]
    try:
        for thread in threads:
            thread.start()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            raise PiTransportError('PI_CHILD_TIMEOUT') from None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=2)
    if overflow.is_set():
        raise PiTransportError('PI_CHILD_OUTPUT_LIMIT')
    if process.returncode != 0:
        raise PiTransportError('PI_CHILD_FAILED')
    return b''.join(output)


def complete(body: dict, selected: str) -> dict:
    request = validate_body(body, selected)
    sdk = Path(os.environ.get('II_PI_SDK_ENTRY', ''))
    node = shutil.which('node')
    if not sdk.is_absolute() or not sdk.is_file() or not node:
        raise PiTransportError('PI_RUNTIME_NOT_CONFIGURED')
    if not SLOTS.acquire(blocking=False):
        raise PiTransportError('PI_CAPACITY_EXHAUSTED')
    try:
        data = _bounded_child([node, str(ROOT / 'scripts/v213_pi_inference.mjs'), '--sdk-entry', str(sdk)],
                              request, PROFILE['timeout_ms'] / 1000 + 15)
        try:
            result = json.loads(data.decode('utf-8'))
        except (ValueError, UnicodeError):
            raise PiTransportError('PI_CHILD_JSON_INVALID') from None
        return validate_result(result)
    finally:
        SLOTS.release()
