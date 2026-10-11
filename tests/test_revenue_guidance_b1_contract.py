"""B1Store, B1Outputs, capture accounting and host public capture over a fake lease.

The lease is a real ``revenue_guidance_storage.NativeStorageLease`` object (the
exact type B1Store admits) built without acquisition. Its real
``namespace_operation`` epoch, ``_namespace_guard``, ``constrain_remaining_budget``
and ``NativeBudget`` run unchanged. Only the namespace operations the B1 adapter
calls (open/create/enumerate/close of held directories, ``capture_bytes``,
``capture_mutable``, ``replace_mutable`` and ``publish_named_immutable``) are
replaced on that instance by an in-memory tree that mirrors their precondition,
identity and compare semantics (revenue_guidance_storage.py NativeStorageLease);
the ranking-pause case also replaces ``read_journal``/``commit_journal``. Host
cases use a fake controlled origin, a fake pinned TLS connection and a fake
resolver; the ranking universe is the repository's layer configuration. A
failing native-binding sentinel guards every case. No native API, handle, ACL,
registry, network request, model build or durability is exercised: these are
mocked caller contracts, not G3 native evidence.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
from datetime import datetime, timedelta, timezone
import functools
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import socket
import ssl
import sys
import time
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import revenue_guidance_host as host
import revenue_guidance_overlay as overlay
import revenue_guidance_storage as storage
import revenue_guidance_windows as windows

MiB = 1024 * 1024
A = "gir1:" + "a" * 64
MAX_GEN = overlay.MAX_GENERATION_BYTES
LEDGER = "guidance-output-accounting-v1"
INDEX = "guidance-public-capture-index-v2"
COMPLETION = "guidance-local-completion-v1"
PUBLIC_ADDRESS = "93.184.216.34"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/NVDA?range=5d&interval=1d"
SEC = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json"
CONTROL = {
    "registry.json": b'{"synthetic":"registry"}',
    "approval.json": b'{"synthetic":"approval"}',
    "profiles.json": b'{"synthetic":"profiles"}',
    "config.json": b'{"synthetic":"config"}',
    "revenue_guidance.py": b"# synthetic protected control copy 1\n",
    "revenue_guidance_auto_verify.py": b"# synthetic protected control copy 2\n",
    "revenue_guidance_overlay.py": b"# synthetic protected control copy 3\n",
}
MUTATIONS = ("create_directory", "replace_mutable", "publish_named_immutable")
OPERATIONS = ("open_directory", "close_owned", "create_directory", "enumerate_directory", "capture_bytes",
              "capture_mutable", "replace_mutable", "publish_named_immutable")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True).encode("utf-8")


def stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def plan_id(name):
    return sha(("guidance-acquisition-v2/" + name).encode())


def journal_state(revision=A, pending=None, intent=None):
    return {"Schema": "guidance-provider-journal-v1", "StateRequired": True,
            "InputRevision": revision, "PendingRevision": pending, "Intent": intent}


# ------------------------------------------------------------------ fake held namespace

class Node:
    """Directory with its own stable object identity."""
    def __init__(self, identity):
        self.identity, self.children = identity, {}


class Blob:
    """File bytes and the identity of the object that holds them."""
    def __init__(self, data, identity):
        self.data, self.identity = data, identity


class Handle:
    """Fake held directory owner of one lease (never a path)."""
    def __init__(self, space, lease, path):
        self.space, self.lease, self.path, self.closed = space, lease, path, False


class FakeNamespace:
    """In-memory B1 tree behind a real NativeStorageLease object.

    Every lease operation first runs the lease's REAL ``_namespace_guard`` (held
    lock + live epoch; close uses the real cleanup custody check) and mirrors
    the native preconditions: names through
    windows._namespace_name, exact caps, captured-state lease/epoch/parent/name
    binding, identity+bytes compare before replace, digest-bound no-replace
    immutable publication and digest-checked capture. Each new object gets a
    fresh identity. ``faults`` raise once before a mutation (the lease stays
    usable, as after a refused pre-mutation step); ``tamper`` makes one capture
    return other bytes without the native digest check.
    """
    def __init__(self, *, control=None, digests=None, limits=None, schema="guidance-provider-storage-v2"):
        self._serial = 0
        self.root = Node(self.identity())
        self.control = dict(CONTROL if control is None else control)
        source = {name: sha(raw) for name, raw in CONTROL.items()} if digests is None else digests
        self.digests = tuple(sorted(source.items()))
        self.limits = storage.NativeLimits.b1(600000) if limits is None else limits
        self.schema = schema
        self.log, self.open, self.results = [], [], []
        self.faults, self.tamper = [], {}
        self.on_enumerate = None
        self.lease = None
        self.reopen()

    def identity(self):
        self._serial += 1
        return storage.ObjectIdentity(volume_serial=7, file_id=self._serial.to_bytes(16, "little"))

    def reopen(self):
        """A later invocation: a new lease object (budget, epoch, owners) over the same tree."""
        lease = storage.NativeStorageLease.__new__(storage.NativeStorageLease)
        lease.anchor = SimpleNamespace(schema_version=self.schema, bootstrap_id="synthetic-bootstrap",
                                       input_digests=self.digests, coordination_identity=None, journal_identity=None)
        lease._initialize_custody(self.limits)
        lease._state = "READY"
        lease.b1_handle = Handle(self, lease, ())
        for name in OPERATIONS:
            setattr(lease, name, functools.partial(getattr(self, "_" + name), lease))
        self.lease = lease
        return lease

    # seeding and inspection (never logged)
    def node(self, path):
        current = self.root
        for name in path:
            current = current.children.get(name) if type(current) is Node else None
            if current is None:
                raise windows.StorageObjectMissingError("synthetic object missing")
        return current

    def mkdir(self, *path):
        current = self.root
        for name in path:
            child = current.children.get(name)
            if child is None:
                child = current.children[name] = Node(self.identity())
            current = child
        return current

    def put(self, path, data):
        self.mkdir(*path[:-1]).children[path[-1]] = Blob(data, self.identity())

    def remove(self, path):
        del self.node(path[:-1]).children[path[-1]]

    def rebind(self, path):
        self.node(path).identity = self.identity()

    def get(self, path):
        return self.node(path).data

    def json(self, path):
        return json.loads(self.get(path))

    def exists(self, path):
        try:
            self.node(path)
        except windows.StorageObjectMissingError:
            return False
        return True

    def snapshot(self):
        out = {}
        def walk(node, path):
            out[path] = ("directory", node.identity)
            for name, child in node.children.items():
                if type(child) is Node:
                    walk(child, path + (name,))
                else:
                    out[path + (name,)] = (child.data, child.identity)
        walk(self.root, ())
        return out

    def mutations(self, start=0):
        return [entry for entry in self.log[start:] if entry[0] in MUTATIONS]

    def last(self, operation):
        return [entry for entry in self.log if entry[0] == operation][-1]

    # lease operations
    def _guard(self, lease):
        lease._namespace_guard()  # the REAL held-lock/live-epoch guard

    def _held(self, lease, handle):
        if type(handle) is not Handle or handle.lease is not lease or handle.closed:
            raise windows.StorageValidationFault("Wrong namespace lease")
        node = self.node(handle.path)
        if type(node) is not Node:
            raise windows.StorageValidationFault("synthetic directory owner required")
        return node

    def _fault(self, operation, path):
        for position, (fault_operation, fault_path, error) in enumerate(self.faults):
            if (fault_operation, fault_path) == (operation, path):
                del self.faults[position]
                raise error

    def _open_directory(self, lease, components):
        self._guard(lease)
        if type(components) not in (tuple, list):
            raise windows.StorageValidationFault("Directory components required")
        names = tuple(components)
        if len(names) < 2 or names[0] != "b1":
            raise windows.StorageValidationFault("Only strict B1 directory descent admitted")
        for name in names:
            windows._namespace_name(name)
        self.log.append(("open_directory", names[1:]))
        if type(self.node(names[1:])) is not Node:
            raise windows.StorageValidationFault("synthetic directory required")
        handle = Handle(self, lease, names[1:])
        self.open.append(handle)
        return handle

    def _close_owned(self, lease, handle):
        windows._require_context(lease, None, cleanup=True)  # held lock; cleanup is not budget-timed
        if handle is lease.b1_handle:
            raise windows.StorageValidationFault("Control/root custody closes only with lease Close")
        if (type(handle) is not Handle or handle.lease is not lease or handle.closed or
                not any(item is handle for item in self.open)):
            raise windows.StorageValidationFault("synthetic unregistered owner")
        handle.closed = True
        self.open = [item for item in self.open if item is not handle]
        self.log.append(("close_owned", handle.path))

    def _create_directory(self, lease, parent, name):
        self._guard(lease)
        node = self._held(lease, parent)
        windows._namespace_name(name)
        path = parent.path + (name,)
        self._fault("create_directory", path)
        if name in node.children:
            raise windows.StorageObjectExistsError("synthetic name collision")
        node.children[name] = Node(self.identity())
        self.log.append(("create_directory", path))
        handle = Handle(self, lease, path)
        self.open.append(handle)
        return handle

    def _enumerate_directory(self, lease, parent):
        self._guard(lease)
        self._held(lease, parent)
        self.log.append(("enumerate_directory", parent.path))
        if self.on_enumerate is not None:
            hook, self.on_enumerate = self.on_enumerate, None
            hook(parent.path)
        return tuple(sorted(self._held(lease, parent).children))

    def _capture_bytes(self, lease, components, max_bytes, expected_sha256=None, *, raw_document=False, historical=False):
        self._guard(lease)
        cap = lease.budget.object_cap(raw_document)
        if type(historical) is not bool:
            raise windows.StorageValidationFault("historical must be exact bool")
        if type(max_bytes) is not int or not 0 <= max_bytes <= cap:
            raise storage.BudgetExceededError("Requested bytes invalid or exceeds hard limit")
        if expected_sha256 is not None and (type(expected_sha256) is not bytes or len(expected_sha256) != 32):
            raise windows.StorageValidationFault("expected_sha256 must be exactly 32 bytes or None")
        names = tuple(components)
        for name in names:
            windows._validate_component(name)
        self.log.append(("capture_bytes", names, max_bytes, expected_sha256, raw_document, historical))
        if len(names) == 2 and names[0] == "control":
            if names[1] not in self.control:
                raise windows.StorageObjectMissingError("synthetic control missing")
            data = self.control[names[1]]
        elif len(names) >= 2 and names[0] == "b1":
            item = self.node(names[1:])
            if type(item) is not Blob:
                raise windows.StorageValidationFault("Object invalid or exceeds max_bytes")
            data = item.data
        else:
            raise windows.StorageObjectMissingError("synthetic object outside the fake root")
        if len(data) > max_bytes:
            raise windows.StorageValidationFault("Object invalid or exceeds max_bytes")
        lease.budget.admit_capture(len(data), historical=historical, raw_document=raw_document)
        if names in self.tamper:
            data = self.tamper.pop(names)  # lying readback: only the caller's own digest can refuse it
            return data, hashlib.sha256(data).digest()
        digest = hashlib.sha256(data).digest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise windows.StorageValidationFault("Object SHA256 mismatch")
        return data, digest

    def _capture_mutable(self, lease, parent, name):
        self._guard(lease)
        node = self._held(lease, parent)
        windows._namespace_name(name)
        item = node.children.get(name)
        if item is not None and type(item) is not Blob:
            raise windows.StorageValidationFault("synthetic directory is not a mutable object")
        if item is not None and len(item.data) > lease.budget.object_cap():
            raise storage.BudgetExceededError("Existing object exceeds supported profile; not truncated")
        if item is None:
            state = storage._CapturedMutableState(lease, lease._live_operation, node.identity, name, None, None)
        else:
            lease.budget.admit_capture(len(item.data))
            state = storage._CapturedMutableState(lease, lease._live_operation, node.identity, name,
                                                  item.identity, item.data)
        self.log.append(("capture_mutable", parent.path + (name,), state))
        return state

    def _replace_mutable(self, lease, parent, name, staging_name, payload, expected):
        self._guard(lease)
        node = self._held(lease, parent)
        windows._namespace_name(name)
        windows._namespace_name(staging_name)
        if type(payload) is not bytes or len(payload) > lease.budget.object_cap():
            raise storage.BudgetExceededError("Payload exceeds supported object policy")
        if (type(expected) is not storage._CapturedMutableState or expected.lease is not lease or
                expected.epoch is not lease._live_operation or expected.parent_identity != node.identity or
                expected.name != name or staging_name.casefold() == name.casefold()):
            raise windows.StorageValidationFault("Same-epoch captured expected state required")
        if (expected.identity is None) != (expected.data is None):
            raise windows.StorageValidationFault("Malformed captured state")
        path = parent.path + (name,)
        current = node.children.get(name)
        if expected.identity is None:
            if current is not None:
                raise storage.NamespaceConflictError("Mutable target appeared")
        elif type(current) is not Blob or current.identity != expected.identity or current.data != expected.data:
            raise storage.NamespaceConflictError("Mutable expected identity/bytes changed")
        self._fault("replace_mutable", path)
        blob = node.children[name] = Blob(payload, self.identity())
        result = storage.NamespaceObjectResult(blob.identity, len(payload), hashlib.sha256(payload).digest(), False)
        self.log.append(("replace_mutable", path, payload, staging_name, expected))
        self.results.append(result)
        return result

    def _publish_named_immutable(self, lease, parent, name, staging_name, payload, expected_content_sha256, *,
                                 raw_document=False):
        self._guard(lease)
        node = self._held(lease, parent)
        windows._namespace_name(name)
        if type(payload) is not bytes or len(payload) > lease.budget.object_cap(raw_document):
            raise storage.BudgetExceededError("Payload exceeds supported object policy")
        digest = hashlib.sha256(payload).digest()
        if (type(expected_content_sha256) is not bytes or len(expected_content_sha256) != 32 or
                digest != expected_content_sha256):
            raise windows.StorageValidationFault("Immutable content digest does not match actual payload")
        windows._namespace_name(staging_name)
        if staging_name.casefold() == name.casefold():
            raise windows.StorageValidationFault("Staging and publication names must differ")
        path = parent.path + (name,)
        existing = node.children.get(name)
        if existing is not None:
            if type(existing) is not Blob or existing.data != payload:
                raise storage.IdentityMismatchError("Existing named immutable content digest mismatch")
            result = storage.NamespaceObjectResult(existing.identity, len(payload), digest, True)
        else:
            self._fault("publish_named_immutable", path)
            blob = node.children[name] = Blob(payload, self.identity())
            result = storage.NamespaceObjectResult(blob.identity, len(payload), digest, False)
        self.log.append(("publish_named_immutable", path, payload, staging_name, expected_content_sha256, raw_document))
        self.results.append(result)
        return result


class FakeLeaseCase(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(windows, "_lazy_bind", side_effect=AssertionError("native binding reached")))
        self.space = self.fresh()
        self.lease = self.space.lease

    def fresh(self, **options):
        space = FakeNamespace(**options)
        self.addCleanup(lambda: self.assertEqual(space.open, [], "owned directory handle leaked"))
        return space


# ------------------------------------------------------------------ capture / output fixtures

def capture_meta(raw, retrieved_at="2026-01-02T03:04:05Z", url="https://www.sec.gov/Archives/edgar/data/1/a.htm"):
    return json.dumps({"url": url, "accession": None, "form": None, "filed": None, "retrieved_at": retrieved_at,
                       "bytes": len(raw), "raw_sha256": sha(raw),
                       "sha256": overlay.verify.sha256(overlay.verify.canonical_bytes(raw)),
                       "content_type": "text/html", "role": "filing"}, sort_keys=True).encode("utf-8")


def put_capture(space, raw, with_meta=True, retrieved_at="2026-01-02T03:04:05Z"):
    digest = sha(raw)
    space.put(("captures", digest[:2], digest), raw)
    if with_meta:
        space.put(("captures", digest[:2], digest + ".json"), capture_meta(raw, retrieved_at))
    return digest


def ledger_doc(claimed, entries=(), captures=(), pending=None):
    return {"schema": LEDGER, "bytes": claimed, "entries": list(entries), "captures": list(captures), "pending": pending}


def completion(rank, body, tag="x"):
    return encode({"schema": COMPLETION, "ranking_sha256": sha(rank), "output_sha256": sha(body), "tag": tag})


def bundle(tag):
    rank, body = encode({"rank": tag}), encode({"body": tag})
    return rank, body, completion(rank, body, tag)


def index_row(url, data=None, pack=None, offset=0, retrieved_at="2026-10-10T00:00:00Z", status="CAPTURED",
              http_status=200):
    return {"url": url, "sha256": None if data is None else sha(data), "pack": pack, "offset": offset,
            "retrieved_at": retrieved_at, "bytes": 0 if data is None else len(data), "status": status,
            "http_status": http_status}


def index_doc(entries=None, progress=None):
    return {"schema": INDEX, "entries": {} if entries is None else entries, "progress": {} if progress is None else progress}


def seed_outputs(space, bundles=(), packs=(), entries=None, progress=None, claimed=None, ledger=None, index=None):
    """An existing b1/outputs layout; returns the actual unique retained payload bytes M."""
    space.mkdir("outputs", "cache")
    total, records = 0, []
    for rank, body, record in bundles:
        for kind, raw in (("rank", rank), ("body", body), ("record", record)):
            path = ("outputs", f"{kind}-{sha(raw)}.json")
            if not space.exists(path):
                space.put(path, raw)
                total += len(raw)
        records.append(sha(record))
    for pack in packs:
        space.put(("outputs", "cache", sha(pack)), pack)
        total += len(pack)
    if type(ledger) is not bytes:
        ledger = encode(ledger if ledger is not None else
                        ledger_doc(total if claimed is None else claimed, records, [sha(pack) for pack in packs]))
    space.put(("outputs", "ledger.json"), ledger)
    if type(index) is not bytes:
        index = encode(index if index is not None else index_doc(entries, progress))
    space.put(("outputs", "capture-index.json"), index)
    return total


# ------------------------------------------------------------------ host fakes

class FakeOrigin:
    """Controlled-origin stand-in: fixed protected files and public role bytes."""
    def __init__(self, public=None, files=None):
        self.public = dict(public or {})
        self.files = dict(files if files is not None else {"scripts/revenue_guidance_host.py": b"# synthetic host\n",
                                                           "config/order-claims-v2.json": b"{}"})
        self.policy = {"release_id": "synthetic-release"}
        self.calls, self.closed = [], 0

    def capture_public_input(self, relative, budget, cap):
        self.calls.append((relative, budget, cap))
        raw = self.public.get(relative)
        return raw, {"status": "PUBLIC_CAPTURE" if raw is not None else "PUBLIC_ABSENT",
                     "sha256": None if raw is None else sha(raw)}

    def close(self):
        self.closed += 1


def owner_over(lease, seconds=600.0):
    value = host._Session(time.monotonic() + seconds, {"User-Agent": "synthetic contact"})
    value.lease = lease
    return value


def make_capture(owner, origin):
    with mock.patch.object(host.provisioner, "controlled_origin", return_value=origin) as factory:
        value = host._Capture(owner)
    factory.assert_called_once_with()
    return value


def plan_rows(*symbols):
    return [(sha(f"yahoo/chart/{symbol}".encode()), f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
             symbol, 8 * MiB) for symbol in symbols]


class FakeSocket:
    def __init__(self):
        self.timeouts, self.closed = [], 0

    def settimeout(self, value):
        self.timeouts.append(value)

    def close(self):
        self.closed += 1


class FakeResponse:
    """http.client-shaped response; a known length closes the response after its final read."""
    def __init__(self, status=200, body=b"{}", *, length="auto", encoding=None, readable_socket=True, chunk=None,
                 on_read=None):
        self.status, self.body, self.offset, self.chunk = status, body, 0, chunk
        self.length = len(body) if length == "auto" else length
        self.encoding, self.on_read = encoding, on_read
        self.sock = FakeSocket() if readable_socket else None
        self.fp = SimpleNamespace(raw=SimpleNamespace(_sock=self.sock)) if readable_socket else None
        self.closed = 0

    def getheader(self, name, default=None):
        return self.encoding if name == "Content-Encoding" and self.encoding is not None else default

    def read(self, amount):
        if self.on_read is not None:
            self.on_read(self)
        size = min(amount, self.chunk or amount, len(self.body) - self.offset)
        part = self.body[self.offset:self.offset + size]
        self.offset += size
        if self.length is not None:
            self.length -= len(part)
        return part

    def isclosed(self):
        return self.length == 0

    def close(self):
        self.closed += 1


class FakeConnection:
    def __init__(self, net, host_name, address, timeout):
        self.net, self.host, self.address, self.timeout = net, host_name, address, timeout
        self.requests, self.closed = [], 0

    def request(self, method, path, headers=None):
        self.requests.append((method, path, dict(headers or {})))

    def getresponse(self):
        item = self.net.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self):
        self.closed += 1


class FakeTLS:
    """Replaces host._PinnedTLS: records each connection and serves queued responses."""
    def __init__(self, responses):
        self.responses, self.connections, self.lookups, self.sleeps = list(responses), [], [], []

    def __call__(self, host_name, address, timeout):
        connection = FakeConnection(self, host_name, address, timeout)
        self.connections.append(connection)
        return connection


@contextmanager
def network(responses=(), address=PUBLIC_ADDRESS):
    net = FakeTLS(responses)

    def getaddrinfo(name, port, *args, **kwargs):
        net.lookups.append((name, port))
        if isinstance(address, BaseException):
            raise address
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    with mock.patch.object(host, "_PinnedTLS", net), \
            mock.patch.object(host.socket, "getaddrinfo", getaddrinfo), \
            mock.patch.object(host.socket, "create_connection", side_effect=AssertionError("real socket reached")), \
            mock.patch.object(host.time, "sleep", net.sleeps.append):
        yield net


# ------------------------------------------------------------------ G2-10 B1Store / B1Object

class B1StoreOperandTests(FakeLeaseCase):
    def test_constructor_requires_the_exact_b1_lease_profile_layout_and_a_live_epoch(self):
        class Derived(storage.NativeStorageLease):
            pass
        derived = Derived.__new__(Derived)  # the b1 limits and v2 anchor: only the exact type differs
        derived.limits, derived.anchor = self.lease.limits, self.lease.anchor
        for operand in (None, SimpleNamespace(limits=self.lease.limits, anchor=self.lease.anchor), derived):
            with self.subTest(operand=type(operand).__name__):
                with self.assertRaises(Exception) as raised:  # any other refusal is a wrong-type FAIL
                    overlay.B1Store(operand)
                self.assertIs(type(raised.exception), overlay.EffectiveInputsError)
                self.assertEqual(str(raised.exception), "CAPABILITY_TYPE")
        for other in (FakeNamespace(limits=storage.NativeLimits()), FakeNamespace(schema="guidance-provider-storage-v1")):
            with other.lease.namespace_operation():
                with self.assertRaises(overlay.EffectiveInputsError) as raised:
                    overlay.B1Store(other.lease)
            self.assertEqual(str(raised.exception), "CAPABILITY_LAYOUT")
        with self.assertRaises(windows.StorageValidationFault):
            overlay.B1Store(self.lease)  # no held lock / live namespace epoch
        with self.lease.namespace_operation():
            store = overlay.B1Store(self.lease)
            self.assertIs(store.lease, self.lease)
            self.assertIs(store.epoch, self.lease._live_operation)
        self.assertIsNone(self.lease._live_operation)
        self.assertEqual(self.space.log, [])

    def test_a_store_from_an_ended_epoch_refuses_every_operation_before_io(self):
        self.space.put(("current.json",), b"{}")
        with self.lease.namespace_operation():
            old = overlay.B1Store(self.lease)
            child = old / "current.json"
        calls = (lambda: old.read(("current.json",)), lambda: old.write(("current.json",), b"{}"),
                 lambda: old.children(("captures",)), lambda: old.input("registry"),
                 lambda: old.implementation("revenue_guidance.py"), lambda: old.capture_mutable(("current.json",)),
                 lambda: old.ensure_capture_bucket("a" * 64), lambda: child.read_bytes(), lambda: old.iterdir(),
                 lambda: old.exists())
        for call in calls:
            with self.assertRaises(windows.StorageValidationFault):
                call()  # outside any epoch: the real lease guard refuses
        with self.lease.namespace_operation():
            for call in calls:
                with self.assertRaises(overlay.EffectiveInputsError) as raised:
                    call()
                self.assertEqual(str(raised.exception), "CAPABILITY_EPOCH")
        self.assertEqual(self.space.log, [])

    def test_operands_expose_no_path_protocol_or_arbitrary_file_surface(self):
        with self.lease.namespace_operation():
            store = overlay.B1Store(self.lease)
            leaf = store / "captures" / "ab"
            for operand in (store, leaf):
                with self.assertRaises(TypeError):
                    os.fspath(operand)
                with self.assertRaises(TypeError):
                    Path(operand)
                for name in ("__fspath__", "open", "unlink", "write_bytes", "write_text", "mkdir", "rmdir", "rename",
                             "replace", "touch", "stat", "resolve", "with_suffix", "chmod", "symlink_to"):
                    self.assertFalse(hasattr(operand, name), name)
            with self.assertRaises(TypeError):
                open(leaf, "rb")
            with self.assertRaises(overlay.EffectiveInputsError) as raised:
                leaf.glob("*")
            self.assertEqual(str(raised.exception), "CAPABILITY_GLOB")
            for name in ("..", ".", "a/b", "a\\b", "journal.dat", "Coordination.LOCK", "", "CON", "x" * 256, "name.",
                         "tab\t"):
                with self.subTest(name=name[:12]), self.assertRaises(windows.StorageValidationFault):
                    store / name
            for owner, components in ((object(), ("x",)), (store, ["x"]), (store, ())):
                with self.assertRaises(overlay.EffectiveInputsError) as raised:
                    overlay.B1Object(owner, components)
                self.assertEqual(str(raised.exception), "CAPABILITY_OPERAND")
            self.assertEqual((leaf.components, leaf.name), (("captures", "ab"), "ab"))
            self.assertEqual(leaf.with_name("cd").components, ("captures", "cd"))
        self.assertEqual(self.space.log, [])

    def test_reads_use_held_capture_with_exact_caps_and_an_epoch_local_cache(self):
        raw = b"captured entity bytes"
        digest = sha(raw)
        self.space.put(("current.json",), b'{"pointer":1}')
        self.space.put(("captures", digest[:2], digest), raw)
        self.space.put(("captures", digest[:2], digest + ".json"), b"{}")
        self.space.put(("captures", digest[:2], "leftover.tmp-1"), b"partial")
        self.space.put(("outputs", "cache", digest), raw)
        with self.lease.namespace_operation():
            store = overlay.B1Store(self.lease)
            self.assertEqual(store.read(("current.json",)), b'{"pointer":1}')
            self.assertEqual((store / "current.json").read_text(), '{"pointer":1}')
            self.assertTrue((store / "current.json").is_file())
            self.assertEqual((store / "captures" / digest[:2] / digest).read_bytes(), raw)
            self.assertEqual(store.read(("captures", digest[:2], digest + ".json")), b"{}")
            self.assertEqual(store.read(("captures", digest[:2], "leftover.tmp-1")), b"partial")
            self.assertEqual(store.read(("outputs", "cache", digest)), raw)
            with self.assertRaises(FileNotFoundError) as raised:
                store.read(("absent.json",))
            self.assertEqual(str(raised.exception), "CAPABILITY_OBJECT_MISSING")
            self.assertFalse((store / "absent.json").exists())
        captures = [entry for entry in self.space.log if entry[0] == "capture_bytes"]
        self.assertEqual(captures, [
            ("capture_bytes", ("b1", "current.json"), MAX_GEN, None, False, False),
            ("capture_bytes", ("b1", "captures", digest[:2], digest), 16 * MiB, None, True, True),
            ("capture_bytes", ("b1", "captures", digest[:2], digest + ".json"), MAX_GEN, None, False, False),
            ("capture_bytes", ("b1", "captures", digest[:2], "leftover.tmp-1"), MAX_GEN, None, False, False),
            ("capture_bytes", ("b1", "outputs", "cache", digest), 16 * MiB, None, True, True),
            ("capture_bytes", ("b1", "absent.json"), MAX_GEN, None, False, False),
            ("capture_bytes", ("b1", "absent.json"), MAX_GEN, None, False, False)])
        with self.lease.namespace_operation():
            self.assertEqual(overlay.B1Store(self.lease).read(("current.json",)), b'{"pointer":1}')
        self.assertEqual(self.space.log[-1], ("capture_bytes", ("b1", "current.json"), MAX_GEN, None, False, False))

    def test_control_inputs_and_implementation_bytes_are_bound_to_release_digests(self):
        self.space.put(("receipts.json",), b'{"schema":"receipts"}')
        with self.lease.namespace_operation():
            store = overlay.B1Store(self.lease)
            for name in ("registry", "approval", "profiles", "config"):
                self.assertEqual(store.input(name), CONTROL[name + ".json"])
            for name in overlay.IMPLEMENTATION_FILES:
                self.assertEqual(store.implementation(name), CONTROL[name])
            self.assertEqual(store.input("receipts"), b'{"schema":"receipts"}')
            self.assertEqual(store.input("registry"), CONTROL["registry.json"])
            expected = hashlib.sha256("\n".join(f"{name}:{sha(CONTROL[name])}" for name in overlay.IMPLEMENTATION_FILES)
                                      .encode("utf-8")).hexdigest()
            self.assertEqual(overlay.implementation_sha256(store), expected)
            self.assertNotEqual(overlay.implementation_sha256(), expected)
            self.assertEqual(overlay.identity(b"p", b"r", b"a", store)["implementation_sha256"], expected)
            before = len(self.space.log)
            for call, reason in ((lambda: store.input("journal"), "CAPABILITY_INPUT_NAME"),
                                 (lambda: store.input("receipts.json"), "CAPABILITY_INPUT_NAME"),
                                 (lambda: store.implementation("revenue_guidance_host.py"), "CAPABILITY_IMPLEMENTATION_NAME")):
                with self.assertRaises(overlay.EffectiveInputsError) as raised:
                    call()
                self.assertEqual(str(raised.exception), reason)
            self.assertEqual(len(self.space.log), before)
        controls = [entry for entry in self.space.log if entry[0] == "capture_bytes" and entry[1][0] == "control"]
        names = ("registry.json", "approval.json", "profiles.json", "config.json") + overlay.IMPLEMENTATION_FILES
        self.assertEqual(controls, [("capture_bytes", ("control", name), MAX_GEN, bytes.fromhex(sha(CONTROL[name])), False, False)
                                    for name in names])
        unbound = self.fresh(digests={name: sha(raw) for name, raw in CONTROL.items() if name != "approval.json"})
        with unbound.lease.namespace_operation():
            with self.assertRaises(overlay.EffectiveInputsError) as raised:
                overlay.B1Store(unbound.lease).input("approval")
        self.assertEqual(str(raised.exception), "CAPABILITY_CONTROL_BINDING")
        self.assertEqual(unbound.log, [])
        # Control bytes that differ from the release-bound digest are never admitted.
        changed = self.fresh(control={**CONTROL, "registry.json": b'{"changed":true}'},
                             digests={name: sha(raw) for name, raw in CONTROL.items()})
        with changed.lease.namespace_operation():
            with self.assertRaises(windows.StorageValidationFault):
                overlay.B1Store(changed.lease).input("registry")

    def test_mutable_writes_bind_the_captured_state_and_return_the_original_native_result(self):
        self.space.put(("current.json",), b'{"old":1}')
        self.space.mkdir("outputs")
        with self.lease.namespace_operation():
            store = overlay.B1Store(self.lease)
            captured = store.capture_mutable(("current.json",))
            self.assertEqual((captured.data, captured.name), (b'{"old":1}', "current.json"))
            self.assertIs(captured.epoch, self.lease._live_operation)
            self.assertEqual(store.read(("current.json",)), b'{"old":1}')
            self.assertEqual([entry[0] for entry in self.space.log], ["capture_mutable"])
            result = store.write(("current.json",), b'{"new":2}')
            replace = self.space.last("replace_mutable")
            self.assertEqual(replace[1:3], (("current.json",), b'{"new":2}'))
            self.assertRegex(replace[3], r"\Astage-[0-9a-f]{24}\Z")
            self.assertIs(replace[4], captured)
            self.assertIs(result, self.space.results[-1])
            self.assertEqual(store.read(("current.json",)), b'{"new":2}')
            second = store.write(("current.json",), b'{"third":3}')
            replace = self.space.last("replace_mutable")
            self.assertIsNot(replace[4], captured)
            self.assertEqual((replace[4].data, replace[4].identity), (b'{"new":2}', result.identity))
            self.assertIs(second, self.space.results[-1])
            start = len(self.space.log)
            store.write(("outputs", "ledger.json"), b"{}")
            self.assertEqual([entry[0] for entry in self.space.log[start:]],
                             ["open_directory", "capture_mutable", "replace_mutable", "close_owned"])
            store.capture_mutable(("queue.json",))
            self.space.put(("queue.json",), b'{"foreign":true}')  # appears after the capture
            with self.assertRaises(storage.NamespaceConflictError):
                store.write(("queue.json",), b'{"last_served":"ZQA"}')
            store.capture_mutable(("current.json",))
            self.space.put(("current.json",), b'{"third":3}')  # same bytes, another object identity
            with self.assertRaises(storage.NamespaceConflictError):
                store.write(("current.json",), b'{"fourth":4}')
            before = len(self.space.log)
            for data in (bytearray(b"{}"), "{}", memoryview(b"{}"), None):
                with self.assertRaises(overlay.EffectiveInputsError) as raised:
                    store.write(("current.json",), data)
                self.assertEqual(str(raised.exception), "CAPABILITY_WRITE_BYTES")
            self.assertEqual(len(self.space.log), before)
        self.assertEqual(self.space.get(("queue.json",)), b'{"foreign":true}')
        self.assertEqual(self.space.get(("current.json",)), b'{"third":3}')

    def test_immutable_writes_publish_exact_names_with_an_independent_content_digest(self):
        raw = b"entity bytes"
        digest = sha(raw)
        name = "20260101T000000Z-0123456789ab.json"
        self.space.mkdir("captures", digest[:2])
        self.space.mkdir("generations")
        with self.lease.namespace_operation():
            store = overlay.B1Store(self.lease)
            before = self.lease.budget.new_capture_bytes
            result = store.write(("captures", digest[:2], digest), raw)
            self.assertIs(result, self.space.results[-1])
            self.assertFalse(result.reused)
            publish = self.space.last("publish_named_immutable")
            self.assertEqual(publish[1:3], (("captures", digest[:2], digest), raw))
            self.assertRegex(publish[3], r"\Astage-[0-9a-f]{24}\Z")
            self.assertEqual(publish[4:], (hashlib.sha256(raw).digest(), True))
            self.assertEqual(self.lease.budget.new_capture_bytes, before + len(raw))
            meta = b'{"meta":1}'
            store.write(("captures", digest[:2], digest + ".json"), meta)
            self.assertEqual(self.space.last("publish_named_immutable")[4:], (hashlib.sha256(meta).digest(), False))
            generation = b'{"generation":1}'
            store.write(("generations", name), generation)
            self.assertEqual(self.space.last("publish_named_immutable")[4:], (hashlib.sha256(generation).digest(), False))
            self.assertEqual(self.lease.budget.new_capture_bytes, before + len(raw))
            self.assertTrue(store.write(("generations", name), generation).reused)
            self.assertEqual(store.read(("generations", name)), generation)
        self.assertEqual([entry for entry in self.space.log if entry[0] in ("capture_mutable", "replace_mutable")], [])

    def test_an_existing_capture_reuses_its_original_metadata_and_is_never_repaired(self):
        raw = b"<html>original filing</html>"
        digest = put_capture(self.space, raw)
        self.space.put(("store_usage.json",), encode({"bytes": len(raw), "files": 1, "pending": {}}))
        before = self.space.snapshot()
        with self.lease.namespace_operation():
            store = overlay.B1Store(self.lease)
            later = {"url": "https://www.sec.gov/other.htm", "retrieved_at": "2026-10-10T00:00:00Z"}
            self.assertEqual(overlay.store_capture(store, raw, later), digest)
            self.assertEqual(overlay.load_capture(store, digest)["retrieved_at"], "2026-01-02T03:04:05Z")
        self.assertEqual(self.space.snapshot(), before)
        self.assertEqual(self.space.mutations(), [])
        for label, meta in (("missing", None), ("foreign-keys", b'{"url":"https://www.sec.gov/x"}'),
                            ("bad-time", capture_meta(raw, retrieved_at="2026-01-02 03:04:05"))):
            with self.subTest(meta=label):
                space = self.fresh()
                put_capture(space, raw, with_meta=False)
                if meta is not None:
                    space.put(("captures", digest[:2], digest + ".json"), meta)
                space.put(("store_usage.json",), encode({"bytes": len(raw), "files": 1, "pending": {}}))
                before = space.snapshot()
                with space.lease.namespace_operation():
                    with self.assertRaises(overlay.StateError) as raised:
                        overlay.store_capture(overlay.B1Store(space.lease), raw, later)
                self.assertTrue(str(raised.exception).startswith("CAPTURE_"))
                self.assertEqual(space.snapshot(), before)
                self.assertEqual(space.mutations(), [])

    def test_a_new_capture_reserves_before_writing_and_settles_last(self):
        raw = b"new entity bytes"
        digest = sha(raw)
        self.space.mkdir("captures")
        self.space.put(("store_usage.json",), encode({"bytes": 0, "files": 0, "pending": {}}))
        meta = {"url": "https://www.sec.gov/a.htm", "retrieved_at": "2026-10-10T01:02:03Z",
                "content_type": "text/html", "role": "filing"}
        with self.lease.namespace_operation():
            self.assertEqual(overlay.store_capture(overlay.B1Store(self.lease), raw, meta), digest)
        steps = self.space.mutations()
        self.assertEqual([(entry[0], entry[1]) for entry in steps], [
            ("replace_mutable", ("store_usage.json",)), ("create_directory", ("captures", digest[:2])),
            ("publish_named_immutable", ("captures", digest[:2], digest)),
            ("publish_named_immutable", ("captures", digest[:2], digest + ".json")),
            ("replace_mutable", ("store_usage.json",))])
        self.assertEqual(json.loads(steps[0][2]), {"bytes": len(raw), "files": 1,
                                                   "pending": {digest: {"bytes": len(raw), "pid": os.getpid()}}})
        self.assertEqual((steps[2][5], steps[3][5]), (True, False))
        self.assertEqual(self.space.json(("store_usage.json",)), {"bytes": len(raw), "files": 1, "pending": {}})
        self.assertEqual(self.space.json(("captures", digest[:2], digest + ".json"))["retrieved_at"], "2026-10-10T01:02:03Z")
        # An existing bucket is opened, never re-created or adopted by guess.
        other = b"second entity in the same bucket"
        while sha(other)[:2] != digest[:2]:
            other += b"."
        with self.lease.namespace_operation():
            overlay.store_capture(overlay.B1Store(self.lease), other, meta)
        self.assertEqual([entry[1] for entry in self.space.mutations() if entry[0] == "create_directory"],
                         [("captures", digest[:2])])
        for label, usage, reason in (("unknown-accounting", None, "STORE_ACCOUNTING_UNKNOWN"),
                                     ("pending-full", {"bytes": 16, "files": 16, "pending": {
                                         f"{i:064x}": {"bytes": 1, "pid": 1} for i in range(16)}}, "STORE_ACCOUNTING_PENDING")):
            with self.subTest(label=label):
                space = self.fresh()
                space.mkdir("captures")
                if usage is not None:
                    space.put(("store_usage.json",), encode(usage))
                with space.lease.namespace_operation():
                    with self.assertRaises(overlay.StateError) as raised:
                        overlay.store_capture(overlay.B1Store(space.lease), raw, meta)
                self.assertEqual(str(raised.exception), reason)
                self.assertEqual(space.mutations(), [])


# ------------------------------------------------------------------ G2-11 capability accounting

class CapabilityAccountingTests(FakeLeaseCase):
    def test_an_interrupted_capture_keeps_its_reservation_and_reconcile_never_settles_it(self):
        raw = b"interrupted entity"
        digest = sha(raw)
        self.space.mkdir("captures")
        self.space.put(("store_usage.json",), encode({"bytes": 0, "files": 0, "pending": {}}))
        self.space.faults.append(("publish_named_immutable", ("captures", digest[:2], digest + ".json"),
                                  windows.StorageUnavailableError("synthetic interruption")))
        with self.lease.namespace_operation():
            with self.assertRaises(windows.StorageUnavailableError):
                overlay.store_capture(overlay.B1Store(self.lease), raw,
                                      {"url": "https://www.sec.gov/a.htm", "retrieved_at": "2026-10-10T01:02:03Z"})
        pending = {digest: {"bytes": len(raw), "pid": os.getpid()}}
        self.assertEqual(self.space.json(("store_usage.json",)), {"bytes": len(raw), "files": 1, "pending": pending})
        self.assertTrue(self.space.exists(("captures", digest[:2], digest)))
        self.assertFalse(self.space.exists(("captures", digest[:2], digest + ".json")))
        before, start = self.space.snapshot(), len(self.space.log)
        lease = self.space.reopen()
        with lease.namespace_operation():
            self.assertIsNone(overlay.reconcile_usage(overlay.B1Store(lease)))
        self.assertEqual(self.space.snapshot(), before)  # no refund, delete or repair
        self.assertEqual(self.space.mutations(start), [])
        with lease.namespace_operation():
            self.assertEqual(overlay.recount_usage(overlay.B1Store(lease)),
                             {"status": "UNKNOWN", "bytes": len(raw), "files": 1, "pending": 1})
        self.assertEqual(self.space.json(("store_usage.json",)), {"bytes": len(raw), "files": 1, "pending": pending})
        self.assertFalse(self.space.exists(("captures", digest[:2], digest + ".json")))

    def test_reconcile_settles_only_complete_admitted_pairs_and_never_lowers_counts(self):
        complete = b"complete admitted capture"
        digest, absent = sha(complete), sha(b"never written")
        reserved = {digest: {"bytes": len(complete), "pid": 77}}
        with_pair = lambda space: put_capture(space, complete)  # noqa: E731
        rows = [
            ("missing-ledger", None, with_pair, None, None),
            ("malformed-ledger", b"[]", with_pair, None, None),
            ("coherent-without-pending", {"bytes": 40, "files": 2, "pending": {}}, with_pair, 40,
             {"bytes": 40, "files": 2, "pending": {}}),
            ("complete-pair-settles-at-the-old-high-water", {"bytes": 100, "files": 3, "pending": reserved}, with_pair, 100,
             {"bytes": 100, "files": 3, "pending": {}}),
            ("reserved-amount-differs", {"bytes": 100, "files": 3,
                                         "pending": {digest: {"bytes": len(complete) + 1, "pid": 77}}}, with_pair, None, None),
            ("metadata-missing", {"bytes": 100, "files": 3, "pending": reserved},
             lambda space: put_capture(space, complete, with_meta=False), None, None),
            ("absent-object-with-temporary", {"bytes": 100, "files": 3, "pending": {absent: {"bytes": 13, "pid": 77}}},
             lambda space: space.put(("captures", absent[:2], absent + ".tmp-77"), b"partial"), None, None),
            ("bytes-below-pending", {"bytes": 5, "files": 3, "pending": reserved}, with_pair, None, None),
            ("files-below-pending", {"bytes": 100, "files": 0, "pending": reserved}, with_pair, None, None),
            ("trailing-newline-digest", {"bytes": 100, "files": 3, "pending": {digest + "\n": reserved[digest]}},
             with_pair, None, None),
        ]
        for label, ledger, setup, expected, settled in rows:
            with self.subTest(label=label):
                space = self.fresh()
                space.mkdir("captures")
                setup(space)
                if ledger is not None:
                    space.put(("store_usage.json",), ledger if type(ledger) is bytes else encode(ledger))
                before = space.snapshot()
                with space.lease.namespace_operation():
                    self.assertEqual(overlay.reconcile_usage(overlay.B1Store(space.lease)), expected)
                after = space.snapshot()
                if settled is None:
                    self.assertEqual(after, before)
                    self.assertEqual(space.mutations(), [])
                    continue
                self.assertEqual(space.json(("store_usage.json",)), settled)
                self.assertEqual([(entry[0], entry[1]) for entry in space.mutations()],
                                 [("replace_mutable", ("store_usage.json",))])
                for path, value in before.items():
                    if path != ("store_usage.json",):
                        self.assertEqual(after[path], value)

    def test_recount_captures_the_original_ledger_first_and_keeps_unknown_and_high_water(self):
        one, two = b"first complete capture", b"second complete capture!"
        base = len(one) + len(two)
        reserved_digest = sha(b"the full reserved object")
        reserved = {reserved_digest: {"bytes": 50, "pid": 7}}

        def complete(space):
            put_capture(space, one)
            put_capture(space, two)

        def with_partial(space):
            complete(space)
            space.put(("captures", reserved_digest[:2], reserved_digest), b"x" * 20)

        def with_leftover(space):
            complete(space)
            space.put(("captures", sha(one)[:2], sha(one) + ".tmp-123"), b"leftover")

        rows = [
            ("clean", {"bytes": base, "files": 2, "pending": {}}, complete,
             {"status": "RECOUNTED", "bytes": base, "files": 2, "pending": 0}, {}),
            ("understated-ledger-raised-to-actual", {"bytes": 1, "files": 1, "pending": {}}, complete,
             {"status": "RECOUNTED", "bytes": base, "files": 2, "pending": 0}, {}),
            ("older-high-water-retained", {"bytes": base + 100, "files": 5, "pending": {}}, complete,
             {"status": "UNKNOWN", "bytes": base + 100, "files": 5, "pending": 0}, {}),
            ("unresolved-reservation-kept-exactly", {"bytes": base + 50, "files": 3, "pending": reserved}, complete,
             {"status": "UNKNOWN", "bytes": base + 50, "files": 3, "pending": 1}, reserved),
            ("partial-raw-counted-once", {"bytes": base + 50, "files": 3, "pending": reserved}, with_partial,
             {"status": "UNKNOWN", "bytes": base + 50, "files": 3, "pending": 1}, reserved),
            ("admitted-reservation-counted-once", {"bytes": base, "files": 2,
                                                   "pending": {sha(two): {"bytes": len(two), "pid": 9}}}, complete,
             {"status": "RECOUNTED", "bytes": base, "files": 2, "pending": 0}, {}),
            ("foreign-leftover-counted-not-admitted", {"bytes": base, "files": 2, "pending": {}}, with_leftover,
             {"status": "UNKNOWN", "bytes": base + 8, "files": 3, "pending": 0}, {}),
        ]
        for label, ledger, setup, expected, kept in rows:
            with self.subTest(label=label):
                space = self.fresh()
                setup(space)
                space.put(("store_usage.json",), encode(ledger))
                before = space.snapshot()
                with space.lease.namespace_operation():
                    self.assertEqual(overlay.recount_usage(overlay.B1Store(space.lease)), expected)
                first = space.log[0]
                self.assertEqual(first[:2], ("capture_mutable", ("store_usage.json",)))
                replaces = [entry for entry in space.log if entry[0] == "replace_mutable"]
                self.assertEqual(len(replaces), 1)
                self.assertIs(replaces[0][4], first[2])  # the ORIGINAL captured ledger binds the write
                self.assertEqual(space.json(("store_usage.json",)),
                                 {"bytes": expected["bytes"], "files": expected["files"], "pending": kept})
                self.assertEqual([entry[0] for entry in space.mutations()], ["replace_mutable"])
                after = space.snapshot()
                for path, value in before.items():
                    if path != ("store_usage.json",):
                        self.assertEqual(after[path], value)  # nothing deleted, refunded or repaired
        missing = self.fresh()
        complete(missing)
        with missing.lease.namespace_operation():
            self.assertEqual(overlay.recount_usage(overlay.B1Store(missing.lease)),
                             {"status": "UNKNOWN", "bytes": None, "files": None, "pending": None})
        self.assertEqual(missing.mutations(), [])
        moved = self.fresh()
        complete(moved)
        moved.put(("store_usage.json",), encode({"bytes": base, "files": 2, "pending": {}}))
        foreign = encode({"bytes": 999, "files": 9, "pending": {}})
        moved.on_enumerate = lambda path: moved.put(("store_usage.json",), foreign)
        with moved.lease.namespace_operation():
            with self.assertRaises(storage.NamespaceConflictError):
                overlay.recount_usage(overlay.B1Store(moved.lease))
        self.assertEqual(moved.get(("store_usage.json",)), foreign)


# ------------------------------------------------------------------ G2-26 B1Outputs layout and accounting

class B1OutputsAccountingTests(FakeLeaseCase):
    def admitted(self, space):
        with space.lease.namespace_operation():
            owner = overlay.B1Outputs(overlay.B1Store(space.lease))
            self.assertEqual(owner._initialization, "READY")
        return owner

    def refused(self, space, reason="OUTPUT_ACCOUNTING_UNKNOWN"):
        with space.lease.namespace_operation():
            with self.assertRaises(overlay.StateError) as raised:
                overlay.B1Outputs(overlay.B1Store(space.lease))
        self.assertEqual(str(raised.exception), reason)
        self.assertEqual(space.mutations(), [])

    def batch_refused(self, observations, plan, cursor, reason, space=None):
        space = space if space is not None else self.fresh()
        with space.lease.namespace_operation():
            owner = overlay.B1Outputs(overlay.B1Store(space.lease))
            start = len(space.log)
            with self.assertRaises(overlay.StateError) as raised:
                owner.capture_batch(observations, plan, cursor)
        self.assertEqual(str(raised.exception), reason)
        self.assertEqual(space.mutations(start), [])

    def test_a_positively_new_layout_initializes_exact_accounting_then_reinventories(self):
        with self.lease.namespace_operation():
            store = overlay.B1Store(self.lease)
            owner = overlay.B1Outputs(store)
            self.assertIs(owner.store, store)
            self.assertEqual(owner._initialization, "READY")
            self.assertIsNone(owner.load_cision())
        steps = self.space.mutations()
        self.assertEqual([(entry[0], entry[1]) for entry in steps], [
            ("create_directory", ("outputs",)), ("replace_mutable", ("outputs", "ledger.json")),
            ("create_directory", ("outputs", "cache")), ("replace_mutable", ("outputs", "capture-index.json"))])
        self.assertEqual(self.space.get(("outputs", "ledger.json")),
                         json.dumps(ledger_doc(0), sort_keys=True, allow_nan=False).encode("utf-8"))
        self.assertEqual(self.space.get(("outputs", "capture-index.json")),
                         b'{"schema":"guidance-public-capture-index-v2","entries":{},"progress":{}}')
        last = max(position for position, entry in enumerate(self.space.log) if entry[0] in MUTATIONS)
        self.assertEqual([entry[1] for entry in self.space.log[last + 1:] if entry[0] == "capture_mutable"],
                         [("outputs", "ledger.json"), ("outputs", "capture-index.json"), ("outputs", "cision.json")])
        self.assertIn(("enumerate_directory", ("outputs",)), self.space.log[last + 1:])
        existing = self.fresh()
        existing.mkdir("outputs")  # present but not positively new: no fabricated accounting
        self.refused(existing)

    def test_accounting_shape_and_layout_refusals_never_mutate(self):
        rank, body, record = bundle("one")
        total = len(rank) + len(body) + len(record)
        good = ledger_doc(total, [sha(record)])
        deep = None
        for _ in range(40):
            deep = [deep]
        ledgers = {
            "schema": dict(good, schema="guidance-output-accounting-v0"),
            "pending": dict(good, pending={"bytes": 1}),
            "over-64-MiB": dict(good, bytes=64 * MiB + 1),
            "negative": dict(good, bytes=-1),
            "boolean": dict(good, bytes=True),
            "float": dict(good, bytes=float(total)),
            "extra-key": dict(good, extra=1),
            "missing-key": {key: value for key, value in good.items() if key != "captures"},
            "65-entries": dict(good, entries=[f"{i:064x}" for i in range(65)]),
            "duplicate-entry": dict(good, entries=[sha(record)] * 2),
            "uppercase-entry": dict(good, entries=[sha(record).upper()]),
            "257-captures": dict(good, captures=[f"{i:064x}" for i in range(257)]),
            "duplicate-capture": dict(good, captures=["0" * 64] * 2),
            "understated-zero": dict(good, bytes=0),
            "one-byte-short": dict(good, bytes=total - 1),
            "unlisted-record": dict(good, entries=[]),
        }
        for label, ledger in ledgers.items():
            with self.subTest(ledger=label):
                space = self.fresh()
                seed_outputs(space, bundles=[(rank, body, record)], ledger=ledger)
                self.refused(space)
        raws = {
            "duplicate-key": (b'{"schema":"guidance-output-accounting-v1","schema":"guidance-output-accounting-v1",'
                              b'"bytes":0,"entries":[],"captures":[],"pending":null}', "OUTPUT_JSON_UNKNOWN"),
            "non-finite": (b'{"schema":"guidance-output-accounting-v1","bytes":NaN,"entries":[],"captures":[],'
                           b'"pending":null}', "OUTPUT_JSON_UNKNOWN"),
            "too-deep": (encode(dict(ledger_doc(0), pending=deep)), "OUTPUT_JSON_UNKNOWN"),
            "not-utf8": (b"\xff\xfe", "OUTPUT_ACCOUNTING_UNKNOWN"),
        }
        for label, (raw, reason) in raws.items():
            with self.subTest(raw=label):
                space = self.fresh()
                seed_outputs(space, ledger=raw)
                self.refused(space, reason)
        layouts = {
            "foreign-name": lambda space: space.put(("outputs", "notes.txt"), b"x"),
            "foreign-directory": lambda space: space.mkdir("outputs", "extra"),
            "orphan-artifact": lambda space: space.put(("outputs", f"rank-{sha(b'orphan')}.json"), b"orphan"),
            "missing-body": lambda space: space.remove(("outputs", f"body-{sha(body)}.json")),
            "missing-record": lambda space: space.remove(("outputs", f"record-{sha(record)}.json")),
        }
        for label, mutate in layouts.items():
            with self.subTest(layout=label):
                space = self.fresh()
                seed_outputs(space, bundles=[(rank, body, record)])
                mutate(space)
                self.refused(space)
        records = {
            "schema": encode({"schema": "guidance-local-completion-v0", "ranking_sha256": sha(rank), "output_sha256": sha(body)}),
            "not-json": b"not json",
            "short-digest": encode({"schema": COMPLETION, "ranking_sha256": "ab", "output_sha256": sha(body)}),
        }
        for label, bad in records.items():
            with self.subTest(record=label):
                space = self.fresh()
                seed_outputs(space, bundles=[(rank, body, bad)])
                self.refused(space)
        for claimed in (total, 64 * MiB):
            with self.subTest(claimed=claimed):
                space = self.fresh()
                seed_outputs(space, bundles=[(rank, body, record)], claimed=claimed)
                self.admitted(space)
                self.assertEqual(space.mutations(), [])

    def test_shared_names_count_once_and_every_unique_name_is_held_and_digest_bound(self):
        rank, body = encode({"rank": "shared"}), encode({"body": "shared"})
        records = [completion(rank, body, str(n)) for n in (1, 2)]
        unique = len(rank) + len(body) + sum(len(record) for record in records)
        refused = self.fresh()
        seed_outputs(refused, bundles=[(rank, body, record) for record in records], claimed=unique - 1)
        self.refused(refused)
        space = self.fresh()
        seed_outputs(space, bundles=[(rank, body, record) for record in records], claimed=unique)
        self.admitted(space)
        expected = {("b1", "outputs", f"{kind}-{sha(raw)}.json"): sha(raw)
                    for kind, raw in [("rank", rank), ("body", body)] + [("record", record) for record in records]}
        reads = [entry for entry in space.log if entry[0] == "capture_bytes"]
        self.assertEqual(sorted(entry[1] for entry in reads), sorted(expected))
        for entry in reads:
            self.assertEqual(entry[2:], (MAX_GEN, bytes.fromhex(expected[entry[1]]), False, False))

    def test_every_retained_pack_counts_and_index_slices_are_digest_bound(self):
        live, old = b"live response", b"old inactive pack"
        pack = live + b"\x00"
        urls = ["https://a.example/live", "https://a.example/empty", "https://a.example/failed"]
        keys = [sha(url.encode()) for url in urls]
        entries = {keys[0]: index_row(urls[0], live, sha(pack), 0),
                   keys[1]: index_row(urls[1], b"", sha(pack), len(live)),
                   keys[2]: index_row(urls[2], status="HTTP_UNAVAILABLE", http_status=503)}
        total = seed_outputs(self.space, packs=[pack, old], entries=entries)
        moment = datetime(2026, 10, 10, 3, 0, 0, tzinfo=timezone.utc)
        with self.lease.namespace_operation():
            owner = overlay.B1Outputs(overlay.B1Store(self.lease))
            self.assertEqual(owner.captured_public(keys[0], urls[0], moment, 3), (live, entries[keys[0]]))
            self.assertEqual(owner.captured_public(keys[1], urls[1], moment, 3), (b"", entries[keys[1]]))
            self.assertEqual(owner.captured_public(keys[2], urls[2], moment, 3), (None, entries[keys[2]]))
            self.assertIsNone(owner.captured_public(keys[0], urls[1], moment, 3))
            self.assertIsNone(owner.captured_public(sha(b"absent"), urls[0], moment, 3))
            self.assertIsNone(owner.captured_public(keys[0], urls[0], moment + timedelta(seconds=1), 3))
            self.assertIsNone(owner.captured_public(keys[0], urls[0], datetime(2026, 10, 9, 23, 59, 59, tzinfo=timezone.utc), 3))
            self.assertEqual(owner.captured_public(keys[0], urls[0], moment + timedelta(hours=17), 20)[0], live)
            reads = len([entry for entry in self.space.log if entry[0] == "capture_bytes"])
            owner.captured_public(keys[0], urls[0], moment, 3)
            self.assertEqual(len([entry for entry in self.space.log if entry[0] == "capture_bytes"]), reads)
        packs = [entry for entry in self.space.log if entry[0] == "capture_bytes" and entry[1][:3] == ("b1", "outputs", "cache")]
        self.assertEqual(sorted(entry[1][3] for entry in packs), sorted([sha(pack), sha(old)]))
        for entry in packs:
            self.assertEqual(entry[2:], (16 * MiB, bytes.fromhex(entry[1][3]), True, True))
        self.assertEqual(self.space.mutations(), [])
        for claimed in (total - len(old), total - 1):  # the unreferenced old pack still counts
            with self.subTest(claimed=claimed):
                space = self.fresh()
                seed_outputs(space, packs=[pack, old], entries=entries, claimed=claimed)
                self.refused(space, "OUTPUT_CAPTURE_UNKNOWN")

    def test_capture_index_rows_and_cache_layout_refuse_without_migration(self):
        data = b"payload"
        pack = data + b"\x00"
        url = "https://a.example/x"
        key = sha(url.encode())
        good = index_row(url, data, sha(pack), 0)
        one = lambda **change: index_doc({key: dict(good, **change)})  # noqa: E731
        cases = {
            "v1-schema": {"schema": "guidance-public-capture-index-v1", "entries": {}, "progress": {}},
            "extra-key": dict(index_doc(), extra=1),
            "1025-slots": index_doc({f"{i:064x}": index_row(f"https://a.example/{i}", status="TRANSPORT_UNAVAILABLE",
                                                            http_status=None) for i in range(1025)}),
            "uppercase-key": index_doc({key.upper(): good}),
            "captured-404": one(http_status=404),
            "unavailable-200": one(status="HTTP_UNAVAILABLE", http_status=200, sha256=None, pack=None, bytes=0),
            "transport-with-status": one(status="TRANSPORT_UNAVAILABLE", http_status=500, sha256=None, pack=None, bytes=0),
            "absence-with-pack": one(status="TRANSPORT_UNAVAILABLE", http_status=None, sha256=None, bytes=0),
            "unknown-pack": one(pack=sha(b"other")),
            "slice-digest": one(sha256=sha(b"other")),
            "slice-past-pack": one(offset=len(data) - 1),
            "empty-slice-past-pack": one(offset=len(pack) + 1, bytes=0, sha256=sha(b"")),
            "beyond-16-MiB": one(offset=16 * MiB, bytes=1),
            "calendar-time": one(retrieved_at="2026-13-01T00:00:00Z"),
            "naive-time": one(retrieved_at="2026-10-10T00:00:00"),
            "status-99": one(http_status=99),
            "long-url": one(url="https://a.example/" + "x" * 4096),
            "nine-plans": index_doc({key: good}, {f"{i:064x}": 0 for i in range(9)}),
            "cursor-1024": index_doc({key: good}, {sha(b"plan"): 1024}),
            "cursor-boolean": index_doc({key: good}, {sha(b"plan"): True}),
            "plan-not-digest": index_doc({key: good}, {"plan": 0}),
        }
        for label, index in cases.items():
            with self.subTest(index=label):
                space = self.fresh()
                seed_outputs(space, packs=[pack], index=index)
                self.refused(space, "OUTPUT_CAPTURE_UNKNOWN")
        layouts = {"unlisted-pack-file": lambda space: space.put(("outputs", "cache", sha(b"stray")), b"stray"),
                   "missing-pack-file": lambda space: space.remove(("outputs", "cache", sha(pack)))}
        for label, mutate in layouts.items():
            with self.subTest(layout=label):
                space = self.fresh()
                seed_outputs(space, packs=[pack], entries={key: good})
                mutate(space)
                self.refused(space, "OUTPUT_CAPTURE_UNKNOWN")
        seed_outputs(self.space, packs=[pack], entries={key: dict(good)}, progress={sha(b"plan"): 1023})
        tail = index_row("https://a.example/tail", b"", sha(pack), len(pack))
        with self.lease.namespace_operation():
            owner = overlay.B1Outputs(overlay.B1Store(self.lease))
            self.assertEqual(owner.progress(sha(b"plan"), 1024), 1023)
            self.assertEqual(owner.progress(sha(b"other plan"), 7), 0)
            for plan, count in ((sha(b"plan"), 0), (sha(b"plan"), 1025), ("plan", 3)):
                with self.assertRaises(overlay.StateError) as raised:
                    owner.progress(plan, count)
                self.assertEqual(str(raised.exception), "OUTPUT_PLAN_BOUND")
        edge = self.fresh()
        seed_outputs(edge, packs=[pack], entries={sha(b"tail"): tail})  # zero-length slice exactly at the pack end
        self.admitted(edge)

    def test_capture_batch_reserves_first_publishes_packs_then_the_index_and_settles_last(self):
        moment = datetime(2026, 10, 10, 1, 2, 3, tzinfo=timezone.utc)
        urls = [f"https://a.example/{i}" for i in range(4)]
        keys = [sha(f"slot{i}".encode()) for i in range(4)]
        observations = [(keys[0], urls[0], b"abc", moment, "CAPTURED", 200),
                        (keys[1], urls[1], b"", moment, "CAPTURED", 200),
                        (keys[2], urls[2], None, moment, "HTTP_UNAVAILABLE", 503),
                        (keys[3], urls[3], None, moment, "TRANSPORT_UNAVAILABLE", None)]
        plan, pack = sha(b"plan"), b"abc\x00"
        with self.lease.namespace_operation():
            owner = overlay.B1Outputs(overlay.B1Store(self.lease))
            start = len(self.space.log)
            owner.capture_batch(observations, plan, 5)
            self.assertEqual(owner.progress(plan, 10), 5)
            self.assertEqual(owner.captured_public(keys[0], urls[0], moment, 3)[0], b"abc")
            self.assertEqual(owner.captured_public(keys[1], urls[1], moment, 3)[0], b"")
            self.assertEqual(owner.captured_public(keys[2], urls[2], moment, 3)[0], None)
            warm = len(self.space.log)
            owner.capture_batch([], plan, 5)  # warm traversal: no duplicate reservation or mutation
            owner.capture_batch([], None, None)
            self.assertEqual(self.space.mutations(warm), [])
        steps = self.space.mutations(start)
        self.assertEqual([(entry[0], entry[1]) for entry in steps], [
            ("replace_mutable", ("outputs", "ledger.json")), ("publish_named_immutable", ("outputs", "cache", sha(pack))),
            ("replace_mutable", ("outputs", "capture-index.json")), ("replace_mutable", ("outputs", "ledger.json"))])
        self.assertEqual(json.loads(steps[0][2]), ledger_doc(4, pending={"kind": "capture_batch", "bytes": 4,
                                                                          "packs": [sha(pack)]}))
        self.assertEqual(steps[1][4:], (hashlib.sha256(pack).digest(), True))
        self.assertEqual(json.loads(steps[3][2]), ledger_doc(4, captures=[sha(pack)]))
        readback = [position for position, entry in enumerate(self.space.log)
                    if entry[0] == "capture_bytes" and entry[1] == ("b1", "outputs", "cache", sha(pack))]
        published = self.space.log.index(steps[1])
        indexed = self.space.log.index(steps[2])
        self.assertTrue(any(published < position < indexed for position in readback))
        index = self.space.json(("outputs", "capture-index.json"))
        self.assertEqual(index["progress"], {plan: 5})
        self.assertEqual(index["entries"][keys[0]], index_row(urls[0], b"abc", sha(pack), 0, "2026-10-10T01:02:03Z"))
        self.assertEqual(index["entries"][keys[1]], index_row(urls[1], b"", sha(pack), 3, "2026-10-10T01:02:03Z"))
        self.assertEqual(index["entries"][keys[2]], index_row(urls[2], retrieved_at="2026-10-10T01:02:03Z",
                                                              status="HTTP_UNAVAILABLE", http_status=503))
        self.assertEqual(index["entries"][keys[3]], index_row(urls[3], retrieved_at="2026-10-10T01:02:03Z",
                                                              status="TRANSPORT_UNAVAILABLE", http_status=None))
        lease = self.space.reopen()
        with lease.namespace_operation():
            again = overlay.B1Outputs(overlay.B1Store(lease))  # M == H == 4 on the next invocation
            self.assertEqual(again.captured_public(keys[0], urls[0], moment, 3)[0], b"abc")
            self.assertEqual(again.progress(plan, 10), 5)

    def test_capture_batch_bounds_refuse_before_any_reservation(self):
        moment = datetime(2026, 10, 10, 1, 0, 0, tzinfo=timezone.utc)
        key = sha(b"slot")

        def observation(**change):
            value = dict(key=key, url="https://a.example/x", raw=b"x", moment=moment, status="CAPTURED", http_status=200)
            value.update(change)
            return (value["key"], value["url"], value["raw"], value["moment"], value["status"], value["http_status"])

        bound = {
            "121-slots": [observation(key=f"{i:064x}", raw=None, status="TRANSPORT_UNAVAILABLE", http_status=None)
                          for i in range(121)],
            "duplicate-key": [observation(), observation()],
            "captured-201": [observation(http_status=201)],
            "captured-without-body": [observation(raw=None)],
            "unavailable-200": [observation(raw=None, status="HTTP_UNAVAILABLE")],
            "transport-with-status": [observation(raw=None, status="TRANSPORT_UNAVAILABLE", http_status=500)],
            "status-600": [observation(raw=None, status="HTTP_UNAVAILABLE", http_status=600)],
            "unknown-status": [observation(status="CACHED")],
            "naive-moment": [observation(moment=moment.replace(tzinfo=None))],
            "offset-moment": [observation(moment=moment.astimezone(timezone(timedelta(hours=8))))],
            "bytearray-body": [observation(raw=bytearray(b"x"))],
            "uppercase-key": [observation(key=key.upper())],
            "long-url": [observation(url="https://a.example/" + "x" * 4096)],
        }
        for label, observations in bound.items():
            with self.subTest(bound=label):
                self.batch_refused(observations, None, None, "OUTPUT_CAPTURE_BOUND")
        self.batch_refused(tuple([observation()]), None, None, "OUTPUT_CAPTURE_BOUND")
        for plan, cursor in (("plan", 0), (sha(b"plan"), 1024), (sha(b"plan"), -1), (sha(b"plan"), True), (None, 0),
                             (sha(b"plan").upper(), 0)):
            with self.subTest(plan=str(plan)[:8], cursor=cursor):
                self.batch_refused([observation()], plan, cursor, "OUTPUT_PLAN_BOUND")
        high = self.fresh()
        seed_outputs(high, claimed=64 * MiB - 3)
        self.batch_refused([observation(raw=b"abcd")], None, None, "OUTPUT_CAPACITY_UNAVAILABLE", high)
        packed = self.fresh()
        seed_outputs(packed, packs=[b"pack-%03d" % i for i in range(256)])
        self.batch_refused([observation(raw=b"new")], None, None, "OUTPUT_CAPACITY_UNAVAILABLE", packed)
        slots = self.fresh()
        seed_outputs(slots, entries={f"{i:064x}": index_row(f"https://a.example/{i}", status="TRANSPORT_UNAVAILABLE",
                                                            http_status=None) for i in range(1024)})
        self.batch_refused([observation()], None, None, "OUTPUT_CAPACITY_UNAVAILABLE", slots)
        edge = self.fresh()
        seed_outputs(edge, claimed=64 * MiB - 4)
        with edge.lease.namespace_operation():
            overlay.B1Outputs(overlay.B1Store(edge.lease)).capture_batch([observation(raw=b"abcd")], None, None)
        self.assertEqual(edge.json(("outputs", "ledger.json"))["bytes"], 64 * MiB)

    def test_packs_split_before_16_MiB_and_each_slice_stays_inside_its_pack(self):
        first, second = b"a" * (9 * MiB), b"b" * (8 * MiB)
        keys = [sha(b"first"), sha(b"second")]
        moment = datetime(2026, 10, 10, 1, 0, 0, tzinfo=timezone.utc)
        with self.lease.namespace_operation():
            owner = overlay.B1Outputs(overlay.B1Store(self.lease))
            owner.capture_batch([(keys[0], "https://a.example/1", first, moment, "CAPTURED", 200),
                                 (keys[1], "https://a.example/2", second, moment, "CAPTURED", 200)], None, None)
            self.assertEqual(owner.captured_public(keys[1], "https://a.example/2", moment, 3)[0], second)
        ledger = self.space.json(("outputs", "ledger.json"))
        self.assertEqual((ledger["captures"], ledger["bytes"]), ([sha(first), sha(second)], len(first) + len(second)))
        index = self.space.json(("outputs", "capture-index.json"))
        self.assertEqual({key: (index["entries"][key]["pack"], index["entries"][key]["offset"]) for key in keys},
                         {keys[0]: (sha(first), 0), keys[1]: (sha(second), 0)})

    def test_a_fault_after_the_reservation_is_never_refunded_and_blocks_every_later_use(self):
        moment = datetime(2026, 10, 10, 1, 0, 0, tzinfo=timezone.utc)
        url, raw, plan = "https://a.example/x", b"abc", sha(b"plan")
        key = sha(url.encode())
        self.space.faults.append(("publish_named_immutable", ("outputs", "cache", sha(raw)),
                                  windows.StorageUnavailableError("synthetic interruption")))
        with self.lease.namespace_operation():
            owner = overlay.B1Outputs(overlay.B1Store(self.lease))
            with self.assertRaises(windows.StorageUnavailableError):
                owner.capture_batch([(key, url, raw, moment, "CAPTURED", 200)], plan, 1)
            calls = (lambda: owner.progress(plan, 3), lambda: owner.captured_public(key, url, moment, 3),
                     lambda: owner.capture_batch([], None, None), lambda: owner.publish(b"r", b"b", b"c"),
                     lambda: overlay.B1Outputs(overlay.B1Store(self.lease)))
            for call in calls:
                with self.assertRaises(overlay.StateError) as raised:
                    call()
                self.assertEqual(str(raised.exception), "OUTPUT_ACCOUNTING_UNKNOWN")
        reserved = ledger_doc(3, pending={"kind": "capture_batch", "bytes": 3, "packs": [sha(raw)]})
        self.assertEqual(self.space.json(("outputs", "ledger.json")), reserved)
        self.assertEqual(self.space.json(("outputs", "capture-index.json")), index_doc())
        lease = self.space.reopen()
        with lease.namespace_operation():
            with self.assertRaises(overlay.StateError) as raised:
                overlay.B1Outputs(overlay.B1Store(lease))
        self.assertEqual(str(raised.exception), "OUTPUT_ACCOUNTING_UNKNOWN")
        self.assertEqual(self.space.json(("outputs", "ledger.json")), reserved)

    def test_a_lying_pack_readback_or_a_foreign_index_change_keeps_the_reservation(self):
        moment = datetime(2026, 10, 10, 1, 0, 0, tzinfo=timezone.utc)
        url, raw = "https://a.example/x", b"abc"
        key = sha(url.encode())
        lying = self.fresh()
        lying.tamper[("b1", "outputs", "cache", sha(raw))] = b"xyz"
        with lying.lease.namespace_operation():
            owner = overlay.B1Outputs(overlay.B1Store(lying.lease))
            with self.assertRaises(overlay.StateError) as raised:
                owner.capture_batch([(key, url, raw, moment, "CAPTURED", 200)], None, None)
            self.assertEqual(str(raised.exception), "OUTPUT_CAPTURE_READBACK")
            with self.assertRaises(overlay.StateError) as raised:
                owner.captured_public(key, url, moment, 3)
            self.assertEqual(str(raised.exception), "OUTPUT_ACCOUNTING_UNKNOWN")
        self.assertEqual(lying.json(("outputs", "ledger.json"))["pending"]["packs"], [sha(raw)])
        self.assertEqual(lying.json(("outputs", "capture-index.json")), index_doc())
        with self.lease.namespace_operation():
            owner = overlay.B1Outputs(overlay.B1Store(self.lease))
            index_raw = self.space.get(("outputs", "capture-index.json"))
            self.space.put(("outputs", "capture-index.json"), index_raw)  # same bytes, another object identity
            with self.assertRaises(overlay.StateError) as raised:
                owner.capture_batch([(key, url, raw, moment, "CAPTURED", 200)], sha(b"plan"), 1)
            self.assertEqual(str(raised.exception), "OUTPUT_CAPTURE_CHANGED")
        self.assertEqual(self.space.get(("outputs", "capture-index.json")), index_raw)
        ledger = self.space.json(("outputs", "ledger.json"))
        self.assertEqual((ledger["bytes"], ledger["pending"]["kind"]), (len(raw), "capture_batch"))
        self.assertTrue(self.space.exists(("outputs", "cache", sha(raw))))  # retained, never deleted
        lease = self.space.reopen()
        with lease.namespace_operation():
            with self.assertRaises(overlay.StateError) as raised:
                overlay.B1Outputs(overlay.B1Store(lease))
        self.assertEqual(str(raised.exception), "OUTPUT_ACCOUNTING_UNKNOWN")

    def test_publish_reserves_first_publishes_the_record_last_and_reads_each_back(self):
        rank, body, record = bundle("publish")
        size = len(rank) + len(body) + len(record)
        with self.lease.namespace_operation():
            owner = overlay.B1Outputs(overlay.B1Store(self.lease))
            start = len(self.space.log)
            digests = owner.publish(rank, body, record)
        self.assertEqual(digests, {"rank": sha(rank), "body": sha(body), "record": sha(record)})
        names = {kind: f"{kind}-{sha(raw)}.json" for kind, raw in (("rank", rank), ("body", body), ("record", record))}
        steps = [entry for entry in self.space.log[start:] if entry[0] in MUTATIONS + ("capture_bytes",)]
        self.assertEqual([(entry[0], entry[1]) for entry in steps], [
            ("replace_mutable", ("outputs", "ledger.json")),
            ("publish_named_immutable", ("outputs", names["rank"])), ("capture_bytes", ("b1", "outputs", names["rank"])),
            ("publish_named_immutable", ("outputs", names["body"])), ("capture_bytes", ("b1", "outputs", names["body"])),
            ("publish_named_immutable", ("outputs", names["record"])), ("capture_bytes", ("b1", "outputs", names["record"])),
            ("replace_mutable", ("outputs", "ledger.json"))])
        for entry, raw in zip(steps[2:7:2], (rank, body, record)):
            self.assertEqual(entry[2:4], (MAX_GEN, hashlib.sha256(raw).digest()))
        self.assertEqual(json.loads(steps[0][2]), ledger_doc(size, pending={"bytes": size, "digests": digests}))
        self.assertEqual(json.loads(steps[-1][2]), ledger_doc(size, [sha(record)]))
        with self.lease.namespace_operation():
            self.assertEqual(overlay.B1Outputs(overlay.B1Store(self.lease)).read("record", sha(record)), record)

    def test_publish_bounds_refuse_before_any_reservation(self):
        rank, body, record = bundle("bound")
        size = len(rank) + len(body) + len(record)
        shared_rank, shared_body = encode({"rank": "shared"}), encode({"body": "shared"})
        rows = [
            ("empty-body", lambda space: None, (rank, b"", record), "OUTPUT_BYTES"),
            ("bytearray-rank", lambda space: None, (bytearray(rank), body, record), "OUTPUT_BYTES"),
            ("text-record", lambda space: None, (rank, body, record.decode("utf-8")), "OUTPUT_BYTES"),
            ("high-water", lambda space: seed_outputs(space, claimed=64 * MiB - size + 1), (rank, body, record),
             "OUTPUT_CAPACITY_UNAVAILABLE"),
            ("64-bundles", lambda space: seed_outputs(space, bundles=[
                (shared_rank, shared_body, completion(shared_rank, shared_body, str(i))) for i in range(64)]),
             (rank, body, record), "OUTPUT_CAPACITY_UNAVAILABLE"),
        ]
        for label, setup, items, reason in rows:
            with self.subTest(label=label):
                space = self.fresh()
                setup(space)
                with space.lease.namespace_operation():
                    owner = overlay.B1Outputs(overlay.B1Store(space.lease))
                    start = len(space.log)
                    with self.assertRaises(overlay.StateError) as raised:
                        owner.publish(*items)
                self.assertEqual(str(raised.exception), reason)
                self.assertEqual(space.mutations(start), [])
        edge = self.fresh()
        seed_outputs(edge, claimed=64 * MiB - size)
        with edge.lease.namespace_operation():
            overlay.B1Outputs(overlay.B1Store(edge.lease)).publish(rank, body, record)
        self.assertEqual(edge.json(("outputs", "ledger.json"))["bytes"], 64 * MiB)

    def test_a_lying_artifact_readback_is_refused_and_the_reservation_never_refunded(self):
        rank, body, record = bundle("lie")
        size = len(rank) + len(body) + len(record)
        self.space.tamper[("b1", "outputs", f"body-{sha(body)}.json")] = b'{"body":"other"}'
        with self.lease.namespace_operation():
            owner = overlay.B1Outputs(overlay.B1Store(self.lease))
            with self.assertRaises(overlay.StateError) as raised:
                owner.publish(rank, body, record)
            self.assertEqual(str(raised.exception), "OUTPUT_READBACK")
            with self.assertRaises(overlay.StateError) as raised:
                owner.publish(rank, body, record)
            self.assertEqual(str(raised.exception), "OUTPUT_ACCOUNTING_UNKNOWN")
        ledger = self.space.json(("outputs", "ledger.json"))
        self.assertEqual((ledger["bytes"], ledger["entries"], ledger["pending"]),
                         (size, [], {"bytes": size, "digests": {"rank": sha(rank), "body": sha(body), "record": sha(record)}}))
        self.assertFalse(self.space.exists(("outputs", f"record-{sha(record)}.json")))  # record stays LAST
        lease = self.space.reopen()
        with lease.namespace_operation():
            with self.assertRaises(overlay.StateError) as raised:
                overlay.B1Outputs(overlay.B1Store(lease))
        self.assertEqual(str(raised.exception), "OUTPUT_ACCOUNTING_UNKNOWN")

    def test_republishing_identical_bytes_reuses_names_and_only_raises_the_high_water(self):
        rank, body, record = bundle("again")
        size = len(rank) + len(body) + len(record)
        with self.lease.namespace_operation():
            owner = overlay.B1Outputs(overlay.B1Store(self.lease))
            first = owner.publish(rank, body, record)
            published = len(self.space.results)
            self.assertEqual(owner.publish(rank, body, record), first)
            self.assertEqual([result.reused for result in self.space.results[published:]], [False, True, True, True, False])
        ledger = self.space.json(("outputs", "ledger.json"))
        self.assertEqual((ledger["bytes"], ledger["entries"], ledger["pending"]), (2 * size, [sha(record)], None))
        lease = self.space.reopen()
        with lease.namespace_operation():
            overlay.B1Outputs(overlay.B1Store(lease))  # M = size <= H = 2 * size: admitted, never lowered
        self.assertEqual(self.space.json(("outputs", "ledger.json"))["bytes"], 2 * size)

    def test_cision_control_bytes_are_bounded_compared_and_faults_are_not_optional_absence(self):
        self.assertFalse(issubclass(overlay.B1OutputControlFault, Exception))
        with self.lease.namespace_operation():
            owner = overlay.B1Outputs(overlay.B1Store(self.lease))
            self.assertIsNone(owner.load_cision())
            owner.save_cision(b'{"NOTE":{}}')
            self.assertEqual(owner.load_cision(), b'{"NOTE":{}}')
            for raw in (b" " * (MiB + 1), "{}", bytearray(b"{}")):
                with self.assertRaises(overlay.B1OutputControlFault) as raised:
                    owner.save_cision(raw)
                self.assertEqual(str(raised.exception), "OUTPUT_CISION_UNAVAILABLE")
            self.space.put(("outputs", "cision.json"), b'{"NOTE":{}}')  # foreign same-byte replacement
            with self.assertRaises(overlay.B1OutputControlFault):
                owner.save_cision(b'{"NOTE":{"x":1}}')
        self.assertEqual(self.space.get(("outputs", "cision.json")), b'{"NOTE":{}}')
        with self.lease.namespace_operation():
            self.assertEqual(overlay.B1Outputs(overlay.B1Store(self.lease)).load_cision(), b'{"NOTE":{}}')
        oversized = self.fresh()
        seed_outputs(oversized)
        oversized.put(("outputs", "cision.json"), b" " * (MiB + 1))
        self.refused(oversized, "OUTPUT_CISION_BOUND")


# ------------------------------------------------------------------ G2-27 output owner / epoch / compare

class B1OutputsOwnerTests(FakeLeaseCase):
    def test_one_output_owner_per_lease_epoch_is_reused_without_rescanning(self):
        rank, body, record = bundle("owner")
        seed_outputs(self.space, bundles=[(rank, body, record)])
        with self.lease.namespace_operation():
            first_store = overlay.B1Store(self.lease)
            first = overlay.B1Outputs(first_store)
            count = len(self.space.log)
            second = overlay.B1Outputs(overlay.B1Store(self.lease))  # a later input snapshot of the same epoch
            self.assertIs(second, first)
            self.assertIs(second.store, first_store)
            self.assertEqual(len(self.space.log), count)
        with self.lease.namespace_operation():
            third = overlay.B1Outputs(overlay.B1Store(self.lease))
            self.assertIsNot(third, first)
            self.assertIs(self.lease._guidance_outputs_owner, third)
            self.assertIn(("enumerate_directory", ("outputs",)), self.space.log[count:])

    def test_an_interrupted_initialization_is_never_retried_or_repaired_in_its_epoch(self):
        rank, body, record = bundle("interrupted")
        seed_outputs(self.space, bundles=[(rank, body, record)])
        self.space.remove(("outputs", f"body-{sha(body)}.json"))
        with self.lease.namespace_operation():
            store = overlay.B1Store(self.lease)
            with self.assertRaises(overlay.StateError) as raised:
                overlay.B1Outputs(store)
            self.assertEqual(str(raised.exception), "OUTPUT_ACCOUNTING_UNKNOWN")
            self.space.put(("outputs", f"body-{sha(body)}.json"), body)  # the layout is admissible again
            count = len(self.space.log)
            for operand in (store, overlay.B1Store(self.lease)):
                with self.assertRaises(overlay.StateError) as raised:
                    overlay.B1Outputs(operand)
                self.assertEqual(str(raised.exception), "OUTPUT_ADMISSION_UNKNOWN")
            self.assertEqual(len(self.space.log), count)
        with self.lease.namespace_operation():
            self.assertEqual(overlay.B1Outputs(overlay.B1Store(self.lease))._initialization, "READY")
        self.assertEqual(self.space.mutations(), [])

    def test_a_planted_or_cross_lease_owner_and_other_operands_are_refused(self):
        other = self.fresh()
        with other.lease.namespace_operation():
            foreign = overlay.B1Outputs(overlay.B1Store(other.lease))
        for planted in (object(), foreign):
            self.lease._guidance_outputs_owner = planted
            with self.lease.namespace_operation():
                with self.assertRaises(overlay.StateError) as raised:
                    overlay.B1Outputs(overlay.B1Store(self.lease))
            self.assertEqual(str(raised.exception), "OUTPUT_ADMISSION_UNKNOWN")
        self.assertEqual(self.space.log, [])

        class Derived(overlay.B1Outputs):
            pass
        with self.lease.namespace_operation():
            for call in (lambda: Derived(overlay.B1Store(self.lease)), lambda: overlay.B1Outputs(SimpleNamespace()),
                         lambda: overlay.B1Outputs(self.lease)):
                with self.assertRaises(overlay.EffectiveInputsError) as raised:
                    call()
                self.assertEqual(str(raised.exception), "OUTPUT_OPERAND")

    def test_foreign_ledger_or_parent_changes_are_refused_before_any_payload_write(self):
        rank, body, record = bundle("foreign")
        changes = (
            ("ledger-identity", lambda space: space.put(("outputs", "ledger.json"), space.get(("outputs", "ledger.json")))),
            ("ledger-bytes", lambda space: space.put(("outputs", "ledger.json"), encode(ledger_doc(5)))),
            ("parent-identity", lambda space: space.rebind(("outputs",))),
        )
        for label, change in changes:
            with self.subTest(change=label):
                space = self.fresh()
                with space.lease.namespace_operation():
                    owner = overlay.B1Outputs(overlay.B1Store(space.lease))
                    start = len(space.log)
                    change(space)
                    with self.assertRaises(overlay.StateError) as raised:
                        owner.publish(rank, body, record)
                    self.assertEqual(str(raised.exception), "OUTPUT_ACCOUNTING_CHANGED")
                self.assertEqual(space.mutations(start), [])
                self.assertFalse(space.exists(("outputs", f"rank-{sha(rank)}.json")))

    def test_reads_are_fresh_named_and_digest_bound(self):
        rank, body, record = bundle("read")
        seed_outputs(self.space, bundles=[(rank, body, record)])
        with self.lease.namespace_operation():
            owner = overlay.B1Outputs(overlay.B1Store(self.lease))
            start = len(self.space.log)
            self.assertEqual(owner.read("rank", sha(rank)), rank)
            self.assertEqual(owner.read("rank", sha(rank)), rank)
            self.assertEqual(len([entry for entry in self.space.log[start:] if entry[0] == "capture_bytes"]), 2)
            for kind, digest in (("pack", sha(rank)), ("rank", sha(rank).upper()), ("rank", "../x"), ("rank", None)):
                with self.assertRaises(overlay.StateError) as raised:
                    owner.read(kind, digest)
                self.assertEqual(str(raised.exception), "OUTPUT_NAME")
            self.space.tamper[("b1", "outputs", f"rank-{sha(rank)}.json")] = b"{}"
            with self.assertRaises(overlay.StateError) as raised:
                owner.read("rank", sha(rank))
            self.assertEqual(str(raised.exception), "OUTPUT_READBACK")


# ------------------------------------------------------------------ G2-20 / G2-23 host public capture

class HostPublicCaptureTests(FakeLeaseCase):
    def capture(self, space=None, origin=None, seconds=600.0):
        space = space if space is not None else self.space
        value = make_capture(owner_over(space.lease, seconds), origin if origin is not None else FakeOrigin())
        value.network_allowed = True
        return value

    def test_public_role_bytes_are_captured_once_through_the_lease_budget_and_bind_the_manifest(self):
        origin = FakeOrigin(public={"price_shards_latest.json": b'{"prices":{}}', "zh_names_latest.json": b'{"a":1,"a":2}'},
                            files={"scripts/revenue_guidance_host.py": b"# host\n", "scripts/bottleneck_top20_v3.py": b"# rank\n",
                                   "config/order-claims-v2.json": b"{}"})
        capture = make_capture(owner_over(self.lease), origin)
        self.assertEqual(capture.release_id, "synthetic-release")
        self.assertEqual(capture.code, {"scripts/revenue_guidance_host.py": sha(b"# host\n"),
                                        "scripts/bottleneck_top20_v3.py": sha(b"# rank\n")})
        self.assertEqual(capture.file("prices", "price_shards_latest.json"), b'{"prices":{}}')
        self.assertEqual(origin.calls, [("price_shards_latest.json", self.lease.budget, 8 * MiB)])
        self.assertIs(origin.calls[0][1], self.lease.budget)
        self.assertIsNone(capture.file("deep", "company_deep_reports_latest.json"))
        with self.assertRaises(host.HostUnavailable) as raised:
            capture.file("names", "zh_names_latest.json")
        self.assertEqual(str(raised.exception), "JSON_DUPLICATE")
        self.assertNotIn("names", capture.entries)
        origin.public["price_shards_latest.json"] = b'{"prices":{"changed":1}}'  # later mutation of the public role
        manifest = capture.manifest()
        self.assertEqual(manifest["schema"], "guidance-consumed-source-v1")
        self.assertEqual(manifest["release_id"], "synthetic-release")
        self.assertEqual(manifest["code_sha256"], capture.code)
        self.assertEqual(manifest["auxiliary_sha256"], {"prices": sha(b'{"prices":{}}'), "deep": "ABSENT"})
        self.assertEqual(manifest["observations"]["prices"], {"status": "PUBLIC_CAPTURE", "sha256": sha(b'{"prices":{}}')})
        self.assertEqual(len(origin.calls), 3)  # the manifest never re-reads a role
        self.assertEqual(origin.closed, 0)
        capture.close()
        capture.close()
        self.assertEqual(origin.closed, 1)

    def test_public_urls_outside_the_fixed_allowlist_are_refused_before_resolution(self):
        capture = self.capture()
        refused = ["http://query1.finance.yahoo.com/v8/finance/chart/NVDA", "https://evil.example/v8/finance/chart/NVDA",
                   "https://user:pw@query1.finance.yahoo.com/v8/finance/chart/NVDA",
                   "https://query1.finance.yahoo.com/v8/finance/chart/NVDA#fragment",
                   "https://query1.finance.yahoo.com:8443/v8/finance/chart/NVDA",
                   "https://query1.finance.yahoo.com/v7/finance/quote?symbols=NVDA",
                   "https://data.sec.gov/submissions/CIK0000000001.json",
                   "https://query1.finance.yahoo.com/v8/finance/chart/" + "A" * 4096]
        with network() as net:
            for url in refused:
                with self.subTest(url=url[:60]), self.assertRaises(host.HostUnavailable) as raised:
                    capture.fetch(url, optional=True)
                self.assertEqual(str(raised.exception), "PUBLIC_URL_REFUSED")
        self.assertEqual((net.lookups, net.connections), ([], []))
        self.assertIsNone(getattr(self.lease, "_network_work", None))
        self.assertEqual(capture.batch, [])

    def test_held_cache_hits_are_unauthenticated_observations_without_network(self):
        now = host.now()
        failing = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/NVDA?modules=price"
        stale = "https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/NVDA"
        capture = self.capture()
        capture.network_allowed = False
        with self.lease.namespace_operation(), network() as net:
            outputs = overlay.B1Outputs(overlay.B1Store(self.lease))
            outputs.capture_batch([
                (sha(YAHOO.encode()), YAHOO, b'{"chart":1}', now - timedelta(hours=1), "CAPTURED", 200),
                (sha(failing.encode()), failing, None, now - timedelta(hours=1), "HTTP_UNAVAILABLE", 404),
                (sha(stale.encode()), stale, b'{"old":1}', now - timedelta(hours=4), "CAPTURED", 200),
                (sha(SEC.encode()), SEC, b'{"facts":1}', now - timedelta(hours=4), "CAPTURED", 200)], None, None)
            capture.outputs = outputs
            self.assertEqual(capture.fetch(YAHOO), b'{"chart":1}')
            self.assertEqual(capture.observations["http/" + YAHOO], {
                "status": "HELD_PUBLIC_CACHE_UNAUTHENTICATED", "claimed_retrieved_at": stamp(now - timedelta(hours=1)),
                "source_status": "CAPTURED", "http_status": 200, "sha256": sha(b'{"chart":1}')})
            self.assertEqual(capture.fetch(SEC, cap=16 * MiB), b'{"facts":1}')  # 20 h window for SEC facts
            self.assertIsNone(capture.fetch(failing, optional=True))
            with self.assertRaises(host.HostUnavailable) as raised:
                capture.fetch(failing)
            self.assertEqual(str(raised.exception), "PUBLIC_SOURCE_UNAVAILABLE")
            with self.assertRaises(host._AcquisitionDeferred):
                capture.fetch(stale, optional=True)  # 4 h > 3 h: not served, and no network outside a stage
        self.assertEqual((net.lookups, net.connections), ([], []))
        self.assertIsNone(getattr(self.lease, "_network_work", None))
        self.assertEqual(capture.batch, [])

    def test_request_quota_and_pacing_are_the_original_shared_lease_bounds(self):
        capture = self.capture()
        other = "https://query1.finance.yahoo.com/v8/finance/chart/AMD"
        with network([FakeResponse(200, b'{"a":1}')]) as net:
            for work in ({"requests": 120, "bytes": 0, "last": None, "issuers": {}},
                         {"requests": 0, "bytes": 0, "last": None, "issuers": {"NVDA": 24}}):
                self.lease._network_work = work
                with self.assertRaises(host._AcquisitionDeferred):
                    capture.fetch(YAHOO, issuer="NVDA", optional=True)
            capture.network_allowed = False
            with self.assertRaises(host._AcquisitionDeferred):
                capture.fetch(YAHOO, issuer="AMD", optional=True)
            self.assertEqual((net.lookups, net.connections), ([], []))
            capture.network_allowed = True
            self.lease._network_work = {"requests": 7, "bytes": 0, "last": time.monotonic(), "issuers": {"NVDA": 24}}
            self.assertEqual(capture.fetch(YAHOO, issuer="AMD", optional=True), b'{"a":1}')
            self.assertEqual(len(net.sleeps), 1)
            self.assertTrue(0 <= net.sleeps[0] <= 0.5)
            work = self.lease._network_work
            self.assertEqual((work["requests"], work["issuers"], work["bytes"]), (8, {"NVDA": 24, "AMD": 1}, 7))
            capture.owner.deadline = time.monotonic() + 0.2
            work["last"] = time.monotonic()
            with self.assertRaises(host.HostUnavailable) as raised:
                capture.fetch(other, issuer="AMD", optional=True)  # pacing cannot outlive the request budget
            self.assertEqual(str(raised.exception), "REQUEST_DEADLINE")
            self.assertEqual((work["requests"], len(net.sleeps), len(net.connections)), (8, 1, 1))

    def test_complete_bodies_are_charged_once_and_both_owners_are_closed(self):
        capture = self.capture()
        body = b'{"chart":{"result":[]}}'
        eof = b'{"eof":true}'
        known = FakeResponse(200, body, chunk=5)
        closing = FakeResponse(200, eof, length=None, chunk=4)
        detached = FakeResponse(200, b'{"detached":1}', length=None, readable_socket=False)
        sec = FakeResponse(200, b'{"facts":{}}')
        with network([known, closing, detached, sec]) as net:
            before = self.lease.budget.new_capture_bytes
            self.assertEqual(capture.fetch(YAHOO, issuer="NVDA"), body)
            self.assertEqual(self.lease.budget.new_capture_bytes, before + len(body))
            self.assertEqual(capture.fetch("https://query1.finance.yahoo.com/v8/finance/chart/AMD", issuer="AMD"), eof)
            self.assertEqual(capture.fetch("https://query1.finance.yahoo.com/v8/finance/chart/TSM", issuer="TSM"),
                             b'{"detached":1}')
            self.assertEqual(capture.fetch(SEC, issuer="NVDA", cap=16 * MiB), b'{"facts":{}}')
        first = net.connections[0]
        self.assertEqual((first.host, first.address), ("query1.finance.yahoo.com", PUBLIC_ADDRESS))
        method, path, headers = first.requests[0]
        self.assertEqual((method, path), ("GET", "/v8/finance/chart/NVDA?range=5d&interval=1d"))
        self.assertEqual(headers["Accept-Encoding"], "identity")
        self.assertNotEqual(headers["User-Agent"], "synthetic contact")  # SEC contact only for SEC hosts
        self.assertEqual(net.connections[3].requests[0][2]["User-Agent"], "synthetic contact")
        for connection, response in zip(net.connections, (known, closing, detached, sec)):
            self.assertEqual((connection.closed, response.closed), (1, 1))
        self.assertEqual(len(known.sock.timeouts), math.ceil(len(body) / 5))  # none after the final read closed it
        self.assertEqual(len(closing.sock.timeouts), math.ceil(len(eof) / 4) + 1)  # read to EOF
        self.assertTrue(all(0 < value <= 30.0 for value in known.sock.timeouts + closing.sock.timeouts))
        observed = capture.observations["http/" + YAHOO]
        self.assertEqual((observed["status"], observed["http_status"], observed["sha256"]), ("CAPTURED", 200, sha(body)))
        key, url, raw, moment, status, http_status = capture.batch[0]
        self.assertEqual((key, url, raw, status, http_status), (sha(YAHOO.encode()), YAHOO, body, "CAPTURED", 200))
        self.assertIs(moment.tzinfo, timezone.utc)
        self.assertEqual(len(capture.batch), 4)

    def test_short_bodies_and_optional_failures_are_typed_absence_never_empty_success(self):
        cases = (
            ("short-body", lambda: [FakeResponse(200, b'{"a"', length=10)], PUBLIC_ADDRESS, "TRANSPORT_UNAVAILABLE", None),
            ("http-404", lambda: [FakeResponse(404, b"missing")], PUBLIC_ADDRESS, "HTTP_UNAVAILABLE", 404),
            ("http-503-empty", lambda: [FakeResponse(503, b"")], PUBLIC_ADDRESS, "HTTP_UNAVAILABLE", 503),
            ("connection-reset", lambda: [ConnectionResetError("synthetic reset")], PUBLIC_ADDRESS, "TRANSPORT_UNAVAILABLE", None),
            ("remote-disconnected", lambda: [http.client.RemoteDisconnected("synthetic")], PUBLIC_ADDRESS,
             "TRANSPORT_UNAVAILABLE", None),
            ("resolver", lambda: [], socket.gaierror(11001, "synthetic"), "TRANSPORT_UNAVAILABLE", None),
        )
        for label, responses, address, status, http_status in cases:
            with self.subTest(case=label):
                space = self.fresh()
                capture = self.capture(space)
                served = responses()
                before = space.lease.budget.new_capture_bytes
                with network(served, address) as net:
                    self.assertIsNone(capture.fetch(YAHOO, optional=True))
                self.assertIsNone(capture.entries["http/" + YAHOO])
                observed = capture.observations["http/" + YAHOO]
                self.assertEqual((observed["status"], observed.get("http_status"), observed["sha256"]), (status, http_status, None))
                key, url, raw, moment, row_status, row_http = capture.batch[-1]
                self.assertEqual((key, url, raw, row_status, row_http), (sha(YAHOO.encode()), YAHOO, None, status, http_status))
                self.assertEqual(space.lease.budget.new_capture_bytes, before)
                for connection in net.connections:
                    self.assertEqual(connection.closed, 1)
                for response in served:
                    if type(response) is FakeResponse:
                        self.assertEqual(response.closed, 1)
                required = self.capture(self.fresh())
                with network(responses(), address), self.assertRaises(host.HostUnavailable) as raised:
                    required.fetch(YAHOO)
                self.assertEqual(str(raised.exception),
                                 "PUBLIC_SOURCE_UNAVAILABLE" if status == "HTTP_UNAVAILABLE" else "PUBLIC_TRANSPORT_UNAVAILABLE")
                self.assertEqual(required.batch, [])
                self.assertNotIn("http/" + YAHOO, required.entries)

    def test_control_faults_propagate_through_optional_channels_with_owner_cleanup(self):
        def expire(capture):
            return lambda response: setattr(capture.owner, "deadline", time.monotonic() - 1)

        def exhaust(space):
            space.lease.budget.new_capture_bytes = space.lease.budget.max_new_capture_bytes

        cases = (
            ("non-global-address", [], "10.0.0.7", {}, host.HostUnavailable, "PUBLIC_DNS_REFUSED"),
            ("loopback-address", [], "127.0.0.1", {}, host.HostUnavailable, "PUBLIC_DNS_REFUSED"),
            ("compressed-body", [FakeResponse(200, b"{}", encoding="gzip")], PUBLIC_ADDRESS, {},
             host.HostUnavailable, "PUBLIC_ENCODING_REFUSED"),
            ("response-cap", [FakeResponse(200, b"12345")], PUBLIC_ADDRESS, {"cap": 4},
             host.HostUnavailable, "NETWORK_CAPACITY_UNAVAILABLE"),
            ("shared-128-MiB", [FakeResponse(200, b"12")], PUBLIC_ADDRESS,
             {"work": {"requests": 0, "bytes": 128 * MiB - 1, "last": None, "issuers": {}}},
             host.HostUnavailable, "NETWORK_CAPACITY_UNAVAILABLE"),
            ("request-deadline", [FakeResponse(200, b"abcdef", chunk=3)], PUBLIC_ADDRESS, {"expire": True},
             host.HostUnavailable, "REQUEST_DEADLINE"),
            ("native-capture-budget", [FakeResponse(200, b"{}")], PUBLIC_ADDRESS, {"exhaust": True},
             storage.BudgetExceededError, None),
        )
        for label, responses, address, options, error, reason in cases:
            with self.subTest(case=label):
                space = self.fresh()
                capture = self.capture(space)
                if "work" in options:
                    space.lease._network_work = options["work"]
                if options.get("expire"):
                    responses[0].on_read = expire(capture)
                if options.get("exhaust"):
                    exhaust(space)
                with network(responses, address) as net, self.assertRaises(error) as raised:
                    capture.fetch(YAHOO, optional=True, cap=options.get("cap", 8 * MiB))
                if reason is not None:
                    self.assertEqual(str(raised.exception), reason)
                self.assertNotIn("http/" + YAHOO, capture.entries)
                self.assertEqual(capture.batch, [])
                self.assertEqual(len(net.connections), len(responses))
                for connection, response in zip(net.connections, responses):
                    self.assertEqual((connection.closed, response.closed), (1, 1))

    def test_a_failed_tls_wrap_closes_the_actual_tcp_owner(self):
        class Interrupt(BaseException):
            pass

        class Context:
            verify_mode, check_hostname, post_handshake_auth = ssl.CERT_REQUIRED, True, None

            def __init__(self, error=None):
                self.error, self.wrapped = error, []

            def wrap_socket(self, plain, server_hostname=None):
                self.wrapped.append((plain, server_hostname))
                if self.error is not None:
                    raise self.error
                return SimpleNamespace(tls=plain)

        for error in (ssl.SSLError("synthetic handshake"), Interrupt(), None):
            with self.subTest(error=type(error).__name__):
                plain, context = FakeSocket(), Context(error)
                with mock.patch.object(host.ssl, "create_default_context", return_value=context), \
                        mock.patch.object(host.socket, "create_connection", return_value=plain) as connect:
                    connection = host._PinnedTLS("query1.finance.yahoo.com", PUBLIC_ADDRESS, 7.5)
                    if error is None:
                        connection.connect()
                    else:
                        with self.assertRaises(type(error)):
                            connection.connect()
                connect.assert_called_once_with((PUBLIC_ADDRESS, 443), 7.5)
                self.assertEqual(context.wrapped, [(plain, "query1.finance.yahoo.com")])
                self.assertEqual(plain.closed, 0 if error is None else 1)
                if error is None:
                    self.assertIs(connection.sock.tls, plain)

    def test_dynamic_fetch_keeps_control_faults_and_staged_pauses_distinct(self):
        capture = self.capture()
        capture.network_allowed = False
        other = "https://query1.finance.yahoo.com/v8/finance/chart/AMD"
        with network([FakeResponse(200, b"{}")]) as net:
            with self.assertRaises(host._CaptureControlFault):
                capture.dynamic_fetch("https://evil.example/x")
            self.assertFalse(capture.network_allowed)
            self.lease._network_work = {"requests": 120, "bytes": 0, "last": None, "issuers": {}}
            with self.assertRaises(host._AcquisitionDeferred):
                capture.dynamic_fetch(YAHOO)
            self.assertFalse(capture.network_allowed)
            self.lease._network_work = {"requests": 0, "bytes": 0, "last": None, "issuers": {}}
            self.assertEqual(capture.dynamic_fetch(YAHOO), b"{}")
            self.assertEqual(self.lease._network_work["issuers"], {"dynamic/query1.finance.yahoo.com": 1})
            capture.owner.deadline = time.monotonic() + 20
            with self.assertRaises(host._AcquisitionDeferred):
                capture.dynamic_fetch(other)
            self.assertEqual(capture.progress_state, {"Stage": "dynamic", "Cursor": 0, "Slots": 1})
            self.assertEqual(capture.dynamic_fetch(YAHOO), b"{}")  # already captured: no pause, no new request
        self.assertEqual(len(net.connections), 1)

    def test_observation_times_are_rechecked_at_the_exact_cutoff(self):
        capture = self.capture()
        cutoff = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
        yahoo, sec = "http/" + YAHOO, "http/" + SEC
        capture.observations = {yahoo: {"observed_at": (cutoff - timedelta(hours=3)).isoformat()},
                                sec: {"claimed_retrieved_at": "2026-10-09T16:00:00Z"},
                                "prices": {"status": "PUBLIC_CAPTURE"}}
        capture.require_observation_times(cutoff)
        for observations in ({yahoo: {"observed_at": (cutoff - timedelta(hours=3, seconds=1)).isoformat()}},
                             {yahoo: {"observed_at": (cutoff + timedelta(seconds=1)).isoformat()}},
                             {yahoo: {"claimed_retrieved_at": "2026-10-10T08:59:59Z", "observed_at": cutoff.isoformat()}},
                             {sec: {"claimed_retrieved_at": "2026-10-09T15:59:59Z"}}):
            capture.observations = observations
            with self.assertRaises(host.HostUnavailable) as raised:
                capture.require_observation_times(cutoff)
            self.assertEqual(str(raised.exception), "CAPTURE_FRESHNESS_UNAVAILABLE")


# ------------------------------------------------------------------ G2-21 / G2-22 acquisition plans

class HostAcquisitionTests(FakeLeaseCase):
    def test_the_real_planner_schedules_every_configured_member_channel_before_any_request(self):
        layers = (ROOT / "config" / "bottleneck-layers-v3.json").read_bytes()
        files = {"config/" + relative: b"{}" for relative in host.CONFIG_FILES.values()}
        files["config/" + host.CONFIG_FILES["layers"]] = layers
        origin = FakeOrigin(public={host.PUBLIC_FILES["tickers"]: encode({"fields": ["ticker", "cik"], "data": []})},
                            files=files)
        seen, real = [], host._Capture._acquire

        def spy(capture, plan, outputs, name):
            seen.append((name, list(plan)))
            return real(capture, plan, outputs, name)

        with self.lease.namespace_operation(), network() as net, mock.patch.object(host._Capture, "_acquire", spy):
            outputs = overlay.B1Outputs(overlay.B1Store(self.lease))
            capture = make_capture(owner_over(self.lease), origin)
            self.lease._network_work = {"requests": 112, "bytes": 0, "last": None, "issuers": {}}
            with self.assertRaises(host._AcquisitionDeferred):
                capture.collect(outputs)
            self.assertEqual(outputs.progress(plan_id("base"), 336), 0)
        # The paused cursor 0 is persisted, not merely the default of an absent plan.
        self.assertEqual(self.space.json(("outputs", "capture-index.json"))["progress"], {plan_id("base"): 0})
        config = json.loads(layers)["layers"]
        members = sorted({row["symbol"] for layer in config for row in layer["capturers"]})
        terms = [term for layer in config for term in layer["filing_terms"]]
        self.assertEqual([name for name, _ in seen], ["base"])
        plan = seen[0][1]
        self.assertEqual(len(plan), 3 * len(members) + 2 * sum("." not in symbol for symbol in members) + 2 + 2 * len(terms))
        self.assertEqual(len(plan), 336)  # the documented universe: 60 members / 40 US, 37 filing terms
        slots = [slot for slot, _, _, _ in plan]
        self.assertEqual(len(set(slots)), len(plan))
        expected = set()
        for symbol in members:
            expected.update(sha(f"yahoo/{kind}/{symbol}".encode()) for kind in ("chart", "summary", "financials"))
            if "." not in symbol:
                expected.update(sha(f"nasdaq/{symbol}/{suffix}".encode()) for suffix in ("targetprice", "earnings-forecast"))
        expected.update(sha(f"news/{term}/{label}".encode()) for term in terms for label in ("recent", "prior"))
        expected.update(sha(f"taiwan/{suffix}".encode()) for suffix in ("TW", "TWO"))
        self.assertEqual(set(slots), expected)
        self.assertEqual((net.lookups, net.connections), ([], []))
        self.assertEqual(capture.progress_state, {"Stage": "base", "Cursor": 0, "Slots": 336})

    def test_a_pause_at_112_shared_requests_persists_the_cursor_and_resumes_fairly(self):
        plan = plan_rows("AAA", "BBB", "CCC")
        # BBB/CCC are scripted only so that a 113th shared request is served and refused by assertion.
        spare = [FakeResponse(200, b'{"s":"BBB"}'), FakeResponse(200, b'{"s":"CCC"}')]
        with self.lease.namespace_operation(), network([FakeResponse(200, b'{"s":"AAA"}')] + spare) as net:
            outputs = overlay.B1Outputs(overlay.B1Store(self.lease))
            capture = make_capture(owner_over(self.lease), FakeOrigin())
            capture.outputs = outputs
            self.lease._network_work = {"requests": 111, "bytes": 0, "last": None, "issuers": {}}
            with self.assertRaises(host._AcquisitionDeferred):
                capture._acquire(plan, outputs, "base")
            self.assertEqual(outputs.progress(plan_id("base"), 3), 1)
        self.assertEqual(self.lease._network_work["requests"], 112)
        self.assertEqual(net.responses, spare)  # no request after the 112th
        self.assertEqual(capture.progress_state, {"Stage": "base", "Cursor": 1, "Slots": 3})
        self.assertFalse(capture.network_allowed)
        self.assertEqual(capture.batch, [])
        self.assertEqual([connection.requests[0][1] for connection in net.connections], ["/v8/finance/chart/AAA"])
        index = self.space.json(("outputs", "capture-index.json"))
        self.assertEqual((index["progress"], set(index["entries"])), ({plan_id("base"): 1}, {plan[0][0]}))
        lease = self.space.reopen()  # a later invocation shares only the persisted index
        with lease.namespace_operation(), network([FakeResponse(200, b'{"s":"BBB"}'), FakeResponse(200, b'{"s":"CCC"}')]) as net:
            outputs = overlay.B1Outputs(overlay.B1Store(lease))
            capture = make_capture(owner_over(lease), FakeOrigin())
            capture.outputs = outputs
            capture._acquire(plan, outputs, "base")
            self.assertEqual(outputs.progress(plan_id("base"), 3), 1)
        self.assertEqual([connection.requests[0][1] for connection in net.connections],
                         ["/v8/finance/chart/BBB", "/v8/finance/chart/CCC"])
        self.assertEqual(capture.observations["http/" + plan[0][1]]["status"], "HELD_PUBLIC_CACHE_UNAUTHENTICATED")
        self.assertEqual(capture.entries["http/" + plan[0][1]], b'{"s":"AAA"}')
        self.assertEqual(len(net.sleeps), 1)  # shared 0.5 s pacing between the two actual requests
        self.assertEqual(set(self.space.json(("outputs", "capture-index.json"))["entries"]), {row[0] for row in plan})

    def test_each_original_bound_pauses_before_its_request_and_persists_the_cursor(self):
        plan = plan_rows("AAA", "BBB")
        rows = (
            ("24-per-issuer", {"requests": 0, "bytes": 0, "last": None, "issuers": {"BBB": 24}}, 600.0, b'{"s":1}', False, 1, 1),
            ("8-MiB-batch", None, 600.0, b"x" * (8 * MiB), False, 1, 1),
            ("under-35-s", None, 34.0, b'{"s":1}', False, 0, 0),
            ("held-slot-under-35-s", None, 34.0, b'{"s":1}', True, 0, 1),
        )
        for label, work, seconds, first, held, connections, cursor in rows:
            with self.subTest(bound=label):
                space = self.fresh()
                with space.lease.namespace_operation(), network([FakeResponse(200, first)]) as net:
                    outputs = overlay.B1Outputs(overlay.B1Store(space.lease))
                    if held:
                        outputs.capture_batch([(plan[0][0], plan[0][1], b'{"held":1}', host.now(), "CAPTURED", 200)], None, None)
                    if work is not None:
                        space.lease._network_work = work
                    capture = make_capture(owner_over(space.lease, seconds), FakeOrigin())
                    capture.outputs = outputs
                    with self.assertRaises(host._AcquisitionDeferred):
                        capture._acquire(plan, outputs, "base")
                    self.assertEqual(outputs.progress(plan_id("base"), 2), cursor)
                self.assertEqual(len(net.connections), connections)
                self.assertEqual(capture.progress_state, {"Stage": "base", "Cursor": cursor, "Slots": 2})
                self.assertFalse(capture.network_allowed)
                self.assertEqual(capture.batch, [])

    def test_plan_bounds_refuse_before_any_output_io(self):
        with self.lease.namespace_operation():
            outputs = overlay.B1Outputs(overlay.B1Store(self.lease))
            capture = make_capture(owner_over(self.lease), FakeOrigin())
            count = len(self.space.log)
            for plan in ([], plan_rows("AAA") * 1025):
                with self.assertRaises(host.HostUnavailable) as raised:
                    capture._acquire(plan, outputs, "base")
                self.assertEqual(str(raised.exception), "ACQUISITION_PLAN_BOUND")
            self.assertEqual(len(self.space.log), count)
        self.assertFalse(capture.network_allowed)


class RankingPauseTests(FakeLeaseCase):
    def session(self, space, journal, commits):
        token = object()
        space.lease.read_journal = lambda: SimpleNamespace(state=copy.deepcopy(journal["state"]), version=token,
                                                           state_required=True)
        space.lease.commit_journal = lambda *args: commits.append(args)
        value = host._Session(time.monotonic() + 600, {})
        value.lease, value.phase = space.lease, "idle"
        value.input_revision = lambda: A  # native snapshot acquisition is outside this mocked contract
        return value

    def test_a_known_acquisition_pause_is_pending_without_witness_or_journal_write(self):
        plan = plan_rows("AAA", "BBB")

        def collect(capture, outputs):
            capture.outputs = outputs
            capture._acquire(plan, outputs, "base")
            raise AssertionError("the synthetic plan did not pause")

        journal, commits, origin = {"state": journal_state(A, A)}, [], FakeOrigin()
        session = self.session(self.space, journal, commits)
        self.lease._network_work = {"requests": 111, "bytes": 0, "last": None, "issuers": {}}
        with self.lease.namespace_operation(), network([FakeResponse(200, b'{"s":"AAA"}')]) as net, \
                mock.patch.object(host.provisioner, "controlled_origin", return_value=origin), \
                mock.patch.object(host._Capture, "collect", collect):
            result = session.rank({"Mode": "Dirty", "Revision": A})
            self.assertEqual(session.completion(A), {"Completed": False, "Revision": A})
        self.assertEqual(result, {"Completed": False, "Revision": A, "AcquisitionProgress": True,
                                  "Progress": {"Stage": "base", "Cursor": 1, "Slots": 2}, "Reason": "ACQUISITION_PENDING"})
        self.assertIsNone(session.witness)
        self.assertEqual(session.phase, "idle")
        self.assertEqual(commits, [])
        self.assertEqual(origin.closed, 1)
        self.assertEqual(len(net.connections), 1)
        self.assertEqual(self.space.json(("outputs", "capture-index.json"))["progress"], {plan_id("base"): 1})
        self.assertEqual([name for name in self.space.node(("outputs",)).children if name.startswith("record-")], [])

        moved = self.fresh()
        journal, commits, origin = {"state": journal_state(A, A)}, [], FakeOrigin()
        session = self.session(moved, journal, commits)

        def collect_while_the_journal_moves(capture, outputs):
            journal["state"] = journal_state(A, None)
            collect(capture, outputs)

        moved.lease._network_work = {"requests": 112, "bytes": 0, "last": None, "issuers": {}}
        with moved.lease.namespace_operation(), network() as net, \
                mock.patch.object(host.provisioner, "controlled_origin", return_value=origin), \
                mock.patch.object(host._Capture, "collect", collect_while_the_journal_moves):
            with self.assertRaises(host.HostUnavailable) as raised:
                session.rank({"Mode": "Dirty", "Revision": A})
        self.assertEqual(str(raised.exception), "ACQUISITION_BINDING_CHANGED")
        self.assertEqual(session.phase, "failed")
        self.assertIsNone(session.witness)
        self.assertEqual((commits, origin.closed, net.connections), ([], 1, []))


if __name__ == "__main__":
    unittest.main()
