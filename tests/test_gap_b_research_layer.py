"""GAP-B additive research-layer regression tests. No network; real Serenity fixture post shape."""
from __future__ import annotations

import importlib
import json
import math
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import serenity_signals as serenity
import bottleneck_top20_v3 as engine
import build_market_quotes_options as quotes
import publish_sealed_snapshot as publisher
import revenue_guidance_host as host
from tests.test_bottleneck_top20_v3 import historical_actions

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)
MAPPING = json.loads((ROOT / "config/serenity-ticker-map-v1.json").read_text(encoding="utf-8"))
US = {"XXXX", "YYYY", "ZZZZ", "ALFA", "BETA", "GAMA", "RELA", "RELB"}
RAW = json.loads((ROOT / "tests/fixtures/serenity/posts.json").read_text(encoding="utf-8"))


def post(pid: int, text: str, days_ago: int, **extra):
    # Same post envelope as tests/test_serenity_signals.py, derived from existing fixture.
    day = NOW - timedelta(days=days_ago)
    item = {"id": str(pid), "createdAtISO": day.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sourceUrl": f"https://x.com/aleabitoreddit/status/{pid}",
            "text": text, "metrics": {"likes": 10, "retweets": 2},
            "isRetweet": False}
    item.update(extra)
    return item


def archive(posts):
    return {"source_url": serenity.ARCHIVE_URL, "repository": serenity.ARCHIVE_REPO,
            "retrieved_at": "2026-10-17T00:00:00Z", "sha256": "0" * 64, "posts": posts}


def classified(posts):
    # A fixture converted from the repo's actual tests/fixtures/serenity/posts.json.
    fixture = [post(int(p["id"]), p["text"], p["days_ago"], **({"isReply": True} if p.get("isReply") else {}))
               for p in RAW["posts"]]
    doc = serenity.build_signals(archive(fixture + posts), MAPPING, US, NOW)
    rows = {row["symbol"]: row for row in doc["signals"]}
    events = {(p["symbol"], p["post_id"]): p["post_type"] for p in doc["post_types"]}
    return doc, rows, events


