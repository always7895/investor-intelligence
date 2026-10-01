# Current state / 目前狀態

Updated 2026-10-01 by Gemini (active writer for STATUS correction under current-session operator override; prior 7 code/test files authored by Claude Code `claude-bridge/claude-sonnet-5-5`; identity verified via PI_PROVIDER/PI_MODEL). Earlier text: `git show 9e00f3b:state/STATUS.md` (OPTIONS-GLOBAL-01 handoff); older: `git show 4c8eb3e:state/STATUS.md`, `b9a05c4`, `e049261` (before rollout v9), `902d893`, `b0860c9`, `ca571aa`, `06a7f28`, `4be0888`, `3ac39a1` (full production record), `git show 38860e7:state/STATUS.md`, `0f5358b` (V12). Release identity stays in `README.md`. Root and source `AGENTS.md` override older control-plane text in any history.

## Identity

- Branch `fix/options-provenance-audit`, base HEAD `9e00f3bee23ad7462ad6d6721f10e73b4d2fc701` (upstream identical). Source CI on this branch ends COMPLETED_SKIPPED (run 36710149323), not PASS; non-release-qualified (LOCAL_SOURCE_CHECKOUT). DEVELOPMENT_COMPLETE=false; FINAL_RELEASE_COMPLETE=false; live fix NOT proven.
- Production RECORDED identity `e049261` (rollout v9): not live-verified this session, no authorization, no external mutation. The new commit hash is not pre-written: base + the immutable commit receipt pointer are the identity.

## OPTIONS-NONUS-02 — source-only non-US covered-call repair (integrated working tree, NOT committed)

Closed prior lane: OPTIONS-GLOBAL-01 (source `9e00f3b`, CI SKIPPED) stays CLOSED; not reopened.

Scope (8 paths total: the 7 below + this file): `scripts/build_market_quotes_options.py`, `cloud/src/v213/rich-menu.ts`, `tests/test_build_market_quotes_options.py`, `tests/fixtures/options_nonus_publisher_cases.py`, `tests/test_options_nonus_bridge.py`, `cloud/test/fixtures/options-nonus-publisher.json`, `cloud/test/v213-options-nonus.test.ts`. Immutable: `cloud/src/qa.ts` (SHA256 `0107ACA6…681EB2`), accepted readers/sealer/validator, prior options fixtures, ADR map and config.

Accepted (writer `claude-sonnet-5-5` + Astra independent, same 7 bytes, r6): patch `proposal-r6-options-nonus.patch` SHA256 `04472532…DAE3`, producer `C212C554…361F`; Astra review SHA256 `00324E14…3984`. Evidence: `_archive/options-nonus-20260930/` (`sonnet-r6-proposal.result.txt`, `astra-proposal-r6-review.result.txt`, earlier r1–r5 receipts and reviews retained).

Semantics (Nordic/Stockholm + Yahoo):
- Typed currency evidence: contract, spot and search currency must be canonical SEK (share size 100) before a strategy; unknown/blank/conflicting currency is a source-scoped unavailable reason, never a minted SEK.
- Native identity: the contract symbol must encode the row's own root, year digit, call-month letter, exact decimal strike and (weekly) day with the only evidenced weekly tag `Y`; monthly `SIVE6J15.50` and weekly `VOLVB6J02Y280` are examples of two source forms, not a root whitelist. `_native_symbol_matches` validates the requested root generically; unsupported forms/series or mismatched roots are refused (unparseable, outside R/H, never a listing or no-listing claim). Unsupported identity precision is distinct from valid sub-cent recommendation precision. Strike, name and symbol decimals compare exactly (no float tolerance); contract size is compared exactly (`100.00` = 100, `100.000000000000000001` is not).
- Advice only for strikes the two-decimal display represents exactly (`_cent_exact`): a valid sub-cent chain stays in R/H and gets a bounded display-precision reason ONLY if unchanged economic filters would produce advice but cent-exact advice is empty. No-two-sided quote keeps the no-quote reason; economic miss keeps its existing reason. Mixed rows advise cent-exact strikes only; nothing is rounded or rewritten.
- Yahoo read chains without a valid two-sided quote get a truthful no-two-sided reason without a Nasdaq retry. Policy windows 3–14 weekly and 21–45 monthly days, quote health, retries, coverage guard (1/11 whole-candidate rejection keeps old bytes and age, 1/10 admits) and freshness are preserved.
- Limits: blank real contract currency and blank quotes (retained receipts) do not become tradeable; unsupported forms, series or mismatched roots are refused; no current quote availability or live symptom repair is claimed; broader strike presentation needs a separately authorized formatter recertification.

