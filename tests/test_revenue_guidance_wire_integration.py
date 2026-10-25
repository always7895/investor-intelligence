"""B3-WIRE-01: ordinary functional integration of the disabled versioned transport through the REAL
lazy publisher (scripts/publish_sealed_snapshot.lazy_bottleneck_v3_body) - three tests only, in-memory,
no filesystem collaborators (external read/data-source collaborators are replaced with in-memory
values and fixed producer results from tests/fixtures/v213-orders-v3-golden-sealed.json; the
publisher functions under test are never stubbed).

The shared cross-language fixture (tests/fixtures/revenue-guidance-wire-v1-functional.json) records
the input ranking document, the fixed producer v2/v3 values and the EXACT body strings the real
publisher emits legacy (option omitted/false) and enveloped (option true); the Worker test consumes
the same strings. The replay clock (NOW) is aligned to the embedded golden evidence cutoff
(2026-09-28T15:00:00Z), so the report's generated_at equals the v2/v3 evidence cutoff and the
untouched strict parser's cutoff checks pass on the ordinary branches. Historical dates are
injected clocks for functional replay, not fresh publication evidence. No security, boundary,
adversarial or full-suite coverage here.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publish_sealed_snapshot  # noqa: E402

FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "revenue-guidance-wire-v1-functional.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 9, 28, 15, 0, 0, tzinfo=timezone.utc)  # the historical golden cutoff (replay clock)
GENERATED_AT = "2026-09-28T15:00:00Z"


def _producer_v2(issuer: str, *args, **kwargs) -> dict:
    """The fixed producer v2 result for one issuer (golden sealed data; non-NVDA entries reuse the
    ordinary unavailable example under their own symbol). The unused model arguments are the
    publisher's real call arguments; they are accepted and ignored."""
    base = FIXTURE["v2_nvda"] if issuer == "NVDA" else FIXTURE["v2_default"]
    result = copy.deepcopy(base)
    result["issuer"] = issuer
    return result


def _producer_v3(issuer: str, *args, **kwargs) -> dict:
    """The fixed producer v3 result: NVDA the ordinary available curated example, SNDK its ordinary
    FRESHNESS_UNVERIFIED example, every other (synthetic) issuer the sealer's issuer-coherent
    no-registry-record shape (INPUTS_MISSING, empty evidence arrays - no foreign-issuer evidence)."""
    if issuer == "NVDA":
        base = FIXTURE["v3_nvda"]
    elif issuer == "SNDK":
        base = FIXTURE["v3_sndk"]
    else:
        base = FIXTURE["v3_norecord"]
    result = copy.deepcopy(base)
    result["issuer"] = issuer
    return result


class WirePublisherTests(unittest.TestCase):
    """The real lazy publisher with the transport option threaded through its per-entry loop."""

    @classmethod
    def setUpClass(cls) -> None:
        def names_for(symbols, identity_path=None, names_path=None, official_path=None):
            assert (identity_path, names_path, official_path) == (None, None, None)
            return {s: [s, "OFFICIAL"] for s in symbols}

        patches = [
            mock.patch("publish_sealed_snapshot.order_forecast.build_v2", side_effect=_producer_v2),
            mock.patch("publish_sealed_snapshot.order_forecast.build_v3", side_effect=_producer_v3),
            mock.patch("publish_sealed_snapshot.revenue_guidance_overlay.load_effective_inputs",
                       return_value={"wire_fixture": True}),
            mock.patch("publish_sealed_snapshot.company_deep_report.load_order_scenarios", return_value={}),
            mock.patch("publish_sealed_snapshot.company_deep_report.load_reports", return_value={}),
            mock.patch("publish_sealed_snapshot._exchange_cross_checks", return_value={}),
            mock.patch("publish_sealed_snapshot._layer_translations", return_value=({}, {})),
            mock.patch("publish_sealed_snapshot.order_claims.load", return_value={}),
            mock.patch("publish_sealed_snapshot.build_zh_names.names_for",
                       side_effect=names_for),
            mock.patch("publish_sealed_snapshot.listing_lineage.clean_market_lineage", return_value={}),
            mock.patch("publish_sealed_snapshot.revenue_consensus_quarterly.load_cache", return_value={}),
        ]
        for patch in patches:
            patch.start()
        cls._patches = patches

    @classmethod
    def tearDownClass(cls) -> None:
        for patch in cls._patches:
            patch.stop()

    def run_publisher(self, **kwargs) -> "dict[str, str]":
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            path.write_text(json.dumps(FIXTURE["unsealed_doc"]), encoding="utf-8")
            return publish_sealed_snapshot.lazy_bottleneck_v3_body(path, NOW, **kwargs)

    def test_1_option_omitted_or_false_produces_exact_frozen_legacy_body(self) -> None:
        body_key = publish_sealed_snapshot.BOTTLENECK_V3_KEY
        res_omitted = self.run_publisher()
        res_false = self.run_publisher(guidance_wire_enabled=False)
        self.assertEqual(res_omitted, res_false)
        # The disabled path is the exact frozen legacy body (the shared fixture's recorded string).
        self.assertEqual(res_omitted, FIXTURE["expected_legacy_body"])
        body = json.loads(res_omitted[body_key])
        self.assertEqual(body["generated_at"], GENERATED_AT)
        self.assertEqual(len(body["top"]), 10)
        # Sibling v2 stays unchanged and the v3 value is the plain producer result (no envelope).
        for entry in body["top"]:
            self.assertEqual(entry["outlook"]["order_forecast"]["version"], 2)
            v3 = entry["outlook"]["order_forecast_v3"]
            self.assertEqual(v3["version"], 3)
            self.assertNotIn("schema", v3)
            self.assertNotIn("payload", v3)

    def test_2_option_true_emits_transport_v1_with_detached_payloads(self) -> None:
        body_key = publish_sealed_snapshot.BOTTLENECK_V3_KEY
        original_doc = copy.deepcopy(FIXTURE["unsealed_doc"])
        res_true = self.run_publisher(guidance_wire_enabled=True)
        # The input mapping is not mutated by the publisher.
        self.assertEqual(FIXTURE["unsealed_doc"], original_doc)
        body = json.loads(res_true[body_key])
        for entry in body["top"]:
            v3 = entry["outlook"]["order_forecast_v3"]
            self.assertEqual(v3["schema"], "v213-order-forecast-transport-v1")
            self.assertEqual(v3["admission_mode"], "EXISTING_V3_ONLY")
            # Every inner forecast is exactly the original producer output for that issuer.
            self.assertEqual(v3["payload"], _producer_v3(entry["symbol"]))
            self.assertEqual(entry["outlook"]["order_forecast"], _producer_v2(entry["symbol"]))        # Repeated serialization is deterministic.
        self.assertEqual(self.run_publisher(guidance_wire_enabled=True), res_true)

    def test_3_output_equals_shared_fixture_legacy_and_enveloped_bodies(self) -> None:
        # A normal report with both an available (NVDA) and ordinary unavailable curated issuers.
        self.assertEqual(self.run_publisher(), FIXTURE["expected_legacy_body"])
        self.assertEqual(self.run_publisher(guidance_wire_enabled=True), FIXTURE["expected_wire_body"])


if __name__ == "__main__":
    unittest.main()
