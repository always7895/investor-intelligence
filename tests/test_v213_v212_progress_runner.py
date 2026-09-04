from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
