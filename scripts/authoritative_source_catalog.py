#!/usr/bin/env python3
"""Fail-closed authoritative source catalog and bounded run planner."""
from __future__ import annotations

import argparse
import copy
import ipaddress
import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = ROOT / "config" / "authoritative-source-catalog.json"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,95}$")
LOWER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
UPPER_RE = re.compile(r"^[A-Z][A-Z0-9_-]{1,31}$")
HOST_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{2,127}$")

MANIFEST_KEYS = {"schema_version", "catalog_policy", "runtime_defaults", "member_columns", "source_defaults", "fragment_paths", "catalog_source_count_snapshot", "catalog_source_count_snapshot_is_not_a_limit"}
POLICY = {"no_fixed_source_count_limit": True, "automatic_activation": False, "free_only": True, "public_data_only": True, "paywall_bypass_forbidden": True, "runtime_enable_requires_all_gates": True, "unknown_fields_fail_closed": True}
RUNTIME_KEYS = {"max_total_requests", "max_total_response_bytes", "max_wall_seconds", "max_requests_per_host", "max_concurrency_per_host", "max_retries_per_request", "connect_timeout_seconds", "read_timeout_seconds"}
DEFAULT_KEYS = {"cost", "rights_status", "redistribution_status", "attribution_required", "data_class", "runtime_enabled", "gates"}
GATE_KEYS = {"authority_reviewed", "rights_reviewed", "free_access_verified", "schema_reviewed", "privacy_reviewed", "adapter_tests_passed", "runtime_health_passed"}
FRAGMENT_KEYS = {"schema_version", "fragment_id", "automatic_activation", "members"}
COLUMNS = ("id", "display_name", "authority", "evidence_tier", "evidence_role", "regions", "jurisdictions", "topics", "claim_types", "official_docs_url", "base_urls", "transport", "authentication", "credential_env", "adapter_id", "adapter_status", "host_group", "freshness_class", "update_cadence_seconds", "max_requests_per_run", "estimated_requests_per_cycle", "estimated_response_bytes_per_cycle", "estimated_wall_seconds_per_cycle", "rate_limit_policy", "requests_per_minute", "requests_per_day", "notes")
TIERS = {"T0", "T1", "T2", "T3"}
ROLES = {"direct_primary", "official_statistical", "regulated_market", "public_market_observation", "corroboration_only", "discovery_only"}
TRANSPORTS = {"rest_json", "sdmx", "odata", "rss", "bulk_csv", "bulk_json", "bulk_xml", "official_download", "public_search"}
AUTH = {"none", "free_api_key", "free_registration"}
RIGHTS = {"reviewed_public_access", "review_before_enable"}
REDISTRIBUTION = {"public_attribution", "metadata_only", "review_before_enable"}
ADAPTERS = {"adapter_reviewed", "adapter_replay_required", "catalog_reviewed", "metadata_only", "blocked"}
FRESHNESS = {"event_driven", "intraday", "daily", "weekly", "monthly", "quarterly", "annual", "mixed"}
RATE_POLICIES = {"documented", "official_unspecified", "free_key_plan", "bulk_download"}
HEALTHY = {"HEALTHY", "DEGRADED"}
TIER_WEIGHT = {"T0": 400, "T1": 300, "T2": 200, "T3": 100}


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class SourceRecord:
    id: str
    display_name: str
    authority: str
    evidence_tier: str
    evidence_role: str
    regions: tuple[str, ...]
    jurisdictions: tuple[str, ...]
    topics: tuple[str, ...]
    claim_types: tuple[str, ...]
    official_docs_url: str
    base_urls: tuple[str, ...]
    transport: str
    authentication: str
    credential_env: str | None
    cost: str
    rights_status: str
    redistribution_status: str
    attribution_required: bool
    data_class: str
    adapter_id: str | None
    adapter_status: str
    runtime_enabled: bool
    host_group: str
    freshness_class: str
    update_cadence_seconds: int
    max_requests_per_run: int
    estimated_requests_per_cycle: int
    estimated_response_bytes_per_cycle: int
    estimated_wall_seconds_per_cycle: float
    rate_limit: Mapping[str, int | str | None]
    gates: Mapping[str, bool]
    notes: str


