# Investor Intelligence v2.1.3 R75 FREE_RELAY

[繁體中文完整說明](README.zh-TW.md)｜[Latest immutable release](https://github.com/always7895/investor-intelligence/releases/tag/v2.1.3-R75-free-relay-final-92c97f9-33896931576)

> **研究軟體／Research software only.** 本專案不提供個人化投資建議、不保證報酬，也不能取代使用者對 SEC、公司公告、交易所資料與其他原始來源的自行查證。

Investor Intelligence is a privacy-first, zero-cost public-market research system. The current production architecture combines a stable Cloudflare `workers.dev` entrypoint with an authenticated, short-lived FREE_RELAY lease to a local llama.cpp model. The exact production model is `qwen38-q6`; no custom domain is required.

## 最新正式版本｜Current production release

| 欄位 / Field | 正式值 / Authoritative value |
|---|---|
| 版本 / Version | `v2.1.3 R75 FREE_RELAY` |
| 不可變 Release / Immutable release | `v2.1.3-R75-free-relay-final-92c97f9-33896931576` |
| 正式程式來源 / Release source commit | `92c97f97694e6e39c7a16986630d248c9ee744fe` |
| 權威 Windows CI / Authoritative Windows CI | `33896931576` — PASS |
| 正式 ZIP SHA-256 | `8b29e6b7ad6237042824e4c6af3a9b9cc16ea8a9e716b51fdfa8aca2c7da56ec` |
| Production Worker version | `27121388-1e6e-445a-b45e-104a867ca70d` — 100% active |
| Rollback baseline | `eb52ece1-8749-4526-a464-3356ec2dbc65` |
| 穩定公開入口 / Stable public entrypoint | `https://investor-intelligence-v21-owner-line.moon951753.workers.dev` |
| 本機模型 / Exact local model | `qwen38-q6` |
| 自訂網域 / Custom domain | **不需要 / Not required** |
| 最終缺陷 / Final defects | `P0=0, P1=0, P2=0` |

The release is protected by GitHub Immutable Releases, contains 10 attested assets, and passed post-download verification of ZIP CRC, path safety, MANIFEST, SHA256SUMS, SBOM, receipts, immutable identity and publication-contract binding.

## 目前運作狀態｜Operational status

- FREE_RELAY uses the existing `workers.dev` Worker as the only stable public entrypoint.
- The ephemeral `*.trycloudflare.com` hostname is never represented as stable.
- The local route is published only after three consecutive Health Schema v2 checks pass for exact model `qwen38-q6`.
- Route registration is HMAC-authenticated and generation-bound; stale, expired, malformed, replayed or model-mismatched leases fail closed.
- `InvestorIntelligence-v213-FreeRelay` is enabled as an at-logon Windows task with `StartWhenAvailable` and `MultipleInstances=IgnoreNew`.
- The task was actually triggered and returned result `0`; it created a new route generation, stopped the previous bridge generation and passed a complete heartbeat cycle plus end-to-end smoke test.
- The old `InvestorIntelligence-v212-LocalModelBridge` task is disabled and its obsolete port-8814 bridge/tunnel processes were removed before the final v2.1.3 generation was validated.
- The llama.cpp Router is constrained to `models-max=1`; only `qwen38-q6` is loaded during the verified production state.
- Existing 08:00 and 21:00 Asia/Taipei Worker schedules are retained. No manual LINE test message was sent during release verification.

## 零成本架構｜Zero-cost architecture

```text
LINE / external request
  -> stable Cloudflare workers.dev Worker
  -> authenticated current-route Durable Object lease
  -> ephemeral TryCloudflare Quick Tunnel
  -> local v2.1.3 Gateway
  -> llama.cpp Router on 127.0.0.1:8080
  -> exact model qwen38-q6
```

No paid domain, paid data source, paid model API or automatic paid fallback is required. Named Tunnel support remains an optional future path, not a requirement for the current FREE_RELAY deployment.

## Serenity 與證據邏輯｜Serenity and evidence logic

The R75 architecture separates scoring from publication eligibility:

```text
public-source evidence
  -> diversified Serenity-compatible operationalization
  -> publication contract
       ├─ EVIDENCE_QUALIFIED
       └─ LIMITED_RESEARCH_CANDIDATE
  -> confidence and delivery gates
```

Key invariants:

- Serenity scoring, source-federation thresholds, the publication-mode contract, sealed activation bundles and release-evidence rules are protected release boundaries.
- `cloud/src/qa.ts` remained byte-identical to the certified R75 baseline during FREE_RELAY work.
- LIMITED rows cannot be promoted to HIGH confidence, cannot be marked as validated theses and cannot retain unsupported positive sensitive factors.
- Missing free non-Yahoo market corroboration is disclosed and caps confidence instead of being silently fabricated.
- BLS is optional macro context, while required family/count and claim-level independence gates remain fail closed.
- Public reports, LINE and Worker state remain separated from brokerage accounts, holdings, cost basis, P&L and private owner data.

## Cloudflare Workers runtime compatibility

Cloudflare Workers production runtime rejects `redirect: "error"`. R75 preserves fail-closed behavior by adapting only HTTPS `POST /v1/chat/completions` calls to `redirect: "manual"` and explicitly rejecting every 3xx response. This transport compatibility layer does not change the certified Q&A or Serenity semantics.

An HMAC-authenticated, fixed-prompt `POST /v213/admin/free-relay-smoke` endpoint verifies the complete path:

```text
workers.dev -> route lease -> Quick Tunnel -> Gateway -> qwen38-q6
```

The verified smoke response returned HTTP 200 with the exact model, Health Schema v2 and the expected fixed marker.

## 驗證結果｜Validation evidence

The authoritative release gate passed:

- Python: **550 passed, 2 skipped**
- Worker: **19 files, 113 tests passed**
- TypeScript typecheck: **PASS**
- Windows PowerShell 5.1: **PASS**
- PowerShell 7: **PASS**
- Security/credential scan: **PASS**
- FREE_RELAY route, stale/replay/expiry/concurrency/heartbeat/reconnect/rollback tests: **PASS**
- Named Tunnel regression tests: **PASS**
- Activation preflight and wrapper self-tests: **PASS**
- Task Scheduler real trigger: **result 0**
- Post-download artifact verification: **PASS**

CI itself retained `production_mutation_by_ci=false`. The actual Worker deployment, real FREE_RELAY route and Windows task registration were separate explicitly authorized operator actions and are documented in the production evidence files.

## 下載與啟動｜Download and run

1. Open the [latest immutable release](https://github.com/always7895/investor-intelligence/releases/tag/v2.1.3-R75-free-relay-final-92c97f9-33896931576).
2. Download the versioned ZIP and its `.zip.sha256` file.
3. Verify SHA-256:

```powershell
$Zip = '.\Investor-Intelligence-v2.1.3-R75-Free-Relay-Hotfix-92c97f97694e6e39c7a16986630d248c9ee744fe-33896931576.zip'
(Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash.ToLowerInvariant()
```

Expected value:

```text
8b29e6b7ad6237042824e4c6af3a9b9cc16ea8a9e716b51fdfa8aca2c7da56ec
```

4. Extract to a dedicated folder and run `InvestorIntelligence.exe`.
5. Keep the existing llama.cpp Router at `http://127.0.0.1:8080` with exact model `qwen38-q6` available. Do not start a second Router instance.
6. FREE_RELAY reconnect is maintained by the registered Windows task and heartbeat. If the PC or tunnel restarts, the route expires closed until a new validated generation is published.

## 快速健康檢查｜Quick health checks

```powershell
# Router model inventory
Invoke-RestMethod http://127.0.0.1:8080/models

# FREE_RELAY task
Get-ScheduledTask -TaskName 'InvestorIntelligence-v213-FreeRelay'
Get-ScheduledTaskInfo -TaskName 'InvestorIntelligence-v213-FreeRelay'

# Stable Worker health
Invoke-RestMethod https://investor-intelligence-v21-owner-line.moon951753.workers.dev/health
```

Never paste Cloudflare, LINE, HMAC, Gateway or brokerage secrets into issues, logs, screenshots or chat.

## 隱私與安全邊界｜Privacy and safety boundaries

```text
LINE_DATA_SCOPE=PUBLIC_ONLY
LINE_IBKR_BRIDGE=FORBIDDEN
LINE_PORTFOLIO_TOOLS=FORBIDDEN
LINE_PRIVATE_SYNC=FORBIDDEN
LINE_OWNER_DATA=FORBIDDEN
FREE_ONLY_MODE=FAIL_CLOSED
AUTOMATIC_TRADING=FORBIDDEN
```

- Shared LINE cannot access IBKR, brokerage accounts, holdings, quantities, costs, P&L, owner watchlists or local private reports.
- Public, tenant-private and ephemeral-security state use separated bindings.
- Secrets remain outside tracked source and are not included in releases.
- Route expiry, model mismatch, failed heartbeat or failed health verification makes the local model unavailable instead of serving stale routing state.
- The system does not place orders and has no brokerage-write path.

## 文件｜Documentation

- [繁體中文完整使用說明](README.zh-TW.md)
- [R75 FREE_RELAY architecture](docs/V213_FREE_WORKERS_RELAY.md)
- [Current release truth](docs/FINAL_RELEASE.md)
- [Current implementation status](IMPLEMENTATION_STATUS.md)
- [Documentation index](docs/README.md)
- [Final delivery and production evidence](state/FINAL_DELIVERY_REPORT_R75_FREE_RELAY.md)
- [Detailed project status](state/STATUS.md)

## 歷史版本｜Historical releases

Older v2.0.0, v2.1.0 and R70 documents/releases remain historical records. They are not the current installation or production authority. The authoritative current release is the immutable R75 FREE_RELAY tag shown above.

---

## English summary

Investor Intelligence v2.1.3 R75 FREE_RELAY is the current verified production release. It uses the existing `workers.dev` endpoint as a stable front door and an authenticated expiring lease to an ephemeral TryCloudflare tunnel. The exact local model is `qwen38-q6`; no custom domain or paid service is required. The authoritative Windows CI run, post-download verification, real Worker deployment, real task-trigger test, complete heartbeat cycle and end-to-end model smoke test all passed. Serenity/publication semantics remain protected and unchanged by the transport integration.