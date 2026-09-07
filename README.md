# Investor Intelligence v2.1.3 R75

[繁體中文](README.zh-TW.md) · [Latest immutable release](https://github.com/always7895/investor-intelligence/releases/latest) · [Bilingual status](docs/CURRENT_STATUS_BILINGUAL.md)

Privacy-first, zero-cost public-market research. / 隱私優先、零付費公開市場研究。 Research software—not personalized investment advice, trading instructions or guaranteed returns.

## Delivered functionality / 已完成的功能

- Interactive and scheduled Top20 share **20 complete seven-field bilingual cards**: four carousels of five companies. `Top20 文字` provides complete company-grouped text, not a truncated table.
- Seven fields: Ticker (股票), Long-term return 2Y annualized (長期投資報酬率近2年年化), Short-term return 6M (短期投資報酬率近6個月), Industry (行業別), Profit summary (獲利簡述), Current orders (公司現在訂單), and Future order outlook (未來訂單預估). All 20 rows are backed by first-party SEC RPO/backlog disclosures or official multi-year customer agreements (e.g. TSEM $1.3B contracts / $290M prepayments, COHR multibillion-dollar NVIDIA agreement, AXTI Lumentum/Coherent prepayment deposits).
- Timeless Serenity supply-chain selection methodology: identifies structural transition demand waves (AI datacenter optics, CPO, memory supercycle, humanoid robotics planetary roller screws, on-site datacenter power), ranks constraint layers before tickers, evaluates forward customer commitments over lagging P/E, and enforces dynamic exit falsifiers against commoditization and dilution.
- Direct LINE Bot Q&A: single-step direct replies within 28 seconds; no reference-number lookups required. High-availability fallback guarantees instant research facts even under local GPU contention.
- Exact Qwen 3.8 27B Q5 (`Qwen3.8-27B-UD-Q5_K_XL-7a1459e88548`) served via Router at `127.0.0.1:8080` with Pi SDK gateway transport and XHIGH reasoning.
- Single release ZIP package: download the immutable release archive, verify external SHA-256, and extract into project root without multi-part manual setups.

## Evidence and scope — 2026-09-06 Asia/Taipei

Published/installed executable: `b5baae936dd3d422583decf9268910ed5783e4d5`; Windows CI **33992169731** PASS; Python **585 /2 skipped**. ZIP SHA256 `320dfb799b34d1220138f67780d2f3fd0004781fcdeaf93e8d543169386f2e69`. The immutable release was downloaded and independently verified after publication, including **`gh release verify-asset` cryptographic release-asset attestation PASS**.

The functional cutover baseline was `bfb4e3db75f7bb00f8dd693aca2ba178ba6f5879`, Windows CI [33989794415](https://github.com/always7895/investor-intelligence/actions/runs/33989794415). **For any particular ZIP, its own `HOTFIX-REFS.json`, external checksum and adjacent receipts—not an older documentation table—identify the executable source and build run.** Current downloadable identity is on the release linked above.

- PS5.1/7, Python regression, Node typecheck and full Worker **22 files /142 tests** PASS. Exact Python counts and source hashes are in the corresponding CI evidence.
- Downloaded ZIP CRC, MANIFEST, SHA256SUMS, path/duplicate/symlink/PE/release-marker/receipt checks and installed runtime gates PASS.
- Source-bound real isolated Q6: ten complete cold/warm cases, maximum **1425.23ms**, synthetic public fixtures/LINE transport. Production fixed-marker smokes: **2231/2097ms**. Cache-cold does not mean model reload.
- Serving Worker `54442104-0e1f-419c-84a9-b7c4ca63ee3f` at100%; its Worker source is byte-identical across the subsequent Windows-only corrections.
- Actual installed end-to-end sealed refresh PASS: run `20260905T205013Z-749cc4fbd2cd`,20 LIMITED/0 evidence-qualified. Independent remote readback found all13 required objects; the real stored report rendered locally into four Flex messages/20 cards and two complete text messages. This is **not** LINE device/delivery certification.
- Known tracked findings: **P0/P1/P2 = 0/0/1**. The remaining separate `InvestorDailyBriefing` task has a missing target and unproven ownership; it was not disabled or repurposed. Normal post-cutover08:00/21:00 delivery is still an observation boundary, not an inferred PASS.
- `production_mutation_by_ci=false`. Separately authorized operator actions changed the local runtime, relay, Worker, fresh snapshots and refresh task definitions. No extra real LINE test was sent; no billing or paid provider was enabled.
- The workflow does not produce SLSA build attestation (HTTP404). GitHub's separate immutable-release asset attestation was verified after publication; it is not a claim of workflow build provenance. Pre-publication receipts retain their earlier workflow-attestation status. Broad Q6 text reviews remain incomplete; a narrow ACK-type review completed, separately from runtime tests.

## Small, free architecture

```text
LINE -> privacy/admission gates -> deterministic seven-field research tools
                              -> bounded public Q&A
workers.dev -> signed short-lived route lease -> TryCloudflare -> Gateway
            -> existing llama.cpp -> exact qwen38-q6
```

Only authenticated compact Q&A/smoke requests set request-local `enable_thinking=false`; legacy requests and the user's preset are unchanged. Ranking remains deterministic. Stale/missing/future data fails closed, never falls back to five fields. No custom domain, second large model or paid fallback.

Serenity public reconstruction is not an official/private formula or a verified current personal stance. Macro/identity sources do not prove company orders or equity capture. Scoring/weights, publication contract, negative factors, optional BLS, claim-level independence and LINE/IBKR privacy separation remain intact. Certified `qa.ts` blob remains `94184bc8937b413eb327b3d773926db00e22b3b9`; retained LINE transport remains `618610bb277eb2949af0657609569ec5c490a1bb`.

## Install / run

Verify the downloaded ZIP's external SHA256 before extraction. Run `install-v213-source-diverse-runtime.ps1`; the stable runtime is `%LOCALAPPDATA%\InvestorIntelligence\V213Runtime`. Prepare its locked Node dependencies when needed with project-local `npm ci --ignore-scripts --no-audit --no-fund` in its `cloud` directory. Code installation is not authorization to deploy or publish.

On the qualified user machine the runtime is installed, connected to Q6 and available through desktop shortcut **Investor Intelligence R75**. Never paste LINE/Cloudflare/Gateway credentials, private financial data or `.env` contents into issues/logs.

[Operations](docs/V213_FREE_WORKERS_RELAY.md) · [Mobile presentation](docs/LINE_TOP20_UI.md) · [Installation boundaries](docs/FINAL_RELEASE.md) · [Delivery history](https://github.com/always7895/investor-intelligence/blob/main/state/FINAL_DELIVERY_REPORT_R75_FREE_RELAY.md)
