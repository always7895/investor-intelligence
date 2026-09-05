"""Real PS orchestration with synthetic files and transport; no remote calls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SealedRefreshTests(unittest.TestCase):
    def test_transaction_and_failure_journals_on_both_windows_hosts(self):
        shells = [shutil.which(x) for x in ('powershell.exe', 'pwsh')]
        if not all(shells):
            self.skipTest('Both Windows PowerShell hosts required')
        for shell in shells:
            for case, state, actions in (
                ('pass', 'FINALIZED', ['Commit', 'Finalize']),
                ('preflight', 'NOT_ATTEMPTED', []),
                ('readback', 'ROLLED_BACK', ['Commit', 'Rollback']),
                ('boolean', 'ROLLED_BACK', ['Commit', 'Rollback']),
                ('identity_boolean', 'ROLLED_BACK', ['Commit', 'Rollback']),
                ('status_boolean', 'ROLLED_BACK', ['Commit', 'Rollback']),
                ('finalize', 'ROLLED_BACK', ['Commit', 'Finalize', 'Rollback']),
                ('rollback', 'UNKNOWN', ['Commit', 'Finalize', 'Rollback']),
            ):
                with self.subTest(shell=shell, case=case), tempfile.TemporaryDirectory() as temp:
                    folder = Path(temp) / 'synthetic (1) 版本'
                    (folder / 'data/cache').mkdir(parents=True)
                    (folder / 'cloud/node_modules/.bin').mkdir(parents=True)
                    bundle = {'run_id': '20260905T180113Z-4a4132a50a46', 'transaction_id': 'a' * 32}
                    (folder / 'data/cache/v213_activation_bundle_upload.json').write_text(json.dumps(bundle), encoding='utf-8')
                    (folder / 'cloud/node_modules/.bin/wrangler.cmd').write_text('@echo off\r\nexit /b 0\r\n')
                    (folder / 'activate-v213-seven-field-schedule.ps1').write_text("param($ProjectRoot,[switch]$PreflightOnly,$FieldLocale)\nif(-not$PreflightOnly){throw 'mutation requested'}\nif($env:FIXTURE_CASE-eq'preflight'){exit 7}\nexit 0\n", encoding='utf-8-sig')
                    (folder / 'sync-v213-activation-bundle.ps1').write_text("""param($Action,$ProjectRoot,$BundlePath,$ExpectedBundleSha256,$LocalConfigPath,$ResultPath,$TransactionId,$RunId)
Add-Content -LiteralPath (Join-Path $ProjectRoot 'actions.txt') $Action
if($Action-eq'Commit'){
 $b=Get-Content -LiteralPath $BundlePath -Raw|ConvertFrom-Json
 if((Get-FileHash -LiteralPath $BundlePath).Hash.ToLowerInvariant()-cne$ExpectedBundleSha256){throw 'wrong sealed bytes'}
 $r=@{transaction_id=$b.transaction_id;run_id=$b.run_id;status='accepted';pointer_written_last=$true;object_count=7;objects_read_back=7;rollback_available=$true}
 if($env:FIXTURE_CASE-eq'readback'){$r.objects_read_back=6}
 if($env:FIXTURE_CASE-eq'boolean'){$r.pointer_written_last='True'}
 if($env:FIXTURE_CASE-eq'identity_boolean'){$r.transaction_id=$true;$r.run_id=$true}
 if($env:FIXTURE_CASE-eq'status_boolean'){$r.status=$true}
}elseif($Action-eq'Finalize'){
 if($env:FIXTURE_CASE-in@('finalize','rollback')){exit 8}
 $r=@{transaction_id=$TransactionId;run_id=$RunId;status='finalized';rollback_handle_deleted=$true}
}else{
 if($env:FIXTURE_CASE-eq'rollback'){exit 9}
 $r=@{transaction_id=$TransactionId;run_id=$RunId;status='rolled_back';exact_pointer_restored=$true}
}
$r|ConvertTo-Json|Set-Content -LiteralPath $ResultPath -Encoding utf8
exit 0
""", encoding='utf-8-sig')
                    helper = str(ROOT / 'scripts/v213_sealed_refresh.ps1').replace("'", "''")
                    runner = folder / 'runner.ps1'
                    runner.write_text("""$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
