# European Central Bank (ECB) Reference Source Admission

## 1. Scope and Identity

This document records the admission review and configuration contract for the European Central Bank (ECB) daily EUR/USD reference exchange rate feed (`eu_ecb_fx_reference`).

- **Source ID**: `eu_ecb_fx_reference`
- **Display Name**: ECB EUR/USD daily reference rate
- **Authority Class**: `central_bank` (Tier 1 Primary Official: `T1_PRIMARY_OFFICIAL`)
- **Publisher**: European Central Bank
- **Independence Group**: `eu_ecb` (shares publisher lineage with `eu_ecb_data`; does NOT constitute an independent second corroboration family relative to other ECB publications)
- **Jurisdiction**: EA (Euro Area)
- **Language**: `en`
- **Roles**: `macroeconomics`, `foreign_exchange`
- **Claim Type**: `macro_indicator`
- **Admission Status**: `RUNTIME_ENABLED`
- **Adapter ID**: `eu_ecb_fx_reference` (`implemented`)

The existing catalog entry `eu_ecb_data` remains disabled (`runtime_enabled: false`) with its original 1800-second freshness policy unchanged.

## 2. Licensing, Rights, and Canonical Terms

Use of the ECB reference rate data is governed by the official ECB disclaimer and copyright notice:

- **Canonical Terms URL**: `https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html`
- **Raw License URI**: `http://www.ecb.europa.eu/home/html/disclaimer.en.html`
- **Attribution**: "European Central Bank" (mandatory attribution preserved in observation payload)
- **No Endorsement**: Use of the ECB name or reference rates does not imply endorsement, affiliation, or sponsorship by the European Central Bank.
- **Free Availability**: The source data is provided free of charge by the ECB. If downstream redistribution occurs, disclosure of the free availability of the underlying official ECB data prior to payment or subscription is required. This adapter selects the latest returned item without changing its rate. Any future data modification would require explicit disclosure under the ECB terms; attribution and free-availability notices remain required.

## 3. Network Transport, Feed URL, and Unfetched Item URIs

- **Actual Request Feed URL**: `https://www.ecb.europa.eu/rss/fxref-usd.html` (HTTPS transport with verified system + certifi TLS context, no proxy credentials, no cookies, no redirects).
- **Native Item URI Provenance**: The RDF/RSS 1.0 items include native URIs using the `http://` scheme (e.g., `http://www.ecb.europa.eu/stats/exchange/eurofxref/html/eurofxref-graph-usd.en.html?date=YYYY-MM-DD&rate=...`). These native item identifiers are retained strictly as unfetched provenance metadata (`original_item_uri`). They are NEVER rewritten to synthetic HTTPS URLs nor fetched directly.
- **Transport Security**: Transport verifies host identity (`www.ecb.europa.eu`), enforces exact URL matching against `ACQUISITION_ONLY_ENDPOINTS`, and disallows arbitrary network redirects or credential leakage.
- **Pre-Admission Transport Snapshot**: The audit artifact `ecb-transport-pre-admission.json` documents a pre-admission single public HTTP 200 GET verification. This snapshot is an immutable pre-admission transport record, NOT a live factory proof or operational release gate.

## 4. Operational Boundaries and Limitations

- **Informational Reference Only**: Reference exchange rates are published for information purposes only. The ECB explicitly discourages using euro reference exchange rates for transaction purposes.
- **No Trade Quotes or Issuer Claims**: The reference exchange rate is strictly a macroeconomic indicator (`macro_indicator`). It is NEVER reinterpreted as an execution quote, intraday price, bid/ask spread, or corporate issuer claim.
- **No Stock Ticker Discovery**: EUR/USD is a macroeconomic currency reference pair, NOT an equity ticker or stock ranking candidate. It is NEVER inserted into Top20 stock candidates or company research records.
- **Freshness and Calendar Coverage**: A freshness limit of 4 calendar days (345,600 seconds) accommodates standard weekend gaps conservatively between Friday reference rate publication (~16:00 CET) and Monday business hours. Long holiday closures (e.g., Easter TARGET closing days) exceed this window and deliberately fail closed to `STALE` / `UNAVAILABLE`. No artificial freshness extensions or synthetic clock manipulation are permitted.
- **Concurrency and Rate Limits**: Host concurrency is bounded to 1 request, with a minimum inter-request interval of 0.5 seconds, and 0 retries on failure.

## 5. Caller Architecture and Macro Reference Context

When public acquisition is active (`--acquire-public`), caller workflows receive:
1. `acquisition_summary`: Sanitized run statistics, hashes, and source-attempt diagnostics, not serialized health authority.
2. `macro_reference_context`: Populated ONLY from exact captured `eu_ecb_fx_reference` candidates for subject `EUR/USD`.
   - Schema version 1 with `reference_only: true`.
   - Standalone macro record reconciled through `reconcile_research_claims` with the active acquisition capability.
   - Evaluates as a single official Tier-1 macro indicator (`SINGLE_SOURCE`), which does not meet high-confidence multi-source criteria (`high_confidence_eligible: false`, `full_research_eligible: false`).
   - If no candidates are captured (e.g., circuit open, stale data, parse failure, or missing flag), `macro_reference_context` is omitted completely.
   - Saved or forged macro context from disk or cache is strictly ignored.

## 6. Gate Status and Opt-In Commands

- **Opt-In Execution**: Public source acquisition requires the explicit `--acquire-public` command-line argument in `v213_source_independence_gate.py`.
- **Mutual Exclusion**: `--offline` and `--acquire-public` are mutually exclusive; passing both aborts immediately before any I/O.
- **Staged Collector Exclusion**: `eu_ecb_fx_reference` is registered in `ACQUISITION_ONLY_ENDPOINTS` and is deliberately excluded from `fetch_public_source_observations.py` default sources and CLI `--source` choices.
- **Release and Line Gates Status**: Future factory verification, live production integration, and LINE publishing gates remain PENDING. This admission configuration validates adapter registration, source eligibility, and caller wiring; it does NOT constitute a finished production release claim.
