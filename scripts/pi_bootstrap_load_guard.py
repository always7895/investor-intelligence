#!/usr/bin/env python3
"""Bootstrap load guard: candidate + injected-target transaction library.

Stdlib-only. Provides GuardError, a deterministic UTF8/LF JSON encoder, a
pure build_candidate_documents(documents, policy, profile) function, and
bounded transaction helpers (prepare/apply/recover/rollback) that operate
only on explicitly injected target paths, documents, policy, and state
directory. No live CLI, activation, receipts, or policy file is implemented
or qualified. Import performs zero settings IO.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path


class GuardError(RuntimeError):
    pass


def _validate_json_value(value) -> None:
    """Recursively reject nonfinite floats (NaN, Infinity, -Infinity)
    in JSON-serializable values. Raises GuardError on first violation."""
    import math
    if isinstance(value, float):
        if not math.isfinite(value):
            raise GuardError("BLG-E026: nonfinite float in JSON value")
    elif isinstance(value, dict):
        for v in value.values():
            _validate_json_value(v)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _validate_json_value(item)


def encode_json_lf(value) -> bytes:
    """Deterministic UTF8/LF JSON encoding (no BOM, LF newlines, trailing
    newline, sorted keys). Repeated same inputs produce identical bytes."""
    _validate_json_value(value)
    text = json.dumps(value, indent=1, ensure_ascii=False, sort_keys=True)
    return (text + "\n").encode("utf-8")


def _package_source(entry) -> str:
    """Extract the source identity from a package entry (string or dict).
    Reject invalid/ambiguous structures rather than guessing."""
    if isinstance(entry, str):
        if not entry.strip():
            raise GuardError("empty package source")
        return entry
    if isinstance(entry, dict):
        source = entry.get("source")
        if not isinstance(source, str) or not source.strip():
            raise GuardError("package dict missing or invalid source")
        return source
    raise GuardError("BLG-E001: invalid package entry type")


def build_candidate_documents(documents, policy, profile="bootstrap"):
    """Pure candidate builder: deep-copy the injected project/global JSON
    dictionaries, apply ONLY the policy-classified startup edits
    (extensions/skills arrays and approved package resource fields),
    preserve every unrelated key and unknown package body. No filesystem
    reads, no real target paths, no globals, no environment lookup, no CLI.
    Deterministic for repeated same inputs; inputs are not mutated.

    Compact policy shape:
      {
        "profiles": {
          "<profile>": {
            "global":  {"extensions": [...], "skills": [...]},
            "project": {"extensions": [...], "skills": [...]}
          }
        },
        "package_policy": {
          "approved": {
            "<source>": {"extensions": [...], "skills": [...],
                          "prompts": [...], "themes": [...]}
          }
        }
      }
    """
    if not isinstance(documents, dict):
        raise GuardError("documents must be a JSON dictionary")
    if not isinstance(policy, dict):
        raise GuardError("policy must be a JSON dictionary")
    profiles = policy.get("profiles")
    if not isinstance(profiles, dict) or profile not in profiles:
        raise GuardError("BLG-E002: policy missing profile")
    prof = profiles[profile]
    if not isinstance(prof, dict):
        raise GuardError("BLG-E003: policy profile must be a dictionary")
    pkg_policy = policy.get("package_policy")
    if not isinstance(pkg_policy, dict):
        raise GuardError("policy missing package_policy")
    approved = pkg_policy.get("approved")
    if not isinstance(approved, dict):
        raise GuardError("policy package_policy missing approved")

    result = {}
    for name in ("project", "global"):
        if name not in documents:
            raise GuardError("BLG-E004: documents must supply required JSON dictionary")
        src = documents[name]
        if not isinstance(src, dict):
            raise GuardError("BLG-E005: documents entry must be a JSON dictionary")
        _validate_json_value(src)
        doc = json.loads(json.dumps(src))  # deep copy (inputs not mutated)
        # Classified startup controls (extensions/skills arrays).
        lane = prof.get(name)
        if not isinstance(lane, dict):
            raise GuardError("BLG-E006: policy profile missing lane")
        for key in ("extensions", "skills"):
            value = lane.get(key)
            if not isinstance(value, list):
                raise GuardError("BLG-E007: policy profile lane field must be a list")
            doc[key] = list(value)
        # Package modifications: only explicitly classified source entries
        # and approved resource fields; source identity/nonresource fields
        # stay unchanged; unknown package bodies preserved.
        if "packages" in doc:
            packages = doc["packages"]
            if not isinstance(packages, list):
                raise GuardError("BLG-E008: documents packages must be a list")
            new_packages = []
            for entry in packages:
                source = _package_source(entry)
                rule = approved.get(source)
                if rule is None:
                    new_packages.append(entry)  # unknown/uncategorized: preserve
                    continue
                if not isinstance(rule, dict):
                    raise GuardError("BLG-E009: approved rule must be a dictionary")
                if isinstance(entry, str):
                    new_entry = {"source": entry}
                else:
                    new_entry = dict(entry)  # preserve source identity/nonresource fields
                for field in ("extensions", "skills", "prompts", "themes"):
                    if field in rule:
                        value = rule[field]
                        if not isinstance(value, list):
                            raise GuardError("BLG-E010: approved rule field must be a list")
                        new_entry[field] = list(value)
                new_packages.append(new_entry)
            doc["packages"] = new_packages
        result[name] = doc
    [_validate_json_value(v) for v in result.values()]
    return result


# ---------------------------------------------------------------------------
# Bounded transaction helpers (explicit required targets map + state dir;
# no default real paths, env, or CLI)
# ---------------------------------------------------------------------------

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def _atomic_write(path, data: bytes) -> None:
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-blg-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _journal_path(state_dir) -> Path:
    return Path(state_dir) / "apply-journal.json"


def _verify_sealed_path(sealed_str, current_resolved) -> None:
    """Verify the current resolved path is consistent with the sealed canonical
    path using pure lexical platform normalization via os.path.normcase.
    No filesystem access, no symlink/junction resolution, no stat.
    On Windows: case-insensitive and separator-equivalent (\\ and /).
    On POSIX: literal string comparison (backslashes preserved as filename
    characters). Reusable for sealed-path binding checks (including later
    backup slice)."""
    if not isinstance(sealed_str, str) or not sealed_str:
        raise GuardError("BLG-E011: journal/target binding mismatch: sealed path invalid")
    sealed = Path(sealed_str)
    if not sealed.is_absolute():
        raise GuardError("BLG-E011: journal/target binding mismatch: sealed path not absolute")
    sealed_norm = os.path.normcase(str(sealed))
    current_norm = os.path.normcase(str(current_resolved))
    if sealed_norm != current_norm:
        raise GuardError("BLG-E011: journal/target binding mismatch: resolved path differs")


def _verify_binding(journal, targets) -> None:
    """Target/journal binding mismatch fails closed; never trust arbitrary
    journal paths to choose write destinations. The sealed canonical path in
    the journal is immutable historical DATA, never re-resolved through
    resolve(). Only the current supplied target path is resolved and compared
    against the sealed absolute pathname using lexical platform normalization.
    Rejects invalid/nonabsolute sealed bindings and any current resolution
    inconsistent with the sealed path."""
    journal_targets = journal.get("targets", {})
    if set(journal_targets) != set(targets):
        raise GuardError("journal/target binding mismatch: target sets differ")
    for name, record in journal_targets.items():
        sealed_str = record.get("path", "")
        # Resolve ONLY the current supplied target path (never the sealed side).
        current_resolved = Path(targets[name]).resolve()
        _verify_sealed_path(sealed_str, current_resolved)


JOURNAL_SCHEMA = "blg-apply-journal-v2"
JOURNAL_VERSION = 2

# Legal progress states derived from actual implemented transitions.
LEGAL_ROOT_STATUSES = frozenset({
    "in_progress", "applied", "rolled_back",
    "rolled_back_partial", "rollback_in_progress", "failed_final_verify",
})
LEGAL_TARGET_STATUSES = frozenset({
    "pending", "applied", "restored",
})


def _validate_journal(journal) -> None:
    """Shared fail-closed schema/version/required-state validation.
    Called by ALL public entry points before any journal-dependent action.
    Rejects unknown schema, version, or missing required fields.
    Unsealed legacy journals (v1) fail closed."""
    if not isinstance(journal, dict):
        raise GuardError("RECOVERY_REQUIRED: journal is not a dictionary")
    if journal.get("schema") != JOURNAL_SCHEMA:
        raise GuardError("RECOVERY_REQUIRED: journal schema unrecognized (unsealed legacy fails closed)")
    # Version must be exact non-bool integer (rejects 2.0, True, "2").
    ver = journal.get("version")
    if isinstance(ver, bool) or not isinstance(ver, int) or ver != JOURNAL_VERSION:
        raise GuardError("RECOVERY_REQUIRED: journal version must be exact integer")
    if not isinstance(journal.get("targets"), dict):
        raise GuardError("RECOVERY_REQUIRED: journal missing targets")
    # Root status must be a known legal state.
    root_status = journal.get("status")
    if not isinstance(root_status, str) or root_status not in LEGAL_ROOT_STATUSES:
        raise GuardError("RECOVERY_REQUIRED: journal root status unrecognized")
    # Per-target status must be a known legal state.
    for tname, trec in journal["targets"].items():
        tstatus = trec.get("status")
        if not isinstance(tstatus, str) or tstatus not in LEGAL_TARGET_STATUSES:
            raise GuardError("RECOVERY_REQUIRED: target progress status unrecognized")
    if not isinstance(journal.get("transaction_id"), str):
        raise GuardError("RECOVERY_REQUIRED: journal missing transaction_id")
    # H7: checkpoint_digest is REQUIRED metadata (not authority).
    # Missing = schema failure, not a descriptor-hash change.
    if not isinstance(journal.get("checkpoint_digest"), str):
        raise GuardError("RECOVERY_REQUIRED: journal missing required checkpoint_digest field")


def compute_checkpoint_descriptor(journal) -> dict:
    """Extract the immutable checkpoint descriptor from a journal.
    Excludes mutable progress fields (status) and the stored seal itself
    (checkpoint_digest) to avoid self-referential hash."""
    return {
        "schema": journal["schema"],
        "version": journal["version"],
        "transaction_id": journal["transaction_id"],
        "targets": {
            name: {
                "path": rec["path"],
                "original_sha256": rec["original_sha256"],
                "applied_sha256": rec["applied_sha256"],
                "backup": rec["backup"],
            }
            for name, rec in journal["targets"].items()
        },
    }


def compute_checkpoint_digest(descriptor) -> str:
    """Compute the canonical checkpoint digest from an immutable descriptor."""
    return _sha256_bytes(encode_json_lf(descriptor))


def verify_checkpoint_integrity(expected_digest, journal) -> None:
    """H7 one integrity path: expected == recomputed == stored.
    For EVERY existing journal, BEFORE any status shortcut or restore.
    Missing/mismatched/tampered authority fails closed."""
    if not isinstance(expected_digest, str) or not expected_digest:
        raise GuardError("H7: missing or malformed expected checkpoint digest")
    _validate_journal(journal)
    # Recompute from journal's immutable descriptor.
    descriptor = compute_checkpoint_descriptor(journal)
    recomputed = compute_checkpoint_digest(descriptor)
    stored = journal["checkpoint_digest"]
    if expected_digest != recomputed:
        raise GuardError("H7: expected checkpoint does not match recomputed descriptor digest")
    if recomputed != stored:
        raise GuardError("H7: stored checkpoint seal does not match recomputed descriptor digest (forged or tampered)")


def _check_no_symlink(path) -> None:
    """Reject symlink/reparse-point backup entries to prevent escape
    outside the bound state directory."""
    p = Path(path)
    if p.is_symlink():
        raise GuardError("BLG-E012: backup path is a symlink; refusing")
    # On Windows, also check reparse points via os.stat
    try:
        st = os.stat(p, follow_symlinks=False)
        if getattr(st, "st_file_attributes", 0) & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
            raise GuardError("BLG-E013: backup path is a reparse point; refusing")
    except OSError:
        pass  # path doesn't exist yet; that's fine for new backups


def _file_identity(path) -> tuple:
    """Return (st_dev, st_ino) for file-identity comparison (hard-link
    detection). Returns (0, 0) if path doesn't exist."""
    try:
        st = os.stat(path)
        return (st.st_dev, st.st_ino)
    except OSError:
        return (0, 0)


