# Dataset-specific source review — 2026-09-09

Scope: public data access and permitted roles, not Production activation or legal advice. Read original dataset terms rather than extrapolating rights from a homepage, search snippet, API availability or another dataset.

## Reviewed usable open datasets

| Dataset | Official evidence | Permitted role | Still not established |
| --- | --- | --- | --- |
| TAIFEX daily options,11320 | https://data.gov.tw/dataset/11320 | Daily/EOD Taiwan option observations through the linked TAIFEX OpenAPI, with attribution | Real-time execution quotes, US stock options, general website scraping, production adapter acceptance |
| TWSE listed issuer profiles,18419 | https://data.gov.tw/dataset/18419 | Exchange-wide company identity/industry discovery via `/opendata/t187ap03_L` | Company orders, scarcity, valuation, investability or ranking |
| TPEx issuer profiles,25036 | https://data.gov.tw/dataset/25036 | Exchange-wide company identity/industry discovery via `/mopsfin_t187ap03_O` | Independent confirmation of issuer-authored filings, company thesis or ranking |

Direct dataset pages retrieved on the review date explicitly state `政府資料開放授權條款-第1版` and `免費`. Dataset11320 states `更新頻率 每1日` and links `https://openapi.taifex.com.tw/swagger.json`. TWSE/TPEx official Swagger descriptions were also retrieved and matched the exact company-directory endpoints before fetching.

