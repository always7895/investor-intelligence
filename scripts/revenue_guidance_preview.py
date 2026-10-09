"""Local in-memory diagnostic preview of the revenue-guidance auto-update lane (B3-PREVIEW-01).

A pure projection over already-loaded ``order_forecast.build_v3()`` results (see
``docs/REVENUE_GUIDANCE_AUTOUPDATE.md``). It reports what the upstream evidence says - the per-issuer
disposition and reason carried in ``evidence.auto_update``, and the snapshot's own input and generation
digests - and builds a deterministic human worklist of the issuers whose disposition is WAITING, BLOCKED
or SUSPENDED, each retaining its original reason text.

Scope (local diagnostic only):
- The function runs no model, loads no state and touches no file. It reads the sealed upstream fields of
  the given forecasts and projects them; it never re-derives, re-verifies or re-admits anything.
- A missing ``evidence.auto_update`` is reported as NOT_PROVIDED with outstanding work UNKNOWN
  (UNASSESSED): an empty candidate worklist does not prove no pending work, and no disposition, no
  success, no update and no "zero outstanding work" is inferred from its absence.
- The bundle always carries ``execution_enabled=false`` and ``publication_eligible=false``. These are new
  local preview fields of this schema; they are not operational feature flags and do not change any
  existing observation/publication schema, operational caller or CLI.
- The worklist is a candidate work list for human review only: it is not a schedule, an execution
  decision or a task-budget commitment.
- Upstream AUTO_VERIFIED dispositions are reported as upstream-reported values; this preview does not
  independently prove them. B3 sealed wire schema, Worker readers, ledger file loading, B2 daily-caller
  integration and task-budget enforcement are all out of scope (see the documentation).

No new dependencies: standard library only (``re``, ``typing``, ``datetime``).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping

PREVIEW_SCHEMA = "revenue-guidance-preview-v1"
# The dispositions that retain a human work item; their original reason text travels unchanged.
WORKLIST_DISPOSITIONS = ("WAITING", "BLOCKED", "SUSPENDED")
_NOT_REVERIFIED = "upstream-reported; not independently reverified by this preview"
_INFER_NOTHING = ("no evidence.auto_update in the upstream forecast: disposition NOT_PROVIDED and outstanding "
                   "work UNKNOWN (UNASSESSED); an empty candidate worklist does not prove no pending work. "
                   "This preview infers no disposition, no success and no update from the absence of the "
                   "evidence.")
_WORKLIST_NOTE = "Candidate work list only: not a schedule, an execution decision or a task-budget commitment."
_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _normalize_cutoff(cutoff: Any) -> str:
    """The preview's own cutoff as the producer's UTC instant string (an argument error raises ValueError)."""
    if isinstance(cutoff, datetime):
        if cutoff.tzinfo is None:
            raise ValueError("cutoff must be an aware datetime or a 'YYYY-MM-DDTHH:MM:SSZ' string")
        moment = cutoff.astimezone(timezone.utc).replace(microsecond=0)
        return moment.strftime(_FORMAT)
    if isinstance(cutoff, str) and _INSTANT.match(cutoff):
        return cutoff
    raise ValueError("cutoff must be an aware datetime or a 'YYYY-MM-DDTHH:MM:SSZ' string")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _auto_update_projection(evidence: Any) -> dict[str, Any]:
    """The projected ``evidence.auto_update`` fields, or the NOT_PROVIDED marker (no inference)."""
    auto = _mapping(evidence).get("auto_update") if isinstance(evidence, Mapping) else None
    if not isinstance(auto, Mapping):
        return {"provided": False, "evidence_version": None, "disposition": "NOT_PROVIDED", "reason": None,
                "admission_kind": None, "generation_id": None, "snapshot_cutoff": None, "input_digest": None,
                "generation_sha256": None, "note": _INFER_NOTHING}
    return {"provided": True, "evidence_version": auto.get("version"), "disposition": auto.get("disposition"),
            "reason": auto.get("reason"), "admission_kind": auto.get("admission_kind"),
            "generation_id": auto.get("generation_id"), "snapshot_cutoff": auto.get("cutoff"),
            "input_digest": auto.get("input_digest"), "generation_sha256": auto.get("generation_sha256"),
            "note": _NOT_REVERIFIED}


def _upstream_projection(forecast: Mapping[str, Any]) -> dict[str, Any]:
    """The upstream-reported forecast state (the sealed build_v3 values, not re-verified here)."""
    evidence = _mapping(forecast.get("evidence"))
    return {"forecast_status": forecast.get("status"), "revenue_status": forecast.get("revenue_status"),
            "revenue_reason": forecast.get("revenue_reason"), "revenue_diagnostic": forecast.get("revenue_diagnostic"),
            "forecast_cutoff": evidence.get("cutoff"), "note": _NOT_REVERIFIED}


def build_report_bundle(*, forecasts: Mapping[str, Any], cutoff: Any) -> dict[str, Any]:
    """The deterministic local diagnostic bundle over issuer-indexed ``build_v3`` results.

    ``forecasts`` maps issuer symbol to an already loaded ``order_forecast.build_v3()`` result (a mapping).
    The function is pure: it projects the sealed upstream fields (disposition, reason, the snapshot cutoff,
    the original input and generation digests), keeps the WAITING / BLOCKED / SUSPENDED issuers as a sorted
    candidate worklist with their original reason text, and marks a missing ``evidence.auto_update`` as
    NOT_PROVIDED. It does not run the model, load state, mutate its inputs, or generate revenue, scores,
    freshness, admission or publication eligibility. The result is JSON-serializable.
    """
    cutoff_instant = _normalize_cutoff(cutoff)
    issuers: list[dict[str, Any]] = []
    worklist: list[dict[str, Any]] = []
    provided = 0
    for symbol in sorted(forecasts):
        forecast = _mapping(forecasts.get(symbol))
        auto = _auto_update_projection(_mapping(forecast).get("evidence"))
        issuers.append({"issuer": symbol, "upstream_reported": _upstream_projection(forecast),
                        "auto_update": auto})
        if auto["provided"]:
            provided += 1
            if auto["disposition"] in WORKLIST_DISPOSITIONS:
                worklist.append({"issuer": symbol, "disposition": auto["disposition"], "reason": auto["reason"]})
    order = {disposition: rank for rank, disposition in enumerate(WORKLIST_DISPOSITIONS)}
    worklist.sort(key=lambda item: (order.get(item["disposition"], len(order)), item["issuer"]))
    return {
        "schema": PREVIEW_SCHEMA,
        "preview_only": True,
        "execution_enabled": False,
        "publication_eligible": False,
        "cutoff": cutoff_instant,
        "issuer_count": len(issuers),
        "issuers": issuers,
        "worklist": worklist,
        "worklist_note": _WORKLIST_NOTE,
        "summary": {"label": "upstream-reported", "independently_reverified": False,
                    "auto_update_provided": provided,
                    "auto_update_not_provided": len(issuers) - provided,
                    "worklist_count": len(worklist)},
    }
