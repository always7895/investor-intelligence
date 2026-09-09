# Current engineering status

Updated2026-09-09. This is current acceptance, not a release certificate. Historical milestones and exact old text remain in [Git at38860e7](https://github.com/always7895/investor-intelligence/blob/38860e730997f7d5b9bccdc242d15e9a904e4c15/state/STATUS.md); use `git show 38860e7:state/STATUS.md` offline. Historical receipts/journals are not removed or restamped.

## Authority and workspaces

- Current fetched audit baseline 2a88e8ef4a1e002a9506bfcd6c3c7b780b41abc7; source review implementation committed as c1ed14e. Main-derived PR37 work is in `D:\Investor-Intelligence-LINE-Pi\_workspace\source`; PR39 remains isolated at d58fdaf in `_workspace/review-source-views` under the same project home. Baseline worktree remains52e285f. Do not merge divergent source-view changes implicitly.
- User authorized Production publication/Worker/schedule repair, newly validated data, and project cleanup. No real LINE sends, broker operations, new paid services or arbitrary credential access. Current step changes source/docs and bounded rebuildable artifacts only.
- Installed runtime `D:\Investor-Intelligence-LINE-Pi` is not this Git worktree. Candidate changes are not installed acceptance.

## Physical workspace consolidation — 2026-09-09

- Starting clean HEAD2a88e8ef4a1e002a9506bfcd6c3c7b780b41abc7. User explicitly requested a single project folder. Before moving: all three Git worktrees clean; no observed process/task/service references to the five moved roots; no old-root references in installed PowerShell/Python callers inspected.
- Physically moved source, both isolated review worktrees and audit runtime under `_workspace`; history backups under `_archive/history-backups`. The five former top-level D-drive investor directories no longer exist; no junction/shortcut substitutes created. Used `git worktree move` then `git worktree repair` after main repository relocation. All three HEADs/branches preserved and clean before documentation updates.
- First command stopped before mutation because PowerShell HOME is read-only; corrected local variable name. Git repair messages about old .git paths were expected and followed by successful worktree/status verification.
- Relocated pinned Python3.12.10/OpenSSL/certifi imports PASS; full Python659/2 skipped, Worker160/typecheck PASS from the new paths. Logs now under `_workspace/audit-runtime/consolidation-*.log`. Installed runtime and task paths remain unchanged. Root installed AGENTS now points development work to the nested Git repository; no runtime binary/config replacement.
- Existing signed/history evidence moved intact, not restamped. Running registered runner, models/Router and unrelated projects remain outside consolidation; they were not safe deletion targets. Moving folders reduces top-level clutter, not their byte size. Current release/data blockers remain unchanged.
- Final bounded cleanup across the three source/review scripts/tests trees removed654 untracked .pyc files in10 directories,7,837,559 bytes; source12, baseline214, source-views428. No tracked files, unique evidence or dependencies deleted. Final instruction-budget/security/docs/workflow/storage/diff gates PASS. Both publisher tasks rechecked Disabled; consolidation did not restore or modify their actions.

## Production: maintenance still active

- Rechecked morning/evening publisher tasks: both Disabled. No task restoration, Production Worker/model/EXE replacement or new sealed publication in this step.
- Last confirmed remote data remains2026-09-08T12:20:02Z, evening promotion12:22:09.595Z; not freshly reverified here.
- Prior signed recovery returned NOT_COMMITTED, preserving original FAIL and byte-identical journal archive; previous journal scan unresolved0. Never replay that stale bundle.
- Current sealed schema4 has seven payloads, not fresh options/universe. Candidate containment removes stale carry-forward, but replacement contract/builders/readback/replay/rollback acceptance remains unfinished.

## Current audit increment — malformed evidence dates

- Fetched clean HEAD b66b5a398e3122791453e0fead5f18ce923a8fb4. Reproduced a fail-open in the actual hardened bundle builder: replacing all first-candidate source dates with a valid date prefix plus NOT_A_TIMESTAMP still built a bundle. Negative tests failed before the fix (four malformed formats plus actual caller).
- Removed invalid-date-prefix rescue in `build_v213_activation_bundle_v2.py` and the upstream `v213_build_v21_public_snapshot.py` evidence guard. Valid date-only disclosure precision and valid ISO offset timestamps remain accepted; malformed times/offsets/suffixes no longer count as evidence. No scoring weights, certified qa.ts, historical receipts or Production objects changed.
- New actual-bundle and upstream support tests PASS; full Python659/2 skipped PASS (`timestamp-audit-python.log`), Worker160/typecheck, security/docs/workflow/storage gates, PS5.1/7 parse and diff check PASS. This fixes one identified defect class at two admission points, not a completed project-wide defect inventory. Other date-prefix consumers need role-specific review; do not indiscriminately change reporting-period extraction or broker code.
- Changes remain source-only. Existing protected-source release recertification is still required; reviewed source inventory does not bypass that gate. No deployment, publication or restored schedule claim.

## Current data findings and progress

- Installed raw options file:24 records, September9 retrieval timestamps, no public eligibility/privacy provenance attestation; retrieval time is not quote time. Development Yahoo DTO now remains line_public_eligible=false on both success/no-underlying paths (38860e7).
- Old installed universe:30 rows, generated September7, legacy serenity-first-v2.1.0. June30 as_of may be a reporting period, not proof of stale financial statements. Do not relabel scoring or dates.
- [Dataset-specific rights review](../docs/PUBLIC_SOURCE_RIGHTS_REVIEW_20260909.md): TAIFEX dataset11320 has explicit open-data license with attribution, scoped to Taiwan daily/EOD observations. This does not authorize real-time quotes or US options. Actual provider gate: reviewed public access1, pending7, prohibited4; fully eligible runtime providers0, selected false. No automatic activation.
- Existing public collector now discovers all1094 TWSE +890 TPEx issuer records, source dates September8, zero parser warnings in the live run. No owner list, fixed sector seed or score changes. All1984 remain PRIMARY_ONLY / DISCOVERED_EVIDENCE_AND_SCORING_PENDING / publication_eligible=false. This is Taiwan discovery, not a globally rebuilt ranked Top20.
- Nasdaq terms retrieval timed out; Alpaca indicative documentation is not redistribution permission. Failed/pending rights states remain visible.

## Model and release acceptance

- Q5 thinking=false/effort=none full live matrix previously passed10 cases844–1890ms, with negatives, reference completion, mock LINE and isolated cleanup. Receipt: `r75-qa-live-model-profile-qualification.json`, starts2026-09-09T05:26:24.943379Z;24h/source/profile binding applies. Historical xhigh failure unchanged. Model PASS is not data/release PASS.
- Source-bound Windows/package/extracted-install/download acceptance and protected-source recertification remain incomplete. No new immutable released ZIP. Certified `cloud/src/qa.ts` unchanged.
- Final current regression: Python655/2 skipped PASS (`lean-source-python-final.log`); Worker23 files/160 tests and typecheck PASS; security/docs/workflow/storage/provider gates and diff check PASS; changed release validator parses on PS5.1/7. Earlier failures retained in logs: old catalog counts after actual review, then unpackaged links introduced in the skill. Fixed the counts without activating providers and reused the existing packaged status link without weakening package verification.
- PR39 previously retained three Python evidence errors; not rerun or represented as fixed. Whole-product P0 inventory is not closed; known P0 must be zero before shipping, not assumed zero from a scoped test.

## Lightweight architecture and cleanup

- AGENTS is the engineering entrypoint; skill routes research to canonical method/schema references. Status now holds only current findings; old118k-character history remains in Git rather than every startup read. No schema, scoring or release guard removed.
- [Workspace maintenance](../docs/WORKSPACE_MAINTENANCE.md) defines bounded deletion and junction/dependency checks. Inventory found the apparently old runner folder has a Running/Auto registered service and junctions to2.337.0. It is NOT unused; retained. Raw first process-reference counts included the inspection command itself and are not inactivity evidence.
- Installed tree inventory had57 file-stat errors; no completeness/deletion safety claim. Models, Router, other projects, history/recovery evidence and unmerged worktrees retained. No broad drive/temp/runner cleanup.
- After tests, removed only467 untracked .pyc files in4 flat __pycache__ directories under source scripts/tests:5,755,638 bytes. Checked tracked paths, regular-file types, junction/symlink exclusion, root containment and unchanged file identities before unlinking. No source, lock, evidence, installed data or runner workspace removed.
- Instruction measurements before final result notes: STATUS123,910→6,205 bytes; skill2,886→2,813; AGENTS2,939→4,119 (adds explicit cleanup safety). These are UTF-8 byte measurements, not tokenizer/latency benchmarks. New size-budget tests prevent unbounded entrypoint/history growth. Installed instructions still require separate verified synchronization.

## Next actions

1. Commit/push current source/doc cleanup separately from deployment. Further large-directory removal requires CI job/registration review; the running old-named runner is not disposable.
2. Complete company evidence/constraint/financing analysis and unchanged scoring for the expanded discovery pool; add US/global coverage with explicit admission. Do not call a directory a qualified research universe.
3. Integrate rights/attribution/freshness-aware options and universe into one versioned sealed contract, both builders, preflight and actual Worker callers. Missing qualified quotes must remain unavailable.
4. Recertify changed activation semantics, exact-source Windows and installed actions; publish only a newly validated bundle with remote byte/claim/pointer readback. Restore exactly the paused tasks only after safe installed acceptance, then verify an actual scheduled run.
