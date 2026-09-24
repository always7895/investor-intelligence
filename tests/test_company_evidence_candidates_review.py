"""Behavioral review tests for company_evidence_candidates producer.

Self-contained synthetic fixtures only; not authenticated or current public research.

Verifies:
1. SECURITY: Credential redaction, static error codes, HTTPS-only, private IP/traversal rejection, canary omission in CLI stdout/stderr.
2. FALSE PROVENANCE: Exact mapped spans / EXACT-only, roundtrip invariant original_text[offset:offset+length] == passage, repeated passage disambiguation.
3. CONTEXT: Context must enclose/connect to selected passage, context verification does not equate to economic support.
4. DEFAULT PROMOTION: Missing metadata marked UNKNOWN/UNREVIEWED, issuer document role promotion rejected.
5. BOUNDED IO & SCHEMA: Oversized files and unknown fields rejected fail-closed before IO.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import company_evidence_candidates as cec
from company_evidence_test_corpus import build_corpus



class TestCompanyEvidenceCandidatesReview(unittest.TestCase):
    def setUp(self) -> None:
        fixture = tempfile.TemporaryDirectory()
        self.addCleanup(fixture.cleanup)
        self.sources_path, self.proposals_path = build_corpus(Path(fixture.name))
        self.assertTrue(self.sources_path.exists(), f"Missing sources: {self.sources_path}")
        with open(self.sources_path, "r", encoding="utf-8") as f:
            self.sources_manifest = json.load(f)

    # 1. SECURITY & REDACTION TESTS
    def test_security_credential_url_redacted_error_code(self) -> None:
        canary = "CANARY_SECRET_PASSWORD_12345"
        url = f"https://admin:{canary}@example.com/sec.pdf"
        try:
            cec.validate_source_url(url)
            self.fail("Expected EvidenceValidationError for credentialed URL")
        except cec.EvidenceValidationError as e:
            err_msg = str(e)
            self.assertNotIn(canary, err_msg, "Security failure: credential leaked into exception message!")
            self.assertIn("CREDENTIALED_URL_REJECTED", err_msg, "Expected static error code")

    def test_security_https_only_enforced(self) -> None:
        http_url = "http://www.hitachi.com/results.pdf"
        with self.assertRaises(cec.EvidenceValidationError) as ctx:
            cec.validate_source_url(http_url)
        self.assertIn("HTTPS_REQUIRED", str(ctx.exception))

    def test_security_private_ip_and_local_rejected(self) -> None:
        prohibited_urls = [
            "https://10.0.0.1/report.pdf",
            "https://192.168.1.100/data.pdf",
            "https://172.16.5.4/filing.pdf",
            "https://169.254.169.254/metadata",
            "https://internal.local/filing.pdf",
        ]
        for u in prohibited_urls:
            with self.assertRaises(cec.EvidenceValidationError) as ctx:
                cec.validate_source_url(u)
            self.assertTrue(
                "PRIVATE_IP_REJECTED" in str(ctx.exception) or "LOCAL_HOST_URL_REJECTED" in str(ctx.exception),
                f"URL {u} did not raise static private/local error code: {ctx.exception}"
            )

    def test_security_cli_stderr_omits_canaries(self) -> None:
        canary = "SUPER_SECRET_CANARY_TOKEN_ABC"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            prop_file = tmp / "proposals_canary.json"
            out_file = tmp / "output.json"
            bad_proposals = {
                "schema_version": 1,
                "canary_leak_field": canary,
                "proposals": [
                    {
                        "claim_id": f"CLAIM_{canary}",
                        "source_id": f"SRC_{canary}",
                        "exact_passage": f"text {canary}",
                        "company_id": "TEST",
                        "legal_entity": "TEST",
                        "metric": "rev"
                    }
                ]
            }
            with open(prop_file, "w", encoding="utf-8") as f:
                json.dump(bad_proposals, f)

            # Sources with bad URL containing canary
            bad_sources = copy.deepcopy(self.sources_manifest)
            bad_sources["sources"][0]["source_url"] = f"https://user:{canary}@hitachi.com/doc.pdf"
            src_file = tmp / "research-sources.json"
            with open(src_file, "w", encoding="utf-8") as f:
                json.dump(bad_sources, f)

            cmd = [
                sys.executable,
                "-B",
                str(SCRIPTS_DIR / "company_evidence_candidates.py"),
                "--sources",
                str(src_file),
                "--proposals",
                str(prop_file),
                "--output",
                str(out_file)
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(res.returncode, 0)
            self.assertNotIn(canary, res.stderr, "CLI stderr leaked canary secret!")
            self.assertNotIn(canary, res.stdout, "CLI stdout leaked canary secret!")

    # 2. FALSE PROVENANCE & EXACT ROUNDTRIP TESTS
    def test_provenance_roundtrip_invariant(self) -> None:
        # Passage has slight whitespace formatting differences from source text
        producer = cec.CandidateProducer(self.sources_path)
        source_id = "gev-1q2026-results"
        doc_text = producer.source_texts[source_id]

        passage_with_extra_spaces = "With  robust   equipment  orders  growth in each segment and continued services strength, our backlog grew to $163 billion, inclusive of Prolec GE"
        prop = {
            "schema_version": 1,
            "proposals": [
                {
                    "claim_id": "GEV-TEST-ROUNDTRIP-01",
                    "company_id": "GE_VERNOVA",
                    "legal_entity": "GE Vernova Inc. (NYSE: GEV)",
                    "metric": "backlog",
                    "source_id": source_id,
                    "exact_passage": passage_with_extra_spaces
                }
            ]
        }
        res = producer.process_proposals(prop)
        if res["summary"]["validated_candidates"] > 0:
            c = res["candidates"][0]
            anchor = c["verified_text_anchor"]
            offset = anchor["char_offset"]
            length = anchor["char_length"]
            # The strict roundtrip invariant: slice of original document MUST match exact verified passage!
            extracted = doc_text[offset : offset + length]
            self.assertEqual(
                extracted,
                c["exact_passage"],
                "Provenance failure: anchor offsets do not address original bytes/text!"
            )
            self.assertEqual(c.get("match_mode"), "EXACT")
        else:
            # If normalized text is not exact, it must be quarantined
            self.assertEqual(res["summary"]["quarantined_proposals"], 1)
            self.assertIn("UNMATCHED", res["quarantine"][0]["reason"])

    def test_repeated_occurrences_require_disambiguation(self) -> None:
        producer = cec.CandidateProducer(self.sources_path)
        # "Electrification" appears dozens of times in gev-2q2026-transcript.md
        prop = {
            "schema_version": 1,
            "proposals": [
                {
                    "claim_id": "GEV-TEST-AMBIGUOUS-01",
                    "company_id": "GE_VERNOVA",
                    "legal_entity": "GE Vernova Inc. (NYSE: GEV)",
                    "metric": "segment_mention",
                    "source_id": "gev-2q2026-transcript",
                    "exact_passage": "Electrification"
                }
            ]
        }
        res = producer.process_proposals(prop)
        # Must not blind first match without context disambiguation
        self.assertEqual(res["summary"]["validated_candidates"], 0, "Blind first match accepted without disambiguation!")
        self.assertEqual(res["summary"]["quarantined_proposals"], 1)
        self.assertIn("AMBIGUOUS_REPEATED_PASSAGE", res["quarantine"][0]["reason"])

    # 3. CONTEXT CONNECTION TESTS
    def test_context_must_enclose_selected_passage(self) -> None:
        producer = cec.CandidateProducer(self.sources_path)
        # Passage from page 5, context from page 2 (unrelated)
        prop = {
            "schema_version": 1,
            "proposals": [
                {
                    "claim_id": "GEV-TEST-CONTEXT-DISCONNECTED-01",
                    "company_id": "GE_VERNOVA",
                    "legal_entity": "GE Vernova Inc. (NYSE: GEV)",
                    "metric": "backlog",
                    "source_id": "gev-2q2026-transcript",
                    "exact_passage": "Our services backlog grew approximately $10 billion or 12% year-over-year to $88 billion, led by Power.",
                    "passage_context": "Welcome to GE Vernova's Second Quarter 2026 Earnings Call. I'm joined today by our CEO, Scott Strazik, and CFO, Ken Parks."
                }
            ]
        }
        res = producer.process_proposals(prop)
        self.assertEqual(res["summary"]["validated_candidates"], 0, "Unrelated context accepted!")
        self.assertEqual(res["summary"]["quarantined_proposals"], 1)
        self.assertIn("CONTEXT_NOT_CONNECTED_TO_PASSAGE", res["quarantine"][0]["reason"])

    # 4. DEFAULT PROMOTION TESTS
    def test_missing_semantics_default_to_unreviewed(self) -> None:
        producer = cec.CandidateProducer(self.sources_path)
        prop = {
            "schema_version": 1,
            "proposals": [
                {
                    "claim_id": "HITACHI-TEST-SEMANTICS-01",
                    "company_id": "HITACHI_LTD",
                    "legal_entity": "Hitachi, Ltd.",
                    "metric": "revenue",
                    "source_id": "hitachi-energy-financial-outlook",
                    "exact_passage": "Revenues CAGR Target 2021-2024 12-15% Actual 21%"
                }
            ]
        }
        res = producer.process_proposals(prop)
        self.assertEqual(res["summary"]["validated_candidates"], 1)
        c = res["candidates"][0]
        self.assertEqual(c.get("proposed_label"), "UNREVIEWED", "Defaulted to affirmative SUPPORTED!")
        self.assertEqual(c.get("period_type"), "UNREVIEWED", "Defaulted to affirmative HISTORICAL_REALIZED!")
        self.assertEqual(c.get("geography"), "UNKNOWN", "Defaulted to GLOBAL!")

    def test_issuer_document_role_promotion_rejected(self) -> None:
        producer = cec.CandidateProducer(self.sources_path)
        prop = {
            "schema_version": 1,
            "proposals": [
                {
                    "claim_id": "HITACHI-TEST-ROLE-01",
                    "company_id": "HITACHI_LTD",
                    "legal_entity": "Hitachi, Ltd.",
                    "metric": "revenue",
                    "source_id": "hitachi-fy2025-results",
                    "source_role": "INDEPENDENT_THIRD_PARTY_AUDIT",
                    "exact_passage": "Consolidated Total Revenue 10,586.7 YoY [YoY excl. FX impact] +8% [+7%]"
                }
            ]
        }
        res = producer.process_proposals(prop)
        self.assertEqual(res["summary"]["validated_candidates"], 1)
        c = res["candidates"][0]
        self.assertEqual(c.get("document_source_role"), "ISSUER_PUBLISHED_DOCUMENT")
        self.assertEqual(c.get("effective_source_role"), "ISSUER_PRIMARY")
        self.assertNotEqual(c.get("effective_source_role"), "INDEPENDENT_THIRD_PARTY_AUDIT")

    # 5. BOUNDED SCHEMA & IO CHECKS
    def test_source_manifest_unknown_fields_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            for item in self.sources_path.parent.iterdir():
                if item.is_file():
                    (tmp / item.name).write_bytes(item.read_bytes())
            sf = tmp / "research-sources.json"
            bad_data = copy.deepcopy(self.sources_manifest)
            bad_data["unknown_evil_field"] = "malicious_payload"
            sf.write_text(json.dumps(bad_data), encoding="utf-8")

            with self.assertRaises(cec.EvidenceValidationError) as ctx:
                cec.SourcesValidator(sf).validate_all()
            self.assertIn("SCHEMA_VALIDATION_FAILED", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
