# LINE Public-Options-Only Architecture

_Last updated: 2026-08-24 Asia/Taipei_

## Non-negotiable boundary

The shared LINE Bot is a public-research client. It must never connect directly or indirectly to Interactive Brokers, any brokerage account, a portfolio file, account-derived coverage, or an owner-private synchronization service.

```text
INDEPENDENT PUBLIC DATA PIPELINE
        |
        v
explicit public artifacts + attestations
        |
        v
private/broker/owner-lineage rejection gate
        |
        v
content-addressed public KV snapshot
        |
        v
LINE Worker
```

The local IBKR runtime, if deliberately enabled for a separate local use case, is a different trust domain:

```text
LOCAL IBKR GATEWAY --> local read-only analysis only
                     X no Worker call
                     X no LINE call
                     X no public KV write
                     X no model-context export
                     X no derived capacity export
```

Removing account identifiers or share quantities is not enough. A record derived from IBKR remains broker-derived and is rejected from the LINE path even after redaction.

## Shared-user admission

- `LINE_ACCESS_MODE=disabled` is the default.
- Only `disabled` and `allowlist` are supported admission modes.
- `allowlist` admits only HMAC-derived tenant IDs in `LINE_ALLOWED_TENANT_HASHES`.
- Raw LINE user, group and room IDs are never stored in the allowlist.
- Group and room operation is permanently disabled in source code; it is not a deployment switch.
- Disabled, invalidly configured, missing-secret and non-allowlisted events are silently ignored before any reply, tenant/event KV write or rate-limit write.
- Both tenant-hash and tenant-data encryption secrets must exist before allowlist operation can answer.
- The model cannot elevate a tenant or alter the allowlist.

The silent-denial rule protects the free LINE reply quota and prevents an unapproved user from probing friend membership or bot readiness through different error messages.

## Owner-data minimization

The shared bot contains no owner-specific role and does not inherit:

- the local/private portfolio;
- `PORTFOLIO_JSON`;
- the local IBKR provider;
- covered-contract capacity;
- account ID, quantity, cost basis, market value or P&L;
- the owner's watchlist;
- owner-specific ticker aliases or examples;
- private reports, private option files or private model context.

`config/line-public-symbols.json` is a separate catalog and has `owner_watchlist_inheritance=false`. It is empty by default so an undeclared owner watchlist can never become shared bot content.

## Independent public snapshot artifacts

The shared LINE snapshot never reads generic operator/watchlist pipeline filenames. It accepts only the following independent files:

```text
data/cache/public_snapshot_metadata.json
data/cache/scores_public_latest.json
data/cache/options_public_latest.json
data/cache/source_views_public_latest.json        # optional
reports/public_briefing_latest.md
reports/public_morning_latest.md                   # optional
reports/public_evening_latest.md                   # optional
```

Legacy files such as `scores_latest.json`, `options_latest.json`, `source_views_latest.json`, `health_latest.json` and private/operator reports are never fallbacks. Known private fields are rejected rather than silently removed.

Every JSON record must declare:

```json
{
  "line_public_eligible": true,
  "provider_scope": "public_only",
  "owner_watchlist_inherited": false
}
```

Option records must additionally declare all broker/account/position attestations false. Public Markdown reports must contain all three literal attestations:

```text
<!-- line-public-eligible: true -->
<!-- provider-scope: public_only -->
<!-- owner-watchlist-inherited: false -->
```

The freshness timestamp comes from `public_snapshot_metadata.json`; synchronization time is never substituted for data time. This prevents an old report or ranking from appearing fresh merely because it was republished.

Public KV synchronization is validation-only by default. A network write requires both the explicit `--apply` command and `PUBLIC_KV_SYNC_ENABLED=true`, while `FREE_ONLY_MODE=true`, `CLOUDFLARE_PLAN=workers_free` and paid fallback remains disabled.

Each manifest entry contains the artifact byte count, source path and SHA-256. All objects and the manifest are written before `snapshot:current` is promoted. Object and total-size limits fail closed before a write.

## Public option dataset

The public option builder uses an owner-independent symbol catalog and a public provider path. It transforms strategies into generic `call_observations` and `put_observations`. LINE never labels a quote as covered by a user position and never displays covered capacity.

