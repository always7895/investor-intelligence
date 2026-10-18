"""SYNTHETIC_G9_NOT_GENUINE: one complete capability-mode updater cycle over a mocked held B1 namespace.

`updater.run` is driven with a real `overlay.B1Store` over the lease mirror of tests/test_revenue_guidance_b1_contract.py
(a real NativeStorageLease object, in-memory namespace operations) on the synthetic issuers of
tests/g9a_synthetic_issuers.py, with an offline connector. Control inputs come from `B1Store.input` (digest-bound),
receipts from `B1Store`, nothing from a path, no StateLock; publication goes through the lease only.

What this proves: the capability BRANCH logic of `run` (inputs, lease counters, store-op order, parity with the path
branch). What it does not prove: the transport guard (G9B-BIND in test_revenue_guidance_g9b_offline pins that; this
module patches the module's `_connect`/`_public_resolver` and passes the same objects, so the identity check passes by
construction), Windows protected storage, native readback or native lease timing (G3). The cycle sleeps for real
(`time.sleep` is part of the default-transport identity), 0.5 s per request, so the scenario has one issuer.
"""
from __future__ import annotations

from collections import Counter
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
import re
import socket
from types import SimpleNamespace
import time
import unittest
from unittest import mock

from tests import g9a_synthetic_issuers as h
from tests import nbis_synthetic_sources as f
from tests import test_revenue_guidance_b1_contract as b1c  # module alias only: its TestCase classes are not re-collected here

import revenue_guidance_windows as windows  # noqa: E402 (tests.nbis_synthetic_sources put scripts/ on sys.path)

updater, overlay, guidance = f.updater, f.overlay, h.guidance
SYM = h.SYMS[0]
SCRIPTS = h.ROOT / "scripts"
USAGE_ZERO = json.dumps({"bytes": 0, "files": 0, "pending": {}}, sort_keys=True).encode("utf-8")
DIRECT = ("read_bytes", "read_text", "write_bytes", "write_text", "exists", "is_dir", "is_file", "iterdir", "mkdir",
          "glob", "unlink", "stat", "open")
BUDGET_STOP = ("RAISED", "BudgetExceededError", "Elapsed admission budget exceeded (not kernel cancellation)")


# ------------------------------------------------------------------ the mocked capability namespace

def seed_path_state(world):
    """Path-mode run 1 with no request budget: the detection generation, pointer and queue file, nothing fetched."""
    outcome = world.run(1, patches={"PER_RUN_REQUESTS": 0})
    return outcome, list(world.calls)


def capability_space(world):
    """A FakeNamespace over a real NativeStorageLease: the World's control inputs bound to their digests, the real
    reviewed implementation bytes, the receipts, and a byte copy of the World's current state tree."""
    control = {"profiles.json": world.profiles.read_bytes(), "registry.json": world.registry.read_bytes(),
               "approval.json": world.approval.read_bytes(), "config.json": b'{"synthetic":"config"}'}
    for name in overlay.IMPLEMENTATION_FILES:
        control[name] = (SCRIPTS / name).read_bytes()
    space = b1c.FakeNamespace(control=control, digests={name: b1c.sha(raw) for name, raw in control.items()})
    for directory in ("captures", "generations", "segments"):
        space.mkdir(directory)
    if world.state.exists():
        for path in sorted(world.state.rglob("*")):
            parts = path.relative_to(world.state).parts
            if path.is_file() and parts[0] != "lock":
                space.put(parts, path.read_bytes())
    if not space.exists(("store_usage.json",)):
        space.put(("store_usage.json",), USAGE_ZERO)
    space.put(("receipts.json",), world.receipts.read_bytes())
    return space


def blobs(space):
    """Every file of the mock namespace: path tuple -> bytes."""
    out = {}

    def walk(node, path):
        for name, child in sorted(node.children.items()):
            if type(child) is b1c.Node:
                walk(child, path + (name,))
            else:
                out[path + (name,)] = child.data

    walk(space.root, ())
    return out


