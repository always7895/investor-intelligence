# Current state / 目前狀態

Updated 2026-09-29 20:50 Asia/Taipei by Claude Code (sole tracked writer). Previous text: `git show b9a05c4:state/STATUS.md` (before ORDERS-V3-AUTOUPDATE-01 slice A1); `git show e049261:state/STATUS.md` (before rollout v9); `git show 902d893:state/STATUS.md` (ORDERS-V3-01 before acceptance); `git show b0860c9:state/STATUS.md` (options, runbook); `git show ca571aa:state/STATUS.md` (rollout v6); `git show 06a7f28:state/STATUS.md` (L18-5351 detail); `git show 4be0888:state/STATUS.md` (ORDERS-V2-01); `git show 349a332:state/STATUS.md`; `git show 914f0e6:state/STATUS.md`; earlier `git show e2365cd:state/STATUS.md`, `git show 5b15984:state/STATUS.md`, `git show 3ac39a1:state/STATUS.md` (full production record), `git show a8c6e58:state/STATUS.md`, `git show 59049db:state/STATUS.md`, `git show 38860e7:state/STATUS.md`; V12 `git show 0f5358b:state/STATUS.md`. Release identity stays in `README.md`. Root and source `AGENTS.md` override older control-plane text in this file's history.

## Identity

