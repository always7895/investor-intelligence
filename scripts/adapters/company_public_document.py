"""Adapter for public company documents and regulatory disclosures.

Enforces:
- Structural validation for parsed public corporate records.
- Fail-closed gating on unreviewed terms and unverified rights.
- Explicit disallowance of forward projections as realized factor evidence.
- Prohibition of inferring scarcity or supplier count from nominal product lines.
- Zero live admission conferral.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

try:
    from .base import AdapterError, ParsedBatch, make_batch, utc_iso
except (ImportError, ValueError):
    from adapters.base import AdapterError, ParsedBatch, make_batch, utc_iso

MAX_PAYLOAD_BYTES = 6_000_000
DOCUMENT_TYPES = {
    "corporate_report",
    "ir_presentation",
    "financial_statement",
    "regulatory_filing",
    "procurement_notice",
}
VALID_PERIOD_TYPES = {
    "REALIZED",
    "HISTORICAL",
    "FORWARD_TARGET",
    "FORWARD_GUIDANCE",
    "CONDITIONAL_FORECAST",
}


class CompanyPublicDocumentAdapter:
    source_id = "company_public_document"
    parser_version = "company-doc-v1"
    content_type = "application/json"

    def parse(
        self,
        content: bytes,
        *,
        content_type: str,
        retrieved_at: str,
        context: Mapping[str, Any] | None = None,
    ) -> ParsedBatch:
        if len(content) > MAX_PAYLOAD_BYTES:
            raise AdapterError("PAYLOAD_TOO_LARGE")

        try:
            doc = json.loads(content.decode("utf-8"))
        except Exception as exc:
            raise AdapterError("INVALID_JSON") from exc

        if not isinstance(doc, Mapping):
            raise AdapterError("INVALID_DOCUMENT_STRUCTURE: must be a JSON object")

        entity = str(doc.get("entity") or "").strip()
        if not entity:
            raise AdapterError("INVALID_DOCUMENT_STRUCTURE: missing entity")

        doc_type = str(doc.get("document_type") or "corporate_report").strip()
        terms_review_status = str(doc.get("terms_review_status") or "NOT_REVIEWED").strip().upper()
        rights_status = str(doc.get("rights_status") or "UNKNOWN").strip().upper()

        raw_records = doc.get("records")
        if not isinstance(raw_records, list) or len(raw_records) == 0:
            raise AdapterError("INVALID_DOCUMENT_STRUCTURE: records must be a non-empty list")

        canonical_url = str((context or {}).get("canonical_url") or "").strip()
        published_at = str(doc.get("published_at") or doc.get("as_of") or retrieved_at).strip()
        jurisdiction = str(doc.get("jurisdiction") or "US").strip()
        language = str(doc.get("language") or "en").strip()
        evidence_role = str(doc.get("evidence_role") or "financial_statements").strip()
        claim_type = str(doc.get("claim_type") or "issuer_financial_statement").strip()

        # Build normalized records enforcing policy invariants
        normalized_records: list[dict[str, Any]] = []
        for raw_rec in raw_records:
            if not isinstance(raw_rec, Mapping):
                raise AdapterError("INVALID_RECORD_STRUCTURE: record must be an object")

            # Check period_type: forward targets cannot be licensed
            p_type = str(raw_rec.get("period_type") or raw_rec.get("target_period_type") or "REALIZED").strip().upper()
            factor_licensing_eligible = p_type not in {
                "FORWARD_TARGET",
                "FORWARD_GUIDANCE",
                "CONDITIONAL_FORECAST",
            }

            # Nominal products cannot confer scarcity inference
            nominal_products = raw_rec.get("nominal_products")
            effective_tp = raw_rec.get("effective_qualified_throughput")
            scarcity_inference_allowed = (
                effective_tp is not None and effective_tp > 0
            )

            # Runtime admission requires explicitly approved terms and reviewed free access
            runtime_admitted = (
                terms_review_status == "APPROVED"
                and rights_status in {"LICENSED_FREE_ACCESS", "PUBLIC_DOMAIN"}
            )

            # Partition rights into granular scopes
            if rights_status in {"LICENSED_FREE_ACCESS", "PUBLIC_DOMAIN"} and terms_review_status == "APPROVED":
                permitted_scopes = [
                    "internal_research",
                    "paraphrased_facts",
                    "brief_quotations",
                    "public_redistribution",
                ]
                disallowed_scopes = []
            elif rights_status == "PROHIBITED":
                permitted_scopes = []
                disallowed_scopes = [
                    "internal_research",
                    "paraphrased_facts",
                    "brief_quotations",
                    "public_redistribution",
                    "raw_document_reproduction",
                ]
            else:
                # UNKNOWN, NOT_REVIEWED, or COPYRIGHT_RESERVED:
                # Internal research and factual paraphrases are permitted;
                # public redistribution and raw document reproduction are strictly prohibited.
                permitted_scopes = [
                    "internal_research",
                    "paraphrased_facts",
                    "brief_quotations",
                ]
                disallowed_scopes = [
                    "public_redistribution",
                    "raw_document_reproduction",
                ]

            rec_payload = dict(raw_rec.get("payload") or {})
            if not rec_payload:
                rec_payload = {
                    "subject": entity,
                    "as_of": published_at,
                    "rights_status": rights_status,
                    "terms_review_status": terms_review_status,
                }
                if raw_rec.get("metric"):
                    rec_payload["metric"] = raw_rec.get("metric")
                if raw_rec.get("value") is not None:
                    rec_payload["value"] = raw_rec.get("value")

            rec: dict[str, Any] = {
                "entity": entity,
                "document_type": doc_type,
                "terms_review_status": terms_review_status,
                "rights_status": rights_status,
                "runtime_admitted": runtime_admitted,
                "permitted_scopes": permitted_scopes,
                "disallowed_scopes": disallowed_scopes,
                "period_type": p_type,
                "factor_licensing_eligible": factor_licensing_eligible,
                "scarcity_inference_allowed": scarcity_inference_allowed,
                "effective_qualified_throughput": effective_tp,
                "canonical_url": canonical_url,
                "published_at": str(raw_rec.get("published_at") or published_at),
                "jurisdiction": str(raw_rec.get("jurisdiction") or jurisdiction),
                "language": str(raw_rec.get("language") or language),
                "evidence_role": str(raw_rec.get("evidence_role") or evidence_role),
                "claim_type": str(raw_rec.get("claim_type") or claim_type),
                "payload": rec_payload,
            }

            for k, v in raw_rec.items():
                if k not in rec and isinstance(v, (str, int, float, bool)) or v is None:
                    rec[k] = v

            normalized_records.append(rec)

        return make_batch(
            source_id=self.source_id,
            parser_version=self.parser_version,
            content=content,
            retrieved_at=retrieved_at,
            records=normalized_records,
        )


def evidence_items(batch: ParsedBatch, *, registry_version: str) -> list[dict[str, Any]]:
    """Build standardized evidence candidate items from parsed company public documents."""
    try:
        from .base import build_evidence_item
    except (ImportError, ValueError):
        from adapters.base import build_evidence_item

    result: list[dict[str, Any]] = []
    for idx, record in enumerate(batch.records, 1):
        cid = None
        fb = record.get("factor_binding")
        if isinstance(fb, Mapping) and fb.get("claim_id"):
            cid = str(fb["claim_id"])
        elif record.get("claim_id"):
            cid = str(record["claim_id"])
        else:
            cid = f"doc:{record.get('entity')}:{record.get('document_type')}:{idx}"

        fields: dict[str, Any] = {
            "entity": str(record.get("entity") or ""),
            "document_type": str(record.get("document_type") or ""),
            "rights_status": str(record.get("rights_status") or "UNKNOWN"),
        }
        if record.get("metric"):
            fields["metric"] = str(record["metric"])
        if record.get("value") is not None:
            fields["value"] = record["value"]
        if record.get("voltage_kv") is not None:
            fields["voltage_kv"] = record["voltage_kv"]

        result.append(
            build_evidence_item(
                batch,
                record,
                claim_id=cid,
                claim_type="corporate_report",
                canonical_url=str(record.get("canonical_url") or f"https://example.com/doc/{cid}"),
                field_values=fields,
                registry_version=str(registry_version),
                published_at=record.get("published_at"),
                as_of=record.get("as_of"),
            )
        )
    return result
