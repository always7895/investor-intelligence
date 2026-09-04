# H5 v3 — Complete SEC Fetch and Transactional Source History

## Why this patch exists

The first Windows H5 v2 live run failed while validating AAOI's first 2026 Equity Distribution Agreement:

`required evidence not found: AAOI First EDA`

The official AAOI Q2 2026 filing does contain the required ATM section. The failure class was caused by the H5 shared fetch helper slicing the **raw inline-XBRL HTML** at 3,000,000 bytes before converting it to visible text. A late filing section can therefore be absent even though the request itself succeeded.

The same failed run also revealed a transactional issue: the Serenity source-history JSONL was appended before all H5 evidence gates had completed. The history remained a valid shadow-only hash chain, but a failed run should not create or modify persistent stage artifacts before success.

## v3 corrections

### 1. Complete bounded response fetch

H5 v3 streams the complete response up to a hard 24 MiB ceiling and only then converts the body to visible text. This preserves late SEC filing sections without permitting unbounded response growth.

### 2. More durable AAOI ATM anchors

The AAOI lineage parser uses dated legal actions and the full `Equity Distribution Agreement` phrase rather than depending on the short quoted label being near a raw-HTML byte position.

Expected lineage remains:

- 2026-02-26 — first EDA / $250m authorization;
- 2026-03-12 — Amendment No. 1, same program raised to $500m;
- 2026-04-02 — first ATM completed;
- 2026-05-14 — separate second EDA / $600m authorization.

An amendment or completion is not counted as a third financing program.

### 3. Transactional source history

H5 v3 validates the existing SHA-256 history chain, copies it into a temporary staging file, performs the entire H5 evidence-deepening operation against the staged copy, and atomically replaces the persistent history **only after all evidence and hard-dependency gates succeed**.

Therefore:

- an existing valid H5 v2 history can be reused;
- duplicate source IDs are not appended again;
- a later H5 failure does not mutate the persistent history;
- a tampered chain fails closed before the evidence run.

## Fidelity boundaries unchanged

This patch does not relax the core public-logic rules:

- Serenity source views are attributable public opinions, not factual dependency proof;
- disclosed qualified alternatives keep AXTI hard-dependency status unproven until effective substitute capacity is independently established;
- SIVE material equity issuance is distinguished from proven toxic financing;
- Soitec photonics architecture does not prove semi-monopoly status;
- no source-view record can create `SINGLE_SOURCE`, `SEMI_MONOPOLY`, `QUALIFICATION_CONSTRAINED`, or `CAPACITY_BOTTLENECK` by itself.

## Production boundary

H5 v3 remains shadow-only. It does not deploy the Worker, sync KV, alter LINE/Cloudflare credentials, modify schedules, or replace Production ranking output.
