# R75 takeover status

## Milestone M1 — shared publication contract (2026-09-04)

- Baseline HEAD: `80c45c4b242dba99560ba99151785812520a09dd`
- Branch: `pi/r75-takeover-20260904-1343`
- Source fetch: completed before edits; Production mutation: **none**.
- Implemented one versioned contract at `config/v213-r75-publication-mode-v1.json`, canonical SHA-256, and common all-LIMITED/mixed fixtures.
- Python, Windows PowerShell 5.1, PowerShell 7, and TypeScript consume the same contract/fixtures.
- Optional BLS is non-required; core SEC/Nasdaq/World Bank/ECB families remain required.
- Worker activation ingestion validates publication modes and returns the contract ID/hash.
- PowerShell `-PreflightOnly` validates the sealed digest-bound bundle, emits no mutation, and pins its SHA into the activation core to block loose-cache/TOCTOU drift.

### Validation

- `python scripts/v213_r75_activation_preflight.py --self-test` — PASS.
- `python scripts/v213_r75_activation_preflight.py --fixture tests/fixtures/v213-r75-publication-mode/mixed.json` — PASS (10 strict, 10 LIMITED, 1 HIGH, BLS absent).
- Windows PowerShell 5.1 `scripts/test_v213_r75_publication_contract.ps1` — PASS; contract SHA `9b96f2fd68318e6476dc00d0d003162c0343d2aece5ef25f522fe7c33dca7bfd`.
- PowerShell 7 same contract test — PASS; same SHA.
- Windows PowerShell 5.1 and PowerShell 7 activation wrapper `-SelfTest` — PASS, no network/mutation.
- `cloud: npm run typecheck` — PASS.
- `cloud: npm test -- --run test/v213-activation.test.ts test/v213-publication-mode.test.ts` — PASS (2 files, 7 tests).

### Open defect counts

- P0: **4** (`P0-04` remaining negative matrix/real bundle; `P0-05` gateway process path; `P0-06` authoritative Windows runner Python; `P0-07` tunnel policy).
- P1: **10**.
- P2: **7** (`P2-08` temporary workflow cleanup completed at baseline; other items remain or require release evidence).

### Next action

Complete M2 fail-closed fixture matrix and full Worker suite, then M3 gateway process/concurrency work.

## Milestone M2 — Worker and fail-closed fixture matrix (2026-09-04)

- Input HEAD: `3880309`.
- Worker all-LIMITED and mixed (10/10) modes PASS with BLS absent; strict HIGH eligibility is accepted only with qualifying evidence/market state.
- Fail-closed coverage now includes LIMITED positive factor, HIGH eligibility, validated thesis, one provenance origin/domain, all four strict evidence metrics, count, order/rank, freshness, stale bundle, and digest defects.
- Negative LIMITED factor remains accepted (positive-only withholding semantics).
- `python scripts/v213_r75_activation_preflight.py --self-test` — PASS for the complete matrix.
- Windows PowerShell 5.1 and PowerShell 7 wrapper `-SelfTest` — PASS and execute the same Python/common-fixture matrix.
- `cloud: npm run typecheck` — PASS.
- `cloud: npm test` — PASS (18 files, 97 tests).
- External/Production mutation: **none**.

### Open defect counts

- P0: **3** (`P0-05`, `P0-06`, `P0-07`).
- P1: **10**.
- P2: **7**.

### Next action

M3: implement a direct Windows-safe Gateway launch contract, exact model pin, bounded generation admission, non-blocking health, and redacted bounded startup diagnostics.

## Milestone M3 — Windows-safe Gateway and exact-model admission (2026-09-04)

