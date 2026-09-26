"""v213 QA capacity control state — tiny persisted ticket01 component.

Pure helpers:
  remaining_budget(deadline, now, previous_now)
  check_authority_pair_claims(auth, handoff, expected_namespace, now)

No clock read, IO, or accepted-runner imports. The S1 pure identity import
(v213_qa_capacity_control_identity) is permitted; no accepted runner/IO imports.
No namespace/state/journal/authority functionality beyond pure in-memory CLAIM
shape/consistency and pure lexical namespace comparison. Neither helper grants
A-G or authorizes execution.
"""

import math
import unicodedata
from collections import namedtuple
from pathlib import PureWindowsPath

from v213_qa_capacity_control_identity import (
    ACCEPTED_CONTROLLER_IDENTITY,
    IdentityValidationError,
    validate_git_commit,
    validate_sha256,
)


class StateValidationError(ValueError):
    """Raised for wrong-type, nonfinite, backward, exceeded, or overflow."""


def _is_finite(value):
    # math.isfinite raises OverflowError for huge builtin ints that cannot be
    # represented as float; normalize that to a representability failure.
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _require_coordinate(value, name):
    # Exact builtin int/float only; reject bool and any subclass.
    if type(value) is not int and type(value) is not float:
        raise StateValidationError(
            "%s must be an exact builtin int or float" % name
        )
    if not _is_finite(value):
        raise StateValidationError("%s must be finite" % name)


def remaining_budget(deadline, now, previous_now):
    """Return deadline - now under strict monotonic finite coordinates.

    Fails when now < previous_now (backward) or now > deadline (exceeded).
    now == deadline returns 0. The result is always finite. The deadline is
    a coordinate argument and is never reset here.
    """
    _require_coordinate(deadline, "deadline")
    _require_coordinate(now, "now")
    _require_coordinate(previous_now, "previous_now")

    if now < previous_now:
        raise StateValidationError("now must not be before previous_now")
    if now > deadline:
        raise StateValidationError("now must not exceed deadline")

    result = deadline - now
    if not _is_finite(result):
        raise StateValidationError("result overflowed to nonfinite")
    return result


# --- ticket02: pure in-memory CLAIM consistency (NOT authority) -----------

TASK_ID = "QA_CAPACITY_OPERATOR_HANDOFF_NATIVE_ONE_SHOT_6922278_V5"


class AuthorityPairFacts:
    """Frozen non-authorizing CLAIM facts. authorizes_execution and
    namespace_requires_attestation are fixed class flags and are NOT
    constructor/_replace inputs. Scalar fields are immutable read-only facts."""
    __slots__ = (
        "task_id", "fixup_sha", "authorized_source_sha",
        "run_plan_sha256", "request_sha256", "harness_sha256",
        "window_id", "valid_from_epoch_s", "valid_until_epoch_s",
        "run_namespace", "operator",
    )
    authorizes_execution = False
    namespace_requires_attestation = True

    def __init__(self, task_id, fixup_sha, authorized_source_sha,
                 run_plan_sha256, request_sha256, harness_sha256,
                 window_id, valid_from_epoch_s, valid_until_epoch_s,
                 run_namespace, operator):
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "fixup_sha", fixup_sha)
        object.__setattr__(self, "authorized_source_sha", authorized_source_sha)
        object.__setattr__(self, "run_plan_sha256", run_plan_sha256)
        object.__setattr__(self, "request_sha256", request_sha256)
        object.__setattr__(self, "harness_sha256", harness_sha256)
        object.__setattr__(self, "window_id", window_id)
        object.__setattr__(self, "valid_from_epoch_s", valid_from_epoch_s)
        object.__setattr__(self, "valid_until_epoch_s", valid_until_epoch_s)
        object.__setattr__(self, "run_namespace", run_namespace)
        object.__setattr__(self, "operator", operator)

    def __setattr__(self, name, value):
        raise AttributeError("AuthorityPairFacts is immutable")

    def __delattr__(self, name):
        raise AttributeError("AuthorityPairFacts is immutable")


def _is_nonempty_str(value):
    return type(value) is str and len(value) > 0


