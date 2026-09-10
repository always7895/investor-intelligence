"""Actual PowerShell recovery caller; synthetic transport only, no Production."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class JournalReconciliationTests(unittest.TestCase):
    def test_confirmed_recovery_preserves_failure_and_refuses_bad_ack(self):
        shells = [shutil.which(name) for name in ('powershell.exe', 'pwsh')]
        if not all(shells):
            self.skipTest('Windows PowerShell5.1/7 required')
        for shell in shells:
            for case in ('unconfirmed', 'not_committed', 'rolled_back', 'bad_identity', 'bad_restore', 'transport'):
                with self.subTest(shell=shell, case=case), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    journals = root / 'InvestorIntelligence/status/sealed-publication'
                    journals.mkdir(parents=True)
                    journal = journals / 'failed.json'
                    original = json.dumps(dict(schema_version=1, status='FAIL', publication_state='UNKNOWN',
                        remote_sync_attempted=True, production_mutation=None, error_type='RuntimeException',
                        recorded_utc='2026-09-09T00:00:00Z', transaction_id='a'*32,
                        run_id='20260909T000000Z-123456789abc')).encode()
                    journal.write_bytes(original)
                    (root / 'sync-v213-activation-bundle.ps1').write_text('''param($Action,$ProjectRoot,$LocalConfigPath,$TransactionId,$RunId,$ResultPath)
if($Action-cne'Rollback'){throw 'UNEXPECTED_MUTATION'}
Add-Content -LiteralPath (Join-Path $ProjectRoot 'calls.txt') $Action
if($env:CASE-eq'transport'){exit 7}
$r=@{status='not_committed';transaction_id=$TransactionId;run_id=$RunId}
if($env:CASE-in@('rolled_back','bad_restore')){$r.status='rolled_back';$r.exact_pointer_restored=($env:CASE-eq'rolled_back')}
if($env:CASE-eq'bad_identity'){$r.transaction_id='b'*32}
$r|ConvertTo-Json|Set-Content -LiteralPath $ResultPath -Encoding utf8
exit 0
''', encoding='utf-8-sig')
                    helper = str(ROOT / 'scripts/v213_sealed_refresh.ps1').replace("'", "''")
                    (root / 'test.ps1').write_text('''$ErrorActionPreference='Stop'
. 'HELPER'
$path=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence/status/sealed-publication/failed.json'
try {
 $null=Resolve-V213SealedRefreshJournal -ProjectRoot $PSScriptRoot -JournalPath $path -LocalConfigPath 'synthetic' -ConfirmRollbackReconciliation:($env:CASE-ne'unconfirmed')
}catch{}
if($env:CASE-in@('not_committed','rolled_back')){
 try {$null=Resolve-V213SealedRefreshJournal -ProjectRoot $PSScriptRoot -JournalPath $path -LocalConfigPath 'synthetic' -ConfirmRollbackReconciliation}catch{}
}
'''.replace('HELPER', helper), encoding='utf-8-sig')
                    result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-File', str(root/'test.ps1')],
                        env=dict(os.environ, LOCALAPPDATA=str(root), CASE=case), capture_output=True,
                        encoding='utf-8', errors='replace', timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    value = json.loads(journal.read_text(encoding='utf-8-sig'))
                    self.assertEqual(value['status'], 'FAIL')
                    self.assertEqual(value['error_type'], 'RuntimeException')
                    self.assertEqual(value['recorded_utc'], '2026-09-09T00:00:00Z')
                    calls = root/'calls.txt'
                    self.assertEqual(calls.read_text().splitlines() if calls.exists() else [],
                        [] if case == 'unconfirmed' else ['Rollback'])
                    if case in ('not_committed', 'rolled_back'):
                        self.assertEqual(value['publication_state'], case.upper())
                        self.assertEqual(Path(value['reconciliation']['original_archive']).read_bytes(), original)
                        self.assertEqual(value['production_mutation'], True if case == 'rolled_back' else None)
                    else:
                        self.assertEqual(journal.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