- Input HEAD: `0824532`.
- Gateway rejects request model substitution with HTTP 409 and always sends the environment-pinned exact model upstream.
- A bounded global generation semaphore rejects excess work with HTTP 429 and `Retry-After`; `/health` does not acquire a generation slot.
- PowerShell 5.1-compatible native argument quoting launches the real Gateway script from a path containing spaces, Unicode, and `(1)`.
- Startup failures include only bounded, secret-redacted stdout/stderr tails.
- Real HTTP process test verifies special-path startup, exact pinning, upstream model identity, concurrent backpressure, and health responsiveness.
- `python -m unittest tests.test_v213_local_llm_gateway tests.test_v213_r75_gateway_process -v` — PASS (6 tests).
- Gateway `--self-test` — PASS.
- Windows PowerShell 5.1 and PowerShell 7 bridge `-SelfTest` — PASS.
- External/Production mutation: **none**; existing llama.cpp Router configuration was not altered.

### Open defect counts

- P0: **2** (`P0-06`, `P0-07`).
- P1: **8** (`P1-02` and `P1-03` completed).
- P2: **7**.

### Next action

M4: enforce test-only Quick Tunnels, named-tunnel Production policy, truthful transient-DNS status, and blue/green cutover/rollback lifecycle tests.

## Milestone M4 — tunnel and bridge lifecycle (2026-09-04)

- Input HEAD: `9171405`.
- Quick Tunnel is explicitly `QuickTest`, marked test-only/non-Production, and requires three consecutive public health checks.
- Transient public health/DNS failures produce `PASS_WITH_TRANSIENT_DNS_FAILURES`, with counts persisted in bridge state; they cannot be reported as a plain PASS.
- Named tunnels require validated name, hostname, and config; Production activation rejects non-named tunnel state unless the operator supplies the explicit test-tunnel exception switch.
- Blue/green behavior starts and validates the new Gateway+tunnel before any old bridge is stopped; failure stops only the new bridge, staged promotion retains old until finalize, and finalize then stops old.
- Root and source-diverse launch aliases route through the same managed core and expose named-tunnel/finalize parameters.
- Windows PowerShell 5.1 and PowerShell 7 bridge lifecycle `-SelfTest` — PASS.
- Activation wrapper aliases remain byte-identical and both shell self-tests PASS.
- External/Production mutation: **none**; no tunnel was created or changed during tests.

### Open defect counts

- P0: **1** (`P0-06`: authoritative Windows Runner Python/release pipeline evidence).
- P1: **7** (`P1-06` completed).
- P2: **6** (`P2-04` completed).

### Next action

M5: snapshot readback/replay/rollback journal, operation locking, scheduler hardening, and atomic LINE dedupe.

## Milestone M5 — transaction, operation, schedule, and LINE safety (2026-09-04)

- Input HEAD: `fca4751`.
- Activation writes immutable objects without short TTL, reads every expected object back before pointer promotion, verifies again after promotion, and rejects missing/corrupt replay.
- Rollback journal moved from short-lived ephemeral KV to durable private operational storage; prepared-journal restart resumes safely, pointer-last remains enforced, rollback restores exact prior text, and finalize removes the journal.
- Public reads fail closed on dangling promoted pointers instead of silently using stale direct-key fallback.
- One cross-process/reentrant named mutex serializes activation, bridge, and scheduled refresh operations; contention fails closed.
- Scheduled refresh is data-only and records no-mutation receipts; Task Scheduler policy includes WakeToRun, network requirement, StartWhenAvailable missed-slot recovery, three retries, 100-minute timeout, and StopExisting timeout recovery.
- Scheduled LINE sends use a Durable Object pending/sent lease; concurrent test sends exactly once and reports the contender as in-progress.
- `cloud: npm run typecheck` — PASS.
- `cloud: npm test` — PASS (18 files, 101 tests).
- Activation core self-tests on Windows PowerShell 5.1 and PowerShell 7 — PASS.
- Operation-lock cross-process tests on both shells — PASS.
- Scheduler ValidateOnly and data-only fake-runtime execution on both shells — PASS.
- External/Production mutation: **none**; no scheduled task was registered and no LINE request was sent outside synthetic mocks.

### Open defect counts

- P0: **1** (`P0-06`).
- P1: **1** (`P1-01`: long-running cloud QA remains an availability limitation; no unsafe fallback).
- P2: **6**.

### Next action

