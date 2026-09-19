"""Tests for company_evidence_candidates reusable producer (Review 1).

Validates:
- Real corpus verification against research-sources.json and primary receipts.
- Fail-closed behavior on modified text / mismatched SHA256.
- Fail-closed behavior on modified receipt SHA256.
- Missing file / source ID mismatch rejected.
- Path traversal rejection (e.g. '../', absolute paths).
- Credentialed URL and local URL rejection.
- Same issuer false independence detection (Hitachi or GEV multiple docs).
- Duplicate claim ID quarantined.
- Unmatched passage in source quarantined.
- Forged ADMITTED or score flags rejected / stripped.
- Raw body hash and rights NOT_REVIEWED exposed.
- CLI execution contract and outputs.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import company_evidence_candidates as cec

RUNTIME_DIR = ROOT.parent / "audit-runtime" / "gemini-executor-20260914"
SOURCES_PATH = RUNTIME_DIR / "company-evidence-public-v1" / "research-sources.json"


class TestCompanyEvidenceCandidates(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(SOURCES_PATH.exists(), f"Missing sources path: {SOURCES_PATH}")
        with open(SOURCES_PATH, "r", encoding="utf-8") as f:
            self.sources_data = json.load(f)

    def _create_temp_corpus(self, tmpdir: Path, mutate_fn=None) -> Path:
        for item in SOURCES_PATH.parent.iterdir():
            if item.is_file():
                shutil.copy(item, tmpdir / item.name)
        sf = tmpdir / "research-sources.json"
        with open(sf, "r", encoding="utf-8") as f:
            data = json.load(f)
        if mutate_fn:
            mutate_fn(data)
        with open(sf, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return sf

    def _sample_valid_proposals(self) -> dict:
        return {
            "schema_version": 1,
            "proposals": [
                {
                    "claim_id": "HITACHI-ENERGY-FY25-REV-001",
                    "company_id": "HITACHI_LTD",
                    "legal_entity": "Hitachi, Ltd. (株式会社日立製作所)",
                    "segment": "Energy / Power Grids (Hitachi Energy)",
                    "product_or_spec": "Power grid systems and transmission equipment",
                    "geography": "Global",
                    "metric": "revenue",
                    "value": 19.8,
                    "unit": "BUSD",
                    "denominator": "FY2025 (year ended March 31, 2026)",
                    "financial_period": "FY2025",
                    "period_type": "HISTORICAL_REALIZED",
                    "source_id": "hitachi-fy2025-results",
                    "source_url": "https://www.hitachi.com/content/dam/hitachi/global/en/press/files/2026/04/260427/2025_Anpre.pdf",
                    "source_lineage": "HITACHI_GROUP_ISSUER",
                    "source_role": "ISSUER_PRIMARY_FINANCIAL_RESULTS",
                    "exact_passage": "Hitachi Energy Revenue 19.8 BUSD (YoY: +4.1 BUSD/+26%) Adj. EBITA 2.64 BUSD (YoY: +1.15 BUSD) Adj. EBITA Margin 13.4% (YoY: +3.9 pts)",
                    "passage_context": "Energy: Performance by Business Segment 25 (*)[ ]: Estimated YoY changes excl. FX impact FY2025 Key Performance Drivers (YoY) FY2026 Key Performance Drivers (YoY) Power Grids (incl. Hitachi Energy) By business: Revenue (+) Continued solid demand for transmission equipment and solid execution of strong order backlog, particularly in large-scale project and product businesses Profit (+) Profit increase driven by higher revenue bringing volume leverage; Improved revenue profile; Operational excellence; Solid project execution; Expansion of Lumada business; Lower IT platform renewal costs By region: Revenue (+) Expansion across all regions primarily in Europe, North America, and others Hitachi Energy Revenue 19.8 BUSD (YoY: +4.1 BUSD/+26%) Adj. EBITA 2.64 BUSD (YoY: +1.15 BUSD) Adj. EBITA Margin 13.4% (YoY: +3.9 pts)",
                    "page_or_location": "Slide 25",
                    "proposed_label": "SUPPORTED",
                    "premises": ["Hitachi official FY2025 financial results slide 25 discloses Hitachi Energy standalone revenue and adjusted EBITA."],
                    "falsifiers": ["Restatement of FY2025 segment definitions or FX translation revisions."],
                    "missing_independent_counterparty_proof": ["Issuer disclosure only; customer contract level volumes not independently verified."],
                    "operating_vs_equity_boundary": "Hitachi Energy is 100% owned by Hitachi, Ltd. Shareholder capture is via Hitachi, Ltd. consolidated equity, subject to conglomerate diversification.",
                    "effective_substitutes_gap": "Hitachi Energy operates in high-voltage grid equipment where multi-year backlogs reflect industry-wide lead times."
                },
                {
                    "claim_id": "GEV-1Q26-BACKLOG-001",
                    "company_id": "GE_VERNOVA",
                    "legal_entity": "GE Vernova Inc. (NYSE: GEV)",
                    "segment": "Consolidated / Power & Electrification",
                    "product_or_spec": "Power generation and grid electrification equipment & services",
                    "geography": "Global",
                    "metric": "backlog",
                    "value": 163.0,
                    "unit": "BUSD",
                    "denominator": "Quarter ended March 31, 2026",
                    "financial_period": "1Q 2026",
                    "period_type": "HISTORICAL_REALIZED",
                    "source_id": "gev-1q2026-results",
                    "source_url": "https://www.gevernova.com/news/press-releases/ge-vernova-reports-first-quarter-2026-financial",
                    "source_lineage": "GE_VERNOVA_ISSUER",
                    "source_role": "ISSUER_PRIMARY_PRESS_RELEASE",
                    "exact_passage": "With robust equipment orders growth in each segment and continued services strength, our backlog grew to $163 billion, inclusive of Prolec GE",
                    "passage_context": "We delivered significant growth and margin expansion in the first quarter as we executed our financial strategy. With robust equipment orders growth in each segment and continued services strength, our backlog grew to $163 billion, inclusive of Prolec GE",
                    "page_or_location": "Paragraph 5",
                    "proposed_label": "SUPPORTED",
                    "premises": ["Official Q1 2026 earnings press release quotes CFO Ken Parks confirming $163B backlog."],
                    "falsifiers": ["Order cancellations or non-fulfillment."],
                    "missing_independent_counterparty_proof": ["Aggregated issuer backlog figure; individual counterparty contracts not unbundled."],
                    "operating_vs_equity_boundary": "Direct NYSE listed equity (GEV). Backlog includes unearned customer advances which fund working capital.",
                    "effective_substitutes_gap": "Includes $5B backlog addition from Prolec GE acquisition."
                }
            ]
        }

    def test_sources_manifest_verification(self) -> None:
        validator = cec.SourcesValidator(SOURCES_PATH)
        verified = validator.validate_all()
        self.assertEqual(len(verified), 4)
        for s in verified:
            self.assertTrue(s["valid"])
            self.assertEqual(s["rights"], "NOT_REVIEWED")
            self.assertFalse(s["runtime_admitted"])
            self.assertIn("text_sha256", s)
            self.assertIn("text_bytes", s)

    def test_modified_text_wrong_hash_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            def mutate(d):
                d["sources"][0]["text_sha256"] = "0" * 64
            sf = self._create_temp_corpus(Path(tmpdir), mutate)
            validator = cec.SourcesValidator(sf)
            with self.assertRaises(cec.EvidenceValidationError) as ctx:
                validator.validate_all()
            self.assertIn("Hash mismatch", str(ctx.exception))

    def test_receipt_wrong_hash_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            def mutate(d):
                d["source_receipts"][0]["sha256"] = "f" * 64
            sf = self._create_temp_corpus(Path(tmpdir), mutate)
            validator = cec.SourcesValidator(sf)
            with self.assertRaises(cec.EvidenceValidationError) as ctx:
                validator.validate_all()
            self.assertIn("Receipt hash mismatch", str(ctx.exception))

    def test_missing_source_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            def mutate(d):
                d["sources"][0]["text_file"] = "nonexistent-file.md"
            sf = self._create_temp_corpus(Path(tmpdir), mutate)
            validator = cec.SourcesValidator(sf)
            with self.assertRaises(cec.EvidenceValidationError) as ctx:
                validator.validate_all()
            self.assertIn("does not exist", str(ctx.exception))

    def test_path_traversal_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            def mutate(d):
                d["sources"][0]["text_file"] = "../secret.txt"
            sf = self._create_temp_corpus(Path(tmpdir), mutate)
            validator = cec.SourcesValidator(sf)
            with self.assertRaises(cec.EvidenceValidationError) as ctx:
                validator.validate_all()
            self.assertIn("traversal", str(ctx.exception).lower())

    def test_credentialed_url_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            def mutate(d):
                d["sources"][0]["source_url"] = "https://user:password@hitachi.com/results.pdf"
            sf = self._create_temp_corpus(Path(tmpdir), mutate)
            validator = cec.SourcesValidator(sf)
            with self.assertRaises(cec.EvidenceValidationError) as ctx:
                validator.validate_all()
            self.assertIn("credential", str(ctx.exception).lower())

    def test_valid_candidate_proposals_processing(self) -> None:
        proposals = self._sample_valid_proposals()
        producer = cec.CandidateProducer(SOURCES_PATH)
        result = producer.process_proposals(proposals)
        self.assertEqual(result["summary"]["total_proposals"], 2)
        self.assertEqual(result["summary"]["validated_candidates"], 2)
        self.assertEqual(result["summary"]["quarantined_proposals"], 0)
        self.assertEqual(result["summary"]["runtime_admitted_claims"], 0)
        for c in result["candidates"]:
            self.assertEqual(c["status"], "RESEARCH_CANDIDATE")
            self.assertEqual(c["passage_status"], "PASSAGE_MATCHED")
            self.assertFalse(c["runtime_admitted"])
            self.assertIn("exact_passage", c)
            self.assertIn("verified_text_anchor", c)

    def test_unmatched_passage_quarantined(self) -> None:
        proposals = self._sample_valid_proposals()
        proposals["proposals"][0]["exact_passage"] = "This is a completely fabricated quote not in Hitachi results."
        producer = cec.CandidateProducer(SOURCES_PATH)
        result = producer.process_proposals(proposals)
        self.assertEqual(result["summary"]["validated_candidates"], 1)
        self.assertEqual(result["summary"]["quarantined_proposals"], 1)
        q = result["quarantine"][0]
        self.assertEqual(q["claim_id"], "HITACHI-ENERGY-FY25-REV-001")
        self.assertEqual(q["reason"], "UNMATCHED_PASSAGE_IN_SOURCE")

    def test_duplicate_claim_id_quarantined(self) -> None:
        proposals = self._sample_valid_proposals()
        dup = copy.deepcopy(proposals["proposals"][0])
        proposals["proposals"].append(dup)
        producer = cec.CandidateProducer(SOURCES_PATH)
        result = producer.process_proposals(proposals)
        self.assertEqual(result["summary"]["validated_candidates"], 2)
        self.assertEqual(result["summary"]["quarantined_proposals"], 1)
        self.assertEqual(result["quarantine"][0]["reason"], "DUPLICATE_CLAIM_ID")

    def test_forged_admitted_or_score_flags_rejected(self) -> None:
        proposals = self._sample_valid_proposals()
        proposals["proposals"][0]["status"] = "ADMITTED"
        proposals["proposals"][0]["bottleneck_score"] = 99.5
        proposals["proposals"][0]["admitted"] = True
        producer = cec.CandidateProducer(SOURCES_PATH)
        result = producer.process_proposals(proposals)
        self.assertEqual(result["summary"]["validated_candidates"], 1)
        self.assertEqual(result["summary"]["quarantined_proposals"], 1)
        self.assertIn("FORBIDDEN_CALLER_STATUS_OR_SCORE", result["quarantine"][0]["reason"])

    def test_same_issuer_lineage_non_independent(self) -> None:
        proposals = {
            "schema_version": 1,
            "proposals": [
                {
                    "claim_id": "GEV-1Q26-REV-001",
                    "company_id": "GE_VERNOVA",
                    "legal_entity": "GE Vernova Inc. (NYSE: GEV)",
                    "segment": "Consolidated",
                    "product_or_spec": "Power and Electrification",
                    "geography": "Global",
                    "metric": "revenue",
                    "value": 9.3,
                    "unit": "BUSD",
                    "denominator": "Quarter ended March 31, 2026",
                    "financial_period": "1Q 2026",
                    "period_type": "HISTORICAL_REALIZED",
                    "source_id": "gev-1q2026-results",
                    "source_url": "https://www.gevernova.com/news/press-releases/ge-vernova-reports-first-quarter-2026-financial",
                    "source_lineage": "GE_VERNOVA_ISSUER",
                    "source_role": "ISSUER_PRIMARY_PRESS_RELEASE",
                    "exact_passage": "Revenue of $9.3B, +16%, +7% organically* led by equipment at Electrification and Power",
                    "page_or_location": "Bullet 4",
                    "proposed_label": "SUPPORTED"
                },
                {
                    "claim_id": "GEV-2Q26-ORDERS-001",
                    "company_id": "GE_VERNOVA",
                    "legal_entity": "GE Vernova Inc. (NYSE: GEV)",
                    "segment": "Consolidated",
                    "product_or_spec": "Power and Electrification",
                    "geography": "Global",
                    "metric": "orders",
                    "value": 24.2,
                    "unit": "BUSD",
                    "denominator": "Quarter ended June 30, 2026",
                    "financial_period": "2Q 2026",
                    "period_type": "HISTORICAL_REALIZED",
                    "source_id": "gev-2q2026-transcript",
                    "source_url": "https://www.gevernova.com/sites/default/files/gev_webcast_transcript_07222026.pdf",
                    "source_lineage": "GE_VERNOVA_ISSUER",
                    "source_role": "ISSUER_PRIMARY_TRANSCRIPT",
                    "exact_passage": "In the second quarter, we booked orders of $24.2 billion, an 88% increase year-over-year",
                    "page_or_location": "Slide 5 / Page 5",
                    "proposed_label": "SUPPORTED"
                }
            ]
        }
        producer = cec.CandidateProducer(SOURCES_PATH)
        result = producer.process_proposals(proposals)
        self.assertEqual(result["summary"]["validated_candidates"], 2)
        lineages = {c["source_lineage"] for c in result["candidates"]}
        self.assertEqual(lineages, {"GE_VERNOVA_ISSUER"})
        self.assertEqual(result["summary"]["distinct_issuer_lineages"], 1)
        for c in result["candidates"]:
            self.assertEqual(c["lineage_independence"], "SAME_ISSUER_LINEAGE_PRIMARY_ONLY")

    def test_cli_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            prop_file = tmp / "proposals.json"
            out_file = tmp / "candidates.json"
            with open(prop_file, "w", encoding="utf-8") as f:
                json.dump(self._sample_valid_proposals(), f)
            cmd = [
                sys.executable,
                "-B",
                str(SCRIPTS_DIR / "company_evidence_candidates.py"),
                "--sources",
                str(SOURCES_PATH),
                "--proposals",
                str(prop_file),
                "--output",
                str(out_file),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"CLI error: {res.stderr}\n{res.stdout}")
            self.assertTrue(out_file.exists())
            with open(out_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["summary"]["validated_candidates"], 2)
            self.assertEqual(data["summary"]["runtime_admitted_claims"], 0)


if __name__ == "__main__":
    unittest.main()
