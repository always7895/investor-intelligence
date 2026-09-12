"""Parse all Git PS1 and exercise corrected guard expressions; no script entrypoints."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOSTS = [host for host in ('powershell.exe', 'pwsh.exe') if shutil.which(host)]


@unittest.skipUnless(HOSTS, 'native PowerShell unavailable')
class PowerShellSourceSyntaxTests(unittest.TestCase):
    def run_probe(self, source, host):
        with tempfile.TemporaryDirectory(prefix='ii-ps-parse-') as directory:
            probe = Path(directory) / 'probe.ps1'
            probe.write_text(source, encoding='utf-8-sig')
            return subprocess.run([host, '-NoProfile', '-NonInteractive', '-File', str(probe),
                                   '-ProjectRoot', str(ROOT)], cwd=ROOT,
                                  capture_output=True, text=True, timeout=40)

    def test_all_tracked_scripts_parse_in_each_available_host_without_execution(self):
        probe = r'''param([string]$ProjectRoot)
$ErrorActionPreference='Stop'
$paths=@(& git -C $ProjectRoot ls-files -- '*.ps1')
if($LASTEXITCODE-ne0-or$paths.Count-eq0){throw 'SOURCE_INVENTORY_UNAVAILABLE'}
$failed=@()
foreach($path in $paths){
 $tokens=$null;$errors=$null
 [void][System.Management.Automation.Language.Parser]::ParseFile((Join-Path $ProjectRoot $path),[ref]$tokens,[ref]$errors)
 if(@($errors).Count-ne0){$failed+=$path}
}
@{count=$paths.Count;failed=@($failed);executed_source_scripts=$false}|ConvertTo-Json -Compress
if($failed.Count-ne0){exit 1}
'''
        for host in HOSTS:
            with self.subTest(host=host):
                result = self.run_probe(probe, host)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                evidence = json.loads(result.stdout)
                self.assertGreaterEqual(evidence['count'], 84)
                self.assertEqual(evidence['failed'], [])
                self.assertFalse(evidence['executed_source_scripts'])

    def test_corrected_guard_expressions_keep_failure_defaults_and_limits(self):
        probe = r'''param([string]$ProjectRoot)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$count=0
foreach($name in @('audit_v213_generated_snapshot.ps1','audit_v213_generated_snapshot_v5.ps1','audit_v213_serenity_scoring_logic_v2.ps1')){
 $path=Join-Path $ProjectRoot ('scripts/'+$name)
 $tokens=$null;$errors=$null
 $ast=[System.Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)
 if(@($errors).Count-ne0){throw 'PARSE_FAILED'}
 # Load only pure scalar/guard helpers, never the file's entrypoint or data reads.
 $functions=$ast.FindAll({param($a) $a-is[System.Management.Automation.Language.FunctionDefinitionAst]-and$a.Name-in@('Require','Value','Get-Value','Integer','Num')},$true)
 foreach($f in $functions){Invoke-Expression $f.Extent.Text}
 $lines=[IO.File]::ReadAllLines($path,[Text.Encoding]::UTF8)
 $selected=@($lines|Where-Object{$_-match "^\s*Require .*'(market_conflict_ticker_count|stale_live_market_observation_count|validated_company_thesis)'"})
 if($selected.Count-eq0){throw 'GUARDS_MISSING'}
 $ticker='SYNTHETIC'
 foreach($line in $selected){
  foreach($case in @('good','bad','missing')){
   $portfolio=[pscustomobject]@{};$freshRoot=[pscustomobject]@{};$logic=[pscustomobject]@{}
   if($case-ne'missing'){
    $n=if($case-eq'good'){0}else{1}
    $portfolio|Add-Member -NotePropertyName market_conflict_ticker_count -NotePropertyValue $n
    $freshRoot|Add-Member -NotePropertyName stale_live_market_observation_count -NotePropertyValue $n
    $logic|Add-Member -NotePropertyName validated_company_thesis -NotePropertyValue ($case-ne'good')
   }
   $refused=$false
   try {Invoke-Expression $line}catch{$refused=$true}
   if($refused-ne($case-ne'good')){throw 'GUARD_SEMANTICS_CHANGED'}
   $count++
  }
 }
 if($name-eq'audit_v213_serenity_scoring_logic_v2.ps1'){
  $line=@($lines|Where-Object{$_-match '^\s*\$limitedScoreMax = \[Math\]::Max'})
  if($line.Count-ne1){throw 'MAX_EXPRESSION_MISSING'}
  $limitedScoreMax=1.0;$top=[pscustomobject]@{serenity_score=2.0}
  Invoke-Expression $line[0]
  if($limitedScoreMax-ne2.0){throw 'MAX_EXPRESSION_FAILED'}
 }
}
Write-Output ('GUARD_CASES='+$count+' SCRIPT_ENTRYPOINTS_EXECUTED=false')
'''
        for host in HOSTS:
            with self.subTest(host=host):
                result = self.run_probe(probe, host)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('GUARD_CASES=12', result.stdout)


if __name__ == '__main__':
    unittest.main()
