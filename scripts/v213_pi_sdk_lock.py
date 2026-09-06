"""Extract the minimal official-registry SDK dependency graph from a local Pi install.

Reads metadata only. Does not install packages, execute third-party scripts, copy
credentials or include unrelated developer plugins. Installation remains pi install -l.
"""
from __future__ import annotations
import argparse
import base64
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit, quote
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PROFILE = json.loads((ROOT / 'config/v213-pi-inference-v1.json').read_text(encoding='utf-8'))


def resolve(packages: dict, parent: str, name: str) -> str:
    if not re.fullmatch(r'(?:@[a-z0-9._-]+/)?[a-z0-9._-]+', name):
        raise ValueError('PI_DEPENDENCY_NAME_INVALID')
    current = PurePosixPath(parent)
    while True:
        if current.name != 'node_modules':
            candidate = str(current / 'node_modules' / name)
            if candidate in packages:
                return candidate
        if str(current) == '.':
            break
        current = current.parent
    raise ValueError('PI_LOCK_DEPENDENCY_MISSING')


class NoRegistryRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('PI_REGISTRY_REDIRECT_FORBIDDEN')


def registry_integrity(name: str, version: str, expected_url: str) -> str:
    request = urllib.request.Request('https://registry.npmjs.org/' + quote(name, safe='') + '/' + quote(version, safe=''),
                                     headers={'accept': 'application/json'})
    with urllib.request.build_opener(NoRegistryRedirect()).open(request, timeout=20) as response:
        if urlsplit(response.geturl()).netloc != 'registry.npmjs.org':
            raise ValueError('PI_REGISTRY_REDIRECT_FORBIDDEN')
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024: raise ValueError('PI_REGISTRY_METADATA_TOO_LARGE')
    value = json.loads(raw)
    if value.get('name') != name or value.get('version') != version or value.get('dist', {}).get('tarball') != expected_url:
        raise ValueError('PI_REGISTRY_IDENTITY_MISMATCH')
    return value['dist']['integrity']


def extract(lock: dict, lookup=None) -> tuple[dict, dict]:
    if lock.get('lockfileVersion') != 3 or not isinstance(lock.get('packages'), dict):
        raise ValueError('PI_LOCK_SCHEMA_INVALID')
    packages = lock['packages']
    start = 'node_modules/' + PROFILE['sdk_package']
    if packages.get(start, {}).get('version') != PROFILE['sdk_version']:
        raise ValueError('PI_SDK_VERSION_MISMATCH')
    pending = [start]
    selected = {}
    while pending:
        key = pending.pop()
        if key in selected:
            continue
        if '\\' in key or '..' in PurePosixPath(key).parts or not key.startswith('node_modules/'):
            raise ValueError('PI_LOCK_PATH_INVALID')
        entry = dict(packages[key])
        if entry.get('link'):
            raise ValueError('PI_LOCK_LINK_FORBIDDEN')
        url = urlsplit(entry.get('resolved', ''))
        if url.scheme != 'https' or url.netloc != 'registry.npmjs.org' or url.query or url.fragment:
            raise ValueError('PI_LOCK_REGISTRY_FORBIDDEN')
        integrity = entry.get('integrity', '')
        if not integrity and lookup is not None:
            integrity = lookup(key.rsplit('node_modules/', 1)[1], entry['version'], entry['resolved'])
            entry['integrity'] = integrity
        if not integrity.startswith('sha512-') or len(base64.b64decode(integrity[7:], validate=True)) != 64:
            raise ValueError('PI_LOCK_INTEGRITY_INVALID')
        selected[key] = entry
        for field in ('dependencies', 'optionalDependencies', 'peerDependencies'):
            for name in entry.get(field, {}):
                try:
                    target = resolve(packages, key, name)
                except ValueError:
                    optional_peer = entry.get('peerDependenciesMeta', {}).get(name, {}).get('optional') is True
                    if field == 'optionalDependencies' or (field == 'peerDependencies' and optional_peer):
                        continue
                    raise
                pending.append(target)
    manifest = {'name': 'investor-intelligence-pi-runtime', 'version': '2.1.3', 'private': True,
                'dependencies': {PROFILE['sdk_package']: PROFILE['sdk_version']}}
    runtime_lock = {'name': manifest['name'], 'version': manifest['version'], 'lockfileVersion': 3, 'requires': True,
                    'packages': {'': {k: manifest[k] for k in ('name', 'version', 'dependencies')}, **dict(sorted(selected.items()))}}
    return manifest, runtime_lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-project', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--resolve-missing-integrity', action='store_true', help='Read exact public npm registry metadata; not an installed-byte verification')
    args = parser.parse_args()
    source = args.source_project / '.pi/npm/package-lock.json'
    manifest, lock = extract(json.loads(source.read_text(encoding='utf-8')), registry_integrity if args.resolve_missing_integrity else None)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in [('package.json', manifest), ('package-lock.json', lock)]:
        (args.output_dir / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'SDK_LOCK_EXTRACTED', 'package_count': len(lock['packages']) - 1,
                      'packages_installed': 0, 'third_party_code_executed': False, 'installed_bytes_verified': False}))

if __name__ == '__main__': main()
