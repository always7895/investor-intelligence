"""Finite synthetic refusal tests for the INERT launcher stub (Gate B REWORK).

The stub must refuse unconditionally from every entry point (Controller.run,
legacy _run_sequence, direct private calls, CLI main). These tests mock
process/socket/filesystem/time side effects and require ZERO calls, proving
the refusal happens before any side effect. No full implementation success is
asserted: the launcher remains an unaccepted draft (Gate B pending).
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
import v213_qa_capacity_launcher as L  # noqa: E402


def valid_handoff(tmpdir):
    return {
        "schema": L.SCHEMA,
        "checkpoint": "CHK-1",
        "origin_pi": {"pid": 7836, "created": "a" * 16, "image": "C:\\node.exe"},
        "bindings": {k: "b" * 64 for k in
                     ("source_sha", "harness_sha", "request_sha",
                      "run_plan_sha", "topology_sha")},
        "tabby": {"port": 5000, "listener": {"pid": 6432, "created": "1" * 16}},
        "nonce": "N-1",
        "canonical_root": str(tmpdir),
        "run_id": "run-1",
    }


def malformed_handoff(tmpdir):
    h = valid_handoff(tmpdir)
    h["schema"] = "wrong"
    h["bindings"]["source_sha"] = "zz"
    h["tabby"]["port"] = 8080
    h["origin_pi"] = "not-an-object"
    return h


ALL_TRUE_GATES = {g: True for g in ("A", "B", "C", "D", "E", "F", "G")}

MALICIOUS_ARGV = (
    ["powershell", "-Command", "Get-Process | Stop-Process"],
    ["python", "-c", "import os; os.system('del /s /q *')"],
    [],
    "not-a-list",
)


class SideEffectGuard:
    """Patch process/socket/filesystem/time side effects with mocks; verify
    ZERO calls. Original objects are restored on exit."""

    TARGETS = (
        ("subprocess", "Popen"), ("subprocess", "run"), ("subprocess", "call"),
        ("socket", "socket"), ("socket", "create_connection"),
        ("os", "open"), ("os", "mkdir"), ("os", "remove"), ("os", "unlink"),
        ("pathlib", "Path.mkdir"), ("pathlib", "Path.open"),
        ("pathlib", "Path.read_text"), ("pathlib", "Path.write_text"),
        ("time", "sleep"),
    )

    def __enter__(self):
        self._saved = []
        for mod_name, attr in self.TARGETS:
            mod = __import__(mod_name, fromlist=[attr])
            obj = mod
            for part in attr.split(".")[:-1]:
                obj = getattr(obj, part)
            leaf = attr.split(".")[-1]
            if not hasattr(obj, leaf):
                continue
            self._saved.append((obj, leaf, getattr(obj, leaf)))
            setattr(obj, leaf, mock.Mock(name=f"{mod_name}.{attr}"))
        return self

    def __exit__(self, *exc):
        for obj, leaf, orig in self._saved:
            setattr(obj, leaf, orig)

    def assert_zero_calls(self):
        for obj, leaf, _orig in self._saved:
            m = getattr(obj, leaf)
            if m.called:
                raise AssertionError(f"side effect {leaf} was called")


class TestControllerRefusal(unittest.TestCase):
    def _refuse(self, d, handoff, argv, seams=None):
        with SideEffectGuard() as g:
            ctrl = L.Controller(handoff, seams=seams)
            with self.assertRaises(L.DraftNotAcceptedError):
                ctrl.run(native_argv=argv)
            g.assert_zero_calls()

    def test_run_refuses_valid_handoff_all_true_gates(self):
        with tempfile.TemporaryDirectory() as d:
            seams = {"gates": ALL_TRUE_GATES,
                     "identity": lambda pid: "a" * 16,
                     "launch_native": lambda argv, job: None}
            self._refuse(d, valid_handoff(d), ["python", "runner.py"], seams)

    def test_run_refuses_malformed_handoff(self):
        with tempfile.TemporaryDirectory() as d:
            self._refuse(d, malformed_handoff(d), ["python", "runner.py"])

    def test_run_refuses_each_malicious_argv(self):
        with tempfile.TemporaryDirectory() as d:
            for argv in MALICIOUS_ARGV:
                with self.subTest(argv=argv):
                    self._refuse(d, valid_handoff(d), argv)

    def test_private_entries_refuse(self):
        with tempfile.TemporaryDirectory() as d:
            ctrl = L.Controller(valid_handoff(d))
            with SideEffectGuard() as g:
                for entry in (lambda: ctrl._run_sequence(native_argv=["x"]),
                              lambda: ctrl._attempt_sequence(native_argv=["x"]),
                              lambda: ctrl("x")):
                    with self.assertRaises(L.DraftNotAcceptedError):
                        entry()
                g.assert_zero_calls()


class TestCliRefusal(unittest.TestCase):
    def _call_main(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = L.main(argv)
        return rc, json.loads(buf.getvalue())

    def test_main_refuses_before_parsing_with_valid_handoff(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "handoff.json")
            p.write_text(json.dumps(valid_handoff(d)), encoding="utf-8")
            with SideEffectGuard() as g:
                rc, out = self._call_main(
                    ["--handoff", str(p),
                     "--native-argv", json.dumps(["python", "runner.py"])])
                g.assert_zero_calls()
            self.assertNotEqual(rc, 0)
            self.assertEqual(out["status"], "ABORT")
            self.assertEqual(out["native_attempt_established"], False)

    def test_main_refuses_without_args(self):
        rc, out = self._call_main([])
        self.assertNotEqual(rc, 0)
        self.assertEqual(out["status"], "ABORT")

    def test_main_refuses_malicious_argv(self):
        rc, out = self._call_main(
            ["--native-argv", json.dumps(MALICIOUS_ARGV[0])])
        self.assertNotEqual(rc, 0)
        self.assertEqual(out["status"], "ABORT")


class TestStubInertStructure(unittest.TestCase):
    def test_no_runner_or_unsafe_imports(self):
        import inspect
        src = inspect.getsource(L)
        for banned in ("import v213_qa_capacity", "import ctypes",
                       "import subprocess", "import socket", "ctypes.",
                       "Popen"):
            self.assertNotIn(banned, src)

    def test_no_mutable_acceptance_switch(self):
        import inspect
        src = inspect.getsource(L)
        self.assertNotIn("ACCEPTED =", src)
        self.assertFalse(hasattr(L, "_DRAFT_ACCEPTED"))

    def test_line_budget(self):
        import inspect
        self.assertLessEqual(len(inspect.getsource(L).splitlines()), 100)


class TestDeferredGateBCoverage(unittest.TestCase):
    """Explicit deferred coverage: Gate B NOT accepted; no success claimed."""

    def test_no_implementation_helpers_exist(self):
        for name in ("bind_origin", "reserve_namespace", "win_job_create",
                     "win_wait_terminate", "authorize_a_g", "terminal_conditions",
                     "win_launch_native_process", "win_relaunch_pi"):
            self.assertFalse(hasattr(L, name), f"unexpected helper {name}")

    def test_run_always_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            ctrl = L.Controller(valid_handoff(d))
            with self.assertRaises(L.DraftNotAcceptedError):
                ctrl.run(native_argv=["python", "runner.py"])


if __name__ == "__main__":
    unittest.main()