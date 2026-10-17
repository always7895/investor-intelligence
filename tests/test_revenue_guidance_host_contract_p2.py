"""Real host session/dispatcher entry points with fake lease, origin and stdio.

The P2 cases drive the real NativeStorageLease journal over the in-memory file
of test_revenue_guidance_storage_contract. serve() runs over in-memory standard
pipes with a fake controlled origin. No bootstrap, native API, enrollment, model
build, network, credential or task action is used; native custody stays G3.
"""
from __future__ import annotations

from contextlib import contextmanager
import base64
import copy
from datetime import timedelta
import io
import json
import os
from pathlib import Path
import pickle
import sys
import time
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import revenue_guidance_host as host
import revenue_guidance_machine as machine
import sec_contact_headers
from tests import test_revenue_guidance_host_contract as hc
from tests import test_revenue_guidance_storage_contract as p2

A, B, state = hc.A, hc.B, hc.state
REF = "5" * 48
DEADLINE = "2099-01-01T00:00:00Z"
CUTOFF = "2026-02-27T13:00:00Z"


def reason(error):
    return str(error.exception)


def intent(base=A, observed=A, prior=None, ident="a" * 32):
    return {"Id": ident, "BaseInputRevision": base, "ObservedAtBeginRevision": observed, "PriorPendingRevision": prior}


def witness(owner, *, rev=A, cutoff=CUTOFF, bundle=None, acked=False):
    value = host._LiveWitness(owner, SimpleNamespace(cutoff=cutoff), None, rev, b"{}", {}, state(rev, rev), {}, bundle)
    value.acked = acked
    return value


def machine_session(lease, revision=A, headers=None):
    value = host._Session(time.monotonic() + 30, {} if headers is None else headers, machine_enabled=True)
    value.lease = lease
    value.phase = "idle"
    value.input_revision = lambda: revision
    return value


def serve_lease(initial=None):
    lease = hc.FakeLease(state(A, A) if initial is None else initial)
    lease.constrain_remaining_budget = mock.Mock()
    return lease


@contextmanager
def module_stub(name, value):
    # Replace exactly one sys.modules entry; never drop modules imported meanwhile.
    missing = object()
    saved = sys.modules.get(name, missing)
    sys.modules[name] = value
    try:
        yield value
    finally:
        if saved is missing:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = saved


class HostP2JournalTests(unittest.TestCase):
    """Host _Session.journal/commit against the real two-slot storage journal."""
    def setUp(self):
        self.journal = p2.FakeJournal(p2.slot(7, state(A, A)), p2.slot(8, state(A)))
        self.lease = p2.lease_over(self.journal)
        self.enterContext(p2.native(self.journal))

    def test_journal_binds_the_original_storage_token_and_rotates_references(self):
        current = hc.session(self.lease)
        first = current.journal()
        self.assertEqual(first["State"], state(A))
        self.assertRegex(first["VersionRef"], r"\A[0-9a-f]{48}\Z")
        self.assertIs(current.version, self.lease.read_journal().version)
        second = current.journal()
        self.assertNotEqual(second["VersionRef"], first["VersionRef"])
        begun = state(A, None, intent())
        for args in ({"VersionRef": first["VersionRef"], "NewState": begun},
                     {"VersionRef": second["VersionRef"], "NewState": begun, "Version": "native"},
                     {"VersionRef": second["VersionRef"].upper(), "NewState": begun}):
            with self.subTest(keys=sorted(args)):
                with self.assertRaises(host.HostUnavailable) as raised:
                    current.commit(args)
                self.assertEqual(reason(raised), "VERSION_REFERENCE_UNAVAILABLE")
        fresh = hc.session(self.lease)
        with self.assertRaises(host.HostUnavailable):
            fresh.commit({"VersionRef": second["VersionRef"], "NewState": begun})
        self.assertEqual(self.journal.writes(), [])

    def test_begin_and_recovery_commit_through_the_real_cas_alternating_slots(self):
        current = hc.session(self.lease, B)
        begun = state(A, None, intent(A, B))
        result = current.commit({"VersionRef": current.journal()["VersionRef"], "NewState": begun})
        self.assertTrue(result["Committed"])
        self.assertEqual(result["State"], begun)
        self.assertEqual(current.phase, "begun")
        self.assertIs(current.version, self.lease.read_journal().version)
        recovered = hc.session(self.lease, B)
        result = recovered.commit({"VersionRef": recovered.journal()["VersionRef"], "NewState": state(B, B)})
        self.assertTrue(result["Committed"])
        self.assertEqual(self.lease.read_journal().state, state(B, B))
        self.assertEqual(recovered.completion(B), {"Completed": False, "Revision": B})
        invalidations = [call[1] for call in self.journal.writes() if call[3] == b"INVALID!"]
        self.assertEqual(invalidations, [0, p2.storage.JOURNAL_SLOT_SIZE])

    def test_concurrent_commit_makes_the_host_lose_the_cas_without_writing(self):
        current = hc.session(self.lease)
        ref = current.journal()["VersionRef"]
        self.assertTrue(self.lease.commit_journal(self.lease.read_journal().version, state(A, A)).success)
        writes = len(self.journal.writes())
        result = current.commit({"VersionRef": ref, "NewState": state(A, A, intent(prior=A))})
        self.assertFalse(result["Committed"])
        self.assertEqual(result["State"], state(A, A))
        self.assertNotEqual(result["VersionRef"], ref)
        self.assertEqual(current.phase, "failed")
        self.assertEqual(len(self.journal.writes()), writes)
        self.assertIs(current.version, self.lease.read_journal().version)

    def test_json_cannot_clear_pending_through_the_real_journal(self):
        journal = p2.FakeJournal(p2.slot(7, state(A)), p2.slot(8, state(A, A)))
        lease = p2.lease_over(journal)
        with p2.native(journal):
            current = hc.session(lease)
            with self.assertRaises(host.HostUnavailable) as raised:
                current.commit({"VersionRef": current.journal()["VersionRef"], "NewState": state(A)})
            self.assertEqual(reason(raised), "COMPLETION_UNAVAILABLE")
            self.assertEqual(lease.read_journal().state, state(A, A))
        self.assertEqual(journal.writes(), [])


