# Investor Intelligence legacy scheduler guard
#
# The original task script embedded a user-specific path and registered an
# incomplete single schedule. It is disabled until the final Phase 7 release.

$ErrorActionPreference = "Stop"

Write-Host "Investor Intelligence scheduled tasks are not ready for installation." -ForegroundColor Yellow
Write-Host "Wait for the final release bootstrap.ps1 and idempotent morning/evening scheduler." -ForegroundColor Cyan
Write-Host "No scheduled task was created, modified or removed." -ForegroundColor Green

exit 2
