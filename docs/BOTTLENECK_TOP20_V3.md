# Bottleneck-explosion Top20 v3 / 瓶頸爆發 TOP20

Status: live in LINE from 2026-09-26 (operator request: the Top20 must follow Serenity's bottleneck logic, exclude
negative long-term returns, rank future bottleneck explosions, and an industry analysis led by Leopold
Aschenbrenner's logic must name the most explosive industries from current events). Current Production state is in
[STATUS](../state/STATUS.md).

## Why the old Top20 differed from Serenity

- Candidates came from three generic Yahoo screeners (most actives, day gainers, undervalued growth).
- The scorer's `chokepoint` and `replacement_friction` factors were fixed at zero, so low P/E and revenue growth
  ranked insurers and retailers; price history was not scored, so negative long-term returns could rank.

## Pipeline

| Step | Script | Source | Cadence |
| --- | --- | --- | --- |
| Serenity leads | `scripts/serenity_signals.py` | public archive `yan-labs/serenity-aleabitoreddit` (post URLs) | 6 h |
| Leopold leads | `scripts/leopold_positions.py` | SEC 13F-HR of Situational Awareness LP (CIK 2045724) | 24 h |
| Layers | `config/bottleneck-layers-v3.json` | structure only: company role in a scarce layer, dated source | reviewed |
| Ranking | `scripts/bottleneck_top20_v3.py` | SEC XBRL companyfacts, Yahoo Finance (labelled unofficial), SEC full-text search | 3 h |
| Seal | `publish_sealed_snapshot.py --bottleneck-v3` | lazy object `v213:bottleneck-top20:v3` | hourly |

Leads weight conviction only; every figure users see comes from filings or market data with its source and date.

## Company score (0–100)

- COMPOUNDER (market cap ≥ US$10B): layer heat 25, company capture 30, lead conviction 20, market confirmation 15,
  size 10. EXPLOSION (< US$10B, often before volume revenue): 25 / 15 / 30 / 20 / 10.
- Capture: latest-quarter revenue YoY, acceleration, gross-margin change, remaining performance obligations,
  normalized over the evidence available (fiscal quarters; a fourth quarter is annual minus nine-month YTD).
- Penalties: share count +5% / +15% a year (SEC shares outstanding; without it, as for dual-class filers and Yahoo-sourced listings, the quarter's diluted weighted-average shares against the same quarter a year earlier, labelled 稀釋加權平均股數; a change outside -50%..+500% is treated as a data error), repeated financing concerns in Serenity's posts.
- Filters: one long-term standard — positive 2-year CAGR (an eligibility gate, not a score component). A security whose
  own regular-way trading is younger than two years because of a verified corporate event (spin-off, trading resumption,
  IPO, new equity after a reorganisation; `config/listing-lineage-v1.json`, every field backed by a primary source,
  checked by `scripts/listing_lineage.py`) uses the annualized return from its first regular-way session, never from
  when-issued trading or a parent's/predecessor's shares, and needs at least 365 days. A short history without a verified
  record is excluded as `HISTORY_OR_LINEAGE_UNVERIFIED` (a verified segment under one year: `MARKET_HISTORY_UNDER_1Y`); a
  missing figure is never read as a negative return. No clearly bearish Serenity stance; at most five names per layer.

## Industry ranking (產業爆發榜, Leopold-led)

Explosiveness = position on Leopold's chain (compute → power → datacenter → chips/memory → network/optics →
materials) 35 + the fund's 13F weight in the layer 25 + median revenue acceleration 20 + SEC filing mentions of the
layer's terms (last 30 days versus the prior 60) 10 + Serenity heat 10.

## LINE

Every card shows the same two returns: 6-month return and 2-year CAGR. A verified short segment reads 獨立交易價格未滿2年
with "<first regular-way session>–<as of> 正常交易以來年化 X%（非2年）" (a resumption: 恢復交易以來); the verified event
(e.g. "2025-02-21 自 Western Digital（WDC）分拆；2025-02-24 起正常交易") shows on every form, also when two years exist, and
the detail lists its primary sources; an unverified short history reads 2年價格資料不足 (可得價格自 <date>；上市沿革未核實),
never "new company". Serenity/Leopold lead scores weight the ranking but are not shown; the
card shows the current-orders tile and an order block instead (operator 2026-09-27; Astra contract ORDERS-V2-01;
`scripts/order_forecast.py` build_v2, sealed as `outlook.order_forecast` version 2, re-validated by
`cloud/src/v213/order-forecast.ts`): 未來訂單預估 with 半年內預計認列 and 1年內預計認列 = the signed orders the company states
it will recognize within that period (RPO × the disclosed share, from the measurement date, 起算日…（非今日起）; an undisclosed
horizon reads 未揭露, interpolated shares are never used); 訂單實現後股價情境 with 若半年內／1年內實現訂單 → 股價預估 ±X% = the
conditional price change if those orders are realized (revenue at that level, P/S and share count unchanged; 非目標價、非今日起報酬).
When the signed orders cover less than the period's revenue level (quarter × months / 3) no price is estimated and the
coverage is shown. An order book extrapolated at its year-on-year change is a labelled model sensitivity
(訂單餘額外推敏感度, never a price). Later issuer disclosures come from the reviewed registry `config/order-claims-v2.json`
(`scripts/order_claims.py`: primary documents with hashes and reviewed publisher URL prefixes, verbatim passages,
measurement and publication dates; selected at the exact build instant; a company US-dollar RPO measured later than the
filing on ASC 606, or correcting/cancelling it via `FILING:<accession>` (published after that filing), is current: with its own schedule it replaces the filing's,
without one both horizons read 未揭露 and the filing's schedule stays a dated reference; a zero, unquantified or range
figure withholds every calculation; a same-date figure differing from the filing without a correction is a conflict;
contracts, intake, guidance and backlog are dated references 期後訂單消息（不併入 RPO）). A registry schedule is priced only
with the filing's validated quarter. The sealed record carries the allowlisted periodic input, order book and claims, and
the Worker recomputes every figure and refuses the whole record on any difference. Not supported (contract amendment):
explicit recognition amounts, schedules with their own period, schedules for a backlog or for the filing's stock. Each
card names 訂單資料截至／來源公布（／本次查核 for reviewed claims) and shows one later disclosure with a count; the detail lists
all with revision reasons. Per issuer at most 8 claims and 4 documents are sealed (EVIDENCE_LIMIT beyond), so twenty
cards fit the LINE limits; a presentation budget of 2,400 UTF-16 units per issuer and lossless pagination of the text detail keep every source line. Analyst targets appear only in the detail as a labelled reference. Fixed-period figures
(24-month schedules, annual new-order guidance) are references only. On 2026-09-27 filings: 1-year schedules for SNDK, MU,
NVDA, AVGO, AMD and CRDO; CRWV/NBIS 24 months only; Gemini's survey found no 6-month schedule and no later order
disclosure except MU's (writer-verified: MU, CRDO and 5351.TWO only); the registry holds one verified MU reference (SCA RPO
about US$100B incl. post-FQ3 agreements). The deployed reader 16cb1b3 ignores the field and keeps its analyst tiles; the
eca78a1 reader shows version 2 as unavailable; rollout order is decided in the rollout review.

