# Current state / 目前狀態

Updated 2026-09-26 (15:00 Asia/Taipei) by an operator-directed Claude Code session (master and writer; the operator granted full authority, 2026-09-25/26). Previous registers: V12 `git show 0f5358b:state/STATUS.md`; older history `git show 38860e7:state/STATUS.md`. Release identity stays in `README.md` (historical 2026-09-06 baseline).

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main` (pushed after every commit). PR CI only reports COMPLETED_SKIPPED; skipped is not PASS or release qualification.
- DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false.

## Production (2026-09-26 02:20Z)

- Worker `513b0444-baf1-4535-b14e-ac7661f7e662` (Chinese names with exchange-name priority, one return standard on Top20 v3 cards, market price shards incl. London/Japan/Korea, lazy-key limit 80; scheduled push off). Rollback order: `b9d270d5…`, `6a359ef1…`, `911fa6b2…`, `8f16c1db…`.
- Hourly task `InvestorIntelligenceSealedFreshness` (:12 local) runs the installed runtime (LOCAL_SOURCE_CHECKOUT `ba8e52f`, tx `0abef62a…`) with `-CarryForwardTop20 -SnapshotRoot data\v213-snapshots`. A manual seal `20260926T014136Z-16629307eb38` (60 lazy objects) passed the post gate `-ExpectTop20Records 20`; live replay probes: IQE.L → LSE:IQE 46.4 GBX, 2059 → TWSE 12350 TWD, 輝達 → NASDAQ:NVDA, 4062.T 23345 JPY, 005930.KS 285500 KRW; 15/20 Top20 v3 entries carry a Chinese name. Reinstalls happen outside :12 (the task's lock timeout is 0).
- **LINE TOP20 = bottleneck-explosion Top20 v3** ([BOTTLENECK_TOP20_V3](../docs/BOTTLENECK_TOP20_V3.md)). Cards: symbol｜sourced Chinese name (or 無公認中文名) and original name; 6-month return and 2-year CAGR on every card (younger listings: 上市未滿2年 + annualized since first day; the same standard excludes negative long-term returns); lead scores hidden; signed-order floor from the RPO recognition schedule or the explicit reason; 瓶頸詳情 opens the SEC company report (non-SEC filers: filing and price figures with sources).
- **Macro TOP5** is ranked by the opportunity score it shows (phase only breaks ties); the live order had put 57/56/55-point DISCOVERY industries below 42/35-point EARLY_VALIDATION ones.
- **Stock lookup**: identity shards (Nasdaq Trader, TWSE, TPEx, Nasdaq Stockholm, JPX, KRX, Euronext, London Main Market and AIM; 25,582 listings, 3,359 with a Chinese name) with a tenth column for Chinese names (TWSE/TPEX short names; Chinese Wikipedia zh-tw titles, Wikidata labels, company-registered names in `config/company-zh-names-v1.json`); Chinese names are searchable (輝達 → NVDA). Prices: watch-universe quotes hourly, otherwise market price shards every 3 h (Nasdaq screener with its stated date, TWSE/TPEx daily close, Nasdaq Nordic, Euronext, London price explorer) and daily for Japan/Korea (Yahoo, labelled unofficial). An exchange's own name outranks a sourced Chinese name (台積電 → TWSE:2330, not the TSM ADR); the staged replay enforces it.
- **Scheduled owner pushes are off by operator decision (2026-09-26).** `V21_SCHEDULED_PUSH_ENABLED="false"` in the local toml and both templates.
- Refresh cadence (post-seal, bounded by a 2100 s budget from task start): quotes/options 1 h, price shards 3 h, bottleneck v3 3 h, Serenity 6 h, Leopold 13F 24 h, identity/rotation/company reports 20 h, Chinese names 7 d (cache-driven), seven-field LKG 8 h (2 h failure backoff).

## Changes today (commits)

| Commit | Change |
| --- | --- |
| `259ae2a` | Covered-call sell suggestions (HIGH_STRIKE, BALANCED) replace UNAVAILABLE payoff rows |
| `e1e6830` | Tier fallthrough on a crashing lazy tier; post-seal budget; run pruning (48 kept); per-step data-refresh log; KV TTLs (run keys 14 d, blobs 30 d) and blob ledger; LKG 8 h / 2 h; atomic Leopold/v3 writes |
| `34cd9bb` | Macro TOP5 ranked by displayed score |
| `dce0830` | Chinese names, one return standard, lead scores hidden, order floor section, market price shards |
| `e02a518` `eefa982` `6d6c49e` | Japan/Korea daily closes; name-cache checkpoints; London identities and prices; Samsung name tiebreak |
| `ba8e52f` | Exchange names outrank sourced Chinese names; gate copies price shards with KV read retries |
| `fdd35b6` | Options universe: 100 largest US listings and optionable Stockholm Large Caps (JEV screen); Stockholm keys carry .ST (AZN vs AZN.ST); Worker accepts share classes (VOLV B) |
| this batch | Nasdaq historical corroboration restored (ISO query dates); read-only MCP servers `public_data_mcp.py` (SEC EDGAR, TWSE/TPEx monthly revenue) and `codex_review_mcp.py` (Codex CLI, read-only); [SOURCE_DIVERSITY_AUDIT](../docs/SOURCE_DIVERSITY_AUDIT.md) |

## Latest gate run

- `security_check`, documentation boundary/structure, workflow supply chain: PASS (2026-09-26 09:10).
- Full offline Python suite 2676 OK (`PYTHONUTF8=1`); focused suites for the price shards afterwards 84 OK. Worker typecheck PASS; vitest 936 passed / 2 skipped.

## Open lanes

1. Production rollout of `fdd35b6` and this batch (Worker deploy, runtime reinstall, manual seal and post gate) awaits the operator's authorization in the current session. Deploy the Worker and reinstall back to back: the new Worker reads .ST keys, the old runtime still writes SIVE.
2. Source diversity ([SOURCE_DIVERSITY_AUDIT](../docs/SOURCE_DIVERSITY_AUDIT.md)): US option chains and the covered-call spot are Yahoo-only (Cboe rejected by the rights review; Nasdaq option chain needs its review), price and identity shards are single per market, Serenity signals single; stooq unreachable, hfmarketdata frozen at 2026-09-03.
3. Company order estimates: only 3 of 16 sealed SEC reports have a disclosed RPO timing (NVDA, AMD, AVGO). Qwen inventory (verified: CRWV RPO $103.7B at 2026-06-30): RPO without XBRL timing also for CRWV, SNDK, MU, AXTI, NBIS (20-F); timing is in the filing text; Taiwan monthly revenue from TWSE `t187ap05_L` / TPEx `mopsfin_t187ap05_O` (5351 present, about the 17th); Korea needs a free OpenDART key (operator registration); Sivers IR unreachable.
4. Worker audit items: aliases (排名/前20), the option phrasing "NVDA 期權" without a period, stale help texts, carousel packing guard, v3 validator for `news.ratio`.
5. Carrying reports:*, source-independence and federation needs report-age gates in their readers (certified `cloud/src/qa.ts` needs recertification): deferred. CI R75 route still blocks release qualification.
6. Covered-call suggestions without a delta (Nasdaq Nordic gives no IV) have no assignment cap: SIVE monthly picked strike 62 on spot 32.78.

## Closed components — no reopening without regression evidence

- Top20 single-writer programme T1–T11 (`90563ee` … `f5bfe78`); T1 finite fractional ordering (`5208d64`), T2 nonauthorizing period declarations (`26842de`), T3 forward comparison declaration diagnostic (`689a682` → `a944410`); O1 options venue coverage shadow (`11436e6`), Case9 (`c178127`), R3A (`e45c1d6`), research method quarantine (`c6ce527`); I1/I2/I3 identity shadows, E2A synthetic capacity, hermetic fixtures. Preserved failures and receipts remain immutable (V12 register).

## Boundary flags

NATIVE_ATTEMPT_COUNT=0; NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; publication_eligible=false for candidates; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY for company proof, leads the industry ranking since 2026-09-26 (operator).

## Control plane

Astra master; exact local Qwen sole tracked writer on the Pi lane; Sol independent read-only reviewer. The operator assigned Claude Code as master and writer for this work (2026-09-25) without waiving boundaries. 2026-09-26: GPT (Codex) quota exhausted; Herdr panes w9:p6 `qwen-scout` (local Qwen, one read-only research task, then paused by the operator) and w9:p7 `gemini-review` (Gemini 3.8, read-only audits and reviews); JEV screens genuinely uncertain forks (options universe). Reviews go to ChatGPT through the `chatgpt-codex` MCP server (Codex CLI, read-only sandbox; no Pro tier there) when the quota returns, otherwise Gemini. The old `chatgpt-web` MCP server was removed (its directory and upstream project no longer exist).

## External mutations (this change)

Commits and normal pushes to `origin` (PR #37). Worker deployments `911fa6b2…`, `6a359ef1…`, `b9d270d5…`, `513b0444…` (operator authority; push off). Runtime reinstalls tx `7dc6bd2f…`, `2ac8cd52…`, `0abef62a…` (previous roots retained); runtime caches seeded from the source tree (Chinese names, identity, prices); one manual hourly-task start. Production public KV: sealed syncs `20260926T011233Z`, `20260926T014136Z` and the hourly runs (`--remote`; run keys 14-day TTL, blobs 30-day TTL). Read-only public calls: Wikidata SPARQL, Chinese Wikipedia API, Taiwan GCIS company registry, Nasdaq, TWSE, TPEx, Euronext, London Stock Exchange, Yahoo Finance. No credential, billing or broker change; no LINE push. 2026-09-26 afternoon (operator instructions): deleted the 12 `V213Runtime.old.*` roots and 8 `v213-previous-*.json` preimages (46,768 files, 6.19 GB; Gemini review APPROVE; live receipt and state hashes unchanged; `-RestorePrevious` now fails closed, rollback = reinstall from a commit); `.mcp.json` gained `public-data` and `chatgpt-codex` and lost `chatgpt-web` (preimages in `_archive/mcp-config-*`). Read-only public calls also to Cboe (one request, not used), Nasdaq option chain and historical APIs, SEC EDGAR, TWSE/TPEx OpenAPI.

## Next action

Hourly seals on `ba8e52f` pass (13:12 `20260926T051233Z-3077c3754e1c`, post gate PASS). Next: the operator's go for the rollout (lane 1), then the Nasdaq option-chain rights review and the order-evidence adapters (lanes 2 and 3).
