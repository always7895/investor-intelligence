# Data-driven industry rotation v1 / 資料驅動產業輪替

[Docs index](README.md) · [Current state](../state/STATUS.md)

Operator rules (2026-09-25): macro industry analysis must rotate with the market, nothing hand-written; every value needs a source; data stay diverse and keep updating after the project is finished.

## What is computed

`scripts/industry_rotation.py` with `config/industry-rotation-v1.json`:

| Signal | Source (independence family) | Rule |
| --- | --- | --- |
| PRICE | BLS Producer Price Index industry series, public API v1 (`bls_ppi`) | Latest month vs the same month a year earlier; ≥ +3% tightening, ≤ −3% relief |
| BACKLOG | SEC XBRL frames `RevenueRemainingPerformanceObligation`, summed over member issuers (`sec_xbrl_issuers`) | ≥ +10% tightening, ≤ −10% relief |
| INVENTORY_BUILD | SEC XBRL frames `InventoryNet` vs revenue (`sec_xbrl_inventory`) | Inventory growth ≥ 10 points above revenue growth is relief |
| Revenue growth | SEC XBRL frames revenue tags | Card growth rate and strength only |
| SUPPLIER_REVENUE | TWSE (listed) and TPEx (OTC) OpenAPI monthly revenue summed by industry category (`taiwan_monthly_revenue`) | Same month a year earlier; ≥ +20% tightening, ≤ −10% relief; a faster read of demand through the Taiwan supply chain |

Industry membership is read from EDGAR's company listing by SIC code (cached 30 days; empty listings are never cached). A metric with fewer than three matched issuers is treated as missing. `scripts/thesis_phase.py` (industry scope) turns the signals into a phase; a published strength (price, backlog, revenue and Taiwan supplier revenue growth, minus an inventory-build penalty) orders industries inside a phase. TOP5 admission needs phase DISCOVERY or EARLY_VALIDATION, revenue growth and strength ≥ 15; fewer than five is published as an honest shortfall.

The configuration lists official classifications only (SIC codes and PPI series per industry). Industry names are labels for those classifications; every sentence on cards and deep analyses is generated from the computed numbers with period, source and URL, and missing data are stated, not filled. Catalysts are limited to data-review dates; no forecast, probability or price target is produced.

## Refresh and publication

- `scripts/run_daily_data_refresh.ps1` decrypts the SEC Fair Access contact from the user's DPAPI file into the process only, runs the refresh at most every 20 hours and keeps the last good file on failure.
- The hourly `run_production_sealed_refresh.ps1` calls it before publishing (non-fatal) and `publish_sealed_snapshot.py` builds the sealed TOP5 overview from `data/cache/industry_rotation_latest.json` (maximum age 45 days). Industry cards and deep analyses are embedded in that overview, and the Worker reads them from it.
- The former hand-written industry rows remain only as a synthetic contract fixture for tests (`_SYNTHETIC_CONTRACT_UNIVERSE`); they are never published.

## Company deep reports

`scripts/company_deep_report.py` builds one report per ticker of the newest sealed ranking (SEC filers only; others keep the audit template): business phrase from the latest annual report, same-calendar-quarter revenue, gross and operating margin, RPO, latest fiscal-year capital expenditure, cash, long-term debt, diluted-share change, inventory versus revenue, the company's SIC industry signals from the rotation, a company-scope `thesis_phase` result with next review date, falsifiers and source URLs. When an issuer switches XBRL tags, the tag with the most recent filing wins. Reports older than 7 days are not sealed. `publish_sealed_snapshot.py` embeds compact reports as `deep_reports` in the sealed bottleneck report, and the Worker renders them for 「深度化分析」 only when they come from the same snapshot the card referenced and pass strict validation.

## Limits and next sources

BLS PPI is monthly and SEC frames are quarterly, so the rotation moves with official releases, not intraday. EDGAR's SIC listing throttles (HTTP 503 with back-off; unavailable codes are recorded and retried on the next run). Census M3 orders need an API key and are not used. Candidate additions: EIA electricity data and buyer capital expenditure from hyperscaler XBRL.