class PostTypeRules(unittest.TestCase):
    def test_new_then_reaffirmed_chronology_remains_consumable(self):
        doc, rows, event = classified([post(9102, "Still holding $XXXX, doubled down", 3),
                                       post(9101, "I opened a position in $XXXX", 20)])
        calibration = importlib.import_module("serenity_calibration").build_calibration(doc, lambda _: [])
        thesis = next(row for row in calibration["symbols"] if row["symbol"] == "XXXX")
        self.assertEqual(thesis["new_thesis_dates"], [post(9101, "", 20)["createdAtISO"][:10]])
        self.assertEqual(thesis["source_kinds"], ["ORIGINAL"])
        self.assertEqual(event["XXXX", "9101"], "NEW_THESIS")
        self.assertEqual(event["XXXX", "9102"], "REAFFIRMATION")
        self.assertEqual(rows["XXXX"]["first_thesis_at"], post(9101,"",20)["createdAtISO"])
        self.assertEqual(rows["XXXX"]["latest_post_type"], "REAFFIRMATION")

    def test_nonpersonal_three_name_supplier_map_not_a_thesis(self):
        _, rows, event = classified([post(9201, "Supplier map: $ALFA, $BETA and $GAMA", 4)])
        self.assertTrue(all(event[s, "9201"] == "WATCHLIST_MAP" for s in ("ALFA","BETA","GAMA")))
        self.assertIsNone(rows["ALFA"]["first_thesis_at"])
        # First-person language about mapping is not first-person bullish STANCE.
        _, _, extra = classified([post(9202, "My supplier map: $ALFA, $BETA and $GAMA", 4),
                                  post(9203, "I bought $ALFA, $BETA and $GAMA", 3)])
        self.assertEqual(extra["ALFA", "9202"], "WATCHLIST_MAP")
        self.assertEqual(extra["ALFA", "9203"], "NEW_THESIS")

    def test_victory_lap_requires_prior_held_name_and_is_not_new_thesis(self):
        _, rows, event = classified([post(9301, "I bought $XXXX", 30),
                                     post(9302, "Told you $XXXX would run, my position is up 40%", 4),
                                     post(9303, "Told you $YYYY is up 40%", 3)])
        self.assertEqual(event["XXXX", "9302"], "VICTORY_LAP")
        self.assertEqual(rows["XXXX"]["victory_laps_60d"], 1)
        self.assertEqual(event["YYYY", "9303"], "OTHER")
        self.assertIsNone(rows["YYYY"]["first_thesis_at"])

    def test_satire_relay_negation_thirdparty_are_never_bullish_or_laps(self):
        _, rows, event = classified([post(9401, "I bought $XXXX /s", 14),
                                     post(9402, "Situational Awareness 13F holdings $ALFA", 12),
                                     post(9403, "I'm not buying $YYYY", 11),
                                     post(9404, "People on my X feed:\n- Long $ALFA\n- Long $BETA\n- Long $GAMA", 10),
                                     post(9405, "I sold $ZZZZ calls, up 40%", 5)])
        self.assertEqual(event["XXXX", "9401"], "OTHER")
        self.assertNotIn(("ALFA","9402"), event)
        self.assertEqual(event["YYYY", "9403"], "OTHER")
        for s in ("ALFA","BETA","GAMA"):
            self.assertEqual(event[s, "9404"], "OTHER")
        self.assertEqual(event["ZZZZ", "9405"], "OTHER")
        self.assertIsNone(rows["XXXX"]["first_thesis_at"])

    def test_only_counted_originals_and_victory_60_day_boundary(self):
        _, rows, event = classified([post(9501, "I bought $XXXX", 100),
                                     post(9502, "I called it on $XXXX! My position up 20%", 61),
                                     post(9503, "I called it on $XXXX! My position up 30%", 59),
                                     post(9504, "I doubled down on $YYYY", 4, isRetweet=True)])
        self.assertEqual(rows["XXXX"]["victory_laps_60d"], 1)
        self.assertEqual(event["XXXX", "9502"], "VICTORY_LAP")
        self.assertNotIn(("YYYY","9504"), event)


