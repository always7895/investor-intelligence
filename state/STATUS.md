# Current state / 目前狀態

Updated 2026-09-26 (01:20 Asia/Taipei) by an operator-directed Claude Code session (master and writer; the operator granted full authority to finish the Top20 publication work unattended, 2026-09-25). Previous registers: V12 `git show 0f5358b:state/STATUS.md`; older history `git show 38860e7:state/STATUS.md`. Release identity stays in `README.md` (historical 2026-09-06 baseline).

## Identity

- Branch `fix/options-provenance-audit`, draft PR #37 to `main` (pushed after every commit). PR CI only reports COMPLETED_SKIPPED; skipped is not PASS or release qualification.
- DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false.

## Production (2026-09-25 17:14Z)

- Worker `05f07139-1f61-415e-8549-c977b7069f37` (same code as `a815e7f9…`: report-age split, admission disclosure, activation commit kill-switch; scheduled push off, below). Rollback order: `a815e7f9…`, `13d665be…`, `2cfb7d0b…`, `70dd7e15…`.
- **Top20 cutover done.** The hourly task now runs from the installed runtime with `-CarryForwardTop20 -SnapshotRoot data\v213-snapshots`. First carried seal `20260925T171240Z-a7825e47ca40`: CARRIED_FORWARD, staged replay PASS, 15 objects read back, pointer last. `deploy_production_gate.ps1 -Phase post -ExpectTop20Records 20`: PASS (20 records, report 17:08:58Z, test_only_admission=false, macro sealed, 20 potential-ranking records, deployed toml sha256 `5456228d…`). Watchdog FRESH, RECORDS_20. The GEV/6501 test corpus has left Production.
- Top20 content (LKG `20260925T171142Z-11bd454063e7`): PATH, AFRM, BBY, CDE, CF, FIS, HIG, HST, SMCI, TRV, ALL, DG, NEM, NUE, PBR, PBR-A, WDC, ACGL, FSLR, GAP; SEC industry text on all 20; no margin over 100%; BBY/PBR/PBR-A show 「SEC 可用獲利指標不足」 (market_observation rows).
- **Scheduled owner pushes are off by operator decision (2026-09-26: no pushes; keep all data updated in real time for on-demand answers).** Worker `05f07139-1f61-415e-8549-c977b7069f37` = same code with `V21_SCHEDULED_PUSH_ENABLED="false"` (verified in the version bindings; now also "false" in the local toml and both production templates, so later deploys keep it off); `V213_ACTIVATION_COMMIT_ENABLED` stays "false". Pre gate PASS; post gate `-ExpectTop20Records 20` PASS (run `20260925T171240Z-a7825e47ca40`, 20 records).
- The runtime is LOCAL_SOURCE_CHECKOUT, release_qualified=false; this is not a release under the source AGENTS.md shipping list (no immutable ZIP, no R75 CI qualification).

## Top20 single-writer programme (design workflow `wf_0fceff70-f50`)