def _require_pinned(value, accepted, validator, label):
    # S1 strict shape validator (lowercase hex, exact type/length) plus exact
    # accepted-pin equality. IdentityValidationError normalized to
    # StateValidationError. No uppercase normalization, no caller pins.
    try:
        checked = validator(value)
    except IdentityValidationError as exc:
        raise StateValidationError("%s: %s" % (label, exc))
    if checked != accepted:
        raise StateValidationError(
            "%s does not equal accepted S1 pin" % label
        )
    return checked


def _is_windows_absolute(value):
    # Pure parsing only; no resolve/stat/etc. Does not claim canonicality.
    return PureWindowsPath(value).is_absolute()


def _require_mapping(mapping, name):
    if type(mapping) is not dict:
        raise StateValidationError("%s must be an exact builtin dict" % name)
    for key in mapping:
        if type(key) is not str:
            raise StateValidationError("%s has a non-str key" % name)


def _require_field(mapping, name, field):
    if field not in mapping:
        raise StateValidationError(
            "%s is missing required field %s" % (name, field)
        )
    return mapping[field]


def check_authority_pair_claims(auth, handoff, expected_namespace, now):
    """Return frozen non-authorizing CLAIM facts for a runner auth/handoff pair.

    Consistency/shape of in-memory claims only: NOT byte observation, review
    approval, operator authentication, runtime admission, or full runner
    compatibility. Never grants A-G. All failures are StateValidationError.
    """
    _require_mapping(auth, "auth")
    _require_mapping(handoff, "handoff")

    auth_task = _require_field(auth, "auth", "task_id")
    handoff_task = _require_field(handoff, "handoff", "task_id")
    if not _is_nonempty_str(auth_task) or auth_task != TASK_ID:
        raise StateValidationError("auth.task_id is invalid")
    if not _is_nonempty_str(handoff_task) or handoff_task != TASK_ID:
        raise StateValidationError("handoff.task_id is invalid")

    acc = ACCEPTED_CONTROLLER_IDENTITY
    fixup = _require_pinned(
        _require_field(auth, "auth", "fixup_sha"),
        acc.source_head, validate_git_commit, "auth.fixup_sha")
    auth_src = _require_pinned(
        _require_field(auth, "auth", "authorized_source_sha"),
        acc.source_head, validate_git_commit, "auth.authorized_source_sha")
    handoff_src = _require_pinned(
        _require_field(handoff, "handoff", "authorized_source_sha"),
        acc.source_head, validate_git_commit,
        "handoff.authorized_source_sha")

    pins = {}
    for field in ("run_plan_sha256", "request_sha256", "harness_sha256"):
        pins[field] = _require_pinned(
            _require_field(auth, "auth", field),
            getattr(acc, field), validate_sha256, "auth.%s" % field)
        _require_pinned(
            _require_field(handoff, "handoff", field),
            getattr(acc, field), validate_sha256, "handoff.%s" % field)

    auth_win = _require_field(auth, "auth", "window_id")
    handoff_win = _require_field(handoff, "handoff", "window_id")
    if not _is_nonempty_str(auth_win) or not _is_nonempty_str(handoff_win):
        raise StateValidationError("window_id must be a nonempty builtin str")
    if auth_win != handoff_win:
        raise StateValidationError("window_id mismatch")

    auth_from = _require_field(auth, "auth", "valid_from_epoch_s")
    handoff_from = _require_field(handoff, "handoff", "valid_from_epoch_s")
    auth_until = _require_field(auth, "auth", "valid_until_epoch_s")
    handoff_until = _require_field(handoff, "handoff", "valid_until_epoch_s")
    for value in (auth_from, handoff_from, auth_until, handoff_until):
        _require_coordinate(value, "epoch bound")
    if auth_from != handoff_from:
        raise StateValidationError("valid_from_epoch_s mismatch")
    if auth_until != handoff_until:
        raise StateValidationError("valid_until_epoch_s mismatch")
    if not (auth_from < auth_until):
        raise StateValidationError(
            "valid_from_epoch_s must be < valid_until_epoch_s"
        )

    _require_coordinate(now, "now")
    if not (auth_from <= now < auth_until):
        raise StateValidationError("now must satisfy from<=now<until")

    auth_ns = _require_field(auth, "auth", "run_namespace")
    handoff_ns = _require_field(handoff, "handoff", "run_namespace")
    if not _is_nonempty_str(auth_ns) or not _is_nonempty_str(handoff_ns):
        raise StateValidationError(
            "run_namespace must be a nonempty builtin str"
        )
    if auth_ns != handoff_ns:
        raise StateValidationError("run_namespace mismatch")
    if type(expected_namespace) is not str or not _is_windows_absolute(
        expected_namespace
    ):
        raise StateValidationError(
            "expected_namespace must be a Windows absolute path"
        )
    if auth_ns != expected_namespace:
        raise StateValidationError("run_namespace must equal expected_namespace")

    operator = _require_field(handoff, "handoff", "operator")
    if not _is_nonempty_str(operator):
        raise StateValidationError("operator must be a nonempty builtin str")

    return AuthorityPairFacts(
        task_id=auth_task,
        fixup_sha=fixup,
        authorized_source_sha=auth_src,
        run_plan_sha256=pins["run_plan_sha256"],
        request_sha256=pins["request_sha256"],
        harness_sha256=pins["harness_sha256"],
        window_id=auth_win,
        valid_from_epoch_s=auth_from,
        valid_until_epoch_s=auth_until,
        run_namespace=auth_ns,
        operator=operator,
    )


