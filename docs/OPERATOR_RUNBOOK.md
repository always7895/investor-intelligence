# OPERATOR RUNBOOK — v213 Owner-Line (2026-09-16)

Applies to: Cloudflare Worker `investor-intelligence-v21-owner-line` + KV
(PUBLIC_CACHE `96142af4…`) + Windows refresh task + local seal tooling.
Principle: **every procedure below is fail-closed** — a failure before any pointer write leaves the live
pointer where it was; once a pointer write has been attempted (sync, rollback), a failed or missing final
verification means the live state is unknown until fresh live bytes are classified (section 7.6). Operators
never patch live state by hand.

Reference: worker base URL `https://investor-intelligence-v21-owner-line.moon951753.workers.dev`
(authenticated browser; plain curl may hit CF 1010 — use a real browser).

## 1. Health check & verification
1. GET `/health` → expect HTTP 200, `ok: true`, `product_version: "2.1.3"`, `top20_presentation: "seven_fields"`.
2. GET `/v213/readiness` → expect HTTP 409 `V213_READINESS_REQUEST_INVALID` and `worker_version` echoing the currently deployed version id. The 409 is the *healthy* challenge-gated response, not an error.
3. Identify the live snapshot run: `npx wrangler kv key get snapshot:current --namespace-id 96142af40b5d4213862d5483fe3a66da --remote` (Wrangler 4 reads the local store without `--remote`) → note `run_id` + `seal_sha256`.
4. Confirm the run passed the seal pipeline in the runtime's `data\cache\sealed-refresh.log` (lines printed by `sync_sealed_snapshot_kv.py`; read the log, never re-run the sync): `OBJECTS_UPLOADED <u> [BLOBS_REUSED <r>] → READBACK_VERIFIED <n> → POINTER_LAST <run_id>`, where `<n>` is the number of entries of that run's `objects.json` and `<u> + <r> = <n>` (for example `OBJECTS_UPLOADED 17 BLOBS_REUSED 60`, `READBACK_VERIFIED 77`). The counts come from the run, never from a fixed number.
5. Verify freshness window: pointer `public_data_as_of` must be ≤ 7200 s old, otherwise Top20 (honestly) answers the stale notice — in that case run procedure 2/refresh instead of chasing the worker. The carried Top20 report itself must be ≤ 14 h old ([TOP20_CARRY_FORWARD_V1](TOP20_CARRY_FORWARD_V1.md)); `scripts/deploy_production_gate.ps1 -Phase post -WorkerVersion <id> -ExpectTop20Records 20` checks both.

## 2. Snapshot rollback (sealed run)
Tool: `scripts/rollback_sealed_snapshot.py` — the ONLY mutation it can perform is the `snapshot:current` pointer.
1. Default (fail-safe) verify-only run:
   `python scripts/rollback_sealed_snapshot.py --target-run <PRIOR_RUN_ID>`
   → expect `"status": "DRY_RUN"` and `"verified_objects"` equal to the number of entries of the target run's `objects.json`, after live readback of all of their bytes.
2. Confirm DRY_RUN output, then apply:
   `python scripts/rollback_sealed_snapshot.py --target-run <PRIOR_RUN_ID> --apply`
   → expect `"status": "ROLLED_BACK"`, `"applied": true`; the previous run id is echoed in `from_run`.
3. Re-run step 1 of Section 1 against the *rolled-back* run.
Guards (all abort with `ROLLBACK ABORT`): target dir not git-tracked and any object byte mismatch abort before the pointer write (pointer untouched); a pointer put failure or pointer readback mismatch happens after the write was attempted — the script reports it, and the live pointer must be classified from fresh bytes before any retry (section 7.6).
Hourly carry-forward runs live under the runtime's `data\v213-snapshots` and are not git-tracked, so this tool cannot target them. To stop carrying the Top20, re-register the hourly task without `-CarryForwardTop20` (Section 4); the next seal publishes INSUFFICIENT Top20 plus macro within about an hour.

## 3. Worker rollback (version)
1. List recent versions: `npx wrangler versions list -c wrangler.v213.production.local.toml` (from `cloud/`).
2. Roll back: `npx wrangler rollback [VERSION_ID] -c wrangler.v213.production.local.toml` (omit id = previous version).
3. Wait ~15 s, then Section 1 steps 1–2; confirm `/v213/readiness` `worker_version` = the target version.
Note: worker rollback does NOT touch KV; the sealed-snapshot pointer is independent (Sections 1–2 cover data-layer state).

## 4. Scheduled task recreation (60-min refresh)
1. Verify: `schtasks /Query /TN "InvestorIntelligenceSealedFreshness" /FO LIST` → `Status: Ready`.
2. If missing/corrupt, recreate from the installed runtime (validate first with `-ValidateOnly`):
   `powershell -NoProfile -File %LOCALAPPDATA%\InvestorIntelligence\V213Runtime\scripts\register_sealed_freshness_tasks.ps1 -ScriptRoot %LOCALAPPDATA%\InvestorIntelligence\V213Runtime -CarryForwardTop20 -SnapshotRoot data\v213-snapshots`
