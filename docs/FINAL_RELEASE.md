# Investor Intelligence v2.0.0 Final Release

## Release identity

- Version: `2.0.0`
- Distribution: verified private direct delivery
- Deployment performed: no
- External users admitted: no
- Billing enabled: no
- Git history included in package: no

GitHub Support completed deletion of the affected pull-request internal references and cleared the unreferenced commits. Exact-head acceptance requires both the fresh isolated all-object history workflow and the formal package workflow to succeed on the same `main` commit.

## Install from the final delivery bundle

The final delivery bundle contains the versioned application ZIP, its SHA-256, manifest, SPDX SBOM, final acceptance receipt, `install-final.ps1`, `install-final.cmd` and a final release notice. The downloaded outer delivery ZIP also has a separate SHA-256 file.

Extract the delivery bundle and double-click `install-final.cmd`. The equivalent PowerShell command is:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\install-final.ps1 -CreateDesktopShortcut
```

The installer verifies the application ZIP against the supplied SHA-256 before extraction. It then installs a SHA-256-verified portable CPython 3.12.10 runtime, installs only the committed hash-locked binary dependencies, runs `pip check` and executes the package-compatible offline smoke suite. An explicit `-Force` reinstall preserves existing `data`, `reports` and `daily_briefing.log` while replacing application files.

Default installation root:

```text
%LOCALAPPDATA%\InvestorIntelligence
```

No LINE token, Cloudflare credential, brokerage login, account information, holdings or private messages are required for installation.

## First local run

Start from the desktop shortcut or run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\InvestorIntelligence\App\2.0.0\run-local.ps1" -OpenReports
```

On first run, the launcher opens the ignored local research-universe file. Replace the `EXAMPLE` ticker with the public symbols you want to research, save, and run again. The local briefing remains local-only and cannot send LINE/public-KV output or place brokerage orders.

## Optional schedules

Scheduling is never enabled by installation. Explicitly enable weekday local runs at 07:30 and 20:30 with:

```powershell
& "$env:LOCALAPPDATA\InvestorIntelligence\App\2.0.0\register-task.ps1" -Enable
```

Disable them with:

```powershell
& "$env:LOCALAPPDATA\InvestorIntelligence\App\2.0.0\register-task.ps1" -Disable
```

## Uninstall

The default uninstall preserves local configuration and generated reports:

```powershell
& "$env:LOCALAPPDATA\InvestorIntelligence\App\2.0.0\uninstall.ps1"
```

Permanent deletion of local configuration and reports requires the explicit `-RemoveLocalData` switch.

## Runtime boundaries

```text
LINE_DATA_SCOPE=PUBLIC_ONLY
LINE_IBKR_BRIDGE=FORBIDDEN
LINE_PORTFOLIO_TOOLS=FORBIDDEN
LINE_PRIVATE_SYNC=FORBIDDEN
LINE_GROUP_ROOM=REJECTED
LINE_OWNER_DATA=FORBIDDEN
FREE_ONLY_MODE=FAIL_CLOSED
```

The final package does not deploy the LINE Worker. A later activation is a separate reviewed transaction requiring fresh KV namespaces, secrets outside Git, disabled admission during smoke tests and explicit verification of public-only behavior.

## Exact-head acceptance and delivery

`Final History and Support Purge Confirmation` creates a fresh isolated Git object database, fetches exact `main` plus every remaining GitHub-managed pull ref, and requires a zero-finding content-free all-object scan. `Formal Private Release Package` builds and verifies the deterministic application ZIP, checksum, manifest, SPDX SBOM, clean install and exact acceptance receipt.

Only after both workflows pass is the outer direct-delivery bundle built twice with `scripts/build_delivery_bundle.py`; the two outputs must be byte-identical and its SHA-256 must match before delivery.
