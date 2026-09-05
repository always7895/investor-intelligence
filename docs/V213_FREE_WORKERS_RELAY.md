# Investor Intelligence v2.1.3 R75 FREE_RELAY

[主 README](../README.md)｜[繁體中文完整說明](../README.zh-TW.md)｜[最新不可變正式版](https://github.com/always7895/investor-intelligence/releases/tag/v2.1.3-R75-free-relay-final-92c97f9-33896931576)

## 繁體中文摘要

FREE_RELAY 是目前正式上線的零成本本機模型連線模式。它不要求購買網域，也不把短效 TryCloudflare hostname 當成固定入口。

```text
LINE／外部請求
  -> 固定 workers.dev Worker
  -> HMAC 驗證的 Durable Object route lease
  -> 短效 TryCloudflare Quick Tunnel
  -> 本機 v2.1.3 Gateway
  -> llama.cpp Router
  -> 精確模型 qwen38-q6
```

目前正式狀態：

```text
Release tag：v2.1.3-R75-free-relay-final-92c97f9-33896931576
Release source：92c97f97694e6e39c7a16986630d248c9ee744fe
Windows CI：33896931576 / PASS
ZIP SHA-256：8b29e6b7ad6237042824e4c6af3a9b9cc16ea8a9e716b51fdfa8aca2c7da56ec
Production Worker：27121388-1e6e-445a-b45e-104a867ca70d / 100%
Stable entrypoint：https://investor-intelligence-v21-owner-line.moon951753.workers.dev
Custom domain required：false
Exact model：qwen38-q6
P0/P1/P2：0/0/0
```

## 零成本架構｜Zero-cost architecture

```text
LINE / external clients
  -> existing stable *.workers.dev Worker
  -> authenticated current-local-route Durable Object lease
  -> ephemeral free *.trycloudflare.com Quick Tunnel
  -> local v2.1.3 Gateway
  -> llama.cpp exact model qwen38-q6
```

FREE_RELAY does not require, purchase or configure a custom domain. The `workers.dev` Worker remains the only stable public entrypoint. A TryCloudflare hostname is explicitly ephemeral and is never presented as stable.

Named Tunnel support remains an optional future stable path, but it is not the current default and is not required by FREE_RELAY.

## Route lease contract

新 route record 只有在本機與 Worker 端都完成驗證後才可發布：

- `tunnel_mode = quick_free_relay`；
- exact model `qwen38-q6`；
- ephemeral HTTPS public URL；
- `connected_at`；
- `expires_at`／TTL；
- `health_schema_version = 2`；
- unique `route_generation`；
- `consecutive_health_checks = 3`。

The request uses the existing DPAPI-protected owner-Worker HMAC configuration. Authentication material and the derived per-generation Gateway secret are never included in the route record, logs or release assets.

The Worker independently performs three schema/model health checks before submitting the route to one Durable Object. The Durable Object serializes updates and atomically accepts only a newer generation or a valid monotonic heartbeat. It rejects malformed, expired, stale, model-mismatched, duplicated and replayed records.

Q&A requests resolve the current lease internally and derive the same per-generation Gateway secret without storing that plaintext secret in route state. Expired leases resolve to unavailable instead of using stale routing data.

## Production Workers runtime compatibility

Cloudflare production Workers runtime accepts `redirect: "follow"` and `redirect: "manual"`, but rejects `redirect: "error"` before issuing the request.

R75 therefore:

1. preserves the certified `cloud/src/qa.ts` blob byte-for-byte;
2. installs a narrowly scoped v2.1.3 compatibility adapter only for HTTPS `POST /v1/chat/completions`;
3. changes the runtime request to `redirect: "manual"`;
4. explicitly throws on every 3xx response;
5. retains fail-closed redirect behavior without changing Q&A or Serenity semantics.

The same correction is applied to Worker-side route health verification: `manual` is used and every non-2xx or schema/model mismatch is rejected.

## Authenticated end-to-end smoke gate

```text
POST /v213/admin/free-relay-smoke
```

This operation:

- requires the existing HMAC admin signature;
- accepts only `{ "schema_version": 1 }`;
- does not accept an arbitrary user prompt;
- does not write public or tenant KV state;
- sends a fixed marker request through the current lease;
- succeeds only when the exact local model returns the expected fixed marker.

The verified production smoke returned HTTP 200 with:

```text
status=PASS
model=qwen38-q6
health_schema_version=2
stable_entrypoint=workers_dev
expected_token_observed=true
```

## Reconnect, heartbeat and rollback

- A heartbeat extends the current lease only while Gateway and cloudflared remain alive and the Worker can revalidate the exact model route.
- If a process exits or the lease cannot be revalidated, the lease is not extended and expires closed.
- A reconnect launches a complete new FREE_RELAY generation.
- The previous route remains current until the new generation passes local and Worker-side health checks and the Durable Object atomically replaces it.
- Failed startup or registration stops the new bridge and preserves the prior healthy route where possible.
- `InvestorIntelligence-v213-FreeRelay` is the current at-logon task.
- The task was actually triggered, returned `LastTaskResult=0`, generated a new route, stopped the prior generation and passed a complete heartbeat cycle plus smoke test.
- The old `InvestorIntelligence-v212-LocalModelBridge` task is disabled.

## Router model policy

The current production state uses one llama.cpp Router on `127.0.0.1:8080`:

```text
models-max=1
qwen38-q6=loaded
other large models=unloaded
```

Do not launch a second llama-server. If `/models` is empty after an external restart, stop the empty Router and serially restart the same executable/port with the project preset, then trigger the FREE_RELAY task again.

## No-mutation validation

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\test_v213_free_relay.ps1
pwsh -NoProfile -File scripts\test_v213_free_relay.ps1
```

The authoritative CI run additionally verified:

```text
Python 550 passed / 2 skipped
Worker 19 files / 113 tests
PowerShell 5.1 / 7
Security scan
Activation preflight/wrapper
Heartbeat/task/lock
Named Tunnel regression
Artifact/manifest/checksum/SBOM/receipts
```

CI uses synthetic credentials, Durable Object state and health responses and retains `production_mutation_by_ci=false`. Real Worker deployment, route registration and Task Scheduler setup are separate explicitly authorized operator actions.

## Serenity and publication boundary

FREE_RELAY does not modify:

- Serenity scoring;
- source federation thresholds;
- publication-mode contract;
- LIMITED/EVIDENCE_QUALIFIED semantics;
- sealed bundle contents;
- release evidence rules;
- certified `cloud/src/qa.ts`.

Transport failures, route expiry, model mismatch or missing market corroboration cannot silently promote confidence or bypass publication gates.

## Health checks

```powershell
Invoke-RestMethod http://127.0.0.1:8080/models
Get-ScheduledTask -TaskName 'InvestorIntelligence-v213-FreeRelay'
Get-ScheduledTaskInfo -TaskName 'InvestorIntelligence-v213-FreeRelay'
Invoke-RestMethod https://investor-intelligence-v21-owner-line.moon951753.workers.dev/health
```

Never publish the current ephemeral TryCloudflare hostname, HMAC secret, Gateway secret, Cloudflare credential, LINE token or brokerage data in GitHub text fields.
