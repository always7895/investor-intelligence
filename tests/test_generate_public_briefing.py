from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_public_briefing as module  # noqa: E402

NOW = "2026-08-24T12:00:00+00:00"


def metadata_fixture() -> dict:
    return {
        "schema_version": 1,
        "line_public_eligible": True,
        "provider_scope": "public_only",
        "owner_watchlist_inherited": False,
        "last_successful_pipeline_timestamp": NOW,
    }


def scores_fixture() -> list[dict]:
    return [
        {
            "schema_version": 1,
            "ticker": "TEST",
            "name": "Synthetic Public Company",
            "rank": 1,
            "total_score": 75.0,
            "data_quality": 0.8,
            "rating": "RESEARCH",
            "category": "Synthetic",
            "generated_at": NOW,
            "line_public_eligible": True,
            "provider_scope": "public_only",
            "owner_watchlist_inherited": False,
        }
    ]


def options_fixture() -> list[dict]:
    return [
        {
            "schema_version": 1,
            "ticker": "TEST",
            "provider_symbol": "TEST",
            "currency": "USD",
            "current_price": 100.0,
            "retrieved_at": NOW,
            "status": "OK",
            "quote_source": "yfinance",
            "quote_delay_status": "THIRD_PARTY_DELAY_UNKNOWN",
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
                    "target_dte": 7,
                    "expiration": "2026-08-28",
                    "actual_dte": 4,
                    "call_observations": {
                        "status": "OK",
                        "recommended_candidates": [
                            {
                                "ticker": "TEST",
                                "option_type": "call",
                                "contract_symbol": "TEST260828C00110000",
                                "expiration": "2026-08-28",
                                "actual_dte": 4,
                                "strike": 110.0,
                                "spot": 100.0,
                                "distance_from_spot_pct": 10.0,
                                "bid": 1.0,
                                "ask": 1.2,
                                "midpoint": 1.1,
                                "last": 1.05,
                                "spread": 0.2,
                                "spread_pct_of_mid": 18.18,
                                "volume": 10,
                                "open_interest": 100,
                                "implied_volatility_pct": 50.0,
                                "delta": None,
                                "delta_status": "NOT_SUPPLIED_BY_YFINANCE",
                                "last_trade_at": "2026-08-24T11:00:00+00:00",
                                "last_trade_age_days": 0.04,
                                "retrieved_at": NOW,
                                "quote_source": "yfinance",
                                "quote_delay_status": "THIRD_PARTY_DELAY_UNKNOWN",
                                "two_sided_quote": True,
                                "liquidity_pass": True,
                                "liquidity_reasons": [],
                                "quote_quality_rank": 80.0,
                                "sell_limit_observation": {
                                    "bid_floor": 1.0,
                                    "reference_mid": 1.1,
                                    "observed_limit_low": 1.05,
                                    "observed_limit_high": 1.1,
                                },
                                "annualized_yield_pct": {
                                    "bid": 91.25,
                                    "mid": 100.38,
                                    "ask": 109.5,
                                },
                                "effective_sale_price": {
                                    "bid": 111.0,
                                    "mid": 111.1,
                                    "ask": 111.2,
                                },
                                "put_break_even": None,
                                "cash_secured_put_cash_requirement": None,
                                "premium": 1.1,
                                "annualized_yield_pct_mid": 100.38,
                                "implied_vol": 50.0,
                            }
                        ],
                        "eligible_count": 1,
                        "window_observation_count": 1,
                    },
                    "put_observations": {
                        "status": "NO_ELIGIBLE_LIQUID_QUOTE",
                        "recommended_candidates": [],
                        "eligible_count": 0,
                        "window_observation_count": 0,
                    },
                }
            },
        }
    ]


