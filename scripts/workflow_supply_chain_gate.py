#!/usr/bin/env python3
"""Audit GitHub Actions workflows for trusted self-hosted supply-chain rules."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]

USES_RE = re.compile(r"^\s*uses:\s*([^\s#]+)", re.MULTILINE)
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
HOSTED_RUNNER_RE = re.compile(
    r"runs-on:\s*(?:ubuntu|windows|macos)(?:-[A-Za-z0-9.]+)?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
PER_COMMIT_CONCURRENCY_RE = re.compile(
    r"^\s*group:\s*.*github\.sha.*$", re.IGNORECASE | re.MULTILINE
)
UNSAFE_RUN_SCALAR_RE = re.compile(
    r"^\s*run:\s*([&*!])(?:\s|$)", re.IGNORECASE | re.MULTILINE
)
PIP_INSTALL_RE = re.compile(r"\bpip\s+install\b", re.IGNORECASE)
PIP_CHECK_RE = re.compile(r"\bpip\s+check\b", re.IGNORECASE)
NPM_CI_COMMAND_RE = re.compile(
    r"^(?:&\s*)?(?:npm(?:\.cmd)?|\$env:PROJECT_NPM)\s+ci(?:\s|$)",
    re.IGNORECASE,
)
NPM_INSTALL_COMMAND_RE = re.compile(
    r"^(?:&\s*)?(?:npm(?:\.cmd)?|\$env:PROJECT_NPM)\s+install(?:\s|$)",
    re.IGNORECASE,
)
CHECKOUT_V6_SHA = "df4cb1c069e1874edd31b4311f1884172cec0e10"
OFFICIAL_PYPI_INDEX = "https://pypi.org/simple"
REQUIRED_PIP_INSTALL_FRAGMENTS = (
    "--isolated",
    "--disable-pip-version-check",
    "--only-binary=:all:",
    f"--index-url {OFFICIAL_PYPI_INDEX}",
    "--require-hashes",
    "requirements-ci.txt",
)

FORBIDDEN_SELF_MUTATION = (
    "git push",
    "git commit",
    "update-ref",
    "contents: write",
)


def workflow_files(root: Path = ROOT) -> Iterable[Path]:
    directory = root / ".github" / "workflows"
    if not directory.exists():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".yml", ".yaml"}
    )


def _meaningful_lines(text: str) -> Iterable[tuple[int, str]]:
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        yield line_number, line


def _audit_yaml_scalar_hazards(relative: Path, text: str) -> list[str]:
    findings: list[str] = []
    for match in UNSAFE_RUN_SCALAR_RE.finditer(text):
        line_number = text.count("\n", 0, match.start()) + 1
        findings.append(
            f"{relative}:{line_number}: run value begins with YAML indicator "
            f"{match.group(1)!r}; use `run: |` or quote the command"
        )
    return findings


def _audit_action_refs(relative: Path, text: str) -> list[str]:
    findings: list[str] = []
    for match in USES_RE.finditer(text):
        reference = match.group(1)
        line_number = text.count("\n", 0, match.start()) + 1
        if reference.startswith("./"):
            continue
        if "@" not in reference:
            findings.append(
                f"{relative}:{line_number}: third-party action lacks an immutable ref"
            )
            continue
        action, ref = reference.rsplit("@", 1)
        if not FULL_SHA_RE.fullmatch(ref):
            findings.append(
                f"{relative}:{line_number}: action {action!r} is not pinned to a full commit SHA"
            )
            continue
        if action.lower() == "actions/checkout" and ref.lower() != CHECKOUT_V6_SHA:
            findings.append(
                f"{relative}:{line_number}: actions/checkout must use reviewed v6.0.3 SHA"
            )
    return findings


def _audit_runner_and_permissions(relative: Path, text: str) -> list[str]:
    findings: list[str] = []
    for match in HOSTED_RUNNER_RE.finditer(text):
        line_number = text.count("\n", 0, match.start()) + 1
        findings.append(f"{relative}:{line_number}: hosted runner fallback is forbidden")
    for match in PER_COMMIT_CONCURRENCY_RE.finditer(text):
        line_number = text.count("\n", 0, match.start()) + 1
        findings.append(
            f"{relative}:{line_number}: concurrency group must be stable per branch/PR, not per commit SHA"
        )
    lower_text = text.lower()
    if "pull_request_target:" in lower_text:
        findings.append(f"{relative}: pull_request_target is forbidden")
    if re.search(r"(?im)^\s*contents:\s*write\s*$", text):
        findings.append(f"{relative}: contents: write is forbidden in active audit workflows")
    if re.search(r"(?im)^\s*persist-credentials:\s*true\s*$", text):
        findings.append(f"{relative}: checkout credentials must not be persisted")
    return findings


def _audit_install_commands(relative: Path, text: str) -> list[str]:
    findings: list[str] = []
    saw_pip_install = False
    saw_pip_check = False
    for line_number, line in _meaningful_lines(text):
        stripped = line.strip()
        lower = stripped.lower()
        if PIP_INSTALL_RE.search(stripped):
            saw_pip_install = True
            missing = [
                fragment
                for fragment in REQUIRED_PIP_INSTALL_FRAGMENTS
                if fragment.casefold() not in lower
            ]
            if missing:
                findings.append(
                    f"{relative}:{line_number}: pip install is missing required locked-install controls: "
                    + ", ".join(missing)
                )
        if PIP_CHECK_RE.search(stripped):
            saw_pip_check = True
        if NPM_INSTALL_COMMAND_RE.search(stripped):
            findings.append(
                f"{relative}:{line_number}: npm install is forbidden; use the committed lock with npm ci"
            )
        if NPM_CI_COMMAND_RE.search(stripped):
            required = ("--ignore-scripts", "--no-audit", "--no-fund")
            missing = [flag for flag in required if flag not in lower]
            if missing:
                findings.append(
                    f"{relative}:{line_number}: npm ci is missing required flags: {', '.join(missing)}"
                )
    if saw_pip_install and not saw_pip_check:
        findings.append(f"{relative}: every dependency-install workflow must run pip check")
    return findings


def _audit_mutation_and_ref_bypass(relative: Path, text: str) -> list[str]:
    findings: list[str] = []
    for line_number, line in _meaningful_lines(text):
        lower = line.lower()
        for forbidden in FORBIDDEN_SELF_MUTATION:
            if forbidden in lower:
                findings.append(
                    f"{relative}:{line_number}: workflow self-mutation or write permission is forbidden"
                )
        if re.search(
            r"(?i)\bref:\s*(?:feature/|audit/|hardening/|refs/heads/)",
            line,
        ):
            findings.append(
                f"{relative}:{line_number}: checkout must use the event SHA, not a hard-coded branch ref"
            )
    return findings


def _audit_pull_request_guard(relative: Path, text: str) -> list[str]:
    if not re.search(r"(?m)^\s*pull_request:\s*$", text):
        return []
    required_fragments = (
        "github.event.pull_request.head.repo.full_name == github.repository",
        "github.actor == 'always7895'",
    )
    if all(fragment in text for fragment in required_fragments):
        return []
    return [
        f"{relative}: self-hosted pull_request workflow lacks the trusted same-repository/actor guard"
    ]


def audit_workflows(root: Path = ROOT) -> list[str]:
    findings: list[str] = []
    for path in workflow_files(root):
        relative = path.relative_to(root)
        text = path.read_text(encoding="utf-8")
        findings.extend(_audit_yaml_scalar_hazards(relative, text))
        findings.extend(_audit_action_refs(relative, text))
        findings.extend(_audit_runner_and_permissions(relative, text))
        findings.extend(_audit_install_commands(relative, text))
        findings.extend(_audit_mutation_and_ref_bypass(relative, text))
        findings.extend(_audit_pull_request_guard(relative, text))
    return findings


def main() -> int:
    findings = audit_workflows()
    if findings:
        print("WORKFLOW SUPPLY-CHAIN GATE FAILED")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print(
        "WORKFLOW SUPPLY-CHAIN GATE PASSED: valid run scalars, immutable checkout v6, "
        "stable branch/PR concurrency, trusted self-hosted runners, read-only credentials, "
        "isolated binary-only official-index hash locks with pip check, and lifecycle-script-free npm ci"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