3. Trigger once manually: `schtasks /Run /TN "InvestorIntelligenceSealedFreshness"` then check the runtime's `data\cache\sealed-refresh.log` for `REFRESH OK run=<run_id> pointer last` (and `CARRY_FORWARD_TOP20 seal first`).
4. Runtime rollback: `scripts\v213_runtime_install_coordinator.ps1 -RuntimeRoot <rt> -RestorePrevious <transaction>` (transaction id from `%LOCALAPPDATA%\InvestorIntelligence\v213-runtime-install.journal.json`).
Wiring: the pipeline re-evaluates the multi-lineage evidence at wall time and re-points only after sealing, replay and object uploads succeed; a failure before the sync's pointer write leaves the previous pointer, while a failure of the pointer write or its readback (the sync writes the pointer, then reads it back) needs live classification (section 7.6) even though the log says "pointer untouched".

## 5. Emergency incident response & fail-closed validation
Decision tree (all steps read-only until a verified action is named):
- **Stale Top20** (expects 7200 s cap): Section 4 step 3 → re-verify `/health` + readiness.
- **Corrupted/rejected seal** (loader answers `INSUFFICIENT_EVIDENCE`): do NOT "fix" bytes — roll back the pointer to the newest verified run (Section 2), then verify 1–2.
- **Bad worker version deployed**: Section 3.
- **Schedule stopped**: Section 4.
- **`SYNC FAILED` with `KV_DAILY_WRITE_LIMIT_REACHED`** (Cloudflare code 10048): the free plan's 1,000 KV writes a day are spent; nothing can publish until 00:00 UTC (08:00 Taipei); when the limit hit an object upload the pointer was not written and stays on the last seal (if the pointer write itself failed, classify the live bytes first, section 7.6), and Top20 answers the stale notice after 7200 s. Wait for the reset; do not re-run seals. Budget: an hourly seal writes about 20 keys; a seal after a Chinese-name or identity rebuild about 70. Until the Worker from batch 28 is deployed, the FREE_RELAY heartbeat (every ~62 s) also writes one KV replay nonce per refresh, about 1,400 a day: on its own past the limit, it exhausted the quota at 21:06 Taipei on 2026-09-26 and kept LINE Q&A off the local model until the reset. From batch 28 the route refresh is signed for that endpoint only (purpose `ii-v213-free-relay-route-v1`, never valid at another admin endpoint) and claims its nonce in the relay Durable Object: no KV write. Order: deploy the Worker first, then reinstall the runtime (the KV saving starts with the reinstall). Either order still keeps the heartbeat working: the new Worker accepts an older runtime's generic signature with its KV nonce, and the new runtime retries once with a generic signature (fresh nonce) when a Worker answers V21_SYNC_SIGNATURE_INVALID (an older Worker, or after a Worker-only rollback), at one KV write per heartbeat as before. The relay needs the PC clock in sync, because the lease dates and the signature both come from it: more than about 165 s behind, every lease expires on arrival; more than about 120 s ahead, the lease exceeds the 300 s maximum; more than 300 s either way, the signature is refused. Each fails closed (Q&A off) until the clock is corrected (`w32tm /resync`); the next heartbeat then succeeds, except after a clock that ran ahead (accepted only up to about 120 s, because a refused lease is never claimed) is stepped back by S seconds: refreshes are refused until S seconds pass, then one heartbeat interval (~62 s). If the relay Durable Object's storage were ever lost or reset, a captured refresh still inside its 300 s window could be admitted once more (it can only re-publish the signed route): after such a reset, wait 5 minutes or rotate the relay HMAC secret before trusting the route. Keep rollout days to a few manual seals (2026-09-26: five reinstalls and a names-cache fill spent the quota by 21:12).
- Full post-action validation (read-only; never run `sync_sealed_snapshot_kv.py` or `rollback_sealed_snapshot.py --apply` to validate — the sync uploads objects and writes `snapshot:current`, spending the daily budget and possibly overwriting a pointer the hourly writer advanced): Section 1 steps 1–5, then
  1. `python scripts/fetch_live_public_snapshot.py --out <empty dir>` (every read passes `--remote`; nothing is written to any namespace) → `"status": "OK"`, `"seal_mismatches": []` and the live `run_id`;
  2. the matching local run is `%LOCALAPPDATA%\InvestorIntelligence\V213Runtime\data\v213-snapshots\<run_id>` (hourly runs) or `state\v213-snapshots\<run_id>` (git-tracked sealed runs); the live copy is EXACT when its pointer bytes and every object equal that run's `pointer.raw.json` and `objects.json`, otherwise classify it (section 7.6);
  3. `python scripts/stage_sealed_replay.py --run-dir <that run>` (local vitest replay through the Worker readers; no KV write) → exit 0.
  A recovery write (Section 2 `--apply`, a re-sync) is a separate authorized action under section 7, not a validation step.
