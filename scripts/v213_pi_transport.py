"""Bounded Gateway -> Pi SDK child transport. No direct-HTTP fallback.

Operator-configured SDK/Node paths only, never taken from HTTP request data.
The existing deployed backend remains unchanged until a qualified cutover.
"""
from __future__ import annotations
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from pathlib import Path
import shutil
import subprocess
import threading

ROOT = Path(__file__).resolve().parents[1]
PROFILE = json.loads((ROOT / 'config/v213-pi-inference-v1.json').read_text(encoding='utf-8'))
MODE = 'pi_public_v1'
SMOKE_MODE = 'pi_smoke_v1'
SMOKE_PROMPT = 'Reply exactly R75_FREE_RELAY_E2E_OK'
SLOTS = threading.BoundedSemaphore(1)

class PiTransportError(RuntimeError):
    pass


def validate_body(body: dict, selected: str) -> dict:
    if not selected or (body.get('model') and str(body.get('model')).casefold() != selected.casefold()):
        raise PiTransportError('PI_CANONICAL_MODEL_REQUIRED')
    if body.get('ii_context_mode') == SMOKE_MODE:
        if (set(body) != {'model', 'messages', 'ii_context_mode'}
                or body.get('messages') != [{'role': 'user', 'content': SMOKE_PROMPT}]):
            raise PiTransportError('PI_SMOKE_INPUT_INVALID')
        return {'query': SMOKE_PROMPT, 'smoke': True}
    if (not {'model', 'messages', 'ii_context_mode'} <= set(body)
            or set(body) - {'model', 'messages', 'ii_context_mode', 'public_context', 'history'}
            or body.get('ii_context_mode') != MODE):
        raise PiTransportError('PI_PROTOCOL_INVALID')
    messages = body.get('messages')
    if (not isinstance(messages, list) or len(messages) != 1 or not isinstance(messages[0], dict)
            or set(messages[0]) != {'role', 'content'} or messages[0].get('role') != 'user'):
        raise PiTransportError('PI_MESSAGES_INVALID')
    query = messages[0].get('content')
    if not isinstance(query, str) or not query.strip() or len(query.encode('utf-16-le')) // 2 > PROFILE['max_query_chars']:
        raise PiTransportError('PI_QUERY_INVALID')
    context = body.get('public_context', {'v': 1, 'freshness': 'UNAVAILABLE'})
    validate_context(context)
    history = body.get('history', [])
    if (not isinstance(history, list) or len(history) > PROFILE['max_history_turns']
            or any(not isinstance(m, dict) or set(m) != {'role', 'content'}
                   or m.get('role') not in ('user', 'assistant') or not isinstance(m.get('content'), str)
                   or utf16_length(m['content']) > PROFILE['max_history_chars'] for m in history)):
        raise PiTransportError('PI_HISTORY_INVALID')
    return {'query': query, 'context': context, 'history': history}


def utf16_length(value: str) -> int:
    return len(value.encode('utf-16-le')) // 2


def validate_context(context: object, now: datetime | None = None) -> None:
    def fail(): raise PiTransportError('PI_PUBLIC_CONTEXT_INVALID')
    if (not isinstance(context, dict) or set(context) - set(PROFILE['context_keys'])
            or utf16_length(json.dumps(context, ensure_ascii=False, separators=(',', ':'))) > PROFILE['max_context_chars']
            or type(context.get('v')) not in (int, float) or context['v'] != 1
            or context.get('freshness') not in ('FRESH', 'STALE', 'UNAVAILABLE')): fail()
    if 'kind' in context and context['kind'] not in ('general', 'methodology', 'evidence', 'ticker'): fail()
    if 'mode' in context and context['mode'] not in ('LIMITED_RESEARCH_CANDIDATE', 'EVIDENCE_QUALIFIED'): fail()
    for key in ('high_eligible', 'validated_thesis'):
        if key in context and type(context[key]) is not bool: fail()
        if context.get(key) is True and (context.get('mode') != 'EVIDENCE_QUALIFIED' or context['freshness'] != 'FRESH'): fail()
    for key in ('methodology', 'evidence_principles', 'summary', 'ticker', 'facts', 'market'):
        if key in context and not isinstance(context[key], str): fail()
    for key in ('limited', 'evidence_qualified'):
        if key in context and context[key] is not None:
            value = context[key]
            if type(value) not in (int, float) or not 0 <= value <= 20 or int(value) != value: fail()
    if context.get('as_of') is not None and not isinstance(context['as_of'], str): fail()
    if 'max_age_seconds' in context:
        limit = context['max_age_seconds']
        if type(limit) not in (int, float) or not 60 <= limit <= PROFILE['max_context_age_seconds'] or int(limit) != limit: fail()
    if context['freshness'] == 'FRESH':
        if 'max_age_seconds' not in context: fail()
        stamp = context.get('as_of')
        if not isinstance(stamp, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', stamp): fail()
        try: age = ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(stamp.replace('Z', '+00:00'))).total_seconds()
        except ValueError: fail()
        if not -PROFILE['future_tolerance_seconds'] <= age <= context['max_age_seconds']: fail()
    if 'missing' in context and (not isinstance(context['missing'], list) or len(context['missing']) > 3
            or any(not isinstance(s, str) or utf16_length(s) > 70 for s in context['missing'])): fail()
    if 'sources' in context:
        if not isinstance(context['sources'], list) or len(context['sources']) > 2: fail()
        for s in context['sources']:
            if (not isinstance(s, dict) or set(s) != {'as_of', 'provenance_only', 'source', 'type', 'url'}
                    or any(not isinstance(s[k], str) for k in ('as_of', 'source', 'type', 'url'))
                    or type(s['provenance_only']) is not bool or utf16_length(s['url']) > 180): fail()
            try: url = urlsplit(s['url'])
            except ValueError: fail()
            if url.scheme != 'https' or not url.hostname or url.username or url.password: fail()


