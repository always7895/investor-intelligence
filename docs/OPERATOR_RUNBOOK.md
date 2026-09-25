# OPERATOR RUNBOOK — v213 Owner-Line (2026-09-16)

Applies to: Cloudflare Worker `investor-intelligence-v21-owner-line` + KV
(PUBLIC_CACHE `96142af4…`) + Windows refresh task + local seal tooling.
Principle: **every procedure below is fail-closed** — on ANY failed verification the
system keeps its last-known-good state; operators never patch live state by hand.

Reference: worker base URL `https://investor-intelligence-v21-owner-line.moon951753.workers.dev`
(authenticated browser; plain curl may hit CF 1010 — use a real browser).

## 1. Health check & verification
1. GET `/health` → expect HTTP 200, `ok: true`, `product_version: "2.1.3"`, `top20_presentation: "seven_fields"`.
2. GET `/v213/readiness` → expect HTTP 409 `V213_READINESS_REQUEST_INVALID` and `worker_version` echoing the currently deployed version id. The 409 is the *healthy* challenge-gated response, not an error.
3. Identify the live snapshot run: `npx wrangler kv key get snapshot:current --namespace-id 96142af40b5d4213862d5483fe3a66da --remote` (Wrangler 4 reads the local store without `--remote`) → note `run_id` + `seal_sha256`.
4. Confirm the run passed the seal pipeline (logs of `sync_sealed_snapshot_kv.py`): `OBJECTS_UPLOADED 14 → READBACK_VERIFIED 14 → POINTER_LAST <run_id>`.
5. Verify freshness window: pointer `public_data_as_of` must be ≤ 7200 s old, otherwise Top20 (honestly) answers the stale notice — in that case run procedure 2/refresh instead of chasing the worker. The carried Top20 report itself must be ≤ 14 h old ([TOP20_CARRY_FORWARD_V1](TOP20_CARRY_FORWARD_V1.md)); `scripts/deploy_production_gate.ps1 -Phase post -WorkerVersion <id> -ExpectTop20Records 20` checks both.

## 2. Snapshot rollback (sealed run)
Tool: `scripts/rollback_sealed_snapshot.py` — the ONLY mutation it can perform is the `snapshot:current` pointer.
1. Default (fail-safe) verify-only run:
   `python scripts/rollback_sealed_snapshot.py --target-run <PRIOR_RUN_ID>`
   → expect `"status": "DRY_RUN"` and `"verified_objects": 14` after live readback of all 14 object bytes.
2. Confirm DRY_RUN output, then apply:
   `python scripts/rollback_sealed_snapshot.py --target-run <PRIOR_RUN_ID> --apply`
   → expect `"status": "ROLLED_BACK"`, `"applied": true`; the previous run id is echoed in `from_run`.
3. Re-run step 1 of Section 1 against the *rolled-back* run.
Guards (all abort with `ROLLBACK ABORT`, pointer untouched): target dir not git-tracked; any object byte mismatch; pointer put failure; pointer readback mismatch.
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
Wiring: the pipeline re-evaluates the multi-lineage evidence at wall time and re-points ONLY on full success; on any stage failure the previous pointer is untouched.

## 5. Emergency incident response & fail-closed validation
Decision tree (all steps read-only until a verified action is named):
- **Stale Top20** (expects 7200 s cap): Section 4 step 3 → re-verify `/health` + readiness.
- **Corrupted/rejected seal** (loader answers `INSUFFICIENT_EVIDENCE`): do NOT "fix" bytes — roll back the pointer to the newest verified run (Section 2), then verify 1–2.
- **Bad worker version deployed**: Section 3.
- **Schedule stopped**: Section 4.
- Full post-action validation: this file's Sections 1–2 checks + `python scripts/sync_sealed_snapshot_kv.py --run-dir state/v213-snapshots/<current>/` reading `READBACK_VERIFIED 14`.
Escalation: if two rollback attempts fail, HALT; the system is by design still serving the last good sealed run — capture `data/cache/live-pointer-at-<ref>.txt` snapshot + readiness echo before any further action.

## 6. Secret rotation (Cloudflare)
1. Rotate the wrangler session credential: sign out/in on the local machine (cached `~/.wrangler` session) — never commit tokens; `wrangler.v213.production.local.toml` remains git-ignored.
2. Verify with a read: `npx wrangler kv key get snapshot:current --namespace-id 96142af40b5d4213862d5483fe3a66da` must return the live pointer.
3. Re-run Section 1 steps 1–2; then `python scripts/security_check.py` locally must stay PASSED.
4. Never echo token values into logs, git, or handoffs; if a secret ever leaked, treat as incident: rotate again, then Section 5 audit + supervisor notification (outside this runbook's authority to classify).

## Standing invariants (verify after ANY of the above)
- `git diff HEAD --stat cloud/src/worker.ts cloud/src/qa.ts` = 0 (certified blobs).
- `snapshot:current` remains run-bound & sealed (pointer text parseable, seal match).
- No broker/IBKR surface touched by any of the above; LINE owner pairing unchanged.