### ORDERS-V3-01: 訂單認列／營收推估與營收實現後股價情境 (Astra contract ORDERS-V3-01 & staleness amendment)

Separates company-wide total revenue models from contractual order recognition (Tile 2: `訂單認列／營收推估`,
Tile 3: `營收實現後股價情境`; operator 2026-09-27; Astra contract ORDERS-V3-01 and amendment 2026-09-28):
- **Tile 2: 訂單認列／營收推估**
  - Company guidance: `公司營收財測＋模型（非訂單）`
  - Analyst consensus: `非公司揭露、非訂單：分析師季度營收共識＋模型`
  - Contracted recognition only: `已簽約預計認列`
  - Contracted recognition beside revenue projection defaults to `另列已簽約預計認列：半年期 X（起訖日；不相加）` / `1年期 X（起訖日；不相加）` (`其中` requires matching issuer, currency, scope, window and proven inclusion).
- **Tile 3: 營收實現後股價情境**
  - Dimensionless constant-P/S formula:
    `B = a1 + a2 + a3 + a4` (latest four standalone reported quarters)
    `amount6 = f1 + f2`, `amount12 = f1 + f2 + f3 + f4`
    `TTM6 = a3 + a4 + f1 + f2`, `TTM12 = f1 + f2 + f3 + f4`
    `change6 = TTM6 / B - 1`, `change12 = TTM12 / B - 1`
  - If 4 reported actuals are missing, price scenario is `NO_BASIS` (`缺完整四季營收基準，無法估算`).
  - If revenue model is unavailable but contracted recognition is valid, Tile 3 is `NO_BASIS` (`缺完整營收推估，無法估算股價情境`).
  - Card assumptions on all surfaces: `條件情境：營收依上述推估實現，P/S與股數不變；以最新已報四季為基準，非目標價、非今日起報酬`.
