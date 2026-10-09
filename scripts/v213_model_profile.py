"""Versioned, request-only model configuration; never changes Router presets."""
from __future__ import annotations
import hashlib
import json
import re

FIELDS = ('schema_version', 'model', 'enable_thinking', 'reasoning_effort',
          'max_output_tokens', 'smoke_output_tokens', 'timeout_ms')
EFFORTS = {'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'}


def validate_profile(value):
    if not isinstance(value, dict) or set(value) != set(FIELDS):
        raise ValueError('MODEL_PROFILE_SCHEMA_INVALID')
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('MODEL_PROFILE_VERSION_INVALID')
    if not isinstance(value['model'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}', value['model']):
        raise ValueError('MODEL_PROFILE_ID_INVALID')
    if type(value['enable_thinking']) is not bool or not isinstance(value['reasoning_effort'], str) or value['reasoning_effort'] not in EFFORTS:
        raise ValueError('MODEL_PROFILE_REASONING_INVALID')
    if value['enable_thinking'] == (value['reasoning_effort'] == 'none'):
        raise ValueError('MODEL_PROFILE_REASONING_CONFLICT')
    for key, lower, upper in (('max_output_tokens', 1, 8192), ('smoke_output_tokens', 1, 8192), ('timeout_ms', 1000, 20000)):
        if type(value[key]) is not int or not lower <= value[key] <= upper:
            raise ValueError('MODEL_PROFILE_BOUNDS_INVALID')
    if value['smoke_output_tokens'] > value['max_output_tokens']:
        raise ValueError('MODEL_PROFILE_BOUNDS_INVALID')
    return {key: value[key] for key in FIELDS}


def parse_profile(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('MODEL_PROFILE_DUPLICATE_KEY')
            result[key] = value
        return result
    if not isinstance(raw, str) or len(raw) > 4096:
        raise ValueError('MODEL_PROFILE_SCHEMA_INVALID')
    try:
        return validate_profile(json.loads(raw, object_pairs_hook=pairs))
    except (TypeError, ValueError):
        raise ValueError('MODEL_PROFILE_INVALID') from None


def profile_sha256(profile):
    value = validate_profile(profile)
    # Fixed-order ASCII scalar array: identical to the Worker implementation.
    encoded = json.dumps([value[k] for k in FIELDS], separators=(',', ':')).encode('ascii')
    return hashlib.sha256(encoded).hexdigest()


# Request intent has its OWN identity. Never append to/change FIELDS above.
BINDING_FIELDS = ('schema_version', 'engine', 'base_url', 'model', 'model_profile_sha256', 'qualification')
OMITTED = object()


class BindingUnavailable(ValueError):
    """Sanitized finite reason only; never raw payloads, headers or credentials."""


def strict_object(raw, limit=8192):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise BindingUnavailable('BINDING_DUPLICATE_KEY')
            result[k] = v
        return result
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > limit:
        raise BindingUnavailable('BINDING_JSON_BOUNDS')
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(BindingUnavailable('BINDING_JSON_NUMBER')))
        stack, nodes = [(value, 0)], 0
        while stack:
            v, depth = stack.pop(); nodes += 1
            if depth > 12 or nodes > 8192:
                raise BindingUnavailable('BINDING_JSON_BOUNDS')
            if isinstance(v, dict):
                stack.extend((x, depth + 1) for x in v.values())
            elif isinstance(v, list):
                stack.extend((x, depth + 1) for x in v)
        return value
    except (ValueError, RecursionError, UnicodeError):
        raise BindingUnavailable('BINDING_JSON_INVALID') from None


def canonical_strata_root(value, *, input_boundary=False):
    if not isinstance(value, str):
        raise BindingUnavailable('BINDING_ENDPOINT_INVALID')
    pattern = r'http://127\.0\.0\.1:([1-9][0-9]{0,4})(?:/v1)?/?' if input_boundary else r'http://127\.0\.0\.1:([1-9][0-9]{0,4})'
    m = re.fullmatch(pattern, value)
    if m is None or not 1 <= int(m.group(1)) <= 65535:
        raise BindingUnavailable('BINDING_ENDPOINT_INVALID')
    return 'http://127.0.0.1:' + str(int(m.group(1)))


def validate_binding(value, profile):
    profile = validate_profile(profile)
    if (not isinstance(value, dict) or set(value) != set(BINDING_FIELDS)
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or value['engine'] != 'strata' or value['qualification'] != 'UNQUALIFIED'):
        raise BindingUnavailable('BINDING_SCHEMA_INVALID')
    canonical_strata_root(value['base_url'])
    if (not isinstance(value['model'], str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}', value['model']) is None
            or value['model'] != profile['model'] or not isinstance(value['model_profile_sha256'], str)
            or re.fullmatch(r'[0-9a-f]{64}', value['model_profile_sha256']) is None
            or value['model_profile_sha256'] != profile_sha256(profile)):
        raise BindingUnavailable('BINDING_PROFILE_MODEL_MISMATCH')
    return {k: value[k] for k in BINDING_FIELDS}


def parse_binding(raw, profile):
    return validate_binding(strict_object(raw, 4096), profile)


def binding_sha256(binding, profile):
    value = validate_binding(binding, profile)
    return hashlib.sha256(json.dumps([value[k] for k in BINDING_FIELDS], separators=(',', ':')).encode('ascii')).hexdigest()


def _user_paths():
    import os
    from pathlib import Path
    location = os.environ.get('LOCALAPPDATA')
    if not location:
        raise BindingUnavailable('BINDING_USERDATA_UNAVAILABLE')
    folder = Path(location) / 'InvestorIntelligence' / 'UserData' / 'config'
    return folder, folder / 'v213-runtime-binding-v1.json', folder / 'v213-model-profile-v1.json', folder / 'v213-model-selection.json'


def _read_bounded(path, limit=4096):
    try:
        with path.open('rb') as handle:
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise BindingUnavailable('BINDING_FILE_BOUNDS')
        return raw.decode('utf-8-sig')
    except (OSError, UnicodeError):
        raise BindingUnavailable('BINDING_SAVED_UNAVAILABLE') from None


def resolve_binding(root, *, binding_json=OMITTED, base_url=OMITTED, model=OMITTED, profile_json=OMITTED):
    """Presence, not truthiness. CLI/env/saved must agree, no stale shadowing."""
    import os
    from pathlib import Path
    if not os.environ.get('LOCALAPPDATA') and binding_json is OMITTED and 'V213_RUNTIME_BINDING_JSON' not in os.environ:
        return {'mode': 'LEGACY_ABSENT'}
    _, intent_path, profile_path, selection_path = _user_paths()
    sources = []
    if binding_json is not OMITTED:
        sources.append(binding_json)
    if 'V213_RUNTIME_BINDING_JSON' in os.environ:
        sources.append(os.environ['V213_RUNTIME_BINDING_JSON'])
    if intent_path.exists() or intent_path.is_symlink():
        sources.append(_read_bounded(intent_path))
    # A torn/explicit selection cannot silently convert to legacy absence.
    selection = None
    if selection_path.exists() or selection_path.is_symlink():
        selection = strict_object(_read_bounded(selection_path, 16384), 16384)
        if not isinstance(selection, dict):
            raise BindingUnavailable('BINDING_SELECTION_INVALID')
        if isinstance(selection, dict) and ('runtime_binding_sha256' in selection or 'engine' in selection) and not sources:
            raise BindingUnavailable('BINDING_SELECTION_WITHOUT_INTENT')
    if not sources:
        return {'mode': 'LEGACY_ABSENT'}
    selected_raw = profile_json
    if selected_raw is OMITTED:
        selected_raw = os.environ['V213_MODEL_PROFILE_JSON'] if 'V213_MODEL_PROFILE_JSON' in os.environ else _read_bounded(
            profile_path if profile_path.exists() else Path(root) / 'config' / 'v213-model-profile-v1.json')
    profile = parse_profile(selected_raw)
    if 'V213_MODEL_PROFILE_JSON' in os.environ and parse_profile(os.environ['V213_MODEL_PROFILE_JSON']) != profile:
        raise BindingUnavailable('BINDING_ENV_PROFILE_CONFLICT')
    if (profile_path.exists() or profile_path.is_symlink()) and parse_profile(_read_bounded(profile_path)) != profile:
        raise BindingUnavailable('BINDING_SAVED_PROFILE_CONFLICT')
    bindings = [parse_binding(raw, profile) for raw in sources]
    binding = bindings[0]
    if any(b != binding for b in bindings[1:]):
        raise BindingUnavailable('BINDING_SOURCE_CONFLICT')
    for supplied, env_key, actual, endpoint in ((base_url, 'II_LLAMA_BASE_URL', binding['base_url'], True),
                                               (model, 'II_LOCAL_LLM_MODEL', binding['model'], False)):
        candidates = ([] if supplied is OMITTED else [supplied]) + ([os.environ[env_key]] if env_key in os.environ else [])
        for v in candidates:
            if (canonical_strata_root(v, input_boundary=True) if endpoint else v) != actual:
                raise BindingUnavailable('BINDING_ARGUMENT_CONFLICT')
    digest = binding_sha256(binding, profile)
    if selection is not None:
        if (set(selection) != {'schema_version', 'product_version', 'engine', 'model', 'llama_base_url',
                               'runtime_binding_sha256', 'model_profile_sha256', 'model_profile_qualified', 'source'}
                or type(selection.get('schema_version')) is not int or selection['schema_version'] != 2
                or selection.get('product_version') != '2.1.3' or selection.get('engine') != 'strata'
                or selection.get('model_profile_qualified') is not False or selection.get('source') != 'EXPLICIT_OFFLINE_INTENT'
                or selection.get('runtime_binding_sha256') != digest or selection.get('model_profile_sha256') != profile_sha256(profile)
                or selection.get('model') != binding['model'] or selection.get('llama_base_url') != binding['base_url']):
            raise BindingUnavailable('BINDING_SELECTION_CONFLICT')
    return {'mode': 'EXPLICIT_STRATA', 'binding': binding, 'binding_sha256': digest,
            'profile': profile, 'profile_sha256': profile_sha256(profile), 'qualification': 'UNQUALIFIED'}


def save_binding(root, value):
    """Future explicit offline save: fail-closed intent barrier, then pointer last."""
    import os
    from pathlib import Path
    if not isinstance(value, dict) or set(value) != {'root', 'base_url', 'model', 'profile'}:
        raise BindingUnavailable('BINDING_SAVE_SCHEMA')
    profile = parse_profile(value['profile']) if isinstance(value['profile'], str) else validate_profile(value['profile'])
    binding = validate_binding({'schema_version': 1, 'engine': 'strata', 'base_url': canonical_strata_root(value['base_url'], input_boundary=True),
                               'model': value['model'], 'model_profile_sha256': profile_sha256(profile), 'qualification': 'UNQUALIFIED'}, profile)
    if 'V213_RUNTIME_BINDING_JSON' in os.environ and parse_binding(os.environ['V213_RUNTIME_BINDING_JSON'], profile) != binding:
        raise BindingUnavailable('BINDING_ENV_CONFLICT_RECONFIGURE_EXPLICITLY')
    if 'V213_MODEL_PROFILE_JSON' in os.environ and parse_profile(os.environ['V213_MODEL_PROFILE_JSON']) != profile:
        raise BindingUnavailable('BINDING_ENV_PROFILE_CONFLICT')
    for key, actual in (('II_LOCAL_LLM_MODEL', binding['model']), ('II_LLAMA_BASE_URL', binding['base_url'])):
        if key in os.environ and (canonical_strata_root(os.environ[key], input_boundary=True) if key.endswith('BASE_URL') else os.environ[key]) != actual:
            raise BindingUnavailable('BINDING_ENV_CONFLICT_RECONFIGURE_EXPLICITLY')
    folder, intent, profile_path, selection = _user_paths()
    digest = binding_sha256(binding, profile)
    folder.mkdir(parents=True, exist_ok=True)
    def replace(path, text):
        import tempfile
        fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=folder)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
                f.write(text); f.flush(); os.fsync(f.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    # An interrupted first save must never expose a new profile as legacy mode.
    replace(intent, '{')  # deliberate invalid/pending presence, NOT an approval
    replace(profile_path, json.dumps(profile, separators=(',', ':')))
    replace(selection, json.dumps({'schema_version': 2, 'product_version': '2.1.3', 'engine': 'strata',
            'model': binding['model'], 'llama_base_url': binding['base_url'], 'runtime_binding_sha256': digest,
            'model_profile_sha256': profile_sha256(profile), 'model_profile_qualified': False, 'source': 'EXPLICIT_OFFLINE_INTENT'}, separators=(',', ':')))
    replace(intent, json.dumps(binding, separators=(',', ':')))
    return {'scope': 'OFFLINE_REQUEST_INTENT', 'binding': binding, 'binding_sha256': digest, 'qualification': 'UNQUALIFIED', 'release_qualified': False}


def binding_json_http(binding, method, suffix, *, payload=None, timeout=15, max_bytes=262144):
    """Future selected-only bounded transport; no redirects/proxies/netrc/auth/cookies."""
    import time
    import urllib.request
    import urllib.error
    if suffix not in ('/health', '/v1/models', '/v1/chat/completions') or method not in ('GET', 'POST'):
        raise BindingUnavailable('BINDING_HTTP_PATH')
    canonical_strata_root(binding['base_url'])
    if (type(timeout) not in (int, float) or not 0 < timeout <= 180 or type(max_bytes) is not int
            or not 1 <= max_bytes <= 1048576 or (method == 'GET' and payload is not None)):
        raise BindingUnavailable('BINDING_HTTP_BOUNDS')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise BindingUnavailable('BINDING_REDIRECT_REFUSED')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    data = None if payload is None else json.dumps(payload, separators=(',', ':'), allow_nan=False).encode('utf-8')
    req = urllib.request.Request(binding['base_url'] + suffix, data=data, method=method, headers={'Content-Type': 'application/json', 'Cache-Control': 'no-cache'})
    deadline = time.monotonic() + timeout
    try:
        with opener.open(req, timeout=min(5, timeout)) as response:
            if response.status != 200:
                raise BindingUnavailable('BINDING_HTTP_STATUS')
            chunks, size = [], 0
            while True:
                if time.monotonic() >= deadline:
                    raise BindingUnavailable('BINDING_HTTP_DEADLINE')
                chunk = response.read1(min(65536, max_bytes + 1 - size))
                size += len(chunk)
                if size > max_bytes:
                    raise BindingUnavailable('BINDING_HTTP_BOUNDS')
                if not chunk:
                    break
                chunks.append(chunk)
            value = strict_object(b''.join(chunks).decode('utf-8'), max_bytes)
            if time.monotonic() >= deadline:
                raise BindingUnavailable('BINDING_HTTP_DEADLINE')
            return value
    except urllib.error.HTTPError as error:
        raise BindingUnavailable('BINDING_AUTH_REQUIRED' if error.code == 401 else 'BINDING_HTTP_STATUS') from None
    except (OSError, UnicodeError, TimeoutError):
        raise BindingUnavailable('BINDING_ENDPOINT_UNAVAILABLE') from None


def selected_metadata(binding, profile, min_context, *, budget=15, max_response_bytes=262144):
    """Metadata-only check of ONE selected binding. `budget` (seconds, <=15) is the result-acceptance budget of the whole call and
    `max_response_bytes` bounds EACH of the two GET bodies (a body, even a failed or oversized one, receives at most
    max_response_bytes + 1 bytes). Both defaults are unchanged for every existing caller. The budget is not a proven hard OS wall."""
    import time
    binding = validate_binding(binding, profile)
    if type(min_context) is not int or not 0 < min_context <= 1073741824:
        raise BindingUnavailable('BINDING_CONTEXT_POLICY_INVALID')
    if (type(budget) not in (int, float) or not 0 < budget <= 15
            or type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 262144):
        raise BindingUnavailable('BINDING_HTTP_BOUNDS')
    deadline = time.monotonic() + budget
    health = binding_json_http(binding, 'GET', '/health', timeout=budget, max_bytes=max_response_bytes)
    if (not isinstance(health, dict) or health.get('service') != 'strata' or health.get('status') != 'ok'
            or type(health.get('loaded')) is not bool or health['loaded'] is not True
            or health.get('model') != binding['model'] or type(health.get('api_key')) is not bool):
        raise BindingUnavailable('STRATA_HEALTH_IDENTITY_UNAVAILABLE')
    if health['api_key']:
        raise BindingUnavailable('BINDING_AUTH_REQUIRED')
    context = health.get('max_context')
    if type(context) is not int or not 0 < context <= 1073741824:
        raise BindingUnavailable('STRATA_CONTEXT_UNKNOWN')
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise BindingUnavailable('BINDING_HTTP_DEADLINE')
    catalog = binding_json_http(binding, 'GET', '/v1/models', timeout=remaining, max_bytes=max_response_bytes)
    rows = catalog.get('data') if isinstance(catalog, dict) else None
    if not isinstance(rows, list) or not 1 <= len(rows) <= 128:
        raise BindingUnavailable('STRATA_CATALOG_INVALID')
    ids, selected = set(), []
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}', row['id']) is None or row['id'] in ids):
            raise BindingUnavailable('STRATA_CATALOG_AMBIGUOUS')
        ids.add(row['id'])
        if row['id'] == binding['model']:
            selected.append(row)
    if len(selected) != 1:
        raise BindingUnavailable('STRATA_EXACT_MODEL_UNAVAILABLE')
    row = selected[0]
    if ('alias_of' in row or not isinstance(row.get('status'), dict) or row['status'].get('value') != 'loaded'
            or not isinstance(row.get('meta'), dict) or type(row['meta'].get('n_ctx')) is not int
            or row['meta']['n_ctx'] != context or context < min_context):
        raise BindingUnavailable('STRATA_SELECTED_CONTEXT_UNAVAILABLE')
    if time.monotonic() >= deadline:
        raise BindingUnavailable('BINDING_HTTP_DEADLINE')
    return {'scope': 'METADATA_ONLY', 'engine': 'strata', 'binding_sha256': binding_sha256(binding, profile),
            'model': binding['model'], 'declared_context': context, 'qualification': 'UNQUALIFIED', 'release_qualified': False,
            # Projection of the actual validated selected row, never a guessed
            # {id=requested} catalog. No unrelated/raw metadata is emitted.
            'selected_catalog': [{'id': row['id'], 'status': {'value': row['status']['value']},
                                  'meta': {'n_ctx': row['meta']['n_ctx']}}]}


