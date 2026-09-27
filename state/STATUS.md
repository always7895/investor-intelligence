# Current state / 目前狀態

Updated 2026-09-27 22:30 Asia/Taipei by Claude Code (sole tracked writer). Previous text: `git show 349a332:state/STATUS.md` (NINFER-DEFAULTS-01); `git show 914f0e6:state/STATUS.md`; earlier `git show e2365cd:state/STATUS.md`, `git show dec7bd0:state/STATUS.md`, `git show 5b15984:state/STATUS.md`, `git show 3ac39a1:state/STATUS.md` (full production record), `git show a8c6e58:state/STATUS.md`, `git show 59049db:state/STATUS.md`, `git show 38860e7:state/STATUS.md`; V12 `git show 0f5358b:state/STATUS.md`. Release identity stays in `README.md`. Root and source `AGENTS.md` override older control-plane text in this file's history.

## Identity

- This batch is an uncommitted candidate on `fix/options-provenance-audit` at `349a332` (NINFER-DEFAULTS-01, pushed). Planned after writer and Astra acceptance: commit and push. CI on this branch ends COMPLETED_SKIPPED by design (`final-release-candidate-v3-pre-rewrite-audit.yml` runs only for head `integration/final-release-candidate-v3`): not PASS. Non-release-qualified (LOCAL_SOURCE_CHECKOUT). DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false.

## This batch: ORDERS-V2-01 revision 6 (Astra contract `_archive\lane-dispatch-20260927T0905Z\astra-orders-v2.result.md`)

Operator 2026-09-27: "未來預估修正為未來訂單預估，根據現有最新消息隨時修正，若實現股價要註明時間（半年、1年）". Revisions 1–5 were REJECTED by Astra (`astra-accept-orders-v2.result.md`, `-r2` … `-r5`); the amendment of revision 2 was accepted: explicit recognition amounts, schedules with their own period, backlog schedules and schedules of the filing's stock are refused at load (deferred, not implemented).
- Registry `config/order-claims-v2.json` + `scripts/order_claims.py`: primary documents (hash, size, retrieval; issuer URL prefixes with canonical paths; SEC kinds paired with forms and exhibits) and dated claims; total validation in both languages (dates 1990–2100, optional fields omitted not null, bounded numbers incl. units, code-point lengths, one text policy refusing format characters, byte-order marks and unpaired surrogates, numbers compared by value, zero unsigned); selection at the exact build instant; only a company USD RPO on ASC 606 is comparable with the filing, and its schedule must share its basis; equal stock observations are one observation whose attached schedules are all compared (ids never decide); same-date differences in figure or schedule are conflicts; `FILING:<accession>` corrections must be on ASC 606 and resolve only against the actual filing after its filing date (else UNRESOLVED_REVISION); zero/unquantified/range observations withhold calculations. Per issuer at most 8 claims, 4 documents and a presentation budget of 2,400 UTF-16 units are sealed (else EVIDENCE_LIMIT); the text detail pages losslessly at line boundaries instead of cutting. One record: MU prepared remarks p.7, reference only.
- `scripts/order_forecast.py` decide/build_v2 seals the allowlisted periodic input, order book, claims and selection; a registry schedule is priced only with the filing's validated quarter. `cloud/src/v213/order-forecast.ts` recomputes the selection and the whole forecast and refuses the record on any difference; the build instant must equal `generated_at`.
- Wording: 半年內／1年內預計認列 with 起算日（非今日起）, 若半年內／1年內實現訂單 → 股價預估 ±X% with the condition; dates of the actual inputs; stock lines explain the rows from their actual relationship (同日同額, 早於申報量測, 認列時程見上); ranges keep their unit; details show metric, scope, measurement date, period and revision reason of every disclosure. Cards and the text form show one later disclosure and a count.
- Evidence: shared fixture `tests/fixtures/v213-order-forecast-v2.json` (S1–S19, each case described in `tests/test_order_claims.py`) and the sealer's fixed-cutoff output `tests/fixtures/v213-order-forecast-v2-sealed.json`, both through `parseBottleneckV3`; twenty cards and both detail forms keep every source and check line at the budget edge (asserted per claim).
- Coverage (2026-09-27): MU one verified reference; CRDO BLOCKED_INPUTS; 5351.TWO evidence verified for lane 18; other Top20 issuers are research leads only (Gemini survey, not writer-verified); no 6-month schedule found by that survey (not a verified absence).

