# Current state / 目前狀態

Updated 2026-09-27 23:20 Asia/Taipei by Claude Code (sole tracked writer). Previous text: `git show 4be0888:state/STATUS.md` (ORDERS-V2-01 detail); `git show 349a332:state/STATUS.md`; `git show 914f0e6:state/STATUS.md`; earlier `git show e2365cd:state/STATUS.md`, `git show 5b15984:state/STATUS.md`, `git show 3ac39a1:state/STATUS.md` (full production record), `git show a8c6e58:state/STATUS.md`, `git show 59049db:state/STATUS.md`, `git show 38860e7:state/STATUS.md`; V12 `git show 0f5358b:state/STATUS.md`. Release identity stays in `README.md`. Root and source `AGENTS.md` override older control-plane text in this file's history.

## Identity

- This batch is an uncommitted candidate on `fix/options-provenance-audit` at `4be0888` (ORDERS-V2-01, pushed). Planned after writer and Astra acceptance: commit and push. CI on this branch ends COMPLETED_SKIPPED by design (`final-release-candidate-v3-pre-rewrite-audit.yml` runs only for head `integration/final-release-candidate-v3`): not PASS. Non-release-qualified (LOCAL_SOURCE_CHECKOUT). DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false.

## This batch: L18-5351-CURATED-01 (Astra contract `_archive\lane-dispatch-20260927T0905Z\astra-5351-contract.result.md`)

