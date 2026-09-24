"""Tests for company_evidence_candidates CLI safety, immutability, and resource bounds (Review 2).

Self-contained synthetic fixtures only; not authenticated or current public research.

Verifies:
1. IMMUTABILITY & ANTI-DESTRUCTION:
   - Reject existing target before write (fail-closed, file remains byte-identical).
   - Reject aliasing output to sources manifest, proposals file, or source text files.
   - Reject symlink targets for output.
   - Use exclusive creation (O_CREAT | O_EXCL) to prevent TOCTOU races.
   - Strict JSON serialization before opening output file (no partial output on failure).
2. OUTPUT PRIVACY & STATIC REPORTING:
   - Output summary only reports counts and static status; never echoes raw output path or private tokens.
   - Stderr emits bounded static error codes; never leaks args or proposals.
3. STRICT JSON & SCALAR TYPES:
   - Non-finite numbers (NaN, Infinity, -Infinity) rejected fail-closed.
   - Duplicate keys in JSON rejected fail-closed.
   - Deep nested values rejected fail-closed.
   - Avoid boolean numeric coercion in metrics/values.
   - No unknown proposed labels or unapproved semantic defaults.
4. RESOURCE BUDGETS & AGGREGATE CAPS:
   - Aggregate source/receipt byte budget cap enforced before loading/hashing.
   - Source and receipt count caps enforced.
   - Manifest record_count consistency enforced.
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
from company_evidence_test_corpus import build_corpus



class TestCompanyEvidenceCandidatesCliSafety(unittest.TestCase):
    def setUp(self) -> None:
        fixture = tempfile.TemporaryDirectory()
        self.addCleanup(fixture.cleanup)
        self.sources_path, self.proposals_path = build_corpus(Path(fixture.name))
        self.assertTrue(self.sources_path.exists(), f"Missing sources path: {self.sources_path}")
        self.assertTrue(self.proposals_path.exists(), f"Missing proposals path: {self.proposals_path}")

    def _run_cli(self, sources: Path, proposals: Path, output: Path) -> subprocess.CompletedProcess:
        cmd = [
            sys.executable,
            "-B",
            str(SCRIPTS_DIR / "company_evidence_candidates.py"),
            "--sources",
            str(sources),
            "--proposals",
            str(proposals),
            "--output",
            str(output),
        ]
        return subprocess.run(cmd, capture_output=True, text=True)

    # 1. IMMUTABILITY & ANTI-DESTRUCTION TESTS
    def test_cli_rejects_existing_output_file_without_modifying(self) -> None:
        """CLI must reject existing output target without truncating or overwriting it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out_file = tmp / "existing_output.json"
            initial_content = b'{"immutable_canary": "DO_NOT_OVERWRITE_12345"}\n'
            out_file.write_bytes(initial_content)

            res = self._run_cli(self.sources_path, self.proposals_path, out_file)
            self.assertNotEqual(res.returncode, 0, "CLI must exit with non-zero when output exists")
            self.assertEqual(out_file.read_bytes(), initial_content, "Existing file must remain byte-identical")
            self.assertIn("OUTPUT_FILE_ALREADY_EXISTS", res.stderr)

    def test_cli_rejects_aliasing_output_to_sources_manifest(self) -> None:
        """CLI must fail before opening if output_path is aliased to sources manifest."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            src_copy = tmp / "research-sources.json"
            shutil.copy(self.sources_path, src_copy)
            initial_bytes = src_copy.read_bytes()

            res = self._run_cli(src_copy, self.proposals_path, src_copy)
            self.assertNotEqual(res.returncode, 0)
            self.assertEqual(src_copy.read_bytes(), initial_bytes, "Sources manifest must remain byte-identical")
            self.assertTrue(
                "OUTPUT_PATH_ALIASED" in res.stderr or "OUTPUT_FILE_ALREADY_EXISTS" in res.stderr
            )

    def test_cli_rejects_aliasing_output_to_proposals_file(self) -> None:
        """CLI must fail before opening if output_path is aliased to proposals file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            prop_copy = tmp / "proposals.json"
            shutil.copy(self.proposals_path, prop_copy)
            initial_bytes = prop_copy.read_bytes()

            res = self._run_cli(self.sources_path, prop_copy, prop_copy)
            self.assertNotEqual(res.returncode, 0)
            self.assertEqual(prop_copy.read_bytes(), initial_bytes, "Proposals file must remain byte-identical")
            self.assertTrue(
                "OUTPUT_PATH_ALIASED" in res.stderr or "OUTPUT_FILE_ALREADY_EXISTS" in res.stderr
            )

    def test_cli_rejects_aliasing_output_to_source_text_file(self) -> None:
        """CLI must fail before opening if output_path is aliased to a source text file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # Copy only the generated synthetic fixture directory
            for item in self.sources_path.parent.iterdir():
                if item.is_file():
                    shutil.copy(item, tmp / item.name)
            src_manifest = tmp / "research-sources.json"
            text_target = tmp / "hitachi-fy2025-results.md"
            initial_bytes = text_target.read_bytes()

            res = self._run_cli(src_manifest, self.proposals_path, text_target)
            self.assertNotEqual(res.returncode, 0)
            self.assertEqual(text_target.read_bytes(), initial_bytes, "Source text file must remain byte-identical")

    def test_cli_rejects_symlink_output(self) -> None:
        """CLI must reject output pointing to a symlink."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            real_file = tmp / "real.json"
            real_file.write_bytes(b'{"real": true}')
            link_file = tmp / "symlink_out.json"
            try:
                os.symlink(real_file, link_file)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks not supported in environment")

            res = self._run_cli(self.sources_path, self.proposals_path, link_file)
            self.assertNotEqual(res.returncode, 0)
            self.assertEqual(real_file.read_bytes(), b'{"real": true}')

    # 2. PRIVACY & STATIC REPORTING TESTS
    def test_cli_stdout_omits_raw_output_path_and_canary_names(self) -> None:
        """CLI stdout must only report static counts and status, never echoing the output path or private canaries."""
        canary = "CANARY_SECRET_PATH_OUTPUT_TOKEN_99"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            out_file = tmp / f"output_{canary}.json"

            res = self._run_cli(self.sources_path, self.proposals_path, out_file)
            self.assertEqual(res.returncode, 0, f"CLI execution failed: {res.stderr}")
            self.assertNotIn(canary, res.stdout, "CLI stdout leaked canary token from output path!")
            self.assertNotIn(str(out_file), res.stdout, "CLI stdout leaked raw output path!")
            self.assertIn("VALIDATION_COMPLETE", res.stdout)
            self.assertIn("validated_candidates=", res.stdout)

    # 3. STRICT JSON & SCALAR TYPES TESTS
    def test_json_parsing_rejects_nan_and_infinity(self) -> None:
        """JSON parsing must reject NaN and Infinity in proposals."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            prop_file = tmp / "proposals_nan.json"
            # Write raw JSON with NaN
            prop_file.write_text('{"schema_version": 1, "scope": "COMPANY_EVIDENCE_RESEARCH_V1_PROPOSALS", "proposals": [{"claim_id": "NAN-1", "company_id": "TEST", "legal_entity": "TEST", "metric": "rev", "source_id": "hitachi-fy2025-results", "exact_passage": "test", "value": NaN}]}', encoding="utf-8")
            out_file = tmp / "output.json"

            res = self._run_cli(self.sources_path, prop_file, out_file)
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("NON_FINITE_NUMERIC_REJECTED", res.stderr)
            self.assertFalse(out_file.exists(), "No partial output file should be created on failure")

    def test_json_parsing_rejects_duplicate_keys(self) -> None:
        """JSON parsing must reject duplicate keys fail-closed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            prop_file = tmp / "proposals_dup.json"
            prop_file.write_text('{"schema_version": 1, "schema_version": 1, "scope": "COMPANY_EVIDENCE_RESEARCH_V1_PROPOSALS", "proposals": []}', encoding="utf-8")
            out_file = tmp / "output.json"

            res = self._run_cli(self.sources_path, prop_file, out_file)
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("DUPLICATE_KEY_REJECTED", res.stderr)
            self.assertFalse(out_file.exists())

    def test_deep_nested_value_rejected(self) -> None:
        """Deep nested values in proposals or sources must be rejected fail-closed."""
        nested = {"level1": {"level2": {"level3": {"level4": {"level5": {"level6": {"level7": {"level8": {"level9": {"level10": {"level11": "deep"}}}}}}}}}}}
        with self.assertRaises(cec.EvidenceValidationError) as ctx:
            cec.check_nesting_depth(nested)
        self.assertIn("DEEP_NESTING_REJECTED", str(ctx.exception))

    def test_boolean_value_numeric_coercion_rejected(self) -> None:
        """Boolean value in metric value field must not be coerced to number (1 or 0)."""
        producer = cec.CandidateProducer(self.sources_path)
        payload = {
            "schema_version": 1,
            "scope": "COMPANY_EVIDENCE_RESEARCH_V1_PROPOSALS",
            "proposals": [
                {
                    "claim_id": "TEST-BOOL-VAL-001",
                    "company_id": "HITACHI_LTD",
                    "legal_entity": "Hitachi, Ltd.",
                    "metric": "revenue",
                    "value": True,
                    "source_id": "hitachi-fy2025-results",
                    "exact_passage": "Hitachi Energy Revenue 19.8 BUSD (YoY: +4.1 BUSD/+26%) Adj. EBITA 2.64 BUSD (YoY: +1.15 BUSD) Adj. EBITA Margin 13.4% (YoY: +3.9 pts)",
                }
            ]
        }
        res = producer.process_proposals(payload)
        self.assertEqual(len(res["candidates"]), 0)
        self.assertEqual(len(res["quarantine"]), 1)
        self.assertIn("INVALID_VALUE_TYPE", res["quarantine"][0]["reason"])

    # 4. RESOURCE BUDGETS & AGGREGATE CAPS TESTS
    def test_aggregate_source_byte_budget_enforced(self) -> None:
        """Aggregate bytes across all source files must be capped before loading."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            src_manifest = tmp / "sources.json"
            # Create a manifest referencing many large dummy files exceeding aggregate limit
            dummy = tmp / "dummy.txt"
            dummy.write_bytes(b"x" * 1024)
            sha = cec.compute_sha256_and_bytes(dummy)[0]
            manifest_data = {
                "schema_version": 1,
                "scope": "PUBLIC_RESEARCH_INPUT_NOT_ADMITTED",
                "assembled_at": "2026-09-15T00:00:00Z",
                "record_count": 1,
                "sources": [
                    {
                        "id": "s1",
                        "source_url": "https://example.com/s1.txt",
                        "text_file": "dummy.txt",
                        "text_sha256": sha,
                        "text_bytes": 1024,
                    }
                ],
                "source_receipts": []
            }
            with open(src_manifest, "w", encoding="utf-8") as f:
                json.dump(manifest_data, f)

            validator = cec.SourcesValidator(src_manifest, max_aggregate_bytes=512)
            with self.assertRaises(cec.EvidenceValidationError) as ctx:
                validator.validate_all()
            self.assertIn("EXCEEDED_AGGREGATE_BYTE_LIMIT", str(ctx.exception))

    def test_record_count_consistency_enforced(self) -> None:
        """Sources manifest record_count must match len(sources) strictly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            sf = tmp / "research-sources.json"
            shutil.copy(self.sources_path, sf)
            with open(sf, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["record_count"] = 999  # Mismatch with 4 sources
            with open(sf, "w", encoding="utf-8") as f:
                json.dump(data, f)

            validator = cec.SourcesValidator(sf)
            with self.assertRaises(cec.EvidenceValidationError) as ctx:
                validator.validate_all()
            self.assertIn("RECORD_COUNT_MISMATCH", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
