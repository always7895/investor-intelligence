# Source diversity audit / 資料來源多元化稽核

Operator rule (2026-09-26): no data product may depend on a single source. 任何資料產品都不得單一依賴一個來源。

Audit of 2026-09-26 (updated the same evening): read-only inventory by Gemini 3.8 (steps of `scripts/run_daily_data_refresh.ps1`, the sealed run and
the Worker readers), verified against the code and the runtime log by the writer. A source that is the statutory
authority (SEC filings, an exchange's own listing or option chain) has no independent free equivalent; there the rule is
met by a cached last good value, an age limit and an explicit unavailability reason, never by a guess.

## Matrix

| Product | Primary | Second source / fallback | State 2026-09-26 |
| --- | --- | --- | --- |
| Stock lookup price | exchange price shard (`loadListingPrice`, official daily feeds) | Yahoo quote (hourly) as the cross-check | two sources |
| Covered-call spot price | Yahoo quote | Alpha Vantage `GLOBAL_QUOTE` for a US listing Yahoo cannot quote (DPAPI key, daily budget) | two sources (US) |
| US option chains | Yahoo option chain | Nasdaq US option chain for a cycle Yahoo cannot read (operator 2026-09-26: Nasdaq data accepted) | two sources |
| Stockholm option chains | Nasdaq Nordic (the exchange) | none free | exchange authority; DEFERRED_WITH_REASON |
| Market corroboration (sealed run) | Yahoo | Nasdaq historical, stooq, hfmarketdata | Nasdaq restored (ISO query dates); stooq unreachable from this host; hfmarketdata frozen at 2026-09-03 |
| Price shards | one official feed per market (Yahoo for Japan/Korea) | previous shard within its age limit | **single per market**: OPEN |
| Identity shards | one official directory per market | previous shard | **single per market**: OPEN (US: SEC `company_tickers_exchange.json` candidate) |
| Broad options universe | Nasdaq stock screener, Stockholm screener | daily cache, 7-day stale fallback | cache only: OPEN (low) |
| SEC company reports, 13F, bottleneck filings | SEC EDGAR | last good file | statutory authority; DEFERRED_WITH_REASON |
| Serenity signals | third-party GitHub archive | local archive cache | **single**: OPEN |
| Chinese names | TWSE/TPEx short names, Chinese Wikipedia, Wikidata, `config/company-zh-names-v1.json` | cache | multiple |
| Taiwan monthly revenue (research MCP) | TWSE OpenAPI (listed), TPEx OpenAPI (OTC) | none per market | **single per market**: OPEN (low) |
| Top20 fundamentals | SEC XBRL (US filers); Yahoo quarterly income statement elsewhere | Taiwan: TWSE/TPEx monthly revenue; Stockholm (SIVE): the issuer's Cision interim report, one feed read a day (`fundamentals.cross_check`, beside the Yahoo quarter) | Taiwan and SIVE two sources; Korea, Japan **single**: OPEN |
| Top20 card price | Yahoo adjusted daily close (returns) | exchange close from the price shards (`market.cross_check`) | two sources where an exchange feed exists |
| US consensus | Yahoo analyst estimates | Nasdaq.com targets and EPS (`consensus_second`), shown beside, never averaged | two sources; outside the US **single**: OPEN |

## Decisions

- Cboe delayed option quotes stay rejected: its official page prohibits automated extraction
  ([PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW](PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW.md)). One read-only request was made to it
  on 2026-09-26 while evaluating, before the review was consulted; it is not used.
- The second US option-chain source is the Nasdaq public option chain, used only for cycles Yahoo cannot read (operator
  2026-09-26: Nasdaq data accepted); its observations carry `rights_status: candidate_local_review`.
- Keyed free APIs (for example Alpha Vantage, OpenDART, FRED) need the operator's own registration; the key is stored
  DPAPI-protected like the SEC contact and never in the repository.
- Cision (news.cision.com) carries Stockholm issuers' MAR releases; its robots.txt allows the release RSS and pages. MFN's
  robots.txt disallows its RSS feeds, so it is not used.
- Research agents reach official keyless data through the read-only MCP server `scripts/public_data_mcp.py` (SEC EDGAR,
  TWSE/TPEx monthly revenue).

## Next steps (in order)

1. Official fundamentals beside Yahoo for Korea: Samsung's IR statement PDF needs a PDF parser outside the hash-locked
   requirements; SK hynix's newsroom terms forbid robots (a curated per-quarter config only). Keyless only.
2. Second identity/price sources per market, starting with the US (SEC directory; Yahoo daily close as the price fallback
   already used for Japan and Korea).
3. A replacement for the frozen hfmarketdata corroborator; stooq only if it becomes reachable again.
4. A second Serenity signal source; consensus outside the US.
