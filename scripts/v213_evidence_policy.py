#!/usr/bin/env python3
"""Shared evidence policy for the seven-field Top20 (Python mirror of cloud/src/v213/top20-report.ts).

- ``policy_binding()``: the freshness-policy binding the Worker re-verifies against its own copy
  (canonical JSON: sorted keys, minimal separators, non-ASCII kept).
- ``CLASS_POLICY_KEY``: evidence class -> policy window key (mirror of EVIDENCE_CLASS_POLICY_KEY).
- ``report_freshness()``: report-age bounds shared with the Worker (config/v213-top20-report-freshness-v1.json).
- ``validate_seven_field_report(doc, now)``: the Worker's strict document/record contract and the
  per-record evidence windows, so a producer or the hourly publisher refuses what the Worker would refuse.
  Two-year return evidence is only checked for presence here; the staged replay through the real Worker
  readers (cloud/test/live-kv-replay.test.ts) remains the final authority.

Evidence anchors are source-state dates, never retrieval times: a current-state order claim is anchored at
its disclosure date, a market row at the date of its latest daily bar.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "v213-serenity-evidence-freshness-policy.json"
REPORT_FRESHNESS_PATH = ROOT / "config" / "v213-top20-report-freshness-v1.json"

CLASS_POLICY_KEY = {
    "current_state_claim": "current_state_claim_max_age_days",
    "market_observation": "market_observation_max_age_days",
    "market_high_confidence": "market_high_confidence_freshest_max_age_days",
    "structural_claim": "structural_claim_max_age_days",
}
DISPLAY_COLUMNS = ["股票", "長期投資報酬率（近2年年化）", "短期投資報酬率（近6個月）", "行業別", "獲利簡述", "公司現在訂單", "未來訂單預估"]
NO_CURRENT_ORDERS = "未揭露（無可靠公開訂單數字）"
NO_FUTURE_ORDER_ESTIMATE = "無可靠公開預估"
DOCUMENT_KEYS = {"schema_version", "product_version", "generated_at", "freshness_policy", "evidence_capture_at", "display_columns",
                 "long_term_definition", "short_term_definition", "records", "provider_scope", "owner_watchlist_inherited"}
REQUIRED_RECORD_KEYS = {
    "schema_version", "rank", "ticker", "name", "long_term_return_pct", "short_term_return_pct", "industry", "profit_summary",
    "current_orders", "future_orders_estimate", "long_term_window", "short_term_window", "market_source", "profit_source",
    "orders_as_of", "orders_confidence", "current_order_source_urls", "future_order_source_urls",
    "numeric_total_order_estimate_prohibited", "retrieved_at", "orders_state_as_of", "evidence_class", "freshness_policy_key",
    "test_only_admission", "provider_scope", "owner_watchlist_inherited",
}
OPTIONAL_RECORD_KEYS = {"two_year_total_return_pct", "two_year_return_evidence"}
CLOCK_SKEW_SECONDS = 300
_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,14}$")


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def policy_binding(path: Path = POLICY_PATH) -> dict[str, str]:
    """Bind the exact policy content (not the filename) into the report."""
    parsed = load_policy(path)
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {"policy_id": parsed["policy_id"], "policy_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def window_days(evidence_class: str, policy: Mapping[str, Any] | None = None) -> float:
    value = (policy or load_policy())[CLASS_POLICY_KEY[evidence_class]]
    if not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"EVIDENCE_WINDOW_INVALID:{evidence_class}")
    return float(value)


def report_freshness(path: Path = REPORT_FRESHNESS_PATH) -> dict[str, float]:
    """{report_max_age_hours, refresh_after_hours}: how long one Top20 report may be re-sealed."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    bounds = {key: float(raw[key]) for key in ("report_max_age_hours", "refresh_after_hours")}
    if not 0 < bounds["refresh_after_hours"] < bounds["report_max_age_hours"] <= 24:
        raise ValueError("REPORT_FRESHNESS_BOUNDS_INVALID")
    return bounds


