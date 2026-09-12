"""Isolated installer topology tests; never use the installed application root."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
# The pinned embedded Python does not necessarily include the script directory.
_harness_spec = importlib.util.spec_from_file_location("v213_installer_parse_harness", ROOT / "tests/installer_parse_harness.py")
harness = importlib.util.module_from_spec(_harness_spec)
_harness_spec.loader.exec_module(harness)


@unittest.skipUnless(os.name == "nt", "Windows installer boundary contract")
class InstallerBoundaryTests(unittest.TestCase):
    def _required_native_hosts(self):
        return harness.required_hosts()

    def test_pure_parse_is_green_on_both_native_hosts_with_valid_control(self):
        """The valid control throws if executed; only its AST may be parsed."""
        harness.run_parse_case()

    def test_harness_native_rejects_wrong_roles_hash_and_syntax(self):
        # Fixed negative oracles; unexpected failure aborts remaining cases/hosts.
        for code in ("ROLE_SET_INVALID", "INPUT_DIGEST_MISMATCH", "PARSE_ERROR"):
            harness.run_parse_case(code)

    def test_harness_rejects_false_green_and_retains_receipts(self):
        for returncode, stderr in ((1, ""), (0, "SYNTHETIC_ERROR")):
            case = harness.new_case("b1-false-green")
            result = subprocess.CompletedProcess([], returncode, harness.PASS_MARKER, stderr)
            passed, record = harness.result_record(case, "powershell.exe", result, harness.PASS_MARKER)
            self.assertFalse(passed)
            self.assertEqual(record["status"], "UNEXPECTED")
            self.assertNotIn("SYNTHETIC_ERROR", json.dumps(record))
            self.assertTrue((case / "powershell_exe-result.json").exists())

    def test_harness_missing_host_is_blocked_not_skipped(self):
        with patch.object(harness.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "BLOCKED_NATIVE_HOST_UNAVAILABLE"):
                harness.required_hosts()

    def test_harness_environment_excludes_caller_private_values(self):
        case = harness.new_case("b1-environment")
        executable = harness.required_hosts()[0][1]
        with patch.dict(os.environ, {"HARNESS_SYNTHETIC_PRIVATE": "NOT_A_REAL_SECRET"}):
            env = harness.isolated_environment(case, executable)
        self.assertNotIn("HARNESS_SYNTHETIC_PRIVATE", env)
        for key in ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "HOME", "USERPROFILE", "PSModuleAnalysisCachePath"):
            self.assertTrue(Path(env[key]).is_relative_to(case))
        self.assertEqual(env["LINE_ENABLED"], "false")

    def test_harness_evidence_is_create_new_and_failure_case_survives(self):
        with harness.persistent_fixture("b1-retention") as directory:
            case = Path(directory)
            receipt = case / "receipt.json"
            harness.write_json(receipt, {"status": "FAILED"})
            before = receipt.read_bytes()
            with self.assertRaises(FileExistsError):
                harness.write_json(receipt, {"status": "PASS"})
            self.assertEqual(receipt.read_bytes(), before)
        self.assertTrue(receipt.exists())

    def test_harness_rejects_reparse_and_source_overlap(self):
        link = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        with patch.object(Path, "lstat", return_value=link):
            with self.assertRaisesRegex(RuntimeError, "FIXTURE_REPARSE_REJECTED"):
                harness.assert_plain_path(harness.AUDIT_CASE_ROOT)
        with patch.object(harness, "AUDIT_CASE_ROOT", ROOT):
            with self.assertRaisesRegex(RuntimeError, "FIXTURE_SOURCE_OVERLAP"):
                harness.new_case("b1-overlap")

    def test_metadata_directory_is_not_original_absence(self):
        """Actual candidate function only; no full coordinator or replacement IO."""
        source = ROOT / 'scripts/v213_runtime_install_coordinator.ps1'
        harness.assert_plain_path(source)
        raw = source.read_bytes(); digest = hashlib.sha256(raw).hexdigest()
        driver = r"""$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
