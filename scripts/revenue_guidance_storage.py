"""
UNEXECUTED/UNVALIDATED CODE-ONLY IMPLEMENTATION.
revenue_guidance_storage.py - P2 Provider-Native Storage Substrate.
Trusted-anchor descent, identity-pinned handle leases, bounded journal I/O.
NOT a capability-proven or durable backend. No automatic activation.
"""

import hashlib
import json
import re
import struct
from dataclasses import dataclass

import revenue_guidance_windows as win32

MAX_OBJECT_BYTES = 8 * 1024 * 1024       # 8 MiB
MAX_CUMULATIVE_BYTES = 64 * 1024 * 1024  # 64 MiB per lease
MAX_OBJECT_OPENS = 4096
MAX_DESCENT_COMPONENTS = 16

JOURNAL_SLOT_SIZE = 65536
JOURNAL_FILE_SIZE = 131072
JOURNAL_HEADER_SIZE = 64
JOURNAL_MAX_PAYLOAD = 8192

class StorageLeaseError(Exception): pass
class JournalRecoveryRequired(StorageLeaseError): pass
class BudgetExceededError(StorageLeaseError): pass
class IdentityMismatchError(StorageLeaseError): pass
class LeaseClosedError(StorageLeaseError): pass
class StorageBusyError(StorageLeaseError): pass
class NamespaceConflictError(StorageLeaseError): pass

class MissingTrustedAnchorError(StorageLeaseError):
    def __init__(self, message="TRUST_AUTHORITY_UNAVAILABLE"):
        super().__init__(message)

def _safe_json_loads(text: str) -> dict:
    def dict_pairs_hook(pairs):
        d = {}
        for k, v in pairs:
            if k in d:
                raise ValueError("Duplicate key")
            d[k] = v
        return d
    def reject_constant(c):
        raise ValueError("Nonfinite float not allowed")
    return json.loads(text, object_pairs_hook=dict_pairs_hook, parse_constant=reject_constant)

def _validate_p1_state(state: dict) -> dict:
    if type(state) is not dict:
        raise ValueError("State must be dict")
    if "Schema" not in state or type(state["Schema"]) is not str or state["Schema"] != "guidance-provider-journal-v1":
        raise ValueError("Invalid State.Schema")
    if "StateRequired" not in state or state["StateRequired"] is not True:
        raise ValueError("StateRequired must be True")
    if "InputRevision" not in state or type(state["InputRevision"]) is not str or not re.fullmatch(r"gir1:[0-9a-f]{64}", state["InputRevision"]):
        raise ValueError("Invalid InputRevision")
    if "PendingRevision" not in state or "Intent" not in state:
        raise ValueError("Missing PendingRevision or Intent")
    rev = state["PendingRevision"]
    if rev is not None and (type(rev) is not str or not re.fullmatch(r"gir1:[0-9a-f]{64}", rev)):
        raise ValueError("Invalid PendingRevision")
    intent = state["Intent"]
    if intent is not None:
        if type(intent) is not dict:
            raise ValueError("Intent must be dict")
        if set(intent.keys()) != {"Id", "BaseInputRevision", "ObservedAtBeginRevision", "PriorPendingRevision"}:
            raise ValueError("Intent keys must exactly match required set")
        if type(intent["Id"]) is not str or not intent["Id"] or len(intent["Id"]) > 255:
            raise ValueError("Intent Id must be bounded non-empty string")
        if type(intent["BaseInputRevision"]) is not str or not re.fullmatch(r"gir1:[0-9a-f]{64}", intent["BaseInputRevision"]):
            raise ValueError("Invalid BaseInputRevision")
        if type(intent["ObservedAtBeginRevision"]) is not str or not re.fullmatch(r"gir1:[0-9a-f]{64}", intent["ObservedAtBeginRevision"]):
            raise ValueError("Invalid ObservedAtBeginRevision")
        prior = intent["PriorPendingRevision"]
        if prior is not None and (type(prior) is not str or not re.fullmatch(r"gir1:[0-9a-f]{64}", prior)):
            raise ValueError("Invalid PriorPendingRevision")
        intent = {
            "Id": intent["Id"],
            "BaseInputRevision": intent["BaseInputRevision"],
            "ObservedAtBeginRevision": intent["ObservedAtBeginRevision"],
            "PriorPendingRevision": prior
        }
    if set(state.keys()) - {"Schema", "StateRequired", "InputRevision", "PendingRevision", "Intent"}:
        raise ValueError("Extra members in state")
    return {
        "Schema": state["Schema"],
        "StateRequired": state["StateRequired"],
        "InputRevision": state["InputRevision"],
        "PendingRevision": rev,
        "Intent": intent
    }

@dataclass(frozen=True)
class NativeLimits:
    max_object_bytes: int = MAX_OBJECT_BYTES
    max_cumulative_bytes: int = MAX_CUMULATIVE_BYTES
    max_object_opens: int = MAX_OBJECT_OPENS
    max_components: int = MAX_DESCENT_COMPONENTS
    max_owned_handles: int = 128
    max_elapsed_ms: int = 10000
    profile: str = "legacy"

    def __post_init__(self):
        if type(self.profile) is not str or self.profile not in ("legacy", "b1"):
            raise ValueError("Unsupported native resource profile")
        for field_name, value in self.__dict__.items():
            if field_name == "profile":
                continue
            if type(value) is not int or value < 0:
                raise TypeError("Limits must be nonnegative exact integers")
        if self.max_owned_handles > 128 or self.max_components > MAX_DESCENT_COMPONENTS:
            raise ValueError("Ownership/depth ceiling exceeded")
        if self.profile == "b1":
            # A fixed application profile, never max_object_bytes override alone.
            if (self.max_object_bytes, self.max_cumulative_bytes,
                self.max_object_opens, self.max_owned_handles, self.max_components) != (
                    16 * 1024 * 1024, 1024 * 1024 * 1024, 4096, 128, MAX_DESCENT_COMPONENTS):
                raise ValueError("B1 profile resource policy must be exact")
            if not 0 < self.max_elapsed_ms <= 600000:
                raise ValueError("B1 elapsed admission ceiling exceeded")
        elif (self.max_object_bytes > MAX_OBJECT_BYTES or
              self.max_cumulative_bytes > MAX_CUMULATIVE_BYTES or
              self.max_object_opens > MAX_OBJECT_OPENS or self.max_elapsed_ms > 10000):
            raise ValueError("Legacy limits exceed strict contract ceilings")

    @classmethod
    def b1(cls, parent_remaining_ms: int):
        """Explicit profile; future host must share/constrain its real parent budget."""
        if type(parent_remaining_ms) is not int or parent_remaining_ms <= 0:
            raise ValueError("Positive actual parent remaining budget required")
        return cls(max_object_bytes=16 * 1024 * 1024,
                   max_cumulative_bytes=1024 * 1024 * 1024,
                   max_object_opens=4096, max_components=MAX_DESCENT_COMPONENTS,
                   max_owned_handles=128, max_elapsed_ms=min(600000, parent_remaining_ms),
                   profile="b1")

@dataclass(frozen=True)
class ObjectIdentity:
    volume_serial: int
    file_id: bytes

@dataclass(frozen=True)
class RootAnchor:
    schema_version: str
    bootstrap_id: str
    volume_guid: str
    volume_root_identity: ObjectIdentity
    root_components: tuple[tuple[str, ObjectIdentity], ...]
    coordination_identity: ObjectIdentity
    journal_identity: ObjectIdentity
    journal_format_version: int
    state_required: bool
    control_identity: ObjectIdentity | None = None
    b1_identity: ObjectIdentity | None = None
    input_digests: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        pass  # Validation moved to _validate_anchor_data

import time

