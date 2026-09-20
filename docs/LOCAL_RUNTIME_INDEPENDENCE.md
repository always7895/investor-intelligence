# Local Runtime Independence V1

100% local AI at the LOCAL v213 gateway — `$0` paid inference, no cloud fallback.
This is a LOCAL-gateway capability, not a Cloudflare Worker change.

## Roles and single config

Two roles, one runtime config (`config/local-runtime-independence-v1.json`):

- **PRIMARY_REASONER** — the local reasoner (default `http://127.0.0.1:5000/v1`,
  exact `Qwen3.8-27B-EXL3-5.5bpw-v2`).
- **DECISION_ROUTER** — the existing local Mapika CPU sidecar
  (`Mapika-decider-2b-v9`; `alias_diagnostic_only: decider-v8`).

Strict hard flags (JSON boolean tokens; numeric `1`/`0` rejected):
`LOCAL_AI_ONLY=true`, `PAID_INFERENCE_ALLOWED=false`, `CLOUD_AI_FALLBACK=false`.
Missing/invalid flags fail closed (no healthy default).

## Observed guards (pre-generation, both lanes)

The v213 gateway runs these BEFORE any reasoner product completion:

1. **Decision gate** — failed source evidence (CONFLICTED/STALE/UNAVAILABLE)
   denies via `source_qualification` without consulting the decider; healthy
   evidence requires an explicit decider approval. The pre-generation gate
   result is reused for the `ii_decision` annotation (no CPU re-query after
   generation).
2. **Served-context capability** — observed from the actual served metadata
   API (`/v1/model` → `parameters.max_seq_len`), compared to the resolved
   canonical identity. Missing/mismatched evidence → `CAPABILITY_UNKNOWN`
   (never assumed-healthy from a model name or configured minimum).
3. **Structured-JSON probe** (both lanes) — a bounded standard
   OpenAI-compatible probe (`response_format: json_object` + exact probe
   prompt, no bespoke test flag). Malformed/NaN/Infinity JSON fails closed.

`capability_report` says `READY` only when BOTH the required context and the
required JSON evidence pass; unknown/failed JSON cannot appear healthy.

## `min_decision_confidence` (newly declared)

`capability_requirements.min_decision_confidence = 0.70` is a **newly declared
backend routing minimum** — NOT a pre-existing value and NOT a source/scoring/
admission threshold. Strict finite numeric 0..1 (not bool/string); missing or
invalid fails closed. A decider confidence below 0.70 denies locally (never
Astra, never cloud). The client also strictly validates the probability vector
(empty / wrong keys / bool / non-numeric / NaN / inf / out-of-range /
unnormalized / choice-confidence mismatch), tolerating legitimate 4dp rounding.

## Failure behavior

Malformed, offline, low-confidence, or NOT_SUFFICIENT decisions return an
explicit **503 `REASONER_DECISION_DENIED`** (or the capability error) with
**zero reasoner product generation** — degraded/fail-closed, no Astra, no cloud
fallback, no healthy default. The natural-prose LINE reply format is unchanged;
only the required structured output/probe is validated.

## Replacement semantics

Swapping the reasoner/decider = change the config endpoint/identity + a
compatible contract + restart the gateway (the decider client is cached). No
business model-name compatibility branches. Active authority:
`V213_MODEL_PROFILE_JSON` (the profile model) takes precedence over the legacy
`II_LOCAL_LLM_MODEL` selection when set (the profile test proves it overrides
an ignored legacy model). Legacy overrides: `II_LLAMA_BASE_URL` (reasoner base)
and `II_LOCAL_LLM_MODEL` (selected model) take precedence over the config when
set. Replacement requires a compatible profile/config and qualification — no
business rewrite.

## Development-only tooling

Pi / Herdr / Astra / bootstrap are **DEVELOPMENT_ONLY** orchestration — they are
NOT runtime prerequisites. Startup (`run_v213_local_llm_bridge_core*.ps1`)
requires no Pi/Herdr/Astra/cloud-AI fallback.

## Evidence (linked, not repeated)

