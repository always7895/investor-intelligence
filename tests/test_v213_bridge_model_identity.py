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
    def test_router_resolution_never_probes_or_starts_other_services(self):
        script = r'''
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('SOURCE',[ref]$tokens,[ref]$errors)
$names=@('Get-ObjectPropertyValue','Read-ModelSelection','Resolve-Llama','Resolve-Model','Get-ModelCatalog','Test-Llama','Get-RunningLlamaCandidates')
foreach($f in $ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $names -contains $n.Name},$true)){. ([scriptblock]::Create($f.Extent.Text))}
function Start-Process { throw 'UNEXPECTED_SERVICE_START' }
function Get-Process { throw 'UNEXPECTED_PROCESS_DISCOVERY' }
function Invoke-WebRequest { throw 'UNEXPECTED_HEALTH_OR_RELOAD_REQUEST' }
$script:Uris=@()
function Invoke-RestMethod {param($Method,$Uri,$Headers,$TimeoutSec,$MaximumRedirection)
 if($MaximumRedirection-cne0){throw 'REDIRECTS_ENABLED'}
 $script:Uris+=,$Uri;throw 'SYNTHETIC_UNAVAILABLE'
}
$selectionPath=Join-Path 'TEMP' 'selection.json'
$LlamaBaseUrl=''
if((Resolve-Llama)-cne'http://127.0.0.1:5000'){throw 'DEFAULT_WRONG'}
foreach($valid in @('http://localhost','http://127.0.0.1:65535','http://localhost:1/')){
 $LlamaBaseUrl=$valid
 if((Resolve-Llama)-cne$valid.TrimEnd('/')){throw 'VALID_ROUTER_REJECTED'}
}
$LlamaBaseUrl=''
@{model='synthetic';llama_base_url='http://localhost:8123/'}|ConvertTo-Json|Set-Content $selectionPath -Encoding UTF8
if((Resolve-Llama)-cne'http://localhost:8123'){throw 'SAVED_ROUTER_IGNORED'}
$failed=$false
try{Get-ModelCatalog (Resolve-Llama)}catch{$failed=$true}
if(-not$failed-or$script:Uris.Count-ne2-or$script:Uris[0]-cne'http://localhost:8123/models'-or$script:Uris[1]-cne'http://localhost:8123/v1/models'){throw 'ENDPOINT_FALLBACK'}
foreach($bad in @('http://localhost:0','http://localhost:65536','http://localhost:8080?reload=1','http://localhost:8080#x','http://x@localhost:8080','http://example.com:8080','http://localhost:8080/path',"http://localhost:8080`n")){
 $LlamaBaseUrl=$bad;$failure=''
 try{Resolve-Llama}catch{$failure=$_.Exception.Message}
 if($failure-cne'MODEL_ROUTER_URL_INVALID'){throw 'INVALID_EXPLICIT_ROUTER_ACCEPTED'}
}
$LlamaBaseUrl=''
foreach($bad in @($true,@('http://localhost:8080'),'http://localhost:65536')){
 @{model='synthetic';llama_base_url=$bad}|ConvertTo-Json -Depth 4|Set-Content $selectionPath -Encoding UTF8
 $failure='';try{Resolve-Llama}catch{$failure=$_.Exception.Message}
 if($failure-cne'MODEL_ROUTER_URL_INVALID'){throw 'INVALID_SAVED_ROUTER_ACCEPTED'}
}
foreach($raw in @('SYNTHETIC_INVALID_JSON','[{"model":"synthetic"}]','{"model":["synthetic"]}')){
 $raw|Set-Content $selectionPath
 $failure='';try{Resolve-Llama}catch{$failure=$_.Exception.Message}
 if($failure-cne'MODEL_SELECTION_INVALID'){throw 'INVALID_SELECTION_DEFAULTED'}
}
$LlamaBaseUrl='http://127.0.0.1:8080'
if((Resolve-Llama)-cne$LlamaBaseUrl){throw 'EXPLICIT_ROUTER_OVERRIDDEN'}
if($script:Uris.Count-ne2){throw 'UNEXPECTED_NETWORK'}
function Get-ModelCatalog {param($Base) return @([pscustomobject]@{id='synthetic';aliases=@()})}
function Invoke-SharedModelIdentity {param($Selected,$Catalog) return @{canonical_model=$Selected}}
if((Resolve-Model $LlamaBaseUrl 'synthetic').model-cne'synthetic'){throw 'EXPLICIT_MODEL_READS_INVALID_SELECTION'}
Write-Output 'ROUTER_RESOLUTION=PASS; no_network=true; no_services=true'
'''
        with tempfile.TemporaryDirectory() as d:
            code = script.replace('SOURCE', str(ROOT / 'scripts/run_v213_local_llm_bridge_core.ps1').replace("'", "''")).replace('TEMP', d.replace("'", "''"))
            path = Path(d) / 'check.ps1'
            path.write_text(code, encoding='utf-8-sig')
            for shell in ('powershell.exe', 'pwsh'):
                (Path(d) / 'selection.json').unlink(missing_ok=True)
                result = subprocess.run([shell, '-NoProfile', '-File', str(path)], capture_output=True, timeout=45)
                with self.subTest(shell=shell):
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_saved_or_default_router_follows_a_moved_local_server_but_explicit_does_not(self):
        script = r'''
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('SOURCE',[ref]$tokens,[ref]$errors)
$names=@('Get-ObjectPropertyValue','Get-ModelCatalog','Find-LocalModelServer','Resolve-ModelWithDiscovery')
foreach($f in $ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $names -contains $n.Name},$true)){. ([scriptblock]::Create($f.Extent.Text))}
$script:Uris=@()
function Invoke-RestMethod {param($Method,$Uri,$Headers,$TimeoutSec,$MaximumRedirection)
 $script:Uris+=,$Uri
 if($Uri-ceq'http://127.0.0.1:11434/v1/models'){return [pscustomobject]@{data=@([pscustomobject]@{id='wanted-model';aliases=@()})}}
 if($Uri-ceq'http://127.0.0.1:5000/v1/models'){return [pscustomobject]@{data=@([pscustomobject]@{id='other-model';aliases=@()})}}
 throw 'SYNTHETIC_UNAVAILABLE'
}
function Resolve-Model {param($Base,$Requested)
 $ids=@(Get-ModelCatalog $Base|ForEach-Object{$_.id})
 if($ids -notcontains $Requested){throw 'MODEL_NOT_IN_CATALOG'}
 return [pscustomobject]@{model=$Requested}
}
function Write-Host {}
$LlamaBaseUrl=''
$found=Resolve-ModelWithDiscovery 'http://127.0.0.1:8080' 'wanted-model'
if($found.base-cne'http://127.0.0.1:11434'-or$found.resolution.model-cne'wanted-model'){throw 'DISCOVERY_MISSED_MOVED_SERVER'}
if(@($script:Uris|Where-Object{$_ -like '*:8000*'}).Count){throw 'DECIDER_PORT_PROBED'}
$LlamaBaseUrl='http://127.0.0.1:8080'
$failed=$false;try{$null=Resolve-ModelWithDiscovery 'http://127.0.0.1:8080' 'wanted-model'}catch{$failed=$true}
if(-not$failed){throw 'EXPLICIT_ROUTER_HOPPED'}
$LlamaBaseUrl=''
$failed=$false;try{$null=Resolve-ModelWithDiscovery 'http://127.0.0.1:8080' 'absent-model'}catch{$failed=$true}
if(-not$failed){throw 'ABSENT_MODEL_SUBSTITUTED'}
Write-Output 'DISCOVERY=PASS'
'''
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'discovery.ps1'
            path.write_text(script.replace('SOURCE', str(ROOT / 'scripts/run_v213_local_llm_bridge_core.ps1').replace("'", "''")),
                            encoding='utf-8-sig')
            for shell in ('powershell.exe', 'pwsh'):
                if shell == 'pwsh' and shutil.which('pwsh') is None:
                    continue
                result = subprocess.run([shell, '-NoProfile', '-File', str(path)], capture_output=True, timeout=60)
                with self.subTest(shell=shell):
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn(b'DISCOVERY=PASS', result.stdout)

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
$names=@('Get-ObjectPropertyValue','Invoke-SharedModelIdentity','Resolve-Model','Test-SelectedModelRoute','Get-RuntimeModelProfile','Resolve-ModelWithDiscovery','Find-LocalModelServer')
$functions=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $names -contains $node.Name},$true))
if($functions.Count-ne7){throw 'FUNCTION_INVENTORY_MISMATCH'}
foreach($function in $functions){. ([scriptblock]::Create($function.Extent.Text))}
function Read-ModelSelection { return $null }
function Get-ModelCatalog { param($Base) return $script:Catalog }
function Set-FollowingModelProfile { param($Model) return $null }  # tested separately below
Remove-Item Env:V213_MODEL_PROFILE_JSON -ErrorAction SilentlyContinue
$script:ProfileActive=$false
function Invoke-RestMethod {
 param($Method,$Uri,$ContentType,$Body,$TimeoutSec,$MaximumRedirection)
 if($MaximumRedirection-cne0){throw 'PROBE_REDIRECTS_NOT_DISABLED'}
 if($Uri-cne'http://127.0.0.1:1/v1/chat/completions'){throw 'UNEXPECTED_ENDPOINT'}
 $request=[Text.Encoding]::UTF8.GetString([byte[]]$Body)|ConvertFrom-Json
 if($script:ProfileActive){
  if($request.model-cne'profile-model-test'-or$request.max_tokens-ne128-or$request.chat_template_kwargs.enable_thinking-ne$true-or$request.reasoning_effort-cne'xhigh'-or$TimeoutSec-ne18){throw 'PROFILE_PROBE_INVALID'}
 }elseif($request.model-cne$script:ExpectedModel-or$request.max_tokens-ne32-or$request.chat_template_kwargs.enable_thinking-ne$false){throw 'PROBE_REQUEST_INVALID'}
 return $script:Response
}
$preferredModel='qwen38-q6'
$script:ExpectedModel='qwen38-q6'
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
# Operator 2026-09-26: an unprofiled relay publishes the served model it verified (the Worker decides whether to
# follow it); a model the server does not serve is still refused before anything starts.
$Model='profile-model-test'
$script:ExpectedModel='profile-model-test'
$script:Catalog=$profileCatalog
$script:Response=@{model='profile-model-test';choices=@(@{finish_reason='stop';message=@{content='R75_FREE_RELAY_E2E_OK'}})}
. $startup
if($Model-cne'profile-model-test'){throw 'UNPROFILED_SERVED_MODEL_NOT_USED'}
$Model='never-served-model'
$LlamaBaseUrl='http://127.0.0.1:1'
$failure=''
try{. $startup}catch{$failure=$_.Exception.Message}
if(-not$failure){throw 'UNSERVED_MODEL_ACCEPTED'}
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


    def test_relay_builds_the_following_profile_from_the_settings_and_the_detected_model(self):
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        script = r'''
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$ProjectRoot=ROOT_VALUE
$python=PYTHON_VALUE
$stateRoot=STATE_VALUE
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $ProjectRoot 'scripts/run_v213_local_llm_bridge_core.ps1'),[ref]$tokens,[ref]$errors)
foreach($function in @($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and @('Set-FollowingModelProfile','Get-RuntimeModelProfile') -contains $node.Name},$true))){. ([scriptblock]::Create($function.Extent.Text))}
Remove-Item Env:V213_MODEL_PROFILE_JSON -ErrorAction SilentlyContinue
$default=Set-FollowingModelProfile 'Qwen3.8-27B'
if($default.model-cne'Qwen3.8-27B'-or$default.enable_thinking-ne$false-or$default.max_output_tokens-ne1024-or$default.timeout_ms-ne18000){throw 'DEFAULT_SETTINGS_NOT_USED'}
@{schema_version=1;model='old';enable_thinking=$true;reasoning_effort='high';max_output_tokens=2048;smoke_output_tokens=64;timeout_ms=19000}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $stateRoot 'v213-model-profile-v1.json') -Encoding utf8
$launcher=Set-FollowingModelProfile 'Other-8B'
if($launcher.model-cne'Other-8B'-or$launcher.enable_thinking-ne$true-or$launcher.reasoning_effort-cne'high'-or$launcher.max_output_tokens-ne2048){throw 'LAUNCHER_SETTINGS_NOT_USED'}
if(([Environment]::GetEnvironmentVariable('V213_MODEL_PROFILE_JSON')|ConvertFrom-Json).model-cne'Other-8B'){throw 'GATEWAY_PROFILE_NOT_SET'}
Write-Output 'FOLLOWING_PROFILE=PASS'
'''
        with tempfile.TemporaryDirectory(prefix='Profile (1) ') as directory:
            script_text = script.replace('ROOT_VALUE', quote(ROOT)).replace('PYTHON_VALUE', quote(sys.executable)).replace('STATE_VALUE', quote(directory))
            path = Path(directory) / 'check.ps1'
            path.write_text(script_text, encoding='utf-8-sig')
            for shell in ('powershell.exe', 'pwsh'):
                if shutil.which(shell) is None:
                    continue
                result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-File', str(path)], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
                with self.subTest(shell=shell):
                    self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-2000:])
                    self.assertIn('FOLLOWING_PROFILE=PASS', result.stdout)
                (Path(directory) / 'v213-model-profile-v1.json').unlink(missing_ok=True)

if __name__ == '__main__':
    unittest.main()
