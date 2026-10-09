# Locked dependencies and local validation

## Authority

Exact dependencies are in [requirements-ci.txt](../requirements-ci.txt) and [cloud/package-lock.json](../cloud/package-lock.json), not a version table in documentation. Both locks exist. Source and installed runtimes require separate validation; do not upgrade packages just to make a benchmark pass.

## Python

Use the existing approved CPython3.12.10 resolved by [bootstrap](../scripts/bootstrap_portable_python.ps1) / [resolver](../scripts/resolve_python.ps1), with the reviewed transitive hash lock. CI bootstraps the portable runtime itself. Locally the resolver has two modes, both setting `$env:PROJECT_PYTHON` in the calling process only on success, reusing a compatible existing venv and never deleting or replacing anything at `-VenvPath`:

- generic (default, activation fallbacks): any 64-bit Python >= `-MinimumVersion`; installs nothing;
- `-InstallLockedDependencies`: only 64-bit CPython 3.12.10 (implementation checked), for the base and a reused venv; installs `requirements-ci.txt` with the command below and runs `pip check` on every call.

`-BasePython` pins the base interpreter only when a venv is created; a reused venv is judged by its own interpreter. An existing destination, even an empty directory, must already be a compatible venv. If an optional GitHub file cannot be written the call fails with `PROJECT_PYTHON` unset; an earlier append to the other file is not undone.

Local gates use a dedicated checkout venv (ignored by `.venv-*/`), not `.venv-ci`. A run on an unpinned base interpreter is diagnostic, not locked acceptance.

```powershell
& .\scripts\resolve_python.ps1 -VenvPath .venv-local-gates -InstallLockedDependencies
$env:PYTHONUTF8 = '1'
& $env:PROJECT_PYTHON scripts/security_check.py
& $env:PROJECT_PYTHON scripts/documentation_boundary_gate.py
& $env:PROJECT_PYTHON scripts/documentation_structure_gate.py
& $env:PROJECT_PYTHON scripts/workflow_supply_chain_gate.py
& $env:PROJECT_PYTHON scripts/run_offline_tests.py --repository
```

The locked install the resolver runs (also what CI and R70 run explicitly):

```powershell
& $env:PROJECT_PYTHON -m pip install --isolated --disable-pip-version-check --only-binary=:all: --index-url https://pypi.org/simple --require-hashes -r requirements-ci.txt
& $env:PROJECT_PYTHON -m pip check
```

Commands run from the development root; stop at each nonzero exit. `PYTHONUTF8=1` matches CI (without it a CLI test fails on cp950 consoles). R75's existing validator enforces failures. Live providers require separate access/rights and source-bound acceptance; successful dependency installation is not that proof.

[scripts/run_offline_tests.py](../scripts/run_offline_tests.py) supplies import stubs **only for absent optional packages**. It is not a network sandbox: installed requests/yfinance are real modules. Tests must mock live transport; never interpret the runner name as permission to fetch or publish. Distribution mode excludes repository-only metadata tests, not production acceptance requirements.

## Worker

From `cloud`, using the approved Node resolver:

```text
npm ci --ignore-scripts --no-audit --no-fund
npm run typecheck
npm test
```

`npm ci` is a clean frozen install: it fails on package/lock disagreement, removes existing node_modules and does not rewrite the lock. `--ignore-scripts` disables install lifecycle scripts; explicit `npm test` / `npm run` still execute their requested scripts. Do not replace it with `npm install` or omit devDependencies needed by tsc/Vitest/Wrangler.

## CI and efficiency

- The [R75 pipeline](../.github/workflows/v213-r75-release.yml) is authoritative; reviewed Windows validation-only runs do not package or qualify a release.
- Preserve full-SHA Actions, non-persisted checkout credentials, read-only contents, self-hosted runner boundaries and no-Production-mutation. Read current workflow pins; the old checkout-v4 prose was stale.
- Do not skip required workflows using path filters without reviewing branch rules: skipped workflows can leave required checks Pending. No automatic trigger is removed by this cleanup.
- Fix stale duplicated lock assertions to the existing reviewed R75 lock; do not weaken the comparison or regenerate dependencies.
- Native PS5.1/7, fresh source-bound live proof, sealed transaction negatives and independent ZIP/receipt/install checks remain separate release gates.

[Official/community rationale and scope](ENGINEERING_MAINTENANCE.md).