- **Time semantics & Post-quarter-end bridge (Astra amendment):**
  - Fiscal 2Q / 4Q convention (`horizon_convention: FISCAL_2Q_4Q`), anchored at latest reported quarter end A. Strict adjacency is required: `f1.start == A + 1 day`, all four forward intervals must be strictly contiguous without gap, and no forward interval may overlap reported actuals. The post-quarter-end bridge (+70-day cap) governs freshness of an ended, unreported quarter after A, not fiscal placement. Endpoints are second and fourth forward quarter ends: `約6個月（2財季）` and `約1年（4財季）` with `自{start}起，非今日起`.
  - Latest-release receipt age <= 24 hours at cutoff C, sourced exclusively from the runtime release-check cache (`data/cache/revenue_guidance_release_checks.json`), covering SEC and wire channels (`SEC_AND_WIRE`; missing/failed/incomplete: `FRESHNESS_UNVERIFIED`).
  - Canonical digest: SHA-256 over keys-sorted canonical JSON using `ensure_ascii=False` (preserving Unicode titles in Korean/Chinese across Python and Worker).
  - Guidance publication age <= 200 days at cutoff C.
  - For each ended, unreported quarter after A used by the path (`UTC_date(C) > quarter.end`): requires `UTC_date(C) <= quarter.end + 70 calendar days`. Day +70 is eligible; day +71 is STALE.
  - Warning on all surfaces: `財測季度已於{end}結束，實際營收尚未公布` (or FY allocation: `全年財測推算季度已於{end}結束，實際營收尚未公布`) together with `截至{checked_at}查核；仍為財測／模型，非實績`.
  - Consensus adapter does not get the +70d bridge (expired if guided period ended at cutoff).
- **First-rollout profile (Astra scope ruling 2026-09-28, `astra-scope.result.md`; W1 ruling `astra-ir-coverage.result.md`):**
  - A company-guidance projection needs three checked channels (`SEC_WIRE_IR`): EDGAR submissions, the Nasdaq wire feed and the issuer's official IR press-release channel (`release_channels.ir`: Q4 feed, RSS or newsroom list, read by `scripts/issuer_ir_feeds.py`; the same-day IR item whose title equals `ir_guidance_release_title` is the guidance release itself). Admitted with IR: NVDA CRWV LITE CRDO MU BE AMD MRVL NBIS. AVGO, SNDK, AAOI, ALAB and MTSI block automated IR access: their projection shows 「官方IR查核未完成，暫停營收推估」 (`IR_COVERAGE_MISSING`) and any contracted recognition stays.
  - Items dated on the guidance day are ambiguous (feeds are day-granular) and stay review items until the writer records them in `reviewed_later_documents` (the guidance filing itself, the same-day periodic report of the anchor quarter, wire copies of the same release). Ownership, registration and proxy filings, and 8-Ks carrying only items 1.01/1.02/2.03/3.02/5.02/5.03/5.07/9.01, are never review items.
  - Document hashes (W2): SHA-256 of the exact public bytes, with EDGAR's per-response watermark attribute value (`bazadebezolkohpepadr="…"`) zeroed at equal length, since EDGAR varies it between requests while the filing is immutable. The byte inventory lives with the writer's evidence (`_archive\lane-orders-v3\sources`, `w2-manifest.json`).
  - Reviewed profile (A1): `config/revenue-guidance-approval-v1.json` binds the exact registry bytes and each record's canonical hash to the writer's decisions (claims verbatim in source, actuals and derivation operands found in their documents, calendar rules quoted, FY reconciliation, routing), all re-verified against the kept source bytes by `_archive\lane-orders-v3\verify\make_approval.py`. A changed registry or record, a missing decision or a decision later than the build cutoff suspends that issuer's revenue path (`UNREVIEWED_INPUTS`, 「營收輸入未經審核，暫停營收推估」); any change to the registry needs a new approval.
  - Official IR coverage is conservative (A2): a feed that does not list the reviewed guidance release on its day, an empty answer or malformed/truncated RSS is incomplete; a title is exempt only when it is, as a whole, one of the known nonmaterial notices (a results-date notice, a date or conference-call announcement, a meeting-vote outcome, a dividend declaration) naming only the issuer before the notice; any other title with financial wording (results, revenue, earnings, sales, guidance, outlook, targets, forecasts, expectations or an expectation verb, preliminary, a financial model/update, a business update), or with an amount or percentage next to period wording, is a review item. For a figure reaffirmed later (NBIS) the interval before the reaffirmation was checked once by the writer (`_archive\lane-orders-v3\verify\nbis-pre-reaffirmation.txt`).
  - Korean quarterly consensus is disabled for the first rollout (`consensus_enabled: false` in the registry, collector not scheduled): 000660.KS and 005930.KS show 「公司未提供營收財測；分析師共識路線本次未啟用」 (`CONSENSUS_DEFERRED`). The adapter stays in the tree (yfinance session transport; a plain request gets HTTP 401) for ORDERS-V3-CONSENSUS-01.
  - Deferred lanes (Astra scope ruling; owner: Claude Code for integration and evidence, implementation by the workspace routing, Astra accepts each fixed snapshot):
    | Lane | Scope | Residual risk | Enforcement / test receipt now | Re-entry trigger |
    |---|---|---|---|---|
    | ORDERS-V3-HARDEN-01 | Worker re-validation of duplicates and metadata the producer already rejects | a future producer regression is caught later | producer projection + approval gate, real-caller tests, W3 replay | another producer, an unsealed input, use of ignored fields |
    | ORDERS-V3-SCHEMA-01 | general revision graphs, other actual/calendar/FY shapes | valid new shapes stay unavailable | approval gate refuses unreviewed records; tests for refused shapes | before admitting a new shape |
    | ORDERS-V3-CONSENSUS-01 | Korean quarterly consensus | no Korean numeric projection | `consensus_enabled: false`, unscheduled collector, gate-off tests | before enabling the collector or the path |
    | ORDERS-V3-TRANSPORT-01 | streaming byte caps; IR adapters for AVGO SNDK AAOI ALAB MTSI | those five stay suspended | IR_COVERAGE_MISSING tests; post-decode bounds | before enabling consensus or any new adapter |
    | ORDERS-V3-TESTS-01 | exhaustive combinations, older non-rollback readers, cosmetic variants | less coverage outside the profile | focused suites, golden, W3 | before widening the profile |
