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


def encode_json_lf(value) -> bytes:
    """Deterministic UTF8/LF JSON encoding (no BOM, LF newlines, trailing
    newline, sorted keys). Repeated same inputs produce identical bytes."""
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
    raise GuardError(f"invalid package entry type: {type(entry).__name__}")


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
        raise GuardError(f"policy missing profile: {profile}")
    prof = profiles[profile]
    if not isinstance(prof, dict):
        raise GuardError(f"policy profile must be a dictionary: {profile}")
    pkg_policy = policy.get("package_policy")
    if not isinstance(pkg_policy, dict):
        raise GuardError("policy missing package_policy")
    approved = pkg_policy.get("approved")
    if not isinstance(approved, dict):
        raise GuardError("policy package_policy missing approved")

    result = {}
    for name in ("project", "global"):
        if name not in documents:
            raise GuardError(f"documents must supply a {name} JSON dictionary")
        src = documents[name]
        if not isinstance(src, dict):
            raise GuardError(f"documents[{name}] must be a JSON dictionary")
        doc = json.loads(json.dumps(src))  # deep copy (inputs not mutated)
        # Classified startup controls (extensions/skills arrays).
        lane = prof.get(name)
        if not isinstance(lane, dict):
            raise GuardError(f"policy profile missing lane: {name}")
        for key in ("extensions", "skills"):
            value = lane.get(key)
            if not isinstance(value, list):
                raise GuardError(f"policy profile {name}.{key} must be a list")
            doc[key] = list(value)
        # Package modifications: only explicitly classified source entries
        # and approved resource fields; source identity/nonresource fields
        # stay unchanged; unknown package bodies preserved.
        if "packages" in doc:
            packages = doc["packages"]
            if not isinstance(packages, list):
                raise GuardError(f"documents[{name}].packages must be a list")
            new_packages = []
            for entry in packages:
                source = _package_source(entry)
                rule = approved.get(source)
                if rule is None:
                    new_packages.append(entry)  # unknown/uncategorized: preserve
                    continue
                if not isinstance(rule, dict):
                    raise GuardError(f"approved rule must be a dictionary: {source}")
                if isinstance(entry, str):
                    new_entry = {"source": entry}
                else:
                    new_entry = dict(entry)  # preserve source identity/nonresource fields
                for field in ("extensions", "skills", "prompts", "themes"):
                    if field in rule:
                        value = rule[field]
                        if not isinstance(value, list):
                            raise GuardError(f"approved rule {source}.{field} must be a list")
                        new_entry[field] = list(value)
                new_packages.append(new_entry)
            doc["packages"] = new_packages
        result[name] = doc
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


def _verify_binding(journal, targets) -> None:
    """Target/journal binding mismatch fails closed; never trust arbitrary
    journal paths to choose write destinations."""
    journal_targets = journal.get("targets", {})
    if set(journal_targets) != set(targets):
        raise GuardError("journal/target binding mismatch: target sets differ")
    for name, record in journal_targets.items():
        if Path(record.get("path", "")) != Path(targets[name]):
            raise GuardError(f"journal/target binding mismatch for {name}: path differs")


def _auto_rollback(journal, targets, state_dir) -> None:
    """Auto-rollback from the journal on partial-write failure. Delegates to
    the SAME strict all-target preflight/CAS logic as explicit
    rollback_transaction (no independent weaker implementation). ORIGINAL
    skip; own APPLIED restore; THIRD_STATE/corrupt backup fail closed
    (RECOVERY_REQUIRED). Errors propagate (no skip/swallow loop)."""
    _verify_binding(journal, targets)
    rollback_transaction(targets=targets, state_dir=state_dir)


def _recover_pending(*, targets, state_dir) -> None:
    """Pending/interrupted transaction must be inspected/recovered BEFORE a
    new apply. Verifies schema/version/status and target binding; delegates
    pending/partial recovery to rollback_transaction. May proceed only after
    confirmed fully rolled_back. Unknown status or incomplete recovery =>
    GuardError RECOVERY_REQUIRED (does not overwrite journal or start a new
    transaction). Applied/rolled_back terminal states are explicit no-ops."""
    jpath = _journal_path(state_dir)
    if not jpath.exists():
        return
    journal = json.loads(jpath.read_text(encoding="utf-8"))
    if journal.get("schema") != "blg-apply-journal" or journal.get("version") != 1:
        raise GuardError("RECOVERY_REQUIRED: journal schema/version unrecognized")
    _verify_binding(journal, targets)
    status = journal.get("status")
    if status in ("applied", "rolled_back"):
        return  # terminal states: nothing to recover
    if status in ("in_progress", "rolled_back_partial"):
        _auto_rollback(journal, targets, state_dir)
        # Verify recovery completion before proceeding.
        recovered = json.loads(jpath.read_text(encoding="utf-8"))
        if recovered.get("status") != "rolled_back":
            raise GuardError("RECOVERY_REQUIRED: recovery did not reach rolled_back")
        return
    raise GuardError(f"RECOVERY_REQUIRED: unknown journal status: {status!r}")