M6 authoritative Windows no-mutation matrix and isolated transaction packaging tests, followed by M7 immutable artifact workflow and independent download verification.

## Milestone M6 — authoritative Windows validation implementation (2026-09-04)

- Input HEAD: `d28a96e`.
- Consolidated the superseded v2.1.3 delivery/hotfix workflows into one read-only, no-mutation R75 Windows workflow: `.github/workflows/v213-r75-release.yml`.
- The workflow bootstraps the repository-pinned CPython 3.12.10 runtime, installs the hash-locked wheel set, runs the complete Python and Worker suites, executes Windows PowerShell 5.1 and PowerShell 7 gates, and performs a real public-data refresh before requiring an actual 20/20 all-LIMITED sealed-bundle preflight.
- Isolated KV-compatible transaction gates cover object readback, pointer-last promotion, corrupt replay rejection, rollback, and finalize under both PowerShell hosts.
- Reconciled the reviewed source inventory from stale 99-source consumers to the current 101-source catalog and repaired import-order-dependent semantic-guard recursion exposed by complete test discovery.
- `pwsh -File scripts/ci_v213_r75_validate.ps1 -SkipLiveRefresh` — PASS locally using repository-pinned CPython 3.12.10.
- Complete Python suite — PASS (546 tests, 2 skipped).
- Worker typecheck and full Vitest — PASS (18 files, 101 tests).
- Workflow supply-chain, Actions storage, security, and canonical candidate gates — PASS.
- Windows PowerShell 5.1 and PowerShell 7 activation transaction/wrapper/operation-lock tests — PASS.
- External/Production mutation: **none**; the local acceptance intentionally skipped only the authoritative real-network refresh, which remains mandatory (not optional) in CI.

### Open defect counts

- P0: **1** (`P0-06`: successful current-HEAD self-hosted Windows run and downloadable release artifact evidence).
- P1: **1** (`P1-01`: long-running public-source availability remains fail-closed).
- P2: **2** (independent downloaded-artifact verification and final evidence reconciliation).

### Next action

Checkpoint and push M6, inspect the authoritative Windows run, then complete M7 immutable R75 packaging, artifact download, and independent verification.

## Deployment hotfix H1 — automated Production Named Tunnel path (2026-09-05)

- Verified release base: `536644d22ef3534be1c4b8a9e1ff969df4d580fa` (`v2.1.3-R75`).
- Branch: `pi/r75-named-tunnel-deployment-hotfix`.
- Implementation commit: `809cf7c`.
- Added a launcher one-time Named Tunnel setup entry requiring explicit name, hostname, and config.
- Setup validates cloudflared authentication, credential JSON/tunnel identity, ingress, named tunnel existence, and an exact DNS route ensure without printing or copying credentials.
- Launcher refresh/bridge/activation paths now pass `-TunnelMode Named`, `-NamedTunnelName`, `-NamedTunnelHostname`, and `-NamedTunnelConfig`; the normal path does not use `AllowTestTunnelException`.
- Named startup rewrites only a temporary runtime ingress config to the new blue/green gateway port, validates it, requires three consecutive public health-schema-v2 checks for the exact selected model, and retains the recorded bridge on failure.
- Added immutable deployment-hotfix packaging, receipts, independent ZIP verification, and conditional integration into the existing consolidated R75 workflow.
- Protected Serenity scoring, federation thresholds, publication contract, publication semantics, sealed bundle, and base R75 release evidence/package verifier files are unchanged from the verified release commit.

### Validation

- Windows PowerShell 5.1 `scripts/test_v213_named_tunnel.ps1` — PASS.
- PowerShell 7.6.5 same test — PASS.
- Special path with spaces, Unicode, and parentheses — PASS.
- Missing inputs, missing credential reference, and mismatched credential/tunnel identity fail closed.
- Gateway exact-pin/process regression — PASS (6 tests).
- Full no-mutation local matrix `scripts/ci_v213_r75_validate.ps1 -SkipLiveRefresh` — PASS: Python 550 tests (2 skipped), Worker typecheck PASS, Worker 18 files/101 tests PASS, both PowerShell hosts PASS.
- Launcher compile and packaged-root self-test — PASS.
- External/Production mutation: **none**. No Cloudflare route was changed, Worker deployed, Production KV/DO written, LINE sent, or schedule registered.

