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
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return ""
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        return ""


def _money_unit(record: Mapping[str, Any] | None) -> str:
    unit = record.get('unit') if record else None
    return unit if isinstance(unit, str) and re.fullmatch(r'[A-Z]{3}', unit) else ''


def _same_filing_basis(left, right, *, duration: bool) -> bool:
    if not left or not right or not _money_unit(left) or _money_unit(left) != _money_unit(right):
        return False
    if left.get('end') != right.get('end'):
        return False
    if duration:
        if not _date_text(left.get('start')) or left.get('start') != right.get('start'):
            return False
    elif left.get('start') or right.get('start'):
        return False
    accession = left.get('accession_number')
    return (isinstance(accession, str) and bool(re.fullmatch(r'[0-9]{10}-[0-9]{2}-[0-9]{6}', accession))
            and accession == right.get('accession_number')
            and isinstance(left.get('record_url'), str) and bool(left['record_url'])
            and left['record_url'] == right.get('record_url'))


def _adjacent_annual_basis(current, prior) -> bool:
    if (not _money_unit(current) or _money_unit(current) != _money_unit(prior)
            or current.get('tag') != prior.get('tag')):
        return False
    try:
        start, end = (dt.date.fromisoformat(_date_text(current.get(k))) for k in ('start', 'end'))
        old_start, old_end = (dt.date.fromisoformat(_date_text(prior.get(k))) for k in ('start', 'end'))
    except ValueError:
        return False
    # Reported annual comparisons (52/53-week years allowed), not normalized growth.
    return ((end-start).days+1 in (364, 365, 366, 371) and (old_end-old_start).days+1 in (364, 365, 366, 371)
            and (start-old_end).days == 1)


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

    filed_by_exact_key: dict[tuple[str, str, str], str] = {}

    for raw in records:
        if (
            not isinstance(raw, Mapping)
            or raw.get("record_type") != "company_fact"
            or raw.get("taxonomy") != "us-gaap"
        ):
            continue
        # SEC wire dates are date-only; never rescue prefixes before the legacy
        # extractor can clip a malformed period into a seemingly valid title.
        if not _date_text(raw.get("end")):
            raise engine.PipelineError("SEC_FACT_PERIOD_DATE_INVALID")
        for field in ("start", "filed"):
            value = raw.get(field)
            if value is not None and value != "" and not _date_text(value):
                raise engine.PipelineError("SEC_FACT_SOURCE_DATE_INVALID")
        tag = str(raw.get("tag") or "").strip()
        period_end = _date_text(raw.get("end"))
        filed = _date_text(raw.get("filed"))
        url = str(raw.get("record_url") or "").strip()
        if not tag or not period_end or not filed:
            continue
        exact_key = (url, tag, period_end)
        if exact_key in filed_by_exact_key and filed_by_exact_key[exact_key] != filed:
            raise engine.PipelineError("SEC_FACT_PUBLICATION_DATE_CONFLICT")
        filed_by_exact_key[exact_key] = filed

    official_metrics, legacy_evidence = LEGACY_METRICS(records)
    # Preserve arithmetic/score weights, but do not divide unrelated financial bases.
    revenue_tags = ('RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet')
    revenue = engine.latest_value(records, revenue_tags, duration=True)
    for metric, tags in (('gross_margin', ('GrossProfit',)), ('operating_margin', ('OperatingIncomeLoss',)),
                         ('net_margin', ('NetIncomeLoss', 'ProfitLoss'))):
        numerator = engine.latest_value(records, tags, duration=True)
        if not _same_filing_basis(numerator, revenue, duration=True):
            official_metrics[metric] = None
    equity = engine.latest_value(records, ('StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'), duration=False)
    debts = engine.latest_records(records, ('LongTermDebtCurrent', 'LongTermDebtNoncurrent', 'LongTermDebt'))
    if not _same_filing_basis(debts[0] if debts else None, equity, duration=False):
        official_metrics['debt_to_equity'] = None
    annual = engine.annual_values(records, revenue_tags)
    if len(annual) < 2 or not _adjacent_annual_basis(annual[0], annual[1]):
        official_metrics['revenue_growth'] = None
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


