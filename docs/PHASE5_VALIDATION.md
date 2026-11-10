# Phase 5 Public LINE Validation Gate

_Last reconciled: 2026-08-25 Asia/Taipei_

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

Phase 5 acceptance validates the exact branch or pull-request head on the trusted BARRY runner. It does not silently validate a GitHub merge ref, and an older successful run never transfers to a newer commit.

## Required gates

- exact revision identity verification;
- immutable workflow supply-chain policy;
- isolated, binary-only, official-index, hash-locked Python installation plus `pip check`;
- current-tree credential and privacy scan;
- shared LINE public-only and broker/owner separation gate;
- documentation/runtime consistency gate;
- Python compile and JSON/TOML validation;
- complete Python unit-test discovery;
- public option closed-schema, freshness and broker/position-lineage rejection tests;
- three-namespace KV isolation tests;
- service-accessible Node.js resolution;
- committed Worker lock hash verification;
- `npm ci --ignore-scripts --no-audit --no-fund`;
- Worker TypeScript typecheck;
- Worker Vitest suite.

## Validation environment

All runtime side effects remain disabled:

```text
LINE_ENABLED=false
LINE_PUSH_ENABLED=false
LINE_ACCESS_MODE=disabled
CURRENT_PUBLIC_DATA_ENABLED=false
CLOUD_INFERENCE_ENABLED=false
IBKR_READONLY_ENABLED=false
ACTIVE_SCAN_APPLY_CHANGES=false
MEMORY_FEATURE_AVAILABLE=false
FREE_ONLY_MODE=true
```

No production LINE, Cloudflare, local-model or brokerage secret is required. No raw LINE ID, account detail, portfolio or other private data is used.

## Required behavior

Acceptance must preserve:

- disabled or HMAC-derived allowlist admission only;
- direct user chat only, with group and room rejection before reply or mutation;
- silent fail-closed behavior for unauthorized or incompletely configured events;
- reply-only LINE behavior with no local report delivery sender;
- public reports, research, source views and public option observations only;
- no owner watchlist/report/preference fallback;
- no portfolio, account, quantity, coverage, cost, P&L, IBKR or broker path;
- no broker-derived record in public KV or LINE model context;
- no arbitrary option-chain injection into general Q&A;
- sensitive first-person financial input rejected before model or memory;
- exact-host authenticated local-model routing and controlled offline behavior;
- physically distinct public, tenant-private and security KV bindings;
- memory unavailable for the initial external-user release;
- no paid dependency, paid fallback or automatic upgrade.

A failing gate blocks merge and deployment. A passing gate proves only the tested development revision; it does not authorize webhook setup, namespace creation, user admission, IBKR authentication, installation or feature activation.