- `audit-runtime/local-runtime-independence-v1/python-full-utf8-retry.log` —
  1627 PASS (395.341s), 3 skips, 0 outer/blocked; Worker 869 PASS 1 skip +
  typecheck PASS; four documentation/security/workflow gates + compile +
  diffcheck PASS; PS 5.1.26100.9444 and 7.6.6 both present (all-tracked-script
  parse in each host PASS). Process-only `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8`
  (not global settings or market-builder changes).
- `audit-runtime/local-runtime-independence-v1/python-full-current.log`
  (preserved failed) — old profile transport/prerequisites + Windows
  readerthread UTF8/CP950 mismatch (root cause of the retry).
- `audit-runtime/local-runtime-independence-v1/contract-edges-focused-2.log` —
  66/66 PASS (57.773s), zero outer/blocked; includes 14 archive cases.
- `audit-runtime/local-runtime-independence-v1/live-compatibility-after-edges.log`
  — strict real CPU READY `.9842`; actual resident exact-v2 `/v1/model` context
  262144 and actual extractor 262144; ONE standard structured-JSON probe True.
  Harmless backend compatibility only — NOT a production market answer / LINE /
  live publication / full-release proof.
- `audit-runtime/local-runtime-independence-v1/python-full-final.log` — full
  1628 PASS 395.568s / 3 skip / 0 outside; `both-lane-json-focused-3.log` 90
  PASS 114.229s; `live-canonical-probe-final.log` current canonical probe PASS
  262144 + source hashes (development-only). Earlier 1627 run is historical
  (prior to the both-lane fix), not latest.

## Release status (LOCAL_DEVELOPMENT_GATES_PASS; NOT final acceptance)

- Verification base `977057d`. **NINE** runtime/config/test paths:
  `scripts/v213_local_llm_gateway.py`, `scripts/v213_decision_backend_client.py`,
  `scripts/v212_local_llm_gateway.py` (transport seam),
  `config/local-runtime-independence-v1.json`,
  `tests/test_local_runtime_independence.py`,
  `tests/test_v213_r75_gateway_process.py`,
  `scripts/verify_v213_r75_free_relay_hotfix.py`,
  `tests/test_v213_free_relay_package_payload.py`,
  `tests/test_v213_model_profile.py` (minimal regression fixture), plus
  `AGENTS.md`/`README.md`/`state/STATUS.md` docs.
- Status **LOCAL_DEVELOPMENT_GATES_PASS** (focused 23 PASS 55.004s 0 blocked
  before full retry; full retry 1627 PASS). Scoped acceptance/commit PENDING;
  no `FINAL_RELEASE_COMPLETE` / Production claim. CI at `977057d` SKIPPED, not
  PASS.
- CRLF_STAGING_BLOCKER_V1 resolved: exact root cause was 35 CRLF lines in the
  new hand-maintained UTF8/no-BOM config entering the index unchanged (no
  applicable text/EOL attribute; observed `core.autocrlf=false`); same-class
  maintained JSON uses LF. One deterministic Qwen byte conversion removed only
  35 CR (1025→990 bytes); parsed JSON and all other bytes equal; no attribute /
  Git-config / generator change. First two unsuccessful EOL rewrite attempts
  retained as NON-PASS, not accepted proof. Focused 48 PASS 52.689s / 0 outside;
  four gates and both diffchecks PASS. Newly tracked fixture's explicit `TEST_`
  marker fixed the scanner finding without changing runtime / assertions /
  scanner. Mapika ACCEPT_COMMIT .9720 applies local development only; no
  Production / bootstrap / settings mutation.
- **Release blocker (blocked/deferred, separate):** the historical PS
  changed-path allowlist is stale for already-accepted paths + this new work;
  not broadened / baseline-waived. Still needed: fresh source-bound release
  proof, Windows self-hosted acceptance, immutable archive + install gates.
- Bootstrap **PAUSED** — stash `14097451040a0ff3f2d0cf3025bd3368e7d66960`;
  independent 9-worktree + 9 index hashes verified, TWO parents (old
  absent-parent receipt wrong, preserved). Settings unchanged, `/new` 0. No
  restore/drop/resume.