class CalibrationTests(unittest.TestCase):
    def module(self):
        return importlib.import_module("serenity_calibration")

    def test_unknown_forward_prices_are_null_and_not_misses(self):
        cal = self.module()
        doc = serenity.build_signals(archive([post(9601, "I bought $XXXX", 17),
                                               post(9602, "I bought $YYYY", 17)]), MAPPING, US, NOW)
        day = (NOW-timedelta(days=17)).date()
        trading_days = [day + timedelta(days=n) for n in range(110)
                        if (day + timedelta(days=n)).weekday() < 5]
        prices = [(d, 100.0 + i) for i,d in enumerate(trading_days)]
        def reader(sym): return prices if sym == "XXXX" else None
        data = cal.build_calibration(doc, reader, evidence_records=[
            {"symbol":"XXXX","published_at":trading_days[7].isoformat(),
             "source_url":"https://issuer.example/ir/2026","evidence_family":"ISSUER"}])
        by = {r["symbol"]: r for r in data["symbols"]}
        self.assertIsNone(by["YYYY"]["ret_5d"])
        self.assertEqual(by["XXXX"]["validation_lag_trading_days"], 7)
        self.assertGreater(by["XXXX"]["ret_20d"], 0)
        self.assertEqual(data["summary"]["5d"]["count_used"], 1)
        self.assertEqual(data["summary"]["5d"]["unknown_count"], 1)
        self.assertEqual(data["summary"]["5d"]["hit_share"], 1.0)
        self.assertTrue(any("self-selection" in s.lower() for s in data["caveats"]))
        self.assertTrue(any("survivorship" in s.lower() for s in data["caveats"]))

    def test_trading_horizon_not_calendar_and_incomplete_is_unknown(self):
        cal = self.module()
        doc = serenity.build_signals(archive([post(9701, "I bought $XXXX", 13)]), MAPPING, US, NOW)
        day = (NOW-timedelta(days=13)).date()
        days=[day+timedelta(days=i) for i in range(20) if (day+timedelta(days=i)).weekday()<5]
        data = cal.build_calibration(doc, lambda _: [(d,100.0+i) for i,d in enumerate(days)])
        self.assertAlmostEqual(data["symbols"][0]["ret_5d"], 0.05)
        self.assertIsNone(data["symbols"][0]["ret_20d"])
        self.assertEqual(data["summary"]["20d"]["unknown_count"],1)

    def test_mirrors_and_reposts_do_not_create_independent_calibration_observations(self):
        original = post(9801, "I bought $XXXX", 13)
        mirror = {**original, "id": "9802", "sourceUrl": "https://mirror.example/status/9802",
                  "originalSourceUrl": original["sourceUrl"]}
        doc = serenity.build_signals(archive([original, mirror,
            post(9803, "I bought $YYYY", 3, isRepost=True)]), MAPPING, US, NOW)
        data = self.module().build_calibration(doc, lambda _: [])
        self.assertEqual(data["count_new_thesis_symbols"], 1)
        self.assertEqual(data["symbols"][0]["independent_source_count"], 1)
        self.assertEqual(data["symbols"][0]["evidence_family"], "SERENITY_AUTHOR")
        self.assertEqual(data["summary"]["5d"]["unknown_count"], 1)

    def test_future_invalid_and_removed_thesis_events_cannot_be_resurrected_by_row_date(self):
        doc = serenity.build_signals(archive([post(9901, "I bought $XXXX", 13)]), MAPPING, US, NOW)
        for bad in ("not-a-date", "2027-01-01T00:00:00Z", "2026-10-05"):
            broken = json.loads(json.dumps(doc))
            broken["post_types"][0]["created_at"] = bad
            self.assertEqual(self.module().build_calibration(broken, lambda _: [])["count_new_thesis_symbols"], 0)
        doc["post_types"] = []
        self.assertEqual(self.module().build_calibration(doc, lambda _: [])["count_new_thesis_symbols"], 0)

    def test_current_signal_document_runs_through_real_calibration_cli(self):
        cal = self.module()
        doc = serenity.build_signals(archive([post(9951, "I bought $XXXX", 13)]), MAPPING, US, NOW)
        with tempfile.TemporaryDirectory() as td:
            source, target = Path(td) / "signals.json", Path(td) / "calibration.json"
            source.write_text(json.dumps(doc), encoding="utf-8")
            with patch.object(cal, "cached_price_reader", return_value=[]):
                self.assertEqual(cal.main(["--signals", str(source), "--output", str(target)]), 0)
            data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["count_new_thesis_symbols"], 1)
        self.assertEqual(data["symbols"][0]["source_kinds"], ["ORIGINAL"])
        self.assertEqual(data["symbols"][0]["source_content_sha256"], doc["signals"][0]["latest_content_sha256"])
        self.assertEqual(data["summary"]["5d"]["count_used"], 0)

    def test_existing_captured_yahoo_chart_parser_is_used_no_provider(self):
        cal = self.module()
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/"yahoo/chart/XXXX"
            target.parent.mkdir(parents=True)
            d = date(2026,10,1)
            body={"chart":{"result":[{"timestamp":[int(datetime(2026,10,i,tzinfo=timezone.utc).timestamp()) for i in (1,2)],
                       "indicators":{"adjclose":[{"adjclose":[100,103]}]}}]}}
            target.write_text(json.dumps(body),encoding="utf-8")
            self.assertEqual(cal.cached_price_reader("XXXX", cache_root=Path(td)), [(d,100.0),(date(2026,10,2),103.0)])
            self.assertEqual(cal.cached_price_reader("YYYY", cache_root=Path(td)), [])


