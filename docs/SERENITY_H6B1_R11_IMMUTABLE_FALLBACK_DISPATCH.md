# Serenity H6B1 R11 — Immutable Fallback Dispatch

## Failure observed in R10

R10 passed all explicit schedule/canonicalization tests and the complete Worker
regression, then failed during the real 20-row build with `RecursionError`.

The loop was architectural rather than evidentiary:

1. R9's `_future_from_context_v4()` handled explicit amount/percentage/fraction,
   fiscal-year and multi-period schedules.
2. If none matched, its final fallback called the mutable module slot
   `r4._future_from_context(metric)`.
3. R10 replaced that same slot with `_future_from_context_v5()` to canonicalize
   the disclaimer.
4. R10 called R9, R9 called the mutable slot, and the slot pointed back to R10.

Therefore a valid RPO that required the older qualitative fallback could recurse
without changing any data or evidence.

## R11 rule

No fallback implementation may call a mutable dispatch slot that can later be
rebound by another wrapper.

R11 imports the last clause-safe layer (R8), captures the pre-R11 R6 future
parser as an immutable function object, and then installs one final R11 dispatch
function. Explicit R9 fulfillment patterns are reproduced in R11, while the
qualitative fallback calls only the captured function object.

This creates a one-way chain:

`generic SEC adapter -> R11 explicit schedules -> immutable R6 fallback`

and never:

`R11 -> mutable r4 slot -> R11`.

## Preserved semantics

R11 changes no public-evidence policy:

- clause-safe backlog/order/RPO amount binding remains active;
- CRDO `$71.3m` supplier-capacity deposits cannot become backlog;
- CRDO `$31.9m` RPO remains supported;
- bare `$946` RPO remains rejected;
- acquired-backlog amortization remains rejected;
- NVDA/PLTR/SMCI/etc. percentage schedules remain inference, not new-order
  forecasts;
- MU `one-third` remains word-preserving rather than converted to a fabricated
  decimal;
- canonical Traditional-Chinese disclaimer remains `非新增訂單預測`;
- unavailable future evidence remains `UNAVAILABLE` rather than inferred.

## Acceptance regression

R11 requires a deliberately non-quantified RPO recognition sentence that forces
the fallback path. The test invokes that path repeatedly and also through the
real `generic_sec_outlook_semantic()` adapter. It must complete without recursive
re-entry and retain the canonical disclaimer.

R11 remains shadow-only. It does not deploy Production, write KV, send LINE,
change credentials or change schedules.