def files_under(blob_map, top):
    return {path[1:]: data for path, data in blob_map.items() if path[0] == top}


def path_files(world, top):
    root = world.state / top
    return {p.relative_to(root).parts: p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()} if root.exists() else {}


def chain_of(blob_map):
    """The generations behind the pointer of a namespace copy, oldest first, each with its digest check."""
    pointer, out = json.loads(blob_map[("current.json",)]), []
    while pointer:
        raw = blob_map[("generations", pointer["generation_id"] + ".json")]
        gen = json.loads(raw)
        out.append((gen, b1c.sha(raw) == pointer["sha256"]))
        pointer = gen["parent"]
    return list(reversed(out))


def tree_digests(world):
    return {p.relative_to(world.state).parts: b1c.sha(p.read_bytes()) for p in sorted(world.state.rglob("*")) if p.is_file()}


def normalized(generations):
    """Generation ids carry a random suffix (and the parent link names it): compare everything else."""
    return [{k: v for k, v in gen.items() if k not in ("generation_id", "parent")} for gen in generations]


def summary_of(result):
    return {k: v for k, v in result[1].items() if k != "generation_id"}


def kind(entry):
    op, path = entry[0], entry[1]
    if op == "create_directory":
        return "D"
    if op == "replace_mutable":
        return {("store_usage.json",): "U", ("queue.json",): "Q", ("current.json",): "P"}.get(path, "X")
    if op == "publish_named_immutable" and path[0] == "generations":
        return "G"
    if op == "publish_named_immutable" and path[0] == "segments":
        return "S"
    if op == "publish_named_immutable" and path[0] == "captures" and len(path) == 3:
        return "M" if path[2].endswith(".json") else "R"
    return "X"


def order_facts(space, start):
    """(mutation kinds, pointer always moves right after its generation file, each meta right after its raw capture)."""
    rows = space.mutations(start)
    kinds = [kind(r) for r in rows]
    pointer_last = all(
        kinds[i - 1] == "G" and rows[i - 1][1][1] == json.loads(rows[i][2])["generation_id"] + ".json"
        and b1c.sha(rows[i - 1][2]) == json.loads(rows[i][2])["sha256"] for i, k in enumerate(kinds) if k == "P")
    meta_after_raw = all(
        kinds[i - 1] == "R" and rows[i - 1][1] == rows[i][1][:2] + (rows[i][1][2][:-len(".json")],)
        for i, k in enumerate(kinds) if k == "M")
    return "".join(kinds), pointer_last, meta_after_raw


@contextmanager
def no_direct_files(prefixes):
    """Refuse any pathlib access to the World's tree or the product default inputs while the capability run executes."""
    def wrap(real):
        def inner(self, *args, **kwargs):
            if any(str(self).startswith(p) for p in prefixes):
                raise AssertionError("DIRECT_FILESYSTEM " + real.__name__)
            return real(self, *args, **kwargs)
        return inner

    with ExitStack() as stack:
        for name in DIRECT:
            stack.enter_context(mock.patch.object(Path, name, wrap(getattr(Path, name))))
        yield


