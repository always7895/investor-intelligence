# KV deployment preflight

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

Design choice: **reader contract `v213-reader-replay-v4`** (not an additive probe under v3). The replay result gains `guidance_machine_probe`, computed by `cloud/test/helpers/guidance-machine-probe.ts` (`probeGuidanceMachine`) and written by `cloud/test/live-kv-replay.test.ts`:

| Value | Meaning |
| --- | --- |
| `ABSENT` | The pinned sealed view names no machine binding (every non-machine tier, or a run that is not a sealed snapshot). |
| `ADMITTED` | `loadBottleneckV3(view, { guidanceMachineEnabled: true })` resolved the binding against the sealed report through the real loader. |
| `REFUSED` | The sealed index names the binding but the machine loader cannot read it (altered, missing, replayed or re-bound blob). |

Why a version bump: an absent-tolerant expectation under v3 would let a v3 reader (which writes no probe) pass a machine run unchecked, which is the hole being closed. The version is pinned in four places that move together: `READER_CONTRACT_VERSION` in `scripts/stage_sealed_replay.py` and `cloud/test/live-kv-replay.test.ts`, the `Test-ReplayAcceptance` check in `scripts/deploy_production_gate.ps1`, and the test pins. The staged layout (`index.json` plus `k<N>.txt`) is unchanged, so the committed F06 fixture needs no regeneration.

Gate rules:

- `stage_sealed_replay.expectations(..., machine=True)` is used when the run's seal lists the binding key; it adds `GUIDANCE_MACHINE_BINDING`, which requires `ADMITTED`. Without the binding in the seal the expectation list is exactly the previous one.
- `deploy_production_gate.ps1` (`-Phase post`, replay of the live snapshot) refuses a replay whose probe is `REFUSED` with `GUIDANCE_MACHINE_BINDING`; `ABSENT` is accepted because the live tier may be non-machine. The post gate has no notion of the intended tier, so the pre-KV gate (driven by the seal) is the authority for machine runs. The probe value is recorded in the acceptance artifact (`replay.guidanceMachineProbe`).
- The probe reads the pinned public view only, at the real clock; it never reads the tenant-private or security namespaces. Machine publication stays opt-in (`-GuidanceMachinePublicationEnabled`), so no current output changes. Installing the changed gate on the machine belongs to the Production rollout.
