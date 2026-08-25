#!/usr/bin/env python3
"""Fail closed when documentation regains removed LINE/private/broker/cost paths."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]

LINE_BOUNDARY_MARKERS = (
    "LINE_DATA_SCOPE=PUBLIC_ONLY",
    "LINE_IBKR_BRIDGE=FORBIDDEN",
    "LINE_PORTFOLIO_TOOLS=FORBIDDEN",
    "LINE_PRIVATE_SYNC=FORBIDDEN",
    "LINE_GROUP_ROOM=REJECTED",
    "LINE_OWNER_DATA=FORBIDDEN",
    "FREE_ONLY_MODE=FAIL_CLOSED",
)

IBKR_BOUNDARY_MARKERS = (
    "IBKR_RUNTIME_SCOPE=LOCAL_READ_ONLY_ONLY",
    "IBKR_TO_LINE=FORBIDDEN",
    "IBKR_TO_WORKER=FORBIDDEN",
    "IBKR_TO_PUBLIC_KV=FORBIDDEN",
    "IBKR_TO_LINE_MODEL_CONTEXT=FORBIDDEN",
    "IBKR_WRITE_PATHS=FORBIDDEN",
)

ZERO_COST_MARKERS = (
    "FREE_ONLY_MODE=FAIL_CLOSED",
    "CLOUD_INFERENCE=DISABLED",
    "PAID_FALLBACK=FORBIDDEN",
    "LINE_PUSH=DISABLED",
    "GITHUB_HOSTED_RUNNERS=FORBIDDEN",
)

OPTIONS_BOUNDARY_MARKERS = LINE_BOUNDARY_MARKERS + (
    "LINE_OPTIONS_SCOPE=PUBLIC_QUOTE_OBSERVATION_ONLY",
    "LINE_POSITION_ELIGIBILITY=FORBIDDEN",
    "LOCAL_POSITION_ANALYSIS=LOCAL_ONLY",
    "IBKR_TO_LINE=FORBIDDEN",
)

DOCUMENT_MARKERS: dict[str, Sequence[str]] = {
    "docs/LINE_BOT_QA_IMPLEMENTATION.md": LINE_BOUNDARY_MARKERS,
    "docs/LINE_BOT_QA_SPEC.md": LINE_BOUNDARY_MARKERS,
    "docs/PRIVACY_MULTI_TENANT_POLICY.md": LINE_BOUNDARY_MARKERS,
    "docs/FINAL_RELEASE_PLAN.md": LINE_BOUNDARY_MARKERS,
    "docs/SECURITY.md": LINE_BOUNDARY_MARKERS,
    "docs/PHASE5_VALIDATION.md": LINE_BOUNDARY_MARKERS,
    "docs/OPTIONS_RECOMMENDATION_SPEC.md": OPTIONS_BOUNDARY_MARKERS,
    "docs/IBKR_READ_ONLY.md": IBKR_BOUNDARY_MARKERS,
    "docs/ZERO_COST_POLICY.md": ZERO_COST_MARKERS,
}

STALE_DOCUMENT_TOKENS = (
    "/internal/private-sync",
    "sync_private_to_worker.py",
    "cloud/src/internal.ts",
    "SERVICE_SYNC_TOKEN",
    "PRIVATE_SYNC_ENABLED",
    "tenant:<hmac-id>:portfolio:latest",
    "tenant:<hmac-id>:options:latest",
    "private portfolio capability",
    "private position-dependent option eligibility",
    "Groups receive public/general answers only",
    "encrypted push destination",
    "portfolio/private tools only",
    "PR #6 remains draft",
    "public/private synchronization tests",
    "Cloud inference is optional",
    "If push is later enabled",
    "LINE_FREE_PUSH_QUOTA_EXHAUSTED",
    "optional private tools",
    "tenant-specific eligibility only",
    "Private eligibility is computed",
    "broker data already available to that tenant",
    "Group chat cannot request private eligibility",
)

REMOVED_ASSETS = (
    "cloud/src/internal.ts",
    "cloud/test/internal.test.ts",
    "scripts/sync_private_to_worker.py",
    "tests/test_sync_private_to_worker.py",
    "scripts/deliver.py",
    "scripts/test_delivery.py",
    "config/delivery.example.json",
)

WORKFLOW_PATH = ".github/workflows/line-kv-isolation-audit.yml"
WORKFLOW_INVOCATION = "scripts/documentation_boundary_gate.py"


def read_text(root: Path, relative: str) -> str:
    path = root / relative
    if not path.is_file():
        raise FileNotFoundError(relative)
    return path.read_text(encoding="utf-8")


def load_documents(root: Path = ROOT) -> dict[str, str]:
    return {path: read_text(root, path) for path in DOCUMENT_MARKERS}


def load_runtime(root: Path = ROOT) -> dict:
    return json.loads(read_text(root, "config/runtime-policy.json"))


def load_workflows(root: Path = ROOT) -> dict[str, str]:
    return {WORKFLOW_PATH: read_text(root, WORKFLOW_PATH)}


def existing_removed_assets(root: Path = ROOT) -> set[str]:
    return {path for path in REMOVED_ASSETS if (root / path).exists()}


def _value(document: Mapping, *keys: str):
    current = document
    for key in keys:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def audit_loaded(
    documents: Mapping[str, str],
    runtime: Mapping,
    workflows: Mapping[str, str],
    present_removed_assets: set[str] | None = None,
) -> list[str]:
    findings: list[str] = []

    for path, markers in DOCUMENT_MARKERS.items():
        text = documents.get(path)
        if text is None:
            findings.append(f"{path}: document is missing")
            continue
        for marker in markers:
            if marker not in text:
                findings.append(f"{path}: missing normative marker {marker!r}")
        for token in STALE_DOCUMENT_TOKENS:
            if token in text:
                findings.append(f"{path}: stale removed capability remains: {token!r}")

    required_runtime_values = {
        "privacy.group_chat_enabled": (
            _value(runtime, "privacy", "group_chat_enabled"),
            False,
        ),
        "privacy.owner_data_available_to_line": (
            _value(runtime, "privacy", "owner_data_available_to_line"),
            False,
        ),
        "privacy.portfolio_available_to_line": (
            _value(runtime, "privacy", "portfolio_available_to_line"),
            False,
        ),
        "privacy.broker_account_available_to_line": (
            _value(runtime, "privacy", "broker_account_available_to_line"),
            False,
        ),
        "privacy.private_sync_available_to_line": (
            _value(runtime, "privacy", "private_sync_available_to_line"),
            False,
        ),
        "privacy.memory_feature_available_for_initial_external_release": (
            _value(
                runtime,
                "privacy",
                "memory_feature_available_for_initial_external_release",
            ),
            False,
        ),
        "authorization.supported_line_access_modes": (
            _value(runtime, "authorization", "supported_line_access_modes"),
            ["disabled", "allowlist"],
        ),
        "authorization.direct_chat_only": (
            _value(runtime, "authorization", "direct_chat_only"),
            True,
        ),
        "authorization.owner_or_operator_role_exists_in_shared_bot": (
            _value(
                runtime,
                "authorization",
                "owner_or_operator_role_exists_in_shared_bot",
            ),
            False,
        ),
        "line.push_messages_enabled": (
            _value(runtime, "line", "push_messages_enabled"),
            False,
        ),
        "line.additional_paid_messages_allowed": (
            _value(runtime, "line", "additional_paid_messages_allowed"),
            False,
        ),
        "line.options_scope": (
            _value(runtime, "line", "options_scope"),
            "public_quote_observation_only",
        ),
        "line.ibkr_bridge": (_value(runtime, "line", "ibkr_bridge"), False),
        "line.brokerage_connection": (
            _value(runtime, "line", "brokerage_connection"),
            False,
        ),
        "line.portfolio_tools": (
            _value(runtime, "line", "portfolio_tools"),
            False,
        ),
        "line.private_sync_route": (
            _value(runtime, "line", "private_sync_route"),
            False,
        ),
        "models.cloud.enabled": (
            _value(runtime, "models", "cloud", "enabled"),
            False,
        ),
        "models.cloud.paid_plan_models_allowed": (
            _value(runtime, "models", "cloud", "paid_plan_models_allowed"),
            False,
        ),
        "models.local.option_chains_in_arbitrary_context": (
            _value(runtime, "models", "local", "option_chains_in_arbitrary_context"),
            False,
        ),
        "local_broker_runtime.line_or_worker_may_call_ibkr": (
            _value(runtime, "local_broker_runtime", "line_or_worker_may_call_ibkr"),
            False,
        ),
        "local_broker_runtime.ibkr_output_may_enter_public_kv": (
            _value(runtime, "local_broker_runtime", "ibkr_output_may_enter_public_kv"),
            False,
        ),
        "local_broker_runtime.ibkr_output_may_enter_line_model_context": (
            _value(
                runtime,
                "local_broker_runtime",
                "ibkr_output_may_enter_line_model_context",
            ),
            False,
        ),
        "local_broker_runtime.broker_write_paths": (
            _value(runtime, "local_broker_runtime", "broker_write_paths"),
            False,
        ),
        "data.line_option_snapshot_rejects_broker_lineage": (
            _value(runtime, "data", "line_option_snapshot_rejects_broker_lineage"),
            True,
        ),
        "data.line_option_snapshot_rejects_position_fields": (
            _value(runtime, "data", "line_option_snapshot_rejects_position_fields"),
            True,
        ),
        "cost.mode": (
            _value(runtime, "cost", "mode"),
            "free_only_fail_closed",
        ),
        "cost.paid_fallback": (
            _value(runtime, "cost", "paid_fallback"),
            False,
        ),
        "cost.automatic_plan_upgrade": (
            _value(runtime, "cost", "automatic_plan_upgrade"),
            False,
        ),
        "cost.paid_model_api_allowed": (
            _value(runtime, "cost", "paid_model_api_allowed"),
            False,
        ),
        "cost.github_hosted_runners_allowed": (
            _value(runtime, "cost", "github_hosted_runners_allowed"),
            False,
        ),
        "cost.line_push_default": (
            _value(runtime, "cost", "line_push_default"),
            False,
        ),
    }
    for label, (actual, expected) in required_runtime_values.items():
        if actual != expected:
            findings.append(
                f"config/runtime-policy.json: {label} must be {expected!r}, found {actual!r}"
            )

    workflow = workflows.get(WORKFLOW_PATH)
    if workflow is None:
        findings.append(f"{WORKFLOW_PATH}: workflow is missing")
    elif WORKFLOW_INVOCATION not in workflow:
        findings.append(f"{WORKFLOW_PATH}: must invoke {WORKFLOW_INVOCATION!r}")

    for path in sorted(present_removed_assets or set()):
        findings.append(f"{path}: removed capability asset must not exist")

    return findings


def audit_repository(root: Path = ROOT) -> list[str]:
    root = root.resolve()
    try:
        return audit_loaded(
            load_documents(root),
            load_runtime(root),
            load_workflows(root),
            existing_removed_assets(root),
        )
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return [str(exc)]


def main() -> int:
    findings = audit_repository(ROOT)
    if findings:
        print("DOCUMENTATION BOUNDARY GATE FAILED")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print(
        "DOCUMENTATION BOUNDARY GATE PASSED: shared LINE remains public-only, "
        "direct-chat allowlist-only, public-options-only, local-model-only, free-only "
        "and separated from owner, portfolio, broker, private-sync, push and removed "
        "delivery surfaces"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
