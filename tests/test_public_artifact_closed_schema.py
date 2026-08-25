from __future__ import annotations

import math
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_to_kv as sync_module  # noqa: E402


def option_fixture() -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "schema_version": 1,
            "ticker": "TEST",
            "status": "OK",
            "quote_source": "yfinance",
            "retrieved_at": now,
            "provider_scope": "public_only",
            "line_public_eligible": True,
            "ibkr_connected": False,
            "brokerage_data_included": False,
            "account_data_included": False,
            "position_data_included": False,
            "owner_watchlist_inherited": False,
            "periods": {
                "weekly": {
                    "status": "OK",
                    "expiration": "2026-08-28",
                    "actual_dte": 4,
                    "call_observations": {
                        "status": "OK",
                        "recommended_candidates": [
                            {
                                "strike": 120,
                                "bid": 4.0,
                                "ask": 4.2,
                                "quote_source": "yfinance",
                                "retrieved_at": now,
                                "liquidity_pass": True,
                            }
                        ],
                    },
                    "put_observations": {
                        "status": "NO_ELIGIBLE_LIQUID_QUOTE",
                        "recommended_candidates": [],
                    },
                }
            },
        }
    ]


class ClosedPublicArtifactSchemaTests(unittest.TestCase):
    def test_rejects_unknown_fields_at_every_option_level(self) -> None:
        mutations = {
            "record": lambda value: value[0].update(owner_research_note="private"),
            "period": lambda value: value[0]["periods"]["weekly"].update(
                private_strategy_label="private"
            ),
            "group": lambda value: value[0]["periods"]["weekly"][
                "call_observations"
            ].update(unexpected_nested=1),
            "candidate": lambda value: value[0]["periods"]["weekly"][
                "call_observations"
            ]["recommended_candidates"][0].update(**{"account-info": "private"}),
            "triplet": lambda value: value[0]["periods"]["weekly"][
                "call_observations"
            ]["recommended_candidates"][0].update(
                annualized_yield_pct={"bid": 10.0, "owner": 99.0}
            ),
        }
        for label, mutate in mutations.items():
            value = option_fixture()
            mutate(value)
            with self.subTest(level=label), self.assertRaises(ValueError):
                sync_module._validate_public_options(value)

    def test_rejects_unknown_score_source_view_and_metadata_fields(self) -> None:
        score = [
            {
                "schema_version": 1,
                "ticker": "TEST",
                "rank": 1,
                "total_score": 70.0,
                "data_quality": 0.8,
                "line_public_eligible": True,
                "provider_scope": "public_only",
                "owner_watchlist_inherited": False,
                "personal_conviction": 9,
            }
        ]
        with self.assertRaises(ValueError):
            sync_module._validate_public_scores(score)

        source_view = [
            {
                "schema_version": 1,
                "author": "Public Author",
                "summary": "Public observation",
                "url": "https://example.org/source",
                "published_at": "2026-08-23T00:00:00Z",
                "line_public_eligible": True,
                "provider_scope": "public_only",
                "owner_watchlist_inherited": False,
                "owner_selection_reason": "private",
            }
        ]
        with self.assertRaises(ValueError):
            sync_module._validate_public_source_views(source_view)

        metadata = {
            "schema_version": 1,
            "line_public_eligible": True,
            "provider_scope": "public_only",
            "owner_watchlist_inherited": False,
            "last_successful_pipeline_timestamp": datetime.now(timezone.utc).isoformat(),
            "private_pipeline_name": "owner-pipeline",
        }
        with self.assertRaises(ValueError):
            sync_module._validate_public_metadata(metadata)

    def test_rejects_non_finite_numbers_before_serialization(self) -> None:
        value = option_fixture()
        candidate = value[0]["periods"]["weekly"]["call_observations"][
            "recommended_candidates"
        ][0]
        candidate["bid"] = math.nan
        with self.assertRaises(ValueError):
            sync_module._validate_public_options(value)

    def test_current_builder_shape_remains_accepted(self) -> None:
        value = sync_module._validate_public_options(option_fixture())
        self.assertEqual(value[0]["ticker"], "TEST")
        self.assertIn("public_view_notice", value[0])


if __name__ == "__main__":
    unittest.main()
