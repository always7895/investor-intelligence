# Investor Intelligence v2.1.3 R75 FREE_RELAY

[繁體中文](README.zh-TW.md) · [Immutable release](https://github.com/always7895/investor-intelligence/releases/tag/v2.1.3-R75-qa-readiness-2cf585d-33960014393) · [Delivery evidence](state/FINAL_DELIVERY_REPORT_R75_FREE_RELAY.md)

Privacy-first, zero-cost public-market research. / 隱私優先、零付費公開市場研究。 Research software only—not personalized investment advice, trading instructions or guaranteed returns.

## Known issue / 已知問題 — seven-field LINE consistency

The published release below qualifies **Q&A/readiness only**, not every product feature. Interactive `Top20` and legacy `/v21/admin/test-push` still use five columns in that ZIP; v213 scheduled broadcast uses seven. The seven-field route fix has passed local TypeScript and 133 Worker tests, but its isolated workers.dev qualification is blocked by HTTP404. It is **not released, installed or deployed**. No actual-user LINE seven-field acceptance is claimed.

下列正式修正版只驗收 Q&A／readiness。互動 Top20 與舊 test-push 仍是五欄；排程已有七欄。新修正尚未發布／安裝／部署。七欄定義與中英狀態：[bilingual status](docs/CURRENT_STATUS_BILINGUAL.md)。

## Current verified release — 2026-09-05

| Field | Verified value |
|---|---|
| Executable source | `2cf585d317a4ba3ca784641b1515bfa862fb38bd` |
| Windows self-hosted CI | `33960014393` — PASS |
| Immutable tag | `v2.1.3-R75-qa-readiness-2cf585d-33960014393` |
| ZIP SHA256 | `da39073a3a0e8367ba7eb06b019a27e0e81bc133acac1fbfc57fcd91fa813e65` |
| Production Worker | `c3cb4024-48f0-403d-9dd2-714d544af024` — 100% |
| Exact model | `qwen38-q6`, existing Router `127.0.0.1:8080`, `models-max=1` |
| Scoped Q&A/readiness defects | P0/P1/P2 = **0/0/0**, supported by this release's evidence |

Earlier release/status documents are historical and do not override this table. The preceding provenance-fix release remains available; no old asset or tag was overwritten.

## Small, free architecture

```text
LINE -> privacy/admission gates -> deterministic ranking/report tools
                              -> bounded query-aware public Q&A
workers.dev -> signed short-lived route lease -> TryCloudflare -> Gateway
            -> existing llama.cpp -> exact qwen38-q6
```

- No custom domain, paid API, second model or paid fallback.
- Ticker prompts contain only the selected ticker's public evidence. Generic prompts are concise; methodology uses fixed context. Ranking stays deterministic.
- Only authenticated compact Q&A/smoke requests set `enable_thinking=false`. The user's Router preset is unchanged. Legacy model requests do not inherit this override.
- Fixed-marker smoke never loads the full Top20 context. Healthy Gateway/model inventory alone is not a Q&A PASS.
- One shared readiness gate verifies exact active/uploaded version, 100% traffic, parser/schema, publication contract and compact policy. Three consecutive no-write proofs are required. Unknown schema/validation errors fail immediately; no TOP20_INVALID retry or fixed propagation sleep.

## Measured latency

Real isolated workers.dev/Gateway/Q6, **synthetic public fixtures**, complete answers:

| Case | Cache cold / warm | Prompt tokens | Output cold / warm |
|---|---|---|---|
| Smoke | 2.660 / 2.127s | 24 | 11 / 11 |
| General | 5.733 / 4.627s | 242 | 39 / 37 |
| Ticker | 3.737 / 2.985s | 316 | 26 / 23 |
| Methodology | 4.362 / 4.115s | 254 | 29 / 32 |
| Evidence | 4.999 / 4.273s | 303 | 36 / 34 |

Cold means prompt cache disabled, not a model reload. Production fixed-marker smoke independently passed at **2.902 / 2.647s**. Real isolated seven-second reference/waitUntil completion passed with synthetic LINE transport; no real-user LINE message was sent.

## Verification and unchanged boundaries

- Python **565 tests, 2 skipped**; Worker **22 files / 131 tests**; typecheck, security, PS5.1/7: PASS.
- Final-ZIP extraction, isolated runtime installation, independent download/CRC/MANIFEST/SHA256SUMS/path/duplicate/symlink/PE/receipt verification: PASS.
- Original sealed bundle passed historical-clock offline transaction tests and still fails current-time freshness when stale. Its bytes and Production pointer were not changed.
- Serenity scores/weights, publication contract, LIMITED/EVIDENCE_QUALIFIED/HIGH rules, optional BLS, claim-level independence, LINE privacy and IBKR separation remain unchanged.
- `qa.ts` blob remains `94184bc8937b413eb327b3d773926db00e22b3b9`.
- `production_mutation_by_ci=false`. Separately authorized operator actions deployed code, replaced the relay bridge and repointed its at-logon task. **No activation resubmission, snapshot change, 08:00/21:00 schedule change or LINE send.** This release does not assert freshness of the retained Production snapshot.

## Install / run

Download the ZIP and checksum from the release above, verify SHA256, extract, then run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-v213-source-diverse-runtime.ps1
& "$env:LOCALAPPDATA\InvestorIntelligence\V213Runtime\InvestorIntelligence.exe"
```

On the verified user machine it is already installed and launched, with desktop shortcut **Investor Intelligence R75**. The existing at-logon FREE_RELAY task reconnects from this stable runtime. The 08:00/21:00 tasks and Worker cron expressions are unchanged.

Keep the existing Router running. Never paste LINE/Cloudflare/Gateway credentials, private financial data or `.env` contents into issues or logs. See [FREE_RELAY operations](docs/V213_FREE_WORKERS_RELAY.md).
