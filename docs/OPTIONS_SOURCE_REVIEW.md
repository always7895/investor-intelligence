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

2026-10-07 local amendment; accepted (scoped O1/O9) by the executor (`R/ASTRA-BATCH06-R2-RESULT.txt`) and independently by the master (`R/BATCH06-MASTER-INDEPENDENT-ACCEPT-CLAUDECODE-2440b1e0.txt`) on the same snapshot, committed in `6fb30da`. The earlier G1B `tests NOT_RUN`
text describes its initial source-only checkpoint, not current verification evidence.
`tests/test_batch06_taifex_callers.py` exercises the actual importer `main` and collector
`main`/atomic writer with synthetic files and injected transports: bounded binary reads,
exact raw-byte hashes, UNVERIFIED manual origin, all-or-nothing refusals, final serialized
output budgets and preservation of non-Delta rows. Private-copy mutation checks are in
`tests/test_batch06_mutations.py`. These are not real dataset-11321 compatibility, rights,
transport-origin authentication or live collection proofs.

### O10 local collection task (authorized 2026-10-11; not registered yet, rollout v10)

`scripts/task-templates/taifex-options-eod.disabled.xml` stays an inert, disabled **template** with placeholders.
`scripts/register_taifex_options_eod_task.ps1` (library `scripts/taifex_options_eod_task.ps1`) is the only entrypoint
that renders it, and it is opt-in: no installer or default refresh calls it, and the operator-authorized rollout runs it
once. It registers `InvestorIntelligence-TaifexOptionsEod`: one daily local trigger (default 17:30), interactive token,
least privilege, no password, five minute limit, `StartWhenAvailable` left at the template's false (a run missed while the host was off is skipped, so no catch-up lands in the 07:45-08:30 window; the next day's run replaces the file). Its single action is
`<python> -I -B -X utf8 <SourceRoot>/scripts/fetch_public_source_observations.py --fetch --source taifex_options_eod --output
<DataRoot>/taifex-options-eod-latest.json`, with `DataRoot` = `%LOCALAPPDATA%\InvestorIntelligence\local-observations\taifex`
(outside the installed payload; each run atomically replaces the file, so only the latest observation set is kept).

- Registration refuses when any `__PLACEHOLDER__` remains, a path is relative, contains `..`, quotes or placeholders, the
  Python or collector file is missing, the output is not a `.json` under `DataRoot`, `DataRoot` and the installed payload
  contain one another, or any output path segment is named like Production/publication storage (`production`, `kv`,
  `public`, `sealed`, `cloud`, `_workspace`, ...). Times from 07:45 to 08:30 are refused (08:00 briefing/Worker window).
- It is idempotent (`-Force` re-registration of an identical definition), captures the previous definition first and
  restores it (or unregisters a fresh task) when the readback of action, arguments, working directory, trigger or
  enabled flags differs. `-Unregister` removes only this task and keeps collected files; `-ValidateOnly` renders and checks
  without touching the scheduler.
- Time choice: the regular session closes 13:45 and the TAIFEX daily options report attributes the after-hours session
  (15:00 to 05:00 next day) to the next trade date. Neither the TAIFEX report page nor data.gov.tw dataset 11320 (update
  frequency "every 1 day") states an exact publication time; the only official timing found (a 2021 TAIFEX rule for the
  institutional statistics, not re-verified) puts open-interest figures at about 15:00. 17:30 is therefore a conservative
  margin of two and a half hours, not an official guarantee. Every item carries its own `trade_date`, and a run that finds
  an earlier date records that date; nothing is inferred from the run time.
- Rights: dataset 11320 is under 政府資料開放授權條款-第1版 (free, attribution), reviewed in
  [PUBLIC_SOURCE_RIGHTS_REVIEW_20260909](PUBLIC_SOURCE_RIGHTS_REVIEW_20260909.md). The task selects only `taifex_options_eod`
  (dataset 11320); dataset 11321 (Delta) is not collected by any schedule and its rights remain an open item.
- Honest limits: collection only. Output is `publication_eligible=false`, `line_quote_eligible=false`,
  `executable_quote=false`; nothing reads the file for publication, KV or LINE. The task runs only while the owning user is
  logged on. `tests/test_taifex_task_registration.py` drives the real registration code over a fake scheduler; it is not
  native Task Scheduler proof, which is the rollout readback (task exists with the expected action/trigger, first run result).
  `tests/test_batch06_taifex_task.py` still fake-runs the real collector/writer in process.

### O10 activation plan (PLAN ONLY: registers nothing, enables nothing)

This section is a source-bound plan that a Sonnet 5.5 review and then the operator's explicit current-session authorization must clear before anything is registered. Registering or enabling the task changes the installed runtime's schedules and is a separate authorization; the operator gave it on 2026-10-11 for rollout v10 (`state/STATUS.md`), which has not run, so nothing is registered. `scripts/register_taifex_options_eod_task.ps1` (O10 local collection task above) renders the template and registers the task enabled in one step; the values below are its defaults unless the operator passes `-DailyTime` or `-DataRoot`. Collected rows stay local (`publication_eligible=false`); while public display is blocked by O11/O12 ([scope decision, design only](PUBLIC_EOD_OPTIONS_SCOPE_DECISION.md)) the operator may reasonably decline activation.

