"""Actual isolated installer callers; synthetic PE/legacy markers are not release proof."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALLERS = ('install-v213-runtime.ps1', 'install-v213-source-diverse-runtime.ps1',
              'install-v213-source-diverse-runtime-v2.ps1', 'install-v213-serenity-latest-runtime.ps1')


@unittest.skipUnless(os.name == 'nt', 'actual Windows installers')
class InstallerModelAuthorityTests(unittest.TestCase):
    def test_actual_packager_rejects_metadata_selection_or_false_qualification(self):
        text = (ROOT / 'scripts/ci_v213_r75_free_relay_package.ps1').read_text(encoding='utf-8')
        start = text.index('            foreach($metadataPath in @(')
        block = text[start:text.index("            Write-Host 'V213_PACKAGED_RUNTIME_INSTALL", start)]
        valid = dict(preferred_model=None, model_selection_authority='runtime_model_profile', model_profile_qualified=False)
        changes = ({}, {'preferred_model': 'RVN-Q6'}, {'preferred_model': []},
                   {'model_profile_qualified': True}, {'model_profile_qualified': 'false'},
                   {'model_profile_qualified': [False]}, {'model_selection_authority': ['runtime_model_profile']})
        for shell in ('powershell.exe', 'pwsh.exe'):
            if not shutil.which(shell): continue
            with tempfile.TemporaryDirectory(prefix='metadata gate ') as directory:
                parent = Path(directory)
                local = parent / 'local/InvestorIntelligence/v213-runtime-state.json'
                runtime = parent / 'runtime/V213-SOURCE-DIVERSE-RUNTIME.json'
                local.parent.mkdir(parents=True); runtime.parent.mkdir(parents=True)
                for change in changes:
                    for bad_path in (local, runtime):
                        local.write_text(json.dumps(valid)); runtime.write_text(json.dumps(valid))
                        bad_path.write_text(json.dumps({**valid, **change}))
                        command = "$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;$installProbe=$env:TEST_INSTALL_PROBE;$env:LOCALAPPDATA=Join-Path $installProbe 'local';" + block
                        result = subprocess.run([shell, '-NoProfile', '-Command', command],
                            env={**{k:v for k,v in os.environ.items() if k.casefold() != 'psmodulepath'}, 'TEST_INSTALL_PROBE': str(parent)},
                            capture_output=True, timeout=15)
                        self.assertEqual(result.returncode == 0, not change, result.stdout + result.stderr)

    def test_installers_do_not_select_model_or_certify_profile(self):
        with tempfile.TemporaryDirectory(prefix='installer authority ') as directory:
            parent = Path(directory)
            source = parent / 'source'; source.mkdir()
            tracked = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z']).decode().split('\0')
            for relative in tracked:
                if not relative or relative.startswith(('.github/', 'state/', 'tests/')):
                    continue
                path = ROOT / relative
                if path.suffix.lower() not in ('.ps1', '.py', '.json', '.md'):
                    continue
                target = source / relative; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            (source / 'InvestorIntelligence.exe').write_bytes(b'MZ_SYNTHETIC_NEVER_EXECUTED')
            (source / 'HOTFIX-REFS.json').write_text(json.dumps(dict(artifact_kind='R75_FREE_WORKERS_RELAY_HOTFIX',
                package_version='2.1.3', source_commit='a'*40, workflow_run_id='12345', production_mutation_by_ci=False)))
            profile_path = source / 'config/v213-model-profile-v1.json'
            original_profile = profile_path.read_bytes()
            activation_path = source / 'activate-v213-seven-field-schedule.ps1'
            original_activation = activation_path.read_bytes()
            for shell in ('powershell.exe', 'pwsh.exe'):
                if not shutil.which(shell): continue
                for index, installer in enumerate(INSTALLERS):
                    with self.subTest(shell=shell, installer=installer):
                        # Retained legacy installer needs its historical contract, not relaxed R75 markers.
                        activation_path.write_bytes(original_activation)
                        if 'serenity-latest' in installer:
                            activation_path.write_text('# Synthetic read-only contract markers; never execute\n' + '\n'.join((
                                'V213_DIVERSIFIED_SOURCE_PREFLIGHT', 'V213_SOURCE_INDEPENDENCE_PREFLIGHT',
                                'V213_MARKET_CORROBORATION_QUALITY = DEGRADED', 'market_corroboration_status',
                                'health-schema-v2', 'install-v213-source-diverse-runtime.ps1', 'rollback',
                                'activate-v213-seven-field-schedule-core.ps1')))
                        target = parent / f'{shell}-{index}'
                        local = target / 'local'; runtime = target / 'runtime'
                        user = local / 'InvestorIntelligence/UserData/config/model-profile-v1.json'
                        user.parent.mkdir(parents=True)
                        operator = b'{"synthetic_operator_sentinel":true}'
                        user.write_bytes(operator)
                        result = subprocess.run([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                            str(source / installer), '-ProjectRoot', str(source), '-RuntimeRoot', str(runtime)],
                            env={**{k: v for k, v in os.environ.items() if k.casefold() != 'psmodulepath'},
                                 'LOCALAPPDATA': str(local), 'V213_MODEL_PROFILE_JSON': 'synthetic-unqualified-override'},
                            capture_output=True, timeout=60)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertEqual(user.read_bytes(), operator)
                        self.assertEqual(profile_path.read_bytes(), original_profile)
                        self.assertEqual((runtime / 'config/v213-model-profile-v1.json').read_bytes(), original_profile)
                        receipts = [local / 'InvestorIntelligence/v213-runtime-state.json']
                        receipts += [p for p in (runtime / 'V213-SOURCE-DIVERSE-RUNTIME.json',
                                                runtime / 'V213-SERENITY-LATEST-RUNTIME.json') if p.exists()]
                        for receipt in receipts:
                            data = json.loads(receipt.read_text(encoding='utf-8-sig'))
                            self.assertIn('preferred_model', data)
                            self.assertIsNone(data['preferred_model'], receipt.name)
                            self.assertEqual(data.get('model_selection_authority'), 'runtime_model_profile')
                            self.assertIs(data.get('model_profile_qualified'), False)


if __name__ == '__main__': unittest.main()
