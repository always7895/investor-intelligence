#!/usr/bin/env python3
"""SEC EDGAR public JSON adapter with filing and XBRL fact normalization."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import quote, urlsplit

from .base import (
    AdapterError,
    FetchReceipt,
    ParsedBatch,
    build_evidence_item,
    canonical_json,
    json_document,
    make_batch,
    mint_fetch_receipt,
    register_adapter,
    scalar,
    sha256_bytes,
    validate_fetch_receipt,
)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CIK_PATH_RE = re.compile(r"/CIK(\d{10})\.json$")
SEC_HOST = "data.sec.gov"
SEC_SUBMISSIONS_PATH_RE = re.compile(r"^/submissions/CIK\d{10}\.json$")
SEC_COMPANYFACTS_PATH_RE = re.compile(r"^/api/xbrl/companyfacts/CIK\d{10}\.json$")

# Canonical registry source for SEC EDGAR (single existing entry; the adapter
# registers as sec_edgar and the registry adapter.id aligns to it).
SEC_REGISTRY_SOURCE_ID = "us_sec_edgar"


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


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


def _clock_bound(value: str | None, *, label: str, latest: datetime | None = None) -> dict[str, Any]:
    """Date-precision clocks carry explicit earliest/latest UTC-day bounds;
    the legacy parser's midnight output is DATE PRECISION, not an actual
    instant. Timestamp-precision clocks carry an exact instant."""
    if not value:
        raise AdapterError(f"clock {label} is missing")
    text = str(value)
    if text.endswith("T00:00:00+00:00") and DATE_RE.fullmatch(text.split("T")[0]):
        text = text.split("T")[0]
    if DATE_RE.fullmatch(text):
        day = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        earliest = day
        day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
        if latest is not None:
            day_end = min(day_end, latest)
        return {
            "label": label,
            "precision": "date_precision",
            "earliest": earliest.isoformat(),
            "latest": day_end.isoformat(),
        }
    exact = _parse_utc(text)
    if exact.tzinfo is None:
        raise AdapterError(f"clock {label} must be UTC")
    return {
        "label": label,
        "precision": "timestamp",
        "earliest": exact.isoformat(),
        "latest": exact.isoformat(),
    }


def _require_clock_order(event_bound: dict[str, Any], retrieved_at: str) -> None:
    """Event day must not be after the verified retrieval day; future clocks
    are rejected. Retrieval is never substituted for the event clock."""
    retrieved = _parse_utc(retrieved_at)
    event_day = _parse_utc(event_bound["earliest"]).date()
    if event_day > retrieved.date():
        raise AdapterError(f"clock {event_bound['label']} is after the verified retrieval")


@dataclass(frozen=True)
class SecClaimBinding:
    """Frozen in-process binding proof for one SEC-bound projection.

    Binds claim kind, canonical source, projected record digest, clocks,
    subject, unit and provenance to the minted receipt. The qualifier
    verifies the proof/digests so callers cannot replace CIK/period/filing/
    as_of/HTTP/hash/subject after projection. In-process integrity only; not
    cryptographic claim proof.
    """

    claim_kind: str
    source_id: str
    canonical_url: str
    expected_cik: str
    expected_period: str | None
    resolved_symbol: str | None
    projected_records: tuple[Mapping[str, Any], ...]
    projected_record_digest: str
    evidence_as_of: str
    clock_labels: tuple[str, ...]
    receipt: FetchReceipt
    raw_content_sha256: str


def _cic_from_receipt_url(canonical_url: str) -> str:
    parts = urlsplit(canonical_url)
    # Exact reviewed host + reviewed path shapes only; strict port/userinfo/
    # query/fragment rules. Validation only — no network endpoint admission.
    if parts.scheme != "https" or parts.hostname != SEC_HOST:
        raise AdapterError("receipt canonical_url must be the reviewed SEC host")
    if parts.port is not None or parts.username is not None or parts.password is not None:
        raise AdapterError("receipt canonical_url must carry no port/userinfo")
    if parts.query or parts.fragment:
        raise AdapterError("receipt canonical_url must carry no query/fragment")
    if not (SEC_SUBMISSIONS_PATH_RE.fullmatch(parts.path) or SEC_COMPANYFACTS_PATH_RE.fullmatch(parts.path)):
        raise AdapterError("receipt canonical_url is not a reviewed SEC path")
    match = CIK_PATH_RE.search(parts.path)
    if not match:
        raise AdapterError("receipt canonical_url does not carry a strict 10-digit CIK")
    return match.group(1)


def project_sec_records(
    records: tuple[Mapping[str, Any], ...],
    *,
    claim_kind: str,
    expected_cik: str,
    expected_period: str | None,
    resolved_symbol_alias: Mapping[str, Any] | None,
    jurisdiction: str,
) -> tuple[Mapping[str, Any], ...]:
    """Deterministic per-record projection (no second parser/pipeline)."""
    if claim_kind == "issuer_financial_statement":
        if not expected_period:
            raise AdapterError("expected_period is mandatory for financial statement claims")
        projected: list[dict[str, Any]] = []
        for record in records:
            if record.get("record_type") != "company_fact":
                continue
            if record.get("cik") != expected_cik:
                continue
            if record.get("unit") != "USD":
                # Reviewed USD-only monetary projection; other units stay
                # valid raw parses but fail monetary qualification.
                continue
            if str(record.get("end")).split("T")[0] != expected_period:
                continue
            projected.append(
                {
                    "entity": expected_cik,
                    "identifier": expected_cik,
                    "legal_name": record.get("entity_name") or "",
                    "period": str(record["end"]).split("T")[0],
                    "currency": record["unit"],
                    "value": record["value"],
                    "filing_identifier": record["accession_number"],
                    "jurisdiction": jurisdiction,
                    "taxonomy": record.get("taxonomy"),
                    "tag": record.get("tag"),
                    "unit": record.get("unit"),
                    "fact_period": {
                        "start": record.get("start"),
                        "end": str(record["end"]).split("T")[0],
                    },
                    "filing_time": record.get("filed"),
                    "source_event_time": record.get("filed"),
                }
            )
        if not projected:
            raise AdapterError("no monetary USD fact records bind the expected CIK/period")
        return tuple(projected)
    if claim_kind == "issuer_identity":
        filings = [
            record
            for record in records
            if record.get("record_type") == "submission_filing" and record.get("cik") == expected_cik
        ]
        if not filings:
            raise AdapterError("no filing records bind the expected CIK")
        record = filings[0]
        legal_name = record.get("entity_name") or ""
        if not legal_name:
            raise AdapterError("identity legal_name is required (descriptive only)")
        filing_event = record.get("acceptance_datetime") or record.get("filing_date")
        return (
            {
                "entity": expected_cik,
                "identifier": expected_cik,
                "legal_name": legal_name,
                "jurisdiction": jurisdiction,
                "filing_identifier": record["accession_number"],
                "filing_time": record.get("filing_date"),
                "source_event_time": filing_event,
            },
        )
    raise AdapterError(f"unsupported SEC claim kind: {claim_kind!r}")


def bind_sec_claim(
    raw_content: bytes,
    fetch_receipt: FetchReceipt,
    registry: Any,
    claim_kind: str,
    expected_cik: str,
    expected_period: str | None = None,
    resolved_symbol_alias: Mapping[str, Any] | None = None,
) -> SecClaimBinding:
    """Bind raw SEC content + minted receipt to one claim (fail-closed).

    The legacy parser is reused unchanged; the receipt gate and the CIK/URL
    binding are strict (no permissive digit stripping on binding input).
    """
    if not isinstance(expected_cik, str) or not re.fullmatch(r"\d{10}", expected_cik):
        raise AdapterError("expected_cik must be a strict 10-digit CIK")
    validate_fetch_receipt(fetch_receipt, source_id=SEC_REGISTRY_SOURCE_ID, content=raw_content)
    url_cik = _cic_from_receipt_url(fetch_receipt.canonical_url)
    if url_cik != expected_cik:
        raise AdapterError("receipt URL CIK does not match the expected CIK")
    if claim_kind not in ("issuer_financial_statement", "issuer_identity"):
        raise AdapterError(f"unsupported SEC claim kind: {claim_kind!r}")
    by_id = registry.by_id()
    source = by_id.get(SEC_REGISTRY_SOURCE_ID)
    if source is None:
        raise AdapterError("canonical SEC registry source is missing")
    if "US" not in tuple(source.jurisdictions):
        raise AdapterError("registered SEC source jurisdiction is not US")
    # Reuse the existing legacy parser unchanged (no second parser/pipeline).
    raw_batch = SecEdgarAdapter().parse(
        raw_content,
        content_type="application/json",
        retrieved_at=fetch_receipt.retrieved_at,
        context={"request_url": fetch_receipt.canonical_url},
    )
    raw_batch = make_batch(
        source_id=SEC_REGISTRY_SOURCE_ID,
        parser_version=raw_batch.parser_version,
        content=raw_content,
        retrieved_at=raw_batch.retrieved_at,
        records=raw_batch.records,
    )
    symbol: str | None = None
    if resolved_symbol_alias is not None:
        if not isinstance(resolved_symbol_alias, Mapping):
            raise AdapterError("resolved_symbol_alias must be an explicit mapping")
        if resolved_symbol_alias.get("cik") != expected_cik:
            raise AdapterError("resolved_symbol_alias does not match the expected CIK")
        alias_symbol = resolved_symbol_alias.get("symbol")
        if not isinstance(alias_symbol, str) or not alias_symbol.strip():
            raise AdapterError("resolved_symbol_alias must carry an explicit symbol")
        symbol = alias_symbol.strip()
    projected = project_sec_records(
        raw_batch.records,
        claim_kind=claim_kind,
        expected_cik=expected_cik,
        expected_period=expected_period,
        resolved_symbol_alias=resolved_symbol_alias,
        jurisdiction="US",
    )
    projected_with_symbol = tuple(
        {**record, "symbol": symbol} if symbol else dict(record) for record in projected
    )
    retrieved = _parse_utc(fetch_receipt.retrieved_at)
    evidence_bound = _clock_bound(
        projected[0]["source_event_time"],
        label="evidence_as_of",
        latest=retrieved,
    )
    _require_clock_order(evidence_bound, fetch_receipt.retrieved_at)
    clock_labels = ("filing_time", "source_event_time", "evidence_as_of", "retrieved_at")
    if claim_kind == "issuer_financial_statement":
        clock_labels = ("fact_period",) + clock_labels
    return SecClaimBinding(
        claim_kind=claim_kind,
        source_id=SEC_REGISTRY_SOURCE_ID,
        canonical_url=fetch_receipt.canonical_url,
        expected_cik=expected_cik,
        expected_period=expected_period,
        resolved_symbol=symbol,
        projected_records=projected_with_symbol,
        projected_record_digest=canonical_json(projected_with_symbol),
        evidence_as_of=f"{evidence_bound['earliest']}|{evidence_bound['label']}|{evidence_bound['precision']}|earliest_bound",
        clock_labels=clock_labels,
        receipt=fetch_receipt,
        raw_content_sha256=sha256_bytes(raw_content),
    )


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
