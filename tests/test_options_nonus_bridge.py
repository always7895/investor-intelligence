"""OPTIONS-NONUS-02 (r3) producer -> sealer bridge tests.

The committed Worker fixture must be exactly what the REAL producer main + REAL lazy_market_bodies emit for the named cases
(regenerated here, byte for byte), every admitted case must carry its intended outcome, every depleted case must have exited 1
with the previous bytes intact, and the harness itself must not mock main/build/health/guard/sealer. Offline, private TEMP.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import build_market_quotes_options as builder  # noqa: E402
from tests.fixtures import options_nonus_publisher_cases as generator  # noqa: E402

COMMITTED = ROOT / "cloud" / "test" / "fixtures" / "options-nonus-publisher.json"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class BridgeFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.committed_bytes = COMMITTED.read_bytes()
        cls.doc = json.loads(cls.committed_bytes)

    def options(self, case: str) -> dict:
        return json.loads(self.doc["cases"][case]["bodies"]["options"])["options"]

    def test_committed_fixture_is_byte_for_byte_the_regeneration_from_real_main_and_sealer(self):
        with tempfile.TemporaryDirectory(prefix="bridge_verify_") as tmp:
            target = Path(tmp) / "options-nonus-publisher.json"
            generator.write_fixture(target)
            self.assertEqual(self.committed_bytes, target.read_bytes())
        self.assertNotIn(b"\r", self.committed_bytes, "generated LF")

    def test_synthetic_admission_is_explicit_and_rights_none_is_restored(self):
        specs = [generator.healthy_st("VOLV-B.ST", 310.0), *generator.healthy_us(10)]
        tickers = frozenset(spec["symbol"] for spec in specs)
        real_admission = generator.option_rights.public_option_cycle_admission
        with tempfile.TemporaryDirectory(prefix="bridge_rights_none_") as tmp:
            result = generator.run_main(specs, generator.NOW, Path(tmp))
            self.assertEqual(result.rc, 0)
            without = generator.publisher.lazy_market_bodies(result.output, generator.NOW)
            self.assertIn("OPTION_RIGHTS_NOT_ADMITTED",
                          generator.cycle_of(without, "VOLV-B.ST", "monthly")["unavailable"])
            admitted = generator.seal(result.output, generator.NOW, synthetic_tickers=tickers)
            self.assertNotIn("unavailable", generator.cycle_of(admitted, "VOLV-B.ST", "monthly"))
            self.assertIs(generator.option_rights.public_option_cycle_admission, real_admission)
            self.assertEqual(generator.publisher.lazy_market_bodies(result.output, generator.NOW), without)
            with self.assertRaises(AssertionError):
                generator.seal(result.output, generator.NOW, synthetic_tickers=tickers | {"OUTSIDE-SCENARIO"})
            self.assertIs(generator.option_rights.public_option_cycle_admission, real_admission)

    def test_every_body_hash_matches_its_exact_string_and_provenance_is_embedded(self):
        self.assertEqual(self.doc["schema"], generator.BRIDGE_SCHEMA)
        prov = self.doc["provenance"]["retained_source_samples"]
        for entry in prov.values():
            self.assertRegex(entry["archive_sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(entry["url"].startswith("https://api.nasdaq.com/api/nordic/"))
        self.assertIn("retrieved_at_utc", prov["sive_option_chain"])
        self.assertIn("SYNTHETIC", self.doc["provenance"]["synthetic"])
        kinds = set()
        for case_id, case in self.doc["cases"].items():
            kinds.add(case["kind"])
            if case["kind"] == "ADMITTED":
                self.assertEqual(case["producer_exit"], 0, case_id)
                self.assertEqual(case["hashes"], {"options_sha256": sha(case["bodies"]["options"]), "quotes_sha256": sha(case["bodies"]["quotes"])}, case_id)
                self.assertGreaterEqual(len(json.loads(case["bodies"]["quotes"])["quotes"]), 10, case_id)
            else:
                self.assertEqual((case["kind"], case["producer_exit"], case["prior_file_unchanged"]), ("REJECTED", 1, True), case_id)
                self.assertEqual(case["status"]["error"], "OPTION_TWO_SIDED_COVERAGE_LOW", case_id)
                self.assertEqual(case["retained_old_hashes"], {"options_sha256": sha(case["retained_old_bodies"]["options"]),
                                                               "quotes_sha256": sha(case["retained_old_bodies"]["quotes"])}, case_id)
                self.assertLess(case["retained_old_generated_at"], self.doc["clock"], "the old file keeps its ORIGINAL earlier timestamp")
                self.assertEqual(json.loads(case["retained_old_bodies"]["options"])["generated_at"], case["retained_old_generated_at"])
        self.assertEqual(kinds, {"ADMITTED", "REJECTED"})

    def test_sive_weekly_is_out_of_policy_beside_healthy_siblings(self):
        options = self.options("retained_sive_sept30")
        self.assertEqual(set(options["SIVE.ST"]["weekly"]), {"unavailable"})
        for key, currency in (("VOLV-B.ST", "SEK"), ("AZN.ST", "SEK"), ("AZN", "USD"), ("SYNTHUS00", "USD")):
            cycle = options[key]["monthly"]
            self.assertEqual((cycle["ticker"], cycle["currency"], cycle["multiplier"]), (key, currency, 100), key)

    def test_each_native_cycle_cites_its_own_listings_order_book_and_the_synthetic_source_label(self):
        options = self.options("retained_sive_sept30")
        expected = {"VOLV-B.ST": "SYNTH-SHARE-VOLVB", "AZN.ST": "SYNTH-SHARE-AZN"}
        for key, order_book in expected.items():
            cycle = options[key]["monthly"]
            self.assertEqual(cycle["provenance"], builder.NORDIC_CHAIN.format(orderbook=order_book), key)
            self.assertEqual(cycle["source"], builder.NORDIC_SOURCE)
        self.assertNotEqual(options["VOLV-B.ST"]["monthly"]["provenance"], options["AZN.ST"]["monthly"]["provenance"])
        self.assertIn("SYNTHETIC", self.doc["provenance"]["synthetic"])
        self.assertEqual(self.doc["provenance"]["retained_source_samples"]["sive_option_chain"]["url"],
                         builder.NORDIC_CHAIN.format(orderbook="TX2540138"))

    def test_currency_evidence_matrix_admits_only_agreeing_sek_or_a_blank_contract_currency(self):
        options = self.options("currency_evidence_matrix")
        strategies = sorted(k for k, cycles in options.items() if k.endswith(".ST") and "unavailable" not in cycles["monthly"])
        # V13: a blank contract currency ("" or an absent key) follows the confirmed SEK underlying (Nasdaq contract specification).
        self.assertEqual(strategies, ["CUREMPTY.ST", "CURMISSING.ST", "CURSEK.ST", "VOLV-B.ST"])
        for key in ("CUREMPTY.ST", "CURMISSING.ST"):
            self.assertEqual((options[key]["monthly"]["currency"], options[key]["monthly"]["multiplier"]), ("SEK", 100), key)
        for key in ("CURNULL.ST", "CURWS.ST", "CURLOWER.ST", "CURUSD.ST", "SPOTUSD.ST", "SPOTNONE.ST", "SEARCHEUR.ST", "SEARCHNONE.ST"):
            self.assertIn("unavailable", options[key]["monthly"], key)

    def test_native_symbol_identity_matrix_admits_only_the_proven_source_forms_through_main_and_sealer(self):
        options = self.options("native_symbol_identity_matrix")
        admitted = sorted(k for k, cycles in options.items() if k.endswith(".ST") and any("unavailable" not in v for v in cycles.values()))
        self.assertEqual(admitted, ["SYMCTL.ST", "SYMMON.ST", "SYMWEEK.ST", "VOLV-B.ST"])
        control = options["SYMCTL.ST"]["weekly"]
        self.assertEqual((control["ticker"], control["currency"], control["dte"], control["suggestions"][0]["strike"]), ("SYMCTL.ST", "SEK", 9, 15.5))
        for root in ("SYMSTRIKE", "SYMMONTH", "SYMYEAR", "SYMPUT", "SYMPREFIX", "SYMDAY", "SYMUNSUP", "SYMEMPTY", "SYMTYPE", "SYMNONE",
                     "SYMTAGZ", "SYMTAGA", "SYMTAGW", "SYMPREC"):
            for cycle in ("weekly", "monthly"):
                value = options[f"{root}.ST"][cycle]
                self.assertEqual(set(value), {"unavailable"}, root)
                self.assertTrue(value["unavailable"], root)
        health = self.doc["cases"]["native_symbol_identity_matrix"]["collection"]["chain_health"]["STOCKHOLM"]
        self.assertEqual((health["read"], health["healthy"]), (4, 4), "a contradictory contract never enters R or H")

    def test_a_sub_cent_strike_keeps_quote_health_but_is_never_recommended_as_another_strike(self):
        options = self.options("strike_precision_matrix")
        for key in ("SUBCENT.ST", "YSUBCENT"):
            self.assertEqual(set(options[key]["weekly"]), {"unavailable"}, key)
        self.assertEqual(options["TRAIL.ST"]["weekly"]["suggestions"][0]["strike"], 15.5)
        mixed = [row["strike"] for row in options["MIXED.ST"]["weekly"]["suggestions"]]
        self.assertTrue(mixed and 15.505 not in mixed and all(round(k, 2) == k for k in mixed), mixed)
        self.assertEqual(set(options["SUBZERO.ST"]["weekly"]), {"unavailable"})
        health = self.doc["cases"]["strike_precision_matrix"]["collection"]["chain_health"]
        self.assertEqual((health["STOCKHOLM"]["read"], health["STOCKHOLM"]["healthy"]), (5, 4), "sub-cent chains are not removed from R/H")
        self.assertEqual((health["US"]["read"], health["US"]["healthy"]), (8, 8))

    def test_the_retained_weekly_volvb_shape_is_a_proven_listing_in_the_real_pipeline(self):
        weekly = self.options("retained_sive_sept30")["VOLV-B.ST"]["weekly"]["unavailable"]
        # this calendar week's weekly; V13: its blank contract currency follows the SEK underlying, its retained bid/ask are empty
        self.assertIn("2026-10-02", weekly)  # source-listed expiry, not a fabricated next-week contract
        self.assertEqual(set(self.options("retained_sive_sept30")["VOLV-B.ST"]["weekly"]), {"unavailable"})
        self.assertIn("volvb_option_chain", self.doc["provenance"]["retained_source_samples"])

    def test_yahoo_read_chains_without_a_usable_quote_are_truthful_and_never_retried(self):
        options = self.options("dte_us_matrix")
        for key in ("UYZERO", "UYONESIDED"):
            self.assertEqual(set(options[key]["weekly"]), {"unavailable"})
            monthly = options[key]["monthly"]
            self.assertEqual(monthly["suggestions"], [])
            observation = monthly["quote_observation"]
            self.assertEqual(observation["kind"], "NO_TWO_SIDED")
            self.assertEqual((observation["bid"], observation["ask"], observation["last"], observation["annualized_yield"]),
                             (None, None, None, None))
        admitted = self.options("us_1_of_10_admitted")
        self.assertEqual(admitted["DEPUS03"]["monthly"]["suggestions"], [])
        self.assertEqual(admitted["DEPUS03"]["monthly"]["quote_observation"]["kind"], "NO_TWO_SIDED")

    def test_invalid_identity_and_terms_never_supply_quote_or_strategy_fields(self):
        ident = self.options("identity_matrix")
        for root in ("IDROOT", "IDDATE", "IDSTRIKE", "IDSYMBOL", "IDNAMENONE", "IDBADDATE", "IDBADSTRIKE", "IDMALONLY",
                     "IDPUT", "IDFUTCOPT", "IDFUTC", "IDUNKNOWN", "IDNOCLASS", "IDEMPTY",
                     "IDROWSNONE", "IDROWSDICT", "IDENVELOPE", "IDENVLIST", "IDEXC"):
            self.assertEqual(set(ident[f"{root}.ST"]["monthly"]), {"unavailable"}, root)
        self.assertNotIn("unavailable", ident["IDMIXED.ST"]["monthly"])
        terms = self.options("terms_and_quote_states")
        for key in ("TSIZE1005.ST", "TSZPREC.ST", "TSZLEADING.ST", "TSZEXP.ST", "TSZLONG.ST"):
            self.assertEqual(set(terms[key]["monthly"]), {"unavailable"}, key)
        self.assertEqual(terms["TSZEXACT.ST"]["monthly"]["multiplier"], 100)
        for key in ("TSIZE50.ST", "TSIZENONE.ST", "TCCYNONE.ST"):
            self.assertEqual(set(terms[key]["monthly"]), {"unavailable"}, key)
            self.assertIn("2026-10-16", terms[key]["monthly"]["unavailable"], key)
        for key in ("QNOQUOTE.ST", "QONESIDED.ST", "QZERO.ST", "QCROSSED.ST", "QLASTSALE.ST", "QMISS.ST", "QCHEAP.ST"):
            self.assertEqual(terms[key]["monthly"]["suggestions"], [], key)
            self.assertFalse(terms[key]["monthly"].get("strategies"), key)
        last_sale = terms["QLASTSALE.ST"]["monthly"]["quote_observation"]
        self.assertEqual((last_sale["kind"], last_sale["bid"], last_sale["ask"], last_sale["last"]),
                         ("NO_TWO_SIDED", None, None, 0.55))
        for key, bid, ask in (("QMISS.ST", 4.0, 4.2), ("QCHEAP.ST", 0.01, 0.02)):
            observation = terms[key]["monthly"]["quote_observation"]
            self.assertEqual((observation["kind"], observation["bid"], observation["ask"], observation["last"]),
                             ("TWO_SIDED", bid, ask, None), key)
            self.assertEqual(observation["annualized_yield"], round(bid / 100 * 365 / 16, 6), key)

    def test_dte_matrices_follow_the_policy_windows_for_every_selector(self):
        for case, keys in (("dte_nordic_matrix", [f"ND{d}.ST" for d in generator.NORDIC_DTES]),
                           ("dte_us_matrix", [f"{p}{d}" for p in ("UY", "UN") for d in generator.US_DTES])):
            options = self.options(case)
            for key in keys:
                dte = int(re.search(r"(\d+)", key.split(".")[0]).group(1))
                for cycle in ("weekly", "monthly"):
                    value = options[key][cycle]
                    emitted = "unavailable" not in value
                    expected = generator.in_cycle(cycle, dte)
                    self.assertEqual(emitted, expected, f"{case} {key} {cycle}")
                    if emitted:
                        self.assertEqual((value["expiry"], value["dte"]), (generator.dte_date(dte), dte))
                        if cycle == "monthly":
                            self.assertNotIn("monthly_nonstandard", value)

    def test_depleted_candidates_are_rejected_with_old_bytes_intact_and_boundaries_admit(self):
        with tempfile.TemporaryDirectory(prefix="bridge_depleted_") as tmp:
            base = Path(tmp)
            (base / "prior").mkdir()
            prior, prior_bodies = generator._prior_bytes(base / "prior")
            for index, (case_id, venue, chains, healthy, admitted) in enumerate(generator.DEPLETION_CASES):
                directory = base / str(index)
                directory.mkdir()
                result = generator.run_main(generator._depletion_specs(venue, chains, healthy), generator.NOW, directory, prior=prior)
                if admitted:
                    self.assertEqual(result.rc, 0, case_id)
                    self.assertEqual(result.doc["collection"]["chain_health"][venue]["healthy"], healthy)
                else:
                    self.assertEqual(result.rc, 1, case_id)
                    self.assertEqual(result.output.read_bytes(), prior, f"{case_id}: nothing was written over the old file")
                    self.assertFalse((directory / "market_quotes_options.json.tmp").exists())
                    self.assertEqual(generator.seal(result.output, generator.NOW,
                                                    synthetic_tickers=frozenset(json.loads(prior)["options"])), prior_bodies)
                    self.assertEqual(self.doc["cases"][case_id]["retained_old_bodies"]["options"], prior_bodies["v213:options:v2"])


if __name__ == "__main__":
    unittest.main()
