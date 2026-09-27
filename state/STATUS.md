# Current state / 目前狀態

Updated 2026-09-27 (afternoon, Asia/Taipei) by Claude Code as sole tracked writer: STATUS-only offline reconcile batch contracted by Astra on base `dec7bd0ca92055862677cf1e90e41d571a475c1d`. Previous text (14:00, now stale): `git show dec7bd0:state/STATUS.md`; earlier: `git show 5b15984:state/STATUS.md`, `git show 3ac39a1:state/STATUS.md` (full production record), `git show a8c6e58:state/STATUS.md`, `git show 59049db:state/STATUS.md`, `git show 38860e7:state/STATUS.md`; V12 `git show 0f5358b:state/STATUS.md`. Release identity stays in `README.md`. Root and source `AGENTS.md` override older control-plane and model text in this file's history.

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main`; latest CI run 36301181043 on `dec7bd0` is COMPLETED_SKIPPED (not PASS). Non-release-qualified (LOCAL_SOURCE_CHECKOUT). DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false.
- This batch: tracked change `state/STATUS.md` only. External mutations by this batch: NONE (no production, task, runtime, model, credential, LINE, broker/billing or GPU action). Gate results and writer verdict: `_archive\pane-restart-20260927T081056Z\writer-result.md` (workspace, outside the repository); done only after Astra accepts the same snapshot. The `eca78a1` gate results (offline run 37, 2,839 OK; vitest 979) are history, not reruns for this batch.

## Production — historical observations, not currently verified

Nothing here was re-read in this batch; the live Worker, runtime, tasks, pointer/object set and relay are UNKNOWN now.

- Last recorded (rollout v5 P0, 2026-09-27 14:53): Worker `25377354-0ff5-4a28-a78b-82ec2457729f` (source `16cb1b3`, rollback target); runtime LOCAL_SOURCE_CHECKOUT `ff6dc42`, tx `75cc59dc…` FINALIZED; tasks SealedFreshness, FreshnessWatchdog, FreeRelay, DailyBriefing recorded Enabled/Ready; hourly seal task `InvestorIntelligenceSealedFreshness` (:12). Rollback order: `git show 3ac39a1:state/STATUS.md`.
- Outage 2026-09-26 22:45 – 09-27 08:12: seals failed on Cloudflare's free KV write quota (code 10048; reinstalls, manual seals and a Chinese-name cache fill that rewrote 52 identity shards an hour). Recovery observed after the 08:00 reset: 08:12 seal, 09:12 seal `20260927T011233Z-80d7c5b186c1`, post gate `-ExpectTop20Records 20` PASS; read-only replay then: seven-field Top20 fresh (20), v3 20, NVDA options VALID.
- The new validators refused historical SIVE.ST/VOLV-B.ST option cycles (no high-strike delta; current live data unverified), so a new Worker may only go live after data built by the new runtime is sealed.

## Rollout record (lane 14)

- Astra NO_GO on plans 1–4 (seal concurrency, pointer rollback, post-publication content checks, recovery, lease, quota). Plan v5 then got a conditional GO (`%TEMP%\ii-live\astra-rollout5.result.md`) for one supervised manual window on `dec7bd0` with ten mandatory stop conditions. It is not driver acceptance, not deployment completion and not authorization for any later session.
- Journal `%TEMP%\ii-live\rollout5\journal.md` records only P0 identities and preparation (quoted operator approval, package manifest `5b7bb387…`, dry-run replays old v2 20/20 and new v3 20/20, conservative KV usage bound). Later `p1-*` files (15:16) do not prove any effect. Execution, deploy, publication, recovery and final task states after P0 are UNKNOWN, not "nothing happened".
- Historical mutation/attempt counters (reinstalls, manual seals, V12 `NATIVE_ATTEMPT_COUNT=0`) are records, not asserted current.

## Priorities (Astra, 2026-09-27)

1. STATUS reconcile: READY (this batch; complete only after Astra ACCEPT, commit and push).
2. Lane 14: BLOCKED_AUTHORIZATION / OUTCOME_UNKNOWN. Needs explicit current-session operator authorization to read back and, if needed, reconcile the production outcome under v5's conditions before its state can be classified.
3. Local Qwen: BLOCKED_CONFIGURATION. Tabby `http://127.0.0.1:5000/v1/models` unreachable; exact `Qwen3.8-27B-EXL3-5.5bpw-v2` not established. `:8080` generic Qwen3.8-27B and `ninfer-local` are not fallbacks (source `AGENTS.md`).
4. Driver v3 batches A–D (contract `_archive\rollout-2026-09-27\reviews\astra-contract-driver-v3.md`): DEFERRED_WITH_REASON. v5 found them not mandatory for a supervised window; what is missing is final evidence and current authorization, not a demonstrated need for a new driver.
5. Other open lanes below: retained or deferred with their existing reasons; accepted lanes stay closed.

