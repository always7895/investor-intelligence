# AGENTS.md — Investor Intelligence source

## Project and authority

Privacy-first public-market research: Python source adapters, claim admission and ranking (`scripts/`, `tests/`); Cloudflare Worker LINE rendering (`cloud/`); optional Windows local model and install tooling (`launcher/`, `*.ps1`). [README](README.md) is human-facing; [STATUS](state/STATUS.md) is the current evidence/defect/next-step ledger; [docs index](docs/README.md) routes deeper contracts.

- Operator-facing responses are **zh-TW**; code and Git commits use concise English. Working docs may be bilingual.
- **explicit current-session authorization** is needed before Production/KV/schedules, real LINE delivery, secrets, billing, broker actions, releases or merges. Historical approvals are not authorization. CI remains **no-Production-mutation**.
- A development PASS does not equal a released product: independent reviewer and writer must accept the same source-bound snapshot. **Known P0 must be zero** before shipping. BLOCKED is never PASS.
- Source research may use public filings and documented permitted feeds. Never transfer owner holdings, broker records, LINE identifiers or private data to Worker, shared model context, public KV, artifacts, logs or prompts. IBKR stays local read-only. No trade execution or paid fallback.
- Verify live served model identity and context; follow the detected model. **No second server** or simultaneous GPU service, silent provider substitution or preset changes to make a benchmark appear to pass.

## Exact setup and checks (Windows source checkout)

Use the hash-locked 64-bit CPython 3.12.10 resolver for acceptance; it changes only an approved local venv. Never install or upgrade dependencies outside an authorized workspace.

```powershell
& .\scripts\resolve_python.ps1 -VenvPath .venv-local-gates -InstallLockedDependencies
$env:PYTHONUTF8 = '1'
& $env:PROJECT_PYTHON scripts/security_check.py
& $env:PROJECT_PYTHON scripts/documentation_boundary_gate.py
& $env:PROJECT_PYTHON scripts/documentation_structure_gate.py
& $env:PROJECT_PYTHON scripts/workflow_supply_chain_gate.py
& $env:PROJECT_PYTHON scripts/run_offline_tests.py --repository
```

For a focused Python module use `python -m unittest tests.test_<module>` with the admitted interpreter. For Worker tests (from `cloud/`): `npm ci --ignore-scripts --no-audit --no-fund`, `npm run typecheck`, `npm test`. `cloud/package.json` specifies Node >=20. The four gates check local safety and docs; a green offline test is **not a completed answer** or a Production acceptance. Follow [DEPENDENCY_LOCKING](docs/DEPENDENCY_LOCKING.md).

## Change discipline

- Read HEAD, `state/STATUS.md`, impacted callers/validators/tests and the exact code before editing. Only one writer per path; use isolated worktrees for parallel tasks. Never assume running a file deletes or deploys nothing: examine its implementation.
- Python: type-safe, explicit unknown/fail-closed states, independent primary-source evidence, dated claims. TypeScript: strict types, bounded LINE messages, deterministic wire validators. Do not infer formatting rules from unreviewed examples.
- Preserve certified `cloud/src/qa.ts`, source/rights/admission gates, scoring weights, publication freshness, digest-bound sealed objects, readback and pointer-last journal/rollback. No release mutation to hide a test failure.
- Keep PRs narrow: conventional commits, exact test exit codes, immutable evidence receipts; no force push. Only explicitly authorized integration/release may push or deploy.
- Do not delete historical evidence, manifests, rollback journals, lock files or wrappers on the basis of age; prove reachability and test pins first.
- `pi install -l` is the only allowed Pi install form: project-local, logged and separately authorized.
- Skills are on-demand and do not authorize runtime execution: [Serenity research skill](skills/serenity-public-research/SKILL.md); [privacy](docs/PRIVACY_MULTI_TENANT_POLICY.md); [release](docs/FINAL_RELEASE_PLAN.md).

## Pull requests

State what changed, why, risks/falsifiers, exact commands/counts, source provenance, tests and rollback. Document permissions/Production separately. Review artifacts must contain no credentials, private account identifiers or broker data.
