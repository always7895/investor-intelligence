"""CANDIDATE_ADMISSION_READINESS_V1 - deterministic readiness audit.

Evaluates one bottleneck candidate's claims against the 4 mandatory pillars
(Dependency, Scarcity, Pricing Power, Company Capture) through
bottleneck_claim_admission.reconcile_factor_authority (which delegates to
company_claim_admission_bridge.bridge_reconcile_factors) and emits a
deterministic, fail-closed readiness JSON.

Invariants:
- admission is ADMISSION_QUALIFIED only when ALL four factors are licensed AND
  core_admitted AND >= 2 independent lineage families corroborate the corpus;
- runtime_admitted_claims is STRICTLY 0 - this evaluator admits nothing at
  runtime; it only measures distance to typed admission;
- zero network: everything is read from in-memory candidate JSON + a static
  registry; no provider is contacted.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import bottleneck_ranking as engine  # noqa: E402
from bottleneck_claim_admission import reconcile_factor_authority  # noqa: E402

SCHEMA = "CANDIDATE_ADMISSION_READINESS_V1"
QUALIFIED = "ADMISSION_QUALIFIED"
BLOCKED = "ADMISSION_BLOCKED_INSUFFICIENT_EVIDENCE"

PILLARS = ("dependency", "scarcity", "pricing_power", "company_capture")
_LICENSE_KEY = {
    "dependency": "dependency_licensed",
    "scarcity": "scarcity_licensed",
    "pricing_power": "pricing_licensed",
    "company_capture": "capture_licensed",
}
_EVIDENCE_KEY = {
    "dependency": "dependency_evidence",
    "scarcity": "scarcity_evidence",
    "pricing_power": "pricing_evidence",
    "company_capture": "company_capture_evidence",
}


def _finite_zero_default(value: Any) -> float:
    try:
        if isinstance(value, bool) or value is None:
            return 0.0
        f = float(value)
        if f != f or f in (float("inf"), float("-inf")):
            return 0.0
        return f
    except (TypeError, ValueError):
        return 0.0


def evidence_present(candidate: Mapping[str, Any], pillar: str) -> bool:
    """True when the candidate carries substantive (non-generic) pillar evidence."""
    ev = candidate.get(_EVIDENCE_KEY[pillar])
    if not isinstance(ev, Mapping) or not ev:
        return False
    score = _finite_zero_default(ev.get("score"))
    if pillar == "dependency":
        # generic revenue numbers do not count; architecture layer or a scored
        # criticality figure is required
        return bool(ev.get("irreplaceable_architecture_layer")) or bool(ev.get("high_criticality_subsystem")) or score > 0
    if pillar == "scarcity":
        # generic backlog does not count; switching latency or supplier-cap proof
        months = _finite_zero_default(ev.get("switching_time_months"))
        count = ev.get("effective_suppliers_count")
        return (
            bool(ev.get("corroborated_scarcity"))
            or months >= 12
            or (isinstance(count, int) and not isinstance(count, bool) and 0 < count <= 2)
        )
    if pillar == "pricing_power":
        return bool(ev.get("contractual_price_increases_documented")) or bool(ev.get("realized_margin_expansion")) or score > 0
    # company_capture
    return (
        bool(ev.get("dominant_bom_share"))
        or bool(ev.get("bom_share_capture"))
        or bool(ev.get("layer_profit_capture"))
        or score > 0
    )


def lineage_count(candidate: Mapping[str, Any]) -> int:
    """Distinct independent evidence families across source observations."""
    groups = set()
    for o in candidate.get("source_observations") or []:
        if not isinstance(o, Mapping):
            continue
        payload = o.get("payload") if isinstance(o.get("payload"), Mapping) else {}
        family = str(o.get("origin_group") or payload.get("origin_group") or "").strip()
        if family:
            groups.add(family)
            continue
        url = str(o.get("canonical_url") or "")
        host = url.split("://", 1)[-1].split("/", 1)[0]
        groups.add("host:" + (host if host else "unknown"))
    return len(groups)


def evaluate_readiness(
    candidate: Mapping[str, Any],
    *,
    registry: Any = None,
    health_states: Optional[Mapping[str, str]] = None,
    now: Optional[datetime] = None,
    fixture_mode: Optional[bool] = None,  # None -> bridge auto-detects synthetic .example fixtures
) -> dict[str, Any]:
    """Deterministic scarcity->admission audit for ONE candidate. Fail-closed."""
    cand = copy.deepcopy(dict(candidate))
    ticker = str(cand.get("ticker") or "UNKNOWN")
    blocker_set: set[str] = set()
    blockers: list[str] = []

    if registry is None:
        blockers.append("missing_registry")
    as_of = None
    if now is not None:
        as_of = now.isoformat().replace("+00:00", "Z") if hasattr(now, "isoformat") else str(now)
    else:
        as_of = str(cand.get("as_of") or None)

    clock = now
    if clock is None:
        try:
            clock = engine.parse_clock(str(cand.get("as_of") or ""))
        except Exception:
            clock = None
    if clock is None:
        blockers.append("missing_or_invalid_clock")

    claims_check: dict[str, Any] = {}
    if registry is not None:
        try:
            claims_check = engine.validate_claim_evidence(
                cand,
                clock,
                health_states=health_states,
                registry=registry,
            )
        except Exception as exc:  # static fail-closed on any pipeline surprise
            blockers.append(f"claims_pipeline_error:{type(exc).__name__}")
    else:
        claims_check = {"claims": [], "has_claims": False, "all_supported": False,
                        "conflict_count": 0, "claims_unconflicted": True}

    has_claims = bool(claims_check.get("has_claims"))
    if not has_claims:
        blockers.append("no_claims")
    if not bool(claims_check.get("all_supported", False)):
        blockers.append("claims_unsupported")
    if (claims_check.get("conflict_count", 0) or 0) > 0 or not bool(claims_check.get("claims_unconflicted", True)):
        blockers.append("claims_conflicted")

    lines = lineage_count(cand)
    if lines < 2:
        blockers.append(f"single_lineage_only(count={lines})")

    bridge = {"core_admitted": False, "admission_tier": "UNADMITTED", "financing_state": "UNKNOWN",
              "missing_core": list(PILLARS), "diagnostics": ["No bridge evaluation (missing registry?)"]}
    if registry is not None:
        bridge = reconcile_factor_authority(
            cand,
            claims_check.get("claims", []),
            ticker,
            now=now,
            fixture_mode=fixture_mode,
        )

    pillars: dict[str, dict[str, Any]] = {}
    satisfied: list[str] = []
    missing: list[str] = []
    for p in PILLARS:
        licensed = bool(bridge.get(_LICENSE_KEY[p], False))
        present = evidence_present(cand, p)
        ok = licensed and present
        pillars[p] = {"licensed": licensed, "evidence_present": present, "satisfied": ok}
        if ok:
            satisfied.append(p)
        else:
            missing.append(p)
            blockers.append(f"missing_pillar:{p}")

    financing = str(bridge.get("financing_state") or "UNKNOWN").upper()
    if financing == "DESTROYED":
        blockers.append("financing_destroyed")
    if not bool(bridge.get("core_admitted", False)):
        blockers.append("core_not_admitted")

    qualified = (
        len(missing) == 0
        and lines >= 2
        and has_claims
        and claims_check.get("all_supported") is True
        and (claims_check.get("conflict_count", 0) or 0) == 0
        and bool(bridge.get("core_admitted", False))
        and financing not in {"DESTROYED", "STRUCTURAL_DISQUALIFIER"}
    )

    claim_statuses = {}
    for c in claims_check.get("claims", []) or []:
        st = str(c.get("status") or "UNAVAILABLE") if isinstance(c, Mapping) else "UNAVAILABLE"
        claim_statuses[st] = claim_statuses.get(st, 0) + 1

    # Deterministic, additive proximity score (0-100; informational only - it
    # never confers admission on its own):
    #   +25 per satisfied pillar (max 100 -> capped below), +25 lineage >= 2,
    #   +25 core admitted. Cap at 100.
    readiness_score = min(
        100,
        25 * len(satisfied)
        + (25 if lines >= 2 else 0)
        + (25 if bool(bridge.get("core_admitted", False)) else 0),
    )

    out = {
        "schema": SCHEMA,
        "ticker": ticker,
        "as_of": as_of,
        "admission": QUALIFIED if qualified else BLOCKED,
        "satisfied_pillars": satisfied,
        "missing_pillars": missing,
        "pillars": pillars,
        "lineage_count": lines,
        "financing_state": financing,
        "runtime_admitted_claims": 0,  # STRICT invariant: never ghost-allow
        "readiness_score": readiness_score,
        "claims_status_counts": claim_statuses,
        "promotion_basis": "TEST_ONLY_FIXTURE" if (qualified and fixture_mode) else "NONE",
        "fail_closed": True,
        "blockers": sorted(set(blockers)),
        "bridge": {
            "core_admitted": bool(bridge.get("core_admitted", False)),
            "admission_tier": str(bridge.get("admission_tier")),
            "financing_state": financing,
            "missing_core": list(bridge.get("missing_core") or []),
            "diagnostics": list(bridge.get("diagnostics") or []),
        },
    }
    return out


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="CANDIDATE_ADMISSION_READINESS_V1")
    parser.add_argument("--candidate", required=True, help="Candidate JSON path")
    parser.add_argument("--registry", default=None, help="Optional registry path (JSON provider registry)")
    parser.add_argument("--as-of", default=None, help="ISO-8601 evaluation clock")
    parser.add_argument("--output", default=None, help="Optional output path (default stdout)")
    args = parser.parse_args(argv)

    try:
        cand_raw = Path(args.candidate).read_text(encoding="utf-8-sig")
        cand = json.loads(cand_raw)
    except Exception as exc:
        print(json.dumps({"schema": SCHEMA, "admission": BLOCKED, "fatal": f"INVALID_CANDIDATE:{type(exc).__name__}", "runtime_admitted_claims": 0}, sort_keys=True, indent=2))
        return 1

    registry = None
    if args.registry:
        try:
            registry = engine.load_json(Path(args.registry))
        except Exception as exc:
            print(json.dumps({"schema": SCHEMA, "admission": BLOCKED, "fatal": f"INVALID_REGISTRY:{type(exc).__name__}", "runtime_admitted_claims": 0}, sort_keys=True, indent=2))
            return 1

    now = None
    if args.as_of:
        try:
            now = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
        except ValueError:
            print(json.dumps({"schema": SCHEMA, "admission": BLOCKED, "fatal": "MALFORMED_AS_OF", "runtime_admitted_claims": 0}, sort_keys=True, indent=2))
            return 1

    health_states = None
    if registry is not None:
        try:
            ids = [s.source_id if hasattr(s, "source_id") else str(s) for s in registry.by_id()]
            health_states = {s: "HEALTHY" for s in ids}
        except Exception:
            health_states = None

    result = evaluate_readiness(cand, registry=registry, health_states=health_states, now=now)
    text = json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())