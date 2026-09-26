# Current state / 目前狀態

Updated 2026-09-26 (16:15 Asia/Taipei) by an operator-directed Claude Code session (master and writer; the operator granted full authority, 2026-09-25/26; rollout go given in this session). Previous registers: V12 `git show 0f5358b:state/STATUS.md`; older history `git show 38860e7:state/STATUS.md`. Release identity stays in `README.md` (historical 2026-09-06 baseline).

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main` (pushed after every commit). PR CI only reports COMPLETED_SKIPPED; skipped is not PASS or release qualification.
- DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false.

## Production (2026-09-26 08:00Z)

- Worker `bb485ed6-66ad-4194-87bd-ab62207ac329` (source `1f717b5`: options universe with .ST keys and share classes such as VOLV B, Nasdaq corroboration; scheduled push off; typecheck PASS, vitest 939 passed / 2 skipped before deploy). Rollback order: `513b0444…`, `b9d270d5…`, `6a359ef1…`, `911fa6b2…`.
- Hourly task `InvestorIntelligenceSealedFreshness` (:12 local) runs the installed runtime (LOCAL_SOURCE_CHECKOUT `1f717b5`, tx `b7531b5a…`, 933 files; previous root retained as `V213Runtime.old.b7531b5a…`) with `-CarryForwardTop20 -SnapshotRoot data\v213-snapshots`. Manual seal `20260926T074858Z-6a0d123bacbc`: Top20 CARRIED_FORWARD 20 records, identity probes all RESOLVED (SIVE → NASDAQ STOCKHOLM, 005930.KS → KRX, 台積電 → TWSE:2330); post gate `-ExpectTop20Records 20` PASS (artifact `state/records/production-post-gate-20260926160147.json`). Runtime writes `SIVE.ST`, `AZN.ST` beside US `AZN`, and `VOLV-B.ST`. Reinstalls happen outside :12 (the task's lock timeout is 0).
- **Incident 15:18–15:59 local:** the reinstall swapped in a fresh root without the mutable `data\` (Top20 LKG bundles, previous sealed runs, caches; the installer attests only the payload). The first seal `20260926T071833Z` therefore promoted an INSUFFICIENT Top20 (`TOP20_BUNDLE_MISSING`) with identity lookups UNAVAILABLE, and the post gate failed closed (`TOP20_NOT_FRESH`). Repair: robocopy of the missing files only from the retained old root (`/XC /XN /XO /XJ`, 726 files, 0 failures, log `logs\carry-data-b7531b5a-*.log`), then the re-seal above. Open lane 7 fixes the procedure.
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
| `de72f50` | Codex review effort `auto`: ultra (the operator's "Pro"), one retry at xhigh only on CODEX_QUOTA_EXHAUSTED; Gemini review APPROVE |
| `1f717b5` | Nasdaq historical corroboration restored (ISO query dates); read-only MCP servers `public_data_mcp.py` (SEC EDGAR, TWSE/TPEx monthly revenue) and `codex_review_mcp.py` (Codex CLI, read-only); [SOURCE_DIVERSITY_AUDIT](../docs/SOURCE_DIVERSITY_AUDIT.md) |

## Latest gate run

- 2026-09-26 15:20–16:10 on `de72f50`'s tree: `security_check`, documentation boundary/structure, workflow supply chain PASS; full offline suite 2704 OK (`PYTHONUTF8=1`, base CPython 3.12.10 from `resolve_python.ps1`; `.venv-ci` lacks pandas and is not the suite interpreter); `tests.test_codex_review_mcp` 5 OK; Worker typecheck PASS, vitest 939 passed / 2 skipped.

## Open lanes

1. CLOSED 2026-09-26: rollout of `fdd35b6`/`1f717b5` (see Production).
2. Source diversity ([SOURCE_DIVERSITY_AUDIT](../docs/SOURCE_DIVERSITY_AUDIT.md)): US option chains and the covered-call spot are Yahoo-only (Cboe rejected by the rights review; Nasdaq option chain needs its review), price and identity shards are single per market, Serenity signals single; stooq unreachable, hfmarketdata frozen at 2026-09-03.
3. Company order estimates: only 3 of 16 sealed SEC reports have a disclosed RPO timing (NVDA, AMD, AVGO). Qwen inventory (verified: CRWV RPO $103.7B at 2026-06-30): RPO without XBRL timing also for CRWV, SNDK, MU, AXTI, NBIS (20-F); timing is in the filing text; Taiwan monthly revenue from TWSE `t187ap05_L` / TPEx `mopsfin_t187ap05_O` (5351 present, about the 17th); Sivers IR unreachable. Korea: OpenDART key pending (operator; individual keys are issued at once, 20,000 calls/day, key only as the `crtfc_key` query parameter). Gemini brief `%TEMP%\ii-live\gemini-opendart-brief.result.md`: no structured order API; 단일판매·공급계약체결 via `list.json` (pblntf_ty=I) + `document.xml`, 수주상황 only in periodic-report bodies, `corpCode.xml` ticker map, `fnlttSinglAcntAll` revenue. Expected disclosers (inferred): 267260 HD Hyundai Electric, 298040 Hyosung Heavy; unlikely: 005930, 000660. Planned: `scripts/fetch_korean_order_evidence.py`, key as DPAPI hex in `<user_config_root>\opendart-key.local.txt` (never Worker/KV/logs), fail-closed `UNAVAILABLE_NO_KEY`.
4. Worker audit items: aliases (排名/前20), the option phrasing "NVDA 期權" without a period, stale help texts, carousel packing guard, v3 validator for `news.ratio`.
5. Carrying reports:*, source-independence and federation needs report-age gates in their readers (certified `cloud/src/qa.ts` needs recertification): deferred. CI R75 route still blocks release qualification.
6. Covered-call suggestions without a delta (Nasdaq Nordic gives no IV) have no assignment cap: SIVE monthly picked strike 62 on spot 32.78.
7. Reinstall data carry: `v213_runtime_install_coordinator.ps1` swaps roots without mutable `data\`, so a reinstall followed by a seal loses the Top20 LKG and lazy objects (incident above). Fix: carry missing `data\` files from the previous root before the swap (no overwrite, no junctions) with a regression test; until then, run the logged robocopy before the first seal.

## Closed components — no reopening without regression evidence

- Top20 single-writer programme T1–T11 (`90563ee` … `f5bfe78`); T1 finite fractional ordering (`5208d64`), T2 nonauthorizing period declarations (`26842de`), T3 forward comparison declaration diagnostic (`689a682` → `a944410`); O1 options venue coverage shadow (`11436e6`), Case9 (`c178127`), R3A (`e45c1d6`), research method quarantine (`c6ce527`); I1/I2/I3 identity shadows, E2A synthetic capacity, hermetic fixtures. Preserved failures and receipts remain immutable (V12 register).

## Boundary flags

NATIVE_ATTEMPT_COUNT=0; NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; publication_eligible=false for candidates; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY for company proof, leads the industry ranking since 2026-09-26 (operator).

## Control plane

Astra master; exact local Qwen sole tracked writer on the Pi lane; Sol independent read-only reviewer. The operator assigned Claude Code as master and writer for this work (2026-09-25) without waiving boundaries. 2026-09-26: Herdr pane w9:p7 `gemini-review` (Gemini 3.8 flash, read-only audits, reviews and research); `qwen-scout` has exited (no Tabby dispatch this session). JEV screens genuinely uncertain forks. Reviews go to ChatGPT through the `chatgpt-codex` MCP server (Windows Codex app's codex.exe, read-only sandbox; default effort `auto` = ultra then xhigh, operator "Pro first"); live probe 15:16 reported CODEX_QUOTA_EXHAUSTED at both efforts, so Gemini reviews until the quota returns. The old `chatgpt-web` MCP server was removed (its directory and upstream project no longer exist).

## External mutations (this change)

2026-09-26 15:17–16:00 (operator go in this session): Worker deploy `bb485ed6…`; runtime reinstall tx `b7531b5a…` from `1f717b5`; runtime `data\` carry from the retained root; two manual task starts; Production public KV sealed syncs `20260926T071833Z` (superseded) and `20260926T074858Z` (`--remote`, pointer last). Earlier today (details: `git show 80f2b46:state/STATUS.md`): Worker deploys `911fa6b2…` … `513b0444…`, reinstalls `7dc6bd2f…`, `2ac8cd52…`, `0abef62a…`, hourly sealed syncs, deletion of 12 `V213Runtime.old.*` roots and 8 preimages (Gemini APPROVE), `.mcp.json` +`public-data` +`chatgpt-codex` −`chatgpt-web`. Read-only public calls only to official or market-data hosts (SEC, TWSE/TPEx, Nasdaq, Euronext, LSE, Yahoo, Wikidata/Wikipedia, GCIS, OpenDART docs via Gemini). No credential, billing or broker change; no LINE push.

## Handoff (2026-09-26 16:15)

- Committed and pushed on PR #37 through the STATUS commit after `de72f50`. Production: Worker `bb485ed6…`, runtime `1f717b5`, post gate PASS on `20260926T074858Z`; the 16:12 hourly run was in progress at handoff.
- Needs the operator: register the free OpenDART key (individual, https://opendart.fss.or.kr) and store it with hidden input as DPAPI hex in `<user_config_root>\opendart-key.local.txt` (the key never enters chat, Git, logs, Worker or KV).
- Herdr w9: `gemini-review` w9:p7 idle; the w6 `gemini` pane belongs to another project.
- Scratch (untracked): `%TEMP%\ii-live`, `%TEMP%\ii-lanes`, `%TEMP%\ii-pkg-1f717b5`.
- Resume order: lane 7 (installer data carry, before any further reinstall); lane 3 (Korea fetcher fail-closed without the key, then live once the key exists; RPO-only SEC filers; Taiwan monthly revenue); lane 2 (Nasdaq option-chain rights review).