Set-StrictMode -Version Latest
try {
    $source=Join-Path $PSScriptRoot 'coordinator.ps1'
    if((Get-FileHash -LiteralPath $source).Hash.ToLowerInvariant() -cne '__SOURCE_SHA__'){throw 'INPUT_CHANGED'}
    $t=$null;$e=$null
    $ast=[System.Management.Automation.Language.Parser]::ParseFile($source,[ref]$t,[ref]$e)
    if(@($e).Count -ne 0){throw 'PARSE_FAILED'}
    $names=@('Remove-V213TrailingSeparator','Resolve-V213DirectoryIdentity','Assert-V213MetadataFilePath','Read-V213Bytes','Restore-V213Metadata')
    $nodes=@($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $names -ccontains $n.Name},$false))
    if($nodes.Count -ne $names.Count){throw 'DEFINITION_FAILED'}
    foreach($node in $nodes){. ([scriptblock]::Create($node.Extent.Text))}
    $readDirectoryRefused=$false
    try {[void](Read-V213Bytes (Join-Path $PSScriptRoot 'occupied'))} catch {
        if($_.Exception.Message -cne 'METADATA_PATH_UNADMITTED'){throw 'READ_REFUSAL_UNEXPECTED'}
        $readDirectoryRefused=$true
    }
    $readAbsent=Read-V213Bytes (Join-Path $PSScriptRoot 'absent')
    $readEmpty=Read-V213Bytes (Join-Path $PSScriptRoot 'empty.bin')
    $readBytes=Read-V213Bytes (Join-Path $PSScriptRoot 'bytes.bin')
    $readChecks=($readDirectoryRefused -and $null -eq $readAbsent -and
        $readEmpty -is [byte[]] -and $readEmpty.Length -eq 0 -and
        $readBytes -is [byte[]] -and [Convert]::ToBase64String($readBytes) -ceq 'QUJD')
    $directory=Restore-V213Metadata (Join-Path $PSScriptRoot 'occupied') $null $false ([byte[]]@(78,69,87))
    $absent=Restore-V213Metadata (Join-Path $PSScriptRoot 'absent') $null $false ([byte[]]@(78,69,87))
    $missing=Restore-V213Metadata (Join-Path $PSScriptRoot 'absent') ([byte[]]@(79,76,68)) $true ([byte[]]@(78,69,87))
    if($directory -isnot [bool] -or $absent -isnot [bool] -or $missing -isnot [bool]){throw 'RESULT_TYPE_FAILED'}
    [ordered]@{kind='METADATA_ABSENCE_GUARD';directory_accepted=$directory;absence_accepted=$absent;missing_original_accepted=$missing;read_checks_pass=$readChecks;full_coordinator_executed=$false;release_qualified=$false}|ConvertTo-Json -Compress
    if($directory -or -not $absent -or $missing -or -not $readChecks){exit 1}
    exit 0
} catch { Write-Output 'METADATA_ABSENCE_GUARD_UNEXPECTED'; exit 1 }
""".replace('__SOURCE_SHA__', digest).encode('utf-8-sig')
        prepared = []
        for host, executable in harness.required_hosts():
            case = harness.new_case('metadata-absence-guard')
            harness.write_new(case / 'coordinator.ps1', raw)
            harness.write_new(case / 'probe.ps1', driver)
            (case / 'occupied').mkdir()
            harness.write_new(case / 'occupied/sentinel.bin', b'UNIQUE_PUBLIC_SENTINEL')
            harness.write_new(case / 'empty.bin', b'')
            harness.write_new(case / 'bytes.bin', b'ABC')
            hashes = {'coordinator.ps1': digest, 'probe.ps1': hashlib.sha256(driver).hexdigest(),
                      'empty.bin': hashlib.sha256(b'').hexdigest(), 'bytes.bin': hashlib.sha256(b'ABC').hexdigest()}
            harness.write_json(case / 'inputs.json', {'files': hashes, 'scope': 'FUNCTION_ABSENCE_GUARD_ONLY', 'release_qualified': False})
            env = harness.isolated_environment(case, executable)
            env['V213_TEST_PARSE_ROOT'] = str(case)
            prepared.append((host, executable, case, env, hashes))
        parse = "$ErrorActionPreference='Stop';foreach($name in @('probe.ps1','coordinator.ps1')){$t=$null;$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile((Join-Path $env:V213_TEST_PARSE_ROOT $name),[ref]$t,[ref]$e);if(@($e).Count -ne 0){exit 1}};Write-Output 'METADATA_GUARD_PARSE_PASS'"
        for phase in ('parse', 'guard'):
            for host, executable, case, env, hashes in prepared:
                args = ['-Command', parse] if phase == 'parse' else ['-File', str(case / 'probe.ps1')]
                try:
                    result = subprocess.run([executable, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', *args], cwd=case, env=env,
                                            capture_output=True, encoding='utf-8', errors='replace', timeout=30)
                except (OSError, subprocess.TimeoutExpired):
                    harness.write_json(case / (phase + '-transport.json'), {'status': 'UNEXPECTED_TRANSPORT', 'release_qualified': False})
                    raise AssertionError('METADATA_GUARD_TRANSPORT_FAILED') from None
                output = (result.stdout + result.stderr).encode('utf-8')
                harness.write_json(case / (phase + '-transport.json'), {'host': host, 'exit_code': result.returncode,
                                   'output_sha256': hashlib.sha256(output).hexdigest(), 'output_bytes': len(output), 'release_qualified': False})
                for name, expected in hashes.items():
                    harness.assert_plain_path(case / name)
                    self.assertEqual(hashlib.sha256((case / name).read_bytes()).hexdigest(), expected)
                self.assertEqual((case / 'occupied/sentinel.bin').read_bytes(), b'UNIQUE_PUBLIC_SENTINEL')
                self.assertFalse((case / 'absent').exists())
                self.assertEqual(result.stderr, '', 'METADATA_GUARD_STDERR')
                if phase == 'parse':
                    self.assertEqual(result.returncode, 0, 'METADATA_GUARD_PARSE_FAILED')
                    self.assertEqual(result.stdout.strip(), 'METADATA_GUARD_PARSE_PASS')
                    continue
                value = json.loads(result.stdout)
                self.assertEqual(set(value), {'kind', 'directory_accepted', 'absence_accepted', 'missing_original_accepted', 'read_checks_pass', 'full_coordinator_executed', 'release_qualified'})
                self.assertEqual(value['kind'], 'METADATA_ABSENCE_GUARD')
                for key in ('directory_accepted', 'absence_accepted', 'missing_original_accepted', 'read_checks_pass', 'full_coordinator_executed', 'release_qualified'):
                    self.assertIs(type(value[key]), bool)
                harness.write_json(case / 'observation.json', value)
                self.assertEqual(result.returncode, 0, 'METADATA_DIRECTORY_GUARD_FAILED')
                self.assertIs(value['directory_accepted'], False)
                self.assertIs(value['absence_accepted'], True)
                self.assertIs(value['missing_original_accepted'], False)
                self.assertIs(value['read_checks_pass'], True)
                self.assertIs(value['full_coordinator_executed'], False)
                self.assertIs(value['release_qualified'], False)

    def test_all_callers_refuse_metadata_directories_before_lock_or_staging(self):
        """Actual source entrypoints, synthetic refusal only; never a live install."""
        callers = [relative for role, relative in harness.PARSE_INPUTS if role.startswith('caller:')]
        for host, executable in harness.required_hosts():
            for caller in callers:
                for name in ('v213-runtime-install.journal.json', 'v213-runtime-install-receipt.json', 'v213-runtime-state.json'):
                    with self.subTest(host=host, caller=caller, metadata=name):
                        case = harness.new_case('metadata-caller-refusal')
                        source = case / 'source'; runtime = case / 'runtime'
                        self._write_minimal_source(source)
                        for relative in callers:
                            if relative != 'install-v213-runtime.ps1':
                                shutil.copyfile(ROOT / relative, source / relative)
                        inputs = {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in source.rglob('*') if p.is_file()}
                        env = harness.isolated_environment(case, executable)
                        metadata = Path(env['LOCALAPPDATA']) / 'InvestorIntelligence'
                        occupied = metadata / name
                        occupied.mkdir(parents=True)
                        harness.write_new(occupied / 'sentinel.bin', b'UNIQUE_PUBLIC_SENTINEL')
                        harness.write_json(case / 'inputs.json', {'files': inputs, 'caller': caller, 'metadata': name,
                            'scope': 'SYNTHETIC_SOURCE_ENTRYPOINT_EARLY_REFUSAL', 'release_qualified': False})
                        command = [executable, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
                                   str(source / caller), '-ProjectRoot', str(source), '-RuntimeRoot', str(runtime)]
                        try:
                            result = subprocess.run(command, cwd=case, env=env, capture_output=True,
                                                    encoding='utf-8', errors='replace', timeout=30)
                        except (OSError, subprocess.TimeoutExpired):
                            harness.write_json(case / 'transport.json', {'status': 'UNEXPECTED_TRANSPORT', 'release_qualified': False})
                            raise AssertionError('METADATA_CALLER_TRANSPORT_FAILED') from None
                        output = result.stdout + result.stderr
                        refused = result.returncode != 0 and 'METADATA_PATH_UNADMITTED' in output
                        # Keep hashes and bounded results, never raw native exceptions.
                        harness.write_json(case / 'transport.json', {'host': host, 'command': command,
                            'exit_code': result.returncode, 'expected_refusal': refused,
                            'output_sha256': hashlib.sha256(output.encode('utf-8')).hexdigest(),
                            'output_bytes': len(output.encode('utf-8')), 'raw_output_retained': False,
                            'source_entrypoint_executed': True, 'release_qualified': False})
                        for relative, expected in inputs.items():
                            path = source / relative; harness.assert_plain_path(path)
                            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)
                        self.assertEqual((occupied / 'sentinel.bin').read_bytes(), b'UNIQUE_PUBLIC_SENTINEL')
                        self.assertFalse(runtime.exists(), 'METADATA_REFUSAL_CREATED_RUNTIME')
                        self.assertFalse(list(case.glob('runtime.*')), 'METADATA_REFUSAL_CREATED_STAGE_OR_BACKUP')
                        lock = Path(env['TEMP']) / 'InvestorIntelligence-v213-runtime-install.lock'
                        harness.write_json(case / 'observation.json', {'expected_refusal': refused,
                            'lock_absent': not lock.exists(), 'runtime_stage_backup_absent': True,
                            'sentinel_unchanged': True, 'inputs_unchanged': True, 'release_qualified': False})
                        self.assertTrue(refused, 'METADATA_TYPE_NOT_REFUSED_AT_SOURCE_ENTRYPOINT')
                        self.assertFalse(lock.exists(), 'METADATA_REFUSAL_ACQUIRED_INSTALL_LOCK')
                        self.assertEqual([p.name for p in metadata.iterdir()], [name])

    def _write_minimal_source(self, source):
        source.mkdir()
        shutil.copyfile(ROOT / "install-v213-runtime.ps1", source / "install-v213-runtime.ps1")
        (source / "scripts").mkdir()
        shutil.copyfile(ROOT / "scripts/v213_runtime_install_coordinator.ps1", source / "scripts/v213_runtime_install_coordinator.ps1")
        (source / "HOTFIX-REFS.json").write_text(
            '{"artifact_kind":"R75_FREE_WORKERS_RELAY_HOTFIX","package_version":"2.1.3",'
            '"source_commit":"' + "a" * 40 + '","workflow_run_id":"12345",'
            '"production_mutation_by_ci":false}\n', encoding="utf-8")

    def _run_minimal_installer(self, shell, source, runtime, local):
        executable = dict(harness.required_hosts())[shell]
        env = harness.isolated_environment(local.parent, executable)
        local.mkdir(exist_ok=True)
        env["LOCALAPPDATA"] = str(local)
        return subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
             str(source / "install-v213-runtime.ps1"), "-ProjectRoot", str(source), "-RuntimeRoot", str(runtime)],
            cwd=str(local.parent), env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        )

    def test_mir_refuses_existing_runtime_data_before_copy(self):
        """A pre-existing runtime sentinel must survive a rejected/unsafe copy."""
        for shell, _ in self._required_native_hosts():
            with self.subTest(shell=shell), harness.persistent_fixture("installer-boundary") as directory:
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
                self.assertIn("RUNTIME_INSTALL_FAILED;failure=RUNTIME_OWNERSHIP_UNPROVEN;rollback=PASS", result.stdout + result.stderr)
                self.assertEqual(sentinel.read_bytes(), b"MUST_SURVIVE_REJECTED_INSTALL")
                self.assertFalse(list(parent.glob('runtime.stage.*')))
                self.assertFalse(list(parent.glob('runtime.old.*')))
                for name in ('v213-runtime-install.journal.json', 'v213-runtime-install-receipt.json', 'v213-runtime-state.json'):
                    self.assertFalse((local / 'InvestorIntelligence' / name).exists())

    def test_refuses_source_destination_overlap_before_any_directory_creation(self):
        for shell, _ in self._required_native_hosts():
            for case in ("destination_below_source", "source_below_destination", "same_path", "same_path_short_alias"):
                with self.subTest(shell=shell, case=case), harness.persistent_fixture("installer-overlap") as directory:
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
                        if short.casefold() == str(source).casefold():
                            continue
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
        for shell, _ in self._required_native_hosts():
            with self.subTest(shell=shell), harness.persistent_fixture("installer-source-reparse") as directory:
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
                    pass  # Preserve this case's link and target; no failure cleanup.

    def _write_full_package_source(self, source):
        source.mkdir()
        tracked = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z"]).decode().split("\0")
        tracked.append("scripts/v213_runtime_install_coordinator.ps1")
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
        for shell, _ in self._required_native_hosts():
            with self.subTest(shell=shell), harness.persistent_fixture("installer-upgrade") as directory:
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
                self.assertTrue(any(marker in (rejected.stdout + rejected.stderr) for marker in ("RUNTIME_TOPOLOGY_UNOWNED_DATA", "RUNTIME_OWNERSHIP_DIGEST_MISMATCH")), rejected.stdout + rejected.stderr)
                self.assertEqual(unknown.read_bytes(), b"MUST_SURVIVE_REJECT")

    def test_failed_overlay_does_not_leave_partial_runtime_or_metadata(self):
        for shell, _ in self._required_native_hosts():
            with self.subTest(shell=shell), harness.persistent_fixture("installer-failure") as directory:
                parent = Path(directory)
                source = parent / "source"
                runtime = parent / "runtime"
                local = parent / "local"
                self._write_full_package_source(source)
                (source / "run-v213-local-llm-bridge-source-diverse.ps1").unlink()
                result = self._run_minimal_installer(shell, source, runtime, local)
                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, output)
                self.assertFalse(runtime.exists(), output)
                self.assertFalse((local / "InvestorIntelligence/v213-runtime-state.json").exists(), output)

    def test_refuses_reparse_entry_before_mir_and_preserves_target(self):
        for shell, _ in self._required_native_hosts():
            with self.subTest(shell=shell), harness.persistent_fixture("installer-reparse") as directory:
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
                    pass  # Preserve this case's link and target; no failure cleanup.


if __name__ == "__main__": unittest.main()
