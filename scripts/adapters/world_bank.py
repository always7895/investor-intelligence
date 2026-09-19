#!/usr/bin/env python3
"""World Bank Indicators API V2 adapter."""
from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Mapping

from .base import (
    AdapterError,
    ParsedBatch,
    build_evidence_item,
    json_document,
    make_batch,
    register_adapter,
    scalar,
)

YEAR_RE = re.compile(r"^\d{4}$")


def _request_url(context: Mapping[str, Any]) -> str:
    value = str(context.get("request_url") or "").strip()
    if not value.startswith("https://"):
        raise AdapterError("World Bank adapter requires an HTTPS request_url")
    return value


def _period_as_of(value: str) -> str | None:
    if YEAR_RE.fullmatch(value):
        return f"{value}-12-31T00:00:00+00:00"
    return None


US_REAL_GDP_URL = 'https://api.worldbank.org/v2/country/USA/indicator/NY.GDP.MKTP.KD.ZG?format=json&per_page=5'
US_REAL_GDP_METADATA_URL = 'https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG?locations=US'


def select_us_real_gdp_window(document, *, as_of_day: str) -> dict[str, Any]:
    """Closed first-page WDI contract, not whole-history or current-quarter proof.

    The general replay adapter below remains a separate compatibility interface.
    Null observations remain visible; malformed newer rows never rescue older data.
    """
    def require(ok):
        if not ok:
            raise AdapterError('WORLD_BANK_US_GDP_WINDOW_INVALID')
    def day(value):
        require(isinstance(value, str) and bool(re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value)))
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise AdapterError('WORLD_BANK_US_GDP_WINDOW_INVALID') from None
    today = day(as_of_day)
    require(isinstance(document, list) and len(document) == 2)
    metadata, rows = document
    require(isinstance(metadata, dict) and set(metadata) == {'page', 'pages', 'per_page', 'total', 'sourceid', 'lastupdated'})
    require(all(type(metadata[k]) is int for k in ('page', 'pages', 'per_page', 'total'))
            and metadata['page'] == 1 and metadata['per_page'] == 5
            and 1 <= metadata['total'] <= 1000 and metadata['pages'] == (metadata['total'] + 4) // 5
            and metadata['sourceid'] == '2')
    require(day(metadata['lastupdated']) <= today)
    require(isinstance(rows, list) and len(rows) == min(5, metadata['total']))
    observations = []
    for row in rows:
        require(isinstance(row, dict) and set(row) == {'indicator', 'country', 'countryiso3code', 'date', 'value', 'unit', 'obs_status', 'decimal'})
        require(row['indicator'] == {'id': 'NY.GDP.MKTP.KD.ZG', 'value': 'GDP growth (annual %)'}
                and row['country'] == {'id': 'US', 'value': 'United States'} and row['countryiso3code'] == 'USA'
                and row['unit'] == '' and row['obs_status'] == '' and type(row['decimal']) is int and 0 <= row['decimal'] <= 15)
        year = row['date']; value = row['value']
        require(isinstance(year, str) and bool(re.fullmatch(r'[0-9]{4}', year)) and 1900 <= int(year) <= today.year)
        require(value is None or type(value) in (int, float) and -100 <= value <= 9007199254740991 and math.isfinite(value))
        # A non-null full-year figure cannot precede its measurement end.
        require(value is None or date(int(year), 12, 31) <= day(metadata['lastupdated']))
        observations.append({'period': year, 'value': value, 'status': 'UNAVAILABLE' if value is None else 'OBSERVED',
                             'provider_decimal': row['decimal']})
    observations.sort(key=lambda v: v['period'], reverse=True)
    years = [int(v['period']) for v in observations]
    require(years == list(range(years[0], years[0] - len(years), -1)))
    available = [v for v in observations if v['value'] is not None]
    latest = available[0] if available else None
    return {'country_iso3': 'USA', 'indicator_id': 'NY.GDP.MKTP.KD.ZG',
            'unit': 'annual_percent_growth_constant_local_currency',
            'period': latest['period'] if latest else None, 'value': latest['value'] if latest else None,
            'dataset_last_updated': metadata['lastupdated'], 'observations': observations,
            'window': {'page': 1, 'pages': metadata['pages'], 'per_page': 5, 'total': metadata['total'],
                       'latest_returned_period': observations[0]['period'], 'selection': 'LATEST_NON_NULL_IN_RETURNED_FIRST_PAGE',
                       'full_history_verified': False, 'latest_release_verified': False},
            'attribution': {'text': 'The World Bank: World Development Indicators: Country official statistics (national statistical organizations and/or central banks); OECD National Accounts data files; World Bank staff estimates.',
                            'metadata_url': US_REAL_GDP_METADATA_URL,
                            'license_url': 'https://creativecommons.org/licenses/by/4.0/',
                            'terms_url': 'https://www.worldbank.org/ext/en/legal/terms-conditions/datasets',
                            'modifications': 'Selected and ordered the returned window; no value adjustment.',
                            'notice': 'CC BY 4.0 with World Bank additional terms; no endorsement or data warranty.'}}


