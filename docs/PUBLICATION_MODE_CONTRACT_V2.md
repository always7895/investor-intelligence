# Publication-mode contract v2 (C1 parity)

Contract file: `config/v213-r75-publication-mode-v2.json` (id `v213-r75-publication-mode-v2`, supersedes `v213-r75-publication-mode-v1`). `config/v213-r75-publication-mode-v1.json` stays byte-identical as history: the committed live receipts `state/r75-qa-live-*.json` pin its hash and still refer to exactly that content.

## What changed

v1 trusted the saved per-row counts (`claim_relevant_independent_families`, `..._domains`, `..._primary_sources`, `claim_dated_evidence_ratio`). The producer already recounted before sealing (factor guard and activation bundle builder, one shared module), but the two consumers did not. v2 makes the consumers recount as well, as defence in depth against a buggy or forged producer:

| Consumer | Where |
| --- | --- |
| Install preflight | `scripts/v213_r75_activation_preflight.py`, reusing `claim_lineage_structurally_qualified` in `scripts/claim_lineage_qualification.py` |
| Worker | `cloud/src/v213/publication-mode.ts`, using `cloud/src/v213/claim-recount.ts`, a port of `compute_independent_lineages` in `scripts/source_observation.py` |

The saved-metric checks stay first and unchanged; the recount runs after them, for `EVIDENCE_QUALIFIED` rows only. LIMITED rows are never recounted (the producer emits a non-qualifying audit for them).

## Rules (structural recount, no time terms)

For every `EVIDENCE_QUALIFIED` row, recompute from `record.claim_evidence_audit`:

1. `schema_version == 2` and `all_material_claims_supported === true`.
2. `claims` is a non-empty list; each claim has a unique non-empty `claim_id`, `status == "SUPPORTED"`, `high_confidence_eligible === true`, an empty or absent `conflict_set`, and a list `evidence_ids`.
3. The evidence bound to a claim is the `evidence` rows with `admitted === true`, `freshness == "CURRENT"`, `observation_id` in the claim's `evidence_ids`, and the claim id in the row's `claim_ids`.
4. `compute_independent_lineages(bound) >= thresholds.min_evidence_claim_families`. This value equals the producer policy key `minimum_claim_source_families_per_ticker` (`config/v213-serenity-evidence-freshness-policy.json`); the contract states the equality (`claim_recount.families_threshold_equals_producer_policy_minimum`) and a test checks it.
5. Every bound row's `value` equals the claim's `value` (Python `==` semantics).
6. Any failure, missing field or wrong type refuses the row: Worker `V213_ACTIVATION_EVIDENCE_QUALIFIED_INVALID`, preflight `PreflightError`.

Not part of the recount: `validated_at`, `valid_until`, per-evidence `valid_until`, clock skew and the producer's 30-minute reserve. The Worker and preflight run up to `max_bundle_age_seconds` (7200 s) after the build while an audit may expire two hours after validation, so judging expiry at consumer time could refuse a bundle the builder legitimately accepted. Expiry stays a producer concern (guard reserve, builder wall clock); consumers still enforce bundle age. Residual risk: a forged bundle carrying an already expired audit passes the structural recount. Anchoring the time terms at the build instant would need a new bundle field and is a later hardening.

## Parity vectors

`tests/fixtures/v213-r75-publication-mode/claim-recount-vectors.json` is the single vector file. `tests/test_v213_publication_mode_claim_recount.py` runs it against the Python implementation and `cloud/test/v213-claim-recount.test.ts` against the Worker port; both also run every vector through the real consumer (`validate_bundle`, `validateR75PublicationModes`). Expectations are authored literals, never computed by either implementation.

`tests/fixtures/make_v213_r75_publication_mode_v2_fixtures.py` regenerates the vectors and the two bundle fixtures (`mixed.json`, `all-limited.json`) deterministically: it re-serialises the embedded JSON strings and recomputes `bundle.sha256` and `contract_sha256`. `--check` writes nothing.

## Contract hash and deploy

The Worker reports `publication_contract_sha256` (canonical JSON of the contract) at `/v213/readiness`; the installer pins the id and hash in `scripts/v213_edge_readiness.ps1`. The two must move together: a v2 Worker with a v1 installer pin (or the reverse) is refused with `V213_READINESS_SCHEMA_OR_CONTRACT_MISMATCH`. Compute the hash with the repository function:

```text
python -I scripts/v213_r75_activation_preflight.py --print-contract-hash
```

`scripts/verify_r75_qa_evidence.py` accepts a readiness proof by contract id: v1 receipts stay verifiable as history, new receipts must carry the v2 hash.
