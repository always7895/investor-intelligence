"""Fixed protected Python entry. F02C SOURCE ONLY / IMPLEMENTED_UNVERIFIED.

Invoked ONLY by a trusted operator/protected host using the approved interpreter:
  <protected Python/python.exe> -I -S -B <protected scripts/this file> <command>
No self-elevation, automatic install/enrollment, arbitrary modules, test runner or
completion claim. F02D still owns same-process real-model execution and PS transport.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Initial entry is independently trusted and protected by the operator/installer;
# these checks cannot secure execution of an already replaced bootstrap/interpreter.
_BASE = Path(r"C:\Program Files\InvestorIntelligence\GuidanceProtected\releases")
_here = Path(__file__)
if _here.name != "revenue_guidance_bootstrap.py" or _here.parent.name != "scripts" or _here.parent.parent.parent != _BASE:
    raise SystemExit("TRUST_AUTHORITY_UNAVAILABLE")
if not sys.flags.isolated or not sys.flags.no_site or not sys.flags.dont_write_bytecode:
    raise SystemExit("TRUST_AUTHORITY_UNAVAILABLE")
sys.path.insert(0, str(_here.parent))  # ONLY the fixed protected closure, never a caller path

import revenue_guidance_provisioner as provisioner


def acquire(parent_remaining_ms, *, parent_deadline):
    """Fresh controlled authority on every acquisition, no process anchor cache."""
    import revenue_guidance_storage as storage
    return storage.open_storage_lease(provisioner.enrolled_anchor(), storage.NativeLimits.b1(parent_remaining_ms),
                                      parent_deadline=parent_deadline)


def _pending(lease, snapshot):
    import revenue_guidance_revision as revision
    current_revision = revision.compute_input_revision(snapshot)
    observed = lease.read_journal()
    state = dict(observed.state)
    # No recovery acknowledgement, fake model completion or on-disk hash witness.
    # A prior intent is conservatively retained until the P1/F02D host recovers it.
    state["InputRevision"] = current_revision
    state["PendingRevision"] = current_revision  # this entry has NO genuine live completion witness
    if state != observed.state:
        committed = lease.commit_journal(observed.version, state)
        if not committed.success:
            raise ValueError("JOURNAL_CONFLICT")
    return {"input_revision": current_revision, "state_required": True,
            "pending_revision": state["PendingRevision"], "intent_pending": state["Intent"] is not None,
            "model_complete": False}


def _native_custody_unresolved():
    # Consult only an ALREADY loaded native domain: no import/binding/probe here.
    domain = sys.modules.get("revenue_guidance_windows")
    return ((domain is not None and domain.native_custody_status() == "UNRESOLVED") or
            provisioner.origin_custody_status() == "UNRESOLVED")


def _hold_native_lifetime():
    domain = sys.modules.get("revenue_guidance_windows")
    if not _native_custody_unresolved():
        return
    # Initial authority cleanup may fail BEFORE the native storage module loads.
    # Both seams retain real owners under the SAME no-exit/no-retry lifetime rule.
    holder = domain.hold_unresolved_native_custody if domain is not None else provisioner.hold_unresolved_origin_custody
    emitted = False
    while True:
        try:
            if not emitted:
                # No success, raw error, owner/ACL/principal details or acknowledgement.
                emitted = True
                print('{"status":"NATIVE_CUSTODY_UNRESOLVED","model_complete":false}', flush=True)
            holder()  # actual owner/context/origin remain rooted
        except BaseException:
            # Interrupt/output failure is NOT permission to exit/unload. This
            # repeats only the lifetime wait, NEVER native IO/cleanup/cancellation.
            continue


def run_with_native_lifetime(argv=None):
    """Outermost owner boundary, also on BaseException/SystemExit/finally failure.

    Known settled failures may return/exit nonzero. Unresolved native custody never
    takes that return path; only external operator/OS termination can end its owner.
    F02D must reuse the windows status/hold seam, not create a new native policy.
    """
    try:
        return main(argv)
    except BaseException:
        actual_args = sys.argv[1:] if argv is None else argv
        if actual_args and actual_args[0] == "host":
            # Protocol child must never emit raw tracebacks, including interrupts
            # before its safe diagnostic adapter loads. No cleanup acknowledgement.
            try:
                sys.stderr.write("HOST_ENTRY_UNAVAILABLE\n")
                sys.stderr.flush()
            except BaseException:
                pass
            return 2
        raise
    finally:
        _hold_native_lifetime()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("enroll", "snapshot", "check", "update", "maintain", "recount", "host"))
    parser.add_argument("--remaining-ms", type=int, default=600000,
                        help="may only tighten this entry's real fixed request deadline")
    args = parser.parse_args(argv)
    if args.remaining_ms <= 0:
        parser.error("positive remaining budget required")
    origin = None
    try:
        # Independent code/principal/policy admission BEFORE backend clock/budget.
        origin = provisioner.controlled_origin(issuer=args.command == "enroll")
        origin.close()
        origin = None
        if args.command == "host":
            # Fixed protected module only. No caller module/path/function/eval.
            import revenue_guidance_host
            return revenue_guidance_host.serve(min(args.remaining_ms, 600000))
        import time
        request_deadline = time.monotonic() + min(args.remaining_ms, 600000) / 1000
        import revenue_guidance_overlay as overlay
        from datetime import datetime, timezone
        remaining = lambda: max(0, int((request_deadline - time.monotonic()) * 1000))
        if args.command == "enroll":
            import revenue_guidance_enroll as enrollment
            result = enrollment.enroll(remaining(), parent_deadline=request_deadline)
        else:
            with acquire(remaining(), parent_deadline=request_deadline) as lease:
                with lease.namespace_operation():
                    lease.constrain_remaining_budget(remaining())
                    store = overlay.B1Store(lease)
                    result = {"status": "OK", "model_complete": False}
                    if args.command in ("check", "update", "maintain"):
                        from sec_contact_headers import sec_identity_headers
                        # The source of public SEC contact headers belongs to the
                        # approved closure. Never echo contact/credential contents.
                        headers = sec_identity_headers()
                        if args.command in ("check", "maintain"):
                            import revenue_guidance_release_check as checker
                            now = datetime.now(timezone.utc).replace(microsecond=0)
                            result["check"] = checker.run(None, store / "receipts.json", now, state_root=store,
                                                        network=checker.ReceiptTransport(store, headers))
                            if result["check"]["status"] != "OK":
                                result["status"] = "CHECK_UNAVAILABLE_PENDING_REBUILD"
                        if args.command in ("update", "maintain"):
                            import revenue_guidance_autoupdate as updater
                            result["update"] = updater.run(store, updater.Transport(headers), lambda: datetime.now(timezone.utc))
                    elif args.command == "recount":
                        result["usage"] = overlay.recount_usage(store)
                        if result["usage"]["status"] != "RECOUNTED":
                            result["status"] = "STORE_ACCOUNTING_UNKNOWN_PENDING_REBUILD"
                    # New store: actually recapture changed receipts/pointer, not a
                    # stale epoch byte-cache. Shared common snapshot assembler.
                    fresh = overlay.B1Store(lease)
                    snapshot = overlay.require_snapshot(overlay.load_effective_inputs(
                        cutoff=datetime.now(timezone.utc), state_root=fresh, state_required=True))
                    result.update(_pending(lease, snapshot))
                    result["condition"] = snapshot.condition
                    result["input_digest"] = snapshot.input_digest  # not gir1 and not authentication
                    result["dispositions"] = {s: snapshot.issuer(s).disposition for s in snapshot.symbols()}
                    if snapshot.condition == "STATE_FAILURE":
                        result["status"] = "STATE_UNAVAILABLE_PENDING_REBUILD"
        if _native_custody_unresolved():
            return 2  # outer finally vetoes actual return/exit; do not emit success
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] in ("OK", "ENROLLED_PENDING_REBUILD") else 2
    except Exception:
        if not _native_custody_unresolved():
            if args.command == "host":
                sys.stderr.write("HOST_ENTRY_UNAVAILABLE\n")
                sys.stderr.flush()
            else:
                print('{"status":"CAPABILITY_UNAVAILABLE","model_complete":false}')
        # The outer boundary, NOT this generic failure handler, owns unresolved
        # custody lifetime. No ordinary process return/exit when it is retained.
        return 2
    finally:
        if origin is not None:
            origin.close()


if __name__ == "__main__":
    raise SystemExit(run_with_native_lifetime())
