[CmdletBinding()]
param([string]$ProjectRoot = '')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$cloudRoot = Join-Path $ProjectRoot 'cloud'
$templatePath = Join-Path $cloudRoot 'wrangler.v21.production.template.toml'
$configRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config'
$productionPath = Join-Path $configRoot 'wrangler.v21.production.local.toml'
$localConfigPath = Join-Path $configRoot 'v21-owner-line.local.json'
New-Item -ItemType Directory -Force -Path $configRoot | Out-Null

function Read-HiddenText([string]$Prompt) {
    $secureValue = Read-Host $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function New-RandomText([int]$Bytes = 32) {
    $buffer = New-Object byte[] $Bytes
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($buffer) } finally { $generator.Dispose() }
    return [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Get-Sha256([string]$Value) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString(
            $algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value))
        )).Replace('-', '').ToLowerInvariant()
    }
    finally { $algorithm.Dispose() }
}

function Invoke-Npx([string[]]$Arguments, [string]$StandardInput = '') {
    $npx = (Get-Command npx.cmd -ErrorAction Stop).Source
    if ($StandardInput) {
        $output = @($StandardInput | & $npx @Arguments 2>&1)
    }
    else {
        $output = @(& $npx @Arguments 2>&1)
    }
    $code = $LASTEXITCODE
    $output | ForEach-Object { Write-Host ([string]$_) }
    if ($code -ne 0) { throw "npx command failed with exit code $code" }
    return ($output | ForEach-Object { [string]$_ }) -join "`n"
}

Push-Location $cloudRoot
$channelKey = ''
$channelAccess = ''
$tenantHashKey = ''
$tenantDataKey = ''
$syncKey = ''
$pairCode = ''
try {
    & npm.cmd ci --ignore-scripts --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Node dependency installation failed.' }
    & npm.cmd run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'TypeScript validation failed.' }
    & npm.cmd test
    if ($LASTEXITCODE -ne 0) { throw 'Worker tests failed.' }

    try { [void](Invoke-Npx @('wrangler', 'whoami')) }
    catch {
        [void](Invoke-Npx @('wrangler', 'login'))
        [void](Invoke-Npx @('wrangler', 'whoami'))
    }

    if (-not (Test-Path -LiteralPath $productionPath -PathType Leaf)) {
        $ids = @()
        foreach ($binding in @('V21_PUBLIC_CACHE', 'V21_TENANT_PRIVATE_CACHE', 'V21_EPHEMERAL_SECURITY_CACHE')) {
            $output = Invoke-Npx @('wrangler', 'kv', 'namespace', 'create', $binding)
            $matches = [regex]::Matches($output, '(?i)\b[0-9a-f]{32}\b')
            if ($matches.Count -lt 1) { throw "Unable to parse the KV namespace ID for $binding" }
            $ids += $matches[$matches.Count - 1].Value
        }
        if ((@($ids | Select-Object -Unique)).Count -ne 3) {
            throw 'The three v2.1 KV namespace IDs must be distinct.'
        }
        $template = Get-Content -LiteralPath $templatePath -Raw -Encoding utf8
        $entryPath = (Join-Path $cloudRoot 'src\v21\worker.ts').Replace('\', '/')
        $template = $template.Replace('main = "src/v21/worker.ts"', "main = `"$entryPath`"")
        $template = $template.Replace('__V21_PUBLIC_CACHE_ID__', $ids[0])
        $template = $template.Replace('__V21_TENANT_PRIVATE_CACHE_ID__', $ids[1])
        $template = $template.Replace('__V21_EPHEMERAL_SECURITY_CACHE_ID__', $ids[2])
        [IO.File]::WriteAllText($productionPath, $template, [Text.UTF8Encoding]::new($false))
    }

    $channelKey = Read-HiddenText 'LINE channel secret（隱藏輸入）'
    $channelAccess = Read-HiddenText 'LINE channel access token（隱藏輸入）'
    if ([string]::IsNullOrWhiteSpace($channelKey) -or $channelKey.Length -lt 16) {
        throw 'LINE channel secret is empty or invalid.'
    }
    if ([string]::IsNullOrWhiteSpace($channelAccess) -or $channelAccess.Length -lt 32) {
        throw 'LINE channel access token is empty or invalid.'
    }
    $tenantHashKey = New-RandomText
    $tenantDataKey = New-RandomText
    $syncKey = New-RandomText
    $pairCode = 'II-' + (New-RandomText 12)
    $pairHash = Get-Sha256 $pairCode

    $deployOutput = Invoke-Npx @('wrangler', 'deploy', '--config', $productionPath)
    $workerUrl = [regex]::Match($deployOutput, 'https://[A-Za-z0-9.-]+\.workers\.dev').Value.TrimEnd('/')
    if (-not $workerUrl) { throw 'The deployed Worker URL could not be determined.' }

    $values = @(
        @('LINE_CHANNEL_SECRET', $channelKey),
        @('LINE_CHANNEL_ACCESS_TOKEN', $channelAccess),
        @('TENANT_HASH_SECRET', $tenantHashKey),
        @('TENANT_DATA_ENCRYPTION_KEY', $tenantDataKey),
        @('V21_SYNC_HMAC_SECRET', $syncKey),
        @('V21_OWNER_PAIRING_CODE_HASH', $pairHash)
    )
    foreach ($entry in $values) {
        [void](Invoke-Npx @('wrangler', 'secret', 'put', [string]$entry[0], '--config', $productionPath) ([string]$entry[1]))
    }
    $deployOutput = Invoke-Npx @('wrangler', 'deploy', '--config', $productionPath)

    $lineHeaders = @{ Authorization = "Bearer $channelAccess" }
    Invoke-RestMethod -Method Put -Uri 'https://api.line.me/v2/bot/channel/webhook/endpoint' `
        -Headers $lineHeaders -ContentType 'application/json' `
        -Body (@{ endpoint = "$workerUrl/webhook" } | ConvertTo-Json -Compress) | Out-Null
    $test = Invoke-RestMethod -Method Post -Uri 'https://api.line.me/v2/bot/channel/webhook/test' `
        -Headers $lineHeaders -ContentType 'application/json' `
        -Body (@{ endpoint = "$workerUrl/webhook" } | ConvertTo-Json -Compress)
    if ($test.success -ne $true) { throw 'LINE webhook verification failed.' }

    $encryptedHmac = ConvertFrom-SecureString (
        ConvertTo-SecureString $syncKey -AsPlainText -Force
    )
    @{
        schema_version = 1
        public_snapshot_endpoint = "$workerUrl/v21/admin/public-snapshot"
        admin_status_endpoint = "$workerUrl/v21/admin/status"
        admin_test_push_endpoint = "$workerUrl/v21/admin/test-push"
        encrypted_hmac = $encryptedHmac
    } | ConvertTo-Json | Set-Content -LiteralPath $localConfigPath -Encoding utf8

    Set-Clipboard "配對 $pairCode"
    Write-Host '一次性配對命令已複製到剪貼簿。請貼到 LINE Bot 的一對一聊天室。' -ForegroundColor Cyan
    Write-Host '完成配對後，再執行本機公開快照同步與 test-push 驗證。' -ForegroundColor Cyan
}
finally {
    $channelKey = $null
    $channelAccess = $null
    $tenantHashKey = $null
    $tenantDataKey = $null
    $syncKey = $null
    $pairCode = $null
    Pop-Location
}
