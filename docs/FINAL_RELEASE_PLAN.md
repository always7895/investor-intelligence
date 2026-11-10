# Release maintenance rules

Current identity/status / 最新版本與狀態：[README](../README.md) · [中英狀態 / Bilingual status](CURRENT_STATUS_BILINGUAL.md). Avoid duplicated version tables / 不重複維護版本表。

## 不可放寬的安全邊界 / Mandatory safety boundaries

LINE 僅使用公開資料，不接 IBKR、持倉工具、私有同步或擁有者私人資料；群組／room 拒絕；免費模式失敗即關閉，不轉付費。／LINE uses public data only: no IBKR bridge, portfolio tools, private synchronization or private owner data. Groups/rooms are rejected; free-only mode fails closed.

```text
LINE_DATA_SCOPE=PUBLIC_ONLY
LINE_IBKR_BRIDGE=FORBIDDEN
LINE_PORTFOLIO_TOOLS=FORBIDDEN
LINE_PRIVATE_SYNC=FORBIDDEN
LINE_GROUP_ROOM=REJECTED
LINE_OWNER_DATA=FORBIDDEN
FREE_ONLY_MODE=FAIL_CLOSED
```

1. Fetch source and inspect current CI and actual machine evidence; do not inherit a blanket completion claim.
2. Preserve scoring, publication/claim-independence, freshness, privacy and exact-model boundaries.
3. Make the smallest runtime change. Use one readiness gate and one opt-in isolated live benchmark, not repeated deployment sleeps or temporary workflows.
4. Runtime changes invalidate the source-bound live proof. Test-only operator refactors retain their historical hashes but do not pretend to be new model measurements.
5. Run security, full Python/Worker regression, typecheck, PS5.1/7, fail-closed lease/readiness/publication tests and historical/current-time bundle checks.
6. Verify actual complete cold/warm model answers and reference completion. Never count reasoning-only, truncated or healthy-but-unanswered requests as PASS.
7. CI must not mutate Production. Build an immutable SHA/run-ID ZIP only with qualified live evidence; test the final extracted ZIP and isolated installer.
8. Independently download and verify the archive and receipts. Separately authorized operator cutover must preserve the existing snapshot and schedules unless a specific data/schedule change is requested.
9. Publish one new immutable release, update the authoritative README and repository homepage once, and archive old status narratives. Record what was and was not actually tested.