O10 template arguments (byte-equal to the XML): `-I -B -X utf8 "__SOURCE_ROOT__/scripts/fetch_public_source_observations.py" --fetch --source taifex_options_eod --output "__LOCAL_OUTPUT__"`

`tests/test_batch06_taifex_task.py` compares the line above with the template's `Arguments` text. `<LOCALAPPDATA>` below stands for the operator profile's local application data directory; the registered copy must contain the literal absolute path with forward slashes, because Task Scheduler does not reliably expand user environment variables in `Arguments`.

| Template placeholder | Resolved value (plan) | Source of the value |
| --- | --- | --- |
| `__PROJECT_PYTHON__` (`Command`) | `<LOCALAPPDATA>/InvestorIntelligence/Runtime/Python-3.12.10/python.exe` | `python_executable` of the installed `install-state.json`; the file existed when read on 2026-10-11 |
| `__SOURCE_ROOT__` (`Arguments`, `WorkingDirectory`) | `<LOCALAPPDATA>/InvestorIntelligence/V213Runtime` | Installed source root that holds `scripts/fetch_public_source_observations.py`; the script puts its own directory on `sys.path`, so `-I` works |
| `__LOCAL_OUTPUT__` | `<LOCALAPPDATA>/InvestorIntelligence/local-observations/taifex/taifex-options-eod-latest.json` (registrar default `DataRoot`) | Outside the repository, the installed payload (`V213Runtime`), the workspace and any Production or public storage; the registrar refuses a `DataRoot` that contains or lies inside the installed payload, and the collector creates the parent directory |
| `__LOCAL_START_BOUNDARY__` | `<registration day>T17:30:00` local time, daily (registrar default `-DailyTime 17:30`) | After the 13:45 Taiwan day-session close, clear of the 07:20/20:20 local refresh tasks, the 08:00 `InvestorDailyBriefing` window and the 21:00 schedule; the operator may pass another `-DailyTime` (07:45 to 08:30 is refused) |

