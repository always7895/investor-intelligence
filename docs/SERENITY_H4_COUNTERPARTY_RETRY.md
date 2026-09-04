# Serenity H4 counterparty corroboration retry

The first H4 v2 live shadow established SIVE official issuer identity, corrected the H3 false positives, and completed all seven symbols, but its independent-graph count remained zero because the default Python request to the GlobalFoundries silicon-photonics page did not yield a usable Sivers relationship marker on Windows.

This retry remains shadow-only.

## Independent-source requirement

The retry uses an official GlobalFoundries page with browser-compatible headers and requires visible evidence that includes both:

- `Sivers`; and
- `GlobalFoundries` or `GF`;

plus collaboration / silicon-photonics / SCALE / optical-solutions context.

A generic GlobalFoundries silicon-photonics page without an explicit Sivers reference does not pass.

## What a successful retry proves

It proves only that an independent official counterparty source acknowledges a Sivers ↔ GlobalFoundries ecosystem relationship. The adapter can add one evidence-bound graph edge for that relationship.

It does **not** establish `SINGLE_SOURCE`, `SEMI_MONOPOLY`, `QUALIFICATION_CONSTRAINED`, or `CAPACITY_BOTTLENECK`. The retry is explicitly prohibited from changing the pre-existing dependency role.

## Production boundary

The retry patches only the H4 shadow JSON. It does not deploy the Worker, write KV, change LINE or Cloudflare secrets, modify schedules, or replace Production ranking.