### Open defect counts

- P0: **1** (successful current-HEAD Windows workflow, immutable hotfix artifact download, and independent post-download receipt remain).
- P1: **0** for this deployment-integration scope.
- P2: **0** for this deployment-integration scope.

### CI iteration

- Windows run `33872737618` at `3033cf79e4f2214617d9abd1535868a76c0f0758` passed Python (550/2 skipped), Worker (18/101), and initial PowerShell gates, then failed closed because the Windows service account had no `python` command on PATH in the bridge child self-test.
- Fix commit `cd1b294` makes the child self-test honor the already verified repository-pinned `PROJECT_PYTHON`; both PowerShell hosts pass with that explicit path.
- Failed run caused no external or Production mutation and produced no artifact.
- Corrected Windows run `33872912456` at `dc6608d5aea31d69410f7ee80394022f2404447a` passed the complete hotfix validation (Python 550/2 skipped, Worker 18/101, PowerShell 5.1/7 named-tunnel gates) and then failed closed before packaging because the verified Python path was not exported between Actions steps.
- Fix commit `706884a` exports the already pinned Python path through `GITHUB_ENV` and retains a deterministic runner-temp fallback. No test, package, or Production mutation occurred after the packaging precondition failure.

## Deployment hotfix H2 — immutable artifact complete (2026-09-05)

- Artifact source commit: `87dde63a800d19f077a41826606f91bf21966873`.
- Authoritative self-hosted Windows workflow run: `33873094537` — **PASS**.
- Windows PowerShell 5.1 and PowerShell 7 named-tunnel gates — PASS.
- Python complete suite — PASS (550 tests, 2 skipped); Worker typecheck and full Vitest — PASS (18 files, 101 tests).
- Immutable artifact: `Investor-Intelligence-v2.1.3-R75-Named-Tunnel-Hotfix-87dde63a800d19f077a41826606f91bf21966873-33873094537.zip`.
- Downloaded artifact SHA-256: `7a222cb2eeebf03049804ba1118037b175d809a92df019df054bd7af530fe0a6`.
- Independent post-download verification — PASS: ZIP CRC, path safety, duplicates, symlinks, PE marker, MANIFEST, SHA256SUMS, publication-contract binding, immutable identity, and three receipts.
- Downloaded files and post-download receipt are stored outside Git at `artifacts/r75-named-tunnel-hotfix-33873094537/`.
- `production_mutation_by_ci=false`; no Cloudflare Production route change, Worker deploy, Production KV/DO write, LINE send, or schedule registration occurred.
- Known deployment-hotfix P0/P1/P2 counts: **0/0/0**.

### Next action

Stop. Production deployment and real Named Tunnel/DNS setup remain operator-controlled and were not executed in this session.

## Deployment hotfix H3 — zero-cost FREE_RELAY implementation candidate (2026-09-05)

- Base Named Tunnel hotfix commit: `43f3be048cedf228cfe9e8e31f7b9901895838be`.
- Branch: `pi/r75-free-workers-relay`.
- Keeps the existing `workers.dev` Worker as the stable public entrypoint; requires no custom domain and makes no stability claim for ephemeral `trycloudflare.com` hostnames.
- Added an authenticated route-registration endpoint and single Durable Object lease for exact model `qwen38-q6`, strict schema/URL/TTL/generation validation, three Worker-side public health-schema-v2 checks, serialized updates, replay/stale rejection, heartbeat expiry, and unavailable-on-expiry behavior.
- Worker Q&A dynamically resolves the current route and derives the same per-generation Gateway authentication secret without storing the plaintext secret in the route record.
- Added Windows PowerShell 5.1/7 FREE_RELAY bridge, heartbeat/reconnect monitor, optional at-logon task, blue/green pre-publication monitor gate, launcher defaults, activation preflight, no-mutation tests, immutable packaging, and independent verification.
- Named Tunnel remains supported as an optional future stable path. `AllowTestTunnelException` is not used by FREE_RELAY.
- Protected Serenity scoring, federation thresholds, publication contract/semantics, sealed bundles, and R75 release evidence rules remain unchanged from `536644d22ef3534be1c4b8a9e1ff969df4d580fa`.

