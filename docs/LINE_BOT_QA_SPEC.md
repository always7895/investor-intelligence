# LINE Bot Full Natural-Language Q&A Specification

_Last reconciled: 2026-08-25 Asia/Taipei_

## Goal

The shared bot accepts ordinary Traditional Chinese or English questions about public research, source views, public reports, public option observations, methodology and general knowledge. It is intentionally unable to access a portfolio, brokerage account, owner-local data or another user's information.

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

“Any question” means broad natural-language routing within these boundaries. It never permits fabrication, secret disclosure, code execution, cross-tenant access, trading, paid fallback or privilege elevation.

## Non-negotiable policies

- `FREE_ONLY_MODE=true`.
- No paid model, search, news, quote or market-data dependency.
- No automatic plan upgrade, payment activation or paid fallback.
- General generation uses only the authenticated private local Qwen/llama.cpp route.
- Current claims require timestamped reviewed public data.
- Scheduled and delayed LINE push are disabled.
- No order, transfer, funding, subscription or brokerage mutation exists.
- Production deployment remains disabled until final acceptance.

## Availability architecture

```text
LINE direct user webhook
  -> raw-body signature verification
  -> event freshness and hashed deduplication
  -> disabled/HMAC-allowlist admission
  -> public-only intent router
  -> deterministic public tool or authenticated local Qwen
  -> LINE reply or controlled unavailable response
```

Only direct user events are eligible. Group and room events are rejected before reply or storage mutation.

## Tenant identity and isolation

1. Raw LINE IDs are used transiently only as required to validate and reply.
2. Internal tenant IDs are HMAC-SHA-256 derived with a server-side secret.
3. Raw IDs, message text, answer text and reply tokens are excluded from ordinary logs.
4. Public/global keys contain no tenant, owner, account, position, portfolio or message data.
5. Optional tenant state is encrypted with a per-tenant AES-GCM key and authenticated with tenant-bound additional data.
6. Another tenant's state is never a fallback.
7. The model cannot select or change a tenant ID.
8. The initial external-user release keeps conversation memory unavailable.

## Admission

- Default mode: `disabled`.
- Supported modes: `disabled`, `allowlist`.
- Allowlist entries: HMAC-derived tenant hashes only.
- Missing secrets or invalid configuration: silent fail closed.
- Non-allowlisted user: silent fail closed before reply, dedupe completion or rate mutation.
- Shared-bot owner/operator role: none.
- Group/room enable switch: none.

## Public intent router

Supported public intents include:

- help and privacy;
- latest/morning/evening public briefing;
- public research score and ranking;
- source views with author/date/URL;
- public option BID/ASK observations;
- data freshness and static safety posture;
- general non-personal knowledge via local Qwen.

No intent may expose or use:

- holdings, positions, quantities or covered capacity;
- cost basis, market value, P&L, margin or buying power;
- account identifiers or broker permissions;
- owner watchlists, local preferences, private reports or local caches;
- another tenant's conversation;
- unreviewed or paid current-data sources.

## Current information

The model may not answer a current financial question from model memory. Required behavior:

- reviewed, timestamped and fresh public tool data: answer with source and retrieval/as-of time;
- missing, disabled or stale data: return an explicit unavailable/degraded status;
- conflicting evidence: show the conflict and provenance;
- no source: do not fabricate.

Source-derived views, project-authored scoring, model inference and any local/private preference overlay must remain separately labelled.

## Public options

When available, output may include:

- ticker and public provider;
- delayed/realtime label as actually supplied;
- retrieval time, expiration and actual DTE;
- call/put, strike and spot distance;
- BID, ASK, midpoint and spread;
- volume, open interest and IV;
- Delta only when supplied or transparently calculated;
- quote quality, event risk and a non-binding limit-reference range.

Public options must declare public eligibility and false broker/account/position attestations. They never claim `COVERED`, cash-secured status or position capacity. Unknown fields, broker lineage and position-capable fields fail closed instead of being silently redacted.

## Sensitive personal financial input

The shared bot does not accept first-person disclosures of holdings, account state, quantities, costs, P&L, margin, buying power or completed trades. Such input is rejected:

1. before deterministic tool routing;
2. before local-model invocation;
3. before memory persistence.

The response asks the user to rephrase the question as a non-personal hypothetical. The system does not confirm whether related private data exists.

## Local model

The model endpoint:

- is private and zero-per-request;
- requires HTTPS, exact-host allowlisting and authentication;
- rejects IP literals, non-default ports, redirects, embedded credentials and wildcard hosts;
- receives bounded public context only;
- never receives public option chains for arbitrary Q&A;
- may receive only the requesting tenant's own opt-in memory in a later release where memory is explicitly enabled;
- returns a controlled unavailable response when offline.

There is no cloud-model fallback.

## Memory and deletion

Initial state:

```text
MEMORY_FEATURE_AVAILABLE=false
default_memory=unavailable
```

No message history is retained in the initial external-user release. The `刪除我的資料` capability remains mandatory so any later optional tenant state can be removed safely.

A future reviewed memory release must require explicit opt-in and enforce:

- no more than eight recent turns;
- AES-GCM encryption;
- tenant-bound keys and additional data;
- TTL no greater than 24 hours;
- no global cache or training use;
- clear/disable/delete commands;
- deletion epochs that prevent retry resurrection.

Memory can never contain owner portfolio or broker data.

## KV contracts

Public:

```text
PUBLIC_CACHE
  reports, scores, source views, public option snapshots, manifests, snapshot pointer
```

Tenant-private:

```text
TENANT_PRIVATE_CACHE
  optional encrypted conversation and job state only
```

Security:

```text
EPHEMERAL_SECURITY_CACHE
  hashed event dedupe and pseudonymous rate-limit state only
```

A combined cache binding is forbidden. Public reads never access tenant-private storage.

## Cost and quota controls

- Cloudflare Workers Free only.
- No Workers AI binding.
- No paid provider credentials.
- No GitHub-hosted runner.
- No scheduled push.
- No automatic plan change.
- Public KV writes require explicit apply + environment gates.
- Quota exhaustion returns a controlled unavailable response.
- Zero-cost operation does not promise unlimited 24/7 generation.

## Acceptance tests

A release must prove:

1. valid signature accepted and tampered signature rejected;
2. duplicate webhook event processed once without storing the raw ID;
3. direct allowlisted user accepted only with all required secrets;
4. group and room events rejected before reply or state mutation;
5. non-allowlisted users denied silently;
6. raw user IDs, messages, answers and tokens absent from logs/storage keys;
7. no owner, portfolio, IBKR, broker, private-sync or order path;
8. public artifacts reject private, position, account and broker lineage;
9. public options disclose BID/ASK/freshness and never invent coverage or Delta;
10. current questions fail closed on missing/stale data;
11. sensitive personal financial disclosures never reach model or memory;
12. local model requires exact-host authenticated HTTPS and fails closed offline;
13. public, tenant-private and security KV namespaces are physically distinct;
14. optional tenant encryption/deletion remains cross-tenant safe;
15. scheduled/push and paid fallback remain disabled;
16. all outputs fit LINE limits;
17. release ZIP contains no secrets, user data, owner files, caches, logs or Git history;
18. implementation, policy and workflow documentation remain consistent with runtime policy.
