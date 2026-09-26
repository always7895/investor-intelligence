# Source diversity audit / 資料來源多元化稽核

Operator rule (2026-09-26): no data product may depend on a single source. 任何資料產品都不得單一依賴一個來源。

Audit of 2026-09-26: read-only inventory by Gemini 3.8 (steps of `scripts/run_daily_data_refresh.ps1`, the sealed run and
the Worker readers), verified against the code and the runtime log by the writer. A source that is the statutory
authority (SEC filings, an exchange's own listing or option chain) has no independent free equivalent; there the rule is
met by a cached last good value, an age limit and an explicit unavailability reason, never by a guess.

## Matrix

| Product | Primary | Second source / fallback | State 2026-09-26 |
| --- | --- | --- | --- |
| Stock lookup price | Yahoo quote (hourly, watch and options universe) | exchange price shard (`loadListingPrice`, official daily feeds) | two sources |
| Covered-call spot price | Yahoo quote | none | **single**: OPEN |
| US option chains | Yahoo option chain | none | **single**: OPEN, see below |
| Stockholm option chains | Nasdaq Nordic (the exchange) | none free | exchange authority; DEFERRED_WITH_REASON |
| Market corroboration (sealed run) | Yahoo | Nasdaq historical, stooq, hfmarketdata | Nasdaq restored (ISO query dates); stooq unreachable from this host; hfmarketdata frozen at 2026-09-03 |
| Price shards | one official feed per market (Yahoo for Japan/Korea) | previous shard within its age limit | **single per market**: OPEN |
| Identity shards | one official directory per market | previous shard | **single per market**: OPEN (US: SEC `company_tickers_exchange.json` candidate) |
| Broad options universe | Nasdaq stock screener, Stockholm screener | daily cache, 7-day stale fallback | cache only: OPEN (low) |
| SEC company reports, 13F, bottleneck filings | SEC EDGAR | last good file | statutory authority; DEFERRED_WITH_REASON |
| Serenity signals | third-party GitHub archive | local archive cache | **single**: OPEN |
| Chinese names | TWSE/TPEx short names, Chinese Wikipedia, Wikidata, `config/company-zh-names-v1.json` | cache | multiple |
| Taiwan monthly revenue (research MCP) | TWSE OpenAPI (listed), TPEx OpenAPI (OTC) | none per market | **single per market**: OPEN (low) |

## Decisions

- Cboe delayed option quotes stay rejected: its official page prohibits automated extraction
  ([PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW](PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW.md)). One read-only request was made to it
  on 2026-09-26 while evaluating, before the review was consulted; it is not used.
- The second US option-chain source is the Nasdaq public option chain, which is `review_before_enable`: automated access,
  free-tier continuity and display rights must be documented before an adapter exists.
- Keyed free APIs (for example Alpha Vantage, OpenDART, FRED) need the operator's own registration; the key is stored
  DPAPI-protected like the SEC contact and never in the repository.
- Research agents reach official keyless data through the read-only MCP server `scripts/public_data_mcp.py` (SEC EDGAR,
  TWSE/TPEx monthly revenue).

## Next steps (in order)

1. Nasdaq option-chain rights review, then a fallback adapter for US option chains and the covered-call spot price.
2. Second identity/price sources per market, starting with the US (SEC directory; Yahoo daily close as the price fallback
   already used for Japan and Korea).
3. A replacement for the frozen hfmarketdata corroborator; stooq only if it becomes reachable again.
4. A second Serenity signal source.