def _validate_anchor_data(anchor: RootAnchor) -> RootAnchor:
    if type(anchor) is not RootAnchor:
        raise MissingTrustedAnchorError("Invalid candidate type")
    if type(anchor.schema_version) is not str or anchor.schema_version not in ("guidance-provider-storage-v1", "guidance-provider-storage-v2"):
        raise MissingTrustedAnchorError("Invalid schema version")
    if type(anchor.bootstrap_id) is not str or not anchor.bootstrap_id or len(anchor.bootstrap_id) > 255:
        raise MissingTrustedAnchorError("Invalid bootstrap id")
    if type(anchor.volume_guid) is not str or not re.fullmatch(r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}", anchor.volume_guid):
        raise MissingTrustedAnchorError("Invalid volume GUID")

    def _val_id(oid: ObjectIdentity) -> ObjectIdentity:
        if type(oid) is not ObjectIdentity:
            raise MissingTrustedAnchorError("Invalid ObjectIdentity")
        if type(oid.volume_serial) is not int or oid.volume_serial < 0 or oid.volume_serial > 0xFFFFFFFFFFFFFFFF:
            raise MissingTrustedAnchorError("Invalid volume serial")
        if type(oid.file_id) is not bytes or len(oid.file_id) != 16:
            raise MissingTrustedAnchorError("Invalid file ID")
        return ObjectIdentity(volume_serial=oid.volume_serial, file_id=bytes(oid.file_id))

    vol_root_id = _val_id(anchor.volume_root_identity)

    if type(anchor.root_components) is not tuple:
        raise MissingTrustedAnchorError("Invalid root components")
    if len(anchor.root_components) > 16:
        raise MissingTrustedAnchorError("Root components > 16")
    comps = []
    for comp in anchor.root_components:
        if type(comp) is not tuple or len(comp) != 2:
            raise MissingTrustedAnchorError("Invalid component tuple")
        name, oid = comp
        try:
            win32._validate_component(name)
        except Exception:
            raise MissingTrustedAnchorError("Invalid component name")
        comps.append((str(name), _val_id(oid)))

    coor_id = _val_id(anchor.coordination_identity)
    journ_id = _val_id(anchor.journal_identity)

    if type(anchor.journal_format_version) is not int or anchor.journal_format_version != 1:
        raise MissingTrustedAnchorError("Invalid journal format")
    if type(anchor.state_required) is not bool or anchor.state_required is not True:
        raise MissingTrustedAnchorError("StateRequired must be True")

    control, b1, inputs = None, None, ()
    if anchor.schema_version == "guidance-provider-storage-v2":
        control, b1 = _val_id(anchor.control_identity), _val_id(anchor.b1_identity)
        from revenue_guidance_provisioner import CONTROL_INPUTS
        if (not comps or type(anchor.input_digests) is not tuple or len(anchor.input_digests) != len(CONTROL_INPUTS)
                or {n for n, _ in anchor.input_digests} != CONTROL_INPUTS
                or any(type(d) is not str or not re.fullmatch("[0-9a-f]{64}", d) for _, d in anchor.input_digests)
                or len({control, b1, coor_id, journ_id, comps[-1][1]}) != 5):
            raise MissingTrustedAnchorError("Invalid controlled layout")
        inputs = tuple(sorted(anchor.input_digests))
    elif anchor.control_identity is not None or anchor.b1_identity is not None or anchor.input_digests:
        raise MissingTrustedAnchorError("Legacy anchor cannot carry split layout")
    return RootAnchor(
        schema_version=str(anchor.schema_version),
        bootstrap_id=str(anchor.bootstrap_id),
        volume_guid=str(anchor.volume_guid),
        volume_root_identity=vol_root_id,
        root_components=tuple(comps),
        coordination_identity=coor_id,
        journal_identity=journ_id,
        journal_format_version=int(anchor.journal_format_version),
        state_required=bool(anchor.state_required), control_identity=control,
        b1_identity=b1, input_digests=inputs
    )


class _StagingReservation:
    """Private prepaid resource custody, NOT enrollment or mutation authority."""
    def __init__(self, budget, lease, epoch, size, read_bytes, mutations):
        self.budget = budget
        self.lease = lease
        self.epoch = epoch
        self.size = size
        self.write_remaining = size
        self.read_remaining = read_bytes
        self.mutation_remaining = mutations
        self.owner = None
        self.readback_owner = None


class NativeBudget:
    """Conservative lease-lifetime reservations; unknown/unused work is not refunded."""
    def __init__(self, limits: NativeLimits, ownership_slots):
        self.limits = limits
        self.bytes_read = 0
        self.bytes_written = 0
        self.buffer_bytes = 0
        self.requests = 0
        self.mutations = 0
        self.directory_pages = 0
        self.directory_entries = 0
        self.new_capture_bytes = 0
        self.historical_capture_bytes = 0
        self.retained_raw_bytes = 0
        self._read_credit = 0
        self._write_credit = 0
        self._mutation_credit = 0
        self._opens = 0
        self._ownership_slots = ownership_slots
        self.start_time = time.monotonic()
        self.deadline = self.start_time + limits.max_elapsed_ms / 1000
        b1 = limits.profile == "b1"
        self.max_write_bytes = (256 if b1 else 64) * 1024 * 1024
        self.max_new_capture_bytes = (128 if b1 else 64) * 1024 * 1024
        self.max_historical_capture_bytes = (256 if b1 else 64) * 1024 * 1024
        self.max_retained_raw_bytes = (384 if b1 else 64) * 1024 * 1024
        self.max_directory_entries = 4096 if b1 else 256
        self.max_directory_pages = self.max_directory_entries + 1
        self.max_requests = 65536 if b1 else 8192
        self.max_mutations = 16384 if b1 else 2048
        # Submitted buffers include read/write, directory pages and bounded
        # names/metadata; this is actual cumulative work, not a claimed heap proof.
        self.max_buffer_bytes = (limits.max_cumulative_bytes + self.max_write_bytes +
                                 self.max_requests * 1024)

    @property
    def opens(self):
        return self._opens

    @property
    def owned_handles(self):
        return sum(1 for h in self._ownership_slots if h is not None and h._charged and not h._active_released)

    @staticmethod
    def _count(value):
        if type(value) is not int or value < 0:
            raise BudgetExceededError("Resource count must be a nonnegative exact integer")

    def _check_time(self):
        if time.monotonic() > self.deadline:
            raise BudgetExceededError("Elapsed admission budget exceeded (not kernel cancellation)")

    def constrain_remaining(self, remaining_ms):
        self._count(remaining_ms)
        self._check_time()
        self.deadline = min(self.deadline, time.monotonic() + remaining_ms / 1000)

    def object_cap(self, raw_document=False):
        if type(raw_document) is not bool:
            raise win32.StorageValidationFault("raw_document must be exact bool")
        if raw_document and self.limits.profile != "b1":
            raise BudgetExceededError("Raw-document profile not admitted")
        return self.limits.max_object_bytes if raw_document else min(MAX_OBJECT_BYTES, self.limits.max_object_bytes)

    def precharge_open(self, owner):
        self.ensure_opens(1)
        if self._ownership_slots[owner._slot] is not owner or owner._charged:
            raise win32.StorageValidationFault("Invalid debit owner")
        # Registered request/owner already exists. No lifetime refund on unwind.
        self._opens += 1
        owner._charged = True

    def ensure_opens(self, count):
        self._count(count)
        self._check_time()
        if self._opens + count > self.limits.max_object_opens:
            raise BudgetExceededError("Handle open lifetime limit exceeded")
        if self.owned_handles + count > self.limits.max_owned_handles:
            raise BudgetExceededError("Active owned handles limit exceeded")

    def release_active_handle(self, owner):
        # Only no-submission, settled absence or checked close; idempotent.
        owner._evidence.released = True
        owner._active_released = True

    def _charge_transition(self, read_bytes, write_bytes, mutations):
        for count in (read_bytes, write_bytes, mutations):
            self._count(count)
        self._check_time()
        if self.bytes_read + read_bytes > self.limits.max_cumulative_bytes:
            raise BudgetExceededError("Cumulative native read/readback ceiling exceeded")
        if self.bytes_written + write_bytes > self.max_write_bytes:
            raise BudgetExceededError("Cumulative native write ceiling exceeded")
        if self.mutations + mutations > self.max_mutations:
            raise BudgetExceededError("Native mutation ceiling exceeded")
        # Counters are lifetime admission, never refunds of success/unused/UNKNOWN.
        self.bytes_read += read_bytes
        self.bytes_written += write_bytes
        self.mutations += mutations

    def reserve_transition(self, *, read_bytes=0, write_bytes=0, mutations=0):
        self._charge_transition(read_bytes, write_bytes, mutations)
        self._read_credit += read_bytes
        self._write_credit += write_bytes
        self._mutation_credit += mutations

    def _reserve_staging(self, lease, size, *, raw_document=False):
        win32._require_context(lease)
        self._count(size)
        if (lease.budget is not self or lease._live_operation is None or
            size > self.object_cap(raw_document)):
            raise win32.StorageValidationFault("Live staging plan required")
        chunks = (size + win32.IO_CHUNK_BYTES - 1) // win32.IO_CHUNK_BYTES
        # Chunk flush/readback + source verification + reopened target verification,
        # with create/EOF/EOF-flush/publication-flush/rename mutations.
        reservation = _StagingReservation(self, lease, lease._live_operation,
                                           size, 3 * size, 2 * chunks + 5)
        self._charge_transition(reservation.read_remaining, size,
                                reservation.mutation_remaining)
        # Deliberately NOT global credit: journal/unrelated work cannot spend it.
        return reservation

    def _bind_staging(self, reservation, owner):
        context = win32._require_context(owner.lease_context)
        if (type(reservation) is not _StagingReservation or reservation.budget is not self or
            reservation.lease is not context or context.budget is not self or
            reservation.epoch is not context._live_operation or reservation.epoch is None or
            reservation.owner is not None or owner._staging_reservation is not None or
            owner._slot is None or self._ownership_slots[owner._slot] is not owner or
            not owner._charged or owner._request.submitted or owner._is_directory or
            not owner._writable or not owner._delete_access or
            reservation.size > owner._object_cap):
            raise win32.StorageValidationFault("Invalid staging reservation binding")
        # Bind before NtCreateFile submission, not a fallible postreturn adoption.
        owner._staging_reservation = reservation
        owner._planned_size = reservation.size
        reservation.owner = owner

    def _staging_for(self, owner):
        win32._require_context(owner.lease_context)
        reservation = owner._staging_reservation
        if (type(reservation) is not _StagingReservation or reservation.budget is not self or
            reservation.owner is not owner or reservation.lease is not owner.lease_context or
            reservation.epoch is None or reservation.epoch is not owner.lease_context._live_operation):
            raise win32.StorageValidationFault("Current owned staging reservation required")
        return reservation

    def _reserve_staging_mutations(self, owner, count):
        reservation = self._staging_for(owner)
        self._count(count)
        self._charge_transition(0, 0, count)
        reservation.mutation_remaining += count

    def _bind_staging_readback(self, reservation, reader):
        context = win32._require_handle(reader)
        if (type(reservation) is not _StagingReservation or reservation.budget is not self or
            reservation.lease is not context or reservation.epoch is None or
            reservation.epoch is not context._live_operation or reservation.owner is None):
            raise win32.StorageValidationFault("Invalid staging readback reservation")
        source = reservation.owner
        if (source._staging_reservation is not reservation or not source._published or
            not source._evidence.close_confirmed or not source._evidence.released or
            source._identity is None or reservation.readback_owner is not None):
            raise win32.StorageValidationFault("Confirmed published source required")
        actual = win32._safe_metadata(reader, directory=False)
        if actual[:2] != source._identity or actual[2] != reservation.size:
            raise IdentityMismatchError("Readback owner is not the actual published object")
        reservation.readback_owner = reader
        reader._readback_reservation = reservation

    def precharge_read(self, size):
        self._count(size)
        if size > self.limits.max_object_bytes:
            raise BudgetExceededError("Object read reservation exceeds admitted ceiling")
        self.reserve_transition(read_bytes=size)

    def consume_read(self, size, *, owner=None, reservation=None):
        self._count(size)
        self._check_time()
        if reservation is not None:
            if owner is None:
                raise win32.StorageValidationFault("Owned readback required")
            context = win32._require_handle(owner)
            if (type(reservation) is not _StagingReservation or reservation.budget is not self or
                reservation.lease is not context or reservation.epoch is None or
                reservation.epoch is not context._live_operation):
                raise win32.StorageValidationFault("Invalid read reservation")
            if owner is reservation.owner:
                if self._staging_for(owner) is not reservation:
                    raise win32.StorageValidationFault("Wrong staging read owner")
            elif owner is not reservation.readback_owner or owner._readback_reservation is not reservation:
                raise win32.StorageValidationFault("Wrong reopened readback owner")
            if size > reservation.read_remaining:
                raise BudgetExceededError("Owned staging readback reservation exhausted")
            reservation.read_remaining -= size
            return
        if size > self._read_credit:
            self.reserve_transition(read_bytes=size - self._read_credit)
        self._read_credit -= size

    def consume_write(self, size, *, owner=None):
        self._count(size)
        self._check_time()
        if owner is not None and owner._staging_reservation is not None:
            reservation = self._staging_for(owner)
            if size > reservation.write_remaining:
                raise BudgetExceededError("Owned staging write reservation exhausted")
            reservation.write_remaining -= size
            return
        if size > self._write_credit:
            self.reserve_transition(write_bytes=size - self._write_credit, read_bytes=size)
        self._write_credit -= size

    def charge_work(self, *, buffer_bytes=0, mutation=False, owner=None):
        self._count(buffer_bytes)
        if type(mutation) is not bool:
            raise win32.StorageValidationFault("Mutation flag must be exact bool")
        self._check_time()
        if self.requests >= self.max_requests or self.buffer_bytes + buffer_bytes > self.max_buffer_bytes:
            raise BudgetExceededError("Native request/buffer-work ceiling exceeded")
        reservation = None
        if mutation and owner is not None and owner._staging_reservation is not None:
            reservation = self._staging_for(owner)
            if reservation.mutation_remaining == 0:
                raise BudgetExceededError("Owned staging mutation reservation exhausted")
        elif mutation and self._mutation_credit == 0:
            self.reserve_transition(mutations=1)
        self.requests += 1
        self.buffer_bytes += buffer_bytes
        if mutation:
            if reservation is not None:
                reservation.mutation_remaining -= 1
            else:
                self._mutation_credit -= 1

    def charge_directory_page(self):
        self._check_time()
        if self.directory_pages >= self.max_directory_pages:
            raise BudgetExceededError("Directory page ceiling exceeded")
        self.directory_pages += 1

    def charge_directory_entry(self):
        self._check_time()
        if self.directory_entries >= self.max_directory_entries:
            raise BudgetExceededError("Directory entry ceiling exceeded")
        self.directory_entries += 1

    def admit_capture(self, size, *, historical=False, raw_document=False):
        self._count(size)
        if type(historical) is not bool or size > self.object_cap(raw_document):
            raise BudgetExceededError("Capture type/size exceeds admitted policy")
        self._check_time()
        if historical:
            if self.historical_capture_bytes + size > self.max_historical_capture_bytes:
                raise BudgetExceededError("Historical capture working-set ceiling exceeded")
        elif self.new_capture_bytes + size > self.max_new_capture_bytes:
            raise BudgetExceededError("New capture/cycle ceiling exceeded")
        if self.retained_raw_bytes + size > self.max_retained_raw_bytes:
            raise BudgetExceededError("Retained capture cache ceiling exceeded")
        if historical:
            self.historical_capture_bytes += size
        else:
            self.new_capture_bytes += size
        # Conservative lifetime retention (no eviction/refund or cross-epoch cache).
        self.retained_raw_bytes += size

    def check_depth(self, depth):
        self._count(depth)
        self._check_time()
        if depth > self.limits.max_components:
            raise BudgetExceededError("Descent depth exceeded")

