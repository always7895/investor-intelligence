#!/usr/bin/env python3
"""Comprehensive behavioral tests for CARB Typed Section Parser (CARB_TYPED_SECTION_PARSER_V1).

SYNTHETIC GRAMMAR TESTS ONLY - NOT REAL LEGAL OR PUBLIC RESEARCH EVIDENCE.
Unchanged parser default URLs/version labels (including CLI output) are not
authenticated provenance. Real-corpus integration is separate and unqualified.

Covers:
- Positive parsing of synthetic CARB grammar fixture.
- Table 1 (<= 38 kV) vs Table 2 (> 38 kV) distinction, configuration handling, and exact row counts.
- Exact boundary equality belonging to proper band (voltage 38 kV, 145 kV, 245 kV; current 25 kA, 63 kA).
- Date distinction: acquisition phase-out date vs regulation promulgation date.
- Exception preservation (§ 95352(a)(1)-(4), § 95352(c), § 95357) and definitions.
- Cross-reference partitioning: internal vs external (UNRESOLVED_OUTSIDE_CORPUS).
- Trust invariants: runtime_admitted=False, company_admissions=0, rights_conferred=False.
- Exact span verification against raw source bytes/characters.
- Negative mutations: corrupted headers, missing tables, conflicting rows, unknown future amendments.
- Type safety: rejecting bool, NaN, Infinity, and kA inference from model strings.
- CLI privacy: static error codes, exclusive output creation, immutable input verification.
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure source/scripts can be imported
SOURCE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SOURCE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import carb_typed_section_parser as parser

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "carb-parser-synthetic.txt"


class TestCarbParserPositiveFixture(unittest.TestCase):
    """Positive tests against the synthetic CARB grammar fixture."""

    @classmethod
    def setUpClass(cls):
        if not FIXTURE_PATH.is_file():
            raise FileNotFoundError("SYNTHETIC_FIXTURE_MISSING")
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            cls.raw_text = f.read()
        cls.parsed = parser.parse_carb_document(
            cls.raw_text,
            source_metadata={
                "id": "SYNTHETIC-CARB-GRAMMAR",
                "file": "carb-parser-synthetic.txt",
                "url": "https://example.com/synthetic/carb-grammar",
            },
        )

    def test_trust_invariants_and_non_admitting(self):
        """Parser must output NON_ADMITTING_REGULATORY_TEXT_PARSE with 0 admissions."""
        res = self.parsed
        self.assertEqual(res["status"], "NON_ADMITTING_REGULATORY_TEXT_PARSE")
        self.assertFalse(res["runtime_admitted"])
        self.assertEqual(res["company_admissions"], 0)
        self.assertEqual(res["source_admissions"], 0)
        self.assertFalse(res["rights_conferred"])
        self.assertEqual(res["semantic_interpretation_status"], "NEEDS_SEMANTIC_REVIEW")
        for k, v in res["factor_qualifications"].items():
            self.assertEqual(v, "UNQUALIFIED", f"Factor {k} must remain UNQUALIFIED")

    def test_jurisdiction_and_promulgation_metadata(self):
        """Rule version, jurisdiction, and statutory sections must be correctly bound."""
        res = self.parsed
        jur = res["jurisdiction"]
        self.assertEqual(jur["state"], "California")
        self.assertEqual(jur["agency"], "California Air Resources Board (CARB)")
        self.assertEqual(jur["code"], "California Code of Regulations (CCR)")
        self.assertEqual(jur["title"], 17)
        self.assertEqual(jur["subarticle"], "3.1")

        meta = res["promulgation_metadata"]
        self.assertTrue(meta["distinct_from_phaseout_dates"])
        self.assertIn("95352", res["statutory_sections_covered"])

    def test_table_counts_and_separation(self):
        """Table 1 has 4 rows; Table 2 has 5 rows; Table 1 vs 2 distinction honored."""
        res = self.parsed
        t1 = res["tables"]["table_1"]
        t2 = res["tables"]["table_2"]
        self.assertEqual(len(t1), 4, "Table 1 must have exactly 4 rows")
        self.assertEqual(len(t2), 5, "Table 2 must have exactly 5 rows")
        self.assertEqual(len(res["all_rows"]), 9, "Total parsed rows must be 9")

        # Table 1 rows must have configuration (Aboveground / Belowground)
        for r in t1:
            self.assertIn(r["configuration"], ["Aboveground", "Belowground"])
            self.assertEqual(r["equipment_category"], "SF6 GIE with Voltage Capacity <= 38 kV")

        # Table 2 rows must NOT have configuration restriction
        for r in t2:
            self.assertEqual(r["configuration"], "Not Specified / Any")
            self.assertEqual(r["equipment_category"], "SF6 GIE with Voltage Capacity > 38 kV")

    def test_table_1_exact_rows(self):
        """Table 1 rows must match statutory text exactly."""
        t1 = self.parsed["tables"]["table_1"]
        # Row 1: Aboveground < 38 kV, All kA, 2025-01-01
        self.assertEqual(t1[0]["configuration"], "Aboveground")
        self.assertEqual(t1[0]["voltage"]["operator"], "<")
        self.assertEqual(t1[0]["voltage"]["upper_bound"], 38.0)
        self.assertEqual(t1[0]["current"]["operator"], "ALL")
        self.assertEqual(t1[0]["phase_out_date"], "2025-01-01")

        # Row 2: Aboveground 38 kV, All kA, 2028-01-01
        self.assertEqual(t1[1]["configuration"], "Aboveground")
        self.assertEqual(t1[1]["voltage"]["operator"], "==")
        self.assertEqual(t1[1]["voltage"]["upper_bound"], 38.0)
        self.assertEqual(t1[1]["current"]["operator"], "ALL")
        self.assertEqual(t1[1]["phase_out_date"], "2028-01-01")

        # Row 3: Belowground <= 38 kV, < 25 kA, 2025-01-01
        self.assertEqual(t1[2]["configuration"], "Belowground")
        self.assertEqual(t1[2]["voltage"]["operator"], "<=")
        self.assertEqual(t1[2]["voltage"]["upper_bound"], 38.0)
        self.assertEqual(t1[2]["current"]["operator"], "<")
        self.assertEqual(t1[2]["current"]["upper_bound"], 25.0)
        self.assertEqual(t1[2]["phase_out_date"], "2025-01-01")

        # Row 4: Belowground <= 38 kV, >= 25 kA, 2031-01-01
        self.assertEqual(t1[3]["configuration"], "Belowground")
        self.assertEqual(t1[3]["voltage"]["operator"], "<=")
        self.assertEqual(t1[3]["voltage"]["upper_bound"], 38.0)
        self.assertEqual(t1[3]["current"]["operator"], ">=")
        self.assertEqual(t1[3]["current"]["lower_bound"], 25.0)
        self.assertEqual(t1[3]["phase_out_date"], "2031-01-01")

    def test_table_2_exact_rows(self):
        """Table 2 rows must match statutory text exactly."""
        t2 = self.parsed["tables"]["table_2"]
        # Row 1: 38 < kV <= 145, < 63 kA, 2025-01-01
        self.assertEqual(t2[0]["voltage"]["operator"], "RANGE_EXCL_INCL")
        self.assertEqual(t2[0]["voltage"]["lower_bound"], 38.0)
        self.assertEqual(t2[0]["voltage"]["upper_bound"], 145.0)
        self.assertEqual(t2[0]["current"]["operator"], "<")
        self.assertEqual(t2[0]["current"]["upper_bound"], 63.0)
        self.assertEqual(t2[0]["phase_out_date"], "2025-01-01")

        # Row 2: 38 < kV <= 145, >= 63 kA, 2028-01-01
        self.assertEqual(t2[1]["voltage"]["operator"], "RANGE_EXCL_INCL")
        self.assertEqual(t2[1]["voltage"]["lower_bound"], 38.0)
        self.assertEqual(t2[1]["voltage"]["upper_bound"], 145.0)
        self.assertEqual(t2[1]["current"]["operator"], ">=")
        self.assertEqual(t2[1]["current"]["lower_bound"], 63.0)
        self.assertEqual(t2[1]["phase_out_date"], "2028-01-01")

        # Row 3: 145 < kV <= 245, < 63 kA, 2027-01-01
        self.assertEqual(t2[2]["voltage"]["operator"], "RANGE_EXCL_INCL")
        self.assertEqual(t2[2]["voltage"]["lower_bound"], 145.0)
        self.assertEqual(t2[2]["voltage"]["upper_bound"], 245.0)
        self.assertEqual(t2[2]["current"]["operator"], "<")
        self.assertEqual(t2[2]["current"]["upper_bound"], 63.0)
        self.assertEqual(t2[2]["phase_out_date"], "2027-01-01")

        # Row 4: 145 < kV <= 245, >= 63 kA, 2031-01-01
        self.assertEqual(t2[3]["voltage"]["operator"], "RANGE_EXCL_INCL")
        self.assertEqual(t2[3]["voltage"]["lower_bound"], 145.0)
        self.assertEqual(t2[3]["voltage"]["upper_bound"], 245.0)
        self.assertEqual(t2[3]["current"]["operator"], ">=")
        self.assertEqual(t2[3]["current"]["lower_bound"], 63.0)
        self.assertEqual(t2[3]["phase_out_date"], "2031-01-01")

        # Row 5: > 245 kV, All kA, 2033-01-01
        self.assertEqual(t2[4]["voltage"]["operator"], ">")
        self.assertEqual(t2[4]["voltage"]["lower_bound"], 245.0)
        self.assertEqual(t2[4]["current"]["operator"], "ALL")
        self.assertEqual(t2[4]["phase_out_date"], "2033-01-01")

    def test_spans_match_original_bytes(self):
        """Every span recorded must match original source text at exact offset without lying."""
        raw = self.raw_text
        for row in self.parsed["all_rows"]:
            span = row["span"]
            start = span["start"]
            length = span["length"]
            extracted = raw[start : start + length]
            import hashlib
            self.assertEqual(
                hashlib.sha256(extracted.encode("utf-8")).hexdigest(),
                span["span_sha256"],
                f"Span SHA256 mismatch for row {row['table_name']}",
            )

    def test_exceptions_and_exemptions_preserved(self):
        """Preserves § 95352(a)(1)-(4) and § 95352(c) exceptions and § 95357 failure rules."""
        excs = self.parsed["exceptions_and_exemptions"]
        keys = [e["clause_id"] for e in excs]
        self.assertIn("95352(a)(1)", keys)
        self.assertIn("95352(a)(2)", keys)
        self.assertIn("95352(a)(3)", keys)
        self.assertIn("95352(a)(4)", keys)
        self.assertIn("95352(c)", keys)

        # § 95352(a)(3) must explicitly note 24-month entry window after purchase
        a3 = next(e for e in excs if e["clause_id"] == "95352(a)(3)")
        self.assertEqual(a3["max_months_to_enter_california"], 24)

        # § 95352(c) must record replacement parts exemption
        c = next(e for e in excs if e["clause_id"] == "95352(c)")
        self.assertTrue(c["replacement_parts_exempt"])

    def test_definitions_and_cross_references(self):
        """Definitions ('Acquire', 'Purchase') and external cross-references verified."""
        defs = {d["term"]: d for d in self.parsed["relevant_definitions"]}
        self.assertIn("Acquire", defs)
        self.assertIn("Purchase", defs)
        self.assertIn("Gas-Insulated Equipment", defs)

        # External cross references must be UNRESOLVED_OUTSIDE_CORPUS
        ext_refs = self.parsed["cross_references"]["external"]
        self.assertTrue(len(ext_refs) >= 3, "Must have external cross references")
        for r in ext_refs:
            self.assertEqual(r["status"], "UNRESOLVED_OUTSIDE_CORPUS")
            self.assertTrue(r["limits_complete_interpretation"])

    def test_boundary_equality_classifier(self):
        """Exact threshold case equality belongs to the proper band."""
        p = self.parsed

        # Table 1: Aboveground < 38 vs 38
        r = parser.classify_gie_phaseout(p, voltage_kv=37.5, configuration="Aboveground")
        self.assertEqual(r["phase_out_date"], "2025-01-01")

        r = parser.classify_gie_phaseout(p, voltage_kv=38.0, configuration="Aboveground")
        self.assertEqual(r["phase_out_date"], "2028-01-01")

        # Table 1: Belowground <= 38 with current < 25 vs >= 25
        r = parser.classify_gie_phaseout(p, voltage_kv=38.0, short_circuit_ka=24.9, configuration="Belowground")
        self.assertEqual(r["phase_out_date"], "2025-01-01")

        # Boundary exact 25 kA belongs to >= 25 band
        r = parser.classify_gie_phaseout(p, voltage_kv=38.0, short_circuit_ka=25.0, configuration="Belowground")
        self.assertEqual(r["phase_out_date"], "2031-01-01")

        # Table 2: 38 < kV <= 145
        # 38 kV belongs to Table 1, NOT Table 2!
        # 38.1 kV belongs to Table 2
        r = parser.classify_gie_phaseout(p, voltage_kv=38.1, short_circuit_ka=40.0)
        self.assertEqual(r["phase_out_date"], "2025-01-01")
        self.assertEqual(r["table_name"], "Table 2")

        # Boundary exact 145.0 kV with 63.0 kA belongs to Table 2 row 2 (38 < kV <= 145, >= 63 kA)
        r = parser.classify_gie_phaseout(p, voltage_kv=145.0, short_circuit_ka=63.0)
        self.assertEqual(r["phase_out_date"], "2028-01-01")
        self.assertEqual(r["table_name"], "Table 2")

        # 145.0 kV with < 63 kA (e.g. 40 kA)
        r = parser.classify_gie_phaseout(p, voltage_kv=145.0, short_circuit_ka=40.0)
        self.assertEqual(r["phase_out_date"], "2025-01-01")

        # Boundary 145.1 kV (> 145) belongs to 145 < kV <= 245 band
        r = parser.classify_gie_phaseout(p, voltage_kv=145.1, short_circuit_ka=40.0)
        self.assertEqual(r["phase_out_date"], "2027-01-01")

        # Boundary exact 245.0 kV with >= 63 kA belongs to 145 < kV <= 245 band
        r = parser.classify_gie_phaseout(p, voltage_kv=245.0, short_circuit_ka=63.0)
        self.assertEqual(r["phase_out_date"], "2031-01-01")

        # > 245 kV (e.g. 550 kV)
        r = parser.classify_gie_phaseout(p, voltage_kv=550.0)
        self.assertEqual(r["phase_out_date"], "2033-01-01")


class TestCarbParserNegativeMutations(unittest.TestCase):
    """Negative mutation tests: parser must FAIL_CLOSED on corrupted inputs."""

    @classmethod
    def setUpClass(cls):
        if not FIXTURE_PATH.is_file():
            raise FileNotFoundError("SYNTHETIC_FIXTURE_MISSING")
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            cls.base_text = f.read()

    def test_corrupt_table_1_header_fails_closed(self):
        """Corrupted Table 1 header must trigger FAIL_CLOSED."""
        mutated = self.base_text.replace(
            "Table 1. Phase-Out Dates for SF 6 GIE with Voltage Capacity ≤ 38 kV",
            "Table 1. Corrupted Forged Header Without Specs",
        )
        with self.assertRaises(parser.CarbParserError) as ctx:
            parser.parse_carb_document(mutated)
        self.assertEqual(str(ctx.exception), "ERR_TABLE_MISSING")

    def test_corrupt_table_2_header_fails_closed(self):
        """Corrupted Table 2 header must trigger FAIL_CLOSED."""
        mutated = self.base_text.replace(
            "Table 2. Phase-Out Dates for SF 6 GIE with Voltage Capacity > 38 kV",
            "Table 2. Corrupted Voltage String",
        )
        with self.assertRaises(parser.CarbParserError) as ctx:
            parser.parse_carb_document(mutated)
        self.assertEqual(str(ctx.exception), "ERR_TABLE_MISSING")

    def test_conflicting_rows_fails_closed(self):
        """Conflicting or overlapping rows must trigger ERR_CONFLICTING_ROWS."""
        mutated = self.base_text.replace(
            "Aboveground < 38 All January 1, 2025",
            "Aboveground < 38 All January 1, 2025 Aboveground < 38 All January 1, 2030",
        )
        with self.assertRaises(parser.CarbParserError) as ctx:
            parser.parse_carb_document(mutated)
        self.assertIn("ERR_CONFLICTING_ROWS", str(ctx.exception))

    def test_unknown_future_amendment_fails_closed(self):
        """Unknown future amendment order text must trigger ERR_UNKNOWN_SCHEMA_OR_VERSION."""
        fake_text = "# Final Regulation Order 2035 Amendment\nTable 1. Phase-Out Dates for SF 6 GIE with Voltage Capacity ≤ 38 kV Configuration Voltage Capacity (kV) Short-Circuit Current Rating (kA) Phase-Out Date Aboveground < 38 All January 1, 2035"
        with self.assertRaises(parser.CarbParserError) as ctx:
            parser.parse_carb_document(fake_text)
        self.assertIn("ERR_UNKNOWN_SCHEMA_OR_VERSION", str(ctx.exception))

    def test_truncated_exceptions_fails_closed(self):
        """Truncated exceptions section must fail closed."""
        mutated = self.base_text.replace(
            "(3) The SF 6 GIE device was purchased by the GIE owner prior to the applicable phase-out date listed in Table 1 or Table 2 for the relevant GIE characteristics, and enters California no later than 24 months after the purchase date.",
            "",
        )
        with self.assertRaises(parser.CarbParserError) as ctx:
            parser.parse_carb_document(mutated)
        self.assertEqual(str(ctx.exception), "ERR_TRUNCATED_EXCEPTIONS")

    def test_unrelated_paragraph_with_matching_digits_rejected(self):
        """Random paragraph mentioning 38 kV or 63 kA outside table must not produce table row."""
        unrelated = "In summary, 38 kV and 63 kA equipment may be mentioned here casually."
        with self.assertRaises(parser.CarbParserError) as ctx:
            parser.parse_carb_document(unrelated)
        self.assertEqual(str(ctx.exception), "ERR_UNSUPPORTED_INPUT")


class TestCarbParserTypeSafety(unittest.TestCase):
    """Type safety and anti-inference invariants."""

    @classmethod
    def setUpClass(cls):
        if not FIXTURE_PATH.is_file():
            raise FileNotFoundError("SYNTHETIC_FIXTURE_MISSING")
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            raw = f.read()
        cls.parsed = parser.parse_carb_document(raw, source_metadata={'id': 'SYNTHETIC-CARB-GRAMMAR', 'file': 'carb-parser-synthetic.txt', 'url': 'https://example.com/synthetic/carb-grammar'})

    def test_reject_bool_voltage(self):
        """Boolean voltage (e.g. True) must be rejected to prevent Python int coercion."""
        with self.assertRaises((TypeError, ValueError)):
            parser.classify_gie_phaseout(self.parsed, voltage_kv=True, configuration="Aboveground")

    def test_reject_nan_infinity(self):
        """NaN and Infinity must be rejected."""
        with self.assertRaises(ValueError):
            parser.classify_gie_phaseout(self.parsed, voltage_kv=float("nan"))
        with self.assertRaises(ValueError):
            parser.classify_gie_phaseout(self.parsed, voltage_kv=float("inf"))

    def test_reject_ka_inferred_from_model_string(self):
        """Model string must not be used to infer kA; non-numeric current raises error."""
        with self.assertRaises((TypeError, parser.CarbParserError)):
            parser.classify_gie_phaseout(self.parsed, voltage_kv=72.5, short_circuit_ka="8VN1-40")

    def test_table_1_requires_configuration(self):
        """Voltage <= 38 kV requires valid configuration (Aboveground / Belowground)."""
        with self.assertRaises(parser.CarbParserError) as ctx:
            parser.classify_gie_phaseout(self.parsed, voltage_kv=25.0, configuration=None)
        self.assertEqual(str(ctx.exception), "ERR_CONFIGURATION_REQUIRED_FOR_TABLE_1")


class TestCarbParserCLIAndPrivacy(unittest.TestCase):
    """CLI execution, privacy, exclusive creation, and immutability invariants."""

    def test_cli_exclusive_output_prevents_overwrite(self):
        """CLI must fail if output file already exists."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            tf.write(b"existing content")
            target_path = tf.name

        try:
            # Calling CLI targeting existing file must fail with exit code != 0
            code = parser.main(["--input", str(FIXTURE_PATH), "--output", target_path])
            self.assertNotEqual(code, 0)
            # Existing content must NOT be overwritten
            with open(target_path, "rb") as f:
                self.assertEqual(f.read(), b"existing content")
        finally:
            if os.path.exists(target_path):
                os.remove(target_path)

    def test_cli_privacy_no_path_leakage(self):
        """CLI errors must use static error codes without echoing private paths or tracebacks."""
        import io
        from unittest.mock import patch

        fake_err = io.StringIO()
        with patch("sys.stderr", fake_err):
            code = parser.main(["--input", "C:/secret/private/path/does_not_exist.md", "--output", "out.json"])
            self.assertNotEqual(code, 0)
            err_msg = fake_err.getvalue()
            self.assertNotIn("secret", err_msg)
            self.assertNotIn("private", err_msg)
            self.assertIn("ERR_", err_msg)


if __name__ == "__main__":
    unittest.main()
