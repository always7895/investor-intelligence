# Load this host's Microsoft module explicitly. A WinPS5.1 process started by
# pwsh can inherit a PSModulePath pointing at incompatible PowerShell7 modules.
# No registry, persistent environment, credential or inference-preset changes.
Set-StrictMode -Version Latest
$hostModules=Join-Path $PSHOME 'Modules'
$otherModules=@($env:PSModulePath-split[IO.Path]::PathSeparator|Where-Object {$_-and$_-ne$hostModules})
$env:PSModulePath=(@($hostModules)+$otherModules)-join[IO.Path]::PathSeparator
$securityModule=Join-Path $hostModules 'Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1'
Import-Module -Name $securityModule -Global -ErrorAction Stop

function Initialize-V213SecContact {
    if($env:SEC_CONTACT_EMAIL-match'^[^@\s]+@[^@\s]+\.[^@\s]+$'){return $true}
    $path=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence\UserData\config\sec-contact.local.txt'
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){return $false}
    $secure=$null; $plain=$null
    try {
        $secure=ConvertTo-SecureString -String ((Get-Content -LiteralPath $path -Raw -Encoding utf8).Trim())
        $pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try {$plain=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)}
        finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)}
        if($plain-match'^[^@\s]+@[^@\s]+\.[^@\s]+$'){$env:SEC_CONTACT_EMAIL=$plain;return $true}
    }
    catch {Write-Host ('II_PROGRESS SEC_CONTACT_UNAVAILABLE; exception_type='+$_.Exception.GetType().Name)}
    finally {$plain=$null;if($secure){$secure.Dispose()}}
    return $false
}
