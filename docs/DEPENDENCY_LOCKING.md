# Dependency Locking and Offline Acceptance

## Policy

Repository validation must not download mutable dependencies before security and privacy gates run. Active workflows therefore reject unpinned Actions, persisted checkout credentials, repository-content writes, unlocked Python installs and `npm install`.

## Python

Offline policy, parser, privacy, provenance and source-fabric tests run through `scripts/run_offline_tests.py`. The runner supplies fail-closed import stubs only when optional live-provider packages are absent. Any attempted yfinance or HTTP operation from an offline test raises immediately.

Live yfinance/requests execution remains disabled until a reviewed transitive lock with SHA-256 hashes is committed and installed with `pip --require-hashes`. Direct top-level version pins without transitive hashes are not sufficient for release acceptance.

## Node / Worker

Worker acceptance requires a reviewed `cloud/package-lock.json`. The only permitted install command is:

```text
npm ci --ignore-scripts --no-audit --no-fund
```

The lockfile must be generated from the exact `cloud/package.json`, independently reviewed for unexpected packages and integrity entries, then verified by typecheck and Vitest on BARRY. Until the lockfile exists, Phase 5 correctly reports FAIL/BLOCKED rather than falling back to `npm install`.

## GitHub Actions

Third-party Actions must use full 40-character commit SHAs. The current checkout pin corresponds to reviewed `actions/checkout` v4.2.2. Moving tags such as `@v4`, hosted runners and `pull_request_target` are rejected by `scripts/workflow_supply_chain_gate.py`.

## Release boundary

An offline Phase 3 PASS proves only the reviewed source-fabric and policy code at the recorded commit. It does not imply Node acceptance, live-provider readiness, deployment approval or final release readiness.
