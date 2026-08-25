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

## Current outcome

No production public option BID/ASK provider is selected. The shared LINE Bot therefore remains fail-closed for live option quotes. The releasable zero-cost mode supports public contract education and a deterministic manual calculator only when the user supplies ticker, option type, expiration/DTE, strike, BID, ASK and spot; those values are labelled unverified and are never treated as fetched market data. Independently attested public snapshots may be enabled only after a future provider passes rights, redistribution and adapter review. The bot never falls back to IBKR, a brokerage account, private holdings or a paid service.
