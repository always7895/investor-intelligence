"""Shared acquisition-clock projection for existing report callers.

Clock/value binding only; not source truth, rights, freshness or publication
certification. No network, private input, model or storage access.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime

FIELDS = ('long_term_return_pct', 'short_term_return_pct', 'industry', 'profit_summary')
ROW_KEYS_V1 = set('schema_version rank ticker long_term_return_pct short_term_return_pct industry profit_summary long_term_window short_term_window market_source profit_source retrieved_at provider_scope owner_watchlist_inherited'.split())
REPORT_KEYS_V1 = set('schema_version product_version generated_at display_columns long_term_definition short_term_definition records provider_scope owner_watchlist_inherited'.split())
CLOCK_KEYS = {'status', 'value', 'retrieved_at', 'evidence_sha256'}
HTTP_RECEIPT_KEYS = {'schema_version', 'request_url', 'body_sha256', 'retrieved_at', 'retrieval_mode'}
COMPANY_RECEIPT_KEYS = HTTP_RECEIPT_KEYS | {'cik', 'adapter_records_sha256'}


class SourceAcquisitionError(ValueError):
    pass


def require(ok, code='SOURCE_ACQUISITION_INVALID'):
    if not ok:
        raise SourceAcquisitionError(code)


def utc_time(value):
    require(isinstance(value, str) and bool(re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{3})?Z', value)), 'SOURCE_ACQUISITION_TIME_INVALID')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise SourceAcquisitionError('SOURCE_ACQUISITION_TIME_INVALID') from None


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def is_sha(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[0-9a-f]{64}', value))


def validate_company_receipt(raw, *, cik, records=None):
    require(isinstance(cik, str) and bool(re.fullmatch(r'[0-9]{10}', cik)) and int(cik) != 0)
    require(isinstance(raw, dict) and set(raw) == COMPANY_RECEIPT_KEYS)
    require(type(raw['schema_version']) is int and raw['schema_version'] == 1
            and raw['cik'] == cik and raw['request_url'] == f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'
            and raw['retrieval_mode'] in ('DIRECT_HTTP', 'BOUND_CACHE')
            and is_sha(raw['body_sha256']) and is_sha(raw['adapter_records_sha256']))
    utc_time(raw['retrieved_at'])
    if records is not None:
        require(raw['adapter_records_sha256'] == digest(records), 'SOURCE_ACQUISITION_RECORDS_MISMATCH')
    return dict(raw)


def bind_company_receipt(raw, *, cik, records):
    require(isinstance(raw, dict) and set(raw) == HTTP_RECEIPT_KEYS)
    return validate_company_receipt({**raw, 'cik': cik, 'adapter_records_sha256': digest(records)}, cik=cik, records=records)


def unavailable(key, value):
    if key in FIELDS[:2]:
        require(value is None or (type(value) in (int, float) and math.isfinite(value) and value >= -100))
        return value is None
    require(isinstance(value, str) and bool(value.strip()))
    try:
        width = len(value.encode('utf-16-le')) // 2
    except UnicodeError:
        raise SourceAcquisitionError('SOURCE_ACQUISITION_INVALID') from None
    require(width <= (100 if key == 'industry' else 120))
    return value == ('未分類' if key == 'industry' else 'SEC 可用獲利指標不足')


def field_clock(key, value, *, retrieved_at=None, evidence_sha256=None):
    require(key in FIELDS)
    missing = unavailable(key, value)
    if missing:
        require(retrieved_at is None and evidence_sha256 is None)
        status = 'UNAVAILABLE'
    elif retrieved_at is None and evidence_sha256 is None:
        status = 'UNKNOWN'
    else:
        utc_time(retrieved_at); require(is_sha(evidence_sha256))
        status = 'KNOWN'
    return {'status': status, 'value': value, 'retrieved_at': retrieved_at, 'evidence_sha256': evidence_sha256}


def row_time(row, *, generated_at):
    clocks = row.get('source_acquisition')
    require(isinstance(clocks, dict) and set(clocks) == set(FIELDS))
    completed = utc_time(generated_at); times = []; unknown = False
    for key in FIELDS:
        item = clocks[key]
        require(isinstance(item, dict) and set(item) == CLOCK_KEYS)
        # Numeric int/float equivalence is allowed, never bool/numeric coercion.
        value = row.get(key); unavailable(key, value)
        require(type(item['value']) is type(value) or (type(value) in (int, float) and type(item['value']) in (int, float)))
        require(item['value'] == value)
        expected = field_clock(key, value, retrieved_at=item['retrieved_at'], evidence_sha256=item['evidence_sha256'])
        require(item == expected)
        if item['status'] == 'UNKNOWN':
            unknown = True
        elif item['status'] == 'KNOWN':
            parsed = utc_time(item['retrieved_at']); require(parsed <= completed, 'SOURCE_ACQUISITION_AFTER_COMPLETION')
            times.append((parsed, item['retrieved_at']))
    return min(times, key=lambda item: item[0])[1] if times and not unknown else None


def validate_report_acquisition(report, *, require_known=False):
    require(isinstance(report, dict) and set(report) == REPORT_KEYS_V1 | {'calculation_cutoff'})
    require(type(report['schema_version']) is int and report['schema_version'] == 2
            and report['product_version'] == '2.1.2' and report['provider_scope'] == 'public_only'
            and report['owner_watchlist_inherited'] is False
            and report['display_columns'] == ['股票', '長期投資報酬率（近2年年化）', '短期投資報酬率（近6個月）', '行業別', '獲利簡述']
            and report['long_term_definition'] == 'trailing_2y_adjusted_close_cagr'
            and report['short_term_definition'] == 'trailing_6m_adjusted_close_price_return')
    require(utc_time(report['calculation_cutoff']) <= utc_time(report['generated_at']))
    rows = report['records']; require(isinstance(rows, list) and len(rows) == 20)
    seen = set()
    for rank, row in enumerate(rows, 1):
        require(isinstance(row, dict) and set(row) == ROW_KEYS_V1 | {'source_acquisition'})
        require(type(row['schema_version']) is int and row['schema_version'] == 2
                and type(row['rank']) is int and row['rank'] == rank
                and isinstance(row['ticker'], str) and bool(re.fullmatch(r'[A-Z0-9][A-Z0-9.-]{0,14}', row['ticker']))
                and row['ticker'] not in seen and row['provider_scope'] == 'public_only'
                and row['owner_watchlist_inherited'] is False
                and row['long_term_window'] == '2y_cagr' and row['short_term_window'] == '6m_price_return'
                and row['market_source'] == 'yfinance' and row['profit_source'] == 'sec_edgar')
        seen.add(row['ticker'])
        expected = row_time(row, generated_at=report['generated_at'])
        require(row['retrieved_at'] == expected)
        if require_known:
            require(expected is not None, 'SOURCE_ACQUISITION_UNKNOWN')
    return report