- Branch `fix/options-provenance-audit` at `e89936f` (A1 on `b9a05c4`), pushed; production runs `e049261` (= `902d893` ORDERS-V3-01 + project-audit repairs) since rollout v9 (below). CI on this branch ends COMPLETED_SKIPPED by design: not PASS. Non-release-qualified (LOCAL_SOURCE_CHECKOUT). DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false.
- Last batches: project-audit repairs (`e049261`, Astra NO_BLOCKING_GAPS round 4, `_archive\project-audit-20260929\`); ORDERS-V3-01 (`902d893`, joint acceptance r11, `_archive\lane-orders-v3\`); RUNBOOK-ROLLOUT-01 (`b0860c9`); OPTIONS-PRESESSION-01 (`c7059d6`); L18-5351-CURATED-01 (`06a7f28`).

## Production — rollout v9 executed 2026-09-29 00:04–02:35Z (receipt `_archive\rollout-2026-09-29\RECEIPT-rollout9.md`)

Worker first, then runtime, under Astra GO_WITH_CONDITIONS (plan r3 `rollout-plan-v9.md`, `astra-rollout9-r2/r3.result.md`; r1 NO_GO). Astra's post-execution review: PRODUCT_H1_CHECKS=PASS, REJECT on execution compliance (`astra-rollout9-acceptance.result.md`): (E1) a failed data-refresh step (executor environment: Windows PowerShell 5.1 started from PowerShell 7 inherited its module path) was retried forward instead of the plan's R-A branch; (E2) when the manual-H1 budget gate failed (1074 > 1000) the writer switched to the automatic-fallback route (840) instead of stopping for the operator, which caused a few minutes of Top20 stale notice (watchdog STALE 02:12:33Z, FRESH 02:42:33Z). The operator accepted the result after the fact (「A」), deviations recorded as non-compliance, no recovery (`DISPOSITION-rollout9.md`). Not a PASS. Rollout v7 history: `git show e049261:state/STATUS.md`.
- Worker `c3828885-9f2a-4155-b158-538acbae19a1` (100 %); runtime `e049261` (tx `8f46bec528604022904814afda7eaf37`, FINALIZED); first seal `20260929T021233Z-c61ace772352` (EXACT; e049261 and ca571aa readers; expected 9/5/2/4; all acceptance tools 0 problems); four tasks enabled; relay up.
- Live now: ORDERS-V3-01 (`order_forecast_v3`: 9 issuers with 約6個月／約1年 figures, e.g. NVDA US$216.0B / US$432.0B; 5 suspended for official IR; Korean consensus deferred; 4 without a record), the options pre-session guard (`c7059d6`), the project-audit repairs, and everything from rollouts v6/v7.
- Recovery (needs then-current compatibility, budget and authorization): Worker rollback `ce9859bb-b6a1-4c89-9113-9927e00e0ae7` (reads v3-carrying data; the v3 tiles disappear); runtime `-RestorePrevious 8f46bec528604022904814afda7eaf37` (ca571aa; preimages `evidence-v9\preimage`).

## Authorization and queue

1. ORDERS-V3-AUTOUPDATE-01 (operator 2026-09-29: 「發佈後依據消息再自動更新，目標是做到完全自主更新，不需要人工」): after each results release the revenue-guidance record and its approval must renew automatically from the official documents (today a curated record plus the writer's approval; a new release suspends the issuer until renewed). Astra contract `_archive\lane-orders-v3-autoupdate\` (build/test, not a production GO). Slice A1 (NVDA, MU; shadow, not wired): Gemini a1 REJECT (R1-R11), discarded; writer r2-r8 REJECT (N1-N8, R3-1..R8-2, each repaired); r9 ACCEPT, committed `e89936f` (`docs/REVENUE_GUIDANCE_AUTOUPDATE.md`). Astra r2 rulings: accession-bound inline XBRL and an in-code schema accepted; Part B may only add a reviewed positive-template classification of earnings-date notices. Order (Astra `astra-priority-partb.result.md`): B0 prerequisites, B1-B4 Part B for NVDA/MU, rollout (operator + Astra GO), then A2a NBIS, A2b CRWV (`astra-contract-a2.result.md`), A3.
1a. ORDERS-V3-01 (`902d893`, in production since rollout v9; operator 2026-09-28: 「未來訂單預估及股價成長那邊還是有問題，請用擴大資來料源等任何方式修復問題」). Live v2 showed a 6-month figure for 0/20 and a price scenario for 0/20. New `order_forecast_v3` beside the unchanged v2 field: tile 2 「訂單認列／營收推估」, tile 3 「營收實現後股價情境」, 約6個月（2財季）/約1年（4財季） from the latest reported quarter, constant P/S on trailing four quarters. Inputs: `config/revenue-guidance-v1.json` (16 records) bound by `config/revenue-guidance-approval-v1.json`; runtime receipts from EDGAR + Nasdaq wire + official IR (`scripts/revenue_guidance_release_check.py`, `scripts/issuer_ir_feeds.py`) before `bottleneck_v3`. First-rollout profile (Astra scope, W1 and acceptance rulings): company guidance with official IR for NVDA CRWV LITE CRDO MU BE AMD MRVL NBIS; AVGO SNDK AAOI ALAB MTSI suspended (official IR unreadable; RPO recognition kept; showing them on SEC+wire alone is an operator policy decision, not taken); Korean consensus disabled (ORDERS-V3-CONSENSUS-01); 5351.TWO SIVE.ST POET AXTI without a reviewed record. Rebuild proof 2026-09-28T18:26:49Z: 0 mismatches with the independent oracle; W2 byte inventory and approval; W3 deployed/rollback readers replayed. Evidence `_archive\lane-orders-v3\` (Astra REJECT r1–r4, final and r7–r10, ACCEPT r11; producer-to-reader probes `tests/fixtures/make_orders_v3_probes.py`). Deferred lanes HARDEN/SCHEMA/CONSENSUS/TRANSPORT/TESTS with owners and re-entry triggers: docs/BOTTLENECK_TOP20_V3.md. Records and the approval need review after each earnings release (MU: FQ4 release expected 2026-09-30; its receipt turns RESULTS_PUBLISHED and MU suspends until renewed).
2. Project audit 2026-09-29 (operator: 「按照建議並核准相關授權，同時對現有專案進行整體查漏補缺，與astra review，重複檢查到沒有問題為止」): rounds in `_archive\project-audit-20260929\`; worktree and scheduled-task roles in `worktree-inventory.md` there.
3. Lane 19 CRDO: CRDO-RPO-01 closed BLOCKED_INPUTS by Astra (not COMPLETE). MU waits for its FQ4 FY26 filings (release expected 2026-09-30).
4. Local Qwen: available on ninfer when idle; dispatch delays LINE answers.
5. DEFERRED_WITH_REASON: lanes 2, 3, 5 (below), driver v3 A–D; the other four lane-18 listings.

## Commits since 2026-09-26 20:45

`13d7c85` … `5b15984`: lanes 2/3/4/6, KV quota handling, ChatGPT Pro reviews, reader replay v3. `aa54416`/`bb95f97`: lanes 15/16. `33d7938`: lanes 17/18. `eca78a1`: lane 19 v1. `dec7bd0`: `AGENTS.md`. `e2365cd`: STATUS reconcile. `914f0e6`: PY-LOCAL-01. `349a332`: NINFER-DEFAULTS-01. `4be0888`: ORDERS-V2-01 (deployed in rollout v6). `06a7f28`: L18-5351 and `ca571aa`: STATUS (deployed in rollout v7). `9c63590`: STATUS (rollout v7 disposition). `c7059d6`: OPTIONS-PRESESSION-01, `b0860c9`: RUNBOOK-ROLLOUT-01 and `902d893`: ORDERS-V3-01 (not deployed).

## Operator decisions (2026-09-26)

ChatGPT review MCP is `chatgpt-web` (workspace `AGENTS.md`); `scripts/codex_review_mcp.py` stays in the repo. No pointless questions. Alpha Vantage key is DPAPI ciphertext; the plaintext desktop note is the operator's to delete. No OpenDART/data.go.kr key; Nasdaq data accepted; Google Finance rejected.

## Open lanes

2. Source diversity: official fundamentals beside Yahoo for Taiwan (TWSE/TPEx), Stockholm (SIVE via Cision) and Korea (curated IR config; refresh after earnings). Still single: Japan fundamentals (EDINET needs a key), Japan/Korea price shards, consensus outside the US.
3. Orders: RPO schedules stay as disclosed (CRWV 24M, SNDK 12M); the revenue path (ORDERS-V3-01) covers the missing horizons. Remaining without a forecast: 5351.TWO, SIVE.ST, POET, AXTI (no reviewed guidance; AXTI guides only on calls). Korea HD Hyundai Electric deck unreadable keylessly.
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

- Next: ORDERS-V3-AUTOUPDATE-01 B0 in review, B1-B4 (NVDA/MU), rollout plan for GO; MU suspends on its FQ4 release until then.
- Operator: the plaintext Alpha Vantage note; whether a 6-month figure may ever be a labelled model estimate (currently shown as 未揭露 when undisclosed).
- Tooling: worktrees, their roles and the four scheduled tasks: `_archive\project-audit-20260929\worktree-inventory.md`; rollout tools `%TEMP%\ii-live\rollout6` and `rollout7`, rollout v9 folder `%TEMP%\ii-live\rollout9`; `chatgpt-web` lane `investor`.
