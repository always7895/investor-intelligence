"""M5: owned Strata instance controller and cooperative GPU reservation (LIBRARY ONLY; tests written, NOT_RUN).

Implements the dual-accepted M4 design (docs/MODEL_RUNTIME_MIGRATION.md, "M4: owned replacement protocol design"): ownership and
admission prerequisites, the state machine PRECHECK -> RESERVED -> ADMISSION_CLOSED -> DRAINED -> OWNED_OLD_EXITED ->
CANDIDATE_READY -> VERIFIED -> COMMITTED -> ADMISSION_OPEN with its drain barrier, rollback, RECOVERY_REQUIRED and bounded
hash-chained transition receipts.

NOT WIRED, NO DEFAULT ACTIVATION: no installed task, launcher, scheduler, installer or CLI imports this module and it has no
command-line entry point. It never starts a process, opens a network connection or inspects another project by itself: every side
effect goes through a REQUIRED injected collaborator (admitted native launcher, OS lock provider, GPU/Herdr/listener observer,
selected-only HTTP transport, request-intent store, clock) and the repository ships no native launcher, lock provider, observer or
transport. A real run still needs the separate Q2 trial GO (R/OPERATOR-DECISIONS-Q1-Q3-20261006.txt) with admitted native
adapters, exact executable/config/model/input pins, resource limits and native ownership, lock, exit and GPU-release proof.
In-memory fakes prove only the protocol sequencing, never Windows handles, job containment, OS locks or GPU release.

Fail-closed rules encoded here (operator: no second model, no shared interruption):
- Ports 5000, 8000, 8001, 8080, 8081 and 8814 are never an owned port and are never contacted. The shared :8080/:8081 Strata is
  only OBSERVED through the admitted observer and must be ABSENT at every check: a running shared instance blocks the run; it is
  never adopted, drained or stopped.
- Ownership is the handle object THIS controller's launcher returned plus its recorded (pid, creation) identity. There is no stop
  by PID, port, image name or file; a handle from anywhere else, identity drift or a controller restart cannot prove ownership.
- One model at a time: a candidate starts only after the old owned process and every accounted job member exited and the
  observer shows the GPU and the enrolled port released under the held reservation. No unload/load endpoint is used and weights
  are never replaced in place.
- A lost lock, lease or acknowledgment, a journal/gate/intent write or readback failure, unproven stop/exit or GPU release and a
  failed rollback close admission, make a request intent this controller wrote unavailable and return RECOVERY_REQUIRED; nothing
  is retried, reclaimed, killed or guessed. recover() is read-only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STATES = ('PRECHECK', 'RESERVED', 'ADMISSION_CLOSED', 'DRAINED', 'OWNED_OLD_EXITED', 'CANDIDATE_READY', 'VERIFIED',
          'COMMITTED', 'ADMISSION_OPEN')
# Journal-only outcome states outside the forward path above.
OUTCOME_STATES = ('REFUSED', 'TRANSITION_FAILED', 'ABORTED_RESTORED', 'ROLLBACK_STARTED', 'ROLLED_BACK', 'RELEASED',
                  'RECOVERY_REQUIRED')
PROTECTED_PORTS = frozenset({5000, 8000, 8001, 8080, 8081, 8814})
SHARED_PORTS = ('8080', '8081')
HTTP_ROUTES = frozenset({('GET', '/health'), ('GET', '/v1/models'), ('POST', '/v1/chat/completions')})
MAX_RECEIPT_BYTES = 8192
MAX_BODY_BYTES = 262144
MAX_CONFIG_BYTES = 1048576
ZERO_SHA256 = '0' * 64
LIMITS = {'ack_seconds': (1, 600), 'drain_seconds': (1, 1800), 'stop_seconds': (1, 600), 'startup_seconds': (1, 1800),
          'answer_seconds': (1, 180), 'lease_seconds': (60, 86400), 'observation_max_age_seconds': (1, 60),
          'log_quiet_seconds': (0, 86400), 'idle_gpu_memory_mib': (0, 131072), 'model_gpu_memory_mib': (1, 131072),
          'poll_seconds': (1, 60)}
_PIN_KEYS = frozenset({'schema_version', 'design_sha256', 'go_sha256', 'source_sha256', 'harness_sha256', 'observer_sha256',
                       'owner', 'holder', 'port', 'requesters', 'min_context', 'limits'})
_SPEC_KEYS = frozenset({'schema_version', 'executable', 'executable_sha256', 'model_file', 'model_sha256', 'config_file',
                        'config_sha256', 'argv', 'model_id', 'profile'})
_RECEIPT_FIELDS = frozenset({'hashes', 'instance', 'acks', 'pending', 'metadata', 'resources', 'deadline_seconds', 'cleanup',
                             'readback', 'invalidated_binding_sha256', 'manifest', 'reason'})
# Refused in startup arguments and in the engine configuration: hooks, shells, downloads, credentials and fallbacks.
_FORBIDDEN_TEXT = ('hook', 'before_load', 'download', '://', 'shell', 'powershell', 'cmd.exe', 'curl', 'wget', 'credential',
                   'apikey', 'api_key', 'cloud', 'fallback')
_HEX64 = re.compile(r'[0-9a-f]{64}')
_HEX32 = re.compile(r'[0-9a-f]{32}')
_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')
_RUN = re.compile(r'[a-z0-9-]{1,64}')
_REASON = re.compile(r'[A-Z][A-Z0-9_]{0,63}')
_MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}')
_REPARSE_POINT = 0x400


class OwnedInstanceUnavailable(ValueError):
    """Finite sanitized reason code only; never a raw payload, path, command line, header or credential."""


class _RecoveryRequired(OwnedInstanceUnavailable):
    """Internal: authority, evidence or exit proof was lost; never answered by an automatic restore or rollback."""


def _fail(reason: str) -> Any:
    raise OwnedInstanceUnavailable(reason)


def _code(error: BaseException, default: str) -> str:
    text = str(error)
    return text if isinstance(error, OwnedInstanceUnavailable) and _REASON.fullmatch(text) else default


def _shared() -> Any:
    try:
        import v213_model_profile as shared  # the ONE seven-field profile, binding schema and digests
    except Exception:
        raise OwnedInstanceUnavailable('PROFILE_HELPER_UNAVAILABLE') from None
    return shared


def _int(value: Any, lower: int, upper: int) -> bool:
    return type(value) is int and lower <= value <= upper


def _identity_ok(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and len(value) == 2 and all(_int(item, 1, 1 << 63) for item in value)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii') + b'\n'


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _new_id(prefix: str) -> str:
    return prefix + '-' + os.urandom(8).hex()


def _plain(path: Path, reason: str, *, directory: bool = False) -> os.stat_result:
    """No-follow check: a plain directory or regular file, never a link or reparse point."""
    try:
        info = os.lstat(path)
    except OSError:
        raise OwnedInstanceUnavailable(reason) from None
    kind = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not kind or getattr(info, 'st_file_attributes', 0) & _REPARSE_POINT:
        raise OwnedInstanceUnavailable(reason)
    return info


def _read_bytes(path: Path, limit: int, reason: str) -> bytes:
    _plain(path, reason)
    try:
        with open(path, 'rb') as handle:
            raw = handle.read(limit + 1)
    except OSError:
        raise OwnedInstanceUnavailable(reason) from None
    if len(raw) > limit:
        raise OwnedInstanceUnavailable(reason)
    return raw


def _parse(raw: bytes, limit: int, reason: str) -> Any:
    try:
        return _shared().strict_object(raw.decode('utf-8'), limit)
    except (UnicodeError, ValueError):
        raise OwnedInstanceUnavailable(reason) from None


def _matches(path: Path, data: bytes) -> bool:
    try:
        return _read_bytes(path, len(data), 'RECORD_MISMATCH') == data
    except OwnedInstanceUnavailable:
        return False


def _write_new(path: Path, data: bytes, reason: str) -> None:
    """Exclusive create (unique evidence is never overwritten), fsync, then byte readback."""
    try:
        with open(path, 'xb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        raise OwnedInstanceUnavailable(reason) from None
    if not _matches(path, data):
        raise OwnedInstanceUnavailable(reason)


def _replace(path: Path, data: bytes, reason: str) -> None:
    """Atomic replace of a record the caller itself owns (its gate, reservation or acknowledgment), fsync, then byte readback."""
    name = None
    try:
        fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    except OSError:
        raise OwnedInstanceUnavailable(reason) from None
    finally:
        if name is not None and os.path.lexists(name):
            try:
                os.unlink(name)
            except OSError:
                pass
    if not _matches(path, data):
        raise OwnedInstanceUnavailable(reason)


def _release(lock: Any) -> None:
    try:
        lock.release()
    except Exception:
        pass  # an OS lock that cannot be released stays held until its process exits: still exclusive, never stolen


def file_sha256(path_text: str) -> str:
    """SHA-256 of a pre-existing plain local file; refuses links, reparse points and a file that changed while it was hashed."""
    path = Path(path_text)
    before = _plain(path, 'SPEC_FILE_UNAVAILABLE')
    digest = hashlib.sha256()
    try:
        with open(path, 'rb') as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b''):
                digest.update(chunk)
    except OSError:
        raise OwnedInstanceUnavailable('SPEC_FILE_UNAVAILABLE') from None
    after = _plain(path, 'SPEC_FILE_UNAVAILABLE')
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise OwnedInstanceUnavailable('SPEC_FILE_CHANGED')
    return digest.hexdigest()


def validate_pins(value: Any) -> dict[str, Any]:
    """The bounded GO pins: design/GO/source/harness/observer digests, owner, reservation holder, one dedicated non-shared
    loopback port, the closed requester roster, the minimum context and every deadline/resource ceiling (no defaults)."""
    if (not isinstance(value, dict) or set(value) != _PIN_KEYS or type(value['schema_version']) is not int
            or value['schema_version'] != SCHEMA_VERSION):
        _fail('PINS_SCHEMA_INVALID')
    for key in ('design_sha256', 'go_sha256', 'source_sha256', 'harness_sha256', 'observer_sha256'):
        if not isinstance(value[key], str) or not _HEX64.fullmatch(value[key]):
            _fail('PINS_DIGEST_INVALID')
    if not all(isinstance(value[key], str) and _ID.fullmatch(value[key]) for key in ('owner', 'holder')):
        _fail('PINS_IDENTITY_INVALID')
    if not _int(value['port'], 1024, 65535) or value['port'] in PROTECTED_PORTS:
        _fail('PINS_PORT_PROTECTED')
    requesters = value['requesters']
    if (not isinstance(requesters, list) or not 1 <= len(requesters) <= 16
            or not all(isinstance(item, str) and _ID.fullmatch(item) for item in requesters)
            or len(set(requesters)) != len(requesters)):
        _fail('PINS_REQUESTERS_INVALID')
    if not _int(value['min_context'], 1, 1073741824):
        _fail('PINS_CONTEXT_INVALID')
    limits = value['limits']
    # The lease must outlive every pinned wait between two renewals (requester acks plus the answer of a refused drain, old
    # stop plus release, startup plus answer); the fixed HTTP timeouts and observer/journal time are the GO's margin.
    if (not isinstance(limits, dict) or set(limits) != set(LIMITS)
            or not all(_int(limits[key], lower, upper) for key, (lower, upper) in LIMITS.items())
            or limits['idle_gpu_memory_mib'] >= limits['model_gpu_memory_mib']
            or limits['lease_seconds'] <= limits['poll_seconds'] + max(limits['ack_seconds'] + limits['answer_seconds'],
                                                                       2 * limits['stop_seconds'],
                                                                       limits['startup_seconds'] + limits['answer_seconds'])):
        _fail('PINS_LIMITS_INVALID')
    return json.loads(json.dumps(value))


def prepare_instance(spec: Any, port: int) -> dict[str, Any]:
    """Validates ONE pinned instance spec for the enrolled port and hashes its pre-existing local executable, weights and config.
    The original seven-field profile identity and the separate binding identity are the shared v213_model_profile ones; nothing
    is downloaded, executed or substituted."""
    shared = _shared()
    if not _int(port, 1024, 65535) or port in PROTECTED_PORTS:
        _fail('PINS_PORT_PROTECTED')
    if (not isinstance(spec, dict) or set(spec) != _SPEC_KEYS or type(spec['schema_version']) is not int
            or spec['schema_version'] != SCHEMA_VERSION):
        _fail('SPEC_SCHEMA_INVALID')
    try:
        profile = shared.validate_profile(spec['profile'])
    except ValueError:
        raise OwnedInstanceUnavailable('SPEC_PROFILE_INVALID') from None
    if not isinstance(spec['model_id'], str) or not _MODEL.fullmatch(spec['model_id']) or spec['model_id'] != profile['model']:
        _fail('SPEC_MODEL_PROFILE_MISMATCH')
    for key in ('executable', 'model_file', 'config_file'):
        text = spec[key]
        if not isinstance(text, str) or not 0 < len(text) <= 1024 or '\x00' in text or not os.path.isabs(text):
            _fail('SPEC_PATH_INVALID')
    for key in ('executable_sha256', 'model_sha256', 'config_sha256'):
        if not isinstance(spec[key], str) or not _HEX64.fullmatch(spec[key]):
            _fail('SPEC_DIGEST_INVALID')
    argv = spec['argv']
    if (not isinstance(argv, list) or not 1 <= len(argv) <= 64
            or not all(isinstance(arg, str) and 0 < len(arg) <= 512 and not {'\x00', '\r', '\n'} & set(arg) for arg in argv)):
        _fail('SPEC_ARGV_INVALID')
    port_hits = 0
    for arg in argv:
        # The pinned local model/config paths are hash-bound files, not options; every other argument is screened.
        if arg not in (spec['model_file'], spec['config_file']) and any(word in arg.lower() for word in _FORBIDDEN_TEXT):
            _fail('SPEC_ARGV_FORBIDDEN')
        values = {arg, arg.rsplit('=', 1)[-1], arg.rsplit(':', 1)[-1]}
        numbers = {int(text) for text in values if text.isascii() and text.isdigit() and len(text) <= 6}
        if numbers & PROTECTED_PORTS:
            _fail('SPEC_ARGV_PROTECTED_PORT')
        port_hits += port in numbers
    if port_hits != 1:
        _fail('SPEC_ARGV_PORT_UNPINNED')
    config = _read_bytes(Path(spec['config_file']), MAX_CONFIG_BYTES, 'SPEC_CONFIG_UNAVAILABLE')
    try:
        config_text = config.decode('utf-8-sig').lower()
    except UnicodeError:
        raise OwnedInstanceUnavailable('SPEC_CONFIG_UNAVAILABLE') from None
    if any(word in config_text for word in _FORBIDDEN_TEXT):
        _fail('SPEC_CONFIG_FORBIDDEN')
    hashes = {'executable': file_sha256(spec['executable']), 'model': file_sha256(spec['model_file']), 'config': _sha(config)}
    if hashes != {'executable': spec['executable_sha256'], 'model': spec['model_sha256'], 'config': spec['config_sha256']}:
        _fail('SPEC_HASH_MISMATCH')
    try:
        profile_digest = shared.profile_sha256(profile)
        binding = shared.validate_binding({'schema_version': 1, 'engine': 'strata', 'base_url': 'http://127.0.0.1:' + str(port),
                                           'model': spec['model_id'], 'model_profile_sha256': profile_digest,
                                           'qualification': 'UNQUALIFIED'}, profile)
        hashes.update(profile=profile_digest, binding=shared.binding_sha256(binding, profile), argv=_sha(_canonical(argv)))
    except ValueError:
        raise OwnedInstanceUnavailable('SPEC_BINDING_INVALID') from None
    return {'spec': json.loads(json.dumps(spec)), 'profile': profile, 'binding': binding, 'hashes': hashes}


class SystemClock:
    """Real time source for a FUTURE admitted run (tests inject a fake): monotonic() for deadlines, time() for UTC receipts and
    the reservation lease, sleep() between bounded polls."""

    def monotonic(self) -> float:
        return time.monotonic()

    def time(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def _reservation_ack(participant: str, reservation_id: str) -> bytes:
    return _canonical({'schema_version': 1, 'reservation_id': reservation_id, 'participant': participant, 'state': 'YIELDED'})


class GpuReservation:
    """Cooperative, exclusive GPU-use reservation shared by every enrolled participant of ONE GPU (M4 prerequisite 1).

    The medium is an existing operator-chosen directory holding the closed roster participants.json
    ({"schema_version":1,"participants":[ids]}), the reservation record and one acknowledgment file per participant.
    Exclusivity is the non-blocking OS-held lock from the injected provider on reservation.lock PLUS the exclusively created
    record. A present record is never reclaimed, aged out or overwritten by anyone but its holder (a crashed holder's record is
    RESERVATION_PRESENT_RECOVERY_REQUIRED). Every other roster participant must acknowledge the exact reservation id
    (acknowledge_reservation) before acquire() returns; a missing, stale or withdrawn acknowledgment, an expired lease, a changed
    roster or record and a lost OS lock are refusals, never permission. File age, a PID, a port or an idle sample prove nothing."""

    ROSTER = 'participants.json'
    RECORD = 'reservation.json'
    LOCK = 'reservation.lock'

    def __init__(self, directory: str | os.PathLike[str], *, holder: str, locks: Any, clock: Any):
        if not isinstance(holder, str) or not _ID.fullmatch(holder):
            _fail('RESERVATION_HOLDER_INVALID')
        self.directory = Path(directory)
        self.holder = holder
        self._locks = locks
        self._clock = clock
        self._lock: Any = None
        self._record: dict[str, Any] | None = None
        self._bytes = b''
        self._roster: tuple[tuple[str, ...], str] | None = None

    def _read_roster(self) -> tuple[tuple[str, ...], str]:
        raw = _read_bytes(self.directory / self.ROSTER, 4096, 'RESERVATION_ROSTER_INVALID')
        value = _parse(raw, 4096, 'RESERVATION_ROSTER_INVALID')
        members = value.get('participants') if isinstance(value, dict) else None
        if (not isinstance(value, dict) or set(value) != {'schema_version', 'participants'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1
                or not isinstance(members, list) or not 1 <= len(members) <= 16
                or not all(isinstance(item, str) and _ID.fullmatch(item) for item in members)
                or len(set(members)) != len(members) or self.holder not in members):
            _fail('RESERVATION_ROSTER_INVALID')
        return tuple(sorted(members)), _sha(raw)

    def _missing(self, reservation_id: str, others: list[str]) -> list[str]:
        return [item for item in others
                if not _matches(self.directory / ('ack-' + item + '.json'), _reservation_ack(item, reservation_id))]

    def acquire(self, *, lease_seconds: int, ack_seconds: int, poll_seconds: int) -> dict[str, Any]:
        if self._lock is not None:
            _fail('RESERVATION_ALREADY_HELD')
        if not (_int(lease_seconds, *LIMITS['lease_seconds']) and _int(ack_seconds, *LIMITS['ack_seconds'])
                and _int(poll_seconds, *LIMITS['poll_seconds'])):
            _fail('RESERVATION_BOUNDS_INVALID')
        _plain(self.directory, 'RESERVATION_MEDIUM_UNAVAILABLE', directory=True)
        roster = self._read_roster()
        try:
            lock = self._locks.acquire(str(self.directory / self.LOCK))
        except Exception:
            raise OwnedInstanceUnavailable('RESERVATION_LOCK_UNAVAILABLE') from None
        if not lock:
            _fail('RESERVATION_BUSY')
        path = self.directory / self.RECORD
        data = b''
        created = False
        try:
            if os.path.lexists(path):
                _fail('RESERVATION_PRESENT_RECOVERY_REQUIRED')  # never reclaimed by age, PID or lock state
            record = {'schema_version': 1, 'reservation_id': os.urandom(16).hex(), 'holder': self.holder,
                      'roster_sha256': roster[1], 'expires_epoch': int(self._clock.time()) + lease_seconds}
            data = _canonical(record)
            _write_new(path, data, 'RESERVATION_WRITE_FAILED')
            created = True
            others = [item for item in roster[0] if item != self.holder]
            deadline = self._clock.monotonic() + ack_seconds
            while self._missing(record['reservation_id'], others):
                if self._clock.monotonic() >= deadline:
                    _fail('RESERVATION_ACK_MISSING')
                self._clock.sleep(poll_seconds)
            if self._read_roster() != roster:
                _fail('RESERVATION_ROSTER_CHANGED')
        except BaseException:
            if created and _matches(path, data):
                try:
                    os.unlink(path)  # only this call's own, unchanged record
                except OSError:
                    pass
            _release(lock)
            raise
        self._lock, self._record, self._bytes, self._roster = lock, record, data, roster
        return {'reservation_id': record['reservation_id'], 'participants': others, 'roster_sha256': roster[1],
                'expires_epoch': record['expires_epoch']}

    def verify(self) -> dict[str, Any]:
        if self._lock is None or self._record is None or self._roster is None:
            _fail('RESERVATION_MISSING')
        try:
            held = self._lock.held() is True
        except Exception:
            held = False
        if not held:
            _fail('RESERVATION_LOCK_LOST')
        if not _matches(self.directory / self.RECORD, self._bytes):
            _fail('RESERVATION_RECORD_CHANGED')
        if not self._clock.time() < self._record['expires_epoch']:
            _fail('RESERVATION_EXPIRED')
        if self._read_roster() != self._roster:
            _fail('RESERVATION_ROSTER_CHANGED')
        others = [item for item in self._roster[0] if item != self.holder]
        if self._missing(self._record['reservation_id'], others):
            _fail('RESERVATION_ACK_WITHDRAWN')
        return {'reservation_id': self._record['reservation_id'], 'participants': others,
                'expires_epoch': self._record['expires_epoch']}

    def renew(self, lease_seconds: int) -> dict[str, Any]:
        """Extends ONLY a still valid lease; an expired one stays expired."""
        self.verify()
        if not _int(lease_seconds, *LIMITS['lease_seconds']):
            _fail('RESERVATION_BOUNDS_INVALID')
        record = dict(self._record or {}, expires_epoch=int(self._clock.time()) + lease_seconds)
        data = _canonical(record)
        _replace(self.directory / self.RECORD, data, 'RESERVATION_WRITE_FAILED')
        self._record, self._bytes = record, data
        return self.verify()

    def release(self) -> None:
        """Removes ONLY this holder's own unchanged record while its OS lock is still held, then releases that lock."""
        if self._lock is None:
            _fail('RESERVATION_MISSING')
        try:
            held = self._lock.held() is True
        except Exception:
            held = False
        if not held:
            _fail('RESERVATION_LOCK_LOST')
        path = self.directory / self.RECORD
        if not _matches(path, self._bytes):
            _fail('RESERVATION_RECORD_CHANGED')
        try:
            os.unlink(path)
        except OSError:
            raise OwnedInstanceUnavailable('RESERVATION_RELEASE_FAILED') from None
        _release(self._lock)
        self._lock, self._record, self._bytes, self._roster = None, None, b'', None


