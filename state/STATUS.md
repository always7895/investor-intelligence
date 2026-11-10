# Current source and release acceptance / 目前狀態

**As of 2026-11-10 (Asia/Taipei).** Source HEAD: `integ/r3` (Stage 2 R2 fixes on reviewed `963fdb2`; immutable final SHA is recorded in `_workspace/integ-r3/REPORT-STAGE2-R2.txt`). Source acceptance, installed runtime, historical release and Production observations are separate. No fresh Production readback, deployment permission or independent Stage 2 acceptance is implied.

## Current gates

- **Options Stage 1G: DUAL-ACCEPTED for integration only.** Accepted source `76b9c40` (independent REVIEW-INTEG-R2-STAGE1G verdict ACCEPT and master ruling). Frozen saved/regular M4 option replays: 291 / 283 symbols with an eligible standard-monthly strategy; SIVE.ST retains CC, CSP and collar. Nearest standard monthly selection has no minimum DTE, and eligible CC/CSP have no annualized-yield floor. Quote-side limits remain on the Stage 1C rule; HISTORICAL_VOL model prices are bounded to executable cent ticks. Stage 2 integrated revalidation and independent acceptance remain mandatory.
- **R2B ranking: Round 5 DUAL-ACCEPTED for integration only (MASTER-R2B-ROUND5-ACCEPT).** Accepted source `8e88181` includes 2 × 720-hour offline machine cases, last-good serving, failure-safe independent product refresh, point-in-time corporate-action selection and two independent retry-inclusive free-KV ledgers (ranking 400 / market 600 out of 1,000). Ranking writes only on confirmed order change or at most a six-hour heartbeat; quotes/options/coverage refresh on a two-hour cadence. Simulations are not live KV evidence; the full unittest discover can retain classified baseline/environment failures.
- **Docs lane R5: ACCEPT as a documentation input, not a release.** Documentation rewrite and official-guidance references were integrated from `docs-min-r3/MD-OPTIMIZE.patch`; source instructions and research history retain their privacy/release boundaries. No installed-root mutation, release asset or cleanup is authorized.
- **Serenity/Leopold screener: UNVERIFIED.** Fourteen exploratory rules, RULES_KEPT=0; weight 0 for all until broad point-in-time SEC filings (>=3 years, including delisted issuers), >=5 years of prices, and independent out-of-sample tests justify adoption. Posts and 13F are dated leads/validation, never automatic source-based ranks.
- **Top20 numeric estimates:** show evidence-labelled modelling basis for 6-month and one-year fields or an explicit verification failure; no blank-as-zero, fabricated growth or unsupported filing attribution. MOD crossing-distribution return remains withheld until entitlement-adjusted verified basis; LITE/MRVL pending deal and MRVL independent score remain gated.
- **Acceptance rule:** IMPLEMENTED_UNVERIFIED until writer and independent reviewer accept the SAME fixed snapshot; known P0 must be zero. publication_eligible=false. Offline checks, a simulated answer, source tag or package metadata cannot replace external acceptance.

## Live and installed boundary

- Historical source v3.3.0 and installed/Production are different. The master's 2026-11-08 **read-only /health readback** (MASTER-LIVE-ACCESS-READBACK-CLAUDECODE-a43bef58-20261108.txt) observed `all_friends`, correcting an older STATUS assertion of `owner_only`. **Actual current live mode remains UNKNOWN here**, without a fresh authorized readback; neither historical observation grants rollout permission.
- Combined all-friends rollout was **PAUSED** by operator on 2026-11-08. Candidate release requires independent review, master GO/NO-GO, and **new explicit current-session authorization** naming the final snapshot before any Worker/KV, schedule, broker, real LINE or release operation.
- The release-r2 report found no downloadable v3.3.0 GitHub assets; the installed tree still differs from integration and lacks required modules/catalog alignment. Coordinator closure, rollback, release ZIP/SHA-256 and source-to-installed parity remain unaccepted.

## Historical v3.3.0 source acceptance

- Historical dual-accepted source `8ff4b07`: H5 `rel1-g2` had 346 modules, 326 PASS, 20 pre-ruled BLOCKED, 0 FAIL (PASS_AS_RULED). This does not prove current installed bytes or attached release assets.

## Dated open follow-ups

- **AGLT:** 365-day listed-history admission gate; a recent listing does not confer immediate rank eligibility.
- **Q3 2026 Aschenbrenner 13F:** recheck the primary filing and reporting period **after 2026-11-16**; an earlier report is not a current holding.
- **LITE/MRVL:** `review_by=2026-12-07`; keep deal state pending until new primary evidence.
- **MOD/THRM:** withhold distribution-crossing return until entitlement-adjusted prices are verified.

## Ordered next actions (no automatic execution authority)

1. Integration executor: complete Stage 2 committed-tree replay, Worker/Python gates, full discover against BOTH accepted input heads, coordinator tests and cross-lane quota/seal checks; record any baseline failures without calling them PASS.
2. Independent reviewer: assess the identical `integ/r3` Stage 2 source commit and R2B round-five evidence, including isolated machine failures and no-product-freeze assurances; master records explicit ACCEPT/NO-GO.
3. Master: reconcile final version/manifest/SHA256SUMS, Worker catalog and installation ownership against one frozen source candidate; no source merge or offline gate grants Production authorization.
4. Reviewer/master: dry-run qualified sealed producer plus Worker compatibility, source catalog/installation manifest closure, rollback rehearsal, immutable release package and checksum; master GO/NO-GO.
5. Operator: new exact release/rollout and cleanup authorization; master executes only permitted phases and observes fresh Production readback. Only accepted post-deploy receipts can set FINAL_RELEASE_COMPLETE=true.
6. Only after final release: archive evidence and backups, then separately authorized cleanup of confirmed-dead development files and runner.

## Dated references

Workspace review receipts: review-r2/REVIEW-STAGE2-INTEGRATED.md (963fdb2: ACCEPT_WITH_FIXES), review-r2/REVIEW-INTEG-R2-STAGE1G.md, review-r2/REVIEW-R2B-ROUND5.md, release-r2/REPORT.txt. R2 fixes require re-review at the new immutable HEAD; the earlier review does not accept that new snapshot. These paths are outside the Git checkout and represent dated independent assessments, not current release approvals. Historical state remains in Git, e.g. git show 38860e7:state/STATUS.md.

Safety: public-only LINE, no private IBKR-to-Worker/LINE/KV, no paid fallback, no unauthorized cloud/broker operations, no secret or identifying value in logs, no forced push, no second large local model server.
