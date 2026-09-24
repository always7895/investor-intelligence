"""v213 QA capacity synthetic checkpoint journal — T05 root scope + claims.

Step A: synthetic fixture-root scope scaffold. Step B: exclusive synthetic
checkpoint claims (claim_checkpoint). No record append, recovery, or full
journal semantics yet (later steps C/D).

Temporary synthetic fixture IO is the ONLY permitted IO in this new API. No
production backend, no mode override, no default or caller-provided production
path. Fixed non-negotiable flags: SYNTHETIC=True, NON_PRODUCTION=True,
AUTHORIZES_EXECUTION=False. A claim is a synthetic single-winner marker, not
real durable authority or a native-attempt count.
"""

import contextlib
import hashlib
import json
import os
import tempfile
from pathlib import Path

from v213_qa_capacity_control_identity import (
    IdentityValidationError,
    validate_git_commit,
    validate_sha256,
)
from v213_qa_capacity_control_state import (
    RunStateBindingClaims,
    StateEventClaims,
    StateValidationError,
    append_event,
    initial_history,
    validate_history,
    validate_state_binding,
)


class SyntheticJournalError(StateValidationError):
    """Raised for fabricated, closed, out-of-scope, or marker-invalid roots."""


# --- fixed non-negotiable flags (immutable; never constructor fields) ------
SYNTHETIC = True
NON_PRODUCTION = True
AUTHORIZES_EXECUTION = False

# --- fixed marker (written once by factory; validated, never repaired) -----
_MARKER_NAME = "NON_PRODUCTION.marker"
_MARKER_CONTENT = (
    "qa-capacity-SYNTHETIC\n"
    "SYNTHETIC=true\n"
    "NON_PRODUCTION=true\n"
    "AUTHORIZES_EXECUTION=false\n"
)
_MARKER_MAX_BYTES = 4096  # bound marker reads (~4KiB)

# --- factory-live identity registry (module-private) -----------------------
# Maps id(root) -> root for factory-issued roots currently OPEN. Only roots
# registered here (and carrying a valid fixed marker) are accepted by
# require_fixture_root. A fabricated/closed/out-of-scope root is never here.
_LIVE_ROOTS = {}

# --- bounded read limits (read limit+1; overbound fails closed) -----------
_CLAIM_MAX_BYTES = 4096
_PAYLOAD_MAX_BYTES = 16384
_SEAL_MAX_BYTES = 4096

# --- event sequence range (0..4, max 5 events) ----------------------------
_EVENT_SEQ_MAX = 4

# --- fixed strict field sets (canonical JSON, exact keys) -----------------
_CLAIM_KEYS = (
    "format", "SYNTHETIC", "NON_PRODUCTION", "AUTHORIZES_EXECUTION",
    "checkpoint_key", "run_id", "run_binding_sha256", "deadline",
)
_PAYLOAD_KEYS = (
    "format", "SYNTHETIC", "NON_PRODUCTION", "AUTHORIZES_EXECUTION",
    "previous_sha256", "event",
)
_SEAL_KEYS = (
    "format", "SYNTHETIC", "NON_PRODUCTION", "AUTHORIZES_EXECUTION",
    "checkpoint_key", "sequence", "payload_sha256", "payload_bytes",
)


