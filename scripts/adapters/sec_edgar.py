#!/usr/bin/env python3
"""SEC EDGAR public JSON adapter with filing and XBRL fact normalization."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import quote

from .base import (
    AdapterError,
    ParsedBatch,
    build_evidence_item,
    json_document,
    make_batch,
    register_adapter,
    scalar,
)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _date_iso(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if not DATE_RE.fullmatch(text):
        raise AdapterError(f"Invalid SEC date: {text}")
    try:
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc).isoformat()
    except ValueError as exc:
        raise AdapterError(f"Invalid SEC date: {text}") from exc


def _cik(value: Any) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    if not digits or len(digits) > 10:
        raise AdapterError("SEC CIK is missing or invalid")
    return digits.zfill(10)


def _request_url(context: Mapping[str, Any]) -> str:
    value = str(context.get("request_url") or "").strip()
    if not value.startswith("https://"):
        raise AdapterError("SEC adapter requires an HTTPS request_url context")
    return value


def _filing_url(cik: str, accession: str, primary_document: str) -> str | None:
    clean_accession = accession.replace("-", "").strip()
    document = primary_document.strip().lstrip("/")
    if not clean_accession.isdigit() or not document:
        return None
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{int(cik)}/{clean_accession}/{quote(document, safe='._-/')}"
    )


def _parallel_rows(document: Mapping[str, Any], cik: str, request_url: str) -> list[dict[str, Any]]:
    filings = document.get("filings")
    recent = filings.get("recent") if isinstance(filings, dict) else None
    if not isinstance(recent, dict):
        raise AdapterError("SEC submissions payload lacks filings.recent")
    columns = {key: value for key, value in recent.items() if isinstance(value, list)}
    if not columns or "accessionNumber" not in columns or "form" not in columns:
        raise AdapterError("SEC submissions recent arrays lack required columns")
    lengths = {len(value) for value in columns.values()}
    if len(lengths) != 1:
        raise AdapterError("SEC submissions recent arrays have inconsistent lengths")
    row_count = lengths.pop()
    records: list[dict[str, Any]] = []
    for index in range(row_count):
        accession = str(columns.get("accessionNumber", [""] * row_count)[index] or "").strip()
        form = str(columns.get("form", [""] * row_count)[index] or "").strip()
        filing_date = _date_iso(columns.get("filingDate", [None] * row_count)[index])
        if not accession or not form or not filing_date:
            continue
        report_date = _date_iso(columns.get("reportDate", [None] * row_count)[index])
        acceptance = str(columns.get("acceptanceDateTime", [""] * row_count)[index] or "").strip()
        primary_document = str(columns.get("primaryDocument", [""] * row_count)[index] or "").strip()
        records.append(
            {
                "record_type": "submission_filing",
                "cik": cik,
                "entity_name": str(document.get("name") or "").strip(),
                "accession_number": accession,
                "form": form,
                "filing_date": filing_date,
                "report_date": report_date,
                "acceptance_datetime": acceptance or None,
                "act": str(columns.get("act", [""] * row_count)[index] or "").strip() or None,
                "file_number": str(columns.get("fileNumber", [""] * row_count)[index] or "").strip() or None,
                "film_number": str(columns.get("filmNumber", [""] * row_count)[index] or "").strip() or None,
                "items": str(columns.get("items", [""] * row_count)[index] or "").strip() or None,
                "size_bytes": int(columns.get("size", [0] * row_count)[index] or 0),
                "is_xbrl": bool(columns.get("isXBRL", [0] * row_count)[index]),
                "is_inline_xbrl": bool(columns.get("isInlineXBRL", [0] * row_count)[index]),
                "primary_document": primary_document or None,
                "primary_document_description": str(
                    columns.get("primaryDocDescription", [""] * row_count)[index] or ""
                ).strip()
                or None,
                "record_url": _filing_url(cik, accession, primary_document) or request_url,
                "source_request_url": request_url,
            }
        )
    if not records:
        raise AdapterError("SEC submissions payload contains no valid filing records")
    return records


def _companyfacts_rows(document: Mapping[str, Any], cik: str, request_url: str) -> list[dict[str, Any]]:
    facts = document.get("facts")
    if not isinstance(facts, dict):
        raise AdapterError("SEC companyfacts payload lacks facts")
    records: list[dict[str, Any]] = []
    for taxonomy, taxonomy_values in sorted(facts.items()):
        if not isinstance(taxonomy_values, dict):
            continue
        for tag, fact in sorted(taxonomy_values.items()):
            if not isinstance(fact, dict):
                continue
            units = fact.get("units")
            if not isinstance(units, dict):
                continue
            for unit, observations in sorted(units.items()):
                if not isinstance(observations, list):
                    continue
                for observation in observations:
                    if not isinstance(observation, dict):
                        continue
                    value = scalar(observation.get("val"), allow_none=False)
                    filed = _date_iso(observation.get("filed"))
                    end = _date_iso(observation.get("end"))
                    accession = str(observation.get("accn") or "").strip()
                    form = str(observation.get("form") or "").strip()
                    if not filed or not end or not accession or not form:
                        continue
                    records.append(
                        {
                            "record_type": "company_fact",
                            "cik": cik,
                            "entity_name": str(document.get("entityName") or "").strip(),
                            "taxonomy": str(taxonomy),
                            "tag": str(tag),
                            "label": str(fact.get("label") or "").strip() or None,
                            "description": str(fact.get("description") or "").strip() or None,
                            "unit": str(unit),
                            "value": value,
                            "start": _date_iso(observation.get("start")),
                            "end": end,
                            "filed": filed,
                            "fiscal_year": observation.get("fy"),
                            "fiscal_period": str(observation.get("fp") or "").strip() or None,
                            "form": form,
                            "accession_number": accession,
                            "frame": str(observation.get("frame") or "").strip() or None,
                            "record_url": request_url,
                            "source_request_url": request_url,
                        }
                    )
    if not records:
        raise AdapterError("SEC companyfacts payload contains no valid observations")
    return records


class SecEdgarAdapter:
    source_id = "sec_edgar"
    parser_version = "sec-edgar-json-v1"

    def parse(
        self,
        content: bytes,
        *,
        content_type: str,
        retrieved_at: str,
        context: Mapping[str, Any],
    ) -> ParsedBatch:
        if "json" not in content_type:
            raise AdapterError("SEC EDGAR adapter requires JSON content")
        document = json_document(content)
        if not isinstance(document, dict):
            raise AdapterError("SEC EDGAR payload must be a JSON object")
        cik = _cik(document.get("cik"))
        request_url = _request_url(context)
        if isinstance(document.get("filings"), dict):
            records = _parallel_rows(document, cik, request_url)
        elif isinstance(document.get("facts"), dict):
            records = _companyfacts_rows(document, cik, request_url)
        else:
            raise AdapterError("Unsupported SEC EDGAR JSON document type")
        return make_batch(
            source_id=self.source_id,
            parser_version=self.parser_version,
            content=content,
            retrieved_at=retrieved_at,
            records=records,
        )


def evidence_items(batch: ParsedBatch, *, registry_version: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in batch.records:
        if record["record_type"] == "submission_filing":
            fields = {
                "accession_number": record["accession_number"],
                "form": record["form"],
                "filing_date": record["filing_date"],
            }
            if record.get("report_date"):
                fields["report_date"] = record["report_date"]
            result.append(
                build_evidence_item(
                    batch,
                    record,
                    claim_id=f"sec:{record['cik']}:filing:{record['accession_number']}",
                    claim_type="issuer_filing",
                    canonical_url=str(record["record_url"]),
                    field_values=fields,
                    registry_version=registry_version,
                    published_at=str(record["filing_date"]),
                    as_of=str(record.get("report_date") or record["filing_date"]),
                    revision_or_vintage=str(record["accession_number"]),
                )
            )
        elif record["record_type"] == "company_fact":
            result.append(
                build_evidence_item(
                    batch,
                    record,
                    claim_id=(
                        "sec:"
                        f"{record['cik']}:xbrl:{record['taxonomy']}:{record['tag']}:"
                        f"{record['unit']}:{record['end']}:{record['accession_number']}"
                    ),
                    claim_type="xbrl_fact",
                    canonical_url=str(record["record_url"]),
                    field_values={
                        "taxonomy": record["taxonomy"],
                        "tag": record["tag"],
                        "unit": record["unit"],
                        "value": record["value"],
                        "period_end": record["end"],
                        "form": record["form"],
                    },
                    registry_version=registry_version,
                    published_at=str(record["filed"]),
                    as_of=str(record["end"]),
                    revision_or_vintage=str(record["accession_number"]),
                )
            )
    return result


register_adapter(SecEdgarAdapter())
