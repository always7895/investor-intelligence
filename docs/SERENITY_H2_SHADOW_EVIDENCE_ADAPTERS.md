# v2.1.3 H2 — Serenity shadow evidence adapters

## Purpose

H2 is a **shadow-only** stage. It does not replace the production Top 20, the v2.1.2 LINE routing, or the deterministic system score.

The goal is to measure what the current public-source ensemble can actually prove under the stricter v2.1.3 Serenity public-logic rules.

## Adapter boundary

The first H2 adapter deliberately maps only evidence provenance and source scope:

- SEC EDGAR company facts / recent filings -> `primary_strong` company regulatory evidence;
- GLEIF -> `primary_strong` legal-entity identity only;
- Yahoo/yfinance -> `lead_only` market/news observations;
- BLS / World Bank -> `corroborating` macro context only.

It does **not** infer any of the following from those sources automatically:

- bottleneck / semi-monopoly status;
- supply-chain graph edges;
- qualification friction;
- company capture;
- design wins / LTAs / prepayments;
- thesis killers;
- Serenity source views.

Those claims require later dedicated adapters with evidence binding.

## Why this conservative stage is useful

The existing system score can be high even when the public-logic engine still has insufficient evidence for a bottleneck thesis. H2 makes that difference explicit instead of forcing the two systems to agree.

For each ticker, the shadow output includes:

- current System operationalization score/rank when present in the local universe;
- public-source coverage actually retrieved;
- evidence tiers and claim scopes;
- fail-closed public-logic state;
- explicit missing adapter classes.

A non-U.S. ticker is allowed to complete the shadow run even when SEC companyfacts is unavailable.

## Expected interpretation

`UNPROVEN` is not a negative stock opinion. It means the current automatic evidence adapters have not yet proven the dependency/architecture claims required by the high-fidelity Serenity reconstruction.

This distinction is intentional. H2 should expose evidence gaps rather than convert weak market metadata into false confidence.

## Regression archetypes for the live shadow run

The Windows H2 validation runner may use AAOI / AXTI / SIVE / LITE / COHR / TSEM / SOI as **test inputs only**. They are not hard-coded into production scoring logic and are not permanent endorsements or expected rankings.

The purpose is to exercise:

- U.S. SEC-covered photonics names;
- an international/Nordic name with no SEC companyfacts;
- established beneficiaries versus smaller supply-chain candidates;
- coexistence of a system score with a more conservative fidelity state.

## H3 dependencies

Before the public-logic fidelity state can replace or materially influence Production, later stages still need:

1. real customer/supplier relationship extraction;
2. qualification/design-win/LTA/prepayment extraction;
3. capacity and lead-time evidence;
4. dilution/financing normalization across jurisdictions;
5. non-U.S. exchange/issuer announcement adapters;
6. architecture roadmap ingestion;
7. qualified competitor/substitute and architecture-bypass adapters;
8. persistent append-only Serenity source-view history;
9. repeated shadow-run comparison and contradiction analysis.

Until then, Production remains v2.1.2 and H2 remains read-only/shadow-only.
