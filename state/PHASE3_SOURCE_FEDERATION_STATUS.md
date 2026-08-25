# Phase 3 Global Source Federation Status

_Last updated: 2026-08-24 Asia/Taipei_

## Implemented in the feature branch

- Directory-based source registry under `config/sources/**/*.json`.
- No artificial total source-count ceiling.
- Multi-region seed catalogs covering official international organizations, regulators, exchanges, central banks, statistics offices, patent/scientific repositories, sector authorities and reputable secondary leads.
- Source-family templates for verified issuer IR sites, tenant-authorized read-only brokers, regulated exchanges, government open data, SDMX services and public media.
- Strict admission lifecycle; discovery never auto-enables a source.
- HTTPS, zero-cost, no-payment, provenance and runtime-enable validation.
- Independent-source evidence assessment for direct and interpretive claims.
- Coverage ledger by jurisdiction, authority class, evidence role and language.
- Dedicated self-hosted BARRY workflow and regression tests.

## Deliberately not enabled yet

The catalogs are an authoritative candidate federation, not a claim that every source already has a production adapter. Runtime enablement remains blocked until each source passes:

1. identity/domain verification;
2. legal/public/free-access review;
3. source-specific adapter contract;
4. provenance and correction tracking;
5. parser/schema canary tests;
6. source health soak and circuit breaker tests;
7. freshness, stale and revision behavior;
8. zero-paid-fallback verification.

## Next engineering work

- Run the source-registry workflow on BARRY and resolve validation failures.
- Implement Phase 3 normalized observation/event schemas.
- Implement the first primary-source adapters by evidence value and coverage gap, not by a fixed source count.
- Add per-host scheduler budgets, circuit-breaker state and last-known-good promotion.
- Add source correction/restatement reconciliation.
- Add primary-document download/hash/parser fixtures for HTML, JSON, RSS, XML, CSV and PDF.
- Add multilingual entity/ticker resolution without allowing model-selected tenant or source identity.
- Add production coverage-gap reports.
- Keep all reputable media T3 and disabled until public-access/terms review passes.

## Safety state

- No private tenant data is included in the public source registry.
- Broker data remains read-only and tenant-scoped.
- No catalog entry requires payment.
- No source is automatically trusted or enabled because it appears in the catalog.
- No low-trust source can silently replace primary evidence.
- Source outages must preserve the last known good record and cannot become zero values.
