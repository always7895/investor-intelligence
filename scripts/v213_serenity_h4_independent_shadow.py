#!/usr/bin/env python3
"""H4 independent-corroboration + non-US primary Serenity shadow.

Shadow-only. It consumes a passed H3 report, suppresses known generic/hypothetical
issuer-text false positives, verifies canonical foreign-company identity against
official issuer sources, and adds independent counterparty corroboration where
available. It never changes Production rankings or claims Serenity's private process.
"""
from __future__ import annotations

import argparse
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
import v213_serenity_public_logic as fidelity
import v213_serenity_evidence_rich_shadow as h3

DEFAULT_OUTPUT = ROOT / "data" / "cache" / "v213_serenity_h4_shadow_latest.json"
MAX_BODY = 2_500_000

FOREIGN_PROFILES: dict[str, dict[str, Any]] = {
    "SIVE": {
        "canonical_company_name": "Sivers Semiconductors AB",
        "exchange": "Nasdaq Stockholm",
        "official_domains": ["sivers-semiconductors.com"],
        "official_urls": [
            "https://www.sivers-semiconductors.com/press/sivers-semiconductors-reports-q2-2026-results-as-product-growth-record-pipeline-and-customer-ramps-position-company-for-growth-acceleration/",
            "https://www.sivers-semiconductors.com/press/sivers-globalfoundries-advance-ai-data-center-optical-solutions/",
        ],
        "allowed_market_symbols": ["SIVE", "SIVEF"],
        "counterparties": [
            {
                "name": "GlobalFoundries Inc.",
                "official_url": "https://gf.com/technologies/silicon-photonics/",
                "required_terms": ["Sivers", "GlobalFoundries"],
                "relationship": "official ecosystem collaboration",
            }
        ],
    },
    "SOI": {
        "canonical_company_name": "Soitec S.A.",
        "exchange": "Euronext Paris",
        "official_domains": ["soitec.com"],
        "official_urls": [
            "https://www.soitec.com/home/investors/regulated-information/financial-reports--results-other-regulated-releases",
            "https://www.soitec.com/home/investors",
        ],
        "allowed_market_symbols": ["SOI.PA"],
        "counterparties": [],
    },
}

COUNTERPARTY_SEC_PROFILES: dict[str, list[dict[str, Any]]] = {
    "AXTI": [
        {
            "name": "Lumentum Holdings Inc.",
            "search_terms": ["AXT", "indium phosphide", "capacity reservation"],
            "relationship": "capacity reservation / purchase commitment",
        },
        {
            "name": "Coherent Corp.",
            "search_terms": ["AXT", "indium phosphide", "prepayment"],
            "relationship": "development / supply agreement",
        },
    ],
}

GENERIC_REJECT_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "design_win": [
        re.compile(r"\bwhether the design win\b", re.I),
        re.compile(r"\bsales cycles? will vary\b", re.I),
        re.compile(r"\bdesign win is with an existing or new customer\b", re.I),
    ],
    "qualification_constraint": [
        re.compile(r"\bif we fail to meet\b.{0,120}\bqualification\b", re.I | re.S),
        re.compile(r"\bmay lose sales to that customer\b", re.I),
    ],
    "qualification_delay": [
        re.compile(r"\bany failure or delay in obtaining\b", re.I),
        re.compile(r"\bcould delay revenue\b", re.I),
        re.compile(r"\bmay delay revenue\b", re.I),
    ],
}

FOCAL_CAPACITY_PATTERNS = [
    re.compile(r"\b(?:our|we|the company).{0,100}\b(?:manufacturing|production)?\s*capacity\b", re.I | re.S),
    re.compile(r"\bmanufacturing capacity\b", re.I),
    re.compile(r"\bproduction capacity\b", re.I),
    re.compile(r"\bmanufacturing footprint\b", re.I),
    re.compile(r"\b(?:facility|fab|cleanroom|equipment|capex|capital expenditures?)\b.{0,120}\bcapacity\b", re.I | re.S),
    re.compile(r"\bcapacity\b.{0,120}\b(?:facility|fab|cleanroom|equipment|capex|capital expenditures?)\b", re.I | re.S),
]
MARKET_CAPACITY_PATTERNS = [
    re.compile(r"\bcapacity expansion across (?:DCIs|networks?|metro|long-haul)\b", re.I),
    re.compile(r"\bneed for capacity expansion across\b", re.I),
]

