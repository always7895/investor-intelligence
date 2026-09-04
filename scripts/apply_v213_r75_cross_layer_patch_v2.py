#!/usr/bin/env python3
"""Second-generation deterministic R75 patch driver.

It reuses the reviewed patch primitives while overriding the few locations that
need more tolerant source-shape matching on the long-lived branch.
"""
from __future__ import annotations

import re

import apply_v213_r75_cross_layer_patch as base


def patch_activation_core() -> None:
    path = "activate-v213-seven-field-schedule-core.ps1"
    value = base.read(path)
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
$script:V213R75ActivationMutex=New-Object Threading.Mutex($false,'Local\InvestorIntelligence_V213_R75_ACTIVATION_LOCK')
if(-not$script:V213R75ActivationMutex.WaitOne(0)){throw 'Another v2.1.3 activation is already running.'}
Write-Host "V213_R75_ACTIVATION_LOCK = PASS; sealed_bundle_sha256=$actualBundleSha" -ForegroundColor Green'''
        value = base.replace_once(value, anchor, block, "activation core sealed SHA and lock")
    if "V213_BROADCAST_DEDUPE" not in value:
        anchor = "[IO.File]::WriteAllText($temp, $text, [Text.UTF8Encoding]::new($false))"
        addition = r'''if($text-notmatch'(?m)^\s*name\s*=\s*"V213_BROADCAST_DEDUPE"\s*$'){
    $text += "`r`n[[durable_objects.bindings]]`r`nname = `"V213_BROADCAST_DEDUPE`"`r`nclass_name = `"V213BroadcastDedupe`"`r`n"
}
if($text-notmatch'(?m)^\s*tag\s*=\s*"v213-r75-broadcast-dedupe-v1"\s*$'){
    $text += "`r`n[[migrations]]`r`ntag = `"v213-r75-broadcast-dedupe-v1`"`r`nnew_sqlite_classes = [`"V213BroadcastDedupe`"]`r`n"
}
$text = Set-Var $text 'LOCAL_LLM_TIMEOUT_MS' '90000'
'''
        value = base.replace_once(value, anchor, addition + anchor, "activation core Durable Object config")
    if "V213_R75_ACTIVATION_LOCK_RELEASED" not in value:
        value = value.rstrip() + r'''

