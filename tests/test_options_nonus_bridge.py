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

    def test_the_harness_stubs_only_transports_and_the_universe_never_main_build_health_or_the_sealer(self):
        source = (ROOT / "tests" / "fixtures" / "options_nonus_publisher_cases.py").read_text(encoding="utf-8")
        patched = set(re.findall(r'\(\("(\w+)", \w+\)|\("(\w+)", (?:lambda|\w+)', source[source.index("for name, value in ("):source.index("stack.enter_context(mock.patch(\"socket")]))
        names = {a or b for a, b in patched}
        self.assertEqual(names, {"http_json", "universe", "broad_universe", "utc_now", "alpha_vantage_quote", "alpha_vantage_key", "cached_universe"})
        for forbidden in ("build", "_build", "main", "observe", "is_venue_coverage_depleted", "lazy_market_bodies", "covered_call_suggestions", "cycle_result"):
            self.assertNotIn(f'("{forbidden}"', source)
        self.assertIn("builder.main([", source)
        self.assertIn("publisher.lazy_market_bodies(", source)

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
            with self.assertRaisesRegex(AssertionError, "exact sealed scenario tickers"):
                generator.seal(result.output, generator.NOW, synthetic_tickers=tickers | {"OUTSIDE-SCENARIO"})
            self.assertIs(generator.option_rights.public_option_cycle_admission, real_admission)

    def test_policy_constants_agree_with_the_validator_and_worker_windows(self):
        self.assertEqual(builder.CYCLES, {"weekly": (3, 14), "monthly": (21, 45)})

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

    def test_sive_cutoff_case_is_listed_but_out_of_policy_beside_healthy_siblings(self):
        options = self.options("retained_sive_sept30")
        monthly = options["SIVE.ST"]["monthly"]["unavailable"]
        self.assertIn("本次回應有上市買權；所列到期不在21–45天策略範圍", monthly)
        self.assertIn("2026-10-16（16天）", monthly)
        self.assertIn("2026-11-20（51天）", monthly)
        self.assertNotIn("年化權利金", monthly)
        self.assertIn("所列到期不在3–14天策略範圍", options["SIVE.ST"]["weekly"]["unavailable"])
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

    def test_currency_evidence_matrix_admits_only_the_agreeing_sek_control(self):
        options = self.options("currency_evidence_matrix")
        strategies = sorted(k for k, cycles in options.items() if k.endswith(".ST") and "unavailable" not in cycles["monthly"])
        self.assertEqual(strategies, ["CURSEK.ST", "VOLV-B.ST"])
        for key in ("CURNULL.ST", "CURUSD.ST", "CURMISSING.ST", "SPOTUSD.ST", "SPOTNONE.ST", "SEARCHEUR.ST", "SEARCHNONE.ST"):
            self.assertIn("unavailable", options[key]["monthly"], key)

    def test_native_symbol_identity_matrix_admits_only_the_proven_source_forms_through_main_and_sealer(self):
        options = self.options("native_symbol_identity_matrix")
        admitted = sorted(k for k, cycles in options.items() if k.endswith(".ST") and any("unavailable" not in v for v in cycles.values()))
        self.assertEqual(admitted, ["SYMCTL.ST", "SYMMON.ST", "SYMWEEK.ST", "VOLV-B.ST"])
        control = options["SYMCTL.ST"]["weekly"]
        self.assertEqual((control["ticker"], control["currency"], control["dte"], control["suggestions"][0]["strike"]), ("SYMCTL.ST", "SEK", 14, 15.5))
        for root in ("SYMSTRIKE", "SYMMONTH", "SYMYEAR", "SYMPUT", "SYMPREFIX", "SYMDAY", "SYMUNSUP", "SYMEMPTY", "SYMTYPE", "SYMNONE",
                     "SYMTAGZ", "SYMTAGA", "SYMTAGW", "SYMPREC"):
            for cycle in ("weekly", "monthly"):
                text = options[f"{root}.ST"][cycle]["unavailable"]
                self.assertIn("買權資料無法解析；不推斷是否上市", text, root)
        health = self.doc["cases"]["native_symbol_identity_matrix"]["collection"]["chain_health"]["STOCKHOLM"]
        self.assertEqual((health["read"], health["healthy"]), (4, 4), "a contradictory contract never enters R or H")

    def test_a_sub_cent_strike_keeps_quote_health_but_is_never_recommended_as_another_strike(self):
        options = self.options("strike_precision_matrix")
        for key in ("SUBCENT.ST", "YSUBCENT"):
            text = options[key]["weekly"]["unavailable"]
            self.assertIn("兩位以上小數", text, key)
            for wrong in ("無有效雙邊報價", "年化權利金", "無法解析", "15.51", "15.50"):
                self.assertNotIn(wrong, text, key)
        self.assertEqual(options["TRAIL.ST"]["weekly"]["suggestions"][0]["strike"], 15.5)
        mixed = [row["strike"] for row in options["MIXED.ST"]["weekly"]["suggestions"]]
        self.assertTrue(mixed and 15.505 not in mixed and all(round(k, 2) == k for k in mixed), mixed)
        self.assertIn("所選到期無有效雙邊報價", options["SUBZERO.ST"]["weekly"]["unavailable"])
        health = self.doc["cases"]["strike_precision_matrix"]["collection"]["chain_health"]
        self.assertEqual((health["STOCKHOLM"]["read"], health["STOCKHOLM"]["healthy"]), (5, 4), "sub-cent chains are not removed from R/H")
        self.assertEqual((health["US"]["read"], health["US"]["healthy"]), (8, 8))

    def test_the_retained_weekly_volvb_shape_is_a_proven_listing_in_the_real_pipeline(self):
        weekly = self.options("retained_sive_sept30")["VOLV-B.ST"]["weekly"]["unavailable"]
        self.assertIn("所列到期不在3–14天策略範圍", weekly)
        self.assertIn("2026-10-02（2天）", weekly)
        self.assertNotIn("無法解析", weekly)
        self.assertIn("volvb_option_chain", self.doc["provenance"]["retained_source_samples"])

    def test_yahoo_read_chains_without_a_usable_quote_are_truthful_and_never_retried(self):
        options = self.options("dte_us_matrix")
        for key in ("UYZERO", "UYONESIDED"):
            for cycle in ("weekly", "monthly"):
                text = options[key][cycle]["unavailable"]
                self.assertIn("所選到期無有效雙邊報價", text)
                self.assertNotIn("年化權利金", text)
        admitted = self.options("us_1_of_10_admitted")
        self.assertIn("所選到期無有效雙邊報價", admitted["DEPUS03"]["monthly"]["unavailable"])

    def test_identity_and_terms_cases_keep_the_reasons_distinct(self):
        ident = self.options("identity_matrix")
        unparseable = [k for k, v in ident.items() if "買權資料無法解析" in v["monthly"].get("unavailable", "")]
        no_records = [k for k, v in ident.items() if "無可用之買權紀錄" in v["monthly"].get("unavailable", "")]
        failed = [k for k, v in ident.items() if "讀取或解析失敗" in v["monthly"].get("unavailable", "")]
        self.assertEqual(sorted(unparseable), sorted(f"{r}.ST" for r in ("IDROOT", "IDDATE", "IDSTRIKE", "IDSYMBOL", "IDNAMENONE", "IDBADDATE", "IDBADSTRIKE", "IDMALONLY")))
        self.assertEqual(sorted(no_records), sorted(f"{r}.ST" for r in ("IDPUT", "IDFUTCOPT", "IDFUTC", "IDUNKNOWN", "IDNOCLASS", "IDEMPTY")))
        self.assertEqual(sorted(failed), sorted(f"{r}.ST" for r in ("IDROWSNONE", "IDROWSDICT", "IDENVELOPE", "IDENVLIST", "IDEXC")))
        self.assertNotIn("unavailable", ident["IDMIXED.ST"]["monthly"])
        terms = self.options("terms_and_quote_states")
        self.assertIn("合約單位非標準100股", terms["TSIZE50.ST"]["monthly"]["unavailable"])
        self.assertNotIn("所列到期不在21", terms["TSIZE50.ST"]["monthly"]["unavailable"])
        self.assertIn("所選到期無有效雙邊報價", terms["QLASTSALE.ST"]["monthly"]["unavailable"])
        self.assertNotIn("unavailable", terms["TSZEXACT.ST"]["monthly"], "100.00 is a validated exact-100 representation")
        self.assertIn("合約單位非標準100股", terms["TSZPREC.ST"]["monthly"]["unavailable"])  # 100.000000000000000001 is not 100
        self.assertNotIn("unavailable", terms["TSZEXACT.ST"]["monthly"])
        for key in ("TSZLEADING.ST", "TSZEXP.ST", "TSZLONG.ST"):
            self.assertIn("合約單位或幣別來源未確認", terms[key]["monthly"]["unavailable"])
            self.assertNotIn("非標準", terms[key]["monthly"]["unavailable"])
        self.assertIn("沒有年化權利金達 6%", terms["QMISS.ST"]["monthly"]["unavailable"])

    def test_dte_matrices_follow_the_policy_windows_for_every_selector(self):
        for case, keys in (("dte_nordic_matrix", [f"ND{d}.ST" for d in generator.NORDIC_DTES]),
                           ("dte_us_matrix", [f"{p}{d}" for p in ("UY", "UN") for d in generator.US_DTES])):
            options = self.options(case)
            for key in keys:
                dte = int(re.search(r"(\d+)", key.split(".")[0]).group(1))
                for cycle, (low, high) in (("weekly", (3, 14)), ("monthly", (21, 45))):
                    emitted = "unavailable" not in options[key][cycle]
                    self.assertEqual(emitted, low <= dte <= high, f"{case} {key} {cycle}")
                    if emitted:
                        self.assertEqual(options[key][cycle]["dte"], dte)

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
