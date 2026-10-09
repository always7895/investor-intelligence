"""Shared TAIFEX daily identity rules; no network, eligibility or expiry inference."""
from datetime import date
from decimal import Decimal
import json
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


# --- Dataset 11321 (DailyOptionsDelta): LOCAL_REFERENCE_ONLY contract/Delta reference rows --------------------------------------
# Never a quote and never joined into the daily EOD rows (dataset 11320; daily_identity above is unchanged). The OpenAPI document
# advertises six string fields and NO as-of date, session, currency, multiplier, underlying, unit or sign convention; the response
# envelope and the value formats are NOT observed. Everything below is a conservative IMPLEMENTATION constraint (compatibility with the
# real response is UNVERIFIED): an unsupported row refuses the whole batch; nothing is coerced, defaulted, scaled or inferred.
TAIFEX_DELTA_URL = 'https://openapi.taifex.com.tw/v1/DailyOptionsDelta'
TAIFEX_DELTA_SCHEMA = 'v213-taifex-delta-reference-v1'
TAIFEX_DELTA_FIELDS = frozenset({'Contract', 'CallPut', 'ContractMonth(Week)', 'StrikePrice', 'Delta', 'ContractSettlementDay'})
TAIFEX_DELTA_ATTRIBUTION = {
    'provider': '\u81fa\u7063\u671f\u8ca8\u4ea4\u6613\u6240', 'dataset': '\u9078\u64c7\u6b0a\u6bcf\u65e5Delta\u503c',
    'dataset_url': 'https://data.gov.tw/dataset/11321', 'dataset_version': None,
    'license': '\u653f\u5e9c\u8cc7\u6599\u958b\u653e\u6388\u6b0a\u689d\u6b3e-\u7b2c1\u7248', 'license_url': 'https://data.gov.tw/license',
    'notice': '\u4f9d\u539f\u59cb\u958b\u653e\u8cc7\u6599\u518d\u88fd\uff1b\u672a\u7372\u8cc7\u6599\u63d0\u4f9b\u6a5f\u95dc\u80cc\u66f8\u3002',
}
# Shared once per output envelope (collector health row / importer result), never repeated per row.
TAIFEX_DELTA_ENVELOPE = {
    'schema': TAIFEX_DELTA_SCHEMA, 'dataset': '11321', 'source_url': TAIFEX_DELTA_URL, 'reference_scope': 'LOCAL_REFERENCE_ONLY',
    'reference_time_status': 'UNALIGNED_NO_PROVIDER_ASOF', 'provider_asof': None, 'quote_asof': None, 'trading_session': None,
    'delta_unit_convention': 'UNDOCUMENTED', 'shape_compatibility': 'UNVERIFIED_AGAINST_REAL_RESPONSE',
    'fields_not_provided': ['currency', 'contract_multiplier', 'underlying', 'instrument_class', 'expiration_instant', 'actual_dte',
                            'cash_settlement_convention', 'quote_time', 'executable_midpoint'],
    'attribution': TAIFEX_DELTA_ATTRIBUTION,
}
TAIFEX_DELTA_MAX_BYTES = 8_000_000  # raw input; both actual callers acquire at most this many bytes + 1 and refuse overflow before any decode
# Limit for an output that RETAINS Delta rows, as that caller actually serializes it (each caller measures its OWN serializer, after its bounded
# in-memory build and before it returns, writes or prints). It is not a cap before every append and not a universal cap on other sources.
TAIFEX_DELTA_MAX_OUTPUT_BYTES = 16_000_000
TAIFEX_DELTA_MAX_DEPTH = 2  # an array of flat objects: array = 1, row object = 2
REFERENCE_MAX_ROWS = 20000
REFERENCE_MAX_FIELD = 64
_REFERENCE_ORIGINS = frozenset({'COLLECTOR_CAPTURE_UNQUALIFIED', 'UNVERIFIED_LOCAL_FILE'})
_DELTA_RIGHT = {'\u8cb7\u6b0a': 'call', '\u8ce3\u6b0a': 'put', 'Call': 'call', 'Put': 'put'}  # vocabulary of the daily rows: UNVERIFIED for 11321
_STRIKE_TEXT = re.compile(r'[0-9]+(?:\.[0-9]+)?')
_DELTA_TEXT = re.compile(r'-?[0-9]+(?:\.[0-9]+)?')
_DAY_COMPACT = re.compile(r'[0-9]{8}')
_DAY_ISO = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')
_DELTA_CODE = re.compile(r'TAIFEX_DELTA_[A-Z_]+')
# Structural pre-scan token: separators, a COMPLETE JSON string (quote/escape aware, so a bracket inside a string is never structure), one
# bracket, or any other atom. It is applied with match() at an advancing position: the first position no alternative can take (an
# unterminated string) refuses immediately instead of being retried from the next character.
_DELTA_TOKEN = re.compile(r'[ \t\r\n,:]+|"[^"\\]*(?:\\.[^"\\]*)*"|[\[\]{}]|[^\s"\[\]{},:]+')
_DELTA_RAW_STRING_MAX = 6 * REFERENCE_MAX_FIELD + 2  # 64 characters at the longest JSON escape (\uXXXX) plus the quotes


