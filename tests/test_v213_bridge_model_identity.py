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
$names=@('Get-ObjectPropertyValue','Invoke-SharedModelIdentity','Resolve-Model','Test-SelectedModelRoute','Get-RuntimeModelProfile')
$functions=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $names -contains $node.Name},$true))
if($functions.Count-ne5){throw 'FUNCTION_INVENTORY_MISMATCH'}
foreach($function in $functions){. ([scriptblock]::Create($function.Extent.Text))}
function Read-ModelSelection { return $null }
function Get-ModelCatalog { param($Base) return $script:Catalog }
Remove-Item Env:V213_MODEL_PROFILE_JSON -ErrorAction SilentlyContinue
$script:ProfileActive=$false
function Invoke-RestMethod {
 param($Method,$Uri,$ContentType,$Body,$TimeoutSec,$MaximumRedirection)
 if($MaximumRedirection-cne0){throw 'PROBE_REDIRECTS_NOT_DISABLED'}
 if($Uri-cne'http://127.0.0.1:1/v1/chat/completions'){throw 'UNEXPECTED_ENDPOINT'}
 $request=[Text.Encoding]::UTF8.GetString([byte[]]$Body)|ConvertFrom-Json
 if($script:ProfileActive){
  if($request.model-cne'profile-model-test'-or$request.max_tokens-ne128-or$request.chat_template_kwargs.enable_thinking-ne$true-or$request.reasoning_effort-cne'xhigh'-or$TimeoutSec-ne18){throw 'PROFILE_PROBE_INVALID'}
 }elseif($request.model-cne'qwen38-q6'-or$request.max_tokens-ne32-or$request.chat_template_kwargs.enable_thinking-ne$false){throw 'PROBE_REQUEST_INVALID'}
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
$script:ProfileActive=$true
$env:V213_MODEL_PROFILE_JSON=@{schema_version=1;model='profile-model-test';enable_thinking=$true;reasoning_effort='xhigh';max_output_tokens=1024;smoke_output_tokens=128;timeout_ms=18000}|ConvertTo-Json -Compress
$profileCatalog=@([pscustomobject]@{id='profile-model-test';aliases=@()})
$script:Response=@{model='profile-model-test';choices=@(@{finish_reason='stop';message=@{content='R75_FREE_RELAY_E2E_OK'}})}
Test-SelectedModelRoute 'http://127.0.0.1:1' 'profile-model-test' $profileCatalog
$failed=$false
try{Test-SelectedModelRoute 'http://127.0.0.1:1' 'wrong-model' $profileCatalog}catch{$failed=$true}
if(-not$failed){throw 'PROFILE_SELECTION_MISMATCH_ACCEPTED'}
Remove-Item Env:V213_MODEL_PROFILE_JSON -ErrorAction SilentlyContinue
$script:ProfileActive=$false
$script:Catalog+=@([pscustomobject]@{id='other';aliases=@('QWEN38-Q6')})
$failed=$false
try{$null=Resolve-Model 'http://127.0.0.1:1' 'qwen38-q6'}catch{$failed=$true}
if(-not$failed){throw 'AMBIGUOUS_ALIAS_ACCEPTED'}
# Execute the real startup decision block, not just its internal formatter/probe.
$source=$ast.Extent.Text
$start=$source.IndexOf('$runtimeProfile = Get-RuntimeModelProfile')
$end=$source.IndexOf('$bridgeMaterial = if', $start)
if($start-lt0-or$end-le$start){throw 'STARTUP_BLOCK_MISSING'}
$startup=[scriptblock]::Create($source.Substring($start,$end-$start))
function Resolve-Llama { return 'http://127.0.0.1:1' }
$tunnelPolicy=@{mode='FreeRelay'}
$LlamaBaseUrl='http://127.0.0.1:1'
$script:ProfileActive=$true
$env:V213_MODEL_PROFILE_JSON=@{schema_version=1;model='profile-model-test';enable_thinking=$true;reasoning_effort='xhigh';max_output_tokens=1024;smoke_output_tokens=128;timeout_ms=18000}|ConvertTo-Json -Compress
$script:Catalog=$profileCatalog
$script:Response=@{model='profile-model-test';choices=@(@{finish_reason='stop';message=@{content='R75_FREE_RELAY_E2E_OK'}})}
$Model=''
. $startup
if($Model-cne'profile-model-test'){throw 'STARTUP_PROFILE_NOT_SELECTED'}
$script:Response.choices[0].finish_reason='length'
$failure=''
try{. $startup}catch{$failure=$_.Exception.Message}
if($failure-notlike'MODEL_ROUTING_PROBE_FAILED;*'){throw 'STARTUP_INCOMPLETE_RESPONSE_ACCEPTED'}
$script:Response.choices[0].finish_reason='stop'
$Model='other-model'
$failure=''
try{. $startup}catch{$failure=$_.Exception.Message}
if($failure-cne'MODEL_PROFILE_SELECTION_MISMATCH'){throw 'STARTUP_PROFILE_CONFLICT_NOT_REJECTED'}
Remove-Item Env:V213_MODEL_PROFILE_JSON -ErrorAction SilentlyContinue
$script:ProfileActive=$false
$Model=''
$script:Catalog=@([pscustomobject]@{id=$canonical;aliases=@('qwen38-q6')})
$script:Response=@{model=$canonical;choices=@(@{finish_reason='stop';message=@{content='R75_FREE_RELAY_E2E_OK'}})}
. $startup
if($Model-cne'qwen38-q6'){throw 'LEGACY_STARTUP_MODEL_CHANGED'}
$Model='profile-model-test'
$script:Catalog=$profileCatalog
$failure=''
try{. $startup}catch{$failure=$_.Exception.Message}
if($failure-cne'FREE_RELAY_LEGACY_MODEL_MISMATCH'){throw 'UNPROFILED_FREE_RELAY_MODEL_ACCEPTED'}
Write-Output 'BRIDGE_SHARED_IDENTITY=PASS; startup_profile=PASS; no_network=true; no_mutation=true'
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