def selected_route_check(request):
    """Future explicit GENERATING action, separate from metadata-only checks."""
    resolved = resolve_binding(**request)
    if resolved['mode'] != 'EXPLICIT_STRATA':
        raise BindingUnavailable('BINDING_REQUIRED_FOR_ROUTING_CHECK')
    binding, profile = resolved['binding'], resolved['profile']
    metadata = selected_metadata(binding, profile, context_minimum(request['root']))
    # Real readonly shared contract: finish=stop, one content choice, catalog
    # identity and literal marker. Exact equality additionally bans aliases.
    from v213_compact_qa_gateway import POLICY, complete_compact_response
    payload = {'model': binding['model'], 'messages': [{'role': 'user', 'content': POLICY['smoke_prompt']}],
               'temperature': 0, 'max_tokens': profile['smoke_output_tokens'], 'stream': False,
               'chat_template_kwargs': {'enable_thinking': profile['enable_thinking']},
               'reasoning_effort': profile['reasoning_effort']}
    response = binding_json_http(binding, 'POST', '/v1/chat/completions', payload=payload,
                                 timeout=profile['timeout_ms'] / 1000, max_bytes=262144)
    if (not isinstance(response, dict) or response.get('model') != binding['model']
            or not complete_compact_response(response, binding['model'], metadata['selected_catalog'])
            or response['choices'][0]['message']['content'].strip() != POLICY['smoke_prompt'].removeprefix('Reply exactly ')):
        raise BindingUnavailable('BINDING_COMPLETE_MARKER_UNAVAILABLE')
    if resolve_binding(**request)['binding_sha256'] != resolved['binding_sha256']:
        raise BindingUnavailable('BINDING_CHANGED_RESTART_REQUIRED')
    return {'scope': 'LOCAL_ROUTING_CHECK_ONLY', 'complete_exact_marker': True,
            'binding_sha256': resolved['binding_sha256'], 'model_profile_sha256': resolved['profile_sha256'],
            'qualification': 'UNQUALIFIED', 'release_qualified': False}