def _auto_rollback(journal, targets, state_dir, expected_digest=None) -> None:
    """Auto-rollback from the journal on partial-write failure. Delegates to
    the SAME verified rollback path as explicit rollback_transaction.
    Internal: passes its retained prewrite digest through the same integrity
    check. No weaker second implementation."""
    _verify_binding(journal, targets)
    rollback_transaction(targets=targets, state_dir=state_dir, checkpoint_digest=expected_digest)


def _verify_backup_binding(journal, state_dir) -> None:
    """Verify each actual expected backup path under current supplied state_dir
    is consistent with the sealed backup path in the journal. The recorded
    backup path is immutable historical DATA, never re-resolved. Only the
    current expected backup path (under supplied state_dir) is resolved and
    compared against the sealed backup path using lexical platform
    normalization. Rejects any current resolution inconsistent with the
    sealed backup path."""
    state_dir = Path(state_dir)
    for name, record in journal.get("targets", {}).items():
        sealed_backup = record.get("backup", "")
        expected_backup = (state_dir / f"{name}-settings.json.orig").resolve()
        _verify_sealed_path(sealed_backup, expected_backup)


def _validate_terminal_claim(journal, targets, state_dir) -> None:
    """Verify a claimed terminal root status against actual per-target
    progress and current target bytes using checkpoint-sealed hashes.
    Applied requires all per-targets at 'applied' with current bytes
    matching applied_sha256. Rolled_back requires all per-targets at
    'restored' with current bytes matching original_sha256.
    Raises GuardError containing 'terminal' on impossible claims."""
    status = journal.get("status")
    if status not in ("applied", "rolled_back"):
        return
    journal_targets = journal.get("targets", {})
    for name, record in journal_targets.items():
        tstatus = record.get("status")
        current = _sha256_file(Path(targets[name]))
        if status == "applied":
            if tstatus != "applied":
                raise GuardError("BLG-E032: terminal claim impossible: applied requires per-target applied progress")
            if current != record["applied_sha256"]:
                raise GuardError("BLG-E032: terminal claim impossible: applied requires current bytes at applied hash")
        elif status == "rolled_back":
            if tstatus != "restored":
                raise GuardError("BLG-E032: terminal claim impossible: rolled_back requires per-target restored progress")
            if current != record["original_sha256"]:
                raise GuardError("BLG-E032: terminal claim impossible: rolled_back requires current bytes at original hash")