The KV publisher fails the entire promotion when it sees portfolio, position, account, quantity, coverage, cost/P&L, IBKR or brokerage lineage. It does not silently redact and continue.

Public option chains are deterministic-tool-only. They are read, ticker-filtered, freshness-checked and formatted only by the dedicated option intent. They are never inserted into an arbitrary local-Qwen prompt merely because a general question contains a ticker. This prevents stale or unnecessarily broad chain data from becoming free-form model context.

## Tenant data and sensitive input

Optional conversation memory is:

- off by default;
- direct-chat-only;
- HMAC tenant scoped;
- AES-GCM encrypted with a per-tenant derived key;
- limited to eight turns and at most 24 hours;
- never used by another tenant;
- removable through the tenant deletion command.

This memory contains only what that LINE user sent to the bot. No owner portfolio or broker data is preloaded into any tenant.

First-person financial disclosures are rejected before model use or memory storage. Messages that disclose a user's holdings, portfolio, account, quantity, cost basis, P&L, margin, buying power or completed trades receive a fixed refusal and are not sent to Qwen or persisted as conversation memory. Users must rephrase educational questions as non-personal hypotheticals.

## Local-model egress

Local-model egress is exact-host allowlisted. A configured `LOCAL_LLM_BASE_URL` is unusable unless:

- it is HTTPS;
- its exact normalized hostname is listed in `LOCAL_LLM_ALLOWED_HOSTS`;
- it is not an IP literal, `localhost`, `.local`, wildcard or URL containing credentials;
- it uses the default HTTPS port;
- at least one API-key or shared-secret authentication header is configured;
- redirects are rejected;
- request caching is disabled.

This prevents a configuration typo or compromised prompt path from forwarding tenant conversation data to an arbitrary remote endpoint. The intended deployment is an authenticated private tunnel to the owner's local llama.cpp/Qwen service, never a general cloud-model URL.

## Public health surface

The unauthenticated `/health` endpoint exposes only static safety posture. It does not reveal exact snapshot IDs, pipeline timestamps, model-route configuration, allowlist membership, tenant identifiers or private system details. Authorized LINE users may receive public-data freshness through the deterministic health intent without exposing the underlying private route.

## Removed surfaces

The following surfaces are absent from the shared-bot branch:

- `/internal/private-sync`;
- `SERVICE_SYNC_TOKEN`;
- private/operator LINE roles;
- public/unrestricted admission mode;
- configurable group/room enablement;
- private portfolio and private option readers;
- local-to-Worker portfolio synchronization;
- IBKR calls from Worker or LINE;
- broker-derived option records in public KV;
- owner/watchlist-derived score and source-view fallbacks;
- arbitrary-model injection of public option chains;
- model or memory acceptance of first-person financial disclosures;
- unauthenticated operational health metadata;
- arbitrary, unauthenticated or redirectable local-model egress.

## Mandatory release gates

A release is rejected unless all of the following pass against the exact release commit:

1. LINE public-boundary static gate;
2. independent public-artifact filename and attestation tests;
3. legacy owner/watchlist artifact no-fallback tests;
4. public option builder and broker/private-lineage rejection tests;
5. attested metadata freshness and future-clock rejection tests;
6. dry-run-by-default and double-gated free-only KV write tests;
7. manifest SHA-256 and pointer-last atomic-promotion tests;
8. disabled/allowlist-only and permanent direct-chat admission tests;
9. silent denial before reply or KV mutation for unauthorized users and missing tenant secrets;
10. raw LINE ID and event-ID non-persistence tests;
11. cross-tenant encryption and deletion tests;
12. arbitrary-model-context test proving legacy private KV records and public option chains are ignored;
13. sensitive-disclosure test proving first-person financial data is neither sent to Qwen nor saved to memory;
14. local-model route tests for exact host allowlisting, required authentication, IP/port rejection and redirect denial;
15. Worker test proving `/internal/private-sync` returns `404`;
16. minimal public-health test proving no snapshot, pipeline or model-route metadata is exposed;
17. complete Python, TypeScript and Vitest suites on BARRY for the exact PR or branch head.

Deployment, LINE webhook registration, IBKR authentication and private data are not required to execute these development gates.
