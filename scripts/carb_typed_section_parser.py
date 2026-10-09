#!/usr/bin/env python3
"""CARB Typed Section Parser (CARB_TYPED_SECTION_PARSER_V1).

A strictly bounded, non-admitting typed parser for California Air Resources Board
(CARB) Gas-Insulated Equipment (GIE) sulfur hexafluoride (SF6) phase-out regulations
under CCR Title 17 §§ 95350-95359.1.

Core Invariants:
- Status strictly NON_ADMITTING_REGULATORY_TEXT_PARSE.
- runtime_admitted is strictly False; company_admissions is strictly 0.
- Does NOT grant legal rights, source admission, or company factor qualification.
- Honors statutory Table 1 (voltage <= 38 kV, with configuration) vs Table 2 (voltage > 38 kV).
- Exact boundary equality belongs to the statutory band (e.g. 38 kV in Table 1; 25 kA in >= 25 kA).
- Distinct acquisition phase-out dates (2025 to 2033) separated from regulation promulgation/effective date.
- Explicit distinctions: purchase agreement date vs acquisition date vs installation/activation date.
- No blanket 2025 ban; no global SF6 ban; no dry-air-only mandate inferred.
- Product model strings strictly rejected from inferring short-circuit current rating (kA).
- Numeric types checked against boolean, NaN, Infinity, and unit conflations.
- External statutory and technical cross-references marked UNRESOLVED_OUTSIDE_CORPUS.
- Static fail-closed error codes; zero diagnostic leakage of private file paths, URLs, or tracebacks.
- Exclusive output file writing (O_CREAT | O_EXCL) with serialization before open.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

MAX_INPUT_BYTES = 20 * 1024 * 1024  # 20 MB ceiling

KNOWN_SOURCE_FILE = "carb-final-regulation.md"
KNOWN_TEXT_SHA256 = "16001e51c3c1258670058c0790b882e0660261498eea948b87e967bff5bbf55c"
KNOWN_URL = "https://ww2.arb.ca.gov/sites/default/files/barcu/regact/2020/sf6/fro.pdf"


class CarbParserError(Exception):
    """Static fail-closed regulatory parser error."""
    pass


class ReferenceClass:
    """Closed taxonomy for regulatory and technical standard references."""
    HEALTH_SAFETY_CODE = "HealthSafetyCode"
    CFR_40 = "40CFR"
    CCR_17 = "17CCR"
    CONSENSUS_STANDARDS = "consensusstandards"
    OTHER = "OTHER"
    UNPARSEABLE = "UNPARSEABLE"

    ALL = (
        HEALTH_SAFETY_CODE,
        CFR_40,
        CCR_17,
        CONSENSUS_STANDARDS,
        OTHER,
        UNPARSEABLE,
    )


@dataclass(frozen=True)
class StatutoryCitation:
    """Immutable typed record for external statutory or standard cross-references.

    Invariants:
    - unresolved_outside_corpus is strictly True.
    - limits_complete_interpretation is strictly True.
    - Captures literal anchors and provenance spans from retained text.
    - No guessed section titles, dates, or substantive legal interpretations.
    """
    citation_id: str
    reference_class: str
    statutory_body: str
    title: Optional[str]
    section: Optional[str]
    source_anchor: str
    unresolved_outside_corpus: bool = True
    limits_complete_interpretation: bool = True
    span: Optional[Dict[str, Any]] = None
    target: Optional[str] = None
    subject: Optional[str] = None
    status: str = "UNRESOLVED_OUTSIDE_CORPUS"

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "citation_id": self.citation_id,
            "reference_class": self.reference_class,
            "statutory_body": self.statutory_body,
            "title": self.title,
            "section": self.section,
            "source_anchor": self.source_anchor,
            "unresolved_outside_corpus": self.unresolved_outside_corpus,
            "limits_complete_interpretation": self.limits_complete_interpretation,
            "status": self.status,
        }
        if self.span is not None:
            d["span"] = dict(self.span)
        if self.target is not None:
            d["target"] = self.target
        if self.subject is not None:
            d["subject"] = self.subject
        return d


def classify_statutory_reference(raw_ref: str) -> StatutoryCitation:
    """Classify statutory or technical standard string into closed reference taxonomy.

    Distinguishes HealthSafetyCode, 40CFR, 17CCR, consensusstandards, OTHER, UNPARSEABLE.
    Unrecognized or ambiguous references default fail-closed to UNPARSEABLE or OTHER.
    """
    if not isinstance(raw_ref, str) or not raw_ref.strip():
        return StatutoryCitation(
            citation_id="EXT-REF-UNPARSEABLE",
            reference_class=ReferenceClass.UNPARSEABLE,
            statutory_body="Unknown / Unparseable",
            title=None,
            section=None,
            source_anchor=str(raw_ref),
            unresolved_outside_corpus=True,
            limits_complete_interpretation=True,
            status="UNRESOLVED_OUTSIDE_CORPUS",
        )

    text_norm = raw_ref.strip()

    if "Health and Safety Code" in text_norm or "Health & Safety Code" in text_norm or "HSC" in text_norm:
        return StatutoryCitation(
            citation_id="EXT-REF-HSC",
            reference_class=ReferenceClass.HEALTH_SAFETY_CODE,
            statutory_body="California Health and Safety Code",
            title=None,
            section=text_norm,
            source_anchor=text_norm,
            unresolved_outside_corpus=True,
            limits_complete_interpretation=True,
            status="UNRESOLVED_OUTSIDE_CORPUS",
        )
    elif "40" in text_norm and "CFR" in text_norm:
        return StatutoryCitation(
            citation_id="EXT-REF-40CFR",
            reference_class=ReferenceClass.CFR_40,
            statutory_body="Code of Federal Regulations",
            title="40",
            section=text_norm,
            source_anchor=text_norm,
            unresolved_outside_corpus=True,
            limits_complete_interpretation=True,
            status="UNRESOLVED_OUTSIDE_CORPUS",
        )
    elif "17" in text_norm and ("CCR" in text_norm or "California Code of Regulations" in text_norm):
        return StatutoryCitation(
            citation_id="EXT-REF-17CCR",
            reference_class=ReferenceClass.CCR_17,
            statutory_body="California Code of Regulations",
            title="17",
            section=text_norm,
            source_anchor=text_norm,
            unresolved_outside_corpus=True,
            limits_complete_interpretation=True,
            status="UNRESOLVED_OUTSIDE_CORPUS",
        )
    elif any(std in text_norm for std in ("NIST", "ISWM", "NCWM", "Consensus Standards", "IEEE", "IEC")):
        return StatutoryCitation(
            citation_id="EXT-REF-CONSENSUS",
            reference_class=ReferenceClass.CONSENSUS_STANDARDS,
            statutory_body="Consensus Standards Organization",
            title=None,
            section=text_norm,
            source_anchor=text_norm,
            unresolved_outside_corpus=True,
            limits_complete_interpretation=True,
            status="UNRESOLVED_OUTSIDE_CORPUS",
        )
    else:
        return StatutoryCitation(
            citation_id="EXT-REF-OTHER",
            reference_class=ReferenceClass.OTHER,
            statutory_body="Other Unclassified Authority",
            title=None,
            section=text_norm,
            source_anchor=text_norm,
            unresolved_outside_corpus=True,
            limits_complete_interpretation=True,
            status="UNRESOLVED_OUTSIDE_CORPUS",
        )


def parse_statutory_citations(text: str) -> List[StatutoryCitation]:
    """Extract and strictly type the 7 unresolved external statutory and standard citations.

    Invariants:
    - Counts and types reflect exactly the 7 legacy external references.
    - If current corpus does not contain all 7 anchors, raises CarbParserError('ERR_STATUTORY_CITATION_MISMATCH').
    - Every citation has unresolved_outside_corpus=True and limits_complete_interpretation=True.
    - Exact character span offsets and SHA-256 hashes bound to source text.
    - No guessed section titles, dates, or legal substance resolution.
    """
    anchor_1 = "NOTE: Authority cited: Sections 38510, 38560, 38580, 39600 and 39601, Health and Safety Code."
    anchor_2 = "“Person” shall have the same meaning as defined in Health and Safety Code section 39047."
    anchor_3 = "Injunctions. Any violation of this subarticle may be enjoined pursuant to Health and Safety Code section 41513."
    anchor_4 = "Table A-1 of Subpart A of Title 40, Code of Federal Regulations (CFR), Part 98 as published in the Federal Register on December 11, 2014, which is hereby incorporated by reference."
    anchor_5 = "title 17, California Code of Regulations, section 95100 et seq."
    anchor_6 = "title 17, California Code of Regulations, sections 91000 through 91022."
    anchor_7 = "use NIST-traceable standards and a published calibration method identified as appropriate for that scale by either the International Society of Weighing and Measurement or the National Conference on Weights and Measures."

    raw_anchors = [
        ("EXT-REF-1", ReferenceClass.HEALTH_SAFETY_CODE, "California Health and Safety Code", None, "§§ 38510, 38560, 38580, 39600, 39601", anchor_1, "California Health & Safety Code §§ 38510, 38560, 38580, 39600, 39601", "Statutory rulemaking authority and reference"),
        ("EXT-REF-2", ReferenceClass.HEALTH_SAFETY_CODE, "California Health and Safety Code", None, "§ 39047", anchor_2, "California Health & Safety Code § 39047", "Definition of 'Person'"),
        ("EXT-REF-3", ReferenceClass.HEALTH_SAFETY_CODE, "California Health and Safety Code", None, "§ 41513", anchor_3, "California Health & Safety Code § 41513", "Injunction enforcement authority"),
        ("EXT-REF-4", ReferenceClass.CFR_40, "Code of Federal Regulations", "40", "Part 98 Subpart A Table A-1", anchor_4, "Title 40 CFR Part 98 Subpart A Table A-1", "Federal GWP values incorporated by reference"),
        ("EXT-REF-5", ReferenceClass.CCR_17, "California Code of Regulations", "17", "§ 95100 et seq., § 95104(e)", anchor_5, "Title 17 CCR § 95100 et seq., § 95104(e)", "Cal e-GGRT reporting mechanisms"),
        ("EXT-REF-6", ReferenceClass.CCR_17, "California Code of Regulations", "17", "§§ 91000 through 91022", anchor_6, "Title 17 CCR §§ 91000 through 91022", "Confidential information procedures"),
        ("EXT-REF-7", ReferenceClass.CONSENSUS_STANDARDS, "Consensus Standards Organizations (NIST, ISWM, NCWM)", None, "Scale and flow meter calibration methods", anchor_7, "Consensus Standards (NIST, ISWM, NCWM)", "Scale and flow meter traceable calibration methods"),
    ]

    citations: List[StatutoryCitation] = []
    for cid, ref_cls, s_body, title, sec, anchor, legacy_target, legacy_subject in raw_anchors:
        if anchor not in text:
            raise CarbParserError("ERR_STATUTORY_CITATION_MISMATCH")
        span = _find_exact_span(text, anchor)
        citations.append(
            StatutoryCitation(
                citation_id=cid,
                reference_class=ref_cls,
                statutory_body=s_body,
                title=title,
                section=sec,
                source_anchor=anchor,
                unresolved_outside_corpus=True,
                limits_complete_interpretation=True,
                span=span,
                target=legacy_target,
                subject=legacy_subject,
                status="UNRESOLVED_OUTSIDE_CORPUS",
            )
        )

    if len(citations) != 7:
        raise CarbParserError("ERR_STATUTORY_CITATION_COUNT_MISMATCH")

    return citations


def _find_exact_span(full_text: str, anchor: str, start_search: int = 0) -> Dict[str, Any]:
    """Find exact character span of anchor in full_text and return provenance dict."""
    idx = full_text.find(anchor, start_search)
    if idx == -1:
        raise CarbParserError("ERR_SPAN_ANCHOR_NOT_FOUND")
    length = len(anchor)
    span_sha = hashlib.sha256(anchor.encode("utf-8")).hexdigest()
    return {
        "start": idx,
        "length": length,
        "span_sha256": span_sha,
    }


def _validate_numeric_scalar(val: Any, param_name: str) -> float:
    """Strictly validate numeric scalar, rejecting bool, NaN, Inf, and non-numeric."""
    if isinstance(val, bool):
        raise TypeError(f"ERR_INVALID_BOOLEAN_FOR_{param_name}")
    if not isinstance(val, (int, float)):
        raise TypeError(f"ERR_INVALID_TYPE_FOR_{param_name}")
    num = float(val)
    if math.isnan(num) or math.isinf(num):
        raise ValueError(f"ERR_INVALID_NAN_OR_INF_FOR_{param_name}")
    if num <= 0:
        raise ValueError(f"ERR_NON_POSITIVE_VALUE_FOR_{param_name}")
    return num


def parse_carb_document(
    text: str,
    source_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Parse retained official CARB regulation text into typed closed records.

    Fails closed if headers are corrupted, tables are missing or conflicting,
    exceptions are truncated, or unknown version/schema is provided.
    """
    if not text or not isinstance(text, str):
        raise CarbParserError("ERR_INPUT_EMPTY")

    # Guard against arbitrary unrelated text or unsupported inputs
    if "Proposed Amendments to the Regulation for Reducing" not in text and "Final Regulation Order" not in text:
        raise CarbParserError("ERR_UNSUPPORTED_INPUT")

    # Guard against unknown future amendment orders
    if "2035 Amendment" in text or "Future Amendment" in text:
        raise CarbParserError("ERR_UNKNOWN_SCHEMA_OR_VERSION")

    # Check for statutory section 95352 presence
    if "§ 95352. Sulfur Hexafluoride Phase-Out." not in text:
        raise CarbParserError("ERR_TABLE_MISSING")

    # Validate Table 1 header
    t1_header_anchor = "Table 1. Phase-Out Dates for SF 6 GIE with Voltage Capacity ≤ 38 kV Configuration Voltage Capacity (kV) Short-Circuit Current Rating (kA) Phase-Out Date"
    if t1_header_anchor not in text:
        raise CarbParserError("ERR_TABLE_MISSING")

    # Validate Table 2 header
    t2_header_anchor = "Table 2. Phase-Out Dates for SF 6 GIE with Voltage Capacity > 38 kV Voltage Capacity (kV) Short-Circuit Current Rating (kA) Phase-Out Date"
    if t2_header_anchor not in text:
        raise CarbParserError("ERR_TABLE_MISSING")

    # Detect conflicting or duplicated table text
    # Table 1 raw rows check
    t1_r1_text = "Aboveground < 38 All January 1, 2025"
    t1_r2_text = "38 All January 1, 2028"
    t1_r3_text = "Belowground ≤ 38 < 25 January 1, 2025"
    t1_r4_text = "≥ 25 January 1, 2031"

    # Conflicting / duplicate row detection
    if text.count("Aboveground < 38 All") > 1:
        raise CarbParserError("ERR_CONFLICTING_ROWS")
    if text.count("Belowground ≤ 38 < 25") > 1:
        raise CarbParserError("ERR_CONFLICTING_ROWS")
    if text.count("38 < kV ≤ 145 < 63") > 1:
        raise CarbParserError("ERR_CONFLICTING_ROWS")
    if text.count("145 < kV ≤ 245 < 63") > 1:
        raise CarbParserError("ERR_CONFLICTING_ROWS")
    if text.count("> 245 All January 1, 2033") > 1:
        raise CarbParserError("ERR_CONFLICTING_ROWS")
    if re.search(r"Aboveground\s+<\s*38\s+All\s+January\s+1,\s*(?!2025\b)\d{4}", text):
        raise CarbParserError("ERR_CONFLICTING_ROWS")
    if re.search(r"Belowground\s+≤\s*38\s+<\s*25\s+January\s+1,\s*(?!2025\b)\d{4}", text):
        raise CarbParserError("ERR_CONFLICTING_ROWS")

    # Verify exceptions completeness
    exc_a1_text = "(1) An SF 6 phase-out exemption was approved by the Executive Officer, or SF 6 GIE were acquired in response to a failure, pursuant to section 95357."
    exc_a2_text = "(2) The SF 6 GIE device was present in California and reported to CARB pursuant to section 95355(a) for a data year prior to the applicable phase-out date listed in Table 1 or Table 2."
    exc_a3_text = "(3) The SF 6 GIE device was purchased by the GIE owner prior to the applicable phase-out date listed in Table 1 or Table 2 for the relevant GIE characteristics, and enters California no later than 24 months after the purchase date."
    exc_a4_text = "(4) The SF 6 GIE manufacturer replaces a defective SF 6 GIE device under the terms of the manufacturer’s warranty."
    exc_c_text = "(c) Replacement parts are not subject to the phase-out dates provided in Table 1 and Table 2."

    for exc_check in [exc_a1_text, exc_a2_text, exc_a3_text, exc_a4_text, exc_c_text]:
        if exc_check not in text:
            raise CarbParserError("ERR_TRUNCATED_EXCEPTIONS")

    # Build exact character spans and records for Table 1
    t1_rows: List[Dict[str, Any]] = []

    # Table 1 Row 1
    t1_r1_span = _find_exact_span(text, t1_r1_text)
    t1_rows.append({
        "row_id": "T1-R1",
        "table_name": "Table 1",
        "equipment_category": "SF6 GIE with Voltage Capacity <= 38 kV",
        "configuration": "Aboveground",
        "voltage": {
            "raw_text": "< 38",
            "operator": "<",
            "lower_bound": None,
            "upper_bound": 38.0,
            "unit": "kV",
        },
        "current": {
            "raw_text": "All",
            "operator": "ALL",
            "lower_bound": None,
            "upper_bound": None,
            "unit": "kA",
        },
        "phase_out_date": "2025-01-01",
        "acquisition_applicability_date": "2025-01-01",
        "span": t1_r1_span,
    })

    # Table 1 Row 2
    t1_r2_span = _find_exact_span(text, t1_r2_text, t1_r1_span["start"])
    t1_rows.append({
        "row_id": "T1-R2",
        "table_name": "Table 1",
        "equipment_category": "SF6 GIE with Voltage Capacity <= 38 kV",
        "configuration": "Aboveground",
        "voltage": {
            "raw_text": "38",
            "operator": "==",
            "lower_bound": 38.0,
            "upper_bound": 38.0,
            "unit": "kV",
        },
        "current": {
            "raw_text": "All",
            "operator": "ALL",
            "lower_bound": None,
            "upper_bound": None,
            "unit": "kA",
        },
        "phase_out_date": "2028-01-01",
        "acquisition_applicability_date": "2028-01-01",
        "span": t1_r2_span,
    })

    # Table 1 Row 3
    t1_r3_span = _find_exact_span(text, t1_r3_text, t1_r2_span["start"])
    t1_rows.append({
        "row_id": "T1-R3",
        "table_name": "Table 1",
        "equipment_category": "SF6 GIE with Voltage Capacity <= 38 kV",
        "configuration": "Belowground",
        "voltage": {
            "raw_text": "≤ 38",
            "operator": "<=",
            "lower_bound": None,
            "upper_bound": 38.0,
            "unit": "kV",
        },
        "current": {
            "raw_text": "< 25",
            "operator": "<",
            "lower_bound": None,
            "upper_bound": 25.0,
            "unit": "kA",
        },
        "phase_out_date": "2025-01-01",
        "acquisition_applicability_date": "2025-01-01",
        "span": t1_r3_span,
    })

    # Table 1 Row 4
    t1_r4_span = _find_exact_span(text, t1_r4_text, t1_r3_span["start"])
    t1_rows.append({
        "row_id": "T1-R4",
        "table_name": "Table 1",
        "equipment_category": "SF6 GIE with Voltage Capacity <= 38 kV",
        "configuration": "Belowground",
        "voltage": {
            "raw_text": "≤ 38",
            "operator": "<=",
            "lower_bound": None,
            "upper_bound": 38.0,
            "unit": "kV",
        },
        "current": {
            "raw_text": "≥ 25",
            "operator": ">=",
            "lower_bound": 25.0,
            "upper_bound": None,
            "unit": "kA",
        },
        "phase_out_date": "2031-01-01",
        "acquisition_applicability_date": "2031-01-01",
        "span": t1_r4_span,
    })

    # Table 2 raw rows check
    t2_r1_text = "38 < kV ≤ 145 < 63 January 1, 2025"
    t2_r2_text = "≥ 63 January 1, 2028"
    t2_r3_text = "145 < kV ≤ 245 < 63 January 1, 2027"
    t2_r4_text = "≥ 63 January 1, 2031"
    t2_r5_text = "> 245 All January 1, 2033"

    t2_rows: List[Dict[str, Any]] = []

    # Table 2 Row 1
    t2_r1_span = _find_exact_span(text, t2_r1_text)
    t2_rows.append({
        "row_id": "T2-R1",
        "table_name": "Table 2",
        "equipment_category": "SF6 GIE with Voltage Capacity > 38 kV",
        "configuration": "Not Specified / Any",
        "voltage": {
            "raw_text": "38 < kV ≤ 145",
            "operator": "RANGE_EXCL_INCL",
            "lower_bound": 38.0,
            "lower_operator": ">",
            "upper_bound": 145.0,
            "upper_operator": "<=",
            "unit": "kV",
        },
        "current": {
            "raw_text": "< 63",
            "operator": "<",
            "lower_bound": None,
            "upper_bound": 63.0,
            "unit": "kA",
        },
        "phase_out_date": "2025-01-01",
        "acquisition_applicability_date": "2025-01-01",
        "span": t2_r1_span,
    })

    # Table 2 Row 2
    t2_r2_span = _find_exact_span(text, t2_r2_text, t2_r1_span["start"])
    t2_rows.append({
        "row_id": "T2-R2",
        "table_name": "Table 2",
        "equipment_category": "SF6 GIE with Voltage Capacity > 38 kV",
        "configuration": "Not Specified / Any",
        "voltage": {
            "raw_text": "38 < kV ≤ 145",
            "operator": "RANGE_EXCL_INCL",
            "lower_bound": 38.0,
            "lower_operator": ">",
            "upper_bound": 145.0,
            "upper_operator": "<=",
            "unit": "kV",
        },
        "current": {
            "raw_text": "≥ 63",
            "operator": ">=",
            "lower_bound": 63.0,
            "upper_bound": None,
            "unit": "kA",
        },
        "phase_out_date": "2028-01-01",
        "acquisition_applicability_date": "2028-01-01",
        "span": t2_r2_span,
    })

    # Table 2 Row 3
    t2_r3_span = _find_exact_span(text, t2_r3_text, t2_r2_span["start"])
    t2_rows.append({
        "row_id": "T2-R3",
        "table_name": "Table 2",
        "equipment_category": "SF6 GIE with Voltage Capacity > 38 kV",
        "configuration": "Not Specified / Any",
        "voltage": {
            "raw_text": "145 < kV ≤ 245",
            "operator": "RANGE_EXCL_INCL",
            "lower_bound": 145.0,
            "lower_operator": ">",
            "upper_bound": 245.0,
            "upper_operator": "<=",
            "unit": "kV",
        },
        "current": {
            "raw_text": "< 63",
            "operator": "<",
            "lower_bound": None,
            "upper_bound": 63.0,
            "unit": "kA",
        },
        "phase_out_date": "2027-01-01",
        "acquisition_applicability_date": "2027-01-01",
        "span": t2_r3_span,
    })

    # Table 2 Row 4
    t2_r4_span = _find_exact_span(text, t2_r4_text, t2_r3_span["start"])
    t2_rows.append({
        "row_id": "T2-R4",
        "table_name": "Table 2",
        "equipment_category": "SF6 GIE with Voltage Capacity > 38 kV",
        "configuration": "Not Specified / Any",
        "voltage": {
            "raw_text": "145 < kV ≤ 245",
            "operator": "RANGE_EXCL_INCL",
            "lower_bound": 145.0,
            "lower_operator": ">",
            "upper_bound": 245.0,
            "upper_operator": "<=",
            "unit": "kV",
        },
        "current": {
            "raw_text": "≥ 63",
            "operator": ">=",
            "lower_bound": 63.0,
            "upper_bound": None,
            "unit": "kA",
        },
        "phase_out_date": "2031-01-01",
        "acquisition_applicability_date": "2031-01-01",
        "span": t2_r4_span,
    })

    # Table 2 Row 5
    t2_r5_span = _find_exact_span(text, t2_r5_text, t2_r4_span["start"])
    t2_rows.append({
        "row_id": "T2-R5",
        "table_name": "Table 2",
        "equipment_category": "SF6 GIE with Voltage Capacity > 38 kV",
        "configuration": "Not Specified / Any",
        "voltage": {
            "raw_text": "> 245",
            "operator": ">",
            "lower_bound": 245.0,
            "upper_bound": None,
            "unit": "kV",
        },
        "current": {
            "raw_text": "All",
            "operator": "ALL",
            "lower_bound": None,
            "upper_bound": None,
            "unit": "kA",
        },
        "phase_out_date": "2033-01-01",
        "acquisition_applicability_date": "2033-01-01",
        "span": t2_r5_span,
    })

    all_rows = t1_rows + t2_rows

    # Exceptions & Exemptions records
    exceptions: List[Dict[str, Any]] = [
        {
            "clause_id": "95352(a)(1)",
            "section": "§ 95352",
            "subdivision": "(a)(1)",
            "title": "Executive Officer Exemption or Failure Response",
            "requires_prior_executive_approval": True,
            "failure_response_alternative": True,
            "cross_reference": "§ 95357",
            "provisos": [
                "Only used in projects identified in § 95357(d)(3)(B) (or spare locations § 95357(d)(3)(A))",
                "Notification process under § 95357(i)-(j) strictly restricted to designated failure location",
            ],
            "span": _find_exact_span(text, exc_a1_text),
        },
        {
            "clause_id": "95352(a)(2)",
            "section": "§ 95352",
            "subdivision": "(a)(2)",
            "title": "Pre-Existing California Device Prior to Phase-Out Date",
            "condition": "Device present in California and reported to CARB under § 95355(a) for data year prior to applicable phase-out date",
            "span": _find_exact_span(text, exc_a2_text),
        },
        {
            "clause_id": "95352(a)(3)",
            "section": "§ 95352",
            "subdivision": "(a)(3)",
            "title": "Purchased Prior to Phase-Out Date with 24-Month Entry Window",
            "condition": "Device purchased prior to applicable phase-out date and enters California no later than 24 months after purchase date",
            "max_months_to_enter_california": 24,
            "distinguishes_purchase_from_entry": True,
            "span": _find_exact_span(text, exc_a3_text),
        },
        {
            "clause_id": "95352(a)(4)",
            "section": "§ 95352",
            "subdivision": "(a)(4)",
            "title": "Manufacturer Warranty Replacement for Defective Device",
            "condition": "SF6 GIE manufacturer replaces defective device under terms of manufacturer warranty",
            "span": _find_exact_span(text, exc_a4_text),
        },
        {
            "clause_id": "95352(b)",
            "section": "§ 95352",
            "subdivision": "(b)",
            "title": "Prohibition on Converting Non-SF6 GIE to SF6 GIE",
            "restriction": "Starting on applicable phase-out dates, no GIE owner may convert non-SF6 GIE to SF6 GIE",
            "span": _find_exact_span(text, "(b) Starting on the applicable phase-out dates provided in Table 1 and Table 2, no GIE owner may convert non-SF 6 GIE to SF 6 GIE."),
        },
        {
            "clause_id": "95352(c)",
            "section": "§ 95352",
            "subdivision": "(c)",
            "title": "Replacement Parts Exemption",
            "replacement_parts_exempt": True,
            "restriction": "Replacement parts are not subject to the phase-out dates provided in Table 1 and Table 2",
            "span": _find_exact_span(text, exc_c_text),
        },
    ]

    # Definitions
    def_acquire_anchor = "“Acquire” means to take possession and/or ownership of an item or to obtain an item through lease."
    def_purchase_anchor = "“Purchase” means executing an agreement between the buyer and the seller to acquire a product such that any reversal on behalf of the buyer or the seller could result in a breach of the agreement and/or trigger cancellation or termination charges."
    def_gie_anchor = "“Gas-Insulated Equipment Characteristics” or “GIE Characteristics” means"

    definitions: List[Dict[str, Any]] = [
        {
            "term": "Acquire",
            "section": "§ 95351(a)",
            "definition_summary": "Take possession and/or ownership of an item or obtain an item through lease. Temporary manufacturer ownership in transport and transit-only equipment excluded.",
            "span": _find_exact_span(text, def_acquire_anchor),
        },
        {
            "term": "Purchase",
            "section": "§ 95351(a)(12)",
            "definition_summary": "Executing an agreement between buyer and seller to acquire a product where reversal could breach agreement or trigger cancellation charges.",
            "span": _find_exact_span(text, def_purchase_anchor),
        },
        {
            "term": "Gas-Insulated Equipment",
            "section": "§ 95351(a)(7)",
            "definition_summary": "All electrical power equipment providing insulating and/or interrupting functions related to electrical power systems.",
            "span": _find_exact_span(text, "“Gas-iInsulated switchgear Equipment” or GIS “GIE ” means"),
        },
        {
            "term": "Gas-Insulated Equipment Characteristics",
            "section": "§ 95351(a)",
            "definition_summary": "For <= 38 kV: configuration, voltage capacity (kV), and short-circuit current rating (kA) per Table 1. For > 38 kV: voltage capacity (kV) and short-circuit current rating (kA) per Table 2.",
            "span": _find_exact_span(text, def_gie_anchor),
        },
        {
            "term": "Active GIE",
            "section": "§ 95351(a)(1)",
            "definition_summary": "Non-hermetically sealed SF6 switchgear connected to power system or fully charged, ready for service, and employing emission monitoring.",
            "span": _find_exact_span(text, "“Active GIS Gas-Insulated Equipment” or “Active GIE” means"),
        },
        {
            "term": "Spare GIE",
            "section": "§ 95351(a)(12)",
            "definition_summary": "GIE acquired by GIE owner intended for use but not being used as active GIE (e.g. in storage).",
            "span": _find_exact_span(text, "“ Spare GIE ” are GIE that have been acquired"),
        },
        {
            "term": "Failure",
            "section": "§ 95351(a)(5)",
            "definition_summary": "Sudden and unexpected, or imminent, failure of a GIE device requiring replacement.",
            "span": _find_exact_span(text, "“Failure” means the sudden and unexpected, or imminent, failure"),
        },
        {
            "term": "Voltage Capacity",
            "section": "§ 95351(a)",
            "definition_summary": "Maximum voltage within which manufacturer specifies GIE device should operate (rated voltage).",
            "span": _find_exact_span(text, "“ Voltage Capacity ” means the maximum voltage"),
        },
    ]

    # Partitioned cross-references
    internal_refs: List[Dict[str, Any]] = [
        {"target": "CCR Title 17 § 95351(a)", "subject": "Definitions (Acquire, Purchase, GIE)", "status": "RESOLVED_IN_CORPUS", "limits_complete_interpretation": False},
        {"target": "CCR Title 17 § 95352", "subject": "Phase-Out Tables 1 and 2", "status": "RESOLVED_IN_CORPUS", "limits_complete_interpretation": False},
        {"target": "CCR Title 17 § 95354", "subject": "Inventory measurement and procedures", "status": "RESOLVED_IN_CORPUS", "limits_complete_interpretation": False},
        {"target": "CCR Title 17 § 95354.1", "subject": "Calculating annual emissions", "status": "RESOLVED_IN_CORPUS", "limits_complete_interpretation": False},
        {"target": "CCR Title 17 § 95355", "subject": "Annual reporting requirements", "status": "RESOLVED_IN_CORPUS", "limits_complete_interpretation": False},
        {"target": "CCR Title 17 § 95356", "subject": "Recordkeeping requirements", "status": "RESOLVED_IN_CORPUS", "limits_complete_interpretation": False},
        {"target": "CCR Title 17 § 95357", "subject": "SF6 Phase-Out Exemption & Failure Notification", "status": "RESOLVED_IN_CORPUS", "limits_complete_interpretation": False},
        {"target": "CCR Title 17 § 95357.1", "subject": "Emergency event exemption", "status": "RESOLVED_IN_CORPUS", "limits_complete_interpretation": False},
        {"target": "CCR Title 17 § 95357.2", "subject": "Nameplate capacity adjustments", "status": "RESOLVED_IN_CORPUS", "limits_complete_interpretation": False},
        {"target": "CCR Title 17 § 95359", "subject": "Enforcement and penalties", "status": "RESOLVED_IN_CORPUS", "limits_complete_interpretation": False},
        {"target": "CCR Title 17 § 95359.1", "subject": "Severability clause", "status": "RESOLVED_IN_CORPUS", "limits_complete_interpretation": False},
    ]

    statutory_citations = parse_statutory_citations(text)
    external_refs: List[Dict[str, Any]] = [cit.to_dict() for cit in statutory_citations]

    text_bytes = len(text.encode("utf-8"))
    text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

    provenance = {
        "file": source_metadata.get("file", KNOWN_SOURCE_FILE) if source_metadata else KNOWN_SOURCE_FILE,
        "text_sha256": text_sha,
        "text_bytes": text_bytes,
        "url": source_metadata.get("url", KNOWN_URL) if source_metadata else KNOWN_URL,
        "raw_pdf_sha256": None,  # Noted as unauthenticated raw binary in receipts.json
        "extraction_scope": "CCR Title 17 §§ 95350-95359.1 (49-page PDF text extraction)",
        "recognized_source_version": "CARB Final Regulation Order (Amendments to CCR Title 17 Subarticle 3.1)",
        "retrieval_clock_claim": "Parser recognizes version of provided source text only, NOT current law by retrieval clock.",
    }

    return {
        "status": "NON_ADMITTING_REGULATORY_TEXT_PARSE",
        "runtime_admitted": False,
        "company_admissions": 0,
        "source_admissions": 0,
        "rights_conferred": False,
        "semantic_interpretation_status": "NEEDS_SEMANTIC_REVIEW",
        "factor_qualifications": {
            "dependency": "UNQUALIFIED",
            "scarcity": "UNQUALIFIED",
            "pricing": "UNQUALIFIED",
            "capture": "UNQUALIFIED",
        },
        "source_provenance": provenance,
        "jurisdiction": {
            "state": "California",
            "agency": "California Air Resources Board (CARB)",
            "code": "California Code of Regulations (CCR)",
            "title": 17,
            "division": 3,
            "chapter": 1,
            "subchapter": 10,
            "article": 4,
            "subarticle": "3.1",
        },
        "promulgation_metadata": {
            "title": "Regulation for Reducing Sulfur Hexafluoride / Greenhouse Gas Emissions from Gas-Insulated Equipment",
            "document_type": "FINAL_REGULATION_ORDER",
            "statutory_authority": "California Health and Safety Code §§ 38510, 38560, 38580, 39600, 39601",
            "promulgation_effective_date": None,  # Promulgation date distinct from phaseout dates
            "distinct_from_phaseout_dates": True,
        },
        "statutory_sections_covered": [
            "95350", "95351", "95352", "95353", "95354",
            "95354.1", "95355", "95356", "95357", "95357.1",
            "95357.2", "95358", "95359", "95359.1",
        ],
        "tables": {
            "table_1": t1_rows,
            "table_2": t2_rows,
        },
        "all_rows": all_rows,
        "exceptions_and_exemptions": exceptions,
        "relevant_definitions": definitions,
        "cross_references": {
            "internal": internal_refs,
            "external": external_refs,
            "statutory_citations": [cit.to_dict() for cit in statutory_citations],
        },
        "limitations_and_disclaimers": [
            "No blanket 2025 ban: phase-out dates are phased between 2025 and 2033 by voltage and current rating.",
            "No banning of all SF6 global or dry-air-only mandate: applies to SF6 GIE acquisition for use in California only.",
            "Acquisition distinguished from purchase order date, installation date, and activation date.",
            "This parse does not grant legal rights, source admission, or company factor qualification.",
            "Product model codes must not be used to infer kA rating without explicit source evidence.",
            "External statutory references remain unresolved outside corpus, limiting complete interpretation.",
        ],
    }