def run_capability(world, space, instant, hook=None):
    """One updater.run in a fresh lease epoch over `space`; the module's _connect/_public_resolver are replaced by
    one offline fake each and the SAME objects are passed to Transport, so only the capability branch is exercised."""
    calls = []
    lease = space.reopen()  # a later invocation: new lease object, budget and epoch over the same tree
    hosts = [h.host(s) for s in world.syms]

    def connector(name, address, path, headers, timeout):
        if name == "data.sec.gov":
            i, what = int(re.fullmatch(r"/submissions/CIK([0-9]{10})\.json", path)[1]) - h.cik(0), "SUB"
        elif name == "www.sec.gov":
            i, what = int(path.split("/")[4]) - h.cik(0), "INDEX" if path.endswith("/index.json") else "DOC"
        else:
            i, what = hosts.index(name), "IR"
        status = 404 if what == "IR" else 200
        calls.append((world.syms[i], what, status))
        if hook is not None:
            hook(lease, len(calls))
        raw, ctype = world.payload(i, what, path.rsplit("/", 1)[-1])
        return h.Response(status, raw, ctype)

    def resolver(name):
        return ["162.159.140.1"]

    forbidden = tuple(str(p) for p in (world.root, updater.PROFILES_PATH, updater.REGISTRY_PATH, updater.APPROVAL_PATH,
                                       updater.RECEIPTS_PATH, getattr(overlay, "PROFILES_DEFAULT", None),
                                       getattr(guidance, "REGISTRY_PATH", None), getattr(guidance, "APPROVAL_PATH", None),
                                       getattr(guidance, "RELEASE_CHECKS_CACHE_PATH", None)) if p is not None)
    start = len(space.log)
    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(socket, "create_connection", side_effect=AssertionError("NO_NETWORK")))
        stack.enter_context(mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("NO_NETWORK")))
        stack.enter_context(mock.patch.object(windows, "_lazy_bind", side_effect=AssertionError("native binding reached")))
        stack.enter_context(mock.patch.object(overlay, "SUPPORTED_AUTO", tuple(world.syms)))
        stack.enter_context(mock.patch.object(updater, "_connect", connector))
        stack.enter_context(mock.patch.object(updater, "_public_resolver", resolver))
        stack.enter_context(mock.patch.object(updater, "StateLock", side_effect=AssertionError("STATE_LOCK")))
        stack.enter_context(no_direct_files(forbidden))
        transport = updater.Transport({"User-Agent": "G9B-CAPABILITY"}, connector=connector, resolver=resolver)

        def cycle():
            with lease.namespace_operation():
                return updater.run(overlay.B1Store(lease), transport, lambda: instant)

        result = f.outcome_of(cycle)
    return SimpleNamespace(result=result, calls=calls, transport=transport, lease=lease, start=start)