def read_reservation(directory: str | os.PathLike[str]) -> dict[str, Any] | None:
    """Participant side, read-only: the current reservation record, or None when no reservation is recorded."""
    path = Path(directory) / GpuReservation.RECORD
    if not os.path.lexists(path):
        return None
    value = _parse(_read_bytes(path, 4096, 'RESERVATION_RECORD_INVALID'), 4096, 'RESERVATION_RECORD_INVALID')
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'reservation_id', 'holder', 'roster_sha256', 'expires_epoch'}
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or not isinstance(value['reservation_id'], str) or not _HEX32.fullmatch(value['reservation_id'])
            or not isinstance(value['holder'], str) or not _ID.fullmatch(value['holder'])
            or not isinstance(value['roster_sha256'], str) or not _HEX64.fullmatch(value['roster_sha256'])
            or not _int(value['expires_epoch'], 0, 1 << 40)):
        _fail('RESERVATION_RECORD_INVALID')
    return value


def acknowledge_reservation(directory: str | os.PathLike[str], participant: str, reservation_id: str) -> None:
    """Participant side: written ONLY by that participant once it has stopped its GPU work and will start none until the record
    is gone. Binds the exact reservation id, so an acknowledgment never carries over to a later reservation."""
    if not isinstance(participant, str) or not _ID.fullmatch(participant):
        _fail('RESERVATION_PARTICIPANT_INVALID')
    record = read_reservation(directory)
    if record is None or record['reservation_id'] != reservation_id or record['holder'] == participant:
        _fail('RESERVATION_ID_MISMATCH')
    _replace(Path(directory) / ('ack-' + participant + '.json'), _reservation_ack(participant, reservation_id),
             'RESERVATION_ACK_WRITE_FAILED')