def source_views_fixture() -> list[dict]:
    return [
        {
            "schema_version": 1,
            "source_id": "synthetic_official",
            "author": "Synthetic Authority",
            "title": "Synthetic public release",
            "summary": "Only public synthetic evidence is used.",
            "url": "https://example.test/public-release",
            "published_at": NOW,
            "retrieved_at": NOW,
            "claim_type": "official_indicator_value",
            "line_public_eligible": True,
            "provider_scope": "public_only",
            "owner_watchlist_inherited": False,
        }
    ]


class GeneratePublicBriefingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.reports = self.root / "reports"
        self.data.mkdir()
        (self.data / "public_snapshot_metadata.json").write_text(
            json.dumps(metadata_fixture()), encoding="utf-8"
        )
        (self.data / "scores_public_latest.json").write_text(
            json.dumps(scores_fixture()), encoding="utf-8"
        )
        (self.data / "options_public_latest.json").write_text(
            json.dumps(options_fixture()), encoding="utf-8"
        )
        (self.data / "source_views_public_latest.json").write_text(
            json.dumps(source_views_fixture()), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_generates_attested_traditional_chinese_public_report(self) -> None:
        dated, latest = module.generate_public_briefing(
            data_dir=self.data,
            reports_dir=self.reports,
            generated_at=datetime(2026, 8, 24, 20, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(dated.is_file())
        self.assertTrue(latest.is_file())
        text = latest.read_text(encoding="utf-8")
        for attestation in module.ATTESTATIONS:
            self.assertIn(attestation, text)
        self.assertIn("公開投資研究摘要", text)
        self.assertIn("公開期權 BID／ASK 觀察", text)
        self.assertIn("Bid".casefold(), text.casefold())
        self.assertIn("USD 1.00", text)
        self.assertIn("USD 1.20", text)
        self.assertIn("THIRD_PARTY_DELAY_UNKNOWN", text)
        self.assertIn("https://example.test/public-release", text)
        self.assertNotIn("covered_contract_capacity", text)
        self.assertNotIn("account_id", text)
        self.assertNotIn("OWNER_PRIVATE", text)

    def test_never_falls_back_to_owner_or_generic_pipeline_files(self) -> None:
        (self.data / "scores_public_latest.json").unlink()
        (self.data / "scores_latest.json").write_text(
            json.dumps(
                [
                    {
                        "ticker": "OWNER_PRIVATE",
                        "user_long_term_overlay": {"label": "private"},
                    }
                ]
            ),
            encoding="utf-8",
        )
        with self.assertRaises(FileNotFoundError):
            module.generate_public_briefing(data_dir=self.data, reports_dir=self.reports)

    def test_public_validators_reject_unknown_private_fields_before_render(self) -> None:
        scores = scores_fixture()
        scores[0]["owner_conviction"] = 99
        (self.data / "scores_public_latest.json").write_text(
            json.dumps(scores), encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            module.generate_public_briefing(data_dir=self.data, reports_dir=self.reports)

    def test_broker_lineage_in_public_option_input_is_rejected(self) -> None:
        options = options_fixture()
        options[0]["quote_source"] = "ibkr_client_portal_read_only"
        (self.data / "options_public_latest.json").write_text(
            json.dumps(options), encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            module.generate_public_briefing(data_dir=self.data, reports_dir=self.reports)

    def test_source_views_are_optional_but_unsafe_urls_are_rejected(self) -> None:
        (self.data / "source_views_public_latest.json").unlink()
        _dated, latest = module.generate_public_briefing(
            data_dir=self.data,
            reports_dir=self.reports,
        )
        self.assertIn(
            "目前沒有通過公開來源檢核的來源觀察",
            latest.read_text(encoding="utf-8"),
        )

        (self.data / "source_views_public_latest.json").write_text(
            json.dumps(source_views_fixture()), encoding="utf-8"
        )
        views = source_views_fixture()
        views[0]["url"] = "http://example.test/insecure"
        (self.data / "source_views_public_latest.json").write_text(
            json.dumps(views), encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            module.generate_public_briefing(data_dir=self.data, reports_dir=self.reports)


if __name__ == "__main__":
    unittest.main()
