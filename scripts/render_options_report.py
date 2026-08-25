#!/usr/bin/env python3
"""Render holdings-aware weekly/monthly option BID/ASK observations."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data" / "cache"
REPORTS_DIR = BASE_DIR / "reports"
TAIPEI = ZoneInfo("Asia/Taipei")


def number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def money(value: Any) -> str:
    parsed = number(value)
    return "N/A" if parsed is None else f"${parsed:,.2f}"


def percent(value: Any, digits: int = 1) -> str:
    parsed = number(value)
    return "N/A" if parsed is None else f"{parsed:.{digits}f}%"


def integer(value: Any) -> str:
    parsed = number(value)
    return "N/A" if parsed is None else f"{int(parsed):,}"


def option_rows(candidates: list[dict[str, Any]], strategy: str) -> list[str]:
    if strategy == "covered_call":
        header = (
            "| Strike | DTE | BID | ASK | Mid | Spread% | OI | Vol | IV | "
            "Bid/Mid/Ask 年化 | 觀察限價區間 | Mid 有效售價 |"
        )
        separator = "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|"
    else:
        header = (
            "| Strike | DTE | BID | ASK | Mid | Spread% | OI | Vol | IV | "
            "Bid/Mid/Ask 年化 | 觀察限價區間 | Mid 損益兩平 | 現金義務 |"
        )
        separator = "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---:|"

    lines = [header, separator]
    for item in candidates:
        yields = item.get("annualized_yield_pct") or {}
        limit_data = item.get("sell_limit_observation") or {}
        limit_text = (
            f"{money(limit_data.get('observed_limit_low'))}–"
            f"{money(limit_data.get('observed_limit_high'))}"
        )
        yield_text = (
            f"{percent(yields.get('bid'))} / {percent(yields.get('mid'))} / "
            f"{percent(yields.get('ask'))}"
        )
        common = (
            f"| {money(item.get('strike'))} | {item.get('actual_dte', 'N/A')} | "
            f"{money(item.get('bid'))} | {money(item.get('ask'))} | "
            f"{money(item.get('midpoint'))} | {percent(item.get('spread_pct_of_mid'))} | "
            f"{integer(item.get('open_interest'))} | {integer(item.get('volume'))} | "
            f"{percent(item.get('implied_volatility_pct'))} | {yield_text} | {limit_text} |"
        )
        if strategy == "covered_call":
            effective = item.get("effective_sale_price") or {}
            lines.append(f"{common} {money(effective.get('mid'))} |")
        else:
            break_even = item.get("put_break_even") or {}
            lines.append(
                f"{common} {money(break_even.get('mid'))} | "
                f"{money(item.get('cash_secured_put_cash_requirement'))} |"
            )
    return lines


def render_options_report(
    options_data: list[dict[str, Any]],
    output_path: Path | None = None,
) -> str:
    now = datetime.now(TAIPEI)
    output = output_path or REPORTS_DIR / "options_latest.md"
    output.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        f"# 每週／每月期權 BID–ASK 觀察 — {now:%Y-%m-%d %H:%M %Z}",
        "",
        "> 本報告列出行情與流動性觀察，不會自動下單。BID/ASK 可能延遲、變動或無法成交。",
        "> 期權模組是本專案自行設計，不歸因於 Serenity 或 Leopold Aschenbrenner。",
        "> Covered call 可能導致持股被履約賣出；cash-secured put 可能要求以 Strike 買進 100 股。",
        "",
    ]

    for result in options_data or []:
        if not isinstance(result, dict):
            continue
        ticker = result.get("ticker", "N/A")
        status = result.get("status", "UNKNOWN")
        position = result.get("position") or {}
        lines.extend([f"## {ticker}", ""])
        lines.append(
            f"- 狀態：`{status}`；行情來源：`{result.get('quote_source', 'N/A')}`；"
            f"延遲標記：`{result.get('quote_delay_status', 'N/A')}`"
        )
        lines.append(
            f"- 標的價格：{money(result.get('current_price'))}；"
            f"持倉來源：`{position.get('source', 'unavailable')}`；"
            f"可覆蓋 call 合約上限：{integer(position.get('covered_contract_capacity'))}"
        )
        if status != "OK":
            lines.extend(
                [
                    "",
                    "目前無法產生合格週／月候選；系統不會捏造期權鏈。",
                    "",
                ]
            )
            continue

        periods = result.get("periods") or {}
        for period_name in ("weekly", "monthly"):
            period = periods.get(period_name)
            if not isinstance(period, dict):
                continue
            label = "每週" if period_name == "weekly" else "每月"
            lines.extend(
                [
                    f"### {label} — 到期 {period.get('expiration', 'N/A')} / "
                    f"實際 DTE {period.get('actual_dte', 'N/A')}",
                    "",
                ]
            )

            call_data = period.get("covered_call") or {}
            calls = call_data.get("recommended_candidates") or []
            lines.extend(["#### Covered call 候選", ""])
            if calls:
                lines.extend(option_rows(calls, "covered_call"))
            else:
                lines.append(
                    f"- `{call_data.get('status', 'NO_DATA')}`：可能沒有確認持有 100 股、沒有雙邊行情，或流動性未通過。"
                )
            lines.append("")

            put_data = period.get("cash_secured_put") or {}
            puts = put_data.get("recommended_candidates") or []
            lines.extend(["#### Cash-secured put 候選", ""])
            if puts:
                lines.extend(option_rows(puts, "cash_secured_put"))
            else:
                lines.append(
                    f"- `{put_data.get('status', 'NO_DATA')}`：沒有符合價差、OI、成交量或報價新鮮度規則的候選。"
                )
            lines.append("")

    if not options_data:
        lines.append("沒有期權資料。")

    lines.extend(
        [
            "---",
            "觀察限價區間預設由 BID 上方四分之一價差至 Midpoint；這不是成交保證或個人化下單指示。",
            "Delta 若資料來源未提供會顯示 N/A，系統不得使用假設值代替。",
        ]
    )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Options report generated: %s", output)
    return str(output)


def main() -> int:
    source = DATA_DIR / "options_latest.json"
    if not source.is_file():
        raise SystemExit("options_latest.json not found")
    document = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(document, list):
        raise SystemExit("options_latest.json must contain an array")
    print(render_options_report(document))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
