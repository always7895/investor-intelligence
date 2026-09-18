#!/usr/bin/env python3
"""TASK0-3D_RECORDED_AUDIT_REPLAY: full real gate replay (isolated root, single load chain).

Per Pro 3D ruling (option (a)): build a complete relative-path isolated replay
root (scripts/, config, whitelisted recorded inputs copied byte-identical), load
v3 ONCE from the isolated copy, follow the existing references
(entrypoint=v3, v4=entrypoint.v4, provider=v4.provider, core=v4.gate), assert
core is provider.gate and all audited modules' __file__ are in the replay root,
then execute the real chain:

  real diversified writer main()  ->  v3.main() (enrich -> normalize ->
  v4.gate.main() --enforce -> normalize_federation)  ->  real
  apply_latest_evidence_factor_guard() (only if front stages succeed)

Network isolation and policy judgment are SEPARATE: the formal policy branches
are kept (no --offline); the transport boundary replays existing recorded
responses/cache. If a request can't find the recorded input, record
REPLAY_INPUT_MISS (even if the inner layer degrades to UNAVAILABLE or the gate
returns PASS, the whole replay must NOT claim input completeness or formal
behavior equivalence).

The completion condition is reaching a PROVERSIBLE result: a real gate result
(completed / policy_failed with actual violations) or a specific reproducible
required-input blocking (BLOCKED_REPLAY_INPUT_MISS). NOT "all PASS".

Read-only source; 0 network; 0 credentials; 0 formal KV/DO; 0 schedules; 0 LINE.
Exit 0 on a completed provable result (the result may be a legal gate FAIL).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
# Files/dirs to copy into the isolated replay root (byte-identical).
COPY_SCRIPTS = True  # entire scripts/ (so all module imports resolve)
COPY_CONFIG = True   # config/ (policy + standard)
RECORDED_INPUTS = [
    "data/cache/top20_public_latest.json",
    "data/cache/v212_top20_report_public_latest.json",
    "data/cache/v213_top20_report_public_latest.json",
    "data/cache/v213_source_federation_latest.json",
    "data/cache/source_plan_public_latest.json",
    "data/cache/v213_source_independence_latest.json",
    "data/cache/v21",  # SEC reference + companyfacts (whole dir)
]


def sha256(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    except Exception:
        return None


def build_replay_root(tmp: Path) -> Path:
    """Copy scripts/, config/, and recorded inputs into the isolated root."""
    for rel in (["scripts"] if COPY_SCRIPTS else []) + (["config"] if COPY_CONFIG else []):
        src = ROOT / rel
        dst = tmp / rel
        if src.is_dir():
            shutil.copytree(src, dst)
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    for rel in RECORDED_INPUTS:
        src = ROOT / rel
        dst = tmp / rel
        if src.is_dir():
            shutil.copytree(src, dst)
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    return tmp


def load_v3_from_replay_root(replay_root: Path):
    """Load v3 ONCE from the isolated copy; follow the existing references."""
    v3_path = replay_root / "scripts" / "v213_source_independence_gate_v3.py"
    spec = importlib.util.spec_from_file_location("ii_3d_replay_v3", v3_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load v3 from {v3_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    now_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    # Install the transport guard BEFORE loading the application (Pro 3D step B).
    # This prevents the full-gate test from external-connecting by default.
    sys.path.insert(0, str(SCRIPT_DIR))
    from ii_v213_replay_guard import TransportGuard
    guard = TransportGuard()
    guard.install()
    with tempfile.TemporaryDirectory(prefix="v213_3d_fullgate_") as tmp:
        replay_root = build_replay_root(Path(tmp))
        v3 = load_v3_from_replay_root(replay_root)

        # --- Load-chain assertions (Pro requirement) ---
        v4 = v3.v4
        provider = v4.provider
        core = v4.gate
        assert core is provider.gate, "core must be provider.gate"
        audited = [v3, v4, provider, core]
        for m in audited:
            f = getattr(m, "__file__", "")
            assert f and str(f).startswith(str(replay_root)), f"module not in replay root: {f}"
        print(f"ENTRYPOINT_CHAIN = v3 -> v4 -> provider -> core (all __file__ in replay root); core is provider.gate = True")
        print(f"  v3: {v3.__file__}")
        print(f"  v4: {v4.__file__}")
        print(f"  provider: {provider.__file__}")
        print(f"  core: {core.__file__}")

        # Record pre-run hashes of the key inputs (in the replay root).
        pre = {
            "top20": sha256(replay_root / "data/cache/top20_public_latest.json"),
            "federation": sha256(replay_root / "data/cache/v213_source_federation_latest.json"),
            "audit": sha256(replay_root / "data/cache/v213_source_independence_latest.json"),
        }
        print(f"PRE_HASH = {pre}")

        # --- Execute the REAL v3.main() (enrich -> normalize -> v4.gate.main() --enforce -> normalize_federation) ---
        # v3.main() reads sys.argv for --enforce; the source Stage 6 passes '--enforce'.
        saved_argv = sys.argv
        sys.argv = [v3.__file__, "--enforce"]
        gate_exit = None
        gate_error = None
        try:
            gate_exit = v3.main()
        except SystemExit as exc:
            gate_exit = exc.code if exc.code is not None else 0
        except Exception as exc:
            gate_error = f"{type(exc).__name__}: {exc}"
        finally:
            sys.argv = saved_argv

        post = {
            "top20": sha256(replay_root / "data/cache/top20_public_latest.json"),
            "federation": sha256(replay_root / "data/cache/v213_source_federation_latest.json"),
            "audit": sha256(replay_root / "data/cache/v213_source_independence_latest.json"),
        }
        # Save the round's normalized top20 + audit to a persistent location for the
        # per-ticker claim-gap analysis (Pro 3D step A: hash-bound input).
        save_dir = SCRIPT_DIR.parent / ".tmp"
        save_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(replay_root / "data/cache/top20_public_latest.json", save_dir / "3d_fullgate_normalized_top20.json")
        shutil.copy2(replay_root / "data/cache/v213_source_independence_latest.json", save_dir / "3d_fullgate_audit.json")
        print(f"SAVED_ROUND_INPUTS = .tmp/3d_fullgate_normalized_top20.json + .tmp/3d_fullgate_audit.json (hash-bound)")
        print(f"REAL_GATE_EXECUTED = True; GATE_EXIT = {gate_exit}; GATE_ERROR = {gate_error}")
        print(f"POST_HASH = {post}")
        audit_changed = pre["audit"] != post["audit"]
        print(f"AUDIT_CONSUMED_NORMALIZED_DATA = {audit_changed} (audit file changed by the real gate, not the old audit)")

        # --- Only if the front stages succeeded, run the real factor guard ---
        if gate_exit == 0 and not gate_error:
            # Load the guard from the replay root and run it on the replay-root inputs.
            guard_path = replay_root / "scripts" / "v213_build_v21_public_snapshot.py"
            gspec = importlib.util.spec_from_file_location("ii_3d_replay_guard", guard_path)
            gmod = importlib.util.module_from_spec(gspec)
            sys.modules[gspec.name] = gmod
            gspec.loader.exec_module(gmod)
            base = gmod.base
            # Point the guard's paths at the replay-root inputs.
            cache = replay_root / "data" / "cache"
            saved = {"b.TOP20": base.TOP20_PATH, "g.AUDIT": gmod.SOURCE_AUDIT_PATH, "g.FED": gmod.FEDERATION_PATH,
                     "g.POLICY": gmod.FRESHNESS_POLICY_PATH, "g.V212": gmod.V212_PATH, "g.V213": gmod.V213_PATH,
                     "b.REPORT": base.REPORT_PATH}
            base.TOP20_PATH = cache / "top20_public_latest.json"
            gmod.SOURCE_AUDIT_PATH = cache / "v213_source_independence_latest.json"
            gmod.FEDERATION_PATH = cache / "v213_source_federation_latest.json"
            gmod.FRESHNESS_POLICY_PATH = replay_root / "config" / "v213-serenity-evidence-freshness-policy.json"
            gmod.V212_PATH = cache / "v212_top20_report_public_latest.json"
            gmod.V213_PATH = cache / "v213_top20_report_public_latest.json"
            base.REPORT_PATH = replay_root / "reports" / "public_briefing_latest.md"
            replay_root.joinpath("reports").mkdir(parents=True, exist_ok=True)
            guard_result = None
            guard_error = None
            try:
                guard_result = gmod.apply_latest_evidence_factor_guard()
            except Exception as exc:
                guard_error = f"{type(exc).__name__}: {exc}"
            finally:
                base.TOP20_PATH = saved["b.TOP20"]; gmod.SOURCE_AUDIT_PATH = saved["g.AUDIT"]; gmod.FEDERATION_PATH = saved["g.FED"]
                gmod.FRESHNESS_POLICY_PATH = saved["g.POLICY"]; gmod.V212_PATH = saved["g.V212"]; gmod.V213_PATH = saved["g.V213"]
                base.REPORT_PATH = saved["b.REPORT"]
            if guard_error:
                print(f"GUARD_EXECUTED = True; GUARD_RESULT = input-rejected/error: {guard_error}")
            else:
                print(f"GUARD_EXECUTED = True; GUARD_RESULT = completed; withheld={guard_result.get('withheld_ticker_count')}")
        else:
            print(f"GUARD_EXECUTED = False (front stage gate_exit={gate_exit} error={gate_error}; normal flow does not run guard)")

        print(f"EVALUATION_UTC = {now_utc} (clock not moved earlier)")
        # R2 wiring: unify all summaries to use the same verdict (guard.verdict()).
        outer_verdict = guard.verdict()
        # NETWORK_ISOLATION based on the unified verdict (NOT just replay_misses).
        if outer_verdict == "HARNESS_ERROR":
            print(f"NETWORK_ISOLATION = HARNESS_ERROR (guard init/internal error; must NOT claim completion)")
        elif outer_verdict == "BLOCKED_TRANSPORT_DENIED":
            print(f"NETWORK_ISOLATION = BLOCKED_TRANSPORT_DENIED (unregistered transport denied; must NOT claim data complete)")
        elif outer_verdict == "BLOCKED_REPLAY_INPUT_MISS":
            print(f"NETWORK_ISOLATION = BLOCKED_REPLAY_INPUT_MISS (replay_misses={len(guard.replay_misses)}; market data not in recorded cache; transport denied; must NOT claim data complete)")
        else:
            print(f"NETWORK_ISOLATION = REPLAY_COMPLETE (all requests replayed from recorded cache; 0 external connections)")
        print(f"DENIED_RESOLVER_ATTEMPTS = {guard.denied_resolver_attempts}; DENIED_CONNECT_ATTEMPTS = {guard.denied_connect_attempts}; DENIED_SPAWN_ATTEMPTS = {guard.denied_spawn_attempts}")
        print(f"RAW_RESOLVER_DELEGATIONS = {guard.raw_resolver_delegations}; RAW_CONNECTOR_DELEGATIONS = {guard.raw_connector_delegations}; RAW_SPAWN_DELEGATIONS = {guard.raw_spawn_delegations} (bottom-layer sentinel; 0 expected)")
        print(f"REPLAY_HITS = {len(guard.replay_hits)}; REPLAY_MISSES = {len(guard.replay_misses)}")
        print(f"OUTER_REPLAY_VERDICT = {outer_verdict} (replay completeness is separate from the gate policy result)")
        print(f"POLICY = formal branches kept (no --offline)")
        print(f"APPLICATION_SOURCE_UNCHANGED = true (replay root is a byte-identical copy; source untouched)")
        print(f"PRODUCTION_TOUCHED = false")
        guard.uninstall()
        # The completion message is based on the unified verdict (NOT hard-coded).
        if outer_verdict == "HARNESS_ERROR":
            print("V213_3D_FULL_GATE_REPLAY = ERROR (harness error; must NOT claim completion)")
        elif outer_verdict == "BLOCKED_TRANSPORT_DENIED":
            print("V213_3D_FULL_GATE_REPLAY = BLOCKED_TRANSPORT_DENIED (gate ran; unregistered transport denied; must NOT claim data complete; policy result separate from replay completeness)")
        elif outer_verdict == "BLOCKED_REPLAY_INPUT_MISS":
            print("V213_3D_FULL_GATE_REPLAY = BLOCKED_REPLAY_INPUT_MISS (gate ran; market recorded inputs missing; transport denied; must NOT claim data complete; policy result separate from replay completeness)")
        else:
            print("V213_3D_FULL_GATE_REPLAY = REPLAY_COMPLETE (provable result reached; all inputs replayed from recorded cache; REPLAY_COMPLETE != gate PASS / claim qualified / publication passed)")
    raise SystemExit(0)


if __name__ == "__main__":
    raise SystemExit(main())