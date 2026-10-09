# Public source coverage / 公開資料來源覆蓋

This is a development audit, not a claim that all financial data is diversified or Production-qualified. One shared adapter interface, provenance validator and explicit local collector are used; staged adapters do not enter the reviewed runtime registry automatically.

## Role and availability matrix

| Data role | Paths | Actual scope |
| --- | --- | --- |
| Official announcements/news leads | Federal Reserve, SEC, ECB RSS | New fixed-endpoint collector and bounded parsers. All three fetched successfully on hash-verified CPython3.12.10 with system trust plus the locked certifi bundle. Headline metadata is not independently verified company-order evidence or general breaking-news coverage. |
| Equity end-of-day observations | TWSE listed-security OpenAPI; TPEx daily-close OpenAPI | New parsers preserve venue, TWD, ROC trade date, unadjusted OHLC, missing prices and share-volume units. Both live parsers passed on the supported pinned runtime; earlier TLS failures remain preserved as historical probes. These are different venues/instruments, not two independent quotes for one instrument. Includes securities other than common stocks. |
| US/other equity prices | Existing Yahoo paths | New Taiwan sources do not solve US quote concentration. Licensed independent same-contract/same-instrument corroboration remains pending. |
| Issuer fundamentals/filings | Existing SEC EDGAR parser and evidence path | Primary filings are distinct from regulatory press-release headlines. A filing must retain accession, filing date, period and currency/unit. No changed fundamental scoring or invented facts. |
| Macro/identity/listings | Existing World Bank, SEC and staged ECB/GLEIF/Nasdaq/SDMX adapters | Existing review/admission gates remain unchanged. A listed parser or catalog entry is not live coverage; identity/macro references do not prove issuer orders. |
| Option observations | Existing Yahoo/local private IBKR; new TAIFEX EOD and Alpaca indicative import adapters | See [options review](OPTIONS_SOURCE_REVIEW.md). Imports are not automated live feeds. No new public LINE quote provider is eligible; broker data stays private. |

Current local development evidence: [pinned-runtime direct-CLI proof](../state/public-source-pinned-runtime-proof.json). The [earlier failed probe](../state/public-source-development-proof.json) remains unchanged and is not relabelled PASS. `record_count` is not the number of usable prices: TPEx records without a close are explicitly `MISSING_CLOSE`, not zero-price observations. No TLS verification, freshness or publication gate was disabled.

## Local collection

Use the existing hash-verified CPython **3.12.10** runtime configured as `PROJECT_PYTHON`, with the committed hash-locked dependencies installed and `pip check` passed. Do not use an arbitrary system `python`: the original failing probes used3.13.15, whose stricter default certificate checks rejected the TWSE chain. The collector does not clear verification flags to make that interpreter pass. Direct CLI now works with embedded Python from an unrelated working directory without PYTHONPATH injection.

```powershell
& $env:PROJECT_PYTHON scripts/fetch_public_source_observations.py --fetch --output data/cache/public_source_observations.json
# Or a bounded subset:
& $env:PROJECT_PYTHON scripts/fetch_public_source_observations.py --fetch --source federal_reserve_news --source sec_news --output data/cache/news_observations.json
& $env:PROJECT_PYTHON scripts/fetch_public_source_observations.py --fetch --source twse_equity_eod --source tpex_equity_eod --output data/cache/equity_observations.json
```

No implicit network fetch: `--fetch` is mandatory. Fixed HTTPS endpoints only, explicit system-plus-certifi CA trust with CERT_REQUIRED/hostname verification and unchanged default verify flags, no redirects, cookies, credentials, environment proxy credentials, paid fallback, concurrency or retries. Requests have a 20-second timeout and bounded read; each chosen source is attempted once per invocation. Do not repeatedly poll this development command. XML entities/DTDs, oversized bodies, bad dates/URLs, duplicate rows and inconsistent OHLC fail closed. Per-source failures and per-row warnings persist locally; stdout prints bounded counts rather than entire rejected-row arrays.

Every result is `LOCAL_PUBLIC_SOURCE_OBSERVATIONS`, `publication_eligible=false`. The command is not wired to cloud publication, owner watchlists, scheduled jobs or LINE. Nonzero exit indicates partial/total failure. Successful network/schema checks do not establish completeness, real-time accuracy, redistribution rights or a safe trade. Publication/admission still requires review and actual user-facing integration tests.

## Official references and rights boundary

- Fed feed index: https://www.federalreserve.gov/feeds/feeds.htm ; terms: https://www.federalreserve.gov/disclaimer.htm . Board-origin materials are generally public domain with attribution, excluding separately credited material. Collector retains headline/link metadata, not images or article bodies.
- SEC feed index: https://www.sec.gov/about/rss-feeds ; announcements: https://www.sec.gov/newsroom/press-releases . Public RSS access does not admit headlines as verified issuer fundamentals.
- ECB RSS: https://www.ecb.europa.eu/home/html/rss.en.html . Successful retrieval by a research tool is not a passing run of the installed Python collector.
- TWSE API: https://openapi.twse.com.tw/ ; daily endpoint `/v1/exchangeReport/STOCK_DAY_ALL`.
- TPEx API: https://www.tpex.org.tw/openapi/ ; endpoint `/openapi/v1/tpex_mainboard_daily_close_quotes`.
- Public redistribution review for the new collector remains incomplete. Do not infer a blanket market-data license from an accessible API or RSS page.

