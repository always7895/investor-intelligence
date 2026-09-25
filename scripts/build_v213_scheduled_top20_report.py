#!/usr/bin/env python3
"""Build the scheduled v2.1.3 seven-field report from fresh v2.1.2 rows
plus the accepted H6B2/R15R public order-evidence baseline.

This deliberately does not ask a local model to invent order totals. The five
market/profit fields refresh from v2.1.2; the two order fields retain their
evidence-bound text, source URLs and as-of dates until a new H6B evidence pass
accepts replacements.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from report_source_acquisition import SourceAcquisitionError, field_clock, utc_time, validate_report_acquisition
from v213_evidence_policy import CLASS_POLICY_KEY, iso_z, load_policy, parse_time, policy_binding, report_freshness, window_days

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_V212 = ROOT / "data" / "cache" / "v212_top20_report_public_latest.json"
DEFAULT_BASELINE = ROOT / "data" / "bootstrap" / "v213-r15r-order-baseline.json"
DEFAULT_TOP20 = ROOT / "data" / "cache" / "top20_public_latest.json"
DEFAULT_OUTPUT = ROOT / "data" / "cache" / "v213_top20_report_public_latest.json"
DEFAULT_PREVIEW = ROOT / "data" / "cache" / "v213_top20_report_public_latest.txt"

DISPLAY_COLUMNS = [
    "股票",
    "長期投資報酬率（近2年年化）",
    "短期投資報酬率（近6個月）",
    "行業別",
    "獲利簡述",
    "公司現在訂單",
    "未來訂單預估",
]


class V213ScheduledReportError(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise V213ScheduledReportError(f"Unable to read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise V213ScheduledReportError(f"JSON root must be an object: {path}")
    return value


def _load_names(path: Path) -> dict[str, str]:
    """Official public company names from the accepted Top20 universe, keyed by ticker."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise V213ScheduledReportError(f"Unable to read Top20 universe: {path}") from exc
    rows = raw if isinstance(raw, list) else raw.get("records") if isinstance(raw, dict) else None
    if not isinstance(rows, list) or len(rows) != 20:
        raise V213ScheduledReportError("TOP20_UNIVERSE_INVALID")
    names: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise V213ScheduledReportError("TOP20_UNIVERSE_INVALID")
        ticker = str(row.get("ticker") or "").upper()
        if not ticker or ticker in names:
            raise V213ScheduledReportError("TOP20_UNIVERSE_INVALID")
        names[ticker] = str(row.get("name") or "")
    return names


def _records(doc: Mapping[str, Any], version: str) -> list[dict[str, Any]]:
    if str(doc.get("product_version")) != version:
        raise V213ScheduledReportError(f"Expected product_version={version}")
    rows = doc.get("records")
    if not isinstance(rows, list) or len(rows) != 20:
        raise V213ScheduledReportError("Expected exactly 20 records")
    result: list[dict[str, Any]] = []
    tickers: set[str] = set()
    for index, raw in enumerate(rows, 1):
        if not isinstance(raw, dict):
            raise V213ScheduledReportError("Record must be an object")
        ticker = str(raw.get("ticker") or "").upper()
        if not ticker or ticker in tickers or int(raw.get("rank") or 0) != index:
            raise V213ScheduledReportError("Ticker/rank contract failed")
        tickers.add(ticker)
        result.append(dict(raw))
    return result


def _completion_time() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _market_anchor(return_evidence: Mapping[str, Any] | None, ticker: str) -> str | None:
    """Date of the latest daily bar behind the row's market fields (source state, not the retrieval time)."""
    record = ((return_evidence or {}).get("records") or {}).get(ticker) or {}
    windows = record.get("windows") or {}
    for window in ("six_month", "two_year"):  # the same daily series; the 2Y window when the 6M one is missing
        end = (windows.get(window) or {}).get("actual_end")
        moment = parse_time(end)
        if moment is not None and len(str(end)) == 10:
            return iso_z(moment)
    return None


