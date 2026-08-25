# Security and Credential Operations

_Last reconciled: 2026-08-25 Asia/Taipei_

## Normative boundary

```text
LINE_DATA_SCOPE=PUBLIC_ONLY
LINE_IBKR_BRIDGE=FORBIDDEN
LINE_PORTFOLIO_TOOLS=FORBIDDEN
LINE_PRIVATE_SYNC=FORBIDDEN
LINE_GROUP_ROOM=REJECTED
LINE_OWNER_DATA=FORBIDDEN
FREE_ONLY_MODE=FAIL_CLOSED
```

## Incident and containment status

Historical repository objects contained operational credentials, direct identifiers, user-specific paths and obsolete delivery/private-data helpers. Current-tree removal and credential rotation contain active exposure but do not clean Git history.

Current containment requires:

- historical LINE and mail credentials remain revoked or rotated;
- no credential-bearing delivery helper exists in the current tree;
- no local report-to-LINE sender exists;
- no private synchronization endpoint or helper exists;
- no owner, portfolio or broker path exists in Worker or LINE;
- runtime values come only from protected environment variables or secret stores;
- examples remain synthetic;
- the repository remains private until history remediation passes.

Full Git-history remediation is a final destructive gate and is never performed automatically.

## Approved secret locations

Secrets may exist only in:

- protected Windows machine/service environment variables for local-only runtime;
- GitHub Actions Secrets for trusted owner-controlled self-hosted validation when strictly required;
- Cloudflare Worker Secrets for a later reviewed Workers Free deployment.

Secrets never belong in source, committed JSON/TOML, logs, issues, PRs, screenshots, chats, reports, workflow summaries or release archives.

The shared bot stores no raw push destination and has no push sender. Raw LINE IDs are transient event data only.

## Shared LINE security

- Default admission is `disabled`.
- Only direct-chat HMAC allowlisting is supported.
- Group and room events are rejected before reply or state mutation.
- Missing secrets, invalid configuration and unauthorized users fail silently and closed.
- The shared bot has no owner/operator role.
- First-person sensitive financial disclosures are rejected before tool, model and memory processing.
- LINE and Worker cannot call IBKR, read a portfolio or ingest owner-local reports.
- Reply messages are the only runtime response path; scheduled and delayed push are absent.

## Tenant and storage security

- Tenant IDs are HMAC-SHA-256 derived; raw provider IDs are excluded from keys and logs.
- Public, tenant-private and ephemeral-security state use three independent KV bindings.
- Public KV contains attested public artifacts only.
- Tenant-private KV is reserved for optional encrypted conversation/job state only.
- Security KV contains hashed dedupe and pseudonymous rate-limit state only.
- Conversation memory is unavailable for the initial external-user release.
- A future memory release requires AES-GCM, per-tenant keys, bounded TTL/turns and deletion epochs.
- No owner portfolio, broker data or private preference enters any LINE namespace.
- The legacy combined cache binding and migration copy are forbidden.

## Local model egress

The local Qwen/llama.cpp route must be:

- HTTPS;
- exact-host allowlisted;
- authenticated;
- default HTTPS port only;
- non-redirecting;
- free of IP literals, localhost/public exposure, wildcard hosts and embedded credentials.

Only bounded public context and, in a future explicitly enabled release, the current tenant's own opt-in memory may enter the model. Public option chains, owner data and broker data are excluded from arbitrary model context.

## Local IBKR security

Optional IBKR support is:

- disabled by default;
- loopback HTTPS only;
- read-only;
- local-only;
- unable to reach LINE, Worker, public KV or shared model context;
- unable to create, modify, cancel or exercise orders or mutate transfer, funding or subscription state.

Broker-derived data remains broker-derived after minimization and is rejected from public artifacts.

## Self-hosted runner

1. Keep runner files outside the repository and application.
2. Never commit runner credentials, service files, `_work` or `_diag`.
3. Run only trusted owner-controlled code.
4. Never use `pull_request_target`.
5. Use read-only permissions and `persist-credentials: false`.
6. Pin third-party Actions to reviewed immutable SHAs.
7. Install Python only from isolated binary-only hash locks and use `npm ci --ignore-scripts`.
8. Pass no production LINE, Cloudflare, broker or local-model secrets to development jobs.
9. Clean ephemeral Node and Python working state after jobs.

## Logging

Allowed metadata is content-free: random reference ID, intent/tool class, status/error code, duration, quota units and public timestamps.

Forbidden:

- secrets or environment dumps;
- raw user, group, room or event IDs;
- message, answer, prompt or reply-token text;
- tenant membership or allowlist details;
- holdings, costs, P&L, account or broker data;
- webhook bodies, authorization headers or provider payloads;
- model-route configuration in unauthenticated health output.

## Git-history remediation gate

Before external-user access or final release:

1. create and verify an offline mirror backup;
2. freeze the accepted current tree;
3. obtain explicit approval for destructive rewrite and force-push;
4. remove historical credentials, direct identifiers, private paths/examples and identifying commit metadata;
5. remove obsolete refs/tags and expire unreachable objects under a reviewed procedure;
6. re-clone into a clean directory;
7. run the manual all-object `--require-clean` scanner;
8. rerun complete exact-head release and package acceptance;
9. keep or destroy the backup according to a documented secure retention decision.

Until this gate passes, the repository remains private and no external user is admitted.

## Release security

The final ZIP is built reproducibly from a clean exported tree. It excludes Git history, secrets, raw IDs, messages, owner/private files, actual portfolios, broker data, caches, reports, logs, runner state and model weights. A checksum, manifest and SBOM accompany the package.