def _gate_ack(owner: str, requester: str, generation: int) -> bytes:
    return _canonical({'schema_version': 1, 'owner': owner, 'requester': requester, 'generation': generation, 'state': 'CLOSED'})


def read_gate(directory: str | os.PathLike[str], owner: str) -> dict[str, Any]:
    """Read-only: the owner's gate record; an absent record is generation 0, CLOSED (nothing admitted)."""
    path = Path(directory) / AdmissionGate.STATE
    if not os.path.lexists(path):
        return {'schema_version': 1, 'owner': owner, 'generation': 0, 'state': 'CLOSED', 'binding_sha256': None, 'txn': None}
    value = _parse(_read_bytes(path, 4096, 'GATE_RECORD_INVALID'), 4096, 'GATE_RECORD_INVALID')
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'owner', 'generation', 'state', 'binding_sha256', 'txn'}
            or type(value['schema_version']) is not int or value['schema_version'] != 1 or not _int(value['generation'], 0, 1 << 31)
            or not (value['txn'] is None or (isinstance(value['txn'], str) and _RUN.fullmatch(value['txn'])))
            or not ((value['state'] == 'OPEN' and isinstance(value['binding_sha256'], str) and _HEX64.fullmatch(value['binding_sha256']))
                    or (value['state'] == 'CLOSED' and value['binding_sha256'] is None))):
        _fail('GATE_RECORD_INVALID')
    if value['owner'] != owner:
        _fail('GATE_OWNER_MISMATCH')
    return value


class AdmissionGate:
    """Owner-only admission gate of ONE enrolled instance (M4 drain barrier); it never touches another project's schedules.

    gate.json holds the generation, OPEN (with the admitted binding digest) or CLOSED. Every requester of this owner (gateway,
    watchdog, retry/reload path, scheduled producer) must call requester_admitted() before each new request and, once it has
    stopped issuing work, acknowledge the CLOSED generation it saw (requester_acknowledge). Requesters are NOT wired to this gate
    in this lane, so a real drain stays ineligible until they are."""

    STATE = 'gate.json'

    def __init__(self, directory: str | os.PathLike[str], *, owner: str, requesters: Any):
        if not isinstance(owner, str) or not _ID.fullmatch(owner):
            _fail('GATE_OWNER_INVALID')
        if (not isinstance(requesters, (list, tuple)) or not 1 <= len(requesters) <= 16
                or not all(isinstance(item, str) and _ID.fullmatch(item) for item in requesters)
                or len(set(requesters)) != len(requesters)):
            _fail('GATE_REQUESTERS_INVALID')
        self.directory = Path(directory)
        self.owner = owner
        self.requesters = tuple(sorted(requesters))

    def read(self) -> dict[str, Any]:
        _plain(self.directory, 'GATE_UNAVAILABLE', directory=True)
        return read_gate(self.directory, self.owner)

    def _set(self, state: str, txn: str, binding_sha256: str | None) -> int:
        current = self.read()
        record = {'schema_version': 1, 'owner': self.owner, 'generation': current['generation'] + 1, 'state': state,
                  'binding_sha256': binding_sha256, 'txn': txn}
        _replace(self.directory / self.STATE, _canonical(record), 'GATE_WRITE_FAILED')
        if self.read() != record:
            _fail('GATE_WRITE_FAILED')
        return record['generation']

    def close(self, txn: str) -> int:
        return self._set('CLOSED', txn, None)

    def open(self, txn: str, binding_sha256: str) -> int:
        if not isinstance(binding_sha256, str) or not _HEX64.fullmatch(binding_sha256):
            _fail('GATE_BINDING_INVALID')
        return self._set('OPEN', txn, binding_sha256)

    def acknowledged(self, generation: int) -> list[str]:
        return [item for item in self.requesters
                if _matches(self.directory / ('ack-' + item + '.json'), _gate_ack(self.owner, item, generation))]


def requester_admitted(directory: str | os.PathLike[str], owner: str) -> dict[str, Any] | None:
    """Requester side: call before every new request, retry, reload or reconnect. None (closed, unknown or unreadable) means do
    not send anything to this owner's instance."""
    try:
        record = read_gate(directory, owner)
    except OwnedInstanceUnavailable:
        return None
    if record['state'] != 'OPEN':
        return None
    return {'generation': record['generation'], 'binding_sha256': record['binding_sha256']}


def requester_acknowledge(directory: str | os.PathLike[str], owner: str, requester: str, generation: int) -> None:
    """Requester side: acknowledges the CLOSED generation it observed, only after it stopped issuing new work for this owner."""
    if not isinstance(requester, str) or not _ID.fullmatch(requester):
        _fail('GATE_REQUESTER_INVALID')
    record = read_gate(directory, owner)
    if record['state'] != 'CLOSED' or record['generation'] != generation:
        _fail('GATE_GENERATION_MISMATCH')
    _replace(Path(directory) / ('ack-' + requester + '.json'), _gate_ack(owner, requester, generation), 'GATE_ACK_WRITE_FAILED')


