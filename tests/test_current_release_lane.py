from pathlib import Path
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]

CANONICAL_TEST_PS_SHA256 = '619a8b4562d85068bc8ac5a3e37fa1be15159ff9b8548c0a840c2f559a2ad42e'
CANONICAL_LOCK_PS_SHA256 = '886e2407d7e3b7677e6e84c5cbe6eeab01cd6d77c7942f073120ec5ce3f4f69c'
PRODUCTION_MUTEX_CONSTRUCTION = b"$mutex = New-Object Threading.Mutex($false, 'Local\\InvestorIntelligence_V213_R75_OPERATION')"
PRODUCTION_MUTEX_LITERAL = b"'Local\\InvestorIntelligence_V213_R75_OPERATION'"
PRODUCTION_MUTEX_UNQUOTED = b"Local\\InvestorIntelligence_V213_R75_OPERATION"


def transform_operation_lock_module(raw_bytes: bytes, test_id: str) -> bytes:
    if PRODUCTION_MUTEX_CONSTRUCTION not in raw_bytes:
        raise ValueError("Production mutex construction not found in source bytes")
    if raw_bytes.count(PRODUCTION_MUTEX_LITERAL) != 1:
        raise ValueError(
            f"Expected exactly 1 quoted production mutex literal, found {raw_bytes.count(PRODUCTION_MUTEX_LITERAL)}"
        )
    if raw_bytes.count(PRODUCTION_MUTEX_UNQUOTED) != 1:
        raise ValueError(
            f"Expected exactly 1 unquoted production mutex reference, found {raw_bytes.count(PRODUCTION_MUTEX_UNQUOTED)}"
        )
    test_mutex_literal = f"'Local\\InvestorIntelligence_V213_TEST_{test_id}'".encode('ascii')
    transformed = raw_bytes.replace(PRODUCTION_MUTEX_LITERAL, test_mutex_literal)
    if transformed.count(PRODUCTION_MUTEX_LITERAL) != 0:
        raise ValueError("Transformed module still contains original quoted mutex literal")
    if transformed.count(PRODUCTION_MUTEX_UNQUOTED) != 0:
        raise ValueError("Transformed module still contains unquoted production mutex name")
    if transformed.count(test_mutex_literal) != 1:
        raise ValueError("Transformed module does not contain exactly 1 test mutex literal")
    restored = transformed.replace(test_mutex_literal, PRODUCTION_MUTEX_LITERAL)
    if restored != raw_bytes:
        raise ValueError("Reverse substitution failed to recover identical original bytes")
    return transformed


def create_isolated_lock_sandbox(sandbox_dir: Path, test_id: str | None = None) -> tuple[Path, Path, str]:
    if test_id is None:
        test_id = uuid.uuid4().hex
    sandbox_scripts = sandbox_dir / 'scripts'
    sandbox_scripts.mkdir(parents=True, exist_ok=True)

    src_test_ps = ROOT / 'scripts/test_v213_operation_lock.ps1'
    src_lock_ps = ROOT / 'scripts/v213_operation_lock.ps1'

    raw_test_ps = src_test_ps.read_bytes()
    raw_lock_ps = src_lock_ps.read_bytes()

    if hashlib.sha256(raw_test_ps).hexdigest() != CANONICAL_TEST_PS_SHA256:
        raise ValueError(
            f"Canonical test_v213_operation_lock.ps1 SHA256 mismatch: {hashlib.sha256(raw_test_ps).hexdigest()}"
        )
    if hashlib.sha256(raw_lock_ps).hexdigest() != CANONICAL_LOCK_PS_SHA256:
        raise ValueError(
            f"Canonical v213_operation_lock.ps1 SHA256 mismatch: {hashlib.sha256(raw_lock_ps).hexdigest()}"
        )

    dest_test_ps = sandbox_scripts / 'test_v213_operation_lock.ps1'
    dest_test_ps.write_bytes(raw_test_ps)
    if dest_test_ps.read_bytes() != raw_test_ps:
        raise ValueError("Byte-for-byte copy of selftest failed")

    transformed_lock_bytes = transform_operation_lock_module(raw_lock_ps, test_id)
    dest_lock_ps = sandbox_scripts / 'v213_operation_lock.ps1'
    dest_lock_ps.write_bytes(transformed_lock_bytes)

    return dest_test_ps, dest_lock_ps, test_id


class TestProcessTracker:
    def __init__(self):
        self.owned: list[dict] = []
        self.sandboxes: list[Path] = []
        self.retained_sandboxes: set[Path] = set()

    def create_sandbox(self, prefix: str) -> Path:
        p = Path(tempfile.mkdtemp(prefix=prefix))
        self.sandboxes.append(p)
        return p

    def register(self, proc, sandbox: Path, default_timeout: float = 30.0, release_file: Path | None = None) -> dict:
        entry = {
            'proc': proc,
            'sandbox': sandbox,
            'default_timeout': default_timeout,
            'release_file': release_file,
            'waited': False,
        }
        self.owned.append(entry)
        return entry

    def settle_and_cleanup(self, failed: bool = False):
        if failed:
            for s in self.sandboxes:
                self.retained_sandboxes.add(s)

        for entry in self.owned:
            proc = entry['proc']
            if not entry['waited']:
                rel = entry.get('release_file')
                if rel is not None:
                    try:
                        rel.write_text('RELEASE', encoding='utf-8')
                    except Exception:
                        pass
                timeout = entry.get('default_timeout', 30.0)
                try:
                    if hasattr(proc, 'communicate'):
                        proc.communicate(timeout=timeout)
                except Exception:
                    self.retained_sandboxes.add(entry['sandbox'])
                finally:
                    entry['waited'] = True

            poll_fn = getattr(proc, 'poll', None)
            if callable(poll_fn):
                try:
                    if poll_fn() is None:
                        self.retained_sandboxes.add(entry['sandbox'])
                except Exception:
                    self.retained_sandboxes.add(entry['sandbox'])

        for s in self.sandboxes:
            if s in self.retained_sandboxes:
                continue
            shutil.rmtree(s, ignore_errors=True)


