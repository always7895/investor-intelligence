#!/usr/bin/env python3
"""Investor Intelligence v2.1.1 coverage upgrade for Serenity-first research.

The v2.1.0 seven-factor Serenity scoring formula remains unchanged.  This layer
fixes candidate-universe coverage bias by combining the existing broad market
screeners with generic AI-infrastructure thematic discovery before SEC
validation.  Theme membership only grants a fair chance to reach full scoring;
it never adds points to the final Serenity score and never inherits an owner
watchlist.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v21_serenity_top20 as base

V211_POLICY_PATH = ROOT / "config" / "v211-serenity-policy.json"
UNIVERSE_PATH = base.PUBLIC_ROOT / "research_universe_public_latest.json"
GENERATED_SYMBOLS_PATH = base.PUBLIC_ROOT / "line_public_symbols_generated.json"
CANDIDATE_CACHE_PATH = base.CACHE_ROOT / "candidate_seed_v211.json"


def v211_policy() -> tuple[dict[str, Any], dict[str, Any]]:
    policy, activation = base.validate_policy()
    overlay = base.load_object(V211_POLICY_PATH)
    if overlay.get("schema_version") != 1 or overlay.get("product_version") != "2.1.1":
        raise base.PipelineError("Invalid v2.1.1 discovery policy")
    if overlay.get("base_scoring_version") != "serenity-first-v2.1.0":
        raise base.PipelineError("v2.1.1 must preserve the accepted v2.1.0 scoring formula")

    merged = dict(policy)
    for key in (
        "candidate_seed_limit",
        "general_seed_limit",
        "thematic_seed_reserve",
        "sec_candidate_limit",
        "sec_thematic_reserve",
        "thematic_search_count",
        "public_option_symbol_limit",
        "thematic_search_terms",
    ):
        merged[key] = overlay[key]

    if not isinstance(merged["thematic_search_terms"], list) or not merged["thematic_search_terms"]:
        raise base.PipelineError("v2.1.1 thematic search terms are empty")
    if any(not str(term).strip() for term in merged["thematic_search_terms"]):
        raise base.PipelineError("v2.1.1 thematic search term is empty")
    if int(merged["candidate_seed_limit"]) < int(merged["top_count"]):
        raise base.PipelineError("v2.1.1 candidate seed limit is too small")
    if int(merged["sec_candidate_limit"]) < int(merged["top_count"]):
        raise base.PipelineError("v2.1.1 SEC candidate limit is too small")
    if not 0 <= int(merged["sec_thematic_reserve"]) <= int(merged["sec_candidate_limit"]):
        raise base.PipelineError("v2.1.1 SEC thematic reserve is invalid")
    return merged, activation


def _entry(merged: dict[str, dict[str, Any]], symbol: str) -> dict[str, Any]:
    return merged.setdefault(
        symbol,
        {
            "ticker": symbol,
            "screen_weight": 0.0,
            "screeners": [],
            "theme_hits": 0,
            "theme_terms": [],
            "market": {},
        },
    )


def _normalized_search_market(raw: Mapping[str, Any]) -> dict[str, Any]:
    market = dict(raw)
    aliases = {
        "shortname": "shortName",
        "longname": "longName",
        "sectorDisp": "sector",
        "industryDisp": "industry",
    }
    for source, target in aliases.items():
        if market.get(target) in (None, "") and market.get(source) not in (None, ""):
            market[target] = market[source]
    return market


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def discover_candidates(policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise base.PipelineError("Verified runtime lacks yfinance") from exc

    merged: dict[str, dict[str, Any]] = {}
    failures: list[str] = []

    # Preserve the accepted v2.1 broad screeners.
    for spec in policy["candidate_screeners"]:
        name = str(spec["name"])
        weight = float(spec["weight"])
        try:
            payload = yf.screen(name, count=int(policy["per_screener_count"]))
            quotes = payload.get("quotes") if isinstance(payload, dict) else None
            if not isinstance(quotes, list):
                raise ValueError("no quotes")
        except Exception as exc:
            failures.append(f"screen:{name}:{type(exc).__name__}")
            continue
        for raw in quotes:
            if not isinstance(raw, dict):
                continue
            symbol = base.ticker(raw.get("symbol"))
            if not symbol:
                continue
            entry = _entry(merged, symbol)
            entry["screen_weight"] = float(entry["screen_weight"]) + weight
            _append_unique(entry["screeners"], name)
            if len(raw) > len(entry["market"]):
                entry["market"] = dict(raw)

    # Add generic bottleneck/thematic discovery.  No ticker is hard-coded here.
    for raw_term in policy["thematic_search_terms"]:
        term = str(raw_term).strip()
        try:
            result = yf.Search(term, max_results=int(policy["thematic_search_count"]))
            quotes = getattr(result, "quotes", None)
            if not isinstance(quotes, list):
                raise ValueError("no quotes")
        except Exception as exc:
            failures.append(f"theme:{term}:{type(exc).__name__}")
            continue
        for raw in quotes:
            if not isinstance(raw, dict):
                continue
            quote_type = str(raw.get("quoteType") or "").strip().upper()
            if quote_type and quote_type not in {"EQUITY", "STOCK"}:
                continue
            symbol = base.ticker(raw.get("symbol"))
            if not symbol:
                continue
            entry = _entry(merged, symbol)
            entry["theme_hits"] = int(entry["theme_hits"]) + 1
            _append_unique(entry["theme_terms"], term)
            normalized = _normalized_search_market(raw)
            if len(normalized) > len(entry["market"]):
                entry["market"] = normalized

    if not merged:
        value = base.cached(CANDIDATE_CACHE_PATH, int(policy["candidate_cache_hours"]))
        if isinstance(value, list) and value:
            return [item for item in value if isinstance(item, dict)]
        raise base.PipelineError("All broad and thematic T3 candidate discovery failed: " + ", ".join(failures))

    broad = sorted(
        (item for item in merged.values() if float(item["screen_weight"]) > 0),
        key=lambda item: (-float(item["screen_weight"]), str(item["ticker"])),
    )
    thematic = sorted(
        (item for item in merged.values() if int(item["theme_hits"]) > 0),
        key=lambda item: (
            -int(item["theme_hits"]),
            -float(item["screen_weight"]),
            str(item["ticker"]),
        ),
    )
    combined = sorted(
        merged.values(),
        key=lambda item: (
            -float(item["screen_weight"]),
            -int(item["theme_hits"]),
            str(item["ticker"]),
        ),
    )

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def take(items: Sequence[dict[str, Any]], limit: int) -> None:
        accepted = 0
        for item in items:
            symbol = str(item["ticker"])
            if symbol in seen:
                continue
            selected.append(item)
            seen.add(symbol)
            accepted += 1
            if accepted >= limit or len(selected) >= int(policy["candidate_seed_limit"]):
                break

    take(broad, int(policy["general_seed_limit"]))
    take(thematic, int(policy["thematic_seed_reserve"]))
    if len(selected) < int(policy["candidate_seed_limit"]):
        take(combined, int(policy["candidate_seed_limit"]) - len(selected))

    base.atomic_json(CANDIDATE_CACHE_PATH, selected)
    if failures:
        base.LOGGER.info("v2.1.1 discovery degraded sources: %s", ", ".join(failures[:12]))
    return selected


def validate_candidates(
    seeds: Sequence[Mapping[str, Any]],
    reference: Mapping[str, Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    allowed = {str(value).casefold() for value in policy["allowed_exchanges"]}
    eligible: list[dict[str, Any]] = []
    for seed in seeds:
        symbol = base.ticker(seed.get("ticker"))
        official = reference.get(symbol)
        if not official or str(official["exchange"]).casefold() not in allowed:
            continue
        market = seed.get("market") if isinstance(seed.get("market"), dict) else {}
        price = base.market_value(market, "regularMarketPrice", "regularMarketPreviousClose")
        cap = base.market_value(market, "marketCap")
        volume = base.market_value(market, "averageDailyVolume3Month", "regularMarketVolume")
        if price is not None and price < float(policy["minimum_price"]):
            continue
        if cap is not None and cap < float(policy["minimum_market_cap"]):
            continue
        if volume is not None and volume < float(policy["minimum_average_volume"]):
            continue
        eligible.append({**dict(seed), "official": dict(official), "preliminary": base.prelim(seed)})

    broad_ranked = sorted(
        eligible,
        key=lambda item: (-float(item["preliminary"]), str(item["ticker"])),
    )
    thematic_ranked = sorted(
        (item for item in eligible if int(item.get("theme_hits") or 0) > 0),
        key=lambda item: (
            -int(item.get("theme_hits") or 0),
            -float(item["preliminary"]),
            str(item["ticker"]),
        ),
    )

    limit = int(policy["sec_candidate_limit"])
    reserve = int(policy["sec_thematic_reserve"])
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def take(items: Sequence[dict[str, Any]], count: int) -> None:
        accepted = 0
        for item in items:
            symbol = str(item["ticker"])
            if symbol in seen:
                continue
            selected.append(item)
            seen.add(symbol)
            accepted += 1
            if accepted >= count or len(selected) >= limit:
                break

    take(broad_ranked, max(0, limit - reserve))
    take(thematic_ranked, reserve)
    if len(selected) < limit:
        take(broad_ranked, limit - len(selected))

    if len(selected) < int(policy["top_count"]):
        raise base.PipelineError(f"Only {len(selected)} SEC-validated v2.1.1 candidates remain")
    return selected


def validate_universe(records: Sequence[Mapping[str, Any]]) -> None:
    if len(records) < 20:
        raise base.PipelineError("v2.1.1 research universe has fewer than 20 scored records")
    if [int(item["rank"]) for item in records] != list(range(1, len(records) + 1)):
        raise base.PipelineError("v2.1.1 research-universe ranks are not contiguous")
    if len({str(item["ticker"]) for item in records}) != len(records):
        raise base.PipelineError("Duplicate ticker in v2.1.1 research universe")
    expected = sorted(
        records,
        key=lambda item: (
            -int(item["serenity_score"]),
            -float(item["data_quality"]),
            str(item["ticker"]),
        ),
    )
    if list(records) != expected:
        raise base.PipelineError("v2.1.1 research-universe order is not deterministic")
    serialized = json.dumps(records, ensure_ascii=False).casefold()
    for forbidden in (
        '"account"', '"portfolio"', '"position"', '"holding"', '"cost_basis"',
        '"pnl"', '"line_user_id"', '"tenant_id"', '"messages"',
    ):
        if forbidden in serialized:
            raise base.PipelineError(f"Forbidden public field in research universe: {forbidden}")


def _write_public_symbol_catalog(records: Sequence[Mapping[str, Any]], limit: int) -> int:
    symbols = [
        {"ticker": str(item["ticker"]), "market_data_ticker": str(item["ticker"]), "currency": "USD"}
        for item in records[: max(0, limit)]
    ]
    base.atomic_json(
        GENERATED_SYMBOLS_PATH,
        {
            "schema_version": 1,
            "owner_watchlist_inheritance": False,
            "symbols": symbols,
        },
    )
    return len(symbols)


def run(*, synthetic: bool) -> dict[str, Any]:
    policy, activation = v211_policy()
    plan = base.source_plan(policy, activation)
    generated = base.iso_now()
    http = base.session()
    macro: dict[str, Any] = {"source_id": "world_bank_indicators", "status": "SYNTHETIC"}

    if synthetic:
        bundles = base.synthetic_candidates()
        thematic_discovered = 0
    else:
        headers = base.sec_headers()
        seeds = discover_candidates(policy)
        thematic_discovered = sum(int(item.get("theme_hits") or 0) > 0 for item in seeds)
        reference = base.sec_reference(policy, http, headers)
        candidates = validate_candidates(seeds, reference, policy)
        bundles = []
        for candidate in candidates:
            try:
                records = base.sec_companyfacts(candidate, policy, http, headers)
                metric, evidence = base.metrics(records)
            except Exception as exc:
                base.LOGGER.warning("SEC facts failed for %s: %s", candidate["ticker"], type(exc).__name__)
                metric, evidence = {}, [
                    base.Evidence(
                        "sec_edgar",
                        "T0",
                        "legal_entity_reference",
                        f"SEC ticker reference for {candidate['ticker']}",
                        str(policy["sec_ticker_exchange_url"]),
                        generated,
                    )
                ]
            bundles.append((candidate, metric, evidence))
        macro = base.world_bank_context(policy, http)

    scored = [base.score_candidate(candidate, metric, evidence, policy) for candidate, metric, evidence in bundles]
    scored.sort(
        key=lambda item: (
            -int(item["serenity_score"]),
            -float(item["data_quality"]),
            str(item["ticker"]),
        )
    )
    if len(scored) < int(policy["top_count"]):
        raise base.PipelineError(f"Only {len(scored)} scored v2.1.1 candidates; 20 required")

    for rank, item in enumerate(scored, start=1):
        item["rank"] = rank
        item["generated_at"] = generated
        item["as_of"] = max((str(e["as_of"]) for e in item["evidence"]), default=generated)

    validate_universe(scored)
    top20 = scored[: int(policy["top_count"])]
    base.validate_top20(top20)

    plan["v211_discovery"] = {
        "product_version": "2.1.1",
        "scoring_formula_changed": False,
        "broad_screener_count": len(policy["candidate_screeners"]),
        "thematic_query_count": len(policy["thematic_search_terms"]),
        "thematic_seed_reserve": int(policy["thematic_seed_reserve"]),
        "sec_thematic_reserve": int(policy["sec_thematic_reserve"]),
        "scored_universe_count": len(scored),
        "owner_watchlist_inherited": False,
    }
    metadata = {
        "schema_version": 1,
        "line_public_eligible": True,
        "provider_scope": "public_only",
        "owner_watchlist_inherited": False,
        "last_successful_pipeline_timestamp": generated,
        "product_version": "2.1.1",
        "research_universe_count": len(scored),
    }
    report = base.build_report(top20, plan, macro, generated).replace(
        "# Investor Intelligence v2.1.0 — Serenity-first 公開 Top 20",
        "# Investor Intelligence v2.1.1 — Serenity-first 公開 Top 20",
        1,
    )
    report += (
        "\n## v2.1.1 candidate coverage\n\n"
        "- Broad market screeners and generic AI-infrastructure thematic discovery are combined before SEC validation.\n"
        "- Thematic discovery only reserves access to full scoring; it does not add Serenity points.\n"
        "- No owner watchlist or owner-specific ticker is inherited.\n"
    )

    base.atomic_json(base.TOP20_PATH, top20)
    base.atomic_json(UNIVERSE_PATH, scored)
    base.atomic_json(base.PLAN_PATH, plan)
    base.atomic_json(base.METADATA_PATH, metadata)
    base.atomic_text(base.REPORT_PATH, report)
    public_option_symbols = _write_public_symbol_catalog(
        scored,
        int(policy["public_option_symbol_limit"]),
    )

    return {
        "top20_count": len(top20),
        "research_universe_count": len(scored),
        "thematic_discovered_count": thematic_discovered,
        "public_option_symbol_count": public_option_symbols,
        "catalog_count": plan["catalog_count"],
        "top20_path": str(base.TOP20_PATH),
        "universe_path": str(UNIVERSE_PATH),
        "public_symbols_path": str(GENERATED_SYMBOLS_PATH),
        "source_plan_path": str(base.PLAN_PATH),
        "report_path": str(base.REPORT_PATH),
        "macro_status": macro.get("status"),
    }


def self_test() -> None:
    output = run(synthetic=True)
    if output["top20_count"] != 20 or output["catalog_count"] != 101:
        raise base.PipelineError("v2.1.1 synthetic acceptance failed")
    if output["research_universe_count"] < 20:
        raise base.PipelineError("v2.1.1 synthetic universe is incomplete")
    if "AAOI" in V211_POLICY_PATH.read_text(encoding="utf-8").upper() or "SIVE" in V211_POLICY_PATH.read_text(encoding="utf-8").upper():
        raise base.PipelineError("Owner-specific ticker leaked into thematic discovery policy")
    print("V211_SERENITY_UNIVERSE_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        else:
            print(json.dumps(run(synthetic=args.synthetic), ensure_ascii=False, indent=2))
        return 0
    except (base.PipelineError, OSError, ValueError, base.requests.RequestException) as exc:
        base.LOGGER.error("V2.1.1 Serenity universe failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