def validate_result(raw: object, selected: str = '') -> dict:
    if not isinstance(raw, dict):
        raise PiTransportError('PI_RESULT_INVALID')
    expected_model = (selected or PROFILE['model_id']).casefold()
    if (str(raw.get('model') or '').casefold() != expected_model or raw.get('provider') != PROFILE['provider']
            or raw.get('thinking_level') != 'xhigh' or raw.get('finish_reason') != 'stop'
            or raw.get('xhigh_payload_validated') is not True
            or type(raw.get('tools_executed')) is not int or raw['tools_executed'] != 0
            or raw.get('production_ready') is not False):
        raise PiTransportError('PI_RESULT_PROOF_INVALID')
    answer = raw.get('content')
    if not isinstance(answer, str) or not answer.strip() or len(answer.encode('utf-16-le')) // 2 > PROFILE['max_answer_chars']:
        raise PiTransportError('PI_RESULT_CONTENT_INVALID')
    # Return only the allowlisted answer/proof; never proxy arbitrary child fields.
    result = {'model': raw['model'], 'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': answer}}],
              'ii_pi': {'provider': raw['provider'], 'thinking_level': 'xhigh', 'xhigh_payload_validated': True,
                        'tools_executed': 0, 'production_ready': False}}
    if 'thinking_chars' in raw:
        if type(raw['thinking_chars']) is not int or not 0 <= raw['thinking_chars'] <= 200000: raise PiTransportError('PI_THINKING_METRIC_INVALID')
        result['ii_pi']['thinking_chars'] = raw['thinking_chars']
    if 'usage' in raw:
        usage = raw['usage']
        if (not isinstance(usage, dict) or set(usage) != {'input_tokens', 'output_tokens', 'cache_read_tokens'}
                or any(type(v) is not int or not 0 <= v <= 200000 for v in usage.values())):
            raise PiTransportError('PI_USAGE_INVALID')
        result['ii_pi']['usage'] = usage
    if 'qualification_cache_prompt' in raw:
        if type(raw['qualification_cache_prompt']) is not bool: raise PiTransportError('PI_CACHE_PROOF_INVALID')
        result['ii_pi']['qualification_cache_prompt'] = raw['qualification_cache_prompt']
    return result


def child_environment() -> dict[str, str]:
    allowed = {'systemroot', 'windir', 'path', 'pathext', 'comspec', 'temp', 'tmp', 'lang', 'lc_all'}
    env = {k: v for k, v in os.environ.items() if k.casefold() in allowed}
    env.update({'LLAMA_BASE_URL': 'http://127.0.0.1:8080', 'PI_SKIP_VERSION_CHECK': '1',
                'NO_PROXY': '127.0.0.1,localhost', 'PYTHONUTF8': '1'})
    return env


def _bounded_child(argv: list[str], request: dict, timeout: float) -> bytes:
    data = json.dumps(request, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
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


def complete(body: dict, selected: str, *, qualification_cache_prompt: bool | None = None) -> dict:
    if qualification_cache_prompt is not None and type(qualification_cache_prompt) is not bool:
        raise PiTransportError('PI_CACHE_CONTROL_INVALID')
    request = validate_body(body, selected)
    sdk = Path(os.environ.get('II_PI_SDK_ENTRY') or str(ROOT / '.pi/npm/node_modules/@earendil-works/pi-coding-agent/dist/index.js'))
    node = shutil.which('node')
    if not sdk.is_absolute() or not sdk.is_file() or not node:
        raise PiTransportError('PI_RUNTIME_NOT_CONFIGURED')
    if not SLOTS.acquire(blocking=False):
        raise PiTransportError('PI_CAPACITY_EXHAUSTED')
    try:
        argv = [node, str(ROOT / 'scripts/v213_pi_inference.mjs'), '--sdk-entry', str(sdk)]
        if qualification_cache_prompt is not None:
            argv.append('--cache-warm' if qualification_cache_prompt else '--cache-cold')
        data = _bounded_child(argv, request, PROFILE['transport_timeout_ms'] / 1000)
        try:
            result = json.loads(data.decode('utf-8'))
        except (ValueError, UnicodeError):
            raise PiTransportError('PI_CHILD_JSON_INVALID') from None
        result = validate_result(result, selected)
        if qualification_cache_prompt is not None and result['ii_pi'].get('qualification_cache_prompt') is not qualification_cache_prompt:
            raise PiTransportError('PI_CACHE_PROOF_MISSING')
        return result
    finally:
        SLOTS.release()
