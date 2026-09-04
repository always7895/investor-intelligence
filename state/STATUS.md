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

## Milestone M6 — authoritative Windows validation implementation (2026-09-04)

- Input HEAD: `d28a96e`.
- Consolidated the superseded v2.1.3 delivery/hotfix workflows into one read-only, no-mutation R75 Windows workflow: `.github/workflows/v213-r75-release.yml`.
- The workflow bootstraps the repository-pinned CPython 3.12.10 runtime, installs the hash-locked wheel set, runs the complete Python and Worker suites, executes Windows PowerShell 5.1 and PowerShell 7 gates, and performs a real public-data refresh before requiring an actual 20/20 all-LIMITED sealed-bundle preflight.
- Isolated KV-compatible transaction gates cover object readback, pointer-last promotion, corrupt replay rejection, rollback, and finalize under both PowerShell hosts.
- Reconciled the reviewed source inventory from stale 99-source consumers to the current 101-source catalog and repaired import-order-dependent semantic-guard recursion exposed by complete test discovery.
- `pwsh -File scripts/ci_v213_r75_validate.ps1 -SkipLiveRefresh` — PASS locally using repository-pinned CPython 3.12.10.
- Complete Python suite — PASS (546 tests, 2 skipped).
- Worker typecheck and full Vitest — PASS (18 files, 101 tests).
- Workflow supply-chain, Actions storage, security, and canonical candidate gates — PASS.
- Windows PowerShell 5.1 and PowerShell 7 activation transaction/wrapper/operation-lock tests — PASS.
- External/Production mutation: **none**; the local acceptance intentionally skipped only the authoritative real-network refresh, which remains mandatory (not optional) in CI.

### Open defect counts

- P0: **1** (`P0-06`: successful current-HEAD self-hosted Windows run and downloadable release artifact evidence).
- P1: **1** (`P1-01`: long-running public-source availability remains fail-closed).
- P2: **2** (independent downloaded-artifact verification and final evidence reconciliation).

### Next action

Checkpoint and push M6, inspect the authoritative Windows run, then complete M7 immutable R75 packaging, artifact download, and independent verification.

## Deployment hotfix H1 — automated Production Named Tunnel path (2026-09-05)

- Verified release base: `536644d22ef3534be1c4b8a9e1ff969df4d580fa` (`v2.1.3-R75`).
- Branch: `pi/r75-named-tunnel-deployment-hotfix`.
- Implementation commit: `809cf7c`.
- Added a launcher one-time Named Tunnel setup entry requiring explicit name, hostname, and config.
- Setup validates cloudflared authentication, credential JSON/tunnel identity, ingress, named tunnel existence, and an exact DNS route ensure without printing or copying credentials.
- Launcher refresh/bridge/activation paths now pass `-TunnelMode Named`, `-NamedTunnelName`, `-NamedTunnelHostname`, and `-NamedTunnelConfig`; the normal path does not use `AllowTestTunnelException`.
- Named startup rewrites only a temporary runtime ingress config to the new blue/green gateway port, validates it, requires three consecutive public health-schema-v2 checks for the exact selected model, and retains the recorded bridge on failure.
- Added immutable deployment-hotfix packaging, receipts, independent ZIP verification, and conditional integration into the existing consolidated R75 workflow.
- Protected Serenity scoring, federation thresholds, publication contract, publication semantics, sealed bundle, and base R75 release evidence/package verifier files are unchanged from the verified release commit.

### Validation

- Windows PowerShell 5.1 `scripts/test_v213_named_tunnel.ps1` — PASS.
- PowerShell 7.6.5 same test — PASS.
- Special path with spaces, Unicode, and parentheses — PASS.
- Missing inputs, missing credential reference, and mismatched credential/tunnel identity fail closed.
- Gateway exact-pin/process regression — PASS (6 tests).
- Full no-mutation local matrix `scripts/ci_v213_r75_validate.ps1 -SkipLiveRefresh` — PASS: Python 550 tests (2 skipped), Worker typecheck PASS, Worker 18 files/101 tests PASS, both PowerShell hosts PASS.
- Launcher compile and packaged-root self-test — PASS.
- External/Production mutation: **none**. No Cloudflare route was changed, Worker deployed, Production KV/DO written, LINE sent, or schedule registered.

### Open defect counts

- P0: **1** (successful current-HEAD Windows workflow, immutable hotfix artifact download, and independent post-download receipt remain).
- P1: **0** for this deployment-integration scope.
- P2: **0** for this deployment-integration scope.

### Next action

Commit status, push the work branch, inspect the no-mutation Windows workflow, download its immutable Named Tunnel deployment-hotfix artifact, and independently verify it before stopping.
