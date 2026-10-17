#!/usr/bin/env python3
"""Bounded Reusable Source-Candidate Producer (COMPANY_EVIDENCE_RESEARCH_V1 Review 2).

Validates candidate claim proposals against provided primary source texts and receipts.
Enforces:
- Exact SHA256 and byte checks on text files and receipts.
- Path traversal rejection, symlink rejection, credentialed URL rejection, local/private IP rejection.
- Immutable output writing: rejection of existing targets, symlinks, and aliased inputs BEFORE write.
- Exclusive creation (O_CREAT | O_EXCL) to close TOCTOU race windows.
- Strict JSON parsing and serialization (rejection of NaN, Infinity, duplicate keys, deep nesting).
- Bounded scalar types for values, preventing boolean and locale numeric coercion.
- Aggregate source and receipt byte budgets and count caps enforced before loading/hashing.
- Strict schema versions, candidate scopes, and record_count consistency.
- Output summary with strictly counts and static status (never leaks raw paths or canary tokens).
- Strict verbatim passage anchor verification against source text files (EXACT match mode).
- Roundtrip invariant: original_text[char_offset : char_offset + char_length] == exact_passage.
- Context connection verification: passage context must enclose the verified passage.
- Repeated passage disambiguation: ambiguous occurrences without enclosing context quarantined.
- Separation of verified text anchor existence from analyst proposed interpretations.
- Separation of authoritative document source role (ISSUER_PUBLISHED_DOCUMENT) from proposed roles.
- Default promotion prevention: missing metadata marked UNKNOWN or UNREVIEWED.
- Tracking of issuer lineages to detect same-issuer false independence.
- Output status strictly locked to RESEARCH_CANDIDATE / PASSAGE_MATCHED.
- Runtime admitted claims count strictly 0.
- Bounded static error codes; never leaks credentials, paths, args, or user input in logs/exceptions.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import os
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

MAX_PROPOSALS = 100
MAX_PASSAGE_WORDS = 200
MAX_FIELD_CHARS = 4000
MAX_SOURCE_BYTES = 10 * 1024 * 1024  # 10 MB per file limit
MAX_AGGREGATE_SOURCE_BYTES = 50 * 1024 * 1024  # 50 MB aggregate source budget
MAX_PROPOSALS_BYTES = 10 * 1024 * 1024
MAX_SOURCES_COUNT = 50
MAX_RECEIPTS_COUNT = 50
MAX_NESTING_DEPTH = 10

FORBIDDEN_CALLER_KEYS = {
    "bottleneck_score",
    "score",
    "rank",
    "source_count_score",
    "factor_points",
}

ALLOWED_SOURCES_MANIFEST_KEYS = {
    "schema_version",
    "scope",
    "assembled_at",
    "record_count",
    "sources",
    "source_receipts",
}

ALLOWED_SOURCES_SCOPES = {
    "PUBLIC_RESEARCH_INPUT_NOT_ADMITTED",
    "PUBLIC_RESEARCH_SOURCES_V1",
}

ALLOWED_SOURCE_ENTRY_KEYS = {
    "id",
    "source_url",
    "text_file",
    "text_sha256",
    "text_bytes",
    "raw_body_sha256",
    "content_kind",
    "published_at",
    "retrieval_clock",
    "lineage_id",
    "rights",
    "runtime_admitted",
}

ALLOWED_RECEIPT_ENTRY_KEYS = {
    "sha256",
    "file",
}

ALLOWED_CONTENT_KINDS = {
    "PDF_EXTRACTED_TEXT",
    "HTML_EXTRACTED_TEXT",
    "TEXT_EXTRACTED",
    "PUBLIC_REPORT",
}

ALLOWED_PROPOSALS_PAYLOAD_KEYS = {
    "schema_version",
    "lane",
    "scope",
    "notice",
    "proposals",
}

ALLOWED_PROPOSALS_SCOPES = {
    "COMPANY_EVIDENCE_RESEARCH_V1_REVIEW1_PROPOSALS",
    "COMPANY_EVIDENCE_RESEARCH_V1_REVIEW2_PROPOSALS",
    "COMPANY_EVIDENCE_RESEARCH_V1_PROPOSALS",
    "RESEARCH_CANDIDATES_ONLY_NOT_ADMITTED",
}

ALLOWED_PROPOSAL_KEYS = {
    "claim_id",
    "company_id",
    "legal_entity",
    "segment",
    "product_or_spec",
    "geography",
    "metric",
    "value",
    "unit",
    "denominator",
    "financial_period",
    "period_type",
    "source_id",
    "source_url",
    "source_lineage",
    "source_role",
    "exact_passage",
    "passage_context",
    "page_or_location",
    "proposed_label",
    "premises",
    "falsifiers",
    "missing_independent_counterparty_proof",
    "operating_vs_equity_boundary",
    "effective_substitutes_gap",
}

ALLOWED_PROPOSED_LABELS = {
    "SUPPORTED",
    "INFERENCE",
    "CONTRADICTED",
    "UNSUPPORTED",
    "UNREVIEWED",
}

ALLOWED_PERIOD_TYPES = {
    "HISTORICAL_REALIZED",
    "FORWARD_GUIDANCE",
    "TARGET_LONG_TERM",
    "UNREVIEWED",
    "UNSPECIFIED",
}


class EvidenceValidationError(Exception):
    """Raised when evidence sources or verification checks fail."""
    pass


def _reject_constant(c: str) -> Any:
    raise EvidenceValidationError("NON_FINITE_NUMERIC_REJECTED: Non-finite numbers are not allowed")


def _strict_pairs_hook(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    d: Dict[str, Any] = {}
    for k, v in pairs:
        if k in d:
            raise EvidenceValidationError("DUPLICATE_KEY_REJECTED: Duplicate key detected in JSON")
        d[k] = v
    return d


def check_nesting_depth(obj: Any, current_depth: int = 0) -> None:
    if current_depth > MAX_NESTING_DEPTH:
        raise EvidenceValidationError("DEEP_NESTING_REJECTED: Value nesting exceeds limit")
    if isinstance(obj, dict):
        for v in obj.values():
            check_nesting_depth(v, current_depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            check_nesting_depth(item, current_depth + 1)


def strict_json_loads(s: str) -> Any:
    try:
        obj = json.loads(
            s,
            parse_constant=_reject_constant,
            object_pairs_hook=_strict_pairs_hook,
        )
    except json.JSONDecodeError:
        raise EvidenceValidationError("INVALID_JSON: Failed to parse JSON")
    check_nesting_depth(obj)
    return obj


def compute_sha256_and_bytes(file_path: Path, max_bytes: int = MAX_SOURCE_BYTES) -> Tuple[str, int]:
    """Compute sha256 hex digest and total byte count of a file within bounds."""
    if file_path.is_symlink():
        raise EvidenceValidationError("SYMLINK_REJECTED: Symlink rejected for source file")
    if not file_path.exists():
        raise EvidenceValidationError("FILE_NOT_FOUND: Source text file does not exist")
    file_size = file_path.stat().st_size
    if file_size > max_bytes:
        raise EvidenceValidationError("EXCEEDED_BYTE_LIMIT: Exceeded max allowed bytes")

    h = hashlib.sha256()
    total_bytes = 0
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise EvidenceValidationError("EXCEEDED_BYTE_LIMIT: Exceeded max allowed bytes")
            h.update(chunk)
    return h.hexdigest(), total_bytes


def validate_source_url(url: str) -> None:
    """Validate URL safety: reject credentials, non-HTTPS schemes, private/local IPs/hosts."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise EvidenceValidationError("HTTPS_REQUIRED: Scheme must be https")
    if parsed.username or parsed.password or ("@" in parsed.netloc):
        raise EvidenceValidationError("CREDENTIALED_URL_REJECTED: Credentialed URL rejected")
    if "%" in parsed.netloc or "%" in (parsed.hostname or ""):
        raise EvidenceValidationError("ENCODED_HOST_REJECTED: Encoded host rejected")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise EvidenceValidationError("EMPTY_HOST_REJECTED: Empty host rejected")
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or hostname.endswith(".local") or hostname.endswith(".localhost") or hostname.endswith(".internal"):
        raise EvidenceValidationError("LOCAL_HOST_URL_REJECTED: Local host URL rejected")

    # Check IP literal
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_multicast or ip.is_link_local or ip.is_unspecified:
            raise EvidenceValidationError("PRIVATE_IP_REJECTED: Private IP rejected")
    except ValueError:
        pass

    # Reject hex / octal / pure integer hosts
    if re.match(r"^0x[0-9a-fA-F]+$", hostname) or re.match(r"^\d+$", hostname):
        raise EvidenceValidationError("PRIVATE_IP_REJECTED: Private IP rejected")

    # Path traversal in URL
    if ".." in parsed.path or "%2e%2e" in parsed.path.lower():
        raise EvidenceValidationError("PATH_TRAVERSAL_REJECTED: Path traversal in URL rejected")

    # Non-standard port check
    if parsed.port is not None and parsed.port != 443:
        raise EvidenceValidationError("NON_STANDARD_PORT_REJECTED: Non-standard port rejected")


