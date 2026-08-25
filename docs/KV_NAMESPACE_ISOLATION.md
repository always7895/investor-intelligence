# LINE Worker KV namespace isolation

The shared LINE Bot uses three physically independent Cloudflare KV namespaces:

```text
PUBLIC_CACHE
  public reports, public scores, public source views, public option snapshots,
  versioned manifests and snapshot:current

TENANT_PRIVATE_CACHE
  encrypted opt-in conversation memory and encrypted long-job results only

EPHEMERAL_SECURITY_CACHE
  hashed webhook deduplication claims and pseudonymous rate-limit counters only
```

## Non-negotiable boundaries

- The three production IDs and three preview IDs must all be distinct.
- `PUBLIC_CACHE` never stores `tenant:*`, raw LINE IDs, messages or account data.
- `TENANT_PRIVATE_CACHE` never stores a public snapshot or shared ranking.
- `EPHEMERAL_SECURITY_CACHE` stores no message text, answer text or raw external identifier.
- The legacy `CACHE` binding is forbidden.
- Generic private JSON storage APIs are absent from the Worker.
- Conversation memory is unavailable by default for the first external-user release.
- Public KV publication targets the public namespace only; no publisher receives credentials for the private or ephemeral namespaces.

## Friend privacy

A friend's HMAC-derived tenant ID is used only inside the private and ephemeral namespaces. Public data cannot contain a tenant ID. A public-data lookup never reads the tenant-private namespace, and arbitrary model context never reads option chains or any tenant namespace except the current tenant's explicitly available encrypted conversation memory.

The repository owner's holdings, watchlist, IBKR data, account information and local reports do not enter any of the three LINE namespaces.

## Migration gate

A deployment must create fresh namespaces rather than reusing the former combined namespace. Legacy combined KV data is not copied. The public snapshot is rebuilt from independently attested public artifacts. Tenant memory begins empty and unavailable. Ephemeral security state begins empty.

No production migration or deployment is performed by this development branch.
