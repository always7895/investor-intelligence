"""Isolated installer topology tests; never use the installed application root."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows installer boundary contract")
class InstallerBoundaryTests(unittest.TestCase):
    def _write_minimal_source(self, source):
        source.mkdir()
        shutil.copyfile(ROOT / "install-v213-runtime.ps1", source / "install-v213-runtime.ps1")
        (source / "HOTFIX-REFS.json").write_text(
            '{"artifact_kind":"R75_FREE_WORKERS_RELAY_HOTFIX","package_version":"2.1.3",'
            '"source_commit":"' + "a" * 40 + '","workflow_run_id":"12345",'
            '"production_mutation_by_ci":false}\n', encoding="utf-8")

    def _run_minimal_installer(self, shell, source, runtime, local):
        env = {k: v for k, v in os.environ.items() if k.casefold() != "psmodulepath"}
        env["LOCALAPPDATA"] = str(local)
        return subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
             str(source / "install-v213-runtime.ps1"), "-ProjectRoot", str(source), "-RuntimeRoot", str(runtime)],
            env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        )

    def test_mir_refuses_existing_runtime_data_before_copy(self):
        """A pre-existing runtime sentinel must survive a rejected/unsafe copy."""
        for shell in ("powershell.exe", "pwsh.exe"):
            if not shutil.which(shell):
                continue
            with self.subTest(shell=shell), tempfile.TemporaryDirectory(prefix="installer-boundary ") as directory:
                parent = Path(directory)
                source = parent / "source"
                runtime = parent / "runtime"
                local = parent / "local"
                self._write_minimal_source(source)
                runtime.mkdir()
                sentinel = runtime / "UNIQUE_OPERATOR_DATA.sentinel"
                sentinel.write_bytes(b"MUST_SURVIVE_REJECTED_INSTALL")
                result = self._run_minimal_installer(shell, source, runtime, local)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(sentinel.exists(), result.stdout + result.stderr)
                self.assertIn("RUNTIME_TOPOLOGY", result.stdout + result.stderr)

    def test_refuses_source_destination_overlap_before_any_directory_creation(self):
        for shell in ("powershell.exe", "pwsh.exe"):
            if not shutil.which(shell):
                continue
            for case in ("destination_below_source", "source_below_destination", "same_path", "same_path_short_alias"):
                with self.subTest(shell=shell, case=case), tempfile.TemporaryDirectory(prefix="installer-overlap ") as directory:
                    parent = Path(directory)
                    source = parent / "source"
                    self._write_minimal_source(source)
                    if case == "destination_below_source":
                        runtime = source / "runtime"
                    elif case == "source_below_destination":
                        runtime = parent
                    elif case == "same_path_short_alias":
                        import ctypes
                        buffer = ctypes.create_unicode_buffer(32768)
                        length = ctypes.windll.kernel32.GetShortPathNameW(str(source), buffer, len(buffer))
                        self.assertGreater(length, 0)
                        short = buffer.value
                        self.assertNotEqual(short.casefold(), str(source).casefold())
                        runtime = Path(short)
                    else:
                        runtime = source
                    local = parent / "local"
                    sentinel = parent / "OVERLAP_SENTINEL"
                    sentinel.write_bytes(b"MUST_SURVIVE_OVERLAP_REJECT")
                    result = self._run_minimal_installer(shell, source, runtime, local)
                    output = result.stdout + result.stderr
                    self.assertNotEqual(result.returncode, 0, output)
                    self.assertIn("RUNTIME_TOPOLOGY_SOURCE_DESTINATION_OVERLAP", output)
                    self.assertEqual(sentinel.read_bytes(), b"MUST_SURVIVE_OVERLAP_REJECT")

    def test_refuses_reparse_in_source_before_creating_runtime(self):
        for shell in ("powershell.exe", "pwsh.exe"):
            if not shutil.which(shell):
                continue
            with self.subTest(shell=shell), tempfile.TemporaryDirectory(prefix="installer-source-reparse ") as directory:
                parent = Path(directory)
                source = parent / "source"
                runtime = parent / "runtime"
                outside = parent / "outside"
                self._write_minimal_source(source)
                outside.mkdir()
                outside_sentinel = outside / "SOURCE_OUTSIDE_SENTINEL"
                outside_sentinel.write_bytes(b"MUST_NOT_BE_TOUCHED")
                junction = source / "linked"
                link = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside)],
                                      capture_output=True, encoding="utf-8", errors="replace", timeout=15)
                self.assertEqual(link.returncode, 0, link.stdout + link.stderr)
                try:
                    result = self._run_minimal_installer(shell, source, runtime, parent / "local")
                    output = result.stdout + result.stderr
                    self.assertNotEqual(result.returncode, 0, output)
                    self.assertIn("PROJECT_ROOT_TOPOLOGY_REPARSE_ENTRY", output)
                    self.assertFalse(runtime.exists())
                    self.assertEqual(outside_sentinel.read_bytes(), b"MUST_NOT_BE_TOUCHED")
                finally:
                    subprocess.run(["cmd.exe", "/c", "rmdir", str(junction)], capture_output=True, timeout=15)

    def _write_full_package_source(self, source):
        source.mkdir()
        tracked = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z"]).decode().split("\0")
        for relative in tracked:
            if not relative or relative.startswith((".github/", "state/", "tests/")):
                continue
            path = ROOT / relative
            if path.suffix.lower() not in (".ps1", ".py", ".json", ".md"):
                continue
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        (source / "InvestorIntelligence.exe").write_bytes(b"MZ_SYNTHETIC_NEVER_EXECUTED")
        (source / "HOTFIX-REFS.json").write_text(
            '{"artifact_kind":"R75_FREE_WORKERS_RELAY_HOTFIX","package_version":"2.1.3",'
            '"source_commit":"' + "a" * 40 + '","workflow_run_id":"12345",'
            '"production_mutation_by_ci":false}\n', encoding="utf-8")

    def test_existing_owned_runtime_supports_reinstall_and_rejects_unknown_data(self):
        for shell in ("powershell.exe", "pwsh.exe"):
            if not shutil.which(shell):
                continue
            with self.subTest(shell=shell), tempfile.TemporaryDirectory(prefix="installer-upgrade ") as directory:
                parent = Path(directory)
                source = parent / "source"
                runtime = parent / "runtime"
                self._write_full_package_source(source)
                first = self._run_minimal_installer(shell, source, runtime, parent / "local")
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                self.assertTrue((runtime / "run-v213-local.ps1").exists())
                second = self._run_minimal_installer(shell, source, runtime, parent / "local")
                self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
                unknown = runtime / "UNOWNED_UPGRADE_DATA.sentinel"
                unknown.write_bytes(b"MUST_SURVIVE_REJECT")
                rejected = self._run_minimal_installer(shell, source, runtime, parent / "local")
                self.assertNotEqual(rejected.returncode, 0, rejected.stdout + rejected.stderr)
                self.assertIn("RUNTIME_TOPOLOGY_UNOWNED_DATA", rejected.stdout + rejected.stderr)
                self.assertEqual(unknown.read_bytes(), b"MUST_SURVIVE_REJECT")

    def test_refuses_reparse_entry_before_mir_and_preserves_target(self):
        for shell in ("powershell.exe", "pwsh.exe"):
            if not shutil.which(shell):
                continue
            with self.subTest(shell=shell), tempfile.TemporaryDirectory(prefix="installer-reparse ") as directory:
                parent = Path(directory)
                source = parent / "source"
                runtime = parent / "runtime"
                outside = parent / "outside"
                self._write_minimal_source(source)
                runtime.mkdir(); outside.mkdir()
                sentinel = outside / "OUTSIDE_SENTINEL"
                sentinel.write_bytes(b"MUST_NOT_BE_TOUCHED")
                junction = runtime / "linked"
                link = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside)],
                                      capture_output=True, encoding="utf-8", errors="replace", timeout=15)
                self.assertEqual(link.returncode, 0, link.stdout + link.stderr)
                try:
                    result = self._run_minimal_installer(shell, source, runtime, parent / "local")
                    output = result.stdout + result.stderr
                    self.assertNotEqual(result.returncode, 0, output)
                    self.assertIn("RUNTIME_ROOT_TOPOLOGY_REPARSE_ENTRY", output)
                    self.assertTrue(junction.exists())
                    self.assertEqual(sentinel.read_bytes(), b"MUST_NOT_BE_TOUCHED")
                finally:
                    subprocess.run(["cmd.exe", "/c", "rmdir", str(junction)], capture_output=True, timeout=15)


if __name__ == "__main__": unittest.main()
