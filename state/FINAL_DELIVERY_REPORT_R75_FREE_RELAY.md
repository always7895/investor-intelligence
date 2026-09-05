# FINAL DELIVERY REPORT — R75 Free Relay Hotfix (2026-09-05)

## 1. 最終判定

**FINAL DELIVERY GATE = PASS**（本節點 commit 封存此報告；artifact 身份綁定 source commit + CI run，不因節點 commit 改變）。

## 2. 身份識別

| 項目 | 值 |
|---|---|
| Branch | `pi/r75-free-workers-relay` |
| Artifact source commit | `b99f371aa471d799f99fd773b37d61753ec6d32e` |
| Gate 時 branch HEAD | `e460a172cabdb79ea6e5f785e11d622673b112eb` |
| 最終 checkpoint commit | 本節點 commit（新增本報告 + STATUS 門禁章節，`[skip ci]`） |
| Base Named Tunnel hotfix commit | `43f3be048cedf228cfe9e8e8e31f7b9901895838be`（typo-guard: 實際 `43f3be048cedf228cfe9e8e31f7b9901895838be`） |
| Verified R75 base | `536644d22ef3534be1c4b8a9e1ff969df4d580fa` |
| Authoritative Windows CI run | `33877850106`（self-hosted Windows Runner，conclusion=success） |
| Artifact 路徑（repo 外） | `artifacts/r75-free-relay-hotfix-33877850106/Investor-Intelligence-v2.1.3-R75-Free-Relay-Hotfix-b99f371aa471d799f99fd773b37d61753ec6d32e-33877850106.zip` |
| Artifact SHA-256 | `4797b0afe18a5599c540dfd9b1a5e52ce7b354a3c34ff72929595f8eaec9e139` |
| Publication contract SHA-256 | `ed57b880bba3b29e41831201dc12bc8100101448f491f687c0bec67e9403f920`（ZIP 內、HOTFIX-REFS、目前樹三者一致） |

## 3. Serenity 核心邏輯狀態

**未被 hotfix 破壞。** 證據：

- 受保護 R75 路徑（publication-mode config、activation preflight、publication-mode.ts、activation-v2.ts、base packaging/verification）對 `536644d22ef3534be1c4b8a9e1ff969df4d580fa` 的 diff 為空。
- `cloud/src/qa.ts` 與 certified base blob 逐位元組一致（`git hash-object` 相等）。
- Python 全量 550 tests（含全部 Serenity H1–H6B、source-family/domain independence、claim coverage、market-quality degraded、seven-field contract 套件）PASS，2 skipped。
- `V213_R75_ACTIVATION_PREFLIGHT_SELF_TEST = PASS`：all_limited=true、optional_bls=true（BLS optional semantics 保留）、positive_limited_rejected、limited_high_rejected、single_origin_rejected、count_order_freshness_digest_rejected、negative_factor_pass。

## 4. R75 framework 狀態

**完整。** 證據：

- Publication contract 雜湊三點一致（ZIP 內 `config/v213-r75-publication-mode-v1.json` = HOTFIX-REFS = 目前樹）。
- Base R75 packaging/verification 腳本未修改；FREE_RELAY 使用獨立 `ci_v213_r75_free_relay_*` 與 `verify_v213_r75_free_relay_hotfix.py`。
- Immutable identity：artifact 名稱含 source commit + run id，MANIFEST `artifact_kind=R75_FREE_WORKERS_RELAY_HOTFIX`、384 files、`production_mutation_by_ci=false`。
- Post-download independent verification：ZIP CRC、path safety、duplicates/case collisions、symlinks、PE marker、MANIFEST、SHA256SUMS、contract binding、immutable identity、三份 receipt 全 PASS。

## 5. 三端 contract alignment（TypeScript / Python / PowerShell）

**PASS。**

