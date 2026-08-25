from __future__ import annotations

import copy
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from schedule_planner import (  # noqa: E402
    SchedulePolicyError,
    load_policy,
    plan_schedule,
    validate_policy,
)

TAIPEI = ZoneInfo("Asia/Taipei")


class SchedulePlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_policy()

    def test_repository_policy_is_valid_disabled_and_side_effect_free(self) -> None:
        self.assertEqual(validate_policy(self.policy), [])
        now = datetime(2026, 8, 24, 12, 0, tzinfo=TAIPEI)
        plan = plan_schedule(
            self.policy,
            now=now,
            last_checked_at=now - timedelta(days=2),
        )
        self.assertFalse(plan.scheduler_enabled)
        self.assertTrue(plan.dry_run_only)
        self.assertEqual(plan.planned, ())
        self.assertFalse(plan.as_dict()["commands_executed"])

    def test_preview_plans_at_most_one_bounded_catch_up(self) -> None:
        previous = datetime(2026, 8, 21, 6, 0, tzinfo=TAIPEI)
        now = datetime(2026, 8, 24, 21, 0, tzinfo=TAIPEI)
        plan = plan_schedule(
            self.policy,
            now=now,
            last_checked_at=previous,
            simulate_enabled=True,
        )
        catch_up = [job for job in plan.planned if job.catch_up]
        self.assertLessEqual(len(catch_up), 1)
        self.assertTrue(
            all(job.network_access is False and job.delivery is False for job in plan.planned)
        )
        self.assertTrue(
            all(item["reason"] == "CATCH_UP_LIMIT" for item in plan.deferred)
        )

    def test_active_job_is_skipped_not_started_twice(self) -> None:
        previous = datetime(2026, 8, 24, 6, 0, tzinfo=TAIPEI)
        now = datetime(2026, 8, 24, 8, 0, tzinfo=TAIPEI)
        plan = plan_schedule(
            self.policy,
            now=now,
            last_checked_at=previous,
            active_job_ids={"public_morning_briefing"},
            simulate_enabled=True,
        )
        self.assertIn("public_morning_briefing", plan.skipped_active_jobs)
        self.assertNotIn(
            "public_morning_briefing",
            {job.job_id for job in plan.planned},
        )

    def test_clock_rollback_and_naive_timestamps_fail_closed(self) -> None:
        now = datetime(2026, 8, 24, 8, 0, tzinfo=TAIPEI)
        with self.assertRaises(SchedulePolicyError):
            plan_schedule(
                self.policy,
                now=now - timedelta(minutes=1),
                last_checked_at=now,
                simulate_enabled=True,
            )
        with self.assertRaises(SchedulePolicyError):
            plan_schedule(
                self.policy,
                now=datetime(2026, 8, 24, 8, 0),
                simulate_enabled=True,
            )

    def test_unknown_network_delivery_or_enabled_job_is_rejected(self) -> None:
        mutations = (
            ("command", "powershell -Command Invoke-WebRequest https://example.test"),
            ("network_access", True),
            ("delivery", True),
            ("enabled", True),
        )
        for field, value in mutations:
            policy = copy.deepcopy(self.policy)
            policy["jobs"][0][field] = value
            findings = validate_policy(policy)
            with self.subTest(field=field):
                self.assertTrue(findings)

    def test_privacy_rights_schema_paid_and_auth_failures_never_retry(self) -> None:
        required = {
            "PRIVACY_BOUNDARY",
            "RIGHTS_REVIEW_REQUIRED",
            "SCHEMA_CHANGED",
            "PAID_FALLBACK_REQUIRED",
            "AUTHORIZATION_FAILURE",
        }
        self.assertTrue(
            required.issubset(
                set(self.policy["retry_policy"]["non_retryable_categories"])
            )
        )
        policy = copy.deepcopy(self.policy)
        policy["retry_policy"]["non_retryable_categories"] = ["SCHEMA_CHANGED"]
        findings = validate_policy(policy)
        self.assertTrue(any("non-retryable safety categories" in item for item in findings))

    def test_first_check_does_not_backfill_historical_jobs(self) -> None:
        now = datetime(2026, 8, 24, 21, 0, tzinfo=TAIPEI)
        plan = plan_schedule(
            self.policy,
            now=now,
            last_checked_at=None,
            simulate_enabled=True,
        )
        self.assertEqual(plan.planned, ())
        self.assertEqual(plan.deferred, ())


if __name__ == "__main__":
    unittest.main()
