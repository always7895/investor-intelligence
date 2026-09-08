# Options source review (development checkpoint)

No new provider is activated by this review. Free access does not establish redistribution rights. Public LINE remains isolated from brokerage accounts. Existing prohibited-provider decisions remain intact pending explicit, evidenced policy review.

## Implemented local-export adapters / 已實作本機匯入

`scripts/import_option_observations.py` accepts an operator-authorized export, normalizes only allowlisted fields and prints a LOCAL_IMPORT_ONLY document. It performs no HTTP, credential lookup, storage publication or orders. It is deliberately not wired into the public LINE quote DTO or scheduled refresh. These adapters add import capabilities, not verified live feed availability.

```powershell
python scripts/import_option_observations.py --source taifex_eod --input <authorized-daily-export.json>
python scripts/import_option_observations.py --source alpaca_indicative --input <authorized-indicative-export.json>
```

- TAIFEX: official schema https://openapi.taifex.com.tw/swagger.json defines `DailyMarketReportOpt`, including trade date, contract month/week, strike, call/put, bid/ask, volume, open interest and session. Daily date is not an intraday quote timestamp; week codes are not invented expiry dates. Missing `-` observations remain null. Futures are not substituted for options.
- Alpaca: https://docs.alpaca.markets/us/reference/optionlatestquotes documents the latest quotes map. The adapter accepts **indicative exports only**, explicitly labels OPRA_DERIVED/INDICATIVE_NOT_NBBO, preserves timestamps and does not infer multiplier or Greeks. Operators must not import OPRA-entitled data under an indicative label.
- TAIFEX terms https://www.taifex.com.tw/cht/edu/userTerms require permission for reuse except specifically authorized government open datasets. The exception has not been mapped to this endpoint; **public redistribution remains unapproved**. API schema access is not a license.
- All output records carry `publication_eligible=false` and `executable_quote=false`. Import time never replaces retrieval/quote time. Invalid rows, duplicates, stale/future quotes, nonfinite/negative/crossed prices, fractional counts, unsupported sessions and malformed contracts are covered by regression tests. Stale valid records remain labelled observations, not current recommendations.
- The CLI returns nonzero for partial, failed or empty imports; failures contain only row index/category, not raw source text. Authorized exports remain local and must never be committed.

繁中摘要：兩個 adapter 已可匯入合法取得的本機 JSON，不需或讀取金鑰。TAIFEX 是日行情，Alpaca 是 indicative；兩者都不能宣稱即時可成交報價。尚未完成公開再散布授權或真實資料驗收，因此不接入 LINE，也不把匯入時間當行情時間。

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