- TypeScript（`cloud/src/v213/free-relay.ts` + production wrapper）：`quick_free_relay`、`qwen38-q6`、`health_schema_version`、`consecutive_health_checks`、`route_generation`、`expires_at` 全部存在；19 files / 110 tests PASS。
- PowerShell（bridge core、`v213_free_relay.ps1`、heartbeat、host tests）：相同 markers 存在；PowerShell 5.1.26100.9168 與 7.6.5 兩 host 的 FREE_RELAY host test、Named Tunnel regression、activation self-test、heartbeat self-test、task validation 全 PASS。
- Python（activation preflight、security check、verifier py_compile）：PASS。
- Wrangler template：`workers_dev = true`、無 custom `routes`、`FREE_RELAY_ENABLED="true"`、`LOCAL_LLM_MODEL="qwen38-q6"`。

## 6. Production mutation 與 entrypoint

- `production_mutation_by_ci = false`（MANIFEST、三份 receipt、post-download verification、independent verification 全一致）。
- 穩定公共 entrypoint 維持既有 `workers.dev` Worker，未被改掉；`custom_domain_required=false`；`trycloudflare.com` 僅為 ephemeral relay，不宣稱穩定。
- 本 session 無 Worker deploy、Production KV/DO 寫入、Cloudflare route 變更、LINE 發送、schedule 註冊、Task Scheduler 註冊。

## 7. 本輪 FINAL DELIVERY GATE 執行記錄

1. `git status --short` — 空（clean）；HEAD=`e460a172cabdb79ea6e5f785e11d622673b112eb`。
2. 未處理 R75 修改 — 無；`git diff --check` clean。
3. Artifact/MANIFEST/SHA256SUMS/receipts/contract 一致性 — `ARTIFACT_CROSSCHECK=PASS`（outer SHA、384 manifest files、contract 三點一致、三 receipt 身份與 mutation 旗標一致）。
4. Targeted tests — 完整 no-mutation matrix PASS：Python 550/2 skipped；Worker typecheck + 19 files/110 tests；PS 5.1/7 全部 host tests；activation preflight/wrapper self-test；heartbeat；task validation；bridge strict-mode；operation lock；security check；artifact verifier 對已下載 ZIP 重跑 PASS；launcher 三項 self-test PASS。
5. 失敗處理 — 本輪 3 個失敗均為驗證指令自身問題（marker 過度要求、git range 語法、launcher EXE 暫存路徑），非產品缺陷；修正後重驗全 PASS。
6. Serenity/R75 核心、source-family/domain independence、claim coverage、market-quality degraded、BLS optional — 未破壞（見 §3）。
7. 三端 contract alignment — PASS（見 §5）。
8. `production_mutation_by_ci=false` — 維持。
9. `workers.dev` entrypoint — 未改。
10. Checkpoint commit — 本 commit。
11. 本報告。

## 8. Remaining blockers

**技術性 blocker：無（P0=0, P1=0, P2=0）。**

剩餘為**設計上由操作者控制的 Production 動作**（非 blocker，須另行授權執行）：

- 實際 Worker 部署至 Production。
- 真實 Quick Tunnel 啟動與 signed route 發布（需 RTX 機器上 `qwen38-q6` Gateway 在線）。
- Task Scheduler（at-logon）實際註冊。
- 首次真實 LINE 交付。
- （可選未來路徑）Named Tunnel 穩定化部署。

## 9. 交付結論

**可以正式交付。** Immutable artifact、SHA-256、MANIFEST、SHA256SUMS、三份 receipt、independent post-download verification、三端 contract、R75/Serenity 保護邊界與 no-mutation 證據全部齊備且相互一致。Production 部署與實際 route 發布留待授權操作者執行。

## 10. 操作者授權後的正式上線附錄（2026-09-05）

本節記錄後續同一 Pi 工作階段中，使用者明確授權後執行的 Production 動作；它不改寫前述 CI no-mutation 證據。