def profitability_evidence(
    records: Sequence[Mapping[str, Any]], *, cik: str, as_of: str,
) -> dict[str, Any]:
    """Report-facing projection of the reviewed metrics, not a new scorer.

    Keep every operand, including both annual revenues, without the legacy
    five-citation cap. Companyfacts and filings are ONE disclosure lineage.
    These local candidates are not source refresh or publication receipts.
    """
    if not isinstance(cik, str) or not re.fullmatch(r'[0-9]{10}', cik) or int(cik) == 0:
        raise engine.PipelineError('PROFIT_CIK_INVALID')
    try:
        cutoff = dt.datetime.fromisoformat(as_of.replace('Z', '+00:00'))
        if cutoff.tzinfo is None:
            raise ValueError()
        cutoff_day = cutoff.astimezone(dt.timezone.utc).date().isoformat()
    except (AttributeError, TypeError, ValueError):
        raise engine.PipelineError('PROFIT_CUTOFF_INVALID') from None
    metrics, _ = publication_aware_metrics(records)
    revenue_tags = ('RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet')
    revenue = engine.latest_value(records, revenue_tags, duration=True)
    annual = engine.annual_values(records, revenue_tags)
    pairs = {
        'revenue_growth': (annual[0] if annual else None, annual[1] if len(annual) > 1 else None, 'numerator / denominator - 1'),
        'gross_margin': (engine.latest_value(records, ('GrossProfit',), duration=True), revenue, 'numerator / denominator'),
        'operating_margin': (engine.latest_value(records, ('OperatingIncomeLoss',), duration=True), revenue, 'numerator / denominator'),
        'net_margin': (engine.latest_value(records, ('NetIncomeLoss', 'ProfitLoss'), duration=True), revenue, 'numerator / denominator'),
    }
    fields = ('cik', 'taxonomy', 'tag', 'unit', 'value', 'start', 'end', 'filed', 'form', 'fiscal_year', 'accession_number', 'record_url')
    identity = ('cik', 'taxonomy', 'tag', 'unit', 'start', 'end', 'filed', 'accession_number', 'record_url')

    def operand(raw):
        if raw is None:
            return None, 'MISSING_OPERAND'
        value = raw.get('value')
        start, end, filed = (_date_text(raw.get(key)) for key in ('start', 'end', 'filed'))
        url, accession, tag, unit = (raw.get(key) for key in ('record_url', 'accession_number', 'tag', 'unit'))
        # Only known SEC public locators; do not persist arbitrary/credential URLs.
        archive = re.fullmatch(r'https://www\.sec\.gov/Archives/edgar/data/([0-9]+)/([0-9]{18})/([A-Za-z0-9._-]*)', url) if isinstance(url, str) else None
        url_safe = isinstance(url, str) and (
            url == f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'
            or bool(archive and archive[1] == str(int(cik)) and isinstance(accession, str)
                    and archive[2] == accession.replace('-', '') and archive[3] not in {'.', '..'}))
        if (raw.get('cik') != cik or raw.get('taxonomy') != 'us-gaap'
                or not isinstance(tag, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9]{0,159}', tag)
                or not (unit is None or isinstance(unit, str) and bool(re.fullmatch(r'[A-Z]{3}', unit)))
                or type(value) not in (int, float) or not (-9007199254740991 <= value <= 9007199254740991)
                or not start or not end or not filed or not start <= end <= filed <= cutoff_day
                or not isinstance(accession, str) or not re.fullmatch(r'[0-9]{10}-[0-9]{2}-[0-9]{6}', accession)
                or not url_safe or raw.get('form') not in {'10-K', '10-K/A', '10-Q', '10-Q/A', '20-F', '40-F'}
                or type(raw.get('fiscal_year')) is not int or not 1900 <= raw['fiscal_year'] <= 9999):
            return None, 'INVALID_OPERAND'
        # Stable sort order must not choose a convenient value from a conflict.
        if any(all(other.get(key) == raw.get(key) for key in identity)
               and (type(other.get('value')) not in (int, float) or other.get('value') != value)
               for other in records if other.get('record_type') == 'company_fact'):
            return None, 'CONFLICTING_OPERAND'
        return {key: raw.get(key) for key in fields}, None

    result = {}
    for name, (numerator, denominator, formula) in pairs.items():
        a, a_error = operand(numerator)
        b, b_error = operand(denominator)
        value = metrics[name]
        reason = a_error or b_error
        if reason is None and (value is None or not math.isfinite(value)):
            reason = 'WITHHELD_NOT_COMPARABLE_OR_NONPOSITIVE_DENOMINATOR'
        result[name] = {
            'status': reason or 'AVAILABLE', 'value': value if reason is None else None,
            'value_unit': 'ratio', 'formula': formula, 'numerator': a, 'denominator': b,
        }
    return {
        'schema_version': 1, 'status': 'CANDIDATE_NOT_PUBLICATION_QUALIFIED',
        'cik': cik, 'as_of_cutoff': as_of, 'provider_scope': 'public_only',
        'publication_eligible': False, 'source_retrieved_at': None,
        'source_lineage': 'issuer_filing_via_sec_companyfacts',
        'source_refresh_verified': False, 'metrics': result,
        'limitations': ['COMPANYFACTS_CONTEXT_AND_RESTATEMENT_REVIEW_INCOMPLETE',
                        'NOT_INDEPENDENT_COMPANY_CLAIM_CORROBORATION',
                        'NO_CASHFLOW_CAPACITY_ORDERS_DILUTION_OR_VALUATION_BRIDGE'],
    }


def validate_v213_policy() -> tuple[dict[str, Any], dict[str, Any]]:
    policy = engine.load_object(engine.POLICY_PATH)
    activation = engine.load_object(engine.ACTIVATION_PATH)
    # Admit the existing broad screeners only; a named sector must not reserve
    # pre-SEC candidate capacity. Discovery is still T3, not final research.
    broad_screeners = {"undervalued_growth_stocks", "most_actives", "day_gainers"}
    screeners = policy.get("candidate_screeners")
    if (not isinstance(screeners, list) or not screeners
            or any(not isinstance(row, dict) or set(row) != {"name", "weight"}
                   or not isinstance(row.get("name"), str) or row["name"] not in broad_screeners
                   or type(row.get("weight")) not in (int, float)
                   or not math.isfinite(row["weight"]) or row["weight"] <= 0 for row in screeners)
            or len({row["name"] for row in screeners}) != len(screeners)):
        raise engine.PipelineError("V213_DISCOVERY_SCREENER_POLICY_INVALID")
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
    evidence_quality = 4.0 if unique_primary_urls else 1.0
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
    penalty = 2.0
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
