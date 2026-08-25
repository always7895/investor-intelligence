#!/usr/bin/env python3
"""Reusable strict SDMX-CSV parsing helpers for reviewed official sources.

This module intentionally does not register itself as a runtime adapter. A
source-specific wrapper must enforce the reviewed host/path and then register a
static source ID. That prevents a generic parser from becoming an automatic
activation mechanism for newly discovered URLs.
"""
from __future__ import annotations

import csv
import io
import math
import re
from datetime import datetime, timezone
from typing import Any

from .base import AdapterError, ParsedBatch, build_evidence_item, sha256_bytes

OBSERVATION_COLUMNS = {
    "TIME_PERIOD",
    "OBS_VALUE",
    "OBS_STATUS",
    "OBS_CONF",
    "OBS_PRE_BREAK",
}
ATTRIBUTE_COLUMNS = {
    "DECIMALS",
    "UNIT",
    "UNIT_MULT",
    "TITLE",
    "TITLE_COMPL",
    "SOURCE_AGENCY",
    "SOURCE_PUB",
    "SOURCE_PUB_DATE",
    "COMMENT_OBS",
}
PERIOD_YEAR = re.compile(r"^(\d{4})$")
PERIOD_QUARTER = re.compile(r"^(\d{4})-Q([1-4])$")
PERIOD_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
PERIOD_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def numeric(value: str) -> int | float:
    text = value.strip()
    try:
        parsed = float(text)
    except ValueError as exc:
        raise AdapterError(f"SDMX OBS_VALUE is not numeric: {text!r}") from exc
    if not math.isfinite(parsed):
        raise AdapterError("SDMX OBS_VALUE must be finite")
    if parsed.is_integer() and not any(marker in text.casefold() for marker in (".", "e")):
        return int(parsed)
    return parsed


def period_as_of(value: str) -> str | None:
    text = value.strip()
    match = PERIOD_YEAR.fullmatch(text)
    if match:
        return f"{match.group(1)}-12-31T00:00:00+00:00"
    match = PERIOD_QUARTER.fullmatch(text)
    if match:
        year = int(match.group(1))
        quarter = int(match.group(2))
        month = quarter * 3
        if month in (3, 12):
            day = 31
        elif month in (6, 9):
            day = 30
        else:  # pragma: no cover - quarter mapping is exhaustive
            day = 28
        return f"{year:04d}-{month:02d}-{day:02d}T00:00:00+00:00"
    match = PERIOD_MONTH.fullmatch(text)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        if month == 12:
            next_month = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            next_month = datetime(year, month + 1, 1, tzinfo=timezone.utc)
        end = next_month.fromtimestamp(next_month.timestamp() - 86400, tz=timezone.utc)
        return end.isoformat()
    if PERIOD_DATE.fullmatch(text):
        try:
            return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc).isoformat()
        except ValueError as exc:
            raise AdapterError(f"Invalid SDMX date period: {text}") from exc
    return None


def series_key(row: dict[str, str], fieldnames: list[str]) -> str:
    preferred = row.get("KEY") or row.get("SERIES_KEY")
    if preferred:
        return preferred
    parts = [
        f"{field}={row[field]}"
        for field in fieldnames
        if field not in OBSERVATION_COLUMNS
        and field not in ATTRIBUTE_COLUMNS
        and field not in {"DATAFLOW"}
        and row.get(field)
    ]
    return ".".join(parts)


def parse_records(
    content: bytes,
    *,
    content_type: str,
    request_url: str,
    dataflow: str | None = None,
    maximum_records: int = 250_000,
) -> tuple[list[dict[str, Any]], list[str]]:
    if "csv" not in content_type.casefold() and "text/plain" not in content_type.casefold():
        raise AdapterError("SDMX adapter requires CSV content")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AdapterError("SDMX CSV must be UTF-8") from exc
    if "\x00" in text:
        raise AdapterError("SDMX CSV contains a NUL byte")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise AdapterError("SDMX CSV lacks a header")
    normalized_names = [str(value).strip().upper() for value in reader.fieldnames]
    if len(normalized_names) != len(set(normalized_names)):
        raise AdapterError("SDMX CSV has duplicate normalized column names")
    if "TIME_PERIOD" not in normalized_names or "OBS_VALUE" not in normalized_names:
        raise AdapterError("SDMX CSV lacks TIME_PERIOD or OBS_VALUE")

    records: list[dict[str, Any]] = []
    warnings: set[str] = set()
    for row_number, original in enumerate(reader, start=2):
        if row_number > maximum_records + 1:
            raise AdapterError(f"SDMX CSV exceeds {maximum_records} records")
        row = {
            str(key).strip().upper(): str(value or "").strip()
            for key, value in original.items()
            if key is not None
        }
        period = row.get("TIME_PERIOD", "")
        raw_value = row.get("OBS_VALUE", "")
        if not period or not raw_value:
            continue
        key = series_key(row, normalized_names)
        if not key:
            warnings.add("ROW_WITHOUT_SERIES_KEY_SKIPPED")
            continue
        as_of = period_as_of(period)
        if as_of is None:
            warnings.add("UNPARSED_TIME_PERIOD_REQUIRES_REVIEW")
        dimensions = {
            field: row[field]
            for field in normalized_names
            if field not in OBSERVATION_COLUMNS
            and field not in ATTRIBUTE_COLUMNS
            and field not in {"KEY", "SERIES_KEY", "DATAFLOW"}
            and row.get(field)
        }
        records.append(
            {
                "record_type": "official_indicator_value",
                "dataflow": dataflow or row.get("DATAFLOW") or None,
                "series_key": key,
                "frequency": row.get("FREQ") or None,
                "time_period": period,
                "period_as_of": as_of,
                "observation_value": numeric(raw_value),
                "observation_status": row.get("OBS_STATUS") or None,
                "observation_confidentiality": row.get("OBS_CONF") or None,
                "unit": row.get("UNIT") or None,
                "unit_multiplier": row.get("UNIT_MULT") or None,
                "decimals": row.get("DECIMALS") or None,
                "source_agency": row.get("SOURCE_AGENCY") or None,
                "dimensions": dimensions,
                "record_url": request_url,
            }
        )
    if not records:
        raise AdapterError("SDMX CSV contains no valid observations")
    return records, sorted(warnings)


def evidence_items(
    batch: ParsedBatch,
    *,
    registry_version: str,
    claim_prefix: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in batch.records:
        as_of = record.get("period_as_of")
        if not as_of:
            continue
        series_hash = sha256_bytes(str(record["series_key"]).encode("utf-8"))[:20]
        fields: dict[str, Any] = {
            "series_key": record["series_key"],
            "time_period": record["time_period"],
            "observation_value": record["observation_value"],
        }
        if record.get("dataflow"):
            fields["dataflow"] = record["dataflow"]
        if record.get("unit"):
            fields["unit"] = record["unit"]
        result.append(
            build_evidence_item(
                batch,
                record,
                claim_id=(
                    f"{claim_prefix}:{record.get('dataflow') or 'unknown'}:"
                    f"{series_hash}:{record['time_period']}"
                ),
                claim_type="official_indicator_value",
                canonical_url=str(record["record_url"]),
                field_values=fields,
                registry_version=registry_version,
                as_of=str(as_of),
                revision_or_vintage=batch.retrieved_at,
            )
        )
    return result
