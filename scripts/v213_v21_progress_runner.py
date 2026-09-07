#!/usr/bin/env python3
"""Progress wrapper and safe preselection bridge for the candidate engine.

The underlying v2.1.0 module remains responsible for deterministic candidate
seeding and SEC extraction. Its historical keyword/margin proxy score is not
allowed to choose v2.1.3 membership. This wrapper replaces that score before the
20-name preselection, and later stages apply the stricter live-source-federated
System operationalization.

SEC evidence freshness is based on the filing/publication date, not the XBRL
period end and never the retrieval timestamp.  The period end is preserved
separately so a newly filed document cannot make an old comparative period look
like current company-state evidence.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import requests
import v21_serenity_top20 as engine

REQUIRED_LIVE_SOURCES = {
    "sec_edgar",
    "world_bank_indicators",
    "bls_public_data",
    "ecb_sdmx",
    "gleif_lei",
    "nasdaq_symbol_directory",
}
PRESELECTION_VERSION = "system-operationalization-v2.1.3-safe-preselection"
SEC_EVIDENCE_TITLE_RE = re.compile(
    r"^SEC XBRL (?P<tag>.+) \((?P<form>[^,]+), (?P<period_end>\d{4}-\d{2}-\d{2})\)$"
)
# Capture unpatched implementations once. main() temporarily replaces engine
# globals, so resolving them dynamically from engine inside a wrapper would
# recurse into the wrapper.
LEGACY_SCORE_CANDIDATE = engine.score_candidate
LEGACY_METRICS = engine.metrics


@dataclass(frozen=True)
class PublicationAwareEvidence:
    """Evidence with distinct filing/publication and financial-period dates."""

    source_id: str
    tier: str
    claim_type: str
    title: str
    url: str
    as_of: str
    publication_date: str = ""
    period_end: str = ""


def _date_text(value: Any) -> str:
    text = str(value or "").strip()[:10]
    if not text:
        return ""
    try:
        return dt.date.fromisoformat(text).isoformat()
    except ValueError:
        return ""


def publication_aware_metrics(
    records: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, float | None], list[PublicationAwareEvidence]]:
    """Run the reviewed metric extractor and correct SEC evidence chronology.

    ``v21_serenity_top20.metrics`` historically emitted an XBRL fact's period
    end as ``as_of``.  That date describes the financial measurement period, not
    when the primary document became public.  This wrapper maps each emitted SEC
    fact back to its Company Facts record and uses the SEC ``filed`` date as the
    evidence publication date.  It never substitutes ``retrieved_at`` or the
    current run time.  When a filing date cannot be matched, the historical
    period-end date is retained so the downstream gate fails closed.
    """

    official_metrics, legacy_evidence = LEGACY_METRICS(records)
    filed_by_exact_key: dict[tuple[str, str, str], str] = {}
    filed_by_fact_key: dict[tuple[str, str], str] = {}

    for raw in records:
        if (
            not isinstance(raw, Mapping)
            or raw.get("record_type") != "company_fact"
            or raw.get("taxonomy") != "us-gaap"
        ):
            continue
        tag = str(raw.get("tag") or "").strip()
        period_end = _date_text(raw.get("end"))
        filed = _date_text(raw.get("filed"))
        url = str(raw.get("record_url") or "").strip()
        if not tag or not period_end or not filed:
            continue
        exact_key = (url, tag, period_end)
        fact_key = (tag, period_end)
        if filed > filed_by_exact_key.get(exact_key, ""):
            filed_by_exact_key[exact_key] = filed
        if filed > filed_by_fact_key.get(fact_key, ""):
            filed_by_fact_key[fact_key] = filed

    normalized: list[PublicationAwareEvidence] = []
    for item in legacy_evidence:
        source_id = str(getattr(item, "source_id", ""))
        title = str(getattr(item, "title", ""))
        url = str(getattr(item, "url", ""))
        legacy_as_of = _date_text(getattr(item, "as_of", ""))
        match = SEC_EVIDENCE_TITLE_RE.fullmatch(title)
        tag = match.group("tag").strip() if match else ""
        period_end = _date_text(match.group("period_end")) if match else legacy_as_of
        filed = ""
        if source_id == "sec_edgar" and tag and period_end:
            filed = filed_by_exact_key.get((url, tag, period_end), "")
            if not filed:
                filed = filed_by_fact_key.get((tag, period_end), "")
        normalized.append(
            PublicationAwareEvidence(
                source_id=source_id,
                tier=str(getattr(item, "tier", "")),
                claim_type=str(getattr(item, "claim_type", "")),
                title=title,
                url=url,
                as_of=filed or legacy_as_of,
                publication_date=filed,
                period_end=period_end,
            )
        )
    return official_metrics, normalized


def validate_v213_policy() -> tuple[dict[str, Any], dict[str, Any]]:
    policy = engine.load_object(engine.POLICY_PATH)
    activation = engine.load_object(engine.ACTIVATION_PATH)
    weights = policy.get("factor_weights")
    expected = {
        "demand_wave", "chokepoint", "pricing_power", "replacement_friction",
        "tam_capture", "valuation_expectations", "evidence_quality",
    }
    if not isinstance(weights, dict) or set(weights) != expected or sum(int(v) for v in weights.values()) != 100:
        raise engine.PipelineError("System operationalization policy must contain seven factors totaling 100")
    if policy.get("official_serenity_formula_claimed") is not False:
        raise engine.PipelineError("The project must not claim an official Serenity formula")
    if policy.get("methodology") != "system-operationalization-v2.1.3-diversified":
        raise engine.PipelineError("v2.1.3 diversified operationalization policy is not active")
    if (
        activation.get("automatic_activation") is not False
        or activation.get("free_only") is not True
        or activation.get("public_data_only") is not True
    ):
        raise engine.PipelineError("Source activation policy is not fail-closed")
    selected = activation.get("selected_sources")
    if not isinstance(selected, dict) or set(selected) != REQUIRED_LIVE_SOURCES:
        raise engine.PipelineError(
            "Reviewed v2.1.3 live federation must include SEC, World Bank, BLS, ECB, GLEIF and Nasdaq symbol identity"
        )
    for source_id, row in selected.items():
        if (
            not isinstance(row, dict)
            or row.get("runtime_enabled") is not True
            or not str(row.get("rights_status") or "").startswith("reviewed_public_access")
            or row.get("adapter_status") != "adapter_reviewed"
            or not isinstance(row.get("gates"), dict)
            or not all(row["gates"].values())
        ):
            raise engine.PipelineError(f"Incomplete reviewed activation: {source_id}")
    yahoo = activation.get("discovery_only_sources", {}).get("yahoo_finance_public_unofficial")
    if (
        not isinstance(yahoo, dict)
        or yahoo.get("runtime_enabled") is not True
        or yahoo.get("authoritative") is not False
        or yahoo.get("raw_payload_redistribution") is not False
    ):
        raise engine.PipelineError("Yahoo/yfinance must remain T3 non-authoritative observation")
    _manifest, sources, _warnings = engine.load_catalog()
    if len(sources) != int(policy["required_catalog_count"]):
        raise engine.PipelineError(
            f"Catalog count changed: {len(sources)} != {policy['required_catalog_count']}"
        )
    by_id = {source.id for source in sources}
    if not REQUIRED_LIVE_SOURCES.issubset(by_id):
        raise engine.PipelineError("Live federation references source IDs outside the reviewed catalog")
    return policy, activation


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _revenue_capture_points(revenue_growth: float | None) -> float:
    if revenue_growth is None or revenue_growth <= 0:
        return 0.0
    if revenue_growth < 0.15:
        return 2.0
    if revenue_growth < 0.35:
        return 4.0
    return 6.0


def safe_preselection_score(
    candidate: Mapping[str, Any],
    official_metrics: Mapping[str, Any],
    evidence: Sequence[Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Produce a bounded shortlist score without unsupported thesis factors.

    No keyword, sector, margin, beta or short-interest value can create
    chokepoint, demand-wave, pricing-power or replacement-friction points.
    Revenue contributes only to provisional realized-capture preselection.
    The historical score is called only to retain schema/category/overlay and a
    low-confidence valuation observation; it is never published.
    """
    legacy = LEGACY_SCORE_CANDIDATE(candidate, official_metrics, evidence, policy)
    revenue = _finite(official_metrics.get("revenue_growth"))
    net_margin = _finite(official_metrics.get("net_margin"))
    debt_equity = _finite(official_metrics.get("debt_to_equity"))
    legacy_factors = legacy.get("serenity_factors") if isinstance(legacy.get("serenity_factors"), dict) else {}
    valuation = min(3.75, max(0.0, float(legacy_factors.get("valuation_expectations") or 0.0)))
    unique_primary_urls = {
        str(getattr(item, "url", ""))
        for item in evidence
        if str(getattr(item, "source_id", "")) == "sec_edgar" and str(getattr(item, "url", ""))
    }
    is_seed = "research_universe_seed" in candidate.get("screeners", [])
    market = candidate.get("market") if isinstance(candidate.get("market"), dict) else {}
    text = engine.keywords(market)
    has_tech = is_seed or engine.contains(text, engine.AI_WORDS) or engine.contains(text, engine.CHOKE_WORDS)
    evidence_quality = 5.0 if is_seed else 4.0 if unique_primary_urls else 1.0
    factors = {
        "demand_wave": 0.0,
        "chokepoint": 0.0,
        "pricing_power": 0.0,
        "replacement_friction": 0.0,
        "tam_capture": _revenue_capture_points(revenue),
        "valuation_expectations": valuation,
        "evidence_quality": evidence_quality,
    }
    risks = {
        "architecture_and_demand_wave_unproven_at_preselection",
        "bottleneck_unproven_without_evidence_bound_graph",
        "pricing_power_unproven_without_contract_or_price_evidence",
        "replacement_friction_unproven_without_switching_or_qualification_evidence",
        "single_market_provider_degraded",
    }
    penalty = 1.0 if is_seed else 2.0
    if not has_tech:
        penalty += 15.0
        risks.add("outside_ai_infrastructure_thematic_scope")
    elif not is_seed:
        if revenue is not None and revenue < 0:
            penalty += 4.0
            risks.add("negative_revenue_growth")
        if net_margin is not None and net_margin < 0:
            penalty += 4.0
            risks.add("negative_net_margin")
        if debt_equity is not None and debt_equity > 2:
            penalty += 3.0
            risks.add("high_debt_to_equity")
    raw = sum(factors.values())
    score = max(0.0, min(100.0, raw - penalty))
    legacy.update({
        "serenity_score": round(score, 2),
        "serenity_raw_score": round(raw, 2),
        "risk_penalty": round(penalty, 2),
        "data_quality": round(0.25 + min(0.25, len(unique_primary_urls) * 0.05), 4),
        "rating": "PROVISIONAL",
        "serenity_factors": factors,
        "risk_flags": sorted(risks),
        "scoring_version": PRESELECTION_VERSION,
    })
    return legacy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()

    original_companyfacts = engine.sec_companyfacts
    original_validate = engine.validate_policy
    original_score = engine.score_candidate
    original_metrics = engine.metrics
    counter = {"value": 0}

    def progress_companyfacts(candidate, policy, http, headers):
        counter["value"] += 1
        limit = int(policy.get("sec_candidate_limit", 50))
        ticker = str(candidate.get("ticker") or "?")
        print(
            f"II_PROGRESS Top20 SEC companyfacts {counter['value']}/{limit} | {ticker}",
            flush=True,
        )
        return original_companyfacts(candidate, policy, http, headers)

    engine.sec_companyfacts = progress_companyfacts
    engine.validate_policy = validate_v213_policy
    engine.metrics = publication_aware_metrics
    engine.score_candidate = safe_preselection_score
    try:
        print("II_PROGRESS Top20 candidate discovery starting; Yahoo is T3 seed only", flush=True)
        result = engine.run(synthetic=args.synthetic)
        print("II_PROGRESS SEC evidence chronology normalized: filing_date!=period_end; retrieval_time_not_used", flush=True)
        print("II_PROGRESS safe preselection complete; proxy-heavy factors excluded; diversified postprocessor required", flush=True)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0
    except (engine.PipelineError, OSError, ValueError, requests.RequestException) as exc:
        print(f"V2.1 candidate engine failed: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        engine.sec_companyfacts = original_companyfacts
        engine.validate_policy = original_validate
        engine.metrics = original_metrics
        engine.score_candidate = original_score


if __name__ == "__main__":
    raise SystemExit(main())
