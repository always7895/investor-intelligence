# Options source review (development checkpoint)

For the broader stock/news/macro source audit and explicit local collector, see [Public source coverage / 全來源覆蓋](PUBLIC_SOURCE_COVERAGE.md). Broader coverage does not upgrade option quote eligibility.

No new provider is activated by this review. Free access does not establish redistribution rights. Public LINE remains isolated from brokerage accounts. Existing prohibited-provider decisions remain intact pending explicit, evidenced policy review.

## Implemented local-export adapters / 已實作本機匯入

`scripts/import_option_observations.py` accepts an operator-authorized export, normalizes only allowlisted fields and prints a LOCAL_IMPORT_ONLY document. It performs no HTTP, credential lookup, storage publication or orders. It is deliberately not wired into the public LINE quote DTO or scheduled refresh. These adapters add import capabilities, not verified live feed availability.

```powershell
python scripts/import_option_observations.py --source taifex_eod --input <authorized-daily-export.json>
python scripts/import_option_observations.py --source alpaca_indicative --input <authorized-indicative-export.json>
```

- TAIFEX: official schema https://openapi.taifex.com.tw/swagger.json defines `DailyMarketReportOpt`, including trade date, contract month/week, strike, call/put, bid/ask, volume, open interest and session. Daily date is not an intraday quote timestamp; week codes are not invented expiry dates. Missing `-` observations remain null. Futures are not substituted for options.
- Alpaca: https://docs.alpaca.markets/us/reference/optionlatestquotes documents the latest quotes map. The adapter accepts **indicative exports only**, explicitly labels OPRA_DERIVED/INDICATIVE_NOT_NBBO, preserves timestamps and does not infer multiplier or Greeks. Operators must not import OPRA-entitled data under an indicative label.
- TAIFEX general website terms do not grant blanket reuse. The later [dataset-specific review](PUBLIC_SOURCE_RIGHTS_REVIEW_20260909.md) maps dataset11320 to the daily OpenAPI under Open Government Data License v1 with attribution. This is not permission for general scraping, commercial/realtime feeds or US options; the importer itself never grants publication eligibility.
- All output records carry `publication_eligible=false` and `executable_quote=false`. Import time never replaces retrieval/quote time. Invalid rows, duplicates, stale/future quotes, nonfinite/negative/crossed prices, fractional counts, unsupported sessions and malformed contracts are covered by regression tests. Stale valid records remain labelled observations, not current recommendations.
- The CLI returns nonzero for partial, failed or empty imports; failures contain only row index/category, not raw source text. Authorized exports remain local and must never be committed.

繁中摘要：既有匯入器保留，TAIFEX 是日行情、Alpaca 是 indicative；皆不等於即時可成交報價。資料集11320的特定免費授權已有後續審查，但不因此開啟LINE或把匯入時間當行情時間。

## Explicit free TAIFEX daily collection / 免費日終資料候選

```powershell
python scripts/fetch_public_source_observations.py --fetch --source taifex_options_eod --output <new-local-observation-file.json>
```

The existing bounded collector now accepts that exact endpoint through its staged adapter registry; default source selection is unchanged. No account, cookie, credential, paid tier, retry, redirect or alternate quote feed is used. This is local collection, not an additional publication workflow.

- `scripts/taifex_contract.py` shares date/contract/month-week/right/session identity rules with the existing local importer. Friday `F` series are preserved without guessing expiry dates; malformed calendar months fail. Importer compatibility, its historical-observation role and its crossed-quote rejection remain.
- The stricter HTTP candidate requires the observed closed schema, a single trade date within a conservative seven-calendar-day ceiling, valid numbers/OHLC and unique contract/session identities. This ceiling is not exchange-calendar or LINE current-quote qualification. Missing observations stay null; session rows/OI are never combined.
- Last best bid/ask have no per-quote timestamps; no simultaneous midpoint, currency, multiplier, expiry day, DTE or Greeks are inferred. Crossed EOD values remain explicitly labelled anomalous, non-executable observations, not admissible order prices.
- Every row retains TAIFEX/dataset11320/date/year/license attribution and `publication_eligible=false`, `line_quote_eligible=false`, `executable_quote=false`. `candidate_implemented` never satisfies `adapter_reviewed` or enables runtime. Current live/LINE quote-provider eligibility remains zero.
- Actual collector proof:12,488 rows for2026-09-09, local only, zero parser warnings. Exact attempts, final source binding and regression scope are recorded under `audit-runtime/free-taifex-eod-a/` and STATUS. This is one source, not independent multi-provider evidence or LINE launch acceptance.

## Independent delivery paths to investigate

| Source | Evidence | Appropriate scope / unresolved limitation |
| --- | --- | --- |
| Alpaca | https://docs.alpaca.markets/us/docs/historical-option-data | Official API documents a free indicative derivative of OPRA and history since February 2024. Indicative prices are not executable NBBO. Credentials, public redistribution and compatibility with free-only/non-broker policy remain unreviewed. |
| Tradier | https://docs.tradier.com/docs/market-data and https://docs.tradier.com/docs/authentication | Official API documents brokerage real-time options and 15-minute delayed sandbox data. Public applications require contacting Tradier. Existing catalog prohibition is NOT overturned by API availability. |
| Yahoo/yfinance | Existing development provider policy | One origin regardless of wrapper/package count; not reviewed for live public LINE publication. |

These are research candidates, not implemented adapters or independent economic observations: multiple vendors may redistribute the same OPRA origin. Exchange contract/open-interest references cannot substitute for timestamped contract-level bid/ask.

## Implementation acceptance

- Match underlying, expiry, right, strike, multiplier and adjusted deliverable before comparison.
- Preserve vendor, upstream origin, quote time versus retrieval time, feed type and entitlement/rights decision.
- Reject nonfinite/negative prices, crossed quotes, stale/future observations and mismatched contracts; preserve missing volume/OI/Greeks rather than inventing zeros.
- Never average incompatible timestamps or label indicative/delayed prices executable.
- Provider failure must be explicit per ticker; preserve good primary results without inventing missing watchlist coverage.
- Exercise actual public builder and local orchestration separately with synthetic transports; no account data in public fixtures.

## Bounded review allocation

One writer integrates. Small-model reviewers, if available, receive only a file list and bounded read-only question (catalog rights, caller graph, or test gaps). Higher-capability review is reserved for privacy/publication invariants and final diffs. No reviewer tools were available in the current harness discovery, so no delegated model execution or token savings are claimed. Do not switch the existing inference Router or install another agent to simulate delegation.