class CapabilityCycleTests(unittest.TestCase):
    """The whole scenario is built once (the cycle paces with real sleeps); each test reads one facet of it."""
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.world = h.World(1, 0)
        cls.addClassCleanup(cls.world.tmp.cleanup)
        w = cls.world
        cls.seed_outcome, cls.seed_calls = seed_path_state(w)
        cls.space = capability_space(w)
        cls.state_before = tree_digests(w)
        cls.pointer_seed = cls.space.get(("current.json",))
        cls.cap2 = run_capability(w, cls.space, h.at(2))
        cls.after2 = blobs(cls.space)
        cls.facts2 = order_facts(cls.space, cls.cap2.start)
        cls.state_after = tree_digests(w)
        cls.path2 = w.run(2)
        cls.path2_calls = [(s, k) for _, s, k in w.calls]
        cls.path2_files = {top: path_files(w, top) for top in ("captures", "generations", "segments")}
        cls.path2_chain = [gen for _, gen in reversed(w.walk())]
        cls.path2_queue, cls.path2_usage = w.cur(), json.loads((w.state / "store_usage.json").read_bytes())
        cls.cap3 = run_capability(w, cls.space, h.at(3))
        cls.after3 = blobs(cls.space)
        cls.facts3 = order_facts(cls.space, cls.cap3.start)
        cls.path3 = w.run(3)
        cls.path3_calls = [(s, k) for _, s, k in w.calls]
        cls.path3_chain = [gen for _, gen in reversed(w.walk())]

    def test_the_seed_is_a_published_detection_with_nothing_fetched(self):
        # The capability lane starts from a pointed generation (see test_capability_run_needs_an_existing_pointer).
        self.assertEqual((self.seed_outcome[0], self.seed_calls, self.pointer_seed is not None), ("RESULT", [], True))

    def test_summary_and_generations_equal_the_path_cycle(self):
        self.assertEqual(self.cap2.result[0], "RESULT", self.cap2.result)
        self.assertEqual(self.path2[0], "RESULT", self.path2)
        self.assertEqual(summary_of(self.cap2.result), summary_of(self.path2))
        self.assertEqual(self.cap2.result[1]["issuers"][SYM]["action"], "ATTEMPTED")
        self.assertEqual([(s, k) for s, k, _ in self.cap2.calls], self.path2_calls)
        cap_chain = chain_of(self.after2)
        self.assertTrue(all(ok for _, ok in cap_chain), "a generation digest does not match its pointer or child")
        self.assertEqual(normalized([g for g, _ in cap_chain]), normalized(self.path2_chain))
        self.assertGreaterEqual(len(cap_chain), 2)  # the seeded detection generation and at least one written by this cycle
        links = [g["parent"]["generation_id"] for g, _ in cap_chain[1:]]
        self.assertEqual(links, [g["generation_id"] for g, _ in cap_chain[:-1]])

    def test_captures_segments_queue_and_usage_equal_the_path_cycle(self):
        for top in ("captures", "generations", "segments"):
            cap = files_under(self.after2, top)
            if top == "generations":
                self.assertEqual(len(cap), len(self.path2_files[top]))
            else:
                self.assertEqual(cap, self.path2_files[top], top)
        self.assertTrue(files_under(self.after2, "captures"), "the cycle stored no capture")
        self.assertEqual(json.loads(self.after2[("queue.json",)])["last_served"], self.path2_queue)
        self.assertEqual(json.loads(self.after2[("store_usage.json",)]), self.path2_usage)
        self.assertEqual(self.path2_usage["pending"], {})

    def test_every_store_write_goes_through_the_lease_in_the_documented_order(self):
        # U reservation/usage, D bucket, R raw capture then M its metadata, G generation file then P pointer, Q queue.
        kinds, pointer_last, meta_after_raw = self.facts2
        self.assertEqual((kinds[:1], pointer_last, meta_after_raw), ("U", True, True), kinds)
        self.assertEqual(set(kinds) - set("UDRMGPQS"), set(), kinds)  # no write of any other shape
        self.assertIn("P", kinds)
        self.assertIn("R", kinds)
        self.assertLess(kinds.index("Q"), kinds.index("R"))  # the queue position is written before the first fetch
        self.assertEqual(kinds.count("G"), kinds.count("P"))
        # Control inputs came from the held, digest-bound control capture, never an unbound read.
        bound = {entry[1]: entry[3] for entry in self.space.log[self.cap2.start:]
                 if entry[0] == "capture_bytes" and entry[1][0] == "control"}
        expected = {("control", name): bytes.fromhex(b1c.sha(raw)) for name, raw in self.space.control.items()
                    if name in ("profiles.json", "registry.json", "approval.json") + overlay.IMPLEMENTATION_FILES}
        self.assertEqual({k: v for k, v in bound.items() if k in expected}, expected)
        self.assertEqual(self.space.open, [])  # no owned directory handle leaked

    def test_lease_counters_are_shared_and_nothing_touches_the_filesystem_or_a_lock(self):
        run = self.cap2
        # bind_capability binds the transport to the lease and creates the shared counters; a skipped bind is a FAIL here.
        self.assertIs(run.transport.lease, run.lease)
        self.assertTrue(hasattr(run.lease, "_network_work"), "bind_capability did not run")
        work = run.lease._network_work  # created by bind_capability on the lease, shared by every transport of it
        self.assertGreater(len(run.calls), 0)
        self.assertEqual((work["requests"], run.transport.requests), (len(run.calls), len(run.calls)))
        self.assertEqual(work["issuers"], dict(Counter(s for s, _, _ in run.calls)))
        self.assertEqual(work["bytes"], 1000 * sum(1 for _, _, status in run.calls if status == 200))
        self.assertEqual(work["last"], run.transport.last)
        self.assertGreaterEqual(run.transport.started, run.lease.budget.start_time)
        # The World's own state and input files were not read or written by the capability run (the guard refused any
        # pathlib access to them or to the product default inputs; StateLock was replaced by a raising stand-in).
        self.assertEqual(self.state_after, self.state_before)

    def test_a_repeat_cycle_equals_the_path_repeat(self):
        self.assertEqual(self.cap3.result[0], "RESULT", self.cap3.result)
        self.assertEqual(summary_of(self.cap3.result), summary_of(self.path3))
        self.assertEqual([(s, k) for s, k, _ in self.cap3.calls], self.path3_calls)
        cap_chain = chain_of(self.after3)
        self.assertEqual(normalized([g for g, _ in cap_chain]), normalized(self.path3_chain))
        kinds, pointer_last, meta_after_raw = self.facts3
        self.assertEqual((kinds[:1], pointer_last, meta_after_raw), ("U", True, True), kinds)
        if len(self.path3_chain) == len(self.path2_chain):  # nothing new to publish: the pointer did not move
            self.assertEqual(self.after3[("current.json",)], self.after2[("current.json",)])
            self.assertEqual(set(kinds) - set("UQ"), set(), kinds)

    def test_capability_run_needs_an_existing_pointer(self):
        # Current behaviour, not a design claim: load_effective_inputs runs with state_required=True in the capability
        # branch, so a held namespace with no pointer is a systemic stop before any write or request (the path branch
        # creates its first generation). Whoever provisions the namespace must therefore seed the first generation.
        with h.World(1, 0) as w:
            space = capability_space(w)
            run = run_capability(w, space, h.at(1))
            self.assertEqual(run.result[:2], ("RAISED", "SystemicFailure"), run.result)
            self.assertTrue(run.result[2].startswith("STATE "), run.result)
            self.assertEqual((space.mutations(run.start), run.calls, space.open), ([], [], []))