class RoboticsAndWindowTests(unittest.TestCase):
    def test_rank_seven_dated_primary_issuer_and_weight(self):
        doc=json.loads((ROOT/"config/bottleneck-layers-v3.json").read_text(encoding="utf-8"))
        layers={layer["id"]:layer for layer in doc["layers"]}
        self.assertIn("physical_ai_robotics",layers)
        robotics=layers["physical_ai_robotics"]
        self.assertEqual(robotics["chain_rank"],7)
        self.assertEqual(doc["chain_weights"]["7"],0.5)
        self.assertEqual(engine.chain_weights(doc)[7],0.5)
        self.assertTrue(robotics["capturers"])
        for row in robotics["capturers"]:
            self.assertTrue(row["symbol"].endswith(".T"))
            self.assertTrue(row["source_url"].startswith("https://"))
            self.assertRegex(row["source_date"],r"^20\d\d-\d\d")
            self.assertTrue(all(row.get(k) for k in ("role","role_zh")))
            self.assertTrue(host.SYMBOL.fullmatch(row["symbol"]))

    def test_non_us_rank_seven_goes_through_ranking_quotes_translations_and_host_scope(self):
        layers=json.loads((ROOT/"config/bottleneck-layers-v3.json").read_text(encoding="utf-8"))
        robotics=next(l for l in layers["layers"] if l["id"]=="physical_ai_robotics")
        sym=robotics["capturers"][0]["symbol"]
        self.assertIn(sym,quotes.universe())
        roles,constraints=publisher._layer_translations(ROOT/"config/bottleneck-layers-v3.json")
        self.assertEqual(roles[sym],robotics["capturers"][0]["role_zh"])
        self.assertEqual(constraints["physical_ai_robotics"],robotics["leopold_constraint_zh"])
        members={entry["symbol"] for layer in layers["layers"] for entry in layer["capturers"]}
        self.assertLessEqual(len(members),256)
        self.assertIn(sym,members)
        # Direct complete build with local stubs, no live exchanges/providers.
        with tempfile.TemporaryDirectory() as td:
            layer_path=Path(td)/"layers.json"
            layer_path.write_text(json.dumps({"layers":[robotics],"chain_weights":{"7":0.5}}),encoding="utf-8")
            market={"ret_6m":0.2,"ret_1y":0.3,"cagr_2y":0.1,"price":100.0,
                    "market_cap":1e9,"currency":"JPY"}
            with patch.object(engine,"LAYERS",layer_path),patch.object(engine,"cik_index",return_value={}),\
                 patch.object(engine,"yahoo_data",return_value={"name":"Nabtesco","market":market}),\
                 patch.object(engine,"taiwan_monthly_revenue",return_value={}),\
                 patch.object(engine,"cision_interim_revenue",return_value={}),\
                 patch.object(engine.listing_lineage,"load",return_value={}),\
                 patch.object(engine,"usd_rate",return_value=0.01),\
                 patch.object(engine,"nasdaq_consensus",return_value=None),\
                 patch.object(engine,"outlook",return_value={}), historical_actions():
                built=engine.build(None,NOW,with_news=False)
        self.assertEqual(built["top"][0]["symbol"],sym)
        self.assertEqual(built["top"][0]["layer"],"physical_ai_robotics")
        self.assertEqual(built["industries"][0]["chain_rank"],7)
        self.assertEqual(built["market_window"]["count_used"],1)

    def test_market_window_count_median_positive_share_unknown_and_score_immutable(self):
        fn=engine.market_window_summary
        scored=[{"symbol":"A","score":80,"market":{"ret_6m":0.5}},
                {"symbol":"B","score":70,"market":{"ret_6m":-0.1}},
                {"symbol":"C","score":60,"market":{"ret_6m":0.0}},
                {"symbol":"D","score":50,"market":None},
                {"symbol":"E","score":40,"market":{"ret_6m":float("nan")}}]
        before=[r["score"] for r in scored]
        window=fn(scored)
        self.assertEqual(window,{"positive_share":1/3,"median_ret_6m":0.0,"count_used":3,
                                 "unknown_count":2,"scored_universe_count":5})
        self.assertEqual([r["score"] for r in scored],before)


if __name__=="__main__":
    unittest.main()
