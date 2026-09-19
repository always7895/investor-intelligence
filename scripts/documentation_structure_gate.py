#!/usr/bin/env python3
"""Offline Markdown inventory, local file-link and entrypoint-budget checks.

No dependency installation, HTTP, runtime traversal or generated-data discovery.
Checks inline/reference-style Markdown file links, not external URLs, anchors,
HTML or factual/semantic accuracy. Historical evidence is not edited by this gate.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
INDEX = "docs/README.md"
BUDGETS = {"AGENTS.md": 6000, "skills/serenity-public-research/SKILL.md": 4000,
           "state/STATUS.md": 12000, "README.md": 9000, "README.zh-TW.md": 5000}
EXCLUDED = {"_workspace", "_archive", ".git", "node_modules"}
INLINE = re.compile(r'!?\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^\s)]+)(?:\s+"[^"\n]*")?\s*\)')
REFERENCE = re.compile(r'^ {0,3}\[[^\]\n]+\]:\s*(<[^>\n]+>|\S+)', re.M)


def prose(text: str) -> str:
    lines = []
    fence = None
    for line in text.splitlines():
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            continue
        if match:
            fence = match[1]
            continue
        lines.append(re.sub(r'(`+).*?\1', '', line))
    return '\n'.join(lines)


def link_targets(text: str) -> list[str]:
    text = prose(text)
    return [m[1].strip('<>') for pattern in (INLINE, REFERENCE) for m in pattern.finditer(text)]


def local_target(root: Path, source: str, target: str) -> Path | None:
    if target.startswith(('#', '//')):
        return None
    url = urlsplit(target)
    if url.scheme:
        if url.scheme not in {'http', 'https', 'mailto'}:
            raise ValueError('unsupported link scheme')
        return None
    name = unquote(url.path)
    if not name:
        return None
    if '\\' in name:
        raise ValueError('backslash in file link')
    path = (root / name.lstrip('/') if name.startswith('/') else root / Path(source).parent / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('file link escapes repository')
    if any(part in EXCLUDED for part in path.relative_to(root.resolve()).parts):
        raise ValueError('file link enters excluded workspace')
    return path


def markdown_paths(root: Path) -> list[str]:
    # Git performs the inventory; do not rglob a mixed installed workspace.
    # Include new, nonignored Markdown so pre-commit checks cannot miss new docs.
    output = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--cached',
                                     '--others', '--exclude-standard', '-z', '--', '*.md'],
                                    stderr=subprocess.DEVNULL)
    paths = sorted({p.decode('utf-8') for p in output.split(b'\0') if p})
    if not paths:
        raise ValueError('Markdown inventory is empty')
    return paths


def audit(root: Path = ROOT) -> tuple[list[str], dict[str, int]]:
    findings = []
    documents = {}
    sizes = {}
    for name in markdown_paths(root):
        path = root / name
        if any(part in EXCLUDED for part in Path(name).parts) or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            findings.append(f'{name}: unsafe document path')
            continue
        try:
            raw = path.read_bytes()
            documents[name] = raw.decode('utf-8-sig')
            sizes[name] = len(raw)
        except (OSError, UnicodeError):
            findings.append(f'{name}: missing/unreadable UTF-8 document')
    for name, maximum in BUDGETS.items():
        if name not in documents:
            findings.append(f'{name}: required entrypoint missing')
        elif sizes[name] > maximum:
            findings.append(f'{name}: {sizes[name]} bytes exceeds {maximum}')
    indexed = {INDEX}
    for name, text in documents.items():
        if not text.strip():
            findings.append(f'{name}: empty document')
        for target in link_targets(text):
            try:
                path = local_target(root, name, target)
                if path is None:
                    continue
                if not path.exists():
                    findings.append(f'{name}: missing local file link {target}')
                if name == INDEX:
                    indexed.add(path.relative_to(root.resolve()).as_posix())
            except ValueError:
                # Do not echo credential-bearing or otherwise invalid URLs.
                findings.append(f'{name}: unsafe/malformed link')
    if INDEX not in documents:
        findings.append(f'{INDEX}: documentation index missing')
    for name in sorted(set(documents) - indexed):
        findings.append(f'{name}: not linked from {INDEX}')
    return findings, {'markdown_files': len(documents), 'markdown_bytes': sum(sizes.values())}


def main() -> int:
    try:
        findings, stats = audit()
    except (OSError, ValueError, subprocess.CalledProcessError):
        print('DOCUMENTATION STRUCTURE FAILED: Git inventory unavailable')
        return 1
    print(f"DOCUMENTATION STRUCTURE: {stats['markdown_files']} Markdown files / {stats['markdown_bytes']} bytes")
    for finding in findings:
        print(f'- {finding}')
    print('DOCUMENTATION STRUCTURE ' + ('FAILED' if findings else 'PASSED (offline file targets; not semantic certification)'))
    return int(bool(findings))


if __name__ == '__main__':
    raise SystemExit(main())
