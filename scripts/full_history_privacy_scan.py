#!/usr/bin/env python3
"""Content-free privacy and credential inventory for candidate Git history.

The scanner reads Git objects without checking out historical trees. ``head``
scans only ancestry reachable from the exact candidate HEAD. ``all`` scans every
ref plus otherwise available Git objects, so the final manual gate can detect
orphaned sensitive objects as well. It never prints matched content, e-mail
addresses or repository paths. Findings contain only a stable code, object SHA
prefix, one-way locator hash and optional line number.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Sequence

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from security_check import (  # noqa: E402
    FORBIDDEN_TRACKED_PATHS,
    PATTERNS,
    value_is_allowed,
)

MAX_BLOB_BYTES = 2 * 1024 * 1024
MAX_FINDINGS_IN_REPORT = 500
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
EMAIL_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]{1,64})@([A-Za-z0-9.-]+\.[A-Za-z]{2,63})(?![A-Za-z0-9.-])"
)
ALLOWED_EMAIL_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "example.test",
    "users.noreply.github.com",
    "noreply.github.com",
}
HISTORIC_PRIVATE_PATHS = {
    *(path.as_posix() for path in FORBIDDEN_TRACKED_PATHS),
    "config/watchlist.json",
    "config/user-preferences.json",
}
SENSITIVE_PATH_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "secrets.json",
}
SENSITIVE_PATH_SUFFIXES = (
    ".pem",
    ".key",
    ".pfx",
    ".p12",
    ".kdbx",
)
LABEL_CODES = dict(
    [
        ("private key", "PRIVATE_KEY_MATERIAL"),
        ("GitHub " + "token", "GITHUB_" + "TOKEN"),
        ("AWS access key", "AWS_ACCESS_KEY"),
        ("bearer credential", "BEARER_CREDENTIAL"),
        ("assigned sensitive value", "ASSIGNED_SENSITIVE_VALUE"),
        ("raw LINE user identifier", "RAW_LINE_USER_IDENTIFIER"),
        ("user-specific Windows profile path", "USER_SPECIFIC_WINDOWS_PATH"),
    ]
)


class HistoryScanError(RuntimeError):
    """Raised when Git history cannot be scanned completely."""


@dataclass(frozen=True, order=True)
class Finding:
    code: str
    object_prefix: str
    locator_hash: str
    line: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ObjectEntry:
    sha: str
    path: str | None


def _git(
    root: Path,
    *arguments: str,
    input_bytes: bytes | None = None,
) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HistoryScanError(f"Git command could not run: {' '.join(arguments)}") from exc
    if completed.returncode != 0:
        stderr_hash = hashlib.sha256(completed.stderr).hexdigest()[:20]
        raise HistoryScanError(
            f"Git command failed without exposing stderr; code={completed.returncode}; error_hash={stderr_hash}"
        )
    return completed.stdout


def _locator_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()[:24]


def _object_prefix(sha: str) -> str:
    return sha[:16] if FULL_SHA_RE.fullmatch(sha) else "invalid-object"


def _line_number(text: str, start: int) -> int:
    return text.count("\n", 0, start) + 1


def _email_allowed(domain: str) -> bool:
    normalized = domain.rstrip(".").casefold()
    return (
        normalized in ALLOWED_EMAIL_DOMAINS
        or normalized.endswith(".example")
        or normalized.endswith(".invalid")
    )


def _email_findings(text: str, *, sha: str, locator: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in EMAIL_RE.finditer(text):
        if _email_allowed(match.group(2)):
            continue
        findings.append(
            Finding(
                code="DIRECT_EMAIL_IDENTIFIER",
                object_prefix=_object_prefix(sha),
                locator_hash=_locator_hash(locator),
                line=_line_number(text, match.start()),
            )
        )
    return findings


def _pattern_findings(text: str, *, sha: str, locator: str) -> list[Finding]:
    findings: list[Finding] = []
    for label, pattern, has_value in PATTERNS:
        code = LABEL_CODES.get(label, "LIKELY_SENSITIVE_VALUE")
        for match in pattern.finditer(text):
            if has_value and value_is_allowed(match):
                continue
            findings.append(
                Finding(
                    code=code,
                    object_prefix=_object_prefix(sha),
                    locator_hash=_locator_hash(locator),
                    line=_line_number(text, match.start()),
                )
            )
    findings.extend(_email_findings(text, sha=sha, locator=locator))
    return findings


def _normalize_history_path(path: str) -> str:
    normalized = PurePosixPath(path).as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _path_findings(path: str, sha: str) -> list[Finding]:
    # Never use str.lstrip("./") here: it turns `.env` into `env` and silently
    # defeats the sensitive-dotfile gate.
    normalized = _normalize_history_path(path)
    name = PurePosixPath(normalized).name.casefold()
    findings: list[Finding] = []
    if normalized in HISTORIC_PRIVATE_PATHS:
        findings.append(
            Finding(
                code="HISTORIC_OWNER_OR_PRIVATE_PATH",
                object_prefix=_object_prefix(sha),
                locator_hash=_locator_hash(normalized),
            )
        )
    if name in SENSITIVE_PATH_NAMES or normalized.casefold().endswith(SENSITIVE_PATH_SUFFIXES):
        findings.append(
            Finding(
                code="HISTORIC_SENSITIVE_FILENAME",
                object_prefix=_object_prefix(sha),
                locator_hash=_locator_hash(normalized),
            )
        )
    return findings


def _revision_entries(root: Path, revision: str) -> list[ObjectEntry]:
    output = _git(root, "-c", "core.quotePath=false", "rev-list", "--objects", revision)
    entries: list[ObjectEntry] = []
    seen: set[tuple[str, str | None]] = set()
    for raw_line in output.decode("utf-8", errors="surrogateescape").splitlines():
        if not raw_line:
            continue
        sha, separator, path = raw_line.partition(" ")
        sha = sha.casefold()
        entry_path = path if separator else None
        identity = (sha, entry_path)
        if not FULL_SHA_RE.fullmatch(sha) or identity in seen:
            continue
        seen.add(identity)
        entries.append(ObjectEntry(sha=sha, path=entry_path))
    return entries


def reachable_objects(root: Path, scope: str) -> tuple[list[ObjectEntry], str]:
    if scope == "head":
        entries = _revision_entries(root, "HEAD")
    elif scope == "all":
        entries = _revision_entries(root, "--all")
        known_shas = {entry.sha for entry in entries}
        all_objects = _git(
            root,
            "cat-file",
            "--batch-all-objects",
            "--batch-check=%(objectname)",
        )
        for raw_line in all_objects.decode("ascii", errors="ignore").splitlines():
            sha = raw_line.strip().casefold()
            if FULL_SHA_RE.fullmatch(sha) and sha not in known_shas:
                known_shas.add(sha)
                entries.append(ObjectEntry(sha=sha, path=None))
    else:
        raise HistoryScanError("History scope must be head or all")

    if not entries:
        raise HistoryScanError("No Git objects were found for requested scope")
    head = _git(root, "rev-parse", "HEAD").decode("ascii", errors="strict").strip().casefold()
    if not FULL_SHA_RE.fullmatch(head):
        raise HistoryScanError("HEAD is not a full commit SHA")
    return entries, head


def cat_objects(
    root: Path,
    entries: Sequence[ObjectEntry],
) -> Iterator[tuple[ObjectEntry, str, int, bytes]]:
    try:
        process = subprocess.Popen(
            ["git", "-C", str(root), "cat-file", "--batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise HistoryScanError("Unable to start git cat-file --batch") from exc
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    try:
        for entry in entries:
            process.stdin.write((entry.sha + "\n").encode("ascii"))
            process.stdin.flush()
            header = process.stdout.readline()
            if not header:
                raise HistoryScanError("git cat-file ended before every object was read")
            fields = header.decode("ascii", errors="replace").strip().split()
            if len(fields) == 2 and fields[1] == "missing":
                raise HistoryScanError("A requested Git object is missing")
            if len(fields) != 3 or fields[0].casefold() != entry.sha:
                raise HistoryScanError("git cat-file returned an invalid object header")
            object_type = fields[1]
            try:
                size = int(fields[2])
            except ValueError as exc:
                raise HistoryScanError("git cat-file returned an invalid object size") from exc
            if size < 0:
                raise HistoryScanError("git cat-file returned a negative object size")
            data = process.stdout.read(size)
            separator = process.stdout.read(1)
            if len(data) != size or separator != b"\n":
                raise HistoryScanError("git cat-file returned a truncated object")
            yield entry, object_type, size, data
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        timed_out = False
        try:
            return_code = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            process.wait(timeout=10)
            return_code = process.returncode
        finally:
            try:
                process.stdout.close()
            except OSError:
                pass
            try:
                process.stderr.close()
            except OSError:
                pass
        if timed_out:
            raise HistoryScanError("git cat-file did not terminate")
        if return_code != 0:
            raise HistoryScanError(f"git cat-file failed with exit {return_code}")


def _commit_findings(data: bytes, sha: str) -> list[Finding]:
    text = data.decode("utf-8", errors="ignore")
    headers, separator, message = text.partition("\n\n")
    findings = _pattern_findings(
        message if separator else "",
        sha=sha,
        locator=f"commit-message:{sha}",
    )
    identities_seen: set[str] = set()
    for line in headers.splitlines():
        if not (line.startswith("author ") or line.startswith("committer ")):
            continue
        match = re.search(r"<([^<>\s]+@[^<>\s]+)>", line)
        if not match:
            continue
        identity = match.group(1).casefold()
        domain = identity.rsplit("@", 1)[-1]
        if _email_allowed(domain) or identity in identities_seen:
            continue
        identities_seen.add(identity)
        findings.append(
            Finding(
                code=(
                    "NON_NOREPLY_AUTHOR_EMAIL"
                    if line.startswith("author ")
                    else "NON_NOREPLY_COMMITTER_EMAIL"
                ),
                object_prefix=_object_prefix(sha),
                locator_hash=_locator_hash(identity),
            )
        )
    return findings


def scan_history(root: Path = ROOT, *, scope: str = "head") -> dict[str, Any]:
    if scope not in {"head", "all"}:
        raise HistoryScanError("History scope must be head or all")
    entries, head = reachable_objects(root, scope)
    findings: set[Finding] = set()
    object_counts: Counter[str] = Counter()
    bytes_scanned = 0
    oversized_objects = 0
    content_scanned: set[tuple[str, str]] = set()

    for entry, object_type, size, data in cat_objects(root, entries):
        if entry.path and object_type == "blob":
            findings.update(_path_findings(entry.path, entry.sha))

        content_identity = (entry.sha, object_type)
        if content_identity in content_scanned:
            continue
        content_scanned.add(content_identity)
        object_counts[object_type] += 1

        if object_type == "blob":
            locator = entry.path or f"blob:{entry.sha}"
            if size > MAX_BLOB_BYTES:
                oversized_objects += 1
                findings.add(
                    Finding(
                        code="OVERSIZED_BLOB_REVIEW_REQUIRED",
                        object_prefix=_object_prefix(entry.sha),
                        locator_hash=_locator_hash(locator),
                    )
                )
                continue
            bytes_scanned += size
            text = data.decode("utf-8", errors="ignore")
            findings.update(_pattern_findings(text, sha=entry.sha, locator=locator))
        elif object_type in {"commit", "tag"}:
            bytes_scanned += size
            findings.update(_commit_findings(data, entry.sha))

    ordered = sorted(findings)
    counts = Counter(finding.code for finding in ordered)
    report_findings = [value.as_dict() for value in ordered[:MAX_FINDINGS_IN_REPORT]]
    return {
        "schema_version": 1,
        "scope": "candidate_ancestry" if scope == "head" else "available_objects",
        "audited_head": head,
        "object_counts": dict(sorted(object_counts.items())),
        "bytes_scanned": bytes_scanned,
        "oversized_object_count": oversized_objects,
        "finding_count": len(ordered),
        "finding_counts": dict(sorted(counts.items())),
        "findings_truncated": len(ordered) > MAX_FINDINGS_IN_REPORT,
        "findings": report_findings,
        "clean": not ordered,
        "remediation_required": bool(ordered),
        "matched_content_in_report": False,
        "raw_paths_in_report": False,
        "raw_email_addresses_in_report": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("head", "all"), default="head")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()
    try:
        report = scan_history(ROOT, scope=args.scope)
        encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.json_output is not None:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(encoded, encoding="utf-8")
    except (HistoryScanError, OSError, UnicodeError, ValueError) as exc:
        error_hash = hashlib.sha256(str(exc).encode("utf-8")).hexdigest()[:20]
        print(f"FULL HISTORY PRIVACY SCAN ERROR: error_hash={error_hash}")
        return 2

    summary = {key: value for key, value in report.items() if key != "findings"}
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    for finding in report["findings"]:
        print(json.dumps(finding, ensure_ascii=False, sort_keys=True))
    if args.require_clean and not report["clean"]:
        print("FULL HISTORY PRIVACY SCAN: REMEDIATION REQUIRED")
        return 1
    print(
        "FULL HISTORY PRIVACY SCAN COMPLETED: "
        + ("clean" if report["clean"] else "content-free findings recorded; remediation pending")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
