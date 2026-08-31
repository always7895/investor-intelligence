#!/usr/bin/env python3
"""H3 evidence-rich Serenity shadow extraction.

This stage remains shadow-only. It reads public-source context, inspects a bounded
set of SEC issuer filings, and extracts only narrow evidence-bound company claims.
It deliberately refuses to turn issuer self-description into a proven Serenity
bottleneck without independent dependency corroboration.
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
import v213_serenity_shadow_adapters as h2

DEFAULT_OUTPUT = ROOT / "data" / "cache" / "v213_serenity_h3_shadow_latest.json"
MAX_DOC_BYTES = 2_500_000
MAX_FILINGS = 5
MAX_EXCERPT = 280

ARCHITECTURE_PATTERNS = [
    ("CPO / co-packaged optics", re.compile(r"\b(?:co[- ]packaged optics|CPO)\b", re.I)),
    ("1.6T optical networking", re.compile(r"\b1\.6\s*T(?:b|bit|bps)?\b", re.I)),
    ("800G optical networking", re.compile(r"\b800\s*G(?:b|bit|bps)?\b", re.I)),
    ("silicon photonics", re.compile(r"\bsilicon photonics?\b", re.I)),
    ("indium phosphide / InP", re.compile(r"\b(?:indium phosphide|InP)\b", re.I)),
    ("HBM / high-bandwidth memory", re.compile(r"\b(?:HBM\d*|high[- ]bandwidth memory)\b", re.I)),
    ("advanced packaging", re.compile(r"\badvanced packaging\b", re.I)),
]

# Positive focal-company dependency claims must say that the issuer itself is a
# scarce/qualified supplier to customers. Statements that the issuer DEPENDS ON
# a sole supplier are upstream-risk evidence and never become bottleneck proof.
DEPENDENCY_CANDIDATE_PATTERNS = {
    "single_source": [
        re.compile(r"\b(?:we|our company|the company)\s+(?:are|is)\s+(?:the\s+)?(?:sole|single|only)\s+(?:qualified\s+)?supplier\b", re.I),
    ],
    "qualified_supplier_concentration": [
        re.compile(r"\b(?:we|our company|the company)\s+(?:are|is)\s+(?:one of\s+)?(?:only\s+)?(?:a\s+)?(?:few|limited number of)\s+qualified suppliers\b", re.I),
        re.compile(r"\bone of only\s+(?:two|three|four|2|3|4)\s+qualified suppliers\b", re.I),
    ],
    "qualification_constraint": [
        re.compile(r"\bcustomer(?:s)?\s+(?:must\s+)?qualif(?:y|ication).{0,120}(?:our|the)\s+products?\b", re.I | re.S),
        re.compile(r"\b(?:our|the)\s+products?.{0,120}qualif(?:ied|ication).{0,120}customer", re.I | re.S),
    ],
    "binding_capacity": [
        re.compile(r"\bdemand.{0,100}exceed(?:s|ed)?\s+(?:our\s+)?(?:available\s+)?capacity\b", re.I | re.S),
        re.compile(r"\bcapacity constraints?.{0,120}(?:meet|satisfy).{0,80}(?:customer\s+)?demand\b", re.I | re.S),
    ],
}

UPSTREAM_RISK_PATTERNS = [
    re.compile(r"\bwe (?:depend|rely) on (?:a |one )?(?:sole|single) source\b", re.I),
    re.compile(r"\b(?:sole|single)[- ]source supplier\b", re.I),
]

COMMERCIAL_PATTERNS = {
    "design_win": [re.compile(r"\bdesign win\b", re.I)],
    "qualification": [
        re.compile(r"\bsuccessfully qualified\b", re.I),
        re.compile(r"\bqualified by (?:a |our |the )?customer\b", re.I),
    ],
    "capacity_reservation": [re.compile(r"\bcapacity reservation\b", re.I)],
    "prepayment": [re.compile(r"\bcustomer prepayment\b", re.I), re.compile(r"\bprepayment agreement\b", re.I)],
    "long_term_agreement": [re.compile(r"\blong[- ]term (?:supply )?agreement\b", re.I)],
}

EXPANSION_PATTERNS = {
    "capacity_expansion": [
        re.compile(r"\bcapacity expansion\b", re.I),
        re.compile(r"\bexpand(?:ing|ed)? (?:our )?(?:manufacturing )?capacity\b", re.I),
    ],
    "vertical_integration": [re.compile(r"\bvertically integrated\b", re.I), re.compile(r"\bvertical integration\b", re.I)],
}

BENEFICIARY_PATTERNS = [
    re.compile(r"\bdemand for (?:our|the company'?s) products?.{0,160}\b(?:AI|artificial intelligence|data ?center|800G|1\.6T|CPO|HBM)\b", re.I | re.S),
    re.compile(r"\b(?:AI|artificial intelligence|data ?center|800G|1\.6T|CPO|HBM).{0,160}\bdemand for (?:our|the company'?s) products?\b", re.I | re.S),
]

KILLER_PATTERNS = {
    "balance_sheet_funding_failure": [re.compile(r"substantial doubt.{0,100}ability to continue as a going concern", re.I | re.S)],
    "customer_loss": [
        re.compile(r"\blost (?:a|our) (?:significant|major|largest) customer\b", re.I),
        re.compile(r"\bcustomer.{0,80}(?:terminated|cancelled|canceled).{0,80}(?:agreement|contract|program)\b", re.I | re.S),
    ],
    "qualification_delay": [re.compile(r"\bqualif(?:ication|y).{0,80}(?:delay|delayed|longer than expected)\b", re.I | re.S)],
    "volume_ramp_delay": [
        re.compile(r"\b(?:volume|production) ramp.{0,80}(?:delay|delayed|slower|pushed out)\b", re.I | re.S),
        re.compile(r"\b(?:delay|delayed|pushed out).{0,80}(?:volume|production) ramp\b", re.I | re.S),
    ],
}
ATM_PATTERN = re.compile(r"\b(?:at[- ]the[- ]market(?: offering)?|ATM offering|sales agreement.{0,100}common stock)\b", re.I | re.S)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _dateish(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if text:
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except ValueError:
            try:
                return datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
            except ValueError:
                pass
    return fallback


def _sec_filing_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "sec.gov" or host.endswith(".sec.gov")


def _visible_text(raw: str) -> str:
    text = re.sub(r"(?is)<(?:script|style|noscript).*?>.*?</(?:script|style|noscript)>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_sec_document(url: str) -> str:
    if not _sec_filing_url(url):
        raise ValueError("H3 only fetches SEC-hosted filing documents")
    response = requests.get(url, headers=sources.sec_headers(), timeout=(10, 45), stream=True)
    response.raise_for_status()
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(64 * 1024):
        if not chunk:
            continue
        size += len(chunk)
        if size > MAX_DOC_BYTES:
            break
        chunks.append(chunk)
    raw = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
    return _visible_text(raw)


def _excerpt(text: str, match: re.Match[str]) -> str:
    start = max(0, match.start() - 110)
    end = min(len(text), match.end() + 140)
    return re.sub(r"\s+", " ", text[start:end]).strip()[:MAX_EXCERPT]


def _first_match(text: str, patterns: Sequence[re.Pattern[str]]) -> re.Match[str] | None:
    matches = [pattern.search(text) for pattern in patterns]
    matches = [match for match in matches if match is not None]
    return min(matches, key=lambda item: item.start()) if matches else None


def _append_binding(target: list[dict[str, Any]], signal: str, url: str, as_of: str, excerpt: str) -> None:
    target.append({"signal": signal, "evidence_url": url, "as_of": as_of, "excerpt": excerpt})


def extract_from_filings(ticker: str, evidence: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    filings = [
        row for row in evidence
        if isinstance(row, Mapping)
        and str(row.get("claim_scope") or "") in {"company_regulatory_filing", "existing_signed_system_public_evidence"}
        and str(row.get("source_id") or "") == "sec_edgar"
        and _sec_filing_url(str(row.get("url") or ""))
    ]
    unique: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for row in filings:
        url = str(row.get("url") or "")
        if url and url not in seen:
            unique.append(row)
            seen.add(url)
        if len(unique) >= MAX_FILINGS:
            break

    result: dict[str, Any] = {
        "documents_attempted": len(unique), "documents_fetched": 0,
        "document_errors": [], "architecture_candidates": [],
        "dependency_candidates": [], "upstream_dependency_risks": [],
        "commercial_signals": [], "expansion_signals": [], "killer_signals": [],
        "beneficiary_evidence_urls": [], "signal_evidence": [],
        "atm_filing_urls": [], "independent_dependency_corroboration": False,
    }
    for row in unique:
        url = str(row.get("url") or "")
        as_of = _dateish(row.get("as_of"), now_iso())
        try:
            text = fetch_sec_document(url)
            result["documents_fetched"] += 1
        except Exception as exc:
            result["document_errors"].append({"url": url, "error": type(exc).__name__})
            continue
        if not text:
            continue

        for label, pattern in ARCHITECTURE_PATTERNS:
            match = pattern.search(text)
            if match:
                result["architecture_candidates"].append({"label": label, "evidence_url": url, "as_of": as_of, "excerpt": _excerpt(text, match)})
                break

        for signal, patterns in DEPENDENCY_CANDIDATE_PATTERNS.items():
            match = _first_match(text, patterns)
            if match:
                result["dependency_candidates"].append({"signal": signal, "evidence_url": url, "as_of": as_of, "excerpt": _excerpt(text, match)})

        upstream = _first_match(text, UPSTREAM_RISK_PATTERNS)
        if upstream:
            result["upstream_dependency_risks"].append({"evidence_url": url, "as_of": as_of, "excerpt": _excerpt(text, upstream)})

        for signal, patterns in COMMERCIAL_PATTERNS.items():
            match = _first_match(text, patterns)
            if match:
                result["commercial_signals"].append(signal)
                _append_binding(result["signal_evidence"], signal, url, as_of, _excerpt(text, match))

        for signal, patterns in EXPANSION_PATTERNS.items():
            match = _first_match(text, patterns)
            if match:
                result["expansion_signals"].append(signal)
                _append_binding(result["signal_evidence"], signal, url, as_of, _excerpt(text, match))

        beneficiary = _first_match(text, BENEFICIARY_PATTERNS)
        if beneficiary:
            result["beneficiary_evidence_urls"].append(url)

        for signal, patterns in KILLER_PATTERNS.items():
            match = _first_match(text, patterns)
            if match:
                result["killer_signals"].append(signal)
                _append_binding(result["signal_evidence"], signal, url, as_of, _excerpt(text, match))

        if ATM_PATTERN.search(text):
            result["atm_filing_urls"].append(url)

    if len(set(result["atm_filing_urls"])) >= 2:
        result["killer_signals"].append("repeated_atm_or_material_dilution")
        for url in sorted(set(result["atm_filing_urls"]))[:2]:
            row = next((item for item in unique if str(item.get("url") or "") == url), {})
            _append_binding(result["signal_evidence"], "repeated_atm_or_material_dilution", url,
                            _dateish(row.get("as_of"), now_iso()), "Repeated ATM/public-equity-sales language detected across distinct SEC filings")

    # Deduplicate while preserving order. Dependency candidates are intentionally
    # NOT promoted to dependency_signals here: SEC issuer self-description is not
    # independent customer/supplier corroboration of Serenity-style chokepoint status.
    for key in ("commercial_signals", "expansion_signals", "killer_signals", "beneficiary_evidence_urls", "atm_filing_urls"):
        result[key] = list(dict.fromkeys(result[key]))
    return result


def build_rich_record(ticker: str, base_evidence: list[dict[str, Any]], adapter_status: Mapping[str, Any],
                      system: Mapping[str, Any] | None, extracted: Mapping[str, Any]) -> dict[str, Any]:
    architecture_candidates = list(extracted.get("architecture_candidates") or [])
    architecture = {}
    if architecture_candidates:
        first = architecture_candidates[0]
        architecture = {"current": first["label"], "as_of": first["as_of"], "evidence_urls": [first["evidence_url"]]}

    commercial = list(extracted.get("commercial_signals") or [])
    expansion = list(extracted.get("expansion_signals") or [])
    killers = list(extracted.get("killer_signals") or [])
    capture_state = "UNPROVEN"
    capture_urls: list[str] = []
    if commercial or expansion:
        capture_state = "POSITIVE"
        capture_urls = [str(row.get("evidence_url")) for row in extracted.get("signal_evidence", [])
                        if str(row.get("signal")) in set(commercial + expansion)]
    if killers and capture_state == "POSITIVE":
        capture_state = "MIXED"
    elif killers:
        capture_state = "WEAK"

    beneficiary_urls = list(extracted.get("beneficiary_evidence_urls") or [])
    record = h2.conservative_record(ticker, base_evidence, adapter_status, system)
    record.update({
        "architecture": architecture,
        "supply_chain_graph": [],
        "dependency_signals": [],
        "beneficiary_signal": bool(beneficiary_urls),
        "beneficiary_evidence_urls": beneficiary_urls,
        "signals": expansion + commercial,
        "signal_evidence": list(extracted.get("signal_evidence") or []),
        "company_capture": {"state": capture_state, "evidence_urls": list(dict.fromkeys(capture_urls))},
        "thesis_killers": killers,
    })
    return record


def rich_shadow_one(ticker: str, *, system_scores: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    symbol = h2.clean_ticker(ticker)
    if not symbol:
        raise ValueError(f"Invalid symbol: {ticker}")
    context = sources.build_source_context(symbol, f"{symbol} H3 evidence-rich Serenity shadow research")
    evidence, adapter_status = h2.context_to_evidence(context)
    system = system_scores.get(symbol)
    evidence = h2.merge_system_evidence(evidence, system)
    extracted = extract_from_filings(symbol, evidence)
    record = build_rich_record(symbol, evidence, adapter_status, system, extracted)
    assessed = fidelity.assess_public_logic(record)
    assessed["shadow_only"] = True
    assessed["h3_evidence_rich"] = True
    assessed["extraction"] = extracted
    assessed["system_operationalization_context"] = dict(system or {})
    assessed["source_context"] = {
        "successful_source_families": list(context.get("successful_source_families") or []),
        "source_diversity_status": str(context.get("source_diversity_status") or "DEGRADED"),
    }
    assessed["missing_adapter_classes"] = [
        "independent_customer_supplier_corroboration",
        "non_us_exchange_primary_filings",
        "qualified_competitor_and_substitute_map",
        "architecture_bypass_cross_company_validation",
        "capacity_and_lead_time_time_series",
        "persistent_serenity_source_delta_history",
    ]
    # Critical H3 boundary: issuer-only SEC language may create auditable candidate
    # claims but not a proven dependency role.
    if extracted.get("dependency_candidates") and assessed["public_logic_fidelity"]["dependency_role"] != "UNPROVEN":
        raise RuntimeError("Issuer-only dependency candidate incorrectly became a proven chokepoint role")
    return assessed


def canonical_safety(result: Mapping[str, Any]) -> dict[str, Any]:
    fidelity_state = result.get("public_logic_fidelity") if isinstance(result.get("public_logic_fidelity"), Mapping) else {}
    capture = fidelity_state.get("company_capture") if isinstance(fidelity_state.get("company_capture"), Mapping) else {}
    return {
        "ticker": result.get("ticker"),
        "dependency_role": fidelity_state.get("dependency_role"),
        "thesis_class": fidelity_state.get("thesis_class"),
        "thesis_state": fidelity_state.get("thesis_state"),
        "company_capture_state": capture.get("state"),
        "thesis_killers": list(fidelity_state.get("thesis_killers") or []),
        "system_score": result.get("system_operationalization_score"),
        "issuer_dependency_candidate_count": len((result.get("extraction") or {}).get("dependency_candidates") or []),
        "independent_dependency_corroboration": bool((result.get("extraction") or {}).get("independent_dependency_corroboration")),
    }


def self_test() -> None:
    text = "We are one of only two qualified suppliers. Our products are qualified by our customer. We announced a capacity expansion."
    fake = [{"source_id": "sec_edgar", "claim_scope": "company_regulatory_filing", "url": "https://www.sec.gov/Archives/test.htm", "as_of": "2026-08-01T00:00:00Z"}]
    original = fetch_sec_document
    try:
        globals()["fetch_sec_document"] = lambda url: text
        extracted = extract_from_filings("TEST", fake)
        assert extracted["dependency_candidates"]
        assert "capacity_expansion" in extracted["expansion_signals"]
        record = build_rich_record("TEST", [dict(fake[0], tier="primary_strong")], {}, {"score": 99}, extracted)
        result = fidelity.assess_public_logic(record)
        assert result["public_logic_fidelity"]["dependency_role"] == "UNPROVEN"
        assert result["public_logic_fidelity"]["thesis_class"] == "EXPANSION_THESIS"
    finally:
        globals()["fetch_sec_document"] = original


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--tickers", nargs="*", default=[])
    parser.add_argument("--system-universe", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("V213_SERENITY_H3_EVIDENCE_RICH_SELF_TEST = PASS")
        return 0
    tickers = [h2.clean_ticker(item) for item in args.tickers]
    tickers = [item for item in tickers if item]
    if not tickers:
        raise SystemExit("At least one --tickers symbol is required")
    system_scores = h2.load_system_scores(args.system_universe)
    results: list[dict[str, Any]] = []
    for symbol in tickers:
        try:
            result = rich_shadow_one(symbol, system_scores=system_scores)
            h2.validate_shadow_result(result)
            results.append(result)
        except Exception as exc:
            results.append({"ticker": symbol, "shadow_only": True, "h3_evidence_rich": True,
                            "status": "ADAPTER_FAILED", "error": type(exc).__name__, "detail": str(exc)[:400]})
    document = {
        "schema_version": 1, "product_version": "2.1.3",
        "mode": "h3_evidence_rich_shadow_only_no_production_mutation",
        "generated_at": now_iso(), "tickers": tickers, "results": results,
        "summary": {
            "requested": len(tickers),
            "completed": sum(1 for row in results if row.get("status") != "ADAPTER_FAILED"),
            "failed": sum(1 for row in results if row.get("status") == "ADAPTER_FAILED"),
            "production_ranking_changed": False,
            "proven_hard_dependency_count": sum(
                1 for row in results
                if isinstance(row.get("public_logic_fidelity"), Mapping)
                and row["public_logic_fidelity"].get("dependency_role") in {
                    "SINGLE_SOURCE", "SEMI_MONOPOLY", "QUALIFICATION_CONSTRAINED", "CAPACITY_BOTTLENECK"
                }
            ),
        },
    }
    atomic_write(args.output, document)
    print(json.dumps(document["summary"], ensure_ascii=False, sort_keys=True))
    print(f"V213_SERENITY_H3_SHADOW_OUTPUT = {args.output}")
    return 0 if document["summary"]["completed"] >= 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
