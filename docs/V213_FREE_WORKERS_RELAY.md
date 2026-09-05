# R75 FREE_RELAY — current operations

[Current release identity and evidence](../README.md) · [繁體中文](../README.zh-TW.md)

```text
workers.dev -> authenticated route lease -> ephemeral TryCloudflare
            -> Gateway -> existing llama.cpp -> exact qwen38-q6
```

No custom domain or paid fallback. Only workers.dev is stable. The Router remains models-max1; only authenticated compact Q&A/smoke requests use the authorized request-level non-thinking mode. The user's preset is not edited.

## Query routing

- Ranking/report tools remain deterministic.
- Ticker context contains only the selected public row's evidence; generic context is bounded; methodology uses fixed context.
- qa.ts privacy, freshness and tenant-memory checks are preserved. The compact wrapper is not a scoring/publication validator and cannot upgrade LIMITED.
- Fixed marker smoke uses no snapshot context. Gateway health alone is not model completion.

## Lease lifecycle

Local bridge and Worker each require three exact-model/health-schema-v2 public checks. Signed route records carry schema, model, URL, connected/expiry times, generation and health count. The DO atomically accepts a newer generation or monotonic heartbeat; expired, stale, replayed and mismatched routes fail closed.

Secrets are derived from the existing DPAPI-protected HMAC configuration, never included in route records or receipts. A new healthy bridge replaces the old bridge; an at-logon reconnect task points to `%LOCALAPPDATA%\InvestorIntelligence\V213Runtime`. This hotfix did not modify the08:00/21:00 tasks or Worker crons.

## One deployment readiness gate

`GET /v213/readiness` is genuinely no-write: no HMAC nonce, KV, DO, model or LINE access. It echoes a fresh challenge and verifies serving-version metadata, actual SEC provenance parser compatibility, publication-contract hash and compact-policy hash.

The activation sync client is the single gate owner: exact100% control plane -> three consecutive matching readiness proofs -> control-plane recheck -> version-pinned commit. The core also checks the uploaded version matches the active version. Only an explicit version mismatch consumes the bounded convergence budget; unknown/old schema, timeout and arbitrary validation errors fail closed. There is no TOP20_INVALID retry or fixed15s propagation sleep.

The authenticated POST smoke endpoint **does write an anti-replay authentication nonce**; it does not write the snapshot. Production smoke therefore requires authorization, unlike the readiness GET.

## Testing and evidence

One opt-in operator driver, `scripts/v213_qa_live_gate.py --live-isolated --output <new-file>`, creates only uniquely named test resources and deletes them afterward. It tests the actual shared readiness gate, lease, fixed smoke, five cold/warm model cases and real waitUntil completion with synthetic LINE transport. Public benchmark fixtures are synthetic—not a claim about current market facts.

CI never runs that external driver. It verifies the source-bound live receipt offline, runs the complete regression and final-ZIP/installer gates, then packages an immutable source-SHA/run-ID ZIP. See [delivery report](../state/FINAL_DELIVERY_REPORT_R75_FREE_RELAY.md). Old dated documents and releases remain historical evidence, not current authority.
