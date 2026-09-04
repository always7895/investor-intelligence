#!/usr/bin/env python3
"""v2.1.3 Serenity public-logic shadow evidence adapters.

This stage is deliberately conservative. It converts the existing public-source
ensemble into provenance-bearing evidence rows, then invokes the public-logic
fidelity engine. It does not manufacture supply-chain edges, bottleneck signals,
company-capture labels, or Serenity source views from weak market metadata.

The output is for shadow comparison only and must not replace Production ranking.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v212_local_llm_gateway as sources
import v213_serenity_public_logic as fidelity

DEFAULT_OUTPUT = ROOT / "data" / "cache" / "v213_serenity_shadow_latest.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_ticker(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text if fidelity.TICKER_RE.fullmatch(text) else ""


def dateish(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if text:
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except ValueError:
            try:
                dt = datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                return dt.isoformat().replace("+00:00", "Z")
            except ValueError:
                pass
    return fallback


def add_evidence(rows: list[dict[str, Any]], seen: set[str], *, tier: str, source_id: str,
                 claim_scope: str, url: Any, as_of: Any, title: str, retrieved_at: str) -> None:
    value = str(url or "").strip()
    if not value.startswith("https://") or value in seen:
        return
    rows.append({
        "tier": tier, "source_id": source_id, "claim_scope": claim_scope,
        "url": value, "as_of": dateish(as_of, retrieved_at),
        "title": title[:300], "retrieved_at": retrieved_at,
    })
    seen.add(value)


def context_to_evidence(context: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    retrieved = str(context.get("retrieved_at") or now_iso())
    status: dict[str, Any] = {
        "successful_source_families": list(context.get("successful_source_families") or []),
        "source_diversity_status": str(context.get("source_diversity_status") or "DEGRADED"),
        "company_primary_sources": [], "company_lead_sources": [], "macro_context_sources": [],
    }
    raw_sources = context.get("sources")
    if not isinstance(raw_sources, Sequence) or isinstance(raw_sources, (str, bytes, bytearray)):
        raw_sources = []

    for item in raw_sources:
        if not isinstance(item, Mapping) or not bool(item.get("ok")):
            continue
        source_id = str(item.get("source_id") or "")
        summary = item.get("summary") if isinstance(item.get("summary"), Mapping) else {}
        item_retrieved = str(item.get("retrieved_at") or retrieved)

        if source_id == "sec_edgar":
            companyfacts_url = summary.get("companyfacts_url")
            add_evidence(rows, seen, tier="primary_strong", source_id=source_id,
                         claim_scope="company_regulatory_facts", url=companyfacts_url,
                         as_of=item_retrieved, title="SEC EDGAR company facts", retrieved_at=item_retrieved)
            filings = summary.get("recent_material_filings")
            if isinstance(filings, Sequence) and not isinstance(filings, (str, bytes, bytearray)):
                for filing in filings[:8]:
                    if not isinstance(filing, Mapping):
                        continue
                    form = str(filing.get("form") or "filing")
                    add_evidence(rows, seen, tier="primary_strong", source_id=source_id,
                                 claim_scope="company_regulatory_filing", url=filing.get("url"),
                                 as_of=filing.get("filing_date") or item_retrieved,
                                 title=f"SEC {form}", retrieved_at=item_retrieved)
            if companyfacts_url:
                status["company_primary_sources"].append(source_id)
            continue

        if source_id == "gleif_lei":
            url = summary.get("url")
            add_evidence(rows, seen, tier="primary_strong", source_id=source_id,
                         claim_scope="legal_entity_identity_only", url=url,
                         as_of=item_retrieved, title="GLEIF legal-entity record", retrieved_at=item_retrieved)
            if url:
                status["company_primary_sources"].append(source_id)
            continue

        if source_id == "yahoo_finance_public_unofficial":
            symbol = str(summary.get("resolved_symbol") or context.get("ticker") or "").strip()
            if symbol:
                add_evidence(rows, seen, tier="lead_only", source_id=source_id,
                             claim_scope="market_observation_lead_only",
                             url="https://finance.yahoo.com/quote/" + symbol,
                             as_of=item_retrieved, title=f"Yahoo market observation for {symbol}",
                             retrieved_at=item_retrieved)
                status["company_lead_sources"].append(source_id)
            news = summary.get("news")
            if isinstance(news, Sequence) and not isinstance(news, (str, bytes, bytearray)):
                for news_item in news[:8]:
                    if not isinstance(news_item, Mapping):
                        continue
                    add_evidence(rows, seen, tier="lead_only", source_id=source_id,
                                 claim_scope="news_lead_only", url=news_item.get("url"),
                                 as_of=news_item.get("published") or item_retrieved,
                                 title=str(news_item.get("title") or "Yahoo news lead"),
                                 retrieved_at=item_retrieved)
            continue

        if source_id in {"bls_public_data", "world_bank_indicators"}:
            url = summary.get("url") or ("https://www.bls.gov/" if source_id == "bls_public_data" else "https://api.worldbank.org/")
            add_evidence(rows, seen, tier="corroborating", source_id=source_id,
                         claim_scope="macro_context_only", url=url, as_of=item_retrieved,
                         title=("BLS macro context" if source_id == "bls_public_data" else "World Bank macro context"),
                         retrieved_at=item_retrieved)
            status["macro_context_sources"].append(source_id)

    status["evidence_row_count"] = len(rows)
    status["primary_company_evidence_count"] = sum(
        1 for row in rows if row["tier"] == "primary_strong"
        and row["claim_scope"] not in {"legal_entity_identity_only", "macro_context_only"}
    )
    return rows, status


def load_system_scores(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in raw:
        if not isinstance(row, Mapping):
            continue
        ticker = clean_ticker(row.get("ticker"))
        if not ticker:
            continue
        result[ticker] = {
            "score": row.get("serenity_score"),
            "rank": row.get("rank"),
            "quality": row.get("data_quality"),
            "scoring_version": row.get("scoring_version"),
            "evidence": list(row.get("evidence") or []) if isinstance(row.get("evidence"), list) else [],
        }
    return result


def merge_system_evidence(evidence: list[dict[str, Any]], system: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    merged = [dict(row) for row in evidence]
    seen = {str(row.get("url") or "") for row in merged if str(row.get("url") or "").startswith("https://")}
    for raw in (system or {}).get("evidence", []):
        if not isinstance(raw, Mapping):
            continue
        url = str(raw.get("url") or "").strip()
        if not url.startswith("https://") or url in seen:
            continue
        source_id = str(raw.get("source_id") or "existing_system_public_evidence")
        raw_tier = str(raw.get("tier") or "").strip().casefold()
        if source_id == "sec_edgar" or raw_tier in {"t0", "t1", "primary", "primary_strong"}:
            tier = "primary_strong"
        elif source_id in {"world_bank_indicators", "bls_public_data", "gleif_lei"} or raw_tier in {"t2", "corroborating", "secondary"}:
            tier = "corroborating"
        else:
            tier = "lead_only"
        merged.append({
            "tier": tier, "source_id": source_id,
            "claim_scope": "existing_signed_system_public_evidence", "url": url,
            "as_of": dateish(raw.get("as_of"), now_iso()),
            "title": str(raw.get("title") or f"Existing signed public evidence: {source_id}")[:300],
            "retrieved_at": now_iso(),
        })
        seen.add(url)
    return merged


def conservative_record(ticker: str, evidence: list[dict[str, Any]], adapter_status: Mapping[str, Any],
                        system: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "ticker": ticker, "focal_company_node": ticker,
        "architecture": {}, "supply_chain_graph": [], "dependency_signals": [],
        "beneficiary_signal": False, "beneficiary_evidence_urls": [],
        "signals": [], "signal_evidence": [], "information_gap": {},
        "company_capture": {"state": "UNPROVEN", "evidence_urls": []},
        "evidence": evidence, "thesis_killers": [],
        "disconfirmation_conditions": [
            "A qualified substitute removes the claimed dependency.",
            "The architecture changes such that the focal company is bypassed.",
            "Financing or dilution destroys the equity-capture mechanism.",
        ],
        "timing": {
            "operating_thesis_horizon": "unknown", "architecture_ramp_window": "unknown",
            "entry_context": "unknown", "valuation_expectation_context": "unknown",
        },
        "source_delta": [],
        "system_operationalization_score": (system or {}).get("score"),
        "shadow_adapter_status": dict(adapter_status),
    }


def shadow_one(ticker: str, *, system_scores: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    symbol = clean_ticker(ticker)
    if not symbol:
        raise ValueError(f"Invalid symbol: {ticker}")
    context = sources.build_source_context(symbol, f"{symbol} public-logic shadow research")
    evidence, adapter_status = context_to_evidence(context)
    system = system_scores.get(symbol)
    evidence = merge_system_evidence(evidence, system)
    record = conservative_record(symbol, evidence, adapter_status, system)
    assessed = fidelity.assess_public_logic(record)
    assessed["shadow_only"] = True
    assessed["source_context"] = {
        "successful_source_families": list(context.get("successful_source_families") or []),
        "source_diversity_status": str(context.get("source_diversity_status") or "DEGRADED"),
    }
    assessed["adapter_status"] = adapter_status
    assessed["system_operationalization_context"] = dict(system_scores.get(symbol) or {})
    assessed["missing_adapter_classes"] = [
        "architecture_roadmap", "customer_supplier_graph",
        "qualification_design_win_lta_prepayment", "capacity_and_lead_time",
        "dilution_and_financing_normalization", "qualified_competitor_and_substitute_map",
        "serenity_source_delta_history",
    ]
    return assessed


def validate_shadow_result(result: Mapping[str, Any]) -> None:
    if result.get("shadow_only") is not True:
        raise RuntimeError("Shadow result is not marked shadow_only")
    if result.get("private_process_reproduction_claimed") is not False:
        raise RuntimeError("Private-process reproduction was incorrectly claimed")
    state = result.get("public_logic_fidelity")
    if not isinstance(state, Mapping):
        raise RuntimeError("Missing public_logic_fidelity")
    if result.get("system_score_can_override_broken_thesis") is not False:
        raise RuntimeError("System score override boundary was lost")


def self_test() -> None:
    context = {
        "ticker": "TEST", "retrieved_at": "2026-08-31T00:00:00Z",
        "successful_source_families": ["sec_edgar", "yahoo_finance_public_unofficial", "world_bank_indicators"],
        "source_diversity_status": "PASS",
        "sources": [
            {"source_id": "sec_edgar", "ok": True, "retrieved_at": "2026-08-31T00:00:00Z",
             "summary": {"companyfacts_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
                         "recent_material_filings": [{"form": "10-Q", "filing_date": "2026-08-01", "url": "https://www.sec.gov/Archives/test.htm"}]}},
            {"source_id": "yahoo_finance_public_unofficial", "ok": True, "retrieved_at": "2026-08-31T00:00:00Z",
             "summary": {"resolved_symbol": "TEST", "news": []}},
            {"source_id": "world_bank_indicators", "ok": True, "retrieved_at": "2026-08-31T00:00:00Z",
             "summary": {"url": "https://api.worldbank.org/v2/example"}},
        ],
    }
    evidence, status = context_to_evidence(context)
    assert any(row["tier"] == "primary_strong" and row["source_id"] == "sec_edgar" for row in evidence)
    assert any(row["tier"] == "lead_only" and row["source_id"] == "yahoo_finance_public_unofficial" for row in evidence)
    system = {
        "score": 99, "rank": 1,
        "evidence": [{"source_id": "sec_edgar", "tier": "T0",
                      "url": "https://www.sec.gov/Archives/existing.htm",
                      "as_of": "2026-08-15T00:00:00Z", "title": "Existing signed evidence"}],
    }
    evidence = merge_system_evidence(evidence, system)
    result = fidelity.assess_public_logic(conservative_record("TEST", evidence, status, system))
    assert result["public_logic_fidelity"]["dependency_role"] == "UNPROVEN"
    assert result["public_logic_fidelity"]["thesis_class"] == "UNPROVEN"
    assert result["system_operationalization_score"] == 99
    assert result["system_score_can_override_broken_thesis"] is False


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
        print("V213_SERENITY_SHADOW_ADAPTER_SELF_TEST = PASS")
        return 0
    tickers = [clean_ticker(item) for item in args.tickers]
    tickers = [item for item in tickers if item]
    if not tickers:
        raise SystemExit("At least one --tickers symbol is required")
    system_scores = load_system_scores(args.system_universe)
    results = []
    for symbol in tickers:
        try:
            result = shadow_one(symbol, system_scores=system_scores)
            validate_shadow_result(result)
            results.append(result)
        except Exception as exc:
            results.append({"ticker": symbol, "shadow_only": True, "status": "ADAPTER_FAILED",
                            "error": type(exc).__name__, "detail": str(exc)[:300]})
    document = {
        "schema_version": 1, "product_version": "2.1.3",
        "mode": "shadow_only_no_production_mutation", "generated_at": now_iso(),
        "tickers": tickers, "results": results,
        "summary": {"requested": len(tickers),
                    "completed": sum(1 for row in results if row.get("status") != "ADAPTER_FAILED"),
                    "failed": sum(1 for row in results if row.get("status") == "ADAPTER_FAILED"),
                    "production_ranking_changed": False},
    }
    atomic_write(args.output, document)
    print(json.dumps(document["summary"], ensure_ascii=False, sort_keys=True))
    print(f"V213_SERENITY_SHADOW_OUTPUT = {args.output}")
    return 0 if document["summary"]["completed"] >= 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