### Local validation to this checkpoint

- Worker typecheck — PASS.
- Worker full suite before the final replay test — PASS (19 files, 109 tests); final full rerun pending checkpoint commit.
- FREE_RELAY host integration — PASS under Windows PowerShell 5.1.26100.9168 and PowerShell 7.6.5.
- Named Tunnel regression — PASS under both PowerShell hosts.
- Activation self-test — PASS under both PowerShell hosts.
- Launcher compile/self-test — PASS.
- External/Production mutation: **none**. No Worker deploy, Production KV/DO write, Cloudflare route change, LINE send, or task registration occurred.

### Open defect counts

- P0: **1** (authoritative Windows workflow, immutable artifact download, and independent post-download verification remain).
- P1: **0** for the FREE_RELAY scope.
- P2: **0** for the FREE_RELAY scope.

### Next action

Commit and push the implementation candidate, run the consolidated no-mutation Windows workflow, then independently download and verify the immutable FREE_RELAY artifact and receipts.

## Deployment hotfix H4 — immutable FREE_RELAY artifact complete (2026-09-05)

- Artifact source commit: `b99f371aa471d799f99fd773b37d61753ec6d32e`.
- Authoritative self-hosted Windows workflow run: `33877850106` — **PASS**.
- Windows PowerShell 5.1 and PowerShell 7 FREE_RELAY and Named Tunnel regression gates — PASS.
- Python complete suite — PASS (550 tests, 2 skipped); Worker typecheck and full Vitest — PASS (19 files, 110 tests).
- Stable public entrypoint: existing `workers.dev` Worker; custom domain required: **false**; ephemeral TryCloudflare hostname stability claimed: **false**.
- Signed route registration, request replay, stale generation, malformed/expired route, concurrent update, heartbeat expiry, reboot/cloudflared reconnect, exact `qwen38-q6`, schema-v2 health, and three-consecutive-health gates — PASS.
- Immutable artifact: `Investor-Intelligence-v2.1.3-R75-Free-Relay-Hotfix-b99f371aa471d799f99fd773b37d61753ec6d32e-33877850106.zip`.
- Downloaded artifact SHA-256: `4797b0afe18a5599c540dfd9b1a5e52ce7b354a3c34ff72929595f8eaec9e139`.
- Independent post-download verification — PASS: ZIP CRC, path safety, duplicates/case collisions, symlinks, PE marker, MANIFEST, SHA256SUMS, publication-contract binding, immutable identity, and exactly three external receipts.
- Downloaded files and post-download receipt are stored outside Git at `artifacts/r75-free-relay-hotfix-33877850106/`.
- Protected R75 publication/scoring semantics and the certified `cloud/src/qa.ts` retained blob are unchanged.
- `production_mutation_by_ci=false`; no Worker deploy, Production KV/DO write, Cloudflare route change, LINE send, task registration, or other external mutation occurred.

### CI iteration evidence

- Initial local clean validator failed closed at the repository credential scanner because three dynamic variables used sensitive-looking names. Commit `6a0e8d3` renamed the local variables; no credential was exposed and no external mutation occurred.
- The next local validator failed closed because direct modification of the certified v2.0 Q&A blob violated its retained-content hash. Commit `b99f371` restored the blob exactly and moved runtime route injection to the v2.1.3 production wrapper. The retained hash gate and full suite then passed.

### Open defect counts

- P0: **0**.
- P1: **0** for the FREE_RELAY scope.
- P2: **0** for the FREE_RELAY scope.

### Next action