## Shared defects corrected

Registry security flags require actual booleans and integer limits cannot silently truncate. Nonstandard HTTPS ports and credential-bearing URLs fail without echoing credentials. A subdomain admission cannot admit its parent. Evidence rejects nonfinite payloads, naive clocks and stacked future-time tolerances. Shared JSON parsing rejects duplicate fields/nonfinite constants. Duplicate observations do not alter a set hash or increase independent corroboration.

## Public broker, asset-manager and media candidates — 2026-09-09

Added15 **disabled discovery candidates** using the existing authoritative catalog loader, planner and gates, not a second collector or publication workflow. Explicit candidate manifest `config/authoritative-source-catalog.research-candidate.json` has116 entries; the reviewed default remains101. Candidate inventory is neither116 working feeds nor116 independent witnesses. Fragment: `config/authoritative-sources/public-research-candidates.json`. All new records are T3 / discovery_only / metadata_only, without adapters or credentials; access, redistribution, article schema and runtime gates remain unqualified.

| Candidate group | Publishers | Permitted research role after admission |
| --- | --- | --- |
| Broker/bank public research | Goldman Sachs, J.P. Morgan, Morgan Stanley, Charles Schwab, Fidelity, UBS | Dated analyst views, macro/industry hypotheses and education. Not broker accounts, customer-only reports, executed trades or authoritative option quotes. |
| Investment-manager public research | BlackRock Investment Institute, Vanguard, PIMCO | Dated allocation, macro, rates and credit views; retain assumptions, horizon, revisions and disclosures. Not company-order proof or guaranteed returns. |
| International market reporting | Reuters, Bloomberg, Financial Times, Wall Street Journal, CNBC, Morningstar | Publicly accessible original reporting and research leads only. Paid terminals, Pro/premium reports, subscriber feeds and full-article republication excluded. |

Actual public tool checks (`web_search` mttuyika2fxi99; `fetch_content` mttv0ik8mvpllv):

- Goldman sample `https://www.goldmansachs.com/insights/outlooks/2026-outlooks`: HTTP403, retained as failed. Morgan Stanley sample `https://www.morganstanley.com/insights/articles/investment-outlook-shaping-markets-2026`: aborted, not verified.
- J.P. Morgan `https://www.jpmorgan.com/insights/global-research/outlook/mid-year-outlook`: readable page returned. Fidelity `https://www.fidelity.com/learning-center/viewpoints`, Vanguard `https://corporate.vanguard.com/vemo`, PIMCO `https://www.pimco.com/us/en/insights`: landing-page text returned. This is not four qualified article feeds or proof of financial claims.
- Schwab/BlackRock were search-discovered, not directly checked. UBS search returned an ambiguous nested URL; only the publisher root is retained for discovery, not a fabricated article endpoint. The six international reporting sites are proposed candidates, not newly fetched or licensed feeds.

Six sample fetches, four readable returns, one403 and one aborted request. No paid fallback, authentication/paywall bypass, cookies or account data used. Search-synthesized forecasts were not promoted to verified observations.

Pair by issuer/security identity, claim, unit/currency, period and source role. A broker quoting an issuer or official statistic does not become another independent witness to that fact. Syndication, shared press releases and affiliated brands require lineage review; different domains alone do not prove independence. Original analyst views remain attributed views, not Serenity's views. Retain conflicts and contrary evidence; do not average incompatible targets or fill undisclosed orders from analyst conjecture.

Inspect explicitly with `python scripts/authoritative_source_catalog.py --manifest config/authoritative-source-catalog.research-candidate.json`. Candidate/base policies and all original source records are checked for equality in tests; only the added fragment differs.

**Release boundary:** initially appending the fragment to the default manifest caused six actual engine regressions (`Catalog count changed: 116 != 101`). Those failures remain in `broker-source-catalog-python.log`. The default was restored unchanged and the expansion isolated through the existing explicit manifest parameter. Existing activation validators still pin the reviewed101-source plan; they were NOT relaxed to accept the expanded candidate catalog. A future runtime plan needs versioned review/recertification; do not publish a116-source plan under the old101-source contract or silently restamp the old plan. No new candidate is runtime-enabled or LINE quote-eligible.

## 未完成事項／Remaining

- ECB／TWSE 已在核准 Python3.12.10＋鎖定 certifi 的直接 CLI 通過；既有系統 Python3.13.15 的失敗不改寫。全球憑證儲存區未變更、未降低 verify flags、不得使用 `verify=false`。
- GitHub／Windows／安裝發布驗收以 [目前狀態](../state/STATUS.md) 為準；不沿用歷史 runner 清單推斷現況。本機通過不是完整發布驗收。
- 股票與期權的美股同標的多源報價、新聞跨出版機構去重／主張核實，以及新來源公開再散布授權仍未完成。
- 新增的 RSS 是官方公告，不代表已覆蓋 Reuters/AP 等新聞，亦不代表所有全球市場或所有資料類型已多元化。
- PR39 的證據錯誤與 Windows／live／封裝資格仍需獨立解決；目前缺陷紀錄見 STATUS，不以本分支通過代替。
