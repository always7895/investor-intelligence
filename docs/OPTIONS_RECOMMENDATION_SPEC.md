# Weekly and Monthly Option BID/ASK Analysis

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
LINE_OPTIONS_SCOPE=PUBLIC_QUOTE_OBSERVATION_ONLY
LINE_POSITION_ELIGIBILITY=FORBIDDEN
LOCAL_POSITION_ANALYSIS=LOCAL_ONLY
IBKR_TO_LINE=FORBIDDEN
```

## Purpose

The project provides weekly and monthly option BID/ASK research in two separate trust domains:

1. **Shared LINE/public mode** — public quote observations only, with no position-dependent eligibility;
2. **Local owner mode** — optional local-only read-only position analysis that never enters LINE, Worker, public KV or shared model context.

The module is project-authored. It is not attributed to Serenity or Leopold Aschenbrenner, does not place orders, does not infer holdings from chat/examples and never describes a stale or one-sided quote as executable.

## Shared LINE/public mode

LINE may display a validated public option snapshot containing:

- ticker and public provider;
- retrieval time and delay/freshness state;
- weekly/monthly expiration and actual DTE;
- call/put, strike and spot distance;
- BID, ASK, midpoint and spread;
- volume, open interest and IV when supplied;
- Delta only when supplied or transparently calculated from documented inputs;
- quote quality, liquidity and event-risk flags;
- non-binding limit-reference observations.

LINE cannot access or derive:

- holdings or exact quantities;
- covered-contract capacity;
- cash-secured capacity;
- cost basis, P&L, market value, margin or buying power;
- account identifiers or brokerage permissions;
- owner-local watchlists, reports or preferences;
- IBKR or any broker-derived record.

`TENANT_POSITION_REQUIRED` in a public artifact is a closed-schema sentinel meaning position-dependent classification is unavailable in public mode. It does not trigger a private lookup and does not imply that the system has a position for that user.

## Local owner mode

A separately enabled local-only workflow may use an authenticated loopback read-only IBKR gateway or another explicitly configured local portfolio input to calculate position-dependent observations such as whole-contract covered capacity.

Local position analysis:

- remains disabled by default;
- runs outside LINE and Cloudflare Worker;
- is never uploaded to public KV;
- is never inserted into shared local-Qwen context;
- is never sent through a LINE delivery helper;
- contains no brokerage write path;
- remains excluded from Git and release artifacts.

Minimization does not change broker lineage. A derived capacity value remains broker-derived and therefore ineligible for public/LINE use.

## Free-only source priority

### Shared LINE/public mode

1. reviewed, lawful, free public option provider with explicit public eligibility;
2. structured unavailable status.

No broker or owner-local fallback is permitted.

### Local owner mode

1. deliberately enabled local read-only provider already available without a new paid subscription;
2. clearly labelled lawful free fallback used only in the local workflow;
3. structured unavailable status.

No provider may create orders, mutate transfers/funding/subscriptions, activate a paid entitlement or auto-upgrade a plan.

## Required periods

### Weekly

- target: 7 DTE;
- accepted range: 3–14 DTE;
- select the expiration nearest the target inside the range.

### Monthly

- target: 30 DTE;
- accepted range: 21–45 DTE;
- select the expiration nearest the target inside the range.

If no expiration qualifies, return `NO_EXPIRATION_IN_WINDOW`. Never relabel another expiration as weekly or monthly. Use actual DTE for every calculation.

## Quote fields and calculations

For every displayed contract, when available:

- ticker and underlying price;
- currency, exchange/provider and delay state;
- retrieval and quote timestamps;
- call/put;
- expiration and actual DTE;
- strike and spot distance in dollars and percent;
- BID, ASK and midpoint;
- absolute and percentage spread;
- last trade and timestamp, separately labelled;
- volume and open interest;
- implied volatility;
- Delta only when supplied or transparently calculated;
- earnings/event flag before expiration;
- quote-quality and liquidity flags;
- premium/yield references at BID, midpoint and ASK using actual DTE;
- non-binding limit-reference range.

Public mode may show hypothetical cash obligation, put break-even or effective sale-price formulas using contract terms only, but it must not claim that the user can fund, cover or execute the strategy.

No default Delta, quote or option chain is invented.

## Strategy observations

### Covered call

Public mode:

- explains that one standard contract normally corresponds to 100 whole shares;
- reports `TENANT_POSITION_REQUIRED` or an equivalent public-unavailable status;
- may show hypothetical assignment consequences and effective sale price;
- never labels the requester's contract `COVERED`.

Local owner mode may label coverage only from authenticated local whole-share data and keeps the result local.

### Cash-secured put

Public mode may show hypothetical full cash obligation and break-even, but never claims that cash is available or that the strategy is secured.

Local owner mode may assess capacity only from deliberately configured local data. Naked-short promotion is prohibited.

### Protective put

Public mode may explain protection cost and payoff mechanics without claiming that the requester owns the underlying.

Local owner mode may relate the observation to an authenticated local position while keeping all results local.

## Liquidity gate

A candidate normally requires:

- BID greater than zero;
- ASK greater than or equal to BID;
- spread within the configured maximum percentage of midpoint;
- minimum open interest or a documented override;
- quote age within the configured maximum;
- no invalid or missing critical fields.

Illiquid contracts may appear only as clearly labelled raw observations, not as recommended candidates.

## Limit-reference observation

For a valid two-sided quote:

- seller reference: one-quarter spread above BID through midpoint;
- buyer reference: midpoint through ASK.

This is quote navigation, not an order instruction, fill guarantee or authorization to trade. Market/order submission paths do not exist.

## Ranking

Public ranking may balance:

- two-sided quote validity;
- spread width and quote age;
- open interest and volume;
- credit/debit at BID and midpoint;
- distance from spot;
- hypothetical obligation;
- earnings/event risk.

Position eligibility is excluded from shared LINE ranking. Local owner analysis may add a separate local eligibility overlay without modifying the public score or artifact.

Selecting only the highest last trade or premium is prohibited.

## Fail-closed statuses

```text
NO_LISTED_OPTIONS
NO_CHAIN_FROM_PROVIDER
NO_EXPIRATION_IN_WINDOW
NO_TWO_SIDED_QUOTES
INSUFFICIENT_LIQUIDITY
DATA_STALE
FREE_DATA_SOURCE_UNAVAILABLE
TENANT_POSITION_REQUIRED
PUBLIC_PROVIDER_NOT_REVIEWED
CURRENT_PUBLIC_DATA_DISABLED
LOCAL_BROKER_NOT_AUTHENTICATED
LOCAL_BROKER_DATA_NOT_ENTITLED
```

`NO_CHAIN_FROM_PROVIDER` means only that the selected provider did not return a usable chain; it does not prove that no exchange-listed product exists.

## Natural-language examples

Shared LINE/public examples use synthetic symbols and non-personal wording:

```text
EXMPL 每週期權 BID ASK
TEST 每月期權公開報價
比較 EXMPL 本週與本月的公開流動性
covered call 需要哪些條件（一般教育）
這份公開 option snapshot 是即時還是延遲
```

Local owner position questions belong only to the separate local interface and are not routed through LINE.

## Security and cost controls

- public schemas reject unknown/private/position/account/broker fields;
- public publication fails closed rather than silently redacting unsafe input;
- public symbols never inherit the owner watchlist;
- local broker provider accepts loopback HTTPS only;
- endpoint allowlists exclude orders, transfers, funding and subscriptions;
- paid provider credentials and paid fallback are prohibited;
- missing free data produces a controlled unavailable status;
- logs contain content-free metadata only;
- no option response can submit an order.

## Acceptance tests

1. Weekly/monthly selection uses actual DTE windows.
2. BID, ASK, midpoint and spread are calculated correctly.
3. Last trade is never substituted for current BID/ASK.
4. One-sided and stale quotes fail liquidity gates.
5. Missing Delta remains missing.
6. Public output rejects all position, account and broker lineage.
7. `TENANT_POSITION_REQUIRED` never triggers a private LINE lookup.
8. LINE/Worker cannot import or call the IBKR provider.
9. Local position-derived results cannot enter public KV or shared model context.
10. Group/room events are rejected before option tool execution.
11. Provider unavailability does not fabricate a chain.
12. Broker adapter cannot call order, transfer, funding or subscription endpoints.
13. Free-only mode cannot activate paid data.
14. No real holding or account data exists in Git, logs, public KV or release package.
