# Options source review (development checkpoint)

No new provider is activated by this review. Free access does not establish redistribution rights. Public LINE remains isolated from brokerage accounts. Existing prohibited-provider decisions remain intact pending explicit, evidenced policy review.

## Independent delivery paths to investigate

| Source | Evidence | Appropriate scope / unresolved limitation |
| --- | --- | --- |
| Alpaca | https://docs.alpaca.markets/us/docs/historical-option-data | Official API documents a free indicative derivative of OPRA and history since February 2024. Indicative prices are not executable NBBO. Credentials, public redistribution and compatibility with free-only/non-broker policy remain unreviewed. |
| Tradier | https://docs.tradier.com/docs/market-data and https://docs.tradier.com/docs/authentication | Official API documents brokerage real-time options and 15-minute delayed sandbox data. Public applications require contacting Tradier. Existing catalog prohibition is NOT overturned by API availability. |
| Yahoo/yfinance | Existing development provider policy | One origin regardless of wrapper/package count; not reviewed for live public LINE publication. |

These are research candidates, not implemented adapters or independent economic observations: multiple vendors may redistribute the same OPRA origin. Exchange contract/open-interest references cannot substitute for timestamped contract-level bid/ask.

## Implementation acceptance

- Match underlying, expiry, right, strike, multiplier and adjusted deliverable before comparison.
- Preserve vendor, upstream origin, quote time versus retrieval time, feed type and entitlement/rights decision.
- Reject nonfinite/negative prices, crossed quotes, stale/future observations and mismatched contracts; preserve missing volume/OI/Greeks rather than inventing zeros.
- Never average incompatible timestamps or label indicative/delayed prices executable.
- Provider failure must be explicit per ticker; preserve good primary results without inventing missing watchlist coverage.
- Exercise actual public builder and local orchestration separately with synthetic transports; no account data in public fixtures.

## Bounded review allocation

One writer integrates. Small-model reviewers, if available, receive only a file list and bounded read-only question (catalog rights, caller graph, or test gaps). Higher-capability review is reserved for privacy/publication invariants and final diffs. No reviewer tools were available in the current harness discovery, so no delegated model execution or token savings are claimed. Do not switch the existing inference Router or install another agent to simulate delegation.
