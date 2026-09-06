"""Self-test for a Pi SDK standalone unit (hermetic; no network).

A standalone unit is the deployable Pi SDK package:
    <unit>/pi/npm/node_modules/...   -> <target>/.pi/npm/node_modules/
    <unit>/pi/settings.json          -> <target>/.pi/settings.json
    <unit>/pi/settings.template.json -> <target>/.pi/settings.template.json
    <unit>/pi/package-lock.json      pinned SDK lock (registry byte-verified
                                     separately by v213_pi_sdk_byte_verify.py)
    <unit>/skills/<name>/SKILL.md    bundled skills
    <unit>/MANIFEST.json             unit metadata
    <unit>/SHA256SUMS.txt            per-file SHA256

Checks (all fail closed):
  unit_layout      required entries exist, no symlinks in node_modules
  settings_audit   valid JSON, no secret-like keys or values, exact canonical
                   model pin, localhost router, xhigh thinking, skill paths
                   resolve to bundled skills with valid frontmatter
  sha256sums       every listed file's bytes match its SHA256 (long-path aware)
  manifest         counts and lock hash agree with the unit contents
  node_load_proof  node requires the SDK entry from the standalone tree; the
                   reported version matches the lock and exports are present

Optional:
  --source-install-root  additionally byte-compares the unit's node_modules
                         against a known-good install (copy fidelity)

The registry byte verification (v213_pi_sdk_byte_verify.py) is a separate
networked step; this tool never touches the network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

MARKER = chr(92) + chr(92) + '?' + chr(92)
LP_THRESHOLD = 200  # scandir on Windows breaks below MAX_PATH (observed 256)

SECRET_KEY_RE = re.compile(
    r'(token|secret|password|passwd|api_?key|access_?key|channel_?access|cookie)', re.I)
SECRET_VALUE_RE = re.compile(
    r'(sk-[A-Za-z0-9]{16,}|xox[baprs]-[A-Za-z0-9-]{12,}|ghp_[A-Za-z0-9]{20,}|'
    r'AIza[0-9A-Za-z_-]{30,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,})')


def lp(p: str) -> str:
    if os.name != 'nt' or p.startswith(MARKER):
        return p
    s = p.replace('/', chr(92))
    if not os.path.isabs(s):
        s = os.path.join(os.getcwd(), s)
    return MARKER + s if len(s) > LP_THRESHOLD else s


def exists(p: Path) -> bool:
    return os.path.exists(lp(str(p)))


def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with open(lp(str(p)), 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def inventory(root: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}

    def walk(dirpath: Path, rel: str) -> None:
        for entry in os.scandir(lp(str(dirpath))):
            if entry.is_symlink():
                raise ValueError('SYMLINK_FORBIDDEN: ' + entry.path)
            relname = rel + '/' + entry.name if rel else entry.name
            if entry.is_dir(follow_symlinks=False):
                walk(Path(entry.path), relname)
            elif entry.is_file(follow_symlinks=False):
                out[relname] = Path(entry.path)

    walk(root, '')
    return out


def check_unit_layout(unit: Path) -> dict:
    errors = []
    required = [
        unit / 'pi' / 'npm' / 'node_modules',
        unit / 'pi' / 'npm' / 'node_modules' / '@earendil-works' / 'pi-coding-agent' / 'dist' / 'index.js',
        unit / 'pi' / 'settings.json',
        unit / 'pi' / 'settings.template.json',
        unit / 'pi' / 'package-lock.json',
        unit / 'skills',
        unit / 'MANIFEST.json',
        unit / 'SHA256SUMS.txt',
    ]
    for p in required:
        if not exists(p):
            errors.append(f'missing: {p.relative_to(unit).as_posix()}')
    # A deployable unit must contain no symlinks anywhere (inventory raises).
    try:
        inventory(unit)
    except ValueError as exc:
        errors.append(str(exc))
    return {'errors': errors}


def check_settings_audit(unit: Path) -> dict:
    errors = []
    settings_path = unit / 'pi' / 'settings.json'
    try:
        settings = json.loads(settings_path.read_text(encoding='utf-8-sig'))
    except Exception as exc:
        return {'errors': [f'settings.json unparseable: {exc}'], 'model': None}

    def scan(obj, path='$'):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if SECRET_KEY_RE.search(str(k)):
                    errors.append(f'secret-like key: {path}.{k}')
                scan(v, f'{path}.{k}')
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                scan(v, f'{path}[{i}]')
        elif isinstance(obj, str):
            if SECRET_VALUE_RE.search(obj):
                errors.append(f'secret-like value at {path}')

    scan(settings)

    # Exact canonical llama.cpp IDs end in a hash suffix of variable length
    # (e.g. -844843d973bf, -7a1459e88548); aliases (qwen38-q5) have none.
    model = settings.get('defaultModel', '')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*-[0-9a-f]{8,20}', str(model)):
        errors.append(f'defaultModel is not an exact canonical model ID: {model!r}')
    url = str(settings.get('llamaServerUrl', ''))
    if not re.fullmatch(r'https?://127\.0\.0\.1:\d+', url):
        errors.append(f'llamaServerUrl must be localhost: {url!r}')
    if settings.get('defaultThinkingLevel') != 'xhigh':
        errors.append(f'defaultThinkingLevel must be xhigh: {settings.get("defaultThinkingLevel")!r}')
    skills = settings.get('skills', [])
    if not skills:
        errors.append('no skills configured')
    for s in skills:
        name = Path(str(s)).name
        skill_md = unit / 'skills' / name / 'SKILL.md'
        if not exists(skill_md):
            errors.append(f'skill path does not resolve to a bundled skill: {s}')
            continue
        text = skill_md.read_text(encoding='utf-8')
        if not re.search(r'(?m)^name:\s*\S+', text) or not re.search(r'(?m)^description:\s*\S+', text):
            errors.append(f'skill frontmatter invalid: {s}')
    return {'errors': errors, 'model': model, 'skills': skills}


def check_sha256sums(unit: Path) -> dict:
    errors = []
    sums_path = unit / 'SHA256SUMS.txt'
    lines = sums_path.read_text(encoding='utf-8').splitlines()
    count = 0
    for line in lines:
        if not line.strip():
            continue
        parts = line.split('  ', 1)
        if len(parts) != 2:
            errors.append(f'malformed line: {line[:80]!r}')
            continue
        digest, rel = parts
        p = unit / rel
        if not exists(p):
            errors.append(f'listed file missing: {rel}')
            continue
        if sha256_of(p) != digest:
            errors.append(f'sha256 mismatch: {rel}')
        count += 1
    return {'errors': errors, 'files_checked': count}


def check_manifest(unit: Path, lock: dict) -> dict:
    errors = []
    manifest = json.loads((unit / 'MANIFEST.json').read_text(encoding='utf-8'))
    actual_lock_hash = sha256_of(unit / 'pi' / 'package-lock.json')
    if manifest.get('lockfile_sha256') != actual_lock_hash:
        errors.append('manifest lockfile_sha256 does not match unit lock')
    if manifest.get('sdk_version') != lock['packages'].get(
            'node_modules/@earendil-works/pi-coding-agent', {}).get('version'):
        errors.append('manifest sdk_version does not match lock')
    actual_nm = len(inventory(unit / 'pi' / 'npm' / 'node_modules'))
    if manifest.get('node_modules_file_count') != actual_nm:
        errors.append(
            f'manifest node_modules_file_count={manifest.get("node_modules_file_count")} '
            f'actual={actual_nm}')
    if manifest.get('secrets_included') is not False:
        errors.append('manifest must declare secrets_included=false')
    return {'errors': errors}


def check_node_load_proof(unit: Path, lock: dict, node: str | None) -> dict:
    if node is None:
        return {'errors': ['node runtime not found'], 'version': None, 'export_count': 0}
    entry = (unit / 'pi' / 'npm' / 'node_modules' / '@earendil-works'
             / 'pi-coding-agent' / 'dist' / 'index.js')
    script = (
        'const path=require("path");'
        f'const entry={json.dumps(str(entry))};'
        'const mod=require(entry);'
        'const pkg=require(path.join(path.dirname(entry),"..","package.json"));'
        'console.log(JSON.stringify({version:pkg.version,exports:Object.keys(mod).length}));'
    )
    try:
        proc = subprocess.run(
            [node, '-e', script], capture_output=True, text=True, timeout=120)
    except Exception as exc:
        return {'errors': [f'node load failed: {exc}'], 'version': None, 'export_count': 0}
    if proc.returncode != 0:
        return {'errors': [f'node load rc={proc.returncode}: '
                           f'{(proc.stderr or proc.stdout)[:400]}'],
                'version': None, 'export_count': 0}
    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as exc:
        return {'errors': [f'unparsable node proof: {exc}; {proc.stdout[:200]!r}'],
                'version': None, 'export_count': 0}
    errors = []
    expected = lock['packages'].get(
        'node_modules/@earendil-works/pi-coding-agent', {}).get('version')
    if out.get('version') != expected:
        errors.append(f'node version {out.get("version")} != lock version {expected}')
    if not isinstance(out.get('exports'), int) or out['exports'] < 10:
        errors.append(f'suspicious export count: {out.get("exports")}')
    return {'errors': errors, 'version': out.get('version'),
            'export_count': out.get('exports', 0)}


def check_copy_fidelity(unit: Path, source_root: Path) -> dict:
    errors = []
    src_inv = inventory(source_root / 'node_modules')
    dst_inv = inventory(unit / 'pi' / 'npm' / 'node_modules')
    only_src = sorted(set(src_inv) - set(dst_inv))
    only_dst = sorted(set(dst_inv) - set(src_inv))
    mismatches = 0
    for rel in sorted(set(src_inv) & set(dst_inv)):
        with open(lp(str(src_inv[rel])), 'rb') as f:
            a = f.read()
        with open(lp(str(dst_inv[rel])), 'rb') as f:
            b = f.read()
        if a != b:
            mismatches += 1
            if mismatches <= 10:
                errors.append(f'byte mismatch: {rel}')
    if only_src:
        errors.append(f'{len(only_src)} files missing from unit (first: {only_src[0]})')
    if only_dst:
        errors.append(f'{len(only_dst)} extra files in unit (first: {only_dst[0]})')
    return {'errors': errors, 'source_files': len(src_inv), 'unit_files': len(dst_inv),
            'byte_mismatches': mismatches}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit', required=True, type=Path)
    parser.add_argument('--source-install-root', type=Path, default=None,
                        help='known-good install root (directory containing node_modules)')
    parser.add_argument('--receipt', type=Path, default=None)
    args = parser.parse_args()
    unit = args.unit.resolve()

    lock = json.loads((unit / 'pi' / 'package-lock.json').read_text(encoding='utf-8'))
    node = shutil.which('node')
    check_fns = {
        'unit_layout': lambda: check_unit_layout(unit),
        'settings_audit': lambda: check_settings_audit(unit),
        'sha256sums': lambda: check_sha256sums(unit),
        'manifest': lambda: check_manifest(unit, lock),
        'node_load_proof': lambda: check_node_load_proof(unit, lock, node),
    }
    if args.source_install_root is not None:
        check_fns['copy_fidelity'] = lambda: check_copy_fidelity(
            unit, args.source_install_root.resolve())
    checks = {}
    for name in check_fns:
        try:
            checks[name] = check_fns[name]()
        except Exception as exc:  # fail closed, never crash mid-receipt
            checks[name] = {'errors': [f'{type(exc).__name__}: {exc}']}

    failed = [name for name, r in checks.items() if r.get('errors')]
    receipt = {
        'scope': 'PI_SDK_STANDALONE_SELF_TEST',
        'unit': str(unit),
        'checks': checks,
        'status': 'PASS' if not failed else 'FAIL',
        'failed_checks': failed,
        'network_used': False,
    }
    receipt_path = args.receipt or (unit.parent / (unit.name + '-self-test-receipt.json'))
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=1, sort_keys=True) + '\n',
                            encoding='utf-8')
    print(f"PI_SDK_STANDALONE_SELF_TEST = {receipt['status']}")
    for name in sorted(checks):
        r = checks[name]
        extra = r.get('errors', [])
        print(f'  {name}: {"PASS" if not extra else "FAIL"}'
              + (f' ({len(extra)} errors)' if extra else ''))
        for e in extra[:5]:
            print(f'    - {e}')
    print(f'receipt: {receipt_path}')
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