def _delta_unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('TAIFEX_DELTA_DUPLICATE_JSON_FIELD')
        result[key] = value
    return result


def _delta_refuse_constant(_value: str) -> None:
    raise ValueError('TAIFEX_DELTA_INVALID_CONSTANT')


def _delta_refuse_number(_value: str) -> None:
    # Every advertised field is a string: a JSON number anywhere is an unsupported shape (and never reaches int()/float()).
    raise ValueError('TAIFEX_DELTA_INVALID_FIELD_TYPE')


def delta_reference_rows(content: bytes) -> list[Any]:
    """Bounded decoder of the RAW bytes of a dataset-11321 response, for the two actual Delta callers only (collector adapter and manual
    importer); it never touches the shared adapter base or the EOD parser. Fixed TAIFEX_DELTA_* codes only, no raw values:
    non-empty bytes <= TAIFEX_DELTA_MAX_BYTES; strict UTF-8 (a leading BOM is tolerated); a quote-aware structural pre-scan refuses nesting
    deeper than TAIFEX_DELTA_MAX_DEPTH, more than REFERENCE_MAX_ROWS + 1 containers, more than a GLOBAL budget of 12 * REFERENCE_MAX_ROWS scalars
    (a coarse bound, not a per-row pre-check; the closed six-key rows and 64-character fields are enforced afterwards by delta_reference_records)
    and any over-long string BEFORE the document is materialized, so json.loads can neither recurse deeply nor build an unbounded tree; then duplicate keys,
    NaN/Infinity and every JSON number are refused. The shape of the decoded value is checked by delta_reference_records."""
    if not isinstance(content, bytes) or not 1 <= len(content) <= TAIFEX_DELTA_MAX_BYTES:
        raise ValueError('TAIFEX_DELTA_INVALID_PAYLOAD_SIZE')
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('TAIFEX_DELTA_INVALID_ENCODING') from None
    position, depth, containers, scalars = 0, 0, 0, 0
    while position < len(text):
        delta_match = _DELTA_TOKEN.match(text, position)
        if delta_match is None:
            raise ValueError('TAIFEX_DELTA_INVALID_JSON')
        piece, position = delta_match.group(), delta_match.end()
        first = piece[0]
        if first in '[{':
            depth += 1
            containers += 1
            if depth > TAIFEX_DELTA_MAX_DEPTH:
                raise ValueError('TAIFEX_DELTA_TOO_DEEP')
            if containers > REFERENCE_MAX_ROWS + 1:
                raise ValueError('TAIFEX_DELTA_INVALID_ROWS')
        elif first in ']}':
            depth -= 1
            if depth < 0:
                raise ValueError('TAIFEX_DELTA_INVALID_JSON')
        elif first not in ' \t\r\n,:':
            scalars += 1
            if scalars > 12 * REFERENCE_MAX_ROWS:
                raise ValueError('TAIFEX_DELTA_INVALID_ROWS')
            if first == '"' and len(piece) > _DELTA_RAW_STRING_MAX:
                raise ValueError('TAIFEX_DELTA_INVALID_FIELD_TYPE')
    try:
        return json.loads(text, object_pairs_hook=_delta_unique_object, parse_constant=_delta_refuse_constant,
                          parse_int=_delta_refuse_number, parse_float=_delta_refuse_number)
    except RecursionError:
        raise ValueError('TAIFEX_DELTA_TOO_DEEP') from None
    except ValueError as exc:
        code = str(exc)
        raise ValueError(code if _DELTA_CODE.fullmatch(code) else 'TAIFEX_DELTA_INVALID_JSON') from None