class CurrentReleaseLaneTests(unittest.TestCase):
    def test_current_qa_reference_has_exact_reviewed_path_admission(self):
        import json
        reference = json.loads((ROOT / 'state/r75-qa-live-current.ref.json').read_text())
        script = (ROOT / 'scripts/ci_v213_r75_free_relay_validate.ps1').read_text(encoding='utf-8-sig')
        allowed = script.split('$allowed = @(', 1)[1].split('\n    )', 1)[0]
        paths = re.findall(r"'([^']+)'", allowed)
        self.assertIn(reference['receipt_path'], paths)
        self.assertFalse(any('*' in path for path in paths))

    def setUp(self):
        self.workflow = (ROOT / '.github/workflows/v213-r75-release.yml').read_text(encoding='utf-8')

    def step(self, name):
        return self.workflow.split('      - name: ' + name + '\n', 1)[1].split('\n      - name: ', 1)[0]

    def test_current_candidates_never_automatically_use_legacy_generic_packager(self):
        runs = re.findall(r'^\s+run:\s*(.+)$', self.workflow, flags=re.MULTILINE)
        self.assertFalse(any('ci_v213_r75_package.ps1' in value for value in runs))
        current = self.step('Run current R75 release validation')
        self.assertIn("github.ref_name != 'pi/r75-named-tunnel-deployment-hotfix'", current)
        self.assertIn('ci_v213_r75_free_relay_validate.ps1', current)
        self.assertNotIn("github.ref_name == 'pi/r75-free-workers-relay'", current)

    def test_current_packaging_and_upload_require_live_qualification(self):
        for name in ('Build and independently verify current immutable R75 package',
                     'Upload current immutable R75 package and receipts'):
            block = self.step(name)
            self.assertIn("env.R75_QA_RELEASE_READY == 'true'", block)
            self.assertIn("github.ref_name != 'pi/r75-named-tunnel-deployment-hotfix'", block)
        self.assertIn("throw 'Current candidate lacks fresh live evidence", self.workflow)
        package = (ROOT / 'scripts/ci_v213_r75_free_relay_package.ps1').read_text()
        for marker in ('Assert-V213QaReleaseQualification', 'Extracted ZIP Worker tests failed',
                       'Extracted ZIP stable runtime installation failed', 'worker_test_payload'):
            self.assertIn(marker, package)
        self.assertEqual(package.count('scripts/verify_r75_qa_evidence.py --receipt $liveProof'), 2)
        self.assertIn('release_evidence_rules_changed = $true', package)
        self.assertIn('Live proof digest changed during packaging', package)
        self.assertIn('Exact checkout changed during packaging', package)
        self.assertNotIn("created='2026-09-04T00:00:00Z'", package)

    def test_profile_candidates_select_new_evidence_and_never_stamp_q6(self):
        for name in ('ci_v213_r75_free_relay_validate.ps1', 'ci_v213_r75_free_relay_package.ps1'):
            script = (ROOT / 'scripts' / name).read_text()
            self.assertIn('scripts/r75_release_inputs.py --project-root $ProjectRoot', script)
            self.assertIn('$qaInput.source_commit -cne $sha', script)
            self.assertIn("$profileArgs=@('--model-profile',$profilePath)", script)
            self.assertIn('--receipt $liveProof @profileArgs', script)
            self.assertNotRegex(script, r"exact_model\s*=\s*'qwen38-q6'")
            self.assertIn('$qa.model_profile_sha256', script)
        self.assertTrue((ROOT / 'state/r75-qa-live-qualification.json').is_file())
        package = (ROOT / 'scripts/ci_v213_r75_free_relay_package.ps1').read_text()
        self.assertIn('Windows/model profile receipt mismatch.', package)
        self.assertIn('Protected R75 release source changed:', package)

    def test_active_activation_is_versioned_and_certified_v2_bytes_are_preserved(self):
        script = (ROOT / 'scripts/ci_v213_r75_free_relay_validate.ps1').read_text()
        baseline = re.search(r"\$r75Commit\s*=\s*'([0-9a-f]{40})'", script).group(1)
        relative = 'cloud/src/v213/activation-v2.ts'
        # Pinned identity of `git show <baseline>:<relative>` (git blob id and SHA-256), so the row needs no git child
        # process against the repository; a different baseline commit needs a reviewed new pin, never a silent refresh.
        self.assertEqual(baseline, '536644d22ef3534be1c4b8a9e1ff969df4d580fa')
        frozen = (ROOT / relative).read_bytes()
        self.assertEqual(hashlib.sha1(b'blob %d\0' % len(frozen) + frozen).hexdigest(), '7475f6cf94380843b4fe57d59e6330a147a33b45')
        self.assertEqual(hashlib.sha256(frozen).hexdigest(), '588d80a7bfeccf1e110ebd065632ff40b0106e6b5559ff366b23a02d99014922')
        self.assertIn('from "./activation-v3"', (ROOT / 'cloud/src/v213/production-worker.ts').read_text())
        for path in (ROOT / 'cloud/src').rglob('*.ts'):
            self.assertNotRegex(path.read_text(encoding='utf-8-sig'), r'''(?:from\s*|(?:import|require)\s*\(\s*)["'][^"']*activation-v2["']''', str(path))

    @unittest.skipUnless(os.name == 'nt', 'native Windows npm export')
    def test_actual_node_export_uses_unique_external_cache_and_rejects_bad_temp(self):
        import ctypes
        text = (ROOT / 'scripts/resolve_node.ps1').read_text(encoding='utf-8')
        block = text[text.index('if ($env:GITHUB_ENV) {'):text.index('\nWrite-Host "Using Node')]
        for shell in ('powershell.exe', 'pwsh.exe'):
            if not shutil.which(shell): continue
            with tempfile.TemporaryDirectory(prefix='npm export ') as d:
                parent = Path(d); source = parent / 'source'; scripts = source / 'scripts'; scripts.mkdir(parents=True)
                outside = parent / 'runner temp'; outside.mkdir()
                short_parent = ctypes.create_unicode_buffer(32768)
                if ctypes.windll.kernel32.GetShortPathNameW(str(parent), short_parent, len(short_parent)):
                    outside = Path(short_parent.value) / outside.name
                inside = source / 'bad temp'; inside.mkdir()
                probe = scripts / 'probe.ps1'
                probe.write_text("$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;$nodeDirectory='synthetic-node';$resolved=[pscustomobject]@{Node='synthetic-node';Npm='synthetic-npm'};\n" + block, encoding='utf-8-sig')
                caches = []
                temporaries = [str(outside), str(outside), str(inside), '']
                short = ctypes.create_unicode_buffer(32768)
                if ctypes.windll.kernel32.GetShortPathNameW(str(inside), short, len(short)) and short.value != str(inside):
                    temporaries.append(short.value)  # Service accounts can inherit 8.3 aliases.
                for index, temporary in enumerate(temporaries):
                    env_file = parent / f'env-{index}.txt'; path_file = parent / f'path-{index}.txt'
                    result = subprocess.run([shell, '-NoProfile', '-File', str(probe)], cwd=source,
                        env={**os.environ, 'RUNNER_TEMP': temporary, 'GITHUB_ENV': str(env_file), 'GITHUB_PATH': str(path_file)},
                        capture_output=True, timeout=20)
                    if index < 2:
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        values = dict(line.split('=', 1) for line in env_file.read_text(encoding='utf-8-sig').splitlines())
                        cache = Path(values['NPM_CONFIG_CACHE'])
                        self.assertTrue(cache.resolve().is_relative_to(outside.resolve()), str(cache))
                        self.assertFalse(cache.resolve().is_relative_to(source.resolve()))
                        caches.append(cache)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertFalse(env_file.exists())
                        self.assertFalse(path_file.exists())
                self.assertNotEqual(caches[0], caches[1])

    def test_historical_scripts_are_retained_and_no_production_mutation_added(self):
        for name in ('ci_v213_r75_package.ps1', 'verify_v213_r75_artifact.py'):
            self.assertTrue((ROOT / 'scripts' / name).is_file())
        self.assertIn("PRODUCTION_MUTATION_BY_CI: 'false'", self.workflow)
        self.assertIn('persist-credentials: false', self.workflow)
        self.assertIn('contents: read', self.workflow)
        self.assertNotIn('gh release create', self.workflow)

    def test_validation_only_cannot_package_upload_or_claim_release(self):
        self.assertIn('default: false', self.workflow)
        self.assertIn("github.actor == 'always7895'", self.workflow)
        self.assertIn('runs-on: [self-hosted, Windows, X64, investor-intelligence-reviewed]', self.workflow)
        self.assertNotIn('runs-on: [self-hosted, Windows, X64, investor-intelligence]', self.workflow)
        self.assertIn('release_qualified=false', self.step('Run source-bound Windows validation only'))
        for name in ('Run R75 Named Tunnel deployment-hotfix validation',
                     'Run current R75 release validation',
                     'Build and independently verify immutable Named Tunnel deployment hotfix',
                     'Build and independently verify current immutable R75 package',
                     'Require current release qualification',
                     'Upload immutable R75 Named Tunnel hotfix and receipts',
                     'Upload current immutable R75 package and receipts'):
            self.assertIn('inputs.validation_only != true', self.step(name), name)

    def test_operation_lock_static_fail_closed_and_sandbox_guards(self):
        canonical_test_path = ROOT / 'scripts/test_v213_operation_lock.ps1'
        canonical_lock_path = ROOT / 'scripts/v213_operation_lock.ps1'

        canonical_test_bytes = canonical_test_path.read_bytes()
        canonical_lock_bytes = canonical_lock_path.read_bytes()

        self.assertEqual(hashlib.sha256(canonical_test_bytes).hexdigest(), CANONICAL_TEST_PS_SHA256)
        self.assertEqual(hashlib.sha256(canonical_lock_bytes).hexdigest(), CANONICAL_LOCK_PS_SHA256)

        # Assert exact production default construction and singleton literal
        self.assertIn(PRODUCTION_MUTEX_CONSTRUCTION, canonical_lock_bytes)
        self.assertEqual(canonical_lock_bytes.count(PRODUCTION_MUTEX_LITERAL), 1)
        self.assertEqual(canonical_lock_bytes.count(PRODUCTION_MUTEX_UNQUOTED), 1)

        # Synthetic zero-match input must fail before subprocess launch
        with self.assertRaises(ValueError):
            transform_operation_lock_module(b"# no mutex construction here", "testguid")

        synthetic_missing_literal = PRODUCTION_MUTEX_CONSTRUCTION.replace(PRODUCTION_MUTEX_LITERAL, b"'other'")
        with self.assertRaises(ValueError):
            transform_operation_lock_module(synthetic_missing_literal, "testguid")

        # Synthetic multiple-match input must fail before subprocess launch
        synthetic_multi = PRODUCTION_MUTEX_CONSTRUCTION + b"\n" + PRODUCTION_MUTEX_LITERAL
        with self.assertRaises(ValueError):
            transform_operation_lock_module(synthetic_multi, "testguid")

        # Sandbox paths resolve inside sandbox; transformed module has no production literal
        with tempfile.TemporaryDirectory(prefix='v213-lock-guard-') as td:
            sandbox_dir = Path(td)
            dest_test_ps, dest_lock_ps, test_id = create_isolated_lock_sandbox(sandbox_dir)
            self.assertTrue(dest_test_ps.resolve().is_relative_to(sandbox_dir.resolve()))
            self.assertTrue(dest_lock_ps.resolve().is_relative_to(sandbox_dir.resolve()))
            self.assertEqual(dest_test_ps.read_bytes(), canonical_test_bytes)

            transformed = dest_lock_ps.read_bytes()
            self.assertNotIn(PRODUCTION_MUTEX_UNQUOTED, transformed)
            self.assertNotIn(PRODUCTION_MUTEX_LITERAL, transformed)
            expected_test_literal = f"'Local\\InvestorIntelligence_V213_TEST_{test_id}'".encode('ascii')
            self.assertEqual(transformed.count(expected_test_literal), 1)
            restored = transformed.replace(expected_test_literal, PRODUCTION_MUTEX_LITERAL)
            self.assertEqual(restored, canonical_lock_bytes)

    def test_operation_lock_actual_callers_have_no_clixml_progress(self):
        shells = [shell for shell in ('powershell.exe', 'pwsh') if shutil.which(shell)]
        if not shells:
            self.skipTest('PowerShell required for actual caller regression')
        for shell in shells:
            tracker = TestProcessTracker()
            sandbox_root = tracker.create_sandbox(prefix=f'v213-lock-caller-{Path(shell).stem}-')
            dest_test_ps, dest_lock_ps, _ = create_isolated_lock_sandbox(sandbox_root)
            failed = True
            try:
                result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-File',
                                         str(dest_test_ps),
                                         '-ProjectRoot', str(sandbox_root)],
                                        cwd=str(sandbox_root),
                                        capture_output=True, text=True,
                                        errors='replace', timeout=30)
                with self.subTest(shell=shell):
                    self.assertEqual(result.returncode, 0)
                    self.assertIn('V213_OPERATION_LOCK_SELF_TEST = PASS', result.stdout)
                    self.assertNotIn('CLIXML', result.stdout + result.stderr)
                    self.assertEqual(result.stderr.strip(), '')
                failed = False
            finally:
                tracker.settle_and_cleanup(failed=failed)

    def test_operation_lock_independent_concurrency_and_contention(self):
        shells = [shell for shell in ('powershell.exe', 'pwsh') if shutil.which(shell)]
        if not shells:
            self.skipTest('PowerShell required for actual caller regression')
        for shell in shells:
            with self.subTest(shell=shell):
                tracker = TestProcessTracker()
                failed = True
                try:
                    sandbox_a = tracker.create_sandbox(prefix=f'v213-lock-conc-a-{Path(shell).stem}-')
                    sandbox_b = tracker.create_sandbox(prefix=f'v213-lock-conc-b-{Path(shell).stem}-')
                    test_ps_a, lock_ps_a, guid_a = create_isolated_lock_sandbox(sandbox_a)
                    test_ps_b, lock_ps_b, guid_b = create_isolated_lock_sandbox(sandbox_b)
                    self.assertNotEqual(guid_a, guid_b)

                    # 1. Concurrent actual selftests in distinct GUID sandboxes
                    p_a = subprocess.Popen(
                        [shell, '-NoProfile', '-NonInteractive', '-File',
                         str(test_ps_a), '-ProjectRoot', str(sandbox_a)],
                        cwd=str(sandbox_a), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                    )
                    rec_a = tracker.register(p_a, sandbox_a, default_timeout=30.0)

                    p_b = subprocess.Popen(
                        [shell, '-NoProfile', '-NonInteractive', '-File',
                         str(test_ps_b), '-ProjectRoot', str(sandbox_b)],
                        cwd=str(sandbox_b), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                    )
                    rec_b = tracker.register(p_b, sandbox_b, default_timeout=30.0)

                    try:
                        stdout_a, stderr_a = p_a.communicate(timeout=30)
                    finally:
                        rec_a['waited'] = True

                    try:
                        stdout_b, stderr_b = p_b.communicate(timeout=30)
                    finally:
                        rec_b['waited'] = True

                    self.assertEqual(p_a.returncode, 0)
                    self.assertEqual(p_b.returncode, 0)
                    self.assertIn('V213_OPERATION_LOCK_SELF_TEST = PASS', stdout_a)
                    self.assertIn('V213_OPERATION_LOCK_SELF_TEST = PASS', stdout_b)
                    self.assertNotIn('CLIXML', stdout_a + stderr_a)
                    self.assertNotIn('CLIXML', stdout_b + stderr_b)
                    self.assertEqual(stderr_a.strip(), '')
                    self.assertEqual(stderr_b.strip(), '')

                    # 2. Bounded synthetic ready/release handshake using actual transformed modules
                    hold_script_source = (
                        "[CmdletBinding()]\n"
                        "param(\n"
                        "    [Parameter(Mandatory=$true)][string]$ReadyFile,\n"
                        "    [Parameter(Mandatory=$true)][string]$ReleaseFile\n"
                        ")\n"
                        "$ErrorActionPreference = 'Stop'\n"
                        "$ProgressPreference = 'SilentlyContinue'\n"
                        "Set-StrictMode -Version Latest\n"
                        "$module = Join-Path $PSScriptRoot 'scripts\\v213_operation_lock.ps1'\n"
                        ". $module\n"
                        "[void](Enter-V213OperationLock -Owner 'orchestrator-A-holder')\n"
                        "try {\n"
                        "    [IO.File]::WriteAllText($ReadyFile, 'HELD')\n"
                        "    $deadline = [DateTime]::UtcNow.AddSeconds(20)\n"
                        "    while (-not (Test-Path -LiteralPath $ReleaseFile)) {\n"
                        "        if ([DateTime]::UtcNow -gt $deadline) {\n"
                        "            throw 'Timed out waiting for release signal'\n"
                        "        }\n"
                        "        [Threading.Thread]::Sleep(50)\n"
                        "    }\n"
                        "}\n"
                        "finally {\n"
                        "    Exit-V213OperationLock\n"
                        "}\n"
                        "Write-Host 'HOLDER_RELEASED = PASS'\n"
                    )
                    probe_script_source = (
                        "[CmdletBinding()]\n"
                        "param(\n"
                        "    [string]$Owner = 'contender',\n"
                        "    [int]$TimeoutSeconds = 0\n"
                        ")\n"
                        "$ErrorActionPreference = 'Stop'\n"
                        "$ProgressPreference = 'SilentlyContinue'\n"
                        "Set-StrictMode -Version Latest\n"
                        "$module = Join-Path $PSScriptRoot 'scripts\\v213_operation_lock.ps1'\n"
                        ". $module\n"
                        "try {\n"
                        "    [void](Enter-V213OperationLock -Owner $Owner -TimeoutSeconds $TimeoutSeconds)\n"
                        "    Exit-V213OperationLock\n"
                        "    Write-Host 'ACQUIRED'\n"
                        "    exit 0\n"
                        "}\n"
                        "catch {\n"
                        "    if ($_.Exception.Message -match 'V213_OPERATION_LOCK_BUSY') {\n"
                        "        Write-Host 'BUSY'\n"
                        "        exit 2\n"
                        "    }\n"
                        "    Write-Error $_\n"
                        "    exit 8\n"
                        "}\n"
                    )

                    hold_ps_a = sandbox_a / 'orchestrate_hold.ps1'
                    hold_ps_a.write_text(hold_script_source, encoding='utf-8')

                    probe_ps_a = sandbox_a / 'orchestrate_probe.ps1'
                    probe_ps_a.write_text(probe_script_source, encoding='utf-8')

                    probe_ps_b = sandbox_b / 'orchestrate_probe.ps1'
                    probe_ps_b.write_text(probe_script_source, encoding='utf-8')

                    ready_file = sandbox_a / 'holder_ready.signal'
                    release_file = sandbox_a / 'release_holder.signal'

                    p_holder = subprocess.Popen(
                        [shell, '-NoProfile', '-NonInteractive', '-File', str(hold_ps_a),
                         '-ReadyFile', str(ready_file), '-ReleaseFile', str(release_file)],
                        cwd=str(sandbox_a), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                    )
                    rec_holder = tracker.register(p_holder, sandbox_a, default_timeout=15.0, release_file=release_file)
                    try:
                        deadline = time.time() + 15.0
                        while not ready_file.exists() and time.time() < deadline:
                            if p_holder.poll() is not None:
                                stdout_h, stderr_h = p_holder.communicate()
                                rec_holder['waited'] = True
                                self.fail(
                                    f"Holder exited prematurely with code {p_holder.returncode}: {stdout_h} {stderr_h}"
                                )
                            time.sleep(0.05)
                        self.assertTrue(ready_file.exists(), 'Holder failed to create ready file within timeout')

                        # While A holds:
                        # 1. B uses DIFFERENT test mutex -> must ACQUIRE successfully
                        res_b = subprocess.run(
                            [shell, '-NoProfile', '-NonInteractive', '-File', str(probe_ps_b),
                             '-Owner', 'contender-B', '-TimeoutSeconds', '0'],
                            cwd=str(sandbox_b), capture_output=True, text=True, timeout=15
                        )
                        self.assertEqual(res_b.returncode, 0)
                        self.assertIn('ACQUIRED', res_b.stdout)
                        self.assertNotIn('CLIXML', res_b.stdout + res_b.stderr)

                        # 2. Process using A's SAME module -> must be BUSY
                        res_a_busy = subprocess.run(
                            [shell, '-NoProfile', '-NonInteractive', '-File', str(probe_ps_a),
                             '-Owner', 'contender-A', '-TimeoutSeconds', '0'],
                            cwd=str(sandbox_a), capture_output=True, text=True, timeout=15
                        )
                        self.assertEqual(res_a_busy.returncode, 2)
                        self.assertIn('BUSY', res_a_busy.stdout)
                        self.assertNotIn('CLIXML', res_a_busy.stdout + res_a_busy.stderr)

                    finally:
                        primary_exc = sys.exc_info()[1]
                        try:
                            release_file.write_text('RELEASE', encoding='utf-8')
                        except Exception:
                            pass
                        if not rec_holder['waited']:
                            # Mark the single settlement attempt BEFORE the call so the
                            # tracker never waits on this handle again (no [15, 15] retry),
                            # even if communicate raises.
                            rec_holder['waited'] = True
                            try:
                                stdout_h, stderr_h = p_holder.communicate(timeout=15)
                            except Exception:
                                # Completion is unproven: retain the sandbox. Preserve the
                                # original contention-body failure as the primary exception;
                                # only surface this cleanup failure when the body succeeded.
                                tracker.retained_sandboxes.add(rec_holder['sandbox'])
                                if primary_exc is None:
                                    raise

                    self.assertEqual(p_holder.returncode, 0)
                    self.assertIn('HOLDER_RELEASED = PASS', stdout_h)
                    self.assertNotIn('CLIXML', stdout_h + stderr_h)
                    self.assertEqual(stderr_h.strip(), '')

                    # 3. After normal release, process using A's SAME module must ACQUIRE successfully
                    res_a_post = subprocess.run(
                        [shell, '-NoProfile', '-NonInteractive', '-File', str(probe_ps_a),
                         '-Owner', 'contender-A-post', '-TimeoutSeconds', '5'],
                        cwd=str(sandbox_a), capture_output=True, text=True, timeout=15
                    )
                    self.assertEqual(res_a_post.returncode, 0)
                    self.assertIn('ACQUIRED', res_a_post.stdout)
                    self.assertNotIn('CLIXML', res_a_post.stdout + res_a_post.stderr)

                    failed = False
                finally:
                    tracker.settle_and_cleanup(failed=failed)

    def test_operation_lock_lifecycle_fake_process_failure_settlement_and_retention(self):
        from unittest.mock import patch

        # 1. Spawn failure on second process: first process must be awaited and sandbox retained
        handles_1 = []
        class FakeProcessSpawnFail:
            returncode = None
            def __init__(self, args, cwd):
                self.args = args
                self.cwd = cwd
                self.waited = False
                handles_1.append(self)
            def communicate(self, timeout=None):
                self.waited = True
                raise subprocess.TimeoutExpired(self.args, timeout)
            def poll(self):
                return None

        calls_1 = []
        def fake_popen_spawn_fail(args, **kwargs):
            calls_1.append(args)
            if len(calls_1) == 2:
                raise OSError('synthetic second spawn failure; ZERO PROCESSES')
            return FakeProcessSpawnFail(args, kwargs['cwd'])

        with patch('subprocess.Popen', side_effect=fake_popen_spawn_fail):
            with self.assertRaises(OSError):
                tracker_1 = TestProcessTracker()
                failed_1 = True
                try:
                    s_a = tracker_1.create_sandbox(prefix='v213-fake-spawn-a-')
                    s_b = tracker_1.create_sandbox(prefix='v213-fake-spawn-b-')
                    p_a = subprocess.Popen(['fake', 'a'], cwd=str(s_a))
                    rec_a = tracker_1.register(p_a, s_a, 30.0)
                    p_b = subprocess.Popen(['fake', 'b'], cwd=str(s_b))
                    rec_b = tracker_1.register(p_b, s_b, 30.0)
                    failed_1 = False
                finally:
                    tracker_1.settle_and_cleanup(failed=failed_1)

        self.assertEqual(len(handles_1), 1)
        self.assertTrue(handles_1[0].waited, 'First process was not awaited on second spawn failure')
        self.assertTrue(Path(handles_1[0].cwd).exists(), 'Sandbox was deleted beneath live child')
        shutil.rmtree(handles_1[0].cwd, ignore_errors=True)
        shutil.rmtree(s_b, ignore_errors=True)

        # 2. First communicate timeout: second process must be awaited and both sandboxes retained
        handles_2 = []
        class FakeProcessCommTimeout:
            returncode = None
            def __init__(self, args, cwd):
                self.args = args
                self.cwd = cwd
                self.waited = False
                handles_2.append(self)
            def communicate(self, timeout=None):
                self.waited = True
                raise subprocess.TimeoutExpired(self.args, timeout)
            def poll(self):
                return None

        def fake_popen_comm_timeout(args, **kwargs):
            return FakeProcessCommTimeout(args, kwargs['cwd'])

        with patch('subprocess.Popen', side_effect=fake_popen_comm_timeout):
            with self.assertRaises(subprocess.TimeoutExpired):
                tracker_2 = TestProcessTracker()
                failed_2 = True
                try:
                    s_a = tracker_2.create_sandbox(prefix='v213-fake-comm-a-')
                    s_b = tracker_2.create_sandbox(prefix='v213-fake-comm-b-')
                    p_a = subprocess.Popen(['fake', 'a'], cwd=str(s_a))
                    rec_a = tracker_2.register(p_a, s_a, 30.0)
                    p_b = subprocess.Popen(['fake', 'b'], cwd=str(s_b))
                    rec_b = tracker_2.register(p_b, s_b, 30.0)
                    try:
                        p_a.communicate(timeout=30)
                    finally:
                        rec_a['waited'] = True
                    try:
                        p_b.communicate(timeout=30)
                    finally:
                        rec_b['waited'] = True
                    failed_2 = False
                finally:
                    tracker_2.settle_and_cleanup(failed=failed_2)

        self.assertEqual(len(handles_2), 2)
        self.assertTrue(handles_2[0].waited, 'Process A was not awaited')
        self.assertTrue(handles_2[1].waited, 'Process B was not settled on Process A timeout')
        self.assertTrue(Path(handles_2[0].cwd).exists(), 'Sandbox A was deleted on timeout')
        self.assertTrue(Path(handles_2[1].cwd).exists(), 'Sandbox B was deleted on timeout')
        shutil.rmtree(handles_2[0].cwd, ignore_errors=True)
        shutil.rmtree(handles_2[1].cwd, ignore_errors=True)

        # 3. Normal completion ordering: both processes awaited and sandboxes cleaned up
        handles_3 = []
        class FakeProcessSuccess:
            returncode = 0
            def __init__(self, args, cwd):
                self.args = args
                self.cwd = cwd
                self.waited = False
                handles_3.append(self)
            def communicate(self, timeout=None):
                self.waited = True
                return 'PASS', ''
            def poll(self):
                return 0

        def fake_popen_success(args, **kwargs):
            return FakeProcessSuccess(args, kwargs['cwd'])

        with patch('subprocess.Popen', side_effect=fake_popen_success):
            tracker_3 = TestProcessTracker()
            failed_3 = True
            try:
                s_a = tracker_3.create_sandbox(prefix='v213-fake-succ-a-')
                s_b = tracker_3.create_sandbox(prefix='v213-fake-succ-b-')
                p_a = subprocess.Popen(['fake', 'a'], cwd=str(s_a))
                rec_a = tracker_3.register(p_a, s_a, 30.0)
                p_b = subprocess.Popen(['fake', 'b'], cwd=str(s_b))
                rec_b = tracker_3.register(p_b, s_b, 30.0)
                try:
                    p_a.communicate(timeout=30)
                finally:
                    rec_a['waited'] = True
                try:
                    p_b.communicate(timeout=30)
                finally:
                    rec_b['waited'] = True
                failed_3 = False
            finally:
                tracker_3.settle_and_cleanup(failed=failed_3)

        self.assertEqual(len(handles_3), 2)
        self.assertTrue(handles_3[0].waited)
        self.assertTrue(handles_3[1].waited)
        self.assertFalse(s_a.exists(), 'Sandbox A should have been cleaned up on success')
        self.assertFalse(s_b.exists(), 'Sandbox B should have been cleaned up on success')

        # 4. End-to-end method run with fake Popen on test_operation_lock_independent_concurrency_and_contention
        for mode in ('second_spawn_error', 'first_communicate_timeout'):
            calls_4 = []
            handles_4 = []
            class FakeLifecycleProcess:
                returncode = None
                def __init__(self, args, cwd):
                    self.args = args
                    self.cwd = cwd
                    self.waited = False
                    handles_4.append(self)
                def communicate(self, timeout=None):
                    self.waited = True
                    raise subprocess.TimeoutExpired(self.args, timeout)
                def poll(self):
                    return None

            def fake_popen_4(args, **kwargs):
                calls_4.append(args)
                if mode == 'second_spawn_error' and len(calls_4) % 2 == 0:
                    raise OSError('synthetic second spawn failure')
                return FakeLifecycleProcess(args, kwargs['cwd'])

            stream = io.StringIO()
            # Both shells resolve whatever the host PATH holds (the gate's has neither), so the fake-only run never skips.
            with patch.object(subprocess, 'Popen', side_effect=fake_popen_4), \
                    patch.object(shutil, 'which', side_effect=lambda name, *a, **k: name if name in ('powershell.exe', 'pwsh') else None):
                suite = unittest.TestSuite([
                    CurrentReleaseLaneTests('test_operation_lock_independent_concurrency_and_contention')
                ])
                runner = unittest.TextTestRunner(stream=stream)
                result = runner.run(suite)

            self.assertFalse(result.wasSuccessful())
            self.assertTrue(len(handles_4) > 0)
            self.assertTrue(all(h.waited for h in handles_4), f"Not all handles waited in {mode}")
            self.assertTrue(all(Path(h.cwd).exists() for h in handles_4), f"Not all sandboxes retained in {mode}")
            for h in handles_4:
                shutil.rmtree(h.cwd, ignore_errors=True)

    def test_operation_lock_holder_finally_preserves_primary_and_settles_once(self):
        # Durable ZERO-PROCESS proof that a failed contention body which is followed
        # by a holder settlement that ALSO fails preserves the original body
        # exception, attempts the holder communicate exactly once (no duplicate
        # 15s wait), accounts for every owned handle, and retains the affected
        # sandboxes because holder completion is unproven. Independent basis:
        # _archive/session-20260930-options-global/lock-isolation-r2-astra.holder-failure.py
        # (which captured the pre-fix bad behavior); this asserts the repaired
        # behavior, never a passing copy of the bad behavior.
        from unittest.mock import patch

        primary = OSError('PRIMARY synthetic contender failure; ZERO NATIVE PROCESSES')
        handles = []

        class FakeHolderProofProcess:
            def __init__(self, args, cwd):
                self.args = args
                self.cwd = cwd
                self.calls = []
                self.waited_at_call = []
                self.holder = Path(args[args.index('-File') + 1]).name == 'orchestrate_hold.ps1'
                self.returncode = None if self.holder else 0
                if self.holder:
                    Path(args[args.index('-ReadyFile') + 1]).write_text('HELD')
                handles.append(self)

            def communicate(self, timeout=None):
                self.calls.append(timeout)
                if self.holder:
                    caller_record = sys._getframe(1).f_locals.get('rec_holder')
                    self.waited_at_call.append(
                        None if caller_record is None else caller_record['waited'])
                    raise subprocess.TimeoutExpired(self.args, timeout)
                return 'V213_OPERATION_LOCK_SELF_TEST = PASS', ''

            def poll(self):
                return self.returncode

        observed = []

        class RecordingResult(unittest.TestResult):
            def addSubTest(self, test, subtest, err):
                if err is not None:
                    exc = err[1]
                    observed.append({
                        'shell': subtest.params['shell'],
                        'exception': type(exc).__name__,
                        'primary_is_propagated': exc is primary,
                        'primary_in_context_only': exc.__context__ is primary,
                    })
                super().addSubTest(test, subtest, err)

        # Fail closed if any real native process is reached while this proof is armed.
        # Installed at most once per class; a no-op whenever disarmed, so it never
        # interferes with the sibling tests that spawn real PowerShell hosts.
        armed = getattr(type(self), '_holder_proof_armed', None)
        if armed is None:
            armed = {'on': False}

            def _reject_native(event, event_args, _armed=armed):
                if _armed['on'] and event == 'subprocess.Popen':
                    raise AssertionError('NO NATIVE PROCESSES permitted in holder-failure proof')

            sys.addaudithook(_reject_native)
            type(self)._holder_proof_armed = armed

        armed['on'] = True
        try:
            with patch.object(subprocess, 'Popen',
                              side_effect=lambda args, **kw: FakeHolderProofProcess(args, kw['cwd'])), \
                    patch.object(subprocess, 'run', side_effect=primary), \
                    patch.object(shutil, 'which', side_effect=lambda name, *a, **k: name if name in ('powershell.exe', 'pwsh') else None):
                # Both shells resolve whatever the host PATH holds (the gate's has neither), so the proof never skips.
                CurrentReleaseLaneTests(
                    'test_operation_lock_independent_concurrency_and_contention'
                ).run(RecordingResult())
        finally:
            armed['on'] = False

        holders = [h for h in handles if h.holder]
        # Both parent hosts (powershell.exe and pwsh) must have surfaced the ORIGINAL
        # OSError, not the secondary cleanup TimeoutExpired.
        self.assertEqual(len(observed), 2)
        self.assertEqual(len(holders), 2)
        for entry in observed:
            self.assertEqual(entry['exception'], 'OSError')
            self.assertTrue(entry['primary_is_propagated'], entry)
            self.assertFalse(entry['primary_in_context_only'], entry)
        # Holder communicate attempted EXACTLY once (no [15, 15] duplicate wait).
        for holder in holders:
            self.assertEqual(holder.calls, [15])
            # The settlement attempt is marked BEFORE communicate is entered.
            self.assertEqual(holder.waited_at_call, [True])
        # Every owned handle is accounted for (each was communicated at least once).
        self.assertTrue(all(h.calls for h in handles), [h.calls for h in handles])
        # Sandboxes retained because holder completion is unproven.
        self.assertTrue(all(Path(h.cwd).exists() for h in handles))
        for h in handles:
            shutil.rmtree(h.cwd, ignore_errors=True)

    def test_actual_validator_rejects_dirty_checkout_before_bootstrap(self):
        shells = [shell for shell in ('powershell.exe', 'pwsh') if shutil.which(shell)]
        if not shells or not shutil.which('git'):
            self.skipTest('PowerShell and Git required for actual caller regression')
        with tempfile.TemporaryDirectory(prefix='r75-dirty-check-') as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', directory], check=True, capture_output=True)
            subprocess.run(['git', '-c', 'user.name=Synthetic', '-c', 'commit.gpgsign=false',
                            '-c', 'core.hooksPath=nonexistent-synthetic-hooks', '-c',
                            'user.email=synthetic@example.invalid', 'commit', '-q',
                            '--allow-empty', '-m', 'synthetic checkout'], cwd=root,
                           check=True, capture_output=True)
            (root / 'untracked.txt').write_text('synthetic dirty source', encoding='utf-8')
            for shell in shells:
                result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-File',
                                         str(ROOT / 'scripts/ci_v213_r75_validate.ps1'),
                                         '-ProjectRoot', directory, '-SkipLiveRefresh'],
                                        capture_output=True, text=True, errors='replace', timeout=30,
                                        env={**os.environ, 'GITHUB_SHA': ''})
                with self.subTest(shell=shell):
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('R75 validation requires a clean exact checkout',
                                  result.stdout + result.stderr)
                    self.assertFalse(list(root.glob('**/*Receipt.json')))

    def test_staged_source_scope_is_explicit_not_a_blanket_exception(self):
        validator = (ROOT / 'scripts/ci_v213_r75_free_relay_validate.ps1').read_text()
        for path in ('scripts/adapters/staged_public.py', 'scripts/fetch_public_source_observations.py',
                     'tests/test_current_release_lane.py'):
            self.assertIn("'" + path + "'", validator)
        for wildcard in ("'scripts/*'", "'tests/*'", "'state/*'"):
            self.assertNotIn(wildcard, validator)
        self.assertIn("'cloud/src/qa.ts'", validator)
        self.assertIn('FREE_RELAY changed protected R75 source', validator)


if __name__ == '__main__':
    unittest.main()
