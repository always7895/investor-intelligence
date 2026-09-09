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
    foreach($name in @('no_write','ready','challenge','worker_version','schema_version','parser_schema','compatibility','publication_contract_id','publication_contract_sha256','compact_policy_sha256','code')){
        if($null-ne$Response){$property=$Response.PSObject.Properties[$name];if($property-and$property.Value-is[array]){throw 'V213_READINESS_SCALAR_REQUIRED'}}
    }
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
function Invoke-V213ReadinessGet([uri]$Uri,[switch]$DiagnosticUserAgent,[switch]$DiagnosticEnvelope){
    if(($DiagnosticUserAgent-or$DiagnosticEnvelope)-and($Uri.Scheme-cne'https'-or$Uri.Port-ne443-or$Uri.UserInfo-or
       $Uri.Host-cnotmatch'^ii-r75-qa-bench-[0-9a-f]{10}\.[a-z0-9-]+\.workers\.dev$'-or
       $Uri.AbsolutePath-cne'/v213/readiness')){throw 'ISOLATED_DIAGNOSTIC_SCOPE_INVALID'}
    # Per-request direct transport, identical on PS5.1/7; no global proxy changes.
    Add-Type -AssemblyName System.Net.Http
    $handler=New-Object Net.Http.HttpClientHandler
    $handler.UseProxy=$false;$handler.UseCookies=$false
    $handler.UseDefaultCredentials=$false;$handler.AllowAutoRedirect=$false
    $client=New-Object Net.Http.HttpClient($handler)
    $client.Timeout=[TimeSpan]::FromSeconds(10)
    $client.MaxResponseContentBufferSize=1048576
    $client.DefaultRequestHeaders.TryAddWithoutValidation('cache-control','no-store')|Out-Null
    $client.DefaultRequestHeaders.TryAddWithoutValidation('pragma','no-cache')|Out-Null
    if($DiagnosticUserAgent){$client.DefaultRequestHeaders.UserAgent.ParseAdd('InvestorIntelligence-IsolatedDiagnostic/1.0')}
    $response=$null;$status=0;$body=''
    try {
        $response=$client.GetAsync($Uri).GetAwaiter().GetResult()
        $status=[int]$response.StatusCode
        $bytes=$response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
        $utf8=New-Object Text.UTF8Encoding($false,$true)
        $body=$utf8.GetString($bytes)
        if($status-notin@(200,409)){throw 'HTTP_STATUS_REJECTED'}
        $parsed=$body|ConvertFrom-Json
        if($status-eq409){
            $readyProperty=$parsed.PSObject.Properties['ready']
            $codeProperty=$parsed.PSObject.Properties['code']
            if(-not$readyProperty-or$readyProperty.Value-isnot[bool]-or$readyProperty.Value-or
               -not$codeProperty-or$codeProperty.Value-isnot[string]-or$codeProperty.Value-cne'V213_READINESS_VERSION_MISMATCH'){throw 'HTTP_CONFLICT_REJECTED'}
        }
        if($DiagnosticEnvelope){return [pscustomobject]@{http_status=$status;body=$parsed}}
        return $parsed
    } catch {
        $failureType=$_.Exception.GetBaseException().GetType().Name
        $bodyKind=if($body-match'There is nothing here yet'){'empty_worker'}elseif($body.Trim()-ceq'Not found'){'not_found'}elseif($body-match'(?i)<html'){'html'}else{'other'}
        throw "V213_READINESS_HTTP_FAILED; http_status=$status; exception_type=$failureType; body_kind=$bodyKind"
    } finally {
        if($response){$response.Dispose()};$client.Dispose();$handler.Dispose()
    }
}
function Get-V213IsolatedTransportDiagnostic([string]$Origin,[string]$ExpectedVersion,[string]$Challenge,[switch]$Direct,[switch]$HttpClient,[switch]$Agent) {
    if($Agent-and-not$HttpClient){throw 'ISOLATED_DIAGNOSTIC_SCOPE_INVALID'}
    if($Origin-cnotmatch'^https://ii-r75-qa-bench-[0-9a-f]{10}\.[a-z0-9-]+\.workers\.dev$'-or
       $ExpectedVersion-cnotmatch'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'-or
       $Challenge-cnotmatch'^[0-9a-f]{32}$'){throw 'ISOLATED_DIAGNOSTIC_SCOPE_INVALID'}
    $target=[uri]($Origin+'/v213/readiness?challenge='+$Challenge+'&expected_version='+$ExpectedVersion)
    $result=[ordered]@{scope='ISOLATED_TRANSPORT_DIAGNOSTIC';release_qualified=$false;http_status=0;body_kind='other';nonce_match=$false;version_match=$false;ready=$false}
    $proxy=if($PSVersionTable.PSVersion.Major-ge7){[Net.Http.HttpClient]::DefaultProxy}else{[Net.WebRequest]::DefaultWebProxy}
    $result.proxy_bypassed=($null-eq$proxy-or$proxy.IsBypassed($target))
    $result.direct_requested=[bool]$Direct
    if($HttpClient){
        $result.proxy_bypassed=$true;$result.direct_requested=$true
        try {
            $response=Invoke-V213ReadinessGet -Uri $target -DiagnosticUserAgent:$Agent -DiagnosticEnvelope
            $body=$response.body
            $result.http_status=[int]$response.http_status
            $result.nonce_match=((Get-V213ReadyField $body 'challenge' '')-ceq$Challenge)
            $result.version_match=((Get-V213ReadyField $body 'worker_version' '')-ceq$ExpectedVersion)
            $ready=Get-V213ReadyField $body 'ready' $null
            $result.ready=($ready-is[bool]-and$ready)
        } catch {
            $message=$_.Exception.Message
            if($message-match'http_status=(\d{1,3})'){$result.http_status=[int]$Matches[1]}
            if($message-match'body_kind=(empty_worker|not_found|html|other)'){$result.body_kind=$Matches[1]}
        }
        return [pscustomobject]$result
    }
    $options=@{}
    if($Direct){if($PSVersionTable.PSVersion.Major-lt7){throw 'DIAGNOSTIC_DIRECT_REQUIRES_PS7'};$options.NoProxy=$true}
    $text=''
    try {
        $response=Invoke-WebRequest -UseBasicParsing -Uri $target -Headers @{'cache-control'='no-store';'pragma'='no-cache'} -MaximumRedirection 0 -TimeoutSec 10 @options
        $result.http_status=[int]$response.StatusCode;$text=[string]$response.Content
    } catch {
        $result.http_status=[int](Get-V213ReadyField (Get-V213ReadyField $_.Exception 'Response' $null) 'StatusCode' 0)
        if($_.ErrorDetails){$text=[string]$_.ErrorDetails.Message}
    }
    $result.body_kind=if($text-match'There is nothing here yet'){'empty_worker'}elseif($text.Trim()-ceq'Not found'){'not_found'}elseif($text-match'(?i)<html'){'html'}else{'other'}
    try {
        $body=$text|ConvertFrom-Json
        $result.nonce_match=((Get-V213ReadyField $body 'challenge' '')-ceq$Challenge)
        $result.version_match=((Get-V213ReadyField $body 'worker_version' '')-ceq$ExpectedVersion)
        $ready=Get-V213ReadyField $body 'ready' $null
        $result.ready=($ready-is[bool]-and$ready)
    } catch { }
    return [pscustomobject]$result
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