## Commits after 20:45 (deployment state unknown)

`13d7c85` … `5b15984`: lanes 2/3/4/6, KV quota handling, ChatGPT Pro reviews, reader replay v3 (`git show 5b15984:state/STATUS.md`). `aa54416`/`bb95f97` (batch 27, lanes 15/16; review record in `git show bb95f97:state/STATUS.md`). `33d7938` (batch 31): lanes 17/18. `eca78a1` (batch 36, Astra ACCEPT after REJECTs on batches 32-35): lane 19. `dec7bd0`: `AGENTS.md` only.

Historical run 36 (14:12) collided with production's hourly task on the global operation lock (`test_current_release_lane`: V213_OPERATION_LOCK_BUSY); current task/collision unknown; rerun outside :12-:25. Gates run with `PYTHONUTF8=1` as in CI (without it `test_v213_market_products.test_cli_builder_synthetic_fixture` fails on cp950 output); `.venv-ci` lacks pandas although `requirements-ci.txt` pins it.

## Operator decisions (2026-09-26)

- ChatGPT review MCP is `chatgpt-web` (rules in the workspace `AGENTS.md`), replacing `chatgpt-codex` (`scripts/codex_review_mcp.py`, kept in the repo). No pointless questions.
- The 2026-09-26 local-model record (ninfer `Qwen3.8-27B` on :8080) is superseded by root/source `AGENTS.md` (priority 3). Alpha Vantage key as DPAPI ciphertext; the plaintext desktop note is still the operator's to delete. No OpenDART/data.go.kr key; Nasdaq data accepted; Google Finance rejected.

## Open lanes

