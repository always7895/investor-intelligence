# Investor Intelligence v2.1.3 — H6B1 R8 clause-safe order metric binding

R7 successfully rebuilt the real current Top 20, but its final semantic audit caught another false positive in CRDO.

## Observed R7 output

R7 emitted roughly:

`SEC文件明確揭露backlog約$71.3 million（文件日2026-06-15）`

The value is real, but the meaning is wrong.

Credo's fiscal-2026 10-K says inventory increased to support **unfulfilled backlog**, then after a semicolon separately says other current/non-current assets increased by **$71.3 million** because of refundable deposits to suppliers for reserved manufacturing production capacity. The $71.3 million is therefore not backlog.

The same filing separately reports contracted-but-unsatisfied performance obligations of approximately **$31.9 million**, expected to be recognized over the next fiscal year. That is valid RPO/contract visibility and must be labelled as RPO, not as all customer orders.

## Root cause

The R4 semantic matcher required a unit-bearing amount, but still used `.{0,N}` between metric label and amount. That allowed the backlog label to cross a semicolon into a different accounting clause and bind an unrelated amount.

## R8 rule

A metric label may bind a money amount only inside the same clause:

- no period between metric and amount;
- no semicolon between metric and amount;
- no newline between metric and amount.

The amount must still carry an explicit million/billion/M/B unit.

This preserves valid constructions such as:

`we had backlog of approximately $5.9 billion`

while rejecting constructions such as:

`... support unfulfilled backlog ...; other assets increased by $71.3 million ...`

## Preserved safeguards

R8 retains the prior protections:

- bare `$946` cannot be treated as RPO;
- acquired-backlog amortization cannot be treated as current backlog;
- RPO is explicitly scoped as not equivalent to all customer orders;
- NVIDIA-style `will be recognized` schedules remain valid future RPO inferences;
- no LINE delivery and no Production mutation occur in H6B1.
