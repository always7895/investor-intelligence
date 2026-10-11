# Public EOD options scope decision (O11/O12, DESIGN ONLY)

[Options source review](OPTIONS_SOURCE_REVIEW.md) · [Public options provider rights review](PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW.md) · [Public source rights review](PUBLIC_SOURCE_RIGHTS_REVIEW_20260909.md) · [Current acceptance](../state/STATUS.md)

**Status: DESIGN_PROPOSED, awaiting an independent review and the operator's scope decision.** This document is not a rights decision and not an admission. It grants no rights, admits no provider or scope, enables nothing, and changes no code, catalog, validator, Worker surface or test. Public admissions stay NONE.

## Question

Daily TAIFEX end-of-day option observations (dataset 11320) can be collected locally (`--source taifex_options_eod`, rows carry `publication_eligible=false`, `line_quote_eligible=false`, `executable_quote=false`). May any of those values be shown publicly, for example in the LINE bot, and in what form? O11 (the product surface) and O12 (the rights and scope decision) are one decision: the licence evidence for 11320 already exists, so what is open is the scope choice and, for option B, a mechanism amendment.

## Facts this design relies on

- **Dataset 11320 licence.** The dataset page states the Open Government Data License v1 and free use ([`PUBLIC_SOURCE_RIGHTS_REVIEW_20260909.md`](PUBLIC_SOURCE_RIGHTS_REVIEW_20260909.md)). Section 2(1) grants reuse that includes reproduction, distribution and public transmission without limit of purpose, time or territory. Section 3(2) requires the attribution statement in the manner the licence annex requires; failing it, the licence is treated as never granted. The review requires provider, dataset name and version where supplied, year, dataset URL and licence link to be kept, and downstream presentation must keep the attribution. The licence does not guarantee accuracy or imply endorsement. The grant covers that dataset only, not unrelated TAIFEX commercial feeds, real-time data or website scraping. The catalog entry `taifex_public_options` records `rights_status` `reviewed_public_access`, `automated_access_allowed` true, `rights_reviewed_at` 2026-09-09, `adapter_status` `candidate_implemented`, `runtime_enabled` false, `line_quote_eligible` false.
- **Dataset 11321 (Delta, contract-day reference).** Its licence has not been reviewed. It stays excluded from every option below until its own review ([`PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW.md`](PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW.md) and the dataset-11321 rights item); that review needs external retrieval and is not done here.
- **EOD row semantics** ([`OPTIONS_SOURCE_REVIEW.md`](OPTIONS_SOURCE_REVIEW.md)): last best bid/ask carry no per-quote timestamps; no midpoint, currency, multiplier, expiry day, days to expiry or Greeks are inferred; crossed values are labelled anomalous, non-executable observations; session rows and open interest are never combined; the collector's date ceiling of seven calendar days is not an exchange-calendar or LINE current-quote qualification.
- **Admission mechanism** (L-RIGHTS, [`PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW.md`](PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW.md)): public display is decided only by the canonical catalog. An admitted scope has exactly `jurisdiction`, `venue`, `instrument_kind` (`equity_option` only), `quote_basis` (`delayed` only) and `publication_scope` (`public_line_quote` only). EOD, theoretical and settlement observations are therefore never upgraded to quotes, and a flag in the catalog cannot admit them.

## Option A: keep EOD local-only (current state)

EOD observations remain local research data: collected on explicit command (or the optional local task, see the O10 plan in the options review), never selected by default, never published, never shown in LINE. No change to code, catalog or admission. The 11320 licence evidence stays on file for a later decision.

Consequence: no public Taiwan option reference. Cost: none. This is also the fallback if option B is declined or fails review.

## Option B: public, date-only reference surface (needs operator decision and a mechanism amendment)

A separate public record type, never a quote. Everything below is proposed design, not implemented.