class WorldBankIndicatorsAdapter:
    source_id = "world_bank_indicators"
    parser_version = "world-bank-indicators-v2-json-v1"

    def parse(
        self,
        content: bytes,
        *,
        content_type: str,
        retrieved_at: str,
        context: Mapping[str, Any],
    ) -> ParsedBatch:
        if "json" not in content_type:
            raise AdapterError("World Bank adapter requires JSON content")
        document = json_document(content)
        if not isinstance(document, list) or len(document) < 2:
            raise AdapterError("World Bank V2 payload must contain metadata and records")
        metadata, observations = document[0], document[1]
        if not isinstance(metadata, dict) or not isinstance(observations, list):
            raise AdapterError("World Bank V2 response structure is invalid")
        request_url = _request_url(context)
        records: list[dict[str, Any]] = []
        for observation in observations:
            if not isinstance(observation, dict):
                continue
            value = observation.get("value")
            if value is None:
                continue
            value = scalar(value, allow_none=False)
            country = observation.get("country")
            indicator = observation.get("indicator")
            if not isinstance(country, dict) or not isinstance(indicator, dict):
                continue
            country_id = str(country.get("id") or observation.get("countryiso3code") or "").strip()
            indicator_id = str(indicator.get("id") or "").strip()
            period = str(observation.get("date") or "").strip()
            if not country_id or not indicator_id or not period:
                continue
            records.append(
                {
                    "record_type": "official_indicator_value",
                    "country_id": country_id,
                    "country_iso3": str(observation.get("countryiso3code") or "").strip() or None,
                    "country_name": str(country.get("value") or "").strip() or None,
                    "indicator_id": indicator_id,
                    "indicator_name": str(indicator.get("value") or "").strip() or None,
                    "period": period,
                    "period_as_of": _period_as_of(period),
                    "value": value,
                    "unit": str(observation.get("unit") or "").strip() or None,
                    "observation_status": str(observation.get("obs_status") or "").strip() or None,
                    "decimal": observation.get("decimal"),
                    "source_id": str(observation.get("source", {}).get("id") or "").strip()
                    if isinstance(observation.get("source"), dict)
                    else None,
                    "source_note": str(observation.get("sourceNote") or "").strip() or None,
                    "record_url": request_url,
                    "api_page": int(metadata.get("page") or 1),
                    "api_pages": int(metadata.get("pages") or 1),
                    "api_total": int(metadata.get("total") or len(observations)),
                    "api_last_updated": str(metadata.get("lastupdated") or "").strip() or None,
                }
            )
        if not records:
            raise AdapterError("World Bank payload contains no non-null observations")
        warnings: list[str] = []
        pages = int(metadata.get("pages") or 1)
        page = int(metadata.get("page") or 1)
        if page < pages:
            warnings.append("PAGINATION_INCOMPLETE")
        return make_batch(
            source_id=self.source_id,
            parser_version=self.parser_version,
            content=content,
            retrieved_at=retrieved_at,
            records=records,
            warnings=warnings,
        )


def evidence_items(batch: ParsedBatch, *, registry_version: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in batch.records:
        as_of = record.get("period_as_of")
        revision_or_vintage = record.get("api_last_updated")
        result.append(
            build_evidence_item(
                batch,
                record,
                claim_id=(
                    "world_bank:"
                    f"{record['indicator_id']}:{record['country_id']}:{record['period']}"
                ),
                claim_type="official_indicator_value",
                canonical_url=str(record["record_url"]),
                field_values={
                    "indicator_id": record["indicator_id"],
                    "country_id": record["country_id"],
                    "period": record["period"],
                    "value": record["value"],
                },
                registry_version=registry_version,
                as_of=as_of,
                revision_or_vintage=revision_or_vintage,
            )
        )
    return result


register_adapter(WorldBankIndicatorsAdapter())
