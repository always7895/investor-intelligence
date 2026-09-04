# H6B1 R6 — RPO recognition wording repair

H6B1 R5 reached the real semantic guard self-test and failed only on the NVIDIA fixture:

`Approximately 39% ... will be recognized over the next twelve months.`

The R4 pattern accepted `will recognized` or `is expected to be recognized`, but omitted the normal SEC phrase `will be recognized`.

R6 introduces a wrapper that replaces only the next-12-month recognition patterns. It accepts:

- `will be recognized ... next twelve months`
- `is expected to be recognized ... next 12 months`
- explicit percentage recognition schedules
- explicit amount recognition schedules

It preserves the R4 strict guards:

- unit-bearing amounts only for generic SEC order metrics;
- acquired-backlog/amortization contexts rejected;
- RPO explicitly scoped as not equal to all customer orders;
- bare `$946` style values rejected;
- no future-order inference from a filing year alone.

R6 remains shadow-only. No LINE delivery or Production mutation is permitted.
