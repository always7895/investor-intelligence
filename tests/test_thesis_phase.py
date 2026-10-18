from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import thesis_phase as tp  # noqa: E402

URL = "https://example.gov/synthetic"


def sig(kind, as_of, family, direction=None, value=None, lens=None, sid=None):
    row = {"kind": kind, "as_of": as_of, "evidence_family": family, "source_url": URL, "signal_id": sid or f"{kind}-{as_of}-{family}"}
    if direction:
        row["direction"] = direction
    if value is not None:
        row["value"] = value
    if lens:
        row["lens"] = lens
    return row


# Synthetic transformer-like constraint; dates and values are test data, not research.
STORY = [
    sig("LEAD_TIME", "2025-01-10", "gov_regulator", "UP", 30),
    sig("PRICE", "2025-03-01", "utility_buyer", "UP", 12),
    sig("COMPANY_PRICING", "2025-05-01", "issuer", "UP", 8),
    sig("LEAD_TIME", "2025-05-10", "gov_regulator", "UP", 33),
    sig("PRICE", "2025-07-01", "utility_buyer", "UP", 9),
    sig("COVERAGE_INITIATIONS", "2025-08-01", "sell_side", value=4),
    sig("COMPANY_MARGIN", "2025-08-15", "issuer", "UP", 3),
    sig("LEAD_TIME", "2025-09-01", "gov_regulator", "UP", 34),
    sig("VALUATION_PERCENTILE", "2025-10-01", "market", value=85),
    sig("COVERAGE_INITIATIONS", "2025-10-10", "sell_side", value=5),
    sig("CAPACITY_ADDITION", "2026-01-01", "issuer_peer", value=1),
    sig("LEAD_TIME", "2026-02-01", "gov_regulator", "DOWN", 20),
]


