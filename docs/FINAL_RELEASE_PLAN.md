# Release maintenance rules

Current identity/status: [README](../README.md). Avoid duplicated version tables.

1. Fetch source and inspect current CI and actual machine evidence; do not inherit a blanket completion claim.
2. Preserve scoring, publication/claim-independence, freshness, privacy and exact-model boundaries.
3. Make the smallest runtime change. Use one readiness gate and one opt-in isolated live benchmark, not repeated deployment sleeps or temporary workflows.
4. Runtime changes invalidate the source-bound live proof. Test-only operator refactors retain their historical hashes but do not pretend to be new model measurements.
5. Run security, full Python/Worker regression, typecheck, PS5.1/7, fail-closed lease/readiness/publication tests and historical/current-time bundle checks.
6. Verify actual complete cold/warm model answers and reference completion. Never count reasoning-only, truncated or healthy-but-unanswered requests as PASS.
7. CI must not mutate Production. Build an immutable SHA/run-ID ZIP only with qualified live evidence; test the final extracted ZIP and isolated installer.
8. Independently download and verify the archive and receipts. Separately authorized operator cutover must preserve the existing snapshot and schedules unless a specific data/schedule change is requested.
9. Publish one new immutable release, update the authoritative README and repository homepage once, and archive old status narratives. Record what was and was not actually tested.
