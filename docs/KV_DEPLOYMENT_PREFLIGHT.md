# KV deployment preflight

No deployment is performed during development. Before a future release can create or bind Cloudflare KV namespaces, six real IDs must be supplied outside Git and validated:

```text
CLOUDFLARE_PUBLIC_KV_NAMESPACE_ID
CLOUDFLARE_TENANT_PRIVATE_KV_NAMESPACE_ID
CLOUDFLARE_EPHEMERAL_SECURITY_KV_NAMESPACE_ID
CLOUDFLARE_PUBLIC_PREVIEW_KV_NAMESPACE_ID
CLOUDFLARE_TENANT_PRIVATE_PREVIEW_KV_NAMESPACE_ID
CLOUDFLARE_EPHEMERAL_SECURITY_PREVIEW_KV_NAMESPACE_ID
```

Run the release-only preflight:

```powershell
python scripts/validate_kv_namespace_ids.py --require-configured
```

The command never prints namespace values. It reports only missing labels, placeholder labels and groups of roles that accidentally reuse an ID.

A release must fail when:

- any label is absent;
- any value remains a placeholder;
- any production ID equals another production or preview ID;
- any preview ID equals another preview or production ID;
- the old combined namespace is selected for migration;
- conversation memory is enabled before Phase 8 deletion/race acceptance.

The public snapshot must be rebuilt into a fresh `PUBLIC_CACHE`. No data is copied from a legacy combined namespace. `TENANT_PRIVATE_CACHE` and `EPHEMERAL_SECURITY_CACHE` begin empty.
