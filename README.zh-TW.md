# Investor Intelligence

[English／發布身分](README.md) · [完整文件索引](docs/README.md) · [當前缺陷與下一步](state/STATUS.md)

隱私優先的公開市場研究與有證據的條件式建議。不連接券商下單、不保證報酬、不使用付費備援。

## 使用

- `Top20`：20家公司、四組carousel，每組五張完整七欄卡片。
- `Top20 文字`：完整20家公司七欄文字；候選卡片的「本公司七欄文字」只展開該公司。
- 「證據詳情」：查看同一公司／時間／snapshot／報告SHA綁定的資料、引用及缺口。舊卡不偷偷改讀另一輪報告。
- 近2年年化與近6個月是**歷史報酬**，不能當半年／1年／2年的未來成長預測。

## 訂單與估值

保留已披露的金額、期間與認列比例；RPO、backlog、預付款、pipeline和已認列營收不能混稱全部訂單或重複相加。文件日期不是交貨日；未公布確切時間就明示未知。

半年／1年／2年情境需逐項來源與可重算的營收→利潤／現金流→融資稀釋→每股估值。不能恢復程式寫死的樂觀漲幅，也不能用「很大」代替證據。「證據詳情」與七欄文字都**不是完整深度估值報告**。[執行稽核及待補資料](docs/RESEARCH_EXECUTION_AUDIT.md) · [完整資料契約](docs/DETAILED_REPORT_CONTRACT.md)。

Serenity是主要公開方法視角；Leopold Aschenbrenner只作CONTEXT_ONLY巨觀假設，不加分、不限制永久AI選股範圍、不代表本人背書。Pi SKILL存在並不表示LINE或排程執行完整研究；實際路徑見上述稽核。

## 狀態、安裝與安全

目前缺陷、測試及下一步只維護在[STATUS](state/STATUS.md)；各ZIP的發布身分只維護在[README](README.md)及其不可變refs／receipts。不沿用舊的停用排程、未部署或零缺陷數字。過去操作者回報的上線／LINE驗收不等於本輪重驗或再次授權。

先驗證ZIP的外部SHA256，再依[安裝界線](docs/FINAL_RELEASE.md)操作。開發來源在`_workspace/source`；本輪來源修改不自動安裝或部署。保留唯一Router `localhost:8080`、核准exact model、scoring／privacy／freshness／sealed publication門檻；不更動Production、憑證、真實LINE或排程，除非本次明確授權。

[操作](docs/V213_FREE_WORKERS_RELAY.md) · [UI](docs/LINE_TOP20_UI.md) · [鎖定依賴／檢查](docs/DEPENDENCY_LOCKING.md) · [工作區維護](docs/WORKSPACE_MAINTENANCE.md)
