# v2.1.3 R75 FREE_RELAY deployment mode

## Zero-cost architecture

```text
LINE / external clients
  -> existing stable *.workers.dev Worker
  -> authenticated current-local-route lease
  -> ephemeral free *.trycloudflare.com Quick Tunnel
  -> local v2.1.3 Gateway
  -> llama.cpp exact model qwen38-q6
```

FREE_RELAY does not require, purchase, or configure a custom domain. The `workers.dev` Worker remains the only stable public entrypoint. A TryCloudflare hostname is explicitly ephemeral and is never presented as stable.

Named Tunnel support remains available as an optional future stable path, but it is not the default and is not required by FREE_RELAY.

## Route lease contract

After the local bridge validates three consecutive public `/health` responses with health schema v2 and exact model `qwen38-q6`, it signs and sends a route record to the existing Worker:

- `tunnel_mode = quick_free_relay`
- exact model
- ephemeral public URL
- `connected_at`
- `expires_at`
- health schema version
- unique route generation
- consecutive health count

The request uses the existing DPAPI-protected v2.1 owner-Worker HMAC configuration. Authentication material and the derived per-generation Gateway secret are never included in the route record or logs.

The Worker independently performs three schema/model health checks before submitting the route to a single Durable Object. The Durable Object atomically applies a newer generation or a monotonic heartbeat. It rejects malformed, expired, stale, model-mismatched, duplicated, and replayed records. Q&A requests resolve the current lease internally and derive the same per-generation Gateway secret. Expired leases resolve to unavailable rather than a stale tunnel.

## Reconnect and rollback

- A heartbeat extends the current lease only while both Gateway and cloudflared processes remain alive and the Worker can revalidate the route.
- If either process exits, the monitor launches a complete new FREE_RELAY generation.
- The old Worker route remains current until the new Quick Tunnel passes local and Worker-side health validation and the Durable Object atomically replaces it.
- Failed startup or failed registration stops the new bridge and leaves the previous route untouched where it remains healthy.
- At logon, `register-v213-free-relay-task.ps1 -Enable` can configure automatic reconnect. `-ValidateOnly` performs no Task Scheduler mutation.

The launcher defaults refresh, bridge, and activation preflight to FREE_RELAY. Its reconnect button is an explicit operator action. `AllowTestTunnelException` is not used by this architecture.

## No-mutation validation

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\test_v213_free_relay.ps1
pwsh -NoProfile -File scripts\test_v213_free_relay.ps1
```

CI uses synthetic endpoints, credentials, Durable Object state, and health responses. It does not deploy the Worker, register a real task, update Production storage, send LINE, or create a real tunnel.
