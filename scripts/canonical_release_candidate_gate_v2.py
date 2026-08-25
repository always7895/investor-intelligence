#!/usr/bin/env python3
"""Fail closed unless the current tree is a coherent release candidate.

This gate does not deploy, publish, rewrite Git history, install credentials or
turn on an external integration. It consolidates repository-wide invariants
that otherwise can pass in isolation while the combined tree remains unsafe.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
USES_RE = re.compile(r"^\s*uses:\s*([^\s#]+)", re.MULTILINE)
WRITE_PERMISSION_RE = re.compile(
    r"(?im)^\s*(?:actions|checks|contents|deployments|issues|packages|pages|pull-requests|security-events|statuses):\s*write\s*$"
)
PIP_INSTALL_RE = re.compile(r"\b(?:pip|pip3)\s+install\b|\s-m\s+pip\s+install\b", re.IGNORECASE)
NPM_INSTALL_RE = re.compile(
    r"(?im)^\s*(?:&\s*)?(?:npm(?:\.cmd)?|\$env:PROJECT_NPM)\s+install(?:\s|$)"
)
NPM_CI_RE = re.compile(
    r"(?im)^\s*(?:&\s*)?(?:npm(?:\.cmd)?|\$env:PROJECT_NPM)\s+ci(?:\s|$)"
)

REQUIRED_PATHS = (
    "config/runtime-policy.json",
    "config/release-package-policy.json",
    "config/authoritative-source-catalog.json",
    "scripts/security_check.py",
    "scripts/line_public_boundary_gate.py",
    "scripts/workflow_supply_chain_gate.py",
    "scripts/authoritative_source_catalog.py",
    "scripts/full_history_privacy_scan.py",
    "scripts/release_package.py",
    "scripts/verify_release_package.py",
    "scripts/clean_install_acceptance.py",
    "cloud/package-lock.json",
    "cloud/src/storage.ts",
    "cloud/src/worker.ts",
    "cloud/wrangler.toml",
)


def _read(root: Path, relative: str) -> str:
    return (root / relative).read_text(encoding="utf-8")


def _workflow_files(root: Path) -> Iterable[Path]:
    directory = root / ".github" / "workflows"
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in {".yml", ".yaml"}
        )
    )


def _audit_workflows(root: Path) -> list[str]:
    findings: list[str] = []
    required_pip_flags = (
        "--isolated",
        "--only-binary=:all:",
        "--index-url https://pypi.org/simple",
        "--require-hashes",
        "-r requirements-ci.txt",
    )
    required_npm_flags = ("--ignore-scripts", "--no-audit", "--no-fund")

    for path in _workflow_files(root):
        relative = path.relative_to(root)
        text = path.read_text(encoding="utf-8")
        lower = text.lower()

        if WRITE_PERMISSION_RE.search(text):
            findings.append(f"{relative}: write permission is forbidden in retained validation workflows")
        for forbidden_event in ("pull_request_target:", "issue_comment:", "workflow_run:"):
            if forbidden_event in lower:
                findings.append(f"{relative}: unsafe workflow event {forbidden_event[:-1]} is forbidden")
        for forbidden_mutation in (
            "git push",
            "git commit",
            "gh issue",
            "update_progress_issue.py",
            "persist-credentials: true",
        ):
            if forbidden_mutation in lower:
                findings.append(f"{relative}: validation workflow contains forbidden mutation/credential retention")

        for match in USES_RE.finditer(text):
            reference = match.group(1)
            if reference.startswith("./") or reference.startswith("docker://"):
                continue
            if "@" not in reference or not FULL_SHA_RE.fullmatch(reference.rsplit("@", 1)[-1]):
                findings.append(f"{relative}: third-party action is not pinned to an immutable full SHA")

        pip_lines = [line.strip() for line in text.splitlines() if PIP_INSTALL_RE.search(line)]
        for line in pip_lines:
            normalized = " ".join(line.split()).lower()
            missing = [flag for flag in required_pip_flags if flag not in normalized]
            if missing:
                findings.append(
                    f"{relative}: pip install is missing release-candidate flags: {', '.join(missing)}"
                )
        if pip_lines and not re.search(r"\s-m\s+pip\s+check\b|\bpip(?:3)?\s+check\b", text, re.IGNORECASE):
            findings.append(f"{relative}: pip check is required after an immutable dependency install")

        if NPM_INSTALL_RE.search(text):
            findings.append(f"{relative}: npm install is forbidden; use the committed lock with npm ci")
        for match in NPM_CI_RE.finditer(text):
            line_end = text.find("\n", match.start())
            line = text[match.start() : line_end if line_end >= 0 else len(text)].lower()
            missing = [flag for flag in required_npm_flags if flag not in line]
            if missing:
                findings.append(f"{relative}: npm ci is missing required flags: {', '.join(missing)}")
    return findings


def _builder_dependency_findings(builder: str) -> list[str]:
    """Detect executable owner/broker dependencies without flagging safety docs.

    Raw substring bans caused false positives when the public builder documented
    names that it explicitly refuses to read. Inspect the Python AST instead so
    imports, variable references and file-path arguments remain fail-closed while
    comments/docstrings/denylist markers are allowed.
    """
    findings: list[str] = []
    try:
        tree = ast.parse(builder)
    except SyntaxError:
        return ["scripts/build_line_public_options.py: Python source could not be parsed"]

    forbidden_modules = {"fetch_options_ibkr", "options_service"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_name = alias.name.split(".", 1)[0]
                if root_name in forbidden_modules:
                    findings.append(
                        f"scripts/build_line_public_options.py: forbidden owner/broker import {root_name}"
                    )
        elif isinstance(node, ast.ImportFrom):
            root_name = str(node.module or "").split(".", 1)[0]
            if root_name in forbidden_modules:
                findings.append(
                    f"scripts/build_line_public_options.py: forbidden owner/broker import {root_name}"
                )
        elif isinstance(node, ast.Name) and node.id == "PORTFOLIO_JSON":
            findings.append(
                "scripts/build_line_public_options.py: forbidden owner/broker variable PORTFOLIO_JSON"
            )
        elif isinstance(node, ast.Call):
            for argument in (*node.args, *(keyword.value for keyword in node.keywords)):
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    if "portfolio.local.json" in argument.value.casefold():
                        findings.append(
                            "scripts/build_line_public_options.py: forbidden owner portfolio path access"
                        )
    return sorted(set(findings))


def _audit_line_and_storage_boundary(root: Path) -> list[str]:
    findings: list[str] = []
    storage = _read(root, "cloud/src/storage.ts")
    worker = _read(root, "cloud/src/worker.ts")
    wrangler = _read(root, "cloud/wrangler.toml")
    builder = _read(root, "scripts/build_line_public_options.py")

    for binding in ("PUBLIC_CACHE", "TENANT_PRIVATE_CACHE", "EPHEMERAL_SECURITY_CACHE"):
        if binding not in storage:
            findings.append(f"cloud/src/storage.ts: missing isolated {binding} binding")
        if f'binding = "{binding}"' not in wrangler:
            findings.append(f"cloud/wrangler.toml: missing isolated {binding} namespace")
    if 'binding = "CACHE"' in wrangler:
        findings.append("cloud/wrangler.toml: legacy shared CACHE binding is forbidden")

    if "/internal/private-sync" in worker:
        findings.append("cloud/src/worker.ts: private synchronization route must remain absent")
    if (root / "cloud" / "src" / "internal.ts").exists():
        findings.append("cloud/src/internal.ts: private synchronization implementation must remain absent")
    if (root / "scripts" / "sync_private_to_worker.py").exists():
        findings.append("scripts/sync_private_to_worker.py: private synchronization client must remain absent")

    findings.extend(_builder_dependency_findings(builder))

    runtime = json.loads(_read(root, "config/runtime-policy.json"))
    privacy = runtime.get("privacy") if isinstance(runtime, dict) else None
    line = runtime.get("line") if isinstance(runtime, dict) else None
    local_broker = runtime.get("local_broker_runtime") if isinstance(runtime, dict) else None
    required_false = {
        "privacy.owner_data_available_to_line": (privacy or {}).get("owner_data_available_to_line"),
        "privacy.owner_watchlist_inherited_by_line": (privacy or {}).get("owner_watchlist_inherited_by_line"),
        "privacy.portfolio_available_to_line": (privacy or {}).get("portfolio_available_to_line"),
        "privacy.broker_account_available_to_line": (privacy or {}).get("broker_account_available_to_line"),
        "privacy.private_sync_available_to_line": (privacy or {}).get("private_sync_available_to_line"),
        "line.ibkr_bridge": (line or {}).get("ibkr_bridge"),
        "line.brokerage_connection": (line or {}).get("brokerage_connection"),
        "line.portfolio_tools": (line or {}).get("portfolio_tools"),
        "line.private_sync_route": (line or {}).get("private_sync_route"),
        "local_broker.line_or_worker_may_call_ibkr": (local_broker or {}).get("line_or_worker_may_call_ibkr"),
        "local_broker.ibkr_output_may_enter_public_kv": (local_broker or {}).get("ibkr_output_may_enter_public_kv"),
        "local_broker.ibkr_output_may_enter_line_model_context": (local_broker or {}).get("ibkr_output_may_enter_line_model_context"),
    }
    for label, value in required_false.items():
        if value is not False:
            findings.append(f"config/runtime-policy.json: {label} must be false")
    return findings


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _audit_source_catalog(root: Path) -> list[str]:
    findings: list[str] = []
    try:
        module = _load_module(root / "scripts" / "authoritative_source_catalog.py", "rc_source_catalog")
        manifest, sources, _warnings = module.load_catalog(
            root / "config" / "authoritative-source-catalog.json"
        )
    except Exception as exc:  # pragma: no cover - failure is reported, not hidden
        return [f"authoritative source catalog could not be loaded: {type(exc).__name__}"]

    if len(sources) < 99:
        findings.append(f"authoritative source catalog unexpectedly shrank to {len(sources)} entries")
    if not (manifest.get("catalog_policy") or {}).get("no_fixed_source_count_limit"):
        findings.append("authoritative source catalog regained a fixed source-count limit")
    enabled = [source.id for source in sources if source.runtime_enabled is True]
    if enabled:
        findings.append(
            "runtime sources were enabled before explicit release admission: "
            + ", ".join(map(str, enabled))
        )
    return findings


def _audit_release_fail_closed(root: Path) -> list[str]:
    findings: list[str] = []
    package_json = json.loads(_read(root, "cloud/package.json"))
    scripts = package_json.get("scripts") if isinstance(package_json, dict) else None
    if isinstance(scripts, dict) and "deploy" in scripts:
        findings.append("cloud/package.json: deploy script is forbidden before final release approval")

    status_documents = list((root / "config").glob("*release*status*.json")) + list(
        (root / "state").glob("*release*status*.json") if (root / "state").is_dir() else []
    )
    for path in status_documents:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(f"{path.relative_to(root)}: unreadable release status ({type(exc).__name__})")
            continue
        for key in ("release_ready", "deployed", "billing_enabled"):
            if key in document and document[key] is not False:
                findings.append(f"{path.relative_to(root)}: {key} must remain false")
    return findings


def audit_repository(root: Path = ROOT) -> list[str]:
    findings: list[str] = []
    for relative in REQUIRED_PATHS:
        if not (root / relative).is_file():
            findings.append(f"missing required release-candidate path: {relative}")
    if findings:
        return findings

    findings.extend(_audit_workflows(root))
    findings.extend(_audit_line_and_storage_boundary(root))
    findings.extend(_audit_source_catalog(root))
    findings.extend(_audit_release_fail_closed(root))
    return sorted(set(findings))


def main() -> int:
    findings = audit_repository()
    if findings:
        print("CANONICAL RELEASE CANDIDATE GATE FAILED")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print(
        "CANONICAL RELEASE CANDIDATE GATE PASSED: immutable read-only workflows, "
        "isolated public/private/security KV, public-only LINE, disabled broker bridge, "
        "unbounded-but-runtime-disabled authoritative catalog and fail-closed release state"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
