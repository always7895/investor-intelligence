# Current state / 目前狀態

Updated 2026-09-26 (20:45 Asia/Taipei) by an operator-directed Claude Code session (master and writer; operator authority 2026-09-25/26; deploy go and relay go given in this session). Earlier detail: `git show a8c6e58:state/STATUS.md` (17:15 handoff), `git show 59049db:state/STATUS.md`; V12 `git show 0f5358b:state/STATUS.md`. Release identity stays in `README.md`.

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main`; PR CI reports COMPLETED_SKIPPED (not PASS). DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false.

## Production (2026-09-26 12:37Z)

- Worker `25377354-0ff5-4a28-a78b-82ec2457729f` (source `16cb1b3`; vars add `LOCAL_LLM_MODEL_FROM_ROUTE=true`); rollback order `e75fe11c…`, `4a187f32…`, `0a4f568f…`, `bb485ed6…`.
- Runtime LOCAL_SOURCE_CHECKOUT `ff6dc42`, tx `75cc59dc…` (installer now carries `data\`; old roots `V213Runtime.old.*` retained, about 0.5 GB each). Manual seal `20260926T122933Z-4cca899a7314`, post gate `-ExpectTop20Records 20` PASS. Hourly task `InvestorIntelligenceSealedFreshness` unchanged (:12).
- LINE Q&A relay live: task `InvestorIntelligence-v213-FreeRelay` runs `scripts\v213_free_relay_watchdog.ps1` at logon and every 5 min; bridge on ninfer `:8080` `Qwen3.8-27B` (auto-detected), gateway :8814, Worker signed smoke PASS (a smoke during the hourly translation can fail transiently; the local server takes one request at a time).
- Production model-profile secret `V213_MODEL_PROFILE_JSON` pins the retired `Qwen3.8-27B-EXL3-SC5-H6-V6` (identified by readiness sha256 `70077f89…`); in route mode only its settings apply (thinking off, 1024/128 tokens, 18 s). Not changed.

## Commits after the 16:00 rollout (all deployed)

| Commit | Change |
| --- | --- |
| `7366181` `bb7b1a3` `9814fa8` | installer data carry; Yahoo fallbacks (Nasdaq US chain, Alpha Vantage quote); LF restore |
| `d021726` | local model auto-detection (`scripts/local_model_endpoint.py`, EXE scan incl. loopback listeners) |
| `0922bf5` `be71da9` `6e957b8` `0cd6a73` | sourced Chinese names; Top20 outlook, scenarios, detail card, Chinese roles/Leopold; Chinese source labels |
| `21c82b1` `d0110e4` `ff6dc42` | ChatGPT packet MCP: clipboard + open app, prompt file, collect (CRLF-safe) |
| `57b9ea6` `067228e` `0cb9f03` | relay follows the route model; watchdog; model selector; route-mode profile; gateway on ninfer with the retired decider |
| `35127bd` `988f25d` | no RPO schedule from zero (CRWV 6M=1Y=2Y artefact); one three-tile order layout on every card |
| `16cb1b3` | exchange price leads lookups with a Yahoo cross-check; exchange close on Top20 cards; Nasdaq.com second US consensus |

## Latest gate run (20:25, tree `16cb1b3`)

Gates PASS; full offline suite 2736 OK (`PYTHONUTF8=1`, base CPython 3.12.10; `.venv-ci` lacks pandas); vitest 946 passed / 2 skipped. Reviews: Qwen APPROVE (auto-detect, lanes 9–12), Gemini APPROVE (lanes 9–12); Qwen review of the evening diff running; ChatGPT 6 Pro packet `chatgpt-pro-relay` awaits the operator.

## Operator decisions (2026-09-26)

- Reviews: ChatGPT 6 Pro first (then 極高). 6 Pro is chat-only; `chatgpt_pro_packet` puts the request on the clipboard and opens the ChatGPT app, the operator pastes and sends, `chatgpt_pro_collect` saves the copied reply (OpenAI terms forbid scripting the chat window). Codex CLI quota (ultra/xhigh) resets 2026-09-30 10:27. Qwen (ninfer, w9:p5) and Gemini (w9:p7) review meanwhile; JEV screens uncertain items.
- Local model: TabbyAPI is gone; ninfer serves `Qwen3.8-27B` on :8080 (shared GPU, concurrency 1). Port or model changes are followed automatically; with several models the pick in the launcher or `select_local_model.ps1` (desktop 選擇本機模型.cmd) wins. The System One decider is retired (`decision_router.retired`).
- Alpha Vantage key stored as DPAPI ciphertext in `<user_config_root>\alphavantage-key.local.txt` (imported from the operator's desktop note; verified with one quote). The plaintext note `Desktop\Alpha Vantage 免費金鑰.txt` still holds the key: operator to delete. Desktop `儲存 Alpha Vantage 金鑰.cmd` re-stores it.
- No OpenDART/data.go.kr key: Korea via company IR decks (Hyosung verified; HD Hyundai Electric unreadable). Nasdaq data accepted. Google Finance rejected (no API; terms forbid automated collection).

## Open lanes (resume order: 2, 3, 6, 4)

2. Source diversity phase 2 (Gemini audit `%TEMP%\ii-live\gemini-source-diversity.result.md`): Top20 returns are Yahoo-only in every market; non-US fundamentals Yahoo-only (next: TWSE/TPEx monthly revenue for Taiwan listings, Cision/MFN reports for Stockholm, EDINET needs a free key); Japan and Korea price shards are Yahoo daily closes (no free exchange feed found); consensus outside the US Yahoo-only. Update `docs/SOURCE_DIVERSITY_AUDIT.md`.
3. Company orders: SEC RPO timing now only from disclosed horizons; RPO without XBRL timing for CRWV, SNDK, MU, AXTI, NBIS (20-F); Korea: HD Hyundai Electric deck unreadable keylessly; Taiwan monthly revenue not yet used.
6. Covered calls without a delta (Nasdaq Nordic, Nasdaq US fallback) have no assignment cap (SIVE monthly strike 62 on spot 32.78).
4. Worker audit items: aliases (排名/前20), "NVDA 期權" without a period, stale help texts, v3 validator for `news.ratio`.
5. Deferred: report-age gates for carried reports and federation readers (certified `cloud/src/qa.ts` needs recertification); the CI R75 route blocks release qualification.

Closed today: lanes 1, 7, 8, 9, 10, 11, 12, 13 (relay).

## Closed components — no reopening without regression evidence

- Top20 single-writer programme T1–T11 (`90563ee` … `f5bfe78`); T1 finite fractional ordering (`5208d64`), T2 nonauthorizing period declarations (`26842de`), T3 forward comparison declaration diagnostic (`689a682` → `a944410`); O1 options venue coverage shadow (`11436e6`), Case9 (`c178127`), R3A (`e45c1d6`), research method quarantine (`c6ce527`); I1/I2/I3 identity shadows, E2A synthetic capacity, hermetic fixtures. Preserved failures and receipts remain immutable (V12 register).

## Boundary flags

NATIVE_ATTEMPT_COUNT=0; NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; publication_eligible=false for candidates; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY for company proof, leads the industry ranking since 2026-09-26 (operator).

## Control plane

Astra master; local Qwen writer lane; Sol reviewer. The operator assigned Claude Code as master and single tracked writer (2026-09-25) and asked for Herdr dispatch to Qwen and Gemini with JEV screening; they write result files only. Herdr w9: p5 `qwen-local` (ninfer Qwen3.8-27B), p7 `gemini-review` (Gemini 3.8 flash; five-hour quota hit once). The w6/wB panes belong to other projects.

## External mutations (this session, after 16:00)

Worker deploys `0a4f568f…`, `4a187f32…`, `e75fe11c…`, `25377354…` (vars `LOCAL_LLM_MODEL_FROM_ROUTE`); runtime reinstalls `a98903e7…`, `7d52c2fc…`, `5c9ca41e…`, `db952013…`, `75cc59dc…`; manual seals `20260926T103905Z`, `20260926T122933Z` (+ hourly); relay task re-registered to the watchdog and briefly disabled around reinstalls; relay routes leased (production Durable Object) and signed smokes; runtime v3 rebuilds; Alpha Vantage key DPAPI file; desktop `.cmd` helpers; `%LOCALAPPDATA%\InvestorIntelligence\tools\save-alphavantage-key.ps1`; model selection saved (`desktop_model_selector`). Read-only: wrangler secret names, Worker readiness, Nasdaq/Alpha Vantage/Wikipedia/GCIS/company sites. No billing or broker change; no LINE push. Earlier today: `git show a8c6e58:state/STATUS.md`.

## Handoff (2026-09-26 20:45)

- All work committed and pushed (PR #37 head = this STATUS commit). Production as above.
- Operator: paste `chatgpt-pro-relay` into ChatGPT 6 Pro and copy the reply (then `chatgpt_pro_collect relay`); delete the plaintext key note on the desktop.
- Scratch: `%TEMP%\ii-live` (tasks, results, packets, probes, offline runs), `%TEMP%\ii-pkg-*` exports.