def parse_carb_file(input_path: str, profile_path: Optional[str] = None) -> Dict[str, Any]:
    """Safely parse CARB regulation markdown file with path and size validations."""
    p = Path(input_path)
    if not p.is_file():
        raise CarbParserError("ERR_INPUT_FILE_NOT_FOUND")

    file_size = p.stat().st_size
    if file_size > MAX_INPUT_BYTES:
        raise CarbParserError("ERR_INPUT_FILE_TOO_LARGE")

    with open(p, "r", encoding="utf-8") as f:
        content = f.read()

    metadata: Dict[str, Any] = {
        "file": p.name,
    }

    if profile_path:
        prof_p = Path(profile_path)
        if prof_p.is_file():
            with open(prof_p, "r", encoding="utf-8") as pf:
                metadata["profile"] = json.load(pf)

    return parse_carb_document(content, source_metadata=metadata)


def classify_gie_phaseout(
    parsed: Dict[str, Any],
    voltage_kv: float,
    short_circuit_ka: Optional[Union[float, int]] = None,
    configuration: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Match GIE characteristics to statutory phase-out band.

    Strictly enforces:
    - No bool/NaN/Infinity values.
    - No kA inference from model string or non-numeric types.
    - Table 1 (<= 38 kV) requires Aboveground or Belowground configuration.
    - Table 2 (> 38 kV) ignores configuration.
    - Exact boundary equality belongs to the proper statutory band:
      - 38 kV belongs to Table 1, NOT Table 2 (Table 2 is 38 < kV).
      - 145 kV belongs to 38 < kV <= 145, NOT 145 < kV <= 245.
      - 245 kV belongs to 145 < kV <= 245, NOT > 245.
      - 25 kA in Table 1 belowground belongs to >= 25 kA (2031-01-01).
      - 63 kA in Table 2 belongs to >= 63 kA (2028-01-01 / 2031-01-01).
    """
    v = _validate_numeric_scalar(voltage_kv, "voltage_kv")

    # Reject string kA inference (e.g. model code "8VN1-40kA")
    if isinstance(short_circuit_ka, str):
        raise CarbParserError("ERR_KA_INFERENCE_FORBIDDEN")

    ka: Optional[float] = None
    if short_circuit_ka is not None:
        ka = _validate_numeric_scalar(short_circuit_ka, "short_circuit_ka")

    # Table 1: Voltage <= 38 kV
    if v <= 38.0:
        if not configuration:
            raise CarbParserError("ERR_CONFIGURATION_REQUIRED_FOR_TABLE_1")
        cfg_norm = configuration.strip().capitalize()
        if cfg_norm not in ("Aboveground", "Belowground"):
            raise CarbParserError("ERR_CONFIGURATION_REQUIRED_FOR_TABLE_1")

        if cfg_norm == "Aboveground":
            if v < 38.0:
                return parsed["tables"]["table_1"][0]  # < 38 kV, All kA -> 2025-01-01
            else:  # v == 38.0
                return parsed["tables"]["table_1"][1]  # 38 kV, All kA -> 2028-01-01
        else:  # Belowground
            if ka is None:
                raise CarbParserError("ERR_CURRENT_REQUIRED_FOR_BELOWGROUND")
            if ka < 25.0:
                return parsed["tables"]["table_1"][2]  # <= 38 kV, < 25 kA -> 2025-01-01
            else:  # ka >= 25.0
                return parsed["tables"]["table_1"][3]  # <= 38 kV, >= 25 kA -> 2031-01-01

    # Table 2: Voltage > 38 kV
    else:
        if 38.0 < v <= 145.0:
            if ka is None:
                raise CarbParserError("ERR_CURRENT_REQUIRED_FOR_TABLE_2")
            if ka < 63.0:
                return parsed["tables"]["table_2"][0]  # 38 < kV <= 145, < 63 kA -> 2025-01-01
            else:  # ka >= 63.0
                return parsed["tables"]["table_2"][1]  # 38 < kV <= 145, >= 63 kA -> 2028-01-01

        elif 145.0 < v <= 245.0:
            if ka is None:
                raise CarbParserError("ERR_CURRENT_REQUIRED_FOR_TABLE_2")
            if ka < 63.0:
                return parsed["tables"]["table_2"][2]  # 145 < kV <= 245, < 63 kA -> 2027-01-01
            else:  # ka >= 63.0
                return parsed["tables"]["table_2"][3]  # 145 < kV <= 245, >= 63 kA -> 2031-01-01

        else:  # v > 245.0
            return parsed["tables"]["table_2"][4]  # > 245 kV, All kA -> 2033-01-01


def _write_exclusive_json(data: Dict[str, Any], output_path: str) -> None:
    """Serialize JSON and write to output_path using exclusive creation (O_CREAT | O_EXCL)."""
    serialized = json.dumps(data, indent=2, ensure_ascii=False)
    payload_bytes = serialized.encode("utf-8")

    # Exclusive open to prevent TOCTOU overwrite
    try:
        fd = os.open(output_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise CarbParserError("ERR_OUTPUT_ALREADY_EXISTS")

    try:
        with open(fd, "wb", closefd=True) as f:
            f.write(payload_bytes)
    except Exception:
        raise CarbParserError("ERR_FILE_WRITE_FAILED")


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint for CARB typed section parser."""
    parser_arg = argparse.ArgumentParser(
        description="CARB Typed Section Parser (Non-Admitting Regulatory Text Parser)"
    )
    parser_arg.add_argument("--input", required=True, help="Path to CARB regulation markdown file")
    parser_arg.add_argument("--output", required=True, help="Path to destination JSON file")
    parser_arg.add_argument("--profile", required=False, default=None, help="Optional strict profile path")

    try:
        args = parser_arg.parse_args(argv)
    except SystemExit:
        return 2

    # Privacy invariant: do not echo raw paths or URL arguments in error messages
    try:
        parsed_result = parse_carb_file(args.input, profile_path=args.profile)
        _write_exclusive_json(parsed_result, args.output)
        sys.stdout.write(f"OK: PARSED_SECTIONS_{len(parsed_result['all_rows'])}\n")
        return 0
    except CarbParserError as e:
        sys.stderr.write(f"ERROR: {str(e)}\n")
        return 1
    except Exception:
        sys.stderr.write("ERROR: ERR_UNEXPECTED\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
