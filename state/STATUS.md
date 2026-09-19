# Current state / 目前狀態

## TASK0-3J_POST_INSTALL_NATURAL_RUN_OBSERVATION (WAITING_FOR_NATURAL_RUN; 2026-09-19)
- Current task: 3J — observe the next natural scheduled run after the 3I single-file runtime install. No forced/synthetic run, no manual trigger, no new schedule, no background monitor, no busy-wait polling.
- Pro ruling (conv 6aacd52f): prework ACCEPTED; 3J stays WAITING_FOR_NATURAL_RUN, not closed.
- Install state (3I, COMPLETE/CLOSED):
  - Installed file: %LOCALAPPDATA%\InvestorIntelligence\V213Runtime\scripts\v213_sealed_refresh.ps1
  - Installed SHA-256: 66b25c0b0ed0732f6d28642c04d2b178249b1ce7e174dbf3ba434767d197f1f7 (matches accepted hash)
  - Old hash (backup .task0-3i-20260919T034131Z.bak): 7ff671257ba94874521937e8fc2915089c4091c3606c072b2d21585cbb87f897
  - Time bound: OBSERVED_AT_UTC 2026-09-19T03:54:47Z; basis = observed installed hash match (INSTALL_COMPLETED_AT not established from available records)
- Observation target:
  - NEXT_EXPECTED_TASK: InvestorIntelligence-v21-EveningRefresh
  - NEXT_SCHEDULED_TIME_AS_OBSERVED: 2026-09-19T20:20:00+08:00
  - POST_INSTALL_COMPLETED_RUN: NOT_OBSERVED (as of prework snapshot); PUBLICATION_RESULT: NOT_TESTED
- Constraints: MANUAL_TASK_TRIGGER_AUTHORIZED=false; RUNTIME_CHANGE_AUTHORIZED=false; CLOUD_API_CALLS_AUTHORIZED=false.
- STATUS: WAITING_FOR_NATURAL_RUN; TASK_COMPLETE=false
- NEXT: after the EveningRefresh natural run, capture schedule state + sealed-refresh.log + freshness-watch + latest snapshot pointer + report mtime, record the result, then report to controller.

## Current operational state (2026-09-19)
- Branch: fix/options-provenance-audit. HEAD before this session's fixes: d5af746.
- Schedules (all Ready): InvestorIntelligence-v21-EveningRefresh (20:20), InvestorIntelligence-v21-MorningRefresh (07:20), InvestorIntelligenceSealedFreshness (60-min), InvestorIntelligenceFreshnessWatchdog (30-min).
- Freshness: FRESH (last watch 2026-09-19 ~05:26Z); 60-min SealedFreshness is producing fresh sealed runs using the newly installed script (latest REFRESH OK run 20260919T045615Z, pointer last; ranked GEV 96.0, 6501 93.0).
- Backend: localhost:5000 tabbyAPI, exact model Qwen3.8-27B-EXL3-SC5-H6-V6 (unchanged).
- Admission: publication_eligible=false (all public-source adapters emit publication_eligible: False; TEST_ONLY tier, no authenticated public publication).

## Open findings — fixed this session (2026-09-19)
1. Gateway startup model-pin gate was id-only and rejected valid alias configs (requested model served as an alias of the canonical id). FIXED: `verify_served_model` in scripts/v213_local_llm_gateway.py now uses the alias-aware `resolve_model_id` (still fail-closed on collision, malformed row, or a name never served). Regression test tests/test_v213_r75_gateway_process.py passes.
2. security_check flagged 5 user-specific Windows profile paths (documents/TASK0-3G, documents/TASK0-3I, state/STATUS.md). FIXED: rewritten to the established %LOCALAPPDATA% convention. security_check now PASS.
3. documentation_structure_gate: state/STATUS.md exceeded the 12000-byte budget (was 98276) and 6 documents/ files were unlinked from docs/README.md. FIXED: STATUS.md trimmed to current state (this file); docs/README.md index links added for documents/TASK0-3E..3J.

## Verification status (this session, 2026-09-19)
- workflow_supply_chain_gate: PASS
- security_check: PASS
- compileall (scripts tests): PASS
- JSON validation (config/*.json): PASS
- unittest discover: 1531 tests — the gateway model-pin failure is fixed; the two STATUS.md-size failures are resolved by this trim. (Re-run to confirm 0 failures before commit.)
- Worker (cloud) typecheck/tests: not yet re-run this session.

## External mutations
- None. 0 Production/KV/DO/schedule/LINE/credential writes this session. No release claim.

## History
- Dated task history (TASK0-3A..3I, TASK0-2K, TASK0-1C..1I, TASK0-E2, autopilot chapters) is preserved in Git. Full pre-trim status text: `git show 38860e7:state/STATUS.md`; later revisions via `git log -- state/STATUS.md`. Immutable task evidence: documents/TASK0-3E_CLAIM_SOURCE_FEASIBILITY.md through documents/TASK0-3J_POST_INSTALL_NATURAL_RUN_OBSERVATION.md. This file holds current findings and next actions only; evidence is never restamped.