class SyntheticJournalSnapshot:
    """Immutable synthetic journal snapshot. Normal construction refuses.

    Returned ONLY by load_journal(). Contains the validated binding, the
    history tuple, the claim header SHA256, the head sequence/SHA256, and the
    accepted-reducer facts (None for header-only). Not permission, recovery,
    or retry authority.
    """
    __slots__ = ("_binding", "_history", "_header_sha256",
                 "_head_sequence", "_head_sha256", "_facts")
    SYNTHETIC = True
    NON_PRODUCTION = True
    AUTHORIZES_EXECUTION = False

    def __init__(self, *args, **kwargs):
        raise SyntheticJournalError(
            "SyntheticJournalSnapshot normal public construction is refused; "
            "use load_journal()")

    def __setattr__(self, name, value):
        raise AttributeError(
            "SyntheticJournalSnapshot instance is immutable; "
            "normal assignment is blocked")

    def __delattr__(self, name):
        raise AttributeError(
            "SyntheticJournalSnapshot instance is immutable; "
            "normal deletion is blocked")

    def __eq__(self, other):
        return self is other

    def __hash__(self):
        return id(self)

    def __repr__(self):
        return "<SyntheticJournalSnapshot opaque>"

    @property
    def binding(self):
        return self._binding

    @property
    def history(self):
        return self._history

    @property
    def header_sha256(self):
        return self._header_sha256

    @property
    def head_sequence(self):
        return self._head_sequence

    @property
    def head_sha256(self):
        return self._head_sha256

    @property
    def facts(self):
        return self._facts


class SyntheticFixtureRoot:
    """Opaque immutable synthetic fixture root. Normal construction refuses.

    Instances are created ONLY by the synthetic_fixture() factory via a private
    path and registered as live. Passing a str/Path/fabricated root never
    enables writes: require_fixture_root accepts exact live factory roots with a
    valid fixed marker only. Hostile arbitrary Python memory monkeypatching is
    outside scope; this is not a security sandbox.
    """
    __slots__ = ("_path", "_open")
    SYNTHETIC = True
    NON_PRODUCTION = True
    AUTHORIZES_EXECUTION = False

    def __init__(self, *args, **kwargs):
        # Normal public construction of an arbitrary root must refuse.
        raise SyntheticJournalError(
            "SyntheticFixtureRoot normal public construction is refused; "
            "use the synthetic_fixture() factory")

    # --- block normal instance assignment/deletion (immutable) -------------
    def __setattr__(self, name, value):
        raise AttributeError(
            "SyntheticFixtureRoot instance is immutable; "
            "normal assignment is blocked")

    def __delattr__(self, name):
        raise AttributeError(
            "SyntheticFixtureRoot instance is immutable; "
            "normal deletion is blocked")

    # --- opaque identity; guard equality without touching arbitrary attrs ---
    def __eq__(self, other):
        return self is other

    def __hash__(self):
        return id(self)

    def __repr__(self):
        # Never expose the raw path; keep the root opaque.
        return "<SyntheticFixtureRoot opaque>"


class SyntheticClaim:
    """Immutable synthetic checkpoint claim. Normal construction refuses.

    Created ONLY by claim_checkpoint() from an exact factory-live root and an
    exact validated RunStateBindingClaims. Contains the validated binding and
    the SHA256 of the exact written claim bytes. Not real durable authority or
    a native-attempt count.
    """
    __slots__ = ("_binding", "_header_sha256")
    SYNTHETIC = True
    NON_PRODUCTION = True
    AUTHORIZES_EXECUTION = False

    def __init__(self, *args, **kwargs):
        raise SyntheticJournalError(
            "SyntheticClaim normal public construction is refused; "
            "use claim_checkpoint()")

    def __setattr__(self, name, value):
        raise AttributeError(
            "SyntheticClaim instance is immutable; "
            "normal assignment is blocked")

    def __delattr__(self, name):
        raise AttributeError(
            "SyntheticClaim instance is immutable; "
            "normal deletion is blocked")

    def __eq__(self, other):
        return self is other

    def __hash__(self):
        return id(self)

    def __repr__(self):
        return "<SyntheticClaim opaque>"

    @property
    def binding(self):
        return self._binding

    @property
    def header_sha256(self):
        return self._header_sha256


def _issue_root(directory):
    """Factory-private: create and register a live root (bypasses __init__)."""
    root = object.__new__(SyntheticFixtureRoot)
    object.__setattr__(root, "_path", Path(directory))
    object.__setattr__(root, "_open", True)
    _LIVE_ROOTS[id(root)] = root
    return root


def _revoke_root(root):
    """Factory-private: close a live root and drop it from the registry."""
    object.__setattr__(root, "_open", False)
    _LIVE_ROOTS.pop(id(root), None)