def prepare_transaction(*, targets, documents, policy, state_dir, profile="bootstrap"):
    """Build candidates, read originals from injected paths, persist verified
    byte backups and the full journal BEFORE any settings write. Returns the
    journal dict. `targets` is an explicit name->Path map; `state_dir` is an
    explicit state directory (no default real paths)."""
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    # Pending/interrupted transaction must be inspected/recovered BEFORE a
    # new apply.
    _recover_pending(targets=targets, state_dir=state_dir)
    candidates = build_candidate_documents(documents, policy, profile=profile)
    # Verify state files do not alias settings targets.
    for name, path in targets.items():
        path = Path(path)
        for state_file in (state_dir / f"{name}-settings.json.orig", _journal_path(state_dir)):
            if state_file.resolve() == path.resolve():
                raise GuardError(f"state file aliases settings target for {name}")
    journal = {
        "schema": "blg-apply-journal",
        "version": 1,
        "transaction_id": uuid.uuid4().hex,
        "profile": profile,
        "status": "in_progress",
        "targets": {},
    }
    for name, path in targets.items():
        path = Path(path)
        if not path.exists():
            raise GuardError(f"cannot read missing settings file: {path}")
        original = path.read_bytes()
        intended = encode_json_lf(candidates[name])
        backup_copy = state_dir / f"{name}-settings.json.orig"
        if backup_copy.exists() and backup_copy.read_bytes() != original:
            raise GuardError(f"existing backup differs from live file for {name}; manual review required")
        backup_copy.write_bytes(original)
        if _sha256_bytes(backup_copy.read_bytes()) != _sha256_bytes(original):
            raise GuardError(f"backup copy not verified for {name}")
        journal["targets"][name] = {
            "path": str(path),
            "original_sha256": _sha256_bytes(original),
            "applied_sha256": _sha256_bytes(intended),
            "backup": str(backup_copy),
            "status": "pending",
        }
    # Journal persisted atomically BEFORE any settings write.
    _atomic_write(_journal_path(state_dir), (json.dumps(journal, indent=1) + "\n").encode("utf-8"))
    return journal


def apply_transaction(*, targets, documents, policy, state_dir, profile="bootstrap", write=None):
    """Prepare + apply with auto-rollback on partial-write failure. `write`
    is an optional injected write seam (for tests to inject a failing
    write); defaults to _atomic_write. Returns the manifest dict."""
    write = write or _atomic_write
    journal = prepare_transaction(targets=targets, documents=documents, policy=policy, state_dir=state_dir, profile=profile)
    candidates = build_candidate_documents(documents, policy, profile=profile)
    state_dir = Path(state_dir)
    try:
        for name, path in targets.items():
            path = Path(path)
            rec = journal["targets"][name]
            # Recheck before each write (ORIGINAL proceed; own APPLIED
            # idempotent proceed; THIRD_STATE refuse).
            current = _sha256_file(path)
            if current == rec["original_sha256"]:
                pass  # at original; proceed to apply
            elif current == rec["applied_sha256"]:
                pass  # already applied (idempotent rerun); proceed
            else:
                raise GuardError(f"apply aborted for {name}: current state is neither original nor journal-approved applied (possible external edit); refusing write")
            write(path, encode_json_lf(candidates[name]))
            journal["targets"][name]["status"] = "applied"
            _atomic_write(_journal_path(state_dir), (json.dumps(journal, indent=1) + "\n").encode("utf-8"))
    except BaseException:
        # Auto-rollback safely from the journal on partial-write failure.
        _auto_rollback(journal, targets, state_dir)
        raise
    # Final verification: every target at its journal-approved applied hash.
    for name, path in targets.items():
        if _sha256_file(Path(path)) != journal["targets"][name]["applied_sha256"]:
            journal["status"] = "failed_final_verify"
            _atomic_write(_journal_path(state_dir), (json.dumps(journal, indent=1) + "\n").encode("utf-8"))
            raise GuardError(f"final verification failed for {name}")
    journal["status"] = "applied"
    _atomic_write(_journal_path(state_dir), (json.dumps(journal, indent=1) + "\n").encode("utf-8"))
    manifest = {
        "schema": "blg-apply-manifest",
        "version": 1,
        "transaction_id": journal["transaction_id"],
        "profile": profile,
        "rollback": {name: {"sha256": rec["original_sha256"], "backup": rec["backup"]} for name, rec in journal["targets"].items()},
        "applied": {name: {"sha256": rec["applied_sha256"]} for name, rec in journal["targets"].items()},
    }
    _atomic_write(state_dir / "rollback-manifest.json", (json.dumps(manifest, indent=1) + "\n").encode("utf-8"))
    return manifest


