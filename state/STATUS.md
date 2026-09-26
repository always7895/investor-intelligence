# Current state / 目前狀態

Updated 2026-09-26 (18:35 Asia/Taipei) by an operator-directed Claude Code session (master and writer; operator authority 2026-09-25/26; rollout go given in this session). Resumed after the 17:15 pause; see "Handoff". Full detail of the day: `git show 59049db:state/STATUS.md`; V12 `git show 0f5358b:state/STATUS.md`; older `git show 38860e7:state/STATUS.md`. Release identity stays in `README.md`.

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
| `9814fa8` | LF line endings restored (bb7b1a3 had converted two files) |
| `d021726` | Local model auto-detection: `scripts/local_model_endpoint.py` (explicit, saved, configured, known ports, then every loopback listener without an exact match; never :8000; exact, same family or only model); used by the translator, the refresh log, the Q&A bridge and the launcher scan (`--model-discovery-check`); Qwen APPROVE |
| `61fb10a` | Codex quota reset time in the error; `chatgpt_pro_packet` tool (review packet file for the operator) |
| `0922bf5` | Sourced Chinese names (SNDK 晟碟, MU 美光科技, +8) read at seal time |
| `be71da9` | Top20 order outlook (SEC RPO, Korean IR backlog, consensus), price scenarios, full 瓶頸詳情 card, Chinese roles and Leopold logic; Qwen APPROVE |
| `6e957b8` | Chinese display labels for recorded source names |

Earlier today: `git log --oneline 259ae2a^..1f717b5`.

## Latest gate run (18:30, tree `6e957b8`)

Full offline suite 2725 OK on `be71da9`'s pre-review tree; vitest 941 passed / 2 skipped and typecheck PASS on `6e957b8`. Earlier (tree `bb7b1a3`): `security_check`, documentation boundary/structure, workflow supply chain PASS; full offline suite 2710 OK (`PYTHONUTF8=1`, base CPython 3.12.10 from `resolve_python.ps1`; `.venv-ci` lacks pandas and is not the suite interpreter; the operation-lock test fails while the real task holds the lock). Worker unchanged since `1f717b5` (typecheck PASS, vitest 939 passed / 2 skipped).

## Operator decisions (2026-09-26, this session)

