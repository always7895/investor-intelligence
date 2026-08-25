# LINE Bot Q&A Runtime Implementation

_Last reconciled: 2026-08-25 Asia/Taipei_

This document describes the implemented shared LINE boundary. The shared bot is a public-research client, not an owner, portfolio or brokerage assistant.

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

These statements are architectural requirements, not deployment suggestions. Removing account identifiers from broker-derived data does not make that data public or eligible for LINE.

## Meaning of broad natural-language Q&A

The bot accepts ordinary Traditional Chinese or English questions and routes them to:

1. deterministic public research/report/source tools;
2. a deterministic public-options tool;
3. an authenticated, exact-host-allowlisted local Qwen/llama.cpp route that receives public context only, plus the requesting tenant's own opt-in conversation memory only when a future reviewed release makes memory available;
4. a controlled unavailable/degraded response.

“Broad Q&A” never means omniscience, fabricated current data, unrestricted tool execution, access to owner data, access to another user, or paid fallback.

## Runtime routes

| Route | Purpose | Boundary |
|---|---|---|
| `POST /webhook` | LINE Messaging API webhook | Raw-body signature verification, freshness, dedupe and HMAC allowlist checks |
| `GET /health` | Static safety posture | No snapshot IDs, tenant membership, timestamps, model-route details or broker state |

There is no private synchronization route, brokerage route, portfolio route, order route, administrative model route or scheduled delivery route.

## Runtime modules

```text
cloud/src/core.ts       public intent parsing and privacy-safe formatting
cloud/src/security.ts   LINE signature checks, HMAC tenant IDs and encryption helpers
cloud/src/storage.ts    physically separated public, tenant-private and security KV access
cloud/src/line.ts       reply-only LINE API, hashed dedupe and pseudonymous rate limits
cloud/src/qa.ts         deterministic public tools and authenticated local-Qwen routing
cloud/src/worker.ts     webhook and minimal health routes
```

The Worker has no IBKR client, account connector, portfolio reader, local-report reader or private-data ingestion endpoint.

## Admission and chat scope

- `LINE_ACCESS_MODE=disabled` is the default.
- The only supported modes are `disabled` and `allowlist`.
- Allowlisting uses HMAC-derived tenant IDs; raw LINE IDs are not committed, logged or stored as allowlist entries.
- Only direct user chats are eligible.
- Group and room events are rejected before reply, tenant/event KV mutation and rate-limit mutation.
- Missing secrets, invalid configuration and non-allowlisted users fail silently and closed.
- The language model cannot alter admission or elevate privileges.
- The shared bot has no owner or operator role.

## Public tools

The shared bot may answer:

- help, privacy and system-boundary questions;
- public Traditional Chinese briefings;
- public research rankings and methodology-separated scores;
- verified public source views with provenance;
- public weekly/monthly option-market observations;
- public-data freshness/availability;
- general non-personal questions through the private local model.

The shared bot cannot answer from:

- holdings, positions, quantities, covered capacity, cost basis, P&L, margin or buying power;
- Interactive Brokers or any other brokerage account;
- the repository owner's watchlist, preferences, reports or local caches;
- another tenant's messages or state;
- unreviewed, paid or stale current-data fallbacks.

## Sensitive financial disclosures

First-person financial disclosures are rejected before model use and before conversation storage. Inputs describing a person's holdings, account, quantity, cost, P&L, margin, buying power or completed trades receive a fixed privacy-safe response and must be rephrased as a non-personal educational hypothetical.

The system does not infer or record a real holding from examples used during development.

## Public option behavior

The dedicated option intent reads only the attested public option snapshot. It may show expiration, actual DTE, call/put, strike, BID, ASK, midpoint, spread, volume, open interest, IV, provider-supplied Delta, source, delay/freshness and non-binding limit-reference observations.

It must not:

- label a contract as covered or cash-secured from a user's position;
- expose or derive position capacity;
- use IBKR or broker-derived records;
- insert an entire option chain into arbitrary local-model context;
- fabricate a missing quote, chain, Delta or liquidity field.

Missing or stale data returns a structured unavailable status.

## Physical storage isolation

The Worker uses three independent KV bindings:

- `PUBLIC_CACHE` — attested public reports, scores, source views, options, manifests and current pointers;
- `TENANT_PRIVATE_CACHE` — encrypted tenant conversation/job state only;
- `EPHEMERAL_SECURITY_CACHE` — hashed webhook dedupe claims and pseudonymous rate-limit counters only.

The former combined `CACHE` binding is forbidden. Public reads do not touch tenant-private storage, and webhook security state does not touch public or tenant-private storage.

Conversation memory is unavailable by default for the initial external-user release. No portfolio, broker or owner data is ever preloaded into tenant-private storage. A future memory release requires separate review, explicit opt-in, AES-GCM encryption, a maximum 24-hour TTL, bounded turns and deletion support.

## Local-model routing

The local model route is usable only when all of the following hold:

- HTTPS;
- exact normalized hostname present in `LOCAL_LLM_ALLOWED_HOSTS`;
- default HTTPS port;
- no IP literal, localhost, `.local`, wildcard, embedded credentials or redirect;
- API-key or shared-secret authentication;
- no response caching;
- public context only, with current-tenant opt-in memory only when that feature is explicitly available.

When the local model is unavailable, the bot returns a controlled unavailable response. It does not call a cloud model or enable a paid fallback.

## Current-data and public publication

Current answers remain disabled until reviewed free public adapters publish attested artifacts with acceptable freshness. The public publisher:

1. validates closed schemas and public eligibility;
2. rejects owner, private, position, account and broker lineage;
3. writes content-addressed objects and a SHA-256 manifest;
4. promotes `snapshot:current` last;
5. performs only a dry run unless both `--apply` and `PUBLIC_KV_SYNC_ENABLED=true` are present under the free-only policy.

Legacy owner/watchlist report filenames are never fallback inputs.

## LINE response behavior

- Verify `X-Line-Signature` over the exact raw body before parsing.
- Bound request size, event age, input and output length.
- Hash webhook event IDs before dedupe storage.
- Use reply tokens only; no local report-to-LINE sender exists.
- Do not schedule delayed push or cron delivery.
- Do not log message text, answer text, reply tokens, raw IDs, secrets or full provider responses.
- Fail closed on quota exhaustion.

## IBKR separation

A deliberately enabled local IBKR Client Portal workflow may exist only for separate local read-only analysis. LINE, the Worker, public KV and local-Qwen context cannot call, receive or inherit that data. Derived coverage remains broker-derived and cannot be exported into the shared bot.

## Required acceptance

Release acceptance must prove, on the exact candidate head:

1. signature, freshness, dedupe and direct-chat admission controls;
2. silent fail-closed behavior before mutation for unauthorized events;
3. no raw LINE IDs or event IDs in storage/log keys;
4. no owner, portfolio, broker, private-sync or order path;
5. public-option closed schemas and broker/position-lineage rejection;
6. three physically distinct KV namespaces and no legacy combined binding;
7. cross-tenant encryption/deletion isolation for any optional tenant state;
8. first-person sensitive financial input never reaches model or memory;
9. exact-host authenticated local-model routing and controlled offline behavior;
10. free-only dependency, quota and no-paid-fallback controls;
11. complete Python, TypeScript and Worker tests;
12. documentation consistency gates.

No deployment, webhook registration, production namespace creation, IBKR login or private credential is performed by these development tests.
