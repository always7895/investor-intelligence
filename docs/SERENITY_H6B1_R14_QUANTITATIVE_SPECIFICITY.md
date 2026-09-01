# H6B1 R14 — Quantitative Specificity Upgrade

## Why R14 exists

R13 passed the full shadow validation and correctly recovered NVIDIA's 39% next-12-month RPO recognition schedule from the same SEC accession package. The resulting 20-row preview was then manually compared with public SEC disclosures.

Three rows were still less specific than the filings support:

- **PLTR** — current RPO `$4.9 billion`; the 2026-06-30 10-Q explicitly says approximately **43%** is expected to be recognized over the next 12 months.
- **NET** — current RPO `$2,732.0 million`; the 2026-06-30 10-Q explicitly says **64%** is expected to be recognized over the next 12 months.
- **SMCI** — current RPO `$2,612.0 million`; the 2026-06-30 10-K explicitly says approximately **60%** is expected to be recognized over the next 12 months.

R13 already classified these future fields as `INFERENCE`, but some bounded source contexts only produced the qualitative sentence that the RPO would be recognized within 12 months. Since R13 only enriches `UNAVAILABLE` futures, it intentionally did not revisit those qualitative inferences.

## R14 rule

R14 is a *specificity upgrade only*.

It may replace an existing qualitative `INFERENCE` with a quantitative `INFERENCE` only when:

1. the current order/contract metric is `SUPPORTED`;
2. the existing future field is already `INFERENCE`;
3. the existing future text contains no safely quantified percentage, amount, fraction, or schedule;
4. the current SEC source has exactly one selected URL;
5. candidate evidence stays in the same SEC accession package;
6. the metric type is identical;
7. the normalized unit-bearing amount is identical;
8. the already accepted R11 fulfillment parser produces the quantitative schedule; and
9. all quantitative candidates agree exactly.

R14 does **not** promote `UNAVAILABLE` futures; that remains R13's responsibility and fail-closed boundary.

## What R14 does not change

R14 does not change:

- Top 20 rank;
- the five existing visible fields;
- current-order metric selection;
- current-order amounts;
- source jurisdiction or issuer identity;
- `SUPPORTED / INFERENCE / UNAVAILABLE` meaning;
- hard-dependency classification;
- Production state;
- LINE state.

The stage remains shadow-only. H6B2 must remain blocked until the R14 preview is re-audited.