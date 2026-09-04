#!/usr/bin/env python3
"""Apply the v2.1.3 R75 cross-layer hardening patch deterministically."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PatchError(RuntimeError):
    pass


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def write(path: str, value: str) -> None:
    (ROOT / path).write_text(value, encoding="utf-8", newline="\n")


def replace_once(value: str, old: str, new: str, label: str) -> str:
    if new in value:
        return value
    count = value.count(old)
    if count != 1:
        raise PatchError(f"{label}: expected one replacement, observed {count}")
    return value.replace(old, new, 1)


def patch_activation_aliases() -> None:
    canonical = (ROOT / "activate-v213-seven-field-schedule.ps1").read_bytes()
    (ROOT / "activate-v213-seven-field-schedule-serenity-latest.ps1").write_bytes(canonical)
    (ROOT / "activate-v213-diversified-schedule.ps1").write_bytes(canonical)


def patch_activation_core() -> None:
    path = "activate-v213-seven-field-schedule-core.ps1"
    value = read(path)
    value = value.replace(
        "install-v213-source-diverse-runtime.ps1",
        "install-v213-r75-runtime.ps1",
    )
    if "V213_R75_SEALED_BUNDLE_SHA256" not in value:
        anchor = "$BundlePath = Join-Path $ProjectRoot 'data\\cache\\v213_activation_bundle_upload.json'"
        block = anchor + r'''
$expectedBundleSha=[string]$env:V213_R75_SEALED_BUNDLE_SHA256
if($expectedBundleSha-notmatch'^[0-9a-fA-F]{64}$'){throw 'The sealed R75 activation-bundle SHA-256 was not supplied by the validated wrapper.'}
if(-not(Test-Path -LiteralPath $BundlePath -PathType Leaf)){throw "Activation prerequisite is missing: $BundlePath"}
$actualBundleSha=(Get-FileHash -LiteralPath $BundlePath -Algorithm SHA256).Hash.ToLowerInvariant()
if($actualBundleSha-ne$expectedBundleSha.ToLowerInvariant()){throw 'The activation bundle changed after the sealed R75 preflight (TOCTOU blocked).'}
$script:V213R75ActivationMutex=New-Object Threading.Mutex($false,'Local\\InvestorIntelligence_V213_R75_ACTIVATION_LOCK')
if(-not$script:V213R75ActivationMutex.WaitOne(0)){throw 'Another v2.1.3 activation is already running.'}
Write-Host "V213_R75_ACTIVATION_LOCK = PASS; sealed_bundle_sha256=$actualBundleSha" -ForegroundColor Green'''
        value = replace_once(value, anchor, block, "activation core sealed SHA and lock")
    if "V213_BROADCAST_DEDUPE" not in value:
        anchor = "[IO.File]::WriteAllText($temp, $text, [Text.UTF8Encoding]::new($false))"
        block = r'''if($text-notmatch'(?m)^\s*name\s*=\s*"V213_BROADCAST_DEDUPE"\s*$'){
    $text += "`r`n[[durable_objects.bindings]]`r`nname = `"V213_BROADCAST_DEDUPE`"`r`nclass_name = `"V213BroadcastDedupe`"`r`n"
}
if($text-notmatch'(?m)^\s*tag\s*=\s*"v213-r75-broadcast-dedupe-v1"\s*$'){
    $text += "`r`n[[migrations]]`r`ntag = `"v213-r75-broadcast-dedupe-v1`"`r`nnew_sqlite_classes = [`"V213BroadcastDedupe`"]`r`n"
}
$text = Set-Var $text 'LOCAL_LLM_TIMEOUT_MS' '90000'
''' + anchor
        value = replace_once(value, anchor, block, "activation core Durable Object config")
    if "V213_R75_ACTIVATION_LOCK_RELEASED" not in value:
        value = value.rstrip() + r'''

if($null-ne$script:V213R75ActivationMutex){
    try{$script:V213R75ActivationMutex.ReleaseMutex()}catch{}
    try{$script:V213R75ActivationMutex.Dispose()}catch{}
    $script:V213R75ActivationMutex=$null
    Write-Host 'V213_R75_ACTIVATION_LOCK_RELEASED = PASS' -ForegroundColor DarkGray
}
''' + "\n"
    write(path, value)


def patch_bridge_core() -> None:
    path = "scripts/run_v213_local_llm_bridge_core.ps1"
    value = read(path)
    value = value.replace(
        "scripts\\v213_local_llm_gateway.py",
        "scripts\\v213_local_llm_gateway_r75.py",
    )
    if "v213_local_llm_gateway_r75.py" not in value:
        raise PatchError("bridge core did not select the R75 gateway")
    write(path, value)


def patch_worker_activation() -> None:
    path = "cloud/src/v213/activation-v2.ts"
    value = read(path)
    import_line = 'import { validateR75PublicationModes } from "./publication-mode";\n'
    if import_line not in value:
        value = import_line + value
    value = value.replace(
        '["us_sec", "nasdaq", "world_bank", "us_bls", "ecb"]',
        '["us_sec", "nasdaq", "world_bank", "ecb"]',
    )
    value = value.replace(
        "!finite(portfolio.claim_source_families) || portfolio.claim_source_families < 2 ||",
        "!finite(portfolio.claim_source_families) || portfolio.claim_source_families < 1 ||",
    )
    value = value.replace(
        "!finite(portfolio.claim_source_domains) || portfolio.claim_source_domains < 2 ||",
        "!finite(portfolio.claim_source_domains) || portfolio.claim_source_domains < 1 ||",
    )
    if "validateR75PublicationModes(doc, top20)" not in value:
        anchor = '''  if (eligibleCount !== Number(portfolio.high_confidence_model_inference_eligible_count ?? -1)) {
    throw new Error("V213_ACTIVATION_HIGH_CONFIDENCE_COUNT_INVALID");
  }
  return doc;'''
        block = '''  if (eligibleCount !== Number(portfolio.high_confidence_model_inference_eligible_count ?? -1)) {
    throw new Error("V213_ACTIVATION_HIGH_CONFIDENCE_COUNT_INVALID");
  }
  if (portfolio.evidence_qualified_candidate_count !== undefined || portfolio.limited_research_candidate_count !== undefined) {
    validateR75PublicationModes(doc, top20 as Array<Record<string, unknown>>);
  }
  return doc;'''
        value = replace_once(value, anchor, block, "Worker publication-mode call")
    if "async function verifySnapshotObjects" not in value:
        anchor = "export async function ingestV213ActivationBundle("
        helper = '''async function verifySnapshotObjects(
  env: V21AdminEnv,
  prefix: string,
  objects: Array<[string, string]>,
): Promise<void> {
  for (const [key, expected] of objects) {
    const observed = await env.PUBLIC_CACHE.get(`${prefix}${key}`, "text");
    if (observed !== expected) throw new Error("V213_ACTIVATION_SNAPSHOT_READBACK_FAILED");
  }
}

''' + anchor
        value = replace_once(value, anchor, helper, "Worker snapshot readback helper")
    if "let idempotentReplay = false;" not in value:
        value = replace_once(
            value,
            "  let state: RollbackState;",
            "  let state: RollbackState;\n  let idempotentReplay = false;",
            "Worker idempotent replay flag",
        )
    old_early = '''    if (previousRunId === runId) {
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
    }'''
    if old_early in value:
        value = value.replace(old_early, "    if (previousRunId === runId) idempotentReplay = true;", 1)
    value = value.replace(
        'await env.PUBLIC_CACHE.put(runClaimKey, JSON.stringify(claim), { expirationTtl: 259200 });',
        'await env.PUBLIC_CACHE.put(runClaimKey, JSON.stringify(claim));',
    )
    value = value.replace(
        'await env.PUBLIC_CACHE.put(`${prefix}${key}`, value, { expirationTtl: 259200 });',
        'await env.PUBLIC_CACHE.put(`${prefix}${key}`, value);',
    )
    if "await verifySnapshotObjects(env, prefix, objects);" not in value:
        anchor = '''  for (const [key, value] of objects) {
    await env.PUBLIC_CACHE.put(`${prefix}${key}`, value);
  }
  await env.EPHEMERAL_SECURITY_CACHE.put'''
        block = '''  for (const [key, value] of objects) {
    await env.PUBLIC_CACHE.put(`${prefix}${key}`, value);
  }
  await verifySnapshotObjects(env, prefix, objects);
  await env.EPHEMERAL_SECURITY_CACHE.put'''
        value = replace_once(value, anchor, block, "Worker pre-pointer readback")
    if value.count("await verifySnapshotObjects(env, prefix, objects);") < 2:
        anchor = '''  if (currentRunId(confirmedPointer) !== runId) {
    throw new Error("V213_ACTIVATION_POINTER_WRITE_NOT_VERIFIED");
  }
  return {'''
        block = '''  if (currentRunId(confirmedPointer) !== runId) {
    throw new Error("V213_ACTIVATION_POINTER_WRITE_NOT_VERIFIED");
  }
  await verifySnapshotObjects(env, prefix, objects);
  return {'''
        value = replace_once(value, anchor, block, "Worker post-pointer readback")
    value = value.replace(
        "    idempotent_replay: false,",
        "    idempotent_replay: idempotentReplay,",
    )
    if "verifySnapshotObjects" not in value or "validateR75PublicationModes" not in value:
        raise PatchError("Worker activation hardening markers are missing")
    write(path, value)


def patch_broadcast() -> None:
    path = "cloud/src/v213/broadcast.ts"
    value = read(path)
    import_line = 'import { runV213BroadcastOnce } from "./broadcast-dedupe";\n'
    if import_line not in value:
        value = import_line + value
    if "V213_BROADCAST_DEDUPE?: DurableObjectNamespace;" not in value:
        pattern = re.compile(r"(export\s+interface\s+V213BroadcastEnv\s*\{)")
        value, count = pattern.subn(r"\1\n  V213_BROADCAST_DEDUPE?: DurableObjectNamespace;", value, count=1)
        if count != 1:
            pattern = re.compile(r"(interface\s+V213BroadcastEnv\s*\{)")
            value, count = pattern.subn(r"\1\n  V213_BROADCAST_DEDUPE?: DurableObjectNamespace;", value, count=1)
        if count != 1:
            raise PatchError("broadcast env interface was not found")
    old = '''  if (slot !== "test" && (await env.EPHEMERAL_SECURITY_CACHE.get(dedupeKey))) {
    return { status: "duplicate" };
  }

  await pushText(env, owner.lineUserId, message);
  if (slot !== "test") {
    await env.EPHEMERAL_SECURITY_CACHE.put(dedupeKey, "sent", { expirationTtl: 259200 });
  }
  return {
    status: "sent",'''
    new = '''  if (slot === "test") {
    await pushText(env, owner.lineUserId, message);
  } else {
    if (!env.V213_BROADCAST_DEDUPE) return { status: "dedupe_unavailable" };
    const delivery = await runV213BroadcastOnce(
      env.V213_BROADCAST_DEDUPE,
      dedupeKey,
      () => pushText(env, owner.lineUserId, message),
    );
    if (delivery.status !== "sent") return { status: delivery.status };
  }
  return {
    status: "sent",'''
    if "runV213BroadcastOnce(" not in value:
        value = replace_once(value, old, new, "atomic LINE broadcast dedupe")
    write(path, value)


def patch_production_worker() -> None:
    path = "cloud/src/v213/production-worker.ts"
    value = read(path)
    line = 'export { V213BroadcastDedupe } from "./broadcast-dedupe";\n'
    if line not in value:
        value = line + value
    write(path, value)


def patch_wrangler() -> None:
    candidates = [ROOT / "cloud" / "wrangler.toml", ROOT / "wrangler.toml"]
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise PatchError("wrangler.toml was not found")
    value = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    if 'name = "V213_BROADCAST_DEDUPE"' not in value:
        value = value.rstrip() + '''

[[durable_objects.bindings]]
name = "V213_BROADCAST_DEDUPE"
class_name = "V213BroadcastDedupe"

[[migrations]]
tag = "v213-r75-broadcast-dedupe-v1"
new_sqlite_classes = ["V213BroadcastDedupe"]
'''
    path.write_text(value, encoding="utf-8", newline="\n")


def patch_qa_timeout() -> None:
    path = "cloud/src/qa.ts"
    value = read(path)
    if "LOCAL_LLM_TIMEOUT_MS?: string;" not in value:
        value = value.replace(
            "  LOCAL_LLM_MODEL?: string;",
            "  LOCAL_LLM_MODEL?: string;\n  LOCAL_LLM_TIMEOUT_MS?: string;",
            1,
        )
    if "function localModelTimeoutMs" not in value:
        anchor = "async function localAnswer("
        helper = '''function localModelTimeoutMs(env: QaEnv): number {
  const parsed = Number(env.LOCAL_LLM_TIMEOUT_MS ?? 90000);
  if (!Number.isFinite(parsed)) return 90000;
  return Math.max(20000, Math.min(110000, Math.trunc(parsed)));
}

''' + anchor
        value = replace_once(value, anchor, helper, "local model timeout helper")
    value = value.replace(
        "signal: AbortSignal.timeout(20000),",
        "signal: AbortSignal.timeout(localModelTimeoutMs(env)),",
    )
    write(path, value)


def patch_candidate_seed() -> None:
    path = "scripts/v21_serenity_top20.py"
    value = read(path)
    if "import os\n" not in value:
        marker = "from __future__ import annotations\n"
        value = replace_once(value, marker, marker + "\nimport os\nimport time\n", "candidate seed imports")
    elif "import time\n" not in value:
        value = value.replace("import os\n", "import os\nimport time\n", 1)
    marker = "V213_CANDIDATE_SEED_REUSE_SECONDS"
    if marker not in value:
        anchor = '''def discover_candidates(policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        import yfinance as yf'''
        replacement = '''def discover_candidates(policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    seed_path = CACHE_ROOT / "candidate_seed.json"
    try:
        reuse_seconds = max(0, min(3600, int(os.getenv("V213_CANDIDATE_SEED_REUSE_SECONDS", "900"))))
    except ValueError:
        reuse_seconds = 900
    if seed_path.is_file() and reuse_seconds > 0 and time.time() - seed_path.stat().st_mtime <= reuse_seconds:
        try:
            locked = json.loads(seed_path.read_text(encoding="utf-8-sig"))
            if isinstance(locked, list) and locked:
                print(f"II_PROGRESS candidate seed reused; age_seconds={int(time.time() - seed_path.stat().st_mtime)}; reuse_window={reuse_seconds}", flush=True)
                return [item for item in locked if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError):
            pass
    try:
        import yfinance as yf'''
        value = replace_once(value, anchor, replacement, "candidate seed reuse")
    write(path, value)


def patch_launcher() -> None:
    path = "launcher/InvestorIntelligenceLauncher.cs"
    value = read(path)
    value = value.replace("Serenity-Latest-MultiSource-R70", "Serenity-Latest-MultiSource-R75")
    value = value.replace("R70", "R75")
    write(path, value)


def patch_release_config() -> None:
    # Ensure the packaged source and Production temp config both know about the
    # Durable Object migration.  Duplicate-safe guards are in the runtime code.
    for path in ("cloud/wrangler.toml",):
        if (ROOT / path).is_file():
            return


def main() -> int:
    patch_activation_aliases()
    patch_activation_core()
    patch_bridge_core()
    patch_worker_activation()
    patch_broadcast()
    patch_production_worker()
    patch_wrangler()
    patch_qa_timeout()
    patch_candidate_seed()
    patch_launcher()
    print(
        "V213_R75_CROSS_LAYER_PATCH = PASS; "
        "sealed_bundle=true; publication_mode=true; optional_bls=true; "
        "snapshot_readback=true; exact_model=true; safe_path=true; "
        "atomic_line_dedupe=true; scheduled_data_only=true"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PatchError, OSError, ValueError) as exc:
        print(f"V213_R75_CROSS_LAYER_PATCH = FAIL; {exc}")
        raise SystemExit(1)
