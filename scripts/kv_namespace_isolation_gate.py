#!/usr/bin/env python3
"""Enforce physical separation of public, tenant-private and security KV state."""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "kv-namespace-policy.json"
WRANGLER_PATH = ROOT / "cloud" / "wrangler.toml"

EXPECTED_BINDINGS = {
    "PUBLIC_CACHE",
    "TENANT_PRIVATE_CACHE",
    "EPHEMERAL_SECURITY_CACHE",
}


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _policy() -> dict[str, Any]:
    value = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("kv-namespace-policy.json must be an object")
    return value


def audit_kv_isolation(root: Path = ROOT) -> list[str]:
    findings: list[str] = []
    policy_path = root / "config" / "kv-namespace-policy.json"
    wrangler_path = root / "cloud" / "wrangler.toml"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    wrangler = tomllib.loads(wrangler_path.read_text(encoding="utf-8"))

    expected_policy = {
        "same_namespace_id_forbidden": True,
        "legacy_cache_binding_forbidden": True,
        "public_namespace_allows_tenant_keys": False,
        "tenant_private_namespace_allows_public_snapshots": False,
        "ephemeral_namespace_allows_message_text": False,
        "ephemeral_namespace_allows_raw_line_ids": False,
        "memory_feature_default": False,
        "generic_private_json_api_allowed": False,
        "public_publisher_target": "PUBLIC_CACHE",
        "release_requires_cross_namespace_tests": True,
    }
    for key, expected in expected_policy.items():
        if policy.get(key) != expected:
            findings.append(f"config/kv-namespace-policy.json: {key} must be {expected!r}")

    bindings = policy.get("bindings")
    if not isinstance(bindings, dict) or set(bindings.values()) != EXPECTED_BINDINGS:
        findings.append("config/kv-namespace-policy.json: bindings must declare exactly three namespaces")

    namespaces = wrangler.get("kv_namespaces")
    if not isinstance(namespaces, list):
        namespaces = []
    actual_bindings = {
        str(value.get("binding") or "")
        for value in namespaces
        if isinstance(value, dict)
    }
    if actual_bindings != EXPECTED_BINDINGS:
        findings.append(
            "cloud/wrangler.toml: KV bindings must be exactly "
            + ", ".join(sorted(EXPECTED_BINDINGS))
        )
    if len(namespaces) != 3:
        findings.append("cloud/wrangler.toml: exactly three KV namespaces are required")

    ids: list[str] = []
    preview_ids: list[str] = []
    for value in namespaces:
        if not isinstance(value, dict):
            continue
        binding = str(value.get("binding") or "")
        namespace_id = str(value.get("id") or "")
        preview_id = str(value.get("preview_id") or "")
        if not namespace_id or not preview_id:
            findings.append(f"cloud/wrangler.toml: {binding} requires id and preview_id")
        ids.append(namespace_id)
        preview_ids.append(preview_id)
    if len(ids) != len(set(ids)):
        findings.append("cloud/wrangler.toml: production namespace IDs must be distinct")
    if len(preview_ids) != len(set(preview_ids)):
        findings.append("cloud/wrangler.toml: preview namespace IDs must be distinct")

    variables = wrangler.get("vars") if isinstance(wrangler.get("vars"), dict) else {}
    if str(variables.get("MEMORY_FEATURE_AVAILABLE") or "").casefold() != "false":
        findings.append("cloud/wrangler.toml: MEMORY_FEATURE_AVAILABLE must default to false")

    storage = (root / "cloud" / "src" / "storage.ts").read_text(encoding="utf-8")
    line = (root / "cloud" / "src" / "line.ts").read_text(encoding="utf-8")
    worker = (root / "cloud" / "src" / "worker.ts").read_text(encoding="utf-8")

    for marker in (
        "PUBLIC_CACHE",
        "TENANT_PRIVATE_CACHE",
        "EPHEMERAL_SECURITY_CACHE",
        "memoryFeatureAvailable",
        "tenantWriteEpoch",
        "tenant-delete-epoch:",
        "rotateTenantWriteEpoch",
    ):
        if marker not in storage:
            findings.append(f"cloud/src/storage.ts: missing {marker}")
    if "EPHEMERAL_SECURITY_CACHE" not in line:
        findings.append("cloud/src/line.ts: missing EPHEMERAL_SECURITY_CACHE")
    for marker in ("tenantWriteEpoch", "operationEpoch"):
        if marker not in worker:
            findings.append(f"cloud/src/worker.ts: missing deletion-race marker {marker}")

    for relative, text in (
        ("cloud/src/storage.ts", storage),
        ("cloud/src/line.ts", line),
        ("cloud/src/worker.ts", worker),
    ):
        if re.search(r"\bCACHE\s*:\s*KVNamespace", text):
            findings.append(f"{relative}: legacy CACHE binding is forbidden")
        if "env.CACHE" in text:
            findings.append(f"{relative}: env.CACHE is forbidden")

    if "privateJson" in storage or "putPrivateJson" in storage:
        findings.append("cloud/src/storage.ts: generic private JSON APIs are forbidden")
    if "TENANT_PRIVATE_CACHE.get" in storage and "publicJson" in storage:
        public_section = storage.split("export async function publicJson", 1)[1].split(
            "function tenantEpochKey", 1
        )[0]
        if "TENANT_PRIVATE_CACHE" in public_section:
            findings.append("cloud/src/storage.ts: public read path touches tenant-private KV")
    if "PUBLIC_CACHE" in line:
        findings.append("cloud/src/line.ts: dedupe/rate-limit code must not touch public KV")

    # The retained v2 storage blob stays frozen. Audit the current report reader
    # separately; older source-package fixtures may predate this module.
    public_reader = root / "cloud/src/v213/public-snapshot.ts"
    if public_reader.exists():
        text = public_reader.read_text(encoding="utf-8")
        if re.search(r"TENANT_PRIVATE_CACHE|EPHEMERAL_SECURITY_CACHE|env\.CACHE|privateJson|putPrivateJson", text):
            findings.append("cloud/src/v213/public-snapshot.ts: public read path touches non-public KV")
        if re.search(r"\.(?:put|delete)\s*\(", text):
            findings.append("cloud/src/v213/public-snapshot.ts: read-only view must not write KV")

    required_tests = {
        "cloud/test/storage.test.ts": (
            "reads public snapshots only from PUBLIC_CACHE",
            "encrypts long-job results only in TENANT_PRIVATE_CACHE",
            "prevents an in-flight retry from resurrecting data after tenant deletion",
        ),
        "cloud/test/line.test.ts": ("EPHEMERAL_SECURITY_CACHE",),
        "cloud/test/qa.test.ts": ("never reads TENANT_PRIVATE_CACHE",),
    }
    for relative, markers in required_tests.items():
        text = (root / relative).read_text(encoding="utf-8")
        for marker in markers:
            if marker not in text:
                findings.append(f"{relative}: missing cross-namespace regression {marker!r}")

    return findings


def main() -> int:
    try:
        findings = audit_kv_isolation()
    except (FileNotFoundError, json.JSONDecodeError, tomllib.TOMLDecodeError, ValueError) as exc:
        print(f"KV NAMESPACE ISOLATION GATE FAILED\n- {exc}")
        return 1
    if findings:
        print("KV NAMESPACE ISOLATION GATE FAILED")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print(
        "KV NAMESPACE ISOLATION GATE PASSED: public, tenant-private and ephemeral "
        "security state use distinct bindings; deletion epochs prevent retry resurrection; "
        "memory defaults unavailable"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
