# Serenity Public Research Lens — Investor Intelligence

## Identity and attribution boundary

This project studies **Serenity / @aleabitoreddit** from public material only.

- Never describe this as Serenity's official score, formula, private process, portfolio, or advice.
- A public Serenity post is an attributable **source view**, not factual company evidence.
- Company facts must be independently proven by filings, exchange/issuer releases, customers, suppliers, government/standards documents, or other admitted sources.
- Do not merge material from a different account named Serenity. In particular, material whose corpus identity is `@stockgodserenity` is a different identity and is quarantined from this methodology.
- Multiple GitHub skills/forks derived from the same tweet archive are one corpus lineage, not independent corroboration.

## Mandatory refresh and staleness rule

Specific ticker views decay quickly. Before reporting "Serenity's current view":

1. check the project's append-only direct-public source history;
2. search for newer original @aleabitoreddit URLs;
3. use archives/Skills only to discover candidates when direct content is unavailable;
4. label archive-only items as unverified until the original post content is independently retrieved;
5. if the latest verified ticker view is stale, say so and do not infer the current stance.

Methodology posts may be durable. Ticker conviction, targets, customer maps, position color, and timing are dated observations.

## Research workflow

### 1. Start with the system change, not the ticker

Define a dated system change: technology adoption, capital replacement, regulation, supply exit, resource availability, demographics, qualification requirements or another structural transition. Let current evidence determine the relevant industry; no sector or company is a permanent preferred seed.

Ask which physical/economic constraint becomes binding: effective productive capacity, critical inputs, quality/yield, approval or qualification, specialized know-how/labor, logistics, infrastructure, switching time or capital. Sector-specific examples explain a mechanism; they never restrict the search universe.

### 2. Map the value chain before ranking companies

Trace at least:

`end demand -> delivered product/service -> system/workflow -> critical component/input -> production/qualification -> materials/skills -> equipment/infrastructure/logistics`

Adapt the map to the industry rather than forcing every business into a semiconductor chain. Require dated evidence for each material dependency edge and for who can capture its economics.

Rank **layers before tickers**. A strong company in a loose layer can rank below an average company sitting at a scarce layer.

### 3. Separate relationship evidence from scarcity evidence

A named customer, partnership, design win, foundry relationship, or capacity reservation proves a relationship or commercial signal only.

Hard dependency roles require separate evidence for scarcity/friction:

- low effective qualified supplier count;
- long or difficult qualification;
- current effective substitute capacity shortage;
- binding lead times or allocation;
- hard-to-expand process/capacity;
- unique process/IP that is actually required;
- customer/counterparty evidence that alternatives cannot meet current requirements.

Never promote `customer_named_dependency` alone to a bottleneck.

### 4. Distinguish qualified substitutes from effective substitutes

`qualified_substitute_exists` does not answer whether enough usable capacity exists at the current ramp.

Track separately:

- nominal qualified suppliers;
- product/spec equivalence;
- qualification status by customer/platform;
- available/current-ramp capacity;
- lead time/allocation;
- switching/requalification time;
- geographic/export constraints;
- announced competitor expansion and its start date.

A `SEMI_MONOPOLY`, `QUALIFICATION_CONSTRAINED`, or `CAPACITY_BOTTLENECK` label is fail-closed until this distinction is evidence-bound.

### 5. Treat the qualification cycle as forward evidence, not current revenue

For pre-volume-ramp names, current revenue can lag the thesis. Accept evidence-bound signals such as qualification, design wins, production readiness, capacity reservations, minimum purchase commitments, prepayments, LTAs, and named customer ramps.

But distinguish:

- signed/contracted quantities from management scenarios;
- company guidance from Serenity's model;
- production readiness from realized volume revenue;
- ecosystem mapping from confirmed customer revenue.

### 6. Split operating thesis from equity capture

Financing is a first-class disconfirmation axis, but do not mechanically turn every dilution event into an operating-thesis failure.

Track two separate states:

**Operating thesis** — architecture, demand, qualification, capacity, customer ramp, economics.

**Equity capture / financing** — ATM size, repeated issuance, warrants, convertibles, discount, proceeds/use, SBC, executive grants, balance-sheet necessity, and whether shareholders retain economic capture.