Root causes: Morning/Evening publication failed at COMMIT_REQUEST since 2026-09-17 (no producer emitted the Worker's two-anchor fields); the source-tree refresh failed at the Nasdaq `(listings, conflicts)` tuple; business-profile phrases picked accounting/legal/TOC text; profit metrics came from filings up to 15 years old or implausible denominators (HIG 979%, AFRM 134%, PBR 2011 20-F).

| Task | State |
| --- | --- |
| T1 Nasdaq unpack, extractor v6, served-model check | DONE `90563ee` `e55f4a0` |
| T2 current, same-period, plausible profit metrics | DONE `84089e6` |
| T3 producer two-anchor contract (`scripts/v213_evidence_policy.py`) | DONE `de595a9` `84089e6` |
| T4 Worker report age vs seal liveness, disclosure, re-seal detail reference, kill-switch | DONE `472a309`, deployed |
| T5 carry-forward publisher, staged replay (reader contract v2), seal-first hourly, bounded refresh, LKG + 3 h backoff | DONE `e4a95c7` |
| T6 gate `-ExpectTop20Records`, report age, state-aware INSUFFICIENT, watchdog report age | DONE `4db8453` |
| T7 LOCAL_SOURCE_CHECKOUT export/install (git-blob check), `-RestorePrevious`, identity-derived labels | DONE `ff2f06a` |
| T8 launcher `-NoSync`, stage-8 `-AllowSealedActivation`; Morning/Evening retired | DONE `0da76d0`; tasks unregistered (XML in `_archive\task-cutover-20260925T170448Z`) |
| T9 reinstall V213Runtime | DONE: tx `d806a6a1935e4213bfc15c5204f2a637`, commit `462fd0f`, LOCAL_SOURCE_CHECKOUT, workflow_run_id null, release_qualified=false; hand-patched `v213_sealed_refresh.ps1` restored from `.bak` (manifest 0/0/0), both archived in `_archive\runtime-restore-20260925T170131Z`; installed self-tests PASS (PS 5.1, 7) |
| T10 cutover | DONE (above); task registration `462fd0f` |
| T11 docs | DONE: [TOP20_CARRY_FORWARD_V1](../docs/TOP20_CARRY_FORWARD_V1.md), runbook §1/2/4 (`f5bfe78`), this file |

Also: `1b43826` sync retries (the 16:56Z hourly aborted on a transient put; a manual retry of the same run passed and was synced). Runtime data was seeded from the source tree's public caches (`data\cache\v21`: BLS PPI within its 35-day cache rule, SEC companyfacts, SIC members, business profiles) because the BLS v1 daily quota refused a live call.

## Latest gate run

- `security_check`, documentation boundary/structure, workflow supply chain: PASS (2026-09-26).
- Full offline Python suite 2643 OK with `PYTHONUTF8=1` (the CI setting; `test_cli_builder_synthetic_fixture` needs it on a cp950 console, also at HEAD before this work). Focused suites after T7/T10 changes OK: installer boundaries/local source/model authority/security, single writer, hourly script (11, PS 5.1 and 7), gate (incl. sync retry). Worker typecheck PASS; 923 passed / 2 skipped.

## Open lanes

1. Carried Top20 cards have no embedded company data report (the seven-field report carries no `deep_reports`; deep analysis shows the audit template). Next: a sealed company-report object bound to the carried tickers plus a Worker reader, replay-tested.
2. Hourly schedule anchor moved from :56 to :12 local (re-registration time); the LKG refresh runs about 11 h after each report. Watch the first automatic refresh (~04:10Z) and the 00:00Z owner push.
3. The default (non-carry) hourly path still tees the rotation output as UTF-16 into the log under PS 5.1 (cosmetic; the carry path logs UTF-8).
4. Carrying reports:*, source-independence and federation needs report-age gates in their readers (certified `cloud/src/qa.ts` needs recertification): deferred. CI R75 route (Sol review of 375 paths, Tabby port of the live QA gate) still blocks release qualification.
5. Forward comparison premises C2b; deferred O1/identity/R3A/U1/U2/E2A-B/Gate B lanes; BLS v1 quota; IFRS metrics for 20-F filers (PBR); WDC/FIS continuing-operations check (plausible, unconfirmed).

## Closed components — no reopening without regression evidence

- T1 finite fractional ordering (`5208d64`), T2 nonauthorizing period declarations (`26842de`), T3 forward comparison declaration diagnostic (`689a682` → `a944410`); O1 options venue coverage shadow (`11436e6`), Case9 (`c178127`), R3A (`e45c1d6`), research method quarantine (`c6ce527`); I1/I2/I3 identity shadows, E2A synthetic capacity, hermetic fixtures. Preserved failures and receipts remain immutable (V12 register).

## Boundary flags

NATIVE_ATTEMPT_COUNT=0; NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY.

## Control plane

Astra master; exact local Qwen sole tracked writer on the Pi lane; Sol independent read-only reviewer. The operator assigned Claude Code as master and writer for this work (2026-09-25) without waiving boundaries.

## External mutations (this change)

Commits and normal pushes to `origin` (PR #37). Worker deployments: `2cfb7d0b…`, `13d665be…`, `a815e7f9…` (operator-requested), `05f07139…` (scheduled push off). Production public KV: hourly sealed syncs (`--remote`), manual syncs of `20260925T155616Z`, `20260925T160733Z`, `20260925T165616Z`, and the first carried seal `20260925T171240Z`. Local: V213Runtime reinstalled (previous root retained as `V213Runtime.old.d806a6a1…`); scheduled tasks: hourly re-registered (carry-forward, runtime root), watchdog re-pointed to the runtime, Morning/Evening unregistered. Read-only SEC/Nasdaq/BLS/Tabby calls. No credential, billing or broker change; no LINE push (scheduled push off by operator decision).

## Next action

Watch the hourly seals and the first automatic LKG refresh (about 04:10Z; log: `%LOCALAPPDATA%\InvestorIntelligence\V213Runtime\data\cache\sealed-refresh.log`), then open lane 1 (sealed company reports for the carried Top20) and shorten data refresh cadence where sources allow.
