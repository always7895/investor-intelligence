#!/usr/bin/env python3
"""Fail closed on unsafe authoritative adapter routing."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

# The reviewed portable CPython used by BARRY is launched in isolated mode and
# intentionally does not assume the repository working directory is importable.
# Add only this repository's static scripts directory before loading reviewed
# adapter modules; dynamic plugin discovery remains forbidden below.
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from adapters import ADAPTERS, EVIDENCE_BUILDERS  # noqa: E402
from authoritative_source_catalog import (  # noqa: E402
    SourceRecord,
    load_catalog as load_authoritative_catalog,
)

DEFAULT_CATALOG = ROOT / "config" / "authoritative-source-catalog.json"
DEFAULT_ROUTES = ROOT / "config" / "authoritative-adapter-routes.json"
STATIC_REGISTRY = ROOT / "scripts" / "adapters" / "__init__.py"

VALID_STATUSES = {
    "adapter_reviewed",
    "adapter_replay_required",
    "catalog_reviewed",
    "blocked",
}
FORBIDDEN_DYNAMIC_MARKERS = (
    "importlib",
    "__import__(",
    "pkgutil",
    "glob(",
    "exec(",
    "eval(",
)


class AdapterGateError(ValueError):
    """Raised when adapter/catalog routing violates a hard boundary."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise AdapterGateError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AdapterGateError(f"Expected an object in {path}")
    return value


def _source_document(source: SourceRecord) -> dict[str, Any]:
    value = asdict(source)
    for key in ("regions", "jurisdictions", "topics", "claim_types", "base_urls"):
        value[key] = list(value[key])
    value["gates"] = dict(source.gates)
    value["rate_limit"] = dict(source.rate_limit)
    return value


def catalog_source_map(path: Path = DEFAULT_CATALOG) -> dict[str, dict[str, Any]]:
    document = _object(path)
    raw = document.get("sources")
    if isinstance(raw, list):
        records = raw
    elif "fragment_paths" in document:
        try:
            _manifest, assembled, _warnings = load_authoritative_catalog(path)
        except (FileNotFoundError, ValueError) as exc:
            raise AdapterGateError(str(exc)) from exc
        records = [_source_document(source) for source in assembled]
    else:
        raise AdapterGateError("Authoritative source catalog requires sources or fragment_paths")

    result: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(records):
        if not isinstance(value, dict):
            raise AdapterGateError(f"sources[{index}] must be an object")
        source_id = str(value.get("id") or "").strip()
        if not source_id:
            raise AdapterGateError(f"sources[{index}] lacks id")
        if source_id in result:
            raise AdapterGateError(f"Duplicate source id: {source_id}")
        result[source_id] = value
    return result