Gemini drafted the patch in worktree `_workspace\gemini-l18-5351` (`gemini-l18-5351.patch`); the writer reworked it before acceptance (sealer rebuild and strip, integer claims, exact shapes, reconciliations tied to claims, half-year claims in the evidence, no digest or issuer hard-coded in the Worker, Python-emitted fixture, real `build` test).
- `config/official-quarterly-revenue-v1.json`: one record, 5351.TWO current 2026-06-30 / previous 2026-03-31, TWD thousands, consolidated IAS 34, CPA-reviewed Etron Q1/Q2 reports (hashes, sizes, retrieval, printed page 39/42, note 六(二十四)); transcription re-checked against `evidence-5351\writer-pdftotext-115Q*.txt`.
- `scripts/official_quarterly_revenue.py`: total validation (exact keys, bounded single-line text, issuer host `etron.com`, dates and clock, integer amounts, adjacent calendar quarters, half-year minus Q2 equals each Q1 claim); `evaluate` for the builder (financialCurrency TWD, all three overlaps within 1000 TWD, current YoY within 0.00001, else a bounded reason); `seal_evidence` rebuilds the evidence from the local config digest and refuses any difference.
- `scripts/bottleneck_top20_v3.py`: only an absent comparator takes the official pair (previous YoY 3.3618 = 2,735,412/627,130 − 1); rejections keep the Yahoo fundamentals, previous YoY null, local `revenue_yoy_prev_reason`. `publish_sealed_snapshot.py` refuses the v3 object on any contradiction. `cloud/src/v213/bottleneck-v3.ts` repeats the checks (document refused) and attributes the previous quarter separately (card, text and card detail).
- Tests: `tests/test_official_quarterly_revenue.py`, `OfficialPreviousQuarterTests` (yahoo_data, build, sealer, fixture `tests/fixtures/v213-official-quarterly-revenue.json`), Worker case in `cloud/test/v213-bottleneck-v3.test.ts`.
- Review: Astra REJECT r1 (`astra-accept-l18-5351.result.md`): (1) the absence test ran after `dropna()`, so an empty comparator cell or a later empty column revived the record; (2) the Worker lacked calendar, chronology (published ≤ retrieved ≤ `generated_at`) and single-line text checks; (3) this evidence summary. Revision 2: a later statement column withholds the record (PERIOD_MISMATCH); an empty (NaN/None) cell counts as absent because that is Yahoo's own shape for 5351.TWO (`yahoo-5351-shape-20260927T1530Z.txt`: 2025-03-31 present, NaN) — submitted for Astra's ruling; present zero/negative/inf values keep Yahoo's arithmetic; Worker checks mirror the sealer.
- Evidence: r1 gates `gates-l18-5351\` — security, documentation, supply-chain 0; `npm test` 991 passed; `run_offline_tests.py --repository` 2901 tests with 1 failure (this file lacked the `38860e7` pointer; fixed, module rerun OK — not a full-suite PASS). Revision 2 gates: `gates-l18-5351-r2\` (writer result r2).
- Rollout order for this batch: Worker before data (the deployed reader would attribute the figure to Yahoo). Not part of rollout v6.

Previous batch: ORDERS-V2-01 (`4be0888`, Astra ACCEPT r6 after five REJECTs; detail in `git show 4be0888:state/STATUS.md`).

## Production — read back 2026-09-27 18:30–18:45 (operator: 授權回讀核對; read-only)

Receipt `_archive\lane14-readback-20260927T1036Z\RECEIPT.md` supersedes the earlier OUTCOME_UNKNOWN assessment: rollout v5 was not executed after P0. Observed then: Worker 25377354… (created 2026-09-26T12:07Z, source 16cb1b3) ready; runtime ff6dc42 tx 75cc59dc FINALIZED; SealedFreshness, FreshnessWatchdog, v213-FreeRelay and InvestorDailyBriefing enabled, actions identical to P0; KV pointer at the 18:12 hourly seal (run 20260927T101233Z-7113fe1deb03, 76 objects, no seal mismatch); reader replay 16cb1b3 (v2) and HEAD (v3) PASS 20/20. This is a read-back of state, not an exhaustive event history. `3ac39a1..HEAD` is undeployed; the live bottleneck outlook is still RPO stock plus analyst-consensus scenarios.
- Rollback target: Worker 25377354 / runtime ff6dc42 (order in `git show 3ac39a1:state/STATUS.md`).
- New validators refuse historical SIVE.ST/VOLV-B.ST option cycles, so a new Worker may only go live after data built by the new runtime is sealed.
- Rollout history: Astra NO_GO on plans 1–4, conditional GO on v5 for one window on `dec7bd0` (`%TEMP%\ii-live\astra-rollout5.result.md`, journal `%TEMP%\ii-live\rollout5\journal.md`); neither is authorization for another snapshot.

## Authorization and queue

Operator 2026-09-27 18:51 "繼續並核准相關授權" (`_archive\authorization-20260927T1051Z\AUTHORIZATION.md`, writer-interpreted scope) was given in an earlier session; the executing session must re-obtain it (Astra v6 condition 1). Excluded: real LINE delivery, credentials, billing, broker actions, merge/tag/release.

1. L18-5351-CURATED-01: this batch; complete only after writer and Astra acceptance, commit and push. The other four lane-18 listings DEFERRED_WITH_REASON.
2. Rollout v6 of `4be0888db6a15edd6776f9dc1a32bb3af2b1f563` (`_archive\rollout-2026-09-28\rollout-plan-v6.md`): Astra conditional GO for one supervised window after 2026-09-28 00:00 UTC with eleven mandatory conditions (`astra-rollout6.result.md`); needs current-session operator authorization. Until the new Worker serves, each night's hourly seals fail once the free KV writes are spent (22:12 SYNC ABORT; last recorded successful pointer `20260927T121233Z-55793fcead2e`).
3. Lane 19 CRDO: CRDO-RPO-01 closed BLOCKED_INPUTS by Astra (not COMPLETE). MU waits for its FQ4 FY26 10-K (report 2026-09-30).
4. Local Qwen: available on ninfer when idle; dispatch delays LINE answers.
5. DEFERRED_WITH_REASON: lanes 2, 3, 5 (below), driver v3 A–D.

## Commits since 2026-09-26 20:45

`13d7c85` … `5b15984`: lanes 2/3/4/6, KV quota handling, ChatGPT Pro reviews, reader replay v3. `aa54416`/`bb95f97`: lanes 15/16. `33d7938`: lanes 17/18. `eca78a1`: lane 19 v1. `dec7bd0`: `AGENTS.md`. `e2365cd`: STATUS reconcile. `914f0e6`: PY-LOCAL-01. `349a332`: NINFER-DEFAULTS-01. `4be0888`: ORDERS-V2-01. None deployed.

## Operator decisions (2026-09-26)

ChatGPT review MCP is `chatgpt-web` (workspace `AGENTS.md`); `scripts/codex_review_mcp.py` stays in the repo. No pointless questions. Alpha Vantage key is DPAPI ciphertext; the plaintext desktop note is the operator's to delete. No OpenDART/data.go.kr key; Nasdaq data accepted; Google Finance rejected.

## Open lanes

2. Source diversity: official fundamentals beside Yahoo for Taiwan (TWSE/TPEx), Stockholm (SIVE via Cision) and Korea (curated IR config; refresh after earnings). Still single: Japan fundamentals (EDINET needs a key), Japan/Korea price shards, consensus outside the US.
3. Orders: CRWV (24M only) and SNDK (12M only) disclose no other horizon. AXTI and NBIS have no deep report (domestic SEC filers only). Korea HD Hyundai Electric deck unreadable keylessly.
5. Deferred: report-age gates for carried reports and federation readers (certified `cloud/src/qa.ts` needs recertification); the CI R75 route blocks release qualification.
17. LINE Q&A relay (Worker → quick tunnel → gateway :8814 → ninfer :8080): gateway health OK at 18:25. Nightly heartbeat failures from one KV nonce per heartbeat are fixed in 33d7938 (undeployed).
18. Dilution: shares_yoy from the quarter's diluted weighted average when shares outstanding are missing. Previous-quarter YoY for Yahoo listings: 5351.TWO from the official pair in this batch; the other four listings DEFERRED_WITH_REASON.
19. Order forecast: v1 in `eca78a1`, v2 in `4be0888` (both undeployed). No Top20 company discloses a 6-month schedule (2026-09-27 survey).

Closed: lanes 1, 4, 6–13, 15, 16. Lane 15 upkeep: a new IPO or spin-off stays excluded (`HISTORY_OR_LINEAGE_UNVERIFIED`) until `config/listing-lineage-v1.json` has its primary-source record; check `excluded` after each v3 build.

Lane 4 compatibility exception (Astra review 2): with a valid fresh v3 document every ranking word opens v3. Without one, words the certified seven-field path already matched (`top 20`, `前20`, `排行`, `排名` as substrings, so also `瓶頸排名`, `瓶頸TOP20`) keep that path, which can show the sealed seven-field report; only `瓶頸榜`, `前二十` and `瓶頸爆發榜` answer the v3 unavailability notice. Retiring the seven-field path needs its own product decision and recertification.

## Closed components — no reopening without regression evidence

Top20 single-writer programme T1–T11 (`90563ee` … `f5bfe78`); T1 (`5208d64`), T2 (`26842de`), T3 (`689a682` → `a944410`); O1 options venue coverage shadow (`11436e6`), Case9 (`c178127`), R3A (`e45c1d6`), research method quarantine (`c6ce527`); I1/I2/I3 identity shadows, E2A synthetic capacity, hermetic fixtures. Preserved failures and receipts stay immutable (V12 register).

## Boundary flags

NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; publication_eligible=false for candidates; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY for company proof, leads the industry ranking since 2026-09-26 (operator).

## Control plane (root `AGENTS.md`, operator 2026-09-27)

Astra (`astra-review`, w9:pA): priorities, contracts, acceptance, arbitration, go/no-go; read-only. Claude Code: sole tracked writer. Gemini (`gemini-review`, w9:pB): research and audits. Both load JEV (`pi-typesafe`, daily cap 60; `_archive\jev-panes-20260927T0930Z\RECEIPT.md`). Qwen (`qwen-local`, w9:pC) was started at 18:52 on ninfer `Qwen3.8-27B` without JEV (JEV .74) and implemented NINFER-DEFAULTS-01; pane state changes, so check it before dispatch. Each Herdr task starts with `/new` (send with `MSYS_NO_PATHCONV=1` from Git Bash). The wB panes belong to another project. `chatgpt-web` selectors do not see answers; read them from the tab.

## Handoff

- Next: Astra acceptance of this snapshot, commit and push; rollout v6 of `4be0888` in the window after 2026-09-28 08:00 Asia/Taipei once the operator re-authorizes it in that session; a later rollout carries this batch (Worker first).
- Operator: the plaintext Alpha Vantage note; whether a 6-month figure may ever be a labelled model estimate (currently shown as 未揭露 when undisclosed).
- Tooling: old-reader worktree `%TEMP%\ii-live\wt-16cb1b3` (`cloud\node_modules` is a junction to the source checkout's); Qwen worktree `_workspace\qwen-ninfer-defaults` and Gemini worktree `_workspace\gemini-l18-5351` (patch integrated, branch not merged); `chatgpt-web` lane `investor` (branch `local/zh-tw-lanes`). Scratch: `%TEMP%\ii-live`.
