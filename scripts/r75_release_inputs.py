"""Select a HEAD-bound QA receipt; selection never grants qualification."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

REFERENCE = 'state/r75-qa-live-current.ref.json'
LIMIT = 1024 * 1024


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, timeout=15)
    if result.returncode:
        raise ValueError('R75_QA_INPUT_NOT_COMMITTED')
    return result.stdout


def committed_bytes(root: Path, relative: str, commit: str = 'HEAD') -> bytes:
    if (not isinstance(relative, str) or not re.fullmatch(r'state/[A-Za-z0-9][A-Za-z0-9._-]{0,160}\.json', relative)
            or '..' in relative):
        raise ValueError('R75_QA_INPUT_PATH_INVALID')
    tree = _git(root, 'ls-tree', commit, '--', relative).decode('utf-8').strip()
    if not re.fullmatch(r'100(?:644|755) blob [0-9a-f]{40}\t' + re.escape(relative), tree):
        raise ValueError('R75_QA_INPUT_NOT_REGULAR_COMMITTED_FILE')
    blob = tree.split('\t', 1)[0].split()[2]
    size = int(_git(root, 'cat-file', '-s', blob).strip())
    if not 0 < size <= LIMIT:
        raise ValueError('R75_QA_INPUT_SIZE_INVALID')
    path = root / relative
    for part in (path.parent, path):
        if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
            raise ValueError('R75_QA_INPUT_LINK_FORBIDDEN')
    path.resolve(strict=True).relative_to(root.resolve(strict=True))
    if path.stat().st_size != size:
        raise ValueError('R75_QA_INPUT_WORKTREE_DRIFT')
    with path.open('rb') as stream:
        data = stream.read(LIMIT + 1)
    if data != _git(root, 'cat-file', 'blob', blob):
        raise ValueError('R75_QA_INPUT_WORKTREE_DRIFT')
    return data


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('R75_QA_REFERENCE_DUPLICATE_KEY')
        result[key] = value
    return result


def select_receipt(root: Path) -> dict:
    root = root.resolve(strict=True)
    commit = _git(root, 'rev-parse', 'HEAD').decode('ascii').strip()
    tracked = _git(root, 'ls-tree', commit, '--', REFERENCE).strip()
    ref_path = root / REFERENCE
    # A malformed, untracked or removed pointer is NOT permission to fall back.
    if tracked or ref_path.exists() or ref_path.is_symlink():
        ref = json.loads(committed_bytes(root, REFERENCE, commit).decode('utf-8-sig'), object_pairs_hook=_object)
        if (not isinstance(ref, dict) or set(ref) != {'schema_version', 'receipt_path', 'receipt_sha256'}
                or type(ref['schema_version']) is not int or ref['schema_version'] != 1
                or not isinstance(ref['receipt_sha256'], str)
                or not re.fullmatch('[0-9a-f]{64}', ref['receipt_sha256'])):
            raise ValueError('R75_QA_REFERENCE_INVALID')
        relative = ref['receipt_path']
        data = committed_bytes(root, relative, commit)
        if hashlib.sha256(data).hexdigest() != ref['receipt_sha256']:
            raise ValueError('R75_QA_REFERENCE_DIGEST_MISMATCH')
    else:
        relative = ('state/r75-qa-live-model-profile-qualification.json'
                    if (root / 'config/v213-model-profile-v1.json').is_file()
                    else 'state/r75-qa-live-qualification.json')
        data = committed_bytes(root, relative, commit)
    return {'source_commit': commit, 'receipt_path': relative, 'receipt_sha256': hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(select_receipt(args.project_root)))
    except Exception:
        parser.exit(1, 'R75_QA_INPUT_SELECTION_FAILED; no_fallback=true\n')


if __name__ == '__main__':
    main()
