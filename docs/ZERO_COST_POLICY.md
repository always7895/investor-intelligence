# Zero-Cost and No-Billing Policy

_Last reconciled: 2026-08-25 Asia/Taipei_

## Normative boundary

```text
FREE_ONLY_MODE=FAIL_CLOSED
CLOUD_INFERENCE=DISABLED
PAID_FALLBACK=FORBIDDEN
LINE_PUSH=DISABLED
GITHUB_HOSTED_RUNNERS=FORBIDDEN
```

The project must not require, initiate or permit an automatic paid charge. When a free quota or local resource is unavailable, it fails closed or returns a clearly labelled degraded status.

Electricity, Internet access and already-owned hardware are outside the software billing boundary; the software cannot purchase, upgrade or subscribe to anything.

## Runtime cost policy

Required behavior:

- no payment method is required;
- no paid subscription is a prerequisite;
- no automatic plan upgrade;
- no usage-billed fallback;
- no paid model, search, news or market-data API;
- no premium data-source dependency or paywall bypass;
- no GitHub-hosted runner;
- no billable artifact/cache dependency;
- no paid LINE messages or push sender;
- quota exhaustion never becomes a charge.

The runtime policy authority is `cost.mode=free_only_fail_closed`.

## Local inference only

General generative Q&A uses the operator's private local Qwen/llama.cpp service through an authenticated, exact-host-allowlisted HTTPS route.

- Per-request software fee is zero.
- No public model endpoint is permitted.
- No cloud-model binding is permitted.
- No cloud-model fallback is permitted.
- No automatic model download is performed.
- A controlled unavailable response is returned when the local route is offline.

Deterministic public tools may continue when reviewed cached data is present and fresh.

## Cloudflare policy

A future deployment may use only Cloudflare Workers Free for webhook execution and physically separated KV storage.

- Workers Paid is prohibited.
- Automatic account upgrade is prohibited.
- Workers AI and other cloud inference are disabled.
- No D1, R2, Vectorize, Durable Object, Logpush or premium add-on is a required dependency.
- Project-side request and KV-write soft limits remain below the reviewed free allocation.
- Public KV network writes are dry-run by default and require explicit apply plus environment gates.
- Exceeding a soft or free limit returns a controlled unavailable/degraded status.

Repository defaults:

```text
CLOUDFLARE_PLAN=workers_free
WORKERS_DAILY_REQUEST_SOFT_LIMIT=90000
KV_DAILY_WRITE_SOFT_LIMIT=800
```

These are safety ceilings, not availability guarantees.

## LINE policy

- Keep the LINE Official Account on a free plan.
- Reply messages are the only supported response path.
- Push, multicast, broadcast, narrowcast and scheduled delivery are absent or disabled.
- The repository contains no local report-to-LINE sender and no raw user-ID push target.
- Quota exhaustion or admission failure causes fail-closed behavior without purchasing messages.
- Long-running work, when supported, is retrieved by a later user reply request rather than push.

## GitHub policy

- Private-repository validation uses the dedicated self-hosted Windows runner only.
- GitHub-hosted labels, larger runners and hosted fallbacks are forbidden.
- Jobs queue or fail when BARRY is offline.
- Workflows use read-only permissions, immutable Action SHAs and locked dependencies.
- Continuous workflow artifacts and caches are not required.
- Final release files are created only after release acceptance.

## Data-source policy

A required source is eligible only when the intended access is lawful and free.

Preferred categories include:

- regulators, exchanges and government institutions;
- issuer investor-relations and official publications;
- multilateral and open public datasets;
- reviewed public market observations;
- reputable discovery/corroboration sources that do not replace primary evidence.

Rules:

- catalog size has no fixed ceiling;
- catalog membership does not activate a source;
- every runtime source remains disabled until authority, rights/free-access, schema, privacy, adapter and health gates pass;
- paid or premium credentials are not accepted;
- paywalled text is not bypassed;
- source failure yields degraded/unavailable output or a reviewed lawful free replacement;
- local IBKR data, when separately enabled, is local-only and never a LINE or public-data fallback.

## Forbidden behavior

The system must not:

- ask the operator to add a payment method;
- click or call an upgrade operation;
- create a paid subscription;
- rely on trial credits that roll into billing;
- retry a free-tier rejection against a paid endpoint;
- hide quota exhaustion by presenting stale data as current;
- enable a paid model, quote, news or search provider;
- purchase LINE messages;
- move a workflow to a hosted runner.

## Structured degraded statuses

Examples:

```text
LOCAL_MODEL_OFFLINE
FREE_DATA_SOURCE_UNAVAILABLE
FREE_QUOTA_UNAVAILABLE
SELF_HOSTED_RUNNER_OFFLINE
CURRENT_PUBLIC_DATA_DISABLED
STALE_PUBLIC_DATA
```

A response states what remains available and discloses freshness or reset information when safely known.

## Deployment certification

Before activation, verify:

1. Cloudflare Workers Free and the LINE free plan;
2. no payment method or paid provider is required;
3. no cloud inference binding or credential exists;
4. no GitHub-hosted runner appears in active workflows;
5. LINE push and scheduled delivery are absent;
6. the local model route is private, authenticated and exact-host allowlisted;
7. public KV writes are explicit and free-only gated;
8. simulated quota exhaustion fails closed;
9. every required source is lawful, free and reviewed;
10. documentation and runtime policy agree.

## Availability limitation

The project guarantees no paid fallback, not unlimited capacity. When the local model, free platform allocation or reviewed public source is unavailable, the corresponding function remains unavailable rather than incurring a charge.
