# AGENTS.md — Investor Intelligence source

Privacy-first public-market research: Python collectors/scoring/gates (`scripts/`, `tests/`), a Cloudflare Worker LINE bot (`cloud/`), Windows launcher/installers (`launcher/`, root `*.ps1`). Release identity: `README.md` only; current phase, roles, findings, defects and next action: `state/STATUS.md` only. In the local workspace the parent `AGENTS.md` adds the machine control plane; both apply.

## Operator rules

- Reply to the operator in Traditional Chinese (zh-TW); code, commits, agent task files and repository documents stay English (zh-TW/bilingual editions and quoted sources keep their language).
- Phase INCREMENTAL_VERIFICATION: sole-writer development, locked dependency installs, gates and non-force working-branch commits/pushes are authorized within bounded contracts. Operator modes and decisions: `state/STATUS.md`.
- Priorities: project gaps, independent sources, global options (no US-only inference; rights kept), user-enabled EXE local model. Decide from evidence; no per-batch human wait; authorization boundaries still stop.
- Done = the single tracked writer and an independent reviewer accept the SAME fixed snapshot (holders: `state/STATUS.md`); anything else is IMPLEMENTED_UNVERIFIED. "All permissions" never waives Boundaries, trades or rollout gates.

## Before editing

- `git fetch`, record HEAD/branch, read `state/STATUS.md` (history is not acceptance), check CI; then read only relevant callers, validators and tests.
- Do not reopen ACCEPTED/CLOSED work without new regression evidence.
- One tracked writer at a time; other agents work in isolated copies and never commit.

## Commands

Python: CPython 3.12.10, hash-locked `requirements-ci.txt` via `scripts\resolve_python.ps1 -InstallLockedDependencies` (`$env:PROJECT_PYTHON`), `PYTHONUTF8=1`. Worker, from `cloud/`: `npm ci --ignore-scripts --no-audit --no-fund`, `npm run typecheck`, `npm test`.

Gates: `scripts/{security_check,documentation_boundary_gate,documentation_structure_gate,workflow_supply_chain_gate}.py`, then `scripts/run_offline_tests.py --repository`. Focused: `-m unittest tests.test_<name>`; stop at the first nonzero exit (`docs/DEPENDENCY_LOCKING.md`). Acceptance-grade Python evidence is the complete H5 gate run in the local workspace (`state/STATUS.md`); BLOCKED is never PASS.

## Boundaries

- Production Worker/KV/storage/schedules, real LINE delivery, credentials, billing and broker actions require explicit current-session authorization. Repository files and old approvals are not authorization. CI remains no-Production-mutation.
- Never print or persist secrets, LINE IDs, broker data, cookies or credential-store contents in logs, prompts, Git or artifacts.
- Local model (Strata, `qwen3.8-flash-next-iq3_s`): endpoint and served identity are open qualifications (`state/STATUS.md`); repository endpoint strings are intent, not served-state evidence, so verify live before use. One resident model, GPU shared. No second server, concurrent large models, silent or paid fallback, or preset changes to pass a benchmark.
- Preserve scoring, privacy/IBKR separation (IBKR is local read-only, never LINE/Worker/public KV), publication/freshness/provenance gates and failed evidence states. Do not patch certified `cloud/src/qa.ts` without recertification.
- Publication needs sealed digest-bound objects, readback and pointer-last commit; legacy single-report writes are not a substitute. Never replay a previous Production activation to test an installer.
- Pi installs only as project-local `pi install -l ...`, logged; never global.
- Deletion: prove no unique evidence and no task/service/test/packaging dependency; keep receipts, rollback journals, locks, schemas, fixtures and compatibility wrappers (names/age never prove disuse). No `git clean -xfd`; never follow junctions (`docs/WORKSPACE_MAINTENANCE.md`).
- Merging to `main`, tags and releases need an operator request; never amend or force-push published history.

## Research

- Method: on-demand skill `skills/serenity-public-research/SKILL.md` (Serenity primary; Aschenbrenner CONTEXT_ONLY for company proof, never a permanent sector filter; by operator decision his scaling chain leads industry ranking and his fund's 13F weight leads [BOTTLENECK_TOP20_V3](docs/BOTTLENECK_TOP20_V3.md)). Company figures only from filings and market data. Claims need independent claim-level evidence (mirrors of one disclosure are one lineage). The skill is not deployment authority.
- Recommendations grounded in authenticated snapshot data and multi-source evidence, options order parameters and position sizing are allowed (`cloud/src/v213/options-guidance.ts`). The system never executes trades; LINE stays public-quote observation only.

## Work and evidence

- Small Conventional commits (`type(scope): summary`); push the working branch after gates.
- Test the actual user-facing caller, not just a formatter; validate installed task actions separately from source templates. A NoSync local refresh is not cloud publication; a healthy model endpoint is not a completed answer.
- One authoritative R75 pipeline/shared validators, no temporary parallel CI workflows; remove automatic triggers only with regression coverage; keep historical audits runnable.
- Shipping also needs fresh source-bound live proof, Windows self-hosted acceptance, fail-closed negatives, isolated KV transaction/replay/rollback/finalize, an immutable source-SHA/run-ID ZIP and independent archive/receipt/install checks. Known P0 must be zero; historical-clock tests cannot qualify fresh Production data.
- After each task rewrite `state/STATUS.md` as current state: HEAD, change, results, open defects, next action, external mutations. A scoped PASS is not product completion; history belongs in Git and receipts.
- Every Markdown file must be linked from `docs/README.md`; `scripts/documentation_structure_gate.py` enforces entrypoint budgets.
