# Public options provider rights review

_Last reviewed: 2026-08-25_

This document records provider-admission decisions for the shared public LINE Bot. A page being viewable without payment does **not** establish permission for automated collection, API use, republishing or redistribution. Catalog membership never activates a provider.

## Mandatory admission conditions

A production public option BID/ASK provider must satisfy all of the following at the same reviewed revision:

- the source is authoritative for the quoted market or is an explicitly licensed public-data provider;
- automated access is affirmatively permitted by the governing terms, not merely technically possible;
- the project may display or redistribute the required fields to LINE users;
- access remains free and has no paid fallback, trial-expiry dependency or automatic plan upgrade;
- a static reviewed adapter, closed output schema, source timestamp and delay classification exist;
- runtime activation and LINE eligibility change atomically only after tests pass;
- no IBKR, brokerage-account, portfolio, holdings or private-user data enters the shared path.

## Reviewed decisions

### Cboe U.S. Options public market data — rejected for automation

- Provider ID: `cboe_public_options_market_data`
- Rights status: `automated_access_prohibited`
- Runtime / LINE eligibility: disabled
- Adapter status: `not_permitted`
- Official market page: `https://www.cboe.com/us/options/market_statistics/`
- Rights evidence: `https://www.cboe.com/delayed_quotes/options_quotes/`

The official delayed-options page expressly prohibits auto-extraction programs, queries and software. The project therefore must not scrape, automate or republish that interface. Manual browser availability is not a machine-data license.

### OCC public market data reports — rejected for automation

- Provider ID: `occ_public_market_data`
- Rights status: `automated_access_prohibited`
- Runtime / LINE eligibility: disabled
- Adapter status: `not_permitted`
- Official market reports: `https://www.theocc.com/market-data/market-data-reports`
- Governing terms: `https://www.theocc.com/specialpages/legal/terms-and-conditions`

OCC publishes examples for batch-processing report URLs, but its governing Terms of Use prohibit launching automated systems to access the services and restrict reproduction or exploitation. The stricter governing terms control this admission decision; an example URL is not permission for a shared bot to ingest or redistribute data.

### Market Data Free Forever — rejected for shared redistribution

- Provider ID: `marketdata_app_free_forever`
- Rights status: `automated_access_prohibited` for this shared-bot use case
- Runtime / LINE eligibility: disabled
- Adapter status: `not_permitted`
- Official plan details: `https://www.marketdata.app/pricing/`
- Redistribution policy: `https://www.marketdata.app/docs/account/data-policies/data-redistribution/`

The free plan offers capped 24-hour-delayed options data, but its self-service license is personal/internal. The official redistribution policy forbids exposing recent data to other users through an application or shared workspace. A commercial and exchange redistribution license would be required, so this source cannot satisfy both shared-LINE and free-only requirements.

### Tradier brokerage market-data API — rejected for the shared bot

- Provider ID: `tradier_broker_market_data_api`
- Rights status: `automated_access_prohibited` by the project's permanent broker boundary
- Runtime / LINE eligibility: disabled
- Adapter status: `not_permitted`
- Official API/onboarding page: `https://trade.tradier.com/buildtotrade/`

Tradier couples options market data with brokerage onboarding, account funding, trading and account-management capabilities. The shared LINE architecture permanently forbids broker-account entitlements, broker tokens and any LINE-to-broker bridge. A technically available broker API is therefore not an admissible public-data provider for friends.

These four decisions are pinned in `scripts/public_options_provider_gate.py`. Changing a status flag, adding an adapter or setting runtime eligibility cannot override the prohibition.

## Pending candidates

Nasdaq, NYSE, CME, Eurex, HKEX, TAIFEX, JPX/OSE and ASX remain metadata-only candidates. For each one, the project still needs direct evidence covering automated access, free-tier continuity and redistribution/display rights for the exact quote fields. Until that review is complete:

- `automated_access_allowed` remains `null`;
- `rights_reviewed_at` remains `null`;
- adapters remain unimplemented;
- runtime and LINE eligibility remain false.

Commercial feeds, temporary trials, broker entitlements and sources that require a paid fallback do not satisfy this project.

## Development-only provider

`yfinance_unreviewed_delayed` remains a local development fixture only. It is not an official authority, its delay and rights posture are not sufficient for external current-data publication, and it cannot be promoted by changing configuration flags. It may support synthetic and local tests while all external live-data switches remain off.

## Public admission mechanism (L-RIGHTS, source text; tests NOT_RUN)

Local research data and public display are separate. `scripts/build_market_quotes_options.py` keeps writing honest local-candidate labels (`candidate_local_review`, `unadmitted_third_party`) and the shared validators (`scripts/validate_v213_market_products.py`, Worker `validateCoveredCallCycle`, `validateOptionContractQuote`) are FORMAT checks only. A rights label, `source` text, currency, free-form provenance, an `admission_status` string or any caller-supplied flag never admits a row for public display. Admission is decided only by the canonical catalog `config/public-options-provider-candidates.json`, the single authority: Python loads it through `public_options_provider_gate.py` (`load_public_option_policy`, built on the same audit and one shared `_rights_reviewed` predicate) and the Worker imports the SAME file at build time in `cloud/src/v213/public-options-admission.ts` (`admitPublicOption`, an immutable projection, not a second editable list; no Wrangler allowlist, copy or invented hash). Any missing, malformed, unselected, stale or scope-less state denies. The Worker helper validates the WHOLE imported catalog before it considers any requested entry, matching the catalog-local rules of `audit_public_options_providers` and `_scope_findings`: root `schema_version` 2, the four root `false` flags and the unknown-field rule; at least eight object providers with unique non-empty ids and the exact required/optional field set; strict types, status vocabularies and per-status rules; review dates and safe HTTPS URLs; the pinned automation-prohibited decisions and their presence; paired runtime/LINE booleans with a reviewed adapter; optional scope and review-window validity on EVERY provider, inactive ones included; the authority/jurisdiction/role diversity minima; and root selection versus the fully eligible set (truth table below). One malformed unrelated provider makes the whole imported policy unusable, as in Python. The field names, vocabularies and pinned ids are safety-invariant constants mirrored in Python and TypeScript, not a second approval catalog. The Python audit also reads repository context that a deployed Worker cannot see (`cloud/wrangler.toml` CURRENT_PUBLIC_DATA_ENABLED, the development-provider file, `runtime-policy.json` and the builder source): those are gate-context checks, not catalog facts, and the Worker does not claim to run them. Source differences that stay UNPROVEN until verification: URL parsing (`new URL` versus `urlsplit`), Python's lenient `str()` coercion of non-string ids, authorities and roles (the Worker is stricter), and date handling at the UTC day boundary.

Admission requires ALL of: root `production_quote_provider_selected` is the boolean `true` and the other root flags are `false`; exactly one provider with the claimed `provider_id`; `rights_status=reviewed_public_access`, `automated_access_allowed` true, `adapter_status=adapter_reviewed`, and the paired booleans `runtime_enabled` and `line_quote_eligible` both true (strict types: the string "true" is not true); safe HTTPS `official_url` and `rights_evidence_url`; a real, non-future `rights_reviewed_at`; and the new fields below. The row must carry the identity it claims (`provider_id`, `jurisdiction`, `venue`, `instrument_kind`, `quote_basis`, `publication_scope`) and all of it must equal one admitted scope of that provider; identity is never guessed from labels, currency or provenance text.

New provider fields, OPTIONAL while the provider is disabled and REQUIRED and fully validated once it is enabled (both validators, `public_options_provider_gate.py` and the Worker helper, apply the same rules; no value is inserted into the catalog by this batch, and existing disabled providers need not acquire them):

