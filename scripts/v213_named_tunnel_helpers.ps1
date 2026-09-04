Set-StrictMode -Version Latest

function ConvertTo-V213WindowsCommandLineArgument {
    param([string]$Value)
    if ($null -eq $Value -or $Value.Length -eq 0) { return '""' }
    if ($Value -notmatch '[\s"]') { return $Value }
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Join-V213NativeArgumentLine {
    param([string[]]$Values)
    $rendered = @($Values | ForEach-Object { ConvertTo-V213WindowsCommandLineArgument -Value ([string]$_) })
    return ($rendered -join ' ')
}

function Get-V213RedactedText {
    param([string]$Text)
    $value = [string]$Text
    $value = [regex]::Replace($value, '(?i)bearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer <redacted>')
    $value = [regex]::Replace($value, '(?i)(authorization|token|secret|api[_-]?key|password|credentials-file)\s*[:=]\s*[^\s;,]+', '$1=<redacted>')
    $value = [regex]::Replace($value, '(?i)(cert\.pem|[0-9a-f-]{36}\.json)', '<credential-file>')
    if ($value.Length -gt 1200) { $value = $value.Substring($value.Length - 1200) }
    return $value
}

function Assert-V213NamedTunnelInputs {
    param(
        [string]$Name,
        [string]$Hostname,
        [string]$ConfigPath
    )
    if ([string]::IsNullOrWhiteSpace($Name)) { throw 'NamedTunnelName is required for a Production named tunnel.' }
    if ([string]::IsNullOrWhiteSpace($Hostname)) { throw 'NamedTunnelHostname is required for a Production named tunnel.' }
    if ([string]::IsNullOrWhiteSpace($ConfigPath)) { throw 'NamedTunnelConfig is required for a Production named tunnel.' }
    if ($Name -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$') { throw 'Named tunnel name is invalid.' }
    if ($Hostname -notmatch '^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])$') { throw 'Named tunnel hostname is invalid.' }
    if ($Hostname -match '(?i)(^|\.)trycloudflare\.com$') { throw 'Quick Tunnel hostnames are not valid named-tunnel hostnames.' }
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { throw 'Named tunnel config is missing.' }
}

function Resolve-V213NamedTunnelConfigPath {
    param([string]$ConfigPath)
    return [IO.Path]::GetFullPath($ConfigPath)
}

function Get-V213NamedTunnelConfigMetadata {
    param(
        [string]$ConfigPath,
        [int]$ExpectedLocalPort = 0,
        [string]$ExpectedTunnelName = ''
    )
    $full = Resolve-V213NamedTunnelConfigPath $ConfigPath
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { throw 'Named tunnel config is missing.' }
    $text = Get-Content -LiteralPath $full -Raw -Encoding utf8
    $configDir = Split-Path -Parent $full
    $credentialMatch = [regex]::Match($text, '(?im)^\s*credentials-file\s*:\s*(.+?)\s*$')
    if (-not $credentialMatch.Success) { throw 'Named tunnel config must include credentials-file.' }
    $credentialPath = $credentialMatch.Groups[1].Value.Trim().Trim('"').Trim("'")
    if (-not [IO.Path]::IsPathRooted($credentialPath)) { $credentialPath = Join-Path $configDir $credentialPath }
    $credentialPath = [IO.Path]::GetFullPath($credentialPath)
    if (-not (Test-Path -LiteralPath $credentialPath -PathType Leaf)) { throw 'Named tunnel credentials file referenced by config is missing.' }
    $credItem = Get-Item -LiteralPath $credentialPath
    if ($credItem.Length -le 0) { throw 'Named tunnel credentials file is empty.' }
    try { $credential = Get-Content -LiteralPath $credentialPath -Raw -Encoding utf8 | ConvertFrom-Json }
    catch { throw 'Named tunnel credentials file is not valid JSON.' }
    $accountTag = $credential.PSObject.Properties['AccountTag']
    $tunnelIdProperty = $credential.PSObject.Properties['TunnelID']
    $tunnelSecret = $credential.PSObject.Properties['TunnelSecret']
    if ($null -eq $accountTag -or [string]::IsNullOrWhiteSpace([string]$accountTag.Value) -or
        $null -eq $tunnelIdProperty -or ([string]$tunnelIdProperty.Value -notmatch '^[0-9a-fA-F-]{36}$') -or
        $null -eq $tunnelSecret -or ([string]$tunnelSecret.Value).Length -lt 16) {
        throw 'Named tunnel credentials JSON is missing required Cloudflare tunnel fields.'
    }
    $configTunnelMatch = [regex]::Match($text, '(?im)^\s*tunnel\s*:\s*([^#\r\n]+)')
    if (-not $configTunnelMatch.Success) { throw 'Named tunnel config must include tunnel identity.' }
    $configTunnel = $configTunnelMatch.Groups[1].Value.Trim().Trim('"').Trim("'")
    if ($ExpectedTunnelName -and $configTunnel -ine $ExpectedTunnelName -and $configTunnel -ine [string]$tunnelIdProperty.Value) {
        throw 'Named tunnel config identity does not match NamedTunnelName or credential TunnelID.'
    }
    $servicePort = 0
    $serviceMatches = @([regex]::Matches($text, '(?i)http://(?:127\.0\.0\.1|localhost):(\d{1,5})') | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique)
    if ($serviceMatches.Count -ne 1) { throw 'Named tunnel config must contain exactly one loopback HTTP ingress service port.' }
    [void][int]::TryParse([string]$serviceMatches[0], [ref]$servicePort)
    if ($ExpectedLocalPort -gt 0) {
        if ($servicePort -ne $ExpectedLocalPort) { throw "Named tunnel config must route to http://127.0.0.1:$ExpectedLocalPort or localhost:$ExpectedLocalPort." }
    }
    $sha = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant()
    return [pscustomobject]@{
        config_path = $full
        config_sha256 = $sha
        credentials_file_present = $true
        tunnel_id = ([string]$tunnelIdProperty.Value).ToLowerInvariant()
        service_port = $servicePort
    }
}

function New-V213RuntimeNamedTunnelConfig {
    param(
        [string]$SourceConfigPath,
        [int]$GatewayPort,
        [string]$DestinationPath
    )
    if ($GatewayPort -lt 1 -or $GatewayPort -gt 65535) { throw 'Gateway port is invalid.' }
    $text = Get-Content -LiteralPath $SourceConfigPath -Raw -Encoding utf8
    $matches = [regex]::Matches($text, '(?i)http://(?:127\.0\.0\.1|localhost):\d{1,5}')
    if ($matches.Count -lt 1) { throw 'Named tunnel config has no loopback HTTP ingress service.' }
    $rewritten = [regex]::Replace($text, '(?i)http://(?:127\.0\.0\.1|localhost):\d{1,5}', "http://127.0.0.1:$GatewayPort")
    if ($rewritten -eq $text -and $text -notmatch "(?i)http://(?:127\.0\.0\.1|localhost):$GatewayPort") { throw 'Named tunnel runtime ingress rewrite failed.' }
    [IO.File]::WriteAllText($DestinationPath, $rewritten, [Text.UTF8Encoding]::new($false))
    return [IO.Path]::GetFullPath($DestinationPath)
}

function Invoke-V213CloudflaredCommand {
    param(
        [string]$CloudflaredPath,
        [string[]]$Arguments,
        [int]$TimeoutSeconds = 45
    )
    if (-not $CloudflaredPath -or -not (Test-Path -LiteralPath $CloudflaredPath -PathType Leaf)) { throw 'cloudflared executable was not found.' }
    $tempRoot = Join-Path $env:TEMP ('ii-cloudflared-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
    $stdout = Join-Path $tempRoot 'stdout.log'
    $stderr = Join-Path $tempRoot 'stderr.log'
    try {
        $argumentLine = Join-V213NativeArgumentLine $Arguments
        $process = Start-Process -FilePath $CloudflaredPath -ArgumentList $argumentLine -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $finished = $process.WaitForExit($TimeoutSeconds * 1000)
        if ($finished) { $process.WaitForExit(); $process.Refresh() }
        else {
            try { $process.Kill() } catch { }
            throw 'cloudflared command timed out.'
        }
        $out = if (Test-Path -LiteralPath $stdout) { Get-Content -LiteralPath $stdout -Raw -ErrorAction SilentlyContinue } else { '' }
        $err = if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr -Raw -ErrorAction SilentlyContinue } else { '' }
        return [pscustomobject]@{
            exit_code = [int]$process.ExitCode
            stdout_tail = Get-V213RedactedText $out
            stderr_tail = Get-V213RedactedText $err
            combined_tail = Get-V213RedactedText ($out + "`n" + $err)
        }
    }
    finally {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Assert-V213CloudflaredSuccess {
    param([object]$Result, [string]$Operation)
    if ([int]$Result.exit_code -ne 0) {
        throw "cloudflared $Operation failed. stdout_tail=$($Result.stdout_tail); stderr_tail=$($Result.stderr_tail)"
    }
}

function Test-V213NamedTunnelPrerequisites {
    param(
        [string]$CloudflaredPath,
        [string]$Name,
        [string]$Hostname,
        [string]$ConfigPath,
        [int]$ExpectedLocalPort = 0
    )
    Assert-V213NamedTunnelInputs -Name $Name -Hostname $Hostname -ConfigPath $ConfigPath
    $metadata = Get-V213NamedTunnelConfigMetadata -ConfigPath $ConfigPath -ExpectedLocalPort $ExpectedLocalPort -ExpectedTunnelName $Name
    Assert-V213CloudflaredSuccess (Invoke-V213CloudflaredCommand -CloudflaredPath $CloudflaredPath -Arguments @('tunnel','list') -TimeoutSeconds 45) 'authentication check'
    Assert-V213CloudflaredSuccess (Invoke-V213CloudflaredCommand -CloudflaredPath $CloudflaredPath -Arguments @('tunnel','--config',$metadata.config_path,'ingress','validate') -TimeoutSeconds 45) 'ingress validation'
    $info = Invoke-V213CloudflaredCommand -CloudflaredPath $CloudflaredPath -Arguments @('tunnel','info',$Name) -TimeoutSeconds 45
    Assert-V213CloudflaredSuccess $info 'tunnel credential check'
    if ([string]$info.combined_tail -notmatch [regex]::Escape([string]$metadata.tunnel_id)) { throw 'NamedTunnelName does not resolve to the TunnelID in the credential file.' }
    return [pscustomobject]@{
        ok = $true
        named_tunnel_name = $Name
        named_tunnel_hostname = $Hostname.ToLowerInvariant()
        named_tunnel_config_path = $metadata.config_path
        named_tunnel_config_sha256 = $metadata.config_sha256
        credentials_file_present = [bool]$metadata.credentials_file_present
        service_port = [int]$metadata.service_port
    }
}

function Invoke-V213NamedTunnelDnsRoute {
    param(
        [string]$CloudflaredPath,
        [string]$Name,
        [string]$Hostname
    )
    if ([string]::IsNullOrWhiteSpace($Name) -or [string]::IsNullOrWhiteSpace($Hostname)) { throw 'Named tunnel DNS route requires name and hostname.' }
    if ($Name -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$') { throw 'Named tunnel name is invalid.' }
    if ($Hostname -notmatch '^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])$') { throw 'Named tunnel hostname is invalid.' }
    if ($Hostname -match '(?i)(^|\.)trycloudflare\.com$') { throw 'Quick Tunnel hostnames are not valid named-tunnel hostnames.' }
    $result = Invoke-V213CloudflaredCommand -CloudflaredPath $CloudflaredPath -Arguments @('tunnel','route','dns','--overwrite-dns',$Name,$Hostname) -TimeoutSeconds 60
    if ([int]$result.exit_code -eq 0) { return 'ENSURED_EXACT' }
    throw "cloudflared exact DNS route ensure failed. stdout_tail=$($result.stdout_tail); stderr_tail=$($result.stderr_tail)"
}

function Write-V213NamedTunnelMetadata {
    param(
        [string]$StateRoot,
        [object]$PrerequisiteResult,
        [string]$DnsRouteStatus
    )
    if ([string]::IsNullOrWhiteSpace($StateRoot)) {
        $StateRoot = Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config'
    }
    New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
    $path = Join-Path $StateRoot 'v213-named-tunnel.json'
    $value = [ordered]@{
        schema_version = 1
        product_version = '2.1.3'
        named_tunnel_name = [string]$PrerequisiteResult.named_tunnel_name
        named_tunnel_hostname = [string]$PrerequisiteResult.named_tunnel_hostname
        named_tunnel_config_path = [string]$PrerequisiteResult.named_tunnel_config_path
        named_tunnel_config_sha256 = [string]$PrerequisiteResult.named_tunnel_config_sha256
        credentials_file_present = [bool]$PrerequisiteResult.credentials_file_present
        dns_route_status = [string]$DnsRouteStatus
        updated_utc = (Get-Date).ToUniversalTime().ToString('o')
        plaintext_credentials_persisted = $false
        credential_file_path_persisted = $false
        production_mutation_by_ci = $false
    }
    [IO.File]::WriteAllText($path, (($value | ConvertTo-Json -Depth 8) + "`n"), [Text.UTF8Encoding]::new($false))
    return $path
}
