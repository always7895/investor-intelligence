#!/usr/bin/env python3
"""Fail closed if shared LINE regains owner, broker or unsafe public paths."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(root: Path, relative: str) -> str:
    path = root / relative
    if not path.is_file():
        raise FileNotFoundError(relative)
    return path.read_text(encoding="utf-8")


def require(text: str, needle: str, label: str, findings: list[str]) -> None:
    if needle not in text:
        findings.append(f"{label}: missing required invariant {needle!r}")


def forbid(text: str, needle: str, label: str, findings: list[str]) -> None:
    if needle in text:
        findings.append(f"{label}: forbidden token/path remains: {needle!r}")


def audit_repository(root: Path = ROOT) -> list[str]:
    root = root.resolve()
    findings: list[str] = []
    try:
        for relative in (
            "cloud/src/internal.ts",
            "cloud/test/internal.test.ts",
            "scripts/sync_private_to_worker.py",
            "tests/test_sync_private_to_worker.py",
            "scripts/deliver.py",
            "scripts/test_delivery.py",
            "config/delivery.example.json",
        ):
            if (root / relative).exists():
                findings.append(f"{relative}: shared-LINE private/push asset must not exist")

        worker = read(root, "cloud/src/worker.ts")
        for needle in (
            "handlePrivateSync",
            "InternalSyncEnv",
            'url.pathname === "/internal/private-sync"',
            "SERVICE_SYNC_TOKEN",
            "BOT_ACCESS_NOT_AUTHORIZED",
            "LINE_DIRECT_CHAT_ONLY",
            "last_successful_pipeline_timestamp",
            "snapshotStatus",
            "local_model_configured",
            "timestamp: new Date",
        ):
            forbid(worker, needle, "cloud/src/worker.ts", findings)
        for needle in (
            "lineAccessAllowed",
            "lineAccessMode",
            "tenantSecretsConfigured",
            'source.type !== "user"',
            'lineAccessMode(env) === "disabled"',
            'options_scope: "public_snapshot_only"',
            "direct_chat_only: true",
            "ibkr_bridge: false",
            "brokerage_connection: false",
            "portfolio_access: false",
            "private_sync: false",
            "intentionally exposes only static",
        ):
            require(worker, needle, "cloud/src/worker.ts", findings)

        security = read(root, "cloud/src/security.ts")
        for needle in (
            "PRIVATE_TENANT_HASHES",
            "OPERATOR_TENANT_HASHES",
            "tenantRole",
            "LINE_DIRECT_CHAT_ONLY",
            'mode === "public"',
            'return mode === "public"',
        ):
            forbid(security, needle, "cloud/src/security.ts", findings)
        for needle in (
            'export type LineAccessMode = "disabled" | "allowlist"',
            'env.LINE_ACCESS_MODE ?? "disabled"',
            '=== "allowlist"',
            'chatType !== "user"',
            "LINE_ALLOWED_TENANT_HASHES",
            "tenantSecretsConfigured",
        ):
            require(security, needle, "cloud/src/security.ts", findings)

        qa = read(root, "cloud/src/qa.ts")
        for needle in (
            "privateJson",
            "formatPortfolioAnswer",
            "PRIVATE_TENANT_HASHES",
            "OPERATOR_TENANT_HASHES",
            "IBKR_READONLY_ENABLED",
            "PUBLIC_OPTIONS",
        ):
            forbid(qa, needle, "cloud/src/qa.ts", findings)
        for needle in (
            "LINE_PUBLIC_ONLY_NO_PORTFOLIO_OR_BROKER_DATA",
            "SENSITIVE_PERSONAL_FINANCIAL_INPUT_NOT_ACCEPTED",
            "sensitiveFinancialDisclosure",
            "async function projectContext(env: QaEnv)",
            "Public option chains are intentionally excluded",
            "LINE/Worker 不具備任何人的持倉",
            "LOCAL_LLM_ALLOWED_HOSTS",
            "allowedLocalModelHosts",
            'redirect: "error"',
            'base.port !== "443"',
            "LOCAL_LLM_SHARED_SECRET",
            "LOCAL_LLM_API_KEY",
            'hostname.endsWith(".local")',
        ):
            require(qa, needle, "cloud/src/qa.ts", findings)

        core = read(root, "cloud/src/core.ts")
        forbid(core, "formatPortfolioAnswer", "cloud/src/core.ts", findings)
        forbid(core, "privateView", "cloud/src/core.ts", findings)
        require(core, "call_observations", "cloud/src/core.ts", findings)
        require(core, "put_observations", "cloud/src/core.ts", findings)
        require(core, "不含持倉、帳戶、覆蓋口數或 IBKR 資料", "cloud/src/core.ts", findings)

        publisher = read(root, "scripts/sync_to_kv.py")
        for needle in (
            'PUBLIC_METADATA_FILENAME = "public_snapshot_metadata.json"',
            'PUBLIC_SCORES_FILENAME = "scores_public_latest.json"',
            'PUBLIC_OPTIONS_FILENAME = "options_public_latest.json"',
            'PUBLIC_SOURCE_VIEWS_FILENAME = "source_views_public_latest.json"',
            "PUBLIC_REPORT_ATTESTATIONS",
            "def _validate_public_scores",
            "def _validate_public_options",
            "def _validate_public_source_views",
            "def sync_snapshot(*, dry_run: bool = True)",
            "PUBLIC_KV_SYNC_ENABLED",
            '"sha256": hashlib.sha256(item.content).hexdigest()',
            "public_as_of",
            'parser.add_argument(\n        "--apply"',
        ):
            require(publisher, needle, "scripts/sync_to_kv.py", findings)
        for needle in (
            '"scores_latest.json"',
            '"options_latest.json"',
            '"source_views_latest.json"',
            '"health_latest.json"',
            "def _strip_keys",
        ):
            forbid(publisher, needle, "scripts/sync_to_kv.py", findings)

        builder = read(root, "scripts/build_line_public_options.py")
        for needle in ("fetch_options_ibkr", "options_service"):
            forbid(builder, needle, "scripts/build_line_public_options.py", findings)
        for needle in (
            "line-public-symbols.json",
            "owner_watchlist_inheritance",
            '"ibkr_connected": False',
            '"provider_scope": "public_only"',
        ):
            require(builder, needle, "scripts/build_line_public_options.py", findings)

        # The owner/local report pipeline may use local-only research/IBKR data,
        # but it must never regain an outbound LINE delivery call.
        daily = read(root, "scripts/daily_briefing.py")
        for needle in ("from deliver import", "send_report(", "LINE_USER_ID"):
            forbid(daily, needle, "scripts/daily_briefing.py", findings)
        require(
            daily,
            "external delivery is structurally unavailable",
            "scripts/daily_briefing.py",
            findings,
        )

        admission_files = {
            ".env.example": (
                "LINE_ACCESS_MODE=disabled",
                "LOCAL_LLM_ALLOWED_HOSTS=",
                "PUBLIC_KV_SYNC_ENABLED=false",
            ),
            "cloud/.dev.vars.example": (
                "LINE_ACCESS_MODE=disabled",
                "LOCAL_LLM_ALLOWED_HOSTS=",
            ),
            "cloud/wrangler.toml": (
                'LINE_ACCESS_MODE = "disabled"',
                'LOCAL_LLM_ALLOWED_HOSTS = ""',
            ),
        }
        for relative, required_markers in admission_files.items():
            text = read(root, relative)
            for marker in required_markers:
                require(text, marker, relative, findings)
            for needle in (
                "SERVICE_SYNC_TOKEN",
                "PRIVATE_TENANT_HASHES",
                "OPERATOR_TENANT_HASHES",
                "PRIVATE_SYNC_ENABLED",
                "LINE_DIRECT_CHAT_ONLY",
                "LINE_USER_ID=",
            ):
                forbid(text, needle, relative, findings)

        runtime = json.loads(read(root, "config/runtime-policy.json"))
        privacy = runtime.get("privacy") or {}
        authorization = runtime.get("authorization") or {}
        local_model = (runtime.get("models") or {}).get("local") or {}
        line = runtime.get("line") or {}
        data = runtime.get("data") or {}
        local_broker = runtime.get("local_broker_runtime") or {}

        required_false = {
            "privacy.group_chat_enabled": privacy.get("group_chat_enabled"),
            "privacy.owner_data_available_to_line": privacy.get("owner_data_available_to_line"),
            "privacy.owner_watchlist_inherited_by_line": privacy.get("owner_watchlist_inherited_by_line"),
            "privacy.portfolio_available_to_line": privacy.get("portfolio_available_to_line"),
            "privacy.broker_account_available_to_line": privacy.get("broker_account_available_to_line"),
            "privacy.private_sync_available_to_line": privacy.get("private_sync_available_to_line"),
            "privacy.arbitrary_model_context_includes_option_chains": privacy.get("arbitrary_model_context_includes_option_chains"),
            "privacy.unauthenticated_health_exposes_operational_metadata": privacy.get("unauthenticated_health_exposes_operational_metadata"),
            "models.local.option_chains_in_arbitrary_context": local_model.get("option_chains_in_arbitrary_context"),
            "models.local.ip_literal_hosts_allowed": local_model.get("ip_literal_hosts_allowed"),
            "models.local.non_443_ports_allowed": local_model.get("non_443_ports_allowed"),
            "models.local.redirects_allowed": local_model.get("redirects_allowed"),
            "line.ibkr_bridge": line.get("ibkr_bridge"),
            "line.brokerage_connection": line.get("brokerage_connection"),
            "line.portfolio_tools": line.get("portfolio_tools"),
            "line.private_sync_route": line.get("private_sync_route"),
            "data.line_public_legacy_artifact_fallback": data.get("line_public_legacy_artifact_fallback"),
            "local_broker.line_or_worker_may_call_ibkr": local_broker.get("line_or_worker_may_call_ibkr"),
            "local_broker.ibkr_output_may_enter_public_kv": local_broker.get("ibkr_output_may_enter_public_kv"),
            "local_broker.ibkr_output_may_enter_line_model_context": local_broker.get("ibkr_output_may_enter_line_model_context"),
        }
        for label, value in required_false.items():
            if value is not False:
                findings.append(f"config/runtime-policy.json: {label} must be false")

        if privacy.get("first_person_financial_disclosure_behavior") != "reject_without_model_or_storage":
            findings.append(
                "config/runtime-policy.json: first-person financial disclosures must be rejected without model or storage"
            )
        for label in ("allowed_hosts_required", "authenticated_route_required"):
            if local_model.get(label) is not True:
                findings.append(f"config/runtime-policy.json: models.local.{label} must be true")
        if authorization.get("supported_line_access_modes") != ["disabled", "allowlist"]:
            findings.append(
                "config/runtime-policy.json: supported_line_access_modes must be exactly disabled/allowlist"
            )
        if authorization.get("direct_chat_only") is not True:
            findings.append("config/runtime-policy.json: direct_chat_only must be true")
        for label in ("unauthorized_event_behavior", "missing_tenant_secret_behavior"):
            if authorization.get(label) != "silent_fail_closed":
                findings.append(
                    f"config/runtime-policy.json: authorization.{label} must be silent_fail_closed"
                )
        expected_datasets = {
            "line_public_metadata_dataset": "data/cache/public_snapshot_metadata.json",
            "line_public_scores_dataset": "data/cache/scores_public_latest.json",
            "line_public_options_dataset": "data/cache/options_public_latest.json",
            "line_public_source_views_dataset": "data/cache/source_views_public_latest.json",
        }
        for key, expected in expected_datasets.items():
            if data.get(key) != expected:
                findings.append(f"config/runtime-policy.json: data.{key} must be {expected}")
        for key in (
            "line_public_reports_require_attestations",
            "line_public_freshness_uses_attested_metadata",
            "line_public_manifest_contains_sha256",
            "line_public_sync_default_dry_run",
            "line_public_sync_requires_apply_and_env_gate",
        ):
            if data.get(key) is not True:
                findings.append(f"config/runtime-policy.json: data.{key} must be true")

        symbols = json.loads(read(root, "config/line-public-symbols.json"))
        if symbols.get("owner_watchlist_inheritance") is not False:
            findings.append(
                "config/line-public-symbols.json: owner_watchlist_inheritance must be false"
            )
        if not isinstance(symbols.get("symbols"), list):
            findings.append("config/line-public-symbols.json: symbols must be an array")

        architecture = read(root, "docs/LINE_PUBLIC_OPTIONS_ONLY_ARCHITECTURE.md")
        for needle in (
            "Only `disabled` and `allowlist` are supported admission modes.",
            "silently ignored before any reply, tenant/event KV write or rate-limit write",
            "Independent public snapshot artifacts",
            "Legacy files such as `scores_latest.json`",
            "The freshness timestamp comes from `public_snapshot_metadata.json`",
            "Public KV synchronization is validation-only by default.",
            "Each manifest entry contains the artifact byte count, source path and SHA-256.",
            "Public option chains are deterministic-tool-only",
            "First-person financial disclosures are rejected before model use or memory storage",
            "Local-model egress is exact-host allowlisted",
            "The unauthenticated `/health` endpoint exposes only static safety posture",
        ):
            require(
                architecture,
                needle,
                "docs/LINE_PUBLIC_OPTIONS_ONLY_ARCHITECTURE.md",
                findings,
            )
        forbid(
            architecture,
            "`public` mode",
            "docs/LINE_PUBLIC_OPTIONS_ONLY_ARCHITECTURE.md",
            findings,
        )

        phase5_workflow = read(root, ".github/workflows/phase5-line-bot-audit.yml")
        require(
            phase5_workflow,
            "TARGET_SHA: ${{ github.event.pull_request.head.sha || github.sha }}",
            ".github/workflows/phase5-line-bot-audit.yml",
            findings,
        )
        require(
            phase5_workflow,
            "ref: ${{ env.TARGET_SHA }}",
            ".github/workflows/phase5-line-bot-audit.yml",
            findings,
        )
        forbid(
            phase5_workflow,
            "LINE_DIRECT_CHAT_ONLY",
            ".github/workflows/phase5-line-bot-audit.yml",
            findings,
        )
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        findings.append(str(exc))
    return findings


def main() -> int:
    findings = audit_repository(ROOT)
    if findings:
        print("LINE PUBLIC BOUNDARY GATE FAILED")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print(
        "LINE PUBLIC BOUNDARY GATE PASSED: allowlist-only direct chats, independent "
        "attested public artifacts, no legacy owner/watchlist fallback or owner-report push, "
        "dry-run-by-default content-addressed publication, authenticated exact-host local-model "
        "egress, minimal public health, no sensitive financial disclosures, private sync, owner "
        "role, portfolio, IBKR or broker lineage"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