- `review_valid_through`: a real `YYYY-MM-DD` date, not before `rights_reviewed_at` and not before today. It is a review-freshness window, not a license expiry.
- `admitted_scopes`: a non-empty array of objects with EXACTLY the string keys `jurisdiction` (one of the provider's `jurisdictions`), `venue` (`^[A-Z0-9][A-Z0-9_.-]{0,31}$`), `instrument_kind` (`equity_option` only), `quote_basis` (`delayed` only) and `publication_scope` (`public_line_quote` only). EOD, theoretical and settlement observations are therefore never upgraded to quotes by this mechanism, and a malformed scope invalidates the whole review.

Enforcement points: the sealed publisher `scripts/publish_sealed_snapshot.py` (`lazy_market_bodies`) admits each cycle on its own before it joins `v213:options:v2` and replaces a refused cycle with the fixed unavailable reason `OPTION_RIGHTS_NOT_ADMITTED`; the Worker loader `loadDetailedOptionObservation` returns the typed status `RIGHTS_NOT_ADMITTED` after the structural read and before any quote is returned, `rich-menu.ts` shows a truthful unavailable report, and `buildCoveredCallMessages`, `buildOptionContractBubble/Flex/Text` and `validateOptionContractQuote` re-check independently, so a new caller or an older sealed payload cannot bypass the loader. No cache or stale-quote fallback exists. Admission is always judged against the real current time: the loader uses the request clock, the renderers use the current clock, and `validateOptionContractQuote`'s `evaluatedAt` or any payload time cannot extend a review window. If the review window closes between the loader and a renderer, the renderer throws the dedicated typed `OptionRightsNotAdmittedError` and `rich-menu.ts` catches only that class and returns the same truthful unavailable report; any other error still propagates and expired data stays refused.

Current outcome of the mechanism: the catalog is unchanged and selects no provider (root `false`, every provider disabled), and the current builder emits no provider identity, so every public options cycle is refused with the fixed reason. This closes a false-admission path; it is NOT global options coverage and no provider is enabled. A future enablement needs a real, evidenced rights review that fills the fields above, a builder that emits the claimed identity for a real adapter, and the later gates. User approval is not a license. Limits: build-time JSON import, packaging and same-source identity of the Worker projection are verified by later gates (NOT_RUN); the Python policy snapshot is a deep copy whose accessors return deep copies (protection against accidental mutation only: in-process code can still construct the class or monkeypatch the module, and no unforgeability is claimed); the existing tests and the committed Worker fixture assume the old publication behavior and need regeneration in the verification phase.

### Root selection truth table (R2 repair of a contradiction)

The Python audit used to require `production_quote_provider_selected` to be `false` unconditionally and, in a later rule, to be `true` when a provider is fully eligible, which made lawful future admission impossible. The root tuple of always-`false` flags no longer contains it. `production_quote_provider_selected` must be a strict boolean (checked by both validators) and must equal whether any provider is fully eligible; the existing consistency branches are unchanged and no other root flag or provider check is weakened:

- not a boolean: invalid.
- `false` with no fully eligible provider: structurally valid when every other catalog check passes, admits nothing (the current catalog, byte-identical, is this case).
- `true` with no fully eligible provider: invalid.
- `false` with a fully eligible provider: invalid (an explicit selection is required).
- `true` with a fully eligible provider: can admit a row only after every whole-catalog invariant, the review window and scope, the pinned restrictions and the exact claimed-identity join pass; a row never self-grants.

This repairs source logic only: it enables no provider, grants no rights, edits no catalog or configuration value and activates no public data. The Worker also refuses a provider id with leading or trailing whitespace instead of normalizing it (Python trims ids before its duplicate and pinned-id checks, so an untrimmed id could hide a trimmed duplicate); canonical ids are unaffected and this typed-string rule is stricter than Python. The Wrangler, development-provider, runtime-policy and builder-source checks remain additional Python repository/release gates and are not reimplemented in the Worker. All of it is source-traced only, tests NOT_RUN; existing gate tests that assume the old always-false root rule need updating in the verification phase.

## Global options SOURCE and GAP status (G1A, source text; tests NOT_RUN)

The command `全球期權來源與缺口` (also `全球期權來源`, `期權來源與缺口`) shows a PUBLIC, METADATA-ONLY page: what the unchanged canonical catalog DECLARES and what the sealed R75 snapshot actually contains. It is not a quote product, not live and not a coverage guarantee, and it is reachable from the options entry text and from the uncovered-market answer. `config/option-adr-map-v1.json` and its `covered_markets` are untouched: they stay the actual covered-call routing scope, and this page adds no market, ADR or chain support.

Wire format: the exact new lazy key `v213:options-coverage:v1` on the existing sealed snapshot (no second storage or route), built by `lazy_options_coverage_body` in `scripts/publish_sealed_snapshot.py` only when the market-observation lane runs, allowed by the mirrored whitelists `SNAPSHOT_LAZY_KEY_RE` (`snapshot-seal.ts`) and `LAZY_KEY` (`scripts/fetch_live_public_snapshot.py`; the first G1A allowlist named a non-existent `v213_live_source.py`, a master contract error corrected before any edit); the existing 80-key and byte budgets are unchanged. Strict bounded closed schema (`validate_options_coverage_document` and the Worker `validateOptionsCoverage`): at most 32 providers, 32 jurisdictions, 8 local capabilities and 64 observed rows, 200000 bytes, a fixed vocabulary and no strike, bid, ask, settlement, Delta, premium or private field. Providers and jurisdictions are DERIVED from the actual catalog JSON (a catalog count is a catalog count, never "N independent confirmations"; origin lineage is unknown here, so no corroboration metric exists and no corporate group is treated as one lineage family); jurisdictions that the catalog does not list are not invented and the page says that absence is not coverage. Local covered-call paths are shown from `covered_markets` as `LOCAL_UNADMITTED_NO_CATALOG_IDENTITY`: a local candidate path with no catalog identity, not an admission. Source documentation, a declared provider or an adapter is shown as DECLARED/UNVERIFIED, never as collected, live, qualified or complete.

Observed admitted rows (count and quote as-of) come only from this publisher's own `v213:options:v2` body, counting only cycles that the canonical policy admits again (`public_option_cycle_admission`), and carry the sha256 and byte length of that very body as a link. The Worker (`options-coverage.ts`) never trusts the body. It rejects a raw sealed body over 200000 UTF-8 bytes BEFORE `JSON.parse`, validates the strict shape, and DERIVES every declared section itself from the SAME canonical catalog and the SAME unchanged ADR map it imports, requiring exact equality: every provider row including `name`, unique ids, the jurisdiction to unique provider-id relation built from the literal declared codes only (a `GLOBAL` role code is its own row and never expands to countries), and the local routing markets from the `covered_markets` KEYS; a skewed or forged body is `COVERAGE_SCHEMA_INVALID`, and the page prints the derived projection, never body fields. The actual catalog has 12 entries (Cboe, OCC, Market Data, Tradier, Nasdaq US, NYSE, CME, Eurex, HKEX, TAIFEX, JPX/OSE, ASX) and no SGX, KRX, NSE or Canadian entry; an earlier master sentence that named them was a master documentation error and the unchanged JSON is the authority. The `covered_markets` declaration is a routing scope, not observed data, and a local producer path without a catalog identity does not mean a whole country has no catalog source. It then rechecks the link against the sealed options body and recomputes every observed row under the SAME rules as the real public loader (`loadDetailedOptionObservation`): a canonical document clock at most 5 minutes in the future and 6 hours old, the v2 shape, ONLY the `weekly` and `monthly` keys, producer-unavailable entries stay unavailable, `validateCoveredCallCycle` with its period, a canonical quote instant, and `admitPublicOption`; the Python helper re-applies the same rules even when called standalone. A row it cannot prove is UNKNOWN, never zero and never assumed, and retrieval time is never an as-of. `ticker_key_count` is the number of distinct sealed option-document ticker keys, NOT native underlyings, ISINs or chain completeness. The G1 instant is the canonical UTC form only (seconds or exactly three fractional digits, a real calendar date, year 1 to 9999, so no February 30 and no year 0000), in both implementations.

The verified result is issued through a module-private `WeakMap` keyed by the identity of a frozen wrapper that exposes only a status; the deeply frozen projection never leaves the module, so a spread, a clone, JSON or a hand-built object (a symbol property is copied by spread and is NOT protection) has no identity in the map and renders as unavailable, and mutating anything a caller holds changes nothing. At render time the page rechecks the real current clock, the document and counted-cycle freshness windows and the canonical admission of every observed row (no network), so a projection cannot outlive its validity; this is not a sandbox against arbitrary privileged code. Output is complete bounded pages (at most 5 messages of at most 4400 characters, every page carries the caveat, the last carries the navigation, at most 24 observed rows with an explicit omitted count, lines are never cut); a result that cannot fit even in compact form is typed unavailable instead of silently truncated. Typed outcomes stay distinct: `SNAPSHOT_UNAVAILABLE`, `COVERAGE_ABSENT`, `COVERAGE_SCHEMA_INVALID`, `COVERAGE_STALE` (6 hours) and `OK`. Current facts: the catalog selects no provider, so zero providers are publicly admitted and the observed rows are verified empty or UNKNOWN; this says nothing about what has or has not been collected elsewhere, and data completeness is NOT_REAUDITED. The delayed-covered-call scope of the admission gate is NOT broadened to EOD, index or Delta data, no catalog or policy value changed, and collection or scheduling hooks are unchanged (an internal-research or brief-quotation collection capability is not public redistribution approval).

Date parity fix (G1A amendment): the Worker `dayStart` now refuses year 0000 before `Date.parse`, because ECMAScript accepts it while Python dates start at year 1; nothing else about eligibility changed and the all-off catalog is unaffected. Limits: nothing was executed, built or run; the existing tests and fixtures that enumerate sealed lazy keys or snapshot contents need regeneration in the verification phase; the Worker catalog import, bundling and TypeScript typing remain unverified.

## Dataset 11321 local reference (G1B, source text; tests NOT_RUN)

`taifex_options_delta` (collector `--source`) and `taifex_delta` (manual importer) ingest TAIFEX dataset 11321 (`DailyOptionsDelta`) as a LOCAL_REFERENCE_ONLY collection; the exact schema, bounds and gaps are in [OPTIONS_SOURCE_REVIEW](OPTIONS_SOURCE_REVIEW.md). This is NOT a rights decision and NOT public admission: the canonical catalog still lists TAIFEX with dataset 11320 evidence only, every selection, runtime and LINE flag stays off, and no catalog value changed. Dataset 11321 carries its own free OGDLv1 attribution and would need its own review, plus a separate scope contract for any EOD or reference data, before any public use. The delayed covered-call admission gate is not broadened, the G1A public coverage object contains no EOD or Delta value, and neither TAIFEX feed is a default or scheduled source. A manual import is local and UNVERIFIED-origin even if the file claims TAIFEX, a receipt or a hash, and collection permissions (internal research, brief quotation) are not structured LINE quote permission.

## Current outcome

No production public option BID/ASK provider is selected. The shared LINE Bot therefore remains fail-closed for live option quotes. The releasable zero-cost mode supports public contract education and a deterministic manual calculator only when the user supplies ticker, option type, expiration/DTE, strike, BID, ASK and spot; those values are labelled unverified and are never treated as fetched market data. Independently attested public snapshots may be enabled only after a future provider passes rights, redistribution and adapter review. The bot never falls back to IBKR, a brokerage account, private holdings or a paid service.
