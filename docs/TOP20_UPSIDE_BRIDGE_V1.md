# Top20 upside ranking and order-realization bridge V1 / Top20 上漲潛力排序與訂單實現估值橋

Status (2026-09-25): design; phase 1 implemented, phases 2–5 open. Operator requirements, recorded verbatim in intent:

1. Rank Top20 by the composite potential of future price appreciation.
2. Every figure and estimate carries an explicit source; vague wording such as 「很多」「市場很大」 is forbidden.
3. The future-orders field adds 6-month, 1-year and 2-year horizons and the estimated share-price change if the orders are realized.
4. The industry field names the specific sub-industry and what the company actually makes or does, never a bare label such as 「半導體」.

This contract keeps the project's evidence rules: no hard-coded bull/bear percentages, no invented order totals, scenarios labelled INFERENCE with premises, missing inputs shown as UNAVAILABLE (never 0%), `publication_eligible=false` until the R75 gates pass, and no Production or LINE change without explicit authorization.

## Current state (read-only map, 2026-09-25)

- Final sort key in every stage is `(-serenity_score, -data_quality, ticker)`, duplicated in six places (`v21_serenity_top20.py`, `v213_apply_diversified_operationalization.py`, `v213_serenity_latest_multisource_audit.py`, `v213_tam_capture_claim_guard.py`, `v213_build_v21_public_snapshot.py`, `bottleneck_ranking.py`). No term models future upside; historical returns carry zero weight by test.
- `current_orders` / `future_orders_estimate` are text with source URLs; amounts, units, recognition windows and accession numbers live inside the strings. `numeric_total_order_estimate_prohibited=true` is enforced in Python and in the Worker.
- 6M/1Y/2Y scenario text is a placeholder (`SCENARIO_STATUS`, `deep-analysis.ts`, `company-evidence-report.ts`). `docs/RESEARCH_EXECUTION_AUDIT.md` already specifies the order ledger and the per-horizon on-time / delay / failure chain, still unimplemented.
- No vague-wording lint exists; retained baseline rows bypass the only quantitative check (for example 「幾乎全部」 in a baseline row, 「能見度偏高」 in a contract fixture, 「強勁能見度」 in macro text).

## Phase 0 — industry detail (IMPLEMENTED, sidecar only for the source URL)

Before: `industry` was yfinance `info.industry` translated through a fixed table, so most technology names read 「半導體」. Now (`scripts/company_business_profile.py`, enabled with `--business-profile` in both scheduled runners): 「細分產業：主要業務」 within the Worker's 100-character limit, for example 「半導體設備與材料：研發與生產高性能化合物及單元素半導體晶圓」. 「｜」 is the report column separator and is rejected.

- Source: the latest 10-K / 20-F on SEC EDGAR. Selection order: a strong self-description in any Item 1 / Item 4 window (tables of contents and MD&A cross-references are both scored, earliest wins); else the first 1–3 sentences of the Overview paragraph; else the best activity sentence; else, without a usable heading, a strong self-description anywhere. Off-topic sentences (auditor report, dividends, fiscal year, committees, headquarters) are penalised.
- Translation: the configured loopback Qwen only (thinking disabled, temperature 0). The phrase is rejected if it adds a digit absent from the source, uses a banned vague phrase, contains 「｜」 or a line break, is not mostly CJK, or exceeds 40 characters; then the classification label stays.
- Provenance: the filing index is re-read every run; the annual document and validated phrase are cached per accession (`data/cache/v21/business_profiles`, extractor-versioned). The industry clock is the index check time with a joint digest of document and index; an unreceipted yfinance label is dropped instead of being composed. SEC 403/429 fences further profile requests for the run; the SEC session fence is honoured too.
- Evidence: `*.business-profile-candidate.json` (not publication eligible) keeps form, accession, filing URL, document SHA-256, English source excerpt and the phrase. Live canary 2026-09-25: 22/22 current Top20 plus TSM/ASML produced specific phrases, about 1 s each.
- Extractor v6 (2026-09-25, after a non-technology Top20 picked accounting, litigation, table-of-contents and logo sentences for NEM, AR, TRV, PBR and HIG): 「Items 1 and 2. Business」 headings; self-descriptions through defined-term parentheticals, 「was incorporated … and is primarily a」 and 「are engaged in」; sentences no longer split at 「Inc.」, 「U.S.」 or a split decimal; subjects naming words outside the registrant (affiliates such as 「Antero Midstream」) lose weight; accounting, legal, index-membership and structure sentences are penalised, while incorporation, headquarters and subsidiaries count against only non-self-descriptions; strong self-descriptions anywhere precede a weak window sentence (20-F cross-reference indexes); a self-description without an activity takes the next same-subject sentence. Phrases with Simplified-only characters or vague quantities (「數萬」) are rejected; the translator asks once more after a timeout. Live: 20/20 Top20 phrases, and 26 filings including the earlier technology names checked by hand.
- Open: surfacing the filing URL on the card still needs an `industry_source_url` field in the exact-key parsers (Python contract, Worker `top20-report.ts`, bottleneck report, activation-v3) as one versioned schema change.

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

Precursor (IMPLEMENTED 2026-09-25, potential ranking only): the on-time case from disclosed RPO timing as coverage of the current revenue run rate and a growth floor under constant margin, shares and P/E; see [INDUSTRY_ROTATION_V1](INDUSTRY_ROTATION_V1.md). It needs no reference price, so it does not close the data gaps below.

## Phase 4 — upside-potential ranking (operator decision 2026-09-25)

Replace the six duplicated sort keys with one shared key function. Only companies whose 6-month, 1-year and 2-year on-time `price_return_pct` can all be computed enter the upside ranking; they are ordered by the 2-year value, ties broken by the failed-case return (smaller loss first) and then data quality. Companies without all three horizons are not ranked by upside and are shown as 「上漲潛力未量化」 in the existing order.

## Phase 5 — presentation

Field 7 keeps its fail-closed strings. When a bridge exists, the card adds one compact line — 「若訂單如期實現：6M ±x%｜1Y ±y%｜2Y ±z%（INFERENCE；依據見深度分析）」 — and the deep analysis lists every operand with its source and date. Card length limits and the seven-field label/value contract stay unchanged.

## Data gaps to close before Phase 3 can run live

- Reference price with a recorded acquisition clock (current market observations lack `retrieved_at`).
- Structured ledger (Phase 2).
- Share count and dilution items bound to filings.