def recover_transaction(*, targets, state_dir):
    """Inspect/recover any pending/interrupted transaction. Returns the
    journal status after recovery."""
    state_dir = Path(state_dir)
    jpath = _journal_path(state_dir)
    if not jpath.exists():
        return {"action": "NO_TRANSACTION"}
    journal = json.loads(jpath.read_text(encoding="utf-8"))
    _verify_binding(journal, targets)
    if journal.get("status") in ("in_progress", "rolled_back_partial"):
        _auto_rollback(journal, targets, state_dir)
        return {"action": "RECOVERED", "status": journal.get("status")}
    return {"action": "NO_RECOVERY_NEEDED", "status": journal.get("status")}


def rollback_transaction(*, targets, state_dir):
    """Journaled recoverable rollback. Preflight is ALL-or-NOTHING: every
    target must be at its ORIGINAL hash (already restored -> skip) or its
    journal-approved APPLIED hash (restore); any third state or corrupt
    backup aborts ALL before any write (unrelated edits never overwritten).
    Safe to rerun after a partial apply or partial rollback; idempotent
    once all targets are at original."""
    state_dir = Path(state_dir)
    jpath = _journal_path(state_dir)
    if not jpath.exists():
        raise GuardError("no apply journal; nothing to roll back")
    journal = json.loads(jpath.read_text(encoding="utf-8"))
    _verify_binding(journal, targets)
    journal_targets = journal.get("targets", {})
    # Phase 1: preflight ALL targets + ALL backup copies (zero writes).
    plan = []
    for name, record in journal_targets.items():
        path = Path(targets[name])
        current = _sha256_file(path)
        if current == record["original_sha256"]:
            continue  # already restored (skip; idempotent rerun)
        if current != record["applied_sha256"]:
            raise GuardError(f"rollback aborted for {name}: current state is neither original nor journal-approved applied (possible external edit); refusing all writes")
        backup_copy = state_dir / f"{name}-settings.json.orig"
        if not backup_copy.exists():
            raise GuardError(f"rollback aborted for {name}: backup copy missing")
        original = backup_copy.read_bytes()
        if _sha256_bytes(original) != record["original_sha256"]:
            raise GuardError(f"rollback aborted for {name}: backup copy does not match the recorded original hash")
        plan.append((name, path, original))
    if not plan:
        journal["status"] = "rolled_back"
        _atomic_write(jpath, (json.dumps(journal, indent=1) + "\n").encode("utf-8"))
        return {"action": "ALREADY_ROLLED_BACK", "rolled_back": True}
    # Phase 2: restore only the targets still at their approved applied state.
    for name, path, original in plan:
        _atomic_write(path, original)
        journal_targets[name]["status"] = "restored"
        _atomic_write(jpath, (json.dumps(journal, indent=1) + "\n").encode("utf-8"))
    # Final verification: every target at its original hash.
    for name, record in journal_targets.items():
        if _sha256_file(Path(targets[name])) != record["original_sha256"]:
            journal["status"] = "failed_final_verify"
            _atomic_write(jpath, (json.dumps(journal, indent=1) + "\n").encode("utf-8"))
            raise GuardError(f"rollback final verification failed for {name}")
    journal["status"] = "rolled_back"
    _atomic_write(jpath, (json.dumps(journal, indent=1) + "\n").encode("utf-8"))
    return {"action": "ROLLED_BACK", "rolled_back": True}