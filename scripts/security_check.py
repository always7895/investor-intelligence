#!/usr/bin/env python3
"""Fail when likely credentials or direct user identifiers are tracked.

This is a conservative current-tree scanner, not a substitute for GitHub secret
scanning, tenant-isolation tests or a one-time Git-history review.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_SIZE = 2 * 1024 * 1024
SKIP_PARTS = {
    ".git",
    ".venv",
    "venv",
    "_work",
    "_diag",
    "data",
    "reports",
}

# Assemble sensitive names so the scanner does not match its own source text.
SENSITIVE_NAME = (
    "(?:to" + "ken|se" + "cret|pass" + "word|api[_-]?key|client[_-]?secret|"
    "access[_-]?token|channel[_-]?secret|channel[_-]?access[_-]?token|app[_-]?password)"
)

PATTERNS: list[tuple[str, re.Pattern[str], bool]] = [
    (
        "private key",
        re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        False,
    ),
    (
        "GitHub token",
        re.compile(r"\bgh" + r"[pousr]_[A-Za-z0-9_]{30,}\b"),
        False,
    ),
    (
        "AWS access key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        False,
    ),
    (
        "bearer credential",
        re.compile(r"Bearer\s+[A-Za-z0-9+/_.=-]{32,}", re.IGNORECASE),
        False,
    ),
    (
        "assigned sensitive value",
        # '=' accepts quoted or unquoted assignments. ':' is accepted only for
        # quoted mapping values so TypeScript/Python annotations such as
        # `secret: string` are never confused with credentials. Two capture
        # groups represent the two forms; value_is_allowed selects the one used.
        re.compile(
            rf"(?i)\b{SENSITIVE_NAME}\b[ \t]*[\"']?[ \t]*(?:"
            rf"=[ \t]*[\"']?([^\"'\r\n]{{12,}})[\"']?"
            rf"|:[ \t]*[\"']([^\"'\r\n]{{12,}})[\"'])"
        ),
        True,
    ),
    (
        "raw LINE user identifier",
        re.compile(r"\bU[0-9a-fA-F]{32}\b"),
        False,
    ),
    (
        "user-specific Windows profile path",
        re.compile(
            r"(?i)C:\\Users\\(?!Public(?:\\|$)|Default(?: User)?(?:\\|$)|All Users(?:\\|$)|\*(?:\\|$)|<[^>]+>\\|%USERNAME%\\)[^\\\s\"']+\\"
        ),
        False,
    ),
]

# Only unmistakable placeholders and narrowly defined runtime retrieval forms
# are exempted. A generic function-call exemption would hide literal secrets
# passed as arguments, so each dynamic form below is intentionally specific.
ALLOWED_VALUE_PATTERNS = [
    re.compile(r"^(?:YOUR_|REPLACE_|EXAMPLE_|TEST_|SYNTHETIC_|FAKE_|DUMMY_|CHANGEME)", re.IGNORECASE),
    re.compile(r"^\$\{[A-Z][A-Z0-9_]+\}$"),
    re.compile(r"^(?:os\.)?getenv\($", re.IGNORECASE),
    re.compile(r"^os\.environ\.get\($", re.IGNORECASE),
    re.compile(r"^required_secret\($", re.IGNORECASE),
    re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.get\($"),
    re.compile(r"^env\.", re.IGNORECASE),
    re.compile(r"^\[string\]\(Get-PropertyValue\b", re.IGNORECASE),
    re.compile(r"^String\(body\.token\b"),
    re.compile(r"^crypto\.randomUUID\(\)"),
    re.compile(r"^Random-Secret\b", re.IGNORECASE),
    re.compile(r"^str\(os\.getenv\(", re.IGNORECASE),
    re.compile(r"^<redacted>", re.IGNORECASE),
]

FORBIDDEN_TRACKED_PATHS = {
    Path("config/delivery.json"),
    Path("config/portfolio.local.json"),
    Path("config/users.local.json"),
    Path("config/tenants.local.json"),
    Path("config/line_user_id.txt"),
    Path("line_user_id.txt"),
}


def tracked_files() -> list[Path]:
    try:
        output = subprocess.check_output(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            stderr=subprocess.DEVNULL,
        )
        return [ROOT / entry.decode("utf-8") for entry in output.split(b"\0") if entry]
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError):
        files: list[Path] = []
        for path in ROOT.rglob("*"):
            if path.is_file() and not any(part in SKIP_PARTS for part in path.parts):
                files.append(path)
        return files


def is_probably_text(path: Path) -> bool:
    try:
        if path.stat().st_size > MAX_FILE_SIZE:
            return False
        sample = path.read_bytes()[:4096]
    except OSError:
        return False
    return b"\0" not in sample


def value_is_allowed(match: re.Match[str]) -> bool:
    if match.lastindex is None:
        return False
    captures = [value for value in match.groups() if value is not None]
    if not captures:
        return False
    value = captures[-1].strip()
    return not value or any(pattern.match(value) for pattern in ALLOWED_VALUE_PATTERNS)


def scan_text(relative: Path, text: str) -> list[str]:
    """Scan one decoded tracked file and return stable, content-free findings."""
    findings: list[str] = []
    for label, pattern, has_value in PATTERNS:
        for match in pattern.finditer(text):
            if has_value and value_is_allowed(match):
                continue
            line_number = text.count("\n", 0, match.start()) + 1
            findings.append(f"{relative}:{line_number}: possible {label}")
    return findings


def scan_repository(files: Iterable[Path] | None = None) -> list[str]:
    findings: list[str] = []
    for path in files if files is not None else tracked_files():
        try:
            relative = path.relative_to(ROOT)
        except ValueError:
            continue

        if relative in FORBIDDEN_TRACKED_PATHS:
            findings.append(f"{relative}: forbidden tenant/private file is tracked")
            continue
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        if not is_probably_text(path):
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        findings.extend(scan_text(relative, text))
    return findings


def main() -> int:
    findings = scan_repository()
    if findings:
        print("SECURITY CHECK FAILED")
        for finding in findings:
            print(f"- {finding}")
        print("Remove current-tree private data and rotate any exposed credential.")
        return 1

    print("SECURITY CHECK PASSED: no likely current-tree credentials or direct user identifiers detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
