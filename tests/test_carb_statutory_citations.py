"""Focused tests for CARB Statutory Cross-Reference Typing (CARB_STATUTORY_CROSS_REFERENCE_TYPING_V1).

SYNTHETIC GRAMMAR TESTS ONLY - NOT REAL LEGAL OR PUBLIC RESEARCH EVIDENCE.
Unchanged parser default URLs/version labels (including CLI output) are not
authenticated provenance. Real-corpus integration is separate and unqualified.

Invariants verified:
- Structured StatutoryCitation dataclass records mapped from fixed synthetic grammar input.
- Reference taxonomy distinguishes HealthSafetyCode, 40CFR, 17CCR, consensusstandards, OTHER, UNPARSEABLE.
- Exactly 7 legacy external cross-references typed (no guessed section titles, dates, or legal substance resolution).
- unresolved_outside_corpus=True and limits_complete_interpretation=True bound to all external citations.
- Character spans match exact substrings and SHA-256 hashes in retained markdown.
- Immutability of StatutoryCitation instances.
- Malformed / ambiguous references stay UNPARSEABLE / UNRESOLVED.
- CLI exclusive JSON creation (O_CREAT | O_EXCL) and safe static error handling.
- Zero company admissions (admissions strictly 0) and non-admitting status preserved.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

# Ensure repository root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import tempfile
import unittest
from dataclasses import FrozenInstanceError

from scripts.carb_typed_section_parser import (
    CarbParserError,
    ReferenceClass,
    StatutoryCitation,
    classify_statutory_reference,
    parse_carb_document,
    parse_carb_file,
    parse_statutory_citations,
)

RETAINED_CORPUS_PATH = Path(__file__).resolve().parent / "fixtures" / "carb-parser-synthetic.txt"


class TestCarbStatutoryCitations(unittest.TestCase):
    """Focused test suite for statutory cross-reference typing and taxonomy."""

    @classmethod
    def setUpClass(cls):
        if not RETAINED_CORPUS_PATH.is_file():
            raise FileNotFoundError("SYNTHETIC_FIXTURE_MISSING")
        with open(RETAINED_CORPUS_PATH, "r", encoding="utf-8") as f:
            cls.corpus_text = f.read()
        cls.parsed = parse_carb_document(cls.corpus_text, source_metadata={'id': 'SYNTHETIC-CARB-GRAMMAR', 'file': 'carb-parser-synthetic.txt', 'url': 'https://example.com/synthetic/carb-grammar'})

    def test_dataclass_immutability(self):
        """StatutoryCitation records must be strictly immutable (frozen)."""
        cit = StatutoryCitation(
            citation_id="EXT-REF-TEST",
            reference_class=ReferenceClass.HEALTH_SAFETY_CODE,
            statutory_body="California Health and Safety Code",
            title=None,
            section="§ 39047",
            source_anchor="Health and Safety Code section 39047",
            unresolved_outside_corpus=True,
            limits_complete_interpretation=True,
        )
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            cit.unresolved_outside_corpus = False  # type: ignore

        with self.assertRaises((FrozenInstanceError, AttributeError)):
            cit.section = "tampered"  # type: ignore

    def test_cardinality_and_typing_of_statutory_citations(self):
        """Must produce exactly 7 typed StatutoryCitation records reflecting legacy refs."""
        citations = parse_statutory_citations(self.corpus_text)
        self.assertEqual(len(citations), 7, f"Expected exactly 7 citations, got {len(citations)}")

        for cit in citations:
            self.assertIsInstance(cit, StatutoryCitation)
            self.assertTrue(cit.citation_id.startswith("EXT-REF-"))
            self.assertIn(cit.reference_class, ReferenceClass.ALL)
            self.assertIsInstance(cit.statutory_body, str)
            self.assertTrue(len(cit.statutory_body) > 0)
            self.assertIsInstance(cit.source_anchor, str)
            self.assertTrue(len(cit.source_anchor) > 0)
            self.assertTrue(cit.unresolved_outside_corpus)
            self.assertTrue(cit.limits_complete_interpretation)
            self.assertEqual(cit.status, "UNRESOLVED_OUTSIDE_CORPUS")

    def test_taxonomy_distribution(self):
        """Taxonomy must distinguish HealthSafetyCode (3), 40CFR (1), 17CCR (2), consensusstandards (1)."""
        citations = parse_statutory_citations(self.corpus_text)

        counts = {cls_name: 0 for cls_name in ReferenceClass.ALL}
        for cit in citations:
            counts[cit.reference_class] += 1

        self.assertEqual(counts[ReferenceClass.HEALTH_SAFETY_CODE], 3, "Expected 3 HealthSafetyCode citations")
        self.assertEqual(counts[ReferenceClass.CFR_40], 1, "Expected 1 40CFR citation")
        self.assertEqual(counts[ReferenceClass.CCR_17], 2, "Expected 2 17CCR citations")
        self.assertEqual(counts[ReferenceClass.CONSENSUS_STANDARDS], 1, "Expected 1 consensusstandards citation")
        self.assertEqual(counts[ReferenceClass.OTHER], 0, "Expected 0 OTHER citations in synthetic grammar fixture")
        self.assertEqual(counts[ReferenceClass.UNPARSEABLE], 0, "Expected 0 UNPARSEABLE citations in synthetic grammar fixture")
        self.assertEqual(sum(counts.values()), 7, "Total typed citations must equal 7")

    def test_citation_provenance_and_spans(self):
        """Character spans must match exact anchors and SHA-256 hashes in retained text."""
        citations = parse_statutory_citations(self.corpus_text)
        for cit in citations:
            self.assertIsNotNone(cit.span, f"Span missing for citation {cit.citation_id}")
            span = cit.span
            start = span["start"]
            length = span["length"]
            expected_sha = hashlib.sha256(cit.source_anchor.encode("utf-8")).hexdigest()

            self.assertGreaterEqual(start, 0)
            self.assertEqual(length, len(cit.source_anchor))
            self.assertEqual(span["span_sha256"], expected_sha)
            extracted = self.corpus_text[start : start + length]
            self.assertEqual(extracted, cit.source_anchor)

    def test_backward_compatibility_of_external_references(self):
        """parsed['cross_references']['external'] must preserve legacy fields while adding typed fields."""
        ext_refs = self.parsed["cross_references"]["external"]
        self.assertEqual(len(ext_refs), 7)

        legacy_targets = [
            "California Health & Safety Code §§ 38510, 38560, 38580, 39600, 39601",
            "California Health & Safety Code § 39047",
            "California Health & Safety Code § 41513",
            "Title 40 CFR Part 98 Subpart A Table A-1",
            "Title 17 CCR § 95100 et seq., § 95104(e)",
            "Title 17 CCR §§ 91000 through 91022",
            "Consensus Standards (NIST, ISWM, NCWM)",
        ]

        for i, ref in enumerate(ext_refs):
            self.assertIn("target", ref)
            self.assertIn("subject", ref)
            self.assertEqual(ref["target"], legacy_targets[i])
            self.assertEqual(ref["status"], "UNRESOLVED_OUTSIDE_CORPUS")
            self.assertTrue(ref["limits_complete_interpretation"])
            # Verify new structured fields are present on the record
            self.assertIn("citation_id", ref)
            self.assertIn("reference_class", ref)
            self.assertIn("statutory_body", ref)
            self.assertIn("source_anchor", ref)
            self.assertTrue(ref["unresolved_outside_corpus"])

    def test_malformed_and_ambiguous_references_stay_unparseable(self):
        """Malformed or unknown citations must classify as UNPARSEABLE/OTHER and stay unresolved."""
        malformed_examples = [
            "Unknown Code Section 99999",
            "Fictional Energy Code § 101",
            "Random string with no statutory pattern",
        ]
        for bad_ref in malformed_examples:
            rec = classify_statutory_reference(bad_ref)
            self.assertIn(rec.reference_class, (ReferenceClass.UNPARSEABLE, ReferenceClass.OTHER))
            self.assertTrue(rec.unresolved_outside_corpus)
            self.assertTrue(rec.limits_complete_interpretation)
            self.assertEqual(rec.status, "UNRESOLVED_OUTSIDE_CORPUS")

    def test_zero_company_admissions_and_core_invariants_preserved(self):
        """Parser invariants: runtime_admitted=False, admissions=0, 4 core gates unqualified."""
        self.assertEqual(self.parsed["status"], "NON_ADMITTING_REGULATORY_TEXT_PARSE")
        self.assertFalse(self.parsed["runtime_admitted"])
        self.assertEqual(self.parsed["company_admissions"], 0)
        self.assertEqual(self.parsed["source_admissions"], 0)
        self.assertFalse(self.parsed["rights_conferred"])

        gates = self.parsed["factor_qualifications"]
        for gate_key in ("dependency", "scarcity", "pricing", "capture"):
            self.assertEqual(gates[gate_key], "UNQUALIFIED")

        # Table rows preserved
        self.assertEqual(len(self.parsed["tables"]["table_1"]), 4)
        self.assertEqual(len(self.parsed["tables"]["table_2"]), 5)
        self.assertEqual(len(self.parsed["all_rows"]), 9)
        self.assertEqual(len(self.parsed["exceptions_and_exemptions"]), 6)

    def test_cli_exclusive_output_and_citation_emission(self):
        """CLI must write exclusive JSON containing citations and fail closed without secret leakage."""
        script_path = Path(__file__).resolve().parent.parent / "scripts" / "carb_typed_section_parser.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "output.json"

            # First run: should succeed
            cmd = [
                sys.executable,
                "-B",
                str(script_path),
                "--input",
                str(RETAINED_CORPUS_PATH),
                "--output",
                str(out_file),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"CLI failed: {res.stderr}")
            self.assertIn("OK: PARSED_SECTIONS_9", res.stdout)
            self.assertTrue(out_file.is_file())

            with open(out_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Validate citations in CLI output
            ext_refs = data["cross_references"]["external"]
            self.assertEqual(len(ext_refs), 7)
            for ref in ext_refs:
                self.assertIn("citation_id", ref)
                self.assertIn("reference_class", ref)
                self.assertTrue(ref["unresolved_outside_corpus"])

            # Second run: must fail closed because output already exists (O_CREAT | O_EXCL)
            res2 = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res2.returncode, 1)
            self.assertIn("ERR_OUTPUT_ALREADY_EXISTS", res2.stderr)
            # Security invariant: no file path leakage in stderr
            self.assertNotIn(str(tmpdir), res2.stderr)
            self.assertNotIn(str(out_file), res2.stderr)


if __name__ == "__main__":
    unittest.main()
