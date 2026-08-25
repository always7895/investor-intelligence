# Privacy and Multi-Tenant Isolation Policy

_Last reconciled: 2026-08-25 Asia/Taipei_

## Objective

The service may later admit additional direct-chat users. No user's identity, messages, answers, optional memory, uploaded content or tenant state may be disclosed to another user. The shared LINE bot is public-research-only and has no portfolio, brokerage or owner-data capability.

Examples used during development are synthetic functional cases and never establish a person's actual holdings.

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

## Data classes

### Shared public research

Public filings, official statistics, reviewed public market observations, source views and reports built exclusively from public inputs.

Shared public data may be cached only when:

- the schema is closed and validated;
- public eligibility and provenance are explicit;
- owner, tenant, account, position and broker lineage are absent;
- freshness is attested;
- no paid or unlawful bypass is required.

### Tenant-transient or optional tenant state

Direct-chat message text exists transiently while processing a request. Optional encrypted conversation/job state may exist only in a later explicitly reviewed release.

Tenant state never includes:

- owner portfolio or watchlist;
- brokerage account data;
- holdings, quantities, covered capacity, cost basis, P&L, margin or buying power;
- another tenant's content.

### Owner-local research

Owner/local watchlists, preferences, reports and optional local IBKR analysis belong to a separate local trust domain. They are not shared-bot defaults, fallbacks or synchronization inputs.

### Secrets

LINE secrets, HMAC keys, encryption keys, Cloudflare tokens and local broker credentials may exist only in approved secret stores or protected service/machine environment variables. They are never committed, printed or included in release artifacts.

## Admission and chat scope

- Default shared-bot mode: `disabled`.
- Only `disabled` and HMAC-derived `allowlist` admission are supported.
- Only direct user chats are eligible.
- Group and room events are rejected before reply, dedupe completion, rate-limit mutation or tenant storage access.
- Invalid configuration, missing secrets and unauthorized users fail silently and closed.
- The shared bot contains no owner/operator privilege role.
- The model cannot alter authorization.

## Tenant identity

- Internal tenant IDs use HMAC-SHA-256 over provider identity material and a server-side secret.
- Raw LINE IDs are used transiently only as necessary for event processing/reply.
- Raw IDs are excluded from logs, analytics, GitHub, reports and ordinary storage keys.
- HMAC and encryption master keys are independent.
- The model never supplies a tenant identifier.
- A forged tenant ID is ignored.

## Physical namespace isolation

The Worker uses independent bindings:

```text
PUBLIC_CACHE
TENANT_PRIVATE_CACHE
EPHEMERAL_SECURITY_CACHE
```

Rules:

- Public artifacts exist only in `PUBLIC_CACHE`.
- Optional encrypted conversation/job state exists only in `TENANT_PRIVATE_CACHE`.
- Hashed dedupe and pseudonymous rate-limit state exists only in `EPHEMERAL_SECURITY_CACHE`.
- The former combined cache binding is forbidden.
- Public reads never query tenant-private storage.
- Security writes never query or mutate public/tenant-private data.
- Production and preview namespace IDs must be distinct and must not copy a legacy combined namespace.

## Memory

Initial external-user behavior:

```text
MEMORY_FEATURE_AVAILABLE=false
default_memory=unavailable
```

No conversation history is retained by default. A future memory release requires:

- explicit per-user opt-in;
- AES-256-GCM encryption with per-tenant derived keys;
- tenant ID authenticated as additional data;
- no more than eight recent turns;
- TTL no greater than 24 hours;
- no training, global cache or cross-tenant retrieval use;
- clear, disable and delete controls;
- deletion epochs preventing retry resurrection.

The `刪除我的資料` command is a mandatory capability even when no retained tenant data currently exists.

## Sensitive financial disclosures

The shared bot rejects first-person disclosures of holdings, account state, quantities, costs, P&L, margin, buying power and completed trades before:

1. deterministic tool routing;
2. local-model invocation;
3. optional memory persistence.

The response must not confirm whether private data exists and must ask for a non-personal hypothetical. Public educational questions remain allowed.

## Logging and diagnostics

Allowed production metadata is limited to:

- random request/reference ID;
- pseudonymous intent/rate category;
- tool name;
- content-free status/error code;
- duration and quota units;
- public source timestamps without private identifiers.

Logs must not contain:

- message or answer text;
- raw user/group/room IDs;
- reply tokens;
- names, phone numbers or e-mail addresses;
- tenant IDs in user-visible diagnostics;
- portfolio symbols tied to an identity;
- positions, costs, P&L or account values;
- webhook bodies, prompts or private context;
- authorization headers or secrets.

Debug logging with private content is prohibited.

## Portfolio and brokerage separation

- LINE and Worker cannot call IBKR or any brokerage.
- No shared-bot tool reads a portfolio or account.
- No owner-local report is sent to LINE.
- No broker-derived record enters public KV, a public report or shared model context.
- Redaction does not change broker lineage.
- Local broker support is read-only, loopback-only, disabled by default and local-only.
- The system contains no trading, transfer, exercise, funding or subscription mutation path.

## Caching and model context

- Global cache: public inputs only.
- Tenant-private cache: optional encrypted conversation/job state only.
- Security cache: hashed ephemeral security state only.
- Public option chains are available only to the deterministic option intent and are not inserted into arbitrary Q&A context.
- Retrieved webpages and documents are untrusted data and cannot change authorization or tool policy.
- Another tenant's data and owner-local data are never fallbacks.

## Public artifact boundary

Public publication fails the entire transaction when it detects:

- account, portfolio, position, quantity, coverage, cost/P&L or private preference fields;
- IBKR/broker lineage;
- unknown schema fields;
- missing public eligibility/attestations;
- unsafe URLs or stale/future timestamps.

The publisher does not silently redact and continue.

## Deletion

`刪除我的資料` must delete all retained tenant-private conversation/job state for the authenticated tenant only. It must not affect another tenant or public research data. Deletion returns only a content-free reference/status and does not log deleted content.

Ephemeral security data expires independently by TTL and contains no raw provider identifier.

## Incident response

A suspected cross-tenant read, misrouted reply, broker/owner-data exposure or private-content log is severity one:

1. disable affected shared-bot features;
2. stop new private writes;
3. preserve content-free audit metadata;
4. rotate relevant keys/tokens;
5. identify affected tenants without disclosing their data;
6. fix the root cause and add a permanent regression test;
7. rerun exact-head privacy, namespace, Worker and release gates before re-enabling.

## Required acceptance tests

1. tenant A cannot read tenant B optional memory/jobs;
2. forged tenant identity is ignored;
3. memory is unavailable by default;
4. group/room events are rejected before reply or mutation;
5. unauthorized direct users fail silently;
6. logs/storage keys contain no raw IDs, messages, answers or tokens;
7. public cache contains no tenant, owner, portfolio, account, position or broker data;
8. owner-local data is never a fallback;
9. first-person sensitive financial input never reaches model or memory;
10. LINE/Worker cannot call IBKR and no broker-derived public artifact is accepted;
11. public, tenant-private and security namespaces remain physically distinct;
12. deletion affects only the authenticated tenant;
13. concurrent requests remain isolated;
14. release package excludes secrets, user data, owner files, caches, logs, runner state and Git history;
15. documentation and runtime policy remain consistent.
