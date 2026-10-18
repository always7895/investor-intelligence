"""B3-PREVIEW-01: ordinary functional tests of the local in-memory revenue-guidance diagnostic preview
(scripts/revenue_guidance_preview.build_report_bundle) against in-memory fixtures shaped like the actual
order_forecast.build_v3 evidence (evidence.auto_update as produced by revenue_guidance_overlay: the
AutoAdmissionEvidence fields plus the snapshot's cutoff, input_digest and generation_sha256).

Isolated Qwen proposal (Qwen3.8-27B): ordinary in-memory functional coverage only - evidence projection,
deterministic ordering, WAITING/BLOCKED/SUSPENDED reason preservation, missing optional evidence and empty
inputs, repeatability, input immutability and JSON serialization. No boundary, adversarial, native,
filesystem, network or full-suite coverage; no model run, no state load, no production action.
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import revenue_guidance_preview as preview  # noqa: E402

SNAPSHOT_CUTOFF = "2026-09-28T12:00:00Z"
PREVIEW_CUTOFF = "2026-10-01T12:00:00Z"


def _identity() -> dict:
    return {"verifier_version": "auto-verify-v1", "normalizer_version": "normalize-v1",
            "implementation_sha256": "a" * 64, "profiles_sha256": "b" * 64,
            "baseline_registry_sha256": "c" * 64, "baseline_approval_sha256": "d" * 64}


def _auto_update(issuer: str, disposition: str, reason: str, admission_kind=None, generation_id="20260928T120000Z-000000000001") -> dict:
    """One auto_update block in the shape build_v3 seals (AutoAdmissionEvidence + snapshot digests)."""
    return {"version": "auto-admission-evidence-v1", "issuer": issuer, "disposition": disposition,
            "reason": reason, "admission_kind": admission_kind, "generation_id": generation_id,
            "identity": _identity(), "producer": None, "decisions": [], "consumed": [], "detections": [],
            "overflow": False, "receipt": None, "cutoff": SNAPSHOT_CUTOFF,
            "input_digest": "e" * 64, "generation_sha256": "f" * 64}


def _forecast(issuer: str, auto_update: dict | None, revenue_reason: str = "STALE",
              evidence_cutoff: str = SNAPSHOT_CUTOFF, with_evidence: bool = True) -> dict:
    """A minimal build_v3-shaped result whose evidence carries (or omits) auto_update."""
    forecast = {"version": 3, "issuer": issuer, "formula": "ORDERS-V3-01", "status": "UNAVAILABLE",
                "reason": revenue_reason, "revenue_status": "UNAVAILABLE", "revenue_basis": None,
                "revenue_reason": revenue_reason, "revenue_diagnostic": None,
                "horizon_convention": "FISCAL_2Q_4Q", "anchor_date": None, "cutoff": evidence_cutoff,
                "m6": {"status": "UNAVAILABLE", "reason": revenue_reason,
                       "scenario": {"status": "NO_BASIS", "reason": "NO_REVENUE_BASIS"}},
                "m12": {"status": "UNAVAILABLE", "reason": revenue_reason,
                        "scenario": {"status": "NO_BASIS", "reason": "NO_REVENUE_BASIS"}},
                "reported_quarters": [], "baseline_b": None, "forward_quarters": [], "warning": None,
                "contracted_recognition": None, "stock_sensitivity": None,
                "order_view": {"status": "UNAVAILABLE", "reason": revenue_reason, "m6": {}, "m12": {}},
                "references": [], "assumptions": "preview fixture"}
    if with_evidence:
        evidence = {"revenue_registry_status": "OK", "revenue_registry_sha256": "1" * 64, "cutoff": evidence_cutoff}
        if auto_update is not None:
            evidence["auto_update"] = auto_update
        forecast["evidence"] = evidence
    return forecast


def _mixed_forecasts() -> dict:
    return {
        "ZETA": _forecast("ZETA", _auto_update("ZETA", "SUSPENDED", "RECEIPT_RESULTS_PUBLISHED")),
        "ALPHA": _forecast("ALPHA", _auto_update("ALPHA", "WAITING", "EVENT_DETECTED")),
        "MU": _forecast("MU", _auto_update("MU", "BLOCKED", "APPROVAL_BINDING")),
        "OKCO": _forecast("OKCO", _auto_update("OKCO", "AUTO_VERIFIED", None, admission_kind="MACHINE_REPLAY"),
                         revenue_reason=None),
    }


class PreviewProjectionTest(unittest.TestCase):
    """1. Ordinary evidence projection and deterministic issuer/worklist order."""

    def test_issuers_sorted_and_worklist_deterministic(self) -> None:
        bundle = preview.build_report_bundle(forecasts=_mixed_forecasts(), cutoff=PREVIEW_CUTOFF)
        self.assertEqual([row["issuer"] for row in bundle["issuers"]], ["ALPHA", "MU", "OKCO", "ZETA"])
        self.assertEqual([row["issuer"] for row in bundle["worklist"]], ["ALPHA", "MU", "ZETA"])
        self.assertEqual([row["disposition"] for row in bundle["worklist"]], ["WAITING", "BLOCKED", "SUSPENDED"])
        self.assertEqual(bundle["issuer_count"], 4)
        self.assertEqual(bundle["summary"]["worklist_count"], 3)
        self.assertEqual(bundle["summary"]["auto_update_provided"], 4)
        # The AUTO_VERIFIED issuer is reported but is not a work item.
        self.assertNotIn("OKCO", [row["issuer"] for row in bundle["worklist"]])
        okco = next(row for row in bundle["issuers"] if row["issuer"] == "OKCO")
        self.assertEqual(okco["auto_update"]["disposition"], "AUTO_VERIFIED")
        self.assertEqual(okco["auto_update"]["admission_kind"], "MACHINE_REPLAY")
        again = preview.build_report_bundle(forecasts=_mixed_forecasts(), cutoff=PREVIEW_CUTOFF)
        self.assertEqual(bundle, again)
        self.assertEqual(json.dumps(bundle, sort_keys=True), json.dumps(again, sort_keys=True))

    def test_digests_and_cutoffs_are_projected_from_upstream(self) -> None:
        bundle = preview.build_report_bundle(forecasts=_mixed_forecasts(), cutoff=PREVIEW_CUTOFF)
        mu = next(row for row in bundle["issuers"] if row["issuer"] == "MU")
        self.assertEqual(mu["auto_update"]["input_digest"], "e" * 64)
        self.assertEqual(mu["auto_update"]["generation_sha256"], "f" * 64)
        self.assertEqual(mu["auto_update"]["snapshot_cutoff"], SNAPSHOT_CUTOFF)
        self.assertEqual(mu["upstream_reported"]["forecast_cutoff"], SNAPSHOT_CUTOFF)
        self.assertEqual(bundle["cutoff"], PREVIEW_CUTOFF)

    def test_cutoff_accepts_aware_datetime_or_instant_string(self) -> None:
        moment = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(preview.build_report_bundle(forecasts={}, cutoff=moment)["cutoff"], PREVIEW_CUTOFF)
        self.assertEqual(preview.build_report_bundle(forecasts={}, cutoff=PREVIEW_CUTOFF)["cutoff"], PREVIEW_CUTOFF)


class WorklistPreservationTest(unittest.TestCase):
    """2. WAITING / BLOCKED / SUSPENDED keep their original state and reason text."""

    def test_states_and_reason_text_are_preserved_verbatim(self) -> None:
        bundle = preview.build_report_bundle(forecasts=_mixed_forecasts(), cutoff=PREVIEW_CUTOFF)
        by_issuer = {row["issuer"]: row for row in bundle["issuers"]}
        self.assertEqual(by_issuer["ALPHA"]["auto_update"]["disposition"], "WAITING")
        self.assertEqual(by_issuer["ALPHA"]["auto_update"]["reason"], "EVENT_DETECTED")
        self.assertEqual(by_issuer["MU"]["auto_update"]["disposition"], "BLOCKED")
        self.assertEqual(by_issuer["MU"]["auto_update"]["reason"], "APPROVAL_BINDING")
        self.assertEqual(by_issuer["ZETA"]["auto_update"]["disposition"], "SUSPENDED")
        self.assertEqual(by_issuer["ZETA"]["auto_update"]["reason"], "RECEIPT_RESULTS_PUBLISHED")
        for row in bundle["worklist"]:
            source = by_issuer[row["issuer"]]["auto_update"]
            self.assertEqual(row["reason"], source["reason"])
            self.assertEqual(row["disposition"], source["disposition"])
        # Upstream-reported values are explicitly labelled, not claimed as re-verified.
        self.assertFalse(bundle["summary"]["independently_reverified"])
        self.assertEqual(bundle["summary"]["label"], "upstream-reported")
        self.assertIn("not independently reverified", by_issuer["MU"]["auto_update"]["note"])
        self.assertIn("not independently reverified", by_issuer["MU"]["upstream_reported"]["note"])


class MissingEvidenceTest(unittest.TestCase):
    """3. Normal missing optional evidence and empty inputs (NOT_PROVIDED, no inference)."""

    def test_missing_auto_update_is_not_provided(self) -> None:
        forecasts = {
            "NOEVIDENCE": _forecast("NOEVIDENCE", None, revenue_reason="NOT_DISCLOSED"),
            "NOEVBLOCK": _forecast("NOEVBLOCK", None, revenue_reason="INVALID"),
        }
        bundle = preview.build_report_bundle(forecasts=forecasts, cutoff=PREVIEW_CUTOFF)
        for row in bundle["issuers"]:
            self.assertFalse(row["auto_update"]["provided"])
            self.assertEqual(row["auto_update"]["disposition"], "NOT_PROVIDED")
            self.assertIsNone(row["auto_update"]["input_digest"])
            self.assertIsNone(row["auto_update"]["generation_sha256"])
            note = row["auto_update"]["note"]
            # The missing-evidence note is an explicit unknown-work diagnostic, never a zero-work claim.
            self.assertIn("NOT_PROVIDED", note)
            self.assertIn("UNKNOWN", note)
            self.assertIn("UNASSESSED", note)
            self.assertIn("does not prove no pending work", note)
            self.assertIn("infers no disposition", note)
        # An empty candidate worklist here is the NOT_PROVIDED projection, not proof of no pending work.
        self.assertEqual(bundle["worklist"], [])
        self.assertEqual(bundle["summary"]["worklist_count"], 0)
        self.assertEqual(bundle["summary"]["auto_update_not_provided"], 2)

    def test_forecast_without_evidence_key_and_non_mapping_value(self) -> None:
        bundle = preview.build_report_bundle(forecasts={"BARE": {"issuer": "BARE"}, "ODD": "not a mapping"},
                                            cutoff=PREVIEW_CUTOFF)
        for row in bundle["issuers"]:
            self.assertFalse(row["auto_update"]["provided"])
            self.assertIsNone(row["upstream_reported"]["forecast_cutoff"])
        self.assertEqual(bundle["worklist"], [])

    def test_empty_forecasts(self) -> None:
        bundle = preview.build_report_bundle(forecasts={}, cutoff=PREVIEW_CUTOFF)
        self.assertEqual(bundle["issuer_count"], 0)
        self.assertEqual(bundle["issuers"], [])
        self.assertEqual(bundle["worklist"], [])
        self.assertEqual(bundle["summary"]["auto_update_provided"], 0)
        self.assertEqual(bundle["summary"]["worklist_count"], 0)


class RepeatabilityTest(unittest.TestCase):
    """4. Repeatability, input immutability and JSON serialization."""

    def test_input_is_not_mutated_and_output_is_stable(self) -> None:
        forecasts = _mixed_forecasts()
        original = copy.deepcopy(forecasts)
        bundle = preview.build_report_bundle(forecasts=forecasts, cutoff=PREVIEW_CUTOFF)
        self.assertEqual(forecasts, original)
        mutated_text = json.dumps(bundle, sort_keys=True)
        forecasts["MU"]["evidence"]["auto_update"]["reason"] = "TAMPERED"
        forecasts["ALPHA"]["evidence"]["auto_update"]["disposition"] = "CURATED"
        forecasts["ZETA"]["evidence"].pop("auto_update")
        self.assertEqual(forecasts["MU"]["evidence"]["auto_update"]["reason"], "TAMPERED")  # the input did change
        self.assertEqual(json.dumps(bundle, sort_keys=True), mutated_text)  # ...and the bundle is unaffected
        self.assertEqual(bundle["worklist"][2]["reason"], "RECEIPT_RESULTS_PUBLISHED")

    def test_bundle_is_json_serializable_and_round_trips(self) -> None:
        bundle = preview.build_report_bundle(forecasts=_mixed_forecasts(), cutoff=PREVIEW_CUTOFF)
        self.assertEqual(json.loads(json.dumps(bundle)), bundle)
        self.assertFalse(bundle["execution_enabled"])
        self.assertFalse(bundle["publication_eligible"])
        self.assertTrue(bundle["preview_only"])
        self.assertEqual(bundle["schema"], "revenue-guidance-preview-v1")
        self.assertEqual(bundle["worklist_note"],
                         "Candidate work list only: not a schedule, an execution decision or a task-budget commitment.")


if __name__ == "__main__":
    unittest.main()
