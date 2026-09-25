# Top20 upside ranking and order-realization bridge V1 / Top20 上漲潛力排序與訂單實現估值橋

Status (2026-09-25): design; phase 1 implemented, phases 2–5 open. Operator requirements, recorded verbatim in intent:

1. Rank Top20 by the composite potential of future price appreciation.
2. Every figure and estimate carries an explicit source; vague wording such as 「很多」「市場很大」 is forbidden.
3. The future-orders field adds 6-month, 1-year and 2-year horizons and the estimated share-price change if the orders are realized.

This contract keeps the project's evidence rules: no hard-coded bull/bear percentages, no invented order totals, scenarios labelled INFERENCE with premises, missing inputs shown as UNAVAILABLE (never 0%), `publication_eligible=false` until the R75 gates pass, and no Production or LINE change without explicit authorization.

## Current state (read-only map, 2026-09-25)

- Final sort key in every stage is `(-serenity_score, -data_quality, ticker)`, duplicated in six places (`v21_serenity_top20.py`, `v213_apply_diversified_operationalization.py`, `v213_serenity_latest_multisource_audit.py`, `v213_tam_capture_claim_guard.py`, `v213_build_v21_public_snapshot.py`, `bottleneck_ranking.py`). No term models future upside; historical returns carry zero weight by test.
- `current_orders` / `future_orders_estimate` are text with source URLs; amounts, units, recognition windows and accession numbers live inside the strings. `numeric_total_order_estimate_prohibited=true` is enforced in Python and in the Worker.
- 6M/1Y/2Y scenario text is a placeholder (`SCENARIO_STATUS`, `deep-analysis.ts`, `company-evidence-report.ts`). `docs/RESEARCH_EXECUTION_AUDIT.md` already specifies the order ledger and the per-horizon on-time / delay / failure chain, still unimplemented.
- No vague-wording lint exists; retained baseline rows bypass the only quantitative check (for example 「幾乎全部」 in a baseline row, 「能見度偏高」 in a contract fixture, 「強勁能見度」 in macro text).

## Phase 1 — sourced-wording guard (IMPLEMENTED)

- One policy file `config/v213-vague-wording-policy.json` lists banned phrases (Chinese and English) and the rule that any digit-bearing order sentence must carry at least one source URL and an as-of date.
- `config/v213-sourced-wording-policy.json` and `scripts/v213_sourced_wording_guard.py` (pure). `reconcile_v213_order_evidence.reconcile` applies it to every retained and newly researched row: a violating field is replaced by the existing fallback (`未揭露（無可靠公開訂單數字）` or `無可靠公開預估`), its source URLs are cleared, confidence becomes UNAVAILABLE when both fields are withheld, and the receipt lists `wording_guard_withheld`. Text is never rephrased.
- English phrases match on word boundaries (「Germany」 does not trigger 「many」). Tests: `tests/test_v213_sourced_wording_guard.py`.
- Worker enforcement is deferred: rejecting at render time would take down a report sealed before the guard existed. After one sealed cycle built with the guard, add a Worker validator.

## Phase 2 — structured order ledger

A sidecar per ticker, bound to the report SHA like the existing rank-coupled companions: item id, counterparty (if disclosed), metric type (RPO, backlog, firm order, LOI, pipeline), amount, currency, unit scale, recognition window or percentage, source URL, accession, filed date, passage hash, claim status and lineage. RPO, backlog and prepayment are never summed; pipeline and LOI are never treated as orders.

## Phase 3 — order-realization valuation bridge

For each horizon h ∈ {6M, 1Y, 2Y} and case ∈ {on-time, delayed/partial, failed}:

1. Revenue added in h = Σ ledger items recognised within h under the case's schedule (disclosed windows only).
2. Operating result = revenue × the company's own trailing operating margin from SEC filings (dated, cited); loss-making companies use EV/Sales, never a positive P/E.
3. Per-share value uses diluted shares from the latest filing plus disclosed dilution (ATM, convertibles, warrants) with sources.
4. Valuation multiple = the company's own multiple at the reference date, computed from a dated price with a known acquisition clock and the same SEC fundamentals (constant-multiple assumption stated as a premise). No third-party or guessed multiples.
5. `price_return_pct = (scenario_value_per_share / dated_reference_price − 1) × 100`, shown with every operand's source; any missing operand makes that horizon UNAVAILABLE.

No scenario probabilities (no calibration basis), no averaging of cases.

## Phase 4 — upside-potential ranking (needs operator decision)

Replace the six duplicated sort keys with one shared key function. Proposed default, without invented weights: candidates with a complete bridge rank first by the on-time 2-year `price_return_pct`, ties broken by the failed-case return (smaller loss first) and then data quality; candidates without a complete bridge follow in the existing order and are labelled 「上漲潛力未量化」. Alternative weightings need the operator's explicit choice.

## Phase 5 — presentation

Field 7 keeps its fail-closed strings. When a bridge exists, the card adds one compact line — 「若訂單如期實現：6M ±x%｜1Y ±y%｜2Y ±z%（INFERENCE；依據見深度分析）」 — and the deep analysis lists every operand with its source and date. Card length limits and the seven-field label/value contract stay unchanged.

## Data gaps to close before Phase 3 can run live

- Reference price with a recorded acquisition clock (current market observations lack `retrieved_at`).
- Structured ledger (Phase 2).
- Share count and dilution items bound to filings.
