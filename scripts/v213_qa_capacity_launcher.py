"""
v213_qa_capacity_launcher.py — INERT refusal-only stub (Gate B REWORK, 2026-09-23).

This module is a containment placeholder, NOT an implementation. It:
  * unconditionally raises DraftNotAcceptedError from every execution entry
    (Controller.run, legacy Controller._run_sequence, and direct calls);
  * makes the CLI main return a nonzero ABORT before any argument parsing;
  * contains NO mutable acceptance switch, NO real Win32/process/TCP/
    namespace/window/native/resume helpers, and NO import of the accepted
    runner. The unsafe prototype is preserved only in audit evidence and is
    never invoked or imported from this module.

Any future genuine implementation must be new source reviewed through the
exact-SHA chain (Gate B). This stub exists so every public caller fails
closed with an explicit refusal.
"""
import json
import sys

SCHEMA = "qa-capacity-native-launcher-handoff-v1"

_REFUSAL = (
    "v213_qa_capacity_launcher is an UNACCEPTED draft (Gate B not accepted); "
    "execution is disabled. No handoff, gate, argv, or seam may bypass this "
    "refusal. The unsafe prototype is preserved in audit evidence only."
)


class DraftNotAcceptedError(Exception):
    """Unconditional refusal raised by every execution entry of this stub."""

    def __init__(self):
        super().__init__(_REFUSAL)


class Controller:
    """Inert refusal-only controller. It stores caller references without
    validating or acting on them; every execution entry raises
    DraftNotAcceptedError unconditionally, before any side effect."""

    def __init__(self, handoff, *, seams=None):
        self.handoff = handoff
        self.seams = seams

    def run(self, *, native_argv):
        raise DraftNotAcceptedError()

    def _run_sequence(self, *, native_argv):
        raise DraftNotAcceptedError()

    def _attempt_sequence(self, *, native_argv, attempt=None):
        raise DraftNotAcceptedError()

    def __call__(self, *args, **kwargs):
        raise DraftNotAcceptedError()


def main(argv=None):
    """CLI entry. Refuses BEFORE any argument parsing, handoff loading, or
    side effect: prints ABORT JSON and returns nonzero."""
    print(json.dumps({"status": "ABORT", "reason": _REFUSAL,
                      "native_attempt_established": False}))
    return 1


if __name__ == "__main__":
    sys.exit(main())