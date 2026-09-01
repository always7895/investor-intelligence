# H6B1 R9 — Explicit RPO/backlog fulfillment schedules

R8 fixed a real current-order false positive by preventing a backlog/RPO label from binding a money amount across clause boundaries. Its real 20-row output also showed a separate under-extraction problem in the **future-order** column: several SEC filings explicitly disclosed when already-contracted RPO/backlog is expected to be recognized or fulfilled, but the generic adapter still returned `無可靠公開預估` or a non-quantified fallback.

R9 keeps the R8 current-order grammar unchanged and expands only the fulfillment-schedule grammar.

## Semantic boundary

A recognition/fulfillment schedule is **not a forecast of new orders**.

The LINE-facing text must therefore use wording such as:

- `公司預期約39%的該RPO於未來12個月認列；這是既有合約履約節奏，不等於新增訂單預測`
- `公司預期幾乎全部既有backlog於未來12個月內履行；屬既有訂單履約節奏，非新增訂單預測`

It must never transform an RPO percentage into an invented future booking number.

## Real filing forms covered

R9 recognizes these evidence-bound forms while preserving issuer wording/precision:

- numeric percentages: `39% ... will be recognized`, `expects 46% to be recognized`, `expected to recognize 64%`, `expect to recognize approximately 60%`;
- explicit amount schedules: `$144 million is expected to be recognized in the next 12 months`;
- worded fractions: `approximately one-third` is retained as `約三分之一`, not silently converted to a decimal;
- fiscal-year precision: `expects to recognize over the next fiscal year` remains `下一會計年度` rather than being rewritten as calendar 12 months;
- explicit multi-period schedules such as CF Industries' 2026 / 2027–2029 / 2030–2032 buckets;
- backlog fulfillment language such as `nearly all ... backlog will be filled within the next 12 months`.

## Current Top20 examples from the R8 audit

The following current rows have explicit schedule evidence that R8 did not fully surface:

- MU: approximately one-third of disclosed RPO expected over the next twelve months.
- NVDA: approximately 39% over the next twelve months.
- CRDO: disclosed RPO expected over the next fiscal year.
- PLTR: approximately 43% over the next 12 months.
- APH: nearly all disclosed backlog expected to be filled within the next 12 months.
- AVGO: approximately 30% over the next 12 months.
- Life360 (LIF): 46% over the next twelve months.
- NET: 64% over the next 12 months.
- CF: explicit multi-period recognition buckets.
- SMCI: approximately 60% over the next 12 months.

AMD's explicit `$144 million` next-12-month schedule was already correctly captured and remains a regression fixture.

## Amount formatting

R9 canonicalizes `$ 31.9 million` to `$31.9 million` (and analogous values) only for display consistency. It does not alter the amount or unit.

## Safety gates preserved

R9 must preserve all prior fail-closed behavior:

- `$71.3 million` supplier-capacity deposits in CRDO cannot become backlog;
- bare `$946` cannot become RPO;
- acquired-backlog amortization cannot become current backlog;
- RPO remains labelled `RPO（剩餘履約義務；非全部客戶訂單）`;
- no LINE delivery or Production mutation occurs in H6B1.
