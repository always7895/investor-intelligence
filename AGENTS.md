# AGENTS.md — Investor Intelligence source

## Project and authority

Public research: Python collectors and gates (`scripts/`, `tests/`), LINE Worker (`cloud/`), Windows runtime (`launcher/`, root `*.ps1`). [README](README.md) serves users; [STATUS](state/STATUS.md) is current acceptance; [docs index](docs/README.md) stores contracts.

- Respond to the operator in **Traditional Chinese (zh-TW)**. Code, commits and agent task files may use English; preserve bilingual documents.
- **Done = the tracked writer and an independent reviewer accept the SAME fixed snapshot**. Otherwise work is **IMPLEMENTED_UNVERIFIED**, not released. **Known P0 must be zero** before shipping; BLOCKED never means PASS.
- **explicit current-session authorization** is required for Production/KV/schedules, real LINE delivery, credentials, billing, broker actions and rollout. Repository files or past operator approvals are not authorization. CI remains **no-Production-mutation**.
- Never expose secrets, LINE IDs, account details, portfolio data, cookies or credential-store contents in logs, prompts, Git or artifacts. LINE stays public-only; IBKR is local read-only and never feeds shared Worker, LINE or public KV.
- Local model selection follows the detected served model, not hardcoded hints; verify live endpoint, served identity and context. **No second server**, concurrent large models, silent or paid fallback, or preset changes to force a benchmark PASS.

## Setup, checks and acceptance

Use the **hash-locked 64-bit CPython 3.12.10** resolver; the approved virtual environment is **scoped to that authorized checkout**. Node.js commands come from `cloud/package.json`. From the source root:

```powershell
& .\scripts\resolve_python.ps1 -VenvPath .venv-local-gates -InstallLockedDependencies
$env:PYTHONUTF8 = '1'
& $env:PROJECT_PYTHON scripts/security_check.py
& $env:PROJECT_PYTHON scripts/documentation_boundary_gate.py
& $env:PROJECT_PYTHON scripts/documentation_structure_gate.py
& $env:PROJECT_PYTHON scripts/workflow_supply_chain_gate.py
& $env:PROJECT_PYTHON scripts/run_offline_tests.py --repository
```

From `cloud/`: `npm ci --ignore-scripts --no-audit --no-fund`, `npm run typecheck`, `npm test`. Focused Python: `python -m unittest tests.test_<module>` with the approved interpreter. Stop at first nonzero; **full H5 gate** is mandatory for acceptance ([dependency contract](docs/DEPENDENCY_LOCKING.md)). A healthy endpoint is **not a completed answer**, and focused tests are not Production proof.

## Change discipline and permissions

- Record source HEAD/branch, current [STATUS](state/STATUS.md), impacted callers, validators and tests before edits. Keep one tracked writer per path; other agents use isolated copies. No version table or historical receipt overrides the current source-bound evidence.
- Preserve certified `cloud/src/qa.ts` unless recertified, along with ranking weights, privacy/IBKR separation, source rights and admission, freshness, sealed digest-bound publication, readback, pointer-last commits, replay refusal, rollback and evidence of failure. No deployment or release shortcuts.
- **Deletion:** prove that no unique evidence, task, service, test or packaging dependency remains. Retain receipts, failure journals, schemas, locks, fixtures and compatibility wrappers. **No `git clean -xfd`; never follow junctions.** Follow [workspace maintenance](docs/WORKSPACE_MAINTENANCE.md).
- Small Conventional commits with test commands, exit codes, evidence and rollback; no forced changes to accepted history. **Merging to `main`, tags and releases need an operator request; never amend or force-push** published history. Push/deploy only within the explicitly authorized scope.
- After each task **rewrite `state/STATUS.md` as current state**: source HEAD, current Production/release evidence, accepted changes, open issues, next action and external mutations; history belongs in Git and receipts.
- **Every Markdown file must be linked from `docs/README.md`**; `scripts/documentation_structure_gate.py` enforces the index and entrypoint budgets. Project-local Pi installs only: `pi install -l ...`, logged and separately authorized.

## Research

- Use [Serenity research SKILL](skills/serenity-public-research/SKILL.md) and [Top20 contract](docs/BOTTLENECK_TOP20_V3.md) on demand. Serenity is a public research lens; Leopold Aschenbrenner is CONTEXT_ONLY for company proof, not a permanent filter; **his scaling chain leads industry ranking**, not company-claim proof. RULES_KEPT=0: unvalidated author-derived conviction weights.
- Company figures require dated primary issuer filings and market data with **independent claim-level evidence**. Attribute the **original date and primary source**; mirrors or syndications of one disclosure count as **one lineage**. Unknown is not zero. Public indicative options guidance (`cloud/src/v213/options-guidance.ts`) may include risk/position sizing, bid/ask/expiry and **liquidity, timestamp and suitability boundaries**, never a trade; the LINE model sees public observations, no broker positions.

## Pull requests and evidence

Record change, source cutoff, exact tests/exit codes, **risks/falsifiers**, approvals and rollback. Test user-facing callers, not only helpers; distinguish **released/installed behavior from the source branch**. Documentation never proves live rollout, model performance or installed qualification.
