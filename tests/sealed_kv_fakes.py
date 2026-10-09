"""Fake KV, fixtures and row harnesses for the T13-P1 sealed-snapshot transaction tests.

Synthetic values only. No network, no credentials, no real wrangler/npx, no
production KV and NO real subprocess at all: KvTestCase installs a guard over
subprocess.run and subprocess.Popen that records the hit and raises, so no argv
can ever launch a process. The seam-B fake answers every 'kv' argv itself, and
RB's tracked check (`git ls-files state/v213-snapshots/<run>/pointer.raw.json`)
is served by a fake from the row's declared tracked set over a plain tmp ROOT
(no git repository exists). Any other argv raises the guard error.

Hook counting: the nth value of fail_put / corrupt_get / missing_get counts the
calls of that (operation, key) made after the hook is installed, 1-based; nth
None means every call. A row that runs several sync passes through one FakeKV
therefore installs its hook right before the pass it targets.

Row tuples: Row(names, values) is a tuple that remembers its field names;
KvTestCase.assertRow(got, want) is the row's assertEqual: it compares the tuple
with the literal and, on a mismatch, appends the names of the differing fields to
the failure message (DIFF_FIELDS=a,b) so a mutation driver can read which field a
mutant moved. It asserts nothing else.
Helpers here never assert or raise on a row's behaviour: a failed run yields an
exception-class exit code or a sentinel in the tuple.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent

NOWRITE = "NOWRITE"
WRITE_THEN_FAIL = "WRITE_THEN_FAIL"
NETWORK = "NETWORK"

RUN = "20261001T000000Z-0123456789ab"
RUN2 = "20261002T000000Z-0123456789cd"
POINTER_KEY = "snapshot:current"
OLD_POINTER = b'{"run_id":"previous-pointer-placeholder"}'
BLOB_PREFIX = "blob:v1:"
Q_OK = ("SUCCEEDED", "COMPLETE", "NONE", "READBACK_CONFIRMED")
SY_FIELDS = ("exit", "outcome", "ops", "diff", "ledger", "stage")

GUARD_HITS: list = []


class KvGuardError(RuntimeError):
    """A subprocess launch was attempted (never launched)."""


def is_kv(argv) -> bool:
    return isinstance(argv, (list, tuple)) and "kv" in [str(part) for part in argv]


def guard(argv):
    """Record the argv and raise: the tests launch no process of any kind."""
    shown = [str(part) for part in argv] if isinstance(argv, (list, tuple)) else [repr(argv)]
    GUARD_HITS.append(shown)
    raise KvGuardError("real subprocess blocked")


def guarded_run(*args, **kwargs):
    return guard(args[0] if args else kwargs.get("args"))


def guarded_popen(*args, **kwargs):
    return guard(args[0] if args else kwargs.get("args"))


def sha(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Row(tuple):
    """A tuple that remembers its field names."""

    def __new__(cls, names, values):
        self = super().__new__(cls, tuple(values))
        self.names = tuple(names)
        return self


class KvTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="t13p1-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.assertFalse(self.tmp.is_relative_to(ROOT.resolve()), "tmp must be outside the repository")
        GUARD_HITS.clear()
        for name, replacement in (("run", guarded_run), ("Popen", guarded_popen)):
            patcher = mock.patch.object(subprocess, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.assertEqual(GUARD_HITS, [], "a real subprocess was attempted")

    def assertRow(self, got, want):
        want = tuple(want)
        diff = [name for name, a, b in zip(got.names, got, want) if a != b]
        if len(got) != len(want):
            diff.append("arity")
        self.assertEqual(tuple(got), want, "DIFF_FIELDS=" + ",".join(diff))


# ------------------------------------------------------------------ fake KV
class FakeKV:
    def __init__(self, store: dict | None = None):
        self.store: dict[str, bytes] = dict(store or {})
        self.log: list[tuple[str, str]] = []
        self.puts: list[tuple[str, object]] = []
        self.argv_log: list[list[str]] = []
        self.tracked: frozenset = frozenset()
        self.git_calls: list[tuple] = []
        self._count: dict[tuple[str, str], int] = {}
        self._put_hooks: dict[str, dict] = {}
        self._get_hooks: dict[str, dict] = {}

    # hooks ---------------------------------------------------------------
    def fail_put(self, key: str, nth: int | None = 1, mode: str = NOWRITE) -> None:
        self._put_hooks[key] = {"base": self._count.get(("put", key), 0), "nth": nth, "mode": mode}

    def corrupt_get(self, key: str, nth: int | None, data: bytes) -> None:
        self._get_hooks[key] = {"base": self._count.get(("get", key), 0), "nth": nth, "kind": "corrupt", "data": data}

    def missing_get(self, key: str, nth: int | None) -> None:
        self._get_hooks[key] = {"base": self._count.get(("get", key), 0), "nth": nth, "kind": "missing", "data": None}

    def clear_hooks(self) -> None:
        self._put_hooks.clear()
        self._get_hooks.clear()

    def mark(self) -> tuple[int, int]:
        return len(self.log), len(self.puts)

    # core ----------------------------------------------------------------
    def _bump(self, op: str, key: str) -> int:
        self._count[(op, key)] = self._count.get((op, key), 0) + 1
        return self._count[(op, key)]

    @staticmethod
    def _hit(hook: dict | None, n: int) -> bool:
        return bool(hook) and (hook["nth"] is None or n - hook["base"] == hook["nth"])

    def do_put(self, key: str, data: bytes, ttl) -> str:
        n = self._bump("put", key)
        self.log.append(("put", key))
        self.puts.append((key, ttl))
        hook = self._put_hooks.get(key)
        if self._hit(hook, n):
            if hook["mode"] == WRITE_THEN_FAIL:
                self.store[key] = data
                return "FAIL"
            if hook["mode"] == NETWORK:
                return "NETWORK"
            return "FAIL"
        self.store[key] = data
        return "OK"

    def do_get(self, key: str) -> bytes | None:
        n = self._bump("get", key)
        self.log.append(("get", key))
        hook = self._get_hooks.get(key)
        if self._hit(hook, n):
            return hook["data"]
        return self.store.get(key)

    # seam A (SY.client_put / SY.client_get) -------------------------------
    def sy_put(self, key, local_path, ttl=None) -> bool:
        return self.do_put(key, Path(local_path).read_bytes(), ttl) == "OK"

    def sy_get(self, key):
        raw = self.do_get(key)
        return None if raw is None else raw.decode("utf-8").rstrip("\r\n")

    # RB kv layer (RB.wrangler_kv_get / RB.wrangler_kv_put) ----------------
    def rb_get(self, key):
        raw = self.do_get(key)
        return None if raw is None else raw.decode("utf-8").rstrip("\r\n")

    def rb_put(self, key, body) -> bool:
        return self.do_put(key, body.encode("utf-8"), None) == "OK"

    # subprocess fakes ------------------------------------------------------
    def git_run(self, *args, **kwargs):
        """RB's tracked check, served from self.tracked (repo-relative posix paths): exactly
        ['git', 'ls-files', <path>] answers stdout '<path>' + LF when tracked and '' when not; any other argv raises."""
        argv = args[0] if args else kwargs.get("args")
        if not (isinstance(argv, list) and len(argv) == 3 and argv[0] == "git" and argv[1] == "ls-files"):
            return guard(argv)
        self.git_calls.append((tuple(argv), kwargs.get("cwd")))
        stdout = argv[2] + "\n" if argv[2] in self.tracked else ""
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    # seam B (subprocess.run) ----------------------------------------------
    def fake_run(self, *args, **kwargs):
        argv = args[0] if args else kwargs.get("args")
        if not is_kv(argv):
            return self.git_run(*args, **kwargs)
        argv = [str(part) for part in argv]
        self.argv_log.append(list(argv))
        rest = argv[argv.index("kv") + 1:]
        if len(rest) < 3 or rest[0] != "key" or rest[1] not in ("get", "put"):
            return subprocess.CompletedProcess(argv, 2, "", "unsupported kv argv")
        op, key = rest[1], rest[2]
        options = {}
        for index, token in enumerate(rest[3:], start=3):
            if token in ("--path", "--ttl") and index + 1 < len(rest):
                options[token] = rest[index + 1]
        if op == "put":
            status = self.do_put(key, Path(options["--path"]).read_bytes(), options.get("--ttl"))
            if status == "OK":
                return subprocess.CompletedProcess(argv, 0, "", "")
            return subprocess.CompletedProcess(argv, 1, "", "fetch failed" if status == "NETWORK" else "kv put failed")
        raw = self.do_get(key)
        if raw is None:
            return subprocess.CompletedProcess(argv, 1, "", "key not found")
        return subprocess.CompletedProcess(argv, 0, raw.decode("utf-8"), "")


def store_diff(before: dict, after: dict, names: dict) -> tuple:
    rows = []
    for key in set(before) | set(after):
        label = names.get(key, key)
        if key not in before:
            rows.append((label, "NEW"))
        elif key not in after:
            rows.append((label, "DEL"))
        elif before[key] != after[key]:
            rows.append((label, "CHG"))
    return tuple(sorted(rows))


def ops_of(kv: FakeKV, mark: int, names: dict) -> tuple:
    return tuple((op, names.get(key, key)) for op, key in kv.log[mark:])


# ----------------------------------------------------------------- fixtures
class Fixture:
    """One synthetic sealed run. flavor 'sy': three blobs + two run keys (B1..B3, S1, S2);
    flavor 'rb': three run keys (O1..O3). Keys are written in sorted order."""

    def __init__(self, run: str = RUN, flavor: str = "sy", s1_body: str | None = None):
        self.run = run
        objects: dict[str, str] = {}
        names: dict[str, str] = {}
        if flavor == "sy":
            bodies = [f"blob-body {run} {index}" for index in (1, 2, 3)]
            for symbol, key in zip(("B1", "B2", "B3"), sorted(BLOB_PREFIX + sha(body) for body in bodies)):
                objects[key] = next(body for body in bodies if BLOB_PREFIX + sha(body) == key)
                names[key] = symbol
            objects[f"snapshot:{run}:v213:a:latest"] = s1_body if s1_body is not None else '{"slot":"a"}'
            objects[f"snapshot:{run}:v213:b:latest"] = '{"slot":"b"}'
            names[f"snapshot:{run}:v213:a:latest"] = "S1"
            names[f"snapshot:{run}:v213:b:latest"] = "S2"
        else:
            for index in (1, 2, 3):
                key = f"snapshot:{run}:v213:o{index}:latest"
                objects[key] = json.dumps({"run": run, "slot": index}, separators=(",", ":"))
                names[key] = f"O{index}"
        self.objects = dict(sorted(objects.items()))
        self.names = dict(names)
        self.names[POINTER_KEY] = "POINTER"
        self.key = {symbol: key for key, symbol in self.names.items()}
        self.pointer = {
            "schema_version": 2, "run_id": run, "transaction_id": "txn-" + run, "seal_sha256": "seal-" + run,
            "public_data_as_of": "2026-10-01T00:00:00Z", "promoted_at": "2026-10-01T01:00:00Z",
            "provider_scope": "public_only", "owner_watchlist_inherited": False,
        }
        self.ptr_raw = json.dumps(self.pointer, separators=(",", ":"))

    def objects_bytes(self) -> bytes:
        return json.dumps(self.objects, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def write_to(self, directory: Path) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "objects.json").write_bytes(self.objects_bytes())
        (directory / "pointer.raw.json").write_bytes(self.ptr_raw.encode("utf-8"))
        return directory

    def store_bytes(self) -> dict:
        return {key: body.encode("utf-8") for key, body in self.objects.items()}


def rewrite_objects(directory: Path, objects: dict) -> None:
    (Path(directory) / "objects.json").write_bytes(json.dumps(objects, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def rewrite_pointer(directory: Path, pointer: dict) -> None:
    (Path(directory) / "pointer.raw.json").write_bytes(json.dumps(pointer, separators=(",", ":")).encode("utf-8"))


def make_rb_root(base: Path, fixtures) -> tuple[Path, frozenset]:
    """A per-row plain tmp ROOT (no git repository, no process) holding
    state/v213-snapshots/<run>/{objects.json,pointer.raw.json} for every fixture, and the declared tracked set:
    the repo-relative posix pointer.raw.json path of every fixture (what `git ls-files` would list)."""
    root = Path(base) / "rbroot"
    root.mkdir(parents=True, exist_ok=True)
    tracked = set()
    for fixture in fixtures:
        directory = fixture.write_to(root / "state" / "v213-snapshots" / fixture.run)
        tracked.add((directory / "pointer.raw.json").relative_to(root).as_posix())
    return root, frozenset(tracked)


def make_cloud(base: Path, version: str = "4.0.0", *, declared: str | None = None, locked: str | None = None,
               installed: str | None = None, with_cli: bool = True) -> Path:
    cloud = Path(base) / "cloud"
    package = cloud / "node_modules" / "wrangler"
    (package / "bin").mkdir(parents=True, exist_ok=True)
    (cloud / "package.json").write_text(json.dumps({"devDependencies": {"wrangler": declared or version}}), encoding="utf-8")
    (cloud / "package-lock.json").write_text(
        json.dumps({"packages": {"node_modules/wrangler": {"version": locked or version}}}), encoding="utf-8")
    (package / "package.json").write_text(json.dumps({"version": installed or version}), encoding="utf-8")
    if with_cli:
        (package / "bin" / "wrangler.js").write_text("// synthetic cli placeholder\n", encoding="utf-8")
    return cloud


@contextlib.contextmanager
def cli_environment(node_path: Path):
    with mock.patch.dict(os.environ, {"PROJECT_NODE": str(node_path)}):
        os.environ.pop("NODE_FOR_RUNNER", None)
        yield


# --------------------------------------------------------------- SY harness
class SyRun:
    def __init__(self, **fields):
        self.__dict__.update(fields)

    def row(self, *extras: str) -> Row:
        values = list(self.values)
        names = list(SY_FIELDS)
        for extra in extras:
            names.append(extra)
            values.append(getattr(self, extra))
        return Row(names, values)


def parse_marker(stdout: str, marker: str):
    for line in stdout.splitlines():
        if line.startswith(marker + " "):
            try:
                return json.loads(line[len(marker) + 1:])
            except ValueError:
                return None
    return None


def run_sy(sy, kv: FakeKV, run_dir: Path, ledger: Path, names: dict, *, seam: str = "A",
           outcome_path: Path | None = None, real_cli: bool = False) -> SyRun:
    """SY.main() takes no argv: sys.argv is set for the call and restored. Seam A patches
    client_put/client_get; seam B installs the fake subprocess.run over the real retry/CLI layers."""
    argv = ["sync_sealed_snapshot_kv.py", "--run-dir", str(run_dir)]
    if outcome_path is not None:
        argv += ["--outcome-path", str(outcome_path)]
    before = dict(kv.store)
    log_mark, puts_mark = kv.mark()
    sleeps: list = []
    out, err = io.StringIO(), io.StringIO()
    code = None
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(sys, "argv", argv))
        stack.enter_context(mock.patch.object(sy, "LEDGER", ledger))
        stack.enter_context(mock.patch.object(sy.time, "sleep", sleeps.append))
        if seam == "A":
            stack.enter_context(mock.patch.object(sy, "client_put", kv.sy_put))
            stack.enter_context(mock.patch.object(sy, "client_get", kv.sy_get))
        else:
            stack.enter_context(mock.patch.object(subprocess, "run", kv.fake_run))
            if not real_cli:
                stack.enter_context(mock.patch.object(sy, "_cli_command", lambda: ["synthetic-cli"]))
        stack.enter_context(contextlib.redirect_stdout(out))
        stack.enter_context(contextlib.redirect_stderr(err))
        try:
            code = sy.main()
        except (Exception, SystemExit) as error:
            code = type(error).__name__
    record = parse_marker(out.getvalue(), "SYNC_OUTCOME")
    if record is None:
        outcome = "NO_OUTCOME"
        counters = None
    else:
        outcome = (record.get("status"), record.get("phase"), record.get("error_category"), record.get("pointer_state"))
        counters = (record.get("cli_attempts_total"), record.get("last_cli_attempts"), record.get("last_cli_exit_code"))
    ops = ops_of(kv, log_mark, names)
    diff = store_diff(before, kv.store, names)
    ledger_written = Path(ledger).exists()
    stage = (Path(run_dir) / ".kv-stage").exists()
    return SyRun(values=(code, outcome, ops, diff, ledger_written, stage), exit=code, outcome=outcome, ops=ops,
                 diff=diff, ledger=ledger_written, stage=stage, record=record, stdout=out.getvalue(),
                 stderr=err.getvalue(), sleeps=tuple(sleeps), counters=counters, kv=kv,
                 puts=tuple((names.get(key, key), ttl) for key, ttl in kv.puts[puts_mark:]),
                 argv_log=list(kv.argv_log))


# --------------------------------------------------------------- RB harness
RB_FIELDS = ("exit", "outcome", "ops", "diff", "ledger", "stage")


class RbRun:
    def __init__(self, **fields):
        self.__dict__.update(fields)


def run_rb(rb, kv: FakeKV, root: Path, tracked, argv: list, names: dict, *, seam: str = "A") -> RbRun:
    """RB.main(argv) over a plain tmp root whose tracked set is `tracked`. Seam A patches
    RB.wrangler_kv_get/put with FakeKV and installs the git-only subprocess fake; seam B leaves them real and
    installs the full fake subprocess.run (kv argv answered by FakeKV, `git ls-files` by the tracked set)."""
    before = dict(kv.store)
    log_mark, _ = kv.mark()
    kv.tracked = frozenset(tracked)
    git_mark = len(kv.git_calls)
    out, err = io.StringIO(), io.StringIO()
    code = None
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(rb, "ROOT", Path(root)))
        stack.enter_context(mock.patch.object(rb, "SNAP_DIR", Path(root) / "state" / "v213-snapshots"))
        if seam == "A":
            stack.enter_context(mock.patch.object(rb, "wrangler_kv_get", kv.rb_get))
            stack.enter_context(mock.patch.object(rb, "wrangler_kv_put", kv.rb_put))
            stack.enter_context(mock.patch.object(subprocess, "run", kv.git_run))
        else:
            stack.enter_context(mock.patch.object(subprocess, "run", kv.fake_run))
        stack.enter_context(contextlib.redirect_stdout(out))
        stack.enter_context(contextlib.redirect_stderr(err))
        try:
            code = rb.main(argv)
        except (Exception, SystemExit) as error:
            code = type(error).__name__
    document = None
    try:
        document = json.loads(out.getvalue())
    except ValueError:
        document = None
    if code == 0 and isinstance(document, dict):
        outcome = document.get("status")
    elif code == 1:
        outcome = "ABORT"
    else:
        outcome = "NO_OUTCOME"
    ops = ops_of(kv, log_mark, names)
    diff = store_diff(before, kv.store, names)
    return RbRun(row=Row(RB_FIELDS, (code, outcome, ops, diff, False, False)), exit=code, outcome=outcome, ops=ops,
                 diff=diff, document=document, stdout=out.getvalue(), stderr=err.getvalue(), kv=kv,
                 git_calls=list(kv.git_calls[git_mark:]))


# --------------------------------------------------------------- PB harness
PB_GLOBALS = ("LIVE_NOW", "LIVE_STAMP", "EVALUATED_AT", "GENERATED_AT", "CLAIMED_AT", "PROMOTED_AT", "PUBLISHED_DATA_AS_OF")


class PbRun:
    def __init__(self, **fields):
        self.__dict__.update(fields)


def run_pb(pb, snapshot_root: Path) -> PbRun:
    """PB.main always gets --snapshot-root <tmp>; exit code 0 if it returns, else the exception class name.
    The wall-clock globals PB rewrites under --live-clock are saved and restored around the call."""
    saved = {name: getattr(pb, name) for name in PB_GLOBALS}
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                pb.main(["--snapshot-root", str(snapshot_root)])
                code = 0
            except (Exception, SystemExit) as error:
                code = type(error).__name__
    finally:
        for name, value in saved.items():
            setattr(pb, name, value)
    try:
        summary = json.loads(out.getvalue())
    except ValueError:
        summary = None
    run_id = summary.get("run_id") if isinstance(summary, dict) else None
    run_dir = Path(snapshot_root) / run_id if isinstance(run_id, str) else None
    return PbRun(exit=code, summary=summary, run_id=run_id, run_dir=run_dir, stdout=out.getvalue(), stderr=err.getvalue())


class WriteBytesRecorder:
    """Wraps pathlib.Path.write_bytes; records (name, pointer.raw.json existed) for files written
    directly inside a run directory under the given snapshot root."""

    def __init__(self, snapshot_root: Path):
        self.root = Path(snapshot_root)
        self.records: list[tuple[str, bool]] = []
        self._original = pathlib.Path.write_bytes

    def __enter__(self):
        recorder = self

        def wrapper(path, data):
            if path.parent.parent == recorder.root:
                recorder.records.append((path.name, (path.parent / "pointer.raw.json").exists()))
            return recorder._original(path, data)

        self._patch = mock.patch.object(pathlib.Path, "write_bytes", wrapper)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        return False

    @property
    def names(self) -> tuple:
        return tuple(name for name, _ in self.records)

    def pointer_existed_at(self, name: str):
        for written, existed in self.records:
            if written == name:
                return existed
        return None
