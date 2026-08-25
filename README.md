# Investor Intelligence System

Privacy-first, zero-cost market-research software for public-source analysis, Traditional Chinese briefings, public option observations and a shared LINE research bot.

> Research software only. It does not provide personalized investment advice, guarantee returns or replace verification against primary sources.

## Non-negotiable policies

- **Public-source provenance:** source claims, project scoring, model inference and local/private preferences remain separate layers.
- **Shared LINE is public-only:** LINE and the Worker cannot access IBKR, brokerage accounts, holdings, quantities, costs, P&L, owner/local watchlists, local reports or private synchronization data.
- **Direct chat only:** shared LINE supports only `disabled` or HMAC-derived `allowlist` admission. Group and room events are rejected.
- **No owner-report push path:** the repository contains no local report-to-LINE delivery sender and no raw LINE user ID target.
- **Free-only operation:** no paid model/API/data dependency, automatic upgrade or paid fallback. Quota exhaustion fails closed.
- **No automatic trading:** the shared system has no order path. Optional local IBKR support is loopback-only/read-only and is structurally separated from LINE, Worker and public KV.
- **No development deployment:** no Worker, webhook, production KV migration or development install is performed before final release acceptance.

## Shared LINE architecture

```text
LINE direct user event
  -> signature/freshness/admission checks
  -> HMAC tenant identifier
  -> deterministic public tools or authenticated allowlisted local-model route
  -> reply message
```

The shared bot can answer public research, ranking, report and public-option questions. It cannot answer account/portfolio/broker questions and rejects first-person sensitive financial disclosures before model use or memory storage.

Initial external release keeps conversation memory unavailable. When a later release explicitly enables memory, tenant state must remain encrypted, TTL-bound, deletable and physically isolated from public/security state.

The unauthenticated `/health` endpoint exposes only static safety posture. It does not reveal tenant membership, snapshot identifiers, timestamps or model routing details.

## Physical KV isolation

The Worker uses three independent bindings:

- `PUBLIC_CACHE` — attested public reports, scores, source views, option snapshots and manifests only;
- `TENANT_PRIVATE_CACHE` — encrypted tenant conversation/job state only;
- `EPHEMERAL_SECURITY_CACHE` — hashed webhook dedupe and pseudonymous rate-limit state only.

The former combined `CACHE` binding is forbidden. A future production migration must create fresh distinct namespace IDs and must not copy a legacy combined namespace.

## Public option data

LINE options use a separate owner-independent public symbol policy and `options_public_latest.json`. Public option records may contain market observations such as expiration, DTE, call/put, strike, BID, ASK, midpoint, spread, volume, open interest, IV, provider-supplied delta, timestamp, delay/freshness and source provenance.

They may not contain or derive from account IDs, holdings, shares, quantities, cost basis, P&L, margin, buying power, covered-contract capacity, private preferences or IBKR/broker lineage. Unknown public fields fail closed rather than being silently copied.

Public current-data functionality remains disabled until an eligible reviewed free public provider passes rights, schema, privacy, adapter and runtime-health gates. There is no IBKR fallback for LINE.

## Local-only research runtime

A separate local research workflow may use local configuration and, when explicitly enabled, a loopback-only read-only IBKR provider. That path is local-only:

```text
local research -> optional local IBKR read-only -> local report
```

There is no path from this output to LINE, Worker, public KV or another tenant. `scripts/daily_briefing.py` intentionally has no outbound delivery capability.

## Authoritative source fabric

The source catalog is modular and has **no fixed source-count limit**. The current development inventory is a snapshot of globally diverse public/free candidates rather than a runtime activation list.

Catalog membership never enables a source. Runtime activation requires all applicable gates, including authority, lawful/free-access review, schema review, privacy review, fixture/adapter tests and runtime health. Runtime work is bounded by request, response-byte, wall-time, retry and per-host concurrency budgets even as the catalog grows.

Primary/direct evidence is distinguished from official statistics, regulated-market data, corroboration and discovery-only sources. Paid/paywalled bypasses are forbidden.

## Source attribution

The project distinguishes:

1. direct source claim with author/authority, timestamp and canonical URL;
2. project-authored operationalization;
3. evidence-based model inference;
4. optional local/private preference layers that are ineligible for shared LINE/public artifacts.

Public research associated with named analysts/authors is never converted into an endorsement unless the cited source actually supports that claim.

## Traditional Chinese reports

Phase 4 produces public-only Traditional Chinese briefing artifacts. Public reports require explicit public eligibility attestations and must not inherit local watchlists, portfolios, brokerage data or private reports.

## Zero-cost model

Runtime policy is:

```text
FREE_ONLY_FAIL_CLOSED
```

Permitted infrastructure is limited to lawful free public data, the already-available private local model, Cloudflare free allocation when explicitly deployed later, and trusted self-hosted GitHub Actions. No paid fallback or automatic plan upgrade is allowed.

## CI and supply-chain policy

Validation uses the trusted self-hosted Windows runner. Active workflows are read-only, pin third-party Actions to immutable commit SHAs, do not persist checkout credentials, use isolated binary-only hash-locked Python dependency installation plus `pip check`, and use the committed npm lock with lifecycle scripts disabled.

Validation results are tied to exact commits. A success on an older commit is never promoted to a newer head.

## Current development line

The canonical development stack is currently:

```text
PR #12  shared LINE public-only privacy boundary
   -> PR #13  privacy-first authoritative source catalog/adapters
      -> PR #14  physical KV isolation + Phase 4/7/8/release hardening
```

PR #13 exact-head Phase 3 catalog/diversity/adapter/public-options acceptance has passed on its accepted development head. PR #14 remains Draft and must pass every exact-head BARRY gate after each change.

Legacy PRs are development history only and are not automatically merged into the canonical line.

## Repository layout

```text
config/                         public/runtime policies; local/private files are release-excluded
schemas/                        strict public/source schemas
scripts/
  authoritative_source_catalog.py
  build_line_public_options.py
  daily_briefing.py             local-only; no external delivery
  generate_public_briefing.py
  sync_to_kv.py                 validation-only by default
  security_check.py
  full_history_privacy_scan.py
  release_package.py
cloud/
  src/                          shared public-only LINE Worker
tests/                          synthetic/offline regression tests
.github/workflows/              trusted read-only BARRY acceptance gates
```

Generated data, reports, logs, tenant data, secrets, real portfolios, runner state and owner/local watchlist/preferences are excluded from the final release package.

## Final release gates

A final package is forbidden until, at minimum:

- all exact-head current-tree/BARRY gates pass;
- LINE/IBKR separation and three-namespace KV isolation pass;
- Phase 4, Phase 7 and Phase 8 synthetic/fault/clean-install acceptance pass;
- Git-history privacy inventory is remediated and the explicit manual all-object clean gate passes;
- final ZIP reproducibility, manifest, checksum and SBOM verification pass;
- release state remains fail-closed until the exact candidate satisfies every mandatory gate.

History rewrite/force-push is destructive and is never performed automatically. It requires an offline backup and explicit approval.