Escalation: if two rollback attempts fail, HALT; do not assume which run is serving — capture `data/cache/live-pointer-at-<ref>.txt` snapshot + readiness echo and classify the live bytes (section 7.6) before any further action; UNKNOWN stops automation and goes to the operator.

## 6. Secret rotation (Cloudflare)
1. Rotate the wrangler session credential: sign out/in on the local machine (cached `~/.wrangler` session) — never commit tokens; `wrangler.v213.production.local.toml` remains git-ignored.
2. Verify with a read: `npx wrangler kv key get snapshot:current --namespace-id 96142af40b5d4213862d5483fe3a66da --remote` must return the live pointer (without `--remote` Wrangler 4 reads the local store).
3. Re-run Section 1 steps 1–2; then `python scripts/security_check.py` locally must stay PASSED.
4. Never echo token values into logs, git, or handoffs; if a secret ever leaked, treat as incident: rotate again, then Section 5 audit + supervisor notification (outside this runbook's authority to classify).

## 7. Rollouts (runtime or Worker update) — lessons of 2026-09-28
Authority first: a production rollout needs the operator's authorization in the executing session and an Astra go/no-go on a fixed plan; receipts in `_archive\rollout-2026-09-28\`.
1. Order by compatibility: a reader that ignores new fields goes second (data first); a reader that would mislabel new fields goes first (Worker first). Prove both readers on the exact bytes (`scripts/stage_sealed_replay.py` from each checkout) before publishing.
2. Exclusion: disable SealedFreshness, FreshnessWatchdog and v213-FreeRelay; wait until no refresh runs (post-seal work can last ~35 min after :12); stop only the relay's own processes (gateway under the runtime, heartbeat script, tunnel on the gateway port; never `D:\ninfer` or other projects); take the operation mutex with `hold-operation-lock.ps1`. The runtime install cannot rename the root while relay processes run.
3. Resume order: **release the operation mutex before starting FreeRelay** — the bridge takes the same mutex at start (`V213_OPERATION_LOCK_BUSY`, watchdog exit 1 otherwise). Then enable the tasks and check one gateway/tunnel/heartbeat and heartbeat PASS.
4. KV budget (free plan 1,000 writes/UTC day; governing contract: section A of `_archive\rollout-2026-09-28\command-sheet-v6-r5.md` and the rollout's GO conditions): before every controlled writer activation (manual sync, relay start, recovery write) compute the retry-inclusive estimate since 00:00 UTC — per sync 3·(uploaded+1) only when its log shows the completed upload count and pointer, otherwise 3·(objects of its run + 1) (the sync prints `OBJECTS_UPLOADED` only after the whole upload loop), an unstarted operation at its full reservation — plus observed Worker traffic, the retained allowances for intervals without capture (disclosed, never zero), and every open retry-inclusive reservation (recovery, resumed relay, the first hourly seal); require estimate + reservations + 50 ≤ 1,000, else **stop and ask the operator** — never replace an allowance by a weaker measurement. Rollouts that write belong right after the 08:00 Asia/Taipei reset.
5. Candidate gates: a failed product assertion stops the rollout before any write and goes to the operator; an explained provider condition (for example option chains without two-sided quotes) is still an operator decision, not a silent waiver.
6. After any sync, classify the live bytes (`EXACT_<run>` / previous / UNKNOWN) before any claim; the sync writes the pointer before its final readback, so a nonzero exit does not prove the pointer stayed. UNKNOWN stops automation.
7. Worker commands always name the production Worker: `--name investor-intelligence-v21-owner-line -c wrangler.v213.production.local.toml` (the default `wrangler.toml` name does not exist on the account).
8. Lessons of rollout v9 (2026-09-29): a failed step or gate follows the plan's written branch; a retry, a different route or any re-interpretation of a branch needs a reviewed plan amendment or the operator before it happens, even when the cause is understood and harmless. When the executor shell is PowerShell 7, start Windows PowerShell 5.1 children (runtime scripts) with the Windows PowerShell module path (`$env:PSModulePath = "$HOME\Documents\WindowsPowerShell\Modules;" + [Environment]::GetEnvironmentVariable('PSModulePath','Machine')`), otherwise `ConvertTo-SecureString` is missing and the SEC steps are skipped. PowerShell drops a bare `--` in function arguments; quote it (`'--'`).

## Standing invariants (verify after ANY of the above)
- `git diff HEAD --stat cloud/src/worker.ts cloud/src/qa.ts` = 0 (certified blobs).
- `snapshot:current` remains run-bound & sealed (pointer text parseable, seal match).
- No broker/IBKR surface touched by any of the above; LINE owner pairing unchanged.