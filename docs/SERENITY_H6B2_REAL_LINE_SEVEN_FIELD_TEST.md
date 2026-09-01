# H6B2 — real owner LINE seven-field acceptance

H6B2 is a one-shot acceptance stage for the H6B1 R15 seven-field data after an
order-only reconciliation to the live public Top20. It does **not** switch the
scheduled 08:00 / 21:00 broadcast from the accepted v2.1 Worker to v2.1.3.

## Accepted R15 / R15R artifact lock

- R15 source SHA: `f1d6790de99c8af981a40e26993a12a444b214ba`
- full shadow SHA-256: `cf0ff1a5a1499a8179fb0b68169511ec71c12f548069a3ee3a711955b705c284`
- original R15 preview SHA-256: `b186136c5540cd9d0d50eb74cf2f0417ccba8b1e6ed16ad15de42e62a8b1334f`
- original R15 validation receipt SHA-256: `ffdb272c62ce537dc6537d7a80c9dbd112b064e1b816e3bdc8851f7d044b45d7`
- R15R order-reconciled preview SHA-256: `ff0e0cfad5fffb6f0ed9c1482bc145f3ced7722f5eb571488e82a4f7b979c2c9`
- R15R order-reconciliation receipt SHA-256: `a9298a29ed007f0b697d6d57789dc00c795a1ff34c66c10903a50018ea1b4282`

R6 observed the live snapshot `20260901T122248Z-fccfd14d3c79` with the same 20
members as R15 but an order-only drift at rank 18. The reconciled order is:

`MU,NVDA,CRDO,WDC,ALAB,AMD,PLTR,APH,AAOI,OCC,AVGO,LIF,LRCX,LASE,NET,CDE,GWRE,SMCI,ADI,CF`

No row content is changed by R15R; only the three final rows are reordered from
`ADI,CF,SMCI` to `SMCI,ADI,CF`. The acceptance runner independently re-verifies
that the original and reconciled previews contain byte-identical rows per ticker
before any external mutation.

The LINE payload is accepted only when the preview has the exact seven-column
header, exactly 20 unique rows, exactly seven fields per row, a single LINE text
message under 4,900 characters, and the same ticker order as the current public
Top20 snapshot resolved through `snapshot:current` plus the direct-key fallback.

## Deployment boundary

`cloud/src/v213/h6b2-worker.ts` is a temporary entrypoint. It adds only the
HMAC-authenticated `POST /v21/admin/v213-test-push` route and a non-sensitive
`GET /h6b2/ready` probe. All other fetch paths and scheduled events delegate to
the already accepted v2.1 owner Worker.

The Windows acceptance runner:

1. validates the original R15 artifacts, the R15R preview and reconciliation
   receipt by exact SHA-256;
2. proves R15R is a row-order-only transform of the accepted R15 preview;
3. validates the H6B2 source scope and complete Worker tests;
4. resolves and locks the current Production Top20 order before deployment;
5. creates a temporary Wrangler config by copying the installed Production
   config and replacing only `main` with the H6B2 delegated entrypoint;
6. records the Worker version active before H6B2;
7. deploys the temporary Worker version;
8. sends one HMAC-authenticated request containing the exact R15R preview;
9. requires LINE API success; and
10. immediately restores and verifies the exact Worker version that was active
    before H6B2.

The H6B2 sender does not write public-snapshot or tenant payload data and does
not change scheduled-format state. The existing admin authentication layer does
write short-lived replay-nonce markers to `EPHEMERAL_SECURITY_CACHE`; that is an
intentional security write and is not treated as a payload/publication mutation.
No LINE credential, HMAC secret or raw owner LINE ID is printed or committed.

## Acceptance result

A successful H6B2 run proves only that the order-reconciled R15 seven-field
payload was actually delivered to the already paired owner LINE account without
changing the scheduled Production format. Visual inspection of the received LINE
message is still required before a later stage may switch scheduled broadcasts to
v2.1.3.
