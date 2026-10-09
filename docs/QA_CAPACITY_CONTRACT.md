# QA Capacity Contract V1 (2026-09-21; base HEAD 84133f8)

## Purpose

Development-only cooperative QA capacity evidence for Windows-native observation.
NOT R75 release acceptance. NOT a machine-wide GPU isolation mechanism.
Native origin: Windows-development environment. Legacy schemas 1/2 and profiles/callers unchanged.

## API (fixture/root; no CLI)

### CapacityLease

- `CapacityLease(root, binding, ttl_s=60, process_probe=process_identity)` — creates/opens a lease at a canonical root directory.
- `lease.acquire() -> metadata` — exclusive cooperative lock guard (flock/byte-range); returns lease metadata.
- `lease.check(nonce) -> metadata` — verifies nonce ownership; returns lease metadata.
- `lease.release(nonce) -> release_event` — explicit release with nonce; returns release event.
- `lease.close()` — drops handle only; leaves residual metadata. NOT a successful release.

### recover_dead (standalone function)

- `recover_dead(root, expected_nonce, expected_metadata_sha256, process_probe=process_identity)` — explicit dead-holder recovery; no silent take-over.
- Digest is actual owner-file bytes. Unknown/live holder refuses.
- This is a STANDALONE function, not a lease method.

### run_window

- `run_window(lease, probe, work, *, interval_s=1, max_gap_s=2, timeout_s=60)` — runs a cooperative observation window.
- `probe() -> raw observation` — caller-supplied sampler returning a raw read-only observation.
- `work(cancel_event)` — caller-supplied work callable that receives a cancellation EVENT (not an observation).

### run_native_window

- `run_native_window(binding, work, *, interval_s=2, max_gap_s=5, timeout_s=60, ttl_s=60)` — runs a native observation window with fixed canonical root and real collector.
- No caller root/probe override.

### verify_receipt

- `verify_receipt(receipt: dict, binding: dict) -> freshly computed summary` — independent strict replay of a receipt.
- Raises `CapacityError` for invalid/contradictory evidence.
- Honest UNQUALIFIED receipt may verify successfully.

## Canonical Lease Root

Fixed local-user path: `%LOCALAPPDATA%/InvestorIntelligence/qa-capacity-v1`.
Not machine-global. Not a hardware-enforcement mechanism. Not configurable. Not a deployment path.

## Native Source Gate

Before any observation:
1. Source HEAD matches exact expected commit.
2. Working tree is CLEAN TRACKED (unrelated untracked files are not this check).
3. Module is present in HEAD (not added after the fact).

All three must pass. Failure raises `CapacityError` BEFORE work / no qualifying receipt.
Do not claim the gate always emits UNQUALIFIED; it is a hard failure, not a soft flag.

## Read-Only Observations (sampled; not machine-wide)

- native 5000/v1/model — served model identity.
- service/PID/birth/hash — process identity and creation time.
- client/Herdr/NVIDIA — client and GPU driver observations.

These are point-in-time samples. No OS/driver machine-wide prevention claim.

## Cooperative Kernel-Lock Enforcement

- Lock is cooperative: the holder must check and release.
- Enforcement via kernel byte-range/flock; no OS-level machine-wide exclusion.
- No models_max/catalog/singleton fiction.
- TTL bounded; nonce bound to owner birth.
- Incomplete/unknown probe = failure (fail-closed).
- Chronology/lease-event hash linkage ensures ordering integrity.

## Summary Fields (EXACT)

- `LEASE_HELD` (bool)
- `MODEL_IDENTITY_VERIFIED` (bool)
- `SERVICE_IDENTITY_VERIFIED` (bool)
- `GPU_CONFLICT_OBSERVED` (bool)
- `TABBY_CONFLICT_OBSERVED` (bool)
- `MONITOR_COMPLETE` (bool)
- `QWEN_CONFLICT_OBSERVED` (bool)
- `lease_released` (bool)
- `CAPACITY_EVIDENCE` ('QUALIFIED' | 'UNQUALIFIED')
- `reasons` (list)

No other summary fields exist. Do not invent qualified/tree_clean/module_in_head/model_verified/observation_count/unexpected_records/unqualified_reason/receipt_hash/etc.

## Receipt Structure

Top-level receipt contains:
- `kind` = 'qa-capacity-cooperative-v1'
- `binding`
- lease metadata
- config
- work times
- raw chained samples
- events
- summary
- digest

Native wrapper adds:
- `origin` = 'WINDOWS_NATIVE_DEVELOPMENT'
- `source_module_sha256`

Do not invent native source boolean fields.

## Hash Semantics

Hashes detect inconsistent evidence between samples.
NOT a defense against:
- Malicious collector/admin forgery.
- Events occurring between samples.

## WDDM C+G Ambiguity

Current host WDDM C+G ambiguity MUST fail (UNQUALIFIED).
No allowlisting GUI names to achieve green status.

## JEV / External Judge

No JEV runtime dependency. External judge is development-only.

## Evidence

- Full qualification (all 14 gates exit 0): Python 1864 OK/424.858s; focused 125/6.583s; Worker 869 pass/1 skip; typecheck, security, both doc gates, workflow, compile/JSON, PS5.1/7, diff pass.
- Receipt: `../../audit-runtime/qa-capacity-full-gates-02-84133/qualification-01/gate-receipt.json`.
- Earlier full attempt failed only missing doc-index link; failure retained, complete suite rerun after fix. Code/test hashes unchanged after full qualification.
- Actual read-only host observation: model+service verified, 28 unexpected compute-capable C+G observations => UNQUALIFIED.
- 28 observations are NOT proof of 28 other models.
- This snapshot is NOT a qualifying window.
- Native positive/live QA NOT established.

## Status

- Full gates: PASS (all 14 exit 0); documentation-only refresh; final docs gates rerun separately.
- Final checkpoint acceptance: PENDING targeted native proof (run_native_window negative proof requires exact committed source).
- QA backend migration: pending independent capacity acceptance.
- Closure review: ACCEPT_SCOPED (5 findings closed). JEV confidence 0.72 BELOW 0.85 material gate; independent contract acceptance NOT complete.
- LIVE_PROOF_STALE: remains separate.
- DEVELOPMENT_COMPLETE = false; FINAL_RELEASE_COMPLETE = false.
- No Production/LINE/KV/Worker/schedule/credential/billing/broker/settings/model/service mutations.
- Global P0 count: not re-audited. Do not claim global P0=0.