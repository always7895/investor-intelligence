# Current state / 目前狀態

Updated 2026-09-27 (03:25 Asia/Taipei) by an operator-directed Claude Code session (master and single tracked writer; operator authority 2026-09-25/26). Earlier detail: `git show 3ac39a1:state/STATUS.md` (20:45 seal, full production record), `git show a8c6e58:state/STATUS.md` (17:15), `git show 59049db:state/STATUS.md`, `git show 38860e7:state/STATUS.md`; V12 `git show 0f5358b:state/STATUS.md`. Release identity stays in `README.md`.

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main`; PR CI reports COMPLETED_SKIPPED (not PASS). DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false.

## Production (unchanged since 20:45; stale since 22:45)

- Worker `25377354-0ff5-4a28-a78b-82ec2457729f` (source `16cb1b3`); runtime LOCAL_SOURCE_CHECKOUT `ff6dc42`, tx `75cc59dc…`; hourly task `InvestorIntelligenceSealedFreshness` (:12); LINE Q&A relay live on ninfer `Qwen3.8-27B` through the watchdog task. Rollback order and secrets: `git show 3ac39a1:state/STATUS.md`.
- Every hourly seal since 21:12 fails: Cloudflare's free KV write quota (1,000/day, code 10048) was spent by five reinstalls, several manual seals and a Chinese-name cache fill that rewrote all 52 identity shards each hour (~70 writes per seal instead of ~20). The pointer stays on `20260926T124509Z-ad93b335bf24`; Top20 answers the stale notice. The quota resets 00:00 UTC (08:00 Taipei); the 08:12 hourly run should recover. `dc7c6f7` names the limit in the log and in `docs/OPERATOR_RUNBOOK.md`.
- Not deployed: `bdd72e5` and every commit below.

## Commits after 20:45 (tests and gates PASS; not deployed; details in the commit messages)

| Commit | Change |
| --- | --- |
| `13d7c85` | lane 6: covered-call high strike needs delta <= 0.20; chains without Greeks use the quote-implied delta |
| `b3f5e8d` | lane 3: RPO timing written as a word fraction (Micron) or with "during" (Nebius) |
| `dee1a05` | lane 4: natural LINE phrasings reach Top20 v3, details, the industry ranking and covered calls; help texts |
| `e8824ae` `4bae22f` `6503a8b` | lane 2: official revenue beside Yahoo: TWSE/TPEx monthly, SIVE via Cision, SK hynix/Samsung curated IR |
| `dc7c6f7` | KV sync names Cloudflare's daily write limit (code 10048) and stops retrying it; runbook budget |
| `bd0a879` | fixes from two ChatGPT Pro reviews, Astra ACCEPT after five rounds (delta cap in both validators, fraction grammar, Cision quarterly scope, one revenue contract, rendering) |
| `441ce9f` | sealed reader replay contract v3 with product probes (gate and every staged seal); Astra ACCEPT (tooling) |
| `ef9d221` | CRLF restored in two files rewritten as LF (no content change) |

Gate run 02:35 (final tree): security, documentation boundary/structure, workflow supply-chain PASS; typecheck PASS; vitest 956 passed / 2 skipped; offline suite 2749 OK (run 23). Run 22 failed once in `test_v213_model_profile ... test_compiled_exe_profile_persistence_and_child_propagation (route='route_incomplete')`: an extra `/v1/models` request reached the test stub (receipt `%TEMP%\ii-live\offline-full-22.txt`); 3/3 isolated passes and seven other full runs passed; no launcher/model-profile change in this batch. Tracked as a suspected environmental flake (root cause unproven; Astra accepted the exception for this batch only, not as release qualification). 

## Operator decisions (2026-09-26)

- ChatGPT review MCP is now `chatgpt-web` (`D:\chatgpt-web-mcp\src\index.js`, dedicated signed-in Chrome profile, zh-TW UI) in the workspace `.mcp.json`, replacing `chatgpt-codex` (`scripts/codex_review_mcp.py`, kept in the repo). Pro first; 極高 only when Pro is locked or spent. On 22:00 the tier slider showed 極高 (4 of 5) and the fifth (Pro) position 「已鎖定」. Its selectors are zh-CN/English: use only `chatgpt_send_message` (`answerTier`, `newChat`, inline prompt) and `chatgpt_route_new_chat`; no uploads or mode/model/thinking options. Rule recorded in the workspace `AGENTS.md`. No pointless questions.
- Local model: ninfer `Qwen3.8-27B` on :8080 (shared GPU, concurrency 1); the System One decider stays retired. Alpha Vantage key as DPAPI ciphertext; the plaintext desktop note is still the operator's to delete. No OpenDART/data.go.kr key; Nasdaq data accepted; Google Finance rejected.

## Open lanes

2. Source diversity: official fundamentals now stand beside Yahoo for Taiwan (TWSE/TPEx monthly revenue), Stockholm (SIVE via Cision; robots.txt allows it; MFN RSS disallowed) and Korea (curated IR config; SK hynix's newsroom terms forbid robots). Refresh the Korea config after each earnings release. Still single: Japan fundamentals (EDINET needs a key), Japan/Korea price shards (Yahoo daily closes), consensus outside the US.
3. Orders: MU fixed. CRWV (24M only) and SNDK (12M only) disclose no other horizon. AXTI ("through the first half of 2029") and NBIS (20-F/6-K, 28%→36% within 24M) have no deep report (only domestic SEC filers get one): DEFERRED_WITH_REASON until foreign-filer deep reports exist. Korea HD Hyundai Electric deck unreadable keylessly.
5. Deferred: report-age gates for carried reports and federation readers (certified `cloud/src/qa.ts` needs recertification); the CI R75 route blocks release qualification.
14. Rollout of `3ac39a1..ef9d221`: DEFERRED_WITH_REASON, blocked at the go/no-go gate. Astra reviewed four rollout plans (NO_GO each: concurrency with the hourly seal, pointer rollback not executable, content only checked after publication, then a driver-level recovery state machine, continuous lease monitoring, conservative quota accounting) and every verdict adds that a production mutation needs explicit current-session authorization it cannot establish from a quoted instruction. Ready for the operator: driver v2 with 15 fault-injection tests, plan v4 and all reviews in `_archive\rollout-2026-09-27` (Astra NO_GO 4 lists the remaining ten changes); live compatibility: the new Worker reads today's sealed v3, refuses 76 Stockholm options cycles without a high-strike delta (options are already past their 6 h bound); the old 16cb1b3 reader reads a full-tier candidate built by the new code path. Decide: authorize and supervise the rollout (the driver's phases or the earlier manual procedure), or have the driver finished first.

Closed today: lanes 1, 4, 6, 7, 8, 9, 10, 11, 12, 13.

Lane 4 compatibility exception (Astra review 2): with a valid, fresh v3 document every ranking word opens v3. Without one, words the certified seven-field Top20 path already matched (`top 20`, `前20`, `排行`, `排名` as substrings, so also `瓶頸排名`, `瓶頸TOP20`) keep that certified path, which can show the sealed seven-field report; only words new to ranking (`瓶頸榜`, `前二十`) and `瓶頸爆發榜` answer the v3 unavailability notice. This is not universal v3-only fail-closed behaviour; retiring the seven-field path needs its own product decision and recertification.

## Closed components — no reopening without regression evidence

- Top20 single-writer programme T1–T11 (`90563ee` … `f5bfe78`); T1 finite fractional ordering (`5208d64`), T2 nonauthorizing period declarations (`26842de`), T3 forward comparison declaration diagnostic (`689a682` → `a944410`); O1 options venue coverage shadow (`11436e6`), Case9 (`c178127`), R3A (`e45c1d6`), research method quarantine (`c6ce527`); I1/I2/I3 identity shadows, E2A synthetic capacity, hermetic fixtures. Preserved failures and receipts remain immutable (V12 register).

## Boundary flags

NATIVE_ATTEMPT_COUNT=0; NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; publication_eligible=false for candidates; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY for company proof, leads the industry ranking since 2026-09-26 (operator).

## Control plane

Claude Code is master and single tracked writer (operator 2026-09-25). Reviews moved to Astra (operator 2026-09-27): Herdr `astra-review` (w9:p9, Pi `openai-codex/gpt-6-astra`, thinking high) gives the read-only acceptance verdict on every batch before commit, arbitrates disagreeing reviews and gives go/no-go on each rollout plan (workspace `AGENTS.md`). `qwen-local` (w9:p5, ninfer Qwen3.8-27B) proposes patches and analyses code; `gemini-review` (w9:p7, Gemini 3.8 flash) researches. ChatGPT Pro through `chatgpt-web` is an optional second opinion on large batches. Each Herdr task starts with `/new` (send it with `MSYS_NO_PATHCONV=1` from Git Bash). The wB panes and the Skyrim ChatGPT profile belong to another project.

## Workspace fixes (outside the repository, logged)

- Pi `[Extension issues]`: `pi-mcp-adapter` failed because `~\.pi\agent\settings.json` had a UTF-8 BOM written by `Configure-Pi-NInfer.ps1` (Windows PowerShell `Set-Content -Encoding UTF8`). The kit and installed copies now write UTF-8 without BOM and read UTF-8; `models.json` BOM removed; the project `.pi/sol-pi.json` reducer that named the removed `tabby-local` provider is off. Receipt `_archive\extension-issues-fix-20260926T132956Z\RECEIPT.md`.
- `.mcp.json` and workspace `AGENTS.md` preimages: `_archive\chatgpt-web-mcp-switch-20260926T135913Z`.

- `D:\chatgpt-web-mcp\src\selectors.js`: the zh-TW new-chat control is `<button aria-label="新對話">` (a collapsed sidebar keeps a hidden copy first), so new chats always failed their check; four `:visible` button selectors added (preimage in the switch archive; the MCP's tests 37/38 before and after, the failure is a pre-existing Windows path assertion).
- `D:\chatgpt-web-mcp` local branch `local/zh-tw-lanes` (c46501a, not pushed): per-project lanes on one browser (`CHATGPT_WEB_LANE`, own tab/lock/state, shared circuit breaker), zh-TW new-chat button. `.mcp.json` sets `CHATGPT_WEB_LANE=investor`. The MCP's message selectors do not match the current ChatGPT page (`data-content-search-unit-key` replaced `data-message-author-role`): sends work but it never sees the answer, so read answers from the tab (as for `%TEMP%\ii-live\chatgpt-review-6ab7*.answer.md`) until the selectors are updated.

## Handoff (2026-09-27 03:25)

- Production is untouched by this session. The hourly seal task was left running: after the KV quota reset at 08:00 its 08:12 run should restore a fresh pointer on its own (checked read-only afterwards; see below if recorded).
- Operator decisions pending: lane 14 (above); the plaintext Alpha Vantage note on the desktop.
- Tooling left in place: old-reader worktree `%TEMP%\ii-live\wt-16cb1b3` (git worktree at 16cb1b3, `cloud\node_modules` is a junction to the source checkout's); `chatgpt-web` lane `investor` with fixed selectors (branch `local/zh-tw-lanes` in `D:\chatgpt-web-mcp`, commits c46501a and d738974).
- Scratch: `%TEMP%\ii-live`.
