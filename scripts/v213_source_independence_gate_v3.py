#!/usr/bin/env python3
"""Stable entrypoint for the final v2.1.3 source-independence gate.

The authoritative market-quality implementation lives in
``v213_source_independence_gate_v4.py``. Before that gate consumes the final
Top20, this wrapper adds one provenance-only row for the newest actual SEC
filing found in the same live Company Facts cache used by candidate research.
The filing date comes from SEC's ``filed`` field, never the retrieval timestamp;
the financial period end remains separate and cannot masquerade as publication
time.

Duplicate evidence observations are then ordered by actual publication date so
publisher-family deduplication keeps the freshest filed observation. After the
gate succeeds, qualified federation rows are normalized to final diversified
Top20 order. None of these boundary operations changes membership, financial
values, market values, source conflicts, or positive factor scores.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
V4_PATH = SCRIPT_DIR / "v213_source_independence_gate_v4.py"
TOP20_PATH = ROOT / "data" / "cache" / "top20_public_latest.json"
FEDERATION_PATH = ROOT / "data" / "cache" / "v213_source_federation_latest.json"
SEC_REFERENCE_PATH = ROOT / "data" / "cache" / "sec_company_tickers_exchange.json"
SEC_COMPANYFACTS_DIR = ROOT / "data" / "cache" / "companyfacts"
SEC_FILING_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "40-F", "6-K", "8-K"}


class FederationOrderError(RuntimeError):
    """Qualified publication inputs cannot be normalized without mutation."""


def _load_v4():
    if not V4_PATH.is_file():
        raise RuntimeError(f"Missing final source-independence implementation: {V4_PATH}")
    spec = importlib.util.spec_from_file_location(
        "investor_intelligence_v213_source_gate_v4_entrypoint",
        V4_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load final source-independence gate: {V4_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


v4 = _load_v4()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FederationOrderError(f"Unable to read qualified publication input: {path}") from exc


def _load_object(path: Path) -> dict[str, Any]:
    value = _load_json(path)
    if not isinstance(value, dict):
        raise FederationOrderError(f"Expected JSON object: {path}")
    return value


def _top_rows(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else value.get("records") if isinstance(value, dict) else None
    if not isinstance(rows, list) or len(rows) != 20 or not all(isinstance(row, dict) for row in rows):
        raise FederationOrderError("Final diversified Top20 must contain exactly 20 object rows")
    return rows


def _atomic_write(path: Path, value: Any) -> None:
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
        temporary = Path(handle.name)
    temporary.replace(path)


def _date_text(value: Any) -> str:
    text = str(value or "").strip()[:10]
    if not text:
        return ""
    try:
        return dt.date.fromisoformat(text).isoformat()
    except ValueError:
        return ""


def _publication_date(source: Mapping[str, Any]) -> str:
    """Return a real publication/filing date without using retrieval time."""

    for key in ("publication_date", "published_at", "filed_at", "filed", "as_of"):
        value = _date_text(source.get(key))
        if value:
            return value
    return ""


def _freshest_first_evidence(raw: list[Any]) -> list[Any]:
    """Stable-sort observations newest first; source membership is unchanged."""

    return sorted(
        raw,
        key=lambda item: _publication_date(item) if isinstance(item, Mapping) else "",
        reverse=True,
    )


def _sec_ticker_cik_map(document: Mapping[str, Any]) -> dict[str, str]:
    fields = document.get("fields")
    data = document.get("data")
    if not isinstance(fields, list) or not isinstance(data, list):
        raise FederationOrderError("SEC ticker reference JSON shape changed")
    names = [str(value) for value in fields]
    result: dict[str, str] = {}
    for raw in data:
        if not isinstance(raw, list) or len(raw) != len(names):
            continue
        item = dict(zip(names, raw))
        ticker = str(item.get("ticker") or "").strip().upper()
        cik = str(item.get("cik") or "").strip()
        if ticker and cik.isdigit():
            result[ticker] = cik.zfill(10)
    if not result:
        raise FederationOrderError("SEC ticker reference contains no usable ticker/CIK rows")
    return result


def _latest_sec_filing(document: Mapping[str, Any], cik: str, ticker: str) -> dict[str, Any] | None:
    """Extract newest actual filing metadata from raw SEC Company Facts JSON."""

    facts = document.get("facts")
    if not isinstance(facts, Mapping):
        return None
    candidates: list[dict[str, Any]] = []
    for taxonomy in facts.values():
        if not isinstance(taxonomy, Mapping):
            continue
        for fact in taxonomy.values():
            if not isinstance(fact, Mapping):
                continue
            units = fact.get("units")
            if not isinstance(units, Mapping):
                continue
            for observations in units.values():
                if not isinstance(observations, list):
                    continue
                for observation in observations:
                    if not isinstance(observation, Mapping):
                        continue
                    filed = _date_text(observation.get("filed"))
                    form = str(observation.get("form") or "").strip().upper()
                    accession = str(observation.get("accn") or "").strip()
                    if not filed or form not in SEC_FILING_FORMS:
                        continue
                    candidates.append(
                        {
                            "filed": filed,
                            "form": form,
                            "accession": accession,
                            "period_end": _date_text(observation.get("end")),
                        }
                    )
    if not candidates:
        return None
    latest = max(candidates, key=lambda item: (item["filed"], item["accession"], item["form"]))
    accession_compact = str(latest["accession"]).replace("-", "")
    cik_numeric = str(int(cik)) if cik.isdigit() else cik
    if accession_compact:
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_numeric}/{accession_compact}/"
    else:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    return {
        "source_id": "sec_edgar",
        "family": "regulator_filing",
        "tier": "T0",
        "claim_type": "filing_publication_provenance",
        "title": f"SEC {latest['form']} filing publication for {ticker}",
        "url": url,
        "as_of": latest["filed"],
        "publication_date": latest["filed"],
        "period_end": latest["period_end"],
        "accession_number": latest["accession"],
        "primary": True,
        "claim_primary": True,
        "provenance_only": True,
        "can_prove_positive_serenity_factor": False,
        "retrieval_timestamp_used_as_publication_date": False,
    }


def enrich_top20_with_latest_sec_filing_provenance() -> None:
    """Add one newest SEC filing row per ticker from the already-fetched cache."""

    top_value = _load_json(TOP20_PATH)
    top_rows = _top_rows(top_value)
    cik_map = _sec_ticker_cik_map(_load_object(SEC_REFERENCE_PATH))
    enriched = 0
    missing: list[str] = []
    for row in top_rows:
        ticker = str(row.get("ticker") or "").strip().upper()
        cik = cik_map.get(ticker, "")
        cache_path = SEC_COMPANYFACTS_DIR / f"CIK{cik}.json"
        if not cik or not cache_path.is_file():
            missing.append(ticker)
            continue
        filing = _latest_sec_filing(_load_object(cache_path), cik, ticker)
        if filing is None:
            missing.append(ticker)
            continue
        evidence = row.get("evidence")
        if not isinstance(evidence, list):
            evidence = []
            row["evidence"] = evidence
        evidence[:] = [
            item
            for item in evidence
            if not (
                isinstance(item, Mapping)
                and str(item.get("claim_type") or "") == "filing_publication_provenance"
            )
        ]
        evidence.append(filing)
        row["evidence_count"] = len(evidence)
        source_ids = {
            str(item.get("source_id") or "")
            for item in evidence
            if isinstance(item, Mapping) and str(item.get("source_id") or "")
        }
        row["source_count"] = len(source_ids | {"yahoo_finance_public_unofficial"})
        enriched += 1
    if missing:
        raise FederationOrderError(
            "Latest SEC filing provenance is unavailable for final Top20: " + ",".join(sorted(missing))
        )
    _atomic_write(TOP20_PATH, top_value)
    print(
        "V213_LATEST_SEC_FILING_PROVENANCE = PASS; "
        f"tickers={enriched}; source=SEC_COMPANYFACTS_CACHE; "
        "filed_date_used=true; period_end_preserved=true; retrieval_time_used=false; "
        "positive_factor_support=false",
        flush=True,
    )


def normalize_top20_evidence_publication_order() -> None:
    top_value = _load_json(TOP20_PATH)
    top_rows = _top_rows(top_value)
    changed_rows = 0
    evidence_count_before = 0
    evidence_count_after = 0
    for row in top_rows:
        raw = row.get("evidence")
        if not isinstance(raw, list):
            continue
        evidence_count_before += len(raw)
        ordered = _freshest_first_evidence(raw)
        evidence_count_after += len(ordered)
        if ordered != raw:
            changed_rows += 1
            row["evidence"] = ordered
    if evidence_count_before != evidence_count_after:
        raise FederationOrderError("Top20 evidence chronology normalization changed source count")
    _atomic_write(TOP20_PATH, top_value)
    print(
        "V213_TOP20_EVIDENCE_PUBLICATION_ORDER = PASS; "
        f"rows_reordered={changed_rows}; evidence_count={evidence_count_after}; "
        "retrieval_time_used=false; membership_changed=false; values_changed=false",
        flush=True,
    )


def normalize_federation_to_final_top20() -> None:
    top_value = _load_json(TOP20_PATH)
    top_rows = _top_rows(top_value)
    order = [str(row.get("ticker") or "").strip().upper() for row in top_rows]
    if any(not ticker for ticker in order) or len(set(order)) != 20:
        raise FederationOrderError("Final diversified Top20 membership is invalid")

    federation = _load_object(FEDERATION_PATH)
    raw_rows = federation.get("ticker_sources")
    if not isinstance(raw_rows, list) or len(raw_rows) != 20:
        raise FederationOrderError("Qualified source federation must contain exactly 20 ticker rows")

    mapping: dict[str, dict[str, Any]] = {}
    original_order: list[str] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise FederationOrderError("Qualified source-federation row must be an object")
        ticker = str(raw.get("ticker") or "").strip().upper()
        if not ticker or ticker in mapping:
            raise FederationOrderError("Qualified source-federation membership is invalid or duplicated")
        mapping[ticker] = dict(raw)
        original_order.append(ticker)
    if set(mapping) != set(order):
        missing = sorted(set(order) - set(mapping))
        extra = sorted(set(mapping) - set(order))
        raise FederationOrderError(
            "Qualified source-federation membership differs from final Top20; "
            f"missing={','.join(missing) or '-'}; extra={','.join(extra) or '-'}"
        )

    normalized: list[dict[str, Any]] = []
    for rank, ticker in enumerate(order, 1):
        row = mapping[ticker]
        row["rank"] = rank
        normalized.append(row)
    federation["ticker_sources"] = normalized
    federation["final_top20_order_normalization"] = {
        "schema_version": 1,
        "status": "PASS",
        "membership_changed": False,
        "evidence_changed": False,
        "source_values_changed": False,
        "original_order": original_order,
        "final_order": order,
        "reordered": original_order != order,
    }
    _atomic_write(FEDERATION_PATH, federation)
    print(
        "V213_SOURCE_FEDERATION_FINAL_ORDER = PASS; "
        f"rows=20; reordered={str(original_order != order).lower()}; "
        "membership_changed=false; evidence_changed=false",
        flush=True,
    )


def _wrapper_self_test() -> None:
    sample = [
        {
            "source_id": "sec_edgar",
            "as_of": "2026-02-01",
            "retrieved_at": "2026-09-03T10:00:00Z",
        },
        {
            "source_id": "sec_edgar",
            "publication_date": "2026-07-29",
            "as_of": "2026-06-30",
        },
        {
            "source_id": "issuer_primary",
            "published_at": "2026-05-01T12:00:00Z",
        },
    ]
    ordered = _freshest_first_evidence(sample)
    assert ordered[0]["publication_date"] == "2026-07-29"
    assert ordered[-1]["as_of"] == "2026-02-01"
    assert _publication_date(sample[0]) == "2026-02-01"

    synthetic_companyfacts = {
        "facts": {
            "us-gaap": {
                "Revenue": {
                    "units": {
                        "USD": [
                            {
                                "form": "10-K",
                                "filed": "2026-02-01",
                                "end": "2025-12-31",
                                "accn": "0000000000-26-000001",
                            },
                            {
                                "form": "10-Q",
                                "filed": "2026-07-29",
                                "end": "2026-06-30",
                                "accn": "0000000000-26-000002",
                            },
                        ]
                    }
                }
            }
        }
    }
    latest = _latest_sec_filing(synthetic_companyfacts, "0000000001", "TEST")
    assert latest is not None
    assert latest["as_of"] == "2026-07-29"
    assert latest["period_end"] == "2026-06-30"
    assert latest["retrieval_timestamp_used_as_publication_date"] is False
    assert latest["can_prove_positive_serenity_factor"] is False

    v4.self_test()
    print(
        "V213_SOURCE_GATE_V3_WRAPPER_SELF_TEST = PASS; "
        "freshest_publication_first=true; latest_sec_filing_provenance=true; "
        "period_end_preserved=true; retrieval_time_ignored=true"
    )


def main() -> int:
    if "--wrapper-self-test" in sys.argv:
        _wrapper_self_test()
        return 0
    enrich_top20_with_latest_sec_filing_provenance()
    normalize_top20_evidence_publication_order()
    result = int(v4.gate.main())
    if result != 0:
        return result
    normalize_federation_to_final_top20()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FederationOrderError, OSError, ValueError) as exc:
        print(f"V213_SOURCE_GATE_V3_WRAPPER = FAIL; {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