def _reported_day(text: str) -> tuple[str | None, str]:
    """A date-only REPORTED reference day: not an expiry instant, not a cash-settlement convention, not a DTE. '' is EMPTY; any other
    text that is not a real YYYYMMDD or YYYY-MM-DD calendar date refuses the batch."""
    if text == '':
        return None, 'EMPTY'
    if _DAY_COMPACT.fullmatch(text):
        year, month, day = int(text[:4]), int(text[4:6]), int(text[6:])
    elif _DAY_ISO.fullmatch(text):
        year, month, day = int(text[:4]), int(text[5:7]), int(text[8:])
    else:
        raise ValueError('TAIFEX_DELTA_INVALID_DAY')
    try:
        return date(year, month, day).isoformat(), 'REPORTED_REFERENCE_DAY_FORMAT_UNVERIFIED'
    except ValueError:
        raise ValueError('TAIFEX_DELTA_INVALID_DAY') from None


def delta_reference_records(rows: Any, *, origin_verification: str) -> list[dict[str, Any]]:
    """Closed-schema, all-or-nothing local reference rows from a list of dataset-11321-shaped rows (shared by the staged adapter and the
    manual importer, so there is ONE parser). The raw strike, Delta and day text are kept verbatim next to a lexical status; Delta is
    never turned into a number and its unit and sign convention stay UNDOCUMENTED. Duplicate (contract, month/week, strike value, right)
    refuses the batch (no last-row-wins); strike identity is exact Decimal equality, never a float. Fixed error codes only. The records-only
    serialized size of the in-memory result is checked here as a first guard; each caller checks the FINAL size of what it returns, writes or
    prints (wrapper, indent, escaping, newline) after this call and before emitting it."""
    if origin_verification not in _REFERENCE_ORIGINS:
        raise ValueError('TAIFEX_DELTA_INVALID_ORIGIN_LABEL')
    if not isinstance(rows, list) or not 1 <= len(rows) <= REFERENCE_MAX_ROWS:
        raise ValueError('TAIFEX_DELTA_INVALID_ROWS')
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, Decimal, str]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != TAIFEX_DELTA_FIELDS:
            raise ValueError('TAIFEX_DELTA_SCHEMA_CHANGED')
        if any(not isinstance(value, str) or len(value) > REFERENCE_MAX_FIELD for value in row.values()):
            raise ValueError('TAIFEX_DELTA_INVALID_FIELD_TYPE')
        contract, series, strike_text = row['Contract'], row['ContractMonth(Week)'], row['StrikePrice']
        right = _DELTA_RIGHT.get(row['CallPut'])
        if (not re.fullmatch(r'[A-Z0-9]{1,12}', contract) or not re.fullmatch(r'[0-9]{6}(?:[WF][1-5])?', series) or right is None
                or not _STRIKE_TEXT.fullmatch(strike_text)):
            raise ValueError('TAIFEX_DELTA_INVALID_CONTRACT')
        try:
            date(int(series[:4]), int(series[4:6]), 1)  # calendar-month validity only, never an expiry day
        except ValueError:
            raise ValueError('TAIFEX_DELTA_INVALID_CONTRACT') from None
        strike = Decimal(strike_text)
        if strike <= 0:
            raise ValueError('TAIFEX_DELTA_INVALID_STRIKE')
        identity = (contract, series, strike, right)
        if identity in seen:
            raise ValueError('TAIFEX_DELTA_DUPLICATE_CONTRACT')
        seen.add(identity)
        delta_text = row['Delta']
        if delta_text == '':
            lexical = 'EMPTY'
        elif _DELTA_TEXT.fullmatch(delta_text):
            lexical = 'LEXICAL_DECIMAL_UNIT_SIGN_UNDOCUMENTED'
        else:
            raise ValueError('TAIFEX_DELTA_INVALID_DELTA')
        reported_day, day_status = _reported_day(row['ContractSettlementDay'])
        records.append({
            'record_type': 'taifex_option_reference', 'source_row_index': index, 'reference_scope': 'LOCAL_REFERENCE_ONLY',
            'reference_time_status': 'UNALIGNED_NO_PROVIDER_ASOF', 'contract': contract, 'contract_month_week': series,
            'option_type': right, 'strike_text': strike_text, 'delta_text': delta_text, 'delta_lexical_status': lexical,
            'contract_settlement_day_text': row['ContractSettlementDay'], 'reported_contract_day': reported_day,
            'contract_day_status': day_status, 'origin_verification': origin_verification,
            'publication_eligible': False, 'line_quote_eligible': False, 'executable_quote': False,
        })
    if len(json.dumps(records, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')) > TAIFEX_DELTA_MAX_OUTPUT_BYTES:
        raise ValueError('TAIFEX_DELTA_OUTPUT_TOO_LARGE')
    return records
