"""Official TWSE/TPEx EOD observations. Distinct venues are not corroborating quotes."""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

from .base import AdapterError, ParsedBatch, json_document, make_batch, utc_iso

EQUITY_FEEDS = {
    "twse_equity_eod": "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
    "tpex_equity_eod": "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
}


def numeric(value: Any, integer: bool = False):
    if isinstance(value, str):
        value = value.strip()
    if value is None or value in ("", "-", "--", "---"):
        return None
    if isinstance(value, bool):
        raise ValueError("INVALID_NUMBER")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (integer and not result.is_integer()):
        raise ValueError("INVALID_NUMBER")
    return int(result) if integer else result


class TaiwanEquitiesAdapter:
    parser_version = "taiwan-equity-eod-v1"

    def __init__(self, source_id: str):
        self.source_id = source_id

    def parse(self, content: bytes, *, content_type: str, retrieved_at: str,
              context: Mapping[str, Any]) -> ParsedBatch:
        if len(content) > 8_000_000:
            raise AdapterError("EQUITY_EXPORT_TOO_LARGE")
        raw = json_document(content)
        if not isinstance(raw, list) or len(raw) > 20000:
            raise AdapterError("INVALID_EQUITY_ROWS")
        retrieved = datetime.fromisoformat(utc_iso(retrieved_at))
        local_day = retrieved.astimezone(timezone(timedelta(hours=8))).date()
        twse = self.source_id == "twse_equity_eod"
        fields = ("Code", "OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice", "TradeVolume") if twse else (
            "SecuritiesCompanyCode", "Open", "High", "Low", "Close", "TradingShares")
        records, warnings, seen = [], [], set()
        for index, row in enumerate(raw):
            try:
                if not isinstance(row, dict):
                    raise ValueError("INVALID_ROW")
                day = str(row.get("Date", ""))
                if not re.fullmatch(r"\d{7}", day):
                    raise ValueError("INVALID_ROC_DATE")
                trade_date = date(int(day[:3]) + 1911, int(day[3:5]), int(day[5:]))
                if trade_date > local_day:
                    raise ValueError("FUTURE_TRADE_DATE")
                code = row.get(fields[0])
                if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9]{4,12}", code):
                    raise ValueError("INVALID_SECURITY_CODE")
                opening, high, low, close = [numeric(row.get(field)) for field in fields[1:5]]
                if high is not None and low is not None:
                    if high < low or any(value is not None and not low <= value <= high for value in (opening, close)):
                        raise ValueError("INCONSISTENT_OHLC")
                key = (code, trade_date)
                if key in seen:
                    raise ValueError("DUPLICATE_SECURITY_DATE")
                volume = numeric(row.get(fields[5]), integer=True)
                seen.add(key)
                records.append({"record_type": "exchange_security_eod", "security_code": code,
                                "venue": "TWSE" if twse else "TPEX", "currency": "TWD",
                                "trade_date": trade_date.isoformat(), "quote_time": None,
                                "open": opening, "high": high, "low": low, "close": close,
                                "quote_status": "MISSING_CLOSE" if close is None else "EOD_OBSERVATION",
                                "volume_shares": volume, "price_adjustment": "UNADJUSTED",
                                "source_id": self.source_id, "origin": "twse.com.tw" if twse else "tpex.org.tw",
                                "source_url": EQUITY_FEEDS[self.source_id], "feed_type": "END_OF_DAY",
                                "age_calendar_days": (local_day - trade_date).days,
                                "publication_eligible": False, "executable_quote": False})
            except (ValueError, TypeError, OverflowError):
                warnings.append(f"INVALID_EQUITY_ROW:{index}")
        return make_batch(source_id=self.source_id, parser_version=self.parser_version, content=content,
                          retrieved_at=retrieved_at, records=records, warnings=warnings)


EQUITY_ADAPTERS = {source: TaiwanEquitiesAdapter(source) for source in EQUITY_FEEDS}
