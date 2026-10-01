"""Wave 1 official public feeds: rights recorded, adapters promoted, not yet runtime-enabled."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_public_source_observations as collector  # noqa: E402
import provider_runtime_hook as hook  # noqa: E402
from sec_contact_headers import SecContactError  # noqa: E402
from source_registry import load_registry  # noqa: E402

WAVE1 = ("federal_reserve_news", "ecb_news", "sec_news", "twse_equity_eod", "tpex_equity_eod",
         "twse_issuer_directory", "tpex_issuer_directory", "taifex_options_eod")


class OfficialPublicFeedsRegistryTests(unittest.TestCase):
    def test_entries_have_reviewed_rights_and_implemented_adapters(self):
        registry = load_registry().by_id()
        for source_id in WAVE1:
            with self.subTest(source_id=source_id):
                source = registry[source_id]
                self.assertEqual(source.terms_review_status, "approved")
                self.assertEqual(source.adapter_status, "implemented")
                self.assertEqual(source.adapter_id, source_id)
                self.assertEqual(source.admission_status, "ADAPTER_CONTRACT_VALIDATED")
                self.assertFalse(source.runtime_enabled)
                self.assertFalse(source.payment_required)
                self.assertEqual(source.trust_tier, "T1_PRIMARY_OFFICIAL")

    def test_capabilities_match_collector_endpoints_and_hosts(self):
        for source_id in WAVE1:
            with self.subTest(source_id=source_id):
                capability = hook.get_provider_capability(source_id)
                self.assertIsNotNone(capability)
                endpoint = collector.ENDPOINTS[source_id]
                self.assertIn(endpoint.split("/")[2], capability.allowed_hosts)
                adapter = capability.adapter_factory()
                self.assertEqual(adapter.source_id, source_id)
                self.assertEqual(adapter.parser_version, capability.parser_version)

    def test_publishers_share_independence_groups_with_existing_entries(self):
        registry = load_registry().by_id()
        self.assertEqual(registry["sec_news"].independence_group, registry["us_sec_edgar"].independence_group)
        self.assertEqual(registry["ecb_news"].independence_group, registry["eu_ecb_fx_reference"].independence_group)
        self.assertEqual(registry["twse_equity_eod"].independence_group, registry["tw_twse"].independence_group)
        self.assertEqual(registry["tpex_equity_eod"].independence_group, registry["tw_tpex"].independence_group)

    def test_sec_requests_fail_closed_without_a_declared_contact(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SEC_CONTACT_EMAIL", None)
            os.environ.pop("SEC_USER_AGENT", None)
            with patch.object(collector, "build_opener", side_effect=AssertionError("no network")):
                with self.assertRaises(SecContactError):
                    collector.fetch_bytes(collector.ENDPOINTS["sec_news"])


if __name__ == "__main__":
    unittest.main()
