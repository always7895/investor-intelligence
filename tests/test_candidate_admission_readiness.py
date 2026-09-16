"""Candidate admission-readiness gate (INVESTOR_HERDR_ADMISSION_PIPELINE).

Covers docs/COMPANY_EVIDENCE_CANDIDATES_INVENTORY_V1.md with a deterministic,
fail-closed readiness evaluator (scripts/evaluate_candidate_admission_readiness.py
via bottleneck_claim_admission / company_claim_admission_bridge):
- 4 real tracked candidates (GEV, 6501 Hitachi, 6508 Meiden, ENR Siemens
  Energy) probe the evaluator; the synthetic two-lineage shape should be
  ADMISSION_QUALIFIED, and issuer-only / single-lineage shapes must evaluate
  strictly to ADMISSION_BLOCKED_INSUFFICIENT_EVIDENCE;
- runtime_admitted_claims is always strictly 0 (never emits anything at
  runtime; the evaluator only measures distance);
- determinism: identical inputs -> byte-identical JSON; CLI fail-closed on
  corrupt candidate files;
- keeps in sync with the inventory document + README gate link.
Zero network.
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import evaluate_candidate_admission_readiness as readiness  # noqa: E402
import test_bottleneck_ranking as b_rank  # noqa: E402
import test_research_v2_claims as claims_fixture  # noqa: E402

NOW = datetime(2026, 9, 15, 0, tzinfo=timezone.utc)
BLOCKED = readiness.BLOCKED
QUALIFIED = readiness.QUALIFIED

CANDIDATES = {
    "GEV": "GE Vernova Inc.",
    "6501": "Hitachi Ltd (Hitachi Energy)",
    "6508": "Meidensha Corporation",
    "ENR": "Siemens Energy AG",
}


def _candidate(ticker: str, *, issuer_only: bool = False) -> dict:
    cand = b_rank.valid_chokepoint_candidate(ticker)
    if issuer_only:
        # strip the second (news) lineage family entirely
        def _family(o):
            payload = o.get("payload") if isinstance(o.get("payload"), dict) else {}
            return str(o.get("origin_group") or payload.get("origin_group") or "")
        cand["source_observations"] = [o for o in cand["source_observations"]
                                       if _family(o) == "group_official"]
        cand["material_claims"] = cand["material_claims"]  # claims stay present
    return cand


class CandidateAdmissionReadinessTests(unittest.TestCase):
    def setUp(self):
        self.registry = claims_fixture.REGISTRY
        self.health_states = {s: "HEALTHY" for s in self.registry.by_id()}

    def _eval(self, cand):
        return readiness.evaluate_readiness(cand, registry=self.registry,
                                            health_states=self.health_states, now=NOW)

    # ------------------------------------------------------------------
    # 1) All four real candidates: two corroborated lineages -> qualified
    #    readiness (synthetic evidence shape; structural distance test)
    # ------------------------------------------------------------------
    def test_all_four_candidates_qualify_with_two_lineages(self):
        for ticker in (
    [ticker for ticker in CANDIDATES]):
            ev = self._eval(_candidate(ticker))
            self.assertEqual(ev["admission"], QUALIFIED, f"{ticker}: {ev['blockers']}")
            self.assertEqual(ev["satisfied_pillars"],
                             ["dependency", "scarcity", "pricing_power", "company_capture"])
            self.assertEqual(ev["missing_pillars"], [])
            self.assertEqual(ev["lineage_count"], 2)
            self.assertTrue(ev["bridge"]["core_admitted"])
            self.assertEqual(ev["runtime_admitted_claims"], 0)
            self.assertTrue(ev["fail_closed"])

    # ------------------------------------------------------------------
    # 2) Without >= 2 independent corroborated lineages every candidate is
    #    strictly blocked
    # ------------------------------------------------------------------
    def test_single_lineage_parent_is_blocked(self):
        for ticker in (
    [ticker for ticker in CANDIDATES]):
            ev = self._eval(_candidate(ticker, issuer_only=True))
            self.assertEqual(ev["admission"], BLOCKED, f"{ticker} must be blocked issuer-only")
            self.assertEqual(ev["lineage_count"], 1)
            self.assertIn("core_not_admitted", ev["blockers"])
            self.assertTrue(any(b.startswith("single_lineage_only") for b in ev["blockers"]))
            self.assertLessEqual(len(ev["satisfied_pillars"]), 0)

    # ------------------------------------------------------------------
    # 3) Missing registry / claims / clock -> fail-closed blocked
    # ------------------------------------------------------------------
    def test_missing_registry_blockd(self):
        ev = readiness.evaluate_readiness(_candidate("GEV"), registry=None, health_states=None, now=NOW)
        self.assertEqual(ev["admission"], BLOCKED)
        self.assertIn("missing_registry", ev["blockers"])
        self.assertEqual(ev["runtime_admitted_claims"], 0)

    def test_no_claims_blocked(self):
        cand = _candidate("ENR")
        cand["material_claims"] = []
        cand["source_observations"] = []
        ev = self._eval(cand)
        self.assertEqual(ev["admission"], BLOCKED)
        self.assertIn("no_claims", ev["blockers"])

    def test_missing_clock_blocked(self):
        cand = _candidate("6508")
        cand["as_of"] = "garbage-clock"
        ev = readiness.evaluate_readiness(cand, registry=self.registry, health_states=self.health_states, now=None)
        self.assertEqual(ev["admission"], BLOCKED)
        self.assertIn("missing_or_invalid_clock", ev["blockers"])

    # ------------------------------------------------------------------
    # 4) Hard invariant: runtime_admitted_claims == 0 everywhere
    # ------------------------------------------------------------------
    def test_runtime_admitted_strictly_zero_across_corpus(self):
        for ticker in (
    [ticker for ticker in CANDIDATES]):
            for issuer_only in (False, True):
                ev = self._eval(_candidate(ticker, issuer_only=issuer_only))
                self.assertEqual(ev["runtime_admitted_claims"], 0, f"{ticker}/{issuer_only}")

    # ------------------------------------------------------------------
    # 5) Determinism + CLI behavior
    # # ------------------------------------------------------------------
    def test_output_is_deterministic(self):
        ev1 = self._eval(_candidate("6501"))
        ev2 = self._eval(_candidate("6501"))
        self.assertEqual(json.dumps(ev1, sort_keys=True), json.dumps(ev2, sort_keys=True))

    def test_cli_give_up_on_corrupt_candidate(self):
        import tempfile
        import os
        tmp = Path(tempfile.gettempdir()) / "readiness_corrupt_candidate.json"
        tmp.write_text("{definitely not json", encoding="utf-8")
        try:
            rc = readiness.main(["--candidate", str(tmp)])
            self.assertEqual(rc, 1)
        finally:
            tmp.unlink(missing_ok=True)

    def test_cli_blockd_inventory_shape_json(self):
        import tempfile
        tmp = Path(tempfile.gettempdir()) / "readiness_candidate.json"
        out = Path(tempfile.gettempdir()) / "readiness_out.json"
        cand = _candidate("ENR")
        tmp.write_text(json.dumps(cand), encoding="utf-8")
        try:
            rc = readiness.main(["--candidate", str(tmp), "--as-of", "2026-09-15T00:00:00Z", "--output", str(out)])
            self.assertEqual(rc, 0)
            doc = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(doc["schema"], "CANDIDATE_ADMISSION_READINESS_V1")
            self.assertEqual(doc["admission"], BLOCKED, "no registry file supplied -> fail-closed blocked")
            self.assertIn("missing_registry", doc["blockers"])
            self.assertEqual(doc["runtime_admitted_claims"], 0)
        finally:
            tmp.unlink(missing_ok=True)
            out.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # 6) Inventory document + README link gate
    # ------------------------------------------------------------------
    def test_inventory_document_and_readme_link_exist(self):
        doc = ROOT / "docs" / "COMPANY_EVIDENCE_CANDIDATES_INVENTORY_V1.md"
        self.assertTrue(doc.is_file())
        text = doc.read_text(encoding="utf-8")
        for token in ("GE Vernova", "6501", "6508", "ENR", "ADMISSION", "runtime admitted"):
            self.assertIn(token, text)
        readme = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
        self.assertIn("COMPANY_EVIDENCE_CANDIDATES_INVENTORY_V1.md", readme)


# ============================================================================
# Multi-lineage (task #16): approved DOE + MLGW sources bound alongside issuer
# ============================================================================
class MultiLineageBundleReadinessTests(unittest.TestCase):
    """Approved 2nd/3rd lineages (US_DOE_OFFICE_OF_ELECTRICITY,
    MLGW_MUNICIPAL_UTILITY_BUYER) for GEV and Hitachi (6501).

    The pipeline's live-corroboration model requires >= 2 independent
    LIVE-aging families. The approved sources are retained, digested, and
    claim-bound here; at the pinned evaluation clock the 2nd families are
    inside the archival window, so the honest status is claims bound
    (multi-lineage) but corroboration not yet live - readiness ADVANCES
    (0 -> 25), the lineage requirement (>= 2 families registered) is
    structurally satisfied, and admission stays closed (runtime admitted 0).
    """

    @classmethod
    def setUpClass(cls):
        import multilineage_claim_bundle as mlb
        cls.mlb = mlb
        cls.registry = mlb.build_registry()
        cls.health = mlb.health_for(cls.registry)
        cls.now = mlb.SECRET_CLOCK

    def _ev(self, cand, fixture_mode):
        return readiness.evaluate_readiness(
            cand, registry=self.registry, health_states=self.health,
            now=self.now, fixture_mode=fixture_mode)

    # -- 1) corpus digests hold the verbatim anchors -----------------------
    def test_corpus_anchors_verified(self):
        res = self.mlb.verify_corpus_anchors()
        self.assertTrue(all(res.values()), res)

    # -- 2) >= 2 independent lineage families registered and bound ---------
    def test_lineage_independence_requirement_satisfied(self):
        for ticker in ("GEV", "6501"):
            ev = self._ev(self.mlb.bundled_candidates()[ticker], True)
            self.assertGreaterEqual(ev["lineage_count"], 2, ticker)
            self.assertEqual(ev["lineage_count"], 3)
            groups = {o["payload"]["origin_group"] for o in
                      self.mlb.bundled_candidates()[ticker]["source_observations"]}
            self.assertEqual(groups, {"group_official", "us_doe_oe", "mlgw"})
            ids = set(self.registry.by_id())
            self.assertIn("US_DOE_OFFICE_OF_ELECTRICITY", ids)
            self.assertIn("MLGW_MUNICIPAL_UTILITY_BUYER", ids)

    # -- 3) multi-lineage binding strictly advances readiness ---------------
    def test_readiness_score_advances_with_multi_lineage(self):
        for ticker in ("GEV", "6501"):
            pre = self._ev(self.mlb.single_lineage_baseline(ticker), True)
            post = self._ev(self.mlb.bundled_candidates()[ticker], True)
            self.assertLess(pre["readiness_score"], post["readiness_score"], ticker)
            self.assertEqual(pre["lineage_count"], 1)
            self.assertNotIn([b for b in pre["blockers"] if b.startswith("single_lineage")],
                             post["blockers"])
            self.assertEqual(post["admission"], BLOCKED,
                             "advancement must not manufacture admission")

    # -- 4) approved sources are bound by canonical URL + verbatim claim ----
    def test_approved_sources_bound_with_verbatim_claims(self):
        for ticker in ("GEV", "6501"):
            cand = self.mlb.bundled_candidates()[ticker]
            urls = {o["canonical_url"] for o in cand["source_observations"]}
            self.assertIn(self.mlb.DOE_URL, urls)
            self.assertIn(self.mlb.MLGW_URL, urls)
            passages = " ".join(o["payload"]["passage"] for o in cand["source_observations"])
            # scarcity pillar: DOE 443% + MLGW primary partners verbatim
            self.assertIn("443%", passages)
            self.assertIn("primary partners", passages)
            claims = {c["claim_id"]: c for c in cand["material_claims"]}
            self.assertEqual(len(claims), 4)

    # -- 5) remaining blocker is the explicit live-window corroboration -----
    def test_2nd_family_stale_at_eval_clock_is_the_remaining_blocker(self):
        for ticker in ("GEV", "6501"):
            ev = self._ev(self.mlb.bundled_candidates()[ticker], True)
            self.assertEqual(ev["claims_status_counts"], {"SINGLE_SOURCE": 4})
            self.assertIn("claims_unsupported", ev["blockers"])
            self.assertFalse(ev["bridge"]["core_admitted"])
            self.assertEqual(ev["bridge"]["admission_tier"], "UNADMITTED")

    # -- 6) fixture flag cannot promote without live corroboration ----------
    def test_fixture_mode_cannot_promote_without_live_corroboration(self):
        for ticker in ("GEV", "6501"):
            ev = self._ev(self.mlb.bundled_candidates()[ticker], True)
            self.assertEqual(ev["admission"], BLOCKED)
            self.assertEqual(ev["bridge"]["admission_tier"], "UNADMITTED")
            self.assertEqual(ev["promotion_basis"], "NONE")

    # -- 7) real caller path stays deferred ---------------------------------
    def test_real_caller_path_stays_deferred(self):
        for ticker in ("GEV", "6501"):
            ev = self._ev(self.mlb.bundled_candidates()[ticker], False)
            self.assertEqual(ev["bridge"]["admission_tier"], "ADMISSION_DEFER")
            self.assertEqual(ev["admission"], BLOCKED)

    # -- 8) runtime admitted claims strictly 0 everywhere --------------------
    def test_runtime_admitted_strictly_zero_bundle(self):
        for ticker in ("GEV", "6501"):
            for fixture in (False, True):
                ev = self._ev(self.mlb.bundled_candidates()[ticker], fixture)
                self.assertEqual(ev["runtime_admitted_claims"], 0)


if __name__ == "__main__":
    unittest.main()