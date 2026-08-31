#!/usr/bin/env python3
"""Fail closed unless the separate v2.1 owner LINE delivery layer is coherent."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

LEGACY_GIT_BLOBS = {
    "cloud/src/worker.ts": "4e0f78af402bcb6103812a3c1e06160cd838bdba",
    "cloud/src/line.ts": "618610bb277eb2949af0657609569ec5c490a1bb",
    "cloud/src/storage.ts": "3f4df4e1ce4d1dba81add2363fb28e5b9bc020b4",
    "cloud/src/qa.ts": "94184bc8937b413eb327b3d773926db00e22b3b9",
    "cloud/src/manual-options.ts": "798839536229943e6a5c2cbb19be7a8f1f198cd8",
}

REQUIRED_FILES = (
    "cloud/src/v21/top20.ts",
    "cloud/src/v21/owner-storage.ts",
    "cloud/src/v21/line-push.ts",
    "cloud/src/v21/admin.ts",
    "cloud/src/v21/broadcast.ts",
    "cloud/src/v21/worker.ts",
    "cloud/test/v21-owner-line.test.ts",
    "cloud/wrangler.v21.production.template.toml",
    "config/v21-owner-line-policy.json",
    "docs/V21_OWNER_LINE_DELIVERY.zh-TW.md",
    "scripts/build_v21_public_snapshot.py",
    "scripts/v21_owner_line_delivery_gate.py",
    "tests/test_v21_owner_line_delivery.py",
    "sync-v21-public-snapshot.ps1",
    "setup-v21-owner-line.ps1",
    ".github/workflows/v21-owner-line-delivery.yml",
)


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def git_blob(relative: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(ROOT), "hash-object", "--", relative],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if process.returncode != 0:
        # Source-package/offline self-tests may not include .git. Recompute the
        # Git blob identity directly so the exact retained-byte assertion still runs.
        data = (ROOT / relative).read_bytes()
        return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()
    return process.stdout.strip().lower()


def require(text: str, marker: str, label: str, findings: list[str]) -> None:
    if marker not in text:
        findings.append(f"{label}: missing {marker!r}")


def forbid(text: str, marker: str, label: str, findings: list[str]) -> None:
    if marker in text:
        findings.append(f"{label}: forbidden {marker!r}")


def load_policy() -> dict[str, Any]:
    value = json.loads(read("config/v21-owner-line-policy.json"))
    if not isinstance(value, dict):
        raise ValueError("v2.1 owner LINE policy must be an object")
    return value


def audit_repository() -> list[str]:
    findings: list[str] = []
    for relative in REQUIRED_FILES:
        if not (ROOT / relative).is_file():
            findings.append(f"missing required v2.1 path: {relative}")
    if findings:
        return findings

    for relative, expected in LEGACY_GIT_BLOBS.items():
        actual = git_blob(relative)
        if actual != expected:
            findings.append(f"{relative}: retained v2.0 blob changed ({actual})")

    policy = load_policy()
    expected_policy = {
        ("legacy_shared_worker", "must_remain_unchanged"): True,
        ("legacy_shared_worker", "reply_only"): True,
        ("legacy_shared_worker", "scheduled_trigger"): False,
        ("legacy_shared_worker", "push_path"): False,
        ("owner_admission", "single_owner"): True,
        ("owner_admission", "direct_chat_only"): True,
        ("owner_admission", "one_time_pairing_code"): True,
        ("owner_admission", "raw_line_user_id_logging"): False,
        ("scheduled_delivery", "maximum_pushes_per_day"): 2,
        ("scheduled_delivery", "freshness_fail_closed"): True,
        ("scheduled_delivery", "dedupe_required"): True,
        ("scheduled_delivery", "paid_fallback"): False,
        ("research", "top_count"): 20,
        ("research", "reviewed_source_catalog_count"): 99,
        ("research", "all_catalog_sources_claimed_active"): False,
        ("research", "automatic_source_activation"): False,
        ("research", "owner_watchlist_inherited"): False,
        ("forbidden", "portfolio"): True,
        ("forbidden", "brokerage"): True,
        ("forbidden", "ibkr_bridge"): True,
        ("forbidden", "automatic_trading"): True,
        ("forbidden", "cloud_paid_model"): True,
        ("source_transaction", "deployment_performed"): False,
        ("source_transaction", "secret_operation_performed"): False,
    }
    for path, expected in expected_policy.items():
        current: Any = policy
        for key in path:
            current = current.get(key) if isinstance(current, dict) else None
        if current != expected:
            findings.append(f"config/v21-owner-line-policy.json: {'.'.join(path)} must be {expected!r}")
    if policy.get("scheduled_delivery", {}).get("times") != ["08:00", "21:00"]:
        findings.append("v2.1 schedule must be exactly 08:00 and 21:00 Asia/Taipei")
    if policy.get("scheduled_delivery", {}).get("cloudflare_crons_utc") != ["0 0 * * *", "0 13 * * *"]:
        findings.append("v2.1 UTC cron mapping is invalid")

    worker = read("cloud/src/v21/worker.ts")
    for marker in (
        'source.type !== "user"',
        "tenantSecretsConfigured",
        "const query = parseQuery(text);",
        "await rateLimit(env, tenantId, query.intent)",
        "const manualOption = manualOptionQuoteAnswer(text);",
        "if (manualOption !== null)",
        "const deterministic = await deterministicAnswer",
        "const operationEpoch = await tenantWriteEpoch",
        'pathname === "/v21/admin/public-snapshot"',
        "authenticateV21AdminRequest",
        "scheduledV21Broadcast",
        "ScheduledController",
        'portfolio_access: false',
        'brokerage_connection: false',
        'ibkr_bridge: false',
        'paid_fallback: false',
        'manual_option_calculator: "ephemeral_user_supplied_only"',
        'events.length > 20',
        '"v21_owner_pairing"',
    ):
        require(worker, marker, "cloud/src/v21/worker.ts", findings)
    order = [
        worker.find("await rateLimit(env, tenantId, query.intent)"),
        worker.find("const manualOption = manualOptionQuoteAnswer(text);"),
        worker.find("const deterministic = await deterministicAnswer"),
    ]
    if not (0 <= order[0] < order[1] < order[2]):
        findings.append("cloud/src/v21/worker.ts: rate-limit/manual-option/QA order is invalid")
    for marker in (
        "lineAccessAllowed",
        "/internal/private-sync",
        "SERVICE_SYNC_TOKEN",
        "env.AI",
        "IBKR_READONLY_ENABLED",
        "fetch_options_ibkr",
        "options_service",
        "LINE_USER_ID=",
    ):
        forbid(worker, marker, "cloud/src/v21/worker.ts", findings)

    owner_storage = read("cloud/src/v21/owner-storage.ts")
    for marker in (
        "encryptTenantJson",
        "decryptTenantJson",
        "tenantDataEncryptionKey",
        "TENANT_PRIVATE_CACHE",
        "tenantWriteEpoch",
        "removeOwnerPairing",
    ):
        require(owner_storage, marker, "cloud/src/v21/owner-storage.ts", findings)
    forbid(owner_storage, "console.", "cloud/src/v21/owner-storage.ts", findings)
    forbid(owner_storage, "PUBLIC_CACHE", "cloud/src/v21/owner-storage.ts", findings)

    admin = read("cloud/src/v21/admin.ts")
    for marker in (
        "V21_SYNC_HMAC_SECRET",
        "timingSafeEqual",
        "V21_SYNC_REPLAY",
        "V21_PUBLIC_SNAPSHOT_PRIVATE_FIELD",
        "parseV21Top20",
        'plan.catalog_count !== 99',
        'plan.automatic_activation !== false',
        'inventory.runtime_enabled_count !== 0',
        '"snapshot:current"',
    ):
        require(admin, marker, "cloud/src/v21/admin.ts", findings)
    for marker in ("TENANT_PRIVATE_CACHE.put", "LINE_CHANNEL_ACCESS_TOKEN", "fetch("):
        forbid(admin, marker, "cloud/src/v21/admin.ts", findings)

    broadcast = read("cloud/src/v21/broadcast.ts")
    for marker in (
        'cron === "0 0 * * *"',
        'cron === "0 13 * * *"',
        "V21_TOP20_MAX_AGE_SECONDS",
        "dedupeKey",
        "getOwnerPushTarget",
        "pushText",
    ):
        require(broadcast, marker, "cloud/src/v21/broadcast.ts", findings)

    template = read("cloud/wrangler.v21.production.template.toml")
    for marker in (
        'main = "src/v21/worker.ts"',
        'binding = "PUBLIC_CACHE"',
        'binding = "TENANT_PRIVATE_CACHE"',
        'binding = "EPHEMERAL_SECURITY_CACHE"',
        'crons = ["0 0 * * *", "0 13 * * *"]',
    ):
        require(template, marker, "cloud/wrangler.v21.production.template.toml", findings)
    if len(re.findall(r'(?m)^id = "__[A-Z0-9_]+__"$', template)) != 3:
        findings.append("v2.1 Wrangler template must contain exactly three placeholder namespace IDs")

    builder = read("scripts/build_v21_public_snapshot.py")
    try:
        ast.parse(builder)
    except SyntaxError:
        findings.append("scripts/build_v21_public_snapshot.py: syntax error")
    for marker in (
        "Top 20 must contain exactly 20 records",
        'value.get("catalog_count") != 99',
        'value.get("automatic_activation") is not False',
        '"top20_json"',
        '"source_plan_json"',
        '"report_text"',
        "hashlib.sha256",
    ):
        require(builder, marker, "scripts/build_v21_public_snapshot.py", findings)

    workflow = read(".github/workflows/v21-owner-line-delivery.yml")
    for marker in (
        "actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10",
        "persist-credentials: false",
        "fetch-depth: 0",
        "scripts\\v21_owner_line_delivery_gate.py",
        "scripts\\build_v21_public_snapshot.py --self-test",
        "npm.cmd ci --ignore-scripts --no-audit --no-fund",
        "npm.cmd run typecheck",
        "npm.cmd test",
    ):
        require(workflow, marker, ".github/workflows/v21-owner-line-delivery.yml", findings)
    for marker in ("contents: write", "git push", "git commit", "wrangler deploy", "secret put"):
        forbid(workflow.casefold(), marker.casefold(), ".github/workflows/v21-owner-line-delivery.yml", findings)

    setup = read("setup-v21-owner-line.ps1")
    for marker in (
        "$entryPath = (Join-Path $cloudRoot 'src\\v21\\worker.ts').Replace('\\', '/')",
        "$template.Replace('main = \"src/v21/worker.ts\"'",
        "LINE channel secret is empty or invalid.",
        "LINE channel access token is empty or invalid.",
    ):
        require(setup, marker, "setup-v21-owner-line.ps1", findings)

    docs = read("docs/V21_OWNER_LINE_DELIVERY.zh-TW.md")
    for marker in (
        "08:00",
        "21:00",
        "Serenity-first",
        "99 個",
        "Aschenbrenner",
        "PUBLIC_CACHE",
        "TENANT_PRIVATE_CACHE",
        "EPHEMERAL_SECURITY_CACHE",
        "不讀取或傳送",
    ):
        require(docs, marker, "docs/V21_OWNER_LINE_DELIVERY.zh-TW.md", findings)

    return sorted(set(findings))


def main() -> int:
    try:
        findings = audit_repository()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"V21 OWNER LINE DELIVERY GATE FAILED: {type(exc).__name__}")
        return 1
    if findings:
        print("V21 OWNER LINE DELIVERY GATE FAILED")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print(
        "V21 OWNER LINE DELIVERY GATE PASSED: retained v2.0 shared worker bytes, "
        "separate owner-only entrypoint, exact 08:00/21:00 schedule, encrypted pairing, "
        "signed public snapshot, Serenity-first Top20, 99-source truth boundary, no broker, "
        "portfolio, automatic trading, paid fallback, deployment or secret operation"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