- **Runtime inputs and refresh (writer integration):**
  - `scripts/revenue_guidance_release_check.py` writes the receipts (EDGAR submissions of the issuer + Nasdaq's press-release feed for the symbol, items naming the issuer; the newest 8 per issuer). 8-K item 2.02 or a periodic report for a later period is `RESULTS_RELEASE`; 8-Ks carrying only items 1.01/1.02/2.03/3.02/5.02/5.03/5.07/9.01 are irrelevant; any other 8-K/6-K and wire titles about results/revenue/guidance/outlook are `POSSIBLY_RELEVANT` until the writer records them in `reviewed_later_documents` (id: accession or `https://www.nasdaq.com/press-release/...`). A channel read completely back to the guidance date is checked through the day of the check.
  - The check starts from the guidance reference document: the claim's own document or, when the company later reaffirmed the figure without restating it (`reaffirmed_by`, e.g. NBIS: figure in the May letter, reaffirmed in August), the latest reaffirmation.
  - `scripts/revenue_consensus_quarterly.py` serves only the registry's `NOT_DISCLOSED` issuers through the project's yfinance session and keeps the newest 8 captures per issuer.
  - `scripts/run_daily_data_refresh.ps1` runs the release-check collector immediately before `bottleneck_v3` (the consensus collector is not scheduled while `consensus_enabled` is false); the sealer binds, per issuer, the newest receipt and the newest consensus capture taken at or before the v3 document's `generated_at` (a later capture never feeds an older build).
  - Curated records need review after every earnings release (the receipt turns `RESULTS_PUBLISHED`/`REVIEW_REQUIRED` and the card shows the reason until the record is updated). The Worker golden `tests/fixtures/v213-orders-v3-golden-sealed.json` is regenerated by `tests/fixtures/make_orders_v3_golden.py` (a test asserts it is reproducible).
- **Dual fields & Reader order:**
  - Sealed additive dual fields: `outlook.order_forecast` (v2, built by unchanged `build_v2`) and `outlook.order_forecast_v3` (v3, built by `build_v3`).
  - New reader validates `order_forecast_v3` if present in outlook; never falls back `v3 || v2`. A tampered or present-invalid v3 fails as INVALID (does not downgrade to v2). Genuine absence of v3 allows v2 parsing. Old readers ignore v3 and read v2 unchanged.

#### `config/revenue-guidance-v1.json` Schema Specification

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "RevenueGuidanceV1Registry",
  "type": "object",
  "required": ["schema", "version", "issuers"],
  "properties": {
    "schema": { "type": "string", "const": "revenue-guidance-v1" },
    "version": { "type": "integer", "const": 1 },
    "issuers": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["symbol", "company_name", "status", "url_prefixes", "documents", "claims", "reported_quarters", "forward_intervals"],
        "properties": {
          "symbol": { "type": "string", "pattern": "^[A-Z0-9][A-Z0-9.\\-]{0,19}$" },
          "company_name": { "type": "string" },
          "status": { "type": "string", "enum": ["GUIDANCE", "NOT_DISCLOSED", "INPUTS_MISSING", "STALE", "CONFLICTING_DISCLOSURES", "WITHDRAWN", "INVALID"] },
          "reason": { "type": ["string", "null"] },
          "url_prefixes": { "type": "array", "items": { "type": "string", "format": "uri" }, "maxItems": 4 },
          "documents": {
            "type": "array",
            "maxItems": 16,
            "items": {
              "type": "object",
              "required": ["id", "issuer", "publisher", "title", "source_kind", "url", "published_date", "retrieved_at", "sha256", "byte_size", "lineage_id"],
              "properties": {
                "id": { "type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$" },
                "issuer": { "type": "string" },
                "publisher": { "type": "string" },
                "title": { "type": "string" },
                "source_kind": { "type": "string", "enum": ["SEC_PERIODIC", "SEC_8K_EXHIBIT", "SEC_6K_EXHIBIT", "ISSUER_EARNINGS_RELEASE", "ISSUER_TRANSCRIPT", "ISSUER_PRESENTATION", "OFFICIAL_FISCAL_CALENDAR", "OFFICIAL_FINANCIAL_STATEMENT"] },
                "url": { "type": "string", "maxLength": 400 },
                "published_date": { "type": "string", "format": "date" },
                "published_at": { "type": ["string", "null"], "format": "date-time" },
                "retrieved_at": { "type": "string", "format": "date-time" },
                "sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" },
                "byte_size": { "type": "integer", "maximum": 52428800 },
                "lineage_id": { "type": "string" }
              }
            }
          },
          "claims": {
            "type": "array",
            "maxItems": 8,
            "items": {
              "type": "object",
              "required": ["id", "document_id", "locator", "passage", "metric", "assertion_kind", "currency", "unit_multiplier", "scope", "fiscal_label", "period_kind", "period_start", "period_end"],
              "properties": {
                "id": { "type": "string" },
                "document_id": { "type": "string" },
                "locator": { "type": "string" },
                "passage": { "type": "string", "maxLength": 1000 },
                "metric": { "type": "string", "const": "REVENUE" },
                "assertion_kind": { "type": "string", "const": "COMPANY_GUIDANCE" },
                "currency": { "type": "string", "enum": ["USD", "KRW", "TWD", "SEK", "JPY", "EUR", "GBP", "HKD", "CNY"] },
                "unit_multiplier": { "type": "integer", "enum": [1, 1000, 1000000, 1000000000] },
                "amount": { "type": ["number", "null"] },
                "low": { "type": ["number", "null"] },
                "high": { "type": ["number", "null"] },
                "stated_point": { "type": ["number", "null"] },
                "scope": { "type": "string", "enum": ["COMPANY", "SEGMENT"] },
                "fiscal_label": { "type": "string" },
                "period_kind": { "type": "string", "enum": ["QUARTER", "FISCAL_YEAR"] },
                "period_start": { "type": "string", "format": "date" },
                "period_end": { "type": "string", "format": "date" },
                "accounting_basis": { "type": "string", "enum": ["GAAP", "NON_GAAP", "IFRS", "K-IFRS"] }
              }
            }
          },
          "reported_quarters": {
            "type": "array",
            "maxItems": 8,
            "items": {
              "type": "object",
              "required": ["fiscal_label", "start", "end", "revenue", "currency", "scope", "accounting_basis", "document_id", "locator"],
              "properties": {
                "fiscal_label": { "type": "string" },
                "start": { "type": "string", "format": "date" },
                "end": { "type": "string", "format": "date" },
                "revenue": { "type": "number" },
                "currency": { "type": "string" },
                "scope": { "type": "string", "enum": ["COMPANY", "CONSOLIDATED"] },
                "accounting_basis": { "type": "string", "enum": ["GAAP", "NON_GAAP", "IFRS", "K-IFRS"] },
                "document_id": { "type": "string" },
                "locator": { "type": "string", "maxLength": 120 },
                "derivation": {
                  "type": ["object", "null"],
                  "description": "XBRL YTD-difference derivation: revenue = longer_value - shorter_value (re-validated), citing the longer/shorter YTD documents."
                }
              }
            }
          },
          "forward_intervals": {
            "type": "array",
            "minItems": 4,
            "maxItems": 4,
            "items": {
              "type": "object",
              "required": ["start", "end"],
              "properties": {
                "fiscal_label": { "type": "string" },
                "start": { "type": "string", "format": "date" },
                "end": { "type": "string", "format": "date" },
                "calendar_locator": { "type": "string", "maxLength": 1000 }
              }
            }
          },
          "fy_reconciliation": {
            "type": ["object", "null"],
            "description": "Dated YTD basis for the FY allocation: fy_claim_id, ytd_start/ytd_end, ytd_revenue (reconciled against the reported quarters inside the window) and the optional ytd_quarter_ends list (each a day inside the YTD window).",
            "properties": {
              "fy_claim_id": { "type": "string" },
              "ytd_start": { "type": "string", "format": "date" },
              "ytd_end": { "type": "string", "format": "date" },
              "ytd_revenue": { "type": "number" },
              "ytd_quarter_ends": { "type": "array", "maxItems": 8, "items": { "type": "string", "format": "date" } }
            }
          },
          "release_channels": {
            "type": ["object", "null"],
            "description": "Collector wiring for the latest-release check (writer-owned targets); validated when present.",
            "properties": {
              "sec_cik": { "type": "integer", "minimum": 1 },
              "news_query": { "type": "string", "maxLength": 40 }
            }
          },
          "reviewed_later_documents": {
            "type": "array",
            "maxItems": 16,
            "description": "The writer's review of a receipt's later_documents: each entry {id, disposition: REVIEWED_IRRELEVANT, reviewed_at?, note?}; a REVIEWED_IRRELEVANT entry may suppress a POSSIBLY_RELEVANT later document in the status recomputation.",
            "items": {
              "type": "object",
              "required": ["id", "disposition"],
              "properties": {
                "id": { "type": "string" },
                "disposition": { "type": "string", "const": "REVIEWED_IRRELEVANT" },
                "reviewed_at": { "type": "string", "format": "date-time" },
                "note": { "type": "string", "maxLength": 300 }
              }
            }
          }
        }
      }
    }
  }
}
```

The runtime release-check cache (`revenue-guidance-release-checks-v1`, `release-check-cache-spec`) seals one
receipt per issuer: `channels` (SEC submissions index + wire/press channel, each with status/completeness and
checked-through day), `later_documents`, `coverage: SEC_AND_WIRE`, `anchor_end`, `guidance_document_id` and a
`digest` over the receipt's own canonical JSON without digest (`ensure_ascii=False`). Both readers (Python `revenue_guidance.validate_receipt` and the Worker's
`parseV3`) recompute the digest and the status from the channels; a missing, stale (> 24h at the build cutoff),
future-dated, digest-mismatched, or status-mismatched receipt reads `FRESHNESS_UNVERIFIED`/`STALE`, never "no newer
release". Receipts are runtime-cache only; no legacy registry-embedded receipt fallback is permitted.

The post-quarter-end bridge governs staleness per ended, unreported quarter after the anchor A used by the path:
each such quarter's end must be within 70 calendar days of the cutoff's UTC day (day +70 eligible, +71 STALE), with
the mandatory warning on all surfaces. Strict A-to-f1 adjacency (`f1.start == A + 1 day`) and interval contiguity are
strictly required. Guidance publication age must be <= 200 days at cutoff C.
anchor quarter (the registry's fiscal calendar places the guided quarter); the 70-day cap, the 24h receipt age and
the 200-day guidance-publication cap (200 eligible, 201 not) remain the fail-closed bounds. Consensus does not get
the bridge: a consensus path whose guided quarter has ended at the cutoff is STALE.

`瓶頸詳情` opens the SEC company report rather than
repeating the card; non-SEC filers get the filing and price figures with sources.

Names: the symbol, the sourced Traditional Chinese name and the original name. Sources, in order: the company's own
Taiwan registration (`config/company-zh-names-v1.json`, GCIS citation per entry), the Chinese Wikipedia article as shown
to zh-tw readers, the Wikidata zh-tw/zh-hant label (`scripts/build_zh_names.py`, weekly); Taiwan listings use the
exchange's Chinese short name. Without a source the card says 無公認中文名; nothing is translated. The same names are
in the identity shards, so the stock lookup shows them and accepts them as queries (e.g. 輝達).

Stock lookup prices: the watch-universe quote (hourly) when present, otherwise the listing's market price shard from
official bulk feeds (`scripts/build_price_shards.py`, every 3 h): Nasdaq stock screener (US, with its stated price
date), TWSE STOCK_DAY_ALL and TPEx daily close (Taiwan, trade date), Nasdaq Nordic (Stockholm; no trade date in the
feed, so the retrieval time is shown as such) and Euronext closing prices. Sealed as lazy `v213:prices:v1:<MARKET>`;
the Worker ignores a shard older than 4 days. Japan and Korea have no free official bulk price file: their common
stocks get Yahoo Finance daily closes once a day (labelled unofficial, each row with its own date). London Main
Market and AIM equities (for example IQE) come from the exchange's public price-explorer API, both as identities and
as last prices (no trade date in the response, so the retrieval time is shown); they are optional feeds, so an
outage there never blocks the other markets.

`TOP20` (v3 when sealed and fresh, else the seven-field Top20), `瓶頸詳情 代號`, `產業爆發榜`, `七欄Top20`.
The Worker refuses a v3 document older than the report bound (14 h) and falls back rather than showing stale data.

## Official previous-quarter comparator (Astra contract L18-5351-CURATED-01)

Yahoo's quarterly income statement has five quarters, so the preceding quarter of some listings has no year-earlier
comparator and its YoY (and the acceleration) stays null. `config/official-quarterly-revenue-v1.json` holds reviewed
records that supply both operands of that previous-quarter YoY from the issuer's CPA-reviewed interim reports;
`scripts/official_quarterly_revenue.py` validates them for the builder and the sealer. One record exists: 5351.TWO
(Etron), current quarter 2026-06-30, previous 2026-03-31 (Q1 report note 六(二十四) p.39: 2,735,412 / 627,130 TWD
thousands; Q2 report p.42: 4,898,686 / 744,722, half-year 7,634,098 / 1,371,852). No other listing is covered.

- Applies only when Yahoo lacks the comparator (an available, zero or conflicting one is never replaced), for the exact
  symbol, the exact Yahoo quarter pair and a Yahoo financial statement currency (`financialCurrency`, not the quote
  currency) equal to the record's. A later Yahoo quarter makes the record inapplicable.
- Yahoo's `Total Revenue` is in base currency units; the official thousands are multiplied by exactly 1000. All three
  overlapping quarters must agree within 1000 TWD (one reporting unit) and the current YoY within 0.00001; the half-year
  minus the second quarter must equal each first-quarter claim. Failures leave the previous YoY null with a local
  reason (`revenue_yoy_prev_reason`: NO_RECORD, PERIOD_MISMATCH, CURRENCY_UNVERIFIED, CROSS_CHECK_MISMATCH,
  INVALID_RECORD, AMBIGUOUS_RECORD); the rest of the Yahoo fundamentals stay.
- Wire: `revenue_yoy_prev_basis` (`YAHOO`, `OFFICIAL_CURATED` or null) and `revenue_yoy_prev_source` (evidence
  `official-quarterly-revenue-evidence-v1`: record, documents with hashes, claims with page/note/row, restatement
  reconciliation, observed Yahoo overlaps and the SHA-256 of the config bytes). The sealer rebuilds the evidence from its
  own config and refuses the v3 object on any difference; the Worker repeats the checks and refuses the document.
  Older documents carry neither field and keep their meaning.
- Display: the current quarter stays attributed to Yahoo; the card notes 前一季採官方合併季報 and the detail (text and
  card) names the official report, quarters, note and page and links the Q1 report.
- Rollout: the deployed reader predates these fields and would attribute the figure to Yahoo, so a Worker that knows
  them must serve before data carrying them is published.
