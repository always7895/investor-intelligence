from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from source_health import (  # noqa: E402
    CIRCUIT_OPEN,
    DEGRADED,
    HALF_OPEN,
    HEALTHY,
    QUARANTINED,
    HealthPolicy,
    SourceHealthError,
    SourceHealthState,
    atomic_write_state,
    half_open_for_probe,
    load_state,
    manual_quarantine,
    probe_allowed,
    record_failure,
    record_success,
)


class SourceHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
        self.policy = HealthPolicy(
            degraded_after_failures=1,
            circuit_open_after_failures=3,
            base_backoff_seconds=60,
            maximum_backoff_seconds=3600,
            quarantine_after_schema_failures=3,
        )

    def test_failure_progression_and_success_recovery(self) -> None:
        state = SourceHealthState.initial("synthetic", self.now)
        self.assertEqual(state.status, HEALTHY)
        state = record_failure(
            state,
            error_code="HTTP_503",
            now=self.now,
            policy=self.policy,
        )
        self.assertEqual(state.status, DEGRADED)
        state = record_failure(
            state,
            error_code="HTTP_503",
            now=self.now + timedelta(seconds=1),
            policy=self.policy,
        )
        self.assertEqual(state.status, DEGRADED)
        state = record_failure(
            state,
            error_code="HTTP_503",
            now=self.now + timedelta(seconds=2),
            policy=self.policy,
        )
        self.assertEqual(state.status, CIRCUIT_OPEN)
        self.assertIsNotNone(state.next_probe_at)
        recovered = record_success(state, now=self.now + timedelta(minutes=2))
        self.assertEqual(recovered.status, HEALTHY)
        self.assertEqual(recovered.consecutive_failures, 0)
        self.assertIsNone(recovered.last_error_code)

    def test_circuit_probe_respects_backoff(self) -> None:
        state = SourceHealthState.initial("synthetic", self.now)
        for index in range(3):
            state = record_failure(
                state,
                error_code="TIMEOUT",
                now=self.now + timedelta(seconds=index),
                policy=self.policy,
            )
        self.assertFalse(probe_allowed(state, now=self.now + timedelta(seconds=30)))
        self.assertTrue(probe_allowed(state, now=self.now + timedelta(minutes=2)))
        half_open = half_open_for_probe(
            state,
            now=self.now + timedelta(minutes=2),
        )
        self.assertEqual(half_open.status, HALF_OPEN)

    def test_schema_failures_quarantine_source(self) -> None:
        state = SourceHealthState.initial("synthetic", self.now)
        for index in range(3):
            state = record_failure(
                state,
                error_code="SCHEMA_DRIFT",
                schema_failure=True,
                now=self.now + timedelta(seconds=index),
                policy=self.policy,
            )
        self.assertEqual(state.status, QUARANTINED)
        self.assertFalse(probe_allowed(state, now=self.now + timedelta(days=1)))

    def test_manual_quarantine_is_fail_closed(self) -> None:
        state = manual_quarantine(
            SourceHealthState.initial("synthetic", self.now),
            now=self.now,
        )
        self.assertEqual(state.status, QUARANTINED)
        self.assertFalse(probe_allowed(state, now=self.now + timedelta(days=1)))

    def test_error_code_cannot_persist_sensitive_free_text(self) -> None:
        state = SourceHealthState.initial("synthetic", self.now)
        with self.assertRaises(SourceHealthError):
            record_failure(
                state,
                error_code="token=EXAMPLE_SECRET_VALUE_NOT_REAL",
                now=self.now,
                policy=self.policy,
            )

    def test_atomic_round_trip(self) -> None:
        state = record_failure(
            SourceHealthState.initial("synthetic", self.now),
            error_code="HTTP_429",
            now=self.now,
            policy=self.policy,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            atomic_write_state(path, state)
            loaded = load_state(path, expected_source_id="synthetic")
            self.assertEqual(loaded, state)


if __name__ == "__main__":
    unittest.main()
