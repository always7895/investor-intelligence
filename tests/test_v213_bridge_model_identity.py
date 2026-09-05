"""Exercise actual bridge functions without executing its deployment/main body."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell bridge')
class BridgeModelIdentityTests(unittest.TestCase):
    def test_ps51_and_ps7_share_alias_and_completed_marker_validation(self):
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        script = r'''
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$ProjectRoot=ROOT_VALUE
$python=PYTHON_VALUE
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $ProjectRoot 'scripts/run_v213_local_llm_bridge_core.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'BRIDGE_PARSE_FAILED'}
$names=@('Get-ObjectPropertyValue','Invoke-SharedModelIdentity','Resolve-Model','Test-SelectedModelRoute')
$functions=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $names -contains $node.Name},$true))
if($functions.Count-ne4){throw 'FUNCTION_INVENTORY_MISMATCH'}
foreach($function in $functions){. ([scriptblock]::Create($function.Extent.Text))}
function Read-ModelSelection { return $null }
function Get-ModelCatalog { param($Base) return $script:Catalog }
function Invoke-RestMethod {
 param($Method,$Uri,$ContentType,$Body,$TimeoutSec)
 if($Uri-cne'http://127.0.0.1:1/v1/chat/completions'){throw 'UNEXPECTED_ENDPOINT'}
 $request=[Text.Encoding]::UTF8.GetString([byte[]]$Body)|ConvertFrom-Json
 if($request.model-cne'qwen38-q6'-or$request.max_tokens-ne32-or$request.chat_template_kwargs.enable_thinking-ne$false){throw 'PROBE_REQUEST_INVALID'}
 return $script:Response
}
$preferredModel='qwen38-q6'
$canonical='canonical-q6-測試'
$script:Catalog=@([pscustomobject]@{id=$canonical;aliases=@('qwen38-q6')})
$resolved=Resolve-Model 'http://127.0.0.1:1' 'qwen38-q6'
if($resolved.model-cne'qwen38-q6'-or$resolved.canonical_model-cne$canonical){throw ('ALIAS_IDENTITY_MISMATCH; synthetic_actual='+($resolved|ConvertTo-Json -Compress))}
$script:Response=@{model=$canonical;choices=@(@{finish_reason='stop';message=@{content='R75_FREE_RELAY_E2E_OK'}})}
Test-SelectedModelRoute 'http://127.0.0.1:1' 'qwen38-q6' $script:Catalog
foreach($bad in @(
 @{model='wrong';choices=@(@{finish_reason='stop';message=@{content='R75_FREE_RELAY_E2E_OK'}})},
 @{model=$canonical;choices=@(@{finish_reason='length';message=@{content='R75_FREE_RELAY_E2E_OK'}})},
 @{model=$canonical;choices=@(@{finish_reason='stop';message=@{content=''}})},
 @{model=$canonical;choices=@(@{finish_reason='stop';message=@{content='wrong marker'}})}
)){
 $script:Response=$bad; $failed=$false
 try{Test-SelectedModelRoute 'http://127.0.0.1:1' 'qwen38-q6' $script:Catalog}catch{$failed=$true}
 if(-not$failed){throw 'INVALID_COMPLETION_ACCEPTED'}
}
$script:Catalog+=@([pscustomobject]@{id='other';aliases=@('QWEN38-Q6')})
$failed=$false
try{$null=Resolve-Model 'http://127.0.0.1:1' 'qwen38-q6'}catch{$failed=$true}
if(-not$failed){throw 'AMBIGUOUS_ALIAS_ACCEPTED'}
Write-Output 'BRIDGE_SHARED_IDENTITY=PASS; no_network=true; no_mutation=true'
'''.replace('ROOT_VALUE', quote(ROOT)).replace('PYTHON_VALUE', quote(sys.executable))
        with tempfile.TemporaryDirectory(prefix='Bridge 身分 (1) ') as directory:
            path = Path(directory) / 'check.ps1'
            path.write_text(script, encoding='utf-8-sig')
            for shell in ('powershell.exe', 'pwsh'):
                self.assertIsNotNone(shutil.which(shell), shell)
                result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-File', str(path)], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=45)
                with self.subTest(shell=shell):
                    self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-2500:])
                    self.assertIn('BRIDGE_SHARED_IDENTITY=PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
