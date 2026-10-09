"""Exchange-wide issuer discovery, not scored research or quote admission.

Only dataset-specific government open-data endpoints are admitted. Personal
contact/management fields in upstream company profiles are never projected.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

from .base import AdapterError, ParsedBatch, json_document, make_batch, utc_iso

ISSUER_FEEDS = {
    'twse_issuer_directory': 'https://openapi.twse.com.tw/v1/opendata/t187ap03_L',
    'tpex_issuer_directory': 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O',
}
DATASETS = {'twse_issuer_directory': '18419', 'tpex_issuer_directory': '25036'}


class IssuerDirectoryAdapter:
    parser_version = 'public-issuer-discovery-v1'

    def __init__(self, source_id: str):
        if source_id not in ISSUER_FEEDS:
            raise AdapterError('UNKNOWN_ISSUER_SOURCE')
        self.source_id = source_id

    def parse(self, content: bytes, *, content_type: str, retrieved_at: str,
              context: Mapping[str, Any]) -> ParsedBatch:
        raw = json_document(content)
        if not isinstance(raw, list) or not 1 <= len(raw) <= 20000:
            raise AdapterError('INVALID_ISSUER_DIRECTORY')
        local_day = datetime.fromisoformat(utc_iso(retrieved_at)).astimezone(
            timezone(timedelta(hours=8))).date()
        twse = self.source_id == 'twse_issuer_directory'
        venue = 'TWSE' if twse else 'TPEX'
        fields = ('出表日期', '公司代號', '公司名稱', '產業別') if twse else (
            'Date', 'SecuritiesCompanyCode', 'CompanyName', 'SecuritiesIndustryCode')
        records, seen, dates = [], set(), set()
        for row in raw:
            if not isinstance(row, dict):
                raise AdapterError('INVALID_ISSUER_ROW')
            stamp, code, name, industry = (row.get(k) for k in fields)
            if not all(isinstance(v, str) for v in (stamp, code, name, industry)):
                raise AdapterError('INVALID_ISSUER_FIELDS')
            if not re.fullmatch(r'[0-9]{7}', stamp):
                raise AdapterError('INVALID_ISSUER_DATE')
            try:
                observed = date(int(stamp[:3]) + 1911, int(stamp[3:5]), int(stamp[5:]))
            except ValueError:
                raise AdapterError('INVALID_ISSUER_DATE') from None
            age = (local_day - observed).days
            if not 0 <= age <= 4:
                raise AdapterError('STALE_OR_FUTURE_ISSUER_DIRECTORY')
            # No symbol seed, thematic reserve, price or sector-score filter.
            if not re.fullmatch(r'[A-Z0-9]{4,12}', code) or code in seen:
                raise AdapterError('INVALID_OR_DUPLICATE_ISSUER')
            if not name.strip() or len(name) > 250 or any(ord(c) < 32 for c in name):
                raise AdapterError('INVALID_ISSUER_NAME')
            if not re.fullmatch(r'[0-9]{1,3}', industry):
                raise AdapterError('INVALID_ISSUER_INDUSTRY')
            seen.add(code)
            dates.add(observed)
            records.append({
                'record_type': 'listed_issuer_candidate', 'venue': venue,
                'security_code': code, 'company_name': name.strip(),
                'industry_code': industry, 'industry_code_namespace': venue,
                'directory_as_of': observed.isoformat(), 'age_calendar_days': age,
                'source_id': self.source_id, 'source_url': ISSUER_FEEDS[self.source_id],
                'dataset_url': 'https://data.gov.tw/dataset/' + DATASETS[self.source_id],
                'license_url': 'https://data.gov.tw/license',
                'attribution': (f'金融監督管理委員會證券期貨局／{venue} {observed.year} '
                                + ('上市公司基本資料' if twse else '上櫃公司基本資料')
                                + '; Open Government Data License v1; https://data.gov.tw/license'),
                'reconciliation_state': 'PRIMARY_ONLY',
                'research_stage': 'DISCOVERED_EVIDENCE_AND_SCORING_PENDING',
                'publication_eligible': False, 'owner_watchlist_inherited': False,
            })
        if len(dates) != 1:
            raise AdapterError('MIXED_ISSUER_DIRECTORY_DATES')
        records.sort(key=lambda row: row['security_code'])
        return make_batch(source_id=self.source_id, parser_version=self.parser_version,
                          content=content, retrieved_at=retrieved_at, records=records)


ISSUER_ADAPTERS = {key: IssuerDirectoryAdapter(key) for key in ISSUER_FEEDS}
