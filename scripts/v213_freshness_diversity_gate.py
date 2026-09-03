#!/usr/bin/env python3
"""Fail-closed promotion gate for v2.1.3 freshness and claim diversity.

This gate runs after the source-independence sidecar is produced and before the
signed snapshot/activation bundle is built. It verifies that every promoted
artifact belongs to the current run, every Top20 order row was rechecked, stale
market observations were excluded, single-publisher rows remain LIMITED, and no
positive Serenity-style structural state was created without explicit
multi-publisher evidence.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "v213-current-data-claim-diversity-policy.json"
TOP20_PATH = ROOT / "data" / "cache" / "top20_public_latest.json"
V212_PATH = ROOT / "data" / "cache" / "v212_top20_report_public_latest.json"
V213_PATH = ROOT / "data" / "cache" / "v213_top20_report_public_latest.json"
ORDER_RUNTIME_PATH = ROOT / "data" / "cache" / "v213_order_evidence_runtime.json"
ORDER_RECEIPT_PATH = (
    ROOT / "data" / "cache" / "v213_order_evidence_reconciliation.json"
)
FEDERATION_PATH = ROOT / "data" / "cache" / "v213_source_federation_latest.json"
SOURCE_AUDIT_PATH = (
    ROOT / "data" / "cache" / "v213_source_independence_latest.json"
)
OUTPUT_PATH = ROOT / "data" / "cache" / "v213_freshness_diversity_audit.json"

STRUCTURAL_FIELDS = {
    "architecture": "architecture_evidence_bound",
    "relationship_state": "relationship_evidence_bound",
    "scarcity_state": "scarcity_evidence_bound",
    "dependency_graph": "dependency_graph_evidence_bound",
    "bottleneck_or_expansion": "bottleneck_evidence_bound",
    "company_capture": "company_capture_evidence_bound",
    "operating_thesis_state": None,
    "equity_capture_state": None,
}
NON_POSITIVE_STATES = {
    "",
    "UNPROVEN",
    "NOT_ATTACHED",
    "CURRENT_LEAD_ONLY",
    "REVIEW_REQUIRED",
    "REQUIRED_NOT_AUTOMATICALLY_SATISFIED",
    "LIMITED",
}


class FreshnessDiversityError(RuntimeError):
    pass


def load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FreshnessDiversityError(f"Unable to read JSON: {path}") from exc


def atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        delete=False,
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)


def instant(value: Any, label: str) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FreshnessDiversityError(f"Invalid timestamp: {label}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def day(value: Any, label: str) -> date:
    text = str(value or "").strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError as exc:
            raise FreshnessDiversityError(f"Invalid date: {label}") from exc


def current_timestamp(
    value: Any,
    label: str,
    now: datetime,
    max_age_seconds: int,
    future_skew_seconds: int,
) -> None:
    observed = instant(value, label).astimezone(timezone.utc)
    age = (now - observed).total_seconds()
    if age < -future_skew_seconds or age > max_age_seconds:
        raise FreshnessDiversityError(
            f"Artifact is not current: {label}; age_seconds={age:.0f}"
        )


def rows(document: Any, label: str) -> list[dict[str, Any]]:
    if isinstance(document, list):
        raw = document
    elif isinstance(document, Mapping) and isinstance(
        document.get("records"), list
    ):
        raw = document["records"]
    else:
        raise FreshnessDiversityError(f"{label} does not contain records")
    if len(raw) != 20 or not all(isinstance(row, Mapping) for row in raw):
        raise FreshnessDiversityError(f"{label} must contain exactly 20 rows")
    result = [dict(row) for row in raw]
    order = [str(row.get("ticker") or "").upper() for row in result]
    if any(not ticker for ticker in order) or len(set(order)) != 20:
        raise FreshnessDiversityError(f"{label} ticker membership is invalid")
    for index, row in enumerate(result, 1):
        if int(row.get("rank") or 0) != index:
            raise FreshnessDiversityError(f"{label} rank order is invalid")
    return result


def order_of(document: Any, label: str) -> list[str]:
    return [str(row["ticker"]).upper() for row in rows(document, label)]


def same_order(expected: list[str], document: Any, label: str) -> None:
    actual = order_of(document, label)
    if actual != expected:
        raise FreshnessDiversityError(
            f"Atomic order mismatch: {label}; expected={expected}; actual={actual}"
        )


def supported_order(row: Mapping[str, Any]) -> bool:
    urls = list(row.get("current_order_source_urls") or []) + list(
        row.get("future_order_source_urls") or []
    )
    return (
        str(row.get("orders_confidence") or "") != "UNAVAILABLE"
        and any(str(url).startswith("https://") for url in urls)
    )


def audit(
    policy: Mapping[str, Any],
    top20: Any,
    v212: Mapping[str, Any],
    v213: Mapping[str, Any],
    order_runtime: Mapping[str, Any],
    order_receipt: Mapping[str, Any],
    federation: Mapping[str, Any],
    source_audit: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if (
        policy.get("schema_version") != 1
        or policy.get("product_version") != "2.1.3"
        or policy.get("policy_id") != "v213-current-data-claim-diversity-v1"
    ):
        raise FreshnessDiversityError("Current-data policy schema/version is invalid")
    max_age = int(policy.get("artifact_max_age_seconds") or 0)
    future_skew = int(policy.get("future_clock_skew_seconds") or 0)
    if max_age <= 0 or future_skew < 0:
        raise FreshnessDiversityError("Artifact freshness policy is invalid")
    freshness_days = policy.get("freshness_days")
    if not isinstance(freshness_days, Mapping):
        raise FreshnessDiversityError("Freshness-day policy is missing")
    order_max_days = int(freshness_days.get("contract_or_order") or 0)
    market_max_days = int(
        freshness_days.get("market_observation_max_calendar_age") or 0
    )

    top_rows = rows(top20, "top20")
    expected_order = [str(row["ticker"]).upper() for row in top_rows]
    same_order(expected_order, v212, "v212")
    same_order(expected_order, v213, "v213")
    same_order(expected_order, order_runtime, "order_runtime")
    same_order(expected_order, federation.get("ticker_sources"), "federation")
    same_order(expected_order, source_audit, "source_audit")

    for index, row in enumerate(top_rows, 1):
        current_timestamp(
            row.get("generated_at"),
            f"top20[{index}].generated_at",
            now,
            max_age,
            future_skew,
        )
        current_timestamp(
            row.get("as_of"),
            f"top20[{index}].as_of",
            now,
            max_age,
            future_skew,
        )
        if (
            row.get("scoring_version")
            != "system-operationalization-v2.1.3-diversified"
        ):
            raise FreshnessDiversityError(
                f"Provisional or legacy Top20 row retained: {row.get('ticker')}"
            )

    for label, document in (
        ("v212.generated_at", v212),
        ("v213.generated_at", v213),
        ("order_runtime.generated_at", order_runtime),
        ("order_receipt.generated_at", order_receipt),
        ("federation.generated_at", federation),
        ("source_audit.generated_at", source_audit),
    ):
        current_timestamp(
            document.get("generated_at"),
            label,
            now,
            max_age,
            future_skew,
        )

    if (
        order_receipt.get("status") != "PASS"
        or order_receipt.get("every_current_member_rechecked") is not True
        or int(order_receipt.get("rechecked_count") or 0) != 20
        or int(order_receipt.get("successful_recheck_count") or 0) != 20
        or int(order_receipt.get("check_error_count") or 0) != 0
        or order_receipt.get("numeric_total_order_estimate_prohibited") is not True
        or order_receipt.get("pipeline_or_guidance_is_not_booked_order") is not True
        or order_receipt.get("local_model_used_for_order_totals") is not False
    ):
        raise FreshnessDiversityError(
            "All-member current order-evidence recheck did not pass"
        )
    if [str(value).upper() for value in order_receipt.get("new_order") or []] != expected_order:
        raise FreshnessDiversityError("Order-evidence receipt membership is not current")

    runtime_rows = rows(order_runtime, "order_runtime")
    supported_count = 0
    unavailable_count = 0
    for row in runtime_rows:
        ticker = str(row["ticker"]).upper()
        current_timestamp(
            row.get("last_checked_at"),
            f"{ticker}.last_checked_at",
            now,
            max_age,
            future_skew,
        )
        if str(row.get("latest_check_result") or "") == "CHECK_EXECUTION_ERROR":
            raise FreshnessDiversityError(
                f"Order-evidence check execution failed: {ticker}"
            )
        if row.get("numeric_total_order_estimate_prohibited") is not True:
            raise FreshnessDiversityError(
                f"Numeric total-order guard is missing: {ticker}"
            )
        if supported_order(row):
            supported_count += 1
            evidence_day = day(row.get("orders_as_of"), f"{ticker}.orders_as_of")
            age = (now.date() - evidence_day).days
            if age < -1 or age > order_max_days:
                raise FreshnessDiversityError(
                    f"Supported order evidence is not current: {ticker}; age_days={age}"
                )
            if row.get("evidence_freshness_status") != "FRESH":
                raise FreshnessDiversityError(
                    f"Supported order evidence lacks FRESH status: {ticker}"
                )
        else:
            unavailable_count += 1

    gates = federation.get("gates")
    if not isinstance(gates, Mapping) or gates.get("pass") is not True:
        raise FreshnessDiversityError("Live source federation gate did not pass")
    if int(gates.get("unresolved_material_conflict_count") or 0) != 0:
        raise FreshnessDiversityError("Source federation contains unresolved conflicts")
    if gates.get("claim_scope_separation_enforced") is not True:
        raise FreshnessDiversityError("Source federation claim-scope separation is off")
    if gates.get("publisher_family_deduplication_enforced") is not True:
        raise FreshnessDiversityError("Source federation publisher deduplication is off")

    if (
        source_audit.get("status") != "PASS"
        or list(source_audit.get("violations") or [])
        or list(source_audit.get("blocking_violations") or [])
    ):
        raise FreshnessDiversityError("Claim-level source audit contains blockers")
    portfolio = source_audit.get("portfolio")
    notice = source_audit.get("methodology_notice")
    contract = source_audit.get("source_diversity_contract")
    if not isinstance(portfolio, Mapping) or not isinstance(notice, Mapping) or not isinstance(contract, Mapping):
        raise FreshnessDiversityError("Source-audit policy metadata is missing")
    if (
        portfolio.get("current_data_policy") != policy.get("policy_id")
        or int(portfolio.get("future_dated_evidence_count") or 0) != 0
        or int(portfolio.get("market_conflict_ticker_count") or 0) != 0
        or notice.get("current_data_freshness_enforced") is not True
        or notice.get("single_source_claims_are_limited") is not True
        or notice.get("identity_and_context_excluded_from_claim_proof") is not True
        or notice.get("same_focal_issuer_ir_and_filing_count_once") is not True
        or notice.get("source_view_system_score_and_model_inference_are_separate") is not True
        or notice.get("structural_claim_requires_evidence_bound_relationship_and_scarcity") is not True
        or contract.get("scope") != "claim_and_publisher_entity"
        or contract.get("identity_market_macro_social_methodology_excluded") is not True
        or contract.get("focal_issuer_repetition_deduplicated") is not True
    ):
        raise FreshnessDiversityError(
            "Source-audit current-data or claim-diversity contract is incomplete"
        )

    source_rows = rows(source_audit, "source_audit")
    high_count = 0
    single_source_rows = 0
    positive_structural_rows = 0
    fresh_market_rows = 0
    for row in source_rows:
        ticker = str(row["ticker"]).upper()
        metrics = row.get("source_metrics")
        market = row.get("market_corroboration")
        logic = row.get("public_logic_state")
        if not isinstance(metrics, Mapping) or not isinstance(market, Mapping) or not isinstance(logic, Mapping):
            raise FreshnessDiversityError(f"Source-audit row is incomplete: {ticker}")
        family_count = int(
            metrics.get("claim_relevant_independent_families") or 0
        )
        domain_count = int(
            metrics.get("claim_relevant_independent_domains") or 0
        )
        primary_count = int(metrics.get("claim_relevant_primary_sources") or 0)
        eligible = row.get("eligible_for_high_confidence_model_inference") is True
        if family_count < 2 or domain_count < 2:
            single_source_rows += 1
            if eligible or logic.get("model_inference_confidence") != "LIMITED":
                raise FreshnessDiversityError(
                    f"Single-publisher row was not limited: {ticker}"
                )
        if eligible:
            high_count += 1
            if (
                family_count < 2
                or domain_count < 2
                or primary_count < 1
                or float(metrics.get("claim_dated_evidence_ratio") or 0) < 0.8
                or int(market.get("fresh_provider_count") or 0) < 1
                or market.get("status") != "CORROBORATED"
                or logic.get("model_inference_confidence") != "HIGH_ELIGIBLE"
            ):
                raise FreshnessDiversityError(
                    f"High-confidence evidence contract failed: {ticker}"
                )

        providers = market.get("providers")
        if not isinstance(providers, list):
            raise FreshnessDiversityError(f"Market provider list is missing: {ticker}")
        row_has_fresh_market = False
        for provider in providers:
            if not isinstance(provider, Mapping):
                raise FreshnessDiversityError(f"Invalid market provider row: {ticker}")
            if str(provider.get("status") or "") in {"LIVE", "CACHED"}:
                if provider.get("freshness_status") != "FRESH":
                    raise FreshnessDiversityError(
                        f"Stale market provider still counts as active: {ticker}"
                    )
                market_day = day(
                    provider.get("as_of"),
                    f"{ticker}.{provider.get('provider')}.as_of",
                )
                age = (now.date() - market_day).days
                if age < -1 or age > market_max_days:
                    raise FreshnessDiversityError(
                        f"Active market provider is not current: {ticker}; age_days={age}"
                    )
                row_has_fresh_market = True
        if row_has_fresh_market:
            fresh_market_rows += 1

        structural_positive = False
        for field, proof_field in STRUCTURAL_FIELDS.items():
            state = str(logic.get(field) or "")
            if state in NON_POSITIVE_STATES:
                continue
            structural_positive = True
            if family_count < 2 or domain_count < 2 or primary_count < 1:
                raise FreshnessDiversityError(
                    f"Structural state lacks multi-publisher proof: {ticker}.{field}"
                )
            if proof_field and logic.get(proof_field) is not True:
                raise FreshnessDiversityError(
                    f"Structural state lacks evidence-bound marker: {ticker}.{field}"
                )
        if structural_positive:
            positive_structural_rows += 1

        for source in row.get("sources") or []:
            if not isinstance(source, Mapping):
                raise FreshnessDiversityError(f"Invalid claim-source row: {ticker}")
            if source.get("eligible_for_company_claim_proof") is True and source.get("freshness_status") != "FRESH":
                raise FreshnessDiversityError(
                    f"Non-fresh source remains claim-proof eligible: {ticker}"
                )
            if source.get("freshness_status") == "FUTURE":
                raise FreshnessDiversityError(
                    f"Future-dated source retained: {ticker}"
                )

    if high_count != int(
        portfolio.get("high_confidence_model_inference_eligible_count") or 0
    ):
        raise FreshnessDiversityError("High-confidence row count is inconsistent")
    if single_source_rows != int(
        portfolio.get("single_claim_publisher_rows") or 0
    ):
        raise FreshnessDiversityError("Single-publisher row count is inconsistent")
    if fresh_market_rows != int(
        portfolio.get("fresh_market_ticker_count") or 0
    ):
        raise FreshnessDiversityError("Fresh-market row count is inconsistent")

    return {
        "schema_version": 1,
        "product_version": "2.1.3",
        "generated_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "PASS",
        "policy_id": policy["policy_id"],
        "top20_count": 20,
        "order_rows_rechecked": 20,
        "supported_order_rows": supported_count,
        "unavailable_order_rows": unavailable_count,
        "single_publisher_rows_limited": single_source_rows,
        "high_confidence_rows": high_count,
        "positive_structural_rows": positive_structural_rows,
        "fresh_market_rows": fresh_market_rows,
        "future_dated_evidence_count": 0,
        "unresolved_conflict_count": 0,
        "production_mutation": False,
    }


def self_test() -> None:
    now = datetime(2026, 9, 3, 4, 0, tzinfo=timezone.utc)
    stamp = "2026-09-03T04:00:00Z"
    policy = load(POLICY_PATH)
    tickers = [f"T{index:02d}" for index in range(20)]
    top20 = [
        {
            "rank": index + 1,
            "ticker": ticker,
            "generated_at": stamp,
            "as_of": stamp,
            "scoring_version": "system-operationalization-v2.1.3-diversified",
        }
        for index, ticker in enumerate(tickers)
    ]
    v212 = {
        "generated_at": stamp,
        "records": [
            {"rank": index + 1, "ticker": ticker}
            for index, ticker in enumerate(tickers)
        ],
    }
    v213 = json.loads(json.dumps(v212))
    order_runtime = {
        "generated_at": stamp,
        "records": [
            {
                "rank": index + 1,
                "ticker": ticker,
                "orders_confidence": "UNAVAILABLE",
                "current_order_source_urls": [],
                "future_order_source_urls": [],
                "last_checked_at": stamp,
                "latest_check_result": "CURRENT_RECHECK_NO_SUPPORTED_ORDER_EVIDENCE",
                "numeric_total_order_estimate_prohibited": True,
            }
            for index, ticker in enumerate(tickers)
        ],
    }
    order_receipt = {
        "generated_at": stamp,
        "status": "PASS",
        "every_current_member_rechecked": True,
        "rechecked_count": 20,
        "successful_recheck_count": 20,
        "check_error_count": 0,
        "numeric_total_order_estimate_prohibited": True,
        "pipeline_or_guidance_is_not_booked_order": True,
        "local_model_used_for_order_totals": False,
        "new_order": tickers,
    }
    federation = {
        "generated_at": stamp,
        "ticker_sources": [
            {"rank": index + 1, "ticker": ticker}
            for index, ticker in enumerate(tickers)
        ],
        "gates": {
            "pass": True,
            "unresolved_material_conflict_count": 0,
            "claim_scope_separation_enforced": True,
            "publisher_family_deduplication_enforced": True,
        },
    }
    source_audit = {
        "generated_at": stamp,
        "status": "PASS",
        "violations": [],
        "blocking_violations": [],
        "portfolio": {
            "current_data_policy": policy["policy_id"],
            "future_dated_evidence_count": 0,
            "market_conflict_ticker_count": 0,
            "high_confidence_model_inference_eligible_count": 0,
            "single_claim_publisher_rows": 20,
            "fresh_market_ticker_count": 0,
        },
        "methodology_notice": {
            "current_data_freshness_enforced": True,
            "single_source_claims_are_limited": True,
            "identity_and_context_excluded_from_claim_proof": True,
            "same_focal_issuer_ir_and_filing_count_once": True,
            "source_view_system_score_and_model_inference_are_separate": True,
            "structural_claim_requires_evidence_bound_relationship_and_scarcity": True,
        },
        "source_diversity_contract": {
            "scope": "claim_and_publisher_entity",
            "identity_market_macro_social_methodology_excluded": True,
            "focal_issuer_repetition_deduplicated": True,
        },
        "records": [
            {
                "rank": index + 1,
                "ticker": ticker,
                "source_metrics": {
                    "claim_relevant_independent_families": 1,
                    "claim_relevant_independent_domains": 1,
                    "claim_relevant_primary_sources": 1,
                    "claim_dated_evidence_ratio": 1.0,
                },
                "market_corroboration": {
                    "status": "UNAVAILABLE",
                    "fresh_provider_count": 0,
                    "providers": [],
                },
                "public_logic_state": {
                    "architecture": "UNPROVEN",
                    "relationship_state": "UNPROVEN",
                    "scarcity_state": "UNPROVEN",
                    "dependency_graph": "UNPROVEN",
                    "bottleneck_or_expansion": "UNPROVEN",
                    "company_capture": "UNPROVEN",
                    "operating_thesis_state": "UNPROVEN",
                    "equity_capture_state": "UNPROVEN",
                    "model_inference_confidence": "LIMITED",
                },
                "eligible_for_high_confidence_model_inference": False,
                "sources": [],
            }
            for index, ticker in enumerate(tickers)
        ],
    }
    receipt = audit(
        policy,
        top20,
        v212,
        v213,
        order_runtime,
        order_receipt,
        federation,
        source_audit,
        now=now,
    )
    assert receipt["status"] == "PASS"
    broken = json.loads(json.dumps(source_audit))
    broken["records"][0]["eligible_for_high_confidence_model_inference"] = True
    try:
        audit(
            policy,
            top20,
            v212,
            v213,
            order_runtime,
            order_receipt,
            federation,
            broken,
            now=now,
        )
    except FreshnessDiversityError:
        pass
    else:
        raise AssertionError("Single-publisher high-confidence row was accepted")
    print(
        "V213_FRESHNESS_DIVERSITY_GATE_SELF_TEST = PASS; "
        "all_orders_rechecked=true; stale_market_excluded=true; "
        "single_source_limited=true; structural_claims_evidence_bound=true"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    parser.add_argument("--top20", type=Path, default=TOP20_PATH)
    parser.add_argument("--v212", type=Path, default=V212_PATH)
    parser.add_argument("--v213", type=Path, default=V213_PATH)
    parser.add_argument("--order-runtime", type=Path, default=ORDER_RUNTIME_PATH)
    parser.add_argument("--order-receipt", type=Path, default=ORDER_RECEIPT_PATH)
    parser.add_argument("--federation", type=Path, default=FEDERATION_PATH)
    parser.add_argument("--source-audit", type=Path, default=SOURCE_AUDIT_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    receipt = audit(
        load(args.policy),
        load(args.top20),
        load(args.v212),
        load(args.v213),
        load(args.order_runtime),
        load(args.order_receipt),
        load(args.federation),
        load(args.source_audit),
    )
    atomic(args.output, receipt)
    print(
        "V213_FRESHNESS_DIVERSITY_GATE = PASS; "
        f"orders_rechecked={receipt['order_rows_rechecked']}; "
        f"single_source_limited={receipt['single_publisher_rows_limited']}; "
        f"high_confidence={receipt['high_confidence_rows']}; "
        f"fresh_market_rows={receipt['fresh_market_rows']}; "
        "future_evidence=0; conflicts=0",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FreshnessDiversityError, OSError, ValueError) as exc:
        print(f"V213_FRESHNESS_DIVERSITY_GATE = FAIL; {exc}", flush=True)
        raise SystemExit(1)
