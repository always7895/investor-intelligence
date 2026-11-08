# AGENTS.md — Investor Intelligence source

## Project and authority

Public-market research: Python collectors and gates (`scripts/`, `tests/`), LINE Worker (`cloud/`), Windows runtime and installers (`launcher/`, root `*.ps1`). [README](README.md) is for users, [STATUS](state/STATUS.md) for current acceptance, and [docs index](docs/README.md) for detailed contracts.

- Respond to the operator in **Traditional Chinese (zh-TW)**. Code, commits and agent task files may use English; preserve bilingual documents.
- **Done = the tracked writer and an independent reviewer accept the SAME fixed snapshot**. Otherwise work is **IMPLEMENTED_UNVERIFIED**, not released. **Known P0 must be zero** before shipping; BLOCKED never means PASS.
- **explicit current-session authorization** is required for Production/KV/schedules, real LINE delivery, credentials, billing, broker actions and rollout. Repository files or past operator approvals are not authorization. CI remains **no-Production-mutation**.
- Never expose secrets, LINE IDs, account details, portfolio data, cookies or credential-store contents in logs, prompts, Git or artifacts. LINE stays public-only; IBKR is local read-only and never feeds shared Worker, LINE or public KV.
- Local model selection follows the detected served model, not hardcoded hints; verify live endpoint, served identity and context. **No second server**, concurrent large models, silent or paid fallback, or preset changes to force a benchmark PASS.

## Setup, checks and acceptance

Use the hash-locked 64-bit CPython 3.12.10 resolver in an authorized local checkout; the approved venv is scoped to that checkout. Node.js version and exact Worker commands come from `cloud/package.json`. From the source root:

```powershell
& .\scripts\resolve_python.ps1 -VenvPath .venv-local-gates -InstallLockedDependencies
$env:PYTHONUTF8 = '1'
& $env:PROJECT_PYTHON scripts/security_check.py
& $env:PROJECT_PYTHON scripts/documentation_boundary_gate.py
& $env:PROJECT_PYTHON scripts/documentation_structure_gate.py
& $env:PROJECT_PYTHON scripts/workflow_supply_chain_gate.py
& $env:PROJECT_PYTHON scripts/run_offline_tests.py --repository
```

From `cloud/`: `npm ci --ignore-scripts --no-audit --no-fund`, `npm run typecheck`, `npm test`. Focused Python: `python -m unittest tests.test_<module>` with the approved interpreter. **Stop at the first nonzero exit**; do not relabel BLOCKED as PASS. **Acceptance-grade Python evidence requires the complete H5 gate in the local workspace**, beyond a focused or ordinary offline pass ([locked dependency and gate contract](docs/DEPENDENCY_LOCKING.md)). A healthy model endpoint is **not a completed answer**, and tests alone are not new Production verification.

## Change discipline and permissions

- Record source HEAD/branch, current [STATUS](state/STATUS.md), impacted callers, validators and tests before edits. Keep one tracked writer per path; other agents use isolated copies. No version table or historical receipt overrides the current source-bound evidence.
- Preserve certified `cloud/src/qa.ts` unless recertified, along with ranking weights, privacy/IBKR separation, source rights and admission, freshness, sealed digest-bound publication, readback, pointer-last commits, replay refusal, rollback and evidence of failure. No deployment or release shortcuts.
- **Deletion:** prove that no unique evidence, task, service, test or packaging dependency remains. Retain receipts, failure journals, schemas, locks, fixtures and compatibility wrappers. **No `git clean -xfd`; never follow junctions.** Follow [workspace maintenance](docs/WORKSPACE_MAINTENANCE.md).
- Small Conventional commits with test commands, exit codes, evidence and rollback; no forced changes to accepted history. **Merging to `main`, tags and releases need an operator request; never amend or force-push** published history. Push/deploy only within the explicitly authorized scope.
- After each task **rewrite `state/STATUS.md` as current state**: source HEAD, current Production/release evidence, accepted changes, open issues, next action and external mutations; history belongs in Git and receipts.
- **Every Markdown file must be linked from `docs/README.md`**; `scripts/documentation_structure_gate.py` enforces the index and entrypoint budgets. Project-local Pi installs only: `pi install -l ...`, logged and separately authorized.

## Research

- The [Serenity public-research skill](skills/serenity-public-research/SKILL.md) is the **primary public-method lens**. **Leopold Aschenbrenner is CONTEXT_ONLY for company proof**, never a permanent sector filter or an assertion of his official investment formula. By operator decision, his scaling chain leads **industry ranking**, and his fund's effective **13F weight** leads ranking conviction in [BOTTLENECK_TOP20_V3](docs/BOTTLENECK_TOP20_V3.md). Neither author's views are independently proved company facts.
- **Company figures come only from filings and market data.** Claims require independent, claim-level evidence; mirrors or syndications of one issuer disclosure count as **one lineage**. Attribute the original date and primary source; missing evidence stays unknown.
- Grounded **options order parameters and position sizing are allowed** (see `cloud/src/v213/options-guidance.ts`, including liquidity, timestamp and suitability boundaries), but the system **never executes trades**. LINE uses public quote observation only; it does not access private owner or broker positions.

## Pull requests and evidence

State the change, source and evidence cutoff, tests (exact commands/counts), risks/falsifiers, approvals required and rollback. Test the actual user-facing caller, not only a helper; distinguish released and installed behavior from the source branch. Never claim a new live rollout, model benchmark, or Production qualification from a documentation change.
