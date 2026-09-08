# Investor Intelligence v2.1.3 R75

[繁體中文](README.zh-TW.md) · [Latest immutable release](https://github.com/always7895/investor-intelligence/releases/latest) · [Bilingual status](docs/CURRENT_STATUS_BILINGUAL.md)

Privacy-first, zero-cost public-market research. / 隱私優先、零付費公開市場研究。 Research software—not personalized investment advice, trading instructions or guaranteed returns.

## Development audit / 開發中稽核

[Stock/news/options source coverage and collector](docs/PUBLIC_SOURCE_COVERAGE.md) · [Options source review and import usage](docs/OPTIONS_SOURCE_REVIEW.md) · [Candidate PR #37](https://github.com/always7895/investor-intelligence/pull/37) · [Remote quote-provenance blocker #38](https://github.com/always7895/investor-intelligence/issues/38).

The candidate adds an opt-in local collector for Fed/SEC/ECB announcements and TWSE/TPEx equity EOD observations, plus local-export adapters for TAIFEX options and Alpaca indicative quotes, alongside existing Yahoo/local IBKR paths. All five endpoints have local direct-CLI live-read evidence on the supported hash-verified CPython3.12.10 plus locked certifi trust bundle. Earlier TLS failures are preserved, not relabelled; arbitrary system Python versions are not qualified. GitHub Windows acceptance still awaits a registered runner. These are **not live public LINE feeds**: redistribution review and source-bound live acceptance remain pending. Daily/indicative data cannot be presented as executable NBBO. Current audit findings supersede historical zero-defect counts; the released executable below is unchanged.

Current-release hardening routes new candidates through receipt-bound ZIP/extracted-install verification, not the legacy generic packager. Live Q&A qualification now requires timezone-aware start/completion timestamps within 24 hours; old receipts remain historical. Release is still blocked by missing Windows runner acceptance and fresh exact-Q6 proof (the observed local endpoint advertises Q5); no model/preset was changed.

## Delivered functionality / 已完成的功能

- Interactive and scheduled Top20 share **20 complete seven-field bilingual cards**: four carousels of five companies. `Top20 文字` provides complete company-grouped text, not a truncated table.
- Seven fields: ticker, historical 2Y annualized return, historical 6M return, industry, profit summary, current orders and future order outlook. Missing evidence stays unavailable; no invented order totals or LIMITED upgrades.
- Strict Q6 alias/canonical identity, bounded requests/backpressure, and shared no-write readiness. The existing Router remains `127.0.0.1:8080`, one model only; no preset or persistent sampling change.
- Sealed, digest-bound publication with pointer-last/object readback, corrupt-replay rejection, durable failure journals, rollback and finalize. Three obsolete unsealed write routes return HTTP410.
- Windows refresh tasks at **07:20/20:20 Asia/Taipei** explicitly publish newly generated sealed bundles. LINE Worker cron remains **08:00/21:00**. Interactive owner logon, IgnoreNew,100-minute timeout and retries are verified; keep the PC/network available and the owner logged in. Locked desktop is supported; logged-out operation is not promised.

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
