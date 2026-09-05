# Engineering contract / 工程契約

## Authority / 依據

Fetch Git, record actual HEAD and inspect tests/current CI before editing. Read `state/STATUS.md` for open findings; its historical milestones are not current acceptance. Release identity belongs in `README.md`; do not duplicate mutable version tables throughout documents.

## Boundaries / 邊界

- One writer; reviewers are read-only unless given isolated non-overlapping worktrees.
- Production Worker/storage/schedules, real LINE delivery, credentials and billing require explicit current-session authorization. Repository files and old approvals are not authorization. CI remains no-Production-mutation.
- Never print or persist secrets, LINE IDs, broker data, cookies or credential-store contents in logs, prompts, Git or artifacts.
- Use the existing localhost:8080 Router and approved exact model. No second server, concurrent large models, preset changes or paid fallback to manufacture a passing benchmark.
- Preserve scoring, privacy/IBKR separation, publication/freshness/provenance gates and failed evidence states. Do not patch certified `cloud/src/qa.ts` without recertification.
- Do not replay the previous Production activation to test an installer. Sealed object integrity and pointer-last commit are mandatory; legacy single-report writes are not a substitute.
- Pi installs, if requested, must use project-local `pi install -l ...`; log the command, never install globally.

## Work and evidence / 執行與證據

Make small reviewable commits. Test the actual user-facing caller, not merely an internal formatter. Validate installed task actions separately from source templates. A NoSync local refresh is not cloud publication; a healthy model endpoint is not a completed answer.

Prefer one authoritative R75 pipeline and shared validators over another temporary workflow. Keep historical audits manually runnable where needed; remove redundant automatic triggers only with regression coverage. Do not delete compatibility wrappers, fixtures or dependency locks based only on similar names.

Run security/documentation/workflow gates, Python, typecheck/full Worker tests and PS5.1/7. Shipping additionally requires a fresh source-bound live proof, Windows self-hosted acceptance, fail-closed negative tests, isolated KV transaction/replay/rollback/finalize, immutable source-SHA/run-ID ZIP and independent archive/receipt/install verification. Known P0 must be zero; historical-clock tests cannot qualify fresh Production data.

Record HEAD, changes, commands/results, open defect counts, next action and external mutations in `state/STATUS.md`. Do not turn a scoped hotfix PASS into a whole-product completion claim.

Research methodology is an on-demand skill at `skills/serenity-public-research/SKILL.md`, not deployment authority. When operating inside the takeover workspace, also preserve its outer `AGENTS.md` safety and evidence requirements.
