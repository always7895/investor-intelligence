# Source activation plan V1 / 來源啟用計畫

Status: PLAN (2026-09-25). Operator rule: every data type must come from diversified, independent sources; no single provider (for example yfinance alone). This plan measures what is actually enabled and orders the work to enable more, without bypassing rights, access or evidence gates.

## Measured state (registry `scripts/source_registry.load_registry`, 2026-09-25)

| Measure | Value |
| --- | --- |
| Catalogued sources | 158 (7 catalog files) |
| `RUNTIME_ENABLED` | 1 — `eu_ecb_fx_reference` (the only `terms_review_status: approved`) |
| Adapter status | 125 planned, 32 manual-only, 1 implemented |
| Catalog `adapter_id` with adapter code | 1 — `us_sec_edgar` → `scripts/adapters/sec_edgar.py` (still planned, terms pending) |
| Adapter modules in `scripts/adapters/` | SEC EDGAR, ECB FX, ECB SDMX, SDMX CSV, GLEIF, World Bank, TWSE/TPEx equities, TAIFEX options EOD, Nasdaq symbol directory, issuer directory, official RSS, company public document, staged public |
| Market prices in the Top20 path | yfinance (`build_v212_top20_report._market_observation`); Stooq, Nasdaq and Alpha Vantage appear only as cross-checks in `v213_source_independence_gate.py` |
| Industry in the Top20 path | yfinance `info.industry` only |

Most adapter modules are called by standalone collectors whose ids do not match the catalog entries, so catalogue coverage overstates runtime diversity.

## Diversity target per data type

| Data type | Minimum independent families | Candidates (primary first) |
| --- | --- | --- |
| Share prices / returns | 2 | Exchange official EOD where free (TWSE, TPEx); secondary providers with reviewed terms (yfinance, Stooq, Nasdaq) |
| Financial statements | 1 primary + corroboration | SEC EDGAR companyfacts and filings; issuer IR |
| Orders / backlog / guidance | 2 (existing claim policy) | SEC filings, issuer releases, counterparty disclosures, reputable media (manual) |
| Industry and business | 2 | SEC SIC + 10-K Item 1; yfinance industry |
| Identity | 2 | SEC ticker map, GLEIF LEI, Nasdaq symbol directory |
| Macro | 2 per series | FRED/ALFRED, BLS, ECB SDMX, World Bank |
| Options quotes | 2 where available | TAIFEX (TW, open data); US quotes remain observation-only |

## Activation checklist (per source)

1. Rights: record the official terms page, date and quoted licence clause (as in `docs/PUBLIC_SOURCE_RIGHTS_REVIEW_20260909.md`); set `terms_review_status` only from that record.
2. Adapter: map the catalog `adapter_id` to the module, with offline fixture tests and fail-closed parsing.
3. Access: one bounded, credential-free live read with a fetch receipt; respect published rate limits and User-Agent rules.
4. Admission: set `admission_status: RUNTIME_ENABLED` in the catalog with the evidence links; update coverage and diversity gates.
5. Wiring: call the source from the actual Top20/QA path and report per-claim lineage counts, not endpoint counts.

## Waves

- **Wave 1 — official open data with adapters already written:** SEC EDGAR (companyfacts, submissions), TWSE and TPEx EOD, TAIFEX options EOD, World Bank, GLEIF, ECB SDMX, official regulator RSS.
- **Wave 2 — official data needing new adapters or terms checks:** FRED/ALFRED, BLS, Nasdaq symbol directory, SEC 10-K Item 1 business text for industry detail.
- **Wave 3 — secondary market providers:** Stooq, Nasdaq quote API, Alpha Vantage free tier — only after a terms review; they add a second price family for US listings where no free official feed exists.

No paid source, paywall bypass or credential is used. Production activation still needs explicit operator authorization.
