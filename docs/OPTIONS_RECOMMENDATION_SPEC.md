# Weekly and Monthly Option BID/ASK Analysis

<!-- DOCS-R1 scope -->
> **Scope:** Contractual safety/evidence boundary; retain exact normative markers and validate against runtime configuration. Current acceptance and unresolved issues: [STATUS](../state/STATUS.md). The document itself does not authorize Production changes.
<!-- /DOCS-R1 scope -->

_Monthly expiry, quote-bounded recommendations and source evidence reconciled: 2026-11-09_

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

The module is project-authored. It is not attributed to Serenity or Leopold Aschenbrenner, does not place orders, does not infer holdings from chat/examples and never describes a delayed limit reference as a guaranteed executable price. A one-sided quote may support a side-specific recommendation only under the rules below.

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
- is never inserted into shared local-model context;
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

Operator 2026-11-03: list the monthly of the month the viewer is looking at, at any distance, with no minimum DTE and no annualized-yield floor. Example: on 2026-11-03, SIVE.ST shows the 2026-11-20 expiry (17 DTE); on 2026-11-20 before the close it shows DTE 0.

- the monthly is the NEAREST standard monthly expiry on or after the exchange-local as-of date (same as-of date as the weekly: the exchange-local calendar date of the observation instant, not the UTC date and not the requester's date);
- a standard monthly is the listed third Friday, or a venue-specific shift supported by explicit source-calendar evidence. An absent Friday plus a Monday–Thursday listing is not holiday proof; a weekly is never relabelled as monthly;
- the expiry day (as-of date equal to the expiry) counts only before the venue's regular-session close, exactly like the weekly (US 16:00, Stockholm 17:30, TAIFEX 13:30, exchange local, no holiday calendar inferred); afterwards the earliest later standard monthly is taken (2026-11-20 after the close selects 2026-12-18);
- if the nearest standard chain is absent, make a bounded source-specific lookup for that exact date. If it remains unverified, show a precise zh-TW refusal naming the expected standard date; never advance to another month because a chain, quote, yield or delta is inadequate;
- only standard monthlies up to 60 DTE are considered (the validators' outer bound, `MONTHLY_DTE_BUCKET` = 0–60). A source-verified dated quote observation may be shown separately from a strategy when conservative eligibility fails; a missing quote is never invented and a later expiry is never borrowed;
- the producer records `monthly_rule` as `THIRD_FRIDAY` or source-proven `HOLIDAY_SHIFT`. Existing sealed `LATER_LISTED` evidence remains subject to strict date/rule validation; it does not authorize the current producer to skip a missing nearest chain. Both validators reject legacy weekly-in-monthly rows instead of relabelling them;
- the Worker admits standard monthly DTE 0–60 and rejects values outside that range. DTE 0–2 carries an amplified-annualization warning, including observation-only cards; annualization uses at least one day. A rule marker does not replace source, rights, freshness or seal checks;
- there is no annualized-yield floor on any strike (covered call `HIGH_STRIKE`, cash-secured put, either cycle); yield stays displayed. OTM, verified identity, cent-exact strikes, executable-side quotes, delta caps/bands, expiry, freshness, rights and seals remain binding. Wide spread is a warning, not a selection refusal.

The shared definitions are `scripts/option_recommendation_rules.py` and `cloud/src/v213/option-recommendation-rules.ts`; the cross-language behavioral test consumes `tests/fixtures/monthly_expiry_cases.json` for selection and `tests/fixtures/options_window_cases.json` for executable collector/Python-validator/Worker admission parity. Collection/fetch bounds, sealed-product validators, selected-row Worker admission and manual/generic quote labels use those definitions. Selection never fabricates an expiration or quote and adds no Black-Scholes price fallback; pre-existing Greek estimation is unchanged.

If no expiration qualifies, return `NO_EXPIRATION_IN_WINDOW` (for the weekly: no listed expiration this week or next). Never borrow another period's sealed row. Use actual DTE for every calculation. When the current week's expiry is also the standard third-Friday monthly expiry, a weekly request still shows it as the week's weekly and notes that it is also the monthly expiry. A navigation button to another period is not evidence that its quote exists.

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

### Contract identity and response meaning

Nasdaq Nordic contracts must agree across full name, native symbol, call/put type, expiration and exact strike, with SEK and standard 100-share terms. The underlying is bound to its verified orderbook id; the chain's sole fully verified exchange root supplies contract identity, not a normalized equity ticker or a guessed mapping. Roots from an initial response and a bounded monthly refetch must agree. Conflicting roots fail closed even if the conflicting row would later fail quote, currency, size or expiry selection. Adjusted `-X`/trailing-X series do not establish or inherit a standard identity.

Strike identity uses exact decimal parsing, separate from quote-price locale parsing. Strict source grouping such as `1,460.00` is accepted; ambiguous `1,460`, malformed grouping and rounded substitutions are rejected. Subcent identity cannot be rounded into a different cent-exact recommendation.

US empty responses, nonempty but untyped rows, and unreadable response shapes have separate causes. Nordic `NO_INST_FOUND` means the source reports no instrument, not independently proven absence of a listing; a readable search without a verified underlying is distinct from an unreadable chain. Contradictory status and nonempty chain content fail closed. Missing legacy metadata never proves that puts or listed options do not exist.

### Observation date versus acquisition date

An optional sealed `source_quote_date` records the actual Nasdaq US response's calendar date for the selected expiry, including its bounded exact-date response when used. Absence remains unknown. Invalid, conflicting, future or stale dates are not replaced with fetch time. `timestamp` remains acquisition time; `asof_date` remains the exchange-local expiry-rule date.

Text and Flex label the source-page observation date, including observation-only cards. Nasdaq `lastTrade` describes the underlying and `asOf` the quote table: neither establishes every option leg's observation time, nor the date of a separately supplied calculation spot. Carry preserves an existing source date without restamping; Nasdaq US remains ineligible for prior-session carry.

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

- `HIGH_STRIKE` (title "建議一：高履約價（不易被賣掉）"): the highest out-of-the-money cent-exact strike with a positive sell Bid and verified Delta at most 0.20. No annualized-yield floor applies. Low yield or a wide spread alone never converts an eligible strike into an observation or advances the expiry.
- `MIDDLE` (optional, "中間型（權利金與被指派機率居中）"): a strike strictly between the two others, the one whose Delta is nearest 0.25 (the strike nearest 2.5% out of the money when a Delta is missing); absent when no listed strike lies between, never padded or duplicated;
- `BALANCED` ("平衡型（收較多權利金）"): the lower strike whose Delta is nearest 0.30.

Strikes are strictly descending HIGH > MIDDLE > BALANCED. Titles are numbered by display position (一, 二, 三) without gaps. Each sell LIMIT starts at midpoint rounded down to 0.01 and clamped within the actual quote; with only a valid Bid it uses Bid. A rounding step must never move the LIMIT below Bid or above midpoint, so a subcent boundary retains its actual precision. Sell instructions describe walking down by 0.01 without crossing Bid and explicitly do not guarantee a fill. Limits need not be ordered across tiers; strikes must be.

Compatibility: `suggestions` keeps one or two entries with the roles `HIGH_STRIKE` or `HIGH_STRIKE`,`BALANCED`, so a Worker that predates the middle tier ignores the additive `middle_suggestion` key and renders the two original tiers; rows sealed before the change simply have no middle tier and render two. The Python publish gate and the Worker validator both reject a malformed middle tier (wrong role, not strictly between, fewer than two neighbours, any failed per-item check) for that cycle only. The shared definition lives in `scripts/option_recommendation_rules.py` and its TypeScript twin `cloud/src/v213/option-recommendation-rules.ts`.

#### Three conservative strategies per cycle (V21, operator 2026-10-19)

Every weekly and monthly cycle carries a covered call, a cash-secured put (CSP) and a collar, conservative first, in the additive optional `strategies` object of the same sealed row (no new KV key; a row without it is an older row and shows the covered call only):

- `cc`: present only as `{"unavailable": reason}` when the cycle has no covered-call strike (`suggestions` is then `[]`, allowed beside a real `csp`/`collar` block or an independently validated dated monthly quote observation);
- `csp`: out-of-the-money puts with a positive sell Bid, absolute Delta 0.20–0.30 (`CONSERVATIVE_DELTA_BAND`), and no yield floor. `CONSERVATIVE` is nearest 0.20; optional `BALANCED` is nearest 0.30 at a higher strike. LIMIT follows the covered call; cash required, break-even and downside buffer remain contract-derived.
- `collar`: long stock, a protective put (absolute Delta nearest 0.15 inside 0.05–0.25, positive buy Ask) and a short call in the same 0.20–0.30 band as CSP (nearest 0.20 first). Buy LIMIT is midpoint rounded up to 0.01 and bounded by Ask, or Ask alone without Bid. Net premium, maximum loss/gain and break-even are LIMIT-based; the conservative quote-side net is Call Bid minus Put Ask. Its annualization is net-premium annualization, not total return or a guaranteed outcome.

Each `csp`/`collar` block retains cycle-matched `rights_status`, `provider_id`, `quote_basis` and `timestamp`. A missing required executable side or verified Delta makes that strategy unavailable independently. A missing opposite side is null, never a fabricated zero/equal quote; midpoint and spread then remain unavailable. One-sided recommendations require source Delta or source IV, never midpoint-implied Greeks. Two-sided quote-derived Greeks remain explicitly model-labelled; call Delta is never reinterpreted as put Delta. The put rights label is unchanged, and puts do not count towards `OPTION_TWO_SIDED_COVERAGE_LOW`. The publish gate still degrades a failing strategy independently and drops strategies first under its size cap.

The Worker mirrors those checks in `cloud/src/v213/covered-call.ts`. Empty `suggestions` needs a real put strategy or a validated monthly observation; diagnostic-only blocks alone are insufficient. US and Stockholm share one renderer: overview, available CC/CSP/collar detail cards and source disclosure, at most five Flex bubbles. Even when a call observation is retained, any qualified put strategy takes this recommendation layout, not the observation-only layout. Every displayed tier exposes its actual Bid/Ask/midpoint, LIMIT instructions, spread or missing-side warning, LIMIT economics and Bid/conservative-side economics in both Text and Flex. Text is split within LINE bounds, not truncated to hide disclosures.

Pure monthly observations retain separate source-backed CC, CSP and collar reasons. Reasons distinguish strike precision, missing required Bid/Ask, unavailable Greek evidence, delta exclusion and genuinely absent same-expiry puts. Wide spread is not a refusal. Missing metadata or an unreadable source does not prove an absent put chain.

Diagnostic-only blocks are not usable strategies for carry-forward. Existing capture eligibility remains explicitly two-sided; a one-sided live recommendation cannot create a two-sided carry capture. A current usable strategy or malformed evidence is not hidden by replacement. An otherwise eligible same-expiry prior capture remains subject to the existing rights, expiry and freshness limits.

### Cash-secured put

Public mode may show hypothetical full cash obligation and break-even, but never claims that cash is available or that the strategy is secured.

Local owner mode may assess capacity only from deliberately configured local data. Naked-short promotion is prohibited.

### Protective put

Public mode may explain protection cost and payoff mechanics without claiming that the requester owns the underlying.

Local owner mode may relate the observation to an authenticated local position while keeping all results local.

## Quote eligibility and liquidity warnings

A recommendation requires a verified standard contract, cent-exact OTM strike, eligible expiry and Delta, finite positive Bid for a sale or Ask for a purchase, and the existing freshness/rights/seal checks. Two positive sides must not be crossed. Missing/zero optional sides may normalize to null; they do not supply a midpoint or quote-implied Greek.

Wide spreads, missing opposite sides, and unavailable OI/volume are disclosed honestly, not converted into invented liquidity. Spread above 25% of midpoint gets a visible warning, including spreads wider than midpoint. Such quotes can support non-binding LIMIT references but never a fill guarantee. Unknown OI/volume stays "未提供", not zero.

## Limit-reference observation

Recommendation cards use the midpoint-based bounded LIMIT rules above, with both LIMIT and conservative quote-side economics. A sell walks down by 0.01 without crossing Bid; a protective put uses its bounded buy LIMIT, with Ask as the conservative cost.

The separate manual quote-navigation calculator retains its two-sided seller range (one-quarter spread above Bid through midpoint), buyer range (midpoint through Ask), and bounded middle-of-range value (`limit_middle` / `limitMiddle`). That educational range is not the recommendation-card LIMIT formula. Its public DTO (`sell_limit_observation`) remains a range; this stage does not change its closed field allowlist.

All are non-binding references, not trade authorization or fill guarantees. No order-submission path exists.

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

1. Weekly selection uses the calendar-week rule and monthly selection the nearest standard monthly (third Friday), both on actual DTE.
2. BID, ASK, midpoint and spread are calculated correctly.
3. Last trade is never substituted for current BID/ASK.
4. Missing required quote sides, unsupported one-sided Greeks, crossed quotes and stale data fail the applicable gates; a valid one-sided reference never qualifies two-sided carry.
5. Missing Delta stays missing unless derived from supported, explicitly labelled inputs. Wide spread alone does not refuse a strategy.
6. Public output rejects all position, account and broker lineage.
7. `TENANT_POSITION_REQUIRED` never triggers a private LINE lookup.
8. LINE/Worker cannot import or call the IBKR provider.
9. Local position-derived results cannot enter public KV or shared model context.
10. Group/room events are rejected before option tool execution.
11. Provider unavailability does not fabricate a chain.
12. Broker adapter cannot call order, transfer, funding or subscription endpoints.
13. Free-only mode cannot activate paid data.
14. No real holding or account data exists in Git, logs, public KV or release package.
