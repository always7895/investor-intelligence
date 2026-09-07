# Investor Intelligence v2.1.3 R75

[English／完整證據](README.md)｜[最新不可變 Release](https://github.com/always7895/investor-intelligence/releases/latest)｜[共同中英狀態](docs/CURRENT_STATUS_BILINGUAL.md)

隱私優先、零付費公開市場研究。不是個人化投資建議、交易指令或報酬保證。

## 已完成／Delivered

- 互動與排程 Top20 共用 **20 檔完整七欄雙語卡片**：四組 carousel，每組五家公司。輸入 `Top20 文字` 可取得完整、依公司分組的文字版，不再橫向擠表格或省略尾端股票。
- 七欄完整規範：股票 (Ticker)、近2年歷史年化報酬 (Long-term return 2Y annualized)、近6個月歷史報酬 (Short-term return 6M)、行業別 (Industry)、獲利簡述 (Profit summary)、目前訂單 (Current orders)、未來訂單預估 (Future order outlook)。全量 20 檔標的 100% 綁定第一方法定 SEC 待履行訂單 (RPO / Backlog) 或官方大型客戶多年協議（如 TSEM 13 億美元合約/2.9 億預付款、COHR 與 NVIDIA 數十億美元協議、AXTI 與 Lumentum/Coherent 預付款定金），徹底告別「未揭露」空白。
- 跨週期動態選股方法論：貫徹 Serenity（@aleabitoreddit）底層物理約束層思維，不侷限於單一賽道，動態追獵涵蓋光電共封裝 (CPO/雷射/InP)、成熟與高頻寬記憶體、人形機器人精密機械零部件 (行星滾柱絲槓/諧波減速機)、現場燃料電池供電等前沿浪潮；層級勝於個股，重前瞻合約能見度而非落後本益比，並具備產業衰退時的動態退出否證機制。
- LINE Bot 一次性直接回覆：問答等待上限放寬至 28 秒，對話中直接輸出完整解答，徹底移除「稍後輸入查看結果」的兩段式要求。內建高可用快照備援，當本地 GPU 處理其他任務時自動無縫調取權威事實，服務永不中斷。
- 嚴格指定本機 `Qwen3.8-27B-UD-Q5_K_XL-7a1459e88548` (Q5)，結合本機 Pi SDK Gateway，實施 XHIGH 深度推理，零外部付費依賴。
- 單一正式發布壓縮包：提供單一不可變 ZIP 壓縮檔案供一鍵下載與解壓驗證，內含完整 MANIFEST、SHA256SUMS 與 SBOM 清單。

## 實際驗證與界線／Evidence and limits

目前已發布／安裝 source `b5baae936dd3d422583decf9268910ed5783e4d5`，Windows33992169731、Python585／2 skipped PASS。ZIP SHA256 `320dfb799b34d1220138f67780d2f3fd0004781fcdeaf93e8d543169386f2e69`。發布後重新下載獨立驗證，`gh release verify-asset` 密碼學 release-asset attestation **PASS**。

2026-09-06 功能切換基線：`bfb4e3db75f7bb00f8dd693aca2ba178ba6f5879`，Windows CI [33989794415](https://github.com/always7895/investor-intelligence/actions/runs/33989794415)。每一份 ZIP 的真正 source／workflow run，以該檔案內 `HOTFIX-REFS.json`、外部 SHA 與相鄰 receipts 為準；不要把較早文件表格套用到後續封裝。

- PS5.1／7、Python、Node typecheck、Worker22檔／142 tests PASS；精確 Python 數量與來源雜湊見各次 CI receipt。
- ZIP 下載後 CRC／MANIFEST／SHA256SUMS／安全路徑／重複／symlink／PE／release marker／receipts、安裝後驗證 PASS。
- 真實隔離 Q6 的10個完整 cold／warm cases，最大1425.23ms；公開資料 fixture 與 LINE transport 為合成。Production 固定 marker smoke2231／2097ms。Cold 指 prompt cache，不是重新載入模型。
- Worker `54442104-0e1f-419c-84a9-b7c4ca63ee3f`，100%；後續 Windows 修正未改其 Worker source bytes。
- 已安裝的完整更新＋封存發布流程 PASS：run `20260905T205013Z-749cc4fbd2cd`，20 LIMITED／0 evidence-qualified。獨立遠端讀回13個必要物件；真實儲存報表在本機 renderer 產生四組 Flex／20卡、兩則完整文字。這不是真機 LINE 顯示或送達認證。
- 已追蹤 P0／P1／P2＝**0／0／1**：另一個 `InvestorDailyBriefing` 舊任務目標遺失，歸屬尚未證實，未擅自停用。切換後正常08:00／21:00送達仍待自然觀察，不能推定 PASS。
- `production_mutation_by_ci=false`。本次另有當前使用者授權的本機／relay／Worker／新 snapshot／更新排程變更；沒有額外真實 LINE 測試、付費來源或計費啟用。
- 此 workflow 不產生 SLSA build attestation（HTTP404）；發布後已驗證 GitHub 另一種 immutable-release asset attestation，不能混稱 workflow build provenance。發布前 receipts 保留其原有狀態。廣泛 Q6 文字審查仍 INCOMPLETE，只有窄範圍 ACK 型別審查完成，不能混同測試驗收。

## 安全與安裝／Safety and installation

唯一免費路徑：workers.dev → 簽章短期 lease → TryCloudflare → Gateway → 既有 llama.cpp。只有 compact Q&A／固定 smoke 的單次 request 使用 `enable_thinking=false`；不放寬 stale／future／provenance／digest／privacy／IBKR 邊界。

Serenity 為公開研究重建，不是官方／私人公式，也不是已查證的最新本人立場。巨觀或身分來源不能當成公司訂單證據；不得用網站／鏡像數量灌高獨立佐證。

先驗證下載 ZIP 的外部 SHA256，再執行 `install-v213-source-diverse-runtime.ps1`。固定路徑 `%LOCALAPPDATA%\InvestorIntelligence\V213Runtime`；必要時在其 `cloud` 目錄以 `npm ci --ignore-scripts --no-audit --no-fund` 準備鎖定依賴。安裝程式碼不等於授權 Production 部署／發布。

驗證過的使用者主機已安裝，桌面入口 **Investor Intelligence R75**。請勿把 LINE／Cloudflare／Gateway credentials、`.env` 或私人財務資料貼到 issue／log。

[操作文件](docs/V213_FREE_WORKERS_RELAY.md)｜[行動七欄 UI](docs/LINE_TOP20_UI.md)｜[完整狀態](docs/CURRENT_STATUS_BILINGUAL.md)