def normalize_whitespace(text: str) -> str:
    """Normalize line endings, collapse whitespace, and clean stray spaces before punctuation."""
    norm = re.sub(r"\s+", " ", text.replace("\r\n", "\n")).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", norm)


class SourcesValidator:
    """Validates the sources manifest against on-disk files and receipts."""

    def __init__(self, sources_path: Path | str, max_aggregate_bytes: int = MAX_AGGREGATE_SOURCE_BYTES) -> None:
        self.sources_path = Path(sources_path).resolve()
        if not self.sources_path.exists():
            raise EvidenceValidationError("SOURCES_MANIFEST_NOT_FOUND: Sources manifest does not exist")
        if self.sources_path.is_symlink():
            raise EvidenceValidationError("SYMLINK_REJECTED: Sources manifest is a symlink")
        self.sources_dir = self.sources_path.parent
        self.max_aggregate_bytes = max_aggregate_bytes

    def validate_all(self) -> List[Dict[str, Any]]:
        # Check size before reading
        if self.sources_path.stat().st_size > MAX_SOURCE_BYTES:
            raise EvidenceValidationError("EXCEEDED_BYTE_LIMIT: Exceeded max allowed bytes")

        with open(self.sources_path, "r", encoding="utf-8") as f:
            raw_text = f.read()
        data = strict_json_loads(raw_text)

        if not isinstance(data, dict):
            raise EvidenceValidationError("SCHEMA_VALIDATION_FAILED: Manifest root must be a dict")

        # Top-level schema check
        unknown_manifest_keys = set(data.keys()) - ALLOWED_SOURCES_MANIFEST_KEYS
        if unknown_manifest_keys:
            raise EvidenceValidationError("SCHEMA_VALIDATION_FAILED: Unknown key in sources manifest")

        s_ver = data.get("schema_version")
        if type(s_ver) is not int or type(s_ver) is bool or s_ver != 1:
            raise EvidenceValidationError("SCHEMA_VALIDATION_FAILED: Invalid schema_version")

        scope = data.get("scope")
        if scope is not None and scope not in ALLOWED_SOURCES_SCOPES:
            raise EvidenceValidationError("SCHEMA_VALIDATION_FAILED: Invalid sources scope")

        sources = data.get("sources", [])
        if not isinstance(sources, list):
            raise EvidenceValidationError("SCHEMA_VALIDATION_FAILED: sources must be a list")

        receipts = data.get("source_receipts", [])
        if not isinstance(receipts, list):
            raise EvidenceValidationError("SCHEMA_VALIDATION_FAILED: source_receipts must be a list")

        # Check counts
        if len(sources) > MAX_SOURCES_COUNT:
            raise EvidenceValidationError("EXCEEDED_COUNT_LIMIT: Sources count exceeds maximum cap")
        if len(receipts) > MAX_RECEIPTS_COUNT:
            raise EvidenceValidationError("EXCEEDED_COUNT_LIMIT: Receipts count exceeds maximum cap")

        # Strict record_count consistency check
        record_count = data.get("record_count")
        if type(record_count) is not int or type(record_count) is bool or record_count != len(sources):
            raise EvidenceValidationError("RECORD_COUNT_MISMATCH: Record count does not match sources list length")

        # Calculate aggregate byte usage across manifest, receipts, and sources before deep reads
        aggregate_bytes = self.sources_path.stat().st_size
        receipt_paths = []
        for r in receipts:
            if not isinstance(r, dict):
                raise EvidenceValidationError("SCHEMA_VALIDATION_FAILED: Receipt entry is not a dict")
            r_file = r.get("file")
            if not r_file or not isinstance(r_file, str):
                raise EvidenceValidationError("RECEIPT_ENTRY_INVALID: Receipt entry missing file")
            if ".." in r_file or "/" in r_file or "\\" in r_file:
                raise EvidenceValidationError("PATH_TRAVERSAL_REJECTED: Path traversal detected in receipt")
            r_path = (self.sources_dir / r_file).resolve()
            if not r_path.is_relative_to(self.sources_dir.resolve()):
                raise EvidenceValidationError("PATH_TRAVERSAL_REJECTED: Receipt file outside root")
            if not r_path.exists() or r_path.is_symlink():
                raise EvidenceValidationError("RECEIPT_FILE_MISSING_OR_SYMLINK: Missing or symlink receipt")
            r_size = r_path.stat().st_size
            if r_size > MAX_SOURCE_BYTES:
                raise EvidenceValidationError("EXCEEDED_BYTE_LIMIT: Exceeded max allowed bytes")
            aggregate_bytes += r_size
            receipt_paths.append((r, r_path))

        source_file_paths = []
        for s in sources:
            if not isinstance(s, dict):
                raise EvidenceValidationError("SCHEMA_VALIDATION_FAILED: Source entry is not a dict")
            t_file = s.get("text_file")
            if not t_file or not isinstance(t_file, str):
                raise EvidenceValidationError("SOURCE_ENTRY_INVALID: Source entry missing text_file")
            if ".." in t_file or "/" in t_file or "\\" in t_file:
                raise EvidenceValidationError("PATH_TRAVERSAL_REJECTED: Path traversal detected in text_file")
            s_path = (self.sources_dir / t_file).resolve()
            if not s_path.is_relative_to(self.sources_dir.resolve()):
                raise EvidenceValidationError("PATH_TRAVERSAL_REJECTED: Source file outside root")
            if not s_path.exists():
                raise EvidenceValidationError("FILE_NOT_FOUND: Source text file does not exist")
            if s_path.is_symlink():
                raise EvidenceValidationError("SYMLINK_REJECTED: Symlink rejected for source file")
            s_size = s_path.stat().st_size
            if s_size > MAX_SOURCE_BYTES:
                raise EvidenceValidationError("EXCEEDED_BYTE_LIMIT: Exceeded max allowed bytes")
            aggregate_bytes += s_size
            source_file_paths.append((s, s_path))

        if aggregate_bytes > self.max_aggregate_bytes:
            raise EvidenceValidationError("EXCEEDED_AGGREGATE_BYTE_LIMIT: Aggregate source bytes exceed maximum cap")

        # Validate receipts
        for r, r_path in receipt_paths:
            unknown_r_keys = set(r.keys()) - ALLOWED_RECEIPT_ENTRY_KEYS
            if unknown_r_keys:
                raise EvidenceValidationError("SCHEMA_VALIDATION_FAILED: Unknown key in receipt entry")
            expected_sha = r.get("sha256")
            if not expected_sha:
                raise EvidenceValidationError("RECEIPT_ENTRY_INVALID: Receipt entry missing sha256")
            actual_sha, _ = compute_sha256_and_bytes(r_path)
            if actual_sha.lower() != expected_sha.lower():
                raise EvidenceValidationError("RECEIPT_HASH_MISMATCH: Receipt hash mismatch")

        # Validate sources
        validated_sources = []
        for s, file_path in source_file_paths:
            unknown_s_keys = set(s.keys()) - ALLOWED_SOURCE_ENTRY_KEYS
            if unknown_s_keys:
                raise EvidenceValidationError("SCHEMA_VALIDATION_FAILED: Unknown key in source entry")
            sid = s.get("id")
            s_url = s.get("source_url")
            t_file = s.get("text_file")
            expected_sha = s.get("text_sha256")
            expected_bytes = s.get("text_bytes")
            content_kind = s.get("content_kind")

            if not sid or not s_url or not t_file or not expected_sha:
                raise EvidenceValidationError("SOURCE_ENTRY_INVALID: Source entry missing required fields")

            if content_kind is not None and content_kind not in ALLOWED_CONTENT_KINDS:
                raise EvidenceValidationError("UNKNOWN_CONTENT_KIND: Unknown content kind in source entry")

            validate_source_url(s_url)

            if expected_bytes is not None and file_path.stat().st_size != expected_bytes:
                raise EvidenceValidationError("BYTE_LENGTH_MISMATCH: Byte length mismatch")

            actual_sha, actual_bytes = compute_sha256_and_bytes(file_path)
            if actual_sha.lower() != expected_sha.lower():
                raise EvidenceValidationError("HASH_MISMATCH: Hash mismatch")
            if expected_bytes is not None and actual_bytes != expected_bytes:
                raise EvidenceValidationError("BYTE_LENGTH_MISMATCH: Byte length mismatch")

            validated_sources.append({
                "id": sid,
                "source_url": s_url,
                "text_file": t_file,
                "file_path": file_path,
                "text_sha256": actual_sha,
                "text_bytes": actual_bytes,
                "raw_body_sha256": s.get("raw_body_sha256"),
                "content_kind": content_kind,
                "retrieval_clock": s.get("retrieval_clock"),
                "lineage_id": s.get("lineage_id"),
                "rights": s.get("rights", "NOT_REVIEWED"),
                "runtime_admitted": False,
                "valid": True,
            })

        return validated_sources


