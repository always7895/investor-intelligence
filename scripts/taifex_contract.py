"""Shared TAIFEX daily identity rules; no network, eligibility or expiry inference."""
from datetime import date
import re
from typing import Any, Mapping

TAIFEX_DAILY_URL = 'https://openapi.taifex.com.tw/v1/DailyMarketReportOpt'


def daily_identity(row: Mapping[str, Any], *, taipei_day: date) -> tuple[date, str, str, str, str]:
    raw_day = str(row.get('Date', ''))
    if not re.fullmatch(r'[0-9]{8}', raw_day): raise ValueError('TAIFEX_EOD_INVALID_DATE')
    day = date(int(raw_day[:4]), int(raw_day[4:6]), int(raw_day[6:]))
    if day > taipei_day: raise ValueError('TAIFEX_EOD_FUTURE_DATE')
    contract = str(row.get('Contract', ''))
    series = str(row.get('ContractMonth(Week)', ''))
    right = {'買權': 'C', '賣權': 'P', 'Call': 'C', 'Put': 'P', 'C': 'C', 'P': 'P'}.get(row.get('CallPut'))
    session = str(row.get('TradingSession', ''))
    if not re.fullmatch(r'[A-Z0-9]{1,12}', contract) or not re.fullmatch(r'[0-9]{6}(?:[WF][1-5])?', series) or not right:
        raise ValueError('TAIFEX_EOD_INVALID_CONTRACT')
    date(int(series[:4]), int(series[4:6]), 1)  # calendar month validity only, not the actual expiry day
    if session not in {'一般', '盤後', 'Position', 'AfterHours'}:
        raise ValueError('TAIFEX_EOD_UNKNOWN_SESSION')
    return day, contract, series, right, session
