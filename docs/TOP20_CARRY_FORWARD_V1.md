# Top20 carry-forward v1 / Top20 單一寫入者

Status: implemented 2026-09-26 (tasks T1–T11 of the single-writer programme). Current Production state and the
cutover record live in [STATUS](../state/STATUS.md); this page is the design and the operating contract.

## Why

From 2026-09-17 no seven-field Top20 reached Production. The Morning/Evening publication failed at COMMIT_REQUEST
(the Worker's two-anchor fields were emitted by no producer), while the hourly sealed publisher re-sealed only the
GEV/6501 test corpus. Two writers, neither complete, and a launcher that could activate a third.

## Topology

- **One writer.** The hourly task `InvestorIntelligenceSealedFreshness` runs
  `scripts/run_production_sealed_refresh.ps1 -CarryForwardTop20 -SnapshotRoot data\v213-snapshots` from the installed
  runtime (`%LOCALAPPDATA%\InvestorIntelligence\V213Runtime`, a LOCAL_SOURCE_CHECKOUT install of a gated commit).
- **Seal first.** Each hour it seals the macro overview plus the newest validated last-known-good (LKG) Top20 bundle
  (`data\cache\top20-lkg\<run_id>.json`), replays the staged run through the real Worker readers
  (`scripts/stage_sealed_replay.py`), and syncs objects first, pointer last (`--remote`, bounded retries).
- **Refresh after.** Only after the pointer write: the daily rotation/company-report refresh, then — when the LKG
  report is 8 h old (`refresh_after_hours`) and no 2 h failure backoff is active — a data-only Top20 refresh
  (`run-v213-local.ps1 -NoSync`) under a hard timeout with a process-tree kill. The candidate becomes the LKG only
  after the bundle checks and a staged replay pass (`scripts/top20_carry_forward.py`).
- **No second writer.** Launcher refresh paths pass `-NoSync`; stage 8 of `run-v213-local.ps1` commits or activates
  only with `-AllowSealedActivation`; the Worker refuses activation commits unless `V213_ACTIVATION_COMMIT_ENABLED`
  is `"true"` (it is `"false"`); the Morning/Evening tasks are retired.

## What is carried

Exactly three objects, byte for byte: `v21:top20:latest`, `v212:top20-report:latest`, `v213:top20-report:latest`.
Report `generated_at`, row `retrieved_at` and the evidence anchors are never re-stamped. `reports:*`,
source-independence, source-federation, source plan and scores keep their sealed placeholders, because their
readers (including certified `cloud/src/qa.ts`) have no report-age gate.

## Freshness contract

| Clock | Bound | Enforced by |
| --- | --- | --- |
| Seal liveness (`last_successful_pipeline_timestamp`) | 7200 s | Worker `V21_TOP20_MAX_AGE_SECONDS` |
| Report and row age | 14 h (`config/v213-top20-report-freshness-v1.json`) | Worker `report-age.ts`, publisher, gate |
| Carry bound | 14 h − one hourly seal | `load_top20_bundle` |
| Evidence anchors | class windows (135 d / 7 d / 550 d) | Worker, `scripts/v213_evidence_policy.py` |

A bundle that fails any check seals an honest INSUFFICIENT Top20 with a reason code; the macro overview is sealed
either way. Every Top20 card carries the admission disclosure (研究候選 LIMITED_RESEARCH_CANDIDATE … 資料擷取).

## Verification

- `scripts/deploy_production_gate.ps1 -Phase post -WorkerVersion <id> -ExpectTop20Records 20` (reader contract v2,
  report age, state-aware INSUFFICIENT handling, deployed config sha256).
- `scripts/freshness_watchdog.ps1` records the pointer age, the Top20 state and the report age.

## Rollback

- Stop carrying: re-register the hourly task without `-CarryForwardTop20`
  (`scripts/register_sealed_freshness_tasks.ps1 -ScriptRoot <root>`); the next seal publishes INSUFFICIENT Top20
  plus macro within about an hour. `rollback_sealed_snapshot.py` targets tracked runs only, not hourly runs.
- Runtime: `scripts/v213_runtime_install_coordinator.ps1 -RuntimeRoot <rt> -RestorePrevious <transaction>` swaps
  the previous install back and re-attests it.
- Owner pushes only: deploy `V21_SCHEDULED_PUSH_ENABLED="false"` from `cloud/wrangler.v213.production.local.toml`
  (authorization required).
