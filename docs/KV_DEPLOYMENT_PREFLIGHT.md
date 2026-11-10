# KV deployment preflight

<!-- DOCS-R1 scope -->
> **Scope:** Technical reference; verify executable behavior against code and current source-bound evidence. Current acceptance and unresolved issues: [STATUS](../state/STATUS.md). The document itself does not authorize Production changes.
<!-- /DOCS-R1 scope -->

No deployment is performed during development. Before a future release can create or bind Cloudflare KV namespaces, six real IDs must be supplied outside Git and validated:

```text
CLOUDFLARE_PUBLIC_KV_NAMESPACE_ID
CLOUDFLARE_TENANT_PRIVATE_KV_NAMESPACE_ID
CLOUDFLARE_EPHEMERAL_SECURITY_KV_NAMESPACE_ID
CLOUDFLARE_PUBLIC_PREVIEW_KV_NAMESPACE_ID
CLOUDFLARE_TENANT_PRIVATE_PREVIEW_KV_NAMESPACE_ID
CLOUDFLARE_EPHEMERAL_SECURITY_PREVIEW_KV_NAMESPACE_ID
```

Run the release-only preflight:

```powershell
python scripts/validate_kv_namespace_ids.py --require-configured
```

The command never prints namespace values. It reports only missing labels, placeholder labels and groups of roles that accidentally reuse an ID.

A release must fail when:

- any label is absent;
- any value remains a placeholder;
- any production ID equals another production or preview ID;
- any preview ID equals another preview or production ID;
- the old combined namespace is selected for migration;
- conversation memory is enabled before Phase 8 deletion/race acceptance.

The public snapshot must be rebuilt into a fresh `PUBLIC_CACHE`. No data is copied from a legacy combined namespace. `TENANT_PRIVATE_CACHE` and `EPHEMERAL_SECURITY_CACHE` begin empty.

## Namespace roles and isolation

The Worker uses three independent namespaces:

- `PUBLIC_CACHE`: public reports, scores, source views, option snapshots, versioned manifests and `snapshot:current`.
- `TENANT_PRIVATE_CACHE`: encrypted, opt-in conversation memory and encrypted long-job results only.
- `EPHEMERAL_SECURITY_CACHE`: hashed webhook-deduplication claims and pseudonymous rate-limit counters only.

Non-negotiable boundaries:

- Public data never stores `tenant:*`, tenant identifiers, raw LINE identifiers, messages or account data; private data never stores public snapshots or shared rankings.
- Ephemeral security state stores no message text, answer text or raw external identifier.
- A tenant's HMAC-derived identifier is confined to `TENANT_PRIVATE_CACHE` and `EPHEMERAL_SECURITY_CACHE`; it never enters public data.
- The legacy `CACHE` binding is forbidden; generic private-JSON storage APIs are absent.
- Conversation memory is off by default for the first external-user release.
- The public publisher receives no private or ephemeral credentials. Public lookups never read tenant-private data; model context never reads option chains or another tenant's data, and may read only the current tenant's explicitly available encrypted conversation memory.
- Owner holdings, watchlists, account/broker data and local reports never enter any of the three namespaces.

## Pre-KV replay gate and the revenue-guidance machine binding

`scripts/stage_sealed_replay.py` replays a locally sealed run through the real Worker readers before any KV write. The machine tier (`--guidance-machine`) seals `v213:revenue-guidance-binding:v1` next to the Top20 v3 report, but the ordinary replay read the report without the machine opt-in and never touched the binding, so a broken binding could not fail the gate.

Design choice: **reader contract `v213-reader-replay-v5`**. It retains the v4 `guidance_machine_probe`, computed by `cloud/test/helpers/guidance-machine-probe.ts` (`probeGuidanceMachine`) and written by `cloud/test/live-kv-replay.test.ts`:

| Value | Meaning |
| --- | --- |
| `ABSENT` | The pinned sealed view names no machine binding (every non-machine tier, or a run that is not a sealed snapshot). |
| `ADMITTED` | `loadBottleneckV3(view, { guidanceMachineEnabled: true })` resolved the binding against the sealed report through the real loader. |
| `REFUSED` | No current machine admission: broken custody, or valid retained facts whose forecasts are explicitly withheld. The separate `guidance_machine_dated_facts_only` boolean distinguishes those cases; it never changes `REFUSED` into `ADMITTED`. |

Version v5 requires the exact verified `seal_sha256` and both identities: `run_id` is immutable eager-core/claim identity; `seal_run_id` is global pointer/seal identity. The real reader exposes audit-only `sealRunId`/`sealSha256`; rights wrappers preserve them without gifting custody. Ordinary roots have equal IDs; reused cores retain original authority and evidence clocks. The version moves together in the Python stage, actual Worker replay and PowerShell gate. The byte layout remains `index.json` plus `k<N>.txt`; committed historical F06 fixture bytes are unchanged.

Gate rules:

- Every tier requires exact global ID, core ID **and seal SHA**. Missing/wrong hashes fail even when both IDs match. Staged replay captures summary/map/pointer bytes before its subprocess, stages only that captured map, and rejects later source mutation without re-associating the result with new metadata.
- `fetch_live_public_snapshot.py` verifies the pointer-hashed root, every declared SHA/byte length and the exact pointer after copying. Payloads use `core_run_id`; for paired roots only the fixed `last_successful_pipeline_timestamp` control uses the global prefix and body exactly global `generated_at`. Legacy roots retain their old semantics; arbitrary key overrides are forbidden.
- Pre/post pointer age uses the verified copied liveness marker bound to the actual pointer ID and seal SHA, never old `public_data_as_of` or unverified `promoted_at`. Evidence dates remain unchanged. Post acceptance freezes copied IDs/SHA before the subprocess and requires the actual replay to echo that exact verified triple.
- A reused core may retain an originally valid legacy report beyond its configured age bound: `legacy_report_expired_refused` proves the actual legacy route refused, canonical original report time is expired, and global liveness is fresh. Only this explicit case skips legacy CARRIED row/LINE/broadcast freshness requirements; it exposes no fresh legacy rows and must not be broadcast-ready. Current v3 structural/rendering checks remain. New-core CARRIED runs retain their original checks; an explicit deployment record-count requirement is never waived.
- Machine binding publication still requires `ADMITTED`, except a verified reused core may carry `REFUSED` with actual `guidance_machine_dated_facts_only` evidence from the real loader. Forecasts remain unavailable, with the original dated-facts notice. Missing, corrupt or replayed bindings have no such evidence and still fail. No machine probe outcome names were added.
- The probes read the pinned public view at the real clock and never read tenant-private or security namespaces. Machine publication remains opt-in (`-GuidanceMachinePublicationEnabled`); these diagnostics do not enable it. Installing the changed gate belongs to the Production rollout.

Seal-root extensions are optional: `core_run_id` and `ranking_persisted_at` must appear together; the latter is the independent ranking publication clock, no later than global `generated_at`. A genuine ranking-only update may advance it and replace lazy ranking/binding bytes while retaining the original eager core; a market-only update retains it. `product_persisted_at`, when present, is a map containing only `market`, `prices` and/or `identity` UTC instants, each no later than `generated_at`; ranking-only assembly retains these product clocks unchanged. Both reuse paths retain the original core transaction, public-data timestamp, claim, approval and eager report bytes. Neither extension renews rights, capture or admission. Identity symbol/name/token readers enforce the original shard's eight-day hard age bound and 300-second future tolerance; options coverage independently retains its six-hour hard bound.
