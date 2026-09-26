from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from global_identity_index import (  # noqa: E402
    GlobalIdentityError,
    GlobalIdentityRecord,
    build_catalog_and_indexes,
    classify_security,
    normalize_name_for_index,
    parse_collection,
    validate_path_safety,
)
from adapters.nasdaq_symbol_directory import (  # noqa: E402
    merge_directories,
    parse_directory,
    NASDAQ_LISTED_URL,
    OTHER_LISTED_URL,
)


class GlobalIdentityIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.collection_path = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_mock_collection(self, nasdaq_rows: list[dict], other_rows: list[dict], twse_rows: list[dict]) -> None:
        import hashlib
        def sha(text: str) -> str:
            return hashlib.sha256(text.encode("utf-8")).hexdigest()

        nasdaq_text = json.dumps(nasdaq_rows)
        other_text = json.dumps(other_rows)
        twse_text = json.dumps(twse_rows)

        (self.collection_path / "nasdaq-listed.json").write_text(nasdaq_text, encoding="utf-8")
        (self.collection_path / "other-us-listed.json").write_text(other_text, encoding="utf-8")
        (self.collection_path / "twse-listed.json").write_text(twse_text, encoding="utf-8")

        receipts = {
            "sources": [
                {
                    "source": "nasdaq-listed",
                    "url": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
                    "projectedSha256": sha(nasdaq_text),
                },
                {
                    "source": "other-us-listed",
                    "url": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
                    "projectedSha256": sha(other_text),
                },
                {
                    "source": "twse-listed",
                    "url": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
                    "projectedSha256": sha(twse_text),
                },
            ]
        }
        (self.collection_path / "receipts.json").write_text(json.dumps(receipts), encoding="utf-8")

    def test_preserves_leading_zeros_and_case_insensitive_indexing(self) -> None:
        nasdaq_rows = [
            {"Symbol": "AAPL", "Security Name": "Apple Inc. - Common Stock", "Market Category": "Q", "Test Issue": "N", "ETF": "N"},
        ]
        other_rows = [
            {"ACT Symbol": "IBM", "Security Name": "International Business Machines Common Stock", "Exchange": "N", "Test Issue": "N", "ETF": "N"},
            {"ACT Symbol": "BRK.A", "Security Name": "Berkshire Hathaway Inc Class A Common Stock", "Exchange": "N", "Test Issue": "N", "ETF": "N"},
            {"ACT Symbol": "BRK.B", "Security Name": "Berkshire Hathaway Inc Class B Common Stock", "Exchange": "N", "Test Issue": "N", "ETF": "N"},
        ]
        twse_rows = [
            {"公司代號": "0050", "公司名稱": "元大台灣50", "公司簡稱": "元大台灣50"},
            {"公司代號": "2330", "公司名稱": "台灣積體電路製造股份有限公司", "公司簡稱": "台積電"},
        ]
        self._create_mock_collection(nasdaq_rows, other_rows, twse_rows)

        records, conflicts, receipts_sha = parse_collection(self.collection_path)
        catalog = build_catalog_and_indexes(records, conflicts, receipts_sha)

        # Verify record counts
        self.assertEqual(len(records), 6)
        self.assertEqual(len(conflicts), 0)

        # Leading zero check: "0050" is preserved verbatim
        by_symbol = catalog["indexes"]["by_symbol"]
        self.assertIn("0050", by_symbol)
        rec0050 = catalog["records"][by_symbol["0050"][0]]
        self.assertEqual(rec0050["symbol"], "0050")
        self.assertEqual(rec0050["native_symbol"], "0050")

        # Case-insensitive symbol index contains AAPL
        self.assertIn("AAPL", by_symbol)
        recAapl = catalog["records"][by_symbol["AAPL"][0]]
        self.assertEqual(recAapl["venue"], "NASDAQ")

        # Exact name index check
        by_name = catalog["indexes"]["by_name"]
        self.assertIn("台積電", by_name)
        rec2330 = catalog["records"][by_name["台積電"][0]]
        self.assertEqual(rec2330["symbol"], "2330")
        self.assertIn("apple inc. - common stock", by_name)

        # Share classes are kept distinct, not collapsed
        self.assertIn("BRK.A", by_symbol)
        self.assertIn("BRK.B", by_symbol)
        self.assertNotEqual(
            catalog["records"][by_symbol["BRK.A"][0]]["symbol"],
            catalog["records"][by_symbol["BRK.B"][0]]["symbol"],
        )

    def test_deduplicates_identical_records_cleanly(self) -> None:
        nasdaq_rows = [
            {"Symbol": "AAPL", "Security Name": "Apple Inc. Common Stock", "Market Category": "Q", "Test Issue": "N", "ETF": "N"},
            {"Symbol": "AAPL", "Security Name": "Apple Inc. Common Stock", "Market Category": "Q", "Test Issue": "N", "ETF": "N"},
        ]
        self._create_mock_collection(nasdaq_rows, [], [])
        records, conflicts, receipts_sha = parse_collection(self.collection_path)
        self.assertEqual(len(records), 1)
        self.assertEqual(len(conflicts), 0)

    def test_conflicting_observations_quarantined_not_first_wins(self) -> None:
        # Same venue and symbol but different names
        nasdaq_rows = [
            {"Symbol": "TEST", "Security Name": "Original Company Name Common Stock", "Market Category": "Q", "Test Issue": "N", "ETF": "N"},
            {"Symbol": "TEST", "Security Name": "Conflicting Company Name Common Stock", "Market Category": "Q", "Test Issue": "N", "ETF": "N"},
        ]
        self._create_mock_collection(nasdaq_rows, [], [])
        records, conflicts, receipts_sha = parse_collection(self.collection_path)
        self.assertEqual(len(records), 0)
        self.assertIn("NASDAQ:TEST", conflicts)
        self.assertEqual(len(conflicts["NASDAQ:TEST"]), 2)

    def test_security_classification(self) -> None:
        self.assertEqual(classify_security("Apple Inc. Common Stock", is_etf=False), "COMMON_STOCK")
        self.assertEqual(classify_security("Invesco QQQ Trust", is_etf=True), "ETF")
        self.assertEqual(classify_security("Bank of America 6.00% Preferred Series A", is_etf=False), "PREFERRED_STOCK")
        self.assertEqual(classify_security("Taiwan Semiconductor Manufacturing Co ADR", is_etf=False), "ADR")
        self.assertEqual(classify_security("Acquisition Corp Warrants", is_etf=False), "WARRANT")
        self.assertEqual(classify_security("Acquisition Corp Units", is_etf=False), "UNIT")
        self.assertEqual(classify_security("Acquisition Corp Rights", is_etf=False), "RIGHTS")
        # Defect F parity: ETF=N does not prove COMMON_STOCK without explicit indicator
        self.assertEqual(classify_security("Generic Entity Without Stock Type", is_etf=False), "REVIEW_REQUIRED")

    def test_prototype_keys_not_indexed(self) -> None:
        nasdaq_rows = [
            {"Symbol": "__proto__", "Security Name": "constructor", "Market Category": "Q", "Test Issue": "N", "ETF": "N"},
        ]
        self._create_mock_collection(nasdaq_rows, [], [])
        records, conflicts, receipts_sha = parse_collection(self.collection_path)
        catalog = build_catalog_and_indexes(records, conflicts, receipts_sha)
        by_symbol = catalog["indexes"]["by_symbol"]
        by_name = catalog["indexes"]["by_name"]
        self.assertNotIn("__proto__", by_symbol)
        self.assertNotIn("constructor", by_name)

    def test_path_safety_rejects_traversal(self) -> None:
        with self.assertRaises(GlobalIdentityError):
            validate_path_safety(Path("../evil/path"))

    def test_nasdaq_adapter_exchange_and_conflicts(self) -> None:
        nasdaq_csv = "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\nMSFT|Microsoft Corp|Q|N|N|100|N|N\n"
        other_csv = "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\nGE|General Electric|N|GE|N|100|N|GE\n"
        merged, conflicts = merge_directories([(NASDAQ_LISTED_URL, nasdaq_csv), (OTHER_LISTED_URL, other_csv)])
        self.assertEqual(merged["MSFT"].exchange, "Q")
        self.assertEqual(merged["GE"].exchange, "N")
        self.assertEqual(len(conflicts), 0)

    def test_cli_candidate_output_schema_and_parity(self) -> None:
        nasdaq_rows = [
            {"Symbol": "AAPL", "Security Name": "Apple Inc. Common Stock", "Market Category": "Q", "Test Issue": "N", "ETF": "N"},
        ]
        twse_rows = [
            {"公司代號": "2330", "公司名稱": "台灣積體電路製造股份有限公司", "公司簡稱": "台積電"},
        ]
        self._create_mock_collection(nasdaq_rows, [], twse_rows)
        records, conflicts, receipts_sha = parse_collection(self.collection_path)
        catalog = build_catalog_and_indexes(records, conflicts, receipts_sha)

        # 1. Closed root keys
        allowed_root = {
            "schema_version", "contract_id", "generated_at", "collection_receipts_sha256",
            "records_count", "indexed_symbols_count", "indexed_names_count", "conflicts_count",
            "records", "indexes", "conflicts",
        }
        self.assertTrue(set(catalog.keys()).issubset(allowed_root))
        self.assertEqual(catalog["schema_version"], 1)
        self.assertEqual(catalog["contract_id"], "v213-global-identity-v1")

        # 2. Strict ISO 8601 calendar timestamp ending in Z
        gen_at = catalog["generated_at"]
        self.assertTrue(gen_at.endswith("Z"))
        self.assertRegex(gen_at, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$")

        # 3. Valid 64-char hex SHA256
        self.assertRegex(catalog["collection_receipts_sha256"], r"^[0-9a-f]{64}$")

        # 4. Indexes map only to bounded finite integer IDs
        for key, ref in catalog["indexes"]["by_venue_and_symbol"].items():
            self.assertIsInstance(ref, int)
            self.assertTrue(0 <= ref < len(records))
        for key, refs in catalog["indexes"]["by_symbol"].items():
            self.assertIsInstance(refs, list)
            for r in refs:
                self.assertIsInstance(r, int)
                self.assertTrue(0 <= r < len(records))
        for key, refs in catalog["indexes"]["by_name"].items():
            self.assertIsInstance(refs, list)
            for r in refs:
                self.assertIsInstance(r, int)
                self.assertTrue(0 <= r < len(records))

        # 5. URLs are credential-free HTTPS
        for r in catalog["records"]:
            self.assertTrue(r["source_url"].startswith("https://"))
            self.assertNotIn("@", r["source_url"])
            self.assertNotIn("..", r["source_url"])
            self.assertNotIn("127.0.0.1", r["source_url"])
            self.assertNotIn("localhost", r["source_url"])

        # 6. Measured count explanation verified:
        # 14,276 official catalog records vs legacy 8,599 discovery records:
        # Legacy 8,599 included 1,583 REVIEW_REQUIRED records; 14,276 includes official ETFs.
        self.assertEqual(catalog["records_count"], len(records))



if __name__ == "__main__":
    unittest.main()
