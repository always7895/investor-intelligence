from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_to_kv as sync_module  # noqa: E402


class FakeKvClient:
    instances: list["FakeKvClient"] = []

    def __init__(self, **_kwargs: str) -> None:
        self.puts: list[tuple[str, bytes, str]] = []
        self.__class__.instances.append(self)

    def put(self, key: str, content: bytes, content_type: str) -> None:
        self.puts.append((key, content, content_type))


def public_options_fixture() -> list[dict]:
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


def public_scores_fixture() -> list[dict]:
    return [
        {
            "schema_version": 1,
            "ticker": "TEST",
            "rank": 1,
            "total_score": 70.0,
            "data_quality": 0.8,
            "line_public_eligible": True,
            "provider_scope": "public_only",
            "owner_watchlist_inherited": False,
        }
    ]


def public_source_views_fixture() -> list[dict]:
    return [
        {
            "schema_version": 1,
            "author": "Public Author",
            "summary": "Publicly attributable research observation.",
            "url": "https://example.org/public-source",
            "published_at": "2026-08-23T00:00:00Z",
            "line_public_eligible": True,
            "provider_scope": "public_only",
            "owner_watchlist_inherited": False,
        }
    ]


class PublicSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeKvClient.instances.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data" / "cache"
        self.reports = self.root / "reports"
        self.data.mkdir(parents=True)
        self.reports.mkdir(parents=True)
        self.public_as_of = (
            datetime.now(timezone.utc) - timedelta(minutes=2)
        ).isoformat()
        (self.data / "public_snapshot_metadata.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "line_public_eligible": True,
                    "provider_scope": "public_only",
                    "owner_watchlist_inherited": False,
                    "last_successful_pipeline_timestamp": self.public_as_of,
                }
            ),
            encoding="utf-8",
        )
        (self.reports / "public_briefing_latest.md").write_text(
            "\n".join(
                [
                    "<!-- line-public-eligible: true -->",
                    "<!-- provider-scope: public_only -->",
                    "<!-- owner-watchlist-inherited: false -->",
                    "# Public report",
                    "Only independently reviewed public research data.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (self.data / "scores_public_latest.json").write_text(
            json.dumps(public_scores_fixture()), encoding="utf-8"
        )
        (self.data / "options_public_latest.json").write_text(
            json.dumps(public_options_fixture()), encoding="utf-8"
        )
        (self.data / "source_views_public_latest.json").write_text(
            json.dumps(public_source_views_fixture()), encoding="utf-8"
        )
        self.patches = [
            patch.object(sync_module, "BASE_DIR", self.root),
            patch.object(sync_module, "DATA_DIR", self.data),
            patch.object(sync_module, "REPORTS_DIR", self.reports),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_default_is_validation_only_dry_run(self) -> None:
        summary = sync_module.sync_snapshot()
        self.assertTrue(summary["dry_run"])
        self.assertFalse(FakeKvClient.instances)
        self.assertEqual(summary["public_data_as_of"], self.public_as_of)
        self.assertFalse(summary["owner_watchlist_inherited"])

    def test_public_options_accept_only_explicit_public_records(self) -> None:
        value = sync_module._validate_public_options(public_options_fixture())
        serialized = json.dumps(value)
        self.assertIn('"bid": 4.0', serialized)
        self.assertIn('"ask": 4.2', serialized)
        self.assertIn('"provider_scope": "public_only"', serialized)
        self.assertEqual(serialized.count("public_view_notice"), 1)
        self.assertNotIn("covered_contract_capacity", serialized)
        self.assertNotIn("account_id", serialized)

    def test_rejects_ibkr_broker_or_non_false_attestations(self) -> None:
        value = public_options_fixture()
        value[0]["quote_source"] = "ibkr_client_portal_read_only"
        with self.assertRaises(ValueError):
            sync_module._validate_public_options(value)

        value = public_options_fixture()
        value[0]["provenance_note"] = "derived from Interactive Brokers Client Portal"
        with self.assertRaises(ValueError):
            sync_module._validate_public_options(value)

        for attestation in (
            "ibkr_connected",
            "brokerage_data_included",
            "account_data_included",
            "position_data_included",
            "owner_watchlist_inherited",
        ):
            value = public_options_fixture()
            value[0][attestation] = True
            with self.subTest(attestation=attestation), self.assertRaises(ValueError):
                sync_module._validate_public_options(value)

    def test_rejects_position_account_coverage_and_private_overlay_keys(self) -> None:
        for key, private_value in (
            ("position", {"shares": 250}),
            ("account_id", "synthetic-account"),
            ("covered_contract_capacity", 2),
            ("portfolio_weight", 0.5),
        ):
            value = public_options_fixture()
            value[0][key] = private_value
            with self.subTest(key=key), self.assertRaises(ValueError):
                sync_module._validate_public_options(value)

        score = public_scores_fixture()
        score[0]["user_long_term_overlay"] = {"minimum_holding_years": 2}
        with self.assertRaises(ValueError):
            sync_module._validate_public_scores(score)

    def test_public_scores_require_independent_attestations(self) -> None:
        value = sync_module._validate_public_scores(public_scores_fixture())
        self.assertEqual(value[0]["ticker"], "TEST")
        self.assertIn("public_view_notice", value[0])

        for field in ("line_public_eligible", "provider_scope", "owner_watchlist_inherited"):
            value = public_scores_fixture()
            value[0].pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                sync_module._validate_public_scores(value)

    def test_public_source_views_require_https_and_public_attestations(self) -> None:
        value = sync_module._validate_public_source_views(public_source_views_fixture())
        self.assertEqual(value[0]["author"], "Public Author")
        self.assertIn("public_view_notice", value[0])

        invalid = public_source_views_fixture()
        invalid[0]["url"] = "http://example.org/insecure"
        with self.assertRaises(ValueError):
            sync_module._validate_public_source_views(invalid)

    def test_public_report_requires_positive_attestations_and_rejects_private_markers(self) -> None:
        path = self.reports / "public_briefing_latest.md"
        original = path.read_text(encoding="utf-8")
        for marker in sync_module.PUBLIC_REPORT_ATTESTATIONS:
            path.write_text(original.replace(marker, ""), encoding="utf-8")
            with self.subTest(missing=marker), self.assertRaises(ValueError):
                sync_module.sync_snapshot()
        path.write_text(original + "\nUser-defined long-term suitability overlay\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            sync_module.sync_snapshot()

    def test_legacy_owner_pipeline_artifacts_are_never_fallbacks(self) -> None:
        (self.data / "scores_public_latest.json").unlink()
        (self.data / "scores_latest.json").write_text(
            json.dumps(
                [
                    {
                        "ticker": "OWNER_SYMBOL",
                        "total_score": 99,
                        "user_long_term_overlay": {"label": "private"},
                    }
                ]
            ),
            encoding="utf-8",
        )
        with self.assertRaises(FileNotFoundError):
            sync_module.sync_snapshot()

        (self.data / "scores_public_latest.json").write_text(
            json.dumps(public_scores_fixture()), encoding="utf-8"
        )
        (self.data / "source_views_public_latest.json").unlink()
        (self.data / "source_views_latest.json").write_text(
            json.dumps([{"author": "Owner-selected", "summary": "private"}]),
            encoding="utf-8",
        )
        summary = sync_module.sync_snapshot()
        self.assertNotIn("source_views:latest", summary["logical_keys"])

    def test_legacy_merged_options_file_is_never_a_fallback(self) -> None:
        (self.data / "options_public_latest.json").unlink()
        (self.data / "options_latest.json").write_text(
            json.dumps(
                [
                    {
                        "ticker": "OWNER_SYMBOL",
                        "quote_source": "ibkr_client_portal_read_only",
                        "position": {"covered_contract_capacity": 9},
                    }
                ]
            ),
            encoding="utf-8",
        )
        with self.assertRaises(FileNotFoundError):
            sync_module.sync_snapshot()

    def test_public_timestamp_comes_from_attested_metadata_not_sync_clock(self) -> None:
        objects, public_as_of = sync_module.collect_snapshot_objects()
        timestamp_object = next(
            item for item in objects if item.logical_key == "last_successful_pipeline_timestamp"
        )
        self.assertEqual(timestamp_object.content.decode("utf-8"), self.public_as_of)
        self.assertEqual(public_as_of, self.public_as_of)

        metadata = json.loads(
            (self.data / "public_snapshot_metadata.json").read_text(encoding="utf-8")
        )
        metadata["last_successful_pipeline_timestamp"] = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).isoformat()
        (self.data / "public_snapshot_metadata.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            sync_module.sync_snapshot()

    def test_apply_requires_explicit_free_only_double_gate(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                sync_module.sync_snapshot(dry_run=False)
        with patch.dict(
            os.environ,
            {
                "PUBLIC_KV_SYNC_ENABLED": "true",
                "FREE_ONLY_MODE": "true",
                "PAID_FALLBACK_ENABLED": "true",
                "CLOUDFLARE_PLAN": "workers_free",
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                sync_module.sync_snapshot(dry_run=False)

    def test_pointer_is_written_last_and_manifest_hashes_every_object(self) -> None:
        environment = {
            "PUBLIC_KV_SYNC_ENABLED": "true",
            "FREE_ONLY_MODE": "true",
            "PAID_FALLBACK_ENABLED": "false",
            "CLOUDFLARE_PLAN": "workers_free",
            "CLOUDFLARE_ACCOUNT_ID": "account",
            "CLOUDFLARE_KV_NAMESPACE_ID": "namespace",
            "CLOUDFLARE_API_TOKEN": "token",
        }
        with patch.dict(os.environ, environment, clear=True), patch.object(
            sync_module, "CloudflareKvClient", FakeKvClient
        ):
            summary = sync_module.sync_snapshot(dry_run=False)
        puts = FakeKvClient.instances[-1].puts
        keys = [key for key, _content, _type in puts]
        self.assertEqual(keys[-1], "snapshot:current")
        self.assertEqual(keys[-2], f"snapshot:{summary['run_id']}:manifest")
        self.assertTrue(
            all(key.startswith(f"snapshot:{summary['run_id']}:") for key in keys[:-1])
        )
        manifest = json.loads(puts[-2][1].decode("utf-8"))
        self.assertEqual(manifest["public_data_as_of"], self.public_as_of)
        self.assertFalse(manifest["owner_watchlist_inherited"])
        physical = {key: content for key, content, _type in puts[:-2]}
        for record in manifest["objects"].values():
            content = physical[record["physical_key"]]
            self.assertEqual(record["sha256"], hashlib.sha256(content).hexdigest())


if __name__ == "__main__":
    unittest.main()
