# Investor Intelligence — 公開市場研究

[English](README.md) · [文件索引](docs/README.md) · [目前來源與驗收](state/STATUS.md) · [協助](SUPPORT.md)

本專案將公開市場公司財報、產業瓶頸、訂單與價格歷史整理成具來源的研究及 LINE 顯示。它**不會**代券商下單、不承諾報酬、不把私人 IBKR／持倉資料傳到 LINE 或公開 KV，也不會在免費來源失效時自行改用付費服務。

## 功能與證據界線

- `Top20` 優先讀取符合新鮮度條件的已封存 V3 瓶頸榜，必要時依既有路由退回舊七欄榜；`產業爆發榜` 是產業層分析。
- `瓶頸詳情 代號` 僅查詢當輪 Top20 入選公司；例如公司行動使歷史報酬無法比較、缺少符合要求的正值時，候選會被排除，不能將「未知」當零或當安全證明。
- RPO、backlog、預付款、未履行訂單及已認列營收不可混算；半年、一年等情境是明示假設，**非目標價**。
- Serenity 為公開研究方法視角；Leopold 的擴張鏈與 13F 僅作背景與線索，不是個股事實的獨立佐證。

## 本機開發與正式交付

依 [鎖定依賴與離線測試](docs/DEPENDENCY_LOCKING.md) 做本機驗證；按 [Release 安裝界線](docs/FINAL_RELEASE.md) 核實不可變 ZIP、SHA256、版本與授權後才進行獨立部署。開發 HEAD 或一次成功測試不代表已部署、已取得最新數據或所有缺陷關閉。

現況與下一步只查 [STATUS](state/STATUS.md)。LINE 僅使用公共資料，免費路線遇到權利／來源問題時 fail closed；任何 Production、排程、憑證及真實 LINE 發送均需本次明示授權。

[操作文件](docs/README.md) · [貢獻規範](CONTRIBUTING.md) · [安全通報](SECURITY.md) · [支援](SUPPORT.md)