- 正式來源 commit：`92c97f97694e6e39c7a16986630d248c9ee744fe`；權威 Windows CI run `33896931576` PASS。
- 發現並修正 Cloudflare 正式 Workers Runtime 對 `redirect: "error"` 的即時 TypeError；route health 改為 `manual` 並拒絕 3xx。經認證 `cloud/src/qa.ts` blob hash 仍為 `94184bc8937b413eb327b3d773926db00e22b3b9`，與 R75 基準相同。
- v2.1.3 wrapper 對 HTTPS `POST /v1/chat/completions` 安裝精準相容層，並保留 redirect fail-closed；新增 HMAC 簽章、固定提示詞、無 KV 寫入的 smoke gate。
- 本機完整 no-mutation 驗證 PASS：Python 550 passed/2 skipped；Worker 19 files/113 tests；PowerShell 5.1/7 及全部回歸／安全 gate PASS。
- 正式 Worker 目前 100% active version：`27121388-1e6e-445a-b45e-104a867ca70d`；部署前回滾基準：`eb52ece1-8749-4526-a464-3356ec2dbc65`。
- 真實 FREE_RELAY signed route、Gateway、Quick Tunnel、heartbeat 均 PASS；穩定 `workers.dev → route lease → Gateway → qwen38-q6` 固定標記 smoke 回應 PASS。短效 TryCloudflare hostname 未記錄為穩定入口。
- `InvestorIntelligence-v213-FreeRelay` at-logon 工作已啟用（`StartWhenAvailable=true`、`MultipleInstances=IgnoreNew`）；Task Scheduler 實際觸發 result=0、新 generation 與一個完整 heartbeat 週期後 smoke PASS。舊 `InvestorIntelligence-v212-LocalModelBridge` 已停用，其 bridge/tunnel 孤兒已清除；早晚資料刷新工作保留。
- 現有 Router 一度由外部以空參數重啟而無模型；首次 Task 失敗時舊 route 完整保留。之後先停舊 Router，再用同一 executable／同一 8080 串行重啟，專案專用 preset 設 `models-max=1`；最終只有 `qwen38-q6` loaded，`qwen38` 保持 unloaded，未同時啟動第二 llama-server。
- 新不可變 artifact：`Investor-Intelligence-v2.1.3-R75-Free-Relay-Hotfix-92c97f97694e6e39c7a16986630d248c9ee744fe-33896931576.zip`；SHA-256 `8b29e6b7ad6237042824e4c6af3a9b9cc16ea8a9e716b51fdfa8aca2c7da56ec`；下載後獨立驗證 PASS。
- GitHub Immutable Releases 已啟用；不可變正式 Release（`isImmutable=true`）為 `v2.1.3-R75-free-relay-final-92c97f9-33896931576`，`gh release verify` PASS，10 個 assets 全部具有 GitHub attestation。
- CI 仍為 `production_mutation_by_ci=false`；上述 Worker deploy、真實 tunnel/route 與 Task Scheduler 註冊均是本次明確授權的操作者動作。未執行臨時 LINE 手動推送；既有 08:00/21:00 TST crons 保留。
- 當時所列缺陷數：P0 **0**、P1 **0**、P2 **0**；後續使用者解壓啟用發現漏測，以下修正記錄取代全面完成的解讀。

## 11. 使用者實際啟用失敗與修正版（2026-09-05）

`20260905-075659-054-run-v213-local.log` 顯示在正式 activation 前 `npm test` 找不到測試檔。原 ZIP 排除 `cloud/test/` 及共用 fixtures；此外 runtime installer 未接受 HOTFIX-REFS/R75 wrapper，且誤判 robocopy 成功退出碼。因此先前對完整發布可用性的結論過度延伸，正式 activation 並未由當時 smoke 證明。

修正版來源 `1ca12437f9608bb971863a6caf69426d75f6ccf9`，Windows CI `33931959307` PASS：Python 556（2 skipped）、Worker 19 files/113 tests、PS 5.1/7、final ZIP 解壓 typecheck/test 及隔離 runtime installer PASS。下載到使用者 Downloads 後，再次獨立執行相同 Worker gate 與隔離 installer 均 PASS。

新不可變 Release：`v2.1.3-R75-package-fix-1ca1243-33931959307`；ZIP SHA-256：`fc374886b50cc1e71c98d464bf3b7c554859651bb38770917c285dcbf2074272`；GitHub attestation、ZIP inventory／MANIFEST／receipts／CRC 驗證 PASS。舊 Release 已標示缺陷且不覆寫資產。

本輪僅修正打包與安裝 gate，未重新執行 Production activation、部署、資料提交或 LINE 發送。**解壓與安裝缺陷已修復；正式 sealed-bundle activation 仍需實際交易成功回執，不宣稱整個產品所有路徑無問題。**
