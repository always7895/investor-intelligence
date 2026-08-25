#!/usr/bin/env python3
"""Project-authored research scoring and user-preference overlay.

The five-layer score is a system operationalization inspired by public source
material. It is not an official Serenity score, an official Leopold
Aschenbrenner score, an endorsement, a holding-period rule, a price target or a
return forecast.

An optional local user's holding-horizon preference is calculated separately
from an ignored local configuration and never changes the methodology-research
score.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from local_research_config import load_local_preferences, load_research_universe

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data" / "cache"

DIRECT_AI_KEYWORDS = {
    "gpu",
    "neocloud",
    "hbm",
    "optical",
    "optics",
    "inp",
    "cpo",
    "ai data",
    "ai compute",
    "asic",
    "networking",
    "storage",
    "nand",
    "foundry",
    "process",
    "fiber",
    "semiconductor",
}
POWER_KEYWORDS = {
    "power",
    "fuel cell",
    "natural gas",
    "data center",
    "datacenter",
    "grid",
    "transformer",
    "switchgear",
}
POTENTIAL_CHOKEPOINT_CATEGORIES = {
    "inp substrate",
    "cpo cw laser",
    "hbm memory",
    "advanced foundry",
    "advanced process",
}
POTENTIAL_SWITCHING_BARRIER_CATEGORIES = {
    "optical transceiver",
    "optical transceiver/els",
    "optical communications",
    "optical test",
    "optical test equipment",
    "optics",
}
DURABLE_MOAT_KEYWORDS = {
    "inp",
    "hbm",
    "foundry",
    "process",
    "optical",
    "cpo",
    "neocloud",
    "gpu",
    "asic",
    "networking",
    "fiber",
    "power",
    "transformer",
}

DEFAULT_USER_PREFERENCES: dict[str, Any] = {
    "schema_version": 1,
    "privacy_class": "local_user_configuration",
    "long_term_overlay": {
        "enabled": False,
        "minimum_holding_years": 2,
        "owner": "local_user",
        "affects_source_view": False,
        "affects_methodology_research_score": False,
        "report_title": "Local user-defined long-term suitability overlay",
        "labels": {
            "high": "較適合長期研究",
            "conditional": "條件式長期觀察",
            "event_driven": "偏事件／交易型",
            "insufficient": "資料不足",
        },
    },
}


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def contains_any(text: Any, keywords: set[str]) -> bool:
    lowered = str(text or "").casefold()
    return any(keyword in lowered for keyword in keywords)


def normalized_debt_to_equity(value: Any) -> float | None:
    """Normalize yfinance debtToEquity, which is often returned in percentage points."""
    number = safe_float(value)
    if number is None:
        return None
    return number / 100.0 if abs(number) > 10 else number


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def evidence_count(stock_meta: dict[str, Any], key: str) -> int:
    value = stock_meta.get(key, 0)
    if isinstance(value, list):
        return len(value)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def load_data(path: Path | None = None) -> list[dict[str, Any]]:
    source = path or DATA_DIR / "market_latest.json"
    if not source.is_file():
        raise FileNotFoundError(f"Market data not found: {source}")
    document = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(document, list):
        raise ValueError("market_latest.json must contain an array")
    return [item for item in document if isinstance(item, dict)]


def load_watchlist(path: Path | None = None) -> list[dict[str, Any]]:
    return load_research_universe(path)


def load_user_preferences(path: Path | None = None) -> dict[str, Any]:
    return load_local_preferences(path, default=DEFAULT_USER_PREFERENCES)


def data_quality(stock_data: dict[str, Any]) -> float:
    fields = (
        "market_cap",
        "revenue_ttm",
        "revenue_growth",
        "forward_pe",
        "ps_ratio",
        "gross_margin",
        "operating_margin",
        "profit_margin",
        "free_cash_flow",
        "total_cash",
        "total_debt",
        "debt_to_equity",
        "beta",
        "short_pct_float",
    )
    available = sum(safe_float(stock_data.get(field)) is not None for field in fields)
    return available / len(fields)


def score_l1_demand_wave(
    stock_data: dict[str, Any], stock_meta: dict[str, Any]
) -> tuple[int, list[str]]:
    """System operationalization: demand and infrastructure alignment, max 20."""
    category = stock_meta.get("category", "")
    reasons: list[str] = []

    if contains_any(category, DIRECT_AI_KEYWORDS):
        alignment = 8
        reasons.append("Category maps to AI compute/component/data infrastructure")
    elif contains_any(category, POWER_KEYWORDS):
        alignment = 7
        reasons.append("Category maps to AI power/physical infrastructure")
    elif category:
        alignment = 3
        reasons.append("Indirect infrastructure category")
    else:
        alignment = 0
        reasons.append("Category unavailable")

    primary_demand = evidence_count(stock_meta, "demand_primary_evidence")
    growth = safe_float(stock_data.get("revenue_growth"))
    if primary_demand >= 2 and growth is not None and growth > 0:
        demand = 7
        reasons.append(f"{primary_demand} primary demand records and positive revenue-growth proxy")
    elif primary_demand >= 1:
        demand = 5
        reasons.append("At least one primary demand record")
    elif growth is None:
        demand = 0
        reasons.append("Demand evidence and revenue-growth proxy unavailable")
    elif growth >= 0.50:
        demand = 5
        reasons.append(f"Strong revenue-growth proxy {growth:.1%}; primary demand evidence pending")
    elif growth >= 0.30:
        demand = 4
        reasons.append(f"Revenue-growth proxy {growth:.1%}; primary demand evidence pending")
    elif growth >= 0.15:
        demand = 3
        reasons.append(f"Moderate revenue-growth proxy {growth:.1%}")
    elif growth > 0:
        demand = 1
        reasons.append(f"Low positive revenue-growth proxy {growth:.1%}")
    else:
        demand = 0
        reasons.append(f"Non-positive revenue-growth proxy {growth:.1%}")

    stage = str(stock_meta.get("implementation_stage", "")).casefold()
    if stage in {"shipping", "production", "ramping"} and primary_demand >= 1:
        implementation = 5
        reasons.append(f"Implementation stage: {stage}")
    elif stage in {"qualification", "design_win", "contracted"}:
        implementation = 3
        reasons.append(f"Implementation stage: {stage}")
    elif stock_meta.get("dated_catalyst"):
        implementation = 2
        reasons.append("Dated catalyst recorded; implementation evidence incomplete")
    else:
        implementation = 0
        reasons.append("Implementation stage not evidenced")

    return min(alignment + demand + implementation, 20), reasons


def score_l2_bottleneck(
    stock_data: dict[str, Any], stock_meta: dict[str, Any]
) -> tuple[int, list[str]]:
    """System operationalization: potential constraint and replacement difficulty, max 25."""
    category = str(stock_meta.get("category", ""))
    normalized_category = category.casefold()
    reasons: list[str] = []

    bottleneck_level = str(stock_meta.get("bottleneck_evidence_level", "")).casefold()
    primary_constraint = evidence_count(stock_meta, "bottleneck_primary_evidence")
    if bottleneck_level == "primary_verified" and primary_constraint >= 2:
        position = 10
        reasons.append("Bottleneck position supported by multiple primary records")
    elif bottleneck_level in {"primary_verified", "corroborated"} and primary_constraint >= 1:
        position = 8
        reasons.append("Bottleneck position has primary support")
    elif normalized_category in POTENTIAL_CHOKEPOINT_CATEGORIES:
        position = 5
        reasons.append("Category is a potential chokepoint hypothesis; company-level proof pending")
    elif normalized_category in POTENTIAL_SWITCHING_BARRIER_CATEGORIES:
        position = 4
        reasons.append("Category may have qualification barriers; company-level proof pending")
    elif contains_any(category, {"neocloud", "gpu", "asic", "networking", "power"}):
        position = 3
        reasons.append("Important infrastructure position, not automatically a bottleneck")
    elif category:
        position = 1
        reasons.append("Bottleneck relevance not evidenced")
    else:
        position = 0
        reasons.append("Category unavailable")

    gross_margin = safe_float(stock_data.get("gross_margin"))
    price_increase_evidence = evidence_count(stock_meta, "pricing_primary_evidence")
    if price_increase_evidence >= 1 and gross_margin is not None and gross_margin >= 0.40:
        pricing = 8
        reasons.append("Primary pricing evidence plus strong gross margin")
    elif price_increase_evidence >= 1:
        pricing = 6
        reasons.append("Primary pricing evidence recorded")
    elif gross_margin is None:
        pricing = 0
        reasons.append("Pricing evidence and gross margin unavailable")
    elif gross_margin >= 0.60:
        pricing = 6
        reasons.append(f"Gross margin {gross_margin:.1%} supports a pricing-power hypothesis")
    elif gross_margin >= 0.40:
        pricing = 5
        reasons.append(f"Gross margin {gross_margin:.1%} supports a pricing-power hypothesis")
    elif gross_margin >= 0.25:
        pricing = 3
        reasons.append(f"Gross margin {gross_margin:.1%} indicates moderate pricing")
    elif gross_margin > 0:
        pricing = 1
        reasons.append(f"Gross margin {gross_margin:.1%} indicates limited pricing")
    else:
        pricing = 0
        reasons.append("No positive gross-margin evidence")

    qualification_months = safe_float(stock_meta.get("qualification_months"))
    substitutes = safe_float(stock_meta.get("qualified_substitute_count"))
    if qualification_months is not None and qualification_months >= 18 and substitutes == 0:
        replacement = 7
        reasons.append("Documented long qualification period and no qualified substitute")
    elif qualification_months is not None and qualification_months >= 12:
        replacement = 5
        reasons.append(f"Documented qualification period {qualification_months:.0f} months")
    elif substitutes is not None and substitutes <= 1:
        replacement = 4
        reasons.append("Limited qualified substitutes recorded")
    elif normalized_category in POTENTIAL_CHOKEPOINT_CATEGORIES:
        replacement = 3
        reasons.append("Category suggests replacement friction; direct evidence pending")
    elif normalized_category in POTENTIAL_SWITCHING_BARRIER_CATEGORIES:
        replacement = 2
        reasons.append("Potential qualification friction; direct evidence pending")
    else:
        replacement = 0
        reasons.append("Replacement difficulty not evidenced")

    return min(position + pricing + replacement, 25), reasons


def score_l3_company_quality(
    stock_data: dict[str, Any], _stock_meta: dict[str, Any]
) -> tuple[int, list[str]]:
    """System operationalization: financial endurance and financing quality, max 20."""
    reasons: list[str] = []
    profit_margin = safe_float(stock_data.get("profit_margin"))
    operating_margin = safe_float(stock_data.get("operating_margin"))

    if profit_margin is None:
        profitability = 0
        reasons.append("Profit margin unavailable")
    elif profit_margin >= 0.20:
        profitability = 7
        reasons.append(f"Profit margin {profit_margin:.1%}")
    elif profit_margin >= 0.05:
        profitability = 5
        reasons.append(f"Profit margin {profit_margin:.1%}")
    elif profit_margin > 0:
        profitability = 3
        reasons.append(f"Thin positive profit margin {profit_margin:.1%}")
    elif operating_margin is not None and operating_margin > -0.20:
        profitability = 1
        reasons.append("Pre-profit operating profile")
    else:
        profitability = 0
        reasons.append("Material losses or insufficient margin data")

    free_cash_flow = safe_float(stock_data.get("free_cash_flow"))
    market_cap = safe_float(stock_data.get("market_cap"))
    if free_cash_flow is None or market_cap is None or market_cap <= 0:
        cash_flow = 0
        reasons.append("Free-cash-flow yield unavailable")
    else:
        fcf_yield = free_cash_flow / market_cap
        if fcf_yield >= 0.05:
            cash_flow = 6
        elif fcf_yield > 0:
            cash_flow = 4
        elif fcf_yield >= -0.02:
            cash_flow = 2
        else:
            cash_flow = 0
        reasons.append(f"Free-cash-flow yield {fcf_yield:.1%}")

    total_cash = safe_float(stock_data.get("total_cash"))
    total_debt = safe_float(stock_data.get("total_debt"))
    debt_to_equity = normalized_debt_to_equity(stock_data.get("debt_to_equity"))
    if total_cash is not None and total_debt is not None and total_cash > total_debt:
        balance = 7
        reasons.append("Net cash position")
    elif debt_to_equity is None:
        balance = 0
        reasons.append("Leverage data unavailable")
    elif debt_to_equity < 0.50:
        balance = 6
        reasons.append(f"Debt/equity proxy {debt_to_equity:.2f}")
    elif debt_to_equity < 1.00:
        balance = 5
        reasons.append(f"Debt/equity proxy {debt_to_equity:.2f}")
    elif debt_to_equity < 2.00:
        balance = 3
        reasons.append(f"Elevated debt/equity proxy {debt_to_equity:.2f}")
    elif debt_to_equity < 3.00:
        balance = 2
        reasons.append(f"High debt/equity proxy {debt_to_equity:.2f}")
    else:
        balance = 0
        reasons.append(f"Very high debt/equity proxy {debt_to_equity:.2f}")

    return min(profitability + cash_flow + balance, 20), reasons


def score_l4_valuation_catalyst(
    stock_data: dict[str, Any], stock_meta: dict[str, Any]
) -> tuple[int, list[str]]:
    """System operationalization: valuation evidence and dated catalysts, max 15."""
    reasons: list[str] = []
    forward_pe = safe_float(stock_data.get("forward_pe"))
    ps_ratio = safe_float(stock_data.get("ps_ratio"))
    growth = safe_float(stock_data.get("revenue_growth"))

    valuation = 0
    if forward_pe is not None and forward_pe > 0 and growth is not None and growth > 0.01:
        growth_percent = growth * 100
        peg_like = forward_pe / growth_percent
        if peg_like < 0.75:
            valuation = 7
        elif peg_like < 1.50:
            valuation = 5
        elif peg_like < 3.00:
            valuation = 3
        else:
            valuation = 1
        reasons.append(f"Forward P/E-to-growth proxy {peg_like:.2f}")
    elif ps_ratio is not None and ps_ratio > 0 and growth is not None and growth > 0:
        if ps_ratio < 5 and growth >= 0.30:
            valuation = 6
        elif ps_ratio < 10 and growth >= 0.20:
            valuation = 4
        elif ps_ratio < 15:
            valuation = 2
        else:
            valuation = 1
        reasons.append(f"P/S proxy {ps_ratio:.1f}x with revenue growth {growth:.1%}")
    else:
        reasons.append("Forward valuation/growth pair unavailable")

    days_to_catalyst = safe_float(
        stock_data.get("days_to_earnings") or stock_meta.get("dated_catalyst_days")
    )
    if days_to_catalyst is not None and 0 <= days_to_catalyst <= 30:
        catalyst = 5
        reasons.append(f"Dated catalyst in {days_to_catalyst:.0f} days")
    elif days_to_catalyst is not None and days_to_catalyst <= 90:
        catalyst = 3
        reasons.append(f"Dated catalyst in {days_to_catalyst:.0f} days")
    elif stock_meta.get("dated_catalyst"):
        catalyst = 2
        reasons.append("Dated catalyst declared but timing not normalized")
    else:
        catalyst = 0
        reasons.append("No dated catalyst metadata")

    expectation_primary = evidence_count(stock_meta, "expectation_gap_primary_evidence")
    analyst_count = safe_float(stock_data.get("num_analysts"))
    institutional = safe_float(stock_data.get("institutional_pct"))
    if expectation_primary >= 1:
        expectation_gap = 3
        reasons.append("Primary evidence supports an expectation gap")
    elif analyst_count is None and institutional is None:
        expectation_gap = 0
        reasons.append("Coverage and ownership data unavailable")
    elif (analyst_count is None or analyst_count < 5) and (
        institutional is None or institutional < 0.50
    ):
        expectation_gap = 2
        reasons.append("Low analyst/institutional coverage proxy")
    elif analyst_count is None or analyst_count < 15:
        expectation_gap = 1
        reasons.append("Moderate analyst coverage proxy")
    else:
        expectation_gap = 0
        reasons.append("High coverage; expectation-gap evidence weak")

    return min(valuation + catalyst + expectation_gap, 15), reasons


def score_l5_evidence_risk(
    stock_data: dict[str, Any], stock_meta: dict[str, Any]
) -> tuple[int, list[str]]:
    """System operationalization: evidence, observable risk and disconfirmation, max 20."""
    reasons: list[str] = []

    primary = evidence_count(stock_meta, "primary_evidence")
    corroborating = evidence_count(stock_meta, "corroborating_evidence")
    if primary >= 2:
        evidence = 8
        reasons.append(f"{primary} primary evidence records")
    elif primary == 1:
        evidence = 6
        reasons.append("One primary evidence record")
    elif corroborating >= 2:
        evidence = 4
        reasons.append(f"{corroborating} corroborating evidence records; primary evidence pending")
    elif corroborating == 1:
        evidence = 2
        reasons.append("One corroborating evidence record; primary evidence pending")
    else:
        evidence = 0
        reasons.append("No structured primary/corroborating evidence metadata")

    beta = safe_float(stock_data.get("beta"))
    short_float = safe_float(stock_data.get("short_pct_float"))
    atm_dilution = safe_float(stock_data.get("atm_dilution_pct") or stock_meta.get("atm_dilution_pct"))
    sbc_ratio = safe_float(stock_data.get("sbc_revenue_pct") or stock_meta.get("sbc_revenue_pct"))

    market_risk_data = beta is not None or short_float is not None
    financing_risk_data = atm_dilution is not None or sbc_ratio is not None
    if not market_risk_data and not financing_risk_data:
        observed_risk = 0
        reasons.append("Observed risk data unavailable")
    else:
        observed_risk = 6
        if beta is not None and beta >= 3.0:
            observed_risk -= 2
            reasons.append(f"High beta {beta:.2f}")
        elif beta is not None and beta >= 2.0:
            observed_risk -= 1
            reasons.append(f"Elevated beta {beta:.2f}")
        if short_float is not None and short_float >= 0.25:
            observed_risk -= 2
            reasons.append(f"High short interest {short_float:.1%}")
        elif short_float is not None and short_float >= 0.15:
            observed_risk -= 1
            reasons.append(f"Elevated short interest {short_float:.1%}")
        if atm_dilution is not None and atm_dilution >= 0.10:
            observed_risk -= 2
            reasons.append(f"Material ATM dilution proxy {atm_dilution:.1%}")
        if sbc_ratio is not None and sbc_ratio >= 0.15:
            observed_risk -= 1
            reasons.append(f"High SBC/revenue proxy {sbc_ratio:.1%}")
        observed_risk = max(0, observed_risk)
        if observed_risk == 6:
            reasons.append("No severe risk flag in available observed fields")

    disconfirmation = list_value(stock_meta.get("disconfirmation_conditions"))
    last_verified = stock_meta.get("last_verified_at")
    if len(disconfirmation) >= 3 and last_verified:
        readiness = 6
        reasons.append("Multiple disconfirmation conditions and verification timestamp recorded")
    elif len(disconfirmation) >= 1 and last_verified:
        readiness = 4
        reasons.append("Disconfirmation conditions and verification timestamp recorded")
    elif len(disconfirmation) >= 1:
        readiness = 2
        reasons.append("Disconfirmation conditions recorded; verification timestamp missing")
    else:
        readiness = 0
        reasons.append("No structured disconfirmation conditions")

    return min(evidence + observed_risk + readiness, 20), reasons


def calculate_long_term_suitability(
    stock_data: dict[str, Any],
    stock_meta: dict[str, Any],
    preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply the local user's separate multi-year suitability preference."""
    prefs = preferences or DEFAULT_USER_PREFERENCES
    overlay = prefs.get("long_term_overlay", {}) if isinstance(prefs, dict) else {}
    enabled = bool(overlay.get("enabled", True))
    minimum_years = int(overlay.get("minimum_holding_years", 2))
    labels = overlay.get("labels", {}) if isinstance(overlay.get("labels"), dict) else {}
    if not enabled:
        return {
            "enabled": False,
            "owner": "local_user",
            "minimum_holding_years": minimum_years,
            "affects_source_view": False,
            "affects_methodology_research_score": False,
            "label": "disabled",
            "score": None,
            "data_quality": None,
            "reasons": [],
            "disclaimer": (
                "Local user-defined holding-horizon overlay is disabled; not attributed "
                "to Serenity or Leopold Aschenbrenner."
            ),
        }

    reasons: list[str] = []
    quality = data_quality(stock_data)
    category = str(stock_meta.get("category", ""))

    growth = safe_float(stock_data.get("revenue_growth"))
    if growth is None:
        demand = 0
        reasons.append("Long-term demand durability cannot be assessed from current growth data")
    elif growth >= 0.30 and contains_any(category, DIRECT_AI_KEYWORDS | POWER_KEYWORDS):
        demand = 20
        reasons.append("Strong growth proxy in a structural infrastructure category")
    elif growth >= 0.15:
        demand = 14
        reasons.append("Moderate positive growth proxy")
    elif growth > 0:
        demand = 8
        reasons.append("Low positive growth proxy")
    else:
        demand = 0
        reasons.append("Non-positive growth proxy")

    qualification = safe_float(stock_meta.get("qualification_months"))
    bottleneck_level = str(stock_meta.get("bottleneck_evidence_level", "")).casefold()
    if bottleneck_level == "primary_verified" and qualification is not None and qualification >= 18:
        moat = 20
        reasons.append("Primary-verified bottleneck and long qualification period")
    elif bottleneck_level in {"primary_verified", "corroborated"}:
        moat = 15
        reasons.append("Bottleneck evidence supports some durability")
    elif contains_any(category, DURABLE_MOAT_KEYWORDS):
        moat = 9
        reasons.append("Category suggests possible durability; company-level proof pending")
    else:
        moat = 3 if category else 0
        reasons.append("Durable moat evidence limited")

    profit_margin = safe_float(stock_data.get("profit_margin"))
    free_cash_flow = safe_float(stock_data.get("free_cash_flow"))
    market_cap = safe_float(stock_data.get("market_cap"))
    total_cash = safe_float(stock_data.get("total_cash"))
    total_debt = safe_float(stock_data.get("total_debt"))
    financial = 0
    if profit_margin is not None and profit_margin > 0:
        financial += 8 if profit_margin >= 0.10 else 5
    if free_cash_flow is not None and market_cap is not None and market_cap > 0:
        fcf_yield = free_cash_flow / market_cap
        financial += 8 if fcf_yield >= 0.03 else 5 if fcf_yield > 0 else 0
    if total_cash is not None and total_debt is not None:
        financial += 9 if total_cash > total_debt else 5
    financial = min(financial, 25)
    if financial:
        reasons.append("Financial endurance supported by available margin/cash-flow/balance-sheet data")
    else:
        reasons.append("Financial endurance data insufficient or weak")

    dilution = safe_float(stock_data.get("atm_dilution_pct") or stock_meta.get("atm_dilution_pct"))
    concentration = safe_float(
        stock_data.get("largest_customer_revenue_pct")
        or stock_meta.get("largest_customer_revenue_pct")
    )
    risk_endurance = 20
    known_risk_fields = 0
    if dilution is not None:
        known_risk_fields += 1
        if dilution >= 0.20:
            risk_endurance -= 12
        elif dilution >= 0.10:
            risk_endurance -= 8
        elif dilution >= 0.05:
            risk_endurance -= 4
    if concentration is not None:
        known_risk_fields += 1
        if concentration >= 0.60:
            risk_endurance -= 8
        elif concentration >= 0.40:
            risk_endurance -= 4
    if known_risk_fields == 0:
        risk_endurance = 5
        reasons.append("Dilution and customer-concentration data unavailable")
    else:
        reasons.append("Dilution/customer-concentration risk assessed from available fields")
    risk_endurance = max(0, risk_endurance)

    primary = evidence_count(stock_meta, "primary_evidence")
    ps_ratio = safe_float(stock_data.get("ps_ratio"))
    evidence_valuation = 0
    if primary >= 2:
        evidence_valuation += 9
    elif primary == 1:
        evidence_valuation += 6
    elif evidence_count(stock_meta, "corroborating_evidence") >= 2:
        evidence_valuation += 3
    if ps_ratio is not None and ps_ratio > 0:
        if ps_ratio < 5:
            evidence_valuation += 6
        elif ps_ratio < 10:
            evidence_valuation += 4
        elif ps_ratio < 15:
            evidence_valuation += 2
    evidence_valuation = min(evidence_valuation, 15)
    if primary == 0:
        reasons.append("No structured primary evidence; long-term confidence is limited")

    score = min(demand + moat + financial + risk_endurance + evidence_valuation, 100)
    if quality < 0.35 or (primary == 0 and evidence_count(stock_meta, "corroborating_evidence") == 0):
        label = labels.get("insufficient", "資料不足")
    elif score >= 75:
        label = labels.get("high", "較適合長期研究")
    elif score >= 55:
        label = labels.get("conditional", "條件式長期觀察")
    else:
        label = labels.get("event_driven", "偏事件／交易型")

    return {
        "enabled": True,
        "owner": overlay.get("owner", "local_user"),
        "minimum_holding_years": minimum_years,
        "affects_source_view": False,
        "affects_methodology_research_score": False,
        "score": score,
        "label": label,
        "data_quality": round(quality, 3),
        "reasons": reasons,
        "disclaimer": (
            "User-defined holding-horizon annotation; not attributed to Serenity or "
            "Leopold Aschenbrenner and not a return forecast or trade instruction."
        ),
    }