def _read_marker(directory):
    """Read + validate the fixed marker (bounded). Fails closed; never repairs."""
    marker = Path(directory) / _MARKER_NAME
    try:
        with open(marker, "rb") as fh:
            data = fh.read(_MARKER_MAX_BYTES + 1)
    except OSError as exc:
        raise SyntheticJournalError(
            "NON_PRODUCTION marker missing/unreadable: %s" % exc)
    if len(data) > _MARKER_MAX_BYTES:
        raise SyntheticJournalError("NON_PRODUCTION marker overbound")
    if data != _MARKER_CONTENT.encode("utf-8"):
        raise SyntheticJournalError("NON_PRODUCTION marker malformed/changed")
    return data


@contextlib.contextmanager
def synthetic_fixture():
    """Context manager: NEW fresh OS-temp synthetic fixture root scope.

    Creates a NEW tempfile.TemporaryDirectory (prefix qa-capacity-SYNTHETIC-),
    writes the fixed NON_PRODUCTION marker, and yields an opaque immutable
    SyntheticFixtureRoot. No caller path argument, no caller flags. Teardown
    closes the root and cleans ONLY its own freshly created directory.
    """
    tmp = tempfile.TemporaryDirectory(prefix="qa-capacity-SYNTHETIC-")
    root = _issue_root(tmp.name)
    try:
        (Path(tmp.name) / _MARKER_NAME).write_bytes(
            _MARKER_CONTENT.encode("utf-8"))
        yield root
    finally:
        _revoke_root(root)
        tmp.cleanup()


def require_fixture_root(root):
    """Validate an exact factory-issued live root + fixed marker; return path.

    Returns the fixture path ONLY for the synthetic backend. Marker
    missing/malformed/changed flags fails closed; no recreate/repair. Closed or
    out-of-scope (non-factory) roots are refused. Ordinary Windows/production
    paths are never accepted as factory input. No filesystem canonical/HANDLE/
    admin-resistance claims.
    """
    # Guard type first; never touch arbitrary object attributes before this.
    if type(root) is not SyntheticFixtureRoot:
        raise SyntheticJournalError(
            "root must be an exact SyntheticFixtureRoot (str/Path/fabricated "
            "roots are refused)")
    live = _LIVE_ROOTS.get(id(root))
    if live is not root or not root._open:
        raise SyntheticJournalError(
            "root is closed or not a live factory-issued root")
    _read_marker(root._path)
    return root._path


