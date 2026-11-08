from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import public_options_provider_gate as gate  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402
import validate_v213_market_products as products  # noqa: E402
from datetime import datetime, timezone  # noqa: E402


class V30OptionsRightsTests(unittest.TestCase):
    def test_catalogue_classification_and_disabled_providers(self):
        doc = json.loads((ROOT / "config/public-options-provider-candidates.json").read_text(encoding="utf-8"))
        rows = {p["id"]: p for p in doc["providers"]}
        required = ("eurex_public_derivatives",
                    "jpx_ose_public_derivatives", "hkex_public_derivatives", "asx_public_options",
                    "krx_open_api_options", "ice_lse_single_stock_options", "tmx_montreal_exchange_options",
                    "nse_india_equity_options")
        for key in required:
            with self.subTest(provider=key):
                row = rows[key]
                self.assertEqual(row["rights_status"], "licence_required")
                self.assertEqual(row["rights_reviewed_at"], "2026-11-02")
                self.assertIs(row["runtime_enabled"], False)
                self.assertIs(row["line_quote_eligible"], False)
        predecessor = json.loads((ROOT / "cloud/src/v213/options-provider-catalog-4065fbe.json").read_text(encoding="utf-8"))
        old_rows = {p["id"]: p for p in predecessor["providers"]}
        for key in ("nyse_options_reference", "cme_delayed_futures_options"):
            self.assertEqual(rows[key], old_rows[key])
        for key in ("cboe_public_options_market_data", "occ_public_market_data"):
            self.assertEqual(rows[key]["rights_status"], "automated_access_prohibited")
            self.assertEqual(rows[key]["rights_reviewed_at"], "2026-11-02")
        self.assertEqual(rows["taifex_public_options"]["rights_status"], "reviewed_public_access")
        self.assertEqual(rows["taifex_public_options"]["rights_reviewed_at"], "2026-11-02")
        self.assertEqual(gate.audit_public_options_providers()[0], [])

    def test_gate_rejects_unlicensed_activation_and_unknown_status(self):
        original = gate._object
        document = original(ROOT / "config/public-options-provider-candidates.json")
        for field, value, message in (("runtime_enabled", True, "lacks rights review"),
                                      ("automated_access_allowed", True, "licence-required source"),
                                      ("adapter_status", "adapter_reviewed", "licence-required source"),
                                      ("rights_status", "invented_rights", "invalid rights_status")):
            with self.subTest(field=field):
                changed = copy.deepcopy(document)
                next(p for p in changed["providers"] if p["id"] == "eurex_public_derivatives")[field] = value
                with mock.patch.object(gate, "_object", side_effect=lambda path: changed if path.name == "public-options-provider-candidates.json" else original(path)):
                    findings, _ = gate.audit_public_options_providers()
                self.assertTrue(any(message in finding for finding in findings), findings)

    def test_coverage_validator_accepts_licence_but_not_unknown(self):
        now = datetime(2026, 11, 2, 14, 0, 0, tzinfo=timezone.utc)
        body = publisher.lazy_options_coverage_body(None, now)[publisher.COVERAGE_KEY]
        doc = json.loads(body)
        self.assertTrue(any(row["rights_status"] == "licence_required" for row in doc["providers"]))
        products.validate_options_coverage_document(doc)
        doc["providers"][0]["rights_status"] = "invented_rights"
        with self.assertRaises(products.MarketProductValidationError):
            products.validate_options_coverage_document(doc)

    def test_taifex_listing_snapshot(self):
        doc = json.loads((ROOT / "config/taifex-stock-option-underlyings-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["source_url"], "https://www.taifex.com.tw/enl/eng2/stockLists")
        self.assertEqual(doc["effective_date"], "2026-11-02")
        self.assertEqual(len(doc["single_stock_options"]), 26)
        self.assertEqual(len(set(doc["single_stock_options"].values())), 26)
        self.assertEqual(doc["single_stock_options"]["1303"], "CAO")
        self.assertNotIn("3006", doc["single_stock_options"])


if __name__ == "__main__":
    unittest.main()
