# IBKR Read-Only Local Analysis Integration

_Last reconciled: 2026-08-25 Asia/Taipei_

This integration is an optional local research capability in a separate trust domain. It is not a data source, tool or fallback for the shared LINE bot.

## Normative boundary

```text
IBKR_RUNTIME_SCOPE=LOCAL_READ_ONLY_ONLY
IBKR_TO_LINE=FORBIDDEN
IBKR_TO_WORKER=FORBIDDEN
IBKR_TO_PUBLIC_KV=FORBIDDEN
IBKR_TO_LINE_MODEL_CONTEXT=FORBIDDEN
IBKR_WRITE_PATHS=FORBIDDEN
```

Redacting account IDs or exact share quantities does not convert broker-derived data into public data. Derived coverage remains broker-derived and is forbidden from the LINE path.

## Local architecture

```text
IBKR Client Portal Gateway on loopback HTTPS
        -> scripts/providers/ibkr_client_portal.py
        -> scripts/fetch_options_ibkr.py
        -> scripts/options_service.py
        -> local-only research output
```

The following edges do not exist:

```text
local IBKR -X-> Cloudflare Worker
local IBKR -X-> LINE webhook/reply
local IBKR -X-> PUBLIC_CACHE
local IBKR -X-> shared local-Qwen context
local IBKR -X-> another tenant
```

## Read-only boundary

The provider rejects operations related to:

- order creation, preview, modification, cancellation, exercise or assignment;
- transfers, funding, withdrawals or deposits;
- account-setting changes;
- market-data subscription mutation;
- arbitrary brokerage endpoints.

The shared Worker contains no IBKR client and cannot authenticate the local gateway.

## Network boundary

The gateway base URL must be loopback HTTPS. Allowed host forms are limited to loopback names/addresses reviewed by the local provider. Remote brokerage gateway URLs are rejected.

Default configuration remains:

```text
IBKR_READONLY_ENABLED=false
```

No GitHub Action, Worker or public endpoint enables or authenticates the gateway.

## Local data minimization

Raw responses remain in process memory for the shortest practical time. Local analysis may derive:

- symbol and currency;
- weekly/monthly expiration status;
- BID, ASK, midpoint and spread;
- source/delay status;
- provider-verified liquidity fields;
- local covered-contract capacity from authenticated long shares.

Local persistent output must exclude account identifiers, exact position quantities, cost basis, market value, P&L and internal contract IDs unless a separately reviewed local-only feature explicitly requires them. All local caches/reports remain outside Git and the release package.

Even minimized IBKR output is ineligible for:

- LINE responses;
- public reports;
- public KV synchronization;
- shared model prompts;
- owner-independent public option artifacts.

## Weekly and monthly semantics

DTE windows come from `config/options-policy.json`.

- Weekly output must use an expiration in the configured weekly window.
- Monthly output must use an expiration in the configured monthly window.
- A monthly expiration is never relabelled as weekly.
- Missing chain, quote, permission or liquidity data produces a structured unavailable/degraded status.
- BID, ASK, midpoint, spread, volume, open interest, IV and Delta are never invented.

## Provider fields

Only reviewed Client Portal fields are used. Optional field tags remain disabled until verified against current official documentation and covered by tests. A provider response that lacks required data cannot be silently combined with an unlabeled secondary source.

A clearly labelled public-data fallback may be used only inside the separate local analysis workflow and may receive only privacy-minimized derived inputs allowed by the local policy. Such fallback output remains local and cannot be published to LINE.

## Local setup outline

1. Obtain the official Client Portal Gateway.
2. Start and authenticate it locally.
3. Confirm the authenticated read-only status.
4. Keep account identifiers and credentials outside the repository.
5. Set protected local environment variables, for example:

```text
IBKR_READONLY_ENABLED=true
IBKR_CP_BASE_URL=https://127.0.0.1:5000/v1/api
IBKR_CP_VERIFY_TLS=false
OPTIONS_PROVIDER=auto
OPTIONS_ALLOW_FALLBACK=true
```

6. Run an explicit local read-only validation.
7. Keep shared LINE, Worker and public KV disabled from this data path.

Development CI uses synthetic fixtures and never requires an IBKR login or account data.

## Output interpretation

- `quote_source` identifies the actual provider.
- Retrieval time and delay state must be preserved.
- BID/ASK candidates and limit ranges are research observations only.
- Local coverage is not an order instruction.
- The project never sends an order to IBKR.
- No broker-derived field may be copied into the shared public option DTO.

## Release requirements

Release gates must prove:

1. loopback/read-only endpoint enforcement;
2. rejection of order, transfer, exercise, funding and subscription paths;
3. privacy minimization of local outputs;
4. no IBKR import/call from Worker or LINE code;
5. no broker lineage in public option artifacts or public KV;
6. no broker data in shared model context;
7. no IBKR credential, account ID, cache or report in Git/release artifacts.
