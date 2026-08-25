from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from source_observation import (  # noqa: E402
    SourceObservationError,
    normalize_observation,
    observation_set_hash,
    promote_last_known_good,
)
from source_registry import Registry, load_registry  # noqa: E402


class SourceObservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = load_registry()
        source = replace(
            base.by_id()["us_sec_edgar"],
            admission_status="RUNTIME_ENABLED",
            adapter_status="implemented",
            runtime_enabled=True,
            terms_review_status="approved",
        )
        cls.registry = Registry(
            schema_version=1,
            sources=(source,),
            catalog_files=("synthetic-runtime-registry",),
        )
        cls.now = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)

    def valid_raw(self) -> dict:
        return {
            "source_id": "us_sec_edgar",
            "canonical_url": "https://www.sec.gov/edgar/example-document",
            "jurisdiction": "US",
            "language": "en",
            "published_at": (self.now - timedelta(minutes=10)).isoformat(),
            "retrieved_at": self.now.isoformat(),
            "parser_id": "sec_test_parser",
            "parser_version": "1.0.0",
            "claim_type": "issuer_filing_fact",
            "evidence_role": "issuer_filings",
            "correction_status": "NEW",
            "payload": {"ticker": "TEST", "reported_revenue": 100},
        }

    def test_normalizes_registry_owned_provenance(self) -> None:
        observation = normalize_observation(
            self.valid_raw(),
            registry=self.registry,
            raw_content=b"synthetic official document",
            now=self.now,
        )
        self.assertEqual(observation.trust_tier, "T1_PRIMARY_OFFICIAL")
        self.assertEqual(observation.authority_class, "securities_regulator")
        self.assertEqual(observation.freshness_status, "CURRENT")
        self.assertEqual(len(observation.observation_id), 64)
        self.assertEqual(len(observation.content_sha256), 64)

    def test_rejects_unregistered_or_disabled_source(self) -> None:
        raw = self.valid_raw()
        raw["source_id"] = "not_registered"
        with self.assertRaises(SourceObservationError):
            normalize_observation(
                raw,
                registry=self.registry,
                raw_content=b"x",
                now=self.now,
            )

        disabled_registry = load_registry()
        raw = self.valid_raw()
        with self.assertRaises(SourceObservationError):
            normalize_observation(
                raw,
                registry=disabled_registry,
                raw_content=b"x",
                now=self.now,
            )

    def test_rejects_cross_domain_url(self) -> None:
        raw = self.valid_raw()
        raw["canonical_url"] = "https://example.test/fake-filing"
        with self.assertRaises(SourceObservationError):
            normalize_observation(
                raw,
                registry=self.registry,
                raw_content=b"x",
                now=self.now,
            )

    def test_rejects_future_or_inverted_chronology(self) -> None:
        raw = self.valid_raw()
        raw["retrieved_at"] = (self.now + timedelta(hours=1)).isoformat()
        with self.assertRaises(SourceObservationError):
            normalize_observation(
                raw,
                registry=self.registry,
                raw_content=b"x",
                now=self.now,
            )

        raw = self.valid_raw()
        raw["published_at"] = (self.now + timedelta(hours=1)).isoformat()
        with self.assertRaises(SourceObservationError):
            normalize_observation(
                raw,
                registry=self.registry,
                raw_content=b"x",
                now=self.now,
            )

    def test_rejects_private_fields_in_public_payload(self) -> None:
        raw = self.valid_raw()
        raw["payload"] = {
            "ticker": "TEST",
            "nested": {"account_id": "must-not-enter-public-cache"},
        }
        with self.assertRaises(SourceObservationError):
            normalize_observation(
                raw,
                registry=self.registry,
                raw_content=b"x",
                now=self.now,
            )

    def test_correction_requires_superseded_observation(self) -> None:
        raw = self.valid_raw()
        raw["correction_status"] = "RESTATED"
        with self.assertRaises(SourceObservationError):
            normalize_observation(
                raw,
                registry=self.registry,
                raw_content=b"x",
                now=self.now,
            )

    def test_last_known_good_is_immutable_then_pointer_is_promoted(self) -> None:
        observation = normalize_observation(
            self.valid_raw(),
            registry=self.registry,
            raw_content=b"synthetic official document",
            now=self.now,
        )
        with tempfile.TemporaryDirectory() as temporary:
            immutable, latest = promote_last_known_good(
                observation,
                output_root=Path(temporary),
            )
            self.assertTrue(immutable.is_file())
            self.assertTrue(latest.is_file())
            pointer = json.loads(latest.read_text(encoding="utf-8"))
            self.assertEqual(pointer["observation_id"], observation.observation_id)
            immutable_again, latest_again = promote_last_known_good(
                observation,
                output_root=Path(temporary),
            )
            self.assertEqual(immutable_again, immutable)
            self.assertEqual(latest_again, latest)

    def test_observation_set_hash_is_order_independent(self) -> None:
        first = normalize_observation(
            self.valid_raw(),
            registry=self.registry,
            raw_content=b"first",
            now=self.now,
        )
        second_raw = self.valid_raw()
        second_raw["canonical_url"] = "https://www.sec.gov/edgar/second-document"
        second = normalize_observation(
            second_raw,
            registry=self.registry,
            raw_content=b"second",
            now=self.now,
        )
        self.assertEqual(
            observation_set_hash([first, second]),
            observation_set_hash([second, first]),
        )


if __name__ == "__main__":
    unittest.main()
