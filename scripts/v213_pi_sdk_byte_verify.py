"""Verify installed project-local Pi SDK bytes against the pinned registry tarballs.

Scope: every package in runtime/pi/package-lock.json (the SDK-only reachable
graph). For each package this tool:
  1. resolves its install directory from the lock key under the install root;
  2. downloads the exact pinned tarball (https://registry.npmjs.org only,
     redirects forbidden, bounded size);
  3. verifies the lock's SHA512 integrity against the downloaded bytes;
  4. extracts the tarball and byte-compares EVERY published file against the
     installed tree (missing, extra, symlinked or differing files fail).

No lifecycle scripts run, nothing is installed, no credentials are read.
Network: registry.npmjs.org only. This is read-only verification.
"""
from __future__ import annotations
import argparse
import base64
import concurrent.futures as cf
import hashlib
import io
import json
import os
import tarfile
import urllib.request
from pathlib import Path


class NoRegistryRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('PI_REGISTRY_REDIRECT_FORBIDDEN')


def sri_sha512(integrity: str) -> bytes:
    if not integrity.startswith('sha512-'):
        raise ValueError('PI_INTEGRITY_ALGORITHM_UNSUPPORTED')
    raw = base64.b64decode(integrity.split('-', 1)[1])
    if len(raw) != 64:
        raise ValueError('PI_INTEGRITY_LENGTH_INVALID')
    return raw


def fetch_tarball(url: str) -> bytes:
    request = urllib.request.Request(url, headers={'accept': 'application/octet-stream',
                                                   'user-agent': 'ii-r75-sdk-byte-verify/2.1.3'})
    with urllib.request.build_opener(NoRegistryRedirect()).open(request, timeout=60) as response:
        if urlsplit_netloc(response.geturl()) != 'registry.npmjs.org':
            raise ValueError('PI_REGISTRY_HOST_MISMATCH')
        data = response.read(MAX_TARBALL_BYTES + 1)
    if len(data) > MAX_TARBALL_BYTES:
        raise ValueError('PI_TARBALL_TOO_LARGE')
    return data


def urlsplit_netloc(url: str) -> str:
    from urllib.parse import urlsplit
    return urlsplit(url).netloc


MAX_TARBALL_BYTES = 16 * 1024 * 1024


def tarball_files(blob: bytes) -> dict[str, bytes]:
    """All published files, relative to the tarball's single top-level prefix.

    npm standard uses 'package/'; @types packages publish under a versioned
    directory (e.g. 'node v22.19/'). Exactly one shared top-level directory is
    required; anything else fails closed.
    """
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as tar:
        all_members = tar.getmembers()
    if any(m.issym() or m.islnk() for m in all_members):
        raise ValueError('PI_TARBALL_LINK_FORBIDDEN')
    members = [m for m in all_members if m.isfile()]
    if not members:
        raise ValueError('PI_TARBALL_EMPTY')
    prefixes = {m.name.split('/', 1)[0] for m in members}
    if len(prefixes) != 1 or '/' in next(iter(prefixes)):
        raise ValueError('PI_TARBALL_LAYOUT_UNEXPECTED')
    prefix = prefixes.pop()
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as tar:
        for member in members:
            name = member.name[len(prefix) + 1:]
            if name.startswith('./'):
                name = name[2:]
            if not name or name.startswith('../') or '..' in name.split('/') or name.startswith('/'):
                raise ValueError('PI_TARBALL_PATH_UNSAFE')
            handle = tar.extractfile(member)
            if handle is None:
                continue
            out[name] = handle.read()
    if not out:
        raise ValueError('PI_TARBALL_EMPTY')
    return out


def _long_path(p: str) -> str:
    # Windows MAX_PATH-aware form: convert to an absolute path, then prefix
    # paths over 258 chars with the extended-length marker so stat/read do
    # not fail with FileNotFoundError.
    if os.name != 'nt':
        return p
    marker = chr(92) + chr(92) + '?' + chr(92)
    if p.startswith(marker):
        return p
    s = p.replace('/', chr(92))
    if not os.path.isabs(s):
        s = os.path.join(os.getcwd(), s)
    if len(s) > 258:
        return marker + s
    return s


