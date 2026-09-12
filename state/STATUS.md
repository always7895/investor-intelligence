# Current state / 目前狀態

Updated:2026-09-12 UTC. Release identity:`README.md`. Historical lookup:`git show 38860e7:state/STATUS.md`; history is not current acceptance.

## Priority / authority / workspace

2026-09-12 使用者指示：**「承接專案上述工作，以line上線為第一要務」**。LINE 正式上線 → UI/UX → EXE/THINK/GitHub 上架（PLAN §13 CP1–CP4）。無任意訊息、stale activation/report replay、restamping、paid fallback 或 gate waiver。Operator permission 不等於 supplier permission；無 broker/trading/billing 變更。Production 寫入（atomic KV commit / Worker redeploy / test-push）仍需當次明確授權；本 session 目前僅完成 read-only 驗證與 source 修正。

Source:`_workspace/source`; evidence:`_workspace/audit-runtime`; mixed parent `D:\Investor-Intelligence-LINE-Pi` is not a fixture. Never mirror/package/adopt/delete `_workspace`/`_archive` or scan them as market data. One writer; retain unrelated worktrees/drafts, locks/journals and failures.

HEAD（本輪 commit 前）`2b9e14396766e4883771a7c452a02bcfebb3c46f`, branch`fix/options-provenance-audit`, upstream`8178f72e1acb5d36cf5121a815a1097a28fdf3a`;28ahead/0behind。

## 2026-09-11 已完成（上一 session，已於 2026-09-12 驗證並 commit）

1. **Installer regression 解決**：`scripts/v213_runtime_install_coordinator.ps1`（staging+swap、pure .NET SHA256、PS5.1 typed-null Replace、`@robocopyArgs` 陣列）；install-*.ps1 全部委派 coordinator。34/34 `test_installer_*.py` PASS（PS5.1+pwsh）。
2. **Fresh data & preflight**：`--require-known-acquisition` fail-closed、reconcile retrieved_at 傳播、independence gate envelope cache；run **`20260911T173535Z-b32b8409717e`**（transaction `85814a46032f40559be3c526a2bf4e62`）preflight PASS。
3. **Worker 部署 & atomic commit**：active version **`c81e8825-66a3-4cc9-8f4e-f55c910b999e`**；edge readiness PASS（consecutive=3, no_write）；atomic commit/finalize PASS；`/health`、`/v213/readiness` HTTP 200。

## 2026-09-12 發現：morning 排程 refresh 失敗根因（fail-closed 正確擋下）

- 07:20 local（2026-09-11 23:20 UTC）scheduled refresh 產出 public snapshot `20260911T232158Z-636748cc4acb`，但 `build_v213_activation_bundle_v2.py` 拒絕：**`Missing dated evidence: v212.records[0].retrieved_at`** → publication NOT_ATTEMPTED（production 未變）。
- 根因鏈：
  1. `run-v213-local.ps1` Stage 4 呼叫 `v213_v212_progress_runner.py` **未帶 `--require-known-acquisition`**；yfinance 回傳數值但無 acquisition receipt（`UNKNOWN_PROVIDER_ACQUISITION_TIME`）→ 市場欄位 clock = UNKNOWN → row `retrieved_at = None` → bundle 驗證 fail-closed。
  2. 上一 session 成功的手動 run 是直接帶 flag 執行；scheduled pipeline 沒有接上。
  3. `v21_serenity_top20.py` 將 SEC companyfacts cache TTL 由 24h 改為 `policy.sec_cache_hours`（default 2h）以配合 7200s freshness gate（07:20/20:20 排程每輪必須拿到新 receipt）；**測試未同步**，造成 26 個測試失敗（fixture 預設 3h 老 cache 被 2h TTL 重抓）。
- 已修正（source）：
  - `run-v213-local.ps1`、`run-v213-local-serenity-latest.ps1`：v2.1.2 build 加 `--require-known-acquisition`（未驗證市場資料一律 UNAVAILABLE，SEC `profit_summary` 提供 row clock）。
  - `config/v21-serenity-policy.json`：明確 `sec_cache_hours: 2`。
  - `tests/test_report_source_acquisition.py`：fixture policy 補 `sec_cache_hours: 24`（保持 BOUND_CACHE 語意）＋新增 default 2h TTL refetch 測試。
  - `tests/test_compatibility_entrypoints.py`、`tests/test_v213_windows_security.py`：改為驗證 coordinator（pipeline order = `RUNTIME_PIPELINE_ORDER_INVALID`；stage copy 永不複製 source `node_modules`）。
- 注意：已安裝 runtime（`%LOCALAPPDATA%\InvestorIntelligence\V213Runtime`）仍是舊版（24h TTL、無 flag）。**重新安裝 runtime（coordinator staging+swap）後才能產生合格的新 bundle。**

## Verification matrix（2026-09-12，source working tree）

- **Worker**：typecheck PASS；vitest **505/505 PASS**（含 core.ts `TOP20/TOP10` ranking-token 修正）。
- **Python 全量**：941 tests；剩餘 14 broken 全部為 **pre-existing（HEAD 2b9e143 同樣失敗）**：`test_v213_journal_reconciliation`（3，PS host archive readback）、`test_compiled_exe_profile_persistence_and_child_propagation`（EXE 環境）、`test_rejects_public_reads_from_private_namespace`（storage.ts 靜態 marker）、`test_repository_passes_v21_delivery_gate`（storage.ts retained v2.0 blob finding）。非 LINE 上線關鍵路徑；不冒充已修。
- **Installer**：34/34 PASS（含修正後 compatibility/windows-security 模組，5 模組 51/51 OK）。
- `git diff --check`: 0 issues。
- 未 commit 的本地安裝輸入（維持 untracked，非 source identity）：`HOTFIX-REFS.json`（CI 產物，coordinator fallback 引用）、`InvestorIntelligence.exe`（68K launcher，installer 必要檔案）。

## Actual LINE state & next step

- Production KV snapshot **`20260911T173535Z-b32b8409717e`**（09-11 17:35 UTC）現已 **stale**（freshness gate 7200s；本輪盤點時 ≈9.4h）。`Top 20` 目前會被 freshness gate 拒絕。
- `cloud/src/core.ts` 的 `TOP20/TOP10` token 修正**尚未部署**（deployed worker c81e8825 建於該修正前）；但 `Top 20`（含空格）在 deployed code 已正確 routing（`TOP` 已在 IGNORED_TICKER_TOKENS）。Redeploy 非首次驗證阻塞項。
- **下一步（依序）**：
  1. Commit 本輪修正（小 commit × 5）。
  2. 以 coordinator 從新 HEAD 重新安裝 runtime（staging+swap；舊 root 保留為 `.old.<hash>`）。
  3. 手動 data-only refresh（`run-v213-scheduled-refresh.ps1 -Slot manual`）產生新 bundle + preflight。
  4. **（需當次明確授權）** atomic production commit（sealed bundle、pointer-last）＋ finalize。
  5. 驗證 `/v213/readiness`、`/health`；使用者手機 LINE 發 `Top 20` 驗收 20 筆新鮮報告。
  6. 07:20 / 20:20 兩個真實 scheduled runs 無重複且同輪 fresh（CP4）。
- Test-push endpoint `/v213/admin/test-push` 仍 `LINE_FREE_PLAN_REVIEW_REQUIRED`（channel SHA pairing 未設定）；不作為上線路徑，改由使用者真實對話驗證。

**G01/G02/G11 status updated; W1 installer regression closed; 上列 14 pre-existing failures 未修（非 P0 關鍵路徑）。AAPL debt conflict persists (publication_eligible=false)。**
