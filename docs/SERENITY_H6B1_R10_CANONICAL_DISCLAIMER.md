# H6B1 R10 — canonical fulfillment-schedule disclaimer

## Observed R9 failure

The R9 fulfillment-schedule logic correctly returned `INFERENCE` for issuer-disclosed recognition/fulfillment schedules. Eight regression cases failed only because the test required the exact Traditional-Chinese phrase `非新增訂單預測`, while several R9 branches emitted the semantically equivalent phrase `不等於新增訂單預測`.

Examples affected included NVDA 39%, MU one-third, AMD $144m, PLTR 43%, AVGO 30%, Life360 46%, NET 64% and SMCI 60%.

## R10 rule

R10 does not change evidence extraction or inference semantics. It canonicalizes all `INFERENCE` fulfillment-schedule disclaimers to:

`非新增訂單預測`

The following remain unchanged:

- current-order/backlog/RPO amount binding;
- clause-safe metric grammar;
- CRDO $71.3m supplier-deposit rejection;
- bare-dollar `$946` rejection;
- acquired-backlog amortization rejection;
- recognition schedule percentages/amounts/periods;
- `SUPPORTED` / `INFERENCE` / `UNAVAILABLE` classification;
- ticker ranking;
- LINE delivery state;
- Production state.

The earlier R9 test is also corrected to accept either semantically equivalent disclaimer when testing the R9 implementation itself. The new R10 test separately requires the canonical wording.