class HostPhaseContractTests(unittest.TestCase):
    def test_rank_argument_and_phase_guards_precede_any_journal_read(self):
        lease = hc.FakeLease(state(A, A))
        reads = mock.Mock(side_effect=lease.read_journal)
        lease.read_journal = reads
        current = hc.session(lease)
        for args in ({}, {"Mode": "Dirty"}, {"Mode": "Dirty", "Revision": A, "Extra": 1},
                     {"Mode": "Eager", "Revision": A}, {"Mode": "dirty", "Revision": A}):
            with self.subTest(args=args):
                with self.assertRaises(host.HostUnavailable) as raised:
                    current.rank(args)
                self.assertEqual(reason(raised), "RANKING_PHASE_UNAVAILABLE")
        for phase in ("new", "begun", "checked", "updated", "dispatching", "failed"):
            with self.subTest(phase=phase):
                current.phase = phase
                with self.assertRaises(host.HostUnavailable) as raised:
                    current.rank({"Mode": "Dirty", "Revision": A})
                self.assertEqual(reason(raised), "RANKING_PHASE_UNAVAILABLE")
        reads.assert_not_called()
        self.assertEqual(lease.commits, [])

    def test_rank_revision_and_live_rebuild_rules(self):
        stale = (host.now() - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cases = (
            ("intent-present", state(A, A, intent()), A, {"Mode": "Dirty", "Revision": A}, None, "RANKING_REVISION_UNAVAILABLE"),
            ("input-moved", state(A, A), B, {"Mode": "Dirty", "Revision": B}, None, "RANKING_REVISION_UNAVAILABLE"),
            ("clean-dirty", state(A), A, {"Mode": "Dirty", "Revision": A}, None, "LIVE_REBUILD_REQUIRED"),
            ("clean-no-witness", state(A), A, {"Mode": "Cadence", "Revision": None}, None, "LIVE_REBUILD_REQUIRED"),
            ("clean-unacked", state(A), A, {"Mode": "Cadence", "Revision": None}, "own-unacked", "LIVE_REBUILD_REQUIRED"),
            ("clean-foreign-owner", state(A), A, {"Mode": "Cadence", "Revision": None}, "foreign", "LIVE_REBUILD_REQUIRED"),
            ("clean-stale-cutoff", state(A), A, {"Mode": "Cadence", "Revision": None}, "own-stale", "LIVE_REBUILD_REQUIRED"),
            ("pending-other-revision", state(A, A), A, {"Mode": "Dirty", "Revision": B}, None, "RANKING_REVISION_UNAVAILABLE"),
            ("pending-null-revision", state(A, A), A, {"Mode": "Cadence", "Revision": None}, None, "RANKING_REVISION_UNAVAILABLE"),
        )
        for name, journal, revision, args, kind, expected in cases:
            with self.subTest(name):
                lease = hc.FakeLease(journal)
                current = hc.session(lease, revision)
                if kind == "own-unacked":
                    current.witness = witness(current.guard)
                elif kind == "foreign":
                    current.witness = witness(object(), acked=True)
                elif kind == "own-stale":
                    current.witness = witness(current.guard, cutoff=stale, acked=True)
                with mock.patch.object(current, "_read_witness", side_effect=AssertionError("readback reached")):
                    with self.assertRaises(host.HostUnavailable) as raised:
                        current.rank(args)
                self.assertEqual(reason(raised), expected)
                self.assertEqual(lease.commits, [])
        lease = hc.FakeLease(state(A))
        current = hc.session(lease)
        current.witness = witness(current.guard, cutoff=host.now().strftime("%Y-%m-%dT%H:%M:%SZ"), acked=True)
        with mock.patch.object(current, "_read_witness") as readback:
            result = current.rank({"Mode": "Cadence", "Revision": None})
        self.assertEqual(result, {"Completed": True, "Revision": A, "ReusedLiveConsumption": True})
        readback.assert_called_once_with(current.witness, state(A))

    def test_check_and_update_require_their_exact_phase(self):
        current = hc.session(hc.FakeLease(state(A, None, intent())))
        for phase, call in (("idle", current.check), ("checked", current.check), ("updated", current.check),
                            ("idle", current.update), ("begun", current.update), ("updated", current.update)):
            with self.subTest(phase=phase, call=call.__name__):
                current.phase = phase
                with self.assertRaises(host.HostUnavailable) as raised:
                    call()
                self.assertEqual(reason(raised), "SESSION_PHASE_UNAVAILABLE")
                self.assertEqual(current.phase, phase)

    def test_updated_phase_intent_clear_follows_the_base_revision(self):
        for name, current_revision, refused, accepted in (
                ("base-unchanged", A, state(A, A), state(A)),
                ("base-moved", B, state(A), state(B, B))):
            with self.subTest(name):
                lease = hc.FakeLease(state(A, None, intent()))
                current = hc.session(lease, current_revision)
                ref = current.journal()["VersionRef"]
                current.phase = "updated"
                with self.assertRaises(host.HostUnavailable) as raised:
                    current.commit({"VersionRef": ref, "NewState": refused})
                self.assertEqual(reason(raised), "JOURNAL_STATE_UNAVAILABLE")
                self.assertEqual((lease.commits, current.phase), ([], "updated"))
                result = current.commit({"VersionRef": ref, "NewState": accepted})
                self.assertTrue(result["Committed"])
                self.assertEqual((lease.state, current.phase), (accepted, "idle"))
        lease = hc.FakeLease(state(A, None, intent()))
        current = hc.session(lease)
        ref = current.journal()["VersionRef"]
        current.phase = "checked"
        with self.assertRaises(host.HostUnavailable) as raised:
            current.commit({"VersionRef": ref, "NewState": state(A)})
        self.assertEqual(reason(raised), "JOURNAL_PHASE_UNAVAILABLE")
        self.assertEqual(lease.commits, [])

    def test_begin_rejects_wrong_phase_and_forged_intents_without_commit(self):
        cases = (
            ("wrong-phase", "checked", state(A, None, intent()), "JOURNAL_PHASE_UNAVAILABLE"),
            ("uppercase-id", "idle", state(A, None, intent(ident="A" * 32)), "JOURNAL_PHASE_UNAVAILABLE"),
            ("short-id", "idle", state(A, None, intent(ident="a" * 31)), "JOURNAL_PHASE_UNAVAILABLE"),
            ("forged-observed", "idle", state(A, None, intent(observed=B)), "JOURNAL_STATE_UNAVAILABLE"),
            ("forged-prior", "idle", state(A, None, intent(prior=A)), "JOURNAL_STATE_UNAVAILABLE"),
            ("forged-base", "idle", state(A, None, intent(base=B)), "JOURNAL_STATE_UNAVAILABLE"),
            ("extra-key", "idle", {**state(A, None, intent()), "Witness": True}, "JOURNAL_STATE_UNAVAILABLE"),
            ("not-required", "idle", {**state(A, None, intent()), "StateRequired": False}, "JOURNAL_STATE_UNAVAILABLE"),
            ("list-state", "idle", [state(A, None, intent())], "JOURNAL_STATE_UNAVAILABLE"),
            ("no-op", "idle", state(A), "JOURNAL_PHASE_UNAVAILABLE"),
        )
        for name, phase, requested, expected in cases:
            with self.subTest(name):
                lease = hc.FakeLease(state(A))
                current = hc.session(lease)
                ref = current.journal()["VersionRef"]
                current.phase = phase
                with self.assertRaises(host.HostUnavailable) as raised:
                    current.commit({"VersionRef": ref, "NewState": requested})
                self.assertEqual(reason(raised), expected)
                self.assertEqual(lease.commits, [])

    def test_live_witness_cannot_be_serialized_copied_or_extended(self):
        value = witness(object(), acked=True)
        for name, call in (("pickle", lambda: pickle.dumps(value)), ("copy", lambda: copy.copy(value)),
                           ("deepcopy", lambda: copy.deepcopy(value))):
            with self.subTest(name):
                with self.assertRaisesRegex(TypeError, "LIVE_WITNESS_NOT_SERIALIZABLE"):
                    call()
        self.assertFalse(hasattr(value, "__dict__"))
        with self.assertRaises(AttributeError):
            value.authority = True

    def test_completion_requires_an_unacknowledged_live_witness_for_the_exact_revision(self):
        absent = {"Completed": False, "Revision": A}
        lease = hc.FakeLease(state(A, A))
        current = hc.session(lease)
        with mock.patch.object(current, "_read_witness", side_effect=AssertionError("readback reached")):
            self.assertEqual(current.completion(A), absent)
            current.witness = witness(current.guard, rev=B)
            self.assertEqual(current.completion(A), absent)
            current.witness = witness(current.guard, acked=True)
            self.assertEqual(current.completion(A), absent)
            current.witness = witness(current.guard)
            self.assertEqual(current.completion("gir1:" + "a" * 63), {"Completed": False, "Revision": "gir1:" + "a" * 63})
            current.phase = "begun"
            self.assertEqual(current.completion(A), absent)
            current.phase = "idle"
            lease.state = state(A, A, intent())
            self.assertEqual(current.completion(A), absent)
            lease.state = state(A)
            self.assertEqual(current.completion(A), absent)
        lease.state = state(A, A)
        with mock.patch.object(current, "_read_witness") as readback:
            self.assertEqual(current.completion(A), {"Completed": True, "Revision": A})
        readback.assert_called_once_with(current.witness, state(A, A))

    def test_public_export_is_single_bounded_and_needs_a_machine_live_witness(self):
        def blocked(current, expected):
            with self.assertRaises(machine.MachinePublicationBlocked) as raised:
                current.export_public()
            self.assertEqual(raised.exception.reason, expected)
        lease = hc.FakeLease(state(A))
        disabled = hc.session(lease)
        disabled.witness = witness(disabled.guard, bundle=(b"{}", b"{}"))
        blocked(disabled, "MACHINE_EXPORT_UNAVAILABLE")
        current = machine_session(lease)
        blocked(current, "MACHINE_EXPORT_UNAVAILABLE")
        current.witness = witness(current.guard)
        blocked(current, "MACHINE_EXPORT_UNAVAILABLE")
        current.witness = witness(current.guard, bundle=(b"{}", b"{}"))
        current.phase = "begun"
        blocked(current, "MACHINE_EXPORT_UNAVAILABLE")
        self.assertFalse(current.public_export_started)
        current.phase = "idle"
        body, binding = b"b" * 1900000, b"m" * 64000
        current.witness = witness(current.guard, bundle=(body, binding))
        with mock.patch.object(current, "_read_witness") as readback:
            metadata, sent_body, sent_binding = current.export_public()
            self.assertEqual(metadata, {"BodyBytes": 1900000, "BindingBytes": 64000, "BodySha256": host.digest(body),
                                        "BindingSha256": host.digest(binding), "Cutoff": CUTOFF, "Revision": A})
            self.assertEqual((sent_body, sent_binding), (body, binding))
            blocked(current, "MACHINE_EXPORT_UNAVAILABLE")
        readback.assert_called_once()
        for name, bundle in (("body", (body + b"b", b"{}")), ("binding", (b"{}", binding + b"m"))):
            with self.subTest(name):
                oversized = machine_session(lease)
                oversized.witness = witness(oversized.guard, bundle=bundle)
                with mock.patch.object(oversized, "_read_witness"):
                    blocked(oversized, "MACHINE_EVIDENCE_LIMIT")
                    blocked(oversized, "MACHINE_EXPORT_UNAVAILABLE")

    def test_session_deadline_constrains_the_lease_and_expires_closed(self):
        lease = serve_lease()
        current = hc.session(lease)
        left = current.remaining()
        self.assertTrue(0 < left <= 30)
        (remaining_ms,), _ = lease.constrain_remaining_budget.call_args
        self.assertEqual(type(remaining_ms), int)
        self.assertTrue(1 <= remaining_ms <= 30000)
        current.tighten({"remaining_ms": 1000, "deadline_utc": DEADLINE})
        self.assertLessEqual(current.deadline, time.monotonic() + 1)
        current.tighten({"remaining_ms": 600000, "deadline_utc": DEADLINE})
        self.assertLessEqual(current.deadline, time.monotonic() + 1)
        lease.constrain_remaining_budget.reset_mock()
        current.deadline = time.monotonic() - 1
        with self.assertRaises(host.HostUnavailable) as raised:
            current.remaining()
        self.assertEqual(reason(raised), "REQUEST_DEADLINE")
        lease.constrain_remaining_budget.assert_not_called()


class HostOpenAndCloseTests(unittest.TestCase):
    def open_session(self, journal, revision=A, *, symbols=("NVDA", "MU"), committed=True):
        order = []
        lease = serve_lease(journal)
        lease.namespace_operation = mock.Mock(return_value=mock.MagicMock())
        real_commit = lease.commit_journal
        def commit(token, requested):
            order.append("commit")
            result = real_commit(token, requested)
            return result if committed else SimpleNamespace(success=False, state=result.state, version=result.version)
        lease.commit_journal = commit
        layers = {"layers": [{"capturers": [{"symbol": symbol} for symbol in symbols]}]}
        origin = SimpleNamespace(files={"config/bottleneck-layers-v3.json": json.dumps(layers).encode("utf-8")},
                                 close=mock.Mock(side_effect=lambda: order.append("origin-close")))
        def acquire(remaining_ms, *, parent_deadline):
            order.append("lease")
            self.assertEqual(type(remaining_ms), int)
            self.assertEqual(type(parent_deadline), float)
            return lease
        owner = SimpleNamespace(live_owner_handle=object(), close=mock.Mock())
        current = host._Session(time.monotonic() + 30, {})
        current.input_revision = lambda: revision
        with module_stub("revenue_guidance_bootstrap", SimpleNamespace(acquire=acquire)), \
                mock.patch.object(host.provisioner, "acquire_live_owner",
                                  side_effect=lambda: order.append("live-owner") or owner), \
                mock.patch.object(host.provisioner, "controlled_origin", return_value=origin):
            try:
                return current, current.open(), lease, order
            except host.HostUnavailable as error:
                return current, error, lease, order

    def test_restart_always_requires_real_consumption_again(self):
        for name, journal, revision, expected in (
                ("acknowledged-clean", state(A), A, state(A, A)),
                ("input-moved", state(A, A), B, state(B, B)),
                ("pending-elsewhere", state(A, B), A, state(A, A))):
            with self.subTest(name):
                current, result, lease, order = self.open_session(journal, revision)
                self.assertEqual(result, {"Available": True, "SessionRef": current.session_ref})
                self.assertEqual(lease.state, expected)
                self.assertEqual(order, ["live-owner", "lease", "origin-close", "commit"])
                self.assertEqual(current.symbols, ["MU", "NVDA"])
                self.assertEqual(current.phase, "idle")
        for name, journal in (("already-pending", state(A, A)), ("interrupted-intent", state(A, None, intent()))):
            with self.subTest(name):
                current, result, lease, order = self.open_session(journal)
                self.assertEqual(result["Available"], True)
                self.assertEqual((lease.commits, lease.state), ([], journal))
                self.assertNotIn("commit", order)

    def test_open_refuses_a_failed_pending_commit_or_an_unbounded_ranking_scope(self):
        current, error, lease, order = self.open_session(state(A), committed=False)
        self.assertIsInstance(error, host.HostUnavailable)
        self.assertEqual(str(error), "OPEN_PENDING_COMMIT_UNAVAILABLE")
        self.assertEqual(current.phase, "new")
        for name, symbols in (("empty", ()), ("lowercase", ("nvda",)), ("too-many", tuple(f"S{i}" for i in range(257)))):
            with self.subTest(name):
                current, error, lease, order = self.open_session(state(A), symbols=symbols)
                self.assertEqual(str(error), "RANKING_SCOPE_UNAVAILABLE")
                self.assertEqual(order, ["live-owner", "lease", "origin-close"])
                self.assertEqual(lease.commits, [])

    def close_session(self, *, exported, origin="SETTLED"):
        order = []
        lease = hc.FakeLease(state(A))
        lease.close = mock.Mock(side_effect=lambda: order.append("lease"))
        current = machine_session(lease, headers={"User-Agent": "synthetic"})
        current.operation = mock.MagicMock()
        current.operation.__exit__.side_effect = lambda *args: order.append("operation")
        owner = SimpleNamespace(live_owner_handle=object(), close=mock.Mock(side_effect=lambda: order.append("owner")))
        current.live_owner = owner
        current.public_export_complete = exported
        current.witness = witness(current.guard, acked=True)
        retained = []
        patches = (mock.patch.object(current, "_read_witness", side_effect=lambda *args: order.append("readback")),
                   mock.patch.object(host.windows, "native_custody_status", return_value="SETTLED"),
                   mock.patch.object(host.provisioner, "origin_custody_status", return_value=origin),
                   mock.patch.object(host.provisioner, "retain_live_owner_custody", side_effect=retained.append))
        return current, owner, order, retained, patches

    def test_settled_close_runs_once_in_owner_order(self):
        for exported, acknowledged, expected in ((True, True, ["readback", "operation", "lease", "owner"]),
                                                 (False, False, ["operation", "lease", "owner"])):
            with self.subTest(exported=exported):
                current, owner, order, retained, patches = self.close_session(exported=exported)
                with patches[0], patches[1], patches[2], patches[3]:
                    result = current.close()
                    self.assertEqual(result, {"Closed": True, "Custody": "SETTLED", "MachineAcknowledged": acknowledged})
                    self.assertEqual(order, expected)
                    self.assertEqual(current.sec_headers, {})
                    self.assertIsNone(current.witness)
                    self.assertIsNone(owner._host_session_custody)
                    with self.assertRaises(host.HostUnavailable) as raised:
                        current.close()
                    self.assertEqual(reason(raised), "SESSION_CLOSED")
                    self.assertEqual(order, expected)
                    self.assertEqual(retained, [])

    def test_unresolved_origin_retains_the_owner_graph_without_retry(self):
        current, owner, order, retained, patches = self.close_session(exported=False, origin="UNRESOLVED")
        with patches[0], patches[1], patches[2], patches[3]:
            with self.assertRaises(host.HostUnavailable) as raised:
                current.close()
            self.assertEqual(reason(raised), "ORIGIN_CUSTODY_UNRESOLVED")
            self.assertEqual(retained, [owner])
            self.assertIs(owner._host_session_custody, current)
            with self.assertRaises(host.HostUnavailable):
                current.close()
            self.assertEqual(order, ["operation", "lease", "owner"])
            self.assertEqual(retained, [owner])


class _Api:
    """Callable native-shaped API slot whose argtypes/restype may be assigned."""
    def __init__(self, fn):
        self.fn = fn

    def __call__(self, *args):
        return self.fn(*args)


def frame(request_id, op, args=None, *, session=None, remaining=30000, **extra):
    value = {"protocol": host.PROTOCOL, "id": request_id, "op": op, "session": session,
             "remaining_ms": remaining, "deadline_utc": DEADLINE, "args": {} if args is None else args}
    value.update(extra)
    return json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n"


def sized_frame(size, request_id, op, args=None, *, session=None):
    raw = frame(request_id, op, args, session=session)[:-1]
    return raw[:-1] + b" " * (size - len(raw)) + b"}\n"


class HostServeProtocolTests(unittest.TestCase):
    def run_serve(self, raw, *, file_type=3, setup=None):
        stdin, stdout, stderr = SimpleNamespace(buffer=io.BytesIO(raw)), SimpleNamespace(buffer=io.BytesIO()), io.StringIO()
        kernel = SimpleNamespace(GetStdHandle=_Api(lambda code: code), GetFileType=_Api(lambda handle: file_type))
        origin = SimpleNamespace(apis=(None, SimpleNamespace(DWORD=int, HANDLE=int), kernel, None), close=mock.Mock())
        observed = SimpleNamespace(closed=[], reads=[], origin=origin, sessions=[])

        def fake_open(session):
            session.lease = serve_lease()
            session.phase = "idle"
            observed.sessions.append(session)
            if setup is not None:
                setup(session)
            return {"Available": True, "SessionRef": session.session_ref}

        def fake_close(session):
            session.closed = True
            observed.closed.append(session.phase)
            return {"Closed": True, "Custody": "SETTLED"}

        def fake_read(session, value, journal_state):
            observed.reads.append((value, journal_state))

        with mock.patch.object(host.provisioner, "controlled_origin", return_value=origin), \
                mock.patch.object(sec_contact_headers, "sec_identity_headers", return_value={"User-Agent": "synthetic"}), \
                mock.patch.dict(os.environ, {}), \
                mock.patch.object(host.windows, "native_custody_status", return_value="SETTLED"), \
                mock.patch.object(host.windows, "hold_unresolved_native_custody", side_effect=AssertionError("held")), \
                mock.patch.object(host.secrets, "token_hex", return_value=REF), \
                mock.patch.object(host._Session, "open", fake_open), \
                mock.patch.object(host._Session, "close", fake_close), \
                mock.patch.object(host._Session, "_read_witness", fake_read), \
                mock.patch.object(sys, "stdin", stdin), mock.patch.object(sys, "stdout", stdout), \
                mock.patch.object(sys, "stderr", stderr):
            try:
                observed.code = host.serve(30000)
            except host.HostUnavailable as error:
                observed.code = error
        observed.replies = [json.loads(line) for line in stdout.buffer.getvalue().splitlines()]
        observed.stderr = stderr.getvalue()
        return observed

    def statuses(self, observed):
        return [(reply["id"], reply["status"]) for reply in observed.replies]

    def test_frames_are_exact_monotonic_session_bound_and_refused_before_dispatch(self):
        nested = {}
        for _ in range(40):
            nested = {"a": nested}
        duplicate = (b'{"protocol":"guidance-private-host-v1","protocol":"guidance-private-host-v1","id":1,"op":"Open",'
                     b'"session":null,"remaining_ms":1,"deadline_utc":"x","args":{}}\n')
        nonfinite = (b'{"protocol":"guidance-private-host-v1","id":1,"op":"Open","session":null,'
                     b'"remaining_ms":NaN,"deadline_utc":"x","args":{}}\n')
        raw = b"".join((
            frame(2, "Open"), frame(1, "Eval"), frame(1, "Open", extra=1), frame(1, "Open", remaining=600001),
            frame(1, "Open", protocol="guidance-private-host-v0"), duplicate, nonfinite, frame(1, "Open", {"a": nested}),
            frame(1, "ReadJournal", session=REF),
            frame(2, "Open", {"GuidanceMachineEnabled": "yes"}),
            frame(3, "Open", session=REF),
            frame(4, "Open"),
            frame(5, "Open"),
            frame(6, "ReadRebuildCompletion", {"Revision": A}, session="0" * 48),
            frame(7, "ReadRebuildCompletion", {"Revision": "gir1:short"}, session=REF),
            frame(8, "CommitJournal", {"VersionRef": "x", "NewState": {}}, session=REF),
            frame(9, "ReadJournal", {"Witness": True}, session=REF),
            frame(10, "ReadRebuildCompletion", {"Revision": A}, session=REF),
            frame(10, "ReadRebuildCompletion", {"Revision": A}, session=REF),
            frame(11, "Close", session=REF),
            frame(12, "ReadRebuildCompletion", {"Revision": A}, session=REF),
        ))
        observed = self.run_serve(raw)
        self.assertEqual(observed.code, 0)
        refused = "REFUSED_BEFORE_DISPATCH"
        self.assertEqual(self.statuses(observed), [(0, "HOST_PROTOCOL_READY")] + [(0, refused)] * 8 + [
            (1, refused), (2, refused), (3, refused), (4, "OK"), (5, refused), (6, refused), (7, refused),
            (8, refused), (9, refused), (10, "OK"), (10, refused), (11, "OK")])
        for reply in observed.replies:
            self.assertEqual(reply["protocol"], host.PROTOCOL)
            self.assertEqual(reply["attempted"], reply["status"] == "OK")
            if reply["status"] == refused:
                self.assertIsNone(reply["result"])
        self.assertEqual(observed.replies[12]["result"], {"Available": True, "SessionRef": REF})
        self.assertEqual(observed.replies[18]["result"], {"Completed": False, "Revision": A})
        self.assertEqual(len(observed.sessions), 1)
        self.assertEqual(observed.closed, ["idle"])
        self.assertEqual(observed.stderr, "")
        observed.origin.close.assert_called_once_with()

    def test_frame_byte_bound_is_exact_and_oversized_lines_never_dispatch(self):
        exact = sized_frame(host.MAX_FRAME, 1, "Open")
        over = sized_frame(host.MAX_FRAME + 1, 2, "ReadRebuildCompletion", {"Revision": A}, session=REF)
        self.assertEqual((len(exact), len(over)), (host.MAX_FRAME + 1, host.MAX_FRAME + 2))
        observed = self.run_serve(exact + over + b"x" * 20000 + b"\n" + frame(2, "Close", session=REF))
        self.assertEqual(observed.code, 0)
        refused = "REFUSED_BEFORE_DISPATCH"
        self.assertEqual(self.statuses(observed), [(0, "HOST_PROTOCOL_READY"), (1, "OK"), (1, refused),
                                                   (1, refused), (1, refused), (2, "OK")])

    def test_request_count_is_bounded_at_max_requests(self):
        raw = frame(1, "Open") + b"".join(frame(n, "ReadRebuildCompletion", {"Revision": A}, session=REF)
                                          for n in range(2, host.MAX_REQUESTS + 1))
        observed = self.run_serve(raw + frame(host.MAX_REQUESTS + 1, "Close", session=REF))
        self.assertEqual(observed.code, 2)
        self.assertEqual(len(observed.replies), host.MAX_REQUESTS + 1)
        self.assertEqual(self.statuses(observed)[-1], (host.MAX_REQUESTS, "OK"))
        self.assertEqual(observed.closed, ["idle"])

    def test_an_attempted_failure_is_terminal_and_never_retried(self):
        raw = (frame(1, "Open") + frame(2, "CommitJournal", {"VersionRef": REF, "NewState": {}}, session=REF)
               + frame(3, "ReadRebuildCompletion", {"Revision": A}, session=REF))
        observed = self.run_serve(raw)
        self.assertEqual(observed.code, 2)
        self.assertEqual(self.statuses(observed), [(0, "HOST_PROTOCOL_READY"), (1, "OK"), (2, "HOST_OPERATION_UNAVAILABLE")])
        self.assertTrue(observed.replies[-1]["attempted"])
        self.assertIsNone(observed.replies[-1]["result"])
        self.assertEqual(observed.closed, ["failed"])

    def test_non_pipe_standard_handles_refuse_before_any_frame(self):
        observed = self.run_serve(frame(1, "Open"), file_type=1)
        self.assertIsInstance(observed.code, host.HostUnavailable)
        self.assertEqual(str(observed.code), "PRIVATE_PIPE_ENTRY_REQUIRED")
        self.assertEqual(observed.replies, [])
        self.assertEqual(observed.sessions, [])
        observed.origin.close.assert_called_once_with()

    def test_public_export_streams_bounded_ordered_chunks_exactly_once(self):
        body, binding = bytes(range(256)) * 80, b'{"schema":"synthetic-binding"}'

        def setup(session):
            session.witness = witness(session.guard, bundle=(body, binding))

        raw = (frame(1, "Open", {"GuidanceMachineEnabled": True}) + frame(2, "ExportPublicBundle", session=REF)
               + frame(3, "ExportPublicBundle", session=REF) + frame(4, "Close", session=REF))
        observed = self.run_serve(raw, setup=setup)
        self.assertEqual(observed.code, 2)
        self.assertEqual(self.statuses(observed), [(0, "HOST_PROTOCOL_READY"), (1, "OK"), (2, "PUBLIC_DATA_BEGIN")]
                         + [(2, "PUBLIC_DATA")] * 4 + [(2, "OK"), (3, "HOST_OPERATION_UNAVAILABLE")])
        begin, data, done, refused = observed.replies[2], observed.replies[3:7], observed.replies[7], observed.replies[8]
        self.assertEqual(begin["result"]["BodyBytes"], len(body))
        self.assertEqual(begin["result"]["BindingSha256"], host.digest(binding))
        self.assertEqual([(d["object"], d["offset"], d["chunk"]) for d in data],
                         [("body", 0, 0), ("body", 8192, 1), ("body", 16384, 2), ("binding", 0, 3)])
        for item in data:
            self.assertEqual(len(base64.b64decode(item["data"])), item["bytes"])
            self.assertLessEqual(len(json.dumps(item, separators=(",", ":"))), host.MAX_FRAME)
        self.assertEqual(b"".join(base64.b64decode(d["data"]) for d in data[:3]), body)
        self.assertEqual(base64.b64decode(data[3]["data"]), binding)
        self.assertEqual(done["result"], {"Exported": True, "Chunks": 4, **begin["result"]})
        self.assertEqual(refused["result"], {"Reason": "MACHINE_EXPORT_UNAVAILABLE"})
        self.assertTrue(observed.sessions[0].public_export_complete)
        # One readback before the DATA frames and one before the terminal OK.
        self.assertEqual(len(observed.reads), 2)
        self.assertEqual(observed.closed, ["failed"])


if __name__ == "__main__":
    unittest.main()
