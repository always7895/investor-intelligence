#!/usr/bin/env python3
"""Verify an immutable R75 FREE_RELAY deployment-hotfix artifact."""
from __future__ import annotations

import argparse
import hashlib
import fnmatch
import json
import posixpath
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v213_model_profile import parse_profile, profile_sha256

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
BASE = "43f3be048cedf228cfe9e8e31f7b9901895838be"


class VerificationError(RuntimeError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(value: str) -> str:
    if not value or "\\" in value or "\0" in value:
        raise VerificationError("unsafe ZIP path")
    path = PurePosixPath(value)
    if path.is_absolute() or re.match(r"^[A-Za-z]:", value) or any(p in {"", ".", ".."} for p in path.parts):
        raise VerificationError("unsafe ZIP path")
    return path.as_posix().rstrip("/")


def load_json(data: bytes, label: str) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result
    try:
        value = json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique)
    except (ValueError, RecursionError) as exc:
        raise VerificationError(f"invalid {label}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"invalid {label}")
    return value


def verify_receipt(path: Path, commit: str, run_id: str) -> dict:
    value = load_json(path.read_bytes(), path.name)
    if value.get("status") != "PASS" or str(value.get("source_commit", "")).lower() != commit or str(value.get("workflow_run_id")) != run_id:
        raise VerificationError(f"receipt identity mismatch: {path.name}")
    if value.get("production_mutation_by_ci") is not False or value.get("external_mutation", False) is not False:
        raise VerificationError(f"receipt mutation attestation failed: {path.name}")
    return value


def verify_public_research_payload(files: dict[str, tuple[str, bytes]]) -> None:
    expected = {
        'skills/serenity-public-research/skill.md',
        'skills/serenity-public-research/references/research_method.md',
        'skills/serenity-public-research/references/cross_validation.md',
    }
    if {p for p in files if p.startswith('skills/')} != expected:
        raise VerificationError('public research payload missing or unreviewed skill included')
    skill = files['skills/serenity-public-research/skill.md'][1].decode('utf-8-sig')
    for target in re.findall(r'\]\(([^)]+)\)', skill):
        if target.startswith('https://'):
            continue
        path = posixpath.normpath('skills/serenity-public-research/' + target).casefold()
        if path.startswith('../') or path not in files:
            raise VerificationError('packaged research reference is missing or unsafe')


def verify_worker_test_payload(files: dict[str, tuple[str, bytes]], refs: dict) -> None:
    """Activation must remain executable after extracting the delivered ZIP."""
    required = {
        "cloud/test/fake-kv.ts", "cloud/test/qa.test.ts",
        "cloud/test/v213-activation.test.ts", "cloud/test/v213-free-relay.test.ts",
        "cloud/test/v213-publication-mode.test.ts",
        "tests/fixtures/v213-r75-publication-mode/all-limited.json",
        "tests/fixtures/v213-r75-publication-mode/mixed.json",
    }
    inventory = refs.get("worker_test_payload")
    if not isinstance(inventory, list) or not all(isinstance(p, str) for p in inventory):
        raise VerificationError("activation test inventory missing")
    expected = {safe_name(p).casefold() for p in inventory}
    actual = {p for p in files if p.startswith(("cloud/test/", "tests/"))}
    if len(expected) != len(inventory) or expected != actual or not required.issubset(actual):
        raise VerificationError("activation test payload missing or inconsistent")
    if any(p.startswith("tests/") and p not in required for p in actual):
        raise VerificationError("non-runtime Python test content leaked")
    count = refs.get("packaged_worker_test_count")
    if type(count) is not int or count <= 0:
        raise VerificationError("packaged Worker test count invalid")


def verify_model_binding(files, refs, receipts, archive_sha):
    """Use trusted validators, never import code from the archive being checked."""
    key = 'config/v213-model-profile-v1.json'
    markers = {key, 'scripts/v213_model_profile.py', 'cloud/src/v213/model-profile.ts'}
    modern = bool(markers.intersection(files)) or any(r.get('model_profile_sha256') is not None for r in [refs, *receipts])
    if not modern:
        if refs.get('exact_model') != 'qwen38-q6':
            raise VerificationError('legacy model mismatch')
        return {'exact_model': 'qwen38-q6', 'model_profile_sha256': None}
    required = {key, 'scripts/v213_model_profile.py', 'scripts/v213_compact_qa_gateway.py',
                'scripts/v213_local_llm_gateway.py', 'cloud/src/v213/model-profile.ts'}
    if not required.issubset(files):
        raise VerificationError('profile runtime payload missing')
    try:
        profile = parse_profile(files[key][1].decode('utf-8-sig'))
    except (ValueError, UnicodeError):
        raise VerificationError('packaged model profile invalid') from None
    if profile['enable_thinking'] or profile['reasoning_effort'] != 'none':
        raise VerificationError('thinking capability unqualified')
    identity = {'exact_model': profile['model'], 'model_profile_sha256': profile_sha256(profile)}
    if any(r.get('artifact_kind') != 'R75_FREE_WORKERS_RELAY_HOTFIX' for r in receipts):
        raise VerificationError('profile receipt artifact kind mismatch')
    windows = [r for r in receipts if r.get('release_ready') is True and
               r.get('live_qa') == 'PASS' and r.get('live_free_relay_smoke') == 'PASS']
    deployment = [r for r in receipts if r.get('extracted_zip_worker_gate') == 'PASS']
    delivery = [r for r in receipts if r.get('zip_sha256') == archive_sha]
    if any(len(group) != 1 for group in (windows, deployment, delivery)) or len({id(windows[0]), id(deployment[0]), id(delivery[0])}) != 3:
        raise VerificationError('profile receipt roles missing or ambiguous')
    for record in (refs, windows[0], deployment[0]):
        if any(record.get(k) != v for k, v in identity.items()):
            raise VerificationError('model profile receipt binding mismatch')
    return identity


def verify_qa_binding(files, refs, receipts, qa_receipt):
    bound = ('scripts/r75_release_inputs.py' in files or 'qa_live_receipt_path' in refs
             or 'qa_live_receipt_sha256' in refs or any('qa_live_receipt_path' in r for r in receipts))
    if not bound:
        if qa_receipt is not None: raise VerificationError('legacy archive has no QA binding')
        return
    relative, digest = refs.get('qa_live_receipt_path'), refs.get('qa_live_receipt_sha256')
    if (not isinstance(relative, str) or not re.fullmatch(r'state/[A-Za-z0-9][A-Za-z0-9._-]{0,160}\.json', relative)
            or '..' in relative or not isinstance(digest, str) or not HEX64.fullmatch(digest)):
        raise VerificationError('QA reference binding missing or invalid')
    windows = [r for r in receipts if r.get('release_ready') is True]
    if (len(windows) != 1 or windows[0].get('qa_live_receipt_path') != relative
            or windows[0].get('qa_live_receipt_sha256') != digest):
        raise VerificationError('Windows/QA reference mismatch')
    if qa_receipt is None or not 0 < qa_receipt.stat().st_size <= 1048576:
        raise VerificationError('external QA receipt missing or oversized')
    raw = qa_receipt.read_bytes()
    if sha(raw) != digest: raise VerificationError('external QA receipt digest mismatch')
    data = load_json(raw, 'external QA receipt')
    manifest = {name: sha(body) for name, body in files.values() if name.startswith('cloud/src/')
                or fnmatch.fnmatchcase(name, 'scripts/v21*.py') or fnmatch.fnmatchcase(name, 'config/*.json')
                or name in ('cloud/test/r75-live-bench-worker.ts', 'cloud/test/r75-line-presentation-proof.ts', 'scripts/v213_edge_readiness.ps1')}
    try:
        from verify_r75_qa_evidence import verify as verify_live
        profile = parse_profile(files['config/v213-model-profile-v1.json'][1].decode('utf-8-sig')) if 'config/v213-model-profile-v1.json' in files else None
        qualified = verify_live(data, manifest, expected_profile=profile)
        if any(qualified.get(key) != refs.get(key) for key in ('exact_model', 'model_profile_sha256')):
            raise ValueError('QA model identity differs from archive')
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise VerificationError('external QA qualification failed') from None


def verify(archive: Path, checksum: Path, commit: str, run_id: str, receipts: list[Path], qa_receipt: Path | None = None) -> dict:
    commit = commit.lower()
    if not HEX40.fullmatch(commit) or not run_id.isdigit():
        raise VerificationError("invalid immutable identity")
    if len(receipts) != 3:
        raise VerificationError("exactly three external receipts are required")
    stem = f"Investor-Intelligence-v2.1.3-R75-Free-Relay-Hotfix-{commit}-{run_id}"
    if archive.name != stem + ".zip":
        raise VerificationError("archive name mismatch")
    parts = checksum.read_text(encoding="ascii").strip().split()
    if len(parts) != 2 or parts[1].lstrip("*") != archive.name or not HEX64.fullmatch(parts[0].lower()):
        raise VerificationError("external checksum malformed")
    actual = sha(archive.read_bytes())
    if actual != parts[0].lower():
        raise VerificationError("archive checksum mismatch")

    with zipfile.ZipFile(archive) as handle:
        if handle.testzip() is not None:
            raise VerificationError("ZIP CRC failure")
        files: dict[str, tuple[str, bytes]] = {}
        seen: set[str] = set()
        for info in handle.infolist():
            name = safe_name(info.filename); key = name.casefold()
            if key in seen:
                raise VerificationError("duplicate/case-colliding ZIP path")
            seen.add(key)
            if stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF):
                raise VerificationError("ZIP symlink")
            if not info.is_dir():
                files[key] = (name, handle.read(info))

    required = {
        "investorintelligence.exe", "hotfix-refs.json", "manifest.json", "sha256sums.txt",
        "scripts/v213_free_relay.ps1", "scripts/v213_free_relay_heartbeat.ps1", "scripts/v213_windows_security.ps1",
        "scripts/run_v213_local_llm_bridge_core.ps1", "register-v213-free-relay-task.ps1",
        "scripts/v213_sealed_refresh.ps1", "run-v213-scheduled-refresh.ps1", "register-v213-refresh-tasks.ps1",
        "cloud/src/v213/free-relay.ts", "cloud/src/v213/production-worker.ts",
        "cloud/wrangler.v213.production.template.toml", "run-v213-local.ps1",
        "config/v213-r75-publication-mode-v1.json", "scripts/v213_r75_activation_preflight.py",
        "cloud/src/v213/publication-mode.ts", "cloud/src/v213/activation-v2.ts",
    }
    if not required.issubset(files):
        raise VerificationError("required payload missing")
    if files["investorintelligence.exe"][1][:2] != b"MZ":
        raise VerificationError("launcher is not PE")
    if any(name.startswith((".github/", "delivery/", "state/")) for name in files):
        raise VerificationError("internal content leaked")
    verify_public_research_payload(files)

    refs = load_json(files["hotfix-refs.json"][1], "HOTFIX-REFS.json")
    if (refs.get("artifact_kind") != "R75_FREE_WORKERS_RELAY_HOTFIX" or
            refs.get("base_named_tunnel_commit") != BASE or refs.get("source_commit") != commit or
            str(refs.get("workflow_run_id")) != run_id or refs.get("production_mutation_by_ci") is not False or
            refs.get("protected_release_semantics_unchanged") is not True or refs.get("consecutive_public_health_required") != 3 or
            refs.get("health_schema_version") != 2 or
            refs.get("normal_production_tunnel_mode") != "quick_free_relay" or
            refs.get("workers_dev_stable_entrypoint") is not True or refs.get("custom_domain_required") is not False):
        raise VerificationError("hotfix refs mismatch")
    verify_worker_test_payload(files, refs)
    contract_sha = sha(files["config/v213-r75-publication-mode-v1.json"][1])
    if refs.get("publication_contract_sha256") != contract_sha:
        raise VerificationError("publication contract binding mismatch")

    manifest = load_json(files["manifest.json"][1], "MANIFEST.json")
    if (manifest.get("artifact_kind") != "R75_FREE_WORKERS_RELAY_HOTFIX" or manifest.get("source_commit") != commit or
            str(manifest.get("workflow_run_id")) != run_id or manifest.get("base_named_tunnel_commit") != BASE or
            manifest.get("production_mutation_by_ci") is not False):
        raise VerificationError("manifest identity mismatch")
    rows = manifest.get("files")
    if not isinstance(rows, list):
        raise VerificationError("manifest rows invalid")
    indexed = {str(row.get("path", "")).casefold(): row for row in rows if isinstance(row, dict)}
    expected = set(files) - {"manifest.json", "sha256sums.txt"}
    if set(indexed) != expected or len(indexed) != len(rows):
        raise VerificationError("manifest file set mismatch")
    for key, row in indexed.items():
        data = files[key][1]
        if row.get("bytes") != len(data) or row.get("sha256") != sha(data):
            raise VerificationError("manifest digest mismatch")

    sums: dict[str, str] = {}
    for line in files["sha256sums.txt"][1].decode("ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise VerificationError("SHA256SUMS malformed")
        key = safe_name(match.group(2)).casefold()
        if key in sums:
            raise VerificationError("SHA256SUMS duplicate")
        sums[key] = match.group(1)
    if set(sums) != set(files) - {"sha256sums.txt"}:
        raise VerificationError("SHA256SUMS file set mismatch")
    if any(sha(files[key][1]) != value for key, value in sums.items()):
        raise VerificationError("SHA256SUMS digest mismatch")

    verified = [verify_receipt(path, commit, run_id) for path in receipts]
    deployment = [r for r in verified if r.get("extracted_zip_worker_gate") == "PASS"]
    if (len(deployment) != 1 or deployment[0].get("packaged_worker_typecheck") != "PASS" or
            deployment[0].get("packaged_worker_tests") != refs["packaged_worker_test_count"] or
            deployment[0].get("extracted_zip_runtime_install") != "PASS"):
        raise VerificationError("extracted ZIP Worker gate receipt missing or inconsistent")
    model_binding = verify_model_binding(files, refs, verified, actual)
    verify_qa_binding(files, refs, verified, qa_receipt)
    return {
        **model_binding,
        "status": "PASS", "artifact_kind": "R75_FREE_WORKERS_RELAY_HOTFIX",
        "archive": archive.name, "archive_sha256": actual, "source_commit": commit,
        "workflow_run_id": run_id, "base_named_tunnel_commit": BASE, "zip_crc": "PASS",
        "path_safety": "PASS", "duplicates": "PASS", "symlinks": "PASS",
        "manifest": "PASS", "sha256sums": "PASS", "pe_marker": "PASS",
        "publication_contract_sha256": contract_sha, "receipt_count": len(verified),
        "activation_test_payload": "PASS", "public_research_payload": "PASS", "extracted_zip_worker_gate": "PASS",
        "extracted_zip_runtime_install": "PASS",
        "packaged_worker_tests": refs["packaged_worker_test_count"],
        "qa_live_receipt_path": refs.get('qa_live_receipt_path'),
        "qa_live_receipt_sha256": refs.get('qa_live_receipt_sha256'),
        "production_mutation_by_ci": False, "protected_release_semantics_unchanged": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--checksum", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--receipt", action="append", default=[], type=Path)
    parser.add_argument("--qa-live-receipt", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.archive, args.checksum, args.source_commit, args.workflow_run_id, args.receipt, args.qa_live_receipt)
    except (OSError, UnicodeError, zipfile.BadZipFile, VerificationError) as exc:
        print(f"V213_R75_FREE_RELAY_ARTIFACT_VERIFICATION = FAIL; reason={type(exc).__name__}")
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print("V213_R75_FREE_RELAY_ARTIFACT_VERIFICATION = PASS; production_mutation_by_ci=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