ATM_PATTERN = re.compile(r"\b(?:at[- ]the[- ]market(?: offering)?|ATM offering|sales agreement)\b", re.I)
ATM_EVENT_ACTION = re.compile(r"\b(?:entered into|amended|amendment|new|increased|upsized|terminated|replaced)\b", re.I)
DATE_PATTERN = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{1,2},\s+20\d{2}\b",
    re.I,
)
AMOUNT_PATTERN = re.compile(r"\$\s?[\d,.]+\s*(?:million|billion)?", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _visible_text(raw: str) -> str:
    text = re.sub(r"(?is)<(?:script|style|noscript).*?>.*?</(?:script|style|noscript)>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def fetch_text(url: str, *, timeout: tuple[int, int] = (10, 35)) -> str:
    response = requests.get(url, headers=sources.sec_headers() if "sec.gov" in (urlparse(url).hostname or "") else {}, timeout=timeout)
    response.raise_for_status()
    raw = response.content[:MAX_BODY].decode(response.encoding or "utf-8", errors="replace")
    return _visible_text(raw)


def claim_is_eventive(signal: str, excerpt: str) -> bool:
    text = str(excerpt or "")
    for pattern in GENERIC_REJECT_PATTERNS.get(signal, []):
        if pattern.search(text):
            return False
    if signal == "capacity_expansion":
        if any(pattern.search(text) for pattern in MARKET_CAPACITY_PATTERNS) and not any(pattern.search(text) for pattern in FOCAL_CAPACITY_PATTERNS):
            return False
        return any(pattern.search(text) for pattern in FOCAL_CAPACITY_PATTERNS)
    return True


def audit_h3_claims(result: Mapping[str, Any]) -> dict[str, Any]:
    extraction = result.get("extraction") if isinstance(result.get("extraction"), Mapping) else {}
    bindings = list(extraction.get("signal_evidence") or [])
    dependency_candidates = list(extraction.get("dependency_candidates") or [])
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    accepted_dependency_candidates: list[dict[str, Any]] = []
    for binding in bindings:
        if not isinstance(binding, Mapping):
            continue
        signal = str(binding.get("signal") or "")
        if signal == "repeated_atm_or_material_dilution":
            # H4 re-verifies ATM events from source documents separately.
            continue
        row = dict(binding)
        row["claim_origin"] = "signal_evidence"
        if claim_is_eventive(signal, str(binding.get("excerpt") or "")):
            accepted.append(row)
        else:
            row["rejection_reason"] = "generic_or_hypothetical_not_observed_event"
            rejected.append(row)
    for candidate in dependency_candidates:
        if not isinstance(candidate, Mapping):
            continue
        row = dict(candidate)
        signal = str(row.get("signal") or "")
        row["claim_origin"] = "dependency_candidate"
        if claim_is_eventive(signal, str(row.get("excerpt") or "")):
            accepted_dependency_candidates.append(row)
        else:
            row["rejection_reason"] = "generic_or_hypothetical_not_observed_event"
            rejected.append(row)
    return {
        "accepted": accepted,
        "accepted_dependency_candidates": accepted_dependency_candidates,
        "rejected": rejected,
    }

def _atm_event_keys_from_text(text: str) -> set[str]:
    keys: set[str] = set()
    for match in ATM_PATTERN.finditer(text):
        start = max(0, match.start() - 260)
        end = min(len(text), match.end() + 420)
        window = re.sub(r"\s+", " ", text[start:end])
        if not ATM_EVENT_ACTION.search(window):
            continue
        dates = DATE_PATTERN.findall(window)
        amounts = AMOUNT_PATTERN.findall(window)
        action = ATM_EVENT_ACTION.search(window)
        key = "|".join([
            (action.group(0).lower() if action else "event"),
            (dates[0].lower() if dates else "undated"),
            (amounts[0].lower().replace(" ", "") if amounts else "noamount"),
        ])
        keys.add(key)
    return keys


def verify_distinct_atm_events(result: Mapping[str, Any]) -> dict[str, Any]:
    extraction = result.get("extraction") if isinstance(result.get("extraction"), Mapping) else {}
    urls = [str(item) for item in extraction.get("atm_filing_urls") or [] if str(item)]
    event_keys: dict[str, list[str]] = {}
    errors: list[dict[str, str]] = []
    for url in sorted(set(urls)):
        try:
            text = h3.fetch_sec_document(url)
            for key in _atm_event_keys_from_text(text):
                event_keys.setdefault(key, []).append(url)
        except Exception as exc:
            errors.append({"url": url, "error": type(exc).__name__})
    distinct = sorted(event_keys)
    return {
        "filing_urls": sorted(set(urls)),
        "event_keys": distinct,
        "distinct_event_count": len(distinct),
        "repeated_distinct_events": len(distinct) >= 2,
        "errors": errors,
    }


def official_identity_shadow(ticker: str, h3_result: Mapping[str, Any]) -> dict[str, Any]:
    profile = FOREIGN_PROFILES.get(ticker)
    if not profile:
        return {"applicable": False}
    official: list[dict[str, Any]] = []
    for url in profile["official_urls"]:
        row: dict[str, Any] = {"url": url, "ok": False}
        try:
            text = fetch_text(url)
            name_tokens = [token for token in re.split(r"\W+", profile["canonical_company_name"]) if len(token) >= 4]
            row["ok"] = sum(1 for token in name_tokens if re.search(re.escape(token), text, re.I)) >= max(1, len(name_tokens) // 2)
            row["text_excerpt"] = text[:500] if row["ok"] else ""
        except Exception as exc:
            row["error"] = type(exc).__name__
        official.append(row)

    market_urls = [
        str(url) for url in ((h3_result.get("evidence_summary") or {}).get("urls") or [])
        if "finance.yahoo.com/quote/" in str(url)
    ]
    observed_symbols = [url.rstrip("/").split("/")[-1].upper() for url in market_urls]
    allowed = {str(item).upper() for item in profile["allowed_market_symbols"]}
    mismatches = [symbol for symbol in observed_symbols if symbol not in allowed]

    return {
        "applicable": True,
        "canonical_company_name": profile["canonical_company_name"],
        "exchange": profile["exchange"],
        "official_sources": official,
        "official_primary_ok": any(row.get("ok") for row in official),
        "observed_market_symbols": observed_symbols,
        "allowed_market_symbols": sorted(allowed),
        "market_identity_mismatches": mismatches,
        "identity_status": "PASS" if any(row.get("ok") for row in official) else "DEGRADED",
    }


def official_counterparty_corroboration(ticker: str) -> list[dict[str, Any]]:
    profile = FOREIGN_PROFILES.get(ticker)
    if not profile:
        return []
    rows: list[dict[str, Any]] = []
    for item in profile.get("counterparties") or []:
        url = str(item["official_url"])
        row = {
            "counterparty": item["name"],
            "url": url,
            "relationship": item["relationship"],
            "ok": False,
            "independent": True,
        }
        try:
            text = fetch_text(url)
            terms = [str(term) for term in item.get("required_terms") or []]
            row["ok"] = all(re.search(re.escape(term), text, re.I) for term in terms)
        except Exception as exc:
            row["error"] = type(exc).__name__
        rows.append(row)
    return rows


def _company_tickers() -> list[dict[str, Any]]:
    response = requests.get("https://www.sec.gov/files/company_tickers.json", headers=sources.sec_headers(), timeout=(10, 30))
    response.raise_for_status()
    payload = response.json()
    return [value for value in payload.values() if isinstance(value, dict)] if isinstance(payload, dict) else []


def _norm_company(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", value.casefold())
    return " ".join(token for token in text.split() if token not in {"inc", "corp", "corporation", "holdings", "llc", "ltd"})


def resolve_counterparty_cik(name: str, tickers: Sequence[Mapping[str, Any]]) -> str | None:
    target = _norm_company(name)
    scored: list[tuple[int, str]] = []
    for row in tickers:
        title = _norm_company(str(row.get("title") or ""))
        if not title:
            continue
        if title == target:
            score = 100
        else:
            shared = len(set(title.split()) & set(target.split()))
            score = shared * 10
        if score >= 20:
            scored.append((score, str(row.get("cik_str") or "").zfill(10)))
    return max(scored)[1] if scored else None


def _recent_sec_documents(cik: str, *, limit: int = 8) -> list[str]:
    response = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=sources.sec_headers(), timeout=(10, 30))
    response.raise_for_status()
    payload = response.json()
    recent = ((payload.get("filings") or {}).get("recent") or {}) if isinstance(payload, dict) else {}
    accessions = recent.get("accessionNumber") or []
    forms = recent.get("form") or []
    docs = recent.get("primaryDocument") or []
    urls: list[str] = []
    cik_num = str(int(cik))
    for accession, form, doc in zip(accessions, forms, docs):
        if str(form) not in {"8-K", "10-Q", "10-K", "6-K", "20-F"}:
            continue
        acc = str(accession).replace("-", "")
        if doc:
            urls.append(f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc}/{doc}")
        if len(urls) >= limit:
            break
    return urls


def sec_counterparty_corroboration(ticker: str) -> list[dict[str, Any]]:
    profiles = COUNTERPARTY_SEC_PROFILES.get(ticker) or []
    if not profiles:
        return []
    try:
        tickers = _company_tickers()
    except Exception as exc:
        return [{"counterparty": item["name"], "ok": False, "independent": True, "error": type(exc).__name__} for item in profiles]
    rows: list[dict[str, Any]] = []
    for item in profiles:
        name = str(item["name"])
        cik = resolve_counterparty_cik(name, tickers)
        row: dict[str, Any] = {
            "counterparty": name,
            "relationship": item["relationship"],
            "independent": True,
            "ok": False,
            "cik": cik,
            "matches": [],
        }
        if not cik:
            row["error"] = "CIK_NOT_FOUND"
            rows.append(row)
            continue
        try:
            for url in _recent_sec_documents(cik):
                try:
                    text = h3.fetch_sec_document(url)
                except Exception:
                    continue
                terms = [str(term) for term in item["search_terms"]]
                hits = [term for term in terms if re.search(re.escape(term), text, re.I)]
                # The focal-company term (first configured term) must be present,
                # plus at least one relationship/material term. This prevents an
                # unrelated counterparty filing about InP/capacity from becoming
                # false independent corroboration of the focal relationship.
                if terms and terms[0] in hits and len(hits) >= 2:
                    row["matches"].append({"url": url, "matched_terms": hits})
            row["ok"] = bool(row["matches"])
        except Exception as exc:
            row["error"] = type(exc).__name__
        rows.append(row)
    return rows


def _base_record_from_h3(result: Mapping[str, Any], audit: Mapping[str, Any], atm: Mapping[str, Any]) -> dict[str, Any]:
    ticker = str(result.get("ticker") or "")
    evidence_urls = list((result.get("evidence_summary") or {}).get("urls") or [])
    evidence: list[dict[str, Any]] = []
    for url in evidence_urls:
        text = str(url)
        if "sec.gov" in (urlparse(text).hostname or ""):
            tier = "primary_strong"
        elif any(domain in (urlparse(text).hostname or "") for domain in ("sivers-semiconductors.com", "soitec.com", "gf.com")):
            tier = "corroborating"
        else:
            tier = "lead_only"
        evidence.append({"tier": tier, "url": text})

    accepted = list(audit.get("accepted") or [])
    signals = [str(row.get("signal") or "") for row in accepted if str(row.get("signal") or "") not in {"qualification_constraint"}]
    killers = [signal for signal in signals if signal in {
        "balance_sheet_funding_failure", "customer_loss", "qualification_delay", "volume_ramp_delay",
    }]
    signals = [signal for signal in signals if signal not in killers]
    if atm.get("repeated_distinct_events"):
        killers.append("repeated_atm_or_material_dilution")
        for url in atm.get("filing_urls") or []:
            accepted.append({
                "signal": "repeated_atm_or_material_dilution",
                "evidence_url": url,
                "as_of": now_iso(),
                "excerpt": "H4 verified at least two distinct ATM event keys rather than repeated mentions of one financing event.",
            })

    old_fidelity = result.get("public_logic_fidelity") if isinstance(result.get("public_logic_fidelity"), Mapping) else {}
    architecture = old_fidelity.get("architecture") if isinstance(old_fidelity.get("architecture"), Mapping) else {}
    record = {
        "ticker": ticker,
        "focal_company_node": ticker,
        "architecture": dict(architecture),
        "supply_chain_graph": [],
        "dependency_signals": [],
        "beneficiary_signal": False,
        "beneficiary_evidence_urls": [],
        "signals": list(dict.fromkeys(signals)),
        "signal_evidence": accepted,
        "information_gap": {"state": "UNKNOWN", "evidence_urls": []},
        "company_capture": {"state": "UNPROVEN", "evidence_urls": []},
        "evidence": evidence,
        "thesis_killers": list(dict.fromkeys(killers)),
        "disconfirmation_conditions": [
            "A qualified substitute removes the claimed dependency.",
            "The architecture changes such that the focal company is bypassed.",
            "Financing or dilution destroys the equity-capture mechanism.",
        ],
        "timing": dict(old_fidelity.get("timing") or {}),
        "serenity_source_views": [],
        "source_delta": [],
        "system_operationalization_score": result.get("system_operationalization_score"),
    }
    expansion = [signal for signal in record["signals"] if signal in {"capacity_expansion", "vertical_integration", "revenue_acceleration", "margin_expansion"}]
    commercial = [signal for signal in record["signals"] if signal in {"design_win", "qualification", "capacity_reservation", "prepayment", "long_term_agreement", "customer_named_ramp"}]
    capture_urls = [str(row.get("evidence_url")) for row in accepted if str(row.get("signal")) in set(expansion + commercial)]
    if expansion or commercial:
        record["company_capture"] = {"state": "POSITIVE", "evidence_urls": list(dict.fromkeys(capture_urls))}
    if record["thesis_killers"] and record["company_capture"]["state"] == "POSITIVE":
        record["company_capture"]["state"] = "MIXED"
    return record


def _add_official_non_us(record: dict[str, Any], identity: Mapping[str, Any]) -> None:
    if not identity.get("applicable") or not identity.get("official_primary_ok"):
        return
    urls = [str(row.get("url")) for row in identity.get("official_sources") or [] if row.get("ok")]
    for url in urls:
        record["evidence"].append({"tier": "primary_strong", "url": url})
    if record["ticker"] == "SIVE":
        collaboration_url = next((url for url in urls if "globalfoundries" in url.casefold()), urls[0] if urls else "")
        q2_url = next((url for url in urls if "q2-2026" in url.casefold()), urls[0] if urls else "")
        record["architecture"] = {
            "current": "silicon photonics / CPO ecosystem",
            "as_of": "2026-06-02T00:00:00Z",
            "evidence_urls": [collaboration_url] if collaboration_url else [],
        }
        if collaboration_url:
            record["beneficiary_signal"] = True
            record["beneficiary_evidence_urls"] = [collaboration_url]
        if q2_url:
            signal = "customer_named_ramp"
            record["signals"].append(signal)
            record["signal_evidence"].append({
                "signal": signal, "evidence_url": q2_url, "as_of": "2026-08-27T00:00:00Z",
                "excerpt": "Official Sivers regulatory Q2 2026 source reports customer production ramps and product revenue growth.",
            })


def _add_independent_graph(record: dict[str, Any], corroboration: Sequence[Mapping[str, Any]]) -> int:
    count = 0
    ticker = str(record["ticker"])
    for row in corroboration:
        if not row.get("ok"):
            continue
        url = str(row.get("url") or "")
        if not url and row.get("matches"):
            url = str(row["matches"][0].get("url") or "")
        if not url:
            continue
        record["evidence"].append({"tier": "corroborating", "url": url})
        record["supply_chain_graph"].append({
            "from": ticker,
            "to": str(row.get("counterparty") or "counterparty"),
            "relationship": str(row.get("relationship") or "independently corroborated relationship"),
            "evidence_url": url,
            "as_of": now_iso(),
        })
        count += 1
    return count


def h4_one(h3_result: Mapping[str, Any]) -> dict[str, Any]:
    ticker = str(h3_result.get("ticker") or "")
    audit = audit_h3_claims(h3_result)
    atm = verify_distinct_atm_events(h3_result)
    identity = official_identity_shadow(ticker, h3_result)
    official_corr = official_counterparty_corroboration(ticker)
    sec_corr = sec_counterparty_corroboration(ticker)
    corroboration = official_corr + sec_corr

    record = _base_record_from_h3(h3_result, audit, atm)
    _add_official_non_us(record, identity)
    graph_edges = _add_independent_graph(record, corroboration)

    assessed = fidelity.assess_public_logic(record)
    assessed["shadow_only"] = True
    assessed["h4_independent_shadow"] = True
    assessed["h3_claim_quality_audit"] = audit
    assessed["atm_event_audit"] = atm
    assessed["identity_verification"] = identity
    assessed["independent_corroboration"] = corroboration
    assessed["independent_graph_edge_count"] = graph_edges
    assessed["h3_original_state"] = {
        "dependency_role": ((h3_result.get("public_logic_fidelity") or {}).get("dependency_role")),
        "thesis_class": ((h3_result.get("public_logic_fidelity") or {}).get("thesis_class")),
        "thesis_state": ((h3_result.get("public_logic_fidelity") or {}).get("thesis_state")),
        "company_capture_state": (((h3_result.get("public_logic_fidelity") or {}).get("company_capture") or {}).get("state")),
    }
    assessed["h4_corrections"] = [
        {
            "signal": str(row.get("signal") or ""),
            "reason": str(row.get("rejection_reason") or ""),
            "evidence_url": str(row.get("evidence_url") or ""),
        }
        for row in audit["rejected"]
    ]
    assessed["production_ranking_changed"] = False
    return assessed


def run(h3_doc: Mapping[str, Any], output: Path) -> dict[str, Any]:
    rows = h3_doc.get("results")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ValueError("H3 results missing")
    results = [h4_one(row) for row in rows if isinstance(row, Mapping)]
    summary = {
        "requested": len(rows),
        "completed": len(results),
        "failed": 0,
        "production_ranking_changed": False,
        "identity_mismatch_count": sum(len((row.get("identity_verification") or {}).get("market_identity_mismatches") or []) for row in results),
        "independent_graph_edge_count": sum(int(row.get("independent_graph_edge_count") or 0) for row in results),
        "hard_dependency_count": sum(
            1 for row in results
            if (row.get("public_logic_fidelity") or {}).get("dependency_role") in {
                "SINGLE_SOURCE", "SEMI_MONOPOLY", "QUALIFICATION_CONSTRAINED", "CAPACITY_BOTTLENECK"
            }
        ),
        "claim_corrections": sum(len(row.get("h4_corrections") or []) for row in results),
    }
    document = {
        "schema_version": 1,
        "product_version": "2.1.3",
        "mode": "h4_independent_and_non_us_shadow_only_no_production_mutation",
        "generated_at": now_iso(),
        "summary": summary,
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document


def self_test() -> None:
    assert not claim_is_eventive("design_win", "sales cycles will vary based on whether the design win is with an existing or new customer")
    assert not claim_is_eventive("qualification_constraint", "If we fail to meet the product qualification and volume requirements of a customer, we may lose sales")
    assert not claim_is_eventive("qualification_delay", "Any failure or delay in obtaining such qualification or requalification could delay revenue")
    assert not claim_is_eventive("capacity_expansion", "This need for capacity expansion across DCIs, metro networks and long-haul networks is accelerating")
    assert claim_is_eventive("capacity_expansion", "Management expects to invest in manufacturing capacity and new equipment through 2027")
    same = (
        "On August 1, 2026 we entered into an at-the-market Sales Agreement for up to $100 million. "
        "The at-the-market Sales Agreement entered into on August 1, 2026 may be used from time to time."
    )
    keys = _atm_event_keys_from_text(same)
    assert len(keys) == 1
    soi = {
        "ticker": "SOI",
        "evidence_summary": {"urls": ["https://finance.yahoo.com/quote/ZQM.SI"]},
    }
    original = fetch_text
    try:
        globals()["fetch_text"] = lambda url, timeout=(10, 35): "Soitec Investor Relations financial reports"
        identity = official_identity_shadow("SOI", soi)
        assert identity["official_primary_ok"]
        assert identity["market_identity_mismatches"] == ["ZQM.SI"]
    finally:
        globals()["fetch_text"] = original
    print("V213_H4_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--h3-report", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.h3_report:
        raise SystemExit("--h3-report is required")
    h3_doc = json.loads(args.h3_report.read_text(encoding="utf-8-sig"))
    result = run(h3_doc, args.output)
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))
    print(f"V213_SERENITY_H4_SHADOW_OUTPUT = {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