Previous batches: NINFER-DEFAULTS-01 (`349a332`, local model defaults to ninfer); PY-LOCAL-01 (`914f0e6`, local Python resolver).

## Production — read back 2026-09-27 18:30–18:45 (operator: 授權回讀核對; read-only)

Receipt `_archive\lane14-readback-20260927T1036Z\RECEIPT.md` supersedes the earlier OUTCOME_UNKNOWN assessment: rollout v5 was not executed after P0. Observed then: Worker 25377354… (created 2026-09-26T12:07Z, source 16cb1b3) ready; runtime ff6dc42 tx 75cc59dc FINALIZED; SealedFreshness, FreshnessWatchdog, v213-FreeRelay and InvestorDailyBriefing enabled, actions identical to P0; KV pointer at the 18:12 hourly seal (run 20260927T101233Z-7113fe1deb03, 76 objects, no seal mismatch); reader replay 16cb1b3 (v2) and HEAD (v3) PASS 20/20. This is a read-back of state, not an exhaustive event history. `3ac39a1..HEAD` is undeployed; the live bottleneck outlook is still RPO stock plus analyst-consensus scenarios.
- Rollback target: Worker 25377354 / runtime ff6dc42 (order in `git show 3ac39a1:state/STATUS.md`).
- New validators refuse historical SIVE.ST/VOLV-B.ST option cycles, so a new Worker may only go live after data built by the new runtime is sealed.
- Rollout history: Astra NO_GO on plans 1–4, conditional GO on v5 for one window on `dec7bd0` (`%TEMP%\ii-live\astra-rollout5.result.md`, journal `%TEMP%\ii-live\rollout5\journal.md`); neither is authorization for another snapshot.

## Authorization and queue

Operator 2026-09-27 18:51 "繼續並核准相關授權" (`_archive\authorization-20260927T1051Z\AUTHORIZATION.md`, writer-interpreted scope): runtime/EXE installation, the task pause/resume that install needs, Worker deployment, KV publication/seal within a stated write budget, transaction/rollback/finalize and read-back — each only after an Astra GO on a fixed-snapshot rollout plan. Excluded: real LINE delivery, credentials, billing, broker actions, merge/tag/release. It does not approve any review or an unspecified snapshot.

1. ORDERS-V2-01: this batch; complete only after writer and Astra acceptance, commit and push.
2. Rollout of the accepted snapshot: a fixed plan for Astra GO. The deployed 16cb1b3 reader ignores the order forecast (keeps its analyst tiles), the eca78a1 reader shows version 2 as unavailable; the order of data and Worker is decided in that review.
3. L18-5351-CURATED-01 (contract `astra-5351-contract.result.md`, evidence verified): queued after ORDERS-V2; the other four lane-18 listings DEFERRED_WITH_REASON.
4. Lane 19 CRDO: CRDO-RPO-01 closed BLOCKED_INPUTS by Astra (RPO only as an extension XBRL concept; not COMPLETE). MU waits for its FQ4 FY26 10-K (report 2026-09-30).
5. Local Qwen: available on ninfer when idle; dispatch delays LINE answers.
6. DEFERRED_WITH_REASON: lanes 2, 3, 5 (below), driver v3 A–D.

## Commits since 2026-09-26 20:45

`13d7c85` … `5b15984`: lanes 2/3/4/6, KV quota handling, ChatGPT Pro reviews, reader replay v3. `aa54416`/`bb95f97`: lanes 15/16. `33d7938`: lanes 17/18. `eca78a1`: lane 19. `dec7bd0`: `AGENTS.md`. `e2365cd`: STATUS reconcile. `914f0e6`: PY-LOCAL-01. `349a332`: NINFER-DEFAULTS-01. None deployed.

## Operator decisions (2026-09-26)

ChatGPT review MCP is `chatgpt-web` (workspace `AGENTS.md`); `scripts/codex_review_mcp.py` stays in the repo. No pointless questions. Alpha Vantage key is DPAPI ciphertext; the plaintext desktop note is the operator's to delete. No OpenDART/data.go.kr key; Nasdaq data accepted; Google Finance rejected.

