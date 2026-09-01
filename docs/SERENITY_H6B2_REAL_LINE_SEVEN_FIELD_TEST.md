# H6B2 — real owner LINE seven-field acceptance

H6B2 is a one-shot acceptance stage for the exact H6B1 R15 seven-field preview.
It does **not** switch the scheduled 08:00 / 21:00 broadcast from v2.1.2 to
v2.1.3.

## Accepted R15 artifact lock

- R15 source SHA: `f1d6790de99c8af981a40e26993a12a444b214ba`
- full shadow SHA-256: `cf0ff1a5a1499a8179fb0b68169511ec71c12f548069a3ee3a711955b705c284`
- seven-field preview SHA-256: `b186136c5540cd9d0d50eb74cf2f0417ccba8b1e6ed16ad15de42e62a8b1334f`
- validation receipt SHA-256: `ffdb272c62ce537dc6537d7a80c9dbd112b064e1b816e3bdc8851f7d044b45d7`

The LINE payload is accepted only when the preview has the exact seven-column
header, exactly 20 unique rows, exactly seven fields per row, a single LINE text
message under 4,900 characters, and the same ticker order as the current public
`v21:top20:latest` snapshot.

## Deployment boundary

`cloud/src/v213/h6b2-worker.ts` is a temporary entrypoint. It adds only the
HMAC-authenticated `POST /v21/admin/v213-test-push` route. All other fetch paths
and scheduled events delegate to the already accepted v2.1 owner Worker.

The Windows acceptance runner:

1. validates the local R15 artifacts by exact SHA-256;
2. validates the H6B2 source scope and complete Worker tests;
3. creates a temporary Wrangler config by copying the already installed v2.1
   production config and replacing only `main` with the H6B2 delegated entrypoint;
4. deploys that temporary Worker version;
5. sends one HMAC-authenticated request containing the exact R15 preview;
6. requires LINE API success;
7. immediately rolls the Worker back to the version active before H6B2.

No LINE credential, HMAC secret, owner LINE ID, KV record or scheduled format is
written by the H6B2 route. The encrypted local HMAC is decrypted only in process
memory and cleared after use.

## Acceptance result

A successful H6B2 run proves only that the accepted R15 seven-field payload was
actually delivered to the already paired owner LINE account without changing the
scheduled production format. Visual inspection of the received LINE message is
still required before a later stage may switch scheduled broadcasts to v2.1.3.