2. Source diversity: official fundamentals now stand beside Yahoo for Taiwan (TWSE/TPEx monthly revenue), Stockholm (SIVE via Cision; robots.txt allows it; MFN RSS disallowed) and Korea (curated IR config; SK hynix's newsroom terms forbid robots). Refresh the Korea config after earnings. Still single: Japan fundamentals (EDINET needs a key), Japan/Korea price shards (Yahoo daily closes), consensus outside the US.
3. Orders: MU fixed. CRWV (24M only) and SNDK (12M only) disclose no other horizon. AXTI ("through the first half of 2029") and NBIS (20-F/6-K, 28%→36% within 24M) have no deep report (only domestic SEC filers get one): DEFERRED_WITH_REASON until foreign-filer deep reports exist. Korea HD Hyundai Electric deck unreadable keylessly.
5. Deferred: report-age gates for carried reports and federation readers (certified `cloud/src/qa.ts` needs recertification); the CI R75 route blocks release qualification.
14. Rollout of `3ac39a1..dec7bd0`: see Rollout record and priority 2. Material in `_archive\rollout-2026-09-27` (driver v2, plans, reviews).
17. LINE Q&A → local model relay: Worker → quick tunnel → gateway :8814 → ninfer :8080, observed healthy on 2026-09-27 morning (historical, not currently verified). Heartbeats failed 21:06–08:01 Taipei on 2026-09-26/27 (one KV nonce per ~62 s heartbeat, ~1,400/day, past the free 1,000). Fixed in 33d7938 (route-bound signature, nonce in the relay Durable Object, no KV; older runtimes/Workers compatible); undeployed versions risk nightly repeats (fix: runtime reinstall; current deployment/recurrence unknown). Three short failures on 2026-09-27 unexplained (not GPU load); the heartbeat now logs the code.
18. Dilution: shares_yoy now from the financial quarter's diluted weighted average when shares outstanding are missing (was missing for 7 of 20; POET +100%, SIVE +14%, NBIS +13%, CRWV +13%). No stated Chinese name exists for NBIS, SIVE, POET, CRWV, AXTI (checked). Remaining: previous-quarter YoY for Yahoo listings (5 quarters only).
19. Order tiles (operator 2026-09-27: "未來預估是訂單，要註明時間，若實現股價至少6個月、1年，兩個數字不應相同"; production last observed on 16cb1b3 showed the old identical analyst percentages): `scripts/order_forecast.py` + `cloud/src/v213/order-forecast.ts` (rules in `git show eca78a1:state/STATUS.md`; golden fixture `tests/fixtures/v213-order-forecast-sealed.json`); order-timing extractor v8. Local matrix (`%TEMP%\ii-live\order-matrix.md`): 1-year orders SNDK 11.36B (coverage 32%), NVDA 1.25B, AMD 0.14B, AVGO 44.8B (38%); CRWV 24 months only; no 6-month schedule and no price; MU and CRDO need the v8 re-extraction (next runtime refresh). Deferred with reason: curated non-RPO records (no company discloses a 6M/1Y order amount outside RPO).

Closed: lanes 1, 4, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16. Lane 15 upkeep: a new IPO or spin-off in a layer stays excluded (`HISTORY_OR_LINEAGE_UNVERIFIED`) until `config/listing-lineage-v1.json` has its primary-source record; check `excluded` after each v3 build.

Lane 4 compatibility exception (Astra review 2): with a valid, fresh v3 document every ranking word opens v3. Without one, words the certified seven-field Top20 path already matched (`top 20`, `前20`, `排行`, `排名` as substrings, so also `瓶頸排名`, `瓶頸TOP20`) keep that certified path, which can show the sealed seven-field report; only words new to ranking (`瓶頸榜`, `前二十`) and `瓶頸爆發榜` answer the v3 unavailability notice. This is not universal v3-only fail-closed behaviour; retiring the seven-field path needs its own product decision and recertification.

## Closed components — no reopening without regression evidence

- Top20 single-writer programme T1–T11 (`90563ee` … `f5bfe78`); T1 finite fractional ordering (`5208d64`), T2 nonauthorizing period declarations (`26842de`), T3 forward comparison declaration diagnostic (`689a682` → `a944410`); O1 options venue coverage shadow (`11436e6`), Case9 (`c178127`), R3A (`e45c1d6`), research method quarantine (`c6ce527`); I1/I2/I3 identity shadows, E2A synthetic capacity, hermetic fixtures. Preserved failures and receipts remain immutable (V12 register).

## Boundary flags

NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; publication_eligible=false for candidates; global P0 NOT_REAUDITED; NATIVE_ATTEMPT_COUNT last recorded 0 (not re-asserted). Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY for company proof, leads the industry ranking since 2026-09-26 (operator).

## Control plane (root `AGENTS.md`, operator 2026-09-27)

Astra (`astra-review`, w9:pA, fresh session, PID 47312; read-only): architecture, priorities, bounded contracts, acceptance of every batch, arbitration, rollout go/no-go. Claude Code: sole tracked writer (integrates, tests, commits). Gemini (`gemini-review`, w9:pB, fresh session, PID 15984; antigravity, web access, serenity skill): research and audits. Qwen (w9:pC): parked shell `qwen-local-blocked`, not restarted; proposals only once the exact authorized backend is verified. JEV selection and restart receipt: `_archive\pane-restart-20260927T081056Z\RECEIPT.md` (earlier `_archive\pane-slimming-20260927T022638Z`). Each Herdr task starts with `/new` (send with `MSYS_NO_PATHCONV=1` from Git Bash). The wB panes and the Skyrim ChatGPT profile belong to another project.

Workspace fixes outside the repository (Pi extension BOM fix, `chatgpt-web` switch): `git show 5b15984:state/STATUS.md`; `chatgpt-web` selectors do not see answers, so read answers from the tab.

## Handoff

- Next: Astra acceptance of this snapshot, then commit and push `state/STATUS.md`.
- Operator: lane 14 authorization (read back/reconcile production), restoring the exact Tabby backend for Qwen, the plaintext Alpha Vantage note.
- Tooling left in place: old-reader worktree `%TEMP%\ii-live\wt-16cb1b3` (git worktree at 16cb1b3, `cloud\node_modules` is a junction to the source checkout's); `chatgpt-web` lane `investor` (branch `local/zh-tw-lanes`, commits c46501a and d738974). Scratch: `%TEMP%\ii-live`.
