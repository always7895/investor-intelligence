# R75 takeover status

## Milestone M1 — shared publication contract (2026-09-04)

- Baseline HEAD: `80c45c4b242dba99560ba99151785812520a09dd`
- Branch: `pi/r75-takeover-20260904-1343`
- Source fetch: completed before edits; Production mutation: **none**.
- Implemented one versioned contract at `config/v213-r75-publication-mode-v1.json`, canonical SHA-256, and common all-LIMITED/mixed fixtures.
- Python, Windows PowerShell 5.1, PowerShell 7, and TypeScript consume the same contract/fixtures.
- Optional BLS is non-required; core SEC/Nasdaq/World Bank/ECB families remain required.
- Worker activation ingestion validates publication modes and returns the contract ID/hash.
- PowerShell `-PreflightOnly` validates the sealed digest-bound bundle, emits no mutation, and pins its SHA into the activation core to block loose-cache/TOCTOU drift.

### Validation

- `python scripts/v213_r75_activation_preflight.py --self-test` — PASS.
- `python scripts/v213_r75_activation_preflight.py --fixture tests/fixtures/v213-r75-publication-mode/mixed.json` — PASS (10 strict, 10 LIMITED, 1 HIGH, BLS absent).
- Windows PowerShell 5.1 `scripts/test_v213_r75_publication_contract.ps1` — PASS; contract SHA `9b96f2fd68318e6476dc00d0d003162c0343d2aece5ef25f522fe7c33dca7bfd`.
- PowerShell 7 same contract test — PASS; same SHA.
- Windows PowerShell 5.1 and PowerShell 7 activation wrapper `-SelfTest` — PASS, no network/mutation.
- `cloud: npm run typecheck` — PASS.
- `cloud: npm test -- --run test/v213-activation.test.ts test/v213-publication-mode.test.ts` — PASS (2 files, 7 tests).

### Open defect counts

- P0: **4** (`P0-04` remaining negative matrix/real bundle; `P0-05` gateway process path; `P0-06` authoritative Windows runner Python; `P0-07` tunnel policy).
- P1: **10**.
- P2: **7** (`P2-08` temporary workflow cleanup completed at baseline; other items remain or require release evidence).

### Next action

Complete M2 fail-closed fixture matrix and full Worker suite, then M3 gateway process/concurrency work.