## Open lanes

2. Source diversity: official fundamentals beside Yahoo for Taiwan (TWSE/TPEx), Stockholm (SIVE via Cision) and Korea (curated IR config; refresh after earnings). Still single: Japan fundamentals (EDINET needs a key), Japan/Korea price shards, consensus outside the US.
3. Orders: CRWV (24M only) and SNDK (12M only) disclose no other horizon. AXTI and NBIS have no deep report (domestic SEC filers only). Korea HD Hyundai Electric deck unreadable keylessly.
5. Deferred: report-age gates for carried reports and federation readers (certified `cloud/src/qa.ts` needs recertification); the CI R75 route blocks release qualification.
17. LINE Q&A relay (Worker → quick tunnel → gateway :8814 → ninfer :8080): gateway health OK at 18:25. Nightly heartbeat failures from one KV nonce per heartbeat are fixed in 33d7938 (undeployed).
18. Dilution: shares_yoy from the quarter's diluted weighted average when shares outstanding are missing. Previous-quarter YoY for Yahoo listings: see queue item 3.
19. Order forecast: v1 in `eca78a1`, v2 this batch (both undeployed). No Top20 company discloses a 6-month schedule (2026-09-27 survey).

Closed: lanes 1, 4, 6–13, 15, 16. Lane 15 upkeep: a new IPO or spin-off stays excluded (`HISTORY_OR_LINEAGE_UNVERIFIED`) until `config/listing-lineage-v1.json` has its primary-source record; check `excluded` after each v3 build.

Lane 4 compatibility exception (Astra review 2): with a valid fresh v3 document every ranking word opens v3. Without one, words the certified seven-field path already matched (`top 20`, `前20`, `排行`, `排名` as substrings, so also `瓶頸排名`, `瓶頸TOP20`) keep that path, which can show the sealed seven-field report; only `瓶頸榜`, `前二十` and `瓶頸爆發榜` answer the v3 unavailability notice. Retiring the seven-field path needs its own product decision and recertification.

## Closed components — no reopening without regression evidence

Top20 single-writer programme T1–T11 (`90563ee` … `f5bfe78`); T1 (`5208d64`), T2 (`26842de`), T3 (`689a682` → `a944410`); O1 options venue coverage shadow (`11436e6`), Case9 (`c178127`), R3A (`e45c1d6`), research method quarantine (`c6ce527`); I1/I2/I3 identity shadows, E2A synthetic capacity, hermetic fixtures. Preserved failures and receipts stay immutable (V12 register).

## Boundary flags

NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; publication_eligible=false for candidates; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY for company proof, leads the industry ranking since 2026-09-26 (operator).

## Control plane (root `AGENTS.md`, operator 2026-09-27)

Astra (`astra-review`, w9:pA): priorities, contracts, acceptance, arbitration, go/no-go; read-only. Claude Code: sole tracked writer. Gemini (`gemini-review`, w9:pB): research and audits. Both load JEV (`pi-typesafe`, daily cap 60; `_archive\jev-panes-20260927T0930Z\RECEIPT.md`). Qwen (`qwen-local`, w9:pC) was started at 18:52 on ninfer `Qwen3.8-27B` without JEV (JEV .74) and implemented NINFER-DEFAULTS-01; pane state changes, so check it before dispatch. Each Herdr task starts with `/new` (send with `MSYS_NO_PATHCONV=1` from Git Bash). The wB panes belong to another project. `chatgpt-web` selectors do not see answers; read them from the tab.

## Handoff

- Next: Astra acceptance of this snapshot (and of the contract amendment), commit and push; then the rollout plan for an Astra GO; then L18-5351-CURATED-01.
- Operator: the plaintext Alpha Vantage note; whether a 6-month figure may ever be a labelled model estimate (currently shown as 未揭露 when undisclosed).
- Tooling: old-reader worktree `%TEMP%\ii-live\wt-16cb1b3` (`cloud\node_modules` is a junction to the source checkout's); Qwen worktree `_workspace\qwen-ninfer-defaults` (branch merged); `chatgpt-web` lane `investor` (branch `local/zh-tw-lanes`). Scratch: `%TEMP%\ii-live`.