def remove_binding():
    """Explicit offline removal; a pending barrier survives interrupted removal."""
    import os
    # External active intent must be cleared explicitly, never secretly ignored.
    if any(k in os.environ for k in ('V213_RUNTIME_BINDING_JSON', 'II_LOCAL_LLM_MODEL', 'II_LLAMA_BASE_URL')):
        raise BindingUnavailable('BINDING_ENV_CONFLICT_REMOVE_EXPLICITLY')
    folder, intent, _, selection = _user_paths()
    if not folder.exists():
        return {'scope': 'OFFLINE_INTENT_REMOVED', 'qualification': 'UNQUALIFIED', 'release_qualified': False}
    import tempfile
    fd, name = tempfile.mkstemp(prefix=intent.name + '.', suffix='.tmp', dir=folder)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write('{'); handle.flush(); os.fsync(handle.fileno())
        os.replace(name, intent)
        if selection.exists() or selection.is_symlink():
            selection.unlink()
        # Last: only this explicit user action allows legacy absence again.
        intent.unlink()
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return {'scope': 'OFFLINE_INTENT_REMOVED', 'qualification': 'UNQUALIFIED', 'release_qualified': False}


def context_minimum(root):
    from pathlib import Path
    policy = strict_object(_read_bounded(Path(root) / 'config' / 'local-runtime-independence-v1.json', 16384), 16384)
    return policy['capability_requirements']['min_context']