def _recover_pending(*, targets, state_dir, prior_checkpoint_digest=None) -> None:
    """Pending/interrupted transaction must be inspected/recovered BEFORE a
    new apply. Requires independently supplied PRIOR checkpoint for any
    existing journal. Fresh apply must NOT derive authority from old journal.
    Empty state (no journal) is a truthful read-only no-op."""
    jpath = _journal_path(state_dir)
    if not jpath.exists():
        return  # empty state: truthful read-only no-op
    journal = json.loads(jpath.read_text(encoding="utf-8"))
    # H7: one integrity path for ANY existing journal.
    if prior_checkpoint_digest is None:
        raise GuardError("H7: existing journal requires independently supplied prior checkpoint digest")
    verify_checkpoint_integrity(prior_checkpoint_digest, journal)
    _verify_binding(journal, targets)
    _verify_backup_binding(journal, state_dir)
    status = journal.get("status")
    if status in ("applied", "rolled_back"):
        _validate_terminal_claim(journal, targets, state_dir)
        return  # terminal: validated, nothing to recover
    if status in ("in_progress", "rolled_back_partial", "rollback_in_progress"):
        _auto_rollback(journal, targets, state_dir, expected_digest=prior_checkpoint_digest)
        recovered = json.loads(jpath.read_text(encoding="utf-8"))
        if recovered.get("status") != "rolled_back":
            raise GuardError("RECOVERY_REQUIRED: recovery did not reach rolled_back")
        return
    raise GuardError("BLG-E014: RECOVERY_REQUIRED: unknown journal status")