class Journal:
    """Append-only transition receipts: one exclusively created file per entry (never overwritten), each bounded, hash-chained
    to its predecessor, fsynced and read back."""

    def __init__(self, directory: str | os.PathLike[str]):
        self.directory = Path(directory)
        try:
            os.mkdir(self.directory)  # a new session directory; an existing one is never reused
        except OSError:
            raise OwnedInstanceUnavailable('JOURNAL_UNAVAILABLE') from None
        self.count = 0
        self.last_sha256 = ZERO_SHA256

    def append(self, record: dict[str, Any]) -> str:
        entry = dict(record, seq=self.count + 1, prev_sha256=self.last_sha256)
        try:
            data = _canonical(entry)
        except (TypeError, ValueError):
            raise OwnedInstanceUnavailable('RECEIPT_SCHEMA_INVALID') from None
        if len(data) > MAX_RECEIPT_BYTES:
            _fail('RECEIPT_BOUNDS')
        _write_new(self.directory / ('%04d.json' % entry['seq']), data, 'JOURNAL_WRITE_FAILED')
        self.count += 1
        self.last_sha256 = _sha(data)
        return self.last_sha256


def read_journal(directory: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Read-only: every entry in order with its sequence, hash chain, bound and canonical bytes verified."""
    folder = Path(directory)
    _plain(folder, 'JOURNAL_INTEGRITY_LOST', directory=True)
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        raise OwnedInstanceUnavailable('JOURNAL_INTEGRITY_LOST') from None
    if not names or names != ['%04d.json' % index for index in range(1, len(names) + 1)]:
        _fail('JOURNAL_INTEGRITY_LOST')
    entries: list[dict[str, Any]] = []
    previous = ZERO_SHA256
    for index, name in enumerate(names, 1):
        raw = _read_bytes(folder / name, MAX_RECEIPT_BYTES, 'JOURNAL_INTEGRITY_LOST')
        try:
            value = json.loads(raw.decode('ascii'))
            canonical = _canonical(value)
        except (UnicodeError, ValueError, TypeError):
            raise OwnedInstanceUnavailable('JOURNAL_INTEGRITY_LOST') from None
        if (not isinstance(value, dict) or value.get('seq') != index or value.get('prev_sha256') != previous
                or canonical != raw):
            _fail('JOURNAL_INTEGRITY_LOST')
        entries.append(value)
        previous = _sha(raw)
    return entries


_RECOVERY_PHASES = {
    'PRECHECK': 'SESSION_INTERRUPTED', 'RESERVED': 'SESSION_INTERRUPTED', 'ADMISSION_OPEN': 'SESSION_INTERRUPTED',
    'REFUSED': 'SESSION_INTERRUPTED', 'ABORTED_RESTORED': 'SESSION_INTERRUPTED', 'ROLLED_BACK': 'SESSION_INTERRUPTED',
    'ADMISSION_CLOSED': 'ADMISSION_CLOSED_OLD_RUNNING', 'DRAINED': 'ADMISSION_CLOSED_OLD_RUNNING',
    'OWNED_OLD_EXITED': 'OLD_EXITED_NO_CANDIDATE', 'CANDIDATE_READY': 'CANDIDATE_READY_POINTER_NOT_COMMITTED',
    'VERIFIED': 'CANDIDATE_READY_POINTER_NOT_COMMITTED', 'COMMITTED': 'COMMITTED_ADMISSION_NOT_OPEN',
    'TRANSITION_FAILED': 'ROLLBACK_INCOMPLETE', 'ROLLBACK_STARTED': 'ROLLBACK_INCOMPLETE',
    'RECOVERY_REQUIRED': 'RECOVERY_REQUIRED_RECORDED'}


def recover(session_dir: str | os.PathLike[str], gate: AdmissionGate | None = None) -> dict[str, Any]:
    """READ-ONLY reconciliation of one session journal (and optionally the owner's gate record) after an interruption.

    It never stops, starts, kills, reclaims, renews, releases or rewrites anything, so repeated calls are idempotent. A restarted
    controller holds no retained handle, so nothing here can prove ownership: every phase except CLEAN (the session ended with
    RELEASED, or was refused before any reservation) is RECOVERY_REQUIRED for a separate bounded recovery GO that establishes
    ownership afresh. Phases name the interrupted point: candidate ready but pointer not committed, committed but admission not
    open, failed or incomplete rollback, admission closed with the old instance running, and a lost session/lease."""
    result: dict[str, Any] = {'outcome': 'RECOVERY_REQUIRED', 'phase': 'JOURNAL_INTEGRITY_LOST', 'entries': 0, 'last_state': None,
                              'last_sha256': None, 'run_id': None, 'generation': None, 'reason': None, 'actions': []}
    try:
        entries = read_journal(session_dir)
    except OwnedInstanceUnavailable:
        return result
    last = entries[-1]
    states = [entry.get('state') for entry in entries]
    result.update(entries=len(entries), last_state=last.get('state'), last_sha256=_sha(_canonical(last)),
                  run_id=last.get('run_id'), generation=last.get('generation'), reason=last.get('outcome'))
    if last.get('state') == 'RELEASED' or (last.get('state') == 'REFUSED' and 'RESERVED' not in states):
        phase = 'CLEAN'
    else:
        phase = _RECOVERY_PHASES.get(last.get('state'), 'JOURNAL_INTEGRITY_LOST')
    if gate is not None:
        try:
            record: dict[str, Any] | None = gate.read()
        except OwnedInstanceUnavailable:
            record = None
        if record is None:
            phase = 'GATE_UNREADABLE'
        elif ((type(last.get('generation')) is int and record['generation'] != last['generation'])
              or (phase == 'CLEAN' and record['state'] != 'CLOSED')):
            phase = 'GENERATION_DISAGREEMENT'
    result.update(phase=phase, outcome='CLEAN' if phase == 'CLEAN' else 'RECOVERY_REQUIRED')
    return result


class ProfileIntent:
    """Request-intent store over the EXISTING shared barrier: v213_model_profile.save_binding (pending marker, profile, selection,
    intent pointer last) and resolve_binding for the readback. It writes the user's intent ONLY when a controller transaction
    commits, or marks it unavailable on RECOVERY_REQUIRED after this controller wrote it."""

    def __init__(self, root: str | os.PathLike[str]):
        self._root = str(root)

    def snapshot(self) -> dict[str, Any]:
        resolved = _shared().resolve_binding(self._root)
        if resolved['mode'] != 'EXPLICIT_STRATA':
            return {'mode': 'LEGACY_ABSENT', 'binding_sha256': None, 'profile_sha256': None}
        return {'mode': 'EXPLICIT_STRATA', 'binding_sha256': resolved['binding_sha256'],
                'profile_sha256': resolved['profile_sha256']}

    def commit(self, binding: dict[str, Any], profile: dict[str, Any]) -> None:
        _shared().save_binding(self._root, {'root': self._root, 'base_url': binding['base_url'], 'model': binding['model'],
                                            'profile': profile})

    def make_unavailable(self) -> None:
        """Leaves the deliberate invalid pending marker save_binding writes first, so every resolver refuses (never legacy)."""
        _, intent, _, _ = _shared()._user_paths()
        _replace(Path(intent), b'{', 'INTENT_UNAVAILABLE_UNPROVEN')


class OwnedStrataController:
    """One controller session for ONE enrolled owned Strata instance on a dedicated, non-shared loopback port.

    open() -> start(spec) -> replace(spec) ... -> shutdown(). Collaborators (all required, none defaulted):
    launcher.harness_sha256 and launcher.launch(argv_tuple, run_nonce=hex) -> handle with .pid, .creation_time, .poll(),
    .terminate(), .wait(seconds) -> bool and .job_members() -> [[pid, creation], ...] of its own job (an admitted native harness);
    http.request(method, url, payload=, timeout=, max_bytes=) -> parsed JSON (selected-only, used for the owned port only);
    observer.snapshot() -> closed observation dict (GPU processes/memory/utilization, foreign Herdr GPU tasks, listeners on
    :8080, :8081 and the enrolled port, owned pending work, direct clients, shared log age); locks.acquire(path) -> held lock or
    None (non-blocking, never stolen); intent.snapshot()/commit(binding, profile)/make_unavailable() (ProfileIntent);
    clock.monotonic()/time()/sleep() (SystemClock). A failing transition returns REFUSED, REFUSED_RESTORED, ROLLED_BACK or
    RECOVERY_REQUIRED; after RECOVERY_REQUIRED this object refuses every further operation."""

    def __init__(self, *, pins: Any, state_dir: str | os.PathLike[str], launcher: Any, http: Any, observer: Any, locks: Any,
                 reservation: GpuReservation, gate: AdmissionGate, intent: Any, clock: Any):
        self._pins = validate_pins(pins)
        self._limits: dict[str, int] = self._pins['limits']
        self._port: int = self._pins['port']
        self._root = 'http://127.0.0.1:' + str(self._port)
        if getattr(launcher, 'harness_sha256', None) != self._pins['harness_sha256']:
            _fail('HARNESS_NOT_ADMITTED')
        if not isinstance(reservation, GpuReservation) or reservation.holder != self._pins['holder']:
            _fail('RESERVATION_MECHANISM_INVALID')
        if (not isinstance(gate, AdmissionGate) or gate.owner != self._pins['owner']
                or gate.requesters != tuple(sorted(self._pins['requesters']))):
            _fail('GATE_ROSTER_MISMATCH')
        if any(item is None for item in (http, observer, locks, intent, clock)):
            _fail('COLLABORATOR_MISSING')
        self._state_dir = Path(state_dir)
        _plain(self._state_dir, 'STATE_DIR_UNAVAILABLE', directory=True)
        self._launcher, self._http, self._observer, self._locks = launcher, http, observer, locks
        self._reservation, self._gate, self._intent, self._clock = reservation, gate, intent, clock
        self.status = 'NEW'  # NEW -> RESERVED -> CLOSED, or RECOVERY_REQUIRED (terminal for this object)
        self.recovery_reason: str | None = None
        self._session: str | None = None
        self._journal: Journal | None = None
        self._last_state: str | None = None
        self._generation: int | None = None
        self._lifecycle: Any = None
        self._participants: list[str] = []
        self._owned: list[dict[str, Any]] = []  # every record this controller's launcher returned, in launch order
        self._current: dict[str, Any] | None = None  # the admitted owned instance
        self._preimage: dict[str, Any] | None = None
        self._intent_owned = False  # set before this controller's first intent write

    # ----- receipts, results, lease -----

    def _utc(self) -> str:
        return datetime.fromtimestamp(self._clock.time(), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    def _receipt(self, state: str, txn: str, outcome: str, **fields: Any) -> None:
        """One bounded, hash-chained, read-back receipt per transition (M4 "Required design and trial evidence"): only digests,
        identities, counts, finite codes and the sanitized selected-metadata projection; never paths, command lines, prompts,
        answers, credentials or LINE IDs. A failed write is RECOVERY_REQUIRED."""
        if self._journal is None or set(fields) - _RECEIPT_FIELDS or state not in STATES + OUTCOME_STATES:
            raise _RecoveryRequired('RECEIPT_SCHEMA_INVALID')
        record: dict[str, Any] = dict.fromkeys(_RECEIPT_FIELDS)
        record.update({'schema_version': SCHEMA_VERSION, 'kind': 'OWNED_STRATA_TRANSITION',
                       'design_sha256': self._pins['design_sha256'], 'go_sha256': self._pins['go_sha256'],
                       'source_sha256': self._pins['source_sha256'], 'session': self._session, 'run_id': txn,
                       'utc': self._utc(), 'monotonic': round(float(self._clock.monotonic()), 3),
                       'prior_state': self._last_state, 'state': state, 'generation': self._generation, 'outcome': outcome,
                       'qualification': 'UNQUALIFIED', 'remaining_jobs': sum(1 for item in self._owned if not item['stopped'])})
        record.update(fields)
        try:
            self._journal.append(record)
        except OwnedInstanceUnavailable as error:
            raise _RecoveryRequired(_code(error, 'JOURNAL_WRITE_FAILED')) from None
        except Exception:
            raise _RecoveryRequired('JOURNAL_WRITE_FAILED') from None
        self._last_state = state

    def _result(self, outcome: str, reason: str, txn: str | None, **extra: Any) -> dict[str, Any]:
        result = {'outcome': outcome, 'reason': reason, 'session': self._session, 'txn': txn, 'generation': self._generation,
                  'status': self.status,
                  'binding_sha256': None if self._current is None else self._current['inst']['hashes']['binding'],
                  'journal_sha256': None if self._journal is None else self._journal.last_sha256,
                  'qualification': 'UNQUALIFIED', 'release_qualified': False}
        result.update(extra)
        return result

    def _lease(self) -> None:
        """Lifecycle lock held and GPU reservation verified and renewed; called LAST before every irreversible step."""
        try:
            held = self._lifecycle is not None and self._lifecycle.held() is True
        except Exception:
            held = False
        if not held:
            raise _RecoveryRequired('LIFECYCLE_LOCK_LOST')
        try:
            self._reservation.renew(self._limits['lease_seconds'])
        except OwnedInstanceUnavailable as error:
            raise _RecoveryRequired(_code(error, 'RESERVATION_LOST')) from None
        except Exception:
            raise _RecoveryRequired('RESERVATION_LOST') from None

    def _require_ready(self) -> None:
        if self.status == 'RECOVERY_REQUIRED':
            _fail('CONTROLLER_RECOVERY_REQUIRED')
        if self.status != 'RESERVED':
            _fail('CONTROLLER_NOT_RESERVED')

    # ----- observation, ownership, transport -----

    def _observe(self) -> dict[str, Any]:
        """One fresh observation from the admitted observer, closed schema; anything missing, extra or UNKNOWN is ambiguity."""
        try:
            snap = self._observer.snapshot()
        except Exception:
            raise OwnedInstanceUnavailable('OBSERVER_UNAVAILABLE') from None
        keys = {'schema_version', 'observer_sha256', 'monotonic', 'gpu', 'herdr', 'ports', 'pending', 'direct_clients', 'log'}
        if not isinstance(snap, dict) or set(snap) != keys or type(snap['schema_version']) is not int or snap['schema_version'] != 1:
            _fail('OBSERVATION_AMBIGUOUS')
        if snap['observer_sha256'] != self._pins['observer_sha256']:
            _fail('OBSERVER_NOT_ADMITTED')
        stamp = snap['monotonic']
        if type(stamp) not in (int, float) or not 0 <= self._clock.monotonic() - stamp <= self._limits['observation_max_age_seconds']:
            _fail('OBSERVATION_STALE')
        gpu, herdr, ports, pending, log = snap['gpu'], snap['herdr'], snap['ports'], snap['pending'], snap['log']
        if (not isinstance(gpu, dict) or set(gpu) != {'processes', 'memory_used_mib', 'utilization_pct'}
                or not isinstance(gpu['processes'], list) or len(gpu['processes']) > 64
                or not all(_identity_ok(item) for item in gpu['processes'])
                or not _int(gpu['memory_used_mib'], 0, 1 << 20) or not _int(gpu['utilization_pct'], 0, 100)
                or not isinstance(herdr, dict) or set(herdr) != {'foreign_gpu_tasks'} or not _int(herdr['foreign_gpu_tasks'], 0, 1 << 16)
                or not isinstance(ports, dict) or set(ports) != {*SHARED_PORTS, str(self._port)}
                or not all(item == 'ABSENT' or _identity_ok(item) for item in ports.values())
                or not isinstance(pending, dict) or set(pending) != {'queued', 'in_flight', 'background'}
                or not all(_int(item, 0, 1 << 20) for item in pending.values())
                or not _int(snap['direct_clients'], 0, 1 << 16)
                or not isinstance(log, dict) or set(log) != {'age_seconds'} or not _int(log['age_seconds'], 0, 1 << 31)):
            _fail('OBSERVATION_AMBIGUOUS')
        listener = ports[str(self._port)]
        return {'gpu_processes': {tuple(item) for item in gpu['processes']}, 'memory_used_mib': gpu['memory_used_mib'],
                'utilization_pct': gpu['utilization_pct'], 'foreign_gpu_tasks': herdr['foreign_gpu_tasks'],
                'shared': [ports[key] for key in SHARED_PORTS], 'listener': 'ABSENT' if listener == 'ABSENT' else tuple(listener),
                'pending': dict(pending), 'direct_clients': snap['direct_clients'], 'log_age_seconds': log['age_seconds']}

    def _exclusive(self, snap: dict[str, Any], record: dict[str, Any] | None) -> None:
        """No other GPU user: shared ports ABSENT, no foreign Herdr GPU task, every GPU process inside the owned instance and the
        enrolled listener exactly its root; with no owned instance the GPU is at its idle ceiling and the enrolled port is free."""
        if snap['foreign_gpu_tasks']:
            _fail('GPU_FOREIGN_TASK')
        if any(item != 'ABSENT' for item in snap['shared']):
            _fail('SHARED_STRATA_PRESENT')
        if record is None:
            if snap['gpu_processes']:
                _fail('GPU_FOREIGN_PROCESS')
            if snap['memory_used_mib'] > self._limits['idle_gpu_memory_mib']:
                _fail('GPU_BUSY')
            if snap['listener'] != 'ABSENT':
                _fail('PORT_FOREIGN_LISTENER')
            if any(snap['pending'].values()) or snap['direct_clients']:
                _fail('PORT_FOREIGN_WORK')
            return
        if not snap['gpu_processes'] <= {record['identity']}:
            _fail('GPU_FOREIGN_PROCESS')
        if snap['listener'] != record['identity']:
            _fail('LISTENER_IDENTITY_MISMATCH')
        if snap['memory_used_mib'] > self._limits['model_gpu_memory_mib']:
            _fail('RESOURCE_LIMIT_EXCEEDED')

    def _quiet(self, record: dict[str, Any]) -> dict[str, Any]:
        """Candidate side, admission closed: one fresh exclusive observation in which nobody else uses the owned port. A direct
        client or pending owned work there is unaccounted and makes the run ineligible (the native observer must not count this
        controller's own selected-only connections or its completed smoke request)."""
        snap = self._observe()
        self._exclusive(snap, record)
        if snap['direct_clients'] or any(snap['pending'].values()):
            _fail('TRIAL_INELIGIBLE_DIRECT_CLIENT')
        return snap

    @staticmethod
    def _resources(snap: dict[str, Any]) -> dict[str, int]:
        return {'gpu_memory_used_mib': snap['memory_used_mib'], 'utilization_pct': snap['utilization_pct']}

    @staticmethod
    def _instance(record: dict[str, Any]) -> dict[str, Any]:
        return {'pid': record['identity'][0], 'creation_time': record['identity'][1], 'run_nonce': record['run_nonce']}

    @staticmethod
    def _identity(handle: Any) -> tuple[int, int]:
        try:
            pid, created = handle.pid, handle.creation_time
        except Exception:
            raise OwnedInstanceUnavailable('OWNERSHIP_IDENTITY_UNAVAILABLE') from None
        if not (_int(pid, 1, 1 << 63) and _int(created, 1, 1 << 63)):
            _fail('OWNERSHIP_IDENTITY_UNAVAILABLE')
        return pid, created

    @staticmethod
    def _members(handle: Any) -> list[tuple[int, ...]]:
        try:
            members = handle.job_members()
        except Exception:
            raise OwnedInstanceUnavailable('JOB_ACCOUNTING_UNAVAILABLE') from None
        if not isinstance(members, list) or len(members) > 64 or not all(_identity_ok(item) for item in members):
            _fail('JOB_ACCOUNTING_UNAVAILABLE')
        return sorted(tuple(item) for item in members)

    def _owned_check(self, record: dict[str, Any], *, running: bool = True) -> None:
        """Positive ownership: the very record this controller's launcher returned, the same (pid, creation) identity read again
        from its retained handle and, while running, a job whose only member is that root (no unexpected child process)."""
        if not any(item is record for item in self._owned):
            _fail('OWNERSHIP_NOT_PROVEN')
        handle = record['handle']
        if self._identity(handle) != record['identity']:
            _fail('OWNERSHIP_IDENTITY_DRIFT')
        if running:
            try:
                code = handle.poll()
            except Exception:
                raise OwnedInstanceUnavailable('OWNERSHIP_IDENTITY_UNAVAILABLE') from None
            if record['stopped'] or code is not None:
                _fail('INSTANCE_EXITED')
            if self._members(handle) != [record['identity']]:
                _fail('UNEXPECTED_CHILD_PROCESS')

    def _check_old(self, record: dict[str, Any]) -> None:
        """The admitted generation must stay positively owned and running; otherwise ownership is lost (no restart by port)."""
        try:
            self._owned_check(record)
        except OwnedInstanceUnavailable as error:
            raise _RecoveryRequired(_code(error, 'OWNERSHIP_NOT_PROVEN')) from None

    def _call(self, method: str, path: str, payload: Any, timeout: int) -> Any:
        if (method, path) not in HTTP_ROUTES:
            _fail('HTTP_ROUTE_REFUSED')
        try:
            return self._http.request(method, self._root + path, payload=payload, timeout=timeout, max_bytes=MAX_BODY_BYTES)
        except Exception:
            raise OwnedInstanceUnavailable('ENDPOINT_UNAVAILABLE') from None

    def _metadata(self, record: dict[str, Any]) -> dict[str, Any]:
        """Exact selected metadata of the owned endpoint (the v213_model_profile.selected_metadata rules, stricter: exactly one
        served model). Returns only the sanitized selected projection."""
        model = record['inst']['binding']['model']
        health = self._call('GET', '/health', None, 15)
        if (not isinstance(health, dict) or health.get('service') != 'strata' or health.get('status') != 'ok'
                or health.get('loaded') is not True or health.get('model') != model or type(health.get('api_key')) is not bool):
            _fail('STRATA_HEALTH_IDENTITY_UNAVAILABLE')
        if health['api_key']:
            _fail('ENDPOINT_AUTH_REQUIRED')
        context = health.get('max_context')
        if not _int(context, 1, 1073741824):
            _fail('STRATA_CONTEXT_UNKNOWN')
        catalog = self._call('GET', '/v1/models', None, 15)
        rows = catalog.get('data') if isinstance(catalog, dict) else None
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            _fail('STRATA_CATALOG_NOT_SINGLE_MODEL')
        row = rows[0]
        if (row.get('id') != model or 'alias_of' in row or 'aliases' in row or not isinstance(row.get('status'), dict)
                or row['status'].get('value') != 'loaded' or not isinstance(row.get('meta'), dict)
                or type(row['meta'].get('n_ctx')) is not int or row['meta']['n_ctx'] != context
                or context < self._pins['min_context']):
            _fail('STRATA_SELECTED_CONTEXT_UNAVAILABLE')
        return {'model': model, 'declared_context': context,
                'selected_catalog': [{'id': model, 'status': {'value': 'loaded'}, 'meta': {'n_ctx': context}}]}

    def _answer(self, record: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        """A complete exact-model answer to the fixed shared smoke prompt (finish=stop, one choice, literal marker) within the
        pinned latency; the raw prompt and answer are never recorded."""
        try:
            from v213_compact_qa_gateway import POLICY, complete_compact_response
        except Exception:
            raise OwnedInstanceUnavailable('ANSWER_POLICY_UNAVAILABLE') from None
        profile, model = record['inst']['profile'], record['inst']['binding']['model']
        payload = {'model': model, 'messages': [{'role': 'user', 'content': POLICY['smoke_prompt']}], 'temperature': 0,
                   'max_tokens': profile['smoke_output_tokens'], 'stream': False,
                   'chat_template_kwargs': {'enable_thinking': profile['enable_thinking']},
                   'reasoning_effort': profile['reasoning_effort']}
        started = self._clock.monotonic()
        response = self._call('POST', '/v1/chat/completions', payload, self._limits['answer_seconds'])
        elapsed = self._clock.monotonic() - started
        if not 0 <= elapsed <= min(self._limits['answer_seconds'], profile['timeout_ms'] / 1000):
            _fail('ANSWER_LATENCY_EXCEEDED')
        try:
            complete = (isinstance(response, dict) and response.get('model') == model
                        and complete_compact_response(response, model, metadata['selected_catalog'])
                        and response['choices'][0]['message']['content'].strip()
                        == POLICY['smoke_prompt'].removeprefix('Reply exactly '))
        except Exception:
            complete = False
        if not complete:
            _fail('ANSWER_INCOMPLETE')
        return {'latency_ms': int(elapsed * 1000)}

    def _verify(self, record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """VERIFIED: exact selected metadata AND a complete exact-model answer within the latency/resource ceilings, the enrolled
        listener being the owned root, no other GPU user and no unaccounted client, before and after the answer. Health alone is
        never enough."""
        self._owned_check(record)
        metadata = self._metadata(record)
        self._quiet(record)
        answer = self._answer(record, metadata)
        self._owned_check(record)
        snap = self._quiet(record)
        resources = dict(self._resources(snap), latency_ms=answer['latency_ms'], complete_exact_marker=True)
        return metadata, resources

    # ----- lifecycle steps -----

    def _launch(self, inst: dict[str, Any]) -> dict[str, Any]:
        """Starts ONE pinned instance in a new owned job through the admitted harness, after re-hashing its pinned bytes."""
        if prepare_instance(inst['spec'], self._port)['hashes'] != inst['hashes']:
            _fail('SPEC_HASH_MISMATCH')
        nonce = os.urandom(16).hex()
        try:
            handle = self._launcher.launch((inst['spec']['executable'], *inst['spec']['argv']), run_nonce=nonce)
        except Exception:
            raise _RecoveryRequired('LAUNCH_OUTCOME_UNKNOWN') from None
        try:
            identity = self._identity(handle)
        except OwnedInstanceUnavailable:
            raise _RecoveryRequired('OWNERSHIP_IDENTITY_UNAVAILABLE') from None
        record = {'handle': handle, 'identity': identity, 'run_nonce': nonce, 'inst': inst, 'stopped': False}
        self._owned.append(record)
        return record

    def _await_ready(self, record: dict[str, Any]) -> None:
        deadline = self._clock.monotonic() + self._limits['startup_seconds']
        while True:
            self._owned_check(record)  # crash, identity drift or a child process enters rollback
            try:
                health = self._call('GET', '/health', None, 5)
                if isinstance(health, dict) and health.get('loaded') is True:
                    return
            except _RecoveryRequired:
                raise
            except OwnedInstanceUnavailable:
                pass
            if self._clock.monotonic() >= deadline:
                _fail('CANDIDATE_STARTUP_TIMEOUT')
            self._clock.sleep(self._limits['poll_seconds'])

    def _stop(self, record: dict[str, Any]) -> None:
        """Stops ONLY a record this controller's launcher returned, through its retained handle (never by PID, port or name), and
        waits for that exact process and every accounted job member to exit. Anything unproven is RECOVERY_REQUIRED."""
        try:
            self._owned_check(record, running=False)
        except OwnedInstanceUnavailable as error:
            raise _RecoveryRequired(_code(error, 'OWNERSHIP_NOT_PROVEN')) from None
        handle = record['handle']
        try:
            if handle.poll() is None:
                handle.terminate()
            exited = handle.wait(self._limits['stop_seconds'])
            code = handle.poll()
        except Exception:
            raise _RecoveryRequired('STOP_UNPROVEN') from None
        if exited is not True or code is None:
            raise _RecoveryRequired('STOP_UNPROVEN')
        try:
            remaining = self._members(handle)
        except OwnedInstanceUnavailable:
            raise _RecoveryRequired('STOP_UNPROVEN') from None
        if remaining:
            raise _RecoveryRequired('STOP_JOB_MEMBERS_REMAIN')
        record['stopped'] = True

    def _await_release(self) -> dict[str, Any]:
        """Proves, under the held reservation, that the GPU, the enrolled port and the owned job are released (bounded wait)."""
        deadline = self._clock.monotonic() + self._limits['stop_seconds']
        while True:
            try:
                snap = self._observe()
                self._exclusive(snap, None)
                return snap
            except OwnedInstanceUnavailable:
                pass
            if self._clock.monotonic() >= deadline:
                raise _RecoveryRequired('GPU_RELEASE_UNPROVEN')
            self._clock.sleep(self._limits['poll_seconds'])

    def _gate_set(self, action: str, txn: str, binding_sha256: str | None = None) -> int:
        try:
            return self._gate.close(txn) if action == 'close' else self._gate.open(txn, binding_sha256 or '')
        except OwnedInstanceUnavailable as error:
            raise _RecoveryRequired(_code(error, 'GATE_WRITE_FAILED')) from None
        except Exception:
            raise _RecoveryRequired('GATE_WRITE_FAILED') from None

    def _intent_snapshot(self) -> dict[str, Any]:
        try:
            value = self._intent.snapshot()
        except Exception:
            raise OwnedInstanceUnavailable('INTENT_UNAVAILABLE') from None
        if not isinstance(value, dict) or set(value) != {'mode', 'binding_sha256', 'profile_sha256'}:
            _fail('INTENT_UNAVAILABLE')
        explicit = value['mode'] == 'EXPLICIT_STRATA'
        if value['mode'] not in ('EXPLICIT_STRATA', 'LEGACY_ABSENT') or not all(
                (isinstance(value[key], str) and _HEX64.fullmatch(value[key])) if explicit else value[key] is None
                for key in ('binding_sha256', 'profile_sha256')):
            _fail('INTENT_UNAVAILABLE')
        return dict(value)

    @staticmethod
    def _intent_of(inst: dict[str, Any]) -> dict[str, Any]:
        return {'mode': 'EXPLICIT_STRATA', 'binding_sha256': inst['hashes']['binding'], 'profile_sha256': inst['hashes']['profile']}

    def _commit_intent(self, inst: dict[str, Any]) -> None:
        """Pointer-last commit of the selected request intent through the existing pending barrier, then readback. Any doubt is
        RECOVERY_REQUIRED with admission still CLOSED; the recovery path leaves the intent unavailable."""
        self._intent_owned = True
        try:
            self._intent.commit(inst['binding'], inst['profile'])
        except Exception:
            raise _RecoveryRequired('INTENT_COMMIT_UNCERTAIN') from None
        try:
            after = self._intent_snapshot()
        except OwnedInstanceUnavailable:
            raise _RecoveryRequired('INTENT_READBACK_MISMATCH') from None
        if after != self._intent_of(inst):
            raise _RecoveryRequired('INTENT_READBACK_MISMATCH')

    def _agreement(self, record: dict[str, Any], inst: dict[str, Any]) -> None:
        """Before ADMISSION_OPEN: ownership, profile/binding intent, the closed generation and the journal readback agree again
        and the owned port is still exclusive with no unaccounted client (a refusal here is post-commit: RECOVERY_REQUIRED)."""
        self._owned_check(record)
        if self._intent_snapshot() != self._intent_of(inst):
            _fail('INTENT_READBACK_MISMATCH')
        gate = self._gate.read()
        if (gate['state'], gate['generation']) != ('CLOSED', self._generation):
            _fail('GATE_GENERATION_DISAGREEMENT')
        journal = self._journal
        entries = read_journal(journal.directory) if journal is not None else []
        if journal is None or len(entries) != journal.count or _sha(_canonical(entries[-1])) != journal.last_sha256:
            _fail('JOURNAL_READBACK_MISMATCH')
        self._quiet(record)

    def _close_and_drain(self, txn: str, old: dict[str, Any]) -> None:
        """ADMISSION_CLOSED then DRAINED: every requester acknowledges the same closed generation, then queued, in-flight and
        background work reach zero within the fixed deadline, ownership and lease revalidated on every poll. Nothing is
        cancelled; an unaccounted direct client makes the run ineligible."""
        self._lease()
        self._generation = self._gate_set('close', txn)
        deadline = self._clock.monotonic() + self._limits['ack_seconds']
        while self._gate.acknowledged(self._generation) != list(self._gate.requesters):
            if self._clock.monotonic() >= deadline:
                _fail('TRIAL_INELIGIBLE_UNACKED')
            self._clock.sleep(self._limits['poll_seconds'])
        self._receipt('ADMISSION_CLOSED', txn, 'OK', acks={'participants': self._participants, 'requesters': list(self._gate.requesters)},
                      deadline_seconds=self._limits['ack_seconds'])
        deadline = self._clock.monotonic() + self._limits['drain_seconds']
        while True:
            self._lease()
            self._check_old(old)
            snap = self._observe()
            self._exclusive(snap, old)
            if snap['direct_clients']:
                _fail('TRIAL_INELIGIBLE_DIRECT_CLIENT')
            if not any(snap['pending'].values()):
                break
            if self._clock.monotonic() >= deadline:
                _fail('DRAIN_TIMEOUT')
            self._clock.sleep(self._limits['poll_seconds'])
        self._receipt('DRAINED', txn, 'OK', pending=snap['pending'], deadline_seconds=self._limits['drain_seconds'])

    def _pre_stop(self, old: dict[str, Any]) -> None:
        """Immediately before the irreversible stop: still drained, exclusive, owned, the same closed generation acknowledged by
        every requester, and the lease held last (a queue/retry/reload race refuses instead of stopping)."""
        snap = self._observe()
        if any(snap['pending'].values()) or snap['direct_clients']:
            _fail('DRAIN_RACE')
        self._exclusive(snap, old)
        self._check_old(old)
        gate = self._gate.read()
        if ((gate['state'], gate['generation']) != ('CLOSED', self._generation)
                or self._gate.acknowledged(self._generation) != list(self._gate.requesters)):
            _fail('GATE_GENERATION_DISAGREEMENT')
        self._lease()

    # ----- recovery paths -----

    def _enter_recovery(self, txn: str, code: str, *, detail: str | None = None) -> dict[str, Any]:
        """RECOVERY_REQUIRED (terminal for this object): close admission, make an intent this controller wrote unavailable,
        preserve the journal. Never kills, restarts, reclaims or guesses; the reservation record and both locks stay held, so
        cooperating participants keep refusing until a separate recovery GO establishes ownership afresh."""
        self.status = 'RECOVERY_REQUIRED'
        self.recovery_reason = code
        cleanup = []
        try:
            if self._gate.read()['state'] == 'OPEN':
                self._generation = self._gate.close(txn)
                cleanup.append('ADMISSION_CLOSED')
        except Exception:
            cleanup.append('ADMISSION_CLOSE_UNPROVEN')
        if self._intent_owned:
            try:
                self._intent.make_unavailable()
                cleanup.append('INTENT_UNAVAILABLE')
            except Exception:
                cleanup.append('INTENT_UNAVAILABLE_UNPROVEN')
        written = True
        try:
            self._receipt('RECOVERY_REQUIRED', txn, code, reason=detail, cleanup='+'.join(cleanup) or 'NONE')
        except Exception:
            written = False
        return self._result('RECOVERY_REQUIRED', code, txn, journal_written=written, cleanup=cleanup)

    def _refuse(self, txn: str, code: str) -> dict[str, Any]:
        try:
            self._receipt('REFUSED', txn, code)
        except _RecoveryRequired as error:
            return self._enter_recovery(txn, str(error), detail=code)
        return self._result('REFUSED', code, txn)

    def _abort_restore(self, txn: str, old: dict[str, Any], code: str) -> dict[str, Any]:
        """Before the old instance was stopped: preserve the failed transition, revalidate the UNCHANGED old generation
        (ownership, exclusivity, exact metadata, a complete answer, unchanged intent) and only then reopen its admission. Shared
        work is never killed or cancelled; any doubt is RECOVERY_REQUIRED."""
        try:
            self._receipt('TRANSITION_FAILED', txn, code)
            self._check_old(old)
            self._exclusive(self._observe(), old)
            metadata = self._metadata(old)
            self._answer(old, metadata)
            admitted = old['inst']['hashes']['binding']
            if (self._intent_snapshot()['binding_sha256'], self._gate.read()['state']) != (admitted, 'CLOSED'):
                _fail('RESTORE_STATE_DISAGREEMENT')
            self._lease()
            self._generation = self._gate_set('open', txn, admitted)
            self._receipt('ABORTED_RESTORED', txn, code, instance=self._instance(old), metadata=metadata,
                          readback='GATE_READBACK_OK')
        except _RecoveryRequired as error:
            return self._enter_recovery(txn, str(error), detail=code)
        except Exception:
            return self._enter_recovery(txn, 'RESTORE_UNPROVEN', detail=code)
        return self._result('REFUSED_RESTORED', code, txn)

    def _rollback(self, txn: str, old: dict[str, Any] | None, candidate: dict[str, Any] | None,
                  preimage: dict[str, Any] | None, code: str) -> dict[str, Any]:
        """After the old instance exited (or for a first start): stop the owned candidate through its handle, prove the GPU
        released, restart ONLY the pinned former instance (if any) under the still-held reservation, revalidate exact metadata
        AND a complete answer, confirm the intent is the unchanged preimage and only then reopen the old generation. The
        candidate intent is never committed before rollback, so restoring it means proving it unchanged. Any doubt is
        RECOVERY_REQUIRED."""
        try:
            self._receipt('TRANSITION_FAILED', txn, code)
            self._receipt('ROLLBACK_STARTED', txn, code)
            if candidate is not None and not candidate['stopped']:
                self._lease()
                self._stop(candidate)
            self._await_release()
            if preimage is None or self._intent_snapshot() != preimage:
                raise _RecoveryRequired('INTENT_DRIFT')
            cleanup = 'CANDIDATE_STOPPED' if candidate is not None else 'NOTHING_STARTED'
            if old is None:
                self._current = None
                self._receipt('ROLLED_BACK', txn, code, cleanup=cleanup, readback='INTENT_UNCHANGED')
                return self._result('ROLLED_BACK', code, txn)
            try:
                former = prepare_instance(old['inst']['spec'], self._port)
            except OwnedInstanceUnavailable:
                raise _RecoveryRequired('PREDECESSOR_BYTES_CHANGED') from None
            if former['hashes'] != old['inst']['hashes']:
                raise _RecoveryRequired('PREDECESSOR_BYTES_CHANGED')
            self._exclusive(self._observe(), None)
            self._lease()
            restored = self._launch(former)
            self._await_ready(restored)
            metadata, resources = self._verify(restored)
            gate = self._gate.read()
            if (gate['state'], gate['generation']) != ('CLOSED', self._generation) or self._intent_snapshot() != preimage:
                _fail('RESTORE_STATE_DISAGREEMENT')
            self._lease()
            self._generation = self._gate_set('open', txn, former['hashes']['binding'])
            self._current = restored
            self._receipt('ROLLED_BACK', txn, code, instance=self._instance(restored), metadata=metadata, resources=resources,
                          cleanup=cleanup, readback='INTENT_UNCHANGED')
        except _RecoveryRequired as error:
            return self._enter_recovery(txn, str(error), detail=code)
        except OwnedInstanceUnavailable as error:
            return self._enter_recovery(txn, 'ROLLBACK_FAILED', detail=_code(error, code))
        except Exception:
            return self._enter_recovery(txn, 'ROLLBACK_FAILED', detail=code)
        return self._result('ROLLED_BACK', code, txn)

    # ----- public operations -----

    def open(self) -> dict[str, Any]:
        """Session PRECHECK and RESERVED: closed gate, readable intent preimage, an exclusive idle GPU (no shared :8080/:8081
        instance, no foreign GPU process or Herdr task, free enrolled port, quiet shared log), then the lifecycle lock and the
        acknowledged GPU reservation, then the same checks again under the held reservation. A refusal holds nothing."""
        if self.status != 'NEW':
            _fail('CONTROLLER_NOT_NEW')
        self._session = _new_id('session')
        txn = self._session
        try:
            self._journal = Journal(self._state_dir / self._session)
            gate = self._gate.read()
            self._generation = gate['generation']
            if gate['state'] != 'CLOSED':
                _fail('GATE_STATE_UNEXPECTED')
            self._preimage = self._intent_snapshot()
            snap = self._observe()
            self._exclusive(snap, None)
            if snap['log_age_seconds'] < self._limits['log_quiet_seconds']:
                _fail('SHARED_LOG_ACTIVE')
            self._receipt('PRECHECK', txn, 'OK', manifest={'kind': 'SESSION', 'gate_generation': self._generation,
                                                           'intent_mode': self._preimage['mode'],
                                                           'intent_binding_sha256': self._preimage['binding_sha256']})
        except Exception as error:
            return self._refuse_open(txn, _code(error, 'PRECHECK_FAILED'))
        try:
            lock = self._locks.acquire(str(self._state_dir / ('instance-' + str(self._port) + '.lock')))
        except Exception:
            lock = None
        if not lock:
            return self._refuse_open(txn, 'LIFECYCLE_LOCK_BUSY')
        self._lifecycle = lock
        try:
            lease = self._reservation.acquire(lease_seconds=self._limits['lease_seconds'], ack_seconds=self._limits['ack_seconds'],
                                              poll_seconds=self._limits['poll_seconds'])
        except Exception as error:
            _release(lock)
            self._lifecycle = None
            return self._refuse_open(txn, _code(error, 'RESERVATION_UNAVAILABLE'))
        self._participants = list(lease['participants'])
        self.status = 'RESERVED'
        try:
            self._exclusive(self._observe(), None)
            self._lease()
            self._receipt('RESERVED', txn, 'OK', acks={'participants': self._participants, 'requesters': []},
                          deadline_seconds=self._limits['ack_seconds'])
        except _RecoveryRequired as error:
            return self._enter_recovery(txn, str(error))
        except Exception as error:
            return self._release_refused(txn, _code(error, 'PRECHECK_FAILED'))
        return self._result('RESERVED', 'OK', txn, participants=self._participants)

    def _refuse_open(self, txn: str, code: str) -> dict[str, Any]:
        self.status = 'CLOSED'
        try:
            self._receipt('REFUSED', txn, code)
        except Exception:
            pass  # nothing is held: the refusal itself is the result
        return self._result('REFUSED', code, txn)

    def _release_refused(self, txn: str, code: str) -> dict[str, Any]:
        """Nothing was launched: release what open() acquired, then refuse."""
        try:
            self._reservation.release()
        except Exception as error:
            return self._enter_recovery(txn, _code(error, 'RESERVATION_RELEASE_FAILED'), detail=code)
        _release(self._lifecycle)
        self._lifecycle = None
        return self._refuse_open(txn, code)

    def start(self, spec: Any) -> dict[str, Any]:
        """First owned instance of the session (no previous generation): PRECHECK -> RESERVED -> CANDIDATE_READY -> VERIFIED ->
        COMMITTED -> ADMISSION_OPEN. A failure after the launch rolls back to 'no instance' with admission CLOSED."""
        self._require_ready()
        if self._current is not None:
            _fail('INSTANCE_ALREADY_ADMITTED')
        return self._transaction(spec, None)

    def replace(self, spec: Any) -> dict[str, Any]:
        """M4 lifecycle replacement of the admitted owned instance by ONE candidate, in exactly the order of STATES."""
        self._require_ready()
        if self._current is None:
            _fail('NO_OWNED_INSTANCE')
        return self._transaction(spec, self._current)

    def _transaction(self, spec: Any, old: dict[str, Any] | None) -> dict[str, Any]:
        txn = _new_id('txn')
        phase = 'pre'  # pre: nothing changed; closed: admission closed, old running; stopped: old exited; committed: intent written
        candidate: dict[str, Any] | None = None
        preimage: dict[str, Any] | None = None
        try:
            inst = prepare_instance(spec, self._port)
            gate = self._gate.read()
            preimage = self._intent_snapshot()
            if old is not None:
                self._check_old(old)
                self._exclusive(self._observe(), old)
                self._metadata(old)
                admitted = old['inst']['hashes']['binding']
                if (gate['state'], gate['generation'], gate['binding_sha256']) != ('OPEN', self._generation, admitted):
                    _fail('GATE_GENERATION_DISAGREEMENT')
                if preimage != self._intent_of(old['inst']):
                    _fail('INTENT_DRIFT')
            else:
                self._exclusive(self._observe(), None)
                if (gate['state'], gate['generation']) != ('CLOSED', self._generation):
                    _fail('GATE_GENERATION_DISAGREEMENT')
                if preimage != self._preimage:
                    _fail('INTENT_DRIFT')
            self._receipt('PRECHECK', txn, 'OK', hashes=inst['hashes'], manifest={
                'kind': 'START' if old is None else 'REPLACE', 'gate_generation': self._generation,
                'intent_mode': preimage['mode'], 'intent_binding_sha256': preimage['binding_sha256'],
                'previous_hashes': None if old is None else old['inst']['hashes'],
                'previous_instance': None if old is None else self._instance(old)})
            self._lease()
            self._receipt('RESERVED', txn, 'OK', acks={'participants': self._participants, 'requesters': []})
            if old is not None:
                phase = 'closed'
                self._close_and_drain(txn, old)
                self._pre_stop(old)
                phase = 'stopped'
                self._stop(old)
                snap = self._await_release()
                self._receipt('OWNED_OLD_EXITED', txn, 'OK', instance=self._instance(old), resources=self._resources(snap))
            self._exclusive(self._observe(), None)
            self._lease()
            phase = 'stopped'
            candidate = self._launch(inst)
            self._await_ready(candidate)
            self._receipt('CANDIDATE_READY', txn, 'OK', instance=self._instance(candidate), hashes=inst['hashes'],
                          deadline_seconds=self._limits['startup_seconds'])
            metadata, resources = self._verify(candidate)
            self._receipt('VERIFIED', txn, 'OK', instance=self._instance(candidate), metadata=metadata, resources=resources)
            self._quiet(candidate)
            self._lease()
            phase = 'committed'
            self._commit_intent(inst)
            self._receipt('COMMITTED', txn, 'OK', readback='INTENT_READBACK_OK',
                          invalidated_binding_sha256=None if old is None else old['inst']['hashes']['binding'])
            self._agreement(candidate, inst)
            self._lease()
            self._generation = self._gate_set('open', txn, inst['hashes']['binding'])
            self._current = candidate
            self._receipt('ADMISSION_OPEN', txn, 'OK', instance=self._instance(candidate), hashes=inst['hashes'],
                          readback='GATE_READBACK_OK')
        except _RecoveryRequired as error:
            return self._enter_recovery(txn, str(error))
        except OwnedInstanceUnavailable as error:
            code = _code(error, 'TRANSACTION_FAILED')
            if phase == 'pre':
                return self._refuse(txn, code)
            if phase == 'closed' and old is not None:
                return self._abort_restore(txn, old, code)
            if phase == 'stopped':
                return self._rollback(txn, old, candidate, preimage, code)
            return self._enter_recovery(txn, code)
        except Exception:
            return self._enter_recovery(txn, 'CONTROLLER_INTERNAL_ERROR')
        return self._result('ADMISSION_OPEN', 'OK', txn)

    def shutdown(self) -> dict[str, Any]:
        """Ends the session: closes admission, drains, stops the owned instance through its handle, proves the GPU released, then
        releases the reservation and the lifecycle lock (RELEASED). A drain refusal reopens the unchanged generation instead
        (REFUSED_RESTORED). The request intent is NOT rewritten here: it keeps selecting the stopped owned endpoint, so every
        caller gets a finite refusal and never a fallback."""
        self._require_ready()
        txn = _new_id('txn')
        old = self._current
        phase = 'pre'
        try:
            if old is not None:
                self._check_old(old)
            self._receipt('PRECHECK', txn, 'OK', manifest={
                'kind': 'SHUTDOWN', 'gate_generation': self._generation,
                'previous_hashes': None if old is None else old['inst']['hashes'],
                'previous_instance': None if old is None else self._instance(old)})
            if old is not None:
                phase = 'closed'
                self._close_and_drain(txn, old)
                self._pre_stop(old)
                phase = 'stopped'
                self._stop(old)
                snap = self._await_release()
                self._current = None
                self._receipt('OWNED_OLD_EXITED', txn, 'OK', instance=self._instance(old), resources=self._resources(snap))
            self._lease()
            try:
                self._reservation.release()
            except Exception as error:
                raise _RecoveryRequired(_code(error, 'RESERVATION_RELEASE_FAILED')) from None
            _release(self._lifecycle)
            self._lifecycle = None
            self.status = 'CLOSED'
            self._receipt('RELEASED', txn, 'OK', cleanup='RESERVATION_RELEASED')
        except _RecoveryRequired as error:
            return self._enter_recovery(txn, str(error))
        except OwnedInstanceUnavailable as error:
            code = _code(error, 'SHUTDOWN_FAILED')
            if phase == 'pre':
                return self._refuse(txn, code)
            if phase == 'closed' and old is not None:
                return self._abort_restore(txn, old, code)
            return self._enter_recovery(txn, code)
        except Exception:
            return self._enter_recovery(txn, 'CONTROLLER_INTERNAL_ERROR')
        return self._result('RELEASED', 'OK', txn)