class CandidateProducer:
    """Validates proposals against sources and produces bounded research candidates."""

    def __init__(self, sources_path: Path | str, max_aggregate_bytes: int = MAX_AGGREGATE_SOURCE_BYTES) -> None:
        validator = SourcesValidator(sources_path, max_aggregate_bytes=max_aggregate_bytes)
        self.sources = validator.validate_all()
        self.sources_by_id = {s["id"]: s for s in self.sources}
        # Pre-cache text contents
        self.source_texts: Dict[str, str] = {}
        for s in self.sources:
            with open(s["file_path"], "r", encoding="utf-8") as f:
                self.source_texts[s["id"]] = f.read()

    def process_proposals(self, proposals_payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(proposals_payload, dict):
            raise EvidenceValidationError("SCHEMA_VALIDATION_FAILED: Proposals root must be a dict")

        unknown_keys = set(proposals_payload.keys()) - ALLOWED_PROPOSALS_PAYLOAD_KEYS
        if unknown_keys:
            raise EvidenceValidationError("SCHEMA_VALIDATION_FAILED: Unknown key in proposals payload")

        s_ver = proposals_payload.get("schema_version")
        if type(s_ver) is not int or type(s_ver) is bool or s_ver != 1:
            raise EvidenceValidationError("SCHEMA_VALIDATION_FAILED: Invalid schema_version in proposals")

        p_scope = proposals_payload.get("scope")
        if p_scope is not None and p_scope not in ALLOWED_PROPOSALS_SCOPES:
            raise EvidenceValidationError("SCHEMA_VALIDATION_FAILED: Invalid scope in proposals")

        p_lane = proposals_payload.get("lane")
        if p_lane is not None and p_lane != "COMPANY_EVIDENCE_RESEARCH_V1":
            raise EvidenceValidationError("SCHEMA_VALIDATION_FAILED: Invalid lane in proposals")

        raw_list = proposals_payload.get("proposals", [])
        if not isinstance(raw_list, list):
            raise EvidenceValidationError("PROPOSALS_MUST_BE_LIST: proposals key must be a list")

        if len(raw_list) > MAX_PROPOSALS:
            raise EvidenceValidationError("MAX_PROPOSALS_EXCEEDED: Exceeded max proposals cap")

        seen_claim_ids: Set[str] = set()
        validated_candidates: List[Dict[str, Any]] = []
        quarantine: List[Dict[str, Any]] = []

        lineages_present: Set[str] = set()

        for idx, prop in enumerate(raw_list):
            if not isinstance(prop, dict):
                quarantine.append({"index": idx, "reason": "PROPOSAL_NOT_A_DICT"})
                continue

            claim_id = prop.get("claim_id")
            if not claim_id or not isinstance(claim_id, str):
                quarantine.append({"index": idx, "reason": "MISSING_OR_INVALID_CLAIM_ID"})
                continue

            # Duplicate check
            if claim_id in seen_claim_ids:
                quarantine.append({"claim_id": claim_id, "reason": "DUPLICATE_CLAIM_ID"})
                continue
            seen_claim_ids.add(claim_id)

            # Caller forbidden status or score injection check
            forged_keys = [k for k in FORBIDDEN_CALLER_KEYS if k in prop]
            if forged_keys or prop.get("status") == "ADMITTED" or prop.get("admitted") is True:
                quarantine.append({
                    "claim_id": claim_id,
                    "reason": "FORBIDDEN_CALLER_STATUS_OR_SCORE"
                })
                continue

            # Check for unknown proposal fields
            unknown_prop_fields = set(prop.keys()) - ALLOWED_PROPOSAL_KEYS
            if unknown_prop_fields:
                quarantine.append({
                    "claim_id": claim_id,
                    "reason": "UNKNOWN_PROPOSAL_FIELDS"
                })
                continue

            # Required fields check
            company_id = prop.get("company_id")
            legal_entity = prop.get("legal_entity")
            metric = prop.get("metric")
            source_id = prop.get("source_id")
            exact_passage = prop.get("exact_passage")

            if not company_id or not legal_entity or not metric or not source_id or not exact_passage:
                quarantine.append({
                    "claim_id": claim_id,
                    "reason": "MISSING_REQUIRED_FIELDS (company_id, legal_entity, metric, source_id, exact_passage)"
                })
                continue

            # Field length checks
            if any(isinstance(prop.get(k), str) and len(prop.get(k)) > MAX_FIELD_CHARS for k in ["company_id", "legal_entity", "metric", "exact_passage"]):
                quarantine.append({
                    "claim_id": claim_id,
                    "reason": "FIELD_LENGTH_EXCEEDED"
                })
                continue

            # Validate metric value scalar & finite bounds without boolean coercion
            val = prop.get("value")
            if val is not None:
                if type(val) is bool:
                    quarantine.append({
                        "claim_id": claim_id,
                        "reason": "INVALID_VALUE_TYPE: Boolean value not allowed in metric value"
                    })
                    continue
                elif type(val) is int:
                    if not (-1e15 <= val <= 1e15):
                        quarantine.append({
                            "claim_id": claim_id,
                            "reason": "VALUE_OUT_OF_BOUNDS: Numeric value exceeds bounds"
                        })
                        continue
                elif type(val) is float:
                    if not math.isfinite(val) or not (-1e15 <= val <= 1e15):
                        quarantine.append({
                            "claim_id": claim_id,
                            "reason": "VALUE_OUT_OF_BOUNDS: Numeric value exceeds bounds"
                        })
                        continue
                elif type(val) is str:
                    if len(val) > MAX_FIELD_CHARS:
                        quarantine.append({
                            "claim_id": claim_id,
                            "reason": "VALUE_FIELD_EXCEEDS_LENGTH: String value exceeds length"
                        })
                        continue
                else:
                    quarantine.append({
                        "claim_id": claim_id,
                        "reason": "INVALID_VALUE_TYPE: Non-scalar value in metric value"
                    })
                    continue

            # Validate proposed_label enum
            raw_label = prop.get("proposed_label")
            if raw_label is None or raw_label == "":
                proposed_label = "UNREVIEWED"
            elif raw_label in ALLOWED_PROPOSED_LABELS:
                proposed_label = raw_label
            else:
                quarantine.append({
                    "claim_id": claim_id,
                    "reason": "UNKNOWN_PROPOSED_LABEL: Unknown proposed label"
                })
                continue

            # Validate period_type enum
            raw_pt = prop.get("period_type")
            if raw_pt is None or raw_pt == "":
                period_type = "UNREVIEWED"
            elif raw_pt in ALLOWED_PERIOD_TYPES:
                period_type = raw_pt
            else:
                quarantine.append({
                    "claim_id": claim_id,
                    "reason": "UNKNOWN_PERIOD_TYPE: Unknown period type"
                })
                continue

            # Geography (never default to GLOBAL!)
            geography = prop.get("geography") or "UNKNOWN"

            # Word count limit on corporate quotes
            words = exact_passage.split()
            if len(words) > MAX_PASSAGE_WORDS:
                quarantine.append({
                    "claim_id": claim_id,
                    "reason": "EXACT_PASSAGE_EXCEEDS_WORD_LIMIT"
                })
                continue

            # Source ID check
            if source_id not in self.sources_by_id:
                quarantine.append({
                    "claim_id": claim_id,
                    "reason": "UNKNOWN_SOURCE_ID"
                })
                continue

            source_meta = self.sources_by_id[source_id]
            doc_text = self.source_texts[source_id]

            # Find all EXACT verbatim occurrences of the passage in source text
            occurrences: List[int] = []
            start = 0
            while True:
                occ_idx = doc_text.find(exact_passage, start)
                if occ_idx == -1:
                    break
                occurrences.append(occ_idx)
                start = occ_idx + 1

            if not occurrences:
                quarantine.append({
                    "claim_id": claim_id,
                    "reason": "UNMATCHED_PASSAGE_IN_SOURCE",
                    "source_id": source_id
                })
                continue

            # Validate context and resolve ambiguity
            context = prop.get("passage_context")
            char_offset = -1

            if len(occurrences) == 1:
                # Unique occurrence in doc
                target_occ = occurrences[0]
                if context:
                    # Verify context exists in source text
                    ctx_occurrences: List[int] = []
                    c_start = 0
                    while True:
                        c_idx = doc_text.find(context, c_start)
                        if c_idx == -1:
                            break
                        ctx_occurrences.append(c_idx)
                        c_start = c_idx + 1

                    if not ctx_occurrences:
                        quarantine.append({
                            "claim_id": claim_id,
                            "reason": "UNMATCHED_PASSAGE_CONTEXT_IN_SOURCE",
                            "source_id": source_id
                        })
                        continue

                    # Context must enclose the selected passage
                    enclosed = any(
                        c_idx <= target_occ and (target_occ + len(exact_passage)) <= (c_idx + len(context))
                        for c_idx in ctx_occurrences
                    )
                    if not enclosed:
                        quarantine.append({
                            "claim_id": claim_id,
                            "reason": "CONTEXT_NOT_CONNECTED_TO_PASSAGE",
                            "source_id": source_id
                        })
                        continue

                char_offset = target_occ
            else:
                # Multiple occurrences (> 1) - requires disambiguation via enclosing context
                if not context:
                    quarantine.append({
                        "claim_id": claim_id,
                        "reason": "AMBIGUOUS_REPEATED_PASSAGE",
                        "source_id": source_id,
                        "occurrence_count": len(occurrences)
                    })
                    continue

                ctx_occurrences = []
                c_start = 0
                while True:
                    c_idx = doc_text.find(context, c_start)
                    if c_idx == -1:
                        break
                    ctx_occurrences.append(c_idx)
                    c_start = c_idx + 1

                if not ctx_occurrences:
                    quarantine.append({
                        "claim_id": claim_id,
                        "reason": "UNMATCHED_PASSAGE_CONTEXT_IN_SOURCE",
                        "source_id": source_id
                    })
                    continue

                valid_matches = [
                    occ for occ in occurrences
                    if any(c_idx <= occ and (occ + len(exact_passage)) <= (c_idx + len(context)) for c_idx in ctx_occurrences)
                ]

                if len(valid_matches) == 1:
                    char_offset = valid_matches[0]
                elif len(valid_matches) == 0:
                    quarantine.append({
                        "claim_id": claim_id,
                        "reason": "CONTEXT_NOT_CONNECTED_TO_PASSAGE",
                        "source_id": source_id
                    })
                    continue
                else:
                    quarantine.append({
                        "claim_id": claim_id,
                        "reason": "AMBIGUOUS_REPEATED_PASSAGE",
                        "source_id": source_id,
                        "occurrence_count": len(valid_matches)
                    })
                    continue

            # Strict roundtrip invariant verification
            match_len = len(exact_passage)
            if doc_text[char_offset : char_offset + match_len] != exact_passage:
                quarantine.append({
                    "claim_id": claim_id,
                    "reason": "ROUNDTRIP_INVARIANT_FAILED",
                    "source_id": source_id
                })
                continue

            # Extract bounded local context before/after
            before_start = max(0, char_offset - 80)
            after_end = min(len(doc_text), char_offset + match_len + 80)
            bounded_before = doc_text[before_start:char_offset]
            bounded_after = doc_text[char_offset + match_len:after_end]

            # Source lineage
            lineage = source_meta.get("lineage_id", "UNKNOWN_LINEAGE")
            lineages_present.add(lineage)

            # Prevent false issuer independence / unearned role promotion
            document_source_role = "ISSUER_PUBLISHED_DOCUMENT"
            proposed_source_role = prop.get("source_role") or "UNREVIEWED"
            effective_source_role = "ISSUER_PRIMARY"

            candidate_record = {
                "claim_id": claim_id,
                "company_id": company_id,
                "legal_entity": legal_entity,
                "segment": prop.get("segment", "UNSPECIFIED"),
                "product_or_spec": prop.get("product_or_spec", "UNSPECIFIED"),
                "geography": geography,
                "metric": metric,
                "value": val,
                "unit": prop.get("unit"),
                "denominator": prop.get("denominator"),
                "financial_period": prop.get("financial_period", "UNSPECIFIED"),
                "period_type": period_type,
                "source_id": source_id,
                "source_url": source_meta["source_url"],
                "source_lineage": lineage,
                "document_source_role": document_source_role,
                "proposed_source_role": proposed_source_role,
                "effective_source_role": effective_source_role,
                "source_role": effective_source_role,
                "lineage_independence": "SAME_ISSUER_LINEAGE_PRIMARY_ONLY",
                "exact_passage": exact_passage,
                "passage_context": context,
                "match_mode": "EXACT",
                "page_or_location": prop.get("page_or_location", "UNSPECIFIED"),
                "status": "RESEARCH_CANDIDATE",
                "passage_status": "PASSAGE_MATCHED",
                "economic_validation": "TEXT_ANCHOR_ONLY_ECONOMICS_UNVERIFIED",
                "runtime_admitted": False,
                "proposed_label": proposed_label,
                "analyst_interpretation": {
                    "premises": prop.get("premises", []),
                    "falsifiers": prop.get("falsifiers", []),
                    "missing_independent_counterparty_proof": prop.get("missing_independent_counterparty_proof", []),
                    "operating_vs_equity_boundary": prop.get("operating_vs_equity_boundary", ""),
                    "effective_substitutes_gap": prop.get("effective_substitutes_gap", "")
                },
                "verified_text_anchor": {
                    "source_id": source_id,
                    "source_file": source_meta["text_file"],
                    "source_sha256": source_meta["text_sha256"],
                    "char_offset": char_offset,
                    "char_length": match_len,
                    "match_mode": "EXACT",
                    "bounded_context_before": bounded_before,
                    "bounded_context_after": bounded_after
                }
            }

            validated_candidates.append(candidate_record)

        audit_sources = []
        for s in self.sources:
            audit_sources.append({
                "id": s["id"],
                "source_url": s["source_url"],
                "text_file": s["text_file"],
                "text_sha256": s["text_sha256"],
                "text_bytes": s["text_bytes"],
                "raw_body_sha256": s["raw_body_sha256"],
                "retrieval_clock": s["retrieval_clock"],
                "lineage_id": s["lineage_id"],
                "rights": s["rights"],
                "runtime_admitted": False,
            })

        output_doc = {
            "schema_version": 1,
            "lane": "COMPANY_EVIDENCE_RESEARCH_V1",
            "scope": "RESEARCH_CANDIDATES_ONLY_NOT_ADMITTED",
            "notice": "Verified text anchors prove passage existence; they do NOT grant bottleneck admission or rank promotion.",
            "summary": {
                "total_proposals": len(raw_list),
                "validated_candidates": len(validated_candidates),
                "quarantined_proposals": len(quarantine),
                "runtime_admitted_claims": 0,
                "distinct_issuer_lineages": len(lineages_present),
                "lineages": sorted(list(lineages_present)),
                "producer": "company_evidence_candidates.py",
                "producer_version": "1.2.0"
            },
            "source_audit": audit_sources,
            "candidates": validated_candidates,
            "quarantine": quarantine
        }
        return output_doc


def main() -> int:
    parser = argparse.ArgumentParser(description="Produce bounded research evidence candidates from primary sources.")
    parser.add_argument("--sources", required=True, help="Path to research-sources.json")
    parser.add_argument("--proposals", required=True, help="Path to proposals JSON")
    parser.add_argument("--output", required=True, help="Path to output JSON")

    args = parser.parse_args()

    sources_path = Path(args.sources)
    proposals_path = Path(args.proposals)
    output_path = Path(args.output)

    if not sources_path.exists():
        sys.stderr.write("SOURCES_FILE_MISSING\n")
        return 1

    if not proposals_path.exists():
        sys.stderr.write("PROPOSALS_FILE_MISSING\n")
        return 1

    try:
        # Immutability and pre-write destination checks
        if output_path.is_symlink():
            raise EvidenceValidationError("OUTPUT_FILE_IS_SYMLINK: Output file is a symlink")
        if output_path.exists():
            raise EvidenceValidationError("OUTPUT_FILE_ALREADY_EXISTS: Output file already exists")

        res_out = output_path.resolve()
        if res_out == sources_path.resolve() or res_out == proposals_path.resolve():
            raise EvidenceValidationError("OUTPUT_PATH_ALIASED_TO_INPUT: Output path cannot match input files")

        if proposals_path.stat().st_size > MAX_PROPOSALS_BYTES:
            raise EvidenceValidationError("EXCEEDED_BYTE_LIMIT: Proposals file exceeds byte limit")

        with open(proposals_path, "r", encoding="utf-8") as f:
            raw_proposals = f.read()
        proposals_data = strict_json_loads(raw_proposals)

        producer = CandidateProducer(sources_path)

        # Ensure output does not alias any validated source text file
        for s in producer.sources:
            if res_out == s["file_path"].resolve():
                raise EvidenceValidationError("OUTPUT_PATH_ALIASED_TO_INPUT: Output path cannot match source text files")

        result = producer.process_proposals(proposals_data)

        # Strict JSON serialization BEFORE touching destination file
        serialized_json = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)

        # Exclusive creation closes TOCTOU race
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(output_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(serialized_json)
        except FileExistsError:
            raise EvidenceValidationError("OUTPUT_FILE_ALREADY_EXISTS: Output file already exists")

        # Static summary only: strictly counts and status (never leaks output path or private tokens)
        print(
            f"VALIDATION_COMPLETE: validated_candidates={result['summary']['validated_candidates']} "
            f"quarantined_proposals={result['summary']['quarantined_proposals']}"
        )
        return 0
    except EvidenceValidationError as e:
        sys.stderr.write(f"VALIDATION_ERROR: {str(e)}\n")
        return 1
    except Exception:
        sys.stderr.write("FATAL_ERROR: CLI_EXECUTION_FAILED\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