def get_rating(score: int) -> str:
    if score >= 85:
        return "S"
    if score >= 75:
        return "A"
    if score >= 65:
        return "B"
    if score >= 55:
        return "C"
    if score >= 45:
        return "D"
    return "F"


def calculate_total_score(
    stock_data: dict[str, Any],
    stock_meta: dict[str, Any],
    preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    l1, r1 = score_l1_demand_wave(stock_data, stock_meta)
    l2, r2 = score_l2_bottleneck(stock_data, stock_meta)
    l3, r3 = score_l3_company_quality(stock_data, stock_meta)
    l4, r4 = score_l4_valuation_catalyst(stock_data, stock_meta)
    l5, r5 = score_l5_evidence_risk(stock_data, stock_meta)

    total = l1 + l2 + l3 + l4 + l5
    quality = data_quality(stock_data)
    warnings: list[str] = []
    if quality < 0.50:
        warnings.append("Low data completeness; ranking confidence is limited")
    if evidence_count(stock_meta, "primary_evidence") == 0:
        warnings.append("No structured primary evidence attached to this watchlist record")

    ticker = str(stock_data.get("ticker") or stock_meta.get("ticker") or "").upper()
    return {
        "ticker": ticker,
        "name": stock_data.get("name") or stock_meta.get("name") or ticker,
        "category": stock_meta.get("category", ""),
        "source": stock_meta.get("source", "unknown"),
        "score_type": "system_operationalization_not_author_score",
        "attribution": {
            "serenity_endorsement": False,
            "aschenbrenner_endorsement": False,
            "user_horizon_included_in_total": False,
        },
        "total_score": total,
        "max_score": 100,
        "layer_scores": {
            "L1_demand_wave": l1,
            "L2_bottleneck": l2,
            "L3_company_quality": l3,
            "L4_valuation_catalyst": l4,
            "L5_evidence_risk": l5,
        },
        "reasons": r1 + r2 + r3 + r4 + r5,
        "warnings": warnings,
        "data_quality": round(quality, 3),
        "user_long_term_overlay": calculate_long_term_suitability(
            stock_data, stock_meta, preferences
        ),
        "current_price": stock_data.get("current_price"),
        "market_cap": stock_data.get("market_cap"),
        "revenue_ttm": stock_data.get("revenue_ttm"),
        "revenue_growth": stock_data.get("revenue_growth"),
        "forward_pe": stock_data.get("forward_pe"),
        "ps_ratio": stock_data.get("ps_ratio"),
        "gross_margin": stock_data.get("gross_margin"),
        "profit_margin": stock_data.get("profit_margin"),
        "rating": get_rating(total),
    }


def score_all(
    market_path: Path | None = None,
    watchlist_path: Path | None = None,
    output_dir: Path | None = None,
    preferences_path: Path | None = None,
) -> list[dict[str, Any]]:
    market_data = load_data(market_path)
    watchlist = load_watchlist(watchlist_path)
    preferences = load_user_preferences(preferences_path)
    metadata = {str(item.get("ticker", "")).upper(): item for item in watchlist}

    scored: list[dict[str, Any]] = []
    for item in market_data:
        if "error" in item or not item.get("ticker"):
            continue
        ticker = str(item["ticker"]).upper()
        result = calculate_total_score(
            item,
            metadata.get(ticker, {"ticker": ticker}),
            preferences,
        )
        scored.append(result)

    scored.sort(key=lambda item: (item["total_score"], item["data_quality"]), reverse=True)
    for index, item in enumerate(scored, start=1):
        item["rank"] = index

    destination = output_dir or DATA_DIR
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = json.dumps(scored, ensure_ascii=False, indent=2, default=str) + "\n"
    (destination / f"scores_{timestamp}.json").write_text(payload, encoding="utf-8")
    (destination / "scores_latest.json").write_text(payload, encoding="utf-8")

    logger.info("Scored %d stocks", len(scored))
    for item in scored[:10]:
        price = safe_float(item.get("current_price"))
        price_text = f"${price:.2f}" if price is not None else "N/A"
        overlay = item.get("user_long_term_overlay") or {}
        logger.info(
            "#%d [%s] %s research_score=%d/100 long_term=%s price=%s quality=%.0f%%",
            item["rank"],
            item["rating"],
            item["ticker"],
            item["total_score"],
            overlay.get("label", "N/A"),
            price_text,
            item["data_quality"] * 100,
        )
    return scored


def main() -> int:
    results = score_all()
    print("RANK TICKER RATING RESEARCH_SCORE DATA_QUALITY USER_LONG_TERM")
    for item in results:
        overlay = item.get("user_long_term_overlay") or {}
        print(
            f"{item['rank']:>4} {item['ticker']:<6} {item['rating']:<6} "
            f"{item['total_score']:>14} {item['data_quality'] * 100:>11.0f}% "
            f"{overlay.get('label', 'N/A')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
