"""The Production verification tools run only the locked local Node CLIs of cloud/ (Fable 5.1 SC-1, 2026-10-12).

scripts/deploy_production_gate.ps1 ran its live KV read and its reader replay through `npx --yes` from the caller's
directory, so a missing local install downloaded the latest registry package and ran it with the cached Production
session; scripts/fetch_live_public_snapshot.py and scripts/stage_sealed_replay.py used the same form. Each row drives the
real resolver or caller over a synthetic cloud/ layout. No network, no Node process, no Production.

The gate also names no Worker origin (Fable 5.1 h-privacy-1): its workers.dev label is the operator's Cloudflare account,
so -Phase post resolves the origin from -WorkerUrl or the local Worker configuration (WorkerOriginTests).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_live_public_snapshot as live  # noqa: E402
import stage_sealed_replay as replay  # noqa: E402
import sync_sealed_snapshot_kv as sync  # noqa: E402

GATE_PATH = ROOT / "scripts" / "deploy_production_gate.ps1"
GATE = GATE_PATH.read_text(encoding="utf-8")
TOOLS = [GATE_PATH, ROOT / "scripts" / "fetch_live_public_snapshot.py", ROOT / "scripts" / "stage_sealed_replay.py"]


def code_lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")]


def layout(root: Path, package: str, entry: str, declared: str = "1.2.3", locked: str | None = "1.2.3",
           installed: str = "1.2.3", cli: bool = True) -> tuple[Path, Path]:
    """A synthetic cloud/ with one devDependency, its lock entry and installed package; returns (cloud, node).

    The lock has the npm lockfile v3 shape: the root package sits under the empty key "" of `packages`, which
    ConvertFrom-Json refuses in both PowerShell hosts (the gate failed on the real lock with LOCKED_CLI_UNAVAILABLE)."""
    cloud = root / "cloud"
    package_dir = cloud / "node_modules" / package
    package_dir.mkdir(parents=True)
    (cloud / "package.json").write_text(json.dumps({"devDependencies": {package: declared}}), encoding="utf-8")
    packages = {"": {"name": "synthetic", "devDependencies": {package: declared}}}
    if locked is not None:
        packages[f"node_modules/{package}"] = {"version": locked}
    lock = {"name": "synthetic", "lockfileVersion": 3, "requires": True, "packages": packages}
    (cloud / "package-lock.json").write_text(json.dumps(lock, indent=2), encoding="utf-8")
    (package_dir / "package.json").write_text(json.dumps({"version": installed}), encoding="utf-8")
    if cli:
        (package_dir / entry).parent.mkdir(parents=True, exist_ok=True)
        (package_dir / entry).write_text("// synthetic\n", encoding="utf-8")
    node = root / "node.exe"
    node.write_bytes(b"synthetic, never executed")
    return cloud, node


def no_process(*args, **kwargs):
    raise AssertionError("guard: no process may start")


MISMATCHES = {
    "declared_differs": {"declared": "1.2.4"},
    "installed_differs": {"installed": "1.2.2"},
    "lock_entry_missing": {"locked": None},
    "cli_missing": {"cli": False},
}


class NoRegistryFetchTests(unittest.TestCase):
    def test_no_tool_invokes_npx(self):
        for path in TOOLS:
            self.assertEqual([line for line in code_lines(path) if "npx" in line or "--yes" in line], [], path.name)

    def test_the_gate_resolves_both_clis_before_any_production_read(self):
        resolve = GATE.index("$node, $wrangler = Get-LockedNodeCli 'wrangler' 'bin/wrangler.js'")
        self.assertLess(resolve, GATE.index("function Read-LivePointer"))
        self.assertIn("(Get-LockedNodeCli 'vitest' 'vitest.mjs')[1]", GATE[resolve:GATE.index("function Read-LivePointer")])
        self.assertEqual(len(re.findall(r"& \$node \$wrangler kv key get [^\n]*--remote", GATE)), 1)
        self.assertEqual(len(re.findall(r"& \$node \$vitest run test/live-kv-replay\.test\.ts", GATE)), 1)


class StageVitestTests(unittest.TestCase):
    def resolve(self, **variant):
        with tempfile.TemporaryDirectory() as tmp:
            cloud, node = layout(Path(tmp), "vitest", "vitest.mjs", **variant)
            with mock.patch.object(replay, "CLOUD", cloud), \
                    mock.patch.dict(os.environ, {"PROJECT_NODE": str(node), "NODE_FOR_RUNNER": ""}):
                return replay._vitest_command(), cloud, node

    def test_matching_install_gives_node_and_the_installed_cli(self):
        command, cloud, node = self.resolve()
        self.assertEqual(command, [str(node.resolve()), str(cloud / "node_modules" / "vitest" / "vitest.mjs")])

    def test_every_mismatch_or_missing_part_refuses(self):
        for name, variant in MISMATCHES.items():
            with self.subTest(name), self.assertRaises(replay.LockedCliUnavailable):
                self.resolve(**variant)

    def test_missing_node_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            cloud, node = layout(Path(tmp), "vitest", "vitest.mjs")
            with mock.patch.object(replay, "CLOUD", cloud), mock.patch.object(replay.shutil, "which", return_value=None), \
                    mock.patch.dict(os.environ, {"PROJECT_NODE": str(node) + ".missing", "NODE_FOR_RUNNER": ""}), \
                    self.assertRaises(replay.LockedCliUnavailable):
                replay._vitest_command()

    def test_runner_starts_only_the_locked_cli(self):
        calls = []
        done = subprocess.CompletedProcess([], 0, b"", b"")
        with mock.patch.object(replay, "_vitest_command", return_value=["NODE", "LOCKED_VITEST_MJS"]), \
                mock.patch.object(replay.subprocess, "run", side_effect=lambda args, **kw: calls.append((args, kw)) or done):
            self.assertEqual(replay.vitest_runner(Path("kv"), Path("result.json")), 0)
        self.assertEqual(calls[0][0], ["NODE", "LOCKED_VITEST_MJS", "run", "test/live-kv-replay.test.ts"])
        self.assertEqual(calls[0][1]["cwd"], str(replay.CLOUD))

    def test_unavailable_cli_is_a_stage_error_and_starts_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "summary.json").write_text(json.dumps({"top20_state": None}), encoding="utf-8")
            out = io.StringIO()
            with mock.patch.object(replay, "stage", return_value="RUN"), \
                    mock.patch.object(replay, "_vitest_command", side_effect=replay.LockedCliUnavailable()), \
                    mock.patch.object(replay.subprocess, "run", side_effect=no_process), contextlib.redirect_stdout(out):
                self.assertEqual(replay.main(["--run-dir", str(run_dir)]), 1)
        self.assertEqual(json.loads(out.getvalue()), {"status": "FAIL", "failed": ["STAGE_ERROR"], "error": "LockedCliUnavailable"})


class FetchWranglerTests(unittest.TestCase):
    def test_the_fetch_uses_the_sync_rule_for_a_matching_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            cloud, node = layout(Path(tmp), "wrangler", "bin/wrangler.js")
            with mock.patch.object(sync, "CLOUD_DIR", cloud), \
                    mock.patch.dict(os.environ, {"PROJECT_NODE": str(node), "NODE_FOR_RUNNER": ""}):
                self.assertEqual(live.sync._cli_command(),
                                 [str(node.resolve()), str(cloud / "node_modules" / "wrangler" / "bin" / "wrangler.js")])
                with mock.patch.object(live.subprocess, "run", side_effect=lambda args, **kw: subprocess.CompletedProcess(
                        args, 0, b"{}", b"")) as run:
                    live.remote_getter()("snapshot:current")
                self.assertEqual(run.call_args.args[0][:2], live.sync._cli_command())

    def test_mismatched_install_refuses_before_any_read(self):
        for name, variant in MISMATCHES.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                cloud, node = layout(Path(tmp), "wrangler", "bin/wrangler.js", **variant)
                with mock.patch.object(sync, "CLOUD_DIR", cloud), \
                        mock.patch.dict(os.environ, {"PROJECT_NODE": str(node), "NODE_FOR_RUNNER": ""}), \
                        mock.patch.object(live.subprocess, "run", side_effect=no_process), \
                        self.assertRaises(sync.CliUnavailable):
                    live.remote_getter()

    def test_main_reports_the_refusal_without_a_read(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(live.sync, "_cli_command", side_effect=sync.CliUnavailable()), \
                mock.patch.object(live.subprocess, "run", side_effect=no_process), \
                mock.patch.object(sys, "argv", ["fetch_live_public_snapshot.py", "--out", str(Path(tmp) / "out")]), \
                contextlib.redirect_stdout(out):
            self.assertEqual(live.main(), 1)
        self.assertEqual(json.loads(out.getvalue()), {"status": "FAIL", "error": "LOCKED_CLI_UNAVAILABLE wrangler"})


class GateResolverTests(unittest.TestCase):
    """Get-LockedNodeCli from the gate itself, in Windows PowerShell 5.1 and PowerShell 7 under strict mode."""

    # The script is passed as the -Command argument: `-Command -` reads stdin line by line and silently drops a multi-line
    # function definition at end of input (empty output, exit 0).

    FUNCTION = re.search(r"function Get-LockedNodeCli.*?\n}\n", GATE, re.S).group(0)

    def run_resolver(self, shell: str, cloud: Path, node: Path, package: str, entry: str) -> subprocess.CompletedProcess:
        script = ("$ErrorActionPreference = 'Stop'\nSet-StrictMode -Version Latest\n"
                  f"$CloudDir = '{cloud}'\n$env:PROJECT_NODE = '{node}'\n$env:NODE_FOR_RUNNER = ''\n" + self.FUNCTION +
                  f"try {{ $r = Get-LockedNodeCli '{package}' '{entry}'; 'OK'; $r[0]; $r[1] }} catch {{ 'ERR ' + $_.Exception.Message }}\n")
        return subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=120)

    def test_resolver_in_both_hosts(self):
        shells = [s for s in ("powershell", "pwsh") if shutil.which(s)]
        if not shells:
            self.skipTest("PowerShell not available")
        for shell in shells:
            for package, entry in (("wrangler", "bin/wrangler.js"), ("vitest", "vitest.mjs")):
                with self.subTest(shell=shell, package=package), tempfile.TemporaryDirectory() as tmp:
                    cloud, node = layout(Path(tmp), package, entry)
                    lines = self.run_resolver(shell, cloud, node, package, entry).stdout.strip().splitlines()
                    self.assertEqual(lines[0], "OK", lines)
                    self.assertEqual(os.path.normcase(lines[1]), os.path.normcase(str(node)))
                    self.assertEqual(Path(lines[2]).resolve(), (cloud / "node_modules" / package / entry).resolve())
            for name, variant in MISMATCHES.items():
                with self.subTest(shell=shell, case=name), tempfile.TemporaryDirectory() as tmp:
                    cloud, node = layout(Path(tmp), "wrangler", "bin/wrangler.js", **variant)
                    out = self.run_resolver(shell, cloud, node, "wrangler", "bin/wrangler.js").stdout.strip()
                    self.assertEqual(out, "ERR LOCKED_CLI_UNAVAILABLE wrangler")
            with self.subTest(shell=shell, case="node_missing"), tempfile.TemporaryDirectory() as tmp:
                cloud, node = layout(Path(tmp), "wrangler", "bin/wrangler.js")
                node.unlink()
                # A named PROJECT_NODE that does not exist refuses; it never falls back to a node on PATH.
                out = self.run_resolver(shell, cloud, node, "wrangler", "bin/wrangler.js").stdout.strip()
                self.assertEqual(out, "ERR LOCKED_CLI_UNAVAILABLE wrangler")

    def test_resolver_reads_the_repository_lock(self):
        """The real cloud/package.json and package-lock.json, with an installed package of the locked version."""
        shells = [s for s in ("powershell", "pwsh") if shutil.which(s)]
        if not shells:
            self.skipTest("PowerShell not available")
        manifest = (ROOT / "cloud" / "package.json").read_bytes()
        lock_bytes = (ROOT / "cloud" / "package-lock.json").read_bytes()
        lock = json.loads(lock_bytes)
        self.assertIn("", lock["packages"])  # the shape that broke ConvertFrom-Json
        for shell in shells:
            for package, entry in (("wrangler", "bin/wrangler.js"), ("vitest", "vitest.mjs")):
                with self.subTest(shell=shell, package=package), tempfile.TemporaryDirectory() as tmp:
                    cloud, node = layout(Path(tmp), package, entry, installed=lock["packages"][f"node_modules/{package}"]["version"])
                    (cloud / "package.json").write_bytes(manifest)
                    (cloud / "package-lock.json").write_bytes(lock_bytes)
                    lines = self.run_resolver(shell, cloud, node, package, entry).stdout.strip().splitlines()
                    self.assertEqual(lines[0], "OK", lines)
                    self.assertEqual(Path(lines[2]).resolve(), (cloud / "node_modules" / package / entry).resolve())



class WorkerOriginTests(unittest.TestCase):
    """Resolve-WorkerOrigin from the gate itself, in Windows PowerShell 5.1 and PowerShell 7 under strict mode."""

    FUNCTION = re.search(r"function Resolve-WorkerOrigin.*?\n}\n", GATE, re.S).group(0)
    HOST = ".".join(["ii-owner-line", "synthetic", "workers", "dev"])
    ORIGIN = "https://" + HOST

    def test_the_gate_names_no_worker_origin(self):
        self.assertIn("\n    [string]$WorkerUrl = '',\n    [string]$WorkerConfigPath = '',\n", GATE)
        self.assertEqual(re.findall(r"[A-Za-z0-9-]+\.[A-Za-z0-9-]+\.workers\.dev", GATE), [])

    def test_post_resolves_the_origin_before_any_read(self):
        call = "if ($Phase -eq 'post') { $WorkerUrl = Resolve-WorkerOrigin $WorkerUrl $WorkerConfigPath }"
        self.assertEqual(GATE.count(call), 1)
        self.assertLess(GATE.index(call), GATE.index("function Read-LivePointer"))
        self.assertLess(GATE.index(call), GATE.index("$readinessUrl = "))

    def run_origin(self, shell: str, explicit: str, config: str, localappdata: str) -> str:
        script = ("$ErrorActionPreference = 'Stop'\nSet-StrictMode -Version Latest\n"
                  f"$env:LOCALAPPDATA = '{localappdata}'\n" + self.FUNCTION +
                  f"try {{ 'OK ' + (Resolve-WorkerOrigin '{explicit}' '{config}') }} catch {{ 'ERR ' + $_.Exception.Message }}\n")
        return subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=120).stdout.strip()

    def test_origin_rule_in_both_hosts(self):
        shells = [s for s in ("powershell", "pwsh") if shutil.which(s)]
        if not shells:
            self.skipTest("PowerShell not available")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default = root / "InvestorIntelligence" / "UserData" / "config" / "v21-owner-line.local.json"
            default.parent.mkdir(parents=True)
            default.write_text(json.dumps({"public_snapshot_endpoint": self.ORIGIN + "/v21/admin/public-snapshot"}), encoding="utf-8")
            configs = {}
            for name, body in (("no_property", json.dumps({"encrypted_hmac": "SYNTHETIC_NOT_READ"})), ("not_json", "{"),
                               ("empty", ""), ("http", json.dumps({"public_snapshot_endpoint": "http://" + self.HOST})),
                               ("relative", json.dumps({"public_snapshot_endpoint": "v21/admin/public-snapshot"}))):
                configs[name] = root / f"{name}.json"
                configs[name].write_text(body, encoding="utf-8")
            cases = [
                ("explicit", self.ORIGIN + "/v213/readiness?x=1", "", "OK " + self.ORIGIN),
                ("explicit_wins", self.ORIGIN, str(configs["not_json"]), "OK " + self.ORIGIN),
                ("default_config", "", "", "OK " + self.ORIGIN),
                ("named_config", "", str(default), "OK " + self.ORIGIN),
                ("missing_config", "", str(root / "absent.json"), "ERR WORKER_URL_UNAVAILABLE"),
                ("no_property", "", str(configs["no_property"]), "ERR WORKER_URL_UNAVAILABLE"),
                ("not_json", "", str(configs["not_json"]), "ERR WORKER_URL_UNAVAILABLE"),
                ("empty", "", str(configs["empty"]), "ERR WORKER_URL_UNAVAILABLE"),
                ("config_http", "", str(configs["http"]), "ERR WORKER_URL_INVALID"),
                ("config_relative", "", str(configs["relative"]), "ERR WORKER_URL_INVALID"),
                ("http", "http://" + self.HOST, "", "ERR WORKER_URL_INVALID"),
                ("other_host", "https://" + ".".join(["ii", "example", "invalid"]), "", "ERR WORKER_URL_INVALID"),
                ("suffix_host", "https://" + self.HOST + ".example.invalid", "", "ERR WORKER_URL_INVALID"),
                ("port", self.ORIGIN + ":8443", "", "ERR WORKER_URL_INVALID"),
                ("user_info", "https://" + "user" + "@" + self.HOST, "", "ERR WORKER_URL_INVALID"),
            ]
            for shell in shells:
                for name, explicit, config, expected in cases:
                    with self.subTest(shell=shell, case=name):
                        self.assertEqual(self.run_origin(shell, explicit, config, str(root)), expected)
                with self.subTest(shell=shell, case="no_localappdata"):
                    self.assertEqual(self.run_origin(shell, "", "", ""), "ERR WORKER_URL_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
