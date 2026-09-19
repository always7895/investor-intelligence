"""Verify Objective A & B statutory authority resolution (STATUTORY_AUTHORITY_RESOLUTION_V1).

Invariants verified (see docs/STATUTORY_AUTHORITY_RESOLUTION_V1.md):
- The 7 typed statutory citations in scripts/carb_typed_section_parser.py carry
  literal anchors that are exact substrings of the retained corpus, provenance
  spans {start, length} consistent with those substrings, and SHA-256 digests of
  the anchor bytes.
- unresolved_outside_corpus=True and limits_complete_interpretation=True are
  enforced across all citations (no out-of-corpus legal resolution, no claim of
  complete interpretation).
- Unknown / malformed reference text fails closed to UNPARSEABLE or OTHER.
- parse_carb_document reports runtime_admitted strictly False and
  company_admissions strictly 0.
- Zero network: everything runs against the digested retained corpus only.
"""
from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.carb_typed_section_parser import (  # noqa: E402
    CarbParserError,
    ReferenceClass,
    classify_statutory_reference,
    parse_carb_document,
    parse_statutory_citations,
)

# ==============================================================================
# Resolve the absolute path to the retained corpus file
# ==============================================================================
RETAINED_CORPUS = (
    _REPO_ROOT.parent
    / "audit-runtime"
    / "gemini-executor-20260914"
    / "meiden-independent-public-v1"
    / "carb-final-regulation.md"
)

EXPECTED_CITATION_COUNT = 7
FAILED_CLOSED_CLASSES = (ReferenceClass.UNPARSEABLE, ReferenceClass.OTHER)


class TestStatutoryAuthorityResolution(unittest.TestCase):
    """Objective A & B resolution: typed citations are bounded, fail-closed, non-admitting."""

    @classmethod
    def setUpClass(cls):
        if not RETAINED_CORPUS.is_file():
            raise unittest.SkipTest(f"Retained corpus not found at {RETAINED_CORPUS}")
        cls.corpus = RETAINED_CORPUS.read_text(encoding="utf-8")
        cls.citations = parse_statutory_citations(cls.corpus)
        cls.document = parse_carb_document(cls.corpus)

    # ------------------------------------------------------------------
    # 1) Exactly 7 typed citations with literal anchors
    # ------------------------------------------------------------------
    def test_seven_typed_citations(self):
        self.assertEqual(len(self.citations), EXPECTED_CITATION_COUNT)
        classes = {c.reference_class for c in self.citations}
        self.assertTrue(classes <= set(ReferenceClass.ALL))

    # ------------------------------------------------------------------
    # 2) validity of spans, literal anchors, and SHA-256 digests
    # ------------------------------------------------------------------
    def test_literal_anchors_and_spans_verified(self):
        for cit in self.citations:
            self.assertIsInstance(cit.source_anchor, str)
            self.assertTrue(cit.source_anchor, "Empty anchor")
            self.assertIsNotNone(cit.span, f"{cit.citation_id} is missing a provenance span")
            span = cit.span
            start = span.get("start")
            length = span.get("length")
            self.assertIsInstance(start, int)
            self.assertIsInstance(length, int)
            self.assertGreaterEqual(start, 0)
            self.assertEqual(length, len(cit.source_anchor))
            window = self.corpus[start : start + length]
            self.assertEqual(
                window,
                cit.source_anchor,
                f"{cit.citation_id}: span offset does not reproduce the literal anchor",
            )

    def test_anchor_sha256_digests(self):
        for cit in self.citations:
            self.assertIsNotNone(cit.span)
            expected = hashlib.sha256(cit.source_anchor.encode("utf-8")).hexdigest()
            self.assertEqual(cit.span["span_sha256"], expected, f"{cit.citation_id}: anchor digest mismatch")

    # ------------------------------------------------------------------
    # 3) Mandatory bounds across all citations
    # ------------------------------------------------------------------
    def test_unresolved_and_limits_flags_enforced(self):
        for cit in self.citations:
            self.assertTrue(cit.unresolved_outside_corpus, f"{cit.citation_id} claims outside-corpus resolution")
            self.assertTrue(
                cit.limits_complete_interpretation,
                f"{cit.citation_id} claims complete legal interpretation",
            )

    # ------------------------------------------------------------------
    # 4) Unknown / malformed references fail closed
    # ------------------------------------------------------------------
    def test_unknown_references_fail_closed(self):
        garbage = [
            "",
            "   ",
            "§ 99999 nonexistent",
            "not a reference at all",
            "garbagefrag00a7-0022-0022-fragment",  # odd/punctuated fragment
        ]
        for raw in garbage:
            cit = classify_statutory_reference(raw)
            self.assertIn(
                cit.reference_class,
                FAILED_CLOSED_CLASSES,
                f"{raw!r} classified as {cit.reference_class} (fail-closed violation)",
            )
            self.assertTrue(cit.unresolved_outside_corpus)
            self.assertTrue(cit.limits_complete_interpretation)

    # ------------------------------------------------------------------
    # 5) Non-admitting result shape
    # ------------------------------------------------------------------
    def test_runtime_not_admitted_and_zero_companies(self):
        self.assertIs(self.document["runtime_admitted"], False)
        self.assertEqual(self.document["company_admissions"], 0)

    # ------------------------------------------------------------------
    # 6) Far-failed inputs stay far-failed (no acceptance of fake regulation text)
    # ------------------------------------------------------------------
    def test_official_text_guard_fails_closed(self):
        with self.assertRaises(CarbParserError):
            parse_carb_document(
                "Totally unrelated text. Proposed Amendments to the Regulation for Reducing"
                " Sulfur Hexafluoride. § 95352. Sulfur Hexafluoride Phase-Out.\nNot the real regulation."
            )
        with self.assertRaises(CarbParserError):
            parse_statutory_citations("some arbitrary text without any citation structure at all")


if __name__ == "__main__":
    unittest.main()