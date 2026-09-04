# H6B1 R2 — zero-safe H6A baseline guard

## Failure observed

The first H6B1 Windows run reached the real 20-row build after the full Worker
regression passed, but rejected the accepted H6A artifact with:

`H6A baseline is not 7/7 PASS`

The accepted H6A summary actually contains numeric `failed: 0` and
`hard_dependency_count: 0`.

## Root cause

The original H6B1 verifier used Python truthiness defaults:

```python
int(summary.get("failed") or -1)
int(summary.get("hard_dependency_count") or -1)
```

Integer zero is falsy in Python. Therefore a valid explicit zero became `-1`.
This is a validator defect, not an H6A evidence or methodology failure.

## R2 behavior

`scripts/v213_serenity_h6b1_zero_safe.py` preserves explicit zero values and
fails closed when a required field is missing, null, boolean, malformed, or
nonzero. It also strengthens `production_ranking_changed` to require explicit
JSON `false`, rather than treating a missing value as equivalent to false.

The wrapper patches only the H6A baseline verifier and then executes the
original H6B1 builder unchanged.

## Scope

H6B1 R2 remains shadow-only:

- no Worker deployment;
- no KV mutation;
- no LINE message;
- no schedule change;
- no Production ranking change.

A separate regression test locks the numeric-zero case so this class of bug
cannot recur silently.
