# R75 delivery evidence / 交付證據

## Final immutable delivery / 最終不可變交付

[Release b5baae9 /33992169731](https://github.com/always7895/investor-intelligence/releases/tag/v2.1.3-R75-seven-field-b5baae9-33992169731) is published and installed. Source b5baae936dd3d422583decf9268910ed5783e4d5; ZIP SHA320dfb799b34d1220138f67780d2f3fd0004781fcdeaf93e8d543169386f2e69. Windows CI, Python585/2 skipped,142 Worker tests, PS5.1/7, actual dependency-preserving reinstall and published download verification PASS.

發布後 `gh release verify-asset` 密碼學 release-asset attestation PASS；SLSA workflow build attestation 仍404，兩者不混用。16個發布資產已鎖定；後續 receipt 上傳被422拒絕，保留本機，未聲稱已上傳。Release notes explain post-publication evidence without altering immutable bytes or pre-publication receipts.

PR34 merged; bilingual About/homepage/docs/release synchronized. P0/P1/P2=0/0/1; issue35 covers the unowned missing-target legacy task, issue33 retains normal-delivery/device observation. No extra real LINE test or subsequent activation replay.

## 2026-09-06 — seven-field / sealed-refresh cutover

Current downloadable identity: [latest release and its own refs/receipts](https://github.com/always7895/investor-intelligence/releases/latest). [Bilingual scope](../docs/CURRENT_STATUS_BILINGUAL.md).

- Functional baseline bfb4e3db75f7bb00f8dd693aca2ba178ba6f5879 / Windows33989794415 PASS; downloaded ZIP independently verified and installed. Subsequent packaging-only identity belongs to its own receipts.
- Authorized Worker54442104-0e1f-419c-84a9-b7c4ca63ee3f at100%; Q6 exact alias/canonical mapping, preset unchanged, fixed-marker2231/2097ms PASS. No extra real LINE send.
- Actual installed full sealed refresh PASS, run20260905T205013Z-749cc4fbd2cd / transaction124ed6f6603d68ea05f81e82517ae320; FINALIZED,20 LIMITED/0 qualified. Independent remote readback found13 required objects and the actual report locally produced4 Flex messages/20 cards/2 complete texts.
- 07:20/20:20 canonical refresh tasks with explicit publication independently read back; Interactive owner/IgnoreNew/100-minute limit/retries.08:00/21:00 Worker cron unchanged. 歸屬未明的舊 InvestorDailyBriefing 保留，已追蹤 P0/P1/P2=0/0/1。
- CI production_mutation_by_ci=false; separate currently authorized operator DID change local runtime, relay, Worker, fresh snapshots and refresh definitions. Normal scheduled LINE delivery/device rendering remains unobserved. Artifact attestation is absent; broad Q6 text review remains incomplete.
- 初次 native task StopExisting 失敗、operator LASTEXITCODE 失敗、依賴尚未準備時的 Node 失敗皆保留；最終 native readback 與重新準備依賴後的 full Worker gates PASS，不將失敗改寫為成功。

## Historical Q&A/readiness delivery — 2026-09-05

This report supersedes older blanket completion narratives. Its scope is the two specified Q&A/readiness defects; it does not assert current market-data freshness or real-user LINE delivery.

## Identity

- Executable commit: `2cf585d317a4ba3ca784641b1515bfa862fb38bd`
- Authoritative self-hosted Windows CI: `33960014393` — SUCCESS
- Immutable release: [v2.1.3-R75-qa-readiness-2cf585d-33960014393](https://github.com/always7895/investor-intelligence/releases/tag/v2.1.3-R75-qa-readiness-2cf585d-33960014393)
- ZIP SHA256: `da39073a3a0e8367ba7eb06b019a27e0e81bc133acac1fbfc57fcd91fa813e65`
- Active Production Worker: `c3cb4024-48f0-403d-9dd2-714d544af024`,100%; previous `80f6565b-3ab6-45f6-8d25-21a3a54a1bca`.
- Installed/started: `%LOCALAPPDATA%\InvestorIntelligence\V213Runtime`; desktop shortcut **Investor Intelligence R75**. Launcher window confirms the source/run revision.

## What changed / simplified

Query-aware compact public context and an authenticated, request-only non-thinking profile replace long context for v213 general Q&A. Ticker context is selected, methodology fixed and ranking remains deterministic. Smoke has a fixed minimal input and requires a completed exact-model marker response. User preset is unchanged.

There is one readiness owner (sync client), not repeated core/client waiting. Product and isolated live test use the same PowerShell gate. The obsolete standalone benchmark was removed. Current documentation references one authoritative release table rather than duplicating stale metadata.

qa.ts remains `94184bc8937b413eb327b3d773926db00e22b3b9`; scoring/weights, source thresholds, claim independence, publication modes, optional BLS, freshness, LINE privacy and IBKR separation remain unchanged.

## Actual model evidence

Real isolated workers.dev -> route DO -> short-lived tunnel -> Gateway -> existing qwen38-q6. Public fixtures are synthetic. Cold means prompt cache disabled, not model reload. All answers finish with `stop`.

| Case | Cold/warm seconds | Prompt tokens | Generated cold/warm |
|---|---|---|---|
| Fixed smoke | 2.660/2.127 | 24 | 11/11 |
| General | 5.733/4.627 | 242 | 39/37 |
| Ticker | 3.737/2.985 | 316 | 26/23 |
| Methodology | 4.362/4.115 | 254 | 29/32 |
| Evidence | 4.999/4.273 | 303 | 36/34 |

The real isolated seven-second reference/waitUntil branch completed and its result was retrieved. It used an explicit test-only8s floor to force the reference branch and mocked LINE transport. Temporary Workers/KV/DO/tunnels were deleted. Source-bound QA-Live-Receipt contains prefill/generation timings and runtime hashes.

The previously failed inherited-high-reasoning measurements remain historical evidence; they were not reclassified as PASS. User explicitly authorized request-level `enable_thinking=false`; original preset SHA remains `b3815956d3fc47bc81db3ec51c71c5460f8aa8e2817b2a12e9815aeac89ae459`. Router models-max1 and only qwen38-q6 loaded.

## Regression / artifact gates

- Python565 tests,2 skipped; Worker22 files/131 tests; TypeScript, security, PS5.1/7: PASS.
- Stale lease, replay, exact-model mismatch, old parser/version, readiness timeout/arbitrary-error fail-closed tests: PASS.
- Final extracted ZIP Worker tests and isolated runtime installer: PASS in CI.
- Independent downloaded ZIP CRC, MANIFEST, SHA256SUMS, path safety, duplicates, symlinks, PE/release markers, contract and receipts: PASS.
- Downloaded artifact's complete Worker suite: PASS.
- Original bundle SHA `f51a99ac709da3cf3fce6c2af0b4f40a967443d5bae41ba3b963a0d716500bad`: unchanged historical-clock offline commit/readback/replay/corruption rejection/rollback/finalize PASS; present-time STALE rejection retained. Historical receipt cannot satisfy the live activation preflight gate.
- GitHub immutable-release attestation: `gh release verify` PASS.

## Authorized Production/local cutover

After acceptance, the operator installed the downloaded package, created a healthy new bridge before stopping the old bridge, deployed code only, verified exact100% active/uploaded version and three no-write parser/contract/policy readiness proofs, then performed two Production fixed-marker smokes: **2.902/2.647s PASS**.

- `production_mutation_by_ci=false`.
- Separately authorized operator mutations: Worker code, relay lease/bridge and its at-logon reconnect-task path.
- No sealed-bundle submission, snapshot write, LINE send,08:00/21:00 task change or Worker cron change.
- Production pointer was compared before/after and unchanged; readback digest `c1ebf710b7939b2029bd275d8ac8d2c1a6a07aa262bf01c3ec035479f34c6a65`.
- Existing activation remains run `20260905T002320Z-6f420ca8d4e8`, transaction `5f2dea606be8095a688e06605f241531`. This hotfix did not repeat activation or promote any LIMITED row.

## Final scope and files

Q&A/readiness P0/P1/P2=**0/0/0** on the attached evidence. Further Production deployment for this hotfix: **not required; completed**. Actual-user LINE delivery, fresh Production data activation and all possible future edge/availability scenarios are not claimed tested.

Evidence is attached to the immutable release and stored locally under `artifacts/r75-qa-hotfix-33960014393/` (outside the repository): Windows/QA-Live/Deployment/Delivery/Independent-Verification receipts, Post-Download-Verification, Downloaded-Historical-Exact-Bundle, Downloaded-Worker-Tests, Authorized-Code-Only-Cutover and Local-Installation-Receipt.
