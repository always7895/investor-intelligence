from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location(
    "v213_v212_progress_runner",
    SCRIPTS / "v213_v212_progress_runner.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _forbid_network(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("Network access forbidden during offline test")


def provisional_rows() -> list[dict[str, object]]:
    stamp = "2026-09-02T00:00:00Z"
    rows: list[dict[str, object]] = []
    for index in range(20):
        ticker = f"T{index:02d}"
        score = 20.0 - index * 0.1
        rows.append(
            {
                "ticker": ticker,
                "name": f"Synthetic {ticker}",
                "serenity_score": score,
                "serenity_raw_score": score + 2.0,
                "risk_penalty": 2.0,
                "data_quality": 0.30,
                "rating": "PROVISIONAL",
                "category": "Synthetic",
                "serenity_factors": {
                    "demand_wave": 0.0,
                    "chokepoint": 0.0,
                    "pricing_power": 0.0,
                    "replacement_friction": 0.0,
                    "tam_capture": 6.0,
                    "valuation_expectations": 3.75,
                    "evidence_quality": 4.0,
                },
                "risk_flags": ["single_market_provider_degraded"],
                "aschenbrenner_overlay": {
                    "domain": "C",
                    "fit_score": 20.0,
                    "included_in_serenity_score": False,
                    "attribution": "system_operationalization_not_aschenbrenner_stock_score",
                },
                "evidence": [
                    {
                        "source_id": "sec_edgar",
                        "tier": "T0",
                        "claim_type": "xbrl_fact",
                        "title": f"Synthetic SEC fact {ticker}",
                        "url": f"https://www.sec.gov/Archives/edgar/data/{1000000 + index}/synthetic.htm",
                        "as_of": stamp,
                    }
                ],
                "evidence_count": 1,
                "source_count": 1,
                "scoring_version": MODULE.PROVISIONAL_SCORING_VERSION,
                "line_public_eligible": True,
                "provider_scope": "public_only",
                "owner_watchlist_inherited": False,
                "rank": index + 1,
                "generated_at": stamp,
                "as_of": stamp,
            }
        )
    return rows


def current_provisional_rows() -> list[dict[str, Any]]:
    policy, _activation = MODULE.preselection.validate_v213_policy()
    bundles = MODULE.preselection.engine.synthetic_candidates()[:20]
    stamp = "2026-09-02T00:00:00Z"
    rows: list[dict[str, Any]] = []
    for candidate, metric, evidence in bundles:
        scored = MODULE.preselection.safe_preselection_score(candidate, metric, evidence, policy)
        rows.append(scored)
    rows.sort(
        key=lambda item: (
            -float(item["serenity_score"]),
            -float(item["data_quality"]),
            str(item["ticker"]),
        )
    )
    for index, row in enumerate(rows, 1):
        row["rank"] = index
        row["generated_at"] = stamp
        row["as_of"] = stamp
    return rows


class ProvisionalFiveFieldBridgeTests(unittest.TestCase):
    def test_exact_provisional_rows_are_accepted_only_by_intermediate_bridge(self) -> None:
        rows = provisional_rows()
        accepted = MODULE.validate_provisional_top20(rows)
        self.assertEqual(len(accepted), 20)
        self.assertTrue(
            all(
                row["scoring_version"] == MODULE.PROVISIONAL_SCORING_VERSION
                for row in accepted
            )
        )

        with self.assertRaises(MODULE.report.snapshot.SnapshotError):
            MODULE.report.snapshot.validate_top20(rows)

    def test_provisional_factor_proxy_cannot_bypass_zero_guard(self) -> None:
        rows = provisional_rows()
        factors = rows[0]["serenity_factors"]
        assert isinstance(factors, dict)
        factors["chokepoint"] = 1.0
        with self.assertRaises(MODULE.report.Top20ReportError):
            MODULE.validate_provisional_top20(rows)

    def test_diversified_version_is_not_misread_as_provisional_input(self) -> None:
        rows = provisional_rows()
        rows[0]["scoring_version"] = "system-operationalization-v2.1.3-diversified"
        with self.assertRaises(MODULE.report.Top20ReportError):
            MODULE.validate_provisional_top20(rows)

    def test_actual_current_safe_preselection_produces_accepted_intermediate_in_temp_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with patch.object(requests.Session, "request", side_effect=_forbid_network) as mock_req, \
                 patch.object(urllib.request, "urlopen", side_effect=_forbid_network) as mock_url:
                rows = current_provisional_rows()
                self.assertEqual(len(rows), 20)
                for row in rows:
                    overlay = row["aschenbrenner_overlay"]
                    self.assertEqual(set(overlay), MODULE.CURRENT_OVERLAY_KEYS)
                    self.assertEqual(overlay["status"], "DISCOVERY_ONLY")
                    self.assertIs(overlay["company_fact_authority"], False)
                    self.assertIs(overlay["current_holdings_verified"], False)
                    self.assertIsNone(overlay["thesis_published_at"])
                    self.assertEqual(overlay["scenario_adjustment"], "UNAVAILABLE")
                    self.assertIs(overlay["included_in_serenity_score"], False)
                    self.assertEqual(
                        overlay["attribution"],
                        "system_operationalization_not_aschenbrenner_stock_score",
                    )

                temp_file = temp_path / "top20_intermediate.json"
                temp_file.write_text(json.dumps(rows, indent=2), encoding="utf-8")
                loaded = json.loads(temp_file.read_text(encoding="utf-8"))

                accepted = MODULE.validate_provisional_top20(loaded)
                self.assertEqual(len(accepted), 20)

                for row in accepted:
                    self.assertEqual(set(row["aschenbrenner_overlay"]), MODULE.CURRENT_OVERLAY_KEYS)
                    self.assertEqual(row["rating"], "PROVISIONAL")
                    self.assertEqual(row["scoring_version"], MODULE.PROVISIONAL_SCORING_VERSION)

                with self.assertRaises(MODULE.report.snapshot.SnapshotError):
                    MODULE.report.snapshot.validate_top20(accepted)

                mock_req.assert_not_called()
                mock_url.assert_not_called()

    def test_current_overlay_rejected_when_status_altered(self) -> None:
        for bad_status in ("PROMOTED", "ACTIVE", "discovery_only", None, "", 123):
            with self.subTest(bad_status=bad_status):
                rows = copy.deepcopy(current_provisional_rows())
                rows[0]["aschenbrenner_overlay"]["status"] = bad_status
                with self.assertRaises(MODULE.report.Top20ReportError):
                    MODULE.validate_provisional_top20(rows)

    def test_current_overlay_rejected_when_company_fact_authority_altered(self) -> None:
        for bad_authority in (True, 0, None, "False", 1):
            with self.subTest(bad_authority=bad_authority):
                rows = copy.deepcopy(current_provisional_rows())
                rows[0]["aschenbrenner_overlay"]["company_fact_authority"] = bad_authority
                with self.assertRaises(MODULE.report.Top20ReportError):
                    MODULE.validate_provisional_top20(rows)

    def test_current_overlay_rejected_when_current_holdings_verified_altered(self) -> None:
        for bad_verified in (True, 0, None, "False", 1):
            with self.subTest(bad_verified=bad_verified):
                rows = copy.deepcopy(current_provisional_rows())
                rows[0]["aschenbrenner_overlay"]["current_holdings_verified"] = bad_verified
                with self.assertRaises(MODULE.report.Top20ReportError):
                    MODULE.validate_provisional_top20(rows)

    def test_current_overlay_rejected_when_thesis_published_at_altered(self) -> None:
        for bad_thesis in ("2026-09-02T00:00:00Z", "", False, 0):
            with self.subTest(bad_thesis=bad_thesis):
                rows = copy.deepcopy(current_provisional_rows())
                rows[0]["aschenbrenner_overlay"]["thesis_published_at"] = bad_thesis
                with self.assertRaises(MODULE.report.Top20ReportError):
                    MODULE.validate_provisional_top20(rows)

    def test_current_overlay_rejected_when_scenario_adjustment_altered(self) -> None:
        for bad_scenario in ("AVAILABLE", "APPLIED", "unavailable", None, "", 123):
            with self.subTest(bad_scenario=bad_scenario):
                rows = copy.deepcopy(current_provisional_rows())
                rows[0]["aschenbrenner_overlay"]["scenario_adjustment"] = bad_scenario
                with self.assertRaises(MODULE.report.Top20ReportError):
                    MODULE.validate_provisional_top20(rows)

    def test_overlay_rejected_when_included_in_serenity_score_true_or_non_bool(self) -> None:
        for builder in (provisional_rows, current_provisional_rows):
            for bad_included in (True, 1, 0, None, "False"):
                with self.subTest(builder=builder.__name__, bad_included=bad_included):
                    rows = copy.deepcopy(builder())
                    rows[0]["aschenbrenner_overlay"]["included_in_serenity_score"] = bad_included
                    with self.assertRaises(MODULE.report.Top20ReportError):
                        MODULE.validate_provisional_top20(rows)

    def test_overlay_rejected_when_wrong_attribution(self) -> None:
        for builder in (provisional_rows, current_provisional_rows):
            for bad_attr in (
                "system_operationalization_aschenbrenner_stock_score",
                "aschenbrenner_stock_score",
                "",
                None,
                123,
            ):
                with self.subTest(builder=builder.__name__, bad_attr=bad_attr):
                    rows = copy.deepcopy(builder())
                    rows[0]["aschenbrenner_overlay"]["attribution"] = bad_attr
                    with self.assertRaises(MODULE.report.Top20ReportError):
                        MODULE.validate_provisional_top20(rows)

    def test_overlay_rejected_on_partial_extensions_extra_keys_and_unknown_keys(self) -> None:
        rows_9 = copy.deepcopy(current_provisional_rows())
        rows_9[0]["aschenbrenner_overlay"]["extra_key"] = "unauthorized"
        with self.assertRaises(MODULE.report.Top20ReportError):
            MODULE.validate_provisional_top20(rows_9)

        rows_4 = copy.deepcopy(provisional_rows())
        rows_4[0]["aschenbrenner_overlay"]["extra_key"] = "unauthorized"
        with self.assertRaises(MODULE.report.Top20ReportError):
            MODULE.validate_provisional_top20(rows_4)

        rows_partial5 = copy.deepcopy(provisional_rows())
        rows_partial5[0]["aschenbrenner_overlay"]["status"] = "DISCOVERY_ONLY"
        with self.assertRaises(MODULE.report.Top20ReportError):
            MODULE.validate_provisional_top20(rows_partial5)

        rows_partial6 = copy.deepcopy(provisional_rows())
        rows_partial6[0]["aschenbrenner_overlay"]["status"] = "DISCOVERY_ONLY"
        rows_partial6[0]["aschenbrenner_overlay"]["company_fact_authority"] = False
        with self.assertRaises(MODULE.report.Top20ReportError):
            MODULE.validate_provisional_top20(rows_partial6)

        rows_partial8 = copy.deepcopy(current_provisional_rows())
        del rows_partial8[0]["aschenbrenner_overlay"]["scenario_adjustment"]
        with self.assertRaises(MODULE.report.Top20ReportError):
            MODULE.validate_provisional_top20(rows_partial8)

        rows_partial3 = copy.deepcopy(provisional_rows())
        del rows_partial3[0]["aschenbrenner_overlay"]["domain"]
        with self.assertRaises(MODULE.report.Top20ReportError):
            MODULE.validate_provisional_top20(rows_partial3)

        rows_unknown9 = copy.deepcopy(current_provisional_rows())
        del rows_unknown9[0]["aschenbrenner_overlay"]["status"]
        rows_unknown9[0]["aschenbrenner_overlay"]["state"] = "DISCOVERY_ONLY"
        with self.assertRaises(MODULE.report.Top20ReportError):
            MODULE.validate_provisional_top20(rows_unknown9)

        rows_unknown4 = copy.deepcopy(provisional_rows())
        del rows_unknown4[0]["aschenbrenner_overlay"]["domain"]
        rows_unknown4[0]["aschenbrenner_overlay"]["sector"] = "C"
        with self.assertRaises(MODULE.report.Top20ReportError):
            MODULE.validate_provisional_top20(rows_unknown4)

    def test_validate_provisional_top20_preserves_input_immutability(self) -> None:
        for builder in (provisional_rows, current_provisional_rows):
            rows = builder()
            serialized_before = json.dumps(rows, sort_keys=True)
            accepted = MODULE.validate_provisional_top20(rows)
            serialized_after = json.dumps(rows, sort_keys=True)
            self.assertEqual(serialized_before, serialized_after)
            self.assertEqual(len(accepted), 20)


if __name__ == "__main__":
    unittest.main()
