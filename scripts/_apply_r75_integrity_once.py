#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def write(path: str, value: str) -> None:
    (ROOT / path).write_text(value, encoding="utf-8", newline="\n")


def replace_once(value: str, old: str, new: str, label: str) -> str:
    if new in value:
        return value
    count = value.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, observed {count}")
    return value.replace(old, new, 1)


def main() -> int:
    required = {
        "activate-v213-seven-field-schedule.ps1": (
            "V213_ACTIVATION_PREFLIGHT_ONLY",
            "LIMITED_RESEARCH_CANDIDATE",
            "v213_activation_bundle_upload.json",
        ),
        "cloud/src/v213/activation-v2.ts": (
            "V213_ACTIVATION_LIMITED_CANDIDATE_INVALID",
            "LIMITED_RESEARCH_CANDIDATE",
        ),
        "scripts/v212_local_llm_gateway.py": (
            "MODEL_PIN_MISMATCH",
            "resolve_pinned_model",
        ),
        "scripts/run_v213_local_llm_bridge_core.ps1": (
            "New-GatewayArgumentLine",
            "V213_BRIDGE_SPACED_PATH_PROCESS_SELF_TEST",
        ),
        "scripts/ci_v213_r75_validate.ps1": (
            "V213_R75_ACTUAL_ACTIVATION_PREFLIGHT",
        ),
        "scripts/ci_v213_r75_package.ps1": ("R75",),
    }
    for path, markers in required.items():
        value = read(path)
        missing = [marker for marker in markers if marker not in value]
        if missing:
            raise RuntimeError(f"P0 hardening prerequisite missing in {path}: {missing}")

    worker_path = "cloud/src/v213/activation-v2.ts"
    worker = read(worker_path)
    helper = r'''

async function verifySnapshotObjects(
  env: V21AdminEnv,
  prefix: string,
  objects: Array<[string, string]>,
): Promise<void> {
  for (const [key, expected] of objects) {
    const observed = await env.PUBLIC_CACHE.get(`${prefix}${key}`, "text");
    if (observed !== expected) {
      throw new Error(`V213_ACTIVATION_SNAPSHOT_READBACK_FAILED_${key.toUpperCase().replace(/[^A-Z0-9]+/g, "_")}`);
    }
  }
}
'''
    if "async function verifySnapshotObjects" not in worker:
        worker = replace_once(
            worker,
            "\nexport async function ingestV213ActivationBundle(",
            helper + "\nexport async function ingestV213ActivationBundle(",
            "Worker snapshot readback helper",
        )
    if "const idempotentReplay = previousRunId === runId;" not in worker:
        worker = replace_once(
            worker,
            "  const previousRunId = currentRunId(previousPointer);\n  const rollbackStateKey = rollbackKey(transactionId);",
            "  const previousRunId = currentRunId(previousPointer);\n  const idempotentReplay = previousRunId === runId;\n  const rollbackStateKey = rollbackKey(transactionId);",
            "Worker idempotent replay flag",
        )
    early = r'''    if (previousRunId === runId) {
      return {
        status: "accepted",
        product_version: "2.1.3",
        transaction_id: transactionId,
        run_id: runId,
        previous_run_id: state.previous_run_id,
        object_count: 0,
        pointer_written_last: true,
        rollback_available: true,
        idempotent_replay: true,
      };
    }
'''
    worker = worker.replace(early, "", 1)
    if "await verifySnapshotObjects(env, prefix, objects);" not in worker:
        worker = replace_once(
            worker,
            "    await env.PUBLIC_CACHE.put(`${prefix}${key}`, value, { expirationTtl: 259200 });\n  }\n  await env.EPHEMERAL_SECURITY_CACHE.put(rollbackStateKey, JSON.stringify(state), { expirationTtl: 1800 });",
            "    await env.PUBLIC_CACHE.put(`${prefix}${key}`, value, { expirationTtl: 604800 });\n  }\n  await verifySnapshotObjects(env, prefix, objects);\n  await env.EPHEMERAL_SECURITY_CACHE.put(rollbackStateKey, JSON.stringify(state), { expirationTtl: 1800 });",
            "Worker immutable object readback",
        )
    if "}), { expirationTtl: 259200 });" not in worker:
        worker = replace_once(
            worker,
            "  await env.PUBLIC_CACHE.put(\"snapshot:current\", JSON.stringify({\n    schema_version: 1,\n    run_id: runId,\n    public_data_as_of: root.public_data_as_of,\n    promoted_at: new Date().toISOString(),\n    provider_scope: \"public_only\",\n    owner_watchlist_inherited: false,\n  }));",
            "  await env.PUBLIC_CACHE.put(\"snapshot:current\", JSON.stringify({\n    schema_version: 1,\n    run_id: runId,\n    public_data_as_of: root.public_data_as_of,\n    promoted_at: new Date().toISOString(),\n    provider_scope: \"public_only\",\n    owner_watchlist_inherited: false,\n  }), { expirationTtl: 259200 });",
            "Worker pointer TTL",
        )
    if "snapshot_readback_verified: true" not in worker:
        worker = replace_once(
            worker,
            "    idempotent_replay: false,\n  };",
            "    idempotent_replay: idempotentReplay,\n    snapshot_readback_verified: true,\n  };",
            "Worker integrity receipt",
        )
    write(worker_path, worker)

    test_path = "cloud/test/v213-activation.test.ts"
    tests = read(test_path)
    replay = r'''

describe("v2.1.3 R75 snapshot integrity", () => {
  it("repairs and verifies a missing immutable object on idempotent replay", async () => {
    const rt = runtime();
    const value = await bundle();
    const first = await ingestV213ActivationBundle(JSON.stringify(value), rt.env);
    expect(first.status).toBe("accepted");
    await rt.env.PUBLIC_CACHE.delete(`snapshot:${RUN_ID}:v21:top20:latest`);
    const replay = await ingestV213ActivationBundle(JSON.stringify(value), rt.env);
    expect(replay.idempotent_replay).toBe(true);
    expect(replay.snapshot_readback_verified).toBe(true);
    expect(await rt.env.PUBLIC_CACHE.get(`snapshot:${RUN_ID}:v21:top20:latest`, "text")).not.toBeNull();
  });
});
'''
    if 'describe("v2.1.3 R75 snapshot integrity"' not in tests:
        tests += replay
    write(test_path, tests)

    candidate_path = "scripts/v21_serenity_top20.py"
    candidate = read(candidate_path)
    if "import time\n" not in candidate:
        if "import sys\n" in candidate:
            candidate = candidate.replace("import sys\n", "import sys\nimport time\n", 1)
        else:
            candidate = candidate.replace("from pathlib import Path\n", "import time\nfrom pathlib import Path\n", 1)
    stability = r'''    seed_path = CACHE_ROOT / "candidate_seed.json"
    stability_minutes = max(1, int(policy.get("candidate_seed_stability_minutes", 30)))
    if seed_path.is_file() and time.time() - seed_path.stat().st_mtime <= stability_minutes * 60:
        try:
            stable = json.loads(seed_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            stable = None
        if isinstance(stable, list) and stable and all(isinstance(item, dict) for item in stable):
            print(
                f"II_PROGRESS candidate seed reused; stability_minutes={stability_minutes}; candidates={len(stable)}",
                flush=True,
            )
            return stable

'''
    if "candidate seed reused; stability_minutes=" not in candidate:
        candidate = replace_once(
            candidate,
            "def discover_candidates(policy: Mapping[str, Any]) -> list[dict[str, Any]]:\n",
            "def discover_candidates(policy: Mapping[str, Any]) -> list[dict[str, Any]]:\n" + stability,
            "Candidate seed stability",
        )
    write(candidate_path, candidate)

    bridge_path = "scripts/run_v213_local_llm_bridge_core.ps1"
    bridge = read(bridge_path)
    if "$consecutive = 0" not in bridge:
        bridge = replace_once(
            bridge,
            "    $deadline = (Get-Date).AddSeconds($Seconds)\n    $last = ''\n    $hostName = ([uri]$Url).Host",
            "    $deadline = (Get-Date).AddSeconds($Seconds)\n    $last = ''\n    $consecutive = 0\n    $hostName = ([uri]$Url).Host",
            "Tunnel consecutive state",
        )
    if "$consecutive -ge 3" not in bridge:
        bridge = replace_once(
            bridge,
            "            if (Test-HealthModel $health $SelectedModel) { return $health }\n            $last =",
            "            if (Test-HealthModel $health $SelectedModel) {\n                $consecutive++\n                if ($consecutive -ge 3) { return $health }\n                Start-Sleep -Seconds 1\n                continue\n            }\n            $consecutive = 0\n            $last =",
            "Tunnel direct health quorum",
        )
        bridge = replace_once(
            bridge,
            "                            if (Test-HealthModel $curlHealth $SelectedModel) { return $curlHealth }",
            "                            if (Test-HealthModel $curlHealth $SelectedModel) {\n                                $consecutive++\n                                if ($consecutive -ge 3) { return $curlHealth }\n                                Start-Sleep -Seconds 1\n                                continue\n                            }\n                            $consecutive = 0",
            "Tunnel DNS fallback quorum",
        )
    if "public_health_consecutive_successes" not in bridge:
        bridge = replace_once(
            bridge,
            "        connected_at = (Get-Date).ToUniversalTime().ToString('o')\n        shared_secret_plaintext_persisted = $false",
            "        connected_at = (Get-Date).ToUniversalTime().ToString('o')\n        tunnel_mode = $(if ($publicUrl) { 'quick_accountless' } else { 'none' })\n        public_health_consecutive_successes = $(if ($publicUrl) { 3 } else { 0 })\n        shared_secret_plaintext_persisted = $false",
            "Tunnel state attestation",
        )
    write(bridge_path, bridge)

    validate_path = "scripts/ci_v213_r75_validate.ps1"
    validate = read(validate_path)
    integrity_check = r'''
    $candidateSource = Get-Content -LiteralPath 'scripts\v21_serenity_top20.py' -Raw -Encoding utf8
    if (-not $candidateSource.Contains('candidate seed reused; stability_minutes=')) { throw 'Candidate seed stability guard is missing.' }
    $workerSource = Get-Content -LiteralPath 'cloud\src\v213\activation-v2.ts' -Raw -Encoding utf8
    foreach ($marker in @('verifySnapshotObjects','snapshot_readback_verified','expirationTtl: 604800')) {
        if (-not $workerSource.Contains($marker)) { throw "Worker snapshot integrity marker is missing: $marker" }
    }
    Write-Host 'V213_R75_INTEGRITY_SOURCE_CONTRACT = PASS; snapshot_readback=true; pointer_expires_before_objects=true; candidate_seed_stability=true'
'''
    if "V213_R75_INTEGRITY_SOURCE_CONTRACT" not in validate:
        validate = replace_once(
            validate,
            "    & $env:PROJECT_PYTHON -m compileall -q scripts tests\n",
            integrity_check + "\n    & $env:PROJECT_PYTHON -m compileall -q scripts tests\n",
            "R75 integrity validation",
        )
    write(validate_path, validate)

    release_path = ".github/workflows/v213-r75-hardening-release.yml"
    release = read(release_path)
    desktop = r'''

      - name: Copy verified R75 delivery to Desktop
        shell: pwsh
        working-directory: ${{ env.SOURCE_DIR }}
        run: |
          $ErrorActionPreference = 'Stop'
          $desktop = [Environment]::GetFolderPath('Desktop')
          if ([string]::IsNullOrWhiteSpace($desktop)) { $desktop = Join-Path $env:USERPROFILE 'Desktop' }
          New-Item -ItemType Directory -Force -Path $desktop | Out-Null
          foreach ($path in @($env:R75_ZIP,$env:R75_SHA_FILE,$env:R75_VERIFICATION,$env:R75_RECEIPT,$env:R75_VALIDATION)) {
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "R75 delivery file is missing: $path" }
            Copy-Item -LiteralPath $path -Destination $desktop -Force
          }
          Write-Host "V213_R75_DESKTOP_DELIVERY = PASS; desktop=$desktop; production_mutation=false"
'''
    if "V213_R75_DESKTOP_DELIVERY = PASS" not in release:
        release = replace_once(
            release,
            "\n      - name: Upload R75 Actions artifact",
            desktop + "\n      - name: Upload R75 Actions artifact",
            "R75 Desktop delivery",
        )
    write(release_path, release)

    audit_path = "scripts/v213_serenity_latest_static_audit.py"
    audit = read(audit_path)
    block = r'''    # R75_SNAPSHOT_CANDIDATE_TUNNEL_INTEGRITY_V1
    require("cloud/src/v213/activation-v2.ts",("verifySnapshotObjects","snapshot_readback_verified","expirationTtl: 604800"),failures)
    require("scripts/v21_serenity_top20.py",("candidate seed reused; stability_minutes=","candidate_seed_stability_minutes"),failures)
    require("scripts/run_v213_local_llm_bridge_core.ps1",("public_health_consecutive_successes","quick_accountless","$consecutive -ge 3"),failures)
'''
    if "R75_SNAPSHOT_CANDIDATE_TUNNEL_INTEGRITY_V1" not in audit:
        index = audit.rfind("\n    if failures:\n")
        if index < 0:
            raise RuntimeError("Static audit failure anchor missing")
        audit = audit[:index] + "\n" + block + audit[index:]
    write(audit_path, audit)

    print("R75_INTEGRITY_PATCH = PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