def parse_time(value: Any) -> datetime | None:
    """ISO date or timestamp (Z or offset); a bare date is midnight UTC, as Date.parse reads it."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _line_safe(value: Any, limit: int) -> bool:
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= limit and "｜" not in value
            and "\r" not in value and "\n" not in value)


def _return_pct(value: Any) -> bool:
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool) and value >= -100)


def _https_urls(value: Any) -> bool:
    return isinstance(value, list) and len(value) <= 8 and all(isinstance(url, str) and url.startswith("https://") for url in value)


def _order_semantics(item: Mapping[str, Any]) -> bool:
    if not isinstance(item.get("orders_as_of"), str) or not isinstance(item.get("orders_confidence"), str):
        return False
    if not _https_urls(item.get("current_order_source_urls")) or not _https_urls(item.get("future_order_source_urls")):
        return False
    confidence = item["orders_confidence"].strip()
    if not confidence or len(confidence) > 80:
        return False
    if confidence == "UNAVAILABLE":
        return ((item["orders_as_of"] == "" or parse_time(item["orders_as_of"]) is not None)
                and item.get("current_orders") == NO_CURRENT_ORDERS and item.get("future_orders_estimate") == NO_FUTURE_ORDER_ESTIMATE
                and item["current_order_source_urls"] == [] and item["future_order_source_urls"] == [])
    return parse_time(item["orders_as_of"]) is not None


def evidence_within_window(record: Mapping[str, Any], *, now: datetime, seal_time: datetime | None,
                           policy: Mapping[str, Any]) -> str | None:
    """Reason the record's evidence is outside its class window, or None (mirror of v213EvidenceWithinWindow,
    including the retrieved_at age bound)."""
    evidence_class = record.get("evidence_class")
    if evidence_class not in CLASS_POLICY_KEY:
        return "EVIDENCE_CLASS_UNKNOWN"
    window_seconds = window_days(evidence_class, policy) * 86400
    anchor = parse_time(record.get("orders_state_as_of"))
    if anchor is None:
        return "EVIDENCE_ANCHOR_INVALID"
    age = (now - anchor).total_seconds()
    if age < -CLOCK_SKEW_SECONDS or age > window_seconds:
        return "EVIDENCE_ANCHOR_OUTSIDE_WINDOW"
    retrieved = parse_time(record.get("retrieved_at"))
    if retrieved is None:
        return "RETRIEVED_AT_INVALID"
    retrieved_age = (now - retrieved).total_seconds()
    if retrieved_age < -CLOCK_SKEW_SECONDS or retrieved_age > window_seconds:
        return "RETRIEVED_AT_OUTSIDE_WINDOW"
    if seal_time is not None and (retrieved - seal_time).total_seconds() > CLOCK_SKEW_SECONDS:
        return "RETRIEVED_AFTER_SEAL"
    return None


def validate_seven_field_report(doc: Any, *, now: datetime, exact_twenty: bool = True) -> list[str]:
    """Every reason the Worker would refuse this report at ``now`` (empty list: accepted)."""
    if not isinstance(doc, dict):
        return ["DOCUMENT_NOT_OBJECT"]
    reasons: list[str] = []
    if set(doc) != DOCUMENT_KEYS:
        reasons.append("DOCUMENT_KEYS")
    policy = load_policy()
    expected = {"schema_version": 2, "product_version": "2.1.3", "provider_scope": "public_only", "owner_watchlist_inherited": False,
                "long_term_definition": "trailing_2y_adjusted_close_cagr",
                "short_term_definition": "trailing_6m_adjusted_close_price_return"}
    reasons += [f"DOCUMENT_{key.upper()}" for key, value in expected.items() if doc.get(key) != value]
    generated = parse_time(doc.get("generated_at"))
    if generated is None:
        reasons.append("GENERATED_AT_INVALID")
    if doc.get("freshness_policy") != policy_binding():
        reasons.append("FRESHNESS_POLICY_BINDING")
    if parse_time(doc.get("evidence_capture_at")) is None:
        reasons.append("EVIDENCE_CAPTURE_AT_INVALID")
    if doc.get("display_columns") != DISPLAY_COLUMNS:
        reasons.append("DISPLAY_COLUMNS")
    records = doc.get("records")
    if not isinstance(records, list) or (len(records) != 20 if exact_twenty else not 1 <= len(records) <= 20):
        return reasons + ["RECORD_COUNT"]
    seen: set[str] = set()
    admissions: set[Any] = set()
    for index, item in enumerate(records):
        label = f"RECORD_{index + 1}"
        if not isinstance(item, dict):
            reasons.append(f"{label}_NOT_OBJECT")
            continue
        if not REQUIRED_RECORD_KEYS <= set(item) or not set(item) <= REQUIRED_RECORD_KEYS | OPTIONAL_RECORD_KEYS:
            reasons.append(f"{label}_KEYS")
            continue
        ticker = str(item.get("ticker") or "").upper()
        checks = {
            "SCHEMA": item.get("schema_version") == 2, "RANK": item.get("rank") == index + 1,
            "TICKER": bool(_TICKER.fullmatch(ticker)) and ticker not in seen, "NAME": _line_safe(item.get("name"), 120),
            "RETURNS": _return_pct(item.get("long_term_return_pct")) and _return_pct(item.get("short_term_return_pct")),
            "INDUSTRY": _line_safe(item.get("industry"), 100), "PROFIT": _line_safe(item.get("profit_summary"), 120),
            "ORDERS_TEXT": _line_safe(item.get("current_orders"), 150) and _line_safe(item.get("future_orders_estimate"), 170),
            "WINDOWS": item.get("long_term_window") == "2y_cagr" and item.get("short_term_window") == "6m_price_return",
            "SOURCES": item.get("market_source") == "yfinance" and item.get("profit_source") == "sec_edgar",
            "ORDER_SEMANTICS": _order_semantics(item), "NO_ORDER_TOTAL": item.get("numeric_total_order_estimate_prohibited") is True,
            "SCOPE": item.get("provider_scope") == "public_only" and item.get("owner_watchlist_inherited") is False,
            "POLICY_KEY": CLASS_POLICY_KEY.get(str(item.get("evidence_class"))) == item.get("freshness_policy_key"),
            "ADMISSION": isinstance(item.get("test_only_admission"), bool),
            "TWO_YEAR": item.get("two_year_total_return_pct") is None or bool(item.get("two_year_return_evidence")),
        }
        reasons += [f"{label}_{name}" for name, ok in checks.items() if not ok]
        admissions.add(item.get("test_only_admission"))
        seen.add(ticker)
        window_reason = evidence_within_window(item, now=now, seal_time=generated, policy=policy)
        if window_reason:
            reasons.append(f"{label}_{window_reason}")
    if len(admissions) > 1:
        reasons.append("ADMISSION_MIXED")
    return reasons
