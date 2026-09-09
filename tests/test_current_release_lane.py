from pathlib import Path
import re
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CurrentReleaseLaneTests(unittest.TestCase):
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
        frozen = subprocess.check_output(['git', '-C', str(ROOT), 'show', baseline + ':' + relative])
        self.assertEqual((ROOT / relative).read_bytes(), frozen)
        self.assertIn('from "./activation-v3"', (ROOT / 'cloud/src/v213/production-worker.ts').read_text())
        for path in (ROOT / 'cloud/src').rglob('*.ts'):
            self.assertNotRegex(path.read_text(encoding='utf-8-sig'), r'''(?:from\s*|(?:import|require)\s*\(\s*)["'][^"']*activation-v2["']''', str(path))

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

    def test_operation_lock_actual_callers_have_no_clixml_progress(self):
        shells = [shell for shell in ('powershell.exe', 'pwsh') if shutil.which(shell)]
        if not shells:
            self.skipTest('PowerShell required for actual caller regression')
        for shell in shells:
            result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-File',
                                     str(ROOT / 'scripts/test_v213_operation_lock.ps1'),
                                     '-ProjectRoot', str(ROOT)], capture_output=True, text=True,
                                    errors='replace', timeout=30)
            with self.subTest(shell=shell):
                self.assertEqual(result.returncode, 0)
                self.assertIn('V213_OPERATION_LOCK_SELF_TEST = PASS', result.stdout)
                self.assertNotIn('CLIXML', result.stdout + result.stderr)
                self.assertEqual(result.stderr.strip(), '')

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