Use these severity levels:

- `NONE`
- `MATERIAL_OVERHANG`
- `STRUCTURAL_DISQUALIFIER`
- `DESTROYED`

Only evidence-bound value-transfer/destruction should support `equity_capture_destroyed_by_financing` and a severe thesis break. Material dilution may coexist with a valid operating thesis.

### 7. Preserve source-view lifecycle

Every public Serenity view should carry:

- original source URL and source id;
- published date/time precision;
- retrieval status and channel;
- direct-content verification status;
- ticker/theme;
- stance and conviction if explicit;
- horizon if explicit;
- whether it is a reply/quote/standalone post;
- prior view it supersedes or modifies;
- what changed;
- lifecycle: `ACTIVE`, `AGING`, `STALE`, `SUPERSEDED`, `REVERSED`, or `ARCHIVE_ONLY`.

Quotes, screenshots, replies, sarcasm, disclaimers, retrospective victory posts, and crowd-sourced watchlists require semantic review before they become a source view.

### 8. Source ladder and independence

Prefer:

1. regulator/exchange/statutory filings;
2. issuer official releases and audited/regulated material;
3. customer/supplier/counterparty official disclosure;
4. government, standards, patents, procurement and technical authority;
5. reputable institutional/trade corroboration;
6. reputable media/context;
7. market-data conveniences and social/archive leads.

A source can be primary within its own authority but still cannot prove a causal investment conclusion.

Deduplicate common lineage: mirrors, forks, copied articles, syndicated releases and Skills based on the same underlying tweet corpus count as one evidence family.

### 9. Make confidence multi-axis

Do not collapse research quality into one `LOW/MEDIUM/HIGH` label. Report separately:

- `factual_evidence_confidence`
- `dependency_confidence`
- `company_capture_confidence`
- `source_view_freshness`
- `timing_confidence`
- `identity_confidence`

A ticker may have high factual confidence and low dependency confidence at the same time.

### 10. Claim-level grounding before output

Every material report claim should be labeled internally as one of:

- `SUPPORTED` — directly supported by admitted evidence;
- `INFERENCE` — reasoned conclusion with explicit premises;
- `UNSUPPORTED` — must not enter the report.

Forward order/revenue outlook is always `INFERENCE` unless a company/counterparty has disclosed the figure as a commitment or guidance.

### 11. Timing and information gap are separate from price performance

Do not use price appreciation as proof of a bottleneck. Timing evidence can include qualification dates, capacity start dates, contract windows, bookings/order changes, customer rollout schedules, institutional validation, and source-view evolution.

Price/attention data may describe expectations or crowding, but it is not company-fact evidence.

### 12. Always end with falsifiers

For each final candidate state what would make the thesis wrong or weaker, including qualified substitutes, faster competitor capacity, architecture bypass, customer loss, failed qualification/ramp, demand deterioration, pricing collapse, margin/capture failure, financing dilution, governance, export/geopolitical constraints, and valuation already pricing success.

## LINE Top 20 output contract

The final visible order is exactly:

1. 股票
2. 長期投資報酬率（近2年年化）
3. 短期投資報酬率（近6個月）
4. 行業別
5. 獲利簡述
6. 公司現在訂單
7. 未來訂單預估

`公司現在訂單` may use disclosed backlog/order book, signed commitments, fixed quantities, minimum-take/MOQ, capacity reservations and prepayments.

`未來訂單預估` must be evidence-bound. Do not invent a total order or revenue number. Fail closed with `未揭露（無可靠公開訂單數字）` / `無可靠公開預估` when necessary.

## Required final research object

For each ticker retain, even if not displayed in LINE:

- architecture/system-change map;
- supply-chain layer and evidence-bound graph;
- qualified/effective substitute map;
- demand/capacity/qualification timeline;
- signed order/commitment evidence;
- company-capture and financing overlay;
- public Serenity source-view lifecycle;
- information-gap / market-awareness state;
- multi-axis confidence;
- claim-level support labels;
- explicit falsifiers;
- source URLs, dates, hashes/provenance where available.

Research support only. Never auto-trade, never use owner/broker private data as a public factual fallback, and never silently upgrade a missing public source to a lower-trust source.