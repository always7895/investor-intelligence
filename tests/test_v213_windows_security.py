"""Synthetic DPAPI only; reproduce a pwsh module path inherited by WinPS5.1."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WindowsSecurityHostTests(unittest.TestCase):
    def test_sync_rejects_changed_bytes_before_readiness_or_credentials(self):
        shells = [shutil.which(s) for s in ('powershell.exe', 'pwsh')]
        if not all(shells):
            self.skipTest('Both Windows PowerShell hosts required')
        for shell in shells:
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                bundle = folder / 'bundle.json'
                bundle.write_text(json.dumps({'run_id':'20260905T180113Z-4a4132a50a46','transaction_id':'a'*32}), encoding='utf-8')
                config = folder / 'config.json'
                config.write_text(json.dumps({'public_snapshot_endpoint':'https://example.invalid/v213/admin/activation-bundle','encrypted_hmac':'SYNTHETIC_NOT_READ'}), encoding='utf-8')
                result = subprocess.run([shell,'-NoProfile','-NonInteractive','-File',str(ROOT/'sync-v213-activation-bundle.ps1'),'-ProjectRoot',str(folder),'-BundlePath',str(bundle),'-LocalConfigPath',str(config),'-ExpectedBundleSha256','0'*64], env=dict(os.environ,LOCALAPPDATA=str(folder)), capture_output=True, encoding='utf-8', errors='replace', timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('V213_ACTIVATION_BUNDLE_CHANGED_AFTER_PREFLIGHT', result.stdout + result.stderr)
                self.assertNotIn('SYNTHETIC_NOT_READ', result.stdout + result.stderr)

    def test_both_hosts_load_own_module_and_keep_contact_private(self):
        shells = [shutil.which(s) for s in ('powershell.exe', 'pwsh')]
        if not all(shells):
            self.skipTest('Windows PowerShell5.1 and PowerShell7 required')
        for shell in shells:
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp) / 'synthetic (1) 版本'
                folder.mkdir()
                script = folder / 'probe.ps1'
                helper = str(ROOT / 'scripts/v213_windows_security.ps1').replace("'", "''")
                script.write_text("""$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
. 'HELPER'
$env:SEC_CONTACT_EMAIL=''
if(Initialize-V213SecContact){throw 'missing contact accepted'}
$p=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence/UserData/config/sec-contact.local.txt'
New-Item -ItemType Directory -Force (Split-Path -Parent $p)|Out-Null
'not-protected'|Set-Content -LiteralPath $p
if(Initialize-V213SecContact){throw 'malformed contact accepted'}
$fixture='synthetic@example.invalid'
ConvertFrom-SecureString (ConvertTo-SecureString $fixture -AsPlainText -Force)|Set-Content -LiteralPath $p
$before=(Get-FileHash -LiteralPath $p).Hash
if(-not(Initialize-V213SecContact)){throw 'valid synthetic contact unavailable'}
if($env:SEC_CONTACT_EMAIL-ne$fixture){throw 'round trip differs'}
if((Get-FileHash -LiteralPath $p).Hash-ne$before){throw 'credential file mutated'}
$module=(Get-Command ConvertTo-SecureString).Module.Path
if(-not$module.StartsWith($PSHOME,[StringComparison]::OrdinalIgnoreCase)){throw 'wrong host module'}
[ordered]@{status='PASS_SYNTHETIC_HOST_SECURITY';powershell=$PSVersionTable.PSVersion.ToString();credential_mutation=$false}|ConvertTo-Json -Compress
""".replace('HELPER', helper), encoding='utf-8-sig')
                env = dict(os.environ, LOCALAPPDATA=str(folder), SEC_CONTACT_EMAIL='',
                           PSModulePath=str(Path(shells[1]).parent / 'Modules'))
                result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-File', str(script)],
                                        env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=45)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('synthetic@example.invalid', result.stdout + result.stderr)
                receipt = json.loads(result.stdout.strip().splitlines()[-1])
                self.assertEqual(receipt['status'], 'PASS_SYNTHETIC_HOST_SECURITY')
                self.assertFalse(receipt['credential_mutation'])


if __name__ == '__main__':
    unittest.main()