# --- ticket03 step A: private pure lexical parser (NOT public yet) ---------

def _parse_namespace_lexical(value):
    """Pure private lexical parser. Returns (normalized, drive_letter, comps).

    No IO/clock/env/process; no Path.resolve/stat. No filesystem claims.
    Slash->backslash conversion only. RAW component validation happens before
    any PureWindowsPath parsing. All rejects are StateValidationError with
    static messages. A bare drive root returns empty components for the
    caller to reject later.
    """
    if type(value) is not str or len(value) == 0:
        raise StateValidationError(
            "value must be an exact builtin nonempty str")

    normalized = value.replace("/", "\\")

    if normalized.startswith("\\\\"):
        raise StateValidationError("UNC or device prefix not allowed")
    if len(normalized) < 3:
        raise StateValidationError("path too short for drive-rooted absolute")
    drive = normalized[0]
    if not (("A" <= drive <= "Z") or ("a" <= drive <= "z")):
        raise StateValidationError("must start with an ASCII drive letter")
    if normalized[1] != ":":
        raise StateValidationError("missing drive colon")
    if normalized[2] != "\\":
        raise StateValidationError("missing drive-root separator")

    drive_letter = drive
    rest = normalized[3:]

    if rest != "" and rest.endswith("\\"):
        raise StateValidationError("trailing separator not allowed")
    if rest == "":
        return normalized, drive_letter, ()

    components = tuple(rest.split("\\"))
    reserved_bases = frozenset(
        ("CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"))
    serial_prefixes = ("COM", "LPT")
    superscripts = ("\u00b9", "\u00b2", "\u00b3")

    for comp in components:
        if comp == "":
            raise StateValidationError("empty component (duplicate separator)")
        if comp == "." or comp == "..":
            raise StateValidationError("dot/traversal component not allowed")
        for ch in comp:
            if ch in "<>:\"|?*":
                raise StateValidationError("invalid character in component")
            if unicodedata.category(ch) == "Cc":
                raise StateValidationError(
                    "NUL or Unicode control character not allowed")
        if comp.endswith(" ") or comp.endswith("."):
            raise StateValidationError(
                "component trailing space/dot not allowed")
        for i in range(len(comp) - 1):
            if comp[i] == "~" and comp[i + 1] in "0123456789":
                raise StateValidationError(
                    "short-name-looking component not allowed")
        base = comp.split(".", 1)[0].rstrip(" ").upper()
        if base in reserved_bases:
            raise StateValidationError("reserved device name not allowed")
        for pref in serial_prefixes:
            if base.startswith(pref):
                tail = base[len(pref):]
                if len(tail) == 1 and (
                    tail in "0123456789" or tail in superscripts
                ):
                    raise StateValidationError(
                        "reserved serial/LPT name not allowed")

    return normalized, drive_letter, components