- Reviews: ChatGPT first (6 Pro, then 極高). The ChatGPT app's 6 Pro chat model is not offered to the Codex CLI or app server (model/list checked 2026-09-26) and OpenAI's terms forbid scripting the chat UI, so a Pro review is a packet (`chatgpt_pro_packet`, `%TEMP%\ii-live\chatgpt-pro-*.prompt.txt`) the operator pastes. Automatic reviews use the `chatgpt-codex` MCP server (Codex CLI, ultra then xhigh; quota exhausted until 2026-09-30 10:27), otherwise Qwen (local) and Gemini (w9), with JEV screening uncertain items (translations).
- Local model (operator): TabbyAPI :5000 is gone; `ninfer-serve` serves `Qwen3.8-27B` (nvfp4) on :8080, shared with other projects (concurrency 1), configured as `ninfer-local` in the global Pi models; Herdr pane w9:p5 `qwen-local` runs it read-only. Every local caller auto-detects port and model (`d021726`).
- No OpenDART and no data.go.kr key: Korea uses keyless sources (lane 3).
- Nasdaq data stays in use (terms risk accepted: nasdaq.com/legal forbids automated capture and third-party-platform distribution; api.nasdaq.com robots `Disallow: /`).
- Alpha Vantage is the backup for US quotes only (its option endpoints are premium). The key file `<user_config_root>\alphavantage-key.local.txt` did not exist at 17:40 (the operator's command had not run in PowerShell); until it exists the fallback makes no request. Cap 20 calls per UTC day.

## Open lanes (resume order: deploy go, 3, 2, 6, 4)

0. **Deploy (needs the operator's go):** Worker from the head (lanes 9–12 render; old sealed documents still parse) and runtime reinstall from the head (outside :12; installer carries `data\`), then a manual seal and the post gate. Until the v3 builder reruns (3-hourly) cards show 未取得 for the outlook; names and Chinese roles apply at the first seal.
3. **Company orders:** SEC RPO timing only for NVDA, AMD, AVGO; RPO without XBRL timing for CRWV, SNDK, MU, AXTI, NBIS (timing is in the filing text); Taiwan monthly revenue from TWSE `t187ap05_L` / TPEx `mopsfin_t187ap05_O`. Korea keyless (`%TEMP%\ii-live\gemini-korea-keyless.result.md`; its figures are 2Q24, re-verify): DART robots disallow `/dsaf001/main.do`, `/report/viewer.do`, `/report/download.do`, `/pdf/download/`; KIND and English DART lead to that viewer. Use company IR earnings decks: HD Hyundai Electric (267260) and Hyosung Heavy (298040) publish order intake and backlog quarterly; 005930, 000660, 138080 are NOT_DISCLOSED. Planned `scripts/fetch_korea_ir_order_evidence.py` + `config/korea-ir-sources.json`, fail-closed `UNAVAILABLE_SOURCE`.
2. Source diversity ([SOURCE_DIVERSITY_AUDIT](../docs/SOURCE_DIVERSITY_AUDIT.md)): update the audit for `bb7b1a3`; price and identity shards single per market; Serenity single; stooq unreachable; hfmarketdata frozen at 2026-09-03.
6. Covered calls without a delta (Nasdaq Nordic and the Nasdaq US fallback give no IV) have no assignment cap (SIVE monthly strike 62 on spot 32.78).
4. Worker audit items: aliases (排名/前20), "NVDA 期權" without a period, stale help texts, carousel packing guard, v3 validator for `news.ratio`.
5. Deferred: report-age gates for carried reports and federation readers (certified `cloud/src/qa.ts` needs recertification); the CI R75 route blocks release qualification.
7. Installer data carry: fixed in `7366181`, effective at the next reinstall; each retained old root keeps about 0.5 GB.
13. Live Q&A relay: the logon task `InvestorIntelligence-v213-FreeRelay` runs the old `D:\Investor-Intelligence-LINE-Pi\run-v213-local-llm-bridge.ps1` and last ran 2026-09-19 with result 1; its saved model (`Qwen3.8-27B-UD-Q5_K_XL…`, 2026-09-07) no longer exists. Production `GENERAL_QA_ENABLED=true`. Needs an operator decision (re-point to the V213 runtime bridge with auto-detection, or disable).

Closed today in source (deploy pending): lanes 9–12 (`0922bf5`, `be71da9`, `6e957b8`). Closed: lane 1 (rollout), lane 8 (Nasdaq kept by the operator).

## Closed components — no reopening without regression evidence

- Top20 single-writer programme T1–T11 (`90563ee` … `f5bfe78`); T1 finite fractional ordering (`5208d64`), T2 nonauthorizing period declarations (`26842de`), T3 forward comparison declaration diagnostic (`689a682` → `a944410`); O1 options venue coverage shadow (`11436e6`), Case9 (`c178127`), R3A (`e45c1d6`), research method quarantine (`c6ce527`); I1/I2/I3 identity shadows, E2A synthetic capacity, hermetic fixtures. Preserved failures and receipts remain immutable (V12 register).

## Boundary flags

NATIVE_ATTEMPT_COUNT=0; NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; publication_eligible=false for candidates; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY for company proof, leads the industry ranking since 2026-09-26 (operator).

## Control plane

Astra master; local Qwen writer lane (Pi); Sol independent reviewer. The operator assigned Claude Code as master and writer (2026-09-25) without waiving boundaries and asked (18:00) for Herdr dispatch to Qwen and Gemini with JEV screening. Herdr w9: p5 `qwen-local` (ninfer Qwen3.8-27B; translations, reviews), p7 `gemini-review` (Gemini 3.8 flash; research, reviews; five-hour quota hit once at 18:20). Qwen and Gemini write result files only; Claude Code stays the single tracked writer. The w6/wB panes belong to other projects.

## External mutations (this change)

2026-09-26 15:17–16:00 (operator go): Worker deploy `bb485ed6…`; reinstall tx `b7531b5a…`; logged `data\` carry; two manual task starts; Production public KV sealed syncs `20260926T071833Z` (superseded) and `20260926T074858Z` (`--remote`, pointer last). After 16:00 no production change; read-only public calls: nasdaq.com terms, api.nasdaq.com robots and one NVDA option-chain sample, alphavantage.co documentation, dart.fss.or.kr and kind.krx.co.kr robots, OpenAI terms (search), zh.wikipedia parse API (10 titles), GCIS open data (3 registrations), nittobo.co.jp, hyosungheavyindustries.com (robots, 2Q26 deck), Yahoo Finance and SEC companyfacts (outlook checks); Gemini read OpenDART, company IR, Wikipedia and exchange pages. Local only: Codex CLI app-server model/list, ninfer :8080 catalog and one translation. Earlier today: `git show 80f2b46:state/STATUS.md`. No credential, billing or broker change; no LINE push.

## Handoff (2026-09-26 18:35)

- All work committed and pushed (PR #37 head = this STATUS commit); production unchanged since 16:00 (Worker `bb485ed6…`, runtime `1f717b5`).
- Needs the operator: (a) deploy go for the Worker and a runtime reinstall from the head (lane 0); (b) store the Alpha Vantage key in PowerShell (the file does not exist yet); (c) optional ChatGPT 6 Pro review: paste `%TEMP%\ii-live\chatgpt-pro-lanes-9-12.prompt.txt`; (d) lane 13 relay decision.
- Pending reviews: Gemini second opinion on `61fb10a..6e957b8` (`%TEMP%\ii-live\gemini-review-lanes-9-12.result.md`).
- Scratch (untracked): `%TEMP%\ii-live` (tasks, results, packets, offline runs), `%TEMP%\ii-lanes`, `%TEMP%\ii-pkg-1f717b5`.
