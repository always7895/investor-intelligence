"""GAP-R2 F1-F6 offline cross-boundary regression: host capture, Worker shape, publisher projection."""
from __future__ import annotations

import copy
import json
import re
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import corporate_actions as actions
import bottleneck_top20_v3 as ranking
import publish_sealed_snapshot as publisher
import revenue_guidance_host as host
import revenue_guidance_provisioner as provisioner
import build_line_public_options as base
import build_v211_public_options as versioned
from tests import test_batch08c_ranking as fixture
from tests.test_bottleneck_top20_v3 import historical_actions

ACTION_BYTES = (ROOT / "config/corporate-actions-v1.json").read_bytes()
LAYERS = json.loads((ROOT / "config/bottleneck-layers-v3.json").read_text(encoding="utf-8"))


def projection():
    roles, translations = publisher._layer_translations(ROOT / "config/bottleneck-layers-v3.json")
    industries = [
        {"rank": i + 1, "id": layer["id"], "name_zh": layer["name_zh"],
         "chain": layer["chain"], "leopold_constraint": layer["leopold_constraint"],
         "leopold_constraint_zh": layer["leopold_constraint_zh"],
         "explosiveness": 0.5, "median_revenue_yoy": None,
         "median_acceleration": None, "median_return_6m": None,
         "fund_13f_weight": 0, "serenity_heat": 0, "news": None}
        for i, layer in enumerate(LAYERS["layers"])
    ]
    projected = publisher._public_industry_rows(industries, translations)
    summary = ranking.market_window_summary([
        {"market": {"ret_6m": 0.4}}, {"market": {"ret_6m": -0.1}},
        {"market": None},
    ])
    return {"industries": projected, "market_window": publisher._public_market_window(summary)}


class ProtectedHostAndCaptureTests(unittest.TestCase):
    def test_package_lists_and_captured_catalog_cover_same_registry(self):
        required = {"scripts/corporate_actions.py", "config/corporate-actions-v1.json"}
        self.assertTrue(required <= provisioner.REQUIRED_FILES)
        self.assertTrue(required <= provisioner.HOST_REQUIRED_FILES)
        self.assertEqual(host.CONFIG_FILES["corporate_actions"], "corporate-actions-v1.json")
        installer = (ROOT / "scripts/install_revenue_guidance_protected.ps1").read_text(encoding="utf-8")
        self.assertTrue(all(f"'{name}'" in installer for name in required))
        files = {"config/" + relative: b"{}" for relative in host.CONFIG_FILES.values()}
        files["config/corporate-actions-v1.json"] = ACTION_BYTES
        self.assertEqual(actions.load_actions_bytes(files["config/corporate-actions-v1.json"],
                                                    today=date(2026, 11, 7))["entries"][0]["target_symbol"], "LITE")

    def test_captured_ranking_consumes_protected_bytes_not_installed_path(self):
        capture = fixture.captured()
        captured_keys = {key for key, _ in capture._entries}
        self.assertTrue({"corporate_actions", "open_candidates", "reviewed_events"} <= captured_keys)
        self.assertEqual(actions.load_actions_bytes(capture.operand("corporate_actions").read_bytes(),
                                                   today=fixture.NOW.date())["entries"], [])
        for name in ("open_candidates", "reviewed_events"):
            self.assertEqual(json.loads(capture.operand(name).read_text()), [])
        with patch.object(actions, "load_actions", side_effect=AssertionError("installed file accessed")):
            built = fixture.rank(capture)
            self.assertTrue(built["top"])
        entries = {key: value.read_bytes() if value.exists() else None for key, value in capture._entries}
        for value in (b"{}", b'{"schema_version":1,"entries":[],"entries":[]}', ACTION_BYTES):
            with self.subTest(value=value):
                entries["corporate_actions"] = value
                with self.assertRaises(ValueError):
                    fixture.rank(publisher.CapturedPublicationInputs(entries))
        del entries["corporate_actions"]
        with self.assertRaisesRegex(ValueError, "CAPTURED_INPUT_NOT_SELECTED"):
            fixture.rank(publisher.CapturedPublicationInputs(entries))

    def test_captured_publisher_uses_same_bytes_loader_not_installation(self):
        raw = json.dumps({
            "schema": "v213-bottleneck-top20-v3",
            "generated_at": "2026-11-07T12:00:00Z", "top": [], "industries": [],
        }).encode("utf-8")
        capture = publisher.CapturedPublicationInputs({
            "layers": (ROOT / "config/bottleneck-layers-v3.json").read_bytes(),
            "corporate_actions": ACTION_BYTES,
        })
        now = datetime(2026, 11, 7, 12, 1, tzinfo=timezone.utc)
        with (patch.object(actions, "load_actions", side_effect=AssertionError("installed file accessed")),
              patch.object(actions, "load_actions_bytes", wraps=actions.load_actions_bytes) as loader):
            # Too-short top is intentionally not sealable; test the exact bound loader reached.
            self.assertEqual(publisher.captured_bottleneck_v3_body(raw, now, captured=capture), {})
            loader.assert_called_once_with(ACTION_BYTES, today=date(2026, 11, 7))


