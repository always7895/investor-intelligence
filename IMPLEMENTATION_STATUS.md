# Investor Intelligence — Development / Release Truth

_Last reconciled: 2026-08-25 Asia/Taipei_

## Authoritative interpretation

`main` now contains the privacy-clean finalization candidate merged from PR #17 at commit:

```text
35a460d509c0329bbddbba0f9fe85d14acf07b82
```

PR #17 is **merged and closed**. Its exact head completed the retained pre-rewrite acceptance workflows successfully. This merge is a source-development milestone only: it is not a production deployment and it does not waive the remaining Git-history and post-rewrite release gates.

The reviewed ancestry represented by PR #12, PR #13 and PR #14 established the public-only LINE boundary, authoritative public-source fabric, three-namespace KV isolation, Phase 4 reporting, Phase 7 recovery and Phase 8 synthetic fault testing. Superseded feature, audit, integration and maintenance branches are not release authority and may be removed only through the final cleanup inventory after post-rewrite acceptance.

## Current exact-head evidence

Commit `35a460d509c0329bbddbba0f9fe85d14acf07b82` completed these exact-head pull-request workflows successfully before merge:

- Final Release Candidate v3 Pre-Rewrite Acceptance — run `32849874849`;
- Phase 1 and 2 Reproducible Audit — run `32849874850`;
- Phase 5 Public LINE Bot and Options Acceptance — run `32849874802`;
- additional retained exact-head gates associated with the same candidate were required to finish before PR #17 merged.

The merged tree is `5656d617f2e95b497dace7bce224bc77996a4f55`. Any subsequent source change creates a new candidate and must receive new exact-head evidence.

## Current privacy and safety invariants

- tracked owner research-universe and owner-preference files are absent from the current tree;
- local research configuration uses ignored `*.local.json` files and cannot enter LINE, Worker or public KV;
- no Worker, LINE webhook, production KV namespace, IBKR bridge or local application is deployed by repository workflows;
- LINE admission defaults to disabled and supports only HMAC-derived direct-chat allowlisting;
- LINE/Worker cannot access portfolio, brokerage account, holdings, quantities, cost/P&L, local watchlists, local reports or private synchronization;
- owner/local report-to-LINE push capability is absent;
- local IBKR, if explicitly enabled later, remains loopback-only, read-only and local-only;
- initial external-user memory is unavailable;
- public, tenant-private and security state use separate KV bindings;
- no authoritative source is automatically activated;
- source-catalog size has no fixed ceiling while runtime traffic remains budget-bounded;
- paid APIs, paid models, paid data, paid fallback and automatic plan upgrades are forbidden;
- validation workflows use immutable Action refs and locked dependencies;
- Actions dependency caches are forbidden;
- future Actions artifacts must be final-release evidence, use an immutable action SHA and retain for no more than one day.

## Public option-data release decision

No reviewed source currently satisfies all requirements for shared automated BID/ASK delivery at zero cost: lawful automated access, sustainable free access and permission to display or redistribute the data to other LINE users.

Therefore the releasable zero-cost mode remains intentionally reduced:

- shared live option lookup is unavailable and fails closed;
- LINE never falls back to IBKR, another broker, owner holdings or a paid feed;
- users may run the deterministic manual calculator only with values they supply themselves;
- supplied values are labelled unverified and are never represented as fetched current market data;
- a future live provider requires a separate rights, redistribution, adapter and exact-head acceptance amendment.

## Remaining mandatory blockers

### 1. Backup-first Git-history remediation

Current-tree cleanup does not erase historical Git objects. Final release still requires:

1. a fresh exact-finalization offline mirror and verified bundle;
2. destructive rewrite of official branch/tag history using the approved backup-first transaction;
3. a fresh GitHub clone with `scripts/full_history_privacy_scan.py --scope all --require-clean`;
4. a separate audit of GitHub-managed pull refs;
5. complete Python, Worker, package, checksum, manifest, SPDX SBOM and clean-install acceptance on the rewritten exact head.

At least one verified rollback bundle must remain protected through the configured cooling-off period.

### 2. Final release receipt and cleanup

`config/final-cleanup-policy.json` keeps repository, branch and backup deletion locked until an exact rewritten-head receipt proves all mandatory release assertions. GitHub Actions storage cleanup is permitted separately because it deletes only superseded hosted artifacts, caches and completed run records while preserving current exact-head evidence and never touching local history backups or Git refs.

## Release state

```text
MAIN_SOURCE_CANDIDATE = 35a460d509c0329bbddbba0f9fe85d14acf07b82
PR17 = merged
DEPLOYED = false
LINE_PRODUCTION_ENABLED = false
IBKR_TO_LINE = forbidden
PRIVATE_SYNC = absent
PAID_FALLBACK = forbidden
CURRENT_TREE_OWNER_CONFIG = absent
ACTIONS_CACHE = forbidden
ACTIONS_ARTIFACT_RETENTION_TARGET_DAYS = 1
HISTORY_CLEAN = false
PUBLIC_OPTIONS_LIVE_PROVIDER_READY = false
PUBLIC_OPTIONS_MANUAL_CALCULATOR = available_with_unverified_input_label
FINAL_CLEANUP = locked_until_final_receipt
FINAL_RELEASE_READY = false
```

## Local action required

None. No credential, raw LINE ID, portfolio, brokerage-account detail or other private user data is required for repository validation.
