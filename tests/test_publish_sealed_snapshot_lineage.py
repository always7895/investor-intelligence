"""B3 lineage caller rows through scripts/publish_sealed_snapshot.py and its ranking engine (offline, no KV).

publish_sealed_snapshot.qualified_ranking() ranks the bundled GEV/6501 multi-lineage corpus
(scripts/multilineage_claim_bundle.py) with bottleneck_ranking.rank_bottleneck_candidates(fixture_mode=True). That one
caller runs BOTH lineage copies: source_observation._research_families over the live (CURRENT, admitted) rows of each
claim inside reconcile_research_claims, then company_claim_admission_bridge.compute_independent_lineages over every raw
observation bound to a factor claim (enforced by enforce_factor_claim_bindings in
config/system-bottleneck-explosion-v1.json). At the pinned 2026-09-15 clock only the issuer and DOE 2026-03-05 rows are
live for every claim (the DOE 2024-02-22 and MLGW 2025-09-17 rows exceed the 180-day issuer_guidance_or_contract fact
limit), so each claim rests on exactly two live families while the bridge also counts the stale rows. Each row mutates
ONE observation (or the registry) of a deep copy of the real bundle; corpus anchors, registry, engine, bridge and
publisher are real, the three lineage functions are only wrapped to record their results. A collapsed claim makes the
publisher refuse to seal: qualified_ranking raises before build_bodies writes anything. The last class runs
rank_bottleneck_candidates(acquisition_run=...) over the BATCH08C acquisition fixtures. Covered elsewhere and not
repeated: the direct copies and the three-implementation graph property (tests/test_batch08c_lineage.py),
acquisition_run mirrors through reconcile_research_claims and the source-independence gate (same file) and
mixed-identity acquisition bindings (tests/test_batch08c_admission.py)."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import socket
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import company_claim_admission_bridge as bridge  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402
from tests import batch08c_fixtures as acquired  # noqa: E402

mlb = publisher.mlb
engine = publisher.engine
FACTORS = {"dependency": "DEP", "scarcity": "SCAR", "pricing": "PRICE", "capture": "CAP"}
TICKERS = ("GEV", "6501")
SEALABLE = "SEALABLE"
REFUSED_ONE = "expected 2/2 qualified admission, got 1/1"
REFUSED_NONE = "expected 2/2 qualified admission, got 0/0"
FRESH = "2026-08-01T00:00:00Z"  # inside the 180-day fact limit at the pinned 2026-09-15 clock
INDEPENDENT_SHA = hashlib.sha256(b"B3 synthetic independent fresh MLGW row").hexdigest()


def cid(ticker, factor):
    return f"ML-{ticker}-{FACTORS[factor]}-01"


def all_claims(value):
    return {cid(ticker, factor): value for ticker in TICKERS for factor in FACTORS}


# Bridge counts of the untouched bundle: DEP = issuer + {DOE 2024, DOE 2026} (shared origin us_doe_oe); SCAR, PRICE and
# CAP add the stale MLGW row as a third family (multilineage_claim_bundle._bundle_for observation list).
CONTROL_LINEAGES = {cid(ticker, factor): count for ticker in TICKERS
                    for factor, count in (("dependency", 2), ("scarcity", 3), ("pricing", 3), ("capture", 3))}


class PublisherLineageCase(unittest.TestCase):
    def setUp(self):
        def refuse(*_args, **_kwargs):
            raise AssertionError("guard: network must never be used")

        for patcher in (mock.patch.object(socket, "create_connection", side_effect=refuse),
                        mock.patch.object(socket, "getaddrinfo", side_effect=refuse),
                        mock.patch.object(publisher, "LIVE_NOW", None)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def row(self, bundle, ticker, source_id, url, claim):
        rows = [item for item in bundle[ticker]["source_observations"]
                if item["source_id"] == source_id and item["canonical_url"] == url
                and item["payload"]["claim_ids"] == [claim]]
        self.assertEqual(len(rows), 1, (ticker, source_id, url, claim))
        return rows[0]

    def issuer(self, bundle, ticker, factor):
        return self.row(bundle, ticker, mlb.ISSUER_LINEAGE, mlb.ISSUER_URLS[ticker], cid(ticker, factor))

    def doe26(self, bundle, ticker, factor):
        return self.row(bundle, ticker, mlb.DOE_LINEAGE, mlb.DOE26_URL, cid(ticker, factor))

    def fresh_copy(self, bundle, ticker, factor, origin, sha):
        """A copy of the live DOE 2026 row re-published by MLGW inside the fact window (own source and URL)."""
        row = copy.deepcopy(self.doe26(bundle, ticker, factor))
        row.update(source_id=mlb.MLGW_LINEAGE, canonical_url=mlb.MLGW_URL, evidence_role="financial_reporting",
                   published_at=FRESH, content_sha256=sha)
        row["payload"].update(origin_group=origin, as_of=FRESH)
        bundle[ticker]["source_observations"].append(row)
        return row

    def rank(self, mutate=None, registry=None, reverse=False):
        """qualified_ranking() over a mutated deep copy of the real bundle.

        Returns (outcome, ranking, audits, lineages): outcome is SEALABLE or the publisher's AssertionError text,
        ranking the engine result, audits the reconcile_research_claims result per ticker and lineages the bridge
        compute_independent_lineages count per bound claim id (absent when the bridge never counted that claim)."""
        bundle = copy.deepcopy(mlb.bundled_candidates())
        if mutate is not None:
            mutate(bundle)
        if reverse:
            for candidate in bundle.values():
                candidate["source_observations"].reverse()
        seen = {"ranking": None, "audits": {}, "lineages": {}}
        real_rank, real_reconcile = engine.rank_bottleneck_candidates, engine.reconcile_research_claims
        real_lineages = bridge.compute_independent_lineages

        def ranking(*args, **kwargs):
            seen["ranking"] = real_rank(*args, **kwargs)
            return seen["ranking"]

        def reconcile(doc, **kwargs):
            audit = real_reconcile(doc, **kwargs)
            seen["audits"][doc["ticker"]] = audit
            return audit

        def lineages(observations):
            count = real_lineages(observations)
            shared = set.intersection(*(set(item["payload"]["claim_ids"]) for item in observations))
            seen["lineages"]["|".join(sorted(shared))] = count
            return count

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(mlb, "bundled_candidates", return_value=bundle))
            if registry is not None:
                stack.enter_context(mock.patch.object(mlb, "build_registry", return_value=registry))
            stack.enter_context(mock.patch.object(engine, "rank_bottleneck_candidates", side_effect=ranking))
            stack.enter_context(mock.patch.object(engine, "reconcile_research_claims", side_effect=reconcile))
            stack.enter_context(mock.patch.object(bridge, "compute_independent_lineages", side_effect=lineages))
            try:
                publisher.qualified_ranking()
                outcome = SEALABLE
            except AssertionError as error:
                outcome = str(error)
        return outcome, seen["ranking"], seen["audits"], seen["lineages"]

    @staticmethod
    def claims(audits):
        return {claim["claim_id"]: (claim["status"], claim["independent_evidence_families"])
                for audit in audits.values() for claim in audit["claims"]}

    def evaluation(self, ranking, ticker):
        rows = [row for row in ranking["ranked_candidates"] + ranking["low_confidence_watchlist"] if row["ticker"] == ticker]
        self.assertEqual(len(rows), 1, ticker)
        return rows[0]

    def assert_gev_refused(self, ranking):
        self.assertEqual(self.evaluation(ranking, "GEV")["admission_status"], "UNRANKED_INSUFFICIENT_EVIDENCE")
        self.assertEqual(self.evaluation(ranking, "6501")["admission_status"], "ADMITTED")


class PublisherLineageRows(PublisherLineageCase):
    # P0 control: every claim of both tickers is SUPPORTED by exactly two live families; the bridge counts every bound
    # row (stale ones included) and licenses all four factors; the publisher can seal (2/2).
    def test_B3_P0_control_two_live_families_per_claim(self):
        outcome, ranking, audits, lineages = self.rank()
        self.assertEqual(outcome, SEALABLE)
        self.assertEqual((ranking["admitted_count"], ranking["ranked_count"]), (2, 2))
        self.assertEqual(self.claims(audits), all_claims(("SUPPORTED", 2)))
        self.assertEqual(lineages, CONTROL_LINEAGES)
        for ticker in TICKERS:
            authority = self.evaluation(ranking, ticker)["factor_claim_authority"]
            self.assertEqual((authority["core_admitted"], authority["admission_tier"], authority["missing_core"]),
                             (True, "TEST_ONLY", []))

    # P1 a mirror of the second live family (same origin lineage, or a byte-identical body) counts once: the claim
    # becomes SINGLE_SOURCE in reconcile_research_claims, the bridge never counts a claim that is not SUPPORTED, GEV is
    # unranked and the publisher refuses to seal. Order of the observations never matters.
    def test_B3_P1_mirror_of_the_second_family_counts_once(self):
        target = cid("GEV", "dependency")
        for field in ("origin_group", "content_sha256"):
            for reverse in (False, True):
                with self.subTest(field=field, reverse=reverse):
                    def mutate(bundle):
                        issuer, mirror = self.issuer(bundle, "GEV", "dependency"), self.doe26(bundle, "GEV", "dependency")
                        if field == "origin_group":
                            mirror["payload"]["origin_group"] = issuer["payload"]["origin_group"]
                        else:
                            mirror["content_sha256"] = issuer["content_sha256"]
                    outcome, ranking, audits, lineages = self.rank(mutate, reverse=reverse)
                    self.assertEqual(outcome, REFUSED_ONE)
                    self.assertEqual(self.claims(audits), {**all_claims(("SUPPORTED", 2)), target: ("SINGLE_SOURCE", 1)})
                    self.assertEqual(lineages, {key: value for key, value in CONTROL_LINEAGES.items() if key != target})
                    self.assert_gev_refused(ranking)

    # P1b extra copies of the second family never add a family: an exact duplicate row, the same body re-published by
    # another source and the same origin lineage under another source all keep two families (and the publisher seals).
    def test_B3_P1b_extra_mirrored_copies_never_add_a_family(self):
        target = cid("GEV", "dependency")
        for case in ("duplicate", "same_body_other_source", "same_origin_other_source"):
            with self.subTest(case=case):
                def mutate(bundle):
                    live = self.doe26(bundle, "GEV", "dependency")
                    if case == "duplicate":
                        bundle["GEV"]["source_observations"].append(copy.deepcopy(live))
                    elif case == "same_body_other_source":
                        self.fresh_copy(bundle, "GEV", "dependency", "mlgw", live["content_sha256"])
                    else:
                        self.fresh_copy(bundle, "GEV", "dependency", live["payload"]["origin_group"], INDEPENDENT_SHA)
                outcome, ranking, audits, lineages = self.rank(mutate)
                self.assertEqual(outcome, SEALABLE)
                self.assertEqual(self.claims(audits), all_claims(("SUPPORTED", 2)))
                self.assertEqual(lineages[target], 2)
                self.assertEqual((ranking["admitted_count"], ranking["ranked_count"]), (2, 2))

    # P2 the publisher leg: when the registry puts the DOE source in the issuer's independence group, every claim of both
    # tickers collapses to one family (0/0). Raw candidate rows carry no registry group, so this leg is enforced by
    # reconcile_research_claims alone; the bridge is never reached.
    def test_B3_P2_shared_publisher_group_counts_once(self):
        real = mlb.build_registry()
        registry = replace(real, sources=tuple(replace(source, independence_group="issuer")
                                               if source.source_id == mlb.DOE_LINEAGE else source
                                               for source in real.sources))
        outcome, ranking, audits, lineages = self.rank(registry=registry)
        self.assertEqual(outcome, REFUSED_NONE)
        self.assertEqual(self.claims(audits), all_claims(("SINGLE_SOURCE", 1)))
        self.assertEqual(lineages, {})
        self.assertEqual((ranking["admitted_count"], ranking["ranked_count"]), (0, 0))

    # P3 transitivity: a fresh third row that shares the issuer's origin AND the DOE body links both families into one
    # (refused); either link alone merges it into one side (two families, sealable); a fully independent third row is a
    # third family in both copies and leaves the ranking unchanged.
    def test_B3_P3_transitive_chain_counts_once_and_a_third_lineage_counts(self):
        target = cid("GEV", "dependency")
        control = self.rank()[1]
        cases = {"chain": ("issuer", "doe", REFUSED_ONE, ("SINGLE_SOURCE", 1), None),
                 "origin_link": ("issuer", "own", SEALABLE, ("SUPPORTED", 2), 2),
                 "hash_link": ("own", "doe", SEALABLE, ("SUPPORTED", 2), 2),
                 "three": ("own", "own", SEALABLE, ("SUPPORTED", 3), 3)}
        for case, (origin, body, want_outcome, want_claim, want_lineage) in cases.items():
            for reverse in (False, True):
                with self.subTest(case=case, reverse=reverse):
                    def mutate(bundle):
                        issuer, live = self.issuer(bundle, "GEV", "dependency"), self.doe26(bundle, "GEV", "dependency")
                        self.fresh_copy(bundle, "GEV", "dependency",
                                        issuer["payload"]["origin_group"] if origin == "issuer" else "mlgw",
                                        live["content_sha256"] if body == "doe" else INDEPENDENT_SHA)
                    outcome, ranking, audits, lineages = self.rank(mutate, reverse=reverse)
                    self.assertEqual(outcome, want_outcome)
                    self.assertEqual(self.claims(audits), {**all_claims(("SUPPORTED", 2)), target: want_claim})
                    self.assertEqual(lineages.get(target), want_lineage)
                    if want_outcome == SEALABLE:
                        self.assertEqual([row["ticker"] for row in ranking["ranked_candidates"]],
                                         [row["ticker"] for row in control["ranked_candidates"]])
                    else:
                        self.assert_gev_refused(ranking)

    # P4 cross-claim and cross-subject borrowing: the live DOE 2026 rows of GEV's other claims never lend a family to the
    # dependency claim; a row relabelled to 6501's claim is borrowed by neither ticker; a row relabelled to another GEV
    # claim keeps its own metric, so that claim turns NOT_COMPARABLE, never supported; a row about another subject under
    # the same claim id makes the claim NOT_COMPARABLE.
    def test_B3_P4_cross_claim_and_cross_subject_rows_are_not_borrowed(self):
        target, scarcity = cid("GEV", "dependency"), cid("GEV", "scarcity")
        cases = {"removed": {target: ("SINGLE_SOURCE", 1)},
                 "other_ticker_claim": {target: ("SINGLE_SOURCE", 1)},
                 "other_gev_claim": {target: ("SINGLE_SOURCE", 1), scarcity: ("UNAVAILABLE", 2)},
                 "other_subject": {target: ("UNAVAILABLE", 1)}}
        for case, changed in cases.items():
            with self.subTest(case=case):
                def mutate(bundle):
                    live = self.doe26(bundle, "GEV", "dependency")
                    if case == "removed":
                        bundle["GEV"]["source_observations"].remove(live)
                    elif case == "other_ticker_claim":
                        live["payload"]["claim_ids"] = [cid("6501", "dependency")]
                    elif case == "other_gev_claim":
                        live["payload"]["claim_ids"] = [scarcity]
                    else:
                        live["payload"]["subject"] = "6501"
                outcome, ranking, audits, _lineages = self.rank(mutate)
                self.assertEqual(outcome, REFUSED_ONE)
                self.assertEqual(self.claims(audits), {**all_claims(("SUPPORTED", 2)), **changed})
                self.assert_gev_refused(ranking)
                for claim_id, (status, _families) in changed.items():
                    if status == "UNAVAILABLE":
                        claim = next(row for row in audits["GEV"]["claims"] if row["claim_id"] == claim_id)
                        self.assertEqual(claim["reasons"], ["NOT_COMPARABLE"])

    # P5 the bridge copy reached through the publisher: a STALE row that shares one family's origin and the other
    # family's body leaves reconcile_research_claims at two live families (SUPPORTED) but collapses the bridge's count
    # over every bound row to one, so the factor is not licensed, core admission fails and the publisher refuses.
    def test_B3_P5_stale_mirror_collapses_the_bridge_count(self):
        for factor in ("dependency", "scarcity"):
            for reverse in (False, True):
                with self.subTest(factor=factor, reverse=reverse):
                    target = cid("GEV", factor)

                    def mutate(bundle):
                        issuer, live = self.issuer(bundle, "GEV", factor), self.doe26(bundle, "GEV", factor)
                        if factor == "dependency":
                            stale = self.row(bundle, "GEV", mlb.DOE_LINEAGE, mlb.DOE_URL, target)
                            stale["payload"]["origin_group"] = issuer["payload"]["origin_group"]
                            stale["content_sha256"] = live["content_sha256"]
                        else:
                            stale = self.row(bundle, "GEV", mlb.MLGW_LINEAGE, mlb.MLGW_URL, target)
                            stale["payload"]["origin_group"] = live["payload"]["origin_group"]
                            stale["content_sha256"] = issuer["content_sha256"]
                    outcome, ranking, audits, lineages = self.rank(mutate, reverse=reverse)
                    self.assertEqual(outcome, REFUSED_ONE)
                    self.assertEqual(self.claims(audits), all_claims(("SUPPORTED", 2)))
                    self.assertEqual(lineages, {**CONTROL_LINEAGES, target: 1})
                    authority = self.evaluation(ranking, "GEV")["factor_claim_authority"]
                    self.assertEqual((authority[factor + "_licensed"], authority["core_admitted"]), (False, False))
                    self.assertIn(f"Claim {target} observations collapse to 1 family (< 2 required)",
                                  authority["diagnostics"])
                    self.assert_gev_refused(ranking)

    # P6 a refused ranking seals nothing: publisher.main on the golden path raises before any run directory exists.
    def test_B3_P6_refused_mirror_seals_nothing(self):
        bundle = copy.deepcopy(mlb.bundled_candidates())
        mirror = self.doe26(bundle, "GEV", "dependency")
        mirror["payload"]["origin_group"] = self.issuer(bundle, "GEV", "dependency")["payload"]["origin_group"]
        with tempfile.TemporaryDirectory() as tmp:
            snapshots = Path(tmp).resolve() / "snapshots"
            with mock.patch.object(mlb, "bundled_candidates", return_value=bundle):
                with self.assertRaises(AssertionError) as raised:
                    publisher.main(["--snapshot-root", str(snapshots)])
            self.assertEqual(str(raised.exception), REFUSED_ONE)
            self.assertFalse(snapshots.exists())


class AcquisitionRunEngineRows(unittest.TestCase):
    """rank_bottleneck_candidates forwards an acquisition run to reconcile_research_claims (registry and health from the
    run, never the candidate). The research-only candidate has no factor evidence, so it is unranked in every row; the
    observable is its claims_audit."""

    def audit(self, mode, reverse=False, ticker="SYN"):
        run = acquired.research_run(mode, reverse)
        record = {"ticker": ticker, "material_claims": [acquired.research.claim()],
                  "source_observations": run.candidates_for("SYN")}
        policy = engine.load_json(engine.POLICY_DEFAULT_PATH)
        with mock.patch.object(acquired.observation, "utc_now", return_value=acquired.NOW), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
            ranking = engine.rank_bottleneck_candidates([record], policy, as_of=acquired.NOW,
                                                        acquisition_run=run, fixture_mode=False)
        self.assertEqual((ranking["admitted_count"], len(ranking["low_confidence_watchlist"])), (0, 1))
        audit = ranking["low_confidence_watchlist"][0]["claims_audit"]
        return audit["all_material_claims_supported"], audit["supported_claim_count"], audit["conflicted_claim_count"]

    # A1 distinct sources support the claim (two or three families); origin, hash, chain and shared-publisher mirrors of
    # the acquired rows count once, in both source orders.
    def test_B3_A1_engine_forwards_the_run_and_mirrors_count_once(self):
        for mode, supported in (("control", True), ("three", True), ("origin", False), ("hash", False),
                                ("chain", False), ("publisher", False)):
            for reverse in (False, True):
                with self.subTest(mode=mode, reverse=reverse):
                    self.assertEqual(self.audit(mode, reverse), (supported, int(supported), 0))

    # A2 the run's healthy rows cannot be borrowed by another caller ticker through the engine.
    def test_B3_A2_run_rows_cannot_be_borrowed_by_another_caller_ticker(self):
        self.assertEqual(self.audit("control"), (True, 1, 0))
        self.assertEqual(self.audit("control", ticker="OTHER"), (False, 0, 0))


if __name__ == "__main__":
    unittest.main()