def _claim_payload(binding):
    """Canonical UTF-8 JSON claim payload (sorted keys, compact, no NaN)."""
    payload = {
        "format": "SYNTHETIC_CHECKPOINT_CLAIM_V1",
        "SYNTHETIC": True,
        "NON_PRODUCTION": True,
        "AUTHORIZES_EXECUTION": False,
        "checkpoint_key": binding.checkpoint_key,
        "run_id": binding.run_id,
        "run_binding_sha256": binding.run_binding_sha256,
        "deadline": binding.deadline,
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def claim_checkpoint(root, binding):
    """Create ONE exclusive synthetic checkpoint claim; return SyntheticClaim.

    Validates the exact factory-live root and an exact RunStateBindingClaims
    (revalidated) BEFORE joining/writing. Creates
    SYNTHETIC-claim-<checkpoint_key>.json exclusively (O_EXCL) within the owned
    fixture. Filename derives ONLY from the 40-hex checkpoint. Returns the
    SHA256 of the exact written bytes. Never removes/truncates/repairs an
    existing or partially created claim; a failed write leaves poison bytes.
    No reset API. Synthetic single-winner marker, not durable authority.
    """
    # 1) exact factory-live root
    fixture_path = require_fixture_root(root)
    # 2) exact RunStateBindingClaims type + revalidate BEFORE joining/writing
    if type(binding) is not RunStateBindingClaims:
        raise SyntheticJournalError(
            "binding must be an exact RunStateBindingClaims")
    validated = validate_state_binding(
        binding.checkpoint_key, binding.run_id,
        binding.run_binding_sha256, binding.deadline)
    # 3) canonical payload
    payload = _claim_payload(validated)
    # 4) exclusive create + full write + flush + fsync
    claim_name = "SYNTHETIC-claim-%s.json" % validated.checkpoint_key
    claim_path = fixture_path / claim_name
    try:
        fh = open(claim_path, "xb")
    except FileExistsError as exc:
        raise SyntheticJournalError(
            "claim already exists (duplicate checkpoint): %s" % exc)
    except OSError as exc:
        raise SyntheticJournalError("claim creation failed: %s" % exc)
    try:
        with fh:
            written = fh.write(payload)
            if written != len(payload):
                raise SyntheticJournalError(
                    "claim short write: %d != %d" % (written, len(payload)))
            fh.flush()
            os.fsync(fh.fileno())
    except SyntheticJournalError:
        raise
    except OSError as exc:
        raise SyntheticJournalError("claim write failed: %s" % exc)
    # 5) SHA256 of exact written bytes
    header_sha256 = hashlib.sha256(payload).hexdigest()
    # 6) immutable SyntheticClaim
    claim = object.__new__(SyntheticClaim)
    object.__setattr__(claim, "_binding", validated)
    object.__setattr__(claim, "_header_sha256", header_sha256)
    return claim


# --- C1: strict bounded decoder + sealed reader (no append yet) -----------

def _bounded_read(path, limit, context):
    """Read at most limit+1 bytes; fail closed if overbound or OS error."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(limit + 1)
    except OSError as exc:
        raise SyntheticJournalError("%s: unreadable: %s" % (context, exc))
    if len(data) > limit:
        raise SyntheticJournalError("%s: overbound" % context)
    return data


def _reject_duplicate_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise SyntheticJournalError("duplicate JSON key")
        obj[key] = value
    return obj


def _strict_decode(data, expected_keys, context):
    """Strict canonical JSON decode. Returns dict. Fails closed on any error."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise SyntheticJournalError("%s: invalid UTF-8" % context)
    try:
        obj = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except SyntheticJournalError:
        raise
    except RecursionError:
        raise SyntheticJournalError("%s: parser recursion limit" % context)
    except ValueError:
        # includes JSONDecodeError and integer digit-limit
        raise SyntheticJournalError("%s: malformed JSON" % context)
    if type(obj) is not dict:
        raise SyntheticJournalError("%s: top-level must be an object" % context)
    if set(obj.keys()) != set(expected_keys):
        raise SyntheticJournalError("%s: exact field set mismatch" % context)
    try:
        canonical = json.dumps(
            obj, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except RecursionError:
        raise SyntheticJournalError("%s: encoder recursion limit" % context)
    except ValueError:
        raise SyntheticJournalError("%s: NaN/Inf not allowed" % context)
    if canonical != data:
        raise SyntheticJournalError("%s: non-canonical JSON encoding" % context)
    return obj


def _require_flags(obj, context):
    """Exact bool flags (never 1/0)."""
    if obj["SYNTHETIC"] is not True:
        raise SyntheticJournalError(
            "%s: SYNTHETIC must be exact bool True" % context)
    if obj["NON_PRODUCTION"] is not True:
        raise SyntheticJournalError(
            "%s: NON_PRODUCTION must be exact bool True" % context)
    if obj["AUTHORIZES_EXECUTION"] is not False:
        raise SyntheticJournalError(
            "%s: AUTHORIZES_EXECUTION must be exact bool False" % context)


def _require_sha(obj, key, context):
    """Strict lowercase 64-hex SHA via S1 validator."""
    value = obj[key]
    if type(value) is not str:
        raise SyntheticJournalError("%s: %s must be str" % (context, key))
    try:
        validate_sha256(value)
    except IdentityValidationError as exc:
        raise SyntheticJournalError("%s: %s: %s" % (context, key, exc))


def _is_seq4(stem):
    """True if stem is exactly a 4-digit zero-padded sequence string."""
    if len(stem) != 4:
        return False
    for ch in stem:
        if ch not in "0123456789":
            return False
    return True


def _make_snapshot(binding, history, header_sha256, head_sequence,
                   head_sha256, facts):
    snap = object.__new__(SyntheticJournalSnapshot)
    object.__setattr__(snap, "_binding", binding)
    object.__setattr__(snap, "_history", history)
    object.__setattr__(snap, "_header_sha256", header_sha256)
    object.__setattr__(snap, "_head_sequence", head_sequence)
    object.__setattr__(snap, "_head_sha256", head_sha256)
    object.__setattr__(snap, "_facts", facts)
    return snap


def load_journal(root, expected_binding, require_terminal=False):
    """Read a sealed synthetic journal; return immutable SyntheticJournalSnapshot.

    Performs NO writes/repair/rename/deletion. Bounded reads. Fails closed on
    any malformed/partial/orphan evidence. Synthetic recovery only, not OS
    restart/power-loss qualification. Snapshot is not permission/retry authority.
    """
    # 1) exact live factory root
    fixture_path = require_fixture_root(root)
    # 2) expected binding exact class + revalidate all fields
    if type(expected_binding) is not RunStateBindingClaims:
        raise SyntheticJournalError(
            "expected_binding must be an exact RunStateBindingClaims")
    validated = validate_state_binding(
        expected_binding.checkpoint_key, expected_binding.run_id,
        expected_binding.run_binding_sha256, expected_binding.deadline)
    # 3) require_terminal exact bool
    if type(require_terminal) is not bool:
        raise SyntheticJournalError("require_terminal must be exact bool")
    checkpoint = validated.checkpoint_key
    # 4) read + verify claim EXACT BYTES
    claim_path = fixture_path / ("SYNTHETIC-claim-%s.json" % checkpoint)
    claim_bytes = _bounded_read(claim_path, _CLAIM_MAX_BYTES, "claim")
    if claim_bytes != _claim_payload(validated):
        raise SyntheticJournalError(
            "claim does not match expected binding exact bytes")
    header_sha256 = hashlib.sha256(claim_bytes).hexdigest()
    # 5) discover exact bound-checkpoint event files
    prefix = "SYNTHETIC-event-%s-" % checkpoint
    prefix_fold = prefix.casefold()
    payload_paths = {}
    seal_paths = {}
    try:
        entries = os.listdir(fixture_path)
    except OSError:
        raise SyntheticJournalError("listdir failed")
    for entry in entries:
        if entry.startswith(prefix):
            pass
        elif entry.casefold().startswith(prefix_fold):
            raise SyntheticJournalError(
                "ambiguous noncanonical bound-checkpoint filename")
        else:
            continue
        suffix = entry[len(prefix):]
        if suffix.endswith(".seal.json"):
            stem = suffix[:-len(".seal.json")]
            kind = seal_paths
        elif suffix.endswith(".json"):
            stem = suffix[:-len(".json")]
            kind = payload_paths
        else:
            raise SyntheticJournalError("malformed event name: %r" % entry)
        if not _is_seq4(stem):
            raise SyntheticJournalError("malformed event sequence: %r" % entry)
        seq = int(stem)
        if seq > _EVENT_SEQ_MAX:
            raise SyntheticJournalError("sequence out of range: %d" % seq)
        kind[seq] = fixture_path / entry
    # 6) header-only (no events) is a valid INCOMPLETE snapshot
    if not payload_paths and not seal_paths:
        if require_terminal:
            raise SyntheticJournalError(
                "require_terminal but journal is header-only")
        return _make_snapshot(
            validated, (), header_sha256, -1, header_sha256, None)
    # 7) contiguous 0..head with matching payload+seal (no orphans/gaps)
    if set(payload_paths) != set(seal_paths):
        raise SyntheticJournalError("orphan payload/seal mismatch")
    seqs = sorted(payload_paths)
    if seqs != list(range(len(seqs))):
        raise SyntheticJournalError("sequence gap or missing predecessor")
    # 8) read + validate each payload/seal, build history
    history = []
    prev_sha = header_sha256
    for seq in seqs:
        ctx = "seq%d" % seq
        payload_bytes = _bounded_read(
            payload_paths[seq], _PAYLOAD_MAX_BYTES, "payload[%s]" % ctx)
        seal_bytes = _bounded_read(
            seal_paths[seq], _SEAL_MAX_BYTES, "seal[%s]" % ctx)
        payload_obj = _strict_decode(
            payload_bytes, _PAYLOAD_KEYS, "payload[%s]" % ctx)
        _require_flags(payload_obj, "payload[%s]" % ctx)
        if payload_obj["format"] != "SYNTHETIC_EVENT_V1":
            raise SyntheticJournalError("payload[%s]: bad format" % ctx)
        _require_sha(payload_obj, "previous_sha256", "payload[%s]" % ctx)
        if payload_obj["previous_sha256"] != prev_sha:
            raise SyntheticJournalError(
                "payload[%s]: previous link mismatch" % ctx)
        event_obj = payload_obj["event"]
        if type(event_obj) is not dict:
            raise SyntheticJournalError(
                "payload[%s]: event must be object" % ctx)
        if set(event_obj.keys()) != set(StateEventClaims._fields):
            raise SyntheticJournalError(
                "payload[%s]: event field set mismatch" % ctx)
        ev = StateEventClaims(
            event_obj["checkpoint_key"], event_obj["run_id"],
            event_obj["run_binding_sha256"], event_obj["deadline"],
            event_obj["sequence"], event_obj["event_id"],
            event_obj["phase"], event_obj["observed_now"])
        history.append(ev)
        seal_obj = _strict_decode(seal_bytes, _SEAL_KEYS, "seal[%s]" % ctx)
        _require_flags(seal_obj, "seal[%s]" % ctx)
        if seal_obj["format"] != "SYNTHETIC_EVENT_SEAL_V1":
            raise SyntheticJournalError("seal[%s]: bad format" % ctx)
        ck = seal_obj["checkpoint_key"]
        if type(ck) is not str:
            raise SyntheticJournalError(
                "seal[%s]: checkpoint_key must be str" % ctx)
        try:
            validate_git_commit(ck)
        except IdentityValidationError as exc:
            raise SyntheticJournalError(
                "seal[%s]: checkpoint_key: %s" % (ctx, exc))
        if ck != checkpoint:
            raise SyntheticJournalError("seal[%s]: checkpoint mismatch" % ctx)
        if type(seal_obj["sequence"]) is not int or seal_obj["sequence"] != seq:
            raise SyntheticJournalError("seal[%s]: sequence mismatch" % ctx)
        _require_sha(seal_obj, "payload_sha256", "seal[%s]" % ctx)
        payload_sha = hashlib.sha256(payload_bytes).hexdigest()
        if seal_obj["payload_sha256"] != payload_sha:
            raise SyntheticJournalError("seal[%s]: payload hash mismatch" % ctx)
        pb = seal_obj["payload_bytes"]
        if type(pb) is not int or pb <= 0:
            raise SyntheticJournalError("seal[%s]: payload_bytes invalid" % ctx)
        if pb != len(payload_bytes):
            raise SyntheticJournalError(
                "seal[%s]: payload byte count mismatch" % ctx)
        prev_sha = payload_sha
    history = tuple(history)
    # 9) validate full history with accepted reducer + bind to expected
    try:
        facts = validate_history(history)
    except StateValidationError as exc:
        raise SyntheticJournalError("history invalid: %s" % exc)
    fb = facts.binding
    if (fb.checkpoint_key != validated.checkpoint_key or
            fb.run_id != validated.run_id or
            fb.run_binding_sha256 != validated.run_binding_sha256 or
            fb.deadline != validated.deadline or
            type(fb.deadline) is not type(validated.deadline)):
        raise SyntheticJournalError(
            "history binding does not match expected binding")
    # 10) require_terminal
    if require_terminal and not facts.terminal:
        raise SyntheticJournalError(
            "require_terminal but history is nonterminal")
    return _make_snapshot(
        validated, history, header_sha256, seqs[-1], prev_sha, facts)


# --- C2: actual sealed append (payload-first, seal-last) ------------------

def _canon_bytes(obj):
    """Canonical UTF-8 JSON bytes (sorted keys, compact, no NaN)."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _event_payload_bytes(event, previous_sha):
    """Canonical C1-protocol event payload bytes."""
    return _canon_bytes({
        "format": "SYNTHETIC_EVENT_V1",
        "SYNTHETIC": True,
        "NON_PRODUCTION": True,
        "AUTHORIZES_EXECUTION": False,
        "previous_sha256": previous_sha,
        "event": {
            "checkpoint_key": event.checkpoint_key,
            "run_id": event.run_id,
            "run_binding_sha256": event.run_binding_sha256,
            "deadline": event.deadline,
            "sequence": event.sequence,
            "event_id": event.event_id,
            "phase": event.phase,
            "observed_now": event.observed_now,
        },
    })


def _seal_bytes(checkpoint, seq, payload_bytes):
    """Canonical C1-protocol event seal bytes."""
    return _canon_bytes({
        "format": "SYNTHETIC_EVENT_SEAL_V1",
        "SYNTHETIC": True,
        "NON_PRODUCTION": True,
        "AUTHORIZES_EXECUTION": False,
        "checkpoint_key": checkpoint,
        "sequence": seq,
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "payload_bytes": len(payload_bytes),
    })


def _event_filename(checkpoint, seq, kind):
    if kind == "payload":
        return "SYNTHETIC-event-%s-%04d.json" % (checkpoint, seq)
    return "SYNTHETIC-event-%s-%04d.seal.json" % (checkpoint, seq)


def _write_exclusive(root, checkpoint, seq, kind, data, context):
    """Exclusive create + full write + flush + fsync + bounded readback.

    Accepts the live factory root plus validated-domain checkpoint/sequence/
    kind. Validates exact builtin types BEFORE any comparison or formatting,
    then the canonical checkpoint, exact int nonbool 0..4 and exact kind
    payload/seal, all with zero IO; only then enforces live factory identity
    and derives the fixed synthetic filename internally. No caller path/name
    or arbitrary repr. Fails closed; never removes/truncates/repairs on
    failure (poison bytes). No auto retry on FileExists.
    """
    # validate exact builtin types BEFORE any comparison or formatting
    if type(checkpoint) is not str:
        raise SyntheticJournalError(
            "%s: checkpoint must be exact builtin str" % context)
    if type(seq) is not int or isinstance(seq, bool):
        raise SyntheticJournalError(
            "%s: sequence must be exact builtin int nonbool" % context)
    if type(kind) is not str:
        raise SyntheticJournalError(
            "%s: kind must be exact builtin str" % context)
    # validate canonical checkpoint (pure, zero IO)
    try:
        validate_git_commit(checkpoint)
    except IdentityValidationError as exc:
        raise SyntheticJournalError(
            "%s: checkpoint not canonical: %s" % (context, exc))
    # validate seq range 0..4 (pure)
    if seq < 0 or seq > _EVENT_SEQ_MAX:
        raise SyntheticJournalError(
            "%s: sequence out of range 0..4" % context)
    # validate exact kind payload/seal (pure)
    if kind != "payload" and kind != "seal":
        raise SyntheticJournalError(
            "%s: kind must be payload or seal" % context)
    # enforce live factory identity (only after all arg validation)
    fixture_path = require_fixture_root(root)
    # derive fixed synthetic filename internally
    name = _event_filename(checkpoint, seq, kind)
    path = fixture_path / name
    try:
        fh = open(path, "xb")
    except FileExistsError:
        raise SyntheticJournalError("%s: already exists" % context)
    except OSError:
        raise SyntheticJournalError("%s: create failed" % context)
    try:
        with fh:
            written = fh.write(data)
            if written != len(data):
                raise SyntheticJournalError("%s: short write" % context)
            fh.flush()
            os.fsync(fh.fileno())
    except SyntheticJournalError:
        raise
    except OSError:
        raise SyntheticJournalError("%s: write failed" % context)
    readback = _bounded_read(path, len(data), context)
    if readback != data:
        raise SyntheticJournalError("%s: readback mismatch" % context)
    return path


def append_record(root, expected_binding, event_id, phase, now, *,
                  expected_sequence, expected_previous_sha256):
    """Append ONE sealed event (payload-first, seal-last); return snapshot.

    No implicit IDs/time/head/default retry. Loads the current journal via the
    existing reader, verifies the expected head, builds the proposed history via
    accepted initial_history/append_event, validates ALL fields before creating
    any files, then writes payload FIRST and seal LAST exclusively. Fails closed;
    never removes/truncates/repairs (poison bytes). Not execution authority.
    """
    # 1) validate args (no implicit values)
    # reject non-exact builtin str phase BEFORE any comparison/equality/write
    if type(phase) is not str:
        raise SyntheticJournalError("phase must be exact builtin str")
    if type(expected_sequence) is not int or expected_sequence < 0 \
            or expected_sequence > _EVENT_SEQ_MAX:
        raise SyntheticJournalError(
            "expected_sequence must be exact builtin int 0..4")
    if type(expected_previous_sha256) is not str:
        raise SyntheticJournalError(
            "expected_previous_sha256 must be str")
    try:
        validate_sha256(expected_previous_sha256)
    except IdentityValidationError:
        raise SyntheticJournalError(
            "expected_previous_sha256 must be strict 64 lower hex")
    # 2) load current full journal via existing reader
    current = load_journal(root, expected_binding)
    # 3) verify expected head (stale/refused never retry next slot)
    if expected_sequence != current.head_sequence + 1:
        raise SyntheticJournalError("stale expected_sequence")
    if expected_previous_sha256 != current.head_sha256:
        raise SyntheticJournalError("stale expected_previous_sha256")
    if current.facts is not None and current.facts.terminal:
        raise SyntheticJournalError("append after terminal/abort refused")
    # 4) build proposed history via accepted initial_history/append_event
    validated = current.binding
    try:
        if current.history:
            proposed = append_event(current.history, event_id, phase, now)
        else:
            if phase != "RESERVED":
                raise SyntheticJournalError(
                    "first event phase must be RESERVED")
            proposed = initial_history(validated, event_id, now)
    except StateValidationError as exc:
        raise SyntheticJournalError("proposed history invalid: %s" % exc)
    if len(proposed) != expected_sequence + 1:
        raise SyntheticJournalError("proposed history length mismatch")
    # 5) build canonical payload/seal (exact C1 protocol)
    new_event = proposed[-1]
    payload_bytes = _event_payload_bytes(new_event, expected_previous_sha256)
    if len(payload_bytes) > _PAYLOAD_MAX_BYTES:
        raise SyntheticJournalError("payload overbound")
    seal_bytes = _seal_bytes(
        validated.checkpoint_key, expected_sequence, payload_bytes)
    if len(seal_bytes) > _SEAL_MAX_BYTES:
        raise SyntheticJournalError("seal overbound")
    # 6) exclusive payload FIRST, then seal LAST
    _write_exclusive(
        root,
        validated.checkpoint_key,
        expected_sequence,
        "payload",
        payload_bytes, "payload[seq%d]" % expected_sequence)
    _write_exclusive(
        root,
        validated.checkpoint_key,
        expected_sequence,
        "seal",
        seal_bytes, "seal[seq%d]" % expected_sequence)
    # 7) return immutable snapshot for committed proposed history
    facts = validate_history(proposed)
    head_sha = hashlib.sha256(payload_bytes).hexdigest()
    return _make_snapshot(
        validated, proposed, current.header_sha256,
        expected_sequence, head_sha, facts)