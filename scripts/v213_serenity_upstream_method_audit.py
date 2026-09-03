#!/usr/bin/env python3
"""Audit the reviewed upstream Serenity-method snapshot.

External repositories are methodology/source-view leads only. They may improve
research workflow design, but they never count as independent company, order, or
market evidence. The snapshot must itself be recent when a release is qualified.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "config" / "v213-serenity-upstream-method-snapshot.json"
POLICY = ROOT / "config" / "v213-current-data-claim-diversity-policy.json"
MAX_SNAPSHOT_AGE_DAYS = 30
MAX_CURRENT_FEED_LAG_DAYS_AT_REVIEW = 7


class UpstreamMethodAuditError(RuntimeError):
    pass


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpstreamMethodAuditError(f"Unable to read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise UpstreamMethodAuditError(f"JSON root must be an object: {path}")
    return value


def instant(value: Any, label: str) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UpstreamMethodAuditError(f"Invalid timestamp: {label}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def audit(snapshot: Mapping[str, Any], policy: Mapping[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if snapshot.get("schema_version") != 1 or snapshot.get("product_version") != "2.1.3":
        raise UpstreamMethodAuditError("Upstream method snapshot schema/version is invalid")
    observed = instant(snapshot.get("observed_at"), "snapshot.observed_at")
    age_days = (now - observed.astimezone(timezone.utc)).total_seconds() / 86400.0
    if age_days < -(5 / 1440) or age_days > MAX_SNAPSHOT_AGE_DAYS:
        raise UpstreamMethodAuditError(
            f"Upstream method snapshot is not current enough for release qualification: age_days={age_days:.2f}"
        )

    boundary = snapshot.get("boundary")
    if not isinstance(boundary, Mapping):
        raise UpstreamMethodAuditError("Upstream methodology boundary is missing")
    for key in ("company_fact_weight", "order_fact_weight", "market_fact_weight"):
        if int(boundary.get(key, -1)) != 0:
            raise UpstreamMethodAuditError(f"External methodology source has factual weight: {key}")
    if (
        boundary.get("methodology_only") is not True
        or boundary.get("fork_or_repost_counts_as_independent_corroboration") is not False
        or boundary.get("official_serenity_formula_claimed") is not False
        or boundary.get("private_process_reproduction_claimed") is not False
    ):
        raise UpstreamMethodAuditError("External methodology boundary is not fail-closed")

    repositories = snapshot.get("repositories")
    if not isinstance(repositories, list) or len(repositories) < 3:
        raise UpstreamMethodAuditError("At least three independently reviewed method repositories are required")
    by_name: dict[str, Mapping[str, Any]] = {}
    for raw in repositories:
        if not isinstance(raw, Mapping):
            raise UpstreamMethodAuditError("Repository review row must be an object")
        name = str(raw.get("repository") or "")
        if not name or name in by_name:
            raise UpstreamMethodAuditError("Repository review identity is missing or duplicated")
        if int(raw.get("company_fact_weight", -1)) != 0:
            raise UpstreamMethodAuditError(f"Method repository has company factual weight: {name}")
        by_name[name] = raw

    current = by_name.get("yan-labs/serenity-aleabitoreddit")
    if not current or current.get("status") != "CURRENT_METHODOLOGY_AND_SOURCE_VIEW_LEAD":
        raise UpstreamMethodAuditError("Current archive/method lead is not identified")
    if not str(current.get("head_sha") or ""):
        raise UpstreamMethodAuditError("Current archive/method lead lacks a reviewed commit SHA")
    current_pushed = instant(current.get("pushed_at"), "yan-labs.pushed_at")
    lag_days = (observed - current_pushed.astimezone(timezone.utc)).total_seconds() / 86400.0
    if lag_days < 0 or lag_days > MAX_CURRENT_FEED_LAG_DAYS_AT_REVIEW:
        raise UpstreamMethodAuditError(
            f"Current archive/method lead was stale at review time: lag_days={lag_days:.2f}"
        )
    current_advantages = set(current.get("adopted_method_advantages") or [])
    for required in (
        "refresh_before_use_and_disclose_cache_staleness",
        "separate_new_bottleneck_reaffirmation_supplier_map_and_victory_lap",
        "track_stance_reversals_and_thesis_decay",
    ):
        if required not in current_advantages:
            raise UpstreamMethodAuditError(f"Current archive method advantage missing: {required}")

    for duplicate in (
        "WOOK98/serenity-aleabitoreddit",
        "toysoldiers000/serenity-skill",
    ):
        row = by_name.get(duplicate)
        if row and int(row.get("company_fact_weight", -1)) != 0:
            raise UpstreamMethodAuditError(f"Duplicate/fork lineage received factual weight: {duplicate}")

    method_policy = policy.get("methodology_sources")
    if not isinstance(method_policy, Mapping):
        raise UpstreamMethodAuditError("Current-data policy lacks methodology-source boundary")
    if (
        method_policy.get("external_skills_are_methodology_leads_only") is not True
        or method_policy.get("external_skills_have_zero_company_fact_weight") is not True
        or method_policy.get("forks_and_reposts_do_not_create_independent_factual_corroboration") is not True
        or method_policy.get("latest_source_snapshot_required_before_adopting_method_changes") is not True
    ):
        raise UpstreamMethodAuditError("Current-data policy weakens upstream methodology boundaries")

    contracts = set(snapshot.get("adopted_runtime_contracts") or [])
    for required in (
        "latest_company_data_must_come_from_current_primary_or_independently_corroborating_sources",
        "single_publisher_rows_cannot_receive_high_confidence_model_inference",
        "structural_bottleneck_claims_require_evidence_bound_relationship_and_scarcity",
        "forward_signal_filters_must_remove_retrospective_victory_laps_and_quote_only_rows",
    ):
        if required not in contracts:
            raise UpstreamMethodAuditError(f"Adopted runtime contract missing: {required}")

    return {
        "status": "PASS",
        "snapshot_age_days": round(age_days, 3),
        "repositories_reviewed": len(repositories),
        "current_lead": "yan-labs/serenity-aleabitoreddit",
        "current_lead_head": str(current.get("head_sha")),
        "external_company_fact_weight": 0,
    }


def self_test() -> None:
    snapshot = load(SNAPSHOT)
    policy = load(POLICY)
    observed = instant(snapshot["observed_at"], "snapshot.observed_at")
    result = audit(snapshot, policy, observed)
    assert result["status"] == "PASS"
    broken = json.loads(json.dumps(snapshot))
    broken["repositories"][0]["company_fact_weight"] = 1
    try:
        audit(broken, policy, observed)
    except UpstreamMethodAuditError:
        pass
    else:
        raise AssertionError("Method repository factual-weight violation was not rejected")
    print(
        "V213_SERENITY_UPSTREAM_METHOD_AUDIT_SELF_TEST = PASS; "
        "methodology_only=true; external_company_fact_weight=0"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    parser.add_argument("--policy", type=Path, default=POLICY)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    result = audit(load(args.snapshot), load(args.policy))
    print(
        "V213_SERENITY_UPSTREAM_METHOD_AUDIT = PASS; "
        f"repositories={result['repositories_reviewed']}; "
        f"current_lead_head={result['current_lead_head']}; "
        "external_company_fact_weight=0",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (UpstreamMethodAuditError, OSError, ValueError) as exc:
        print(f"V213_SERENITY_UPSTREAM_METHOD_AUDIT = FAIL; {exc}", flush=True)
        raise SystemExit(1)
