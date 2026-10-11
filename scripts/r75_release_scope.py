#!/usr/bin/env python3
"""Reviewed-scope inventory for the successor R75 release lane (build and check).

The legacy FREE_RELAY lane hard-codes the base commit and an exact-path allowlist. The successor lane keeps the same
protection (every path changed since the baseline must have accepting evidence; anything else refuses) but makes the
reviewed scope an explicit, committed, regenerable inventory:

  state/r75-release-acceptance-ranges-<lane>.json  curated input: ordered commit ranges with accepting receipts
  state/r75-release-reviewed-scope-<lane>.json     generated: every path changed baseline..covered_head, its blob and range

`build` writes the inventory from git. `check` rebuilds it from git and requires byte-for-byte equality, then applies the
narrow tail rule to the commits after covered_head. It never reads the network and never writes Git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

SCHEMA = 1
HEX40 = re.compile(r'^[0-9a-f]{40}$')
HEX64 = re.compile(r'^[0-9a-f]{64}$')
LANE = re.compile(r'^[a-z0-9][a-z0-9-]{0,30}$')
RANGE_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
INVENTORY_PATH = re.compile(r'^state/r75-release-reviewed-scope-[A-Za-z0-9][A-Za-z0-9._-]{0,60}\.json$')
RANGES_PATH = re.compile(r'^state/r75-release-acceptance-ranges-[A-Za-z0-9][A-Za-z0-9._-]{0,60}\.json$')
RECEIPT_NAME = re.compile(r'^R/[A-Za-z0-9][A-Za-z0-9._-]{0,200}$')
STATUSES = ('ACCEPTED', 'UNREVIEWED')
KINDS = ('FABLE_INDEPENDENT_ACCEPT', 'MASTER_INDEPENDENT_ACCEPT', 'DUAL_ACCEPT_RECEIPT', 'OPERATOR_DECISION', 'NONE')

# Narrow tail rule (TAIL_RULE_V1). Hard-coded here, not read from the inventory: a commit after covered_head may touch
# only the inventory and its ranges input, state/STATUS.md, the live Q&A pointer, and at most one NEW live Q&A receipt
# that the pointer names. No wildcard over state/, scripts/, tests/, cloud/ or docs/.
TAIL_RULE_ID = 'TAIL_RULE_V1'
TAIL_FIXED_STATE = ('state/STATUS.md', 'state/r75-qa-live-current.ref.json')
TAIL_QA_RECEIPT = re.compile(r'^state/r75-qa-live-[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.json$')
TAIL_MAX_COMMITS = 8
TAIL_MAX_NEW_RECEIPTS = 1
REGULAR_MODES = ('100644', '100755')
REPORT_LIMIT = 20


class ScopeRefused(Exception):
    def __init__(self, code: str, detail: str = ''):
        super().__init__(code)
        self.code = code
        self.detail = detail


def refuse(code: str, detail: str = '') -> None:
    raise ScopeRefused(code, detail)


def git(root: Path, *args: str, check: bool = True) -> bytes:
    result = subprocess.run(['git', '-C', str(root), '-c', 'core.quotepath=false', *args], capture_output=True, timeout=180)
    if check and result.returncode:
        refuse('GIT_COMMAND_FAILED', args[0])
    return result.stdout if result.returncode == 0 else b''


def resolve_commit(root: Path, revision: str) -> str:
    if not isinstance(revision, str) or not revision or revision.startswith('-'):
        refuse('REVISION_INVALID', str(revision)[:40])
    out = git(root, 'rev-parse', '--verify', '--quiet', revision + '^{commit}', check=False).decode('ascii', 'replace').strip()
    if not HEX40.fullmatch(out):
        refuse('COMMIT_NOT_FOUND', revision[:40])
    return out


def is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', ancestor, descendant], capture_output=True, timeout=60)
    if result.returncode not in (0, 1):
        refuse('GIT_COMMAND_FAILED', 'merge-base')
    return result.returncode == 0


def _tokens(data: bytes) -> list[str]:
    parts = data.decode('utf-8').split('\0')
    if parts and parts[-1] == '':
        parts.pop()
    return parts


def name_status(root: Path, *args: str) -> dict[str, str]:
    tokens = _tokens(git(root, 'diff', '--name-status', '--no-renames', '-z', *args))
    if len(tokens) % 2:
        refuse('GIT_OUTPUT_MALFORMED', 'name-status')
    out: dict[str, str] = {}
    for status, path in zip(tokens[0::2], tokens[1::2]):
        if status not in ('A', 'M', 'D', 'T'):
            refuse('CHANGE_KIND_UNSUPPORTED', path)
        out[path] = 'M' if status == 'T' else status
    return out


def tree(root: Path, commit: str) -> dict[str, tuple[str, str, str]]:
    out: dict[str, tuple[str, str, str]] = {}
    for token in _tokens(git(root, 'ls-tree', '-r', '-z', commit)):
        match = re.fullmatch(r'([0-7]{6}) (blob|commit) ([0-9a-f]{40})\t(.+)', token, re.S)
        if not match:
            refuse('GIT_OUTPUT_MALFORMED', 'ls-tree')
        out[match.group(4)] = (match.group(1), match.group(2), match.group(3))
    return out


def commit_changes(root: Path, commits: list[str]) -> list[tuple[str, dict[str, str]]]:
    """Per-commit changed paths in the given order (merge commits report none and are refused by the callers that care)."""
    if not commits:
        return []
    result = subprocess.run(['git', '-C', str(root), '-c', 'core.quotepath=false', 'diff-tree', '--stdin', '-r', '--no-renames', '--name-status', '-z'],
                            input=('\n'.join(commits) + '\n').encode('ascii'), capture_output=True, timeout=600)
    if result.returncode:
        refuse('GIT_COMMAND_FAILED', 'diff-tree')
    rows: list[tuple[str, dict[str, str]]] = []
    tokens = _tokens(result.stdout)
    index = 0
    while index < len(tokens):
        header = tokens[index]
        if not HEX40.fullmatch(header):
            refuse('GIT_OUTPUT_MALFORMED', 'diff-tree header')
        index += 1
        changes: dict[str, str] = {}
        while index + 1 < len(tokens) and not HEX40.fullmatch(tokens[index]):
            status, path = tokens[index], tokens[index + 1]
            if status not in ('A', 'M', 'D', 'T'):
                refuse('CHANGE_KIND_UNSUPPORTED', path)
            changes[path] = 'M' if status == 'T' else status
            index += 2
        rows.append((header, changes))
    if [row[0] for row in rows] != commits:
        # diff-tree omits nothing for non-merge commits; a mismatch means a merge or a malformed stream.
        merges = set(git(root, 'rev-list', '--merges', '--no-walk', *commits).decode('ascii').split())
        if merges:
            refuse('MERGE_COMMIT_IN_SCOPE', sorted(merges)[0][:12])
        refuse('GIT_OUTPUT_MALFORMED', 'diff-tree order')
    return rows


def rev_list(root: Path, baseline: str, head: str) -> list[str]:
    commits = git(root, 'rev-list', '--reverse', '--topo-order', f'{baseline}..{head}').decode('ascii').split()
    if any(not HEX40.fullmatch(c) for c in commits):
        refuse('GIT_OUTPUT_MALFORMED', 'rev-list')
    return commits


def _object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            refuse('JSON_DUPLICATE_KEY', str(key)[:40])
        out[key] = value
    return out


def load_json(data: bytes, what: str):
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=_object)
    except (ValueError, UnicodeError):
        refuse('JSON_INVALID', what)


def dump(value) -> bytes:
    return (json.dumps(value, indent=1, ensure_ascii=True) + '\n').encode('ascii')


def committed_bytes(root: Path, commit: str, relative: str) -> bytes:
    entry = tree(root, commit).get(relative)
    if entry is None or entry[1] != 'blob' or entry[0] not in REGULAR_MODES:
        refuse('FILE_NOT_COMMITTED', relative)
    return git(root, 'cat-file', 'blob', entry[2])


def validate_ranges_document(doc) -> list[dict]:
    if (not isinstance(doc, dict) or set(doc) != {'schema_version', 'lane', 'baseline', 'ranges'} or doc['schema_version'] != SCHEMA
            or type(doc['schema_version']) is not int or not isinstance(doc['lane'], str) or not LANE.fullmatch(doc['lane'])
            or not isinstance(doc['baseline'], str) or not HEX40.fullmatch(doc['baseline']) or not isinstance(doc['ranges'], list)
            or not doc['ranges']):
        refuse('RANGES_INVALID', 'document')
    seen: set[str] = set()
    for row in doc['ranges']:
        if (not isinstance(row, dict) or set(row) != {'id', 'to', 'status', 'kind', 'receipt', 'note'}
                or not all(isinstance(row[k], str) for k in row) or not RANGE_ID.fullmatch(row['id']) or row['id'] in seen
                or not HEX40.fullmatch(row['to']) or row['status'] not in STATUSES or row['kind'] not in KINDS):
            refuse('RANGES_INVALID', str(row.get('id') if isinstance(row, dict) else row)[:40])
        seen.add(row['id'])
        if row['status'] == 'ACCEPTED' and (row['kind'] == 'NONE' or not RECEIPT_NAME.fullmatch(row['receipt'])):
            refuse('RANGE_ACCEPTED_WITHOUT_RECEIPT', row['id'])
        if row['status'] == 'UNREVIEWED' and row['kind'] != 'NONE':
            refuse('RANGE_UNREVIEWED_WITH_KIND', row['id'])
        if len(row['note']) > 600:
            refuse('RANGES_INVALID', row['id'])
    return doc['ranges']


def build_inventory(root: Path, ranges_doc: dict, covered_head: str) -> dict:
    """Pure function of git objects and the curated ranges; used by `build` and by `check`."""
    ranges = validate_ranges_document(ranges_doc)
    baseline = ranges_doc['baseline']
    if resolve_commit(root, baseline) != baseline:
        refuse('BASELINE_NOT_FOUND', baseline[:12])
    if baseline == covered_head or not is_ancestor(root, baseline, covered_head):
        refuse('BASELINE_NOT_ANCESTOR', baseline[:12])
    if git(root, 'rev-list', '--merges', f'{baseline}..{covered_head}').strip():
        refuse('MERGE_COMMIT_IN_SCOPE', baseline[:12])
    commits = rev_list(root, baseline, covered_head)
    position = {c: i for i, c in enumerate(commits)}
    last = -1
    commit_range: list[str] = []
    for row in ranges:
        if row['to'] not in position:
            refuse('RANGE_END_NOT_IN_HISTORY', row['id'])
        if position[row['to']] <= last:
            refuse('RANGE_ORDER_INVALID', row['id'])
        commit_range.extend([row['id']] * (position[row['to']] - last))
        last = position[row['to']]
    unassigned = len(commits) - 1 - last
    commit_range.extend(['UNASSIGNED_TAIL'] * unassigned)
    by_id = {row['id']: row for row in ranges}
    by_id['UNASSIGNED_TAIL'] = {'id': 'UNASSIGNED_TAIL', 'to': covered_head, 'status': 'UNREVIEWED', 'kind': 'NONE', 'receipt': '',
                                'note': 'Commits after the last curated range end; add a range that covers them.'}
    net = name_status(root, baseline, covered_head)
    head_tree = tree(root, covered_head)
    touched: dict[str, list[str]] = {}
    for (_, changes), rid in zip(commit_changes(root, commits), commit_range):
        for path in changes:
            if path in net:
                chain = touched.setdefault(path, [])
                if not chain or chain[-1] != rid:
                    chain.append(rid)
    paths = []
    for path in sorted(net):
        chain = touched.get(path, [])
        entry = head_tree.get(path)
        if net[path] != 'D':
            if entry is None or entry[1] != 'blob' or entry[0] not in REGULAR_MODES:
                refuse('PATH_NOT_REGULAR_BLOB', path)
        final = by_id[chain[-1]] if chain else None
        status = 'ACCEPTED' if final is not None and final['status'] == 'ACCEPTED' else 'UNREVIEWED'
        paths.append({'path': path, 'change': net[path], 'blob': None if net[path] == 'D' else entry[2],
                      'range': chain[-1] if chain else 'NONE', 'touched_by': chain or ['NONE'],
                      'status': status, 'evidence': final['receipt'] if final is not None else ''})
    touched_ids = {c for p in paths for c in p['touched_by']}
    used = [rid for rid in [r['id'] for r in ranges] + ['UNASSIGNED_TAIL'] if rid in touched_ids]
    inventory = {
        'schema_version': SCHEMA, 'lane': ranges_doc['lane'], 'baseline': baseline, 'covered_head': covered_head,
        'tail_rule': TAIL_RULE_ID, 'commit_count': len(commits),
        'ranges': [dict(row) for row in ranges] + ([by_id['UNASSIGNED_TAIL']] if unassigned else []),
        'ranges_used': used, 'paths': paths,
    }
    return inventory


def summarize(inventory: dict) -> dict:
    unreviewed = [p['path'] for p in inventory['paths'] if p['status'] != 'ACCEPTED']
    return {'lane': inventory['lane'], 'baseline': inventory['baseline'], 'covered_head': inventory['covered_head'],
            'paths': len(inventory['paths']), 'unreviewed': len(unreviewed), 'unreviewed_sample': unreviewed[:REPORT_LIMIT],
            'unreviewed_ranges': sorted({r['id'] for r in inventory['ranges'] if r['status'] != 'ACCEPTED'}),
            'unreviewed_by_range': {rid: sum(1 for p in inventory['paths'] if p['range'] == rid and p['status'] != 'ACCEPTED')
                                    for rid in sorted({p['range'] for p in inventory['paths'] if p['status'] != 'ACCEPTED'})}}


def check_tail(root: Path, covered_head: str, head: str, inventory_path: str, ranges_path: str) -> dict:
    if head == covered_head:
        return {'tail_commits': 0, 'new_receipts': []}
    if not is_ancestor(root, covered_head, head):
        refuse('COVERED_HEAD_NOT_ANCESTOR', covered_head[:12])
    commits = rev_list(root, covered_head, head)
    if len(commits) > TAIL_MAX_COMMITS:
        refuse('TAIL_TOO_LONG', str(len(commits)))
    if git(root, 'rev-list', '--merges', f'{covered_head}..{head}').strip():
        refuse('TAIL_MERGE_FORBIDDEN')
    allowed_fixed = {inventory_path, ranges_path, *TAIL_FIXED_STATE}
    new_receipts: list[str] = []
    covered_tree = tree(root, covered_head)
    for sha, changes in commit_changes(root, commits):
        for path, kind in changes.items():
            if path in allowed_fixed:
                if kind == 'D':
                    refuse('TAIL_DELETE_FORBIDDEN', path)
                continue
            if TAIL_QA_RECEIPT.fullmatch(path) and kind == 'A' and path not in covered_tree:
                if path not in new_receipts:
                    new_receipts.append(path)
                continue
            refuse('TAIL_PATH_NOT_ALLOWED', f'{path} {sha[:12]}')
    if len(new_receipts) > TAIL_MAX_NEW_RECEIPTS:
        refuse('TAIL_TOO_MANY_RECEIPTS', str(len(new_receipts)))
    if new_receipts:
        pointer = load_json(committed_bytes(root, head, 'state/r75-qa-live-current.ref.json'), 'QA pointer')
        if not isinstance(pointer, dict) or pointer.get('receipt_path') != new_receipts[0]:
            refuse('TAIL_RECEIPT_NOT_POINTED_AT', new_receipts[0])
    return {'tail_commits': len(commits), 'new_receipts': new_receipts}


def check(root: Path, inventory_path: str, head_revision: str = 'HEAD', ranges_path: str | None = None,
          expect_sha256: str | None = None, receipts_root: Path | None = None) -> dict:
    root = root.resolve(strict=True)
    if not INVENTORY_PATH.fullmatch(inventory_path):
        refuse('INVENTORY_PATH_INVALID', inventory_path[:80])
    head = resolve_commit(root, head_revision)
    raw = committed_bytes(root, head, inventory_path)
    digest = hashlib.sha256(raw).hexdigest()
    if expect_sha256 is not None and (not HEX64.fullmatch(expect_sha256) or expect_sha256 != digest):
        refuse('INVENTORY_DIGEST_MISMATCH', digest[:12])
    doc = load_json(raw, 'inventory')
    if (not isinstance(doc, dict) or doc.get('schema_version') != SCHEMA or doc.get('tail_rule') != TAIL_RULE_ID
            or not isinstance(doc.get('covered_head'), str) or not HEX40.fullmatch(doc['covered_head'])
            or not isinstance(doc.get('baseline'), str) or not HEX40.fullmatch(doc['baseline'])
            or not isinstance(doc.get('lane'), str) or not LANE.fullmatch(doc['lane']) or not isinstance(doc.get('ranges'), list)
            or not isinstance(doc.get('paths'), list)):
        refuse('INVENTORY_INVALID')
    covered, baseline = doc['covered_head'], doc['baseline']
    if resolve_commit(root, baseline) != baseline or resolve_commit(root, covered) != covered:
        refuse('INVENTORY_COMMIT_NOT_FOUND')
    if not is_ancestor(root, baseline, head):
        refuse('BASELINE_NOT_ANCESTOR', baseline[:12])
    if baseline == covered or not is_ancestor(root, baseline, covered):
        refuse('BASELINE_NOT_ANCESTOR', baseline[:12])
    ranges = [dict(row) for row in doc['ranges'] if isinstance(row, dict) and row.get('id') != 'UNASSIGNED_TAIL']
    if any(row.get('id') == 'UNASSIGNED_TAIL' for row in doc['ranges'] if isinstance(row, dict)):
        refuse('INVENTORY_HAS_UNASSIGNED_COMMITS')
    ranges_doc = {'schema_version': SCHEMA, 'lane': doc['lane'], 'baseline': baseline, 'ranges': ranges}
    if ranges_path is None:
        derived = 'state/r75-release-acceptance-ranges-' + doc['lane'] + '.json'
        if derived in tree(root, head):
            ranges_path = derived  # the curated input travels with the inventory: it must equal what the inventory embeds
    if ranges_path is not None:
        if not RANGES_PATH.fullmatch(ranges_path):
            refuse('RANGES_PATH_INVALID', ranges_path[:80])
        if load_json(committed_bytes(root, head, ranges_path), 'ranges input') != ranges_doc:
            refuse('RANGES_INPUT_DIFFERS_FROM_INVENTORY')
    expected = build_inventory(root, ranges_doc, covered)
    if expected != doc:
        have = {p.get('path'): p for p in doc['paths'] if isinstance(p, dict)}
        want = {p['path']: p for p in expected['paths']}
        missing = sorted(set(want) - set(have))
        if missing:
            refuse('CHANGED_PATH_NOT_IN_INVENTORY', ' '.join(missing[:REPORT_LIMIT]))
        stale = sorted(set(have) - set(want))
        if stale:
            refuse('INVENTORY_PATH_NOT_CHANGED', ' '.join(stale[:REPORT_LIMIT]))
        differing = sorted(p for p in want if have[p] != want[p])
        if differing:
            refuse('INVENTORY_ENTRY_DIFFERS', ' '.join(differing[:REPORT_LIMIT]))
        refuse('INVENTORY_DIFFERS_FROM_GIT')
    bad = [p['path'] for p in expected['paths'] if p['status'] != 'ACCEPTED']
    if bad:
        refuse('UNREVIEWED_PATH', ' '.join(bad[:REPORT_LIMIT]))
    if receipts_root is not None:
        # Local master check only (CI has no access to R): every accepting receipt named by a used range must exist.
        for row in expected['ranges']:
            if row['id'] in expected['ranges_used'] and row['status'] == 'ACCEPTED':
                candidate = receipts_root / row['receipt'][2:]
                if not candidate.is_file():
                    refuse('RECEIPT_MISSING', row['id'])
    inventory_range_path = ranges_path or ('state/r75-release-acceptance-ranges-' + doc['lane'] + '.json')
    tail = check_tail(root, covered, head, inventory_path, inventory_range_path)
    # Content pin: a listed path may differ from its recorded blob at HEAD only when the tail rule allowed that path.
    head_tree = tree(root, head)
    tail_free = {inventory_path, inventory_range_path, *TAIL_FIXED_STATE}
    for p in expected['paths']:
        if p['path'] in tail_free:
            continue
        entry = head_tree.get(p['path'])
        if (entry is None) != (p['change'] == 'D') or (entry is not None and entry[2] != p['blob']):
            refuse('PATH_CHANGED_AFTER_REVIEW', p['path'])
    return {'status': 'PASS', 'lane': doc['lane'], 'baseline': baseline, 'covered_head': covered, 'head': head,
            'paths': len(expected['paths']), 'ranges': len(expected['ranges']), 'tail_commits': tail['tail_commits'],
            'tail_new_receipts': tail['new_receipts'], 'inventory_path': inventory_path, 'inventory_sha256': digest}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    build = sub.add_parser('build', help='write the inventory for --head from the curated ranges input')
    build.add_argument('--project-root', type=Path, required=True)
    build.add_argument('--ranges', required=True, help='repository-relative ranges input (read from the working tree)')
    build.add_argument('--output', required=True, help='repository-relative inventory path to write')
    build.add_argument('--head', default='HEAD')
    verify = sub.add_parser('check', help='refuse unless the committed inventory matches git and the tail rule holds')
    verify.add_argument('--project-root', type=Path, required=True)
    verify.add_argument('--inventory', required=True)
    verify.add_argument('--ranges', default=None)
    verify.add_argument('--head', default='HEAD')
    verify.add_argument('--expect-sha256', default=None)
    verify.add_argument('--receipts-root', type=Path, default=None, help='local directory holding the R/ receipts (master-side existence check)')
    args = parser.parse_args(argv)
    try:
        root = args.project_root.resolve(strict=True)
        if args.mode == 'build':
            if not RANGES_PATH.fullmatch(args.ranges) or not INVENTORY_PATH.fullmatch(args.output):
                refuse('PATH_INVALID')
            doc = load_json((root / args.ranges).read_bytes(), 'ranges input')
            inventory = build_inventory(root, doc, resolve_commit(root, args.head))
            (root / args.output).write_bytes(dump(inventory))
            summary = summarize(inventory)
            print(json.dumps(summary, sort_keys=True))
            return 3 if summary['unreviewed'] else 0
        print(json.dumps(check(root, args.inventory, args.head, args.ranges, args.expect_sha256, args.receipts_root), sort_keys=True))
        return 0
    except ScopeRefused as exc:
        sys.stderr.write(f'R75_RELEASE_SCOPE_REFUSED reason={exc.code}' + (f' detail={exc.detail}' if exc.detail else '') + '\n')
        return 1
    except (OSError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f'R75_RELEASE_SCOPE_REFUSED reason=IO_ERROR detail={type(exc).__name__}\n')
        return 1


if __name__ == '__main__':
    sys.exit(main())
