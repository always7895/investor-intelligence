"""Behavioral quiescence checks against isolated coordinator inputs and mutexes."""
import ctypes
import importlib.util
import os
from pathlib import Path
import subprocess
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("v213_installer_parse_harness", ROOT / "tests/installer_parse_harness.py")
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)

TASKS = (
    "InvestorDailyBriefing",
    "InvestorIntelligence-TaifexOptionsEod",
    "InvestorIntelligence-v213-FreeRelay",
    "InvestorIntelligenceFreshnessWatchdog",
    "InvestorIntelligenceSealedFreshness",
)

# Invoke through -Command so the provider is a real scriptblock, not a string
# passed through -File. The second process probes the mutex while this process
# is still alive, so process termination cannot hide a leaked mutex.
DRIVER = r"""
$ErrorActionPreference = 'Stop'
$provider = {
    if ($env:Q_MODE -eq 'query_error') { throw 'SYNTHETIC_QUERY_ERROR' }
    if ($env:Q_MODE -eq 'running') {
        [pscustomobject]@{TaskName=$env:Q_TASK; State='Running'}
    } elseif ($env:Q_MODE -eq 'unknown') {
        [pscustomobject]@{TaskName=$env:Q_TASK; State='Unknown'}
    } else {
        [pscustomobject]@{TaskName='UnrelatedSyntheticTask'; State='Running'}
        [pscustomobject]@{TaskName='InvestorDailyBriefing'; State='Ready'}
    }
}
$params = @{
    RuntimeRoot=$env:Q_RUNTIME; ProjectRoot=$env:Q_SOURCE; Profile='BASE'
    TaskStateProvider=$provider; OperationMutexName=$env:Q_MUTEX
}
if ($env:Q_RESTORE -eq '1') { $params.RestorePrevious = '0123456789abcdef0123456789abcdef' }
try {
    & $env:Q_COORDINATOR @params
    Write-Output 'RESULT=UNEXPECTED_SUCCESS'
} catch {
    Write-Output ('RESULT=' + $_.Exception.Message)
}
if ($env:Q_MODE -ne 'held') {
    $probe = '$m = New-Object System.Threading.Mutex($false, $env:Q_MUTEX); try { if (-not $m.WaitOne(0)) { exit 7 }; $m.ReleaseMutex(); exit 0 } finally { $m.Dispose() }'
    & $env:Q_HOST -NoProfile -NonInteractive -Command $probe
    Write-Output ('MUTEX_PROBE=' + $LASTEXITCODE)
}
"""


def snapshot(path):
    if not path.exists():
        return None
    return {p.relative_to(path).as_posix(): (None if p.is_dir() else p.read_bytes())
            for p in path.rglob("*")}


@unittest.skipUnless(os.name == "nt", "Windows coordinator quiescence contract")
class InstallerQuiescenceTests(unittest.TestCase):
    def run_case(self, executable, mode, restore=False, task=TASKS[0], expected=None):
        case = harness.new_case("coordinator-quiescence")
        env = harness.isolated_environment(case, executable)
        source = case / "source"
        source.mkdir()
        (source / "sentinel").write_bytes(b"source stays unchanged")
        runtime = case / "runtime"
        runtime.mkdir()
        (runtime / "sentinel").write_bytes(b"runtime stays unchanged")
        old = case / "runtime.old.0123456789abcdef0123456789abcdef"
        old.mkdir()
        (old / "sentinel").write_bytes(b"backup stays unchanged")
        metadata = Path(env["LOCALAPPDATA"]) / "InvestorIntelligence"
        metadata.mkdir(parents=True)
        for name in ("v213-runtime-install.journal.json", "v213-runtime-install-receipt.json",
                     "v213-runtime-state.json", "v213-previous-0123456789abcdef0123456789abcdef.json"):
            (metadata / name).write_bytes(("unchanged " + name).encode())
        before = [snapshot(p) for p in (source, runtime, old, metadata)]
        runtime_entries = {p.name for p in case.glob("runtime*")}
        mutex = "Local\\II_quiescence_test_" + uuid.uuid4().hex
        env.update(Q_COORDINATOR=str(ROOT / "scripts/v213_runtime_install_coordinator.ps1"),
                   Q_SOURCE=str(source), Q_RUNTIME=str(runtime), Q_MUTEX=mutex,
                   Q_HOST=executable, Q_MODE=mode, Q_TASK=task,
                   Q_RESTORE="1" if restore else "0")

        handle = None
        if mode == "held":
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
            kernel.CreateMutexW.restype = ctypes.c_void_p
            kernel.ReleaseMutex.argtypes = (ctypes.c_void_p,)
            kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
            handle = kernel.CreateMutexW(None, True, mutex)
            self.assertTrue(handle)
            self.assertNotEqual(ctypes.get_last_error(), 183, "synthetic mutex unexpectedly existed")
        try:
            result = subprocess.run(
                [executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", DRIVER],
                cwd=case, env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
            )
        finally:
            if handle:
                kernel.ReleaseMutex(handle)
                kernel.CloseHandle(handle)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("RESULT=" + expected, output)
        self.assertNotIn("RESULT=UNEXPECTED_SUCCESS", output)
        if mode != "held":
            self.assertIn("MUTEX_PROBE=0", output)
        self.assertEqual([snapshot(p) for p in (source, runtime, old, metadata)], before)
        self.assertEqual({p.name for p in case.glob("runtime*")}, runtime_entries)
        self.assertFalse((Path(env["TEMP"]) / "InvestorIntelligence-v213-runtime-install.lock").exists())

    def test_running_tasks_refuse_install_and_restore(self):
        for host, executable in harness.required_hosts():
            for restore in (False, True):
                for task in TASKS:
                    with self.subTest(host=host, restore=restore, task=task):
                        self.run_case(executable, "running", restore, task, "RUNTIME_TASK_RUNNING")

    def test_query_failure_and_unknown_state_refuse_install_and_restore(self):
        for host, executable in harness.required_hosts():
            for restore in (False, True):
                for mode, expected in (("query_error", "RUNTIME_TASK_QUERY_FAILED"),
                                       ("unknown", "RUNTIME_TASK_STATE_UNKNOWN")):
                    with self.subTest(host=host, restore=restore, mode=mode):
                        self.run_case(executable, mode, restore, expected=expected)

    def test_held_operation_mutex_refuses_install_and_restore(self):
        for host, executable in harness.required_hosts():
            for restore in (False, True):
                with self.subTest(host=host, restore=restore):
                    self.run_case(executable, "held", restore, expected="V213_OPERATION_LOCK_BUSY")

    def test_mutex_released_after_later_install_failure(self):
        # An unrelated running task and a Ready tracked task must pass the guard.
        # The deliberately incomplete source then fails before any mutation.
        for host, executable in harness.required_hosts():
            with self.subTest(host=host):
                self.run_case(executable, "ready", expected="PACKAGE_IDENTITY_MISSING")