class LeaseDeadlineCycleTests(unittest.TestCase):
    """G9 O7 at run level: the lease deadline passing mid-fetch is a storage stop, resumable next run."""
    maxDiff = None

    def test_the_lease_deadline_passing_during_a_fetch_stops_the_run_before_any_publication(self):
        with h.World(1, 0) as w:
            seed_path_state(w)
            space = capability_space(w)
            before = blobs(space)

            def expire(lease, count):
                lease.budget.deadline = time.monotonic() - 1.0  # the lease deadline passes while the first request is in flight

            stopped = run_capability(w, space, h.at(2), hook=expire)
            after = blobs(space)
            self.assertEqual(stopped.result, BUDGET_STOP)  # not a WAITING outcome, not a SystemicFailure of the updater
            self.assertEqual((stopped.transport.requests, stopped.lease._network_work["requests"]), (1, 1))
            self.assertEqual(order_facts(space, stopped.start)[0], "UQ")  # usage reconcile, queue position; nothing after
            steady = (set(before) | set(after)) - {("queue.json",), ("store_usage.json",)}
            self.assertEqual({p: before.get(p) for p in steady}, {p: after.get(p) for p in steady})  # pointer, generations, captures
            self.assertEqual(json.loads(after[("queue.json",)]), {"last_served": SYM})
            self.assertEqual(json.loads(after[("store_usage.json",)]), {"bytes": 0, "files": 0, "pending": {}})
            self.assertEqual(space.open, [])
            # The next run (fresh lease) serves the issuer: it was the only one, so the advanced queue wraps to it.
            resumed = run_capability(w, space, h.at(3))
            self.assertEqual(resumed.result[0], "RESULT", resumed.result)
            self.assertEqual(resumed.result[1]["issuers"][SYM]["action"], "ATTEMPTED")
            self.assertNotEqual(space.get(("current.json",)), before[("current.json",)])


if __name__ == "__main__":
    unittest.main()