def installed_files(root: Path, exclude_prefixes: set[str]) -> tuple[dict[str, bytes], int]:
    """Installed package files, excluding nested lock-package subtrees and the
    npm-generated .bin shims (created by npm at install time; not published
    content). Walks with long-path-aware scandir so MAX_PATH cannot hide files.
    Returns (files, excluded_count)."""
    out: dict[str, bytes] = {}
    counter = {'excluded': 0}

    def walk(dirpath: Path, rel: str) -> None:
        for entry in os.scandir(_long_path(str(dirpath))):
            relname = f'{rel}/{entry.name}' if rel else entry.name
            if entry.is_symlink():
                raise ValueError('PI_INSTALLED_LINK_FORBIDDEN')
            if entry.is_dir(follow_symlinks=False):
                walk(Path(entry.path), relname)
            elif entry.is_file(follow_symlinks=False):
                if relname.startswith('node_modules/.bin/') or any(
                        relname == p or relname.startswith(p + '/') for p in exclude_prefixes):
                    counter['excluded'] += 1
                    continue
                with open(_long_path(entry.path), 'rb') as handle:
                    out[relname] = handle.read()

    walk(root, '')
    return out, counter['excluded']


def verify_package(key: str, entry: dict, install_root: Path, workdir: Path, lock_keys: set[str]) -> dict:
    name = key.rsplit('node_modules/', 1)[1]
    url = entry.get('resolved', '')
    if urlsplit_netloc(url) != 'registry.npmjs.org' or 'registry.npmjs.org' not in url:
        raise ValueError('PI_RESOLVED_HOST_INVALID')
    expected = sri_sha512(entry['integrity'])
    blob = fetch_tarball(url)
    if hashlib.sha512(blob).digest() != expected:
        raise ValueError('PI_TARBALL_SHA512_MISMATCH')
    tarred = tarball_files(blob)
    installed_dir = install_root / key
    if not installed_dir.is_dir():
        raise ValueError('PI_INSTALLED_DIR_MISSING')
    nested = {k[len(key) + 1:] for k in lock_keys if k.startswith(key + '/node_modules/')}
    on_disk, excluded = installed_files(installed_dir, nested)
    missing = sorted(set(tarred) - set(on_disk))
    extra = sorted(set(on_disk) - set(tarred))
    differing = sorted(n for n in set(tarred) & set(on_disk) if on_disk[n] != tarred[n])
    if missing or extra or differing:
        detail = {'missing': missing[:8], 'extra': extra[:8], 'differing': differing[:8]}
        raise ValueError('PI_INSTALLED_BYTES_MISMATCH:' + json.dumps(detail, separators=(',', ':'))[:400])
    return {'name': name, 'version': entry['version'], 'files': len(tarred), 'npm_generated_files_excluded': excluded,
            'tarball_bytes': len(blob), 'sha512': expected.hex(), 'status': 'PASS'}


def main() -> int:
    global MAX_TARBALL_BYTES
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--install-root', type=Path, required=True, help='Directory containing node_modules (e.g. .pi/npm)')
    parser.add_argument('--workdir', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    MAX_TARBALL_BYTES = 16 * 1024 * 1024
    args.install_root = args.install_root.resolve()
    lock = json.loads(args.lock.read_text(encoding='utf-8'))
    packages = {k: v for k, v in lock['packages'].items() if k}
    args.workdir.mkdir(parents=True, exist_ok=True)
    failures: dict[str, str] = {}
    results: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(verify_package, k, v, args.install_root, args.workdir, set(packages)): k for k, v in sorted(packages.items())}
        for future in cf.as_completed(futures):
            key = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 - bounded redacted code per package
                code = str(exc).split(':', 1)[0]
                failures[key] = code if code.startswith('PI_') else 'PI_VERIFY_FAILED'
    results.sort(key=lambda r: r['name'])
    receipt = {
        'scope': 'PI_SDK_INSTALLED_BYTE_VERIFICATION',
        'lock': str(args.lock),
        'packages_expected': len(packages),
        'packages_verified': len(results),
        'packages_failed': len(failures),
        'failures': failures,
        'total_files_verified': sum(r['files'] for r in results),
        'npm_generated_files_excluded': sum(r['npm_generated_files_excluded'] for r in results),
        'total_tarball_bytes': sum(r['tarball_bytes'] for r in results),
        'registry_only': True,
        'lifecycle_scripts_executed': False,
        'production_mutation': False,
        'status': 'PASS' if not failures else 'FAIL',
        'results': results,
    }
    out = args.workdir / 'pi-sdk-byte-verify-receipt.json'
    out.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({k: receipt[k] for k in
                      ('status', 'packages_expected', 'packages_verified', 'packages_failed',
                       'total_files_verified', 'total_tarball_bytes')}, indent=1))
    if failures:
        print(json.dumps(failures, indent=1))
    return 0 if not failures else 1


if __name__ == '__main__':
    raise SystemExit(main())
