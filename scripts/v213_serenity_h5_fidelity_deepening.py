#!/usr/bin/env python3
"""H5 fidelity-deepening shadow adapter.

Consumes the passed H4 v4 semantic shadow report and adds four evidence layers that
matter to a high-fidelity reconstruction of Serenity's *public* logic:

1. financing-program lineage (rather than naive ATM mention/event counting);
2. qualified-substitute and capacity-tightness context;
3. official non-US financing / architecture evidence;
4. an append-only, hash-chained history of directly verified public Serenity views.

This module is shadow-only. It never changes Production rankings and never lets a
Serenity source view substitute for factual dependency evidence.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v212_local_llm_gateway as sources

MAX_BODY = 3_000_000
DEFAULT_OUTPUT = ROOT / "data" / "cache" / "v213_serenity_h5_shadow_latest.json"
DEFAULT_HISTORY = ROOT / "data" / "cache" / "v213_serenity_source_history.jsonl"

AAOI_10Q = "https://www.sec.gov/Archives/edgar/data/1158114/000143774926026278/aaoi20260630_10q.htm"
AXTI_2024_10K = "https://www.sec.gov/Archives/edgar/data/1051627/000155837025003004/axti-20241231x10k.htm"
AXTI_2026_10Q = "https://www.sec.gov/Archives/edgar/data/1051627/000143774926027677/axti20260630_10q.htm"
AXTI_COHERENT_8K = "https://www.sec.gov/Archives/edgar/data/1051627/000143774926022557/axti20260630_8k.htm"
AXTI_LUMENTUM_8K = "https://www.sec.gov/Archives/edgar/data/1051627/000143774926024883/axti20260715_8k.htm"
AXTI_CASELA_8K = "https://www.sec.gov/Archives/edgar/data/1051627/000143774926020978/axti20260615_8k.htm"

SIVE_APRIL_ISSUE = "https://www.sivers-semiconductors.com/press/sivers-semiconductors-has-resolved-on-a-directed-share-issue-of-shares-amounting-to-approximately-125-msek/"
SIVE_JUNE_ISSUE = "https://www.sivers-semiconductors.com/press/sivers-semiconductors-has-resolved-on-a-directed-share-issue-of-shares-amounting-to-approximately-sek-700-million/"
SIVE_Q1 = "https://www.sivers-semiconductors.com/2026/05/29/vickram-vathulyas-letter-to-shareholders-interim-report-q1-2026/"
SIVE_Q2 = "https://www.sivers-semiconductors.com/press/sivers-semiconductors-reports-q2-2026-results-as-product-growth-record-pipeline-and-customer-ramps-position-company-for-growth-acceleration/"
SIVE_SHARE_COUNT = "https://www.sivers-semiconductors.com/press/change-in-the-total-number-of-shares-and-votes-in-sivers-semiconductors-ab-11/"

SOITEC_PHOTONICS = "https://www.soitec.com/home/products/product-platforms/photonics-soi"
SOITEC_SMARTCUT = "https://www.soitec.com/home/technology/innovation/smart-cut"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

# Direct public X posts verified during development.  These rows are source views,
# not factual supply-chain proof.  Paraphrases intentionally avoid pretending the
# account owner published a mechanical score or private decision model.
SERENITY_SOURCE_SEEDS: list[dict[str, Any]] = [
    {
        "source_id": "x-2013947011490615486",
        "source_url": "https://x.com/aleabitoreddit/status/2013947011490615486",
        "published_at": "2026-01-21T12:09:00Z",
        "scope": "methodology",
        "tickers": [],
        "view_type": "financing_disconfirmation",
        "paraphrase": "Repeated discounted offerings or ATM dilution can destroy retail equity capture; financing structure is a first-class disconfirmation check.",
        "verification": "development_verified_direct_public_x",
    },
    {
        "source_id": "x-2021053268420591653",
        "source_url": "https://x.com/aleabitoreddit/status/2021053268420591653",
        "published_at": "2026-02-10T02:47:00Z",
        "scope": "methodology",
        "tickers": [],
        "view_type": "short_interest_deemphasized",
        "paraphrase": "Short interest is not a primary thesis input when fundamentals are strong; some reported short interest can reflect convertible hedging.",
        "verification": "development_verified_direct_public_x",
    },
    {
        "source_id": "x-2033889361801175094",
        "source_url": "https://x.com/aleabitoreddit/status/2033889361801175094",
        "published_at": "2026-03-17T07:53:00Z",
        "scope": "ticker_view",
        "tickers": ["AXTI", "SOI", "TSEM", "COHR", "SIVE", "AAOI"],
        "view_type": "relative_public_view",
        "paraphrase": "Publicly favored semi-monopoly-like substrate exposure in AXTI/SOI; described TSEM/COHR as steady compounders and SIVE as highest-upside, with AAOI and AXTI also high-upside.",
        "verification": "development_verified_direct_public_x",
    },
    {
        "source_id": "x-2034752613246542215",
        "source_url": "https://x.com/aleabitoreddit/status/2034752613246542215",
        "published_at": "2026-03-19T17:03:00Z",
        "scope": "supercycle",
        "tickers": ["AXTI"],
        "view_type": "photonics_supercycle",
        "paraphrase": "Framed the trade as riding Photonics and Memory supercycles, explicitly including AXTI on the photonics side.",
        "verification": "development_verified_direct_public_x",
    },
]

HARD_DEPENDENCY_ROLES = {"SINGLE_SOURCE", "SEMI_MONOPOLY", "QUALIFICATION_CONSTRAINED", "CAPACITY_BOTTLENECK"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _visible_text(raw: str) -> str:
    text = re.sub(r"(?is)<(?:script|style|noscript).*?>.*?</(?:script|style|noscript)>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def fetch_text(url: str, *, timeout: tuple[int, int] = (10, 40)) -> str:
    host = (urlparse(url).hostname or "").lower()
    headers = sources.sec_headers() if host.endswith("sec.gov") else BROWSER_HEADERS
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    raw = response.content[:MAX_BODY].decode(response.encoding or "utf-8", errors="replace")
    return _visible_text(raw)


def _must(pattern: str, text: str, label: str, flags: int = re.I | re.S) -> re.Match[str]:
    match = re.search(pattern, text, flags)
    if not match:
        raise ValueError(f"required evidence not found: {label}")
    return match


def aaoi_financing_lineage(text: str) -> dict[str, Any]:
    # The lineage is two ATM programs, not three independent programs.  The first
    # program was created, upsized, then completed; the second program is separate.
    _must(r"On February 26, 2026.{0,220}First EDA.{0,260}\$?250\s*million", text, "AAOI First EDA")
    _must(r"On March 12, 2026.{0,220}Amendment No\.\s*1.{0,260}250 million to \$?500 million", text, "AAOI First EDA amendment")
    completion = _must(r"On April 2, 2026.{0,260}completed the First ATM Offering.{0,160}4\.8 million shares.{0,180}approximately \$490 million", text, "AAOI First ATM completion")
    _must(r"On May 14, 2026.{0,220}Second.{0,40}EDA.{0,260}\$?600 million", text, "AAOI Second EDA")
    balance = _must(r"84,386\s+and\s+74,998\s+shares issued and outstanding at June 30, 2026 and December 31, 2025", text, "AAOI share-count change")
    total = _must(r"Total\s+7,775,523.{0,180}\$\s*1,049,814.{0,180}\$\s*20,996.{0,180}\$\s*1,028,817", text, "AAOI ATM total")
    del completion, balance, total

    shares_issued = 7_775_523
    shares_2025 = 74_998_000
    shares_2026 = 84_386_000
    return {
        "program_count": 2,
        "amendment_count": 1,
        "completed_program_count": 1,
        "programs": [
            {
                "program": "First ATM Offering",
                "entered_at": "2026-02-26",
                "initial_authorization_usd": 250_000_000,
                "amended_at": "2026-03-12",
                "amended_authorization_usd": 500_000_000,
                "completed_at": "2026-04-02",
                "completion_net_proceeds_usd_approx": 490_000_000,
            },
            {
                "program": "Second ATM Offering",
                "entered_at": "2026-05-14",
                "authorization_usd": 600_000_000,
            },
        ],
        "shares_sold_through_atm_h1_2026": shares_issued,
        "gross_proceeds_usd_h1_2026": 1_049_814_000,
        "net_proceeds_usd_h1_2026": 1_028_817_000,
        "shares_outstanding_2025_12_31": shares_2025,
        "shares_outstanding_2026_06_30": shares_2026,
        "share_count_growth_pct": round((shares_2026 / shares_2025 - 1.0) * 100.0, 2),
        "material_equity_capture_pressure": True,
        "repeated_financing_programs": True,
        "killer_basis": "two_distinct_atm_programs_plus_actual_material_share_issuance",
        "evidence_url": AAOI_10Q,
    }


def axti_substitute_capacity_map(text_2024: str, text_2026: str, coherent: str, lumentum: str, casela: str) -> dict[str, Any]:
    _must(r"customer or prospective customer has at least two qualified substrate suppliers", text_2024, "AXTI typical qualified suppliers")
    _must(r"Sumitomo and JX also compete with us in the InP market", text_2026, "AXTI InP competitors")
    _must(r"three \(3\) years.{0,260}6-inch indium phosphide", coherent, "AXTI-Coherent 6-inch InP agreement")
    _must(r"prepayment of US\$22,288,500", coherent, "AXTI-Coherent prepayment")
    _must(r"six \(6\) year period", lumentum, "AXTI-Lumentum six-year reservation")
    _must(r"January 1, 2027 through December 31, 2027", casela, "AXTI-Casela 2027 commitment")

    return {
        "known_inp_competitors": ["Sumitomo Electric", "JX"],
        "typical_customer_qualified_supplier_floor": 2,
        "qualified_substitutes_exist": True,
        "effective_capacity_substitutability_at_current_ramp": "UNPROVEN",
        "capacity_tightness_candidate": True,
        "capacity_tightness_reason": "multiple material multi-year/fixed-quantity capacity commitments coexist with disclosed qualified substitutes",
        "capacity_series": [
            {
                "as_of": "2024-12-31",
                "event": "customers_typically_have_at_least_two_qualified_substrate_suppliers",
                "source": AXTI_2024_10K,
            },
            {
                "as_of": "2026-06-11",
                "event": "Casela_2027_fixed_quantity_InP_supply_priority_and_prepayment",
                "source": AXTI_CASELA_8K,
            },
            {
                "as_of": "2026-06-25",
                "event": "Coherent_three_year_6inch_InP_capacity_commitment_with_22.2885m_prepayment",
                "source": AXTI_COHERENT_8K,
            },
            {
                "as_of": "2026-07-26",
                "event": "Lumentum_six_year_InP_capacity_reservation",
                "source": AXTI_LUMENTUM_8K,
            },
        ],
        "dependency_promotion_allowed": False,
        "reason_not_promoted": "qualified alternatives are disclosed and effective available capacity/qualification at the current ramp is not independently proven",
    }


def sive_financing_and_capacity(april: str, june: str, q1: str, q2: str, share_count: str) -> dict[str, Any]:
    _must(r"8,620,000 ordinary shares.{0,220}SEK 14\.5", april, "SIVE April directed issue")
    _must(r"dilution of approximately 2\.5 percent", april, "SIVE April dilution")
    _must(r"12,280,701 ordinary shares.{0,220}SEK 57 per share", june, "SIVE June directed issue")
    _must(r"discount of approximately 9\.7 percent", june, "SIVE June discount")
    _must(r"dilution of approximately 3\.3 percent", june, "SIVE June dilution")
    _must(r"qual builds and production readiness is on track.{0,160}Q4 2026", q1, "SIVE Q4 2026 production readiness")
    _must(r"multi-year imbalance.{0,180}demand-supply.{0,240}optical networking", q1, "SIVE optical demand-supply imbalance")
    _must(r"Product Revenue Increases 18% Year-Over-Year", q2, "SIVE Q2 product growth")
    _must(r"directed share issues amounting to approximately SEK 825 m", q2, "SIVE Q2 total directed capital")
    _must(r"355,081,317 ordinary shares", share_count, "SIVE July share count")

    return {
        "financing_events": [
            {
                "as_of": "2026-04-16",
                "type": "directed_institutional_share_issue",
                "gross_sek": 125_000_000,
                "new_shares": 8_620_000,
                "reported_fully_diluted_dilution_pct": 2.5,
                "pricing_context": "1.3% discount to 10-day VWAP and 29.8% premium to 30-day VWAP",
                "source": SIVE_APRIL_ISSUE,
            },
            {
                "as_of": "2026-07-01",
                "type": "accelerated_bookbuild_directed_share_issue",
                "gross_sek": 700_000_000,
                "new_shares": 12_280_701,
                "reported_fully_diluted_dilution_pct": 3.3,
                "pricing_context": "9.7% discount to June 30 closing price; multiple-times oversubscribed institutional bookbuild",
                "source": SIVE_JUNE_ISSUE,
            },
        ],
        "q2_reported_directed_equity_capital_sek": 825_000_000,
        "equity_capture_pressure": "MATERIAL",
        "toxic_financing_proven": False,
        "toxicity_reason": "material dilution is factual, but current official terms show institutional bookbuilding and do not by themselves prove a retail-to-insider value-transfer pattern",
        "capacity_series": [
            {
                "as_of": "2026-05-29",
                "event": "LiDAR_qualification_builds_and_Q4_2026_production_readiness_on_track",
                "source": SIVE_Q1,
            },
            {
                "as_of": "2026-05-29",
                "event": "management_reports_multi_year_optical_networking_demand_supply_imbalance_and_relevant_manufacturing_capacity_strategy",
                "source": SIVE_Q1,
            },
            {
                "as_of": "2026-08-27",
                "event": "product_revenue_up_18pct_yoy_and_customer_production_ramps",
                "source": SIVE_Q2,
            },
        ],
        "shares_outstanding_2026_07_31": 355_081_317,
        "source": SIVE_SHARE_COUNT,
    }


def soitec_architecture(photonics: str, smartcut: str) -> dict[str, Any]:
    _must(r"Photonics-SOI.{0,220}silicon-on-insulator", photonics, "Soitec Photonics-SOI")
    _must(r"data center interconnect", photonics, "Soitec photonics datacom use")
    _must(r"Smart Cut", smartcut, "Soitec Smart Cut")
    _must(r"silicon photonics", smartcut, "Soitec Smart Cut silicon photonics")
    return {
        "current": "Photonics-SOI engineered substrates / silicon photonics",
        "as_of": now_iso(),
        "evidence_urls": [SOITEC_PHOTONICS, SOITEC_SMARTCUT],
        "architecture_evidence_bound": True,
        "dependency_promotion_allowed": False,
        "reason_not_promoted": "official product/technology evidence establishes relevance, not market exclusivity or effective substitute scarcity",
    }


def _history_payload(row: Mapping[str, Any], previous_hash: str) -> str:
    base = {key: value for key, value in row.items() if key not in {"previous_hash", "record_hash"}}
    canonical = json.dumps(base, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return previous_hash + "\n" + canonical


def _record_hash(row: Mapping[str, Any], previous_hash: str) -> str:
    return hashlib.sha256(_history_payload(row, previous_hash).encode("utf-8")).hexdigest()


def read_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    previous = "GENESIS"
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("previous_hash") != previous:
            raise ValueError(f"source-history chain broken at line {number}")
        expected = _record_hash(row, previous)
        if row.get("record_hash") != expected:
            raise ValueError(f"source-history record hash mismatch at line {number}")
        rows.append(row)
        previous = expected
    return rows


def ensure_source_history(path: Path) -> dict[str, Any]:
    rows = read_history(path)
    existing = {str(row.get("source_id")) for row in rows}
    previous = rows[-1]["record_hash"] if rows else "GENESIS"
    appended = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for seed in SERENITY_SOURCE_SEEDS:
            if seed["source_id"] in existing:
                continue
            row = dict(seed)
            row["history_appended_at"] = now_iso()
            row["previous_hash"] = previous
            row["record_hash"] = _record_hash(row, previous)
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            previous = row["record_hash"]
            appended += 1
    verified = read_history(path)
    return {
        "path": str(path),
        "entries": len(verified),
        "appended": appended,
        "chain_verified": True,
        "latest_hash": verified[-1]["record_hash"] if verified else "GENESIS",
    }


def source_views_for_ticker(ticker: str) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    for seed in SERENITY_SOURCE_SEEDS:
        if seed["scope"] == "methodology" or ticker in seed.get("tickers", []):
            views.append({
                "source_id": seed["source_id"],
                "source_url": seed["source_url"],
                "published_at": seed["published_at"],
                "scope": seed["scope"],
                "view_type": seed["view_type"],
                "paraphrase": seed["paraphrase"],
                "factual_dependency_proof": False,
            })
    return views


def _find_row(document: Mapping[str, Any], ticker: str) -> dict[str, Any]:
    for row in document.get("results") or []:
        if isinstance(row, Mapping) and str(row.get("ticker")) == ticker:
            return row  # type: ignore[return-value]
    raise ValueError(f"missing ticker in H4 v4 report: {ticker}")


def _append_warning(row: dict[str, Any], warning: str) -> None:
    warnings = list(row.get("warnings") or [])
    if warning not in warnings:
        warnings.append(warning)
    row["warnings"] = warnings


def apply_h5(h4: Mapping[str, Any], history_path: Path) -> dict[str, Any]:
    output = copy.deepcopy(dict(h4))
    rows = output.get("results")
    if not isinstance(rows, list) or len(rows) != 7:
        raise ValueError("H4 v4 seven-symbol result set missing")

    history = ensure_source_history(history_path)

    aaoi = _find_row(output, "AAOI")
    aaoi_text = fetch_text(AAOI_10Q)
    aaoi_lineage = aaoi_financing_lineage(aaoi_text)
    aaoi["h5_financing_lineage"] = aaoi_lineage
    aaoi["atm_event_audit"] = {
        "distinct_program_count": aaoi_lineage["program_count"],
        "program_amendment_count": aaoi_lineage["amendment_count"],
        "repeated_distinct_programs": aaoi_lineage["repeated_financing_programs"],
        "shares_sold_through_atm_h1_2026": aaoi_lineage["shares_sold_through_atm_h1_2026"],
        "net_proceeds_usd_h1_2026": aaoi_lineage["net_proceeds_usd_h1_2026"],
        "semantic_rule": "distinct financing programs are separated from amendments/completions; killer is supported by actual material issuance",
    }
    aaoi["serenity_source_views"] = source_views_for_ticker("AAOI")
    aaoi["h5_source_delta"] = {
        "requires_updated_serenity_view": True,
        "reason": "the positive relative public view predates the May 2026 second ATM and more than $1.0B of H1 2026 net ATM proceeds",
        "do_not_infer_current_view": True,
    }

    axti = _find_row(output, "AXTI")
    axti_map = axti_substitute_capacity_map(
        fetch_text(AXTI_2024_10K), fetch_text(AXTI_2026_10Q), fetch_text(AXTI_COHERENT_8K), fetch_text(AXTI_LUMENTUM_8K), fetch_text(AXTI_CASELA_8K)
    )
    axti["h5_qualified_substitute_capacity"] = axti_map
    axti["serenity_source_views"] = source_views_for_ticker("AXTI")
    axti["h5_source_delta"] = {
        "requires_updated_serenity_view": True,
        "reason": "the March public semi-monopoly/supercycle view predates multiple June-July 2026 InP capacity reservation commitments; disclosed qualified substitutes still prevent a hard-dependency conclusion",
        "do_not_infer_current_view": True,
    }
    _append_warning(axti, "Issuer filings disclose multiple qualified substrate suppliers and Sumitomo/JX InP competition; semi-monopoly source view requires current effective-capacity corroboration")

    sive = _find_row(output, "SIVE")
    sive_context = sive_financing_and_capacity(
        fetch_text(SIVE_APRIL_ISSUE), fetch_text(SIVE_JUNE_ISSUE), fetch_text(SIVE_Q1), fetch_text(SIVE_Q2), fetch_text(SIVE_SHARE_COUNT)
    )
    sive["h5_financing_capacity"] = sive_context
    sive["serenity_source_views"] = source_views_for_ticker("SIVE")
    sive["h5_source_delta"] = {
        "requires_updated_serenity_view": True,
        "reason": "the March high-upside public view predates both material 2026 directed equity raises and subsequent customer/GF production-ramp evidence",
        "do_not_infer_current_view": True,
        "delta_direction": "MIXED",
    }
    _append_warning(sive, "Material 2026 directed equity raises are real but their toxicity is not proven; separate dilution magnitude from financing-quality judgment")

    soi = _find_row(output, "SOI")
    soi_arch = soitec_architecture(fetch_text(SOITEC_PHOTONICS), fetch_text(SOITEC_SMARTCUT))
    fidelity = soi.setdefault("public_logic_fidelity", {})
    fidelity["architecture"] = {key: soi_arch[key] for key in ("current", "as_of", "evidence_urls")}
    fidelity["architecture_evidence_bound"] = True
    soi["h5_official_architecture"] = soi_arch
    soi["serenity_source_views"] = source_views_for_ticker("SOI")
    soi["h5_source_delta"] = {
        "requires_updated_serenity_view": False,
        "reason": "official Soitec sources establish silicon-photonics substrate relevance but do not independently prove the public semi-monopoly characterization",
        "do_not_infer_exclusivity": True,
    }

    for ticker in ("TSEM", "COHR", "LITE"):
        row = _find_row(output, ticker)
        row["serenity_source_views"] = source_views_for_ticker(ticker)
        row.setdefault("h5_source_delta", {"requires_updated_serenity_view": False, "do_not_infer_current_view": True})

    # Source views are opinions/observations and may never promote a dependency role.
    hard = []
    for row in rows:
        role = str((row.get("public_logic_fidelity") or {}).get("dependency_role"))
        if role in HARD_DEPENDENCY_ROLES:
            hard.append(str(row.get("ticker")))
    if hard:
        raise ValueError("H5 unexpectedly produced hard dependency roles: " + ",".join(hard))

    output["generated_at"] = now_iso()
    output["h5_fidelity_deepening_shadow_only"] = True
    output["source_history"] = history
    output["summary"] = dict(output.get("summary") or {})
    output["summary"].update({
        "h5_fidelity_deepening_applied": True,
        "production_ranking_changed": False,
        "hard_dependency_count": 0,
        "aaoi_distinct_financing_programs": aaoi_lineage["program_count"],
        "axti_qualified_substitutes_disclosed": axti_map["qualified_substitutes_exist"],
        "axti_capacity_tightness_candidate": axti_map["capacity_tightness_candidate"],
        "sive_material_financing_context_added": True,
        "soi_official_photonics_architecture_added": True,
        "source_history_chain_verified": history["chain_verified"],
    })
    return output


def self_test() -> None:
    aaoi_fixture = (
        "On February 26, 2026, the Company entered into an Equity Distribution Agreement (the First EDA) having an aggregate offering price of up to $250 million. "
        "On March 12, 2026, the Company entered into Amendment No. 1 to the First EDA to increase the aggregate offering price from $250 million to $500 million. "
        "On April 2, 2026, the Company completed the First ATM Offering and sold approximately 4.8 million shares, providing proceeds of approximately $490 million, net of expenses. "
        "On May 14, 2026, the Company entered into an Equity Distribution Agreement (the Second EDA) having an aggregate offering price of up to $600 million. "
        "84,386 and 74,998 shares issued and outstanding at June 30, 2026 and December 31, 2025. "
        "Total 7,775,523 $ 1,049,814 $ 20,996 $ 1,028,817"
    )
    lineage = aaoi_financing_lineage(aaoi_fixture)
    assert lineage["program_count"] == 2
    assert lineage["amendment_count"] == 1
    assert lineage["share_count_growth_pct"] > 10

    axti = axti_substitute_capacity_map(
        "our customer or prospective customer has at least two qualified substrate suppliers",
        "Sumitomo and JX also compete with us in the InP market",
        "initial term of three (3) years for 6-inch indium phosphide wafer substrates and prepayment of US$22,288,500",
        "capacity reservation for a six (6) year period",
        "January 1, 2027 through December 31, 2027",
    )
    assert axti["qualified_substitutes_exist"]
    assert axti["capacity_tightness_candidate"]
    assert not axti["dependency_promotion_allowed"]

    # Hash-chain semantics: old records remain immutable and duplicate seeds are not re-appended.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        history = Path(td) / "history.jsonl"
        first = ensure_source_history(history)
        second = ensure_source_history(history)
        assert first["entries"] == len(SERENITY_SOURCE_SEEDS)
        assert second["appended"] == 0
        assert second["chain_verified"]

    print("V213_H5_FIDELITY_DEEPENING_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=False)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.input is None:
        parser.error("--input is required unless --self-test is used")
    source = json.loads(args.input.read_text(encoding="utf-8-sig"))
    document = apply_h5(source, args.history)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "output": str(args.output),
        "source_history": str(args.history),
        "hard_dependency_count": document["summary"]["hard_dependency_count"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