# --- ticket03 step B: immutable lexical facts + public caller --------------

class LexicalNamespaceFacts:
    """Frozen non-authorizing LEXICAL facts. Fixed class flags are NOT
    constructor/_replace inputs. Scalar fields are immutable read-only facts.
    LEXICAL only: no filesystem/canonical identity is established."""
    __slots__ = (
        "raw_root", "raw_candidate",
        "normalized_root", "normalized_candidate",
        "root_drive", "candidate_drive",
        "root_components", "candidate_components",
    )
    LEXICAL_ONLY = True
    FILESYSTEM_ATTESTATION_REQUIRED = True
    AUTHORIZES_EXECUTION = False
    ROOT_IDENTITY_UNATTESTED = True
    root_alias_policy = "EXACT_CASE_COMPONENT_PREFIX"

    def __init__(self, raw_root, raw_candidate,
                 normalized_root, normalized_candidate,
                 root_drive, candidate_drive,
                 root_components, candidate_components):
        object.__setattr__(self, "raw_root", raw_root)
        object.__setattr__(self, "raw_candidate", raw_candidate)
        object.__setattr__(self, "normalized_root", normalized_root)
        object.__setattr__(self, "normalized_candidate", normalized_candidate)
        object.__setattr__(self, "root_drive", root_drive)
        object.__setattr__(self, "candidate_drive", candidate_drive)
        object.__setattr__(self, "root_components", root_components)
        object.__setattr__(self, "candidate_components", candidate_components)

    def __setattr__(self, name, value):
        raise AttributeError("LexicalNamespaceFacts is immutable")

    def __delattr__(self, name):
        raise AttributeError("LexicalNamespaceFacts is immutable")


def check_namespace_lexical(canonical_root, candidate):
    """Return frozen LEXICAL-only facts for a root/candidate pair.

    Pure string comparison after slash->backslash normalization. Uses the
    private parser on both. Root must be a named directory (>=1 component);
    candidate must be a STRICT descendant via exact raw-case component prefix.
    No Path.resolve/stat/reparse/clock/network/process or filesystem claim.
    All failures are StateValidationError.
    """
    root_norm, root_drive, root_comps = _parse_namespace_lexical(canonical_root)
    cand_norm, cand_drive, cand_comps = _parse_namespace_lexical(candidate)

    if len(root_comps) < 1:
        raise StateValidationError(
            "root must be a named directory, not a bare drive root")

    if root_drive != cand_drive:
        if root_drive.upper() != cand_drive.upper():
            raise StateValidationError("candidate drive differs from root")
        raise StateValidationError("ROOT_ALIAS_AMBIGUOUS")

    n = len(root_comps)
    if cand_comps[:n] != root_comps:
        if (tuple(p.casefold() for p in cand_comps[:n])
                == tuple(p.casefold() for p in root_comps)):
            raise StateValidationError("ROOT_ALIAS_AMBIGUOUS")
        raise StateValidationError("candidate is outside root")

    if len(cand_comps) <= n:
        raise StateValidationError(
            "candidate must be a strict descendant of root")

    return LexicalNamespaceFacts(
        raw_root=canonical_root,
        raw_candidate=candidate,
        normalized_root=root_norm,
        normalized_candidate=cand_norm,
        root_drive=root_drive,
        candidate_drive=cand_drive,
        root_components=root_comps,
        candidate_components=cand_comps,
    )


# --- ticket04 step B1: tuple-based immutable records + phase constants -----

PHASES = ("RESERVED", "VERIFIED", "ACTIVATION_RESERVED", "RUNNER_STARTED", "TERMINAL")
ABORT = "ABORT"


class RunStateBindingClaims(namedtuple("RunStateBindingClaims",
        ["checkpoint_key", "run_id", "run_binding_sha256", "deadline"])):
    """Tuple-based immutable binding CLAIM. Fixed class flags are NOT
    constructor fields. Scalar positions are immutable tuple elements."""
    __slots__ = ()
    AUTHORIZES_EXECUTION = False
    SYNTHETIC_CLAIMS_ONLY = True