Focused evidence on the accepted bytes: Python 94 tests (producer, bridge with byte-for-byte fixture regeneration, market products), Worker 9 files / 152 tests, typecheck exit 0, independent Astra probes and closure probes (all in `astra-proposal-r6-*`).

## Gates

Full-gate outcome is an immutable receipt pointer, not a prediction: qualified prior run `_archive/options-nonus-20260930/options-nonus-full-gates-20260930T213523Z` (all 7 gates exit 0 on tree `9c9b60b06a8924f171b432c7e409b191f3b8da2e`; Python repo 3232 tests, Worker 1120 passed/2 skipped); first failed run `options-nonus-full-gates-20260930T210906Z` preserved. New STATUS bytes constitute a new eight-file candidate requiring fresh verification and manifest `gemini-status-v3-manifest.json` under `_archive/options-nonus-20260930/`. If a receipt is absent or has a nonzero exit, the tree is NOT gate-qualified. Required: `git diff --check` and `git diff --cached --check` exit 0. Commit/push needs separate coordinator authorization after Astra's independent review; source only, no live fix, no rollout authorization.

## ORDERS-V3-AUTOUPDATE-01 (B2a) — foundation NOT integrated, INACTIVE

B1 accepted and committed earlier. B2a helper, overlay seam, docs and tests live only in isolated worktrees (latest `sonnet-autoupdate-b2a-r5a5-20261001`, checkpoint A5, evidence `_archive/lane-orders-v3-autoupdate/b2a-20260930/`). Checkpoint A5 is dual-accepted (Astra review `astra-r5a5-cpA5-review.result.txt` ACCEPT), permitting coordinator CPB scheduling; not whole-B2a acceptance. Earlier checkpoints A–A4 remain frozen. Checkpoints B (traced evidence IO) and C (helper-clock safety), stale tests/docs, B2b callers/ownership/transport, B3, B4 and rollout are OPEN. Operational invocation stays disabled (`OPERATIONAL_INVOCATION_ENABLED=False`). Nothing of B2a is in the canonical tree.

## Control plane (root `AGENTS.md`, operator 2026-09-27)

- Operator 2026-10-01 session override: continuation execution delegated to Gemini/Qwen; Gemini active writer for this STATUS task under operator authorization; Claude Code remains parked/quota-blocked without model swap; prior accepted seven code/test files authored and dual-accepted by Sonnet+Astra remain historical fact; Qwen/ChatGPT lanes unused for this integration task. Astra (`openai-codex/gpt-6-astra`): master for contracts, independent acceptance, arbitration and go/no-go; read-only. Completion requires writer own acceptance plus Astra independent acceptance of the same fixed snapshot.
- Coordinator driver UNARMED (no restart); no R75 live-mutex caller was run.

## Open lanes (unchanged)

2. Source diversity: single for Japan fundamentals (EDINET key), Japan/Korea price shards, non-US consensus. 3. Orders without a forecast: 5351.TWO, SIVE.ST, POET, AXTI. 5. Report-age gates for carried reports and federation readers (certified `qa.ts` needs recertification); CI R75 route blocks release qualification. 17. LINE Q&A relay live since rollout v6. 18. Dilution shares_yoy fallback; four Yahoo listings DEFERRED. 19. Order forecast v2 live since rollout v6. Lane 19 CRDO-RPO-01 BLOCKED_INPUTS. DEFERRED_WITH_REASON: lanes 2, 3, 5; driver v3 A–D.

Closed (no reopening without regression evidence): lanes 1, 4, 6–13, 15, 16; Top20 T1–T11; O1/Case9/R3A; identity shadows; OPTIONS-GLOBAL-01.

## Boundary flags

NATIVE_EXECUTION_AUTHORIZED=false; CAPACITY_EVIDENCE=UNQUALIFIED; publication_eligible=false for candidates; global P0 NOT_REAUDITED. Serenity primary; Leopold Aschenbrenner CONTEXT_ONLY for company proof, leads the industry ranking since 2026-09-26 (operator). Production Worker/KV/schedules, real LINE delivery, credentials, billing and broker actions require explicit current-session authorization; repository files and old approvals are not authorization.

## Handoff

- Next: Astra independent integrated review of the new 8-file manifest and gate receipts; then coordinator authorization for commit/push of the working branch (no production). Then resume B2a CPB after coordinator scheduling.
- Operator: the plaintext Alpha Vantage note; whether a 6-month figure may ever be a labelled model estimate (currently 未揭露 when undisclosed).
- Tooling: worktrees in `_archive/project-audit-20260929/`; options evidence in `_archive/options-nonus-20260930/`.