. 'HELPER'
$preference=Join-Path $PSScriptRoot 'preference.json'
if(Get-V213SealedPublicationPreference -Path $preference){throw 'missing preference enabled publication'}
foreach($flag in @($false,$true)){
 @{sealed_publication_enabled=$flag}|ConvertTo-Json|Set-Content -LiteralPath $preference
 if((Get-V213SealedPublicationPreference -Path $preference)-ne$flag){throw 'preference not preserved'}
}
@{sealed_publication_enabled='false'}|ConvertTo-Json|Set-Content -LiteralPath $preference
try{$null=Get-V213SealedPublicationPreference -Path $preference;throw 'string preference accepted'}catch{if($_.Exception.Message-eq'string preference accepted'){throw}}
try {$null=Invoke-V213SealedRefresh -ProjectRoot $PSScriptRoot -LocalConfigPath 'synthetic-only'}catch{}
if($env:FIXTURE_CASE-eq'rollback'){
 try{$null=Invoke-V213SealedRefresh -ProjectRoot $PSScriptRoot -LocalConfigPath 'synthetic-only';throw 'unresolved journal accepted'}catch{if($_.Exception.Message-eq'unresolved journal accepted'){throw}}
}
""".replace('HELPER', helper), encoding='utf-8-sig')
                    env = dict(os.environ, LOCALAPPDATA=str(folder), FIXTURE_CASE=case)
                    result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-File', str(runner)], env=env,
                                            capture_output=True, encoding='utf-8', errors='replace', timeout=45)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    journals = list((folder / 'InvestorIntelligence/status/sealed-publication').glob('*.json'))
                    self.assertTrue(journals, result.stdout + result.stderr)
                    records = [json.loads(p.read_text(encoding='utf-8-sig')) for p in journals]
                    self.assertIn(state, [r['publication_state'] for r in records])
                    path = folder / 'actions.txt'
                    observed = path.read_text(encoding='utf-8-sig').splitlines() if path.exists() else []
                    self.assertEqual(observed, actions)
                    self.assertTrue(all(r['real_line_sent'] is False and r['worker_deployed'] is False for r in records))
                    if case == 'pass':
                        self.assertEqual(records[0]['status'], 'PASS')
                    else:
                        self.assertTrue(all(r['status'] == 'FAIL' for r in records))
                    if case == 'pass':
                        (folder / 'scripts').mkdir()
                        for name in ('v213_operation_lock.ps1', 'v213_windows_security.ps1', 'v213_sealed_refresh.ps1'):
                            shutil.copyfile(ROOT / 'scripts' / name, folder / 'scripts' / name)
                        (folder / 'run-v213-local.ps1').write_text("""param($ProjectRoot,[switch]$NoModelBridge,[switch]$NoTunnel,[switch]$NoSync,[switch]$NoAutoActivation)
if(-not($NoModelBridge-and$NoTunnel-and$NoSync-and$NoAutoActivation)){throw 'unsafe data job arguments'}
$run=[DateTimeOffset]::UtcNow.ToString("yyyyMMdd'T'HHmmss'Z'")+'-'+[guid]::NewGuid().ToString('N').Substring(0,12)
@{run_id=$run;transaction_id=[guid]::NewGuid().ToString('N')}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $ProjectRoot 'data/cache/v213_activation_bundle_upload.json') -Encoding utf8
exit 0
""", encoding='utf-8-sig')
                        for enabled in (False, True):
                            argv = [shell, '-NoProfile', '-NonInteractive', '-File', str(ROOT / 'run-v213-scheduled-refresh.ps1'), '-RuntimeRoot', str(folder), '-Slot', 'manual']
                            if enabled:
                                argv.append('-PublishSealedBundle')
                            process = subprocess.run(argv, env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=45)
                            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                            receipt = json.loads((folder / 'InvestorIntelligence/status/v213-r75-scheduled-refresh-manual-latest.json').read_text(encoding='utf-8-sig'))
                            self.assertEqual(receipt['status'], 'PASS')
                            self.assertEqual(receipt['remote_sync_attempted'], enabled)
                            self.assertEqual(receipt['publication_state'], 'FINALIZED' if enabled else 'NOT_ATTEMPTED')
                            self.assertFalse(receipt['model_bridge_started'])
                        self.assertEqual(path.read_text(encoding='utf-8-sig').splitlines(), ['Commit', 'Finalize', 'Commit', 'Finalize'])


if __name__ == '__main__':
    unittest.main()
