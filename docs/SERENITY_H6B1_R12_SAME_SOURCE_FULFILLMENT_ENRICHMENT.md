# H6B1 R12 — Same-source fulfillment enrichment

## Trigger

The real Windows R11 run passed all semantic regressions, passed the full Worker
suite, and successfully built the real 20-row seven-field shadow.  The build
reported `current_order_supported_rows=13`, `future_order_evidence_bound_rows=7`,
`production_ranking_changed=false`, and `line_delivery_performed=false`.

The final audit then stopped on NVDA because its current order evidence was
supported but its future field was still `無可靠公開預估`.

## Public-source fact

NVIDIA's Form 10-Q for the quarter ended July 26, 2026 discloses both facts in the
same filing: revenue related to remaining performance obligations from contracts
greater than one year was approximately $3.2 billion, and approximately 39% of
that revenue will be recognized over the next twelve months.

The future field therefore should be an evidence-bound fulfillment/recognition
schedule, explicitly labeled as not a forecast of newly booked orders.

## Failure mode

The accepted strict metric extractor intentionally returns one best current
metric occurrence and stores a bounded local context around that occurrence.
Real iXBRL/SEC source views can contain repeated or early fact representations.
An early valid occurrence can bind the correct current RPO amount while its
bounded context does not include the later visible fulfillment sentence.

Synthetic tests that place the current amount and fulfillment sentence adjacent
do not reproduce this source-view duplication pattern.

## R12 boundary

R12 does **not** loosen current-order extraction and does **not** search another
issuer/document for a missing outlook.

It first runs the accepted R11 adapter unchanged.  Enrichment is attempted only
when:

1. current orders are `SUPPORTED`;
2. future orders are `UNAVAILABLE`;
3. there is exactly one selected current-order source URL;
4. the selected current metric type can be recovered from the supported summary;
5. the current unit-bearing amount can be recovered exactly.

R12 then re-opens only that same selected source view and searches all existing
clause-safe metric matches for the **same metric type and same normalized amount**.
Only an explicit R11-recognized fulfillment schedule in the local context of such
a match can change the future classification from `UNAVAILABLE` to `INFERENCE`.

A schedule attached to a different amount or a different metric type cannot be
borrowed.  Existing `INFERENCE` rows are never replaced.  Rows with no matching
schedule remain fail-closed as `UNAVAILABLE`.

## Regression requirements

R12 regression coverage includes:

- duplicate/current-only occurrence followed by the same NVDA $3.2b RPO with 39%
  next-12-month recognition;
- a different RPO amount with a schedule must not enrich the selected amount;
- a different metric type with the same numeric amount must not enrich;
- an existing inference must remain untouched;
- the real generic SEC adapter wrapper must recover the schedule from the same
  selected source;
- an issuer with no same-amount schedule remains unavailable.

## Production boundary

H6B1 R12 remains shadow-only.  It does not change Production, LINE delivery, KV,
credentials, schedules, or production ranking.