class PhaseTests(unittest.TestCase):
    def setUp(self):
        self.policy = tp.load_policy()

    def phase(self, when, signals=STORY, **kwargs):
        return tp.assess_phase(signals, when, policy=self.policy, **kwargs)

    def test_phase_moves_with_time_as_evidence_arrives(self):
        expected = [("2025-01-20", "DISCOVERY"), ("2025-03-05", "EARLY_VALIDATION"),
                    ("2025-05-15", "COMMERCIAL_VALIDATION"), ("2025-08-05", "INSTITUTIONAL_VALIDATION"),
                    ("2025-10-03", "CONSENSUS"), ("2026-02-05", "RELIEVING")]
        for when, phase in expected:
            self.assertEqual(self.phase(when)["phase"], phase, when)

    def test_market_signals_expire_fast_and_the_view_reverts(self):
        # The valuation reading is 7 days old at most; afterwards only coverage remains.
        self.assertEqual(self.phase("2025-10-20")["phase"], "INSTITUTIONAL_VALIDATION")
        self.assertIn("VALUATION_PERCENTILE-2025-10-01-market", self.phase("2025-10-20")["expired_signal_ids"])

    def test_stale_constraint_evidence_downgrades_without_refresh(self):
        stale = STORY[:3]
        self.assertEqual(self.phase("2025-05-15", stale)["phase"], "COMMERCIAL_VALIDATION")
        # The January lead-time signal leaves its 135-day window; one family remains.
        self.assertEqual(self.phase("2025-06-01", stale)["phase"], "DISCOVERY")

    def test_relief_maps_to_engine_flags(self):
        result = self.phase("2026-02-05")
        self.assertEqual((result["engine_lifecycle"], result["shortage_relieved"]), ("CONSENSUS", True))
        self.assertEqual(result["relief_families"], ["gov_regulator", "issuer_peer"])

    def test_context_lens_is_recorded_but_never_counted(self):
        signals = [sig("LEAD_TIME", "2025-01-10", "gov_regulator", "UP"),
                   sig("BUYER_CAPEX", "2025-01-12", "aschenbrenner_13f", "UP", lens="ASCHENBRENNER_CONTEXT")]
        result = self.phase("2025-01-20", signals)
        self.assertEqual(result["phase"], "DISCOVERY")
        self.assertEqual(result["context_only_signal_ids"], ["BUYER_CAPEX-2025-01-12-aschenbrenner_13f"])

    def test_dilution_breaks_or_flags_equity_capture(self):
        base = STORY[:3]
        broken = self.phase("2025-05-15", base + [sig("DILUTION", "2025-05-12", "issuer", value=25)])
        self.assertEqual(broken["phase"], "BROKEN")
        overhang = self.phase("2025-05-15", base + [sig("DILUTION", "2025-05-12", "issuer", value=8)])
        self.assertEqual(overhang["phase"], "COMMERCIAL_VALIDATION")
        self.assertTrue(overhang["dilution_overhang"])

    def test_ramp_evidence_reaches_commercial_validation_before_margins(self):
        signals = STORY[:2] + [sig("RAMP_EVIDENCE", "2025-03-10", "customer_disclosure")]
        self.assertEqual(self.phase("2025-03-15", signals)["phase"], "COMMERCIAL_VALIDATION")
        down = STORY[:2] + [sig("RAMP_EVIDENCE", "2025-03-10", "customer_disclosure", "DOWN")]
        self.assertEqual(self.phase("2025-03-15", down)["phase"], "EARLY_VALIDATION")

    def test_active_atm_blocks_entry_until_finished(self):
        base = STORY[:3]
        blocked = self.phase("2025-05-15", base + [sig("ATM_CAPACITY", "2025-05-05", "issuer", value=55)])
        self.assertEqual(blocked["phase"], "BROKEN")
        self.assertIn("ATM_CAPACITY", blocked["reasons"][0])
        finished = base + [sig("ATM_CAPACITY", "2025-05-05", "issuer", value=55),
                           sig("ATM_CAPACITY", "2025-05-12", "issuer", value=0, sid="atm-done")]
        self.assertEqual(self.phase("2025-05-15", finished)["phase"], "COMMERCIAL_VALIDATION")
        small = self.phase("2025-05-15", base + [sig("ATM_CAPACITY", "2025-05-05", "issuer", value=12)])
        self.assertTrue(small["dilution_overhang"])

    def test_industry_scope_ignores_company_capture_and_consensus(self):
        self.assertEqual(self.phase("2025-10-03", scope="industry")["phase"], "EARLY_VALIDATION")

    def test_next_review_is_the_earliest_supporting_expiry_or_catalyst(self):
        result = self.phase("2025-03-05")
        self.assertEqual(result["next_review_at"], "2025-05-25")  # 2025-01-10 + 135 days
        announced = sig("CATALYST", "2025-04-15", "issuer")
        announced["announced_at"] = "2025-02-20"
        self.assertEqual(self.phase("2025-03-05", STORY + [announced])["next_review_at"], "2025-04-15")
        # Not yet announced at the evaluation date: no look-ahead.
        unannounced = sig("CATALYST", "2025-04-15", "issuer")
        self.assertEqual(self.phase("2025-03-05", STORY + [unannounced])["next_review_at"], "2025-05-25")

    def test_timeline_marks_transitions(self):
        rows = tp.phase_timeline(STORY, ["2025-01-20", "2025-02-01", "2025-03-05"], policy=self.policy)
        self.assertEqual([(r["phase"], r["changed"]) for r in rows],
                         [("DISCOVERY", True), ("DISCOVERY", False), ("EARLY_VALIDATION", True)])

    def test_screen_prefers_information_gap_and_puts_broken_last(self):
        early = [sig("LEAD_TIME", "2025-09-20", "gov_regulator", "UP"), sig("PRICE", "2025-09-25", "utility_buyer", "UP"),
                 sig("COMPANY_PRICING", "2025-09-28", "issuer", "UP")]
        candidates = {"LATE": STORY[:9], "EARLY": early, "DEAD": early + [sig("THESIS_KILLER", "2025-09-30", "issuer")],
                      "STALE": STORY[:3]}
        order = [row["subject"] for row in tp.screen(candidates, "2025-10-03", policy=self.policy)]
        self.assertEqual(order[-1], "DEAD")
        self.assertEqual(order[:3], ["EARLY", "LATE", "STALE"])

    def test_invalid_signals_fail_closed(self):
        for bad in ({**STORY[0], "source_url": "http://insecure.example"}, {**STORY[0], "kind": "RUMOR"},
                    {**STORY[0], "value": True}, {**STORY[0], "as_of": "yesterday"},
                    {**STORY[0], "evidence_family": "Bad Family"}, {**STORY[0], "direction": "SIDEWAYS"}):
            with self.assertRaises(tp.ThesisPhaseError):
                tp.assess_phase([bad], "2025-02-01", policy=self.policy)
        with self.assertRaises(tp.ThesisPhaseError):
            tp.assess_phase(STORY, "2025-02-01", policy=self.policy, scope="sector")


if __name__ == "__main__":
    unittest.main()
