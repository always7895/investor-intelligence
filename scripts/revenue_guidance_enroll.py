"""Genuine first enrollment; source-only, no automatic activation or financial inputs."""
from __future__ import annotations

import hashlib
import json
import secrets
import struct
from datetime import datetime, timezone

import revenue_guidance as guidance
import revenue_guidance_auto_verify as verify
import revenue_guidance_overlay as overlay
import revenue_guidance_provisioner as provisioner
import revenue_guidance_revision as revision
import revenue_guidance_storage as storage
import revenue_guidance_windows as windows


def validate_initial_inputs(origin):
    """Protected, independently approved release captures; shared financial validators."""
    origin.check_live()
    bindings = {"config.json": "config/system-bottleneck-explosion-v1.json",
                "profiles.json": "config/revenue-guidance-extraction-profiles-v1.json",
                "registry.json": "config/revenue-guidance-v1.json",
                "approval.json": "config/revenue-guidance-approval-v1.json"}
    bindings.update({n: "scripts/" + n for n in overlay.IMPLEMENTATION_FILES})
    inputs = {n: origin.files[p] for n, p in bindings.items()}
    if any(hashlib.sha256(inputs[n]).hexdigest() != origin.policy["files"][p] for n, p in bindings.items()):
        raise provisioner.AuthorityUnavailable()
    moment = datetime.now(timezone.utc).replace(microsecond=0)
    config = json.loads(inputs["config.json"].decode("utf-8"))
    if type(config) is not dict or not config:
        raise ValueError("ENROLLMENT_CONFIG_INVALID")
    profiles = verify.validate_profiles(json.loads(inputs["profiles.json"].decode("utf-8")))
    registry = guidance.parse_registry(inputs["registry.json"])
    approval = guidance.parse_approval(inputs["approval.json"])
    if registry.get("status") != "OK" or not registry.get("issuers") or approval.get("status") != "OK":
        raise ValueError("ENROLLMENT_BASELINE_INVALID")
    if approval.get("registry_sha256") != hashlib.sha256(inputs["registry.json"]).hexdigest():
        raise ValueError("ENROLLMENT_APPROVAL_BINDING")
    # Check actual record digests and every operative timestamped decision, not
    # merely approval presence. Non-guidance records retain their normal validators.
    for symbol, record in registry["issuers"].items():
        guidance.validate_issuer_record(record, expected_symbol=symbol)
        if record.get("status") == "GUIDANCE" and guidance.check_reviewed_profile(
                symbol, record, approval, registry["sha256"], moment) is not None:
            raise ValueError("ENROLLMENT_APPROVAL_BINDING")
    for symbol in profiles:
        if symbol not in registry["issuers"]:
            raise ValueError("ENROLLMENT_PROFILE_BASELINE_MISSING")
    if not set(overlay.SUPPORTED_AUTO) & set(profiles):
        raise ValueError("ENROLLMENT_PROFILES_EMPTY")
    return inputs


def _control_file(issuer, name, data, role):
    """Exact NEW name, complete owned staging plan, flush/readback, then protect."""
    handle = issuer.create_staging_file(issuer.control_handle, name, len(data))
    for offset in range(0, len(data), windows.IO_CHUNK_BYTES):
        issuer.write_owned_chunk(handle, offset, data[offset:offset + windows.IO_CHUNK_BYTES])
    issuer.truncate_owned(handle, len(data))
    issuer.flush_owned(handle)
    issuer._verify_bytes(handle, data, reservation=handle._staging_reservation)
    windows.protect_issuer_object(handle, role)
    # Direct control initialization, never a namespace rename of journal/lock.
    # Reservation already consumed and actual bytes verified; unused credit is
    # NOT refunded or made global. Future in-place journal work reserves afresh.
    handle._staging_reservation = None
    handle._published = True
    handle._temporary_operation = None
    return handle


