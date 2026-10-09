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

## Local TAIFEX Delta/contract-day REFERENCE (dataset 11321, G1B, source text, tests NOT_RUN)

```powershell
python scripts/fetch_public_source_observations.py --fetch --source taifex_options_delta --output <new-local-reference-file.json>
python scripts/import_option_observations.py --source taifex_delta --input <local-export.json>
```

A separate LOCAL_REFERENCE_ONLY collection. The official OpenAPI document (server `https://openapi.taifex.com.tw/v1`, `GET /DailyOptionsDelta`) advertises six string fields: `Contract`, `CallPut`, `ContractMonth(Week)`, `StrikePrice`, `Delta`, `ContractSettlementDay`. It advertises NO as-of date, session, currency, multiplier, underlying, unit or sign convention, and it does not show the response envelope or value formats. The decoder and parser (`taifex_contract.delta_reference_rows` and `delta_reference_records`, shared by the staged adapter and the manual importer; the shared adapter base and the EOD parser are untouched) therefore enforce conservative IMPLEMENTATION constraints whose compatibility with the real response is UNVERIFIED. Acquisition is bounded binary: the collector keeps its existing 8,000,000-byte bounded response read, and the importer reads through ONE binary handle with `read(8,000,001)` and refuses an overflow before any decode (no stat-then-read of a changing file). A quote-aware structural pre-scan then refuses, before anything is materialized, nesting deeper than an array of flat objects, more than 20,000 rows, more than a global budget of 12 scalars per allowed row (a coarse bound; the closed six-key rows and 64-character fields are enforced afterwards) and over-long strings; duplicate JSON keys, NaN/Infinity and every JSON number are refused; rows must be closed six-key string objects of at most 64 characters; duplicate (contract, month/week, strike value, call/put) rows refuse the whole batch (no last-row-wins; strike identity is exact `Decimal` equality, never a float); any unsupported input refuses the whole batch with a fixed `TAIFEX_DELTA_*` code and no raw values.

An output that RETAINS Delta rows is limited to 16,000,000 bytes as each actual caller serializes it; the check runs on the bounded in-memory result after the build and before the caller returns, writes or prints it (not before every append). The collector measures the whole file as `source_observation.atomic_write_json` writes it (UTF-8, `indent=2`, sorted keys, wrapper, per-row `retrieved_at` and `content_sha256`, every requested source included); over budget it drops ALL Delta rows (never a partial set), marks the Delta health row FAILED with `TAIFEX_DELTA_OUTPUT_TOO_LARGE` and leaves the other sources exactly as collected. This is not a universal whole-file cap: after the Delta rows are removed a legacy-only result may still exceed 16,000,000 bytes and is preserved unchanged, and a collection that requests no Delta source is returned untouched. The importer PRINTS (it does not write a file): it measures that compact `ensure_ascii` rendering of a Delta result, plus a CRLF allowance, and prints only a fixed error when over budget; other importer sources print exactly as before.

Rows keep the raw strike, Delta and settlement-day text verbatim plus a lexical status. Delta is never turned into a number, its unit and sign convention stay `UNDOCUMENTED`, and it has NO as-of: `reference_time_status=UNALIGNED_NO_PROVIDER_ASOF`, `provider_asof`, `quote_asof` and `trading_session` are null. The retrieval time of a collector run is the collection time only (not a market time); file time or an operator time is never an as-of. `reported_contract_day` is a date-only REPORTED reference day parsed only from a real `YYYYMMDD` or `YYYY-MM-DD` date: it is not an expiry instant, a cash-settlement convention or a DTE. No currency, multiplier, underlying, instrument class, DTE, annualized yield, executable midpoint or 100-share assumption is created, and nothing is joined into the daily EOD rows (their sessions and semantics are unchanged); a unified view needs real samples that prove identity, precision and clocks first. Every row keeps `publication_eligible=false`, `line_quote_eligible=false`, `executable_quote=false`.

The collector endpoint is merged only AFTER `DEFAULT_SOURCES` is captured, exactly like the EOD feed, so no default or scheduled collection changes; the staged adapter has no evidence builder and is in no source registry or reviewed runtime registry, so nothing reaches research, sealing or LINE. The manual importer keeps UNVERIFIED local origin even for a file that claims TAIFEX, a URL, a receipt or a hash, mints and reads no transport receipt, and reports `imported_at` only; the SHA-256 it reports is computed over the exact bytes it read and is not an authenticated origin. Dataset 11321 has its own free OGDLv1 attribution (carried once in the output envelope), but the canonical public-options catalog still covers dataset 11320 only and all of its flags stay off; nothing here is a public-admission or rights decision, and one authority with two endpoints is not independent confirmation. Nothing was fetched or run: no sample, fixture or value exists, the real response shape, value formats, delimiter conventions and update timing are unobserved, and an unsupported real payload refuses the whole batch.

## Local caller verification and disabled scheduling template (BATCH06)

2026-10-07 local amendment; independent acceptance pending. The earlier G1B `tests NOT_RUN`
text describes its initial source-only checkpoint, not current verification evidence.
`tests/test_batch06_taifex_callers.py` exercises the actual importer `main` and collector
`main`/atomic writer with synthetic files and injected transports: bounded binary reads,
exact raw-byte hashes, UNVERIFIED manual origin, all-or-nothing refusals, final serialized
output budgets and preservation of non-Delta rows. Private-copy mutation checks are in
`tests/test_batch06_mutations.py`. These are not real dataset-11321 compatibility, rights,
transport-origin authentication or live collection proofs.

`scripts/task-templates/taifex-options-eod.disabled.xml` is an inert, opt-in **template**,
not an installer or registration command. Both task and trigger are disabled. No project
entrypoint loads/registers it; no default collection changes. Its only action names the
existing local collector with explicit `--fetch --source taifex_options_eod`. A separately
reviewed/authorized copy must supply the exact Python/source paths, local start boundary
and local output file (outside repository/installed/Production storage); the unresolved
placeholders deliberately prevent direct use. Do not enable or register it without new
scheduling authority. `tests/test_batch06_taifex_task.py` parses the action and fake-runs
the real collector/writer in process, with an injected fixture transport and disposable
output; it never calls Windows Task Scheduler. This is not installed-action/native proof.

Public EOD option display remains BLOCKED by the separate O12 rights/scope contract:
only delayed quotes and metadata-only coverage have public contracts, neither permits
EOD/Delta values. All public admissions remain NONE. JP/HK/EU/AU adapter work (O5) waits
for a pinned official wire specification from a separate bounded research task; no
provider format is invented and no adapter or rights decision is added here.

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