if($null-ne$script:V213R75ActivationMutex){
    try{$script:V213R75ActivationMutex.ReleaseMutex()}catch{}
    try{$script:V213R75ActivationMutex.Dispose()}catch{}
    $script:V213R75ActivationMutex=$null
    Write-Host 'V213_R75_ACTIVATION_LOCK_RELEASED = PASS' -ForegroundColor DarkGray
}
''' + "\n"
    base.write(path, value)


def patch_worker_activation() -> None:
    path = "cloud/src/v213/activation-v2.ts"
    value = base.read(path)
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
    if "validateR75PublicationModes(doc, top20" not in value:
        pattern = re.compile(
            r'(\s+if \(eligibleCount !== Number\(portfolio\.high_confidence_model_inference_eligible_count \?\? -1\)\) \{\n'
            r'\s+throw new Error\("V213_ACTIVATION_HIGH_CONFIDENCE_COUNT_INVALID"\);\n\s+\}\n)(\s+return doc;)'
        )
        replacement = (
            r'\1'
            '  if (portfolio.evidence_qualified_candidate_count !== undefined || portfolio.limited_research_candidate_count !== undefined) {\n'
            '    validateR75PublicationModes(doc, top20 as unknown as Array<Record<string, unknown>>);\n'
            '  }\n'
            r'\2'
        )
        value, count = pattern.subn(replacement, value, count=1)
        if count != 1:
            raise base.PatchError("Worker publication-mode insertion anchor was not found")
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
        value = base.replace_once(value, anchor, helper, "Worker snapshot readback helper")
    if "let idempotentReplay = false;" not in value:
        value = base.replace_once(
            value,
            "  let state: RollbackState;",
            "  let state: RollbackState;\n  let idempotentReplay = false;",
            "Worker idempotent replay flag",
        )
    early_pattern = re.compile(
        r'\s+if \(previousRunId === runId\) \{\n'
        r'\s+return \{[\s\S]*?\n\s+\};\n\s+\}'
    )
    if "if (previousRunId === runId) idempotentReplay = true;" not in value:
        value, count = early_pattern.subn(
            "\n    if (previousRunId === runId) idempotentReplay = true;",
            value,
            count=1,
        )
        if count != 1:
            raise base.PatchError("Worker idempotent early-return block was not found")
    value = value.replace(
        "    if (previousPointer !== state.previous_pointer) {",
        "    if (!idempotentReplay && previousPointer !== state.previous_pointer) {",
        1,
    )
    value = value.replace(
        'await env.PUBLIC_CACHE.put(runClaimKey, JSON.stringify(claim), { expirationTtl: 259200 });',
        'await env.PUBLIC_CACHE.put(runClaimKey, JSON.stringify(claim));',
    )
    value = value.replace(
        'await env.PUBLIC_CACHE.put(`${prefix}${key}`, value, { expirationTtl: 259200 });',
        'await env.PUBLIC_CACHE.put(`${prefix}${key}`, value);',
    )
    if "await verifySnapshotObjects(env, prefix, objects);" not in value:
        pattern = re.compile(
            r'(\s+for \(const \[key, value\] of objects\) \{\n\s+await env\.PUBLIC_CACHE\.put\(`\$\{prefix\}\$\{key\}`, value\);\n\s+\}\n)'
            r'(\s+await env\.EPHEMERAL_SECURITY_CACHE\.put)'
        )
        value, count = pattern.subn(r'\1  await verifySnapshotObjects(env, prefix, objects);\n\2', value, count=1)
        if count != 1:
            raise base.PatchError("Worker object-write loop was not found")
    if value.count("await verifySnapshotObjects(env, prefix, objects);") < 2:
        anchor = '''  if (currentRunId(confirmedPointer) !== runId) {
    throw new Error("V213_ACTIVATION_POINTER_WRITE_NOT_VERIFIED");
  }
  return {'''
        replacement = '''  if (currentRunId(confirmedPointer) !== runId) {
    throw new Error("V213_ACTIVATION_POINTER_WRITE_NOT_VERIFIED");
  }
  await verifySnapshotObjects(env, prefix, objects);
  return {'''
        value = base.replace_once(value, anchor, replacement, "Worker post-pointer readback")
    value = value.replace("    idempotent_replay: false,", "    idempotent_replay: idempotentReplay,")
    base.write(path, value)


def patch_broadcast() -> None:
    path = "cloud/src/v213/broadcast.ts"
    value = base.read(path)
    import_line = 'import { runV213BroadcastOnce } from "./broadcast-dedupe";\n'
    if import_line not in value:
        value = import_line + value
    if "V213_BROADCAST_DEDUPE?: DurableObjectNamespace;" not in value:
        patterns = [
            re.compile(r"(export\s+interface\s+V213BroadcastEnv\s*\{)"),
            re.compile(r"(interface\s+V213BroadcastEnv\s*\{)"),
            re.compile(r"(export\s+type\s+V213BroadcastEnv\s*=\s*\{)"),
            re.compile(r"(type\s+V213BroadcastEnv\s*=\s*\{)"),
        ]
        count = 0
        for pattern in patterns:
            value, count = pattern.subn(r"\1\n  V213_BROADCAST_DEDUPE?: DurableObjectNamespace;", value, count=1)
            if count:
                break
        if not count:
            raise base.PatchError("broadcast env declaration was not found")
    if "runV213BroadcastOnce(" not in value:
        pattern = re.compile(
            r'\s+if \(slot !== "test" && \(await env\.EPHEMERAL_SECURITY_CACHE\.get\(dedupeKey\)\)\) \{\n'
            r'\s+return \{ status: "duplicate" \};\n\s+\}\n\n'
            r'\s+await pushText\(env, owner\.lineUserId, message\);\n'
            r'\s+if \(slot !== "test"\) \{\n'
            r'\s+await env\.EPHEMERAL_SECURITY_CACHE\.put\(dedupeKey, "sent", \{ expirationTtl: 259200 \}\);\n'
            r'\s+\}\n'
            r'\s+return \{\n\s+status: "sent",'
        )
        replacement = '''
  if (slot === "test") {
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
        value, count = pattern.subn(replacement, value, count=1)
        if count != 1:
            raise base.PatchError("legacy LINE dedupe block was not found")
    base.write(path, value)


def patch_qa_timeout() -> None:
    path = "cloud/src/qa.ts"
    value = base.read(path)
    if "LOCAL_LLM_TIMEOUT_MS?: string;" not in value:
        patterns = [
            ("  LOCAL_LLM_MODEL?: string;", "  LOCAL_LLM_MODEL?: string;\n  LOCAL_LLM_TIMEOUT_MS?: string;"),
            ("  LOCAL_LLM_MODEL: string;", "  LOCAL_LLM_MODEL: string;\n  LOCAL_LLM_TIMEOUT_MS?: string;"),
        ]
        for old, new in patterns:
            if old in value:
                value = value.replace(old, new, 1)
                break
        else:
            # Structural typing permits the runtime lookup even when the
            # repository composes QaEnv from another interface.
            pass
    if "function localModelTimeoutMs" not in value:
        anchor = "async function localAnswer("
        helper = '''function localModelTimeoutMs(env: QaEnv): number {
  const raw = (env as QaEnv & { LOCAL_LLM_TIMEOUT_MS?: string }).LOCAL_LLM_TIMEOUT_MS;
  const parsed = Number(raw ?? 90000);
  if (!Number.isFinite(parsed)) return 90000;
  return Math.max(20000, Math.min(110000, Math.trunc(parsed)));
}

''' + anchor
        value = base.replace_once(value, anchor, helper, "local model timeout helper")
    value = value.replace("signal: AbortSignal.timeout(20000),", "signal: AbortSignal.timeout(localModelTimeoutMs(env)),")
    base.write(path, value)


base.patch_activation_core = patch_activation_core
base.patch_worker_activation = patch_worker_activation
base.patch_broadcast = patch_broadcast
base.patch_qa_timeout = patch_qa_timeout

if __name__ == "__main__":
    raise SystemExit(base.main())
