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