class StateEventClaims(namedtuple("StateEventClaims",
        ["checkpoint_key", "run_id", "run_binding_sha256", "deadline",
         "sequence", "event_id", "phase", "observed_now"])):
    """Tuple-based immutable event CLAIM. Represents untrusted CLAIM data,
    not a validated transition. Fixed class flags are NOT constructor fields."""
    __slots__ = ()
    AUTHORIZES_EXECUTION = False
    SYNTHETIC_CLAIMS_ONLY = True


_RUN_ID_ALLOWED = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


def validate_state_binding(checkpoint_key, run_id, run_binding_sha256, deadline):
    """Strict pure binding CLAIM validator. Returns frozen RunStateBindingClaims.

    checkpoint_key: 40-lowercase-hex Git-style claim (S1 shape, NOT runtime pin).
    run_id: exact builtin nonempty portable ASCII letters/digits/_/- <=128.
    run_binding_sha256: 64-lowercase-hex opaque claim (S1 shape).
    deadline: finite nonbool representable builtin numeric.
    No IO/clock/RNG. No Event/history. AUTHORIZES_EXECUTION always False.
    """
    try:
        ck = validate_git_commit(checkpoint_key)
    except IdentityValidationError as exc:
        raise StateValidationError("checkpoint_key: %s" % exc)

    if type(run_id) is not str or len(run_id) == 0 or len(run_id) > 128:
        raise StateValidationError(
            "run_id must be nonempty builtin str <=128 chars")
    for ch in run_id:
        if ch not in _RUN_ID_ALLOWED:
            raise StateValidationError(
                "run_id contains invalid character %r" % ch)

    try:
        rb = validate_sha256(run_binding_sha256)
    except IdentityValidationError as exc:
        raise StateValidationError("run_binding_sha256: %s" % exc)

    _require_coordinate(deadline, "deadline")

    return RunStateBindingClaims(
        checkpoint_key=ck, run_id=run_id,
        run_binding_sha256=rb, deadline=deadline)


# --- ticket04 step B2: immutable derived facts + complete-history validator ---

class StateHistoryFacts(namedtuple("StateHistoryFacts",
        ["binding", "phase", "sequence", "last_observed_now",
         "invocation_count", "event_ids", "terminal",
         "activation_history_ambiguous"])):
    """Tuple-based immutable derived history facts. NOT an authorization API."""
    __slots__ = ()
    AUTHORIZES_EXECUTION = False
    SYNTHETIC_CLAIMS_ONLY = True


