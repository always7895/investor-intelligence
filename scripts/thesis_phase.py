#!/usr/bin/env python3
"""Time-aware thesis phase from dated, sourced signals (operator request 2026-09-25).

A candidate's (or an industry constraint's) phase is derived, not declared: each
signal carries its own date, source and independence family, expires after its
class window, and the phase is recomputed for any evaluation date. Screening
therefore changes with time as new evidence arrives and old evidence ages out,
and every result names the date when it should be re-checked.

Serenity is the primary lens (constraint → control → pricing → equity capture,
information gap). Signals tagged with a context-only lens (Leopold Aschenbrenner)
are reported but never counted toward any phase. Output is PROJECT_AUTHORED
inference: no probability, no price target, no score bonus.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "thesis-phase-policy-v1.json"
PHASES = ("INSUFFICIENT_EVIDENCE", "DISCOVERY", "EARLY_VALIDATION", "COMMERCIAL_VALIDATION",
          "INSTITUTIONAL_VALIDATION", "CONSENSUS", "RELIEVING", "BROKEN")
# The ranking engine has no RELIEVING state: it becomes CONSENSUS with shortage_relieved.
ENGINE_LIFECYCLE = {"RELIEVING": "CONSENSUS"}
DIRECTIONS = ("UP", "DOWN", "FLAT")


class ThesisPhaseError(ValueError):
    pass


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy.get("schema_version") != 1 or set(policy.get("phase_preference", [])) != set(PHASES):
        raise ThesisPhaseError("THESIS_PHASE_POLICY_INVALID")
    return policy


def _day(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T.*)?", value):
        return date.fromisoformat(value[:10])
    raise ThesisPhaseError("THESIS_SIGNAL_DATE_INVALID")


def validate_signal(signal: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    """Closed schema: kind, dated as_of, https source, independence family, optional value/direction/lens."""
    kinds = policy["signal_kinds"]
    kind = signal.get("kind")
    if kind not in kinds:
        raise ThesisPhaseError("THESIS_SIGNAL_KIND_INVALID")
    url = signal.get("source_url")
    if not isinstance(url, str) or not url.startswith("https://") or any(ch.isspace() for ch in url):
        raise ThesisPhaseError("THESIS_SIGNAL_SOURCE_INVALID")
    family = signal.get("evidence_family")
    if not isinstance(family, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,63}", family):
        raise ThesisPhaseError("THESIS_SIGNAL_FAMILY_INVALID")
    direction = signal.get("direction")
    if direction is not None and direction not in DIRECTIONS:
        raise ThesisPhaseError("THESIS_SIGNAL_DIRECTION_INVALID")
    value = signal.get("value")
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
        raise ThesisPhaseError("THESIS_SIGNAL_VALUE_INVALID")
    lens = signal.get("lens", "SERENITY")
    if not isinstance(lens, str):
        raise ThesisPhaseError("THESIS_SIGNAL_LENS_INVALID")
    as_of = _day(signal.get("as_of"))
    # A catalyst is dated at its event; announced_at says when it became known (default: its own date).
    announced = _day(signal["announced_at"]) if signal.get("announced_at") is not None else as_of
    return {"signal_id": str(signal.get("signal_id") or f"{kind}:{family}:{signal.get('as_of')}"),
            "kind": kind, "as_of": as_of, "announced_at": announced, "source_url": url, "evidence_family": family,
            "direction": direction, "value": value, "lens": lens,
            "claim_class": kinds[kind]["class"], "group": kinds[kind]["group"]}


def _expires(signal: Mapping[str, Any], policy: Mapping[str, Any]) -> date:
    return signal["as_of"] + timedelta(days=int(policy["signal_windows_days"][signal["claim_class"]]))


def _tightening(signal: Mapping[str, Any]) -> bool:
    if signal["group"] == "constraint":
        return True
    return signal["group"] == "constraint_or_relief" and signal["direction"] == "UP"


def _relief(signal: Mapping[str, Any]) -> bool:
    if signal["group"] == "relief":
        return True
    return signal["group"] == "constraint_or_relief" and signal["direction"] == "DOWN"


class _ThresholdUnavailable(Exception):
    """Private: a policy threshold needed only by a NEW display field is missing or not a finite non-bool number."""


def _display_threshold(limits: Mapping[str, Any], name: str) -> int | float:
    """Strict threshold reader for NEW display fields only (FINANCE-SPLIT-03-R1); legacy code keeps its own lookups.

    No default, repair or float conversion: a Python int (not bool) or a finite float is returned as configured;
    anything else raises _ThresholdUnavailable, which is caught only around the new display evaluations.
    """
    if name not in limits:
        raise _ThresholdUnavailable(name)
    value = limits[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)):
        raise _ThresholdUnavailable(name)
    return value


def assess_phase(signals: Iterable[Mapping[str, Any]], as_of: Any, *, policy: Mapping[str, Any] | None = None,
                 scope: str = "company") -> dict[str, Any]:
    """Phase at ``as_of`` from the signals dated on or before it and still inside their window.

    ``scope="industry"`` evaluates the constraint only (company capture, consensus
    and company falsifiers do not apply to an industry-level constraint).
    """
    policy = policy or load_policy()
    if scope not in ("company", "industry"):
        raise ThesisPhaseError("THESIS_SCOPE_INVALID")
    today = _day(as_of)
    limits = policy["thresholds"]
    context_lenses = set(policy.get("context_only_lenses", []))
    parsed = [validate_signal(signal, policy) for signal in signals]
    future = [s for s in parsed if s["as_of"] > today]
    known = [s for s in parsed if s["as_of"] <= today]
    active = [s for s in known if _expires(s, policy) >= today]
    expired = [s for s in known if _expires(s, policy) < today]
    context = [s for s in active if s["lens"] in context_lenses]
    counted = [s for s in active if s["lens"] not in context_lenses]
    if scope == "industry":
        counted = [s for s in counted if s["group"] not in ("capture", "consensus", "falsifier")]

    def families(rows: Sequence[Mapping[str, Any]]) -> list[str]:
        return sorted({row["evidence_family"] for row in rows})

    tightening = [s for s in counted if _tightening(s)]
    relief = [s for s in counted if _relief(s)]
    # Ramp evidence (design wins, qualification, reservations) counts unless it points down:
    # gains usually come before earnings confirm the ramp (Serenity, secondary 2026-05-26).
    capture = [s for s in counted if s["group"] == "capture" and (
        s["direction"] == "UP" or (s["kind"] == "RAMP_EVIDENCE" and s["direction"] != "DOWN"))]
    latest = {kind: max((s for s in counted if s["kind"] == kind), key=lambda s: s["as_of"], default=None)
              for kind in ("VALUATION_PERCENTILE", "COVERAGE_INITIATIONS", "HOLDER_CROWDING", "DILUTION", "ATM_CAPACITY")}
    dilution, atm = latest["DILUTION"], latest["ATM_CAPACITY"]
    killers = [s for s in counted if s["kind"] in ("THESIS_KILLER", "CUSTOMER_LOSS")]
    diluted = bool(dilution and (dilution["value"] or 0) >= limits["dilution_broken_pct"])
    # An active ATM near half of market cap blocks a long entry until it completes (later reading of 0 lifts it).
    atm_blocked = bool(atm and (atm["value"] or 0) >= limits["atm_block_pct_of_market_cap"])

    def classify_core(threshold: Callable[[str], Any]) -> tuple[str, list[str], list[Mapping[str, Any]]]:
        """The original phase chain without the numeric DILUTION/ATM entry blocks (FINANCE-SPLIT-03-R1).

        Thesis killers and customer loss stay operating falsifiers. Thresholds are read through ``threshold`` in the
        original order and short-circuits; it is the legacy lookup when this chain is the legacy result.
        """
        if killers:
            return "BROKEN", ["falsifier active: " + ", ".join(sorted({s["kind"] for s in killers}))], killers
        if len(families(relief)) >= threshold("relief_families") and relief and (
                not tightening or max(s["as_of"] for s in relief) >= max(s["as_of"] for s in tightening)):
            return ("RELIEVING",
                    [f"relief confirmed by {len(families(relief))} families and newer than the latest tightening signal"], relief)
        if not tightening:
            return "INSUFFICIENT_EVIDENCE", ["no active constraint signal"], []
        if len(families(tightening)) < threshold("confirmed_constraint_families"):
            return "DISCOVERY", ["constraint seen by one independent family only"], tightening
        if scope == "industry":
            return "EARLY_VALIDATION", [f"constraint confirmed by {len(families(tightening))} independent families"], tightening
        if not capture:
            return "EARLY_VALIDATION", ["constraint confirmed; no company-level capture (pricing or margin) yet"], tightening
        valuation = latest["VALUATION_PERCENTILE"]["value"] if latest["VALUATION_PERCENTILE"] else None
        coverage = latest["COVERAGE_INITIATIONS"]["value"] if latest["COVERAGE_INITIATIONS"] else None
        holders = latest["HOLDER_CROWDING"]["value"] if latest["HOLDER_CROWDING"] else None
        crowded = (valuation is not None and valuation >= threshold("valuation_crowded_percentile")) or (
            coverage is not None and coverage >= threshold("coverage_initiations_institutional")
            and holders is not None and holders >= threshold("holder_crowding_pct"))
        institutional = (valuation is not None and valuation >= threshold("valuation_institutional_percentile")) or (
            coverage is not None and coverage >= threshold("coverage_initiations_institutional"))
        if crowded:
            return ("CONSENSUS", ["capture visible and consensus crowded (valuation percentile or coverage plus holder crowding)"],
                    tightening + capture)
        if institutional:
            return "INSTITUTIONAL_VALIDATION", ["capture visible; institutions arriving"], tightening + capture
        return "COMMERCIAL_VALIDATION", ["constraint confirmed and company capture visible before consensus"], tightening + capture

    # Legacy gate, unchanged: the original numeric financing blocks (original latest picks and value-or-zero tests)
    # override the core exactly as before. Without a block the core IS the legacy result: it reads thresholds with the
    # original lookups and any original error propagates. With a block the core is a NEW display-only evaluation the old
    # code never reached: a threshold it needs that is missing or not a finite non-bool number makes only the new
    # operating fields unavailable (no default, no repair); every legacy field keeps the original BROKEN result.
    reasons: list[str]
    if diluted or atm_blocked:
        try:
            operating_phase, operating_reasons, operating_supporting = classify_core(
                lambda name: _display_threshold(limits, name))
        except _ThresholdUnavailable:
            operating_phase, operating_reasons, operating_supporting = None, ["OPERATING_POLICY_THRESHOLD_UNAVAILABLE"], []
        phase = "BROKEN"
        causes = sorted({s["kind"] for s in killers} | ({"DILUTION"} if diluted else set()) | ({"ATM_CAPACITY"} if atm_blocked else set()))
        reasons = ["falsifier active: " + ", ".join(causes)]
        supporting = killers + ([dilution] if diluted else []) + ([atm] if atm_blocked else [])
    else:
        operating_phase, operating_reasons, operating_supporting = classify_core(lambda name: limits[name])
        phase, reasons, supporting = operating_phase, list(operating_reasons), operating_supporting
    overhang = bool(
        (dilution and limits["dilution_overhang_pct"] <= (dilution["value"] or 0) < limits["dilution_broken_pct"])
        or (atm and limits["atm_overhang_pct_of_market_cap"] <= (atm["value"] or 0) < limits["atm_block_pct_of_market_cap"]))
    if overhang:
        reasons.append("dilution overhang: equity capture at risk")

    # Financing observations (FINANCE-SPLIT-03-R1), display only and never fed to the legacy gate, screen or preference.
    # Per kind, the latest as_of DATE GROUP of counted signals: any invalid value -> unknown, different valid values ->
    # conflict, no fallback to older rows; only then are thresholds read, each strictly and only when needed (an entry
    # block needs no overhang threshold). False below states only that both supplied observations are under the entry
    # block thresholds; it is never an entry permission, a safety certificate or complete financing coverage.
    financing_reason_codes: list[str] = []
    financing_support: set[str] = set()
    financing_blocked: bool | None = None
    if scope == "industry":
        financing_status = "NA"
        financing_reason_codes.append("FINANCING_NOT_APPLICABLE")
    else:
        levels: dict[str, str] = {}
        for kind, block_key, overhang_key in (("DILUTION", "dilution_broken_pct", "dilution_overhang_pct"),
                                              ("ATM_CAPACITY", "atm_block_pct_of_market_cap", "atm_overhang_pct_of_market_cap")):
            rows = [s for s in counted if s["kind"] == kind]
            if not rows:
                financing_reason_codes.append(f"{kind}_NO_APPLICABLE_OBSERVATION")
                continue
            newest = max(s["as_of"] for s in rows)
            group = [s for s in rows if s["as_of"] == newest]
            values = [s["value"] for s in group]
            if any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or (isinstance(value, float) and not math.isfinite(value))
                   or (kind == "ATM_CAPACITY" and value < 0) for value in values):
                financing_reason_codes.append(f"{kind}_LATEST_VALUE_INVALID")
                continue
            if len(set(values)) != 1:
                financing_reason_codes.append(f"{kind}_LATEST_VALUE_CONFLICT")
                continue
            try:
                if values[0] >= _display_threshold(limits, block_key):
                    level = "ENTRY_BLOCK_OBSERVED"
                elif values[0] >= _display_threshold(limits, overhang_key):
                    level = "OVERHANG_OBSERVED"
                else:
                    level = "BELOW_OVERHANG_OBSERVED"
            except _ThresholdUnavailable:
                financing_reason_codes.append(f"{kind}_POLICY_THRESHOLD_UNAVAILABLE")
                continue
            levels[kind] = level
            financing_reason_codes.append(f"{kind}_{level}")
            financing_support.update(s["signal_id"] for s in group)
        if "ENTRY_BLOCK_OBSERVED" in levels.values():
            financing_status, financing_blocked = "ENTRY_BLOCK_OBSERVED", True
        elif "OVERHANG_OBSERVED" in levels.values():
            financing_status, financing_blocked = "OVERHANG_OBSERVED", (False if len(levels) == 2 else None)
        elif len(levels) == 2:
            financing_status, financing_blocked = "BELOW_OVERHANG_OBSERVED", False
        else:
            financing_status = "UNKNOWN"
    # Only catalysts already announced by the evaluation date may schedule a review;
    # any other future-dated signal is unknown at that date (no look-ahead).
    catalysts = sorted(s["as_of"] for s in future if s["kind"] == "CATALYST" and s["announced_at"] <= today)
    expiries = sorted(_expires(s, policy) for s in supporting)
    next_review = min([*expiries[:1], *catalysts[:1]], default=None)
    return {
        "as_of": today.isoformat(), "scope": scope, "phase": phase,
        "engine_lifecycle": ENGINE_LIFECYCLE.get(phase, phase),
        "shortage_relieved": phase == "RELIEVING",
        "extreme_valuation_crowding": phase == "CONSENSUS",
        "dilution_overhang": overhang,
        "preference_rank": list(policy["phase_preference"]).index(phase) + 1,
        "constraint_families": families(tightening), "relief_families": families(relief),
        "capture_families": families(capture),
        "reasons": reasons,
        "supporting_signal_ids": sorted({s["signal_id"] for s in supporting}),
        "context_only_signal_ids": sorted(s["signal_id"] for s in context),
        "expired_signal_ids": sorted(s["signal_id"] for s in expired),
        "next_review_at": next_review.isoformat() if next_review else None,
        "authorship": policy["authorship"],
        "operating_phase": operating_phase,
        "operating_reasons": operating_reasons,
        "operating_supporting_signal_ids": sorted({s["signal_id"] for s in operating_supporting}),
        "financing_status": financing_status,
        "financing_reason_codes": financing_reason_codes,
        "financing_supporting_signal_ids": sorted(financing_support),
        "known_financing_entry_blocked": financing_blocked,
    }


def phase_timeline(signals: Sequence[Mapping[str, Any]], dates: Iterable[Any], *,
                   policy: Mapping[str, Any] | None = None, scope: str = "company") -> list[dict[str, Any]]:
    """Phase at each date plus the transitions, so a review shows when and why the view changed."""
    policy = policy or load_policy()
    rows, previous = [], None
    for when in sorted(_day(value) for value in dates):
        result = assess_phase(signals, when, policy=policy, scope=scope)
        rows.append({"as_of": result["as_of"], "phase": result["phase"], "changed": result["phase"] != previous,
                     "reasons": result["reasons"]})
        previous = result["phase"]
    return rows


def screen(candidates: Mapping[str, Sequence[Mapping[str, Any]]], as_of: Any, *,
           policy: Mapping[str, Any] | None = None, scope: str = "company") -> list[dict[str, Any]]:
    """Order candidates by phase preference, then by independent constraint families; BROKEN last."""
    policy = policy or load_policy()
    results = [{"subject": subject, **assess_phase(signals, as_of, policy=policy, scope=scope)}
               for subject, signals in candidates.items()]
    return sorted(results, key=lambda r: (r["preference_rank"], -len(r["constraint_families"]),
                                          -len(r["capture_families"]), r["subject"]))


if __name__ == "__main__":
    import argparse
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signals", type=Path, required=True, help="JSON object: subject -> list of signals")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--scope", choices=("company", "industry"), default="company")
    args = parser.parse_args()
    try:
        data = json.loads(args.signals.read_text(encoding="utf-8"))
        print(json.dumps(screen(data, args.as_of, scope=args.scope), ensure_ascii=False, indent=2))
    except (OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}))
        sys.exit(1)
