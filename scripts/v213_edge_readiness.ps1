Set-StrictMode -Version Latest
function Assert-V213QaReleaseQualification($Receipt) {
    $qualified = Get-V213ReadyField $Receipt 'release_ready' $false
    if ($qualified -isnot [bool] -or -not $qualified -or
        (Get-V213ReadyField $Receipt 'live_qa' '') -cne 'PASS' -or
        (Get-V213ReadyField $Receipt 'live_free_relay_smoke' '') -cne 'PASS') {
        throw 'R75_QA_RELEASE_NOT_QUALIFIED; immutable_package_forbidden=true'
    }
}
function Get-V213DeployedVersion([string]$Output) {
    $plain = [regex]::Replace($Output, ([regex]::Escape([string][char]27) + '\[[0-?]*[ -/]*[@-~]'), '')
    $ids = [regex]::Matches($plain, '(?m)^\s*Current Version ID:\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\s*$')
    if ($ids.Count -ne 1) { throw 'V213_READINESS_DEPLOYED_VERSION_UNPROVEN' }
    return $ids[0].Groups[1].Value
}
function Get-V213DeploymentVersion($Deployment) {
    $versions = @(Get-V213ReadyField $Deployment 'versions' @())
    if ($versions.Count -ne 1) { throw 'V213_READINESS_NOT_SINGLE_ACTIVE_VERSION' }
    $share = Get-V213ReadyField $versions[0] 'percentage' $null
    $id = [string](Get-V213ReadyField $versions[0] 'version_id' '')
    if ($share -is [string] -or $share -is [bool] -or $null -eq $share -or $share -ne 100 -or
        $id -cnotmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') {
        throw 'V213_READINESS_CONTROL_PLANE_INVALID'
    }
    return $id
}
function Get-V213ReadOnlyActiveVersion([string]$ProjectRoot) {
    $wrangler = Join-Path $ProjectRoot 'cloud/node_modules/.bin/wrangler.cmd'
    $config = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence/UserData/config/wrangler.v213.production.local.toml'
    if (-not(Test-Path -LiteralPath $wrangler) -or -not(Test-Path -LiteralPath $config)) { throw 'V213_READINESS_CONTROL_PLANE_CONFIG_MISSING' }
    # Capture only: never emit config/bindings, account identifiers or raw diagnostics.
    $raw = (& $wrangler deployments list --json --config $config 2>$null | Out-String)
    if ($LASTEXITCODE -ne 0) { throw 'V213_READINESS_CONTROL_PLANE_FAILED' }
    try { $deployments = $raw | ConvertFrom-Json } catch { throw 'V213_READINESS_CONTROL_PLANE_JSON_INVALID' }
    $latest = $deployments | Sort-Object created_on | Select-Object -Last 1
    return Get-V213DeploymentVersion $latest
}
function Get-V213CompactPolicyHash([string]$ProjectRoot) {
    $policy=Get-Content -LiteralPath (Join-Path $ProjectRoot 'config/v213-compact-qa-v1.json') -Raw -Encoding utf8|ConvertFrom-Json
    $canonical=$policy|ConvertTo-Json -Depth 32 -Compress
    # Windows PowerShell 5.1 HTML-escapes these ASCII characters; JSON.stringify
    # and PS7 do not. Preserve literal escaped backslashes (e.g. "\\\\u0026").
    $canonical=[regex]::Replace($canonical,'(?<!\\)((?:\\\\)*)\\u(0026|0027|003c|003e)',{
        param($m)
        $m.Groups[1].Value + [string][char][Convert]::ToInt32($m.Groups[2].Value,16)
    },[Text.RegularExpressions.RegexOptions]::IgnoreCase)
    $hash=[Security.Cryptography.SHA256]::Create()
    try{return ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($canonical)))).Replace('-','').ToLowerInvariant()}
    finally{$hash.Dispose()}
}
function Get-V213ReadyField($Value,[string]$Name,$Default=$null){
    if($null-eq$Value){return $Default};$p=$Value.PSObject.Properties[$Name];if($null-eq$p){return $Default};return $p.Value
}
function Test-V213EdgeReadinessResponse($Response,[string]$ExpectedVersion,[string]$Challenge,[string]$PolicyHash){
    $noWrite=Get-V213ReadyField $Response 'no_write' $false
    $isReady=Get-V213ReadyField $Response 'ready' $false
    if($noWrite-isnot[bool]-or-not$noWrite-or$isReady-isnot[bool]-or(Get-V213ReadyField $Response 'challenge' '')-cne$Challenge){throw 'V213_READINESS_NONCE_OR_NO_WRITE_INVALID'}
    if(-not$isReady){
        if((Get-V213ReadyField $Response 'code' '')-ceq'V213_READINESS_VERSION_MISMATCH'){return $false}
        throw 'V213_READINESS_UNKNOWN_OR_UNAVAILABLE_SCHEMA'
    }
    $version=[string](Get-V213ReadyField $Response 'worker_version' '')
    if($version-notmatch'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'){throw 'V213_READINESS_VERSION_INVALID'}
    $schema=Get-V213ReadyField $Response 'schema_version' 0
    if(($schema-isnot[int]-and$schema-isnot[long])-or$schema-ne1-or
       (Get-V213ReadyField $Response 'parser_schema' '')-cne'v213-r75-sec-filing-provenance-v1'-or
       (Get-V213ReadyField $Response 'compatibility' '')-cne'PASS'-or
       (Get-V213ReadyField $Response 'publication_contract_id' '')-cne'v213-r75-publication-mode-v1'-or
       (Get-V213ReadyField $Response 'publication_contract_sha256' '')-cne'9b96f2fd68318e6476dc00d0d003162c0343d2aece5ef25f522fe7c33dca7bfd'-or
       (Get-V213ReadyField $Response 'compact_policy_sha256' '')-cne$PolicyHash){throw 'V213_READINESS_SCHEMA_OR_CONTRACT_MISMATCH'}
    if($ExpectedVersion-and$version-cne$ExpectedVersion){return $false}
    return $true
}
function Invoke-V213ReadinessGet([uri]$Uri){
    try{return Invoke-RestMethod -Method Get -Uri $Uri -Headers @{'cache-control'='no-store';'pragma'='no-cache'} -TimeoutSec 10 -MaximumRedirection 0}
    catch{
        $failureType=$_.Exception.GetType().Name
        $response=Get-V213ReadyField $_.Exception 'Response' $null
        $status=[int](Get-V213ReadyField $response 'StatusCode' 0)
        $failure="V213_READINESS_HTTP_FAILED; http_status=$status; exception_type=$failureType"
        $body=''
        if($_.ErrorDetails){$body=[string]$_.ErrorDetails.Message}
        if(-not$body-and$_.Exception.Response){
            try{$reader=New-Object IO.StreamReader($_.Exception.Response.GetResponseStream());try{$body=$reader.ReadToEnd()}finally{$reader.Dispose()}}catch{}
        }
        try{$parsed=$body|ConvertFrom-Json}catch{throw $failure}
        if(-not$parsed){throw $failure}
        return $parsed
    }
}
function Wait-V213EdgeReadiness {
    param([string]$Origin,[string]$ExpectedVersion='',[string]$ProjectRoot,[int]$MaxAttempts=8,[int]$DelayMilliseconds=1000,[scriptblock]$Transport=$null)
    $uri=[uri]$Origin
    if($uri.Scheme-ne'https'-or-not$uri.IsDefaultPort-or$uri.UserInfo-or$uri.Host-notmatch'^[a-z0-9-]+(?:\.[a-z0-9-]+)*\.workers\.dev$'){throw 'V213_READINESS_ORIGIN_INVALID'}
    if(-not$ExpectedVersion-or$ExpectedVersion-cnotmatch'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'){throw 'V213_READINESS_EXPECTED_VERSION_INVALID'}
    $policyHash=Get-V213CompactPolicyHash $ProjectRoot
    $consecutive=0;$last=$null
    for($attempt=1;$attempt-le[Math]::Min(12,[Math]::Max(3,$MaxAttempts));$attempt++){
        $nonce=[guid]::NewGuid().ToString('N')
        $url=$uri.GetLeftPart([UriPartial]::Authority)+'/v213/readiness?challenge='+$nonce
        if($ExpectedVersion){$url+='&expected_version='+$ExpectedVersion}
        $last=if($Transport){& $Transport ([uri]$url)}else{Invoke-V213ReadinessGet ([uri]$url)}
        if(Test-V213EdgeReadinessResponse $last $ExpectedVersion $nonce $policyHash){
            $consecutive++
            if($consecutive-ge3){
                Write-Host "V213_EDGE_READINESS = PASS; version=$ExpectedVersion; parser=sec-provenance-v1; consecutive=3; no_write=true"
                return $last
            }
        }else{$consecutive=0}
        if($DelayMilliseconds-gt0){Start-Sleep -Milliseconds ([Math]::Min(5000,$DelayMilliseconds))}
    }
    throw 'V213_EDGE_READINESS_NOT_CONVERGED; commit_forbidden=true'
}