def _slot(bootstrap_id, sequence, state):
    envelope = {"schema": "guidance-provider-storage-v1", "bootstrap_id": bootstrap_id,
                "sequence": sequence, "state": storage._validate_p1_state(state)}
    payload = json.dumps(envelope, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(payload) > storage.JOURNAL_MAX_PAYLOAD:
        raise storage.StorageLeaseError("ENROLLMENT_JOURNAL_CAPACITY")
    header = struct.pack("<8sIIQII32s", b"INVALID!", 1, storage.JOURNAL_HEADER_SIZE, sequence, len(payload), 0,
                         hashlib.sha256(payload).digest())
    return header + payload + bytes(storage.JOURNAL_SLOT_SIZE - len(header) - len(payload))


def enroll(parent_remaining_ms, *, parent_deadline):
    """Explicit protected privileged entry only; publishes authority LAST.

    No repair of an existing root, rollback by guessed pathname, HTTP observations,
    fictional financial rows, caller-sealed snapshot or model-completion witness.
    A failed new root remains un-enrolled evidence; later operator cleanup is separate.
    """
    with storage.NativeIssuerContext(parent_remaining_ms, parent_deadline=parent_deadline) as issuer:
        with issuer.namespace_operation():
            inputs = issuer._initial_inputs
            for name, data in inputs.items():
                handle = _control_file(issuer, name, data, "input")
                issuer.close_owned(handle)
            issuer.coordination_handle = _control_file(issuer, "coordination.lock", b"\x00", "journal")
            # Allocate journal before anchor/snapshot construction; no valid state
            # is exposed until both actual adjacent slots have been completed.
            issuer.journal_handle = _control_file(issuer, "journal.dat", bytes(storage.JOURNAL_FILE_SIZE), "journal")
            anchor = issuer.bind_anchor({n: hashlib.sha256(b).hexdigest() for n, b in inputs.items()})
            for name in ("captures", "segments", "generations"):
                directory = issuer.create_directory(issuer.b1_handle, name)
                issuer.close_owned(directory)
            store = overlay.B1Store(issuer)
            store.write(("store_usage.json",), json.dumps({"bytes": 0, "files": 0, "pending": {}}).encode("utf-8"))
            store.write(("queue.json",), b'{"last_served":null}')
            # Empty MACHINE history is honest; no generated_at/check/financial facts.
            store.write(("receipts.json",), json.dumps({"schema": guidance.RELEASE_CHECKS_SCHEMA, "issuers": {}}).encode("utf-8"))
            initialized = datetime.now(timezone.utc).replace(microsecond=0)
            instant = initialized.strftime("%Y-%m-%dT%H:%M:%SZ")
            ident = overlay.identity(inputs["profiles.json"], inputs["registry.json"], inputs["approval.json"], store)
            generation = dict(ident, schema=overlay.STATE_SCHEMA,
                generation_id=initialized.strftime("%Y%m%dT%H%M%SZ-") + secrets.token_hex(6),
                parent=None, created_at=instant, issuers={}, detections={})
            digest = overlay.publish_generation(store, generation, None)
            snapshot = overlay.require_snapshot(overlay.load_effective_inputs(cutoff=initialized, state_root=store, state_required=True), initialized)
            if snapshot.condition != "PINNED" or snapshot.generation_sha256 != digest:
                raise storage.StorageLeaseError("ENROLLMENT_SNAPSHOT_UNAVAILABLE")
            input_revision = revision.compute_input_revision(snapshot)  # unchanged authoritative P1r5
            state = {"Schema": "guidance-provider-journal-v1", "StateRequired": True,
                     "InputRevision": input_revision, "PendingRevision": input_revision, "Intent": None}
            invalid = _slot(anchor.bootstrap_id, 0, state) + _slot(anchor.bootstrap_id, 1, state)
            issuer.budget.reserve_transition(write_bytes=len(invalid) + 16,
                read_bytes=len(invalid) + storage.JOURNAL_FILE_SIZE, mutations=6)
            windows.write_at(issuer.journal_handle, 0, invalid)
            windows.flush(issuer.journal_handle)
            if windows.read_at(issuer.journal_handle, 0, len(invalid)) != invalid:
                raise storage.StorageLeaseError("ENROLLMENT_JOURNAL_READBACK")
            for offset in (0, storage.JOURNAL_SLOT_SIZE):
                windows.write_at(issuer.journal_handle, offset, b"GJSLT001")
                windows.flush(issuer.journal_handle)
            both = issuer._get_both_slots(precharged=True)
            if any(slot.state != state for slot in both):
                raise storage.StorageLeaseError("ENROLLMENT_JOURNAL_READBACK")
            # Complete readback from new handles, not cache assertions.
            fresh = overlay.B1Store(issuer)
            readback = overlay.require_snapshot(overlay.load_effective_inputs(cutoff=initialized, state_root=fresh, state_required=True), initialized)
            if revision.compute_input_revision(readback) != input_revision:
                raise storage.StorageLeaseError("ENROLLMENT_REVISION_READBACK")
            for name, data in inputs.items():
                if fresh._control(name) != data:
                    raise storage.StorageLeaseError("ENROLLMENT_INPUT_READBACK")
            issuer._verify_identity(issuer.root_handle, anchor.root_components[-1][1])
            issuer._verify_identity(issuer.control_handle, anchor.control_identity)
            issuer._verify_identity(issuer.b1_handle, anchor.b1_identity)
            # Confirm native custody cleanup before publishing machine authority.
        storage.NativeStorageLease.close(issuer)  # confirmed native cleanup; origin still held
        provisioner.publish_enrollment(issuer._issuer_origin, anchor, input_revision)
        return {"status": "ENROLLED_PENDING_REBUILD", "state_required": True, "model_complete": False}
