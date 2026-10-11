"""SYNTHETIC_G9_NOT_GENUINE: G9a follow-up rows and the G9b guards that are exercisable offline.

Fake connectors, clocks, leases and stores only; every store is an owned TemporaryDirectory. No network, no
subprocess, no real sleep. Not issuer admission and not native capability proof.
"""
from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tests import g9a_synthetic_issuers as h
from tests import nbis_synthetic_sources as f

updater, overlay = f.updater, f.overlay
A, B, C = h.SYMS[:3]
NV = next(p for p in json.loads(h.PROFILE.read_bytes())["profiles"] if p["symbol"] == "NVDA")
DOC = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000073/a.htm"
BODY = h.padded("<html><body>SYNTHETIC_G9_NOT_GENUINE G9B</body></html>")
OK = ("RESULT", "text/html")
RB = ("RAISED", "NetworkBlocked", "RUN_BUDGET")
TOO_LARGE = ("RAISED", "SystemicFailure", "PUBLISH GENERATION_TOO_LARGE")
UQ = ("BLOCKED", "WAITING", "CAPTURE_LIMIT", "store accounting unknown or quota")


def at_hour(hour):
    return datetime(2026, 3, 2, hour, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Reply:
    def __init__(self, status=200, retry=None):
        self.status, self.body = status, BODY if status == 200 else b""
        self.headers = {"content-type": "text/html"}
        if retry is not None:
            self.headers["retry-after"] = retry

    def read(self, n):
        body, self.body = self.body, b""
        return body

    def close(self):
        pass


def transport(replies, clock):
    calls = []

    def connector(host, address, path, headers, timeout):
        calls.append((host, path, timeout))
        reply = replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    return updater.Transport({"User-Agent": "G9B-SYNTHETIC"}, connector=connector,
                             resolver=lambda host: ["162.159.140.1"], sleep=clock.sleep, monotonic=clock), calls


def get(t):
    return f.outcome_of(lambda: t.get(DOC, NV, "ZQA")[1])


def lease(deadline=10.0 ** 9, start=0.0, work=True):
    held = SimpleNamespace(budget=SimpleNamespace(_check_time=lambda: None, deadline=deadline, start_time=start))
    if work:
        held._network_work = {"requests": 0, "bytes": 0, "last": -updater.PACING_SECONDS, "issuers": {}}
    return held


def pacing():
    clock = Clock()
    t, calls = transport([Reply(), Reply(), Reply()], clock)
    clock.now = 599.0
    first, second, third = get(t), get(t), get(t)  # the third would have to wait 0.5 s with 0.5 s left
    return first, second, third, len(calls), clock.sleeps, clock.now


def budgeted(replies, now):
    clock = Clock()
    t, calls = transport(replies, clock)
    clock.now = now
    return get(t), len(calls), clock.sleeps


def retries():
    return (budgeted([Reply(503, "10")], 590.0), budgeted([Reply(503, "9"), Reply()], 590.0),
            budgeted([OSError("reset")], 598.0), budgeted([OSError("reset"), Reply()], 597.0),
            budgeted([OSError("reset"), OSError("reset")], 0.0))


def shared_lease():
    held = lease()
    clock = Clock()
    with mock.patch.object(updater, "CYCLE_CAPTURE_BYTES", 2000):
        t1, calls1 = transport([Reply(), Reply(), Reply()], clock)
        t1.lease = held
        first = get(t1)
        clock.now += 1.0
        second = get(t1)  # exactly 2000 new bytes on the lease's run counter: still admitted
        clock.now += 1.0
        third = get(t1)  # 3000
    work = deepcopy(held._network_work)
    with mock.patch.object(updater, "PER_RUN_REQUESTS", 3):
        t2, calls2 = transport([Reply()], clock)
        t2.lease = held
        shared = get(t2)  # another transport on the same lease shares the run's request counter
    paced = Clock()
    t3, calls3 = transport([Reply()], paced)
    t3.lease = lease()
    t3.lease._network_work["last"] = paced.now  # a request just made by another transport of the lease
    waited = get(t3)
    near = Clock()
    t4, calls4 = transport([Reply(503, "5")], near)
    t4.lease = lease(deadline=5.0)  # the lease deadline binds before started + RUN_BUDGET_SECONDS
    late = get(t4)
    return ((first, second, third, len(calls1), work), (shared, len(calls2), t2.requests), (waited, paced.sleeps),
            (late, len(calls4), near.sleeps))


def binding():
    live = []
    store = SimpleNamespace(require_live=lambda: live.append("live"), lease=lease(start=10.0 ** 12, work=False))

    class Derived(updater.Transport):
        pass

    refused = (f.outcome_of(lambda: updater.Transport({"User-Agent": "G9B"}, connector=lambda *a: None).bind_capability(store)),
               f.outcome_of(lambda: updater.Transport({"User-Agent": "G9B"}, sleep=lambda s: None).bind_capability(store)),
               f.outcome_of(lambda: Derived({"User-Agent": "G9B"}).bind_capability(store)))
    before = list(live)
    one, two = updater.Transport({"User-Agent": "G9B"}), updater.Transport({"User-Agent": "G9B"})
    first = f.outcome_of(lambda: one.bind_capability(store))
    created = deepcopy(getattr(store.lease, "_network_work", None))
    store.lease._network_work["requests"] = 7  # work already counted on this lease by the first transport
    second = f.outcome_of(lambda: two.bind_capability(store))
    return (refused, before, first, second, live, one.lease is store.lease and two.lease is store.lease,
            created == {"requests": 0, "bytes": 0, "last": -updater.PACING_SECONDS, "issuers": {}},
            store.lease._network_work["requests"], one.started == two.started == 10.0 ** 12)


def capability_gates():
    store = object.__new__(overlay.B1Store)
    store.lease = SimpleNamespace(_namespace_guard=lambda: None, _live_operation=object())
    store.epoch = store.lease._live_operation
    clock = lambda: h.at(1)  # noqa: E731
    with tempfile.TemporaryDirectory() as tmp:
        conflict = f.outcome_of(lambda: updater.run(store, updater.Transport({"User-Agent": "G9B"}), clock,
                                                    profiles_path=Path(tmp) / "profiles.json"))
        replay = f.outcome_of(lambda: updater.run(store, SimpleNamespace(replay=True), clock))
        custom = f.outcome_of(lambda: updater.run(store, updater.Transport({"User-Agent": "G9B"}, connector=lambda *a: None), clock))
        store.epoch = object()
        stale = f.outcome_of(lambda: updater.run(store, updater.Transport({"User-Agent": "G9B"}), clock))
        untouched = sorted(p.name for p in Path(tmp).iterdir())
    return conflict, replay, custom, stale, untouched


def queue_files():
    cases = (None, b"[", b'{"last_served": 5}', b'{"last_served": "ZQA", "x": 1}', b"[]", b"\xff\xfe",
             b'{"last_served": null}', b'{"last_served": "ZQA"}', "DIRECTORY")
    out = []
    for raw in cases:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            if isinstance(raw, str):  # a directory where the file belongs: an OSError on read
                (root / "queue.json").mkdir()
            elif raw is not None:
                (root / "queue.json").write_bytes(raw)
            out.append(updater.read_queue(root))
    with tempfile.TemporaryDirectory() as tmp, mock.patch.object(overlay, "_durable_write", side_effect=PermissionError("synthetic")):
        failed = f.outcome_of(lambda: updater.write_queue(Path(tmp), {"last_served": "ZQA"}))
    return out, failed


def queue_runs():
    with h.World(3, 0) as w:
        trace = [w.run(1)[0], w.cur()]
        for k, raw in ((2, '{"last_served": "ZQA"}'), (3, "["), (4, '{"last_served": "ZQZ"}')):
            (w.state / "queue.json").write_text(raw, encoding="utf-8")
            trace.append((w.run(k)[0], w.calls[0][1], w.cur()))
    with h.World(1, 0) as w:
        real = overlay._durable_write

        def failing(path, data):
            if path.name == "queue.json":
                raise PermissionError("synthetic")
            return real(path, data)

        with mock.patch.object(overlay, "_durable_write", failing):
            o = w.run(1)
        stopped = (o, len(w.calls), w.pointer() is not None, w.counts()[0], (w.state / "queue.json").exists())
    return trace, stopped


def nbis_store():
    out = []
    for budget in ({"bytes": 0, "store": None}, {"bytes": 0, "store": updater.STORE_QUOTA_BYTES},
                   {"bytes": 0, "store": updater.STORE_QUOTA_BYTES - 1}, {"bytes": updater.CYCLE_CAPTURE_BYTES, "store": 0}):
        with f.Scenario() as s:
            o = f.outcome_of(lambda: updater.plan_nbis_event(s.transport, s.root, s.profile, s.lead, s.now[:10], s.clock, budget))
            out.append((o, list(s.transport.requests), s.root.exists()))
    return out


def seed(w, mutate):
    """A successor of the pointed generation, created 2026-03-02T12:30:00Z (as R6.4)."""
    pointer, gen = w.pointer(), deepcopy(w.pg())
    when = datetime(2026, 3, 2, 12, 30, tzinfo=timezone.utc)
    gen.update(generation_id=updater._new_generation_id(lambda: when),
               parent={k: pointer[k] for k in ("generation_id", "sha256")}, created_at="2026-03-02T12:30:00Z")
    mutate(gen)
    overlay.publish_generation(w.state, gen, pointer)
    return w.pointer()


def sealed_before_refusal():
    with h.World(1, 0) as w:
        first = w.run(1)

        def opened(gen):
            last = gen["issuers"][A]["open"][-1]
            gen["issuers"][A]["open"] = [dict(deepcopy(last), detail=f"seed {j}") for j in range(33)]

        seeded = seed(w, opened)
        real = overlay.seal

        def sealing(root, entry):
            written = real(root, entry)
            overlay.MAX_GENERATION_BYTES = 1  # restored by the patch below: refuse right after the segment is written
            return written

        with mock.patch.object(overlay, "MAX_GENERATION_BYTES", overlay.MAX_GENERATION_BYTES), mock.patch.object(overlay, "seal", sealing):
            refused = w.run(instant=at_hour(13))
        orphans = [p.stem for p in w.files("segments")]
        referenced = sum(any(d in p.read_text(encoding="utf-8") for d in orphans) for p in w.files("generations"))
        after_refusal = (refused, w.req(), len(orphans), referenced, w.pointer() == seeded, len(w.pg()["issuers"][A]["open"]))
        recovered = w.run(instant=at_hour(14))
        entry = w.pg()["issuers"][A]
        reused = (recovered[0], [p.stem for p in w.files("segments")] == orphans, entry["head"] == orphans[0],
                  entry["sealed"], len(entry["open"]), overlay.verify_history(w.state, entry))
        loads, real_load = [], overlay.load_segment
        with mock.patch.object(overlay, "load_segment", lambda root, digest: loads.append(digest) or real_load(root, digest)):
            quiet = w.run(instant=at_hour(15))
        return first[0], after_refusal, reused, (quiet[0], w.req(), len(loads), w.counts()[0])


def too_large_twice():
    with h.World(1, 0) as w:
        control = w.run(1)
        if control[0] != "RESULT":
            return control
        s0 = list(reversed(w.walk()))[0][0].stat().st_size
    with h.World(1, 0) as w, mock.patch.object(overlay, "MAX_GENERATION_BYTES", s0):
        runs = []
        for k in (1, 2):
            o = w.run(k)
            runs.append((o, w.counts()[0], (w.state / "current.json").read_bytes(), len(w.calls)))
        return runs[0][0], runs[1][0], runs[0][1], runs[1][1], runs[0][2] == runs[1][2], runs[0][3], runs[1][3]


def overflow_then_publish():
    with h.World(3, 0) as w:
        control = w.run(1)
        if control[0] != "RESULT":
            return control

        def full(gen):
            gen["issuers"][B]["index"]["settled"] = h.settled()

        seed(w, full)
        w.ghost(1)
        w.ghost(2)
        o = w.run(instant=at_hour(13))
        if o[0] != "RESULT":
            return o
        pg = w.pg()
        return (tuple(w.summary()["issuers"][s] for s in w.syms), w.req(), w.cur(),
                tuple(len(pg["issuers"][s]["index"]["settled"]) for s in w.syms), w.last(B)["reason"],
                (w.last(C)["outcome"], w.last(C)["reason"]))


def merged_wait():
    def attempt(detail, captures):
        return {"event_key": h.acc(0, 1), "outcome": "WAITING", "reason": "NETWORK_UNAVAILABLE", "detail": detail,
                "event": {"accession": h.acc(0, 1)}, "captures": captures}
    entry = overlay.new_entry()
    overlay.append_attempt(entry, attempt("HTTP 404", {"submissions": "a" * 64, "ir_copy": "b" * 64}))
    changed = updater._record(entry, attempt("RUN_BUDGET", {"submissions": "c" * 64}))
    same = updater._record(entry, attempt("RUN_BUDGET", {"submissions": "c" * 64}))
    return changed, same, len(entry["open"]), entry["open"][-1]["detail"], entry["open"][-1]["captures"]


def construction_failure():
    created, real = [], tempfile.TemporaryDirectory

    def tracked():
        created.append(real())
        return created[-1]

    with mock.patch.object(h.tempfile, "TemporaryDirectory", tracked), \
            mock.patch.object(h.guidance, "parse_registry", return_value={"status": "ERROR", "error": "SYNTHETIC"}):
        o = f.outcome_of(lambda: h.World(1, 0))
    try:
        return o, len(created), [Path(t.name).exists() for t in created]
    finally:
        for t in created:
            t.cleanup()


class G9bOfflineRows(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        stack = self.enterContext(ExitStack())
        stack.enter_context(mock.patch.object(socket, "create_connection", side_effect=AssertionError("NO_NETWORK")))
        stack.enter_context(mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("NO_NETWORK")))

    def test_pacing_wait_at_the_remaining_budget_refuses_without_sleeping(self):
        # G9b `wait >= self.remaining()`: 1.0 s left waits 0.5 s; 0.5 s left refuses before sleeping or connecting.
        self.assertEqual(f.observe_boundary("G9B-PACE", f.outcome_of(pacing)),
                         ("RESULT", (OK, OK, RB, 2, [0.5], 599.5)))

    def test_retry_waits_never_reach_the_run_deadline(self):
        # G9b retry guards: a Retry-After or the 2 s reconnect wait at or over the remaining time refuses at once.
        self.assertEqual(f.observe_boundary("G9B-RETRY", f.outcome_of(retries)),
                         ("RESULT", ((RB, 1, []), (OK, 2, [9]), (RB, 1, []), (OK, 2, [2]),
                                     (("RAISED", "NetworkBlocked", "UNREACHABLE OSError"), 2, [2]))))

    def test_lease_counters_are_shared_and_bound_new_bytes(self):
        # G9b account_bytes and the capability lane's lease counters (bytes, requests, pacing, deadline).
        self.assertEqual(f.observe_boundary("G9B-LEASE", f.outcome_of(shared_lease)),
                         ("RESULT", ((OK, OK, ("RAISED", "NetworkBlocked", "RUN_CAPTURE_BUDGET"), 3,
                                      {"requests": 3, "bytes": 3000, "last": 2.0, "issuers": {"ZQA": 3}}),
                                     (("RAISED", "NetworkBlocked", "RUN_REQUEST_BUDGET"), 0, 0), (OK, [0.5]),
                                     (RB, 1, []))))

    def test_bind_capability_admits_only_the_default_transport(self):
        # Refused before the store is touched; a second transport joins the lease's counters without resetting them.
        required = ("RAISED", "SystemicFailure", "CAPABILITY_TRANSPORT_REQUIRED")
        self.assertEqual(f.observe_boundary("G9B-BIND", f.outcome_of(binding)),
                         ("RESULT", ((required,) * 3, [], ("RESULT", None), ("RESULT", None), ["live", "live"], True, True,
                                     7, True)))

    def test_capability_run_refuses_foreign_inputs_and_transports_before_any_read(self):
        required = ("RAISED", "SystemicFailure", "CAPABILITY_TRANSPORT_REQUIRED")
        self.assertEqual(f.observe_boundary("G9B-CAPABILITY", f.outcome_of(capability_gates)),
                         ("RESULT", (("RAISED", "SystemicFailure", "CAPABILITY_INPUT_SOURCE_CONFLICT"), required, required,
                                     ("RAISED", "EffectiveInputsError", "CAPABILITY_EPOCH"), [])))

    def test_queue_file_errors_only_reset_the_order(self):
        default = {"last_served": None}
        self.assertEqual(f.observe_boundary("G9B-QUEUE", f.outcome_of(queue_files)),
                         ("RESULT", ([default] * 7 + [{"last_served": "ZQA"}, default],
                                     ("RAISED", "SystemicFailure", "QUEUE PermissionError"))))

    def test_queue_cursor_is_a_hint_and_a_write_failure_stops_before_fetching(self):
        self.assertEqual(f.observe_boundary("G9B-QUEUE-RUN", f.outcome_of(queue_runs)),
                         ("RESULT", (["RESULT", C, ("RESULT", B, A), ("RESULT", A, C), ("RESULT", A, C)],
                                     (("RAISED", "SystemicFailure", "QUEUE PermissionError"), 0, True, 2, False))))

    def test_nbis_store_accounting_is_checked_before_each_request(self):
        # G9a N1 fixed: unknown accounting or a full store makes no request; a crossing fetch still refuses after it.
        self.assertEqual(f.observe_boundary("G9B-NBIS-STORE", f.outcome_of(nbis_store)),
                         ("RESULT", [(UQ, [], False), (UQ, [], False), (UQ, [f.SUBMISSIONS], False),
                                     (("BLOCKED", "WAITING", "CAPTURE_LIMIT", "RUN_CAPTURE_BUDGET"), [f.SUBMISSIONS], False)]))

    def test_segment_sealed_before_a_size_refusal_is_reused(self):
        # G9a F5 and G9b (d)/(f): the refused publication leaves one unreferenced segment; the next publication seals
        # the same 32 attempts into that very file, open stays at most 32, the audit counts all 33, admission reads none.
        self.assertEqual(f.observe_boundary("G9B-SEGMENT", f.outcome_of(sealed_before_refusal)),
                         ("RESULT", ("RESULT", (TOO_LARGE, ((A, 2),), 1, 0, True, 33), ("RESULT", True, True, 32, 1, 33),
                                     ("RESULT", ((A, 2),), 0, 5))))

    def test_generation_too_large_persists_across_runs(self):
        # G9a F10: nothing is compacted, so every later run refuses the same way before any fetch or pointer move.
        self.assertEqual(f.observe_boundary("G9B-TOO-LARGE", f.outcome_of(too_large_twice)),
                         ("RESULT", (TOO_LARGE, TOO_LARGE, 1, 1, True, 0, 0)))

    def test_settled_overflow_is_issuer_local_and_a_later_publication_succeeds(self):
        # G9a F3: B is refused alone with its entry restored, so C's detection and BLOCKED outcome still publish.
        self.assertEqual(f.observe_boundary("G9B-SETTLED", f.outcome_of(overflow_then_publish)),
                         ("RESULT", (({"action": "ATTEMPTED", "event": h.acc(0, 1), "outcome": "WAITING", "reason": "NETWORK_UNAVAILABLE"},
                                      {"action": "BLOCKED", "reason": "SETTLED_OVERFLOW"},
                                      {"action": "ATTEMPTED", "event": h.acc(2, 900001), "outcome": "BLOCKED", "reason": "EVENT_UNRESOLVED"}),
                                     ((A, 2), (B, 1), (C, 1)), C, (0, 256, 1), "EVENT_DETECTED", ("BLOCKED", "EVENT_UNRESOLVED"))))

    def test_a_superseding_wait_keeps_the_captures_already_referenced(self):
        self.assertEqual(f.observe_boundary("G9B-MERGE", f.outcome_of(merged_wait)),
                         ("RESULT", (True, False, 1, "RUN_BUDGET", {"submissions": "c" * 64, "ir_copy": "b" * 64})))

    def test_world_construction_failure_removes_its_directory(self):
        # G9a REV-4: a builder error cleans the TemporaryDirectory at once instead of leaving it to the finalizer.
        self.assertEqual(f.observe_boundary("G9B-WORLD", f.outcome_of(construction_failure)),
                         ("RESULT", (("RAISED", "ValueError", "synthetic builder validation: 'SYNTHETIC'"), 1, [False])))


if __name__ == "__main__":
    unittest.main()
