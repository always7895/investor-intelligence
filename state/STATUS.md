# Current state / 目前狀態

Updated 2026-09-26 (17:15 Asia/Taipei) by an operator-directed Claude Code session (master and writer; operator authority 2026-09-25/26; rollout go given in this session). **Paused by the operator at a safe checkpoint; resume from "Handoff".** Full detail of the day: `git show 59049db:state/STATUS.md`; V12 `git show 0f5358b:state/STATUS.md`; older `git show 38860e7:state/STATUS.md`. Release identity stays in `README.md`.

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main`; PR CI reports COMPLETED_SKIPPED (not PASS). DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false.

## Production (2026-09-26 08:00Z, unchanged since)

- Worker `bb485ed6-66ad-4194-87bd-ab62207ac329` (source `1f717b5`); rollback order `513b0444…`, `b9d270d5…`, `6a359ef1…`.
- Runtime LOCAL_SOURCE_CHECKOUT `1f717b5`, tx `b7531b5a…` (old root `V213Runtime.old.b7531b5a…` kept). Hourly task `InvestorIntelligenceSealedFreshness` (:12, `-CarryForwardTop20 -SnapshotRoot data\v213-snapshots`); 16:12 run result 0. Seal `20260926T074858Z` post gate `-ExpectTop20Records 20` PASS (`state/records/production-post-gate-20260926160147.json`). Reinstall only outside :12.
- Incident 15:18–15:59: the reinstall root lacked `data\`, so an INSUFFICIENT Top20 was sealed and the post gate failed closed; repaired by a logged carry (`logs\carry-data-b7531b5a-*.log`) and a re-seal; source fix `7366181`.
- Product: LINE TOP20 = bottleneck Top20 v3 ([BOTTLENECK_TOP20_V3](../docs/BOTTLENECK_TOP20_V3.md)); macro TOP5 by displayed score; stock lookup over identity shards (25,582 listings) and price shards; covered-call suggestions (US via Yahoo, Stockholm via Nasdaq Nordic); scheduled pushes off (operator). Cadence: quotes/options 1 h, price shards and v3 3 h, Serenity 6 h, 13F 24 h, identity and company reports 20 h, Chinese names 7 d, seven-field LKG 8 h.

## Commits since the rollout (not deployed)

| Commit | Change |
| --- | --- |
| `de72f50` | Codex review effort `auto` (ultra, then xhigh on an exhausted quota) |
| `7366181` | Installer carries live `data\` files the package does not ship (no overwrite, no junction); Gemini APPROVE |
| `bb7b1a3` | US fallbacks: cycles Yahoo cannot read try the Nasdaq US option chain (no IV, no delta); US quotes Yahoo cannot give try Alpha Vantage GLOBAL_QUOTE (DPAPI key, 20 calls per UTC day, a rate-limit reply spends the day, no key no request); Gemini change request (security_check) fixed |

Earlier today: `git log --oneline 259ae2a^..1f717b5`.

## Latest gate run (17:10, tree `bb7b1a3`)

`security_check`, documentation boundary/structure, workflow supply chain PASS; full offline suite 2710 OK (`PYTHONUTF8=1`, base CPython 3.12.10 from `resolve_python.ps1`; `.venv-ci` lacks pandas and is not the suite interpreter; the operation-lock test fails while the real task holds the lock). Worker unchanged since `1f717b5` (typecheck PASS, vitest 939 passed / 2 skipped).

## Operator decisions (2026-09-26, this session)

- Reviews go to ChatGPT (Windows desktop app, chat mode; Pro first, then 極高), not Codex. OpenAI's Terms of Use forbid "Automatically or programmatically extract data or Output", so the chat UI is never scripted: the master writes a review packet to `%TEMP%\ii-live\chatgpt-<task>.md`, puts it on the clipboard (`Set-Clipboard`), the operator pastes it into ChatGPT and pastes the reply back. Gemini (w9:p7) reviews in between. The `chatgpt-codex` MCP server stays but is not the review channel.
- No OpenDART and no data.go.kr key: Korea uses keyless sources (lane 3).
- Nasdaq data stays in use (terms risk accepted: nasdaq.com/legal forbids automated capture and third-party-platform distribution; api.nasdaq.com robots `Disallow: /`).
- Alpha Vantage is the backup. Its free key serves quotes only (REALTIME_OPTIONS and HISTORICAL_OPTIONS are premium on alphavantage.co/documentation). The operator creates the free key and stores it with hidden input: `ConvertFrom-SecureString (Read-Host -AsSecureString)` written to `<user_config_root>\alphavantage-key.local.txt` (`user_config_root` from `%LOCALAPPDATA%\InvestorIntelligence\install-state.json`). Normal days use about 0 calls; a full Yahoo outage would need 100+ per hourly run, so the cap of 20 per day serves the watch universe first.

## Open lanes (resume order: 11, 12, 10, 9, 3, then reinstall + seal)

11. **Chinese translations (operator):** 瓶頸位置 (`capturers[].role`) and the Leopold constraint (`layers[].leopold_constraint`) in `config/bottleneck-layers-v3.json` are English. Add `role_zh` and `leopold_constraint_zh` (translations of our own descriptions, not company facts), pass them through `scripts/bottleneck_top20_v3.py`, show Chinese first in `cloud/src/v213/bottleneck-v3.ts` (English as footnote). Translate English source labels on cards (for example "Yahoo Finance quarterly income statement (unofficial)" → Yahoo Finance 季度損益表（非官方）) and other user-facing English text.
12. **Missing Chinese names (operator; SNDK → 晟碟, https://zh.wikipedia.org/zh-tw/晟碟公司):** the name cache (16:21) lacks US:SNDK, NBIS, POET, CRWV, AXTI and SWEDEN:SIVE; MU carries the Wikidata label 美光記憶台 although the zh-wiki title is 美光科技. SNDK's 2025 spin-off item has no zhwiki sitelink (the article sits on the predecessor item). Plan: sourced overrides (zh-wiki article URL or a company-stated name) in `config/company-zh-names-v1.json` with its rule extended to predecessor-item articles; prefer ZHWIKI over WIKIDATA_LABEL; never machine-translate. The runtime `bottleneck_top20_v3.json` (07:28Z) has `name_zh` null for all 20 (built before the data carry); verify the next v3 refresh restores them.
10. **Order visibility (operator):** each Top20 entry needs current orders, a future estimate and an order-realization price scenario. `bottleneck_top20_v3.py` adds `outlook`: current orders = SEC XBRL `RevenueRemainingPerformanceObligation` amount and date (companyfacts), Korea IR backlog (lane 3), otherwise 未揭露; future = analyst consensus revenue and EPS for the next fiscal year (Yahoo `revenue_estimate` / `earnings_estimate`, labelled unofficial, dated); scenarios 若訂單實現 = revenue growth from RPO due within 12 months over TTM revenue at a constant P/S, and consensus EPS growth at a constant P/E, labelled 情境推算，非預測. Worker validator and renderer in `orderSection`, tests.
9. **瓶頸詳情 card (operator screenshot POET):** `buildBottleneckDetail` returns text for non-SEC filers (only SEC filers get `buildCompanyDataReportFlex`). Build a Flex bubble for every entry with all fundamentals (revenue YoY, prior YoY, acceleration, gross margin and change, RPO YoY, share-count YoY), market data, the lane-10 outlook and sources; keep text for `style=text`.
3. **Company orders:** SEC RPO timing only for NVDA, AMD, AVGO; RPO without XBRL timing for CRWV, SNDK, MU, AXTI, NBIS (timing is in the filing text); Taiwan monthly revenue from TWSE `t187ap05_L` / TPEx `mopsfin_t187ap05_O`. Korea keyless (`%TEMP%\ii-live\gemini-korea-keyless.result.md`; its figures are 2Q24, re-verify): DART robots disallow `/dsaf001/main.do`, `/report/viewer.do`, `/report/download.do`, `/pdf/download/`; KIND and English DART lead to that viewer. Use company IR earnings decks: HD Hyundai Electric (267260) and Hyosung Heavy (298040) publish order intake and backlog quarterly; 005930, 000660, 138080 are NOT_DISCLOSED. Planned `scripts/fetch_korea_ir_order_evidence.py` + `config/korea-ir-sources.json`, fail-closed `UNAVAILABLE_SOURCE`.
2. Source diversity ([SOURCE_DIVERSITY_AUDIT](../docs/SOURCE_DIVERSITY_AUDIT.md)): update the audit for `bb7b1a3`; price and identity shards single per market; Serenity single; stooq unreachable; hfmarketdata frozen at 2026-09-03.
6. Covered calls without a delta (Nasdaq Nordic and the Nasdaq US fallback give no IV) have no assignment cap (SIVE monthly strike 62 on spot 32.78).
4. Worker audit items: aliases (排名/前20), "NVDA 期權" without a period, stale help texts, carousel packing guard, v3 validator for `news.ratio`.
5. Deferred: report-age gates for carried reports and federation readers (certified `cloud/src/qa.ts` needs recertification); the CI R75 route blocks release qualification.
7. Installer data carry: fixed in `7366181`, effective at the next reinstall; each retained old root keeps about 0.5 GB.

Closed today: lane 1 (rollout), lane 8 (Nasdaq kept by the operator).

## Closed components — no reopening without regression evidence

- Top20 single-writer programme T1–T11 (`90563ee` … `f5bfe78`); T1 finite fractional ordering (`5208d64`), T2 nonauthorizing period declarations (`26842de`), T3 forward comparison declaration diagnostic (`689a682` → `a944410`); O1 options venue coverage shadow (`11436e6`), Case9 (`c178127`), R3A (`e45c1d6`), research method quarantine (`c6ce527`); I1/I2/I3 identity shadows, E2A synthetic capacity, hermetic fixtures. Preserved failures and receipts remain immutable (V12 register).

## Boundary flags

NATIVE_ATTEMPT_COUNT=0; NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; publication_eligible=false for candidates; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY for company proof, leads the industry ranking since 2026-09-26 (operator).

## Control plane

Astra master; exact local Qwen sole tracked writer (Pi lane); Sol independent reviewer. The operator assigned Claude Code as master and writer (2026-09-25) without waiving boundaries. Herdr w9:p7 `gemini-review` (Gemini 3.8 flash, read-only research and reviews); `qwen-scout` exited (no Tabby dispatch); the w6 `gemini` pane belongs to another project. Reviews follow the operator decision above; JEV only for genuinely uncertain forks.

## External mutations (this change)

2026-09-26 15:17–16:00 (operator go): Worker deploy `bb485ed6…`; reinstall tx `b7531b5a…`; logged `data\` carry; two manual task starts; Production public KV sealed syncs `20260926T071833Z` (superseded) and `20260926T074858Z` (`--remote`, pointer last). After 16:00 no production change; read-only public calls: nasdaq.com terms, api.nasdaq.com robots and one NVDA option-chain sample, alphavantage.co documentation, dart.fss.or.kr and kind.krx.co.kr robots, OpenAI terms (search); Gemini read OpenDART, company IR and exchange pages. Earlier today: `git show 80f2b46:state/STATUS.md`. No credential, billing or broker change; no LINE push.

## Handoff (2026-09-26 17:15, paused by the operator)

- Safe checkpoint: all work committed and pushed (PR #37 head = this STATUS commit); nothing uncommitted. Production unchanged since 16:00.
- `7366181` and `bb7b1a3` change only the runtime: they take effect after a reinstall from the head (outside :12), then a manual seal and the post gate. Lanes 9–12 change the Worker and the v3 builder: deploy both back to back after the gates.
- Needs the operator: the Alpha Vantage free key (see Operator decisions); the deploy go for lanes 9–12 when built.
- Scratch (untracked): `%TEMP%\ii-live` (Gemini tasks and results: opendart, korea-keyless, options rights, reviews; offline runs), `%TEMP%\ii-lanes`, `%TEMP%\ii-pkg-1f717b5` (export of `1f717b5`).
