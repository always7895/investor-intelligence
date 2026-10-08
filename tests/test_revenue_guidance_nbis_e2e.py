"""Synthetic NBIS MACHINE_REPLAY; never genuine admission or enablement."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tests import nbis_e2e_support as h
from tests import nbis_synthetic_sources as f


class NbisEndToEnd(unittest.TestCase):
    def test_n3_1_machine_replay(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-g4-e2e-") as tmp:
            chains = []
            def admission():
                chain = h.Chain(Path(tmp))
                chains.append(chain)
                item = chain.produce().issuer("NBIS")
                return (item.disposition, item.admission_kind,
                        item.receipt_admission["decision"])
            actual = f.outcome_of(admission)
            f.observe_boundary("N3-1.a", actual)
            self.assertEqual(actual, ("RESULT", ("AUTO_VERIFIED", "MACHINE_REPLAY", None)))
            chain = chains[0]
            actual = f.outcome_of(lambda: chain.receipt()["status"])
            f.observe_boundary("N3-1.b", actual)
            self.assertEqual(actual, ("RESULT", "REVIEW_REQUIRED"))
            actual = f.outcome_of(chain.forward)
            f.observe_boundary("N3-1.c", actual)
            self.assertEqual(actual, ("RESULT", ("AVAILABLE", None, 1850000000.0, 1850000000.0,
                                                1850000000.0, 1850000000.0, 4, 0)))


    def test_n3_2_human_zero_ytd_refused(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-g4-human-") as tmp:
            controls = []
            def control():
                chain = h.Chain(Path(tmp))
                chain.produce()
                controls.append(chain.human_control())
                return controls[0][1]["issuers"]["NBIS"][-1]["status"]
            actual = f.outcome_of(control)
            f.observe_boundary("N3-2.precondition", actual)
            self.assertEqual(actual, ("RESULT", "OK"))
            record, cache, _snapshot = controls[0]
            def forward():
                result = f.guidance.build_forward_quarters(
                    "NBIS", record, h.CUTOFF, release_checks_cache=cache)
                return result["status"], result["reason"]
            actual = f.outcome_of(forward)
            f.observe_boundary("N3-2", actual)
            self.assertEqual(actual, ("RESULT", ("UNAVAILABLE", "PERIOD_MISMATCH")))

    def test_n3_2c_curated_snapshot_is_invalid(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-g4-curated-") as tmp:
            controls = []
            def control():
                chain = h.Chain(Path(tmp))
                chain.produce()
                _record, _cache, snapshot = chain.human_control()
                item = snapshot.issuer("NBIS")
                record = item.usable_record
                controls.append((record, snapshot))
                return (item.disposition, item.admission_kind, item.usable_record is not None,
                        record is item.usable_record)
            actual = f.outcome_of(control)
            f.observe_boundary("N3-2c.precondition", actual)
            self.assertEqual(actual, ("RESULT", ("CURATED", "HUMAN_PROFILE", True, True)))
            record, snapshot = controls[0]
            actual = f.outcome_of(lambda: f.guidance.build_forward_quarters(
                "NBIS", record, h.CUTOFF, effective_inputs=snapshot))
            f.observe_boundary("N3-2c", actual)
            self.assertEqual(actual, ("RESULT", {
                "status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                "forward_quarters": [], "f1": 0.0, "f2": 0.0, "f3": 0.0, "f4": 0.0,
                "basis_type": None, "claims_used": [], "receipt": None}))

    def test_n3_3_and_4_zero_ytd_validator(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-g4-validator-") as tmp:
            records = []
            def control():
                chain = h.Chain(Path(tmp))
                chain.produce()
                record = chain.snapshot.issuer("NBIS").usable_record
                f.guidance.validate_issuer_record(record, "NBIS")
                records.append(record)
                return True
            actual = f.outcome_of(control)
            f.observe_boundary("N3-3/4.precondition", actual)
            self.assertEqual(actual, ("RESULT", True))
            for label, field, value in (("N3-3", "ytd_end", "2032-01-02"),
                                        ("N3-4", "ytd_revenue", 1.0)):
                with self.subTest(row=label):
                    def validate():
                        record = copy.deepcopy(records[0])
                        recon = record["fy_reconciliation"]
                        recon.update(ytd_quarter_ends=[], ytd_start="2032-01-01",
                                     ytd_end="2032-01-01", ytd_revenue=0.0)
                        recon[field] = value
                        return f.guidance.validate_issuer_record(record, "NBIS")
                    actual = f.outcome_of(validate)
                    f.observe_boundary(label, actual)
                    self.assertEqual(actual, ("RAISED", "GuidanceError",
                        "EMPTY_YTD_MUST_BE_ZERO_DEGENERATE in fy_reconciliation for NBIS"))

    def test_n3_5_tracked_profile_is_curated(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-g4-disabled-") as tmp:
            def invoke():
                chain = h.Chain(Path(tmp), tracked=True)
                chain.check(h.T0)
                chain.update()
                item = chain.load(h.CUTOFF_TEXT).issuer("NBIS")
                return item.disposition, item.admission_kind, len(chain.transport.requests)
            actual = f.outcome_of(invoke)
            f.observe_boundary("N3-5", actual)
            self.assertEqual(actual, ("RESULT", ("CURATED", "HUMAN_PROFILE", 0)))

    def test_n3_6_unaccounted_ir_suspends(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-g4-extra-ir-") as tmp:
            def invoke():
                chain = h.Chain(Path(tmp))
                chain.check(h.T0)
                chain.update()
                chain.extra_ir = True
                chain.check(h.T1)
                item = chain.load(h.CUTOFF_TEXT).issuer("NBIS")
                return item.disposition, item.receipt_admission["decision"] is None
            actual = f.outcome_of(invoke)
            f.observe_boundary("N3-6", actual)
            self.assertEqual(actual, ("RESULT", ("SUSPENDED", False)))

    def test_n3_7_temp_profile_changes_only_enabled_symbols(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-g4-profile-") as tmp:
            def invoke():
                chain = h.Chain(Path(tmp))
                tracked = f.tracked()
                temporary = json.loads(chain.profiles.read_bytes())
                temporary_enabled = temporary.pop("enabled_symbols")
                tracked_enabled = tracked.pop("enabled_symbols")
                return tracked == temporary, temporary_enabled, tracked_enabled
            actual = f.outcome_of(invoke)
            f.observe_boundary("N3-7", actual)
            self.assertEqual(actual, ("RESULT", (True, ["NBIS"], ["NVDA", "MU"])))

    def test_n3_8_profile_identity_change(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-g4-identity-") as tmp:
            def invoke():
                chain = h.Chain(Path(tmp))
                chain.produce()
                item = chain.load(h.CUTOFF_TEXT, profiles=f.PROFILE_PATH).issuer("NBIS")
                return item.disposition, item.admission_kind, item.usable_record is None
            actual = f.outcome_of(invoke)
            f.observe_boundary("N3-8", actual)
            self.assertEqual(actual, ("RESULT", ("CURATED", "HUMAN_PROFILE", False)))


if __name__ == "__main__":
    unittest.main()