def _withheld_orders(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Order fields when a disclosed claim is older than its evidence window: shown as not disclosed, never
    re-anchored to a longer window or a newer date."""
    return {**evidence, "current_orders": NO_CURRENT_ORDERS, "future_orders_estimate": NO_FUTURE_ORDER_ESTIMATE,
            "orders_as_of": "", "orders_confidence": "UNAVAILABLE", "current_order_source_urls": [], "future_order_source_urls": []}


NO_CURRENT_ORDERS = "未揭露（無可靠公開訂單數字）"
NO_FUTURE_ORDER_ESTIMATE = "無可靠公開預估"
NO_PROFIT_METRICS = "SEC 可用獲利指標不足"


def _profit_claim_displayed(summary: Any) -> bool:
    """The profit column shows at least one SEC metric (anything but the 'metrics insufficient' text)."""
    return isinstance(summary, str) and bool(summary.strip()) and summary.strip() != NO_PROFIT_METRICS


def build(v212: Mapping[str, Any], baseline: Mapping[str, Any], top20_names: Mapping[str, str], *,
          require_known_acquisition: bool = False, return_evidence: Mapping[str, Any] | None = None,
          profit_display: Mapping[str, Any] | None = None, report_notes: dict[str, Any] | None = None) -> dict[str, Any]:
    """Seven-field report with the two-anchor evidence contract the Worker enforces (top20-report.ts).

    A row that displays a company current-state claim (a retained order disclosure, or a profit metric
    from ``profit_display``: the v212 builder's display sidecar) is a current_state_claim anchored at the
    oldest filing date behind those claims. Only a row that displays no company claim is a market_observation
    anchored at its latest daily bar, which never certifies an SEC claim. Every window keeps the report carry
    margin (report_max_age_hours) so a row accepted now is still inside its window when last re-sealed. An order
    claim outside that is withheld (``report_notes``); a displayed profit claim without a filing date, or a row
    without a dated anchor inside its window, fails the build."""
    # Orders can be acquired AFTER the five-field report. This is a new artifact
    # completion clock; it must never replace any operand's acquisition clock.
    completed_at = _completion_time()
    try:
        validate_report_acquisition(v212, require_known=require_known_acquisition)
        if utc_time(v212['generated_at']) > utc_time(completed_at):
            raise SourceAcquisitionError('SOURCE_ACQUISITION_AFTER_COMPLETION')
    except SourceAcquisitionError as error:
        raise V213ScheduledReportError(str(error)) from None
    fresh = _records(v212, "2.1.2")
    accepted = _records(baseline, "2.1.3")
    fresh_order = [row["ticker"] for row in fresh]
    accepted_order = [row["ticker"] for row in accepted]
    if set(fresh_order) != set(accepted_order):
        added = sorted(set(fresh_order) - set(accepted_order))
        missing = sorted(set(accepted_order) - set(fresh_order))
        raise V213ScheduledReportError(
            "Top20 membership changed; H6B evidence rebuild required; "
            f"added={','.join(added) or '-'}; missing={','.join(missing) or '-'}"
        )

    evidence_by_ticker = {row["ticker"]: row for row in accepted}
    policy = load_policy()
    margin = report_freshness()["report_max_age_hours"] * 3600
    claim_window = window_days("current_state_claim", policy) * 86400 - margin
    market_window = window_days("market_observation", policy) * 86400 - margin
    completed = utc_time(completed_at)
    profit_claims = (profit_display or {}).get("records") or {}
    withheld: list[str] = []
    rows: list[dict[str, Any]] = []
    for rank, fresh_row in enumerate(fresh, 1):
        ticker = fresh_row["ticker"]
        evidence = evidence_by_ticker[ticker]
        retrieved = fresh_row['retrieved_at']
        no_order_claim = (evidence.get('orders_confidence') in ('UNAVAILABLE', 'NO_RELIABLE_PUBLIC_ORDER_NUMBER')
                          and evidence.get('current_orders') == NO_CURRENT_ORDERS
                          and evidence.get('future_orders_estimate') == NO_FUTURE_ORDER_ESTIMATE
                          and evidence.get('current_order_source_urls') == []
                          and evidence.get('future_order_source_urls') == [])
        claim_anchor = None if no_order_claim else parse_time(evidence.get('orders_as_of'))
        if not no_order_claim and (claim_anchor is None or (completed - claim_anchor).total_seconds() > claim_window):
            withheld.append(ticker)  # stale or undated claim: not publishable under the current-state window
            evidence, no_order_claim, claim_anchor = _withheld_orders(evidence), True, None
        if not no_order_claim:
            # Retained order evidence does not inherit a refreshed market clock.
            # Neither orders_as_of nor a new generation date is acquisition time.
            try:
                retained = evidence.get('retrieved_at')
                if retained is None:
                    retrieved = None
                else:
                    if utc_time(retained) > utc_time(completed_at):
                        raise SourceAcquisitionError('SOURCE_ACQUISITION_AFTER_COMPLETION')
                    retrieved = min((retrieved, retained), key=utc_time) if retrieved is not None else None
            except SourceAcquisitionError:
                raise V213ScheduledReportError('ORDER_SOURCE_ACQUISITION_UNKNOWN_OR_INVALID') from None
        if require_known_acquisition and retrieved is None:
            raise V213ScheduledReportError('SOURCE_ACQUISITION_UNKNOWN')
        name = top20_names.get(ticker)
        if (not isinstance(name, str) or not name.strip() or len(name.strip()) > 120
                or "\r" in name or "\n" in name or "｜" in name):
            raise V213ScheduledReportError(f"TOP20_NAME_MISSING_OR_INVALID:{ticker}")
        claim_dates = [] if claim_anchor is None else [claim_anchor]
        if _profit_claim_displayed(fresh_row.get("profit_summary")):
            filed = parse_time((profit_claims.get(ticker) or {}).get("claim_filed_at"))
            if filed is None:
                raise V213ScheduledReportError(f"PROFIT_CLAIM_DATE_UNKNOWN:{ticker}")
            claim_dates.append(filed)
        if claim_dates:
            evidence_class, anchor, limit = "current_state_claim", min(claim_dates), claim_window
        else:
            evidence_class, anchor, limit = "market_observation", parse_time(_market_anchor(return_evidence, ticker)), market_window
        if anchor is None:
            raise V213ScheduledReportError(f"EVIDENCE_ANCHOR_MISSING:{ticker}")
        if not -300 <= (completed - anchor).total_seconds() <= limit:
            raise V213ScheduledReportError(f"EVIDENCE_ANCHOR_OUTSIDE_WINDOW:{ticker}")
        anchor = iso_z(anchor)
        record = {
            "schema_version": 2,
            "rank": rank,
            "ticker": ticker,
            "name": name.strip(),
            "long_term_return_pct": fresh_row.get("long_term_return_pct"),
            "short_term_return_pct": fresh_row.get("short_term_return_pct"),
            "industry": fresh_row.get("industry"),
            "profit_summary": fresh_row.get("profit_summary"),
            "current_orders": evidence.get("current_orders"),
            "future_orders_estimate": evidence.get("future_orders_estimate"),
            "long_term_window": "2y_cagr",
            "short_term_window": "6m_price_return",
            "market_source": "yfinance",
            "profit_source": "sec_edgar",
            "orders_as_of": evidence.get("orders_as_of"),
            "orders_confidence": evidence.get("orders_confidence"),
            "current_order_source_urls": list(evidence.get("current_order_source_urls") or []),
            "future_order_source_urls": list(evidence.get("future_order_source_urls") or []),
            "numeric_total_order_estimate_prohibited": True,
            "retrieved_at": retrieved,
            "orders_state_as_of": anchor,
            "evidence_class": evidence_class,
            "freshness_policy_key": CLASS_POLICY_KEY[evidence_class],
            # Real public-data rows, not the licensed test-qualification path (readers disclose LIMITED research).
            "test_only_admission": False,
            "provider_scope": "public_only",
            "owner_watchlist_inherited": False,
        }
        if "two_year_total_return_pct" in fresh_row:
            record["two_year_total_return_pct"] = fresh_row["two_year_total_return_pct"]
        if "two_year_return_evidence" in fresh_row:
            record["two_year_return_evidence"] = fresh_row["two_year_return_evidence"]
        rows.append(record)

    known = [utc_time(row["retrieved_at"]) for row in rows if row["retrieved_at"] is not None]
    if not known and require_known_acquisition:
        raise V213ScheduledReportError("EVIDENCE_CAPTURE_UNKNOWN")
    if report_notes is not None:
        report_notes["withheld_stale_order_claims"] = withheld
    return {
        "schema_version": 2,
        "product_version": "2.1.3",
        "generated_at": completed_at,
        "freshness_policy": policy_binding(),
        # Oldest real acquisition behind the rows (never the completion or seal clock). A candidate whose
        # clocks are all unknown carries null, which every reader refuses (not publishable).
        "evidence_capture_at": iso_z(min(known)) if known else None,
        "display_columns": DISPLAY_COLUMNS,
        "long_term_definition": "trailing_2y_adjusted_close_cagr",
        "short_term_definition": "trailing_6m_adjusted_close_price_return",
        "records": rows,
        "provider_scope": "public_only",
        "owner_watchlist_inherited": False,
    }


def _percent(value: Any) -> str:
    if value is None:
        return "N/A"
    value = float(value)
    return f"{value:+.1f}%"


def preview(report: Mapping[str, Any]) -> str:
    lines = ["｜".join(DISPLAY_COLUMNS)]
    for row in report["records"]:
        lines.append("｜".join([
            str(row["ticker"]),
            _percent(row.get("long_term_return_pct")),
            _percent(row.get("short_term_return_pct")),
            str(row.get("industry") or ""),
            str(row.get("profit_summary") or ""),
            str(row.get("current_orders") or ""),
            str(row.get("future_orders_estimate") or ""),
        ]))
    text = "\n".join(lines)
    if len(lines) != 21 or any(len(line.split("｜")) != 7 for line in lines[1:]):
        raise V213ScheduledReportError("Seven-field preview contract failed")
    if len(text) > 4900:
        raise V213ScheduledReportError(f"LINE preview exceeds one-message limit: {len(text)}")
    return text


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False, dir=path.parent,
        prefix=f".{path.name}.", suffix=".tmp"
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def self_test() -> None:
    generated = "2026-09-01T12:22:48Z"
    tickers = [f"T{i:02d}" for i in range(20)]
    v212 = {
        "product_version": "2.1.2", "generated_at": generated,
        "records": [{
            "rank": i + 1, "ticker": ticker, "long_term_return_pct": 10 + i,
            "short_term_return_pct": 2 + i, "industry": "半導體",
            "profit_summary": "獲利", "retrieved_at": generated,
        } for i, ticker in enumerate(tickers)]
    }
    # Explicit synthetic acquisition metadata; not a real source proof.
    v212.update(schema_version=2, calculation_cutoff=generated, display_columns=DISPLAY_COLUMNS[:5],
                long_term_definition='trailing_2y_adjusted_close_cagr', short_term_definition='trailing_6m_adjusted_close_price_return',
                provider_scope='public_only', owner_watchlist_inherited=False)
    for row in v212['records']:
        row.update(schema_version=2, long_term_window='2y_cagr', short_term_window='6m_price_return',
                   market_source='yfinance', profit_source='sec_edgar', provider_scope='public_only', owner_watchlist_inherited=False)
        row['source_acquisition'] = {key: field_clock(key, row[key], retrieved_at=generated, evidence_sha256='1'*64)
                                     for key in ('long_term_return_pct', 'short_term_return_pct', 'industry', 'profit_summary')}
    baseline = {
        "product_version": "2.1.3",
        "records": [{
            "rank": i + 1, "ticker": ticker,
            "current_orders": "未揭露（無可靠公開訂單數字）",
            "future_orders_estimate": "無可靠公開預估",
            "orders_as_of": "2026-08-31",
            "orders_confidence": "NO_RELIABLE_PUBLIC_ORDER_NUMBER",
            "current_order_source_urls": [], "future_order_source_urls": [],
        } for i, ticker in enumerate(reversed(tickers))]
    }
    names = {ticker: f"Synthetic Company {i}" for i, ticker in enumerate(tickers)}
    today = datetime.now(timezone.utc).date().isoformat()
    returns = {"records": {ticker: {"windows": {"six_month": {"actual_end": today}}} for ticker in tickers}}
    claims = {"records": {ticker: {"claim_filed_at": today} for ticker in tickers}}
    result = build(v212, baseline, names, return_evidence=returns, profit_display=claims)
    assert [r["ticker"] for r in result["records"]] == tickers
    assert [r["name"] for r in result["records"]] == [f"Synthetic Company {i}" for i in range(20)]
    assert all(r["evidence_class"] == "current_state_claim" and r["orders_state_as_of"] == f"{today}T00:00:00Z"
               and r["test_only_admission"] is False for r in result["records"])
    assert result["evidence_capture_at"] == "2026-09-01T12:22:48Z" and result["freshness_policy"] == policy_binding()
    assert len(preview(result).splitlines()) == 21
    bad = dict(v212)
    bad["records"] = [dict(row) for row in v212["records"]]
    bad["records"][19]["ticker"] = "NEW"
    for broken, kwargs in ((bad, {"return_evidence": returns, "profit_display": claims}),
                           (v212, {"return_evidence": returns, "profit_display": {"records": {}}})):
        try:
            build(broken, baseline, names, **kwargs)
        except V213ScheduledReportError:
            pass
        else:
            raise AssertionError("membership drift or a missing evidence anchor did not fail closed")
    print("V213_SCHEDULED_REPORT_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v212-report", type=Path, default=DEFAULT_V212)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--top20", type=Path, default=DEFAULT_TOP20, help="Accepted Top20 universe (official company names)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--require-known-acquisition", action="store_true", help="Refuse unknown clocks before output writes; never grants publication authority")
    parser.add_argument("--return-evidence", type=Path, default=None,
                        help="Market return sidecar (latest daily bar anchors); default: <v212-report>.return-evidence-candidate.json")
    parser.add_argument("--profit-display", type=Path, default=None,
                        help="Displayed profit metrics with filing dates; default: <v212-report>.profit-display-candidate.json")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    evidence_path = args.return_evidence or args.v212_report.with_name(args.v212_report.stem + ".return-evidence-candidate.json")
    display_path = args.profit_display or args.v212_report.with_name(args.v212_report.stem + ".profit-display-candidate.json")
    notes: dict[str, Any] = {}
    report = build(_load(args.v212_report), _load(args.baseline), _load_names(args.top20),
                   require_known_acquisition=args.require_known_acquisition, return_evidence=_load(evidence_path),
                   profit_display=_load(display_path) if display_path.exists() else None, report_notes=notes)
    text = preview(report)
    atomic_text(args.output, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
    atomic_text(args.preview, text + "\n")
    unknown = sum(row['retrieved_at'] is None for row in report['records'])
    withheld = ",".join(notes.get("withheld_stale_order_claims") or []) or "-"
    print(f"V213_SCHEDULED_REPORT = CANDIDATE; rows=20; chars={len(text)}; acquisition_unknown={unknown}; "
          f"withheld_stale_order_claims={withheld}; publication_qualified=false")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except V213ScheduledReportError as exc:
        print(f"V213_SCHEDULED_REPORT = FAIL; {exc}", file=sys.stderr)
        raise SystemExit(1)
