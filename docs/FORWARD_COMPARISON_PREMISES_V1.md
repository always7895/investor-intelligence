# Forward comparison premises V1 / 前瞻比較前提 V1

Status (2026-09-25): design accepted for development; C1 implemented as a nonauthorizing shadow. No scoring, ranking, publication or consumer change is authorized by this document. It names the finite contracts that implement lane 1 of `state/STATUS.md`.

## Problem

`scripts/v213_forward_comparison_shadow.py` (T3) diagnoses a caller-declared pair — a reported baseline period and a forward period from `scripts/v213_forward_period_shadow.py` (T2) — across 12 descriptor axes, but always returns UNQUALIFIED with six unresolved premises. Caller declarations are never evidence. This design states which *admitted* inputs from existing components could resolve each premise, and what a consumer may conclude once they do.

## V1 scope

- One issuer, one metric family: revenue, `measure_form = AGGREGATE_FLOW`. Per-share metrics are out of scope.
- Baseline: an SEC-reported actual bound by `bind_sec_claim` (`scripts/adapters/sec_edgar.py`; entity = CIK, USD only, raw units) and retained as a `company_financial_products.py` operand.
- Forward: an issuer management-guidance or signed-commitment claim assessed by the existing claim engine (`scripts/source_observation.py` through `v213_source_independence_gate_v4.py`), with its period declared through T2 (`CALLER_CLAIMED_MANAGEMENT_GUIDANCE` or `CALLER_CLAIMED_COMMITMENT`).

## Premise resolution map

| T3 unresolved premise | Admitted input that can resolve it | Resolution rule (all must hold) | Otherwise |
| --- | --- | --- | --- |
| IDENTITY_ASSOCIATION | SEC CIK binding for both claims | Same CIK; issuer-level aggregate only, so `security_id`/`venue` may stay UNSPECIFIED | UNRESOLVED |
| METRIC_UNIT_CURRENCY_ACCOUNTING | Evidence payload fields `metric`, `unit`, `currency`, `basis`, `scope` of both claims | Identical values taken from admitted evidence, not from caller descriptors; the engine's `NOT_COMPARABLE` on any axis blocks | NOT_COMPARABLE |
| PERIOD_ALIGNMENT_BASELINE_VINTAGE | SEC fact `start`/`end`/`filed`/`accession_number`; T2 declaration | Equal period length; T3 `NONOVERLAPPING_TOTALS`; forward role `FUTURE_START_TOTAL`; baseline is the latest filing on or before `information_cutoff`, and its accession is shown | UNRESOLVED (STRADDLING_TOTAL never yields a comparison) |
| SHARE_COUNT_DILUTION | Not needed for aggregate flows | Resolved by scope only when `measure_form = AGGREGATE_FLOW` | OUT_OF_SCOPE for per-share |
| FRESHNESS_LINEAGE_RIGHTS_COUNTEREVIDENCE | Claim-engine status; `qualify_claim_evidence` in `scripts/source_registry.py`; source rights review | Forward claim `SUPPORTED` (two or more independent families, evidence `as_of` not after the cutoff, no conflict); sources terms-reviewed for the display | SINGLE_SOURCE / CONFLICTED / UNAVAILABLE stay visible |
| CONSUMER_ADMISSION | Consumer contract below | Every other premise resolved and publication gates passed | Withheld |

Existing-engine observations already pin the important negatives (`tests/test_research_v2_claims.py`): a supported baseline cannot corroborate the forward claim; a future `as_of` is rejected; axis mismatch yields `NOT_COMPARABLE`; conflicting guidance is never averaged; `stock_score_adjustment` stays 0.

## Intended consumer conclusion

Consumer: the local detailed report (`data_report` kind in `scripts/company_financial_products.py`), never the Top20 order fields. `公司現在訂單` and `未來訂單預估` are order fields; revenue guidance must not fill them.

When all premises resolve, the report may place the two SUPPORTED disclosed values side by side, without inference:

> 公司指引 {forward period} 營收 {value} {unit} {currency}（{basis}，{scope}；{guidance date}，{n} 個獨立來源）；對照已申報 {baseline period} 營收 {value}（{form} {accession}）。此為揭露值並列，非預測或成長評分。

Otherwise it shows `無可靠公開預估` plus the unresolved premise names. V1 computes no ratio, CAGR, annualization or growth score. Whether a later version may show an explicitly labelled "implied change versus reported baseline" is an operator decision (see below).

## Non-goals

No new provider or live fetch, no change to scoring, ranking, weights, LIMITED gates, Top20 fields, LINE output, publication or Worker code. `publication_eligible` remains false until the R75 release gates pass.

## Proposed finite contracts (each needs its own task)

1. **C1 read contract — IMPLEMENTED:** `assess_forward_premises` in `scripts/v213_forward_premises_shadow.py` takes a T3 diagnostic, an SEC `SecClaimBinding`, the forward claim declaration and the claim-engine result, and returns per-premise states; tests in `tests/test_v213_forward_premises_shadow.py` drive the real T3, SEC binding and claim engines. Implemented rules:
   - Periods are half-open UTC-midnight intervals. The declared baseline start and end select the SEC duration fact, because annual and quarterly facts can share an end date. The forward claim period label must be `YYYY-MM-DD/YYYY-MM-DD` matching the T2 dates.
   - Length classes: ANNUAL 364–371 days (52/53-week and calendar years), QUARTER 89–98 days; baseline and forward must share a class.
   - SEC filing dates have day precision, so a fact counts only if its whole filing day precedes the information cutoff. The latest such filing wins; same-day conflicting values block; earlier different values add `BASELINE_REVISED_WITHIN_DOCUMENT`. The companyfacts receipt must be retrieved at or after the cutoff.
   - Identity uses the SEC binding's resolved symbol alias; its trust is inherited from that binding (`SYMBOL_ALIAS_TRUST_INHERITED_FROM_SEC_BINDING`).
   - Unit scale may differ (display only, never converted); currency, GAAP basis, consolidated scope and revenue tag must match.
   - Consumer admission is always `DEFERRED_TO_CONSUMER_CONTRACT`; scoring, publication and admission flags are fixed false.
2. **C2 consumer contract:**
   - **C2a renderer — IMPLEMENTED:** `render_forward_comparison_block` in `scripts/v213_forward_comparison_render.py` turns a C1 assessment into one section: the side-by-side disclosure (values as disclosed, `Decimal` formatting, no conversion), a revision notice when the baseline changed within the SEC document, or `無可靠公開預估` with every unresolved premise and reason. Byte-exact text fixtures in `tests/test_v213_forward_comparison_render.py`; the section respects the 4400 UTF-16 unit ceiling used by `company_financial_products._product`.
   - **C2b wiring — NEXT:** add the section to the local `data_report` only. `verify_financial_products` replays from input bytes, so the wiring needs a serializable, digest-bound forward-comparison input bundle (SEC receipt bytes, claim-engine document, T2/T3 declarations) that the replay can rebuild; in-process objects alone are not replayable. Still `publication_eligible=false`.
3. **C3 live qualification:** a source-bound run on one real issuer under the existing R75 gates. Needs explicit operator authorization if it touches Production, KV or LINE.

## Operator decisions needed

- Implied-change display: keep V1 side-by-side only (current), or allow a labelled ratio in a later version.
