# Investor Intelligence legacy installer guard
#
# The original installer was unsafe and obsolete: it expected a committed
# credential file and registered an incomplete single schedule. The local
# project is intentionally not installed during development.

$ErrorActionPreference = "Stop"

Write-Host "Investor Intelligence is not ready for local installation." -ForegroundColor Yellow
Write-Host "This legacy installer has been disabled to prevent an incomplete or unsafe setup." -ForegroundColor Yellow
Write-Host "Wait for the final signed/versioned release package and its bootstrap.ps1." -ForegroundColor Cyan
Write-Host "No files, tasks, secrets or services were changed." -ForegroundColor Green

exit 2
