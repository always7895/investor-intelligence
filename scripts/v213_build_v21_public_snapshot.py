#!/usr/bin/env python3
"""Build the v2.1 public snapshot after diversified v2.1.3 scoring.

Before the immutable snapshot is created, this entrypoint reconciles positive
Serenity advantage factors against the exact source-level audit produced in the
same run. A positive demand-wave, chokepoint, pricing-power,
replacement-friction or TAM-capture factor is retained only when the ticker has
fresh claim evidence from at least two independent source units and domains,
including primary evidence. Unsupported positives are withheld, scores are
recomputed, and every rank-coupled document is atomically reordered.

This is a fail-closed evidence guard, not a source-discovery shortcut. It never
creates a positive factor and never treats market, macro, listing identity,
legal-entity identity or Yahoo observations as company-advantage evidence.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import math
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
BASE_PATH = SCRIPT_DIR / "build_v21_public_snapshot.py"
SCORER_PATH = SCRIPT_DIR / "v213_apply_diversified_operationalization.py"
V212_PATH = ROOT / "data" / "cache" / "v212_top20_report_public_latest.json"
V213_PATH = ROOT / "data" / "cache" / "v213_top20_report_public_latest.json"
FEDERATION_PATH = ROOT / "data" / "cache" / "v213_source_federation_latest.json"
SOURCE_AUDIT_PATH = ROOT / "data" / "cache" / "v213_source_independence_latest.json"
FRESHNESS_POLICY_PATH = ROOT / "config" / "v213-serenity-evidence-freshness-policy.json"

_SPEC = importlib.util.spec_from_file_location("ii_build_v21_public_snapshot", BASE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load base snapshot builder: {BASE_PATH}")
base = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = base
_SPEC.loader.exec_module(base)

_SCORER_SPEC = importlib.util.spec_from_file_location(
    "ii_v213_diversified_snapshot_scorer", SCORER_PATH
)
if _SCORER_SPEC is None or _SCORER_SPEC.loader is None:
    raise RuntimeError(f"Unable to load diversified scorer: {SCORER_PATH}")
scorer = importlib.util.module_from_spec(_SCORER_SPEC)
sys.modules[_SCORER_SPEC.name] = scorer
_SCORER_SPEC.loader.exec_module(scorer)

SCORING_VERSION = "system-operationalization-v2.1.3-diversified"
CATALOG_COUNT = 101
NON_CLAIM_TYPES = {
    "market_return_calculation",
    "independent_market_corroboration",
    "macro_context",
    "regulated_listing_identity",
    "legal_entity_reference",
    "live_legal_entity_registry_observation",
    "independent_legal_entity_identity",
}
NON_CLAIM_FAMILIES = {
    "official_macro",
    "yahoo_market",
    "stooq_market",
    "nasdaq_market",
    "alpha_vantage_market",
    "hfmarketdata_market",
}
CLAIM_PRIMARY_FAMILIES = {"regulator_filing", "issuer_primary", "exchange_sro"}
DEFAULT_SENSITIVE_FACTORS = (
    "demand_wave",
    "chokepoint",
    "pricing_power",
    "replacement_friction",
    "tam_capture",
)


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise base.SnapshotError(f"Invalid latest-evidence input: {path}") from exc


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        delete=False,
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        pending = Path(handle.name)
    pending.replace(path)


def _timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text[:10] + "T00:00:00+00:00")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_claim_source(source: Mapping[str, Any]) -> bool:
    family = str(source.get("family") or "").strip().lower()
    claim_type = str(source.get("claim_type") or "").strip().lower()
    return bool(
        family
        and claim_type
        and family not in NON_CLAIM_FAMILIES
        and not family.endswith("_market")
        and claim_type not in NON_CLAIM_TYPES
    )


def _fresh_claim_support(
    audit_row: Mapping[str, Any],
    *,
    now: datetime,
    maximum_age_days: float,
) -> dict[str, Any]:
    raw_sources = audit_row.get("sources")
    sources = raw_sources if isinstance(raw_sources, list) else []
    units: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for raw in sources:
        if not isinstance(raw, Mapping) or not _is_claim_source(raw):
            continue
        url = str(raw.get("url") or "")
        family = str(raw.get("family") or "").strip().lower()
        domain = str(raw.get("domain") or "").strip().lower()
        claim_type = str(raw.get("claim_type") or "").strip().lower()
        observed = _timestamp(raw.get("as_of"))
        if not url.startswith("https://") or not family or not domain or not claim_type or observed is None:
            continue
        age = (now - observed).total_seconds() / 86400.0
        if age < -(5.0 / 1440.0) or age > maximum_age_days:
            continue
        units.setdefault((family, domain, claim_type), raw)

    values = list(units.values())
    domains = {str(source.get("domain") or "").strip().lower() for source in values}
    primary = [
        source
        for source in values
        if source.get("primary") is True
        or str(source.get("family") or "").strip().lower() in CLAIM_PRIMARY_FAMILIES
    ]
    usable_domains = {value for value in domains if value and value != "unknown"}
    return {
        "unit_count": len(values),
        "domain_count": len(usable_domains),
        "primary_count": len(primary),
        "supported": len(values) >= 2 and len(usable_domains) >= 2 and bool(primary),
    }


def _rating(score: float) -> str:
    if score >= 55:
        return "A"
    if score >= 40:
        return "B"
    if score >= 25:
        return "C"
    return "D"


def _guard_row(
    row: dict[str, Any],
    audit_row: Mapping[str, Any],
    policy: Mapping[str, Any],
    now: datetime,
) -> list[str]:
    factors = row.get("serenity_factors")
    if not isinstance(factors, dict):
        raise base.SnapshotError(f"{row.get('ticker')}: Serenity factors are missing")
    sensitive = tuple(
        str(value)
        for value in policy.get("sensitive_advantage_factors", DEFAULT_SENSITIVE_FACTORS)
        if str(value)
    )
    positive = [name for name in sensitive if float(factors.get(name) or 0.0) > 0.0]
    if not positive:
        return []

    support = _fresh_claim_support(
        audit_row,
        now=now,
        maximum_age_days=float(policy.get("current_state_claim_max_age_days") or 135.0),
    )
    if support["supported"]:
        return []

    for name in positive:
        factors[name] = 0.0
    flags = {
        str(value)
        for value in row.get("risk_flags", [])
        if str(value)
    }
    flags.add("positive_advantage_withheld_until_fresh_multisource_support")
    row["risk_flags"] = sorted(flags)
    raw_score = sum(float(value or 0.0) for value in factors.values())
    penalty = max(0.0, float(row.get("risk_penalty") or 0.0))
    final_score = max(0.0, min(100.0, raw_score - penalty))
    row["serenity_raw_score"] = round(raw_score, 2)
    row["serenity_score"] = round(final_score, 2)
    row["rating"] = _rating(final_score)
    return positive


def _reorder_records(document: dict[str, Any], key: str, order: list[str]) -> dict[str, Any]:
    rows = document.get(key)
    if not isinstance(rows, list) or len(rows) != 20:
        raise base.SnapshotError(f"Rank-coupled document does not contain 20 {key} rows")
    mapping = {
        str(row.get("ticker") or "").strip().upper(): copy.deepcopy(row)
        for row in rows
        if isinstance(row, Mapping) and str(row.get("ticker") or "").strip()
    }
    if set(mapping) != set(order):
        raise base.SnapshotError(f"Rank-coupled {key} membership does not match guarded Top20")
    ordered: list[dict[str, Any]] = []
    for rank, ticker in enumerate(order, 1):
        row = mapping[ticker]
        row["rank"] = rank
        ordered.append(row)
    result = copy.deepcopy(document)
    result[key] = ordered
    return result


def apply_latest_evidence_factor_guard() -> dict[str, Any]:
    rows = _load(base.TOP20_PATH)
    audit = _load(SOURCE_AUDIT_PATH)
    policy = _load(FRESHNESS_POLICY_PATH)
    federation = _load(FEDERATION_PATH)
    if not isinstance(rows, list) or len(rows) != 20:
        raise base.SnapshotError("Latest-evidence factor guard requires exactly 20 Top20 rows")
    audit_rows = audit.get("records") if isinstance(audit, dict) else None
    if not isinstance(audit_rows, list) or len(audit_rows) != 20:
        raise base.SnapshotError("Latest-evidence factor guard requires exactly 20 source-audit rows")
    audit_by_ticker = {
        str(row.get("ticker") or "").strip().upper(): row
        for row in audit_rows
        if isinstance(row, Mapping)
    }
    now = datetime.now(timezone.utc)
    withheld: dict[str, list[str]] = {}
    guarded: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise base.SnapshotError("Top20 row must be an object")
        row = copy.deepcopy(raw)
        ticker = str(row.get("ticker") or "").strip().upper()
        audit_row = audit_by_ticker.get(ticker)
        if not ticker or audit_row is None:
            raise base.SnapshotError(f"Source-audit row missing for {ticker or 'unknown'}")
        removed = _guard_row(row, audit_row, policy, now)
        if removed:
            withheld[ticker] = removed
        guarded.append(row)

    guarded.sort(
        key=lambda item: (
            -float(item.get("serenity_score") or 0.0),
            -float(item.get("data_quality") or 0.0),
            str(item.get("ticker") or ""),
        )
    )
    for rank, row in enumerate(guarded, 1):
        row["rank"] = rank
    order = [str(row["ticker"]).upper() for row in guarded]

    v212 = _reorder_records(_load(V212_PATH), "records", order)
    v213 = _reorder_records(_load(V213_PATH), "records", order)
    federation = _reorder_records(federation, "ticker_sources", order)
    audit = _reorder_records(audit, "records", order)

    _atomic_json(base.TOP20_PATH, guarded)
    _atomic_json(V212_PATH, v212)
    _atomic_json(V213_PATH, v213)
    _atomic_json(FEDERATION_PATH, federation)
    _atomic_json(SOURCE_AUDIT_PATH, audit)
    base.REPORT_PATH.write_text(
        scorer.markdown_report(guarded, federation) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "withheld_ticker_count": len(withheld),
        "withheld": withheld,
        "final_order": order,
    }


def validate_top20(records: Any) -> list[dict[str, Any]]:
    if not isinstance(records, list) or len(records) != 20:
        raise base.SnapshotError("Top 20 must contain exactly 20 records")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(records, 1):
        if not isinstance(raw, dict) or set(raw) != base.RECORD_KEYS:
            raise base.SnapshotError(f"Top 20 record {index} has an invalid closed schema")
        ticker = str(raw.get("ticker") or "").upper()
        if not ticker or ticker in seen or raw.get("rank") != index:
            raise base.SnapshotError("Top 20 ticker/rank contract failed")
        seen.add(ticker)
        for key in ("serenity_score", "serenity_raw_score", "risk_penalty", "data_quality"):
            value = raw.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise base.SnapshotError(f"Top 20 {ticker} has invalid numeric field {key}")
        if not 0 <= float(raw["serenity_score"]) <= 100 or not 0 <= float(raw["data_quality"]) <= 1:
            raise base.SnapshotError(f"Top 20 {ticker} score/quality is out of range")
        if (
            raw.get("scoring_version") != SCORING_VERSION
            or raw.get("line_public_eligible") is not True
            or raw.get("provider_scope") != "public_only"
            or raw.get("owner_watchlist_inherited") is not False
        ):
            raise base.SnapshotError(f"Top 20 {ticker} diversified public boundary is invalid")
        overlay = raw.get("aschenbrenner_overlay")
        if not isinstance(overlay, dict) or overlay.get("included_in_serenity_score") is not False:
            raise base.SnapshotError(f"Top 20 {ticker} overlay boundary is invalid")
        evidence = raw.get("evidence")
        source_ids = {
            str(item.get("source_id") or "")
            for item in evidence
            if isinstance(item, dict) and item.get("source_id")
        } if isinstance(evidence, list) else set()
        if (
            not isinstance(evidence, list) or len(evidence) < 2
            or raw.get("evidence_count") != len(evidence)
            or raw.get("source_count") != len(source_ids)
            or len(source_ids) < 2
        ):
            raise base.SnapshotError(f"Top 20 {ticker} lacks genuine multi-source evidence")
        base.iso_timestamp(raw.get("generated_at"), f"{ticker}.generated_at")
        base.iso_timestamp(raw.get("as_of"), f"{ticker}.as_of")
        result.append({**raw, "ticker": ticker})
    expected = sorted(
        result,
        key=lambda item: (-float(item["serenity_score"]), -float(item["data_quality"]), str(item["ticker"])),
    )
    if result != expected:
        raise base.SnapshotError("Top 20 ordering is not deterministic")
    base.reject_private_keys(result)
    return result


def validate_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise base.SnapshotError("Source plan must be an object")
    inventory = value.get("inventory")
    federation = value.get("live_source_federation")
    scoring = value.get("scoring_methodology")
    if (
        value.get("schema_version") != 1
        or value.get("catalog_count") != CATALOG_COUNT
        or value.get("automatic_activation") is not False
        or value.get("owner_watchlist_inherited") is not False
        or value.get("provider_scope") != "public_only"
        or value.get("line_public_eligible") is not True
        or not isinstance(inventory, dict)
        or inventory.get("source_count") != CATALOG_COUNT
        or inventory.get("runtime_enabled_count") != 0
        or not isinstance(federation, dict)
        or len(federation.get("successful_families") or []) < 5
        or len(federation.get("official_successful_families") or []) < 4
        or float(federation.get("ticker_coverage_ratio") or 0) < 0.8
        or int(federation.get("unresolved_material_conflict_count") or 0) != 0
        or federation.get("yahoo_authoritative") is not False
        or federation.get("catalog_source_count_is_not_live_use") is not True
        or not isinstance(scoring, dict)
        or scoring.get("scoring_version") != SCORING_VERSION
        or scoring.get("official_serenity_formula_claimed") is not False
    ):
        raise base.SnapshotError("Source plan does not preserve the v2.1.3 diversified fail-closed boundary")
    base.reject_private_keys(value)
    return value


def self_test() -> None:
    assert BASE_PATH.is_file()
    assert SCORING_VERSION.startswith("system-operationalization-")
    assert CATALOG_COUNT == 101
    now = datetime.now(timezone.utc)
    stamp = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    row = {
        "ticker": "TEST",
        "serenity_score": 10.0,
        "serenity_raw_score": 12.0,
        "risk_penalty": 2.0,
        "rating": "D",
        "risk_flags": [],
        "serenity_factors": {
            "demand_wave": 0.0,
            "chokepoint": 0.0,
            "pricing_power": 0.0,
            "replacement_friction": 0.0,
            "tam_capture": 6.0,
            "valuation_expectations": 3.0,
            "evidence_quality": 3.0,
        },
    }
    audit = {
        "sources": [{
            "family": "regulator_filing",
            "domain": "sec.gov",
            "claim_type": "xbrl_fact",
            "url": "https://www.sec.gov/test",
            "as_of": stamp,
            "primary": True,
        }]
    }
    removed = _guard_row(
        row,
        audit,
        {
            "current_state_claim_max_age_days": 135,
            "sensitive_advantage_factors": list(DEFAULT_SENSITIVE_FACTORS),
        },
        now,
    )
    assert removed == ["tam_capture"]
    assert row["serenity_factors"]["tam_capture"] == 0.0
    assert row["serenity_score"] == 4.0
    assert "positive_advantage_withheld_until_fresh_multisource_support" in row["risk_flags"]

    identity_row = {
        "ticker": "IDENTITY",
        "serenity_score": 10.0,
        "serenity_raw_score": 12.0,
        "risk_penalty": 2.0,
        "rating": "D",
        "risk_flags": [],
        "serenity_factors": {
            "demand_wave": 0.0,
            "chokepoint": 0.0,
            "pricing_power": 0.0,
            "replacement_friction": 0.0,
            "tam_capture": 6.0,
            "valuation_expectations": 3.0,
            "evidence_quality": 3.0,
        },
    }
    identity_audit = {
        "sources": [
            {
                "family": "regulator_filing",
                "domain": "sec.gov",
                "claim_type": "xbrl_fact",
                "url": "https://www.sec.gov/identity",
                "as_of": stamp,
                "primary": True,
            },
            {
                "family": "secondary_or_other",
                "domain": "gleif.org",
                "claim_type": "legal_entity_reference",
                "url": "https://api.gleif.org/api/v1/lei-records",
                "as_of": stamp,
                "primary": False,
            },
        ]
    }
    identity_removed = _guard_row(
        identity_row,
        identity_audit,
        {
            "current_state_claim_max_age_days": 135,
            "sensitive_advantage_factors": list(DEFAULT_SENSITIVE_FACTORS),
        },
        now,
    )
    assert identity_removed == ["tam_capture"]
    assert identity_row["serenity_factors"]["tam_capture"] == 0.0
    print("V213_DIVERSIFIED_PUBLIC_SNAPSHOT_SELF_TEST = PASS; unsupported_positive_factors=withheld; legal_identity_not_advantage=true")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path, default=base.OUTPUT_PATH)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    guard = apply_latest_evidence_factor_guard()
    print(
        "V213_LATEST_EVIDENCE_FACTOR_GUARD = PASS; "
        f"withheld_tickers={guard['withheld_ticker_count']}; "
        "unsupported_positive_factors=zeroed_before_snapshot",
        flush=True,
    )
    base.validate_top20 = validate_top20
    base.validate_plan = validate_plan
    base.REPORT_PREFIX = "\n".join((
        "<!-- line-public-eligible: true -->",
        "<!-- provider-scope: public_only -->",
        "<!-- owner-watchlist-inherited: false -->",
        f"<!-- scoring-version: {SCORING_VERSION} -->",
        "<!-- scoring-display-label: System operationalization score -->",
        "<!-- official-serenity-formula-claimed: false -->",
        "",
    ))
    envelope = base.build_envelope()
    base.atomic_write(args.output, envelope)
    print(json.dumps({
        "status": "PASS",
        "run_id": envelope["run_id"],
        "output": str(args.output),
        "top20_count": 20,
        "catalog_count": CATALOG_COUNT,
        "scoring_version": SCORING_VERSION,
        "provider_scope": "public_only",
        "withheld_ticker_count": guard["withheld_ticker_count"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
