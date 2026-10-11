"""Offline F06 producer -> wire -> Worker replay fixture (G7): the single source of truth for
`cloud/test/fixtures/revenue-guidance-f06-sealed-replay.json`.

Chain: the genuine AUTO producer/serializer bytes (tests/fixtures/revenue-guidance-machine-auto-functional.json, byte-
checked against the real producer by tests/test_revenue_guidance_machine_auto_parity.py) are written as the same-owner
PUBLIC export (<id>.body.txt / <id>.binding.json) into a temporary stage root; the real
scripts/publish_sealed_snapshot.py main() seals them with --guidance-machine through the real
revenue_guidance_machine.read_staged_bundle, in the MACHINE_CARRIED tier shape of run_production_sealed_refresh.ps1
without the other lazy families (the Top20 is an honest INSUFFICIENT carry); the real scripts/stage_sealed_replay.py
stage() then writes the k<N>.txt + index.json layout cloud/test/live-kv-replay.test.ts reads. The fixture records that
staged layout verbatim; cloud/test/v213-revenue-guidance-f06-replay.test.ts loads it into a memory KV and reads it
through the real pinPublicSnapshot -> loadBottleneckV3 route, and tests/test_revenue_guidance_f06_replay.py checks
that the committed file is a fresh regeneration.

Fixture inputs only: the assembly clocks are pinned to the historical AUTO cutoff (the stamps --live-clock would give
at that instant), the macro rotation input is absent and the macro overview's own wall-clock stamp is pinned. The
export reader, publisher, activation claim, seal, pointer and stager are real. Every intermediate file lives in a
temporary directory and generation runs under a socket guard; only main() writes the committed fixture.
Regenerate the committed fixture with:  python -I -B -X utf8 tests/fixtures/make_revenue_guidance_f06_replay.py
"""
from __future__ import annotations

import contextlib
import io
import json
import socket
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(ROOT), str(ROOT / "scripts")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import publish_sealed_snapshot as publisher  # noqa: E402
import revenue_guidance_machine as machine  # noqa: E402
import stage_sealed_replay as stager  # noqa: E402

FIXTURE_PATH = ROOT / "cloud" / "test" / "fixtures" / "revenue-guidance-f06-sealed-replay.json"
AUTO_FIXTURE = ROOT / "tests" / "fixtures" / "revenue-guidance-machine-auto-functional.json"
SCHEMA = "revenue-guidance-f06-sealed-replay-v1"
SCOPE = "SYNTHETIC_HISTORICAL_AUTO_OFFLINE_REPLAY_NOT_NATIVE_OR_LIVE"
CUTOFF = "2026-02-27T13:00:00Z"
CLOCKS = {"LIVE_NOW": datetime(2026, 2, 27, 13, tzinfo=timezone.utc), "LIVE_STAMP": "20260227T130000Z",
          "EVALUATED_AT": CUTOFF, "GENERATED_AT": CUTOFF, "CLAIMED_AT": CUTOFF, "PROMOTED_AT": CUTOFF,
          "PUBLISHED_DATA_AS_OF": CUTOFF}
EXPORT_ID = "0f06" * 8  # the 32-hex PUBLIC export name (revenue_guidance_machine.TOKEN_PATTERN)
TOP20_REASON = "F06_REPLAY_TOP20_NOT_CARRIED"


def producer_bundle() -> tuple[bytes, bytes]:
    """The genuine AUTO report and binding bytes (scope SYNTHETIC_HISTORICAL_AUTO_NOT_NATIVE_OR_LIVE)."""
    auto = json.loads(AUTO_FIXTURE.read_text(encoding="utf-8"))
    return auto["report"].encode("utf-8"), auto["binding"].encode("utf-8")


@contextlib.contextmanager
def offline():
    def refuse(*_args, **_kwargs):
        raise AssertionError("F06 replay fixture: network is forbidden")
    with mock.patch.object(socket, "create_connection", side_effect=refuse), \
            mock.patch.object(socket, "getaddrinfo", side_effect=refuse):
        yield