class CorporateActionSchemaTests(unittest.TestCase):
    def test_historical_installed_registry_keeps_future_sources_fail_closed(self):
        cutoff = fixture.NOW.date()
        with historical_actions() as path:
            self.assertEqual(actions.load_actions(today=cutoff),
                             actions.load_actions_bytes(fixture.old.HISTORICAL_ACTION_BYTES, today=cutoff))
            # The current real registry is not valid September evidence, through either path adapter.
            path.write_bytes(ACTION_BYTES)
            for selected in (None, path):
                with self.subTest(default_path=selected is None):
                    with self.assertRaisesRegex(ValueError, "CORPORATE_ACTION_CHRONOLOGY"):
                        actions.load_actions(selected, today=cutoff)

    def test_sec_archives_only_rejects_issuer_ir_and_other_sec_urls(self):
        obj = json.loads(ACTION_BYTES)
        for url in (
            "https://ir.lumentum.com/news-releases/example",
            "https://data.sec.gov/submissions/CIK0001633978.json",
            "https://www.sec.gov/other/archive.htm",
            "https://www.sec.gov.evil.example/Archives/edgar/data/123/a",
            "http://www.sec.gov/Archives/edgar/data/123/a",
        ):
            with self.subTest(url=url):
                obj["entries"][0]["source_url"] = url
                with self.assertRaisesRegex(ValueError, "CORPORATE_ACTION_SOURCE"):
                    actions.load_actions_bytes(json.dumps(obj).encode(), today=date(2026, 11, 7))
        self.assertEqual(actions.load_actions_bytes(ACTION_BYTES, today=date(2026, 11, 7))["entries"][0]["flags"], [])

    def test_lite_review_deadline_and_robotics_constraints(self):
        row = actions.load_actions_bytes(ACTION_BYTES, today=date(2026, 11, 7))["entries"][0]
        self.assertEqual(row["review_by"], "2026-12-07")
        self.assertEqual(actions.load_actions_bytes(ACTION_BYTES, today=date(2026, 12, 8))["entries"][0]["flags"],
                         ["REVIEW_OVERDUE"])
        robotics = next(item for item in LAYERS["layers"] if item["id"] == "physical_ai_robotics")
        self.assertEqual(len(LAYERS["layers"]), 13)
        self.assertLessEqual(len(robotics["leopold_constraint"]), 120)
        self.assertLessEqual(len(robotics["leopold_constraint_zh"]), 50)
        self.assertIn("Outside Leopold", robotics["leopold_constraint"])
        self.assertIn("瓶頸待驗證", robotics["leopold_constraint_zh"])

    def test_pending_failure_records_equal_real_worker_option_keys(self):
        item = {"ticker": "LITE", "market_data_ticker": "LITE", "currency": "USD"}
        worker = (ROOT / "cloud/src/v211/admin.ts").read_text(encoding="utf-8")
        block = worker.split("const OPTION_KEYS = new Set([", 1)[1].split("]);", 1)[0]
        keys = set(re.findall(r'"([^"]+)"', block))
        self.assertEqual(len(keys), 17)
        for record in (base.failure_record(item, "DEAL_PENDING_TARGET"),
                       versioned.failure_record(item, "DEAL_PENDING_TARGET")):
            self.assertEqual(set(record), keys)
            self.assertIsNone(record["current_price"])
            self.assertTrue(record["line_public_eligible"])
            self.assertEqual(record["status"], "DEAL_PENDING_TARGET")
            self.assertEqual(record["periods"], {})
            self.assertNotIn("withheld_reason", record)


class PublishedIndustryShapeTests(unittest.TestCase):
    def test_publisher_projects_13_layers_worker_budgets_and_window(self):
        result = projection()
        expected = {"rank", "id", "name_zh", "chain", "leopold_constraint",
                    "leopold_constraint_zh", "explosiveness", "median_revenue_yoy",
                    "median_acceleration", "median_return_6m", "fund_13f_weight",
                    "serenity_heat", "news"}
        self.assertEqual(len(result["industries"]), 13)
        for index, row in enumerate(result["industries"], start=1):
            self.assertEqual(set(row), expected)
            self.assertEqual(row["rank"], index)
            self.assertLessEqual(len(row["id"]), 40)
            self.assertLessEqual(len(row["name_zh"]), 40)
            self.assertLessEqual(len(row["chain"]), 30)
            self.assertLessEqual(len(row["leopold_constraint"]), 300)
            self.assertLessEqual(len(row["leopold_constraint_zh"]), 300)
        robot = next(row for row in result["industries"] if row["id"] == "physical_ai_robotics")
        self.assertLessEqual(len(robot["leopold_constraint"]), 120)
        self.assertLessEqual(len(robot["leopold_constraint_zh"]), 50)
        self.assertEqual(result["market_window"],
                         {"positive_share": 0.5, "median_ret_6m": 0.15000000000000002,
                          "count_used": 2, "unknown_count": 1, "scored_universe_count": 3})
        self.assertIsNone(publisher._public_market_window({"positive_share": 0.5}))


if __name__ == "__main__":
    unittest.main()
