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

BATCH05 local reader amendment (2026-10-07; verification/independent acceptance pending):
both V213 qualified-bottleneck and seven-field readers apply the shared report-age gate to
every row's `retrieved_at` as well as `generated_at`. A fresh report/seal cannot renew an
older row still inside a longer evidence-class window. Diagnostic precedence is preserved:
an invalid/stale report or seal keeps the existing report-stale message; a fresh report with
an older-than-14-h row (or a row more than 300 s in the future) takes the existing row-specific
`V213_STALE_RECORDS_MESSAGE` path. Auxiliary reports and federation
remain placeholders, never carried. Certified `qa.ts` is unchanged; no live recertification
was performed or claimed.

qa.ts recertification plan (remaining Lane5 qualification: carried-report and federation ages; a plan only, nothing in
it is implemented or accepted). Today `build_bodies` in `scripts/publish_sealed_snapshot.py` seals `reports:*`,
`scores:latest`, `source_views:latest`, `source_plan:latest`, `v213:source-federation:latest` and
`v213:source-independence:latest` as placeholders in every sealed run (activation commits stay refused, see Topology),
so the gap below is latent. Certified `cloud/src/qa.ts` checks only seal liveness (`publicFreshness`:
`last_successful_pipeline_timestamp` against
`PUBLIC_DATA_MAX_AGE_SECONDS`, default 1800 s, which every hourly seal renews): always for the `morning_report`,
`evening_report` and `latest_report` intents, and for `ranking`, `source_views` and the general answer (whose context
`projectContext` reads `reports:latest`, `scores:latest` and `source_views:latest`) only on a current-data question.
It has no report-age gate. `cloud/src/v213/compact-qa.ts` (not certified) reads `v213:source-independence:latest`
under the same liveness rule and applies `v213ReportAgeFresh` only to the matched `v21:top20:latest` row. Before
any of these objects may be carried:

1. Contract: every carried object gets a machine-readable generation time from the same bundle as the three carried
   Top20 objects (the plain-text `reports:*` bodies have none today), checked against the shared 14 h bound
   (`v213ReportAgeFresh`, `config/v213-top20-report-freshness-v1.json`), never re-stamped.
2. Readers: qa.ts applies that bound wherever it reads these objects, after `requirePublicFreshness` (a stale seal
   keeps its existing reason first; an over-age or future report gets one fixed new reason), and compact-qa.ts applies
   it to the audit it reads. The privacy, tenant-memory, option and model-routing code of qa.ts stays byte-identical.
3. Tests, written before the change: report-age negatives (older than 14 h, more than 300 s in the future, missing or
   invalid time) and the precedence case in `cloud/test/qa.test.ts` and `cloud/test/v213-compact-qa.test.ts`, plus a
   publisher test that every placeholder stays a placeholder until the readers are deployed.
4. Recertification record, in the same change: the new qa.ts sha256 replaces the current pin
   `0107aca61f8a881192d1747a6cc31e87aeadf3c00cf19e8bbc10d9ba3f681eb2` in `state/r75-qa-live-qualification.json` and
   `state/r75-qa-live-activation-v3-20260909.json`; the protected R75 source check of
   `scripts/ci_v213_r75_free_relay_validate.ps1` (its `$protected` list, compared with `git diff --quiet` against
   `$r75Commit`; `tests/test_current_release_lane.py` keeps qa.ts listed) moves to the recertified commit; a new receipt records the new
   blob next to the R75 one (`94184bc8`, kept as history in `state/FINAL_DELIVERY_REPORT_R75_FREE_RELAY.md`); the
   writer's acceptance and the independent review accept the same snapshot.
5. Rollout: Worker readers first, publisher carry second, each an operator-authorized production step checked by
   `scripts/deploy_production_gate.ps1 -Phase post`. Until then the placeholders stay and nothing here is claimed.

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
