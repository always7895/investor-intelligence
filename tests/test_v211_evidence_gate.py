from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v211_serenity_top20_evidence_gate as gate


class V211EvidenceGateTests(unittest.TestCase):
    def test_empty_metric_evidence_gets_neutral_sec_reference(self) -> None:
        policy, _ = gate.impl.v211_policy()
        candidate = {
            "ticker": "TEST",
            "official": {"name": "Test Issuer"},
            "market": {
                "industry": "Semiconductors",
                "sector": "Technology",
                "marketCap": 1_000_000_000,
                "averageDailyVolume3Month": 1_000_000,
            },
        }
        scored = gate.evidence_gated_score_candidate(candidate, {}, [], policy)
        self.assertEqual(scored["ticker"], "TEST")
        self.assertGreaterEqual(scored["evidence_count"], 1)
        self.assertEqual(scored["evidence"][0]["source_id"], "sec_edgar")
        self.assertEqual(scored["evidence"][0]["claim_type"], "legal_entity_reference")
        self.assertFalse(scored["owner_watchlist_inherited"])

    def test_existing_metric_evidence_is_preserved_without_duplication(self) -> None:
        policy, _ = gate.impl.v211_policy()
        candidate = {
            "ticker": "TEST",
            "official": {"name": "Test Issuer"},
            "market": {
                "industry": "Semiconductors",
                "sector": "Technology",
                "marketCap": 1_000_000_000,
                "averageDailyVolume3Month": 1_000_000,
            },
        }
        evidence = [
            gate.impl.base.Evidence(
                "sec_edgar",
                "T0",
                "xbrl_fact",
                "Synthetic SEC fact",
                "https://www.sec.gov/Archives/edgar/data/1/test.htm",
                "2026-06-30T00:00:00+00:00",
            )
        ]
        scored = gate.evidence_gated_score_candidate(candidate, {}, evidence, policy)
        self.assertEqual(scored["evidence_count"], 1)
        self.assertEqual(scored["evidence"][0]["claim_type"], "xbrl_fact")


if __name__ == "__main__":
    unittest.main()
