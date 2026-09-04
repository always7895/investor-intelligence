# v2.1.3 R75 Production Named Tunnel deployment hotfix

This hotfix replaces the test-only Quick Tunnel path for formal Production activation. It does not change scoring, source federation, publication modes, sealed bundles, or release evidence rules.

## One-time setup

1. Install `cloudflared` and authenticate interactively with Cloudflare (`cloudflared tunnel login`). Do not copy credentials into the package or logs.
2. Create a named tunnel and its credentials file if one does not already exist.
3. Prepare a YAML config containing:
   - the tunnel name or UUID;
   - `credentials-file` pointing to the local Cloudflare tunnel credential JSON;
   - exactly one loopback HTTP ingress service for the gateway (normally `http://127.0.0.1:8814`);
   - the intended hostname and a terminal fallback rule.
4. In `InvestorIntelligence.exe`, choose **One-time Named Tunnel setup** and explicitly enter `NamedTunnelName`, `NamedTunnelHostname`, and `NamedTunnelConfig`.

The setup fails closed unless cloudflared authentication works, the credential JSON has the required Cloudflare tunnel fields, the config identity and ingress validate, the tunnel exists, and Cloudflare accepts an exact DNS route ensure. `--overwrite-dns` is used deliberately so an existing unrelated DNS record is not mistaken for a verified route.

Only non-secret metadata is written under `%LOCALAPPDATA%\InvestorIntelligence\UserData\config\v213-named-tunnel.json`. Credential contents and the credential-file path are not copied into metadata, stdout, receipts, or the repository.

## Bridge and activation

The launcher passes all required values explicitly:

```powershell
-TunnelMode Named `
-NamedTunnelName <name> `
-NamedTunnelHostname <hostname> `
-NamedTunnelConfig <config-path>
```

The bridge verifies the selected router model without substitution, requires health schema v2, starts a new gateway and named-tunnel connector before retiring the recorded bridge, and requires three consecutive public `/health` successes. If startup or public verification fails, only the new processes are stopped and the recorded bridge is retained. The runtime ingress config is generated for the newly selected blue/green gateway port and removed after cloudflared loads it.

`AllowTestTunnelException` is not used by this normal Production path. Quick Tunnel remains test-only.

## No-mutation validation

Use these local gates without touching Cloudflare, Worker, Production KV/DO, LINE, or schedules:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\test_v213_named_tunnel.ps1
pwsh -NoProfile -File scripts\test_v213_named_tunnel.ps1
```

The tests use a synthetic cloudflared executable and synthetic credential material in a special-character temporary path. Never use real credentials in CI or test fixtures.
