[CmdletBinding()]
param([string]$ProjectRoot='', [string]$WorkerFixture='')
$ErrorActionPreference='Stop'
if(-not$ProjectRoot){$ProjectRoot=Split-Path -Parent $PSScriptRoot}
. (Join-Path $ProjectRoot 'scripts/v213_edge_readiness.ps1')
$version='12345678-1234-1234-1234-123456789abc'
$policy=Get-V213CompactPolicyHash $ProjectRoot
function Proof([string]$nonce){return [pscustomobject]@{schema_version=1;ready=$true;worker_version=$version;challenge=$nonce;parser_schema='v213-r75-sec-filing-provenance-v1';compatibility='PASS';no_write=$true;publication_contract_id='v213-r75-publication-mode-v1';publication_contract_sha256='9b96f2fd68318e6476dc00d0d003162c0343d2aece5ef25f522fe7c33dca7bfd';compact_policy_sha256=$policy}}
function Must-Fail([scriptblock]$Action,[string]$Name){$failed=$false;try{& $Action|Out-Null}catch{$failed=$true};if(-not$failed){throw "Negative invariant accepted: $Name"}}
foreach ($receipt in @([pscustomobject]@{}, [pscustomobject]@{release_ready=$false}, [pscustomobject]@{release_ready='true';live_qa='PASS';live_free_relay_smoke='PASS'}, [pscustomobject]@{release_ready=$true;live_qa='PASS_SYNTHETIC';live_free_relay_smoke='PASS'})) {
    Must-Fail {Assert-V213QaReleaseQualification $receipt} 'unqualified release forbidden'
}
Assert-V213QaReleaseQualification ([pscustomobject]@{release_ready=$true;live_qa='PASS';live_free_relay_smoke='PASS'})
if($WorkerFixture){
    $fixture=Get-Content -LiteralPath $WorkerFixture -Raw -Encoding utf8|ConvertFrom-Json
    if(-not(Test-V213EdgeReadinessResponse $fixture $version $fixture.challenge $policy)){throw 'Cross-language Worker proof failed'}
}
if ((Get-V213DeployedVersion "Uploaded synthetic worker`nCurrent Version ID: $version") -cne $version) { throw 'Exact uploaded version not recovered' }
Must-Fail {Get-V213DeployedVersion 'deployment finished without version identity'} 'missing uploaded version'
Must-Fail {Get-V213DeployedVersion "Current Version ID: $version`nCurrent Version ID: $version"} 'ambiguous uploaded version'
$single = [pscustomobject]@{versions=@([pscustomobject]@{version_id=$version;percentage=100})}
if ((Get-V213DeploymentVersion $single) -cne $version) { throw 'Control-plane identity failure' }
foreach ($versions in @(@(), @([pscustomobject]@{version_id=$version;percentage=99}), @([pscustomobject]@{version_id=$version;percentage='100'}), @([pscustomobject]@{version_id=$version;percentage=50},[pscustomobject]@{version_id=$version;percentage=50}))) {
    Must-Fail {Get-V213DeploymentVersion ([pscustomobject]@{versions=$versions})} 'not exactly one version at 100 percent'
}
$nonce='1'*32
foreach($name in @('schema_version','parser_schema','publication_contract_id','publication_contract_sha256','compact_policy_sha256','no_write','challenge')){
    $bad=Proof $nonce
    $bad.$name=if($name-eq'no_write'){$false}elseif($name-eq'schema_version'){99}else{'INVALID'}
    Must-Fail {Test-V213EdgeReadinessResponse $bad $version $nonce $policy} $name
}
$script:calls=0
$script:nonces=@{}
$transport={param($uri)
    $match=[regex]::Match($uri.Query,'challenge=([0-9a-f]{32})');$n=$match.Groups[1].Value
    if($script:nonces.ContainsKey($n)){throw 'NONCE_REPLAY'};$script:nonces[$n]=$true;$script:calls++
    if($script:calls-in@(1,3)){return [pscustomobject]@{ready=$false;code='V213_READINESS_VERSION_MISMATCH';challenge=$n;no_write=$true;worker_version='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}}
    return Proof $n
}
$ready=Wait-V213EdgeReadiness -Origin 'https://synthetic.workers.dev' -ExpectedVersion $version -ProjectRoot $ProjectRoot -Transport $transport -DelayMilliseconds 0
if($ready.worker_version-ne$version-or$script:calls-ne6){throw 'Convergence must require THREE consecutive same-version proofs'}
Must-Fail {Wait-V213EdgeReadiness -Origin 'https://synthetic.workers.dev' -ExpectedVersion $version -ProjectRoot $ProjectRoot -DelayMilliseconds 0 -Transport {param($uri)[pscustomobject]@{ready=$true;schema_version=99}}} 'unknown schema'
Must-Fail {Wait-V213EdgeReadiness -Origin 'https://synthetic.workers.dev' -ExpectedVersion $version -ProjectRoot $ProjectRoot -DelayMilliseconds 0 -Transport {param($uri)throw 'HTTP_404_OLD_PARSER'}} 'old edge'
Must-Fail {Wait-V213EdgeReadiness -Origin 'http://synthetic.workers.dev' -ProjectRoot $ProjectRoot} 'plaintext origin'
Must-Fail {Wait-V213EdgeReadiness -Origin 'https://synthetic.workers.dev' -ProjectRoot $ProjectRoot} 'missing expected version'
$script:timeoutCalls=0
Must-Fail {Wait-V213EdgeReadiness -Origin 'https://synthetic.workers.dev' -ExpectedVersion $version -ProjectRoot $ProjectRoot -MaxAttempts 3 -DelayMilliseconds 0 -Transport {
    param($uri)
    $script:timeoutCalls++
    [pscustomobject]@{ready=$false;code='V213_READINESS_VERSION_MISMATCH';challenge=([regex]::Match($uri.Query,'challenge=([0-9a-f]{32})').Groups[1].Value);no_write=$true;worker_version='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}
}} 'readiness timeout'
if ($script:timeoutCalls -ne 3) { throw 'Readiness retry budget not enforced' }
$script:invalidCalls=0
Must-Fail {Wait-V213EdgeReadiness -Origin 'https://synthetic.workers.dev' -ExpectedVersion $version -ProjectRoot $ProjectRoot -DelayMilliseconds 0 -Transport {
    param($uri)
    $script:invalidCalls++
    [pscustomobject]@{ready=$false;code='V213_ACTIVATION_TOP20_INVALID';challenge=([regex]::Match($uri.Query,'challenge=([0-9a-f]{32})').Groups[1].Value);no_write=$true}
}} 'arbitrary validation error must not retry'
if ($script:invalidCalls -ne 1) { throw 'Validation errors were retried' }
Write-Host "V213_EDGE_READINESS_SELF_TEST = PASS; PowerShell=$($PSVersionTable.PSVersion); no_network=true; production_mutation=false"
