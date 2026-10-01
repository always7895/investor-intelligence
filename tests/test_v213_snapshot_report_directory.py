from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location(
    "v213_build_v21_public_snapshot",
    SCRIPTS / "v213_build_v21_public_snapshot.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

SYNTHETIC_TICKERS = [f"SYNTH{i:02d}" for i in range(20)]
SYNTHETIC_MARKDOWN_REPORT = "# Synthetic Public Briefing Report\n\n- Ticker: SYNTH00\n"


def _forbid_network(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("Network access forbidden during offline test")


def _synthetic_top20_rows() -> list[dict[str, Any]]:
    stamp = "2026-09-02T00:00:00Z"
    rows: list[dict[str, Any]] = []
    for index, ticker in enumerate(SYNTHETIC_TICKERS):
        score = 80.0 - float(index)
        rows.append(
            {
                "ticker": ticker,
                "name": f"Synthetic Company {ticker}",
                "serenity_score": score,
                "serenity_raw_score": score + 2.0,
                "risk_penalty": 2.0,
                "data_quality": 0.85,
                "rating": "A" if score >= 55 else "B",
                "category": "Synthetic",
                "serenity_factors": {
                    "demand_wave": 0.0,
                    "chokepoint": 0.0,
                    "pricing_power": 0.0,
                    "replacement_friction": 0.0,
                    # SYNTH00 has fresh claim support in audit -> retained.
                    # SYNTH01 has positive factor without fresh claim support -> withheld by _guard_row.
                    # Others have 0.0 -> unaffected.
                    "tam_capture": 6.0 if index < 2 else 0.0,
                    "valuation_expectations": 3.0,
                    "evidence_quality": 3.0,
                },
                "risk_flags": [],
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
                        "title": f"Synthetic fact 1 {ticker}",
                        "url": f"https://www.sec.gov/{ticker}/1",
                        "as_of": stamp,
                    },
                    {
                        "source_id": "nasdaq",
                        "tier": "T1",
                        "claim_type": "press_release",
                        "title": f"Synthetic fact 2 {ticker}",
                        "url": f"https://nasdaq.com/{ticker}/2",
                        "as_of": stamp,
                    },
                ],
                "evidence_count": 2,
                "source_count": 2,
                "scoring_version": MODULE.SCORING_VERSION,
                "line_public_eligible": True,
                "provider_scope": "public_only",
                "owner_watchlist_inherited": False,
                "rank": index + 1,
                "generated_at": stamp,
                "as_of": stamp,
            }
        )
    return rows


def _synthetic_source_audit() -> dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()
    synth00_sources = [
        {
            "family": "regulator_filing",
            "domain": "sec.gov",
            "claim_type": "xbrl_fact",
            "url": "https://www.sec.gov/synth00",
            "as_of": now_iso,
            "primary": True,
        },
        {
            "family": "independent_audit",
            "domain": "auditor.example",
            "claim_type": "financial_audit",
            "url": "https://auditor.example/synth00",
            "as_of": now_iso,
            "primary": False,
        },
    ]
    records = []
    for index, ticker in enumerate(SYNTHETIC_TICKERS):
        sources = synth00_sources if index == 0 else []
        records.append({
            "ticker": ticker,
            "rank": index + 1,
            "sources": sources,
        })
    return {"records": records}


def _synthetic_freshness_policy() -> dict[str, Any]:
    return {
        "current_state_claim_max_age_days": 135.0,
        "sensitive_advantage_factors": [
            "demand_wave",
            "chokepoint",
            "pricing_power",
            "replacement_friction",
            "tam_capture",
        ],
    }


def _synthetic_federation() -> dict[str, Any]:
    return {
        "ticker_sources": [
            {"ticker": ticker, "rank": index + 1, "synthetic_notes": "ok"}
            for index, ticker in enumerate(SYNTHETIC_TICKERS)
        ]
    }


def _synthetic_v212() -> dict[str, Any]:
    return {
        "records": [
            {"ticker": ticker, "rank": index + 1, "synthetic_version": "2.1.2"}
            for index, ticker in enumerate(SYNTHETIC_TICKERS)
        ]
    }


