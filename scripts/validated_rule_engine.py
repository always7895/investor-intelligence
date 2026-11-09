"""Prospective, *unvalidated* decision-rule screen — NOT a live score component.

Every row is dated, provenance-bound, and explicitly not an investment recommendation.
Research hypotheses are not promoted without independent out-of-sample validation.
Missing, incomparable, future-filed, or non-finite observations are UNKNOWN, never zero.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from typing import Any
from urllib.parse import urlsplit

RULESET_VERSION = "r3-research-only-v1"
RULES_KEPT = 0
# Frozen R3 hypotheses, including the two explicitly uncomputable document-level rules.
# R11/R12 have no definition in RULES-R3; do not invent additional hypotheses.
RULES = (
    ("R01_REV_GROWTH_20", "營收年增至少20%", "fundamentals", "revenue_yoy", 0.20, ">="),
    ("R02_REV_ACCEL_10PP", "營收年增加速至少10個百分點", "fundamentals", "revenue_acceleration", 0.10, ">="),
    ("R03_GM_EXPAND_2PP", "毛利率年增至少2個百分點", "fundamentals", "gross_margin_change", 0.02, ">="),
    ("R04_RPO_GROWTH_20", "剩餘履約義務年增至少20%", "fundamentals", "rpo_yoy", 0.20, ">="),
    ("R05_DILUTION_BELOW_5", "同季可比股數年增不超過5%", "fundamentals", "shares_yoy", 0.05, "<="),
    ("R06_REL_MOMENTUM_6M", "近6個月報酬高於QQQ", "market", "relative_qqq_6m", 0.0, ">"),
    ("R07_PRICE_2Y_POSITIVE", "近2年調整後價格報酬為正", "market", "cagr_2y", 0.0, ">"),
    ("R08_REL_MOMENTUM_SOXX_6M", "近6個月報酬高於SOXX", "market", "relative_soxx_6m", 0.0, ">"),
    ("R09_MAX_DRAWDOWN_12M", "近1年最大回撤不超過35%", "market", "max_drawdown_12m", -0.35, ">="),
    ("R10_ATM_MATERIAL_DILUTION", "已查證有效ATM及重大稀釋條款", "documents", "active_atm", 0.0, ">"),
    ("R13_INDEPENDENT_13F_POSITION_CHANGE", "已查證獨立機構13F持股變化", "documents", "independent_13f", 0.0, ">"),
)
MAX_FILING_AGE_DAYS = 180
MAX_PERIOD_AGE_DAYS = 240
MAX_QUOTE_AGE_DAYS = 7


def _day(value: Any) -> date | None:
    if type(value) is not str or len(value) != 10:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _finite(value: Any) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except OverflowError:
        return None


def _hash(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _source_url(value: Any, family: str) -> str | None:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parts = urlsplit(value)
        domains = {"www.sec.gov", "data.sec.gov"} if family == "fundamentals" else {
            "finance.yahoo.com", "query1.finance.yahoo.com", "query2.finance.yahoo.com"}
        if (parts.scheme != "https" or parts.hostname not in domains or parts.username
                or parts.password or parts.port not in (None, 443) or parts.fragment or parts.query):
            return None
    except ValueError:
        return None
    return value


def _feature(data: dict[str, Any], field: str) -> float | None:
    if field == "revenue_acceleration":
        a, b = _finite(data.get("revenue_yoy")), _finite(data.get("revenue_yoy_prev"))
        return _finite(a - b) if a is not None and b is not None else None
    return _finite(data.get(field))


def _observation(data: dict[str, Any], family: str, field: str, cutoff: date) -> dict[str, Any]:
    filed = _day(data.get("rpo_filed") if field == "rpo_yoy" else data.get("filed"))
    period = _day(data.get("rpo_end") if field == "rpo_yoy" else data.get("quarter_end"))
    quoted = _day(data.get("asof"))
    url = _source_url(data.get("source_url"), family)
    reason = None
    freshness = "UNKNOWN"
    if family == "fundamentals":
        if data.get("source") != "SEC EDGAR XBRL companyfacts" or url is None:
            reason = "缺少可核對的公開原始財報來源，暫不判斷"
        elif filed is None or period is None:
            reason = "財報申報日或資料期間不明，暫不判斷"
        elif period > filed or filed > cutoff:
            reason = "財報日期不一致或尚未公開，暫不判斷"
        elif (cutoff - filed).days > MAX_FILING_AGE_DAYS or (cutoff - period).days > MAX_PERIOD_AGE_DAYS:
            freshness, reason = "STALE", "財報已逾研究資料時效，暫不判斷"
        else:
            freshness = "FRESH"
        if reason is None and field == "rpo_yoy":
            prior, prior_filed = _day(data.get("rpo_prior_end")), _day(data.get("rpo_prior_filed"))
            if (prior is None or prior_filed is None or not 345 <= (period - prior).days <= 385
                    or not prior <= prior_filed <= cutoff):
                reason = "缺少同期間可比且已公開的前期剩餘履約義務，暫不判斷"
        if reason is None and field == "shares_yoy" and data.get("shares_basis") not in {
                "DILUTED_WEIGHTED_AVERAGE", "OUTSTANDING"}:
            reason = "股數口徑或同季可比基礎不明，暫不判斷"
    else:
        if data.get("source") not in {
                "Yahoo Finance adjusted daily close (unofficial)", "Yahoo Finance chart (unofficial)"} or url is None:
            reason = "缺少可核對的調整後價格來源，暫不判斷"
        elif quoted is None:
            reason = "價格觀測日期不明，暫不判斷"
        elif quoted > cutoff:
            reason = "價格觀測日期在未來，暫不判斷"
        elif (cutoff - quoted).days > MAX_QUOTE_AGE_DAYS:
            freshness, reason = "STALE", "價格已逾研究資料時效，暫不判斷"
        else:
            freshness = "FRESH"
        return_field = "ret_6m" if field.startswith("relative_") else field
        reasons = data.get("return_reasons")
        if isinstance(reasons, dict) and reasons.get(return_field):
            reason = "價格期間跨越尚未完整調整的公司行動，暫不判斷"
    return {"filed_at": filed.isoformat() if family == "fundamentals" and filed else None,
            "period_end": period.isoformat() if family == "fundamentals" and period else None,
            "quote_asof": quoted.isoformat() if family == "market" and quoted else None,
            "source_url": url, "freshness": freshness, "reason": reason}


def evaluate(fund: dict[str, Any] | None, market: dict[str, Any] | None,
             *, cutoff: date, symbol: str = "") -> dict[str, Any]:
    """Pure, score-neutral R3 shadow over admitted observations; no author/fund score drivers.

    Relative returns require the named benchmark's own same-date, same-window adjusted
    return in market['benchmarks']; a positive stock return alone is not a proxy.
    """
    if type(cutoff) is not date:
        raise ValueError("SCREENER_CUTOFF_INVALID")
    fund = fund if isinstance(fund, dict) else {}
    market = market if isinstance(market, dict) else {}
    rows = []
    for rule_id, label_zh, family, field, threshold, direction in RULES:
        data = fund if family == "fundamentals" else market
        if family == "documents":
            reason = ("缺少已查證的ATM原始條款、有效狀態與規模，暫不判斷" if field == "active_atm" else
                      "缺少獨立機構逐季13F明細與證券身分核對，暫不判斷")
            observation = {"filed_at": None, "period_end": None, "quote_asof": None,
                           "source_url": None, "freshness": "UNKNOWN", "reason": reason}
            value, operands = None, {}
        else:
            observation = _observation(data, family, field, cutoff)
            value = _feature(data, field)
            fields = ("revenue_yoy", "revenue_yoy_prev") if field == "revenue_acceleration" else (field,)
            operands = {name: _finite(data.get(name)) for name in fields}
            if field == "rpo_yoy":
                operands.update({name: (_day(data.get(name)).isoformat() if _day(data.get(name)) else None)
                                 for name in ("rpo_prior_end", "rpo_prior_filed")})
            if field == "shares_yoy":
                operands["shares_basis"] = data.get("shares_basis") if data.get("shares_basis") in {
                    "DILUTED_WEIGHTED_AVERAGE", "OUTSTANDING"} else None
            if field.startswith("relative_"):
                name = "QQQ" if field == "relative_qqq_6m" else "SOXX"
                benchmarks = market.get("benchmarks")
                benchmark = benchmarks.get(name) if isinstance(benchmarks, dict) else None
                benchmark = benchmark if isinstance(benchmark, dict) else {}
                checked = _observation(benchmark, "market", "ret_6m", cutoff)
                stock, index = _finite(market.get("ret_6m")), _finite(benchmark.get("ret_6m"))
                aligned = (market.get("ret_6m_start") is not None
                           and _day(market.get("ret_6m_start")) is not None
                           and market.get("ret_6m_start") == benchmark.get("ret_6m_start")
                           and checked["quote_asof"] == observation["quote_asof"])
                value = _finite(stock - index) if stock is not None and index is not None else None
                operands = {"ret_6m": stock, "benchmark_ret_6m": index, "benchmark": name,
                            "window_start": market.get("ret_6m_start") if aligned else None,
                            "benchmark_observation": {key: val for key, val in checked.items()
                                                      if key not in {"freshness", "reason"}}}
                if checked["reason"] is not None or not aligned:
                    observation["reason"] = "缺少同日期、同期間的調整後基準報酬，暫不判斷"
            if field == "max_drawdown_12m":
                if _day(market.get("drawdown_start")) is None or not observation["quote_asof"]:
                    observation["reason"] = "缺少完整近1年調整後價格回撤期間，暫不判斷"
                elif not 360 <= (_day(observation["quote_asof"]) - _day(market["drawdown_start"])).days <= 370:
                    observation["reason"] = "回撤價格期間不足1年，暫不判斷"
                elif value is not None and not -1.0 <= value <= 0.0:
                    observation["reason"] = "回撤數值口徑不明，暫不判斷"
                operands["drawdown_start"] = (_day(market.get("drawdown_start")).isoformat()
                                              if _day(market.get("drawdown_start")) else None)
        reason = observation.pop("reason")
        if reason is None and value is None:
            reason = "缺少有限且可比的研究數值，暫不判斷"
        if reason is not None:
            status, value = "UNKNOWN", None
        else:
            if math.isclose(value, threshold, rel_tol=0.0, abs_tol=1e-12):
                value = threshold
            passed = (value > threshold if direction == ">" else
                      value <= threshold if direction == "<=" else value >= threshold)
            status = "PASS" if passed else "FAIL"
            reason = "研究條件暫時符合；未經前瞻驗證" if passed else "研究條件暫時不符；未經前瞻驗證"
        evidence = {"rule_id": rule_id, "ruleset": RULESET_VERSION, "symbol": symbol,
                    "observation": {key: val for key, val in observation.items() if key != "freshness"},
                    "operands": operands}
        rows.append({"rule_id": rule_id, "label_zh": label_zh, "status": status,
                     "value": round(value, 6) if value is not None else None, "reason_zh": reason,
                     **observation, "complete": status != "UNKNOWN", "provenance_hash": _hash(evidence)})
    return {"state": "UNVERIFIED", "ruleset": RULESET_VERSION, "rules_kept": RULES_KEPT,
            "asof": cutoff.isoformat(), "rules": rows, "input_sha256": _hash({
                "ruleset": RULESET_VERSION, "symbol": symbol,
                "evidence": [row["provenance_hash"] for row in rows]})}


def display_projection(screen: dict[str, Any] | None) -> dict[str, Any]:
    """Bounded display: only reviewed enum labels, never unbounded text or author assertions."""
    rows = screen.get("rules", []) if (isinstance(screen, dict) and screen.get("state") == "UNVERIFIED"
                                      and screen.get("ruleset") == RULESET_VERSION) else []
    rows = rows if isinstance(rows, list) else []
    allowed = {rule_id: label for rule_id, label, *_ in RULES}
    safe = [{"rule_id": r["rule_id"], "label_zh": allowed[r["rule_id"]], "status": r["status"]}
            for r in rows if isinstance(r, dict) and r.get("rule_id") in allowed
            and r.get("status") in ("PASS", "FAIL", "UNKNOWN")]
    if len(safe) != len(RULES) or len(set(r["rule_id"] for r in safe)) != len(RULES):
        return {"state": "UNVERIFIED", "rules": [
            {"rule_id": key, "label_zh": label, "status": "UNKNOWN"} for key, label, *_ in RULES]}
    return {"state": "UNVERIFIED", "rules": safe}