if __name__ == '__main__':
    import argparse
    import os
    import sys
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--profile', type=Path)
    group.add_argument('--env', action='store_true')
    group.add_argument('--resolve-stdin', action='store_true')
    group.add_argument('--routing-check-stdin', action='store_true')
    group.add_argument('--save-binding-stdin', action='store_true')
    group.add_argument('--remove-binding', action='store_true')
    parser.add_argument('--metadata-check', action='store_true')
    parser.add_argument('--require-gateway-deps', action='store_true')
    args = parser.parse_args()
    try:
        if sys.version_info < (3, 10):
            raise BindingUnavailable('BINDING_PYTHON_PREREQUISITE_UNAVAILABLE')
        if args.metadata_check and not args.resolve_stdin:
            raise BindingUnavailable('BINDING_CHECK_ARGUMENT_CONFLICT')
        if args.require_gateway_deps and not args.resolve_stdin:
            raise BindingUnavailable('BINDING_CHECK_ARGUMENT_CONFLICT')
        if args.resolve_stdin or args.save_binding_stdin or args.routing_check_stdin:
            request = strict_object(sys.stdin.read(16385), 16384)
            if not isinstance(request, dict) or not isinstance(request.get('root'), str) or not 0 < len(request['root']) <= 1024:
                raise BindingUnavailable('BINDING_REQUEST_INVALID')
            if args.save_binding_stdin:
                result = save_binding(request['root'], request)
            else:
                if set(request) - {'root', 'binding_json', 'base_url', 'model', 'profile_json'}:
                    raise BindingUnavailable('BINDING_REQUEST_INVALID')
                result = selected_route_check(request) if args.routing_check_stdin else resolve_binding(**request)
                if args.require_gateway_deps:
                    if result['mode'] != 'EXPLICIT_STRATA':
                        raise BindingUnavailable('BINDING_REQUIRED_FOR_PREFLIGHT')
                    # FUTURE normal-start prerequisite only, AFTER local intent
                    # validation. No installer/package acquisition or inference.
                    try:
                        import requests
                    except ImportError:
                        raise BindingUnavailable('BINDING_GATEWAY_PREREQUISITE_UNAVAILABLE') from None
                if args.metadata_check:
                    if result['mode'] != 'EXPLICIT_STRATA':
                        raise BindingUnavailable('BINDING_REQUIRED_FOR_METADATA_CHECK')
                    result['metadata'] = selected_metadata(result['binding'], result['profile'], context_minimum(request['root']))
        elif args.remove_binding:
            result = remove_binding()
        else:
            raw = os.environ.get('V213_MODEL_PROFILE_JSON') if args.env else args.profile.read_text(encoding='utf-8-sig')
            profile = parse_profile(raw)
            result = {'schema_version': 1, 'profile': profile, 'profile_sha256': profile_sha256(profile), 'release_qualified': False}
        print(json.dumps(result, separators=(',', ':')))
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        print('{"error":"MODEL_PROFILE_OR_BINDING_UNAVAILABLE","qualification":"UNQUALIFIED"}')
        raise SystemExit(1)
