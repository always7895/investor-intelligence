[CmdletBinding()]
param([string]$ProjectRoot = '')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if([string]::IsNullOrWhiteSpace($ProjectRoot)){$ProjectRoot=Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)}
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
$source=Join-Path $ProjectRoot 'scripts\ci_v213_r70_package.ps1'
if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw "Reviewed R70 packager is missing: $source"}
$text=Get-Content -LiteralPath $source -Raw -Encoding utf8
$text=$text.Replace('Serenity-Latest-MultiSource-R70','Serenity-Latest-MultiSource-R75')
$text=$text.Replace('v213-r70','v213-r75').Replace('V213_R70','V213_R75').Replace('R70_','R75_').Replace('R70-','R75-').Replace('-R70','-R75').Replace('r70_','r75_').Replace('r70-','r75-').Replace('-r70','-r75')
$generated=Join-Path $env:RUNNER_TEMP ('ci_v213_r75_package.generated.'+[guid]::NewGuid().ToString('N')+'.ps1')
[IO.File]::WriteAllText($generated,$text,[Text.UTF8Encoding]::new($false))
try{
    & $generated -ProjectRoot $ProjectRoot
    if(-not$?){throw 'Generated R75 packager did not complete.'}
}finally{Remove-Item -LiteralPath $generated -Force -ErrorAction SilentlyContinue}
if(-not$env:R75_ZIP-or-not(Test-Path -LiteralPath $env:R75_ZIP -PathType Leaf)){throw 'R75 packager did not expose R75_ZIP.'}
$required=@(
    'scripts/v213_r75_activation_preflight.py',
    'scripts/v213_r75_activation_preflight_entry.py',
    'scripts/run_v213_local_llm_bridge_core_v3.ps1',
    'scripts/v213_local_llm_gateway_r75.py',
    'run-v213-scheduled-refresh.ps1',
    'install-v213-r75-runtime.ps1',
    'R75-SOURCE-HARDENING.json'
)
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive=[IO.Compression.ZipFile]::OpenRead($env:R75_ZIP)
try{
    $names=@($archive.Entries|ForEach-Object{$_.FullName.Replace('\','/')})
    foreach($name in $required){if($names-notcontains$name){throw "R75 package is missing: $name"}}
    $canonical=$archive.GetEntry('activate-v213-seven-field-schedule.ps1')
    $alias=$archive.GetEntry('activate-v213-seven-field-schedule-serenity-latest.ps1')
    if($null-eq$canonical-or$null-eq$alias){throw 'R75 package activation wrappers are missing.'}
    $reader=New-Object IO.StreamReader($canonical.Open(),[Text.Encoding]::UTF8,$true);try{$a=$reader.ReadToEnd()}finally{$reader.Dispose()}
    $reader=New-Object IO.StreamReader($alias.Open(),[Text.Encoding]::UTF8,$true);try{$b=$reader.ReadToEnd()}finally{$reader.Dispose()}
    if($a-ne$b){throw 'R75 canonical activation and compatibility alias differ.'}
    foreach($marker in @('V213_R75_ACTIVATION_PREFLIGHT','V213_ACTIVATION_PREFLIGHT_ONLY','publication_mode_aware=true')){if(-not$a.Contains($marker)){throw "R75 packaged activation lost marker: $marker"}}
}finally{$archive.Dispose()}
Write-Host "V213_R75_PACKAGE_WRAPPER = PASS; zip=$env:R75_ZIP; sha256=$env:R75_SHA" -ForegroundColor Green
