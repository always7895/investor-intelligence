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

The weekly is the current calendar week's expiry (operator 2026-10-11; the earlier "nearest 7 DTE inside 3–14 DTE" rule skipped a Friday expiry two days away and showed the next week's, for example 2026-10-16 on Wednesday 2026-10-07):

- the as-of date is the exchange-local calendar date of the observation instant (US listings: New York, Stockholm: Stockholm, TAIFEX: Taipei), not the UTC date and not the requester's date;
- the week is Monday to Sunday in exchange-local time;
- select the earliest listed expiration from the as-of date through that week's Sunday (Wednesday 2026-10-07 with 2026-10-09 and 2026-10-16 listed selects 2026-10-09);
- only when the current week has no remaining listed expiration (weekend, after the week's last weekly, or the expiry day after the regular-session close) select the earliest listed expiration of the next calendar week (Saturday 2026-10-10 selects 2026-10-16) and mark it as next week (`weekly_week` NEXT);
- nothing later than the next week's Sunday is ever a weekly, and an index or ETF series with Monday, Wednesday and Friday expirations simply returns the earliest of them;
- the expiry day (DTE 0) counts only before the regular-session close (US 16:00, Stockholm 17:30, TAIFEX 13:30, exchange local; no holiday calendar is inferred); both validators also reject a DTE 0 row whose evaluation instant is past that close (`EXPIRY_DAY_SESSION_CLOSED` / Worker null), and the local `fetch_options*` paths apply the same cut-off when no date is passed;
- the rule uses listed expiration dates only and never infers one (it applies unchanged to TAIFEX Wednesday and Friday weeklies once an adapter provides them);
- the accepted DTE range is 0–14 as the outer bound, and each public covered-call row records the exchange-local `asof_date` and `weekly_week` so the validators re-check the rule from the sealed row.

Annualized figures use at least one day (`max(DTE, 1)`), so a same-day expiry never divides by zero; a cycle with DTE 0–2 is labelled on the card because its annualized yield is strongly amplified and is not a sustainable return.

### Monthly

- target: 30 DTE;
- accepted range: 21–45 DTE;
- select the expiration nearest the target inside the range.

If no expiration qualifies, return `NO_EXPIRATION_IN_WINDOW` (for the weekly: no listed expiration this week or next). Never relabel another expiration as weekly or monthly. Use actual DTE for every calculation. When the current week's expiry is also the standard third-Friday monthly expiry, a weekly request still shows it as the week's weekly and notes that it is also the monthly expiry; the monthly request is unchanged.

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

#### Covered-call price tiers (public LINE cards)

Per underlying and cycle the sealed `v213:options:v2` row carries up to three strike tiers (operator 2026-09-26 and 2026-10-11):

- `HIGH_STRIKE` (title "建議一：高履約價（不易被賣掉）"): the highest out-of-the-money strike whose bid pays at least 6% annualized with model Delta at most 0.20;
- `MIDDLE` (optional, "中間型（權利金與被指派機率居中）"): a strike strictly between the two others, the one whose Delta is nearest 0.25 (the strike nearest 2.5% out of the money when a Delta is missing); absent when no listed strike lies between, never padded or duplicated;
- `BALANCED` ("平衡型（收較多權利金）"): the lower strike whose Delta is nearest 0.30.

Strikes are strictly descending HIGH > MIDDLE > BALANCED. Titles are numbered by display position (一, 二, 三) without gaps, so a row without a middle shows exactly the two earlier titles. Every tier carries its own sell limit (mid rounded down to the 0.01 tick when the spread is within 25% of mid, otherwise Bid plus a quarter of the spread, never below Bid or above mid); limit prices are not required to be ordered across tiers, only the strikes are.

Compatibility: `suggestions` keeps one or two entries with the roles `HIGH_STRIKE` or `HIGH_STRIKE`,`BALANCED`, so a Worker that predates the middle tier ignores the additive `middle_suggestion` key and renders the two original tiers; rows sealed before the change simply have no middle tier and render two. The Python publish gate and the Worker validator both reject a malformed middle tier (wrong role, not strictly between, fewer than two neighbours, any failed per-item check) for that cycle only. The shared definition lives in `scripts/option_recommendation_rules.py` and its TypeScript twin `cloud/src/v213/option-recommendation-rules.ts`.

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

The manual calculator additionally shows a middle price of the seller range: `(low + high) / 2` rounded to the 0.01 tick and clamped into the range, so low ≤ middle ≤ high always holds (`limit_middle` / `limitMiddle` in the shared rules modules). The local report and the public candidate DTO (`sell_limit_observation`) keep the two-value range until the closed field allowlists are changed together.

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
