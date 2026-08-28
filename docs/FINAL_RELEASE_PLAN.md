# Final Release and Local Installation Plan

_Finalized: 2026-08-28 Asia/Taipei — GitHub Support purge completed_

## Normative boundary

```text
LINE_DATA_SCOPE=PUBLIC_ONLY
LINE_IBKR_BRIDGE=FORBIDDEN
LINE_PORTFOLIO_TOOLS=FORBIDDEN
LINE_PRIVATE_SYNC=FORBIDDEN
LINE_GROUP_ROOM=REJECTED
LINE_OWNER_DATA=FORBIDDEN
FREE_ONLY_MODE=FAIL_CLOSED
```

The final package does not change these boundaries. Installation never creates a path from owner/local research or IBKR into the shared LINE bot.

## Development mode

The application remains uninstalled and undeployed during development. Only the trusted self-hosted BARRY runner is present for isolated validation.

Development branches must not:

- install or register the application;
- configure the production LINE webhook;
- create/migrate production KV namespaces;
- authenticate IBKR;
- restore private data or secrets;
- enable billing, paid fallback or automatic upgrades.

`install.ps1` now delegates to the reviewed final `bootstrap.ps1`. Scheduling remains disabled by default and requires the explicit `register-task.ps1 -Enable` action after installation.

## Mandatory release gates

No downloadable package is accepted until the same exact `main` commit passes both the fresh all-object history workflow and the formal package workflow, collectively proving:

1. current-tree security/privacy scan;
2. immutable workflow/dependency supply-chain gates;
3. Phase 1–8 Python, TypeScript and Worker acceptance;
4. shared LINE public-only and broker/owner separation;
5. three-namespace KV isolation and clean migration preflight;
6. public artifact closed-schema, provenance, freshness and atomic-publication tests;
7. source catalog/adapter rights, schema, privacy and replay gates;
8. scheduling, recovery, quota and synthetic fault-injection tests;
9. reproducible package, checksum, manifest and SBOM verification;
10. clean-install simulation from the package;
11. completed GitHub Support dereferencing plus a fresh isolated `--scope all --require-clean` result;
12. final human review of release truth and package contents.

An older successful workflow does not transfer to a newer head. Pending, queued or cancelled jobs are not PASS.

## Final package

The canonical release is produced only by the reviewed package builder from tracked files in an exported clean tree. It includes:

- deterministic outer final-delivery ZIP and separate SHA-256;
- versioned source/application ZIP and its SHA-256;
- internal release manifest and metadata;
- SPDX SBOM;
- locked Python and Node dependency metadata;
- tests, public configuration examples and documentation.

The package excludes:

- Git history and unreachable Git objects;
- LINE, Cloudflare, GitHub or broker credentials;
- raw LINE IDs, messages, answers, reply tokens or optional tenant memory/jobs;
- owner watchlists, preferences, portfolio files or local reports;
- IBKR responses, account IDs, quantities, costs, P&L or coverage;
- data caches, generated reports, logs and temporary state;
- runner `_work`, `_diag`, service configuration and credentials;
- `.env`, local JSON, database/key/certificate files;
- model weights.

Synthetic package builds may run while release status is pending, but a final release build must fail unless release truth is fully PASS.

## Delivery

After final acceptance:

1. freeze the accepted commit;
2. build twice and prove byte reproducibility;
3. verify ZIP contents, checksum, manifest and SBOM independently;
4. upload the exact application evidence with one-day retention;
5. assemble the deterministic outer direct-delivery bundle twice from that accepted evidence and verify its separate SHA-256;
6. provide the user a direct download link only after every file exists and passes verification.

No development branch or runner workspace is used as an installer.

## First local installation

Installation begins only after the outer delivery ZIP and inner application ZIP have been verified. The extracted delivery folder provides a double-click `install-final.cmd` path and a PowerShell `install-final.ps1` path. Installation must:

- verify version and SHA-256 before extraction;
- refuse to run inside the self-hosted runner workspace;
- use only free/open-source dependencies and committed locks;
- create a separate application directory;
- keep secrets and local/private data outside source files;
- start with LINE, public KV writes, schedules, memory and IBKR disabled;
- run security, configuration and local smoke tests before any feature is enabled;
- never print secrets or private values;
- preserve existing generated data, reports and the local briefing log during an explicit verified force reinstall;
- never enable a paid plan or provider.

The local owner research workflow and optional local IBKR read-only workflow remain a separate trust domain. They have no outbound LINE delivery capability.

## Production LINE activation

A later production activation requires a separate reviewed transaction:

1. confirm Workers Free and LINE free-plan constraints;
2. create six fresh distinct production/preview KV namespace IDs;
3. configure secrets outside Git;
4. keep admission disabled during smoke tests;
5. verify signature, health, direct-chat allowlist and public-only replies;
6. verify group/room, portfolio, broker and owner-data requests fail closed;
7. verify public current-data remains disabled until reviewed providers are ready;
8. enable only explicitly accepted public features.

No private credential or broker login is required for repository acceptance.

## Uninstall, recovery and rollback

The final installer must support idempotent removal/recovery of application code and schedules without touching the GitHub Actions runner. Optional tenant state, if a future release enables it, is preserved or deleted only through an explicit choice.

Rollback restores the prior verified code/schedule definition without restoring revoked secrets, copying legacy combined KV data or re-enabling a failed feature.