def audit_adapter_routes(
    *,
    catalog_path: Path = DEFAULT_CATALOG,
    routes_path: Path = DEFAULT_ROUTES,
    static_registry_path: Path = STATIC_REGISTRY,
) -> list[str]:
    findings: list[str] = []
    sources = catalog_source_map(catalog_path)
    routes_document = _object(routes_path)

    if routes_document.get("schema_version") != 1:
        findings.append("authoritative-adapter-routes.json: schema_version must be 1")
    if routes_document.get("dynamic_adapter_loading") is not False:
        findings.append("authoritative-adapter-routes.json: dynamic_adapter_loading must be false")
    if routes_document.get("automatic_adapter_activation") is not False:
        findings.append("authoritative-adapter-routes.json: automatic_adapter_activation must be false")

    registry_text = static_registry_path.read_text(encoding="utf-8")
    for marker in FORBIDDEN_DYNAMIC_MARKERS:
        if marker in registry_text:
            findings.append(
                f"scripts/adapters/__init__.py: dynamic code-loading marker is forbidden: {marker}"
            )

    raw_routes = routes_document.get("routes")
    if not isinstance(raw_routes, list):
        return findings + ["authoritative-adapter-routes.json: routes must be an array"]

    seen_sources: set[str] = set()
    reviewed = 0
    pending = 0
    for index, route in enumerate(raw_routes):
        label = f"authoritative-adapter-routes.json routes[{index}]"
        if not isinstance(route, dict):
            findings.append(f"{label}: route must be an object")
            continue
        allowed_fields = {
            "source_id",
            "adapter_id",
            "adapter_status",
            "runtime_enabled",
            "fixture_tests_required",
            "claim_types",
            "notes",
        }
        unknown = sorted(set(route).difference(allowed_fields))
        if unknown:
            findings.append(f"{label}: unknown field(s): {', '.join(unknown)}")

        source_id = str(route.get("source_id") or "").strip()
        adapter_id = str(route.get("adapter_id") or "").strip()
        status = str(route.get("adapter_status") or "").strip()
        if not source_id or not adapter_id:
            findings.append(f"{label}: source_id and adapter_id are required")
            continue
        if source_id in seen_sources:
            findings.append(f"{label}: duplicate route for {source_id}")
        seen_sources.add(source_id)
        source = sources.get(source_id)
        if source is None:
            findings.append(f"{label}: source {source_id!r} is absent from the catalog")
            continue
        if status not in VALID_STATUSES:
            findings.append(f"{label}: unsupported adapter_status {status!r}")
        if route.get("runtime_enabled") is not False:
            findings.append(f"{label}: runtime_enabled must remain false in this draft")
        if source.get("runtime_enabled") is not False:
            findings.append(f"catalog source {source_id}: runtime_enabled must remain false")
        if route.get("fixture_tests_required") is not True:
            findings.append(f"{label}: fixture_tests_required must be true")
        claim_types = route.get("claim_types")
        if not isinstance(claim_types, list) or not claim_types or not all(
            isinstance(item, str) and item.strip() for item in claim_types
        ):
            findings.append(f"{label}: claim_types must be a non-empty string array")

        catalog_adapter_id = source.get("adapter_id")
        if catalog_adapter_id not in (None, adapter_id):
            findings.append(
                f"catalog source {source_id}: adapter_id {catalog_adapter_id!r} conflicts with route {adapter_id!r}"
            )

        if status == "adapter_reviewed":
            reviewed += 1
            if adapter_id not in ADAPTERS:
                findings.append(f"{label}: reviewed adapter {adapter_id!r} is not statically registered")
            if adapter_id not in EVIDENCE_BUILDERS:
                findings.append(f"{label}: reviewed adapter {adapter_id!r} lacks an evidence builder")
        elif status == "adapter_replay_required":
            pending += 1
            if adapter_id in ADAPTERS or adapter_id in EVIDENCE_BUILDERS:
                findings.append(
                    f"{label}: pending adapter {adapter_id!r} is already executable; review status must be updated atomically"
                )

    registered = set(ADAPTERS)
    routed_reviewed = {
        str(route.get("adapter_id"))
        for route in raw_routes
        if isinstance(route, dict) and route.get("adapter_status") == "adapter_reviewed"
    }
    unrouted = sorted(registered.difference(routed_reviewed))
    if unrouted:
        findings.append(
            "Static adapter registry contains reviewed code without an explicit reviewed route: "
            + ", ".join(unrouted)
        )
    if reviewed < 1:
        findings.append("At least one reviewed fixture-tested adapter route is required")

    audit_adapter_routes.last_summary = {
        "catalog_count": len(sources),
        "route_count": len(raw_routes),
        "reviewed_route_count": reviewed,
        "pending_replay_count": pending,
        "static_adapter_count": len(ADAPTERS),
        "runtime_enabled_count": sum(
            source.get("runtime_enabled") is True for source in sources.values()
        ),
    }
    return findings


audit_adapter_routes.last_summary = {}


def main() -> int:
    try:
        findings = audit_adapter_routes()
    except (FileNotFoundError, AdapterGateError, OSError) as exc:
        print(f"AUTHORITATIVE ADAPTER GATE FAILED\n- {exc}")
        return 1
    if findings:
        print("AUTHORITATIVE ADAPTER GATE FAILED")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("AUTHORITATIVE ADAPTER GATE PASSED")
    print(json.dumps(audit_adapter_routes.last_summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
