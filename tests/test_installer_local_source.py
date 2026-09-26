"""LOCAL_SOURCE_CHECKOUT installs (design T7): an honest local package bound to one commit's git blobs.

Each case builds a synthetic git repository from the tracked payload, exports one commit with
scripts/export_local_source_checkout.ps1 (-SkipToolchain; a synthetic launcher and wrangler.cmd stand in for the
allowed extras), and runs the real install coordinator with an isolated LOCALAPPDATA. Never touches the installed
application root."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
_harness_spec = importlib.util.spec_from_file_location("v213_installer_parse_harness", ROOT / "tests/installer_parse_harness.py")
harness = importlib.util.module_from_spec(_harness_spec)
_harness_spec.loader.exec_module(harness)
GIT = shutil.which("git")


def git(repo, *args):
    return subprocess.run([GIT, "-C", str(repo), "-c", "core.autocrlf=false", "-c", "user.name=fixture",
                           "-c", "user.email=fixture@example.invalid", *args],
                          check=True, capture_output=True, encoding="utf-8", errors="replace").stdout.strip()


@unittest.skipUnless(os.name == "nt" and GIT, "Windows installer contract with git")
class LocalSourceInstallTests(unittest.TestCase):
    def _repository(self, parent):
        repo = parent / "repo"
        repo.mkdir()
        tracked = subprocess.check_output([GIT, "-C", str(ROOT), "ls-files", "-z"]).decode().split("\0")
        for extra in ("scripts/v213_runtime_install_coordinator.ps1", "scripts/v213_runtime_restore_previous.ps1",
                      "scripts/export_local_source_checkout.ps1"):
            tracked.append(extra)
        for relative in tracked:
            if not relative or relative.startswith((".github/", "state/", "tests/")):
                continue
            path = ROOT / relative
            if path.suffix.lower() not in (".ps1", ".py", ".json", ".md") or not path.is_file():
                continue
            target = repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        git(repo, "init", "-q")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "fixture")
        return repo

    def _export(self, shell, repo, out):
        executable = dict(harness.required_hosts())[shell]
        result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                 str(repo / "scripts/export_local_source_checkout.ps1"), "-SourceRepository", str(repo),
                                 "-OutputRoot", str(out), "-SkipToolchain"],
                                capture_output=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (out / "InvestorIntelligence.exe").write_bytes(b"MZ_SYNTHETIC_NEVER_EXECUTED")
        wrangler = out / "cloud/node_modules/.bin/wrangler.cmd"
        wrangler.parent.mkdir(parents=True, exist_ok=True)
        wrangler.write_bytes(b"@ECHO off\r\nnode wrangler.js\r\n")
        return out

    def _coordinator(self, shell, parent, *args):
        executable = dict(harness.required_hosts())[shell]
        env = harness.isolated_environment(parent, executable)
        env["PATH"] = os.pathsep.join((env["PATH"], str(Path(GIT).parent)))
        return subprocess.run([executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                               str(ROOT / "scripts/v213_runtime_install_coordinator.ps1"), *args],
                              cwd=str(parent), env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=300)

    def _install(self, shell, parent, export, repo, runtime):
        return self._coordinator(shell, parent, "-ProjectRoot", str(export), "-RuntimeRoot", str(runtime),
                                 "-Profile", "SOURCE_DIVERSE", "-PackageOrigin", "LOCAL_SOURCE_CHECKOUT",
                                 "-SourceRepository", str(repo))

    def test_verified_export_installs_with_an_honest_identity(self):
        for shell, _ in harness.required_hosts():
            with self.subTest(shell=shell), harness.persistent_fixture("local-source-pass") as directory:
                parent = Path(directory)
                repo = self._repository(parent)
                export = self._export(shell, repo, parent / "export")
                result = self._install(shell, parent, export, repo, parent / "runtime")
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0, output)
                self.assertIn("package_origin=LOCAL_SOURCE_CHECKOUT", output)
                receipt = json.loads((parent / "local/InvestorIntelligence/v213-runtime-install-receipt.json").read_text(encoding="utf-8"))
                self.assertEqual(receipt["source_commit"], git(repo, "rev-parse", "HEAD"))
                self.assertEqual((receipt["package_origin"], receipt["workflow_run_id"], receipt["release_qualified"]),
                                 ("LOCAL_SOURCE_CHECKOUT", None, False))
                self.assertIn("install-v213-source-diverse-runtime-v2.ps1 -> install-v213-source-diverse-runtime.ps1", receipt["overlay_map"])
                state = json.loads((parent / "local/InvestorIntelligence/v213-runtime-state.json").read_text(encoding="utf-8"))
                self.assertEqual((state["package_origin"], state["release_qualified"]), ("LOCAL_SOURCE_CHECKOUT", False))

    def test_changed_extra_or_mislabelled_exports_are_refused(self):
        def one_byte(export):
            target = export / "scripts/publish_sealed_snapshot.py"
            target.write_bytes(target.read_bytes() + b" ")

        def identity(**change):
            def apply(export):
                path = export / "LOCAL-SOURCE-REFS.json"
                value = json.loads(path.read_text(encoding="utf-8"))
                value.update(change)
                path.write_text(json.dumps(value), encoding="utf-8")
            return apply

        cases = {
            "PACKAGE_SOURCE_TREE_MISMATCH:byte": one_byte,
            "PACKAGE_SOURCE_TREE_MISMATCH:venv": lambda e: (e / ".venv-ci").mkdir() or (e / ".venv-ci/pyvenv.cfg").write_text("x"),
            "PACKAGE_SOURCE_TREE_MISMATCH:toml": lambda e: (e / "cloud/wrangler.v213.production.local.toml").write_text("x"),
            "PACKAGE_SOURCE_TREE_MISMATCH:missing": lambda e: (e / "scripts/stage_sealed_replay.py").unlink(),
            "PACKAGE_IDENTITY_INVALID:run": identity(workflow_run_id="12345"),
            "PACKAGE_IDENTITY_INVALID:qualified": identity(release_qualified=True),
            "PACKAGE_IDENTITY_AMBIGUOUS:both": lambda e: (e / "HOTFIX-REFS.json").write_text("{}"),
            "RUNTIME_REQUIRED_FILE_MISSING:wrangler": lambda e: (e / "cloud/node_modules/.bin/wrangler.cmd").unlink(),
        }
        shell = harness.required_hosts()[0][0]
        for label, spoil in cases.items():
            expected = label.split(":")[0]
            with self.subTest(case=label), harness.persistent_fixture("local-source-refuse") as directory:
                parent = Path(directory)
                repo = self._repository(parent)
                export = self._export(shell, repo, parent / "export")
                spoil(export)
                result = self._install(shell, parent, export, repo, parent / "runtime")
                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, output)
                self.assertIn(expected, output)
                self.assertFalse((parent / "runtime").exists(), output)
                self.assertFalse((parent / "local/InvestorIntelligence/v213-runtime-install-receipt.json").exists())

    def test_reinstall_carries_live_data_without_overwriting_packaged_files_and_refuses_junctions(self):
        shell = harness.required_hosts()[0][0]
        with harness.persistent_fixture("local-source-data-carry") as directory:
            parent = Path(directory)
            runtime = parent / "runtime"
            repo = self._repository(parent)
            first = self._install(shell, parent, self._export(shell, repo, parent / "export-a"), repo, runtime)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            packaged = "data/bootstrap/v213-r15r-order-baseline.json"
            self.assertTrue((runtime / packaged).is_file())
            lkg = runtime / "data/cache/top20-lkg/20260926T000000Z-fixture.json"
            sealed = runtime / "data/v213-snapshots/20260926T000000Z-fixture/objects.json"
            for path, body in ((lkg, b"LKG"), (sealed, b"SEALED")):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            (runtime / packaged).write_bytes(b"STALE")
            outside = parent / "outside"
            outside.mkdir()
            (outside / "secret.txt").write_text("never carried", encoding="utf-8")
            subprocess.run(["cmd", "/c", "mklink", "/J", str(runtime / "data/cache/link"), str(outside)], check=True, capture_output=True)
            marker = repo / "docs/LOCAL_FIXTURE_SECOND_COMMIT.md"
            marker.parent.mkdir(exist_ok=True)
            marker.write_text("second commit\n", encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "second")
            export_b = self._export(shell, repo, parent / "export-b")
            refused = self._install(shell, parent, export_b, repo, runtime)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("RUNTIME_ROOT_TOPOLOGY_REPARSE_ENTRY", refused.stdout + refused.stderr)
            self.assertFalse((runtime / "docs/LOCAL_FIXTURE_SECOND_COMMIT.md").exists())
            os.rmdir(runtime / "data/cache/link")  # removes the junction itself, never its target
            self.assertTrue((outside / "secret.txt").is_file())
            second = self._install(shell, parent, export_b, repo, runtime)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertTrue((runtime / "docs/LOCAL_FIXTURE_SECOND_COMMIT.md").exists())
            self.assertEqual((runtime / "data/cache/top20-lkg/20260926T000000Z-fixture.json").read_bytes(), b"LKG")
            self.assertEqual((runtime / "data/v213-snapshots/20260926T000000Z-fixture/objects.json").read_bytes(), b"SEALED")
            self.assertEqual((runtime / packaged).read_bytes(), (repo / packaged).read_bytes())
            transaction = json.loads((parent / "local/InvestorIntelligence/v213-runtime-install.journal.json").read_text(encoding="utf-8"))["transaction_id"]
            old = parent / ("runtime.old." + transaction)
            self.assertEqual((old / "data/cache/top20-lkg/20260926T000000Z-fixture.json").read_bytes(), b"LKG")
            self.assertEqual((old / packaged).read_bytes(), b"STALE")

    def test_restore_previous_swaps_back_and_reattests(self):
        for shell, _ in harness.required_hosts():
            with self.subTest(shell=shell), harness.persistent_fixture("local-source-restore") as directory:
                parent = Path(directory)
                runtime = parent / "runtime"
                metadata = parent / "local/InvestorIntelligence"
                repo = self._repository(parent)
                first_commit = git(repo, "rev-parse", "HEAD")
                first = self._install(shell, parent, self._export(shell, repo, parent / "export-a"), repo, runtime)
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                marker = repo / "docs/LOCAL_FIXTURE_SECOND_COMMIT.md"
                marker.parent.mkdir(exist_ok=True)
                marker.write_text("second commit\n", encoding="utf-8")
                git(repo, "add", "-A")
                git(repo, "commit", "-q", "-m", "second")
                second = self._install(shell, parent, self._export(shell, repo, parent / "export-b"), repo, runtime)
                self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
                self.assertTrue((runtime / "docs/LOCAL_FIXTURE_SECOND_COMMIT.md").exists())
                transaction = json.loads((metadata / "v213-runtime-install.journal.json").read_text(encoding="utf-8"))["transaction_id"]
                wrong = self._coordinator(shell, parent, "-RuntimeRoot", str(runtime), "-RestorePrevious", "0" * 32)
                self.assertIn("RESTORE_NOT_LATEST_TRANSACTION", wrong.stdout + wrong.stderr)
                restored = self._coordinator(shell, parent, "-RuntimeRoot", str(runtime), "-RestorePrevious", transaction)
                output = restored.stdout + restored.stderr
                self.assertEqual(restored.returncode, 0, output)
                self.assertIn("V213_RUNTIME_RESTORE = PASS", output)
                self.assertFalse((runtime / "docs/LOCAL_FIXTURE_SECOND_COMMIT.md").exists())
                self.assertTrue((parent / ("runtime.replaced." + transaction)).is_dir())
                receipt = json.loads((metadata / "v213-runtime-install-receipt.json").read_text(encoding="utf-8"))
                self.assertEqual(receipt["source_commit"], first_commit)
                journal = json.loads((metadata / "v213-runtime-install.journal.json").read_text(encoding="utf-8"))
                self.assertEqual(journal["state"], "RESTORED_PREVIOUS")
                again = self._install(shell, parent, parent / "export-b", repo, runtime)
                self.assertEqual(again.returncode, 0, again.stdout + again.stderr)


if __name__ == "__main__":
    unittest.main()