import threading
from contextlib import contextmanager

COORDINATION_FILENAME = "coordination.lock"
JOURNAL_FILENAME = "journal.dat"

class JournalVersionToken:
    def __init__(self, seq: int, digest: bytes):
        self._seq = seq
        self._digest = digest

@dataclass(frozen=True)
class JournalStateResult:
    state: dict
    version: JournalVersionToken
    state_required: bool
    bootstrap_id: str
    schema_version: str

@dataclass(frozen=True)
class JournalCommitResult:
    success: bool
    state: dict
    version: JournalVersionToken
    state_required: bool
    bootstrap_id: str
    schema_version: str

@dataclass(frozen=True)
class NamespaceObjectResult:
    identity: ObjectIdentity
    size: int
    sha256: bytes
    reused: bool

@dataclass(frozen=True)
class _CapturedMutableState:
    # Comparison evidence, never enrollment/authority. Revalidated before replace.
    lease: object
    epoch: object
    parent_identity: ObjectIdentity
    name: str
    identity: ObjectIdentity | None
    data: bytes | None

class NativeStorageLease:
    def __init__(self, candidate: RootAnchor, limits: NativeLimits, *, parent_deadline=None):
        if type(limits) is not NativeLimits:
            raise TypeError("limits must be NativeLimits")
        detached_limits = NativeLimits(
            max_object_bytes=limits.max_object_bytes,
            max_cumulative_bytes=limits.max_cumulative_bytes,
            max_object_opens=limits.max_object_opens,
            max_components=limits.max_components,
            max_owned_handles=limits.max_owned_handles,
            max_elapsed_ms=limits.max_elapsed_ms,
            profile=limits.profile
        )
        detached_candidate = _validate_anchor_data(candidate)

        try:
            import revenue_guidance_provisioner as provisioner
            if not hasattr(provisioner, 'require_anchor'):
                raise MissingTrustedAnchorError("TRUST_AUTHORITY_UNAVAILABLE")
            approved = provisioner.require_anchor(detached_candidate)

            detached_approved = _validate_anchor_data(approved)

            if (detached_approved.schema_version != detached_candidate.schema_version or
                detached_approved.bootstrap_id != detached_candidate.bootstrap_id or
                detached_approved.volume_guid != detached_candidate.volume_guid or
                detached_approved.volume_root_identity != detached_candidate.volume_root_identity or
                detached_approved.root_components != detached_candidate.root_components or
                detached_approved.coordination_identity != detached_candidate.coordination_identity or
                detached_approved.journal_identity != detached_candidate.journal_identity or
                detached_approved.journal_format_version != detached_candidate.journal_format_version or
                detached_approved.state_required != detached_candidate.state_required or
                detached_approved.control_identity != detached_candidate.control_identity or
                detached_approved.b1_identity != detached_candidate.b1_identity or
                detached_approved.input_digests != detached_candidate.input_digests):
                raise MissingTrustedAnchorError("Authority rejected candidate")
        except Exception:
            raise MissingTrustedAnchorError("TRUST_AUTHORITY_UNAVAILABLE") from None

        self.anchor = detached_approved
        if detached_limits.profile == "b1":
            detached_limits = _remaining_b1_limits(detached_limits, parent_deadline)
        self._initialize_custody(detached_limits)
        self._start_acquisition()

    def _initialize_custody(self, detached_limits):
        self.limits = detached_limits
        # Active custody is bounded independently of 4096 lifetime submissions.
        # Clean confirmed slots may be reused; failures/quarantine never are.
        self._owned_handles = [None] * detached_limits.max_owned_handles
        self._open_evidence = [None] * detached_limits.max_object_opens
        self._next_serial = 0
        self._cleanup_epoch = 0
        self._live_operation = None
        self._io_record = None
        self.budget = NativeBudget(detached_limits, self._owned_handles)
        self._closed = False
        self._quarantined = False
        self._failure_primary = None
        self._cleanup_failure = StorageLeaseError("Failed to close all handles cleanly")
        self._pending_failure = win32.StorageUnavailableError("PENDING_IO_UNRESOLVED")
        for error in (self._cleanup_failure, self._pending_failure):
            error.ownership_context = self
            error.primary_error = None
        self.root_handle: win32.OwnedHandle | None = None
        self.control_handle: win32.OwnedHandle | None = None
        self.b1_handle: win32.OwnedHandle | None = None
        self.coordination_handle: win32.OwnedHandle | None = None
        self.journal_handle: win32.OwnedHandle | None = None
        self._lock = threading.Lock()
        self._guard_thread = None
        self._issued_tokens: list[JournalVersionToken] = []
        self._state = "INITIAL"

    def _start_acquisition(self):
        try:
            self._acquire()
        except BaseException as primary:
            self._state = "FAILED"
            self._failure_primary = primary
            try:
                self.close()
            except BaseException as cleanup:
                # The bounded context keeps every close error and original status.
                if cleanup is primary:
                    raise
                raise cleanup from primary
            raise

    @contextmanager
    def _serialized(self):
        if not self._lock.acquire(blocking=False):
            raise StorageBusyError("Lease is busy")
        try:
            self._guard_thread = threading.get_ident()
            yield
        finally:
            self._guard_thread = None
            self._lock.release()

    def _mark_quarantined(self):
        self._quarantined = True
        for h in self._owned_handles:
            if h is not None:
                h._quarantined = True
        if self.root_handle: self.root_handle._quarantined = True
        if self.coordination_handle: self.coordination_handle._quarantined = True
        if self.journal_handle: self.journal_handle._quarantined = True

    def _track_open_root(self, guid: str) -> win32.OwnedHandle:
        return win32.open_volume_root(guid, lease_context=self)

    def _track_open_relative(self, parent: win32.OwnedHandle, name: str, is_dir: bool, write_access: bool) -> win32.OwnedHandle:
        return win32.open_relative(parent, name, is_dir, write_access, lease_context=self)

    def _check_token_capacity(self, sequence: int, digest: bytes):
        for t in self._issued_tokens:
            if t._seq == sequence and t._digest == digest:
                return
        if len(self._issued_tokens) >= 64:
            raise win32.StorageValidationFault("Maximum issued tokens limit reached")

    def _issue_token(self, sequence: int, digest: bytes) -> JournalVersionToken:
        for t in self._issued_tokens:
            if t._seq == sequence and t._digest == digest:
                return t
        self._check_token_capacity(sequence, digest)
        version_token = JournalVersionToken(sequence, digest)
        self._issued_tokens.append(version_token)
        return version_token

    def _acquire(self):
        with self._serialized():
            if self._closed or self._state != "INITIAL":
                raise LeaseClosedError("Lease cannot be re-acquired")

            self._state = "ACQUIRING"

            root = self._track_open_root(self.anchor.volume_guid)
            self._verify_identity(root, self.anchor.volume_root_identity)

            current_dir = root
            depth = 0
            for comp_name, expected_id in self.anchor.root_components:
                depth += 1
                self.budget.check_depth(depth)
                current_dir = self._track_open_relative(current_dir, comp_name, is_dir=True, write_access=False)
                self._verify_identity(current_dir, expected_id)
            self.root_handle = current_dir

            control_parent = self.root_handle
            if self.anchor.schema_version == "guidance-provider-storage-v2":
                self.control_handle = self._track_open_relative(self.root_handle, "control", True, False)
                self._verify_identity(self.control_handle, self.anchor.control_identity)
                self.b1_handle = win32.open_namespace_directory(self.root_handle, "b1")
                self._verify_identity(self.b1_handle, self.anchor.b1_identity)
                control_parent = self.control_handle
            self.coordination_handle = self._track_open_relative(
                control_parent, COORDINATION_FILENAME, is_dir=False, write_access=True
            )
            self._verify_identity(self.coordination_handle, self.anchor.coordination_identity)

            self.journal_handle = self._track_open_relative(
                control_parent, JOURNAL_FILENAME, is_dir=False, write_access=True
            )
            self._verify_identity(self.journal_handle, self.anchor.journal_identity)

            vol, fid, size, is_dir, del_pend, attr, rep, links = win32.get_file_metadata(self.journal_handle)
            if size != 131072:
                raise win32.StorageValidationFault("Journal EOF is not exactly 131072")

            # Full initial journal validated before usable lease escapes
            self._get_both_slots()
            self._state = "READY"

    def _verify_identity(self, handle: win32.OwnedHandle, expected: ObjectIdentity):
        vol_serial, file_id, _, _, _, _, _, _ = win32.get_file_metadata(handle)
        if vol_serial != expected.volume_serial or file_id != expected.file_id:
            raise IdentityMismatchError("Identity mismatch")

    def _ownership_boundary(self):
        return self._next_serial

    def _cleanup_owned(self, first_slot=0):
        try:
            return self._cleanup_registered_owners(first_slot)
        except BaseException:
            # An interrupted traversal must retain any actual still-live owner,
            # not merely exceptions originating inside CloseHandle itself.
            win32._retain_uncertain_cleanup(self)
            raise

    def _cleanup_registered_owners(self, first_slot=0):
        # Slots can be reused; acquisition serial, not slot index, orders ancestry.
        # No fallible cleanup-list growth. Failed owners are retained and attempted
        # once only; their stable close_error is re-reported on later Close.
        has_error = False
        self._cleanup_epoch += 1
        epoch = self._cleanup_epoch
        while True:
            selected = None
            for h in self._owned_handles:
                if (h is None or h._serial < first_slot or h._cleanup_mark == epoch or
                    (h._closed and h.close_error is None)):
                    continue
                # Rename target ancestry can be acquired after the source.
                # Process still-unattempted children first; a failed child stays
                # retained and will also prevent its ancestor's native close.
                dependent = False
                for child in self._owned_handles:
                    if (child is not None and not child._closed and child is not h and
                        child._cleanup_mark != epoch and
                        (child._request.parent is h or child._rename_parent is h)):
                        dependent = True
                        break
                if not dependent and (selected is None or h._serial > selected._serial):
                    selected = h
            if selected is None:
                break
            selected._cleanup_mark = epoch
            try:
                selected.close()
            except BaseException as error:
                has_error = True
                if selected.close_error is None:
                    selected.close_error = error
        return has_error

    def _raise_cleanup_failure(self, primary):
        error = self._pending_failure if (self._quarantined or win32._retains_context(self)) else self._cleanup_failure
        # Avoid self-cause on an already propagated pending/cleanup error.
        if primary is not error:
            error.primary_error = primary
            raise error from primary
        raise error

    def close(self):
        try:
            with self._serialized():
                self._closed = True
                has_error = self._cleanup_owned()
                if self._quarantined or win32._retains_context(self) or has_error:
                    self._raise_cleanup_failure(self._failure_primary)
        except BaseException:
            # Also cover serialization failure before cleanup begins. The narrow
            # seam checks existing submitted/registered owners, never adopts one.
            win32._retain_uncertain_cleanup(self)
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val is not None:
            self._failure_primary = exc_val
        self.close()

    def identity_for(self) -> ObjectIdentity:
        with self._serialized():
            if self._closed or not self.root_handle:
                raise LeaseClosedError("Lease closed")
            vol, fid, _, _, _, _, _, _ = win32.get_file_metadata(self.root_handle)
            return ObjectIdentity(volume_serial=vol, file_id=fid)

    def capture_bytes(self, components: list[str], max_bytes: int, expected_sha256: bytes | None = None, *, raw_document=False, historical=False) -> tuple[bytes, bytes]:
        with self._use_guard():
            if self._closed or not self.root_handle:
                raise LeaseClosedError("Lease closed")
            cap = self.budget.object_cap(raw_document)
            if type(historical) is not bool:
                raise win32.StorageValidationFault("historical must be exact bool")
            if type(max_bytes) is not int or max_bytes < 0 or max_bytes > cap:
                raise BudgetExceededError("Requested bytes invalid or exceeds hard limit")
            if expected_sha256 is not None:
                if type(expected_sha256) is not bytes or len(expected_sha256) != 32:
                    raise win32.StorageValidationFault("expected_sha256 must be exactly 32 bytes or None")
            if type(components) not in (list, tuple):
                raise win32.StorageValidationFault("components must be list or tuple")
            if not components or len(components) > self.limits.max_components:
                raise win32.StorageValidationFault("Invalid component count")
            detached_comps = tuple(components[:self.limits.max_components + 1])
            if not detached_comps or len(detached_comps) > self.limits.max_components:
                raise win32.StorageValidationFault("Invalid component count")
            for c in detached_comps:
                if type(c) is not str:
                    raise win32.StorageValidationFault("Component must be exactly string")
                win32._validate_component(c)

            current_dir = self.root_handle
            first_slot = self._ownership_boundary()
            primary_exc = None
            try:
                for i, comp in enumerate(detached_comps):
                    is_last = (i == len(detached_comps) - 1)
                    self.budget.check_depth(i + 1)
                    nxt = self._track_open_relative(current_dir, comp, is_dir=not is_last, write_access=False)
                    current_dir = nxt

                leaf = current_dir
                leaf._object_cap = cap
                vol_serial, file_id, size, is_dir, del_pending, attrs, reparse, links = win32.get_file_metadata(leaf)
                if is_dir or size > max_bytes:
                    raise win32.StorageValidationFault("Object invalid or exceeds max_bytes")

                self.budget.admit_capture(size, historical=historical, raw_document=raw_document)
                self.budget.precharge_read(size)
                data = win32.read_at(leaf, 0, size)
                if win32.get_file_metadata(leaf) != (vol_serial, file_id, size, is_dir, del_pending, attrs, reparse, links):
                    raise IdentityMismatchError("Object changed during capture")

                digest = hashlib.sha256(data).digest()
                if expected_sha256 is not None and digest != expected_sha256:
                    raise win32.StorageValidationFault("Object SHA256 mismatch")
            except BaseException as primary:
                primary_exc = primary
                self._failure_primary = primary
                raise
            finally:
                # Includes opens failing before metadata/identity handoff returns.
                # No postreturn cleanup append; each stable record holds evidence.
                has_error = self._cleanup_owned(first_slot)
                if self._quarantined or win32._retains_context(self) or has_error:
                    self._closed = True
                    self._raise_cleanup_failure(primary_exc)
            return data, digest

    @contextmanager
    def _use_guard(self):
        # Composition may share the ONE held guard, only in an admitted namespace
        # operation. No Boolean authorization, unlocked bypass or second writer.
        if (self._guard_thread == threading.get_ident() and self._lock.locked() and
            self._live_operation is not None):
            win32._require_context(self)
            yield
        else:
            with self._serialized():
                win32._require_context(self)
                yield

    def _namespace_guard(self):
        win32._require_context(self)
        if self._state != "READY" or self._live_operation is None:
            raise win32.StorageValidationFault("Held live namespace operation required")

    @contextmanager
    def namespace_operation(self):
        """Cooperative serialization epoch, NOT hostile-writer CAS or durability."""
        with self._serialized():
            win32._require_context(self)
            if self._state != "READY" or self._live_operation is not None:
                raise LeaseClosedError("Namespace operation unavailable")
            boundary = self._ownership_boundary()
            self._live_operation = object()
            primary = None
            try:
                yield self
            except BaseException as error:
                primary = error
                self._failure_primary = error
                raise
            finally:
                # Never delete by name or assume interruption means settlement.
                failed = self._cleanup_owned(boundary)
                if self._quarantined or win32._retains_context(self) or failed:
                    self._closed = True
                    self._raise_cleanup_failure(primary)
                self._live_operation = None

    def constrain_remaining_budget(self, actual_parent_remaining_ms: int):
        with self._use_guard():
            self.budget.constrain_remaining(actual_parent_remaining_ms)

    def open_directory(self, components) -> win32.OwnedHandle:
        """Hold an existing strict descendant; namespace rights on the leaf only."""
        with self._use_guard():
            if type(components) not in (tuple, list):
                raise win32.StorageValidationFault("Directory components required")
            names = tuple(components[:self.limits.max_components + 1])
            if not names or len(names) > self.limits.max_components:
                raise win32.StorageValidationFault("Directory depth invalid")
            for name in names:
                win32._namespace_name(name)
            boundary = self._ownership_boundary()
            directory_scope = object()
            parent = self.root_handle
            start = 0
            if self.anchor.schema_version == "guidance-provider-storage-v2":
                if names[0] != "b1" or len(names) < 2:
                    raise win32.StorageValidationFault("Only strict B1 directory descent admitted")
                parent, start = self.b1_handle, 1
            try:
                for i in range(start, len(names)):
                    name = names[i]
                    self.budget.check_depth(i + 1)
                    if i == len(names) - 1:
                        parent = win32.open_namespace_directory(parent, name)
                    else:
                        parent = self._track_open_relative(parent, name, True, False)
                    parent._directory_scope = directory_scope
                return parent
            except BaseException as primary:
                self._failure_primary = primary
                failed = self._cleanup_owned(boundary)
                if self._quarantined or win32._retains_context(self) or failed:
                    self._closed = True
                    self._raise_cleanup_failure(primary)
                raise

    def close_owned(self, handle):
        with self._use_guard():
            win32._require_context(self, handle, cleanup=True)
            if handle in (self.root_handle, self.control_handle, self.b1_handle, self.coordination_handle, self.journal_handle):
                raise win32.StorageValidationFault("Control/root custody closes only with lease Close")
            try:
                scope = handle._directory_scope
                parent = handle._request.parent
                handle.close()
                # Release this descent's private intermediates, never unrelated
                # handles, control files, the enrolled root, or shared ancestors.
                while scope is not None and parent is not self.root_handle and parent is not None and parent._directory_scope is scope:
                    ancestor = parent._request.parent
                    parent.close()
                    parent = ancestor
            except BaseException as primary:
                self._closed = True
                self._failure_primary = primary
                raise

    def create_directory(self, parent, name):
        self._namespace_guard()
        win32._require_context(self, parent)
        self.budget.ensure_opens(1)
        self.budget.reserve_transition(mutations=1)
        try:
            return win32.create_relative(parent, name, directory=True,
                                         operation=self._live_operation,
                                         object_cap=self.budget.object_cap())
        except win32.StorageObjectExistsError:
            raise  # FILE_CREATE never opens/adopts a pre-existing directory.
        except BaseException as primary:
            self._closed = True
            self._failure_primary = primary
            raise

    def create_staging_file(self, parent, name, expected_size: int, *, raw_document=False):
        self._namespace_guard()
        win32._require_context(self, parent)
        cap = self.budget.object_cap(raw_document)
        if type(expected_size) is not int or not 0 <= expected_size <= cap:
            raise BudgetExceededError("Complete staging size must be admitted before create")
        self.budget.ensure_opens(1)
        reservation = self.budget._reserve_staging(self, expected_size, raw_document=raw_document)
        try:
            return win32.create_relative(parent, name, directory=False,
                                         operation=self._live_operation, object_cap=cap,
                                         _reservation=reservation)
        except win32.StorageObjectExistsError:
            raise
        except BaseException as primary:
            self._closed = True
            self._failure_primary = primary
            raise

    def _temporary(self, handle):
        self._namespace_guard()
        win32._require_context(self, handle)
        if (not handle._created or handle._published or not handle._writable or
            handle._temporary_operation is not self._live_operation):
            raise win32.StorageValidationFault("This operation's owned temporary required")

    def read_owned_chunk(self, handle, offset, count):
        self._namespace_guard()
        win32._require_context(self, handle)
        if handle is self.coordination_handle or handle is self.journal_handle:
            raise win32.StorageValidationFault("Control handles are not namespace objects")
        return win32.read_chunk(handle, offset, count)

    def write_owned_chunk(self, handle, offset, data):
        self._temporary(handle)
        if type(data) is not bytes or len(data) > win32.IO_CHUNK_BYTES:
            raise win32.StorageValidationFault("Chunk must be bytes <=1 MiB")
        win32._validate_range(handle, offset, len(data))
        if handle._planned_size is None or offset + len(data) > handle._planned_size:
            raise win32.StorageValidationFault("Chunk exceeds complete staging plan")
        reservation = self.budget._staging_for(handle)
        if not data:
            # Empty payload contributes no planned chunks; its explicitly
            # requested flush is extra work, not a second payload reservation.
            self.budget._reserve_staging_mutations(handle, 1)
        needed_mutations = 2 if data else 1
        if (len(data) > reservation.write_remaining or len(data) > reservation.read_remaining or
            needed_mutations > reservation.mutation_remaining):
            raise BudgetExceededError("Complete chunk + flush/readback reservation exhausted")
        # Already charged before FILE_CREATE. Consume this owner's credit once;
        # never add the same successful payload to cumulative write budget again.
        try:
            win32.write_chunk(handle, offset, data)
            win32.flush(handle)
            if win32.read_chunk(handle, offset, len(data), _reservation=reservation) != data:
                raise StorageLeaseError("Chunk readback failed")
        except BaseException as primary:
            self._closed = True
            self._failure_primary = primary
            raise

    def truncate_owned(self, handle, length):
        self._temporary(handle)
        win32._validate_range(handle, length, 0)
        if handle._planned_size is not None and length != handle._planned_size:
            raise win32.StorageValidationFault("EOF must match the admitted complete staging plan")
        if handle._staging_reservation is not None:
            if self.budget._staging_for(handle).mutation_remaining < 2:
                raise BudgetExceededError("Owned EOF + flush reservation exhausted")
        else:
            self.budget.reserve_transition(mutations=2)
        try:
            win32.truncate(handle, length)
            win32.flush(handle)
        except BaseException as primary:
            self._closed = True
            self._failure_primary = primary
            raise

    def flush_owned(self, handle):
        self._temporary(handle)
        if handle._staging_reservation is not None:
            # An explicitly requested extra flush is not the planned pipeline
            # flush: reserve its own work without stealing publication credit.
            self.budget._reserve_staging_mutations(handle, 1)
        try:
            win32.flush(handle)
        except BaseException as primary:
            self._closed = True
            self._failure_primary = primary
            raise

    def discard_temporary(self, handle):
        self._temporary(handle)
        if handle._staging_reservation is not None:
            # Explicit disposal is extra work, including after known collision;
            # unused planned credit stays charged and is never refunded.
            self.budget._reserve_staging_mutations(handle, 1)
        # Positively created by this live operation; never journal/control/delete
        # by untrusted filename. Successful disposition permits only handle close.
        win32.dispose_temporary(handle, self._live_operation)

    def enumerate_directory(self, parent):
        with self._use_guard():
            win32._require_context(self, parent)
            return win32.enumerate_names(parent)

    def _open_namespace_object(self, parent, name, *, raw_document=False):
        self._namespace_guard()
        if win32._namespace_parent(parent) is not self:
            raise win32.StorageValidationFault("Wrong namespace lease")
        win32._namespace_name(name)
        h = self._track_open_relative(parent, name, False, False)
        h._object_cap = self.budget.object_cap(raw_document)
        m = win32._safe_metadata(h, directory=False)
        if m[2] > h._object_cap:
            raise BudgetExceededError("Existing object exceeds supported profile; not truncated")
        if ObjectIdentity(m[0], m[1]) in (self.anchor.coordination_identity, self.anchor.journal_identity):
            raise win32.StorageValidationFault("Control identity is not a namespace object")
        return h

    def _close_namespace_object(self, handle, primary=None):
        try:
            handle.close()
        except BaseException as error:
            self._failure_primary = primary if primary is not None else error
            self._closed = True
            self._raise_cleanup_failure(self._failure_primary)

    def _verify_bytes(self, handle, expected, *, reservation=None):
        m = win32._safe_metadata(handle, directory=False)
        if m[2] != len(expected) or m[2] > handle._object_cap:
            raise IdentityMismatchError("Readback size mismatch")
        digest = hashlib.sha256()
        for offset in range(0, len(expected), win32.IO_CHUNK_BYTES):
            count = min(win32.IO_CHUNK_BYTES, len(expected) - offset)
            chunk = win32.read_chunk(handle, offset, count, _reservation=reservation)
            if chunk != expected[offset:offset + count]:
                raise IdentityMismatchError("Actual object bytes do not match")
            digest.update(chunk)
        if win32._safe_metadata(handle, directory=False) != m:
            raise IdentityMismatchError("Object changed during readback")
        return NamespaceObjectResult(ObjectIdentity(m[0], m[1]), m[2], digest.digest(), False)

    def capture_mutable(self, parent, name):
        self._namespace_guard()
        if win32._namespace_parent(parent) is not self:
            raise win32.StorageValidationFault("Wrong namespace lease")
        win32._namespace_name(name)
        parent_identity = ObjectIdentity(*win32._safe_metadata(parent, directory=True)[:2])
        boundary = self._ownership_boundary()
        primary = None
        try:
            try:
                h = self._open_namespace_object(parent, name)
            except win32.StorageObjectMissingError:
                return _CapturedMutableState(self, self._live_operation, parent_identity, name, None, None)
            m = win32._safe_metadata(h, directory=False)
            self.budget.admit_capture(m[2])
            self.budget.precharge_read(m[2])
            data = win32.read_at(h, 0, m[2])
            if win32._safe_metadata(h, directory=False) != m:
                raise IdentityMismatchError("Mutable object changed during capture")
            return _CapturedMutableState(self, self._live_operation, parent_identity,
                                         name, ObjectIdentity(m[0], m[1]), data)
        except BaseException as error:
            primary = error
            self._failure_primary = error
            raise
        finally:
            failed = self._cleanup_owned(boundary)
            if self._quarantined or win32._retains_context(self) or failed:
                self._closed = True
                self._raise_cleanup_failure(primary)

    def _close_conflicting_reads(self, identity):
        # An actual identity match, not a filename-based close or delete. Direct
        # readers exposed through the admitted native API are included too.
        for owner in self._owned_handles:
            if (owner is None or owner._closed or owner._active_released or
                owner._is_directory or owner._writable or
                owner is self.coordination_handle or owner is self.journal_handle):
                continue
            m = win32._safe_metadata(owner, directory=False)
            if ObjectIdentity(m[0], m[1]) == identity:
                self._close_namespace_object(owner)

    def _payload(self, payload, raw_document=False):
        if type(payload) is not bytes or len(payload) > self.budget.object_cap(raw_document):
            raise BudgetExceededError("Payload exceeds supported object policy")
        return hashlib.sha256(payload).digest()

    def _stage_verified(self, parent, staging_name, payload, raw_document):
        # Caller has reserved ALL write + BOTH staging/target readbacks first.
        h = win32.create_relative(parent, staging_name, directory=False,
                                  operation=self._live_operation,
                                  object_cap=self.budget.object_cap(raw_document))
        h._planned_size = len(payload)
        win32.write_at(h, 0, payload)
        win32.truncate(h, len(payload))
        win32.flush(h)
        actual = self._verify_bytes(h, payload)
        return h, actual

    def _reopen_verified(self, parent, name, payload, expected_identity, raw_document, *, reservation=None):
        h = self._open_namespace_object(parent, name, raw_document=raw_document)
        primary = None
        try:
            if reservation is not None:
                self.budget._bind_staging_readback(reservation, h)
            actual = self._verify_bytes(h, payload, reservation=reservation)
            if expected_identity is not None and actual.identity != expected_identity:
                raise IdentityMismatchError("Renamed target identity mismatch")
            return actual
        except BaseException as error:
            primary = error
            raise
        finally:
            self._close_namespace_object(h, primary)

    def _immutable_payload(self, name, payload, expected_content_sha256, raw_document):
        win32._namespace_name(name)
        digest = self._payload(payload, raw_document)
        if (type(expected_content_sha256) is not bytes or len(expected_content_sha256) != 32 or
            digest != expected_content_sha256):
            raise win32.StorageValidationFault("Immutable content digest does not match actual payload")
        return digest

    def rename_named_immutable(self, source, target_parent, name, payload, expected_content_sha256, *, raw_document=False):
        """Exact single target name is independent of verified content digest."""
        self._temporary(source)
        if win32._namespace_parent(target_parent) is not self:
            raise win32.StorageValidationFault("Wrong target lease")
        digest = self._immutable_payload(name, payload, expected_content_sha256, raw_document)
        if (len(payload) > source._object_cap or
            (source._planned_size is not None and len(payload) != source._planned_size)):
            raise win32.StorageValidationFault("Immutable source/plan binding invalid")
        self.budget.ensure_opens(1)
        reservation = source._staging_reservation
        if reservation is not None:
            self.budget._staging_for(source)
            if (reservation.read_remaining < 2 * len(payload) or
                reservation.mutation_remaining < 2):
                raise BudgetExceededError("Owned publication + complete readback reservation exhausted")
        else:
            self.budget.reserve_transition(read_bytes=2 * len(payload), mutations=2)
        try:
            win32.flush(source)
            staged = self._verify_bytes(source, payload, reservation=reservation)
            win32.rename_relative(source, target_parent, name, replace=False)
            self._close_namespace_object(source)
            actual = self._reopen_verified(target_parent, name, payload, staged.identity,
                                           raw_document, reservation=reservation)
            if actual.sha256 != digest:
                raise IdentityMismatchError("Named immutable final digest mismatch")
            return actual
        except win32.StorageObjectExistsError:
            raise  # Established no-replace collision; original temporary stays owned.
        except BaseException as primary:
            self._failure_primary = primary
            self._closed = True
            raise

    def rename_immutable(self, source, target_parent, digest_hex, payload, *, raw_document=False):
        """Compatibility shorthand for a bare content-addressed raw-object name."""
        self._namespace_guard()
        digest = self._payload(payload, raw_document)
        if type(digest_hex) is not str or digest_hex != digest.hex():
            raise win32.StorageValidationFault("Immutable raw-object name must be payload SHA256")
        return self.rename_named_immutable(source, target_parent, digest_hex, payload, digest,
                                           raw_document=raw_document)

    def publish_named_immutable(self, parent, name, staging_name, payload, expected_content_sha256, *, raw_document=False):
        """No-replace exact name; reuse ONLY identical validated bytes/digest.

        B1 segments/<digest>.json, generations/<id>.json and captures/<raw_sha>.json
        keep their caller-selected identities. Metadata content hash is NOT raw_sha.
        The B1 adapter must admit actual existing metadata before deliberately reusing
        its original retrieved_at/payload; a newly changed payload is never substituted,
        overwritten, or accepted merely because the name/schema looks valid here.
        """
        self._namespace_guard()
        if win32._namespace_parent(parent) is not self:
            raise win32.StorageValidationFault("Wrong namespace lease")
        digest = self._immutable_payload(name, payload, expected_content_sha256, raw_document)
        win32._namespace_name(staging_name)
        if staging_name.casefold() == name.casefold():
            raise win32.StorageValidationFault("Staging and publication names must differ")
        chunks = (len(payload) + win32.IO_CHUNK_BYTES - 1) // win32.IO_CHUNK_BYTES
        self.budget.ensure_opens(4)
        self.budget.reserve_transition(read_bytes=3 * len(payload), write_bytes=len(payload),
                                       mutations=chunks + 5)
        boundary = self._ownership_boundary()
        primary = None
        mutation_started = False
        try:
            # No cross-epoch byte cache. Named-object reuse requires full ACTUAL
            # readback of the independently supplied exact payload/content digest.
            try:
                existing = self._open_namespace_object(parent, name, raw_document=raw_document)
            except win32.StorageObjectMissingError:
                existing = None
            if existing is not None:
                actual = self._verify_bytes(existing, payload)
                self._close_namespace_object(existing)
                if actual.sha256 != digest:
                    raise IdentityMismatchError("Existing named immutable content digest mismatch")
                return NamespaceObjectResult(actual.identity, actual.size, actual.sha256, True)
            mutation_started = True
            stage, staged = self._stage_verified(parent, staging_name, payload, raw_document)
            try:
                win32.rename_relative(stage, parent, name, replace=False)
            except win32.StorageObjectExistsError:
                # Known collision, not an UNKNOWN retry or mutable overwrite.
                win32.dispose_temporary(stage, self._live_operation)
                actual = self._reopen_verified(parent, name, payload, None, raw_document)
                if actual.sha256 != digest:
                    raise IdentityMismatchError("Colliding named immutable content digest mismatch")
                return NamespaceObjectResult(actual.identity, actual.size, actual.sha256, True)
            self._close_namespace_object(stage)
            actual = self._reopen_verified(parent, name, payload, staged.identity, raw_document)
            if actual.sha256 != digest:
                raise IdentityMismatchError("Named immutable readback digest mismatch")
            return actual
        except BaseException as error:
            primary = error
            self._failure_primary = error
            if mutation_started:
                self._closed = True
            raise
        finally:
            failed = self._cleanup_owned(boundary)
            if self._quarantined or win32._retains_context(self) or failed:
                self._closed = True
                self._raise_cleanup_failure(primary)

    def publish_immutable(self, parent, digest_hex, staging_name, payload, *, raw_document=False):
        """Compatibility shorthand; named B1 artifacts use publish_named_immutable."""
        self._namespace_guard()
        digest = self._payload(payload, raw_document)
        if type(digest_hex) is not str or digest_hex != digest.hex():
            raise win32.StorageValidationFault("Immutable raw-object name must be payload SHA256")
        return self.publish_named_immutable(parent, digest_hex, staging_name, payload, digest,
                                            raw_document=raw_document)

    def replace_mutable(self, parent, name, staging_name, payload, expected):
        """Compare + replace is ONLY cooperative lease-serialized, NOT atomic CAS."""
        self._namespace_guard()
        if win32._namespace_parent(parent) is not self:
            raise win32.StorageValidationFault("Wrong namespace lease")
        win32._namespace_name(name)
        win32._namespace_name(staging_name)
        digest = self._payload(payload)
        parent_identity = ObjectIdentity(*win32._safe_metadata(parent, directory=True)[:2])
        if (type(expected) is not _CapturedMutableState or expected.lease is not self or
            expected.epoch is not self._live_operation or expected.parent_identity != parent_identity or
            expected.name != name or staging_name.casefold() == name.casefold()):
            raise win32.StorageValidationFault("Same-epoch captured expected state required")
        if (expected.identity is None) != (expected.data is None):
            raise win32.StorageValidationFault("Malformed captured state")
        if expected.data is not None:
            self._payload(expected.data)
        old_size = len(expected.data) if expected.data is not None else 0
        chunks = (len(payload) + win32.IO_CHUNK_BYTES - 1) // win32.IO_CHUNK_BYTES
        self.budget.ensure_opens(3)
        self.budget.reserve_transition(read_bytes=old_size + 2 * len(payload),
                                       write_bytes=len(payload), mutations=chunks + 5)
        boundary = self._ownership_boundary()
        primary = None
        mutation_started = False
        try:
            try:
                old = self._open_namespace_object(parent, name)
            except win32.StorageObjectMissingError:
                old = None
            if expected.identity is None:
                if old is not None:
                    raise NamespaceConflictError("Mutable target appeared")
            else:
                if old is None:
                    raise NamespaceConflictError("Mutable target disappeared")
                metadata = win32._safe_metadata(old, directory=False)
                if ObjectIdentity(metadata[0], metadata[1]) != expected.identity or metadata[2] != old_size:
                    raise NamespaceConflictError("Mutable expected identity/size changed")
                try:
                    self._verify_bytes(old, expected.data)
                except IdentityMismatchError:
                    raise NamespaceConflictError("Mutable expected bytes changed") from None
                # Close ALL conflicting reads before replace; no stale pinned
                # reader becomes an excuse for path-based reopen or weaker sharing.
                self._close_conflicting_reads(expected.identity)
            mutation_started = True
            stage, staged = self._stage_verified(parent, staging_name, payload, False)
            win32.rename_relative(stage, parent, name, replace=expected.identity is not None)
            self._close_namespace_object(stage)
            actual = self._reopen_verified(parent, name, payload, staged.identity, False)
            if actual.sha256 != digest:
                raise IdentityMismatchError("Mutable final readback mismatch")
            return actual
        except BaseException as error:
            primary = error
            self._failure_primary = error
            if mutation_started:
                self._closed = True
            raise
        finally:
            failed = self._cleanup_owned(boundary)
            if self._quarantined or win32._retains_context(self) or failed:
                self._closed = True
                self._raise_cleanup_failure(primary)

    def _parse_slot(self, slot_index: int, raw_bytes: bytes) -> 'JournalSlot | None':
        if len(raw_bytes) != JOURNAL_SLOT_SIZE:
            return None
        header_bytes = raw_bytes[:JOURNAL_HEADER_SIZE]
        try:
            magic, fmt, hdr_size, seq, plen, res, p_sha256 = struct.unpack("<8s I I Q I I 32s", header_bytes)
        except struct.error:
            return None
        if magic != b"GJSLT001" or fmt != 1 or hdr_size != JOURNAL_HEADER_SIZE:
            return None
        if plen > JOURNAL_MAX_PAYLOAD or res != 0:
            return None
        payload = raw_bytes[JOURNAL_HEADER_SIZE : JOURNAL_HEADER_SIZE + plen]
        if hashlib.sha256(payload).digest() != p_sha256:
            return None
        try:
            envelope = _safe_json_loads(payload.decode('utf-8'))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError, RecursionError):
            return None
        if not isinstance(envelope, dict):
            return None
        if set(envelope.keys()) != {"schema", "bootstrap_id", "sequence", "state"}:
            return None
        if envelope["schema"] != "guidance-provider-storage-v1":
            return None
        if envelope["bootstrap_id"] != self.anchor.bootstrap_id:
            return None
        seq_val = envelope["sequence"]
        if type(seq_val) is not int or type(seq_val) is bool or seq_val < 0 or seq_val > 0xFFFFFFFFFFFFFFFF:
            return None
        if seq_val != seq:
            return None

        try:
            state = _validate_p1_state(envelope["state"])
        except ValueError:
            return None

        if raw_bytes[JOURNAL_HEADER_SIZE + plen:] != bytes(JOURNAL_SLOT_SIZE - JOURNAL_HEADER_SIZE - plen):
            return None
        return JournalSlot(sequence=seq, state=state, raw_digest=p_sha256, slot_index=slot_index)

    def _get_both_slots(self, precharged=False) -> tuple['JournalSlot', 'JournalSlot']:
        if not precharged:
            self.budget.precharge_read(JOURNAL_FILE_SIZE)
        data = win32.read_at(self.journal_handle, 0, JOURNAL_FILE_SIZE)
        if len(data) != JOURNAL_FILE_SIZE:
            raise JournalRecoveryRequired("Journal file size is not exactly 131072 bytes")
        s0 = self._parse_slot(0, data[0:JOURNAL_SLOT_SIZE])
        s1 = self._parse_slot(1, data[JOURNAL_SLOT_SIZE:JOURNAL_FILE_SIZE])
        if s0 and s1:
            if abs(s0.sequence - s1.sequence) != 1:
                raise JournalRecoveryRequired("Sequences not adjacent")
            return s0, s1
        raise JournalRecoveryRequired("Invalid/torn/ambiguous journal slots")

    def read_journal(self) -> JournalStateResult:
        with self._use_guard():
            if self._closed or not self.journal_handle:
                raise LeaseClosedError("Lease closed")
            s0, s1 = self._get_both_slots()
            auth = s0 if s0.sequence > s1.sequence else s1
            if self.anchor.state_required and not auth.state:
                raise win32.StorageValidationFault("StateRequired=true but state is empty")
            version_token = self._issue_token(auth.sequence, auth.raw_digest)
            return JournalStateResult(state=auth.state, version=version_token, state_required=auth.state["StateRequired"], bootstrap_id=self.anchor.bootstrap_id, schema_version=auth.state["Schema"])

    def commit_journal(self, expected_version: JournalVersionToken, new_state: dict) -> JournalCommitResult:
        with self._use_guard():
            if self._closed or not self.journal_handle:
                raise LeaseClosedError("Lease closed")

            try:
                detached_new_state = _validate_p1_state(new_state)
            except ValueError:
                raise win32.StorageValidationFault("Invalid P1 state")

            if type(expected_version) is not JournalVersionToken:
                raise win32.StorageValidationFault("Invalid version token type")
            if expected_version not in self._issued_tokens:
                raise win32.StorageValidationFault("Unissued or invalid version token")

            s0, s1 = self._get_both_slots()
            auth, older = (s0, s1) if s0.sequence > s1.sequence else (s1, s0)

            if expected_version._seq != auth.sequence or expected_version._digest != auth.raw_digest:
                version_token = self._issue_token(auth.sequence, auth.raw_digest)
                return JournalCommitResult(success=False, state=auth.state, version=version_token, state_required=auth.state["StateRequired"], bootstrap_id=self.anchor.bootstrap_id, schema_version=auth.state["Schema"])

            new_seq = auth.sequence + 1
            if new_seq > 0xFFFFFFFFFFFFFFFF:
                raise win32.StorageValidationFault("Sequence overflow")

            env = {"schema": "guidance-provider-storage-v1", "bootstrap_id": self.anchor.bootstrap_id, "sequence": new_seq, "state": detached_new_state}
            payload = json.dumps(env, separators=(',', ':'), allow_nan=False).encode('utf-8')
            if len(payload) > JOURNAL_MAX_PAYLOAD:
                raise win32.StorageValidationFault("Payload exceeds limits")

            p_sha256 = hashlib.sha256(payload).digest()
            self._check_token_capacity(new_seq, p_sha256)

            hdr = struct.pack("<8s I I Q I I 32s", b"GJSLT001", 1, JOURNAL_HEADER_SIZE, new_seq, len(payload), 0, p_sha256)
            padded = hdr + payload + bytes(JOURNAL_SLOT_SIZE - len(hdr) - len(payload))
            offset = older.slot_index * JOURNAL_SLOT_SIZE
            # Reserve ENTIRE transition: 8-byte readback + 131072 byte reread.
            # Writes are bounded and within the lease.
            self.budget.reserve_transition(read_bytes=8 + JOURNAL_FILE_SIZE,
                                           write_bytes=JOURNAL_SLOT_SIZE + 8, mutations=6)
            try:
                win32.write_at(self.journal_handle, offset, b"INVALID!")
                win32.flush(self.journal_handle)
                if win32.read_at(self.journal_handle, offset, 8) != b"INVALID!":
                    raise StorageLeaseError("Invalidation readback failed")
                win32.write_at(self.journal_handle, offset + 8, padded[8:])
                win32.flush(self.journal_handle)
                win32.write_at(self.journal_handle, offset, b"GJSLT001")
                win32.flush(self.journal_handle)
                n0, n1 = self._get_both_slots(precharged=True)
                new_auth = n0 if n0.sequence > n1.sequence else n1
                if (new_auth.sequence != new_seq or
                    new_auth.raw_digest != p_sha256 or
                    new_auth.state != detached_new_state or
                    new_auth.state["StateRequired"] is not True):
                    raise StorageLeaseError("Final verify failed")

                version_token = self._issue_token(new_auth.sequence, new_auth.raw_digest)
                return JournalCommitResult(success=True, state=new_auth.state, version=version_token, state_required=new_auth.state["StateRequired"], bootstrap_id=self.anchor.bootstrap_id, schema_version=new_auth.state["Schema"])
            except BaseException as primary:
                self._failure_primary = primary
                self._closed = True
                raise

