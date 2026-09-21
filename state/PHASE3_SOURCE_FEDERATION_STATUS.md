# Phase 3 Global Source Federation Status

_Foundation snapshot: 2026-08-24 Asia/Taipei; current code reconciliation below._

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

## Current code reconciliation (source ec82cfb)

**Present building blocks (implemented, not re-derived):**
- Normalized `SourceObservation` with privacy/chronology: [source_observation.py](../scripts/source_observation.py)
- Run-bound acquisition, per-host/run budgets, circuit-breaker: [source_acquisition.py](../scripts/source_acquisition.py), [report_source_acquisition.py](../scripts/report_source_acquisition.py)
- LKG persistence/promotion helpers (promotion ≠ automatic stale-serving; no stale-as-HEALTHY requirement)
- Outages/unknowns remain failed/unknown, never zero/fresh
- Typed metadata/hashes are not independent fetch authenticity by themselves

**Evidence (factory-only, NOT release/shipping proof):**
- Current inventory authority: `python scripts/source_registry.py summary`. Runtime-enabled catalog metadata is not broad live coverage; the ECB observation below is limited to its recorded source baseline.
- ONE default factory read at `ec82cfb` (admitted ECB endpoint, real clock/transport): ACQUIRED 1 candidate / 1 successful source; hashes unchanged; `release_qualified=false`, `live_proof=false`.
- Factory-only; NOT whole caller/answer/shipping acceptance. No endpoint admission, Production, or settings changes.

**Remaining (scoped reconciliation/evidence required; not assumed absent from old TODOs):**
- Broader canonical qualification + clearing-lane evidence (separately bounded contracts; not all require Production mutation)
- Windows/archive/install/release proofs (separate)
- Primary-document download/hash/parser fixtures (HTML, JSON, RSS, XML, CSV, PDF)
- Multilingual entity/ticker resolution (no model-selected tenant/source identity)
- Source correction/restatement reconciliation
- Production coverage-gap reports
- Keep reputable media T3, disabled until public-access/terms review passes

**Tests:** [test_source_observation.py](../tests/test_source_observation.py), [test_source_acquisition.py](../tests/test_source_acquisition.py), [test_source_acquisition_caller.py](../tests/test_source_acquisition_caller.py), [test_report_source_acquisition.py](../tests/test_report_source_acquisition.py)

## Safety state

- No private tenant data is included in the public source registry.
- Broker data remains read-only and tenant-scoped.
- No catalog entry requires payment.
- No source is automatically trusted or enabled because it appears in the catalog.
- No low-trust source can silently replace primary evidence.
- Source outages must preserve the last known good record and cannot become zero values.