def _synthetic_v213() -> dict[str, Any]:
    return {
        "records": [
            {"ticker": ticker, "rank": index + 1, "synthetic_version": "2.1.3"}
            for index, ticker in enumerate(SYNTHETIC_TICKERS)
        ]
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


class SnapshotReportDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.req_patcher = patch.object(requests.Session, "request", side_effect=_forbid_network)
        self.url_patcher = patch.object(urllib.request, "urlopen", side_effect=_forbid_network)
        self.mock_req = self.req_patcher.start()
        self.mock_url = self.url_patcher.start()

    def tearDown(self) -> None:
        self.url_patcher.stop()
        self.req_patcher.stop()

    def _setup_test_files(
        self,
        temp_path: Path,
        top20: Any | None = None,
        audit: Any | None = None,
        policy: Any | None = None,
        federation: Any | None = None,
        v212: Any | None = None,
        v213: Any | None = None,
    ) -> tuple[Path, Path, Path, Path, Path, Path]:
        top20_path = temp_path / "top20.json"
        audit_path = temp_path / "source_audit.json"
        policy_path = temp_path / "freshness_policy.json"
        federation_path = temp_path / "federation.json"
        v212_path = temp_path / "v212.json"
        v213_path = temp_path / "v213.json"

        _write_json(top20_path, _synthetic_top20_rows() if top20 is None else top20)
        _write_json(audit_path, _synthetic_source_audit() if audit is None else audit)
        _write_json(policy_path, _synthetic_freshness_policy() if policy is None else policy)
        _write_json(federation_path, _synthetic_federation() if federation is None else federation)
        _write_json(v212_path, _synthetic_v212() if v212 is None else v212)
        _write_json(v213_path, _synthetic_v213() if v213 is None else v213)

        return top20_path, audit_path, policy_path, federation_path, v212_path, v213_path

    def test_missing_nested_report_parent_created_and_report_written(self) -> None:
        """Prove missing nested report parent directory is created and markdown report is written.

        Scope: Caller directory creation and evidence guard execution, not full renderer acceptance.
        The renderer (scorer.markdown_report) is patched to a fixed synthetic string because the
        minimal fixture lacks unrelated report rendering fields.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            top20_p, audit_p, policy_p, fed_p, v212_p, v213_p = self._setup_test_files(temp_path)
            report_path = temp_path / "nested" / "briefings" / "public_briefing_latest.md"

            self.assertFalse(report_path.parent.exists())

            with patch.object(MODULE.base, "TOP20_PATH", top20_p), \
                 patch.object(MODULE, "SOURCE_AUDIT_PATH", audit_p), \
                 patch.object(MODULE, "FRESHNESS_POLICY_PATH", policy_p), \
                 patch.object(MODULE, "FEDERATION_PATH", fed_p), \
                 patch.object(MODULE, "V212_PATH", v212_p), \
                 patch.object(MODULE, "V213_PATH", v213_p), \
                 patch.object(MODULE.base, "REPORT_PATH", report_path), \
                 patch.object(MODULE.scorer, "markdown_report", return_value=SYNTHETIC_MARKDOWN_REPORT):

                result = MODULE.apply_latest_evidence_factor_guard()

            # Prove missing nested directory was created and report written
            self.assertTrue(report_path.parent.is_dir())
            self.assertTrue(report_path.is_file())
            self.assertEqual(
                report_path.read_text(encoding="utf-8"),
                SYNTHETIC_MARKDOWN_REPORT + "\n",
            )

            # Prove actual _guard_row ran: SYNTH01 lacked multi-source claim support and was withheld
            self.assertEqual(result["withheld_ticker_count"], 1)
            self.assertIn("SYNTH01", result["withheld"])
            self.assertEqual(result["withheld"]["SYNTH01"], ["tam_capture"])

            # Verify persisted top20 reflected the guard decision
            guarded_top20 = json.loads(top20_p.read_text(encoding="utf-8"))
            synth00_row = next(r for r in guarded_top20 if r["ticker"] == "SYNTH00")
            synth01_row = next(r for r in guarded_top20 if r["ticker"] == "SYNTH01")
            self.assertEqual(synth00_row["serenity_factors"]["tam_capture"], 6.0)
            self.assertEqual(synth01_row["serenity_factors"]["tam_capture"], 0.0)
            self.assertIn(
                "positive_advantage_withheld_until_fresh_multisource_support",
                synth01_row["risk_flags"],
            )

            # Prove reorder validators ran and assigned ranks
            self.assertEqual(len(result["final_order"]), 20)
            for doc_path, key in [
                (top20_p, None),
                (v212_p, "records"),
                (v213_p, "records"),
                (fed_p, "ticker_sources"),
                (audit_p, "records"),
            ]:
                doc = json.loads(doc_path.read_text(encoding="utf-8"))
                records = doc if key is None else doc[key]
                self.assertEqual(len(records), 20)
                self.assertEqual([r["rank"] for r in records], list(range(1, 21)))

            self.mock_req.assert_not_called()
            self.mock_url.assert_not_called()

    def test_existing_report_parent_directory_preserved(self) -> None:
        """Prove an existing parent directory and its existing contents are preserved."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            top20_p, audit_p, policy_p, fed_p, v212_p, v213_p = self._setup_test_files(temp_path)
            report_dir = temp_path / "existing_reports"
            report_dir.mkdir(parents=True, exist_ok=True)
            sibling_file = report_dir / "pre_existing_note.txt"
            sibling_file.write_text("prior report archive note", encoding="utf-8")
            report_path = report_dir / "public_briefing_latest.md"

            with patch.object(MODULE.base, "TOP20_PATH", top20_p), \
                 patch.object(MODULE, "SOURCE_AUDIT_PATH", audit_p), \
                 patch.object(MODULE, "FRESHNESS_POLICY_PATH", policy_p), \
                 patch.object(MODULE, "FEDERATION_PATH", fed_p), \
                 patch.object(MODULE, "V212_PATH", v212_p), \
                 patch.object(MODULE, "V213_PATH", v213_p), \
                 patch.object(MODULE.base, "REPORT_PATH", report_path), \
                 patch.object(MODULE.scorer, "markdown_report", return_value=SYNTHETIC_MARKDOWN_REPORT):

                result = MODULE.apply_latest_evidence_factor_guard()

            self.assertTrue(report_dir.is_dir())
            self.assertTrue(sibling_file.is_file())
            self.assertEqual(sibling_file.read_text(encoding="utf-8"), "prior report archive note")
            self.assertTrue(report_path.is_file())
            self.assertEqual(
                report_path.read_text(encoding="utf-8"),
                SYNTHETIC_MARKDOWN_REPORT + "\n",
            )
            self.assertEqual(result["withheld_ticker_count"], 1)

            self.mock_req.assert_not_called()
            self.mock_url.assert_not_called()

    def test_parent_file_collision_fails_and_preserves_exception(self) -> None:
        """Prove that if the report parent path is an existing regular file, mkdir raises OSError without swallowing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            top20_p, audit_p, policy_p, fed_p, v212_p, v213_p = self._setup_test_files(temp_path)
            colliding_parent = temp_path / "colliding_parent_file"
            colliding_parent.write_text("i am a regular file, not a folder", encoding="utf-8")
            report_path = colliding_parent / "public_briefing_latest.md"

            with patch.object(MODULE.base, "TOP20_PATH", top20_p), \
                 patch.object(MODULE, "SOURCE_AUDIT_PATH", audit_p), \
                 patch.object(MODULE, "FRESHNESS_POLICY_PATH", policy_p), \
                 patch.object(MODULE, "FEDERATION_PATH", fed_p), \
                 patch.object(MODULE, "V212_PATH", v212_p), \
                 patch.object(MODULE, "V213_PATH", v213_p), \
                 patch.object(MODULE.base, "REPORT_PATH", report_path), \
                 patch.object(MODULE.scorer, "markdown_report", return_value=SYNTHETIC_MARKDOWN_REPORT):

                with self.assertRaises(OSError) as ctx:
                    MODULE.apply_latest_evidence_factor_guard()

            self.assertIsInstance(ctx.exception, (FileExistsError, NotADirectoryError, OSError))
            # Prove colliding regular file was not modified or removed
            self.assertTrue(colliding_parent.is_file())
            self.assertEqual(colliding_parent.read_text(encoding="utf-8"), "i am a regular file, not a folder")

            self.mock_req.assert_not_called()
            self.mock_url.assert_not_called()

    def test_malformed_top20_count_fails_before_report_parent_creation(self) -> None:
        """Prove that malformed Top20 input fails before report parent creation and is not publication-qualified."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            # Only 19 records instead of 20
            bad_top20 = _synthetic_top20_rows()[:19]
            top20_p, audit_p, policy_p, fed_p, v212_p, v213_p = self._setup_test_files(
                temp_path, top20=bad_top20
            )
            report_parent = temp_path / "uncreated_parent_bad_count"
            report_path = report_parent / "public_briefing_latest.md"

            with patch.object(MODULE.base, "TOP20_PATH", top20_p), \
                 patch.object(MODULE, "SOURCE_AUDIT_PATH", audit_p), \
                 patch.object(MODULE, "FRESHNESS_POLICY_PATH", policy_p), \
                 patch.object(MODULE, "FEDERATION_PATH", fed_p), \
                 patch.object(MODULE, "V212_PATH", v212_p), \
                 patch.object(MODULE, "V213_PATH", v213_p), \
                 patch.object(MODULE.base, "REPORT_PATH", report_path), \
                 patch.object(MODULE.scorer, "markdown_report", return_value=SYNTHETIC_MARKDOWN_REPORT):

                with self.assertRaises(MODULE.base.SnapshotError) as ctx:
                    MODULE.apply_latest_evidence_factor_guard()

            self.assertIn("requires exactly 20 Top20 rows", str(ctx.exception))
            self.assertFalse(report_parent.exists())
            self.assertFalse(report_path.exists())

            self.mock_req.assert_not_called()
            self.mock_url.assert_not_called()

    def test_malformed_audit_missing_ticker_fails_before_report_parent_creation(self) -> None:
        """Prove that missing source-audit rows fail before report parent creation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bad_audit = {"records": _synthetic_source_audit()["records"][:19]}
            top20_p, audit_p, policy_p, fed_p, v212_p, v213_p = self._setup_test_files(
                temp_path, audit=bad_audit
            )
            report_parent = temp_path / "uncreated_parent_missing_audit"
            report_path = report_parent / "public_briefing_latest.md"

            with patch.object(MODULE.base, "TOP20_PATH", top20_p), \
                 patch.object(MODULE, "SOURCE_AUDIT_PATH", audit_p), \
                 patch.object(MODULE, "FRESHNESS_POLICY_PATH", policy_p), \
                 patch.object(MODULE, "FEDERATION_PATH", fed_p), \
                 patch.object(MODULE, "V212_PATH", v212_p), \
                 patch.object(MODULE, "V213_PATH", v213_p), \
                 patch.object(MODULE.base, "REPORT_PATH", report_path), \
                 patch.object(MODULE.scorer, "markdown_report", return_value=SYNTHETIC_MARKDOWN_REPORT):

                with self.assertRaises(MODULE.base.SnapshotError) as ctx:
                    MODULE.apply_latest_evidence_factor_guard()

            self.assertIn("requires exactly 20 source-audit rows", str(ctx.exception))
            self.assertFalse(report_parent.exists())
            self.assertFalse(report_path.exists())

            self.mock_req.assert_not_called()
            self.mock_url.assert_not_called()

    def test_malformed_rank_coupled_membership_fails_before_report_parent_creation(self) -> None:
        """Prove that mismatched membership in rank-coupled records fails before report parent creation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bad_v212 = _synthetic_v212()
            bad_v212["records"][0]["ticker"] = "SYNTH_EXTRA"
            top20_p, audit_p, policy_p, fed_p, v212_p, v213_p = self._setup_test_files(
                temp_path, v212=bad_v212
            )
            report_parent = temp_path / "uncreated_parent_bad_v212"
            report_path = report_parent / "public_briefing_latest.md"

            with patch.object(MODULE.base, "TOP20_PATH", top20_p), \
                 patch.object(MODULE, "SOURCE_AUDIT_PATH", audit_p), \
                 patch.object(MODULE, "FRESHNESS_POLICY_PATH", policy_p), \
                 patch.object(MODULE, "FEDERATION_PATH", fed_p), \
                 patch.object(MODULE, "V212_PATH", v212_p), \
                 patch.object(MODULE, "V213_PATH", v213_p), \
                 patch.object(MODULE.base, "REPORT_PATH", report_path), \
                 patch.object(MODULE.scorer, "markdown_report", return_value=SYNTHETIC_MARKDOWN_REPORT):

                with self.assertRaises(MODULE.base.SnapshotError) as ctx:
                    MODULE.apply_latest_evidence_factor_guard()

            self.assertIn("membership does not match guarded Top20", str(ctx.exception))
            self.assertFalse(report_parent.exists())
            self.assertFalse(report_path.exists())

            self.mock_req.assert_not_called()
            self.mock_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
