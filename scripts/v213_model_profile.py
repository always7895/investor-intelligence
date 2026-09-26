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


if __name__ == '__main__':
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--profile', type=Path)
    group.add_argument('--env', action='store_true')
    args = parser.parse_args()
    try:
        import os
        raw = os.environ.get('V213_MODEL_PROFILE_JSON') if args.env else args.profile.read_text(encoding='utf-8-sig')
        profile = parse_profile(raw)
        print(json.dumps({'schema_version': 1, 'profile': profile,
                          'profile_sha256': profile_sha256(profile), 'release_qualified': False}))
    except (OSError, UnicodeError, ValueError):
        print('{"error":"MODEL_PROFILE_INVALID"}')
        raise SystemExit(1)
