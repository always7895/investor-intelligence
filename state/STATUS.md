# Current state / 目前狀態

Updated 2026-09-27 19:40 Asia/Taipei by Claude Code (sole tracked writer). Previous text: `git show 914f0e6:state/STATUS.md`; earlier `git show e2365cd:state/STATUS.md`, `git show dec7bd0:state/STATUS.md`, `git show 5b15984:state/STATUS.md`, `git show 3ac39a1:state/STATUS.md` (full production record), `git show a8c6e58:state/STATUS.md`, `git show 59049db:state/STATUS.md`, `git show 38860e7:state/STATUS.md`; V12 `git show 0f5358b:state/STATUS.md`. Release identity stays in `README.md`. Root and source `AGENTS.md` override older control-plane text in this file's history.

## Identity

- This batch is an uncommitted candidate on the isolated worktree branch `qwen/ninfer-defaults` at base `914f0e6a26033af3e5af0b406995bc84aaafe06d`. Planned after writer and Astra acceptance: commit there, fast-forward the integration target `fix/options-provenance-audit` (draft PR #37 to `main`) and push it. CI on the working branch ends COMPLETED_SKIPPED by design (`final-release-candidate-v3-pre-rewrite-audit.yml` runs only for head `integration/final-release-candidate-v3`): not PASS. Non-release-qualified (LOCAL_SOURCE_CHECKOUT). DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false.

## This batch: NINFER-DEFAULTS-01

Operator 2026-09-27: TabbyAPI `:5000` and `Qwen3.8-27B-EXL3-5.5bpw-v2` were removed; the local model is ninfer (`D:\ninfer\ninfer-serve.exe`, `http://127.0.0.1:8080`, `Qwen3.8-27B`, `--max-concurrency 1`, shared with the LINE gateway :8814). Implemented by qwen-local on ninfer; revision 2 after an Astra REJECT for missing current-doc corrections.
- Defaults: `config/local-runtime-independence-v1.json` (primary reasoner `http://127.0.0.1:8080/v1`, `Qwen3.8-27B`), launcher `DefaultLlamaBase` :8080, `scripts/run_v213_local_llm_bridge_core.ps1`, `scripts/run_production_sealed_refresh.ps1` (defaults only; parameter names kept for the installed task actions); two tests.
- Current wording: `docs/LOCAL_RUNTIME_INDEPENDENCE.md`, `docs/MODEL_RUNTIME_MIGRATION.md`, gateway docstrings/comments (no logic change), source `AGENTS.md`: the System One decider is retired (source qualification alone); dated history kept.
- Open, not in this batch: `scripts/v213_qa_capacity.py` still pins the removed model (recertification decision); the opt-in manual live harness `cloud/test/manual/v213-task0-general-qa-live.manual.ts`; port 5000 in the known-port lists (now the IBKR Client Portal; a discovery-policy follow-up across launcher, bridge and detector). The installed EXE (2026-09-07) has no port/model discovery; the source launcher and `scripts/local_model_endpoint.py` do (live: ninfer :8080 `Qwen3.8-27B`, gateway health OK at 18:25). A rebuilt EXE needs the install step of the authorized rollout and an Astra GO.
- Gates (`.venv-local-gates`, PYTHONUTF8=1) ran on the revision-2 candidate with its earlier STATUS text: security, documentation boundary/structure, workflow supply-chain exit 0; `run_offline_tests.py --repository` 2,854 OK (19:17–19:27, overlapping the :12–:25 seal window without an operation-lock collision). Revision 3 changes only this file; on it the writer reran `tests.test_agent_skill_structure` and the documentation structure gate. No Worker change.

Previous batch PY-LOCAL-01 (`914f0e6`, writer and Astra ACCEPT): non-destructive local Python resolver with `-InstallLockedDependencies`; local gates run from `.venv-local-gates` (`docs/DEPENDENCY_LOCKING.md`).

## Production — read back 2026-09-27 18:30–18:45 (operator: 授權回讀核對; read-only)

Receipt `_archive\lane14-readback-20260927T1036Z\RECEIPT.md` supersedes the earlier OUTCOME_UNKNOWN assessment: rollout v5 was not executed after P0. Observed then: Worker 25377354… (created 2026-09-26T12:07Z, source 16cb1b3) ready; runtime ff6dc42 tx 75cc59dc FINALIZED; SealedFreshness, FreshnessWatchdog, v213-FreeRelay and InvestorDailyBriefing enabled, actions identical to P0; KV pointer at the 18:12 hourly seal (run 20260927T101233Z-7113fe1deb03, 76 objects, no seal mismatch); reader replay 16cb1b3 (v2) and HEAD (v3) PASS 20/20. This is a read-back of state, not an exhaustive event history. `3ac39a1..HEAD` is undeployed; the live bottleneck outlook is still RPO stock plus analyst-consensus scenarios.
- Rollback target: Worker 25377354 / runtime ff6dc42 (order in `git show 3ac39a1:state/STATUS.md`).
- New validators refuse historical SIVE.ST/VOLV-B.ST option cycles, so a new Worker may only go live after data built by the new runtime is sealed.
- Rollout history: Astra NO_GO on plans 1–4, conditional GO on v5 for one window on `dec7bd0` (`%TEMP%\ii-live\astra-rollout5.result.md`, journal `%TEMP%\ii-live\rollout5\journal.md`); neither is authorization for another snapshot.

## Authorization and queue

Operator 2026-09-27 18:51 "繼續並核准相關授權" (`_archive\authorization-20260927T1051Z\AUTHORIZATION.md`, writer-interpreted scope): runtime/EXE installation, the task pause/resume that install needs, Worker deployment, KV publication/seal within a stated write budget, transaction/rollback/finalize and read-back — each only after an Astra GO on a fixed-snapshot rollout plan. Excluded: real LINE delivery, credentials, billing, broker actions, merge/tag/release. It does not approve any review or an unspecified snapshot.

1. ORDERS-V2-01 (Astra contract `_archive\lane-dispatch-20260927T0905Z\astra-orders-v2.result.md`): in progress in the working tree (dated issuer claims registry, two-horizon wording, model sensitivity); needs writer and Astra acceptance.
2. Rollout of the accepted snapshot: plan for Astra GO; deploy the reader before sealing version-2 data (the deployed 16cb1b3 reader ignores the field; the eca78a1 reader shows version 2 as unavailable).
3. L18-5351-CURATED-01 (contract `astra-5351-contract.result.md`, evidence verified): queued after ORDERS-V2; the other four lane-18 listings DEFERRED_WITH_REASON.
4. Lane 19 CRDO: CRDO-RPO-01 closed BLOCKED_INPUTS by Astra (RPO only as an extension XBRL concept; not COMPLETE). MU waits for its FQ4 FY26 10-K (report 2026-09-30).
5. Local Qwen: available on ninfer when idle; dispatch delays LINE answers.
6. DEFERRED_WITH_REASON: lanes 2, 3, 5 (below), driver v3 A–D.

## Commits since 2026-09-26 20:45

`13d7c85` … `5b15984`: lanes 2/3/4/6, KV quota handling, ChatGPT Pro reviews, reader replay v3. `aa54416`/`bb95f97`: lanes 15/16. `33d7938`: lanes 17/18. `eca78a1`: lane 19. `dec7bd0`: `AGENTS.md`. `e2365cd`: STATUS reconcile. `914f0e6`: PY-LOCAL-01. None deployed.

## Operator decisions (2026-09-26)

ChatGPT review MCP is `chatgpt-web` (workspace `AGENTS.md`); `scripts/codex_review_mcp.py` stays in the repo. No pointless questions. Alpha Vantage key is DPAPI ciphertext; the plaintext desktop note is the operator's to delete. No OpenDART/data.go.kr key; Nasdaq data accepted; Google Finance rejected.

## Open lanes

2. Source diversity: official fundamentals beside Yahoo for Taiwan (TWSE/TPEx), Stockholm (SIVE via Cision) and Korea (curated IR config; refresh after earnings). Still single: Japan fundamentals (EDINET needs a key), Japan/Korea price shards, consensus outside the US.
3. Orders: CRWV (24M only) and SNDK (12M only) disclose no other horizon. AXTI and NBIS have no deep report (domestic SEC filers only). Korea HD Hyundai Electric deck unreadable keylessly.
5. Deferred: report-age gates for carried reports and federation readers (certified `cloud/src/qa.ts` needs recertification); the CI R75 route blocks release qualification.
17. LINE Q&A relay (Worker → quick tunnel → gateway :8814 → ninfer :8080): gateway health OK at 18:25. Nightly heartbeat failures from one KV nonce per heartbeat are fixed in 33d7938 (undeployed).
18. Dilution: shares_yoy from the quarter's diluted weighted average when shares outstanding are missing. Previous-quarter YoY for Yahoo listings: see queue item 3.
19. Order forecast: v1 in `eca78a1` (undeployed); v2 is queue item 1. No Top20 company discloses a 6-month schedule (2026-09-27 survey).

Closed: lanes 1, 4, 6–13, 15, 16. Lane 15 upkeep: a new IPO or spin-off stays excluded (`HISTORY_OR_LINEAGE_UNVERIFIED`) until `config/listing-lineage-v1.json` has its primary-source record; check `excluded` after each v3 build.

Lane 4 compatibility exception (Astra review 2): with a valid fresh v3 document every ranking word opens v3. Without one, words the certified seven-field path already matched (`top 20`, `前20`, `排行`, `排名` as substrings, so also `瓶頸排名`, `瓶頸TOP20`) keep that path, which can show the sealed seven-field report; only `瓶頸榜`, `前二十` and `瓶頸爆發榜` answer the v3 unavailability notice. Retiring the seven-field path needs its own product decision and recertification.

## Closed components — no reopening without regression evidence

Top20 single-writer programme T1–T11 (`90563ee` … `f5bfe78`); T1 (`5208d64`), T2 (`26842de`), T3 (`689a682` → `a944410`); O1 options venue coverage shadow (`11436e6`), Case9 (`c178127`), R3A (`e45c1d6`), research method quarantine (`c6ce527`); I1/I2/I3 identity shadows, E2A synthetic capacity, hermetic fixtures. Preserved failures and receipts stay immutable (V12 register).

## Boundary flags

NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; publication_eligible=false for candidates; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY for company proof, leads the industry ranking since 2026-09-26 (operator).

## Control plane (root `AGENTS.md`, operator 2026-09-27)

Astra (`astra-review`, w9:pA): priorities, contracts, acceptance, arbitration, go/no-go; read-only. Claude Code: sole tracked writer. Gemini (`gemini-review`, w9:pB): research and audits. Both load JEV (`pi-typesafe`, daily cap 60; `_archive\jev-panes-20260927T0930Z\RECEIPT.md`). Qwen (`qwen-local`, w9:pC) was started at 18:52 on ninfer `Qwen3.8-27B` without JEV (JEV .74) and implemented this batch; pane state changes, so check it before dispatch. Each Herdr task starts with `/new` (send with `MSYS_NO_PATHCONV=1` from Git Bash). The wB panes belong to another project. `chatgpt-web` selectors do not see answers; read them from the tab.

## Handoff

- Next: Astra acceptance of this snapshot, commit on `qwen/ninfer-defaults`, fast-forward and push the working branch; then ORDERS-V2-01 acceptance, then the rollout plan for Astra GO.
- Operator: the plaintext Alpha Vantage note; whether a 6-month figure may ever be a labelled model estimate (currently shown as 未揭露 when undisclosed).
- Tooling: old-reader worktree `%TEMP%\ii-live\wt-16cb1b3` (`cloud\node_modules` is a junction to the source checkout's); Qwen worktree `_workspace\qwen-ninfer-defaults`; `chatgpt-web` lane `investor` (branch `local/zh-tw-lanes`). Scratch: `%TEMP%\ii-live`.
