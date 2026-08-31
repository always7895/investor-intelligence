# Serenity v2.1.3 H3 — Evidence-rich shadow rules

H3 remains **shadow-only**. It does not replace the Production ranking, LINE Worker, KV data, scheduled refresh, or the v2.1.2 live model bridge.

## Purpose

H2 proved that the existing source ensemble can be reused without inventing a Serenity-style bottleneck. H3 adds a narrow, auditable document-extraction layer over a bounded set of SEC issuer filings.

The goal is not to maximize the number of positive labels. The goal is to prove that stronger issuer evidence can be extracted while preserving the attribution boundary.

## New extraction classes

H3 may extract from SEC issuer filings:

- architecture candidates: CPO, 1.6T, 800G, silicon photonics, InP, HBM, advanced packaging;
- issuer self-description that it is a scarce/qualified supplier;
- customer qualification language;
- capacity expansion and vertical integration;
- design wins, qualification, capacity reservations, prepayments and LTAs;
- explicit AI/datacenter demand linkage to the issuer's own products;
- repeated ATM evidence across at least two distinct SEC filings;
- explicit going-concern language;
- customer-loss, qualification-delay and volume-ramp-delay language.

Every promoted commercial/expansion/killer signal is bound to an SEC URL and filing date.

## Critical directionality rule

`We depend on a sole supplier` is an **upstream company risk**. It is not evidence that the focal company is a chokepoint.

Conversely, even issuer language such as `we are one of only two qualified suppliers` remains only an `issuer_dependency_candidate` in H3. An issuer's own SEC filing is primary evidence that the issuer made the statement, but H3 does not treat self-description as independent customer/supplier corroboration of Serenity-style bottleneck status.

Therefore H3 does **not** promote issuer-only dependency candidates into `dependency_signals`.

A future adapter must add independent customer/supplier/roadmap corroboration before the fidelity engine can classify:

- `SINGLE_SOURCE`
- `SEMI_MONOPOLY`
- `QUALIFICATION_CONSTRAINED`
- `CAPACITY_BOTTLENECK`

## Expansion vs bottleneck

Issuer evidence can legitimately support an ordinary expansion thesis. For example:

- capacity expansion;
- vertical integration;
- evidence-bound beneficiary demand.

That can yield `EXPANSION_THESIS` or `BENEFICIARY` without implying a bottleneck.

## Financing rules

A single ATM mention does not prove `repeated_atm_or_material_dilution`.

H3 requires the ATM/public-equity-sales language to appear in at least two distinct SEC filing URLs before that killer is emitted. This can move the thesis to `THESIS_WEAKENING`, but H3 does not automatically claim that equity capture is destroyed.

Explicit going-concern language may emit `balance_sheet_funding_failure` and weaken the thesis.

## Fetch boundary

H3's new document fetcher accepts only SEC-hosted filing URLs and uses the existing SEC contact policy. It does not crawl arbitrary URLs or follow unbounded web discovery.

Each document is bounded in bytes, the number of filings is bounded, and stored excerpts are bounded to a short audit context.

## Repeated shadow comparison

The H3 Windows runner executes the same archetype set twice:

- AAOI
- AXTI
- SIVE
- LITE
- COHR
- TSEM
- SOI

It compares safety-critical canonical states rather than retrieval timestamps. Transient source availability may reduce evidence, but no run is allowed to manufacture a hard dependency from issuer-only claims.

## Remaining gaps after H3

H3 intentionally does not claim completion of:

1. independent customer/supplier corroboration;
2. non-US exchange/company primary filing adapters;
3. qualified competitor/substitute mapping;
4. architecture-bypass cross-company validation;
5. capacity and lead-time time series;
6. persistent Serenity source-view history.

Until those are present and repeatedly shadow-validated, the production fidelity layer must prefer `UNPROVEN` to false confidence.
