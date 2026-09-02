#!/usr/bin/env python3
"""Fail closed unless every current public-schema field has zh-TW + English labels.

Scope: v2.1 Top20/evidence/source-plan/snapshot envelope, v2.1.1 public options
DTO, v2.1.2/v2.1.3 reports, and the v2.1.3 live source-federation/truth-gate
schema. Internal secrets and local-only process-state keys are excluded.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DICTIONARIES = (
    ROOT / "config" / "field-labels.zh-en.json",
    ROOT / "config" / "field-labels-source-federation.zh-en.json",
)

REQUIRED_FIELDS = {
    # Snapshot/document envelope and source-plan/public symbol metadata.
    "schema_version", "product_version", "run_id", "generated_at", "public_data_as_of",
    "payloads", "sha256", "top20_json", "research_universe_json", "options_json",
    "source_plan_json", "report_text", "catalog_count", "automatic_activation",
    "inventory", "runtime_enabled_count", "topic_counts", "symbols",
    "owner_watchlist_inheritance", "market_data_ticker", "output",
    # Top20/research/evidence.
    "ticker", "name", "serenity_score", "serenity_raw_score", "risk_penalty",
    "data_quality", "rating", "category", "serenity_factors", "risk_flags",
    "aschenbrenner_overlay", "evidence", "evidence_count", "source_count",
    "scoring_version", "line_public_eligible", "provider_scope",
    "owner_watchlist_inherited", "rank", "as_of", "source_id", "tier",
    "claim_type", "title", "url", "demand_wave", "chokepoint", "pricing_power",
    "replacement_friction", "tam_capture", "valuation_expectations",
    "evidence_quality", "domain", "fit_score", "included_in_serenity_score",
    "attribution",
    # v2.1.1 public options top-level and candidate DTO.
    "provider_symbol", "currency", "current_price", "retrieved_at", "status",
    "quote_source", "quote_delay_status", "ibkr_connected", "brokerage_data_included",
    "account_data_included", "position_data_included", "periods", "weekly", "monthly",
    "target_dte", "expiration", "actual_dte", "covered_call", "cash_secured_put",
    "call_observations", "put_observations", "recommended_candidates", "eligible_count",
    "window_observation_count", "option_type", "contract_symbol", "strike", "spot",
    "distance_from_spot_pct", "bid", "ask", "midpoint", "last", "spread",
    "spread_pct_of_mid", "volume", "open_interest", "implied_volatility_pct", "delta",
    "delta_status", "last_trade_at", "last_trade_age_days", "two_sided_quote",
    "liquidity_pass", "liquidity_reasons", "quote_quality_rank", "sell_limit_observation",
    "annualized_yield_pct", "effective_sale_price", "put_break_even",
    "cash_secured_put_cash_requirement", "premium", "annualized_yield_pct_mid", "implied_vol",
    # v2.1.2/v2.1.3 reports.
    "display_columns", "long_term_definition", "short_term_definition", "records",
    "long_term_return_pct", "short_term_return_pct", "industry", "profit_summary",
    "long_term_window", "short_term_window", "market_source", "profit_source",
    "current_orders", "future_orders_estimate", "orders_as_of", "orders_confidence",
    "current_order_source_urls", "future_order_source_urls",
    "numeric_total_order_estimate_prohibited",
    # v2.1.3 live source federation and diversified methodology metadata.
    "policy_id", "global_sources", "ticker_sources", "unresolved_material_conflicts",
    "coverage", "concentration", "disclosures", "gates", "family", "authority", "role",
    "official", "detail", "successful_families", "official_successful_families",
    "missing_required_families", "ticker_rows_meeting_minimum", "ticker_count",
    "ticker_coverage_ratio", "minimum_per_ticker_independent_families",
    "minimum_official_identity_or_filing_families", "deficient_tickers",
    "largest_family_share", "maximum_single_family_evidence_share", "concentration_pass",
    "unresolved_material_conflict_count", "yahoo_authoritative",
    "catalog_source_count_is_not_live_use", "claim_scope_separation_enforced", "source_ids",
    "independent_families", "independent_family_count",
    "official_identity_or_filing_families", "official_identity_or_filing_family_count",
    "market_observation_families", "market_provider_confidence",
    "issuer_financial_claim_family_count", "evidence_additions", "gleif_match",
    "listing_identity", "nasdaq_listing_matches", "gleif_identity_matches",
    "alpha_vantage_market_matches", "yahoo_market_observations", "family_counts",
    "largest_family", "source_catalog_size_is_not_live_source_count",
    "different_claim_scopes_are_not_false_corroboration",
    "issuer_financials_remain_sec_primary_until_independent_claim_source_exists",
    "local_model_may_not_create_source_success", "security_name", "exchange", "source_url",
    "lei", "legal_name", "entity_status", "registration_status", "last_update", "similarity",
    "cache_hit", "cache_hits", "credential_present", "observations", "latest_date",
    "latest_adjusted_close", "series", "value", "ticker_observations", "ticker_matches",
    "scoring_methodology", "machine_key_compatibility", "display_label",
    "official_serenity_formula_claimed", "keyword_only_chokepoint_points",
    "gross_margin_only_replacement_friction_points",
    "single_market_provider_valuation_cap_fraction",
}

SEVEN_FIELD_EXPECTED = {
    "ticker": ("股票", "Ticker"),
    "long_term_return_pct": ("長期投資報酬率（近2年年化）", "Long-term return (2Y annualized)"),
    "short_term_return_pct": ("短期投資報酬率（近6個月）", "Short-term return (6M)"),
    "industry": ("行業別", "Industry"),
    "profit_summary": ("獲利簡述", "Profit summary"),
    "current_orders": ("公司現在訂單", "Current orders"),
    "future_orders_estimate": ("未來訂單預估", "Future order outlook"),
}


def load_fields() -> dict[str, dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for path in DICTIONARIES:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if raw.get("product_version") != "2.1.3":
            raise SystemExit(f"BILINGUAL_AUDIT_FAIL: product_version={path.name}")
        fields = raw.get("fields")
        if not isinstance(fields, dict):
            raise SystemExit(f"BILINGUAL_AUDIT_FAIL: fields object missing={path.name}")
        overlap = sorted(set(merged) & set(fields))
        if overlap:
            raise SystemExit("BILINGUAL_AUDIT_FAIL: duplicate_keys=" + ",".join(overlap))
        merged.update(fields)
    return merged


def main() -> int:
    fields = load_fields()
    missing = sorted(REQUIRED_FIELDS - set(fields))
    if missing:
        raise SystemExit("BILINGUAL_AUDIT_FAIL: missing=" + ",".join(missing))

    incomplete: list[str] = []
    for key in sorted(REQUIRED_FIELDS):
        value = fields.get(key)
        if not isinstance(value, dict):
            incomplete.append(key)
            continue
        zh = value.get("zh-TW")
        en = value.get("en")
        if not isinstance(zh, str) or not zh.strip() or not isinstance(en, str) or not en.strip():
            incomplete.append(key)
    if incomplete:
        raise SystemExit("BILINGUAL_AUDIT_FAIL: incomplete=" + ",".join(incomplete))

    for key, (zh_expected, en_expected) in SEVEN_FIELD_EXPECTED.items():
        value = fields[key]
        if value["zh-TW"] != zh_expected or value["en"] != en_expected:
            raise SystemExit(f"BILINGUAL_AUDIT_FAIL: seven-field label mismatch={key}")

    for key in ("serenity_score", "serenity_raw_score", "serenity_factors"):
        blob = (fields[key]["zh-TW"] + " " + fields[key]["en"]).lower()
        if "system" not in blob and "系統" not in blob:
            raise SystemExit(f"BILINGUAL_AUDIT_FAIL: legacy score attribution={key}")

    formula = fields["official_serenity_formula_claimed"]
    if "是否宣稱" not in formula["zh-TW"] or "claimed" not in formula["en"].lower():
        raise SystemExit("BILINGUAL_AUDIT_FAIL: formula-claim label")

    print(
        f"V213_BILINGUAL_PUBLIC_FIELD_AUDIT = PASS; "
        f"required_fields={len(REQUIRED_FIELDS)}; dictionaries={len(DICTIONARIES)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
