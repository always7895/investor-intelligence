# Local Runtime Independence V1

100% local AI at the LOCAL v213 gateway — `$0` paid inference, no cloud fallback.
This is a LOCAL-gateway capability, not a Cloudflare Worker change.

## Roles and single config

Two roles, one runtime config (`config/local-runtime-independence-v1.json`):

- **PRIMARY_REASONER** — the local reasoner. The served model is auto-detected at run time, so a model or port change
  needs no config edit (mechanism and limits: [Local model auto-detection](MODEL_RUNTIME_MIGRATION.md#local-model-auto-detection)).
  `primary_reasoner.model` is empty by design (`model_selection=FOLLOW_DETECTED`) and `base_url`
  (`http://127.0.0.1:8080/v1`) is only a loopback first-probe hint; a model id set there is a non-binding preference that never
  pins or blocks a different served model. The gateway refuses to start without `II_LOCAL_LLM_MODEL` (the
  bridge always sets it to the served id); a handler without a selected id answers 503 `SELECTED_MODEL_NOT_CONFIGURED` and forwards nothing.
  The explicit runtime binding plus model profile is the only exact pin and rejects any other model. The server uses `--max-concurrency 1`; local tasks may delay LINE answers while sharing it.
  No live qualification is claimed here.
- **DECISION_ROUTER** — the legacy decision role remains retired in the shipped
  config (`decision_router.retired: true`). Source qualification alone controls
  the gate; no decider approval is required.

Strict hard flags (JSON boolean tokens; numeric `1`/`0` rejected):
`LOCAL_AI_ONLY=true`, `PAID_INFERENCE_ALLOWED=false`, `CLOUD_AI_FALLBACK=false`.
Missing/invalid flags fail closed (no healthy default).

## Observed guards (pre-generation, both lanes)

The v213 gateway runs these BEFORE any reasoner product completion:

1. **Decision gate** — failed source evidence (CONFLICTED/STALE/UNAVAILABLE)
   denies via `source_qualification` without consulting the decider. With the
   shipped `decision_router.retired: true`, source qualification alone is
   sufficient — no decider approval is required for healthy evidence. (Legacy,
   non-retired configuration: healthy evidence additionally required an
   explicit decider approval.) The pre-generation gate result is reused for
   the `ii_decision` annotation (no CPU re-query after generation).
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
invalid fails closed. A decider confidence below 0.70 denies locally (never cloud).
The client also strictly validates the probability vector
(empty / wrong keys / bool / non-numeric / NaN / inf / out-of-range /
unnormalized / choice-confidence mismatch), tolerating legitimate 4dp
rounding. In the shipped retired configuration the decider is never consulted,
so this minimum applies only when a non-retired decision router is
configured.

## Failure behavior

Malformed, offline, low-confidence, or NOT_SUFFICIENT decisions return an
explicit **503 `REASONER_DECISION_DENIED`** (or the capability error) with
**zero reasoner product generation** — degraded/fail-closed, no cloud
fallback, no healthy default. In the shipped retired configuration only the
failed-source-qualification denial and the capability errors can fire; the
decider denial paths above are legacy (non-retired configuration only). The
natural-prose LINE reply format is unchanged; only the required structured
output/probe is validated.

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

Agent, pane and bootstrap tooling is **DEVELOPMENT_ONLY** orchestration; it is
NOT runtime prerequisites. Startup (`run_v213_local_llm_bridge_core*.ps1`)
requires no such tooling and no cloud-AI fallback.

## Current status

Current acceptance is recorded in [STATUS](../state/STATUS.md) and source-bound receipts. This local-development contract does not qualify a live model or authorize production, bootstrap, settings, or shared-process changes.
