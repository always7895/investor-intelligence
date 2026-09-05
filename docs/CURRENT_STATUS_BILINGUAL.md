# 目前狀態／Current status

## 正式版是否全部完成？／Is the entire product finished?

否。已發布、安裝的 Q&A／readiness 正式修正版是真實且可驗證的，但不能擴張成所有功能均已收尾。新確認的 LINE 五／七欄入口不一致仍須完成獨立驗收與新版本發布。

No. The published and installed Q&A/readiness hotfix is real and verified, but that does not certify every product feature. The newly confirmed five/seven-field LINE routing inconsistency still requires independent qualification and a new release.

## 七項／Seven fields

| 繁體中文 | English |
|---|---|
| 股票 | Ticker |
| 長期投資報酬率（近2年年化） | Long-term return (2Y annualized) |
| 短期投資報酬率（近6個月） | Short-term return (6M) |
| 行業別 | Industry |
| 獲利簡述 | Profit summary |
| 公司現在訂單 | Current orders |
| 未來訂單預估 | Future order outlook |

缺乏公開證據時，訂單必須顯示未揭露／無可靠預估，不填造數字，不提升 LIMITED。雙語欄名不代表已翻譯或重新驗證所有來源原文。

Missing public evidence must remain undisclosed/unavailable; no invented order figures or LIMITED upgrades. Bilingual labels do not imply translation or revalidation of every source narrative.

## 已確認差異／Confirmed routing differences

- 已發布的互動 Top20：舊 v212 五欄。／Released interactive Top20: legacy v212 five fields.
- 已發布的舊 test-push：五欄。／Released legacy test-push: five fields.
- v213 排程：七欄，仍有 freshness／dedupe gate。／v213 schedule: seven fields with freshness/deduplication gates.
- Production GET /health：仍顯示 v2.1.2／five_fields_only，已實際唯讀確認。／Production health still advertises v2.1.2/five_fields_only, confirmed read-only.

## 修正與門檻／Fix and gates

候選修正統一七欄回覆、舊 test-push alias 與 health，預設雙語欄名；新增真正 authorized LINE handler 的 mock-transport 整合測試，取代原本 `expect(true)` 的「未接線」placeholder。本機 TypeScript 與22檔／133 tests PASS。

The candidate unifies seven-field replies, the legacy test-push alias and health metadata, with bilingual labels by default. A real authorized LINE handler test with mocked transport replaces the obsolete `expect(true)` placeholder. Local TypeScript and22 files/133 tests pass.

隔離 live gate 的新 workers.dev hostname 持續回 HTTP404，因此沒有跳過 readiness、沒有借用舊 runtime receipt 充當新驗收、沒有發新版 ZIP／安裝／部署。隔離資源已清除；未發真實 LINE、未改 Production snapshot 或排程。

New isolated workers.dev hostnames returned HTTP404, so readiness was not bypassed and the old runtime receipt was not reused to qualify new code. No new ZIP, installation or Production deployment occurred. Isolated resources were deleted; no real LINE message, Production snapshot or schedule was changed.

目前新修正 P0/P1/P2＝0/1/1：七欄一致性 P1 尚未交付；隔離 edge readiness P2 尚未通過。舊版 Q&A/readiness 的已完成證據維持原範圍。

Current follow-up P0/P1/P2=0/1/1: seven-field consistency P1 remains undelivered; isolated edge readiness P2 remains unqualified. Prior Q&A/readiness evidence retains its original scope.

## GitHub 雙語維護範圍／GitHub bilingual maintenance scope

目前維護 README 英文／繁中雙版本、About 雙語描述、Release 雙語標題與摘要、此共同狀態頁，以及新 issue／PR 的雙語說明。Homepage 是 URL，版本 tag、hash 與機器欄位保持原樣。

Current maintenance covers paired English/Traditional-Chinese READMEs, bilingual About description, release title/summary, this shared status page and new issue/PR descriptions. Homepage remains a URL; version tags, hashes and machine keys remain unchanged.

不是聲稱所有歷史 issue、PR、commit、舊 release 與每份技術文件均已全文翻譯；不改寫歷史證據。／This is not a claim that every historical issue, PR, commit, release or technical document has been fully translated; historical evidence is not rewritten.

## Candidate checkpoint / 候選版進度

- LINE mobile Top20: four Flex groups, twenty complete seven-field cards; full text fallback. Actual isolated Worker payload tests and Q6 cold/warm qualification PASS (maximum 1,425.23 ms). LINE transport was synthetic, not a real delivery/device test.
- LINE 行動版：四組 Flex、20 張完整七欄卡片及完整文字備援。隔離 Worker payload 與 Q6 cold/warm 驗證通過，最慢 1,425.23 ms；LINE 傳輸為合成測試，非真實送達或裝置認證。
- Fresh local data-only build and actual all-LIMITED preflight passed on Windows PowerShell5.1/7: twenty LIMITED, zero evidence-qualified. Host-specific Microsoft module loading fixes a reproduced cross-host DPAPI command-loading failure; historical task causality remains unproven.
- 新鮮本機資料建置及 Windows PowerShell5.1／7 實際 all-LIMITED preflight 通過：20 LIMITED、0 已驗證論點。已修正可重現的跨 PowerShell 主機模組載入問題，但不把它冒稱為歷史排程故障的已證實原因。
- Sealed refresh is explicit opt-in and defaults to no publication. Synthetic tests cover readback, strict acknowledgements, finalize, rollback, unresolved journals and both actual scheduled-wrapper modes. Task definitions require a logged-in owner for DPAPI; locked desktop is supported, logged-out operation is not promised.
- 封存更新須明確啟用，預設不發布。合成測試涵蓋讀回、嚴格回執、finalize、rollback、未解決 journal 與排程 wrapper 兩種模式。DPAPI 排程需要使用者已登入；可鎖定桌面，不承諾登出後運作。
- Full Python regression: 582 tests, two skips, PASS. Retained v2.0 LINE transport and certified qa.ts bytes remain unchanged. Broader Q6 code-review attempts exhausted their output budgets and are INCOMPLETE, not review PASS.
- Python 完整回歸：582 測試、2 skipped、PASS；保留的 v2.0 LINE transport 與 qa.ts 位元組未改。較廣泛 Q6 程式審查耗盡輸出預算，仍為未完成，不能列為審查通過。
- New Windows CI, immutable successor packaging, independent download verification and authorized Production migration remain pending. No candidate installation, Worker/storage/task/cron mutation or extra real LINE send has occurred in this checkpoint.
- 新版 Windows CI、不可變後繼封裝、獨立下載驗證及已授權的正式遷移仍待完成；本階段未安裝候選版，未變更正式 Worker／儲存／工作排程／cron，未額外發送真實 LINE。

UI details / UI 詳細說明：[LINE_TOP20_UI.md](LINE_TOP20_UI.md).
