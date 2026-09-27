# Bottleneck-explosion Top20 v3 / 瓶頸爆發 TOP20

Status: live in LINE from 2026-09-26 (operator request: the Top20 must follow Serenity's bottleneck logic, exclude
negative long-term returns, rank future bottleneck explosions, and an industry analysis led by Leopold
Aschenbrenner's logic must name the most explosive industries from current events). Current Production state is in
[STATUS](../state/STATUS.md).

## Why the old Top20 differed from Serenity

- Candidates came from three generic Yahoo screeners (most actives, day gainers, undervalued growth).
- The scorer's `chokepoint` and `replacement_friction` factors were fixed at zero, so low P/E and revenue growth
  ranked insurers and retailers; price history was not scored, so negative long-term returns could rank.

## Pipeline

| Step | Script | Source | Cadence |
| --- | --- | --- | --- |
| Serenity leads | `scripts/serenity_signals.py` | public archive `yan-labs/serenity-aleabitoreddit` (post URLs) | 6 h |
| Leopold leads | `scripts/leopold_positions.py` | SEC 13F-HR of Situational Awareness LP (CIK 2045724) | 24 h |
| Layers | `config/bottleneck-layers-v3.json` | structure only: company role in a scarce layer, dated source | reviewed |
| Ranking | `scripts/bottleneck_top20_v3.py` | SEC XBRL companyfacts, Yahoo Finance (labelled unofficial), SEC full-text search | 3 h |
| Seal | `publish_sealed_snapshot.py --bottleneck-v3` | lazy object `v213:bottleneck-top20:v3` | hourly |

Leads weight conviction only; every figure users see comes from filings or market data with its source and date.

## Company score (0–100)

- COMPOUNDER (market cap ≥ US$10B): layer heat 25, company capture 30, lead conviction 20, market confirmation 15,
  size 10. EXPLOSION (< US$10B, often before volume revenue): 25 / 15 / 30 / 20 / 10.
- Capture: latest-quarter revenue YoY, acceleration, gross-margin change, remaining performance obligations,
  normalized over the evidence available (fiscal quarters; a fourth quarter is annual minus nine-month YTD).
- Penalties: share count +5% / +15% a year (SEC shares outstanding; without it, as for dual-class filers and Yahoo-sourced listings, the quarter's diluted weighted-average shares against the same quarter a year earlier, labelled 稀釋加權平均股數; a change outside -50%..+500% is treated as a data error), repeated financing concerns in Serenity's posts.
- Filters: one long-term standard — positive 2-year CAGR (an eligibility gate, not a score component). A security whose
  own regular-way trading is younger than two years because of a verified corporate event (spin-off, trading resumption,
  IPO, new equity after a reorganisation; `config/listing-lineage-v1.json`, every field backed by a primary source,
  checked by `scripts/listing_lineage.py`) uses the annualized return from its first regular-way session, never from
  when-issued trading or a parent's/predecessor's shares, and needs at least 365 days. A short history without a verified
  record is excluded as `HISTORY_OR_LINEAGE_UNVERIFIED` (a verified segment under one year: `MARKET_HISTORY_UNDER_1Y`); a
  missing figure is never read as a negative return. No clearly bearish Serenity stance; at most five names per layer.

## Industry ranking (產業爆發榜, Leopold-led)

Explosiveness = position on Leopold's chain (compute → power → datacenter → chips/memory → network/optics →
materials) 35 + the fund's 13F weight in the layer 25 + median revenue acceleration 20 + SEC filing mentions of the
layer's terms (last 30 days versus the prior 60) 10 + Serenity heat 10.

## LINE

Every card shows the same two returns: 6-month return and 2-year CAGR. A verified short segment reads 獨立交易價格未滿2年
with "<first regular-way session>–<as of> 正常交易以來年化 X%（非2年）" (a resumption: 恢復交易以來); the verified event
(e.g. "2025-02-21 自 Western Digital（WDC）分拆；2025-02-24 起正常交易") shows on every form, also when two years exist, and
the detail lists its primary sources; an unverified short history reads 2年價格資料不足 (可得價格自 <date>；上市沿革未核實),
never "new company". Serenity/Leopold lead scores weight the ranking but are not shown; the
card shows the signed-order floor instead (RPO on the recognition schedule of the latest 10-Q/10-K: 6M/1Y/2Y coverage
and the growth floor, or the explicit reason it cannot be computed). `瓶頸詳情` opens the SEC company report rather than
repeating the card; non-SEC filers get the filing and price figures with sources.

Names: the symbol, the sourced Traditional Chinese name and the original name. Sources, in order: the company's own
Taiwan registration (`config/company-zh-names-v1.json`, GCIS citation per entry), the Chinese Wikipedia article as shown
to zh-tw readers, the Wikidata zh-tw/zh-hant label (`scripts/build_zh_names.py`, weekly); Taiwan listings use the
exchange's Chinese short name. Without a source the card says 無公認中文名; nothing is translated. The same names are
in the identity shards, so the stock lookup shows them and accepts them as queries (e.g. 輝達).

Stock lookup prices: the watch-universe quote (hourly) when present, otherwise the listing's market price shard from
official bulk feeds (`scripts/build_price_shards.py`, every 3 h): Nasdaq stock screener (US, with its stated price
date), TWSE STOCK_DAY_ALL and TPEx daily close (Taiwan, trade date), Nasdaq Nordic (Stockholm; no trade date in the
feed, so the retrieval time is shown as such) and Euronext closing prices. Sealed as lazy `v213:prices:v1:<MARKET>`;
the Worker ignores a shard older than 4 days. Japan and Korea have no free official bulk price file: their common
stocks get Yahoo Finance daily closes once a day (labelled unofficial, each row with its own date). London Main
Market and AIM equities (for example IQE) come from the exchange's public price-explorer API, both as identities and
as last prices (no trade date in the response, so the retrieval time is shown); they are optional feeds, so an
outage there never blocks the other markets.

`TOP20` (v3 when sealed and fresh, else the seven-field Top20), `瓶頸詳情 代號`, `產業爆發榜`, `七欄Top20`.
The Worker refuses a v3 document older than the report bound (14 h) and falls back rather than showing stale data.
