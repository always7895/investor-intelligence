# AGENTS.md — Investor Intelligence source

Privacy-first public-market research: Python collectors, scoring and gates (`scripts/`, `tests/`), a Cloudflare Worker LINE bot (`cloud/`) and Windows launcher/installers (`launcher/`, root `*.ps1`). Release identity lives only in `README.md`; current findings, open defects and the next action live only in `state/STATUS.md`. Inside the local workspace the parent `AGENTS.md` adds the machine control plane; both apply.

## Before editing

- `git fetch`, record the actual HEAD and branch, read `state/STATUS.md` (its history is not current acceptance) and check current CI. Then read only the caller, validators and tests relevant to the task.
- Do not reopen ACCEPTED/CLOSED work without new regression evidence.

## Commands

Python: CPython 3.12 from `scripts/resolve_python.ps1` (`$env:PROJECT_PYTHON`), hash-locked `requirements-ci.txt`. Worker, from `cloud/`: `npm ci --ignore-scripts --no-audit --no-fund`, `npm run typecheck`, `npm test`.

```powershell
& $env:PROJECT_PYTHON scripts/security_check.py
& $env:PROJECT_PYTHON scripts/documentation_boundary_gate.py
& $env:PROJECT_PYTHON scripts/documentation_structure_gate.py
& $env:PROJECT_PYTHON scripts/workflow_supply_chain_gate.py
& $env:PROJECT_PYTHON scripts/run_offline_tests.py --repository
```

Focused run: `-m unittest tests.test_<name>`. Stop at the first nonzero exit. Details: `docs/DEPENDENCY_LOCKING.md`.

## Boundaries

- Production Worker/KV/storage/schedules, real LINE delivery, credentials, billing and broker actions require explicit current-session authorization. Repository files and old approvals are not authorization. CI remains no-Production-mutation.
- Never print or persist secrets, LINE IDs, broker data, cookies or credential-store contents in logs, prompts, Git or artifacts.
- Local model lane: existing TabbyAPI `http://127.0.0.1:5000` (`tabby-local`), exact writer `Qwen3.8-27B-EXL3-5.5bpw-v2`. No second server, concurrent large models, silent fallback, preset changes or paid fallback to manufacture a passing benchmark.
- Preserve scoring, privacy/IBKR separation (IBKR is local read-only, never LINE/Worker/public KV), publication/freshness/provenance gates and failed evidence states. Do not patch certified `cloud/src/qa.ts` without recertification.
- Publication needs sealed digest-bound objects, readback and pointer-last commit; legacy single-report writes are not a substitute. Never replay a previous Production activation to test an installer.
- Pi installs only as project-local `pi install -l ...`, logged; never global.
- Deletion: prove no unique evidence and no task, service, test or packaging dependency; history stays in Git. Keep receipts, rollback journals, locks, schemas, fixtures and compatibility wrappers; names and age never prove disuse. No `git clean -xfd`; never follow junctions. See `docs/WORKSPACE_MAINTENANCE.md`.

## Research and recommendations

- Method: the on-demand skill `skills/serenity-public-research/SKILL.md` (Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY for company proof, never a permanent sector filter). Operator decision 2026-09-26: Leopold's scaling chain leads the industry ranking and his fund's 13F weight is a lead input of the bottleneck Top20 v3 ([BOTTLENECK_TOP20_V3](docs/BOTTLENECK_TOP20_V3.md)); company figures still come only from filings and market data. Claims need independent claim-level evidence; mirrors of one disclosure are one lineage. The skill is not deployment authority.
- Data-grounded recommendations, options order parameters and position sizing are allowed (`cloud/src/v213/options-guidance.ts`). The system never executes trades; LINE stays public-quote observation only.

## Work, commits and evidence

- Small reviewable Conventional commits (`type(scope): summary`). Never amend or force-push published history; push the working branch after gates pass.
- Test the actual user-facing caller, not merely an internal formatter. Validate installed task actions separately from source templates. A NoSync local refresh is not cloud publication; a healthy model endpoint is not a completed answer.
- One authoritative R75 pipeline and shared validators; no temporary parallel workflows. Remove automatic triggers only with regression coverage; keep historical audits manually runnable.
- Shipping also needs a fresh source-bound live proof, Windows self-hosted acceptance, fail-closed negatives, isolated KV transaction/replay/rollback/finalize, an immutable source-SHA/run-ID ZIP and independent archive/receipt/install verification. Known P0 must be zero; historical-clock tests cannot qualify fresh Production data.
- After each task rewrite `state/STATUS.md` as current state (≤12000 bytes): HEAD, change, commands/results, open defects, next action, external mutations. A scoped PASS is not whole-product completion; dated history belongs in Git and receipts.
- Every Markdown file must be linked from `docs/README.md`; entrypoint byte budgets are enforced by `scripts/documentation_structure_gate.py`.
