#!/usr/bin/env python3
"""Validate and atomically promote an owner-independent public KV snapshot.

The shared LINE Bot consumes only explicitly attested public artifacts. Legacy
operator/watchlist outputs are never fallbacks. Network writes are dry-run by
default and require both ``--apply`` and ``PUBLIC_KV_SYNC_ENABLED=true`` while
free-only policy remains active.

Every public JSON shape is a closed schema. Unknown fields are rejected instead
of being copied or heuristically redacted, so a future internal/private field
cannot become public merely because its name is absent from a denylist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data" / "cache"
REPORTS_DIR = BASE_DIR / "reports"

PUBLIC_METADATA_FILENAME = "public_snapshot_metadata.json"
PUBLIC_SCORES_FILENAME = "scores_public_latest.json"
PUBLIC_OPTIONS_FILENAME = "options_public_latest.json"
PUBLIC_SOURCE_VIEWS_FILENAME = "source_views_public_latest.json"

PUBLIC_REPORT_ATTESTATIONS = (
    "<!-- line-public-eligible: true -->",
    "<!-- provider-scope: public_only -->",
    "<!-- owner-watchlist-inherited: false -->",
)
MAX_PUBLIC_OBJECT_BYTES = 5_000_000
MAX_PUBLIC_SNAPSHOT_BYTES = 15_000_000
MAX_CLOCK_SKEW = timedelta(minutes=5)

# Closed-schema fields. These sets are intentionally explicit: adding a public
# field requires a reviewed code/test change rather than relying on redaction.
PUBLIC_METADATA_FIELDS = frozenset(
    {
        "schema_version",
        "line_public_eligible",
        "provider_scope",
        "owner_watchlist_inherited",
        "last_successful_pipeline_timestamp",
    }
)
PUBLIC_SCORE_FIELDS = frozenset(
    {
        "schema_version",
        "ticker",
        "name",
        "rank",
        "total_score",
        "data_quality",
        "rating",
        "category",
        "current_price",
        "market_cap",
        "revenue_growth",
        "scoring_version",
        "generated_at",
        "as_of",
        "source_count",
        "evidence_count",
        "line_public_eligible",
        "provider_scope",
        "owner_watchlist_inherited",
    }
)
PUBLIC_SOURCE_VIEW_FIELDS = frozenset(
    {
        "schema_version",
        "source_id",
        "author",
        "title",
        "summary",
        "url",
        "published_at",
        "retrieved_at",
        "as_of",
        "claim_type",
        "line_public_eligible",
        "provider_scope",
        "owner_watchlist_inherited",
    }
)
PUBLIC_OPTION_FIELDS = frozenset(
    {
        "schema_version",
        "ticker",
        "provider_symbol",
        "currency",
        "current_price",
        "retrieved_at",
        "status",
        "quote_source",
        "quote_delay_status",
        "provider_scope",
        "line_public_eligible",
        "ibkr_connected",
        "brokerage_data_included",
        "account_data_included",
        "position_data_included",
        "owner_watchlist_inherited",
        "periods",
    }
)
PUBLIC_OPTION_PERIOD_NAMES = frozenset({"weekly", "monthly"})
PUBLIC_OPTION_PERIOD_FIELDS = frozenset(
    {
        "status",
        "target_dte",
        "expiration",
        "actual_dte",
        "call_observations",
        "put_observations",
    }
)
PUBLIC_OPTION_GROUP_FIELDS = frozenset(
    {
        "status",
        "recommended_candidates",
        "eligible_count",
        "window_observation_count",
    }
)
PUBLIC_OPTION_CANDIDATE_FIELDS = frozenset(
    {
        "ticker",
        "option_type",
        "contract_symbol",
        "expiration",
        "actual_dte",
        "strike",
        "spot",
        "distance_from_spot_pct",
        "bid",
        "ask",
        "midpoint",
        "last",
        "spread",
        "spread_pct_of_mid",
        "volume",
        "open_interest",
        "implied_volatility_pct",
        "delta",
        "delta_status",
        "last_trade_at",
        "last_trade_age_days",
        "retrieved_at",
        "quote_source",
        "quote_delay_status",
        "two_sided_quote",
        "liquidity_pass",
        "liquidity_reasons",
        "quote_quality_rank",
        "sell_limit_observation",
        "annualized_yield_pct",
        "effective_sale_price",
        "put_break_even",
        "cash_secured_put_cash_requirement",
        # Public backward-compatible arithmetic fields retained by the existing
        # deterministic formatter. They contain no account/position information.
        "premium",
        "annualized_yield_pct_mid",
        "implied_vol",
    }
)
PUBLIC_OPTION_TRIPLET_FIELDS = frozenset({"bid", "mid", "ask"})
PUBLIC_OPTION_LIMIT_FIELDS = frozenset(
    {"bid_floor", "reference_mid", "observed_limit_low", "observed_limit_high"}
)

FORBIDDEN_PUBLIC_KEYS = {
    "account",
    "account_id",
    "account_number",
    "accountid",
    "acctid",
    "portfolio",
    "portfolio_weight",
    "holding",
    "holdings",
    "position",
    "positions",
    "shares",
    "whole_shares",
    "position_shares",
    "position_quantity",
    "quantity",
    "covered_contract_capacity",
    "coverage_status",
    "cost_basis",
    "average_price",
    "averagecost",
    "market_value",
    "realized_pnl",
    "unrealized_pnl",
    "daily_pnl",
    "buying_power",
    "margin",
    "cash_balance",
    "user_long_term_overlay",
    "user_preferences",
    "private_preferences",
    "tenant_preferences",
    "owner_preferences",
    "owner_watchlist",
    "tenant_id",
    "line_user_id",
    "raw_user_id",
    "conversation",
    "messages",
    "memory",
    "primary_provider_status",
    "primary_provider_capacity_applied",
    "primary_provider_error",
    "fallback_provider_status",
}
NEGATIVE_PUBLIC_ATTESTATIONS = {
    "owner_watchlist_inherited",
    "ibkr_connected",
    "brokerage_data_included",
    "account_data_included",
    "position_data_included",
}
PRIVATE_LINEAGE_MARKERS = (
    "tenant-private",
    "private sync",
    "portfolio.local",
    "repository user's preference",
    "user-defined long-term suitability overlay",
    "owner watchlist",
    "owner_private",
    "private portfolio",
)
BROKER_LINEAGE_MARKERS = (
    "ibkr",
    "interactive brokers",
    "client portal",
    "brokerage",
    "broker account",
)
FORBIDDEN_PUBLIC_REPORT_MARKERS = (
    *PRIVATE_LINEAGE_MARKERS,
    "PRIVATE_PORTFOLIO",
    "IBKR account",
    "broker account",
)

PUBLIC_OPTIONS_NOTICE = (
    "Public option snapshot only: no owner watchlist, portfolio, account, "
    "covered-capacity, IBKR or brokerage-derived data is accepted."
)
PUBLIC_SCORES_NOTICE = (
    "Public ranking artifact only: no owner watchlist or user/tenant preference "
    "overlay is accepted."
)
PUBLIC_SOURCE_VIEWS_NOTICE = (
    "Public source-view artifact only: no owner watchlist, private report or "
    "tenant-derived selection is accepted."
)


@dataclass(frozen=True)
class SnapshotObject:
    logical_key: str
    content: bytes
    content_type: str
    required: bool
    source_path: str


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"PUT"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _normalized_key(value: object) -> str:
    return str(value).replace("-", "_").casefold()


def _reject_unknown_fields(
    value: dict[str, Any],
    allowed: frozenset[str],
    label: str,
) -> None:
    unknown = sorted(set(value).difference(allowed))
    if unknown:
        raise ValueError(f"{label} contains unknown field(s): {', '.join(unknown)}")


def _validate_finite_json(value: Any, path: str = "$") -> None:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"Public artifact contains a non-finite number at {path}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_finite_json(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_finite_json(item, f"{path}.{key}")
        return
    raise ValueError(f"Public artifact contains a non-JSON value at {path}")


def _parse_timestamp(value: Any, label: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is missing")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    parsed = parsed.astimezone(timezone.utc)
    if parsed > datetime.now(timezone.utc) + MAX_CLOCK_SKEW:
        raise ValueError(f"{label} is unreasonably in the future")
    return parsed


def _validate_public_attestations(value: dict[str, Any], label: str) -> None:
    if value.get("line_public_eligible") is not True:
        raise ValueError(f"{label} lacks line_public_eligible=true")
    if value.get("provider_scope") != "public_only":
        raise ValueError(f"{label} lacks provider_scope=public_only")
    if value.get("owner_watchlist_inherited") is not False:
        raise ValueError(f"{label} must declare owner_watchlist_inherited=false")


def _validate_no_private_lineage(
    value: Any,
    path: str = "$",
    *,
    reject_broker_lineage: bool = False,
) -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_no_private_lineage(
                item,
                f"{path}[{index}]",
                reject_broker_lineage=reject_broker_lineage,
            )
        return
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = _normalized_key(key)
            if normalized in NEGATIVE_PUBLIC_ATTESTATIONS:
                if item is not False:
                    raise ValueError(f"Public artifact has non-false attestation at {path}.{key}")
                continue
            if normalized in FORBIDDEN_PUBLIC_KEYS:
                raise ValueError(f"Public artifact contains forbidden key at {path}.{key}")
            if any(marker.replace(" ", "_") in normalized for marker in PRIVATE_LINEAGE_MARKERS):
                raise ValueError(f"Public artifact contains private-lineage key at {path}.{key}")
            if reject_broker_lineage and any(
                marker.replace(" ", "_") in normalized for marker in BROKER_LINEAGE_MARKERS
            ):
                raise ValueError(f"Public artifact contains broker-lineage key at {path}.{key}")
            _validate_no_private_lineage(
                item,
                f"{path}.{key}",
                reject_broker_lineage=reject_broker_lineage,
            )
        return
    if isinstance(value, str):
        normalized = value.casefold()
        if any(marker.casefold() in normalized for marker in PRIVATE_LINEAGE_MARKERS):
            raise ValueError(f"Public artifact contains private lineage at {path}")
        if reject_broker_lineage and any(
            marker.casefold() in normalized for marker in BROKER_LINEAGE_MARKERS
        ):
            raise ValueError(f"Public artifact contains broker lineage at {path}")


def _validate_public_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Public snapshot metadata must be an object")
    _reject_unknown_fields(value, PUBLIC_METADATA_FIELDS, "Public snapshot metadata")
    _validate_public_attestations(value, "Public snapshot metadata")
    _validate_no_private_lineage(value)
    _validate_finite_json(value)
    timestamp = _parse_timestamp(
        value.get("last_successful_pipeline_timestamp"),
        "last_successful_pipeline_timestamp",
    )
    result = dict(value)
    result["last_successful_pipeline_timestamp"] = timestamp.isoformat()
    return result


def _validate_public_scores(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("Public scores must be a non-empty array")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"Public score record {index} must be an object")
        _reject_unknown_fields(item, PUBLIC_SCORE_FIELDS, f"Public score record {index}")
        _validate_public_attestations(item, f"Public score record {index}")
        _validate_no_private_lineage(item, f"$[{index}]")
        _validate_finite_json(item, f"$[{index}]")
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker or not ticker.replace(".", "").replace("-", "").isalnum():
            raise ValueError(f"Public score record {index} has an invalid ticker")
        if ticker in seen:
            raise ValueError(f"Duplicate public score ticker: {ticker}")
        seen.add(ticker)
        score = item.get("total_score")
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score):
            raise ValueError(f"Public score record {index} lacks a finite total_score")
        records.append({**item, "ticker": ticker, "public_view_notice": PUBLIC_SCORES_NOTICE})
    return records


def _validate_triplet(value: Any, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object or null")
    _reject_unknown_fields(value, PUBLIC_OPTION_TRIPLET_FIELDS, label)
    _validate_finite_json(value, label)


def _validate_option_candidate(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    _reject_unknown_fields(value, PUBLIC_OPTION_CANDIDATE_FIELDS, label)
    if "sell_limit_observation" in value:
        nested = value["sell_limit_observation"]
        if not isinstance(nested, dict):
            raise ValueError(f"{label}.sell_limit_observation must be an object")
        _reject_unknown_fields(nested, PUBLIC_OPTION_LIMIT_FIELDS, f"{label}.sell_limit_observation")
    for key in ("annualized_yield_pct", "effective_sale_price", "put_break_even"):
        if key in value:
            _validate_triplet(value[key], f"{label}.{key}")
    reasons = value.get("liquidity_reasons")
    if reasons is not None and (
        not isinstance(reasons, list) or not all(isinstance(item, str) for item in reasons)
    ):
        raise ValueError(f"{label}.liquidity_reasons must be an array of strings")
    _validate_finite_json(value, label)


def _validate_option_group(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    _reject_unknown_fields(value, PUBLIC_OPTION_GROUP_FIELDS, label)
    candidates = value.get("recommended_candidates")
    if not isinstance(candidates, list):
        raise ValueError(f"{label}.recommended_candidates must be an array")
    for index, candidate in enumerate(candidates):
        _validate_option_candidate(candidate, f"{label}.recommended_candidates[{index}]")
    _validate_finite_json(value, label)


def _validate_option_period(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    _reject_unknown_fields(value, PUBLIC_OPTION_PERIOD_FIELDS, label)
    for key in ("call_observations", "put_observations"):
        if key in value:
            _validate_option_group(value[key], f"{label}.{key}")
    _validate_finite_json(value, label)


def _validate_public_options(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("Public option snapshot must be a non-empty array")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"Public option record {index} must be an object")
        _reject_unknown_fields(item, PUBLIC_OPTION_FIELDS, f"Public option record {index}")
        _validate_public_attestations(item, f"Public option record {index}")
        for attestation in (
            "ibkr_connected",
            "brokerage_data_included",
            "account_data_included",
            "position_data_included",
        ):
            if item.get(attestation) is not False:
                raise ValueError(f"Public option record {index} must declare {attestation}=false")
        source = str(item.get("quote_source") or "").strip()
        if not source:
            raise ValueError(f"Public option record {index} lacks quote_source")
        periods = item.get("periods")
        if not isinstance(periods, dict):
            raise ValueError(f"Public option record {index} lacks periods")
        unknown_periods = sorted(set(periods).difference(PUBLIC_OPTION_PERIOD_NAMES))
        if unknown_periods:
            raise ValueError(
                f"Public option record {index}.periods contains unknown period(s): "
                + ", ".join(unknown_periods)
            )
        for period_name, period in periods.items():
            _validate_option_period(period, f"Public option record {index}.periods.{period_name}")
        _validate_no_private_lineage(
            item,
            f"$[{index}]",
            reject_broker_lineage=True,
        )
        _validate_finite_json(item, f"$[{index}]")
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker or not ticker.replace(".", "").replace("-", "").isalnum():
            raise ValueError(f"Public option record {index} has an invalid ticker")
        if ticker in seen:
            raise ValueError(f"Duplicate public option ticker: {ticker}")
        seen.add(ticker)
        records.append({**item, "ticker": ticker, "public_view_notice": PUBLIC_OPTIONS_NOTICE})
    return records


def _validate_public_source_views(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("Public source views must be an array")
    records: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"Public source-view record {index} must be an object")
        _reject_unknown_fields(
            item,
            PUBLIC_SOURCE_VIEW_FIELDS,
            f"Public source-view record {index}",
        )
        _validate_public_attestations(item, f"Public source-view record {index}")
        _validate_no_private_lineage(item, f"$[{index}]")
        _validate_finite_json(item, f"$[{index}]")
        author = str(item.get("author") or "").strip()
        summary = str(item.get("summary") or "").strip()
        raw_url = str(item.get("url") or "").strip()
        parsed = urlsplit(raw_url)
        if not author or not summary:
            raise ValueError(f"Public source-view record {index} lacks author/summary")
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError(f"Public source-view record {index} has an invalid HTTPS URL")
        records.append({**item, "public_view_notice": PUBLIC_SOURCE_VIEWS_NOTICE})
    return records


def _validate_public_report(text: str, path: Path) -> str:
    missing = [marker for marker in PUBLIC_REPORT_ATTESTATIONS if marker not in text]
    if missing:
        raise ValueError(
            f"Public report {path} lacks required public attestations: " + ", ".join(missing)
        )
    matches = [
        marker
        for marker in FORBIDDEN_PUBLIC_REPORT_MARKERS
        if marker.casefold() in text.casefold()
    ]
    if matches:
        raise ValueError(
            f"Public report {path} contains private/operator-only marker(s): "
            + ", ".join(matches)
        )
    return text


def _snapshot_object(
    *,
    logical_key: str,
    content: bytes,
    content_type: str,
    required: bool,
    source_path: str,
) -> SnapshotObject:
    if len(content) > MAX_PUBLIC_OBJECT_BYTES:
        raise ValueError(
            f"Public snapshot object {logical_key} exceeds {MAX_PUBLIC_OBJECT_BYTES} bytes"
        )
    return SnapshotObject(
        logical_key=logical_key,
        content=content,
        content_type=content_type,
        required=required,
        source_path=source_path,
    )


def collect_snapshot_objects() -> tuple[list[SnapshotObject], str]:
    objects: list[SnapshotObject] = []

    metadata_path = DATA_DIR / PUBLIC_METADATA_FILENAME
    if not metadata_path.is_file():
        raise FileNotFoundError("Required public snapshot metadata is missing")
    metadata = _validate_public_metadata(json.loads(metadata_path.read_text(encoding="utf-8")))
    public_as_of = str(metadata["last_successful_pipeline_timestamp"])
    objects.append(
        _snapshot_object(
            logical_key="public_snapshot_metadata:latest",
            content=_json_bytes(metadata),
            content_type="application/json; charset=utf-8",
            required=True,
            source_path=str(metadata_path.relative_to(BASE_DIR)),
        )
    )

    def add_text(key: str, path: Path, required: bool) -> None:
        if not path.is_file():
            if required:
                raise FileNotFoundError(f"Required public snapshot object missing: {key}")
            return
        text = _validate_public_report(path.read_text(encoding="utf-8"), path)
        objects.append(
            _snapshot_object(
                logical_key=key,
                content=text.encode("utf-8"),
                content_type="text/markdown; charset=utf-8",
                required=required,
                source_path=str(path.relative_to(BASE_DIR)),
            )
        )

    def add_json(
        key: str,
        path: Path,
        required: bool,
        transform: Callable[[Any], Any],
    ) -> None:
        if not path.is_file():
            if required:
                raise FileNotFoundError(f"Required public snapshot object missing: {key}")
            return
        value = transform(json.loads(path.read_text(encoding="utf-8")))
        objects.append(
            _snapshot_object(
                logical_key=key,
                content=_json_bytes(value),
                content_type="application/json; charset=utf-8",
                required=required,
                source_path=str(path.relative_to(BASE_DIR)),
            )
        )

    add_text("reports:latest", REPORTS_DIR / "public_briefing_latest.md", True)
    add_text("reports:morning:latest", REPORTS_DIR / "public_morning_latest.md", False)
    add_text("reports:evening:latest", REPORTS_DIR / "public_evening_latest.md", False)
    add_json(
        "scores:latest",
        DATA_DIR / PUBLIC_SCORES_FILENAME,
        True,
        _validate_public_scores,
    )
    add_json(
        "options:latest",
        DATA_DIR / PUBLIC_OPTIONS_FILENAME,
        True,
        _validate_public_options,
    )
    add_json(
        "source_views:latest",
        DATA_DIR / PUBLIC_SOURCE_VIEWS_FILENAME,
        False,
        _validate_public_source_views,
    )

    objects.append(
        _snapshot_object(
            logical_key="last_successful_pipeline_timestamp",
            content=public_as_of.encode("utf-8"),
            content_type="text/plain; charset=utf-8",
            required=True,
            source_path=str(metadata_path.relative_to(BASE_DIR)),
        )
    )
    total = sum(len(item.content) for item in objects)
    if total > MAX_PUBLIC_SNAPSHOT_BYTES:
        raise ValueError(f"Public snapshot exceeds {MAX_PUBLIC_SNAPSHOT_BYTES} bytes")
    return objects, public_as_of


class CloudflareKvClient:
    def __init__(self, *, account_id: str, namespace_id: str, api_token: str) -> None:
        self.base_url = (
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/storage/kv/"
            f"namespaces/{namespace_id}/values"
        )
        self.headers = {"Authorization": f"Bearer {api_token}"}
        self.session = _session()

    def put(self, key: str, content: bytes, content_type: str) -> None:
        response = self.session.put(
            f"{self.base_url}/{quote(key, safe='')}",
            headers={**self.headers, "Content-Type": content_type},
            data=content,
            timeout=(10, 45),
        )
        if not 200 <= response.status_code < 300:
            request_id = response.headers.get("cf-ray", "unknown")
            raise RuntimeError(
                f"Cloudflare KV PUT failed for {key}: HTTP {response.status_code}, cf-ray={request_id}"
            )


def build_manifest(run_id: str, objects: list[SnapshotObject], public_as_of: str) -> bytes:
    return _json_bytes(
        {
            "schema_version": 3,
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "public_data_as_of": public_as_of,
            "privacy_class": "public",
            "owner_watchlist_inherited": False,
            "line_options_scope": "public_only_no_broker_lineage",
            "objects": {
                item.logical_key: {
                    "physical_key": f"snapshot:{run_id}:{item.logical_key}",
                    "content_type": item.content_type,
                    "required": item.required,
                    "source_path": item.source_path,
                    "bytes": len(item.content),
                    "sha256": hashlib.sha256(item.content).hexdigest(),
                }
                for item in objects
            },
        }
    )


def _enforce_write_policy() -> None:
    if not env_bool("PUBLIC_KV_SYNC_ENABLED", False):
        raise RuntimeError("Network write requires PUBLIC_KV_SYNC_ENABLED=true")
    if not env_bool("FREE_ONLY_MODE", False):
        raise RuntimeError("Network write requires FREE_ONLY_MODE=true")
    if env_bool("PAID_FALLBACK_ENABLED", False):
        raise RuntimeError("Network write is forbidden while PAID_FALLBACK_ENABLED=true")
    if os.getenv("CLOUDFLARE_PLAN", "").strip().casefold() != "workers_free":
        raise RuntimeError("Network write requires CLOUDFLARE_PLAN=workers_free")


def sync_snapshot(*, dry_run: bool = True) -> dict[str, Any]:
    objects, public_as_of = collect_snapshot_objects()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    manifest = build_manifest(run_id, objects, public_as_of)
    summary = {
        "run_id": run_id,
        "object_count": len(objects),
        "total_bytes": sum(len(item.content) for item in objects) + len(manifest),
        "logical_keys": [item.logical_key for item in objects],
        "privacy_class": "public",
        "owner_watchlist_inherited": False,
        "line_options_scope": "public_only_no_broker_lineage",
        "public_data_as_of": public_as_of,
        "dry_run": dry_run,
    }
    if dry_run:
        logger.info("Public KV snapshot dry-run passed")
        return summary

    _enforce_write_policy()
    client = CloudflareKvClient(
        account_id=_required_env("CLOUDFLARE_ACCOUNT_ID"),
        namespace_id=_required_env("CLOUDFLARE_KV_NAMESPACE_ID"),
        api_token=_required_env("CLOUDFLARE_API_TOKEN"),
    )
    for item in objects:
        client.put(
            f"snapshot:{run_id}:{item.logical_key}",
            item.content,
            item.content_type,
        )
    manifest_key = f"snapshot:{run_id}:manifest"
    client.put(manifest_key, manifest, "application/json; charset=utf-8")
    client.put(
        "snapshot:current",
        _json_bytes(
            {
                "schema_version": 3,
                "run_id": run_id,
                "manifest_key": manifest_key,
                "promoted_at": datetime.now(timezone.utc).isoformat(),
                "public_data_as_of": public_as_of,
                "privacy_class": "public",
                "owner_watchlist_inherited": False,
                "line_options_scope": "public_only_no_broker_lineage",
            }
        ),
        "application/json; charset=utf-8",
    )
    logger.info("Promoted public KV snapshot %s", run_id)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform the network write; default is validation-only dry-run",
    )
    args = parser.parse_args()
    try:
        summary = sync_snapshot(dry_run=not args.apply)
    except (
        FileNotFoundError,
        ValueError,
        json.JSONDecodeError,
        RuntimeError,
        requests.RequestException,
    ) as exc:
        logger.error("Public KV sync failed: %s", exc)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
