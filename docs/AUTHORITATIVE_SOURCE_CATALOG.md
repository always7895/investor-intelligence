# Authoritative Source Catalog

_Last reviewed: 2026-08-24 Asia/Taipei_

## Purpose

This catalog is the privacy-first Phase 3 source foundation built on top of the shared LINE public-only boundary. It is designed to expand without a fixed numeric source ceiling while keeping each execution finite, free-only, reviewable and stable.

**Catalog membership does not mean runtime activation.** Every current record has `runtime_enabled=false`. No source is fetched merely because it appears in the catalog.

## Current inventory snapshot

The initial modular snapshot contains **99 unique source records**. This number is an inventory checkpoint, not a cap.

| Region | Sources |
|---|---:|
| Asia-Pacific | 31 |
| Americas | 27 |
| Global / multilateral | 17 |
| Europe | 16 |
| Middle East and Africa | 8 |

Evidence tiers:

| Tier | Meaning | Count |
|---|---|---:|
| T0 | Primary legal, regulatory, filing or registry record | 27 |
| T1 | Official statistical or public-authority data | 53 |
| T2 | Regulated market or market-infrastructure record | 18 |
| T3 | Public market observation or secondary corroboration candidate | 1 |

The catalog covers company filings, legal entities, macroeconomics, central banks, rates, foreign exchange, banking, labor, trade, industry, energy, grids, procurement, patents, trademarks, telecommunications, cybersecurity, health, clinical trials, exchange disclosures, corporate actions, futures and options-market observations.

## Regional coverage

### Taiwan and Asia-Pacific

The Asia-Pacific fragment includes Taiwan TWSE OpenAPI, MOPS, TPEx, FSC, DGBAS, Central Bank statistics, government open data, MOEA, TIPO and NCC. It also covers official authorities and exchanges in Japan, Korea, Hong Kong, Singapore, Australia and India.

### Americas

The Americas fragment includes SEC EDGAR, FRED/ALFRED, BLS, BEA, Census, U.S. Treasury, EIA, CFTC, FDIC, openFDA, ClinicalTrials.gov, USPTO, NIST NVD, SAM.gov, FCC, NOAA, Statistics Canada, Bank of Canada, SEDAR+, Banxico, INEGI, Banco Central do Brasil, IBGE and CVM.

### Europe

The Europe fragment includes ECB, Eurostat, ESMA, EBA, EIOPA, EU TED, ENTSO-E, EPO, EUIPO, ONS, Bank of England, Companies House, FCA, Ofgem, SNB and SIX Exchange Regulation.

### Global and multilateral

The global fragment includes World Bank, IMF, OECD, BIS, WTO, UN Comtrade, UN Data, ILOSTAT, FAOSTAT, WHO GHO, GLEIF, WIPO, ITU, UN SDG and NASA POWER.

### Middle East and Africa

The regional fragment includes SARB, JSE SENS, Saudi CMA, Saudi Exchange disclosures, Central Bank of the UAE, ADX, DFM and Bank of Israel statistics.

## Runtime activation gate

A source may enter runtime only when **all** of the following are true:

1. authority scope reviewed;
2. access and rights reviewed for the exact endpoint and use;
3. free access or an optional free credential verified;
4. response schema reviewed;
5. privacy boundary reviewed;
6. a statically reviewed adapter and fixture tests pass;
7. runtime health/probation passes;
8. `rights_status=reviewed_public_access`;
9. `redistribution_status=public_attribution`;
10. `adapter_status=adapter_reviewed`;
11. every gate is true;
12. any required free credential is present at runtime.

Automatic discovery may create disabled candidate metadata. It may not enable an endpoint, execute remote code, install a plugin, bypass a paywall/CAPTCHA/robots restriction, purchase a plan or inherit a user's private source entitlement.

## Finite runtime planning

Catalog growth is unbounded by source count, but each run is bounded by:

- total request budget;
- total response-byte budget;
- total wall-clock budget;
- per-host request budget;
- per-host concurrency;
- source-specific request ceiling;
- retry and timeout limits;
- free credential availability;
- source health state.

The planner defers excess sources rather than increasing traffic or silently upgrading to a paid plan. A 300-source synthetic regression test proves that source count itself is not a cap while runtime budgets still restrict the selected subset.

## Existing reviewed adapter candidates

The older Phase 3 line contains fixture-tested adapter implementations for:

- SEC EDGAR;
- World Bank Indicators;
- GLEIF LEI;
- ECB SDMX.

In this reconciliation branch they are marked `adapter_replay_required`, not accepted or active. They will be selectively replayed only after compatibility review against the PR #12 privacy boundary, strict catalog model and latest exact-head BARRY gate.

## Options and quote-source caveat

The catalog distinguishes authoritative records from public market observations.

- OCC public statistics may support aggregate options volume/open-interest context.
- Cboe and Nasdaq public pages are metadata-only candidates until automated-access, redistribution, freshness and schema rights are reviewed.
- Yahoo Finance/yfinance is explicitly marked a **T3 public market observation**, not an authoritative source. It is disabled by default and cannot be represented as official or broker-grade data.
- LINE never falls back to IBKR, owner holdings, account data or covered-capacity calculations.

A public options provider may be enabled only after the same rights, schema, freshness, quota, privacy, health and exact-head acceptance gates pass. Missing or stale public data must return unavailable; it must not trigger a broker or paid fallback.

## Privacy boundary

The catalog contains only public-source metadata. It must never contain or ingest:

- raw LINE user identifiers or messages;
- user query history or watchlists;
- owner holdings, cost basis, P&L, margin or account identifiers;
- IBKR sessions, account data or broker-derived public snapshots;
- tenant memory, encrypted private records or private report content.

Public data, tenant-private memory/jobs and ephemeral security state will use separate storage bindings before external-user release.

## Files

- `config/authoritative-source-catalog.json` — policy, columns, defaults and fragment list;
- `config/authoritative-sources/*.json` — modular regional catalogs;
- `schemas/authoritative-source-catalog.schema.json` — strict schema contract;
- `scripts/authoritative_source_catalog.py` — fail-closed loader, validator, inventory and runtime planner;
- `tests/test_authoritative_source_catalog.py` — strictness, diversity, activation and budget regressions.

No deployment, live fetch, credential installation, LINE connection, IBKR connection or paid service is performed by this catalog work.
