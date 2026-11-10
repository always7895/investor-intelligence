# Changelog / 更新紀錄

Changes here describe source history, not installed, downloadable or Production equivalence. [STATUS](state/STATUS.md) is the current acceptance ledger.

## v3.4.0 — Unreleased (Stage 2 integrated source candidate)

- **Public options:** non-US/SIVE eligible covered calls (CC), cash-secured puts (CSP) and collars with model-based price limits on wide quotes, exact cent ticks and dated quote/HV bounds; unavailable legs remain refused rather than repriced.
- **Monthly choice:** nearest standard monthly expiry without a minimum DTE; no annualized-yield floor suppresses an otherwise qualified CC/CSP recommendation.
- **Ranking and free KV:** publish ranking on confirmed change or a six-hour heartbeat; preserve retry-inclusive independent 400-ranking/600-other-product ledgers, with quotes/options/coverage on the unchanged two-hour market cadence and verified last-good always served.
- **Failure independence:** healthy market/price/identity products continue publishing when the guidance machine fails, without resetting ranking clocks or changing source observation times.
- **Corporate actions:** validate chronology and calculate point-in-time eligibility; historical runs omit future-source-dated evidence, and unauthorized entitlements or prices are still withheld.
- **Documents:** research and operational guidance rewritten and indexed, with status/acceptance boundaries separated from current deployment.

This entry describes offline source integration only: **NOT released, installed, deployed, pushed or Production-approved**. Final integrated review, manifest/catalog alignment, release assets, and current-session operator authorization remain outstanding.

### Documentation changes included in v3.4.0

- Current agent routing, independent review and safety boundaries clarified in source instructions and separately proposed installed control-plane files.
- Owner decisions since November 8 audited; Stage 1D, R2B ranking cadence/freshness, screener calibration and remaining release work made explicit.
- Existing safety and research contracts linked to immutable evidence; workspace minimization is a post-release plan, not a deletion.
- This documentation subset makes no Worker, KV, broker, scheduled task, installed application, release asset or Production mutation.

## v3.3.0 — historical source release

- See the immutable Git history and release receipts for source changes and acceptance in their original contexts.
- The 2026-11-09 read-only release-lane check found no attached GitHub assets for v3.3.0. Treat ZIP/download claims as unverified until release attachments, digests, manifest and post-download evidence pass.
- Old authorizations and old deployment versions do not authorize another all-friends rollout.

Do not use this page as a substitute for fixed-source tests, reviewer acceptance, signed release metadata or current operator permission.
