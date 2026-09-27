# Current state / 目前狀態

Updated 2026-09-27 (11:30 Asia/Taipei) by an operator-directed Claude Code session (master and single tracked writer; operator authority 2026-09-25/26). Earlier detail: `git show 5b15984:state/STATUS.md` (09:40, commits after 20:45, gate run 23), `git show 3ac39a1:state/STATUS.md` (20:45 seal, full production record), `git show a8c6e58:state/STATUS.md` (17:15), `git show 59049db:state/STATUS.md`, `git show 38860e7:state/STATUS.md`; V12 `git show 0f5358b:state/STATUS.md`. Release identity stays in `README.md`.

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main`; PR CI reports COMPLETED_SKIPPED (not PASS). DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false.

## Production (recovered 2026-09-27 08:12; code unchanged since 2026-09-26 20:45)

- Worker `25377354-0ff5-4a28-a78b-82ec2457729f` (source `16cb1b3`); runtime LOCAL_SOURCE_CHECKOUT `ff6dc42`, tx `75cc59dc…`; hourly task `InvestorIntelligenceSealedFreshness` (:12); LINE Q&A relay on ninfer `Qwen3.8-27B`. Rollback order: `git show 3ac39a1:state/STATUS.md`.
- Outage 22:45-08:12: every seal failed on Cloudflare's free KV write quota (code 10048; five reinstalls, several manual seals and a Chinese-name cache fill that rewrote 52 identity shards an hour). The untouched hourly task recovered after the 08:00 reset: 08:12 seal (15 uploads), 09:12 seal `20260927T011233Z-80d7c5b186c1` (23 uploads), post gate `-ExpectTop20Records 20` PASS; read-only replay: seven-field Top20 fresh (20), v3 20, NVDA options VALID.
- The new validators refuse the live SIVE.ST and VOLV-B.ST option cycles (no high-strike delta), so the new Worker must only go live after data built by the new runtime is sealed.

## Commits after 20:45 (not deployed)

`13d7c85` … `5b15984`: lanes 2/3/4/6, KV quota handling, two ChatGPT Pro reviews, reader replay v3 (table and gate run 23 in `git show 5b15984:state/STATUS.md`). This commit (batch 27): lanes 15 and 16.

Batch 27 review record: Astra REJECT on the first horizons/options draft (5 items), REJECT on batch 25 (collector bound, lineage temporal consistency, horizon overflow, producer boundary; the producer part implemented by `qwen-local` in an isolated worktree), REJECT on batch 26 (universe discovery outside the deadline, legacy lineage erased across the sealer→Worker boundary, revenue guidance labelled as new orders, this file); batch 27 fixes all of them and adds a sealer↔Worker wire-contract fixture (`tests/fixtures/v213-lineage-sealed-markets.json`). Gates (Python 3.12.10, `PYTHONUTF8=1` as in CI): security, documentation boundary/structure, workflow supply chain PASS; typecheck PASS; vitest 969 passed / 2 skipped; focused unittest 59 OK; offline suite run 27 (`%TEMP%\ii-live\offline-full-27.txt`). Without `PYTHONUTF8=1` `test_v213_market_products.test_cli_builder_synthetic_fixture` fails (child output in cp950; run 25); `.venv-ci` lacks pandas although `requirements-ci.txt` pins it. Astra ACCEPT on batch 27 (`%TEMP%\ii-livestra-accept-batch27.result.md`). Known limits: process exit is bounded by daemon containment, not by cancelling every socket read (yfinance and a blocked read may outlive the deadline inside abandoned workers; not a guarantee for a resident process); a new IPO/spin-off stays excluded until curated. Next: any rollout still needs the operator's current-session authorization and an Astra go/no-go (lane 14).

## Operator decisions (2026-09-26)

- ChatGPT review MCP is now `chatgpt-web` (`D:\chatgpt-web-mcp\src\index.js`, dedicated signed-in Chrome profile, zh-TW UI) in the workspace `.mcp.json`, replacing `chatgpt-codex` (`scripts/codex_review_mcp.py`, kept in the repo). Pro first; 極高 only when Pro is locked or spent. On 22:00 the tier slider showed 極高 (4 of 5) and the fifth (Pro) position 「已鎖定」. Its selectors are zh-CN/English: use only `chatgpt_send_message` (`answerTier`, `newChat`, inline prompt) and `chatgpt_route_new_chat`; no uploads or mode/model/thinking options. Rule recorded in the workspace `AGENTS.md`. No pointless questions.
- Local model: ninfer `Qwen3.8-27B` on :8080 (shared GPU, concurrency 1); the System One decider stays retired. Alpha Vantage key as DPAPI ciphertext; the plaintext desktop note is still the operator's to delete. No OpenDART/data.go.kr key; Nasdaq data accepted; Google Finance rejected.

## Open lanes

2. Source diversity: official fundamentals now stand beside Yahoo for Taiwan (TWSE/TPEx monthly revenue), Stockholm (SIVE via Cision; robots.txt allows it; MFN RSS disallowed) and Korea (curated IR config; SK hynix's newsroom terms forbid robots). Refresh the Korea config after each earnings release. Still single: Japan fundamentals (EDINET needs a key), Japan/Korea price shards (Yahoo daily closes), consensus outside the US.
3. Orders: MU fixed. CRWV (24M only) and SNDK (12M only) disclose no other horizon. AXTI ("through the first half of 2029") and NBIS (20-F/6-K, 28%→36% within 24M) have no deep report (only domestic SEC filers get one): DEFERRED_WITH_REASON until foreign-filer deep reports exist. Korea HD Hyundai Electric deck unreadable keylessly.
5. Deferred: report-age gates for carried reports and federation readers (certified `cloud/src/qa.ts` needs recertification); the CI R75 route blocks release qualification.
14. Rollout of `3ac39a1..ef9d221`: DEFERRED_WITH_REASON, blocked at the go/no-go gate. Astra reviewed four rollout plans (NO_GO each: concurrency with the hourly seal, pointer rollback not executable, content only checked after publication, then a driver-level recovery state machine, continuous lease monitoring, conservative quota accounting) and every verdict adds that a production mutation needs explicit current-session authorization it cannot establish from a quoted instruction. Ready for the operator: driver v2 with 15 fault-injection tests, plan v4 and all reviews in `_archive\rollout-2026-09-27` (Astra NO_GO 4 lists the remaining ten changes); live compatibility: the new Worker reads today's sealed v3, refuses 76 Stockholm options cycles without a high-strike delta (options are already past their 6 h bound); the old 16cb1b3 reader reads a full-tier candidate built by the new code path. Decide: authorize and supervise the rollout (the driver's phases or the earlier manual procedure), or have the driver finished first.

15. Listing lineage (operator 2026-09-27: "Sandisk is not a new company"): `config/listing-lineage-v1.json` (SNDK spin-off from WDC, regular way 2025-02-24; NBIS resumption after Yandex N.V.; ALAB/CRWV IPO; CORZ new equity), primary sources re-read; `scripts/listing_lineage.py` shared by producer and sealer, same rules in the Worker. The long-term figure starts at the first regular-way session (Yahoo's first SNDK bar 2025-02-13 is when-issued: +1027%/yr → +872%/yr), needs 365 days, never fabricates two years; unverified short history is excluded (`HISTORY_OR_LINEAGE_UNVERIFIED`). Ranking on 2026-09-27 closes: no inclusion change (gate only). A new IPO/spin-off in a layer is excluded until curated: check `excluded` after each v3 build.
16. Top20 horizons and options (operator 2026-09-27): future ORDER estimate and price scenario with 6-month/1-year horizons from the report date; RPO coverage labelled as revenue only; option answers for Chinese names, ADR routes (TSMC→TSM 1:5, UMC, ASX) and a coverage statement elsewhere (IQE); options universe 200 largest US names under one 20-minute run deadline (daemon workers, last-good file kept when >50% unfinished; live run 313 underlyings in 285 s).

Closed today: lanes 1, 4, 6, 7, 8, 9, 10, 11, 12, 13.

Lane 4 compatibility exception (Astra review 2): with a valid, fresh v3 document every ranking word opens v3. Without one, words the certified seven-field Top20 path already matched (`top 20`, `前20`, `排行`, `排名` as substrings, so also `瓶頸排名`, `瓶頸TOP20`) keep that certified path, which can show the sealed seven-field report; only words new to ranking (`瓶頸榜`, `前二十`) and `瓶頸爆發榜` answer the v3 unavailability notice. This is not universal v3-only fail-closed behaviour; retiring the seven-field path needs its own product decision and recertification.

## Closed components — no reopening without regression evidence

- Top20 single-writer programme T1–T11 (`90563ee` … `f5bfe78`); T1 finite fractional ordering (`5208d64`), T2 nonauthorizing period declarations (`26842de`), T3 forward comparison declaration diagnostic (`689a682` → `a944410`); O1 options venue coverage shadow (`11436e6`), Case9 (`c178127`), R3A (`e45c1d6`), research method quarantine (`c6ce527`); I1/I2/I3 identity shadows, E2A synthetic capacity, hermetic fixtures. Preserved failures and receipts remain immutable (V12 register).

## Boundary flags

NATIVE_ATTEMPT_COUNT=0; NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; publication_eligible=false for candidates; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY for company proof, leads the industry ranking since 2026-09-26 (operator).

## Control plane

Claude Code is master writer (operator 2026-09-25): the single tracked writer that integrates, tests and commits. Panes (operator 2026-09-27, JEV-selected minimal loads, receipt `_archive\pane-slimming-20260927T022638Z`): tab w9:t4 `astra-review` (pA), `gemini-review` (pB, + antigravity, web access, serenity skill), `qwen-local` (pC, isolated worktree patches). Astra (operator 2026-09-27; Pi `openai-codex/gpt-6-astra`) writes bounded task contracts for complex lanes, prioritises lanes, gives the acceptance verdict on every batch before commit, arbitrates reviews and gives go/no-go on rollouts. `qwen-local` implements contracts and proposes patches; `gemini-review` researches; ChatGPT Pro via `chatgpt-web` is optional. Each Herdr task starts with `/new` (send with `MSYS_NO_PATHCONV=1` from Git Bash). The wB panes and the Skyrim ChatGPT profile belong to another project.

## Workspace fixes (outside the repository, logged)

Pi extension BOM fix, `chatgpt-web` MCP switch and its zh-TW lane branch `local/zh-tw-lanes` in `D:\chatgpt-web-mcp` (details: `git show 5b15984:state/STATUS.md`); its message selectors do not see answers (`data-content-search-unit-key` replaced `data-message-author-role`), so read answers from the tab. Pane slimming: `_archive\pane-slimming-20260927T022638Z`.

## Handoff (2026-09-27 03:25)

- Production is untouched by this session and recovered on its own (Production above).
- Lane 14 path (Astra contract `_archive\rollout-2026-09-27\reviews\astra-contract-driver-v3.md`): driver v3 in four batches, each needing Astra ACCEPT: A offline-only core (state machine, time/quota/identity/acceptance logic, ~30 fault tests, every live action disabled), B holder/task/install adapters with Windows job-object containment, C per-PUT guarded sync, D integration evidence. Even then a rollout needs the operator's explicit current-session authorization and Astra GO. Operator to choose: fund batches A-D (Qwen implements, Astra accepts), or authorize and supervise a rollout now.
- Operator decisions pending: lane 14 (above); the plaintext Alpha Vantage note on the desktop.
- Tooling left in place: old-reader worktree `%TEMP%\ii-live\wt-16cb1b3` (git worktree at 16cb1b3, `cloud\node_modules` is a junction to the source checkout's); `chatgpt-web` lane `investor` with fixed selectors (branch `local/zh-tw-lanes` in `D:\chatgpt-web-mcp`, commits c46501a and d738974).
- Scratch: `%TEMP%\ii-live`.
