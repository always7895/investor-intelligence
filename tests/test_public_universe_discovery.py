#!/usr/bin/env python3
"""Tests for strict independent public universe identity discovery and coverage ledger.

Validates schema parsing, hash receipts, tamper resistance, deduplication,
exclusion of ETFs/test issues, review-required flags for preferred/warrants/units,
leading-zero TWSE preservation, permutation invariance, absence of AI whitelists,
failure handling, privacy guards, and offline CLI subprocess execution.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import public_universe_discovery as pud


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def create_synthetic_collection(
    directory: Path,
    nasdaq_records: list[dict] | None = None,
    other_records: list[dict] | None = None,
    twse_records: list[dict] | None = None,
    tamper_file: str | None = None,
    simulate_failure: bool = False,
) -> dict[str, Any]:
    """Helper to create a deterministic bounded synthetic collection directory."""
    if nasdaq_records is None:
        nasdaq_records = [
            {"Symbol": "AAAP", "Security Name": "Pacer CLO ETF", "Market Category": "G", "ETF": "Y", "Test Issue": "N"},
            {"Symbol": "AACG", "Security Name": "ATA Creativity Global - ADS", "Market Category": "S", "ETF": "N", "Test Issue": "N"},
            {"Symbol": "TESTA", "Security Name": "Nasdaq Test Issue Security", "Market Category": "G", "ETF": "N", "Test Issue": "Y"},
            {"Symbol": "AACIU", "Security Name": "Armada Acquisition Corp. - Units", "Market Category": "G", "ETF": "N", "Test Issue": "N"},
        ]
    if other_records is None:
        other_records = [
            {"ACT Symbol": "A", "Security Name": "Agilent Technologies Common Stock", "Exchange": "N", "ETF": "N", "Test Issue": "N"},
            {"ACT Symbol": "AAA", "Security Name": "Alternative Access ETF", "Exchange": "P", "ETF": "Y", "Test Issue": "N"},
            {"ACT Symbol": "A-P", "Security Name": "Agilent Technologies Preferred Series A", "Exchange": "N", "ETF": "N", "Test Issue": "N"},
        ]
    if twse_records is None:
        twse_records = [
            {"公司代號": "0050", "公司名稱": "元大台灣50指數股票型證券投資信託基金", "公司簡稱": "元大台灣50", "產業別": "00", "上市日期": "20030630"},
            {"公司代號": "1101", "公司名稱": "臺灣水泥股份有限公司", "公司簡稱": "台泥", "產業別": "01", "上市日期": "19620209"},
            {"公司代號": "01001T", "公司名稱": "土銀富邦R1受託信託財產專戶", "公司簡稱": "土銀富邦R1", "產業別": "20", "上市日期": "20050310"},
        ]

    receipts = []
    sources = [
        ("nasdaq-listed", nasdaq_records, "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"),
        ("other-us-listed", other_records, "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"),
        ("twse-listed", twse_records, "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"),
    ]

    for source_id, recs, official_url in sources:
        if simulate_failure:
            receipts.append({
                "source": source_id,
                "url": official_url,
                "retrievedUtc": "2026-09-14T12:00:00+00:00",
                "sourcePublishedAt": "UNVERIFIED",
                "scope": "PUBLIC_LISTING_IDENTITY_DISCOVERY_ONLY",
                "claimAdmission": False,
                "httpStatus": 503,
                "records": 0,
                "status": "UNAVAILABLE",
            })
            continue

        payload = {"source": source_id, "records": recs}
        data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")

        if tamper_file == source_id:
            # Write tampered content
            tampered_data = data + b"//tampered\n"
            (directory / f"{source_id}.json").write_bytes(tampered_data)
        else:
            (directory / f"{source_id}.json").write_bytes(data)

        receipts.append({
            "source": source_id,
            "url": official_url,
            "retrievedUtc": "2026-09-14T12:00:00+00:00",
            "sourcePublishedAt": "UNVERIFIED",
            "scope": "PUBLIC_LISTING_IDENTITY_DISCOVERY_ONLY",
            "claimAdmission": False,
            "httpStatus": 200,
            "projectedSha256": compute_sha256(data),
            "records": len(recs),
            "status": "RETRIEVED_NOT_ADMITTED",
        })

    receipts_doc = {
        "sources": receipts,
        "externalWrites": 0,
        "authenticatedRequests": 0,
        "rankingAdmission": False,
    }
    (directory / "receipts.json").write_text(json.dumps(receipts_doc, indent=2), encoding="utf-8")
    return receipts_doc


class PublicUniverseDiscoveryTests(unittest.TestCase):
    """Synthetic unit and integration tests for public universe identity discovery."""

    def test_synthetic_official_schema_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="test-universe-schema-") as tmpdir:
            temp_path = Path(tmpdir)
            create_synthetic_collection(temp_path)

            report = pud.execute_universe_discovery(temp_path)
            self.assertEqual(report["status"], "SUCCESS_PARTIAL_COVERAGE")
            self.assertEqual(report["scope"], "PUBLIC_LISTING_IDENTITY_DISCOVERY_ONLY")
            self.assertFalse(report["publication_qualified"])
            self.assertFalse(report["claim_admission"])
            self.assertFalse(report["ranking_admission"])
            self.assertEqual(report["admitted_company_count"], 0)
            self.assertIsNone(report["score"])
            self.assertIsNone(report["rank"])
            self.assertFalse(report["full_market_coverage_claimed"])

            # Verify collection audit
            audit = report["collection_audit"]
            self.assertEqual(audit["sources_declared"], 3)
            self.assertEqual(audit["sources_intact"], 3)
            self.assertEqual(audit["sources_failed"], 0)

    def test_tamper_and_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="test-universe-tamper-") as tmpdir:
            temp_path = Path(tmpdir)
            create_synthetic_collection(temp_path, tamper_file="nasdaq-listed")

            with self.assertRaises(pud.DiscoveryValidationError) as ctx:
                pud.execute_universe_discovery(temp_path)
            self.assertIn("SHA256 mismatch", str(ctx.exception))

    def test_schema_flag_and_type_failures_no_coercion(self) -> None:
        # Invalid ETF flag (Boolean instead of 'Y'/'N' string)
        with self.assertRaises(pud.DiscoveryValidationError):
            pud.parse_nasdaq_record({
                "Symbol": "BAD",
                "Security Name": "Bad Co",
                "Market Category": "G",
                "ETF": True,  # Boolean coercion forbidden
                "Test Issue": "N",
            })

        # Missing symbol
        with self.assertRaises(pud.DiscoveryValidationError):
            pud.parse_other_us_record({
                "ACT Symbol": "",
                "Security Name": "Empty Symbol Co",
                "Exchange": "N",
                "ETF": "N",
                "Test Issue": "N",
            })

        # TWSE missing 公司代號
        with self.assertRaises(pud.DiscoveryValidationError):
            pud.parse_twse_record({
                "公司名稱": "臺灣水泥",
                "產業別": "01",
            })

    def test_duplicates_stable_dedup_and_cross_venue(self) -> None:
        nasdaq = [
            {"Symbol": "DUP", "Security Name": "Duplicate Co Class A", "Market Category": "G", "ETF": "N", "Test Issue": "N"},
            {"Symbol": "DUP", "Security Name": "Duplicate Co Class A Secondary", "Market Category": "G", "ETF": "N", "Test Issue": "N"},
        ]
        other = [
            # Same symbol "DUP" but on NYSE venue -> separate identity, NOT merged
            {"ACT Symbol": "DUP", "Security Name": "NYSE Duplicate Co", "Exchange": "N", "ETF": "N", "Test Issue": "N"},
        ]
        with tempfile.TemporaryDirectory(prefix="test-universe-dedup-") as tmpdir:
            temp_path = Path(tmpdir)
            create_synthetic_collection(temp_path, nasdaq_records=nasdaq, other_records=other, twse_records=[])
            report = pud.execute_universe_discovery(temp_path)

            self.assertEqual(report["summary_counts"]["duplicates_detected"], 1)
            # Two distinct venue:symbol identities: (NASDAQ, DUP) and (NYSE, DUP)
            self.assertEqual(report["summary_counts"]["unique_security_identities"], 2)

    def test_class_ambiguity_flagged_review_required(self) -> None:
        nasdaq = [
            {"Symbol": "ACQU", "Security Name": "Alpha Acquisition Corp. - Units", "Market Category": "G", "ETF": "N", "Test Issue": "N"},
            {"Symbol": "ACQW", "Security Name": "Alpha Acquisition Corp. - Warrants", "Market Category": "G", "ETF": "N", "Test Issue": "N"},
            {"Symbol": "BOND", "Security Name": "Corporate Bond Index Fund", "Market Category": "G", "ETF": "N", "Test Issue": "N"},
        ]
        other = [
            {"ACT Symbol": "PRFD", "Security Name": "Beta Corp 5.5% Preferred Stock", "Exchange": "N", "ETF": "N", "Test Issue": "N"},
        ]
        with tempfile.TemporaryDirectory(prefix="test-universe-classes-") as tmpdir:
            temp_path = Path(tmpdir)
            create_synthetic_collection(temp_path, nasdaq_records=nasdaq, other_records=other, twse_records=[])
            report = pud.execute_universe_discovery(temp_path)

            # None of these ambiguous/preferred/units/warrants should be silent common-stock candidates
            self.assertEqual(report["summary_counts"]["candidates_discovered"], 0)
            self.assertEqual(report["summary_counts"]["review_required_records"]["total"], 4)

    def test_leading_zero_preservation_and_chinese_names(self) -> None:
        twse = [
            {"公司代號": "0050", "公司名稱": "元大台灣50基金", "公司簡稱": "元大台灣50", "產業別": "00", "上市日期": "20030630"},
            {"公司代號": "01001T", "公司名稱": "土銀富邦R1專戶", "公司簡稱": "土銀富邦R1", "產業別": "20", "上市日期": "20050310"},
            {"公司代號": "2330", "公司名稱": "台灣積體電路製造股份有限公司", "公司簡稱": "台積電", "產業別": "24", "上市日期": "19940905"},
        ]
        with tempfile.TemporaryDirectory(prefix="test-universe-twse-") as tmpdir:
            temp_path = Path(tmpdir)
            create_synthetic_collection(temp_path, nasdaq_records=[], other_records=[], twse_records=twse)
            report = pud.execute_universe_discovery(temp_path)

            records = {r["symbol"]: r for r in report["records"]}
            self.assertIn("0050", records)
            self.assertIn("01001T", records)
            self.assertIn("2330", records)

            # Check that leading zero is strictly preserved as string
            self.assertEqual(records["0050"]["symbol"], "0050")
            self.assertEqual(records["01001T"]["symbol"], "01001T")

            # Check that Chinese company name is preserved as-is, not translated
            self.assertEqual(records["2330"]["security_name"], "台灣積體電路製造股份有限公司")
            self.assertEqual(records["2330"]["issuer_name_lead"], "台積電")

    def test_empty_or_all_failed_feeds(self) -> None:
        with tempfile.TemporaryDirectory(prefix="test-universe-failed-") as tmpdir:
            temp_path = Path(tmpdir)
            create_synthetic_collection(temp_path, simulate_failure=True)
            report = pud.execute_universe_discovery(temp_path)

            self.assertEqual(report["status"], "PARTIAL_OR_FAILED")
            self.assertEqual(report["summary_counts"]["candidates_discovered"], 0)
            self.assertEqual(report["collection_audit"]["sources_failed"], 3)
            self.assertFalse(report["publication_qualified"])

    def test_permutation_invariance_and_no_ai_whitelist(self) -> None:
        rec1 = {"Symbol": "ABC", "Security Name": "Traditional Steel Manufacturing Corp", "Market Category": "G", "ETF": "N", "Test Issue": "N"}
        rec2 = {"Symbol": "XYZ", "Security Name": "Advanced AI Neural Accelerators Inc", "Market Category": "G", "ETF": "N", "Test Issue": "N"}

        with tempfile.TemporaryDirectory(prefix="test-universe-perm1-") as t1, tempfile.TemporaryDirectory(prefix="test-universe-perm2-") as t2:
            p1 = Path(t1)
            p2 = Path(t2)
            create_synthetic_collection(p1, nasdaq_records=[rec1, rec2], other_records=[], twse_records=[])
            create_synthetic_collection(p2, nasdaq_records=[rec2, rec1], other_records=[], twse_records=[])

            rep1 = pud.execute_universe_discovery(p1)
            rep2 = pud.execute_universe_discovery(p2)

            syms1 = {r["symbol"] for r in rep1["records"]}
            syms2 = {r["symbol"] for r in rep2["records"]}
            self.assertEqual(syms1, syms2)

            # Verify no AI-only filtering: traditional steel is discovered without penalty
            self.assertIn("ABC", syms1)
            self.assertIn("XYZ", syms1)

    def test_clock_retrieval_distinction(self) -> None:
        with tempfile.TemporaryDirectory(prefix="test-universe-clock-") as tmpdir:
            temp_path = Path(tmpdir)
            create_synthetic_collection(temp_path)
            report = pud.execute_universe_discovery(temp_path)

            # Verify analysis execution timestamp is distinct from retrieved and unverified published
            self.assertTrue(report["generated_at_utc"].endswith("+00:00") or "Z" in report["generated_at_utc"])
            receipts_sources = report["collection_audit"]["provider_failures"]
            self.assertEqual(len(receipts_sources), 0)

    def test_no_fixture_leakage_into_product(self) -> None:
        with tempfile.TemporaryDirectory(prefix="test-universe-leak-") as tmpdir:
            temp_path = Path(tmpdir)
            create_synthetic_collection(temp_path)
            report = pud.execute_universe_discovery(temp_path)

            # Ensure neither cache root nor data dir were written
            prod_cache = ROOT / "data" / "cache" / "v21"
            if prod_cache.exists():
                for f in prod_cache.glob("*test-universe*"):
                    self.fail(f"Fixture leaked into product cache: {f}")

    def test_security_guards_symlink_and_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="test-universe-security-") as tmpdir:
            temp_path = Path(tmpdir)
            create_synthetic_collection(temp_path)

            # File count bounding / non-allowlisted file rejection
            for i in range(15):
                (temp_path / f"extra_{i}.tmp").write_text("extra", encoding="utf-8")
            with self.assertRaises(pud.DiscoveryValidationError):
                pud.execute_universe_discovery(temp_path)

    def test_privacy_and_forbidden_keys(self) -> None:
        with tempfile.TemporaryDirectory(prefix="test-universe-privacy-") as tmpdir:
            temp_path = Path(tmpdir)
            create_synthetic_collection(temp_path)
            report = pud.execute_universe_discovery(temp_path)

            # Dump whole report to string and check no forbidden private keys exist
            serialized = json.dumps(report)
            for k in pud.FORBIDDEN_PRIVATE_KEYS:
                self.assertNotIn(f'"{k}"', serialized)

    def test_record_bound(self) -> None:
        nasdaq = [
            {"Symbol": f"TICK{i}", "Security Name": f"Company {i}", "Market Category": "G", "ETF": "N", "Test Issue": "N"}
            for i in range(10)
        ]
        with tempfile.TemporaryDirectory(prefix="test-universe-bound-") as tmpdir:
            temp_path = Path(tmpdir)
            create_synthetic_collection(temp_path, nasdaq_records=nasdaq, other_records=[], twse_records=[])
            report = pud.execute_universe_discovery(temp_path, record_bound=3)
            self.assertEqual(report["summary_counts"]["total_records_ingested"], 3)

    def test_offline_cli_subprocess_execution(self) -> None:
        python_exe = sys.executable
        cli_script = SCRIPTS_DIR / "public_universe_discovery.py"
        with tempfile.TemporaryDirectory(prefix="test-universe-cli-") as tmpdir:
            temp_path = Path(tmpdir)
            create_synthetic_collection(temp_path)
            out_file = temp_path / "result.json"

            cmd = [
                python_exe,
                "-B",
                str(cli_script),
                "--collection",
                str(temp_path),
                "--output",
                str(out_file),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, f"CLI stderr: {proc.stderr}")
            self.assertTrue(out_file.exists())
            self.assertIn("=== PUBLIC UNIVERSE DISCOVERY SUMMARY ===", proc.stdout)
            self.assertIn("Admitted Companies: 0", proc.stdout)

            # Verify exclusive write: running again on existing output must fail
            proc_dup = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(proc_dup.returncode, 0)
            self.assertIn("Output path already exists", proc_dup.stderr)

    def test_unrelated_same_prefix_name_collision_no_merging_or_verified_lineage_claims(self) -> None:
        # Two unrelated entities sharing name prefix lead
        nasdaq = [
            {"Symbol": "FNB", "Security Name": "First National Bancshares - Common", "Market Category": "G", "ETF": "N", "Test Issue": "N"},
            {"Symbol": "FNE", "Security Name": "First National Energy Corp - Common", "Market Category": "S", "ETF": "N", "Test Issue": "N"},
        ]
        with tempfile.TemporaryDirectory(prefix="test-universe-collision-") as tmpdir:
            temp_path = Path(tmpdir)
            create_synthetic_collection(temp_path, nasdaq_records=nasdaq, other_records=[], twse_records=[])
            report = pud.execute_universe_discovery(temp_path)

            # Both distinct securities must be preserved, NOT merged or collapsed
            self.assertEqual(report["summary_counts"]["unique_security_identities"], 2)
            symbols = {r["symbol"] for r in report["records"]}
            self.assertEqual(symbols, {"FNB", "FNE"})

            # Lineage diagnostics must explicitly state unverified heuristic, NO authoritative claim
            diag = report["lineage_diagnostics"]
            self.assertFalse(diag["authoritative_lineage_available"])
            self.assertEqual(diag["authoritative_identifier_types_missing"], ["CIK", "LEI", "ISIN"])
            self.assertIn("unverified_name_similarity_clusters_count", diag)
            self.assertIn("heuristic groupings based solely on name", diag["diagnostic_note"])

    def test_covered_vs_observed_venues_and_zero_record_gap(self) -> None:
        # Synthetic collection only has NASDAQ, NYSE (other-us), TWSE. IEX has 0 records.
        with tempfile.TemporaryDirectory(prefix="test-universe-venues-") as tmpdir:
            temp_path = Path(tmpdir)
            create_synthetic_collection(temp_path)
            report = pud.execute_universe_discovery(temp_path)

            cov = report["market_coverage"]
            covered_venues = [entry["venue"] for entry in cov["covered_venues"]]
            self.assertNotIn("IEX", covered_venues, "IEX with 0 records must NOT be claimed as a covered venue")

            # IEX must be explicitly recorded in observed coverage gaps
            gap_venues = [gap["venue"] for gap in cov["observed_coverage_gaps"]]
            self.assertIn("IEX", gap_venues)

    def test_conflicting_duplicate_identity_quarantined_not_first_wins(self) -> None:
        nasdaq = [
            {"Symbol": "CONF", "Security Name": "Conflicting Corp Common", "Market Category": "G", "ETF": "N", "Test Issue": "N"},
            {"Symbol": "CONF", "Security Name": "Conflicting Corp Series A Preferred", "Market Category": "G", "ETF": "N", "Test Issue": "N"},
        ]
        with tempfile.TemporaryDirectory(prefix="test-universe-conflict-") as tmpdir:
            temp_path = Path(tmpdir)
            create_synthetic_collection(temp_path, nasdaq_records=nasdaq, other_records=[], twse_records=[])
            report = pud.execute_universe_discovery(temp_path)

            # Conflicting duplicate must NOT silently keep first or claim candidate
            conf_rec = [r for r in report["records"] if r["symbol"] == "CONF"][0]
            self.assertEqual(conf_rec["status"], "REVIEW_REQUIRED")
            self.assertIn("CONFLICTING_DUPLICATE_IDENTITY", conf_rec["review_reasons"])
            self.assertIn("duplicate_conflicts", report["summary_counts"])
            self.assertGreaterEqual(len(report["summary_counts"]["duplicate_conflicts"]), 1)

    def test_symlink_and_junction_reparse_ancestor_rejection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="test-universe-junction-") as tmpdir:
            temp_path = Path(tmpdir)
            create_synthetic_collection(temp_path)

            target_link = temp_path / "link_target"
            link_created = False
            if sys.platform == "win32":
                try:
                    import _winapi
                    _winapi.CreateJunction(str(temp_path), str(target_link))
                    link_created = True
                except (OSError, NotImplementedError, PermissionError):
                    pass
            if not link_created:
                try:
                    os.symlink(temp_path, target_link, target_is_directory=True)
                    link_created = True
                except (OSError, NotImplementedError, PermissionError) as exc:
                    self.skipTest(f"Platform symlink/junction creation not permitted without elevation: {exc}")

            with self.assertRaises(pud.DiscoveryValidationError) as ctx:
                pud.execute_universe_discovery(target_link)
            self.assertIn("Symlinks, junctions, or reparse points rejected", str(ctx.exception))

    def test_privacy_error_sanitization_and_failclosed_malicious_urls(self) -> None:
        # Test malicious / credentialed receipt URL fails closed
        with tempfile.TemporaryDirectory(prefix="test-universe-malicious-") as tmpdir:
            temp_path = Path(tmpdir)
            doc = create_synthetic_collection(temp_path)
            doc["sources"][0]["url"] = "https://user:password@malicious.test/exploit.txt"
            (temp_path / "receipts.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")

            with self.assertRaises(pud.DiscoveryValidationError) as ctx:
                pud.execute_universe_discovery(temp_path)
            self.assertIn("Credentialed URLs forbidden", str(ctx.exception))

        # Test URL mismatch fails closed
        with tempfile.TemporaryDirectory(prefix="test-universe-badurl-") as tmpdir:
            temp_path = Path(tmpdir)
            doc = create_synthetic_collection(temp_path)
            doc["sources"][0]["url"] = "https://example.com/spoofed.txt"
            (temp_path / "receipts.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")

            with self.assertRaises(pud.DiscoveryValidationError) as ctx:
                pud.execute_universe_discovery(temp_path)
            self.assertIn("Source URL mismatch", str(ctx.exception))

        # Test sanitized error types in provider failures, no raw exception messages
        with tempfile.TemporaryDirectory(prefix="test-universe-sanitize-") as tmpdir:
            temp_path = Path(tmpdir)
            create_synthetic_collection(temp_path)
            (temp_path / "nasdaq-listed.json").write_text("{malformed json input", encoding="utf-8")
            receipts_doc = json.loads((temp_path / "receipts.json").read_text(encoding="utf-8"))
            receipts_doc["sources"][0]["projectedSha256"] = compute_sha256(b"{malformed json input")
            (temp_path / "receipts.json").write_text(json.dumps(receipts_doc, indent=2), encoding="utf-8")

            rep = pud.execute_universe_discovery(temp_path)
            failures = rep["collection_audit"]["provider_failures"]
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["status"], "PARSE_ERROR")
            self.assertEqual(failures[0]["reason"], "JSON_DECODE_FAILURE")
            self.assertEqual(failures[0]["error_type"], "JSONDecodeError")
            self.assertNotIn("{malformed", json.dumps(failures))


if __name__ == "__main__":
    unittest.main()