def write_export(stage_root: Path, report: bytes, binding: bytes | None, export_id: str = EXPORT_ID) -> None:
    """The same-owner PUBLIC export files read_staged_bundle opens (binding None: the binding file is absent)."""
    stage_root.mkdir(parents=True, exist_ok=True)
    (stage_root / (export_id + ".body.txt")).write_bytes(report)
    if binding is not None:
        (stage_root / (export_id + ".binding.json")).write_bytes(binding)


def machine_argv(base: Path, report_sha256: str, binding_sha256: str, export_id: str = EXPORT_ID) -> list[str]:
    """MACHINE_CARRIED publisher arguments; the absent bundle path keeps the newest-LKG lookup off data/cache."""
    return ["--guidance-machine", "--guidance-public-token", export_id,
            "--guidance-report-sha256", report_sha256, "--guidance-binding-sha256", binding_sha256,
            "--top20-bundle", str(base / "absent-top20-bundle.json"), "--top20-insufficient", TOP20_REASON,
            "--snapshot-root", str(base / "snapshots")]


def run_publisher(argv: list[str], stage_root: Path) -> dict:
    """One real publisher.main(argv) with the fixture inputs pinned; returns the printed run summary."""
    real_overview = publisher.macro_builder.build_macro_overview_output

    def pinned_overview(*args, **kwargs):
        overview = real_overview(*args, **kwargs)
        overview["generated_at"] = CUTOFF  # the builder's own wall-clock stamp; everything else stays real
        return overview

    output = io.StringIO()
    with contextlib.ExitStack() as stack:
        stack.enter_context(offline())
        for name, value in CLOCKS.items():
            stack.enter_context(mock.patch.object(publisher, name, value))
        stack.enter_context(mock.patch.object(machine, "PUBLIC_STAGE_ROOT", stage_root))
        stack.enter_context(mock.patch.object(publisher.macro_builder, "load_rotation_candidates",
                                              return_value=([], {}, None)))
        stack.enter_context(mock.patch.object(publisher.macro_builder, "build_macro_overview_output",
                                              side_effect=pinned_overview))
        stack.enter_context(contextlib.redirect_stdout(output))
        publisher.main(argv)
    return json.loads(output.getvalue())


def generate() -> dict:
    """The staged sealed run as one fixture document (no file outside a temporary directory is written)."""
    report, binding = producer_bundle()
    with tempfile.TemporaryDirectory(prefix="ii-f06-replay-") as tmp:
        base = Path(tmp).resolve()
        stage_root = base / "guidance-public-exports"
        write_export(stage_root, report, binding)
        summary = run_publisher(machine_argv(base, machine.sha256(report), machine.sha256(binding)), stage_root)
        staged = base / "kv"
        run_id = stager.stage(base / "snapshots" / summary["run_id"], staged)
        index = json.loads((staged / "index.json").read_text(encoding="utf-8"))
        files = {name: (staged / name).read_bytes().decode("utf-8") for name in index.values()}
    if run_id != summary["run_id"]:
        raise AssertionError("staged run id differs from the sealed run id")
    return {"schema": SCHEMA, "scope": SCOPE, "cutoff": CUTOFF, "run_id": run_id,
            "top20_state": summary.get("top20_state"), "top20_reason": summary.get("top20_reason"),
            "lazy_objects": summary.get("lazy_objects"), "index": index, "files": files}


def serialize(document: dict) -> str:
    # ASCII-escaped (the sealed macro text is Chinese); JSON readers restore the exact body strings.
    return json.dumps(document, ensure_ascii=True, indent=1) + "\n"


def main() -> int:
    text = serialize(generate())
    FIXTURE_PATH.write_bytes(text.encode("ascii"))
    print(f"wrote {FIXTURE_PATH.relative_to(ROOT).as_posix()} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
