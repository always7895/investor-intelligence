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

## Milestone M2 — Worker and fail-closed fixture matrix (2026-09-04)

- Input HEAD: `3880309`.
- Worker all-LIMITED and mixed (10/10) modes PASS with BLS absent; strict HIGH eligibility is accepted only with qualifying evidence/market state.
- Fail-closed coverage now includes LIMITED positive factor, HIGH eligibility, validated thesis, one provenance origin/domain, all four strict evidence metrics, count, order/rank, freshness, stale bundle, and digest defects.
- Negative LIMITED factor remains accepted (positive-only withholding semantics).
- `python scripts/v213_r75_activation_preflight.py --self-test` — PASS for the complete matrix.
- Windows PowerShell 5.1 and PowerShell 7 wrapper `-SelfTest` — PASS and execute the same Python/common-fixture matrix.
- `cloud: npm run typecheck` — PASS.
- `cloud: npm test` — PASS (18 files, 97 tests).
- External/Production mutation: **none**.

### Open defect counts

- P0: **3** (`P0-05`, `P0-06`, `P0-07`).
- P1: **10**.
- P2: **7**.

### Next action

M3: implement a direct Windows-safe Gateway launch contract, exact model pin, bounded generation admission, non-blocking health, and redacted bounded startup diagnostics.

## Milestone M3 — Windows-safe Gateway and exact-model admission (2026-09-04)

- Input HEAD: `0824532`.
- Gateway rejects request model substitution with HTTP 409 and always sends the environment-pinned exact model upstream.
- A bounded global generation semaphore rejects excess work with HTTP 429 and `Retry-After`; `/health` does not acquire a generation slot.
- PowerShell 5.1-compatible native argument quoting launches the real Gateway script from a path containing spaces, Unicode, and `(1)`.
- Startup failures include only bounded, secret-redacted stdout/stderr tails.
- Real HTTP process test verifies special-path startup, exact pinning, upstream model identity, concurrent backpressure, and health responsiveness.
- `python -m unittest tests.test_v213_local_llm_gateway tests.test_v213_r75_gateway_process -v` — PASS (6 tests).
- Gateway `--self-test` — PASS.
- Windows PowerShell 5.1 and PowerShell 7 bridge `-SelfTest` — PASS.
- External/Production mutation: **none**; existing llama.cpp Router configuration was not altered.

### Open defect counts

- P0: **2** (`P0-06`, `P0-07`).
- P1: **8** (`P1-02` and `P1-03` completed).
- P2: **7**.

### Next action

M4: enforce test-only Quick Tunnels, named-tunnel Production policy, truthful transient-DNS status, and blue/green cutover/rollback lifecycle tests.

## Milestone M4 — tunnel and bridge lifecycle (2026-09-04)

- Input HEAD: `9171405`.
- Quick Tunnel is explicitly `QuickTest`, marked test-only/non-Production, and requires three consecutive public health checks.
- Transient public health/DNS failures produce `PASS_WITH_TRANSIENT_DNS_FAILURES`, with counts persisted in bridge state; they cannot be reported as a plain PASS.
- Named tunnels require validated name, hostname, and config; Production activation rejects non-named tunnel state unless the operator supplies the explicit test-tunnel exception switch.
- Blue/green behavior starts and validates the new Gateway+tunnel before any old bridge is stopped; failure stops only the new bridge, staged promotion retains old until finalize, and finalize then stops old.
- Root and source-diverse launch aliases route through the same managed core and expose named-tunnel/finalize parameters.
- Windows PowerShell 5.1 and PowerShell 7 bridge lifecycle `-SelfTest` — PASS.
- Activation wrapper aliases remain byte-identical and both shell self-tests PASS.
- External/Production mutation: **none**; no tunnel was created or changed during tests.

### Open defect counts

- P0: **1** (`P0-06`: authoritative Windows Runner Python/release pipeline evidence).
- P1: **7** (`P1-06` completed).
- P2: **6** (`P2-04` completed).

### Next action

M5: snapshot readback/replay/rollback journal, operation locking, scheduler hardening, and atomic LINE dedupe.

## Milestone M5 — transaction, operation, schedule, and LINE safety (2026-09-04)

- Input HEAD: `fca4751`.
- Activation writes immutable objects without short TTL, reads every expected object back before pointer promotion, verifies again after promotion, and rejects missing/corrupt replay.
- Rollback journal moved from short-lived ephemeral KV to durable private operational storage; prepared-journal restart resumes safely, pointer-last remains enforced, rollback restores exact prior text, and finalize removes the journal.
- Public reads fail closed on dangling promoted pointers instead of silently using stale direct-key fallback.
- One cross-process/reentrant named mutex serializes activation, bridge, and scheduled refresh operations; contention fails closed.
- Scheduled refresh is data-only and records no-mutation receipts; Task Scheduler policy includes WakeToRun, network requirement, StartWhenAvailable missed-slot recovery, three retries, 100-minute timeout, and StopExisting timeout recovery.
- Scheduled LINE sends use a Durable Object pending/sent lease; concurrent test sends exactly once and reports the contender as in-progress.
- `cloud: npm run typecheck` — PASS.
- `cloud: npm test` — PASS (18 files, 101 tests).
- Activation core self-tests on Windows PowerShell 5.1 and PowerShell 7 — PASS.
- Operation-lock cross-process tests on both shells — PASS.
- Scheduler ValidateOnly and data-only fake-runtime execution on both shells — PASS.
- External/Production mutation: **none**; no scheduled task was registered and no LINE request was sent outside synthetic mocks.

### Open defect counts

- P0: **1** (`P0-06`).
- P1: **1** (`P1-01`: long-running cloud QA remains an availability limitation; no unsafe fallback).
- P2: **6**.

### Next action

M6 authoritative Windows no-mutation matrix and isolated transaction packaging tests, followed by M7 immutable artifact workflow and independent download verification.