Stop. Real Worker deployment, route publication, Quick Tunnel startup, LINE delivery, and Task Scheduler registration remain operator-controlled Production actions and were not executed in this session.

## Final delivery gate — PASS (2026-09-05)

- Gate ran on a clean working tree at branch `pi/r75-free-workers-relay`, HEAD `e460a172cabdb79ea6e5f785e11d622673b112eb`; `git status --short` empty, `git diff --check` clean.
- Artifact cross-check re-run without regeneration: `ARTIFACT_CROSSCHECK=PASS`; outer SHA-256 `4797b0afe18a5599c540dfd9b1a5e52ce7b354a3c34ff72929595f8eaec9e139`; 384 MANIFEST files; publication-contract SHA-256 `ed57b880bba3b29e41831201dc12bc8100101448f491f687c0bec67e9403f920` consistent across ZIP entry, HOTFIX-REFS, and current tree; all three receipts identity-bound to `b99f371`/run `33877850106` with `production_mutation_by_ci=false`.
- Full no-mutation re-verification: Python 550 passed/2 skipped; Worker typecheck + 19 files/110 tests; PowerShell 5.1.26100.9168 and 7.6.5 FREE_RELAY host tests, Named Tunnel regression, activation preflight/wrapper self-tests, heartbeat self-test, task validation, bridge strict-mode, operation lock, security check; artifact verifier re-run on the downloaded ZIP PASS; launcher three self-tests PASS.
- Three failures encountered during the gate were probe/self-test invocation errors (over-strict marker requirement, Git range syntax, launcher temp EXE path), not product defects; each was corrected and re-verified PASS.
- Protected R75 boundary versus `536644d22ef3534be1c4b8a9e1ff969df4d580fa` remains empty; certified `cloud/src/qa.ts` blob byte-identical; Serenity scoring, federation thresholds, publication contract/semantics, sealed bundles, and release evidence rules unchanged.
- TypeScript/Python/PowerShell contract alignment PASS; `workers_dev = true` retained, no custom routes, `custom_domain_required=false`, exact model `qwen38-q6`.
- `production_mutation_by_ci=false` throughout; no Worker deploy, Production KV/DO write, Cloudflare route change, LINE send, or task registration occurred.
- FINAL DELIVERY REPORT written to `state/FINAL_DELIVERY_REPORT_R75_FREE_RELAY.md` and sealed by this checkpoint commit (`[skip ci]`).
- Open defect counts: P0 **0**, P1 **0**, P2 **0**.

### Next action

Stop. Delivery complete at the artifact/receipt boundary. Real Worker deployment, Quick Tunnel startup, signed route publication, Task Scheduler registration, and LINE delivery remain operator-controlled Production actions requiring separate authorization.

## 操作者授權後正式上線 — PASS（2026-09-05）

