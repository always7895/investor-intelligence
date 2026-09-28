# Current state / 目前狀態

Updated 2026-09-28 10:45 Asia/Taipei by Claude Code (sole tracked writer). Previous text: `git show 06a7f28:state/STATUS.md` (L18-5351 detail); `git show 4be0888:state/STATUS.md` (ORDERS-V2-01); `git show 349a332:state/STATUS.md`; `git show 914f0e6:state/STATUS.md`; earlier `git show e2365cd:state/STATUS.md`, `git show 5b15984:state/STATUS.md`, `git show 3ac39a1:state/STATUS.md` (full production record), `git show a8c6e58:state/STATUS.md`, `git show 59049db:state/STATUS.md`, `git show 38860e7:state/STATUS.md`; V12 `git show 0f5358b:state/STATUS.md`. Release identity stays in `README.md`. Root and source `AGENTS.md` override older control-plane text in this file's history.

## Identity

- Branch `fix/options-provenance-audit` at `06a7f28` (L18-5351-CURATED-01, pushed; writer + Astra ACCEPT r2). Production runs `4be0888` (rollout v6, below). CI on this branch ends COMPLETED_SKIPPED by design: not PASS. Non-release-qualified (LOCAL_SOURCE_CHECKOUT). DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false.
- Last batches: L18-5351-CURATED-01 (`06a7f28`: official previous-quarter comparator for 5351.TWO; Astra REJECT r1, ACCEPT r2 with the ruling that an empty Yahoo cell is absent); ORDERS-V2-01 (`4be0888`); NINFER-DEFAULTS-01 (`349a332`); PY-LOCAL-01 (`914f0e6`).

## Production — rollout v6 executed 2026-09-28 00:35–02:25Z (receipt `_archive\rollout-2026-09-28\RECEIPT-rollout6.md`)

