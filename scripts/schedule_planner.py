#!/usr/bin/env python3
"""Plan disabled-by-default Taiwan schedules without executing commands.

The planner is deterministic and side-effect free. It rejects clock rollback,
unknown commands, overlapping jobs, unbounded catch-up and retry categories that
could bypass privacy, rights, schema or free-only boundaries. Windows task
registration remains a separate final-release action.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config" / "schedule-policy.json"
ALLOWED_COMMANDS = {
    "python scripts/generate_public_briefing.py",
    "python scripts/authoritative_source_catalog.py --validate",
    "python scripts/release_candidate_gate.py",
}


class SchedulePolicyError(ValueError):
    """Raised when scheduling would violate a hard safety rule."""


@dataclass(frozen=True)
class PlannedJob:
    job_id: str
    scheduled_for: str
    command: str
    catch_up: bool
    network_access: bool
    delivery: bool


@dataclass(frozen=True)
class SchedulePlan:
    timezone: str
    scheduler_enabled: bool
    dry_run_only: bool
    now: str
    last_checked_at: str | None
    planned: tuple[PlannedJob, ...]
    skipped_active_jobs: tuple[str, ...]
    deferred: tuple[dict[str, str], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "timezone": self.timezone,
            "scheduler_enabled": self.scheduler_enabled,
            "dry_run_only": self.dry_run_only,
            "now": self.now,
            "last_checked_at": self.last_checked_at,
            "planned": [asdict(item) for item in self.planned],
            "skipped_active_jobs": list(self.skipped_active_jobs),
            "deferred": list(self.deferred),
            "commands_executed": False,
        }


def load_policy(path: Path = DEFAULT_POLICY) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise SchedulePolicyError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SchedulePolicyError("Schedule policy must be an object")
    return value


def _parse_clock(value: Any) -> time:
    text = str(value or "").strip()
    try:
        parsed = datetime.strptime(text, "%H:%M").time()
    except ValueError as exc:
        raise SchedulePolicyError(f"Invalid local_time: {text!r}") from exc
    return parsed


def _aware(value: datetime | None, timezone: ZoneInfo) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise SchedulePolicyError("Schedule timestamps must include timezone information")
    return value.astimezone(timezone)


def validate_policy(document: Mapping[str, Any]) -> list[str]:
    findings: list[str] = []
    allowed_top = {
        "schema_version",
        "timezone",
        "scheduler_enabled",
        "automatic_task_registration",
        "development_dry_run_only",
        "overlap_policy",
        "clock_rollback_behavior",
        "missed_run_behavior",
        "maximum_catch_up_jobs",
        "retry_policy",
        "jobs",
    }
    unknown = sorted(set(document).difference(allowed_top))
    if unknown:
        findings.append("schedule policy has unknown fields: " + ", ".join(unknown))
    if document.get("schema_version") != 1:
        findings.append("schedule policy schema_version must be 1")
    if document.get("timezone") != "Asia/Taipei":
        findings.append("schedule timezone must be Asia/Taipei")
    if document.get("scheduler_enabled") is not False:
        findings.append("scheduler_enabled must remain false during development")
    if document.get("automatic_task_registration") is not False:
        findings.append("automatic_task_registration must remain false")
    if document.get("development_dry_run_only") is not True:
        findings.append("development_dry_run_only must be true")
    if document.get("overlap_policy") != "skip_if_previous_run_active":
        findings.append("overlap policy must skip active jobs")
    if document.get("clock_rollback_behavior") != "fail_closed":
        findings.append("clock rollback behavior must fail closed")
    if document.get("missed_run_behavior") != "single_bounded_catch_up":
        findings.append("missed run behavior must be single_bounded_catch_up")
    if document.get("maximum_catch_up_jobs") != 1:
        findings.append("maximum_catch_up_jobs must be exactly 1")

    retry = document.get("retry_policy")
    if not isinstance(retry, dict):
        findings.append("retry_policy must be an object")
    else:
        attempts = retry.get("maximum_attempts")
        if not isinstance(attempts, int) or isinstance(attempts, bool) or not 0 <= attempts <= 3:
            findings.append("retry maximum_attempts must be between 0 and 3")
        initial = retry.get("initial_backoff_seconds")
        maximum = retry.get("maximum_backoff_seconds")
        if not isinstance(initial, int) or initial < 1:
            findings.append("initial_backoff_seconds must be a positive integer")
        if not isinstance(maximum, int) or maximum < int(initial or 0) or maximum > 3600:
            findings.append("maximum_backoff_seconds must be bounded and >= initial")
        non_retryable = set(str(item) for item in retry.get("non_retryable_categories", []))
        required = {
            "PRIVACY_BOUNDARY",
            "RIGHTS_REVIEW_REQUIRED",
            "SCHEMA_CHANGED",
            "PAID_FALLBACK_REQUIRED",
            "AUTHORIZATION_FAILURE",
        }
        if not required.issubset(non_retryable):
            findings.append("non-retryable safety categories are incomplete")

    jobs = document.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        findings.append("jobs must be a non-empty array")
        return findings
    seen: set[str] = set()
    for index, job in enumerate(jobs):
        label = f"jobs[{index}]"
        if not isinstance(job, dict):
            findings.append(f"{label} must be an object")
            continue
        allowed_job = {
            "id",
            "local_time",
            "days",
            "command",
            "network_access",
            "requires_public_snapshot",
            "delivery",
            "enabled",
        }
        unknown_job = sorted(set(job).difference(allowed_job))
        if unknown_job:
            findings.append(f"{label} has unknown fields: {', '.join(unknown_job)}")
        job_id = str(job.get("id") or "").strip()
        if not job_id or job_id in seen:
            findings.append(f"{label} has missing or duplicate id")
        seen.add(job_id)
        try:
            _parse_clock(job.get("local_time"))
        except SchedulePolicyError as exc:
            findings.append(f"{label}: {exc}")
        days = job.get("days")
        if not isinstance(days, list) or not days or not all(
            isinstance(day, int) and not isinstance(day, bool) and 1 <= day <= 7
            for day in days
        ):
            findings.append(f"{label}.days must contain ISO weekday numbers 1..7")
        command = str(job.get("command") or "").strip()
        if command not in ALLOWED_COMMANDS:
            findings.append(f"{label}: command is not allowlisted")
        if job.get("network_access") is not False:
            findings.append(f"{label}: development jobs must not require network access")
        if job.get("delivery") is not False:
            findings.append(f"{label}: delivery must remain false")
        if job.get("enabled") is not False:
            findings.append(f"{label}: enabled must remain false")
    return findings


def _candidate_times(
    job: Mapping[str, Any],
    *,
    start: datetime,
    end: datetime,
) -> Iterable[datetime]:
    clock = _parse_clock(job.get("local_time"))
    days = set(int(day) for day in job.get("days", []))
    cursor = start.date()
    while cursor <= end.date():
        candidate = datetime.combine(cursor, clock, tzinfo=end.tzinfo)
        if candidate.isoweekday() in days and start < candidate <= end:
            yield candidate
        cursor += timedelta(days=1)


def plan_schedule(
    document: Mapping[str, Any],
    *,
    now: datetime,
    last_checked_at: datetime | None = None,
    active_job_ids: Iterable[str] = (),
    simulate_enabled: bool = False,
) -> SchedulePlan:
    findings = validate_policy(document)
    if findings:
        raise SchedulePolicyError("; ".join(findings))
    timezone = ZoneInfo(str(document["timezone"]))
    current = _aware(now, timezone)
    previous = _aware(last_checked_at, timezone)
    assert current is not None
    if previous and current < previous:
        raise SchedulePolicyError("Clock moved backward; refusing schedule plan")

    scheduler_enabled = bool(document.get("scheduler_enabled"))
    effective_enabled = scheduler_enabled or simulate_enabled
    if not effective_enabled:
        return SchedulePlan(
            timezone=str(document["timezone"]),
            scheduler_enabled=False,
            dry_run_only=True,
            now=current.isoformat(),
            last_checked_at=previous.isoformat() if previous else None,
            planned=(),
            skipped_active_jobs=(),
            deferred=(),
        )

    # First check only establishes a watermark; it never backfills historical jobs.
    start = previous or current
    active = {str(value) for value in active_job_ids}
    due: list[tuple[datetime, Mapping[str, Any]]] = []
    for job in document.get("jobs", []):
        if not isinstance(job, Mapping):
            continue
        # Development policy stores enabled=false. simulate_enabled is used only
        # by tests/planning previews and never authorizes command execution.
        if job.get("enabled") is not True and not simulate_enabled:
            continue
        due.extend((candidate, job) for candidate in _candidate_times(job, start=start, end=current))
    due.sort(key=lambda item: (item[0], str(item[1].get("id"))))

    planned: list[PlannedJob] = []
    skipped: list[str] = []
    deferred: list[dict[str, str]] = []
    catch_up_used = 0
    for scheduled_for, job in due:
        job_id = str(job.get("id"))
        if job_id in active:
            skipped.append(job_id)
            continue
        catch_up = scheduled_for < current.replace(second=0, microsecond=0)
        if catch_up:
            if catch_up_used >= int(document["maximum_catch_up_jobs"]):
                deferred.append(
                    {
                        "job_id": job_id,
                        "scheduled_for": scheduled_for.isoformat(),
                        "reason": "CATCH_UP_LIMIT",
                    }
                )
                continue
            catch_up_used += 1
        planned.append(
            PlannedJob(
                job_id=job_id,
                scheduled_for=scheduled_for.isoformat(),
                command=str(job.get("command")),
                catch_up=catch_up,
                network_access=False,
                delivery=False,
            )
        )

    return SchedulePlan(
        timezone=str(document["timezone"]),
        scheduler_enabled=scheduler_enabled,
        dry_run_only=True,
        now=current.isoformat(),
        last_checked_at=previous.isoformat() if previous else None,
        planned=tuple(planned),
        skipped_active_jobs=tuple(sorted(set(skipped))),
        deferred=tuple(deferred),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    try:
        policy = load_policy()
        findings = validate_policy(policy)
        if findings:
            raise SchedulePolicyError("; ".join(findings))
        if args.preview:
            now = datetime.now(ZoneInfo("Asia/Taipei"))
            plan = plan_schedule(
                policy,
                now=now,
                last_checked_at=now - timedelta(hours=24),
                simulate_enabled=True,
            )
            print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"valid": True, "scheduler_enabled": False}, sort_keys=True))
        return 0
    except (FileNotFoundError, SchedulePolicyError) as exc:
        print(f"SCHEDULE PLANNER FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
