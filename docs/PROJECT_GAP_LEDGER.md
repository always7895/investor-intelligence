# PROJECT GAP LEDGER — Investor Intelligence v213 (2026-09-16, Task #28)

Project-wide gap audit across the 13 required areas. Format per item:
ID / AREA / ISSUE / SEVERITY / CURRENT_STATE / EVIDENCE / ACTION / TEST / RESULT.
Statuses as of: worker `928539bd-e351-4832-9ad7-cebaeae7be37`, live pointer run-bound
(re-pointed by 60-min refresh; latest committed integrity-proof run `897a86efa733`),
working tree clean, all gates green. Companion ledger for LINE-surface items:
`docs/LINE_GAP_LEDGER.md` (31 items, kept authoritative for that layer).

PG-01 / Source-of-Truth / STATUS.md had drifted: stale routing text (session-tool blocker, `qwen_routed`, Astra role, retired llama.cpp routing) mixed with live state. / P1 / DONE (2026-09-16, Task #28).
EVIDENCE: prior `state/STATUS.md` contained those references; `git show 38860e7:state/STATUS.md` historical anchor retained; current header lists the `range` ledger and the `CURRENT TRUE PRODUCTION ARCHITECTURE` block. / ACTION: stale blocks removed; architecture block records Primary Supervisor = Gemini, Local Writer = Qwen (Herdr `qwen-worker`), Production live = Cloudflare Worker + KV, Active Snapshot = run-bound sealed pointer. / TEST: `test_agent_skill_structure.py` + `test_documentation_structure_gate.py` (size + anchors `publication_eligible=false` historical / `publication_eligible=true` live / `git show 38860e7…`). / RESULT: GREEN (11982 B ≤ 12000; anchors = 1/2/1).

PG-02 / Source-of-Truth / Committed sealed runs vs untracked scheduler runs were intermixed, risking git-tracking drift. / P2 / DONE.
EVIDENCE: `.gitignore` rule `state/v213-snapshots/*/` (Task #27) verified bidirectional by `git check-ignore` (tracked run file = NOT ignored; synthetic new dir = ignored). / ACTION: 3 committed runs stay tracked integrity proofs; hourly dirs stay audit-on-KV + `data/cache`. / RESULT: GREEN.

PG-03 / Sealed publication pipeline / Pointer-last + byte-exact artifacts were previously violated by CRLF/trailing-newline writers and a strict equality seal gate that broke on transport whitespace. / P0 / DONE (025A + #26 deploy).
EVIDENCE: pointer raw = 339 B exact `JSON.stringify` shape, zero transport bytes; sync log `objects 14 → readback 14/14 → pointer LAST`; live probe on fresh run (no stale notice; GEV #1 / 6501 #2). / ACTION: `write_bytes` writers + `raw.trim()` seal gate + paired tests. / TEST: seal suite, sync readback, `v213-live-production-probe.test.ts`, 816/0/1. / RESULT: GREEN.

PG-04 / Production worker & config / Production lags source on redeploy; legacy config sprawl; local toml must not leak. / P1 / DONE (deployment) / BY-DESIGN (config split).
EVIDENCE: version `928539bd…` live (readiness echo); `wrangler.v213.production.local.toml` gitignored; template committed; v2.x LEGACY_GIT_BLOBS pin guards (worker.ts `4e0f78af…`; qa.ts diff 0). / ACTION: redeploy under session authorization; template/local split frozen. / TEST: readiness version echo + `git diff HEAD --stat` = 0 + canonical RC gate. / RESULT: GREEN.

PG-05 / KV namespaces & pointer contract / Cross-namespace bleed possible if namespaces are mirrored or shared. / P1 / BY-DESIGN (isolated).
EVIDENCE: toml binds 3 distinct namespaces; tests pin isolation (`test_kv_namespace_isolation*` within 816); pointer keys = `snapshot:<run>:` scoped + `snapshot:current` only. / ACTION: keep isolation; no cross-binding code paths. / TEST: KV isolation tests. / RESULT: GREEN.

PG-06 / Refresh scheduler / Freshness (7200 s cap) requires cadence << window; failures must not corrupt the live pointer. / P1 / DONE (mitigated).
EVIDENCE: task `InvestorIntelligenceSealedFreshness` (SC MINUTE MO 60) Ready; ≥4 observed cycles; `run_production_sealed_refresh.ps1` fail-closed (abort → pointer untouched); HTTP auto-refresh N/A (CLI+KV lane). / ACTION: 60-min cadence; double-failure still inside one window if last run < 50 min old. / TEST: refresh log `REFRESH OK … pointer last`; sync abort paths. / RESULT: GREEN.

PG-07 / Disaster recovery & rollback / No verified path to restore `snapshot:current` to a prior run (manual byte surgery = corruption vector). / P0 / DONE (Task #28).
EVIDENCE: `scripts/rollback_sealed_snapshot.py` — git-tracked-only target rule, 14-object live sha re-verification, NO-OP/DRY_RUN/ROLLED_BACK states, pointer-only mutation, readback after put. / ACTION: adopted as runbook procedure 2; default mode is verify-only dry-run, `--apply` trails. / TEST: `tests/test_rollback_sealed_snapshot.py` 10/10 (git-tracked rule, mismatch abort, NO-OP, apply-once, untracked refusal, CLI). / RESULT: GREEN.

PG-08 / Operator runbook / No single-step operator manual for health, data rollback, worker rollback, schedule, incident, secrets. / P1 / DONE (Task #28).
EVIDENCE: `docs/OPERATOR_RUNBOOK.md` (6 numbered procedures + standing invariants; fail-closed decision tree for incidents; no live-state hand edits). / ACTION: operator accepts as seed runbook; deviations require supervisor sign-off. / TEST: documented procedure cross-check against implemented tooling (rollback tool exists; schtasks commands verified by Task #23/#27 recreation). / RESULT: GREEN (documentation complete).

PG-09 / Security & secrets / Credential exposure via logs, git, or config drift. / P0 / DONE.
EVIDENCE: `security_check.py` PASSED this cycle; zero token echo across deploy/sync logs (checked textually); toml/vars gitignored; local Launchpad `SecureCredentialStore.cs` extraction (TASK-14); 410s preserve legacy admin surfaces. / ACTION: rotation procedure in runbook §6; never commit tokens. / TEST: security gate + manual log review each deploy. / RESULT: GREEN.

PG-10 / Privacy (IBKR/credentials separation) / Identity/broker fields must never leak into public or logs. / P0 / DONE.
EVIDENCE: public view exposes zero identity fields (7-field Top20; `owner_watchlist_inherited: false`); `test_v213_secure_credentials.py` + privacy scan gates green; no IBKR keys in tree (security PASS). / ACTION: keep private namespace separation; no identity header addition. / RESULT: GREEN.

PG-11 / Ranking & admission evidence / Admitted pool is GEV+6501 (test-only claim layer); uncorroborated candidates risk manufactured ranking. / P1 / OPEN.
EVIDENCE: readiness audit JSON: GEV/6501 ADMISSION_QUALIFIED (test-only 100); 6508/ENR UNRANKED_INSUFFICIENT_EVIDENCE (strict — never zero-padded; admitted/ranked = 2/2 = everything ranked, total 2). / ACTION: ingest new 2nd/3rd family sources before the 180-day window (DOE 2026-03-05 is close). / TEST: `test_candidate_admission_readiness.py` + engine gates. / RESULT: OPEN (evidence-blocked).

PG-12 / Tests & gates / Single-source drift risk across python/TS/src tooling. / P2 / DONE.
EVIDENCE: full regression this cycle — pytest 1511→1524/0/3 after Task #28 additions (rollback suite 10); `npm test` 816/0/1 + 10 new contract tests (TS unchanged); `tsc` 0; 3 gate scripts PASSED. / ACTION: retain gate + suite as release criteria (no weakening). / TEST: `tests/` + `cloud/test` full. / RESULT: GREEN.

PG-13 / Options & market data / Broker-connected price feed not present in the lane; option guidance stays derivation-only; manual calculator = ephemeral user-supplied only. / P2 / PARTIAL / BY-DESIGN.
EVIDENCE: `/health` `automatic_trading: false`, `brokerage_connection: false`, `manual_option_calculator: ephemeral_user_supplied_only`; option guidance engine + provider-retired 410 pin; 20-test option guidance suite. / ACTION: broker feed = external authorization lane; no fee fall-back (enforced). / RESULT: PARTIAL-ACCEPTED (logic green; feed lane held).

---
Summary: P0s (PG-03, PG-07, PG-09, PG-10) all closed with evidence; P1 PG-11 remains OPEN on evidence (never manufactured); PG-13 is a lane held by design. Project is DEPLOYMENT_READY in this lane; `publication_eligible=true` (live, top20 only) / `publication_eligible=false` retained as the historical baseline anchor; `LINE_LIVE=true` (owner pairing).