**Record schema (closed, proposed).** `schema` id and version; `source` block: `provider` (Taiwan Futures Exchange), `dataset_id` (11320), dataset name and version as supplied, `year`, `dataset_url`, `license` name and `license_url`, plus the licence annex attribution statement text exactly as the annex requires (to be copied from the licence page at implementation time; not retrieved here); `trade_date` (one date, no time of day); `contract` identity fields exactly as the collector validates them (series, month or week, strike, right, session kept separate); `settlement` and `close` values and open interest as reported, null when absent; `anomaly` flag for crossed values (shown only as a labelled observation, or omitted); `executable_quote` always false; `observation_class` fixed `eod_reference`. Absent by construction: any quote timestamp, midpoint, days to expiry, annualized yield, Greeks, 100-share-lot inference, currency or multiplier the source does not state, and any owner or portfolio context.

**Admission scope (mechanism amendment).** The existing scope vocabulary cannot carry this record: a new `quote_basis` value (for example `eod_reference`) and a new `publication_scope` value would have to be added to both validators (`public_options_provider_gate.py` and the Worker admission helper), the pinned vocabularies, the catalog audit and every fixture that mirrors them, while `delayed` and `public_line_quote` keep their meaning. This is a mechanism change, not a flag flip: setting `line_quote_eligible` or `runtime_enabled` on the existing entry would not admit EOD and must not be attempted. The new scope must be unreachable from the quote path (a quote row can never claim it, an EOD row can never claim the quote scopes), and the catalog entry would need a real, non-future `rights_reviewed_at`, a `review_valid_through`, an `adapter_reviewed` adapter (today `candidate_implemented`), and the paired runtime flags, each set only by a reviewed change.

**Worker surface and labels (proposed zh-TW wording).** A separate, clearly labelled reference view, not the option-quote view and not any order or covered-call guidance. Example label: 「資料日期：YYYY-MM-DD｜臺灣期貨交易所日終資料，非即時報價，不可作為下單價格」, followed by the attribution line naming the provider, dataset (11320), year and licence with its link. No wording that implies a current price, a recommendation, a yield or government endorsement. Final wording is reviewed for zh-TW and English consistency at implementation.

**Freshness rules (proposed).** The dataset updates daily; the surface shows `trade_date` always and treats a record older than a pinned limit as stale and unavailable (never a cached or substituted value). The limit is an operator pin, proposed at the last trading day plus one calendar day of publication lag, and never looser than the collector's seven calendar days. A missed collection day shows the older date honestly or the fixed unavailable reason; it is never filled.

**Acceptance tests a later implementation GO must pass.** Schema closure (unknown fields refused; forbidden derived fields absent); attribution presence on every rendered record and refusal when any attribution field is missing; the admission scope is distinct and cross-unreachable (a quote row claiming it, an EOD row claiming a quote scope, a catalog flag flip alone: all refused); `executable_quote` false and no quote-style fields in any output; stale and missing-date states render the fixed unavailable text; the Worker, sealed publisher and Python validators agree on the vocabularies (same-source import, no second list); privacy and IBKR separation unchanged (no owner, portfolio or broker context in the record or the view); dataset 11321 values cannot reach the surface; fresh source-bound live proof and the Production rollout gates of the repository contract before enablement.

## Recommendation (not a decision)

Option A for now: it needs nothing, loses nothing, and the 11320 evidence stays valid. Reconsider option B only if the operator wants a public Taiwan reference view and accepts the mechanism amendment and its rollout; start with the O10 local collection to see whether the data are stable enough to publish. Dataset 11321 stays out until its own licence review.

## Decisions for the operator

1. Choose A or B (rights and public-output scope; this document cannot).
2. If B: approve the mechanism amendment as a bounded implementation lane, the freshness pin, and the attribution wording after a licence-annex check.
3. Separately, for any production display: Fable 5.1 go/no-go and current-session Production authorization (Worker, schedules, LINE delivery stay separate boundaries).

Status line for the record: O11 DESIGN_PROPOSED; O12 11320 licence evidence ALREADY_DONE (not an admission), scope decision awaiting the operator, 11321 licence review NEEDS_EXTERNAL.