Operator authorized rollout v6 in the executing session, approved the availability-tolerant budget contract (section A of `command-sheet-v6-r5.md`) and explicitly overrode Astra's NO_GO on the command sheet (r1–r5). Astra's post-execution review ACCEPTs the resulting combination, scoped (`astra-rollout6-acceptance.result.md`).
- Runtime `4be0888` (tx `fca52e17b6784bcba3dd9ae37eeb031d`, FINALIZED); Worker `02ef0276-2aaa-491e-ae98-a238744b8ea2` (100 %); pointer after the first hourly seal `20260928T021234Z-297fd3172895` (CARRIED_FORWARD, seven-field report 2026-09-28T00:21:49Z); four tasks enabled; LINE Q&A relay up.
- Live now: order forecast v2 (半年內／1年內預計認列, 若半年內／1年內實現訂單 → 股價預估), listing lineage, dilution basis, route-bound relay heartbeat (P7: 17 accepted heartbeats, no generic KV nonce observed under a 180 s visibility assumption — the nightly quota exhaustion cause), options validators (SIVE.ST/VOLV-B.ST cycles valid).
- Before publication the 08:12 hourly seal had sealed Top20 INSUFFICIENT (`TOP20_REPORT_TOO_OLD`); the candidate carried the new LKG and restored it.
- Recovery: runtime `-RestorePrevious fca52e17b6784bcba3dd9ae37eeb031d` (old root ff6dc42 retained, preimages in `evidence\preimage`); Worker rollback `25377354-0ff5-4a28-a78b-82ec2457729f` (restores the KV-nonce heartbeat). Re-evaluate compatibility first; the 08:12 baseline run is not a healthy target.
- Limits: section-A accounting not fully executed (post-reset start); readiness bodies executor-attested; evidence `_archive\rollout-2026-09-28\evidence\` with `evidence-inventory.sha256`.

## Authorization and queue

1. Rollout v6 follow-ups (Astra): read back a later hourly seal with actual-reader replay and readiness; runbook: the relay bridge needs the operation mutex (release the holder before starting the relay), record gate/census at each activation, keep a serving-reader-compatible recovery candidate.
2. `06a7f28` (L18-5351) is undeployed; it needs Worker first, then data, and a new current-session authorization.
3. Lane 19 CRDO: CRDO-RPO-01 closed BLOCKED_INPUTS by Astra (not COMPLETE). MU waits for its FQ4 FY26 10-K (report 2026-09-30).
4. Local Qwen: available on ninfer when idle; dispatch delays LINE answers.
5. DEFERRED_WITH_REASON: lanes 2, 3, 5 (below), driver v3 A–D; the other four lane-18 listings.

## Commits since 2026-09-26 20:45

`13d7c85` … `5b15984`: lanes 2/3/4/6, KV quota handling, ChatGPT Pro reviews, reader replay v3. `aa54416`/`bb95f97`: lanes 15/16. `33d7938`: lanes 17/18. `eca78a1`: lane 19 v1. `dec7bd0`: `AGENTS.md`. `e2365cd`: STATUS reconcile. `914f0e6`: PY-LOCAL-01. `349a332`: NINFER-DEFAULTS-01. `4be0888`: ORDERS-V2-01 (deployed 2026-09-28). `06a7f28`: L18-5351 (not deployed).

## Operator decisions (2026-09-26)

ChatGPT review MCP is `chatgpt-web` (workspace `AGENTS.md`); `scripts/codex_review_mcp.py` stays in the repo. No pointless questions. Alpha Vantage key is DPAPI ciphertext; the plaintext desktop note is the operator's to delete. No OpenDART/data.go.kr key; Nasdaq data accepted; Google Finance rejected.

## Open lanes

2. Source diversity: official fundamentals beside Yahoo for Taiwan (TWSE/TPEx), Stockholm (SIVE via Cision) and Korea (curated IR config; refresh after earnings). Still single: Japan fundamentals (EDINET needs a key), Japan/Korea price shards, consensus outside the US.
3. Orders: CRWV (24M only) and SNDK (12M only) disclose no other horizon. AXTI and NBIS have no deep report (domestic SEC filers only). Korea HD Hyundai Electric deck unreadable keylessly.
5. Deferred: report-age gates for carried reports and federation readers (certified `cloud/src/qa.ts` needs recertification); the CI R75 route blocks release qualification.
17. LINE Q&A relay (Worker → quick tunnel → gateway :8814 → ninfer :8080): the route-bound heartbeat without a KV nonce (33d7938) is live since rollout v6.
18. Dilution: shares_yoy from the quarter's diluted weighted average when shares outstanding are missing. Previous-quarter YoY for Yahoo listings: 5351.TWO from the official pair in this batch; the other four listings DEFERRED_WITH_REASON.
19. Order forecast: v2 live since rollout v6 (`4be0888`). No Top20 company discloses a 6-month schedule (2026-09-27 survey).

Closed: lanes 1, 4, 6–13, 15, 16. Lane 15 upkeep: a new IPO or spin-off stays excluded (`HISTORY_OR_LINEAGE_UNVERIFIED`) until `config/listing-lineage-v1.json` has its primary-source record; check `excluded` after each v3 build.

Lane 4 compatibility exception (Astra review 2): with a valid fresh v3 document every ranking word opens v3. Without one, words the certified seven-field path already matched (`top 20`, `前20`, `排行`, `排名` as substrings, so also `瓶頸排名`, `瓶頸TOP20`) keep that path, which can show the sealed seven-field report; only `瓶頸榜`, `前二十` and `瓶頸爆發榜` answer the v3 unavailability notice. Retiring the seven-field path needs its own product decision and recertification.

## Closed components — no reopening without regression evidence

Top20 single-writer programme T1–T11 (`90563ee` … `f5bfe78`); T1 (`5208d64`), T2 (`26842de`), T3 (`689a682` → `a944410`); O1 options venue coverage shadow (`11436e6`), Case9 (`c178127`), R3A (`e45c1d6`), research method quarantine (`c6ce527`); I1/I2/I3 identity shadows, E2A synthetic capacity, hermetic fixtures. Preserved failures and receipts stay immutable (V12 register).

## Boundary flags

NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; publication_eligible=false for candidates; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY for company proof, leads the industry ranking since 2026-09-26 (operator).

## Control plane (root `AGENTS.md`, operator 2026-09-27)

Astra (`astra-review`, w9:pA): priorities, contracts, acceptance, arbitration, go/no-go; read-only. Claude Code: sole tracked writer. Gemini (`gemini-review`, w9:pB): research and audits. Both load JEV (`pi-typesafe`, daily cap 60; `_archive\jev-panes-20260927T0930Z\RECEIPT.md`). Qwen (`qwen-local`, w9:pC) was started at 18:52 on ninfer `Qwen3.8-27B` without JEV (JEV .74) and implemented NINFER-DEFAULTS-01; pane state changes, so check it before dispatch. Each Herdr task starts with `/new` (send with `MSYS_NO_PATHCONV=1` from Git Bash). The wB panes belong to another project. `chatgpt-web` selectors do not see answers; read them from the tab.

## Handoff

- Next: rollout v6 follow-ups (queue 1); then a Worker-first rollout plan for `06a7f28` when the operator authorizes it; MU after its 10-K.
- Operator: the plaintext Alpha Vantage note; whether a 6-month figure may ever be a labelled model estimate (currently shown as 未揭露 when undisclosed).
- Tooling: rollout worktree `_workspace\rollout-4be0888` (detached 4be0888, git-ignored production config copy inside); old-reader worktree `%TEMP%\ii-live\wt-16cb1b3`; rollout tools `%TEMP%\ii-live\rollout6`; Gemini worktree `_workspace\gemini-l18-5351` and Qwen worktree `_workspace\qwen-ninfer-defaults` (integrated); `chatgpt-web` lane `investor`.
