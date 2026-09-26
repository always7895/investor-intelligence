# Current state / 目前狀態

Updated 2026-09-26 (09:20 Asia/Taipei) by an operator-directed Claude Code session (master and writer; the operator granted full authority, 2026-09-25/26). Previous registers: V12 `git show 0f5358b:state/STATUS.md`; older history `git show 38860e7:state/STATUS.md`. Release identity stays in `README.md` (historical 2026-09-06 baseline).

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main` (pushed after every commit). PR CI only reports COMPLETED_SKIPPED; skipped is not PASS or release qualification.
- DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false.

## Production (2026-09-26 01:15Z)

- Worker `911fa6b2-92a9-46a4-bf42-ca9285ef1cdf` (this change: Chinese names, one return standard on Top20 v3 cards, market price shards, lazy-key limit 80; scheduled push off). Rollback order: `8f16c1db…`, `fc96b97f…`, `e1dd6694…`, `c95f939c…`.
- Hourly task `InvestorIntelligenceSealedFreshness` (:12 local) runs the installed runtime with `-CarryForwardTop20 -SnapshotRoot data\v213-snapshots`; runtime reinstall to this HEAD follows the next hourly seal (the task's lock timeout is 0, a reinstall during :12 would skip a seal).
- **LINE TOP20 = bottleneck-explosion Top20 v3** ([BOTTLENECK_TOP20_V3](../docs/BOTTLENECK_TOP20_V3.md)). Cards: symbol｜sourced Chinese name (or 無公認中文名) and original name; 6-month return and 2-year CAGR on every card (younger listings: 上市未滿2年 + annualized since first day; the same standard excludes negative long-term returns); lead scores hidden; signed-order floor from the RPO recognition schedule or the explicit reason; 瓶頸詳情 opens the SEC company report (non-SEC filers: filing and price figures with sources).
- **Macro TOP5** is ranked by the opportunity score it shows (phase only breaks ties); the live order had put 57/56/55-point DISCOVERY industries below 42/35-point EARLY_VALIDATION ones.
- **Stock lookup**: identity shards (Nasdaq Trader, TWSE, TPEx, Nasdaq Stockholm, JPX, KRX, Euronext; 23,964 listings) with a tenth column for Chinese names (TWSE/TPEX short names; Chinese Wikipedia zh-tw titles, Wikidata labels, company-registered names in `config/company-zh-names-v1.json`); Chinese names are searchable (輝達 → NVDA). Prices: watch-universe quotes hourly, otherwise market price shards every 3 h (Nasdaq screener with its stated date, TWSE/TPEx daily close, Nasdaq Nordic, Euronext).
- **Scheduled owner pushes are off by operator decision (2026-09-26).** `V21_SCHEDULED_PUSH_ENABLED="false"` in the local toml and both templates.
- Refresh cadence (post-seal, bounded by a 2100 s budget from task start): quotes/options 1 h, price shards 3 h, bottleneck v3 3 h, Serenity 6 h, Leopold 13F 24 h, identity/rotation/company reports 20 h, Chinese names 7 d (cache-driven), seven-field LKG 8 h (2 h failure backoff).

## Changes today (commits)

| Commit | Change |
| --- | --- |
| `259ae2a` | Covered-call sell suggestions (HIGH_STRIKE, BALANCED) replace UNAVAILABLE payoff rows |
| `e1e6830` | Tier fallthrough on a crashing lazy tier; post-seal budget; run pruning (48 kept); per-step data-refresh log; KV TTLs (run keys 14 d, blobs 30 d) and blob ledger; LKG 8 h / 2 h; atomic Leopold/v3 writes |
| `34cd9bb` | Macro TOP5 ranked by displayed score |
| `dce0830` | Chinese names, one return standard, lead scores hidden, order floor section, market price shards |

## Latest gate run

- `security_check`, documentation boundary/structure, workflow supply chain: PASS (2026-09-26 09:10).
- Full offline Python suite 2676 OK (`PYTHONUTF8=1`); focused suites for the price shards afterwards 84 OK. Worker typecheck PASS; vitest 936 passed / 2 skipped.

## Open lanes

1. Runtime reinstall to `dce0830` after the 09:12 seal; seed the runtime with the Chinese-name title cache; verify the next seal carries identity rows with names, `v213:prices:v1:*` and v3 `name_zh`; post gate `-ExpectTop20Records 20`.
2. Prices for Japan, Korea and London listings (IQE is not in the identity directories yet: add LSE listings and a price source); options universe beyond the Top20/layers.
3. Company order estimates: only 3 of 16 sealed SEC reports have a disclosed RPO timing (NVDA, AMD, AVGO); the card states the reason for the rest. Wider order evidence (backlog in filings, Taiwan monthly revenue) is the next step for the 6M/1Y/2Y order-realization view.
4. Worker audit items: aliases (排名/前20), option phrasings (NVDA 期權, SIVE.ST), stale help texts, carousel packing guard, v3 validator for `news.ratio`.
5. Carrying reports:*, source-independence and federation needs report-age gates in their readers (certified `cloud/src/qa.ts` needs recertification): deferred. CI R75 route still blocks release qualification. Nine `V213Runtime.old.*` roots (220–680 MB each) await a retention decision.

## Closed components — no reopening without regression evidence

- Top20 single-writer programme T1–T11 (`90563ee` … `f5bfe78`); T1 finite fractional ordering (`5208d64`), T2 nonauthorizing period declarations (`26842de`), T3 forward comparison declaration diagnostic (`689a682` → `a944410`); O1 options venue coverage shadow (`11436e6`), Case9 (`c178127`), R3A (`e45c1d6`), research method quarantine (`c6ce527`); I1/I2/I3 identity shadows, E2A synthetic capacity, hermetic fixtures. Preserved failures and receipts remain immutable (V12 register).

## Boundary flags

NATIVE_ATTEMPT_COUNT=0; NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; publication_eligible=false for candidates; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY for company proof, leads the industry ranking since 2026-09-26 (operator).

## Control plane

Astra master; exact local Qwen sole tracked writer on the Pi lane; Sol independent read-only reviewer. The operator assigned Claude Code as master and writer for this work (2026-09-25) without waiving boundaries.

## External mutations (this change)

Commits and normal pushes to `origin` (PR #37). Worker deployment `911fa6b2…` (operator authority; push off). Read-only public calls: Wikidata SPARQL, Chinese Wikipedia API, Taiwan GCIS company registry, Nasdaq, TWSE, TPEx, Euronext. No credential, billing or broker change; no LINE push.

## Next action

Reinstall the runtime after the 09:12 seal, seed the Chinese-name cache, verify the 10:12 seal and the post gate; then Japan/Korea/London prices and IQE identity.
