# Investor Intelligence — Development / Release Truth

_Last reconciled: 2026-08-25 Asia/Taipei_

## Authoritative interpretation

`main` is **not** a Phase 1–8 release and is not the current canonical development head. Draft pull-request evidence must never be described as merged or deployed production state.

The sole finalization line is:

```text
integration/final-release-candidate-v3
```

It was cut from accepted predecessor commit `a7849229bc53c74d08476bb2258effff1b8ef0eb` and tree `669296817b6ed05732dde978ca1fbfe5c3d86fac`. Every newer finalization head must be revalidated; success on an earlier head never transfers automatically.

PR #17 is the open Draft finalization PR. PR #12, PR #13 and PR #14 remain the reviewed stacked ancestry for the public-only LINE boundary, authoritative-source fabric, three-namespace KV isolation, Phase 4, Phase 7 and Phase 8. Older feature and integration PRs are superseded development history, not release authority.

## Durable exact-head evidence

Accepted predecessor `a7849229bc53c74d08476bb2258effff1b8ef0eb` completed these BARRY workflows successfully on the same SHA:

- Canonical Release Candidate Acceptance v2 — run `32834953663`;
- Release Candidate Truth — run `32834957994`;
- Full Candidate History Privacy Inventory — run `32834958004`;
- Phase 4 Traditional Chinese Briefing — run `32834957987`;
- Phase 7 Scheduling and Recovery — run `32834958071`;
- LINE Three-Namespace KV Isolation — run `32834958066`;
- Phase 8 Synthetic Fault Injection — run `32834958146`.

Finalization head `7240c8c86b0f763bc0fb29e2d4dc386af00e49f7` subsequently passed the read-only **Final Release Candidate v3 Pre-Rewrite Acceptance** in run `32840317934`. That exact-head run combined current-tree privacy, owner-config removal, LINE/broker and three-KV boundaries, authoritative source gates, Phase 4/7/8 retained regressions, complete Python and Worker suites, content-free history inventory, reproducible synthetic ZIP, SHA-256, manifest, SPDX SBOM and a distinct clean-install environment.

The public-options licensing transaction completed successfully in run `32846253322` and committed the reviewed provider decisions while removing its own write-enabled workflow, marker and patch helper. That transaction passed the complete Python suite and canonical boundary checks before publication. Its resulting source commit `105e3a6950d56cb8b1c0700921ce059c86e6df16` uses GitHub noreply metadata.

These are development/pre-rewrite acceptances only. This documentation reconciliation creates a newer exact head, so the retained read-only acceptance workflows must pass again. History remediation plus post-rewrite fresh-clone acceptance remain mandatory.

## Current privacy and safety invariants

- tracked owner research-universe and owner-preference files are absent from the current tree;
- local research configuration uses ignored `*.local.json` files and cannot enter LINE, Worker or public KV;
- all development PRs remain Draft and unmerged;
- no Worker, LINE webhook, production KV namespace, IBKR bridge or local application is deployed by development workflows;
- LINE admission defaults to disabled and supports only HMAC-derived direct-chat allowlisting;
- LINE/Worker cannot access portfolio, brokerage account, holdings, quantities, cost/P&L, local watchlists, local reports or private synchronization;
- owner/local report-to-LINE push capability is absent;
- local IBKR, if explicitly enabled later, remains loopback-only, read-only and local-only;
- initial external-user memory is unavailable;
- public, tenant-private and security state use separate KV bindings;
- no authoritative source is automatically activated;
- source-catalog size has no fixed ceiling while runtime traffic remains budget-bounded;
- paid APIs, paid models, paid data, paid fallback and automatic plan upgrades are forbidden;
- validation workflows use immutable Action refs and locked dependencies.

## Public option-data release decision

No reviewed source currently satisfies all requirements for shared automated BID/ASK delivery at zero cost: lawful automated access, sustainable free access and permission to display or redistribute the data to other LINE users.

The provider catalog now records explicit decisions instead of treating every public web page or free personal API as a usable shared feed:

- Cboe delayed-options pages: automated extraction prohibited; adapter `not_permitted`;
- OCC market-data reports: governing terms prohibit automated service access; adapter `not_permitted`;
- Market Data Free Forever: delayed personal/internal use exists, but shared recent-data redistribution requires commercial and exchange licensing; adapter `not_permitted` for shared LINE;
- Tradier brokerage market-data API: rejected because shared LINE permanently forbids broker entitlements, broker tokens and any LINE-to-broker bridge;
- Nasdaq, NYSE, CME, Eurex, HKEX, TAIFEX, JPX/OSE and ASX: automated access and redistribution rights remain unverified, no adapter, disabled;
- yfinance: local development-only and impossible to promote through configuration flags.

`docs/PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW.md` records the reviewed evidence. `scripts/public_options_provider_gate.py` pins the four rejected decisions so a configuration-only change cannot activate them.

Absence of a live shared quote provider does **not** authorize a bypass and is not a blocker for the deliberately reduced zero-cost release mode. In that mode:

- live shared option lookup remains unavailable and fails closed;
- LINE never falls back to IBKR, another broker, owner holdings or a paid feed;
- the user may run the deterministic manual calculator only by supplying ticker, option type, expiration/DTE, strike, BID, ASK and spot;
- supplied figures are labelled unverified and are never represented as fetched current market data;
- a future live provider requires a separate rights, redistribution, adapter and exact-head acceptance amendment.

## Known final-release blockers

### 1. Git history

The accepted predecessor's non-destructive history inventory scanned 504 commits, 587 blobs and 1,210 trees. It returned `clean=false` with 552 content-free findings, including historical non-noreply commit metadata, assigned sensitive-value patterns, direct identifier patterns, historical owner/private paths, raw LINE identifiers and user-specific Windows paths.

Current-tree cleanup does not erase historical Git objects. Final release therefore requires a backup-first destructive history transaction, followed by a fresh GitHub clone and `--scope all --require-clean`.

A verified offline pre-rewrite bundle already exists and remains protected. A new exact-finalization backup must also be created before the final rewrite so the final tree and ref inventory are recoverable.

### 2. Final exact-head acceptance and package

Every finalization change must rerun the combined pre-rewrite workflow. The final ZIP, SHA-256 checksum, manifest and SPDX SBOM may be promoted only after rewritten history is clean, the repository passes a fresh GitHub clone, and `config/release-candidate-status.json` plus the final cleanup receipt are bound to that exact head.

## Final cleanup policy

The user has authorized removal of unnecessary backups and generated files **after** the final version is complete. `config/final-cleanup-policy.json` keeps that operation locked until an exact final acceptance receipt proves history cleanliness, fresh-clone acceptance, clean install and reproducible package integrity.

Until then:

- no verified backup is deleted;
- no obsolete branch is deleted as part of development validation;
- no GitHub-managed pull ref is modified;
- no final ZIP, checksum, manifest, SBOM or acceptance receipt is removed.

After final acceptance, a separate reviewed transaction may remove only the closed allowlist of transient repository files and explicitly inventoried obsolete branches/backups. It must retain the newest verified rollback bundle and at least one verified backup through the required cooling-off period.

## Release state

```text
DEVELOPMENT = active
FINALIZATION_BRANCH = integration/final-release-candidate-v3
FINALIZATION_PR = 17 (Draft)
DEPLOYED = false
LINE_PRODUCTION_ENABLED = false
IBKR_TO_LINE = forbidden
PRIVATE_SYNC = absent
PAID_FALLBACK = forbidden
CURRENT_TREE_OWNER_CONFIG = absent
HISTORY_CLEAN = false
CBOE_AUTOMATION = prohibited
OCC_AUTOMATION = prohibited
MARKETDATA_SHARED_REDISTRIBUTION = prohibited_without_paid_licenses
TRADIER_SHARED_BROKER_ACCESS = prohibited
PUBLIC_OPTIONS_LIVE_PROVIDER_READY = false
PUBLIC_OPTIONS_MANUAL_CALCULATOR = available_with_unverified_input_label
FINAL_CLEANUP = locked
FINAL_RELEASE_READY = false
```

## Local action required

None. No credential, raw LINE ID, portfolio, brokerage-account detail or other private user data is required for repository validation.
