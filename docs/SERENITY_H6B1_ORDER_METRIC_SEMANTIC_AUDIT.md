# H6B1 R4 — SEC order metric semantic audit

The H6B1 R3 Windows run passed its structural gates and produced a 20-row seven-field preview, but a manual evidence audit found that the generic SEC fallback was still too permissive for Production/LINE acceptance.

## Observed false bindings

The R3 preview included three concrete problems:

- **CRDO**: `RPO ≈ $104,367` was not the actual RPO. The same filing states contracted-but-unsatisfied performance obligations of about **$31.8 million**.
- **AMD**: `RPO ≈ $946` was not the actual RPO. The June 2026 10-Q states aggregate RPO of **$222 million**, including **$144 million** expected in the next 12 months.
- **APH**: `backlog ≈ $23.5` was a false positive. The filing's `$23.5` refers to acquisition-related amortization of **acquired backlog**, not the company's current backlog balance.

The failure mode was caused by searching a long sentence/window for any dollar amount whenever the same window contained an order-related label.

## R4 extraction rules

The generic SEC adapter now requires:

1. a direct metric phrase (`backlog`, `order book`, `production order`, or RPO);
2. a bounded grammatical link between the metric and the amount;
3. an explicit monetary unit (`million`, `billion`, `M`, or `B`) for generic extraction;
4. rejection of acquired-backlog/amortization/fair-value/purchase-accounting contexts;
5. RPO to be labeled as **contract visibility, not total customer orders**;
6. forward outlook only when the same evidence contains an explicit recognition schedule.

A filing date alone is no longer enough to generate text such as "訂單/履約語境延伸至2026".

## Filing selection

The prior candidate selection could let numerous recent 8-K filings crowd out the latest 10-Q/10-K. R4 always retains the latest 10-Q, latest 10-K/20-F where available, plus at most three recent event filings.

## Serenity fidelity boundary

This repair does not change ranking, dependency roles, or the public-logic methodology. It only improves claim grounding for the two new LINE fields:

- 公司現在訂單
- 未來訂單預估

RPO/backlog/order evidence remains separate from Serenity bottleneck proof. A large RPO, backlog, or order commitment cannot create `SEMI_MONOPOLY`, `SINGLE_SOURCE`, `QUALIFICATION_CONSTRAINED`, or `CAPACITY_BOTTLENECK` without independent scarcity/effective-capacity evidence.

H6B2 real LINE delivery must remain blocked until the corrected 20-row R4 preview passes audit.
