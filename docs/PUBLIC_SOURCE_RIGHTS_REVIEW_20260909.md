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