def validate_history(history):
    """Pure complete-history validator. Returns frozen StateHistoryFacts.

    Accepts a history tuple ONLY; derives counts/flags. Never caller overrides.
    No IO/clock/RNG. No global exactly-once/durability/authority claim.
    """
    if type(history) is not tuple:
        raise StateValidationError("history must be an exact builtin tuple")
    if len(history) < 1 or len(history) > 5:
        raise StateValidationError("history length must be 1..5")
    for i, ev in enumerate(history):
        if type(ev) is not StateEventClaims:
            raise StateValidationError(
                "history[%d] must be exact StateEventClaims" % i)

    first_binding = validate_state_binding(
        history[0].checkpoint_key, history[0].run_id,
        history[0].run_binding_sha256, history[0].deadline)
    for i, ev in enumerate(history):
        # Validate each event binding BEFORE any value comparison (C1 repair)
        try:
            eb = validate_state_binding(
                ev.checkpoint_key, ev.run_id,
                ev.run_binding_sha256, ev.deadline)
        except StateValidationError as exc:
            raise StateValidationError(
                "history[%d] binding: %s" % (i, exc))
        if (eb.checkpoint_key != first_binding.checkpoint_key or
                eb.run_id != first_binding.run_id or
                eb.run_binding_sha256 != first_binding.run_binding_sha256 or
                eb.deadline != first_binding.deadline):
            raise StateValidationError(
                "history[%d] binding does not match first" % i)
        if type(eb.deadline) is not type(first_binding.deadline):
            raise StateValidationError(
                "history[%d] deadline type mismatch" % i)

    seen_ids = set()
    prev_now = None
    invocation_count = 0
    is_terminal = False

    for i, ev in enumerate(history):
        if type(ev.sequence) is bool or type(ev.sequence) is not int:
            raise StateValidationError(
                "history[%d].sequence must be exact builtin int" % i)
        if ev.sequence != i:
            raise StateValidationError(
                "history[%d].sequence must equal %d" % (i, i))
        try:
            validate_sha256(ev.event_id)
        except IdentityValidationError as exc:
            raise StateValidationError(
                "history[%d].event_id: %s" % (i, exc))
        if ev.event_id in seen_ids:
            raise StateValidationError(
                "history[%d].event_id duplicate" % i)
        seen_ids.add(ev.event_id)
        if type(ev.phase) is not str:
            raise StateValidationError(
                "history[%d].phase must be exact builtin str" % i)
        if ev.phase not in PHASES and ev.phase != ABORT:
            raise StateValidationError(
                "history[%d].phase invalid" % i)
        _require_coordinate(ev.observed_now, "observed_now")
        if prev_now is not None and ev.observed_now < prev_now:
            raise StateValidationError(
                "history[%d].observed_now backward" % i)

        if i == 0:
            if ev.phase != "RESERVED":
                raise StateValidationError(
                    "first event phase must be RESERVED")
        else:
            if is_terminal:
                raise StateValidationError("append after terminal/abort")
            if ev.phase != ABORT:
                prev_phase = history[i - 1].phase
                prev_idx = PHASES.index(prev_phase)
                if ev.phase != PHASES[prev_idx + 1]:
                    raise StateValidationError(
                        "history[%d] phase not next forward" % i)

        if ev.phase != ABORT:
            if ev.observed_now >= first_binding.deadline:
                raise StateValidationError(
                    "history[%d] forward at/after deadline" % i)
            prev = ev.observed_now if i == 0 else prev_now
            remaining_budget(first_binding.deadline, ev.observed_now, prev)

        if ev.phase == "ACTIVATION_RESERVED":
            invocation_count = None
        elif ev.phase in ("RUNNER_STARTED", "TERMINAL"):
            invocation_count = 1
        if ev.phase in ("TERMINAL", ABORT):
            is_terminal = True
        prev_now = ev.observed_now

    last = history[-1]
    return StateHistoryFacts(
        binding=first_binding,
        phase=last.phase,
        sequence=last.sequence,
        last_observed_now=last.observed_now,
        invocation_count=invocation_count,
        event_ids=tuple(ev.event_id for ev in history),
        terminal=is_terminal,
        activation_history_ambiguous=(invocation_count is None))


# --- ticket04 step C1: small initial/append APIs (NOT launch rights) -------

def initial_history(binding, event_id, now):
    """Create a one-event RESERVED history. Returns immutable tuple.

    binding: exact RunStateBindingClaims (revalidated).
    event_id: S1 SHA256 shape. now: explicit finite coordinate.
    No clock/default IDs/permission. Validates full one-event tuple.
    """
    if type(binding) is not RunStateBindingClaims:
        raise StateValidationError(
            "binding must be exact RunStateBindingClaims")
    validated = validate_state_binding(
        binding.checkpoint_key, binding.run_id,
        binding.run_binding_sha256, binding.deadline)
    ev = StateEventClaims(
        validated.checkpoint_key, validated.run_id,
        validated.run_binding_sha256, validated.deadline,
        0, event_id, "RESERVED", now)
    hist = (ev,)
    validate_history(hist)
    return hist


def append_event(history, event_id, phase, now):
    """Append one event to a validated history. Returns new immutable tuple.

    Validates complete original history first. Copies bound identity/deadline
    from validated facts. sequence=len(history). Never mutates original.
    No reset/retry/resume. No caller binding/deadline/counter overrides.
    """
    facts = validate_history(history)
    seq = len(history)
    ev = StateEventClaims(
        facts.binding.checkpoint_key, facts.binding.run_id,
        facts.binding.run_binding_sha256, facts.binding.deadline,
        seq, event_id, phase, now)
    new_history = history + (ev,)
    validate_history(new_history)
    return new_history