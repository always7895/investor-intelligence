"""Dataset 11320 only: local TAIFEX daily options observations, never live BBO.

No contract multiplier, expiry day, currency, Greeks or executable midpoint is
inferred from the daily export. Session rows remain distinct; OI is not summed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math
import re
from typing import Any, Mapping

from .base import AdapterError, ParsedBatch, json_document, make_batch, utc_iso
from taifex_contract import TAIFEX_DAILY_URL, daily_identity

SOURCE = 'taifex_options_eod'
TAIFEX_EOD_FEEDS = {SOURCE: TAIFEX_DAILY_URL}
FIELDS = frozenset({'Date', 'Contract', 'ContractMonth(Week)', 'StrikePrice', 'CallPut',
                    'Open', 'High', 'Low', 'Close', 'Volume', 'SettlementPrice', 'OpenInterest',
                    'BestBid', 'BestAsk', 'HistoricalHigh', 'HistoricalLow', 'TradingHalt', 'TradingSession'})
CALL_PUT = {'買權': 'call', '賣權': 'put'}
SESSIONS = {'一般': 'REGULAR', '盤後': 'AFTER_HOURS'}
HALT = {'': 'NOT_REPORTED', '是': 'HALTED', '否': 'NOT_HALTED'}


def number(raw: str, *, integer: bool = False, positive: bool = False) -> float | int | None:
    text = raw.strip()
    if text in ('', '-', '--', '---'):
        if positive: raise ValueError('TAIFEX_EOD_REQUIRED_NUMBER')
        return None
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', text):
        raise ValueError('TAIFEX_EOD_INVALID_NUMBER')
    value = Decimal(text)
    if value > 2**53 - 1 or (positive and value <= 0) or (integer and value != value.to_integral_value()):
        raise ValueError('TAIFEX_EOD_INVALID_NUMBER')
    parsed = float(value)
    if not math.isfinite(parsed): raise ValueError('TAIFEX_EOD_INVALID_NUMBER')
    return int(value) if integer else parsed


class TaifexOptionsEodAdapter:
    source_id = SOURCE
    parser_version = 'taifex-options-eod-v1'

    def parse(self, content: bytes, *, content_type: str, retrieved_at: str,
              context: Mapping[str, Any]) -> ParsedBatch:
        if len(content) > 8_000_000: raise AdapterError('TAIFEX_EOD_TOO_LARGE')
        raw = json_document(content)
        if not isinstance(raw, list) or not 1 <= len(raw) <= 20000:
            raise AdapterError('TAIFEX_EOD_INVALID_ROWS')
        local_day = datetime.fromisoformat(utc_iso(retrieved_at)).astimezone(timezone(timedelta(hours=8))).date()
        records, seen = [], set()
        batch_day = None
        try:
            for row in raw:
                if not isinstance(row, dict) or set(row) != FIELDS:
                    raise ValueError('TAIFEX_EOD_SCHEMA_CHANGED')
                if any(not isinstance(value, str) or len(value) > 64 for value in row.values()):
                    raise ValueError('TAIFEX_EOD_INVALID_FIELD_TYPE')
                trade_day, code, series, _, _ = daily_identity(row, taipei_day=local_day)
                age = (local_day - trade_day).days
                # Conservative local observation ceiling, not an exchange calendar
                # certification or the LINE current-quote freshness policy.
                if not 0 <= age <= 7: raise ValueError('TAIFEX_EOD_DATE_OUT_OF_RANGE')
                if batch_day is not None and trade_day != batch_day:
                    raise ValueError('TAIFEX_EOD_MIXED_DATES')
                batch_day = trade_day
                if row['CallPut'] not in CALL_PUT or row['TradingSession'] not in SESSIONS or row['TradingHalt'] not in HALT:
                    raise ValueError('TAIFEX_EOD_UNKNOWN_ENUM')
                strike = number(row['StrikePrice'], positive=True)
                kind, session = CALL_PUT[row['CallPut']], SESSIONS[row['TradingSession']]
                identity = (trade_day, code, series, Decimal(row['StrikePrice'].strip()), kind, session)
                if identity in seen: raise ValueError('TAIFEX_EOD_DUPLICATE_CONTRACT_SESSION')
                seen.add(identity)
                prices = {key: number(row[key]) for key in ('Open', 'High', 'Low', 'Close', 'SettlementPrice', 'BestBid', 'BestAsk', 'HistoricalHigh', 'HistoricalLow')}
                high, low = prices['High'], prices['Low']
                if high is not None and low is not None and (high < low or any(prices[k] is not None and not low <= prices[k] <= high for k in ('Open', 'Close'))):
                    raise ValueError('TAIFEX_EOD_INCONSISTENT_OHLC')
                bid, ask = prices['BestBid'], prices['BestAsk']
                quote_status = 'NO_POSITIVE_TWO_SIDED_OBSERVATION' if bid is None or ask is None or bid <= 0 or ask <= 0 else (
                    'CROSSED_EOD_OBSERVATION' if bid > ask else 'UNTIMED_EOD_OBSERVATION')
                records.append({
                    'record_type': 'exchange_option_eod', 'source_id': SOURCE, 'provider_id': 'taifex_public_options',
                    'source_url': TAIFEX_EOD_FEEDS[SOURCE], 'origin': 'taifex.com.tw', 'venue': 'TAIFEX',
                    'contract_code': code, 'contract_month_week': series, 'option_type': kind,
                    'strike': strike, 'strike_source_text': row['StrikePrice'], 'trade_date': trade_day.isoformat(),
                    'trading_session': session, 'trading_halt_status': HALT[row['TradingHalt']],
                    'open': prices['Open'], 'high': high, 'low': low, 'last_trade_price': prices['Close'],
                    'settlement_price': prices['SettlementPrice'], 'last_best_bid': bid, 'last_best_ask': ask,
                    'volume_contracts': number(row['Volume'], integer=True),
                    'open_interest_contracts': number(row['OpenInterest'], integer=True),
                    'open_interest_not_additive_across_sessions': True,
                    'quote_status': quote_status, 'quote_time': None, 'feed_type': 'END_OF_DAY',
                    'age_calendar_days': age, 'price_unit_status': 'UNRESOLVED_CONTRACT_SPEC',
                    'currency': None, 'contract_multiplier': None, 'expiration_date': None, 'actual_dte': None, 'delta': None,
                    'publication_eligible': False, 'line_quote_eligible': False, 'executable_quote': False,
                    'attribution': {'provider': '臺灣期貨交易所', 'dataset': '選擇權每日交易行情',
                                    'dataset_url': 'https://data.gov.tw/dataset/11320', 'dataset_version': None,
                                    'data_date': trade_day.isoformat(), 'source_year': trade_day.year,
                                    'license': '政府資料開放授權條款-第1版', 'license_url': 'https://data.gov.tw/license',
                                    'notice': '依原始開放資料再製；未獲資料提供機關背書。'},
                })
        except (ValueError, TypeError, OverflowError) as exc:
            code = str(exc)
            # All-or-nothing batch, no raw provider values/exception messages.
            raise AdapterError(code if re.fullmatch(r'TAIFEX_EOD_[A-Z_]+', code) else 'TAIFEX_EOD_INVALID_VALUE') from None
        return make_batch(source_id=SOURCE, parser_version=self.parser_version, content=content,
                          retrieved_at=retrieved_at, records=records)


TAIFEX_EOD_ADAPTERS = {SOURCE: TaifexOptionsEodAdapter()}