@dataclass(frozen=True)
class PlannedSource:
    source_id: str
    priority: int
    host_group: str
    estimated_requests: int
    estimated_response_bytes: int
    estimated_wall_seconds: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class SourceRunPlan:
    catalog_count: int
    runtime_enabled_count: int
    eligible_count: int
    selected: tuple[PlannedSource, ...]
    deferred: tuple[Mapping[str, Any], ...]
    planned_requests: int
    planned_response_bytes: int
    planned_wall_seconds: float
    host_request_totals: Mapping[str, int]
    request_budget: int
    byte_budget: int
    wall_budget_seconds: float
    max_requests_per_host: int
    max_concurrency_per_host: int
    source_count_cap: None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["source_count_cap"] = None
        return value


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CatalogError(f"{path}: expected a JSON object")
    return value


def _keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    missing, unknown = sorted(expected - set(value)), sorted(set(value) - expected)
    if missing:
        raise CatalogError(f"{label}: missing field(s): {', '.join(missing)}")
    if unknown:
        raise CatalogError(f"{label}: unknown field(s): {', '.join(unknown)}")


def _integer(value: Any, label: str, *, minimum: int = 1, maximum: int | None = None) -> int:
    if isinstance(value, bool):
        raise CatalogError(f"{label}: invalid integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise CatalogError(f"{label}: invalid integer") from exc
    if parsed < minimum or (maximum is not None and parsed > maximum):
        raise CatalogError(f"{label}: integer outside permitted range")
    return parsed


def _number(value: Any, label: str, *, maximum: float | None = None) -> float:
    if isinstance(value, bool):
        raise CatalogError(f"{label}: invalid number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise CatalogError(f"{label}: invalid number") from exc
    if parsed <= 0 or (maximum is not None and parsed > maximum):
        raise CatalogError(f"{label}: number outside permitted range")
    return parsed


def _labels(value: Any, label: str, pattern: re.Pattern[str]) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CatalogError(f"{label}: expected non-empty array")
    result = tuple(str(item).strip() for item in value)
    if len(set(result)) != len(result) or any(not pattern.fullmatch(item) for item in result):
        raise CatalogError(f"{label}: invalid or duplicate value")
    return result


def _host(value: str | None) -> str:
    if not value:
        return ""
    try:
        return value.rstrip(".").encode("idna").decode("ascii").casefold()
    except (UnicodeError, ValueError):
        return ""


def _url(value: Any, label: str) -> str:
    text = str(value or "").strip()
    try:
        parsed, port = urlsplit(text), urlsplit(text).port
    except ValueError as exc:
        raise CatalogError(f"{label}: invalid URL") from exc
    hostname = _host(parsed.hostname)
    if parsed.scheme.casefold() != "https" or not hostname or parsed.username or parsed.password or port not in (None, 443):
        raise CatalogError(f"{label}: URL must be credential-free HTTPS on port 443")
    if hostname == "localhost" or hostname.endswith(".local"):
        raise CatalogError(f"{label}: local hostname forbidden")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast or address.is_unspecified):
        raise CatalogError(f"{label}: non-public IP address forbidden")
    return text


def _runtime(value: Mapping[str, Any]) -> dict[str, Any]:
    _keys(value, RUNTIME_KEYS, "runtime_defaults")
    return {
        "max_total_requests": _integer(value["max_total_requests"], "max_total_requests"),
        "max_total_response_bytes": _integer(value["max_total_response_bytes"], "max_total_response_bytes"),
        "max_wall_seconds": _number(value["max_wall_seconds"], "max_wall_seconds"),
        "max_requests_per_host": _integer(value["max_requests_per_host"], "max_requests_per_host"),
        "max_concurrency_per_host": _integer(value["max_concurrency_per_host"], "max_concurrency_per_host", maximum=8),
        "max_retries_per_request": _integer(value["max_retries_per_request"], "max_retries_per_request", minimum=0, maximum=4),
        "connect_timeout_seconds": _integer(value["connect_timeout_seconds"], "connect_timeout_seconds", maximum=30),
        "read_timeout_seconds": _integer(value["read_timeout_seconds"], "read_timeout_seconds", maximum=120),
    }


def _manifest(value: Mapping[str, Any]) -> None:
    _keys(value, MANIFEST_KEYS, "catalog manifest")
    if value["schema_version"] != 1 or value["catalog_policy"] != POLICY:
        raise CatalogError("catalog manifest: schema/policy is not fail-closed")
    if not isinstance(value["runtime_defaults"], dict):
        raise CatalogError("runtime_defaults: expected object")
    _runtime(value["runtime_defaults"])
    if tuple(value["member_columns"]) != COLUMNS:
        raise CatalogError("member_columns: unexpected order or fields")
    defaults = value["source_defaults"]
    if not isinstance(defaults, dict):
        raise CatalogError("source_defaults: expected object")
    _keys(defaults, DEFAULT_KEYS, "source_defaults")
    if defaults["cost"] != "free" or defaults["data_class"] != "public" or defaults["runtime_enabled"] is not False:
        raise CatalogError("source_defaults: only disabled free public sources permitted")
    if defaults["rights_status"] not in RIGHTS or defaults["redistribution_status"] not in REDISTRIBUTION:
        raise CatalogError("source_defaults: invalid rights state")
    if not isinstance(defaults["gates"], dict):
        raise CatalogError("source_defaults.gates: expected object")
    _keys(defaults["gates"], GATE_KEYS, "source_defaults.gates")
    if any(not isinstance(v, bool) for v in defaults["gates"].values()):
        raise CatalogError("source_defaults.gates: booleans required")
    paths = value["fragment_paths"]
    if not isinstance(paths, list) or not paths or len(set(paths)) != len(paths):
        raise CatalogError("fragment_paths: non-empty unique array required")
    for path in paths:
        parts = Path(str(path).replace("\\", "/")).parts
        if not str(path).startswith("config/authoritative-sources/") or not str(path).endswith(".json") or ".." in parts:
            raise CatalogError(f"fragment_paths: unsafe path {path!r}")
    _integer(value["catalog_source_count_snapshot"], "catalog_source_count_snapshot", minimum=0)
    if value["catalog_source_count_snapshot_is_not_a_limit"] is not True:
        raise CatalogError("source-count snapshot must not be a cap")


def _record(row: Sequence[Any], defaults: Mapping[str, Any], label: str) -> SourceRecord:
    if len(row) != len(COLUMNS):
        raise CatalogError(f"{label}: expected {len(COLUMNS)} fields, found {len(row)}")
    raw = dict(zip(COLUMNS, row, strict=True))
    source_id = str(raw["id"] or "").strip()
    if not ID_RE.fullmatch(source_id):
        raise CatalogError(f"{label}: invalid source id")
    name, authority = str(raw["display_name"] or "").strip(), str(raw["authority"] or "").strip()
    tier, role = str(raw["evidence_tier"]), str(raw["evidence_role"])
    if len(name) < 3 or len(authority) < 2 or tier not in TIERS or role not in ROLES:
        raise CatalogError(f"{label}: invalid identity/evidence metadata")
    regions = _labels(raw["regions"], f"{label}.regions", UPPER_RE)
    jurisdictions = _labels(raw["jurisdictions"], f"{label}.jurisdictions", UPPER_RE)
    topics = _labels(raw["topics"], f"{label}.topics", LOWER_RE)
    claims = _labels(raw["claim_types"], f"{label}.claim_types", LOWER_RE)
    docs = _url(raw["official_docs_url"], f"{label}.official_docs_url")
    if not isinstance(raw["base_urls"], list) or not raw["base_urls"]:
        raise CatalogError(f"{label}.base_urls: non-empty array required")
    base_urls = tuple(_url(item, f"{label}.base_urls") for item in raw["base_urls"])
    if len(set(base_urls)) != len(base_urls):
        raise CatalogError(f"{label}.base_urls: duplicates forbidden")
    transport, auth = str(raw["transport"]), str(raw["authentication"])
    if transport not in TRANSPORTS or auth not in AUTH:
        raise CatalogError(f"{label}: invalid transport/authentication")
    credential = None if raw["credential_env"] is None else str(raw["credential_env"]).strip()
    if (auth == "none" and credential is not None) or (auth != "none" and (not credential or not TOKEN_RE.fullmatch(credential))):
        raise CatalogError(f"{label}: credential metadata conflicts with authentication")
    adapter_id = None if raw["adapter_id"] is None else str(raw["adapter_id"]).strip()
    adapter_status = str(raw["adapter_status"])
    if adapter_status not in ADAPTERS or (adapter_id and not ID_RE.fullmatch(adapter_id)) or (adapter_status in {"adapter_reviewed", "adapter_replay_required"} and not adapter_id):
        raise CatalogError(f"{label}: invalid adapter metadata")
    host_group = _host(str(raw["host_group"] or ""))
    if not HOST_RE.fullmatch(host_group) or host_group != _host(urlsplit(base_urls[0]).hostname):
        raise CatalogError(f"{label}: host_group must match first base URL")
    freshness = str(raw["freshness_class"])
    if freshness not in FRESHNESS:
        raise CatalogError(f"{label}: invalid freshness class")
    cadence = _integer(raw["update_cadence_seconds"], f"{label}.cadence")
    if cadence < 60:
        raise CatalogError(f"{label}: cadence below 60 seconds forbidden")
    maximum = _integer(raw["max_requests_per_run"], f"{label}.max_requests", maximum=10000)
    requests = _integer(raw["estimated_requests_per_cycle"], f"{label}.requests", maximum=10000)
    if requests > maximum:
        raise CatalogError(f"{label}: estimated requests exceed source maximum")
    response_bytes = _integer(raw["estimated_response_bytes_per_cycle"], f"{label}.bytes", maximum=1_073_741_824)
    seconds = _number(raw["estimated_wall_seconds_per_cycle"], f"{label}.seconds", maximum=3600)
    policy = str(raw["rate_limit_policy"])
    if policy not in RATE_POLICIES:
        raise CatalogError(f"{label}: invalid rate-limit policy")
    rpm = None if raw["requests_per_minute"] is None else _integer(raw["requests_per_minute"], f"{label}.rpm")
    rpd = None if raw["requests_per_day"] is None else _integer(raw["requests_per_day"], f"{label}.rpd")
    if auth != "none" and policy not in {"free_key_plan", "documented"}:
        raise CatalogError(f"{label}: credentialed source requires documented/free-key limits")
    d = copy.deepcopy(defaults)
    return SourceRecord(source_id, name, authority, tier, role, regions, jurisdictions, topics, claims, docs, base_urls, transport, auth, credential, str(d["cost"]), str(d["rights_status"]), str(d["redistribution_status"]), bool(d["attribution_required"]), str(d["data_class"]), adapter_id, adapter_status, bool(d["runtime_enabled"]), host_group, freshness, cadence, maximum, requests, response_bytes, seconds, {"policy": policy, "requests_per_minute": rpm, "requests_per_day": rpd}, dict(d["gates"]), str(raw["notes"] or "").strip())


def load_catalog(manifest_path: Path = DEFAULT_MANIFEST_PATH) -> tuple[dict[str, Any], list[SourceRecord], list[str]]:
    manifest_path = manifest_path.resolve()
    manifest = _json(manifest_path)
    _manifest(manifest)
    root = manifest_path.parents[1]
    sources: list[SourceRecord] = []
    fragments: set[str] = set()
    for relative in manifest["fragment_paths"]:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise CatalogError(f"fragment escapes repository root: {relative}") from exc
        fragment = _json(path)
        _keys(fragment, FRAGMENT_KEYS, f"fragment {relative}")
        fragment_id = str(fragment["fragment_id"] or "")
        if fragment["schema_version"] != 1 or fragment["automatic_activation"] is not False or not ID_RE.fullmatch(fragment_id) or fragment_id in fragments:
            raise CatalogError(f"fragment {relative}: invalid schema/id/activation")
        fragments.add(fragment_id)
        if not isinstance(fragment["members"], list):
            raise CatalogError(f"fragment {relative}: members must be array")
        for index, row in enumerate(fragment["members"]):
            if not isinstance(row, list):
                raise CatalogError(f"fragment {fragment_id}.members[{index}]: row must be array")
            sources.append(_record(row, manifest["source_defaults"], f"fragment {fragment_id}.members[{index}]"))
    duplicates = sorted(key for key, count in Counter(source.id for source in sources).items() if count > 1)
    if duplicates:
        raise CatalogError(f"duplicate source id(s): {', '.join(duplicates)}")
    warnings = []
    snapshot = int(manifest["catalog_source_count_snapshot"])
    if snapshot != len(sources):
        warnings.append(f"SOURCE_COUNT_SNAPSHOT_CHANGED:{snapshot}->{len(sources)}; informational only, no catalog cap")
    for source in sources:
        validate_runtime_activation(source, credentials={})
    return manifest, sources, warnings


def validate_runtime_activation(source: SourceRecord, *, credentials: Mapping[str, str] | None = None, require_enabled: bool = False) -> tuple[bool, str]:
    if not source.runtime_enabled:
        if require_enabled:
            raise CatalogError(f"{source.id}: runtime disabled")
        return False, "DISABLED"
    if source.cost != "free" or source.data_class != "public" or source.rights_status != "reviewed_public_access" or source.redistribution_status != "public_attribution":
        raise CatalogError(f"{source.id}: activation requires reviewed free public rights")
    if source.adapter_status != "adapter_reviewed" or not source.adapter_id:
        raise CatalogError(f"{source.id}: activation requires reviewed adapter")
    missing = sorted(key for key, value in source.gates.items() if value is not True)
    if missing:
        raise CatalogError(f"{source.id}: incomplete gates: {', '.join(missing)}")
    available = os.environ if credentials is None else credentials
    if source.authentication != "none" and (not source.credential_env or not str(available.get(source.credential_env, "")).strip()):
        return False, "FREE_CREDENTIAL_UNAVAILABLE"
    return True, "ELIGIBLE"


def plan_source_run(sources: Sequence[SourceRecord], runtime_defaults: Mapping[str, Any], *, requested_topics: Iterable[str] | None = None, health: Mapping[str, Any] | None = None, credentials: Mapping[str, str] | None = None) -> SourceRunPlan:
    budgets = _runtime(dict(runtime_defaults))
    requested = {str(item).strip().casefold() for item in requested_topics or [] if str(item).strip()}
    health_map, creds = health or {}, os.environ if credentials is None else credentials
    eligible: list[tuple[int, SourceRecord, tuple[str, ...]]] = []
    deferred: list[dict[str, Any]] = []
    for source in sources:
        try:
            active, reason = validate_runtime_activation(source, credentials=creds)
        except CatalogError as exc:
            deferred.append({"source_id": source.id, "reason": "INVALID_ACTIVATION", "detail": str(exc)})
            continue
        if not active:
            deferred.append({"source_id": source.id, "reason": reason})
            continue
        status_value = health_map.get(source.id, "PROBATION")
        if isinstance(status_value, dict):
            status_value = status_value.get("status")
        status = str(status_value or "PROBATION").upper()
        if status not in HEALTHY:
            deferred.append({"source_id": source.id, "reason": status})
            continue
        match = bool(requested.intersection(topic.casefold() for topic in source.topics))
        eligible.append((TIER_WEIGHT[source.evidence_tier] + (100 if match else 0), source, ("REQUESTED_TOPIC_MATCH",) if match else ("BACKGROUND_DUE_SOURCE",)))
    eligible.sort(key=lambda item: (-item[0], item[1].id))
    selected: list[PlannedSource] = []
    requests = response_bytes = 0
    seconds = 0.0
    host_totals: Counter[str] = Counter()
    for priority, source, reasons in eligible:
        nr = requests + source.estimated_requests_per_cycle
        nb = response_bytes + source.estimated_response_bytes_per_cycle
        ns = seconds + source.estimated_wall_seconds_per_cycle
        nh = host_totals[source.host_group] + source.estimated_requests_per_cycle
        exceeded = []
        if nr > budgets["max_total_requests"]:
            exceeded.append("total_requests")
        if nb > budgets["max_total_response_bytes"]:
            exceeded.append("total_response_bytes")
        if ns > budgets["max_wall_seconds"]:
            exceeded.append("wall_seconds")
        if nh > budgets["max_requests_per_host"]:
            exceeded.append("per_host_requests")
        if exceeded:
            deferred.append({"source_id": source.id, "reason": "RUNTIME_BUDGET_DEFERRED", "budgets": exceeded})
            continue
        selected.append(PlannedSource(source.id, priority, source.host_group, source.estimated_requests_per_cycle, source.estimated_response_bytes_per_cycle, source.estimated_wall_seconds_per_cycle, reasons))
        requests, response_bytes, seconds, host_totals[source.host_group] = nr, nb, ns, nh
    return SourceRunPlan(len(sources), sum(s.runtime_enabled for s in sources), len(eligible), tuple(selected), tuple(deferred), requests, response_bytes, round(seconds, 3), dict(host_totals), budgets["max_total_requests"], budgets["max_total_response_bytes"], budgets["max_wall_seconds"], budgets["max_requests_per_host"], budgets["max_concurrency_per_host"])


def inventory(sources: Sequence[SourceRecord]) -> dict[str, Any]:
    return {
        "source_count": len(sources),
        "runtime_enabled_count": sum(source.runtime_enabled for source in sources),
        "region_counts": dict(sorted(Counter(region for source in sources for region in source.regions).items())),
        "jurisdiction_counts": dict(sorted(Counter(item for source in sources for item in source.jurisdictions).items())),
        "tier_counts": dict(sorted(Counter(source.evidence_tier for source in sources).items())),
        "role_counts": dict(sorted(Counter(source.evidence_role for source in sources).items())),
        "transport_counts": dict(sorted(Counter(source.transport for source in sources).items())),
        "authentication_counts": dict(sorted(Counter(source.authentication for source in sources).items())),
        "adapter_status_counts": dict(sorted(Counter(source.adapter_status for source in sources).items())),
        "topic_counts": dict(sorted(Counter(topic for source in sources for topic in source.topics).items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--topic", action="append", default=[])
    parser.add_argument("--health", type=Path)
    args = parser.parse_args()
    try:
        manifest, sources, warnings = load_catalog(args.manifest)
        result: dict[str, Any] = {"valid": True, "policy": manifest["catalog_policy"], "inventory": inventory(sources), "warnings": warnings}
        if args.plan:
            result["plan"] = plan_source_run(sources, manifest["runtime_defaults"], requested_topics=args.topic, health=_json(args.health) if args.health else {}).as_dict()
    except (CatalogError, FileNotFoundError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
