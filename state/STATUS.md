# Current state / 目前狀態

Updated:2026-09-12 UTC (13:30 local). Release identity:`README.md`. Historical lookup:`git show 38860e7:state/STATUS.md`; history is not current acceptance.

## Priority / authority / workspace

2026-09-12 使用者指示：**「承接專案上述工作，以line上線為第一要務」**。本 session 完成：source 修正、runtime 重新安裝、production 新資料發布（evening slot，FINALIZED）、production 端點驗證。**下一步在操作者：手機 LINE 發 `Top 20` 驗收**（snapshot fresh 至 2026-09-12 07:11 UTC / 15:11 local；20:20 local 排程會再生成下一輪）。

Source:`_workspace/source`; evidence:`_workspace/audit-runtime`; mixed parent `D:\Investor-Intelligence-LINE-Pi` is not a fixture. One writer; retain worktrees/drafts, locks/journals and failures。

HEAD **`7253764`**（本輪 8 commits：6f93242→7253764），branch`fix/options-provenance-audit`, upstream`8178f72e1acb5d36cf51212a815a1097a28fdf3a`。未 commit 的本地安裝輸入（維持 untracked）：`HOTFIX-REFS.json`、`InvestorIntelligence.exe`。

## 2026-09-12 完成事項（LINE 上線關鍵路徑）

1. **Morning 排程失敗根因 + 修正**：Stage 4 v2.1.2 build 缺 `--require-known-acquisition` → UNKNOWN market clock → row `retrieved_at=None` → bundle fail-closed 拒絕（正確行為）。兩個 entrypoint 已補 flag；`sec_cache_hours: 2` 明確寫進 policy；測試同步（fixture 24h + 新 2h TTL refetch 測試）。
2. **Production 新資料已上線（evening slot, 2026-09-12 05:09–05:12 UTC）**：
   - run **`20260912T051141Z-f04e8b28cf3a`**, transaction **`21c094ecd78783082b4ea9a89e77fa67`**, bundle sha `6cde50f3…`
   - journal `7525990b770f4e728a4b85a7daab55ce.json` = PASS/FINALIZED, production_mutation=true, 20/20 行皆帶 SEC-anchored retrieved_at，市場欄位 fail-closed UNAVAILABLE（degradation policy 語意）
   - `/health` 200；`/v213/readiness?challenge=…` → **ready=true, compatibility=PASS**, worker `c81e8825-…`
   - 注意：12:20 UTC 排程實際 12:42 才觸發（StartWhenAvailable 補跑；機器/排程疑似 12:20 時 sleep）。13:09 的 FINALIZED 為手動 `Start-ScheduledTask` 觸發（同一 task、同一 code path）。**07:20/20:20 兩個 slot 的「自然觸發」尚未各完成一次**（09-12 07:20 morning 已自然跑過但 publication 被下述 journal 問題擋下）。
3. **修復擋住所有 publication 的 broken journal**：`3df09596…json`（9/6 NOT_COMMITTED probe）9/7 被手動加 `resolved_utc`+`resolution` 欄位 → 超出 closed schema → `Read-V213RefreshJournal` INVALID → JOURNAL_CHECK 永久擋下。已還原 closed schema；註解版存 `.details/annotated-journal-20260907.json`；`.details/rollback.json`（not_committed ack）證據完整。
4. **Installer（coordinator）三個設計缺陷修復 + 端到端驗證**：
   - ownership coverage 原先涵蓋 `data/`：任何 refresh 寫 data 後，下一次 reinstall 必 fail `RUNTIME_OWNERSHIP_DIGEST_MISMATCH` → coverage-aware 驗證（manifest 檔案須 authentic per receipt；live payload 全部為已知且未改動；歷史 payload entries 須仍在且未改動；migration 掉的可變路徑永不 re-attest）。
   - 可變 segment 補齊：`__pycache__`（任意深度）、`reports/`（public_briefing_latest.md）、`.wrangler/`（auth cache）。
   - `cloud/node_modules` 被 name-based /XD 全深度排除 → runtime 無 wrangler → AUTH_CHECK `CommandNotFoundException`（9/12 evening 第二輪失敗根因）→ /XD 改 full top-level path；source 有 wrangler 時 stage 必須帶（否則 RUNTIME_REQUIRED_FILE_MISSING）。
   - 驗證：installer 測試 **35/35 PASS**（PS5.1+pwsh，含新 wrangler 回歸測試）；live reinstall **PASS**（transaction `71921c0f410c4a5ea895a6a21702efc5`，舊 root 保留；wrangler hash == source；manifest 678 files、無 excluded-segment leak）。
5. **Worker**：typecheck PASS；vitest **505/505 PASS**（含 core.ts `TOP20/TOP10` ranking-token 修正；deployed worker c81e8825 建於該修正前，但 `Top 20`（含空格）在 deployed code 已正確 routing — redeploy 非上線阻塞項，待下次 Worker 變更一併部署）。
6. **Python 全量**：941 tests；剩餘 14 broken 全部 pre-existing（HEAD 2b9e143 同失敗）：`test_v213_journal_reconciliation`（3，PS host archive readback）、`test_compiled_exe_profile_persistence_and_child_propagation`、`test_rejects_public_reads_from_private_namespace`（storage.ts 靜態 marker）、`test_repository_passes_v21_delivery_gate`（storage.ts retained v2.0 blob finding）。非 P0 關鍵路徑；不冒充已修。
- `git diff --check`: 0 issues（所有 commit 前）。

## Open findings（未修，非上線阻塞）

- **P2** manifest `source_commit` 綁定 `HOTFIX-REFS.json`（stale CI 產物，2b9e143）而非安裝當下 git HEAD；檔案 hash（entries_sha256）才是真實完整性綁定。建議：installer 以實際 git HEAD 記錄 source_commit 或要求 fresh refs。
- **P2** evening trigger 延遲 22 分鐘觸發（StartWhenAvailable）；WakeToRun=true 但未能在 12:20 準時喚醒/觸發。觀察明晨 07:20 自然觸發。
- **P2** 14 個 pre-existing Python 環境失敗（上列）。
- AAPL debt conflict：`publication_eligible=false` 持續（不擋 Top20 發布）。
- `/v213/admin/test-push` 仍 `LINE_FREE_PLAN_REVIEW_REQUIRED`（channel SHA pairing 未設）；上線驗證改走使用者真實對話。

## Next step

1. **操作者**：手機 LINE 發 `Top 20` → 預期 20 筆七欄報告（run 20260912T051141Z，bilingual 欄位）。
2. 明晨 07:20 local morning slot 自然觸發 → 驗證 receipt（含 publication）→ CP4 兩 slot 自然跑各一次。
3. 其後依 PLAN §13：UI/UX → EXE/THINK → GitHub 上架。

**G01/G02/G11 status updated; W1 installer regression closed（含本輪三個 coverage/toolchain 缺陷）。Production snapshot live（20260912T051141Z）。**