Fixed by the template and unchanged: principal `Collector` with `InteractiveToken` and `LeastPrivilege` and no `UserId` (the task registers under the operator's own account and runs only while that account is logged on), `MultipleInstancesPolicy` `IgnoreNew`, `StartWhenAvailable` false (a missed run is skipped, not replayed), `WakeToRun` false, `ExecutionTimeLimit` `PT5M`, one `Exec` action. The only network access is the public HTTPS read of the TAIFEX open-data host named in `scripts/provider_runtime_hook.py`; no credential is used.

One fixed output file means each run replaces the previous one (the writer is a same-directory temporary file plus `os.replace`; a failed run leaves the previous file intact). History is not kept by the task; keeping any run requires a separate reviewed step. This limitation is part of the plan, not hidden.

**Pre-checks (all must hold, otherwise stop).**

1. Installed collector equals source. Observed 2026-10-11: the installed `V213Runtime/scripts/fetch_public_source_observations.py` has SHA-256 `f574c85bd2914ac248fee210e29a896a039299c84dde48443cdafd4e7cf962f9`, the committed source at `f7d6353` has `6af912a11384d5e2045b8ebd2ac263fa967b29ef552a2ad00a3e1892711c78c9`, and the installed `LOCAL-SOURCE-REFS.json` names source commit `e0492613f6d1` exported 2026-09-28. The check therefore FAILS today. Activation first needs the logged installed-payload sync (back up the old bytes to `_archive/instruction-sync-<UTC>/` with a RECEIPT, then copy the committed source) and a hash comparison of the collector's whole import closure (the collector, `scripts/adapters/*`, `scripts/taifex_contract.py`, `scripts/source_observation.py` and whatever the then-current imports name), listed from the source at plan time.
2. The Python path and source root above exist; `--output` parent is outside the repository, the installed tree and Production storage.
3. No `InvestorDailyBriefing`, refresh or rollout window overlaps the trigger; no registered task of the same name exists.
4. The XML registered is the registrar's render of the template: only the four placeholders replaced (it refuses any that remain) and both Enabled values set true in the same authorized step (registration and enabling are one step; the readback refuses a disabled task or trigger); its action `Arguments` equal the line above after substitution.

**Post-run verification (first manual run, then each scheduled run).** Task Scheduler last result 0; stdout summary line shows `publication_eligible` false; the output file parses as JSON with top-level `status` `OK`, a source row (health row) for `taifex_options_eod` with status OK and zero warnings, `publication_eligible` false at the top level, `item_count` greater than zero and of the same order as the first manual run (12,488 rows were observed for 2026-09-09; the exact count varies by date and is not a pass bound), every item with `line_quote_eligible` false, `executable_quote` false and `quote_time` null, a single `trade_date` inside the collector's seven-calendar-day ceiling, and no other source or Production path touched. A failure or deviation is recorded and the task is disabled; there is no retry loop.

**Rollback.** Disable then unregister the task (export its XML first as a receipt); leave the output directory in place as evidence; if the installed-payload sync was part of the activation, restore the backed-up preimage from `_archive/instruction-sync-<UTC>/` through the same logged sync. Nothing else (Worker, KV, LINE, other tasks) is touched, so nothing else needs rolling back.

**Authorization list (each explicit, current session, operator).** (1) The installed-payload sync, if the pre-check fails. (2) Registering and enabling the task with the resolved values above and the exact trigger time (one registrar step). (3) The first manual run. The operator's 2026-10-11 decision covers O10 activation through the installer or a logged installed-payload change within rollout v10 (`state/STATUS.md`); none of these steps has run. Not covered: any Production Worker, KV, storage or schedule change, any LINE delivery, adding the feed to default sources, and any public display. The paragraph for `docs/OPERATOR_RUNBOOK.md` is a separate documentation request.

Public EOD option display remains BLOCKED by the separate O12 rights/scope contract:
only delayed quotes and metadata-only coverage have public contracts, neither permits
EOD/Delta values. All public admissions remain NONE. JP/HK/EU/AU adapter work (O5) waits
for a pinned official wire specification from a separate bounded research task; no
provider format is invented and no adapter or rights decision is added here.

The public-EOD options (keep local-only versus a date-only reference surface) are laid out for the operator in [PUBLIC_EOD_OPTIONS_SCOPE_DECISION](PUBLIC_EOD_OPTIONS_SCOPE_DECISION.md); it is design only, grants no rights or admission and changes no code or catalog.

## Nasdaq Nordic contract terms (V13, Stockholm listings such as SIVE.ST)

The exchange chain read by `scripts/build_market_quotes_options.py` (`NORDIC_SOURCE`) sends `contractSize` "100" and `currency` "" on
every option row (retained 2026-10-17: 634 rows; evidence and hashes in the workspace receipt folder `v13-evidence-a43bef58`). Nasdaq's
contract specification for stock options on Swedish shares states "Contract Size One hundred shares per contract" and that the
premium "Shall be expressed in Swedish Kronor or Euro depending on the underlying shares". Rule:

- A blank contract currency (exactly "" or an absent key) follows the underlying, and only after the spot quote and the listing
  search both confirm SEK; it is never typed SEK on its own (`_typed_currency("")` stays `UNKNOWN`).
- `null`, whitespace, lowercase, padded, numeric, boolean or container values stay `UNKNOWN` (「合約單位或幣別來源未確認」); an explicit
  other currency stays a conflict; a size other than "100" stays nonstandard; quotes must still be real two-sided bid/ask.
- Re-calculated (adjusted) contracts are not modelled: a size other than "100" is refused rather than rescaled.

## Nasdaq US option chain (V19, the labelled Yahoo fallback)

`nasdaq_us_options` in `scripts/build_market_quotes_options.py` reads the Nasdaq quote-page API
(`api.nasdaq.com/api/quote/{symbol}/option-chain`) only for a cycle Yahoo could not read (no expiry list, a failed chain). Retained shape
(2026-10-19, HTTP 200, 4.5 KB): `expirygroup` header rows, then strike rows with `c_Bid`, `c_Ask`, `c_Openinterest` ("--" when unknown);
`table.asOf` is null and `data.lastTrade` carries the only date, "LAST TRADE: $343.46 (AS OF OCT 15, 2026)", four days before the request.
Rule:

- The cycle is shown only when the "AS OF" date is within 4 calendar days of the run date; an absent or unparsable date, or an older one,
  is unavailable (health `STALE_ASOF`). A bot challenge or non-JSON body is `READ_ERROR`; nothing is retried.
- No implied volatility or delta is published: the delta is Black-Scholes from the strike's own bid/ask mid (`QUOTE_IMPLIED`).
- No merge with Yahoo, no averaging, no second display; a cycle Yahoo read without a qualifying strike keeps Yahoo's reason.
- Rights: an operator decision, not a licence (2026-10-19, [PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW](PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW.md));
  the cycle claims the catalog identity `nasdaq_public_option_chain` with the label `operator_accepted_unlicensed`, quote basis `delayed`,
  and is never carried forward.

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

One writer integrates. Small-model reviewers, if available, receive only a file list and bounded read-only question (catalog rights, caller graph, or test gaps). Higher-capability review is reserved for privacy/publication invariants and final diffs. No reviewer tools were available in the harness discovery of this 2026-09 checkpoint (commit `ead246c`), so no delegated model execution or token savings were claimed; current review roles are recorded in `state/STATUS.md` (Identity / roles) and the current GO. Do not switch the existing inference Router or install another agent to simulate delegation.
