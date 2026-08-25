#!/usr/bin/env python3
"""Generate a Taiwan Traditional Chinese public-only research briefing.

The generator reads only independently attested public artifacts. It never
loads the owner watchlist, portfolio, IBKR output, private reports, generic
operator pipeline files or tenant data. Validation is reused from the public KV
publisher so the report and Worker share the same closed schemas.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sync_to_kv import (
    PUBLIC_METADATA_FILENAME,
    PUBLIC_OPTIONS_FILENAME,
    PUBLIC_SCORES_FILENAME,
    PUBLIC_SOURCE_VIEWS_FILENAME,
    _validate_public_metadata,
    _validate_public_options,
    _validate_public_scores,
    _validate_public_source_views,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "cache"
REPORTS_DIR = ROOT / "reports"
TAIPEI = ZoneInfo("Asia/Taipei")
MAX_REPORT_BYTES = 2_000_000
ATTESTATIONS = (
    "<!-- line-public-eligible: true -->",
    "<!-- provider-scope: public_only -->",
    "<!-- owner-watchlist-inherited: false -->",
)
FORBIDDEN_REPORT_MARKERS = (
    "user-defined long-term suitability overlay",
    "repository user's preference",
    "owner watchlist",
    "private portfolio",
    "portfolio.local",
    "tenant-private",
    "ibkr account",
    "broker account",
    "covered_contract_capacity",
    "account_id",
    "position_shares",
)


class PublicBriefingError(ValueError):
    """Raised when a public report input or output violates a hard boundary."""


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise PublicBriefingError(f"Invalid JSON in {path}: {exc}") from exc


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _money(value: Any, currency: str = "USD") -> str:
    parsed = _number(value)
    return "N/A" if parsed is None else f"{currency} {parsed:,.2f}"


def _percent(value: Any, *, fraction: bool = False) -> str:
    parsed = _number(value)
    if parsed is None:
        return "N/A"
    if fraction:
        parsed *= 100
    return f"{parsed:.1f}%"


def _safe_text(value: Any, maximum: int = 500) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split())
    return text[:maximum]


def _safe_https_url(value: Any) -> str:
    text = str(value or "").strip()
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError as exc:
        raise PublicBriefingError("Public source URL is invalid") from exc
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or port not in (None, 443)
    ):
        raise PublicBriefingError("Public source URL must be safe HTTPS")
    return text


def load_public_inputs(
    *,
    data_dir: Path = DATA_DIR,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    metadata = _validate_public_metadata(_json(data_dir / PUBLIC_METADATA_FILENAME))
    scores = _validate_public_scores(_json(data_dir / PUBLIC_SCORES_FILENAME))
    options = _validate_public_options(_json(data_dir / PUBLIC_OPTIONS_FILENAME))
    source_path = data_dir / PUBLIC_SOURCE_VIEWS_FILENAME
    source_views = (
        _validate_public_source_views(_json(source_path)) if source_path.is_file() else []
    )
    return metadata, scores, options, source_views


def _option_rows(options: list[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for record in options:
        ticker = _safe_text(record.get("ticker"), 20)
        currency = _safe_text(record.get("currency") or "USD", 8)
        retrieved_at = _safe_text(record.get("retrieved_at"), 40)
        delay = _safe_text(record.get("quote_delay_status") or "UNKNOWN", 80)
        periods = record.get("periods")
        if not isinstance(periods, dict):
            continue
        for period_name in ("weekly", "monthly"):
            period = periods.get(period_name)
            if not isinstance(period, dict):
                continue
            expiration = _safe_text(period.get("expiration") or "N/A", 20)
            dte = period.get("actual_dte")
            for side_key, side_label in (
                ("call_observations", "Call"),
                ("put_observations", "Put"),
            ):
                group = period.get(side_key)
                if not isinstance(group, dict):
                    continue
                candidates = group.get("recommended_candidates")
                if not isinstance(candidates, list):
                    continue
                for item in candidates[:3]:
                    if not isinstance(item, dict):
                        continue
                    rows.append(
                        "| {ticker} | {period} | {side} | {expiration} | {dte} | {strike} | {bid} | {ask} | {mid} | {spread} | {oi} | {volume} | {iv} | {delay} | {retrieved} |".format(
                            ticker=ticker,
                            period="週" if period_name == "weekly" else "月",
                            side=side_label,
                            expiration=expiration,
                            dte=dte if isinstance(dte, int) else "N/A",
                            strike=_money(item.get("strike"), currency),
                            bid=_money(item.get("bid"), currency),
                            ask=_money(item.get("ask"), currency),
                            mid=_money(item.get("midpoint"), currency),
                            spread=_percent(item.get("spread_pct_of_mid")),
                            oi=item.get("open_interest") if isinstance(item.get("open_interest"), int) else "N/A",
                            volume=item.get("volume") if isinstance(item.get("volume"), int) else "N/A",
                            iv=_percent(item.get("implied_volatility_pct")),
                            delay=delay,
                            retrieved=retrieved_at,
                        )
                    )
    return rows


def render_public_briefing(
    metadata: dict[str, Any],
    scores: list[dict[str, Any]],
    options: list[dict[str, Any]],
    source_views: list[dict[str, Any]],
    *,
    generated_at: datetime | None = None,
) -> str:
    now = (generated_at or datetime.now(TAIPEI)).astimezone(TAIPEI)
    public_as_of = _safe_text(metadata.get("last_successful_pipeline_timestamp"), 50)
    lines = [
        *ATTESTATIONS,
        f"# 公開投資研究摘要 — {now:%Y-%m-%d}",
        "",
        f"> 產生時間：{now:%Y-%m-%d %H:%M:%S %Z}",
        f"> 公開資料截至：{public_as_of}",
        "> 本報告只使用經公開資料邊界驗證的內容，不含任何人的持股、帳戶、成本、損益、IBKR、私人觀察清單或對話。",
        "> 報價可能延遲、不完整或暫時無法取得；這是研究軟體輸出，不是交易指示。",
        "",
        "## 公開研究排名",
        "",
        "| 排名 | 代號 | 名稱 | 公開研究分數 | 資料品質 | 評級 | 類別 | 公開資料時間 |",
        "|---:|---|---|---:|---:|---|---|---|",
    ]
    for index, record in enumerate(scores, start=1):
        rank = record.get("rank") if isinstance(record.get("rank"), int) else index
        lines.append(
            "| {rank} | **{ticker}** | {name} | {score} | {quality} | {rating} | {category} | {as_of} |".format(
                rank=rank,
                ticker=_safe_text(record.get("ticker"), 20),
                name=_safe_text(record.get("name") or "N/A", 80),
                score=(f"{_number(record.get('total_score')):.1f}" if _number(record.get("total_score")) is not None else "N/A"),
                quality=_percent(record.get("data_quality"), fraction=True),
                rating=_safe_text(record.get("rating") or "N/A", 30),
                category=_safe_text(record.get("category") or "N/A", 60),
                as_of=_safe_text(record.get("as_of") or record.get("generated_at") or public_as_of, 50),
            )
        )

    lines.extend(
        [
            "",
            "## 公開期權 BID／ASK 觀察",
            "",
            "> 僅列出公開快照中的一般市場觀察；沒有 covered-call 口數、持股數量或帳戶衍生建議。",
            "",
            "| 代號 | 週／月 | 類型 | 到期日 | DTE | 履約價 | BID | ASK | 中間價 | 價差／中間價 | OI | 成交量 | IV | 延遲標籤 | 擷取時間 |",
            "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    option_rows = _option_rows(options)
    lines.extend(option_rows or ["| N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | 目前沒有通過流動性與公開資料驗證的觀察 | N/A |"])

    lines.extend(["", "## 可追溯的公開來源觀察", ""])
    if source_views:
        for record in source_views[:30]:
            url = _safe_https_url(record.get("url"))
            title = _safe_text(record.get("title") or record.get("author") or "公開來源", 120)
            summary = _safe_text(record.get("summary"), 500)
            published = _safe_text(record.get("published_at") or "日期未提供", 50)
            lines.append(f"- **{title}**（{published}）：{summary} — {url}")
    else:
        lines.append("- 目前沒有通過公開來源檢核的來源觀察。")

    lines.extend(
        [
            "",
            "## 資料與風險控制",
            "",
            "- 未知欄位、私人／券商 lineage、非 HTTPS 來源、未標示時間及非有限數值會被拒絕。",
            "- 不以同步時間冒充資料時間；過期資料必須標示或直接不可用。",
            "- 來源數量沒有固定上限，但每次執行受請求、流量、時間、host concurrency 與免費額度限制。",
            "- 編輯性來源只能交叉佐證，不能取代主管機關、交易所、公司申報或官方統計。",
            "- 公開 LINE Bot 不具備投資組合、IBKR、帳戶或交易寫入能力。",
            "",
            "---",
            f"公開研究軟體輸出；產生於 {now:%Y-%m-%d %H:%M:%S %Z}。",
            "",
        ]
    )
    report = "\n".join(lines)
    lowered = report.casefold()
    matches = [marker for marker in FORBIDDEN_REPORT_MARKERS if marker in lowered]
    if matches:
        raise PublicBriefingError(
            "Generated public report contains forbidden marker(s): " + ", ".join(matches)
        )
    encoded = report.encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise PublicBriefingError("Generated public report exceeds the size boundary")
    return report


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def generate_public_briefing(
    *,
    data_dir: Path = DATA_DIR,
    reports_dir: Path = REPORTS_DIR,
    generated_at: datetime | None = None,
) -> tuple[Path, Path]:
    metadata, scores, options, source_views = load_public_inputs(data_dir=data_dir)
    now = (generated_at or datetime.now(TAIPEI)).astimezone(TAIPEI)
    report = render_public_briefing(
        metadata,
        scores,
        options,
        source_views,
        generated_at=now,
    )
    dated = reports_dir / now.strftime("%Y-%m-%d") / "public_briefing.md"
    latest = reports_dir / "public_briefing_latest.md"
    atomic_write(dated, report)
    atomic_write(latest, report)
    return dated, latest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    args = parser.parse_args()
    try:
        dated, latest = generate_public_briefing(
            data_dir=args.data_dir,
            reports_dir=args.reports_dir,
        )
    except (FileNotFoundError, json.JSONDecodeError, PublicBriefingError, ValueError) as exc:
        print(f"PUBLIC BRIEFING FAILED: {exc}")
        return 1
    print(json.dumps({"dated": str(dated), "latest": str(latest)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
