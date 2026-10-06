# AGENTS.md — Investor Intelligence source

Privacy-first public-market research: Python collectors/scoring/gates (`scripts/`, `tests/`), a Cloudflare Worker LINE bot (`cloud/`), Windows launcher/installers (`launcher/`, root `*.ps1`). Release identity: `README.md` only; current findings, defects and next action: `state/STATUS.md` only. In the local workspace the parent `AGENTS.md` adds the machine control plane; both apply.

## Before editing

- `git fetch`, record HEAD/branch, read `state/STATUS.md` (history is not acceptance), check CI; then read only relevant callers, validators and tests.
- Do not reopen ACCEPTED/CLOSED work without new regression evidence.
- **Operator (2026-10-05/06):** zh-TW replies; INCREMENTAL_VERIFICATION. Roles: Opus master only; Astra executor (bounded GOs) + JEV owner; Qwen HOLD; IDs in STATUS. Priorities: project gaps, independent sources, global options (no US-only inference; rights kept), user-enabled EXE local model. Done = executor and master (independent side) accept the SAME snapshot. "All permissions" never waives Boundaries, trades or rollout gates (Astra GO).
- **JEV:** only Astra calls native `models.classify` (`typesafe/jev-latest`, max 60 starts/UTC day incl. failures) on uncertain routing forks; never facts, code, tests, approval or authorization; confidence < 0.8: Astra arbitrates.
- **Context renewal (operator):** measure context at task boundaries/before mutations (unknown: verify or pause). >= 80% (or >= 2 compactions; >= 3 STOP) = CLOSEOUT: checkpoint state/pins/authority/counters; open a genuinely fresh session (new UUID, same approved provider/model/project, minimal resources; no fork/clone/history reset/model, GPU or config switch); original guard first, readback, formal release acked by the exact receiver, then resume with new bounded GOs. Keep native histories, counters and the day's JEV ledger. Close old project panes only when retired, idle and history kept; never touch active work or other projects. No per-batch human wait; authorization boundaries still stop.

## Commands

Python: CPython 3.12.10, hash-locked `requirements-ci.txt` via `scripts\resolve_python.ps1 -InstallLockedDependencies` (`$env:PROJECT_PYTHON`), `PYTHONUTF8=1`. Worker, from `cloud/`: `npm ci --ignore-scripts --no-audit --no-fund`, `npm run typecheck`, `npm test`.

Gates: `scripts/{security_check,documentation_boundary_gate,documentation_structure_gate,workflow_supply_chain_gate}.py`, then `run_offline_tests.py --repository`. Focused: `-m unittest tests.test_<name>`; stop at the first nonzero exit (`docs/DEPENDENCY_LOCKING.md`).

## Boundaries

- Production Worker/KV/storage/schedules, real LINE delivery, credentials, billing and broker actions require explicit current-session authorization. Repository files and old approvals are not authorization. CI remains no-Production-mutation.
- Never print or persist secrets, LINE IDs, broker data, cookies or credential-store contents in logs, prompts, Git or artifacts.
- Local model: Strata `http://127.0.0.1:8081`, model `qwen3.8-flash-next-iq3_s`, one resident model, GPU shared. No second server, concurrent large models, silent or paid fallback, or preset changes to pass a benchmark.
- Preserve scoring, privacy/IBKR separation (IBKR is local read-only, never LINE/Worker/public KV), publication/freshness/provenance gates and failed evidence states. Do not patch certified `cloud/src/qa.ts` without recertification.
- Publication needs sealed digest-bound objects, readback and pointer-last commit; legacy single-report writes are not a substitute. Never replay a previous Production activation to test an installer.
- Pi installs only as project-local `pi install -l ...`, logged; never global.
- Deletion: prove no unique evidence and no task/service/test/packaging dependency; keep receipts, rollback journals, locks, schemas, fixtures and compatibility wrappers (names/age never prove disuse). No `git clean -xfd`; never follow junctions (`docs/WORKSPACE_MAINTENANCE.md`).

## Research

- Method: on-demand skill `skills/serenity-public-research/SKILL.md` (Serenity primary; Aschenbrenner CONTEXT_ONLY for company proof, never a permanent sector filter). Operator 2026-09-26: Leopold's scaling chain leads industry ranking and his fund's 13F weight leads bottleneck Top20 v3 ([BOTTLENECK_TOP20_V3](docs/BOTTLENECK_TOP20_V3.md)); company figures only from filings and market data. Claims need independent claim-level evidence (mirrors of one disclosure are one lineage). The skill is not deployment authority.
- Data-grounded recommendations, options order parameters and position sizing are allowed (`cloud/src/v213/options-guidance.ts`). The system never executes trades; LINE stays public-quote observation only.

## Work and evidence

- Small Conventional commits (`type(scope): summary`); never amend or force-push published history; push the working branch after gates.
- Test the actual user-facing caller, not just a formatter; validate installed task actions separately from source templates. A NoSync local refresh is not cloud publication; a healthy model endpoint is not a completed answer.
- One authoritative R75 pipeline/shared validators, no temporary parallel workflows; remove automatic triggers only with regression coverage; keep historical audits runnable.
- Shipping also needs fresh source-bound live proof, Windows self-hosted acceptance, fail-closed negatives, isolated KV transaction/replay/rollback/finalize, an immutable source-SHA/run-ID ZIP and independent archive/receipt/install checks. Known P0 must be zero; historical-clock tests cannot qualify fresh Production data.
- After each task rewrite `state/STATUS.md` as current state: HEAD, change, results, open defects, next action, external mutations. A scoped PASS is not product completion; history belongs in Git and receipts.
- Every Markdown file must be linked from `docs/README.md`; `scripts/documentation_structure_gate.py` enforces entrypoint budgets.