- 使用者於本 Pi 工作階段明確授權 Production Worker 部署、真實 FREE_RELAY route、端到端驗證與 Task Scheduler 註冊。
- 修正 Cloudflare production Workers Runtime 不接受 `redirect: "error"` 的實際缺陷：health fetch 使用 `manual` 並拒絕所有 3xx；認證 `cloud/src/qa.ts` 不變，由 production wrapper 對 HTTPS completion 路徑提供同等 fail-closed 相容層。
- 正式來源 HEAD `92c97f97694e6e39c7a16986630d248c9ee744fe`；權威 Windows run `33896931576` success；本機完整 gate：Python 550/2 skipped、Worker 19 files/113 tests、PS 5.1/7、security、Named Tunnel regression、activation、heartbeat/task/lock 全 PASS。
- Production Worker 100% active version `27121388-1e6e-445a-b45e-104a867ca70d`；rollback baseline `eb52ece1-8749-4526-a464-3356ec2dbc65`；既有 08:00/21:00 TST crons 保留。
- 真實 route registration、三次 schema-v2 health、exact `qwen38-q6`、heartbeat 與穩定 `workers.dev` 入口端到端 smoke 全 PASS；未把 ephemeral TryCloudflare hostname 當成穩定入口。
- `InvestorIntelligence-v213-FreeRelay` at-logon task 已啟用（StartWhenAvailable、IgnoreNew）；實際 `Start-ScheduledTask` 測試 result=0、新 generation 成功、舊 8816 三程序全停止、新 8814 Gateway/tunnel/heartbeat 全存活；舊 v2.1.2 bridge task 已停用，其孤兒已清除。
- 現有 llama.cpp Router 曾由外部空參數重啟而變成零模型，Task 首次觸發因此 result=1 並完整保留舊 route。之後以同一 executable／同一 8080 串行重啟（先停舊程序，未並行第二 server），專案專用 preset 設 `models-max=1`；`qwen38-q6=loaded`、`qwen38=unloaded`。再測 Task 與完整 heartbeat 週期後 smoke PASS。
- 新 artifact `Investor-Intelligence-v2.1.3-R75-Free-Relay-Hotfix-92c97f97694e6e39c7a16986630d248c9ee744fe-33896931576.zip`，SHA-256 `8b29e6b7ad6237042824e4c6af3a9b9cc16ea8a9e716b51fdfa8aca2c7da56ec`；3 CI receipts + post-download verification PASS。
- GitHub Immutable Releases 已啟用；正式 tag `v2.1.3-R75-free-relay-final-92c97f9-33896931576`，`isImmutable=true`，10 assets，`gh release verify` PASS。Release 標題／說明、repository description/homepage 皆已加入繁體中文；topics 使用 GitHub 僅允許的 ASCII 格式。
- CI Production mutation 維持 `false`；實際 mutation 僅限本次明確授權的操作者動作。未手動發送 LINE。
- P0/P1/P2：**0/0/0**。

### 下一步

正式發布完成。持續由 heartbeat 維護短效 lease；若 Gateway/cloudflared 失效則 fail closed，登入工作會建立新 generation。

## 2026-09-05 08:02 TST — 使用者解壓版啟用失敗，重新開啟發布 gate

- Fetched HEAD: `7011676f6b98112182eee0f291c2ff3c75817615`；使用者 launcher log `20260905-075659-054-run-v213-local.log` 在第 8 階段出現 `No test files found, exiting with code 1`。
- 原 ZIP `92c97f9`/`33896931576` 實際 `cloud/test/*=0`、共用 publication fixtures=0；packager 明確刪除這兩項，而 activation 必須執行 `npm test`。這是產品打包缺陷，不是使用者操作錯誤。
- Bridge、20-row all-LIMITED bundle 與 sealed preflight 通過；行情 corroboration 0/20 正確降級，非本次退出原因。此次日誌未進入 activation commit。
- 更正先前全面完成的結論：先前驗證只涵蓋 source checkout 與 ZIP 完整性，未涵蓋解壓後 activation 測試依賴。
- 修正範圍：FREE_RELAY packager 保留 Worker tests 和兩個 synthetic fixtures；final ZIP 解壓至特殊路徑後執行 npm ci/typecheck/full tests；verifier 強制 inventory 與 extracted-ZIP receipt；新增缺檔負向測試。不修改受保護 R75 contract、scoring 或跳過 activation 測試。
- 本里程碑 P0/P1/P2 = **0/1/0**（發布阻塞：解壓後 Worker gate）；外部 mutation：無。
- 下一步：執行回歸、Windows CI、下載修正版與獨立解壓實測，產生新的 immutable release；舊 ZIP 不覆寫。
- 延伸測試另發現 runtime installer 僅接受舊 VERSION-REFS、未識別 R75 sealed wrapper，且把 robocopy 成功碼 1 當失敗。僅修正套件識別、加入完整 R75 marker 組與成功後退出碼正規化；未放寬 publication validator。
- 隔離 LOCALAPPDATA 的 installer 實測從錯誤重現到 `INSTALL_PROBE_EXIT=0`；已加入每個 final ZIP 的必跑 gate。第一輪 `bae5c53`/`33931793055` Windows CI success，但不發布此中間版本，等待包含 installer 修正的新完整 CI。