[Open Government Data License v1](https://data.gov.tw/license), section2(1):

> 授權使用者不限目的、時間及地域、非專屬、不可撤回、免授權金進行利用，利用之方式包括重製、散布、公開傳輸

Section3(2):

> 應以符合附件所示「顯名聲明」要求之方式，明確標示原資料提供機關之相關聲明；未盡顯名標示義務者，視為自始未取得開放資料之授權。

Retain provider, dataset name/version where supplied, year, dataset URL and license link; downstream presentation must also retain attribution. The license does not guarantee data accuracy or imply government endorsement. This dataset-specific grant does not authorize unrelated TAIFEX commercial feeds.

## Non-admitted alternatives

- [Alpaca historical option documentation](https://docs.alpaca.markets/us/docs/historical-option-data), directly retrieved: indicative quotes are derivatives, not actual OPRA quotes; trades are derivatives delayed15 minutes. This is not proof of redistribution permission or executable quotes. No account/token/paid service enabled.
- Nasdaq terms direct retrieval timed out. Search results about European or index-data policies are not evidence of US option-chain permission. Keep its pending state; do not mark review completed or access prohibited merely because retrieval failed.
- Previously prohibited/pending sources remain unchanged. Seven rights reviews remain pending; reviewed public access1 does not mean fully eligible runtime providers1. Actual gate still reports fully eligible0, runtime enabled0 and production provider selected false.

## Actual candidate discovery, not finished research

The existing `fetch_public_source_observations.py` caller now supports both issuer directories, through its existing bounded, no-redirect, no-cookie, no-credential, verified-TLS transport. No second scheduler/workflow or scoring algorithm was introduced.

Live command:

```powershell
python scripts/fetch_public_source_observations.py --fetch --source twse_issuer_directory --source tpex_issuer_directory --output <local-observation-file>
```

Actual pinned Python3.12.10 run:1094 TWSE +890 TPEx =1984 issuer records, both sources OK, zero parser warnings; source directory dates2026-09-08. All source industries enter discovery without an AI seed list, sector preference, owner watchlist or altered score. Closed projection excludes contact/address/management fields. Raw responses are hashed in memory, not stored as contact-rich archives.

Each candidate is `DISCOVERED_EVIDENCE_AND_SCORING_PENDING`, `PRIMARY_ONLY`, `publication_eligible=false`. This is Taiwan discovery coverage, not a rebuilt global ranked Top20 or an attributed Serenity view. Company evidence, constraint/financing analysis, existing scoring and sealed publication are still required. Retrieval date does not replace source date. Stale/future/mixed-date/duplicate/malformed directories fail closed, and source failures remain visible.

## 2026-09-10 — exact World Bank USA real-GDP series, conditional reuse review

This is a dataset-specific review for the **existing** USA `NY.GDP.MKTP.KD.ZG` caller, not another provider activation, legal opinion or LINE publication grant.

Direct public HTTP200 evidence, without credentials/cookies/proxy/redirect following:

- [Exact USA indicator metadata](https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG?locations=US) explicitly shows **“GDP growth (annual %) - United States”** and **“CC BY-4.0”**. Providers shown: country official statistics (national statistical organizations/central banks), OECD National Accounts data files, and World Bank staff estimates. Raw page SHA256 `1600ae8d50c0bc2e8228b524f3fa787e443768d7971f70147fbc7babca9a2725`.
- [Summary terms](https://data.worldbank.org/summary-terms-of-use) permits copying/distributing/adapting/displaying data at no cost unless indicator metadata says otherwise. This summary is not the controlling agreement; raw SHA256 `b5a5abcd3eafb8f547282dc13a42f23937fde474c9721051532706fb9904f5b3`.
- [Controlling dataset terms](https://www.worldbank.org/ext/en/legal/terms-conditions/datasets), page dated2018-03-23: default CC BY4.0 plus World Bank additions; dataset terms prevail over conflicting general terms. They permit API use, require World Bank/dataset/data-provider credit and passing on acknowledgment requirements, preserve third-party exceptions, prohibit endorsement/affiliation claims, disclaim warranties/ownership guarantees and add mediation/arbitration requirements.
- [General site/API terms](https://www.worldbank.org/ext/en/legal/terms-conditions), notice dated2025-07-25, and [CC BY4.0 legal code](https://creativecommons.org/licenses/by/4.0/legalcode.en) were also read. The general terms expressly recognize dataset-specific terms but include site-use, API-volume, downstream-agreement and other conditions. CC requires attribution, license/source links and indication of changes; no implied endorsement or additional restrictions on licensed rights.

**Decision:** the exact metadata supports a stated royalty-free reuse license, subject to its actual conditions; it does **not** prove compliance of this project's public application. Downstream terms/acknowledgment, applicable site/API conditions, third-party exceptions and periodic review remain open for public LINE delivery. Do not call every World Bank webpage CC-licensed, silently resolve legal ambiguity, or infer rights for company financials, prices/options, other indicators or providers. No user agreement/account/billing change or public distribution was performed.

The existing caller now carries credit, metadata/license/terms links, selection/no-value-adjustment notice and no-endorsement/no-warranty notice in its **unqualified** context. This is not a rights-status or eligibility switch. World Bank/OECD/national accounts within this compilation count as one lineage, not independent company-thesis corroboration.

Evidence under `_workspace/audit-runtime/world-bank-context-a/`: raw public pages, text extraction and bounded receipts. The initial1191-byte API contract probe binds SHA256 `65ad63f75bb71171a1869bf7843b21dea9b44e4000ea818e86bd200a4bd96b0d`, source2/page1/14pages/66rows and dataset lastupdated2026-07-13. Its exact HTTP acquisition clock was **not captured**; do not infer one from file mtime or later observation. A separate actual engine CLI run acquired the same body SHA at **2026-09-10T20:03:22Z** through the existing bounded transport: one real WDI GET with20 synthetic company inputs; federation reused that receipt without HTTP or restamping (`live-wdi-cli-result.json`). This is one live macro source, not a live20-company run; the initial curl probe still has no exact acquisition clock. A later range-before-float guard correction was checked through the actual Serenity progress CLI using that retained cache, HTTP0 (`final-retained-replay.json`); this does not rebind the original live receipt to later source bytes or qualify a fresh final-source release. No complete history/latest-release, stock/option quote or three-product delivery qualification follows from HTTP200.

## 2026-09-11 — exact 2025 GAAP taxonomy definition sources, not issuer-data rights

Reviewed only the three existing debt concepts, not a new provider catalog or runtime source activation. Four direct, bounded, credential-free GETs returned200: the [2025 elements directory](https://xbrl.fasb.org/us-gaap/2025/elts/), its `us-gaap-2025.xsd` and `us-gaap-doc-2025.xml`, and the [Authorized Uses notice](https://xbrl.fasb.org/terms/TaxonomiesTermsConditions.html) linked by the schema's copyright comment. No redirects, retries, SEC GETs or contact-setting reads. Original bytes, acquisition receipts and full notice remain in `_workspace/audit-runtime/debt-definition-review-a/`; no taxonomy files or copied definitions were added to the application/package.

The served notice permits royalty-free public use for GAAP financial reporting and unchanged incorporation into works that explain or assist use/implementation of the taxonomy. Its permission to copy/publish/distribute such works is conditional on including the **Authorized Uses notice on their first page**. A source URL, small footer, hash or generic attribution is not evidence that this condition is met. It prohibits taxonomy modification, including removing copyright notices, apart from the specified translation exception or prior written FAF consent.

Third-party content remains subject to its own notices and XBRL International / XBRL US intellectual-property policies. The notice also points to separate SRT terms; it includes warranty and liability disclaimers. Those imported/third-party policy documents were not fetched or fully reviewed here. No claim of complete downstream rights, license compliance or permission to redistribute issuer filings/market data follows. The current notice contains2026 copyright years while the selected taxonomy files contain2025 notices: this is evidence of the notice served **at acquisition**, not proof of its historical2025 wording.

**Decision:** the notice supports a conditional royalty-free permitted-work route, not unconditional open-data redistribution or general website scraping permission. Before any public taxonomy incorporation, resolve the applicable scope, first-page notice, unmodified content and imported/third-party conditions in the actual rendered/downloadable artifact. Do not mark the existing financial products, LINE service, issuer sources, WDI or any quotation provider eligible from this review. No paid license, account, billing, agreement acceptance or runtime setting was activated.

SHA256: schema `4639263ec38aaa5d531cb7d0afb33f9582c2d602fb4623d4921e47e365b6ac9f`; documentation `27f1d4ba06b0dcb0c91225db2ac746d5adefc167518fa3948abbdfb944dab019`; notice `26d35a4ffd5129c4e75bd11ebb20ef3b27bdd93a3df41bac8c69874727c3434f`. Raw notice declares Windows-1252; the separate readable extraction decodes that charset without replacing or rebinding the original bytes. Semantic findings and the still-unloaded issuer calculation/definition network are recorded in the [detailed-report contract](DETAILED_REPORT_CONTRACT.md).

## 2026-09-25 — Wave 1 official public feeds

Scope: rights for the eight feeds the existing collector already fetches, reviewed from the original pages on 2026-09-25. Registry entries: `config/sources/official-public-feeds.json`.

| Feed | Official evidence | Licence / terms | Attribution |
| --- | --- | --- | --- |
| `twse_equity_eod` | https://data.gov.tw/dataset/11549 | 政府資料開放授權條款-第1版; 免費; 每1日 | Provider and dataset, licence link |
| `tpex_equity_eod` | https://data.gov.tw/dataset/11371 | 政府資料開放授權條款-第1版; 免費; 每1日 | Provider and dataset, licence link |
| `twse_issuer_directory`, `tpex_issuer_directory`, `taifex_options_eod` | datasets 18419, 25036, 11320 (reviewed 2026-09-09 above) | 政府資料開放授權條款-第1版 | As above |
| `federal_reserve_news` | https://www.federalreserve.gov/disclaimer.htm (updated 2024-08-02) | "Unless otherwise indicated, information on Board's website is in the public domain and may be copied and distributed without permission." Third-party material excluded. | "Please cite to the Board as the source" |
| `ecb_news` | https://www.ecb.europa.eu/services/disclaimer/html/index.en.html | Reuse permitted when reproduced accurately with the ECB cited; modifications must be stated; authored papers excluded | Cite the ECB |
| `sec_news` | https://www.sec.gov/privacy (updated 2023-11-29); https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data | "Information presented on sec.gov is considered public information and may be copied or further distributed ... without the SEC's permission"; fair access at most 10 requests per second with a declared User-Agent contact | Attribution encouraged |

Decision: rights approved for internal factual research and brief quotation with attribution. Requests to `www.sec.gov` now send the configured SEC contact identity and fail closed without it. The canary (`_workspace/audit-runtime/source-activation-wave1-20260925/`) fetched the feeds, but the claim-evidence acquisition factory rejects bulk datasets (100-record cap) and news leads (not claim observations), so the entries stop at `ADAPTER_CONTRACT_VALIDATED`, not `RUNTIME_ENABLED`. This review is not legal advice and does not authorize redistribution beyond the stated terms.

## 2026-09-25 — Industry rotation sources

- **BLS Producer Price Index, public API v1** (`https://api.bls.gov/publicAPI/v1/timeseries/data/`): U.S. federal statistics, public domain (17 U.S.C. 105); version 1 needs no key or registration (daily query limit respected: one run per ~20 hours, ≤25 series per request). Only a generic User-Agent is sent, no personal data.
- **SEC EDGAR XBRL frames and company listing by SIC**: public filings data under SEC Fair Access (declared contact, ≤4 requests/second with back-off; 403/429 stop the run).
- **Not used:** FRED CSV downloads (terms limit use to personal, non-commercial and prohibit automated extraction; the original publishers are used instead) and the Census Economic Indicators API (now requires a registered key).