@dataclass(frozen=True)
class JournalSlot:
    sequence: int
    state: dict
    raw_digest: bytes
    slot_index: int

class NativeIssuerContext(NativeStorageLease):
    """Genuine first-issuer custody; never a fabricated normal lease.

    Independent privileged controlled_origin completes BEFORE backend binding,
    native clock/budget/allocation. Shares the very same pending/owner machinery.
    Only a positively NEW bootstrap root below the fixed held ancestry is writable.
    """
    def __init__(self, parent_remaining_ms, *, parent_deadline):
        import revenue_guidance_provisioner as provisioner
        from types import SimpleNamespace
        import secrets
        self._issuer_origin = provisioner.require_issuer()
        try:
            from revenue_guidance_enroll import validate_initial_inputs
            self._initial_inputs = validate_initial_inputs(self._issuer_origin)
            c, _, k, _ = self._issuer_origin.apis
            volume = c.create_unicode_buffer(64)
            if not k.GetVolumeNameForVolumeMountPointW("C:\\", volume, 64):
                raise MissingTrustedAnchorError()
            prefix = "\\\\?\\Volume"
            if not volume.value.startswith(prefix) or not volume.value.endswith("\\"):
                raise MissingTrustedAnchorError()
            guid = volume.value[len(prefix):-1]
            if not re.fullmatch(r"\{[0-9a-fA-F-]{36}\}", guid):
                raise MissingTrustedAnchorError()
            self._new_root_name = "enroll-" + secrets.token_hex(16)
            # Descent coordinates only, not an approved RootAnchor or fake IDs.
            self.anchor = SimpleNamespace(volume_guid=guid, bootstrap_id=self._new_root_name)
            self._bootstrap_parent = None
            self._initialize_custody(_remaining_b1_limits(NativeLimits.b1(parent_remaining_ms), parent_deadline))
            self._start_acquisition()
        except BaseException:
            if not win32.context_custody_unresolved(self):
                self._issuer_origin.close()  # only settled native custody permits origin disposal
            raise

    def _acquire(self):
        with self._serialized():
            self._state = "ACQUIRING"
            volume = self._track_open_root(self.anchor.volume_guid)
            self._volume_identity = ObjectIdentity(*win32._safe_metadata(volume, directory=True)[:2])
            parent = volume
            components = []
            for name in ("ProgramData", "InvestorIntelligenceGuidance"):
                parent = self._track_open_relative(parent, name, True, False)
                actual = ObjectIdentity(*win32._safe_metadata(parent, directory=True)[:2])
                components.append((name, actual))
            # Independently held protected ancestor must match the native descent.
            _, expected = self._issuer_origin.hold(provisioner_data_base(), directory=True)
            if (actual.volume_serial, actual.file_id) != expected:
                raise IdentityMismatchError("Issuer ancestry mismatch")
            base_parent = parent._request.parent
            parent.close()
            self._bootstrap_parent = win32._nt_open(base_parent, "InvestorIntelligenceGuidance", True, False,
                                                    self, namespace_access=True)
            self._live_operation = object()
            try:
                self.root_handle = win32.create_relative(self._bootstrap_parent, self._new_root_name, directory=True,
                    operation=self._live_operation, object_cap=self.budget.object_cap())
                win32.protect_issuer_object(self.root_handle, "root")
                components.append((self._new_root_name, ObjectIdentity(*win32._safe_metadata(self.root_handle, directory=True)[:2])))
                self.control_handle = win32.create_relative(self.root_handle, "control", directory=True,
                    operation=self._live_operation, object_cap=self.budget.object_cap())
                win32.protect_issuer_object(self.control_handle, "control")
                self.b1_handle = win32.create_relative(self.root_handle, "b1", directory=True,
                    operation=self._live_operation, object_cap=self.budget.object_cap())
                win32.protect_issuer_object(self.b1_handle, "b1")
            except BaseException as error:
                self._failure_primary = error
                raise  # UNKNOWN retains the exact operation/owners/origin
            self._live_operation = None
            self._root_components = tuple(components)
            self._state = "READY"

    def bind_anchor(self, input_digests):
        self._namespace_guard()
        if not self.coordination_handle or not self.journal_handle:
            raise MissingTrustedAnchorError("Issuer control objects missing")
        self.anchor = _validate_anchor_data(RootAnchor("guidance-provider-storage-v2", self._new_root_name,
            self.anchor.volume_guid, self._volume_identity, self._root_components,
            ObjectIdentity(*win32._safe_metadata(self.coordination_handle, directory=False)[:2]),
            ObjectIdentity(*win32._safe_metadata(self.journal_handle, directory=False)[:2]), 1, True,
            ObjectIdentity(*win32._safe_metadata(self.control_handle, directory=True)[:2]),
            ObjectIdentity(*win32._safe_metadata(self.b1_handle, directory=True)[:2]), tuple(sorted(input_digests.items()))))
        return self.anchor

    def close(self):
        super().close()  # UNKNOWN retains native context AND independent origin; no workaround
        self._issuer_origin.close()


def provisioner_data_base():
    from revenue_guidance_provisioner import DATA_BASE
    return DATA_BASE


def _remaining_b1_limits(limits, parent_deadline):
    # Only consulted AFTER independent authority; no backend clock on unavailable
    # authority. Absolute trusted host request deadline includes authority work.
    if type(parent_deadline) is not float or not 0 < parent_deadline < float("inf"):
        raise BudgetExceededError("Actual parent deadline required for B1")
    remaining = int((parent_deadline - time.monotonic()) * 1000)
    if remaining <= 0:
        raise BudgetExceededError("Parent budget exhausted before native acquisition")
    return NativeLimits.b1(min(limits.max_elapsed_ms, remaining))


def open_storage_lease(candidate: RootAnchor, limits: NativeLimits, *, parent_deadline=None) -> NativeStorageLease:
    return NativeStorageLease(candidate, limits, parent_deadline=parent_deadline)