def _prepare_plan(*, targets, documents, policy, state_dir, profile="bootstrap", checkpoint_sink=None, prior_checkpoint_digest=None):
    """Private plan builder: captures encoded candidate bytes, target mapping,
    and journal BEFORE descriptor/callback. Returns a plan dict containing:
    journal, captured_targets, encoded_candidates, retained_digest.
    Raw candidate/original bytes are NOT persisted as extra journal fields.
    `checkpoint_sink` is REQUIRED for fresh transactions:
    a callable(descriptor_copy, digest) invoked BEFORE any helper writes.
    `prior_checkpoint_digest` is required if an existing journal is present."""
    state_dir = Path(state_dir)
    state_dir = state_dir.resolve()
    # Pending/interrupted transaction must be inspected/recovered BEFORE a
    # new apply. Requires independently supplied PRIOR checkpoint.
    _recover_pending(targets=targets, state_dir=state_dir, prior_checkpoint_digest=prior_checkpoint_digest)
    candidates = build_candidate_documents(documents, policy, profile=profile)
    # Require absolute target paths (H8: prevent relative-path rebinding).
    for name, path in targets.items():
        if not Path(path).is_absolute():
            raise GuardError("BLG-E015: target path must be absolute")
    # Verify state files do not alias settings targets (H1: extended check
    # including manifest, cross-target aliases, and file identity).
    all_state_files = []
    for name in targets:
        all_state_files.append(state_dir / f"{name}-settings.json.orig")
    all_state_files.append(_journal_path(state_dir))
    all_state_files.append(state_dir / "rollback-manifest.json")
    for name, path in targets.items():
        resolved_target = Path(path).resolve()
        target_identity = _file_identity(path)
        for state_file in all_state_files:
            if state_file.resolve() == resolved_target:
                raise GuardError("BLG-E016: state file aliases settings target")
            # File-identity check (hard-link detection)
            if target_identity != (0, 0) and state_file.exists():
                if _file_identity(state_file) == target_identity:
                    raise GuardError("BLG-E017: state file is a hard-link alias of settings target")
    # Cross-target alias check (H1: no two targets may be the same file).
    seen_identities = {}
    for name, path in targets.items():
        ident = _file_identity(path)
        if ident != (0, 0):
            if ident in seen_identities:
                raise GuardError("BLG-E018: cross-target alias: two targets are the same file")
            seen_identities[ident] = name
    journal = {
        "schema": JOURNAL_SCHEMA,
        "version": JOURNAL_VERSION,
        "transaction_id": uuid.uuid4().hex,
        "profile": profile,
        "status": "in_progress",
        "targets": {},
        "checkpoint_digest": "",  # sealed after sink succeeds
    }
    _originals = {}  # deferred backup bytes (written after sink succeeds)
    captured_targets = {}
    encoded_candidates = {}
    for name, path in targets.items():
        path = Path(path)
        captured_targets[name] = str(path.resolve())
        if not path.exists():
            raise GuardError("BLG-E019: cannot read missing settings file")
        original = path.read_bytes()
        # H3: Stale injected snapshot rejection. The injected documents must
        # match the current file content for ALL fields (including
        # policy-classified fields). If the file has been modified since the
        # documents were captured, reject before applying stale candidates.
        try:
            current_doc = json.loads(original.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise GuardError("BLG-E020: H3: cannot parse current file; refusing stale snapshot") from None
        # Type-aware comparison: Python True==1 but JSON types differ.
        # Use deterministic serialization to preserve value types.
        if encode_json_lf(current_doc) != encode_json_lf(documents[name]):
            raise GuardError("BLG-E021: H3: stale injected snapshot: documents do not match current file content (type-aware); refusing to apply")
        intended = encode_json_lf(candidates[name])
        encoded_candidates[name] = intended
        backup_copy = state_dir / f"{name}-settings.json.orig"
        # H2: reject symlink/reparse-point backup entries before any write.
        _check_no_symlink(backup_copy)
        if backup_copy.exists() and backup_copy.read_bytes() != original:
            raise GuardError("BLG-E022: existing backup differs from live file; manual review required")
        # Gather plan in memory; backup write deferred until after sink succeeds.
        journal["targets"][name] = {
            "path": captured_targets[name],
            "original_sha256": _sha256_bytes(original),
            "applied_sha256": _sha256_bytes(intended),
            "backup": str(backup_copy),
            "status": "pending",
        }
        # Retain original bytes for deferred backup write.
        _originals[name] = original
    # H7: Compute checkpoint descriptor and digest from the fresh in-memory plan.
    descriptor = compute_checkpoint_descriptor(journal)
    digest = compute_checkpoint_digest(descriptor)
    # H7: Invoke required checkpoint_sink BEFORE any helper writes
    # (backups, journal, targets). Deep copy passed to caller.
    if checkpoint_sink is None or not callable(checkpoint_sink):
        raise GuardError("H7: checkpoint_sink is required and must be callable")
    sink_copy = json.loads(json.dumps(descriptor))  # deep copy
    sink_copy_digest = digest  # immutable string
    try:
        checkpoint_sink(sink_copy, sink_copy_digest)
    except Exception:
        raise GuardError("H7: checkpoint_sink callback failed; aborting before any helper writes") from None
    # After sink: verify the copy was not mutated (digest comparison).
    if compute_checkpoint_digest(sink_copy) != digest:
        raise GuardError("H7: checkpoint_sink mutated the descriptor copy; aborting")
    # Seal the journal with the digest.
    journal["checkpoint_digest"] = digest
    # Helper retains its own separate immutable copy for internal auto-rollback.
    _helper_descriptor = json.loads(json.dumps(descriptor))
    _helper_digest = digest
    # Post-callback binding revalidation: after successful sink and
    # descriptor-copy integrity, but BEFORE any filesystem persistence
    # (mkdir, backup, journal), revalidate current destinations against
    # the already-sealed plan using private captured targets (never
    # caller-mutated mapping). Closes stable callback-time parent rebinding.
    _verify_binding(journal, captured_targets)
    _verify_backup_binding(journal, state_dir)
    # NOW: Create state directory and write backups (after sink succeeded,
    # before journal/target writes).
    state_dir.mkdir(parents=True, exist_ok=True)
    for name in captured_targets:
        backup_copy = state_dir / f"{name}-settings.json.orig"
        _atomic_write(backup_copy, _originals[name])
        if _sha256_bytes(backup_copy.read_bytes()) != _sha256_bytes(_originals[name]):
            raise GuardError("BLG-E023: backup copy not verified")
    # Journal persisted atomically BEFORE any settings write.
    _atomic_write(_journal_path(state_dir), (json.dumps(journal, indent=1) + "\n").encode("utf-8"))
    return {
        "journal": journal,
        "captured_targets": captured_targets,
        "encoded_candidates": encoded_candidates,
        "retained_digest": digest,
    }


def _public_boundary(func):
    """Stdlib-only public boundary: converts ordinary unexpected Exception
    into a fixed private-value-safe GuardError (raise from None). Trusted
    library GuardError diagnostics pass through unchanged. BaseException
    process-control interruptions are not caught."""
    import functools
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except GuardError as error:
            raise error from None
        except Exception:
            raise GuardError("BLG-E040: operational error; details suppressed") from None
    return wrapper


@_public_boundary
def prepare_transaction(*, targets, documents, policy, state_dir, profile="bootstrap", checkpoint_sink=None, prior_checkpoint_digest=None):
    """Build candidates, read originals from injected paths, persist verified
    byte backups and the full journal BEFORE any settings write. Returns the
    journal dict. `checkpoint_sink` is REQUIRED for fresh transactions:
    a callable(descriptor_copy, digest) invoked BEFORE any helper writes.
    `prior_checkpoint_digest` is required if an existing journal is present."""
    plan = _prepare_plan(targets=targets, documents=documents, policy=policy, state_dir=state_dir, profile=profile, checkpoint_sink=checkpoint_sink, prior_checkpoint_digest=prior_checkpoint_digest)
    return plan["journal"]


@_public_boundary
def apply_transaction(*, targets, documents, policy, state_dir, profile="bootstrap", write=None, checkpoint_sink=None, prior_checkpoint_digest=None):
    """Prepare + apply with auto-rollback on partial-write failure. `write`
    is an optional injected write seam (for tests to inject a failing
    write); defaults to _atomic_write. `checkpoint_sink` is REQUIRED.
    Returns the manifest dict."""
    write = write or _atomic_write
    state_dir = Path(state_dir).resolve()
    plan = _prepare_plan(targets=targets, documents=documents, policy=policy, state_dir=state_dir, profile=profile, checkpoint_sink=checkpoint_sink, prior_checkpoint_digest=prior_checkpoint_digest)
    journal = plan["journal"]
    captured_targets = plan["captured_targets"]
    encoded_candidates = plan["encoded_candidates"]
    retained_digest = plan["retained_digest"]
    try:
        for name in captured_targets:
            path = Path(captured_targets[name])
            rec = journal["targets"][name]
            # Recheck before each write (ORIGINAL proceed; own APPLIED
            # idempotent proceed; THIRD_STATE refuse).
            current = _sha256_file(path)
            if current == rec["original_sha256"]:
                pass  # at original; proceed to apply
            elif current == rec["applied_sha256"]:
                pass  # already applied (idempotent rerun); proceed
            else:
                raise GuardError("BLG-E024: apply aborted: current state is neither original nor journal-approved applied; refusing write")
            try:
                write(path, encoded_candidates[name])
            except Exception:
                raise GuardError("BLG-E040: write seam failure; details suppressed") from None
            journal["targets"][name]["status"] = "applied"
            _atomic_write(_journal_path(state_dir), (json.dumps(journal, indent=1) + "\n").encode("utf-8"))
        # H6: Final verification INSIDE the try block so failure triggers
        # _auto_rollback (not an unsupported recovery state).
        for name in captured_targets:
            if _sha256_file(Path(captured_targets[name])) != journal["targets"][name]["applied_sha256"]:
                journal["status"] = "failed_final_verify"
                _atomic_write(_journal_path(state_dir), (json.dumps(journal, indent=1) + "\n").encode("utf-8"))
                raise GuardError("BLG-E025: final verification failed")
    except BaseException as original:
        # Auto-rollback safely from the journal on partial-write or
        # final-verification failure. Uses retained prewrite digest.
        try:
            _auto_rollback(journal, captured_targets, state_dir, expected_digest=retained_digest)
        except BaseException as cleanup_exc:
            # Non-Exception process control (KeyboardInterrupt/SystemExit)
            # must not be replaced by an ordinary Exception from cleanup.
            if not isinstance(original, Exception) and isinstance(cleanup_exc, Exception):
                raise original from None
            raise
        raise original
    # M3: Write manifest BEFORE publishing applied terminal marker.
    # If manifest write fails, status remains in_progress (recoverable).
    manifest = {
        "schema": "blg-apply-manifest",
        "version": 1,
        "transaction_id": journal["transaction_id"],
        "profile": profile,
        "rollback": {name: {"sha256": rec["original_sha256"], "backup": rec["backup"]} for name, rec in journal["targets"].items()},
        "applied": {name: {"sha256": rec["applied_sha256"]} for name, rec in journal["targets"].items()},
    }
    _atomic_write(state_dir / "rollback-manifest.json", (json.dumps(manifest, indent=1) + "\n").encode("utf-8"))
    # Only after manifest success: publish applied terminal marker.
    journal["status"] = "applied"
    _atomic_write(_journal_path(state_dir), (json.dumps(journal, indent=1) + "\n").encode("utf-8"))
    return manifest


@_public_boundary
def recover_transaction(*, targets, state_dir, checkpoint_digest=None):
    """Inspect/recover any pending/interrupted transaction. Requires
    independently supplied `checkpoint_digest` for any existing journal.
    Empty state (no journal) is a truthful read-only NO_TRANSACTION no-op.
    Returns the journal status after recovery."""
    state_dir = Path(state_dir)
    jpath = _journal_path(state_dir)
    if not jpath.exists():
        return {"action": "NO_TRANSACTION"}  # empty state: truthful no-op
    journal = json.loads(jpath.read_text(encoding="utf-8"))
    # H7: one integrity path for ANY existing journal, BEFORE status shortcut.
    verify_checkpoint_integrity(checkpoint_digest, journal)
    _verify_binding(journal, targets)
    _verify_backup_binding(journal, state_dir)
    if journal.get("status") in ("in_progress", "rolled_back_partial", "rollback_in_progress"):
        _auto_rollback(journal, targets, state_dir, expected_digest=checkpoint_digest)
        # M2: Reload journal from disk after recovery; return actual
        # persisted outcome, not stale pre-recovery dict.
        reloaded = json.loads(jpath.read_text(encoding="utf-8"))
        return {"action": "RECOVERED", "status": reloaded.get("status")}
    if journal.get("status") == "failed_final_verify":
        raise GuardError("BLG-E031: RECOVERY_REQUIRED: journal status failed_final_verify is an unresolved nonterminal state; manual recovery is required")
    if journal.get("status") in ("applied", "rolled_back"):
        _validate_terminal_claim(journal, targets, state_dir)
    return {"action": "NO_RECOVERY_NEEDED", "status": journal.get("status")}


@_public_boundary
def rollback_transaction(*, targets, state_dir, checkpoint_digest=None):
    """Journaled recoverable rollback. Requires independently supplied
    `checkpoint_digest` for integrity verification BEFORE any restore.
    Preflight is ALL-or-NOTHING: every target must be at its ORIGINAL hash
    (already restored -> skip) or its journal-approved APPLIED hash (restore);
    any third state or corrupt backup aborts ALL before any write."""
    state_dir = Path(state_dir)
    jpath = _journal_path(state_dir)
    if not jpath.exists():
        raise GuardError("no apply journal; nothing to roll back")
    journal = json.loads(jpath.read_text(encoding="utf-8"))
    # H7: one integrity path BEFORE any status shortcut or restore.
    verify_checkpoint_integrity(checkpoint_digest, journal)
    # Private canonical CURRENT target map (resolved paths for write safety).
    captured = {name: str(Path(targets[name]).resolve()) for name in targets}
    _verify_binding(journal, captured)
    _verify_backup_binding(journal, state_dir)
    journal_targets = journal.get("targets", {})
    # Phase 1: preflight ALL targets + ALL backup copies (zero writes).
    plan = []
    for name, record in journal_targets.items():
        path = Path(captured[name])
        current = _sha256_file(path)
        if current == record["original_sha256"]:
            record["status"] = "restored"  # genuinely already-original: LOCAL journal mark (no disk write)
            continue  # already restored (skip; idempotent rerun)
        if current != record["applied_sha256"]:
            raise GuardError("BLG-E026: rollback aborted: current state is neither original nor journal-approved applied; refusing all writes")
        backup_copy = state_dir / f"{name}-settings.json.orig"
        if not backup_copy.exists():
            raise GuardError("BLG-E027: rollback aborted: backup copy missing")
        original = backup_copy.read_bytes()
        if _sha256_bytes(original) != record["original_sha256"]:
            raise GuardError("BLG-E028: rollback aborted: backup copy does not match recorded original hash")
        plan.append((name, path, original))
    if not plan:
        journal["status"] = "rolled_back"
        _atomic_write(jpath, (json.dumps(journal, indent=1) + "\n").encode("utf-8"))
        return {"action": "ALREADY_ROLLED_BACK", "rolled_back": True}
    # H5: Persist rollback_in_progress BEFORE first restore. Interrupted
    # rollback is recoverable; never reports rolled_back until complete.
    journal["status"] = "rollback_in_progress"
    _atomic_write(jpath, (json.dumps(journal, indent=1) + "\n").encode("utf-8"))
    # Phase 2: restore only the targets still at their approved applied state.
    # H4: Recheck each target immediately before restore (post-preflight
    # edits must survive; no cross-file atomicity claimed).
    for name, path, original in plan:
        current = _sha256_file(path)
        if current != journal_targets[name]["applied_sha256"]:
            raise GuardError("BLG-E029: rollback aborted: state changed since preflight; refusing restore")
        _atomic_write(path, original)
        journal_targets[name]["status"] = "restored"
        _atomic_write(jpath, (json.dumps(journal, indent=1) + "\n").encode("utf-8"))
    # Final verification: every target at its original hash.
    for name, record in journal_targets.items():
        if _sha256_file(Path(captured[name])) != record["original_sha256"]:
            journal["status"] = "failed_final_verify"
            _atomic_write(jpath, (json.dumps(journal, indent=1) + "\n").encode("utf-8"))
            raise GuardError("BLG-E030: rollback final verification failed")
    journal["status"] = "rolled_back"
    _atomic_write(jpath, (json.dumps(journal, indent=1) + "\n").encode("utf-8"))
    return {"action": "ROLLED_BACK", "rolled_back": True}