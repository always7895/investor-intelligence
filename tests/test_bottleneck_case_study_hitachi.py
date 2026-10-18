"""Bottleneck case study: Power Transformer chokepoint / Hitachi Energy (TSE: 6501).

Pins the canonical archetype from docs/BOTTLENECK_CASE_STUDY_HITACHI_ENERGY_V1.md
against the ranking engine:
- a 4-factor Hitachi transformer candidate reaches a positive qualified score
  under the synthetic fixture alone;
- conglomerate business-mix dilution (600-subsidiary group) does NOT trigger
  the DESTROYED shareholder-dilution disqualifier, while actual DESTROYED
  financing still does;
- switching latency >= 12 months is required for the Scarcity pillar;
- missing any of the 4 core pillars fails closed to UNRANKED_INSUFFICIENT_
  EVIDENCE;
- factor authority for real (non-.example) hosts is strictly not admitted
  outside synthetic fixtures (runtime admission remains 0).
Zero network; deterministic clock.
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import bottleneck_ranking as engine  # noqa: E402
import test_bottleneck_ranking as b_rank  # noqa: E402
import test_research_v2_claims as claims_fixture  # noqa: E402

NOW = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)

UNRANKED = "UNRANKED_INSUFFICIENT_EVIDENCE"
DESTROYED_STATUS = "DISQUALIFIED_FINANCING_DESTROYED"


def _hitachi_candidate(**overrides) -> dict:
    """Build the Hitachi Energy transformer archetype on the proven positive recipe."""
    cand = b_rank.valid_chokepoint_candidate("6501")
    cand.update({
        "name": "Hitachi (TSE) - Hitachi Energy Power Transformer Archetype",
        "exchange": "TSE",
        "country": "JP",
        "bottleneck_role": "CAPACITY_BOTTLENECK",
        "scarcity_evidence": {
            **cand["scarcity_evidence"],
            "effective_suppliers_count": 2,
            "switching_time_months": 132,
            "details": "UHV power transformers + bushings + core steel qualified production cluster; 128-144 week (30-33 month) lead times.",
        },
        "dependency_evidence": {
            **cand["dependency_evidence"],
            "layer": "EHV transmission interconnect (UHV power transformers, bushings, core steel)",
            "assessment": "Grid power cannot reach load centers without the qualified EHV interconnect stack.",
        },
        "pricing_evidence": {
            **cand["pricing_evidence"],
            "mechanism": "Long-term supply agreements with indexation + realized multi-year margin expansion.",
        },
        "company_capture_evidence": {
            **cand["company_capture_evidence"],
            "assessment": (
                "Captures EHV transformer layer profit pool. Business mix: Energy is one segment of a "
                "600-subsidiary group (conglomerate business-mix dilution, NOT shareholder dilution); "
                "no death-spiral converts, warrant overhang, or predatory financing observed in window."
            ),
        },
        "backlog_orders_evidence": {
            **cand["backlog_orders_evidence"],
            "current_orders": "$10B+ firm order book disclosed for North American grid buildout",
            "future_orders_estimate": "Multi-year committed grid investment disclosed through 2030",
        },
    })
    cand.update(overrides)
    return cand


class HitachiEnergyBottleneckCaseStudyTests(unittest.TestCase):
    def setUp(self):
        self.policy = engine.load_json(engine.POLICY_DEFAULT_PATH)
        self.registry = claims_fixture.REGISTRY
        self.health_states = {s: "HEALTHY" for s in claims_fixture.REGISTRY.by_id()}

    def _eval(self, cand) -> dict:
        return engine.evaluate_candidate(
            cand, self.policy, now=NOW, registry=self.registry, health_states=self.health_states
        )

    # ------------------------------------------------------------------
    # 1) The archetype qualifies positively under the synthetic fixture
    # ------------------------------------------------------------------
    def test_archetype_qualifies_with_positive_score_under_synthetic_fixture(self):
        ev = self._eval(_hitachi_candidate())
        self.assertEqual(ev["admission_status"], "ADMITTED")
        self.assertIs(ev["score_qualified"], True)
        self.assertEqual(ev["candidate_assessment_mode"], "RANKING_QUALIFIED")
        score = ev["system_bottleneck_explosion_score"]
        self.assertGreater(score, 0.0)
        self.assertLess(score, 100.0)
        # historical returns are display context only, zero influence
        self.assertEqual(ev["historical_returns_context"]["influence_on_score"], 0.0)

    # ------------------------------------------------------------------
    # 2) Business-mix dilution != shareholder dilution
    # ------------------------------------------------------------------
    def test_business_mix_dilution_does_not_trigger_destroyed(self):
        cand = _hitachi_candidate()
        # make the language explicit and hostile-sounding: the group IS a
        # diluting conglomerate in business-mix terms.
        cand["company_capture_evidence"]["assessment"] += (
            " WARNING business-mix dilution: investors hold 1 of 600+ subsidiaries."
        )
        ev = self._eval(cand)
        self.assertNotEqual(ev["admission_status"], DESTROYED_STATUS)
        self.assertNotIn("financing_equity_capture_destroyed", ev["risk_flags"])
        self.assertEqual(ev["downside_penalty"] >= 0, True)

    def test_destroyed_financing_still_disqualifies(self):
        ev = self._eval(_hitachi_candidate(financing_risk="DESTROYED"))
        self.assertEqual(ev["admission_status"], DESTROYED_STATUS)
        self.assertIn("financing_equity_capture_destroyed", ev["risk_flags"])
        self.assertIsNone(ev["score_qualified"])

    # ------------------------------------------------------------------
    # 3) Switching latency >= 12 months is required for Scarcity
    # ------------------------------------------------------------------
    def test_short_switching_latency_fails_scarcity(self):
        cand = _hitachi_candidate()
        cand["bottleneck_role"] = "SINGLE_SOURCE"
        cand["scarcity_evidence"] = {
            **cand["scarcity_evidence"],
            "corroborated_scarcity": False,
            "effective_suppliers_count": 8,
            "switching_time_months": 11,  # below the 12-month floor
        }
        ev = self._eval(cand)
        self.assertEqual(ev["admission_status"], UNRANKED)

    def test_thirty_month_lead_time_meets_scarcity(self):
        cand = _hitachi_candidate()
        cand["scarcity_evidence"] = {
            **cand["scarcity_evidence"],
            "effective_suppliers_count": 2,
            "switching_time_months": 30,
        }
        ev = self._eval(cand)
        self.assertEqual(ev["admission_status"], "ADMITTED")
        self.assertGreater(ev["system_bottleneck_explosion_score"], 0.0)

    # ------------------------------------------------------------------
    # 4) Any missing core pillar fails closed to UNRANKED_INSUFFICIENT_
    #    EVIDENCE
    # ------------------------------------------------------------------
    def test_missing_verified_claims_fails_closed(self):
        ev = self._eval(_hitachi_candidate(material_claims=[], source_observations=[]))
        self.assertEqual(ev["admission_status"], UNRANKED)

    def test_missing_demand_pillar_fails_closed(self):
        ev = self._eval(_hitachi_candidate(demand_evidence={
            "structural_acceleration": False,
            "multi_year_committed": False,
            "horizon_months": 0,
        }))
        self.assertEqual(ev["admission_status"], UNRANKED)

    def test_missing_pricing_and_capture_pillar_fails_closed(self):
        cand = _hitachi_candidate()
        # pilot absent entirely: claims stay verifiable, but the pillar evidence is missing
        cand.pop("pricing_evidence", None)
        cand.pop("company_capture_evidence", None)
        ev = self._eval(cand)
        self.assertEqual(ev["admission_status"], UNRANKED)

    def test_missing_catalyst_pillar_fails_closed(self):
        cand = _hitachi_candidate(catalysts_6_12_24m=[])
        cand.pop("catalyst_score", None)
        ev = self._eval(cand)
        self.assertEqual(ev["admission_status"], UNRANKED)

    # ------------------------------------------------------------------
    # 5) Runtime admission is strictly closed for real (non-.example)
    #    sources outside synthetic fixtures
    # ------------------------------------------------------------------
    def test_real_host_sources_are_not_runtime_admitted(self):
        cand = _hitachi_candidate()
        # re-map every observation to a real hostname (never .example)
        for obs in cand["source_observations"]:
            host = obs["canonical_url"].rsplit("/", 1)[0]
            obs["canonical_url"] = host.rstrip("https://") + "ww2.arb.ca.gov/probe"
            if obs["canonical_url"].startswith("https://"):
                obs["canonical_url"] = "https://ww2.arb.ca.gov/probe/" + obs["canonical_url"].replace("https://", "", 1)
        claims_check = engine.validate_claim_evidence(
            cand, NOW, health_states=self.health_states, registry=self.registry
        )
        res = engine.reconcile_factor_authority(
            cand, claims_check.get("claims", []), "6501", fixture_mode=None
        )
        # auto-detection must NOT classify real hosts as a synthetic fixture
        self.assertFalse(res["core_admitted"], "real-host evidence must fail closed to UNADMITTED (no runtime admission outside synthetic fixtures)")


if __name__ == "__main__":
    unittest.main()