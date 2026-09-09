# Investor Intelligence v2.1.3 R75

[English／完整證據](README.md)｜[最新不可變 Release](https://github.com/always7895/investor-intelligence/releases/latest)｜[共同中英狀態](docs/CURRENT_STATUS_BILINGUAL.md)

隱私優先、零付費公開研究與資料依據的條件式建議。不連接券商下單，不保證報酬。

## 開發中稽核／Development audit

[股票／新聞／期權來源覆蓋與抓取](docs/PUBLIC_SOURCE_COVERAGE.md)｜[期權來源與匯入用法](docs/OPTIONS_SOURCE_REVIEW.md)｜[候選 PR #37](https://github.com/always7895/investor-intelligence/pull/37)｜[遠端報價來源阻擋 #38](https://github.com/always7895/investor-intelligence/issues/38)。

候選版新增 Fed／SEC／ECB 公告與 TWSE／TPEx 股票日行情的明確選用本機抓取器，以及 TAIFEX 期權／Alpaca indicative 匯入 adapter，保留原有 Yahoo／本機 IBKR 路徑。五個端點皆已在核准且雜湊驗證的 CPython3.12.10＋鎖定 certifi 信任來源下，通過本機直接 CLI 真實抓取。早期 TLS 失敗仍保留，不代表任意系統 Python 皆已驗收；受控 GitHub Windows 回歸已通過只驗證模式，完整發布驗收仍待完成。**尚非 LINE 即時多源資料**：再散布權利與來源綁定 live 驗收未完成。日行情／指示價不可冒充可成交 NBBO。目前稽核問題不受歷史零缺陷數字覆蓋；以下已發布版本未變更。

候選發布需要新鮮 source／profile 綁定問答證據、receipt 綁定 ZIP 與解壓安裝驗收。舊 Q5 none-thinking PASS 不能替後續來源版本背書，失敗紀錄保留。候選 EXE 已有模型清單與手動 THINK 關閉／強度選擇，測試涵蓋共同 profile 儲存及子程序傳遞；清單讀取固定所選 Router。設定可傳遞不等於模型已支援或完成回答，think 自動判定仍未實作。已安裝鏈路與候選檔案存在差異，兩個發布任務仍 Disabled；沒有新的合格 EXE、正式模型切換、新資料發布或自動更新恢復。詳見[當前驗收](state/STATUS.md)及[模型契約](docs/MODEL_RUNTIME_MIGRATION.md)。

## 歷史已發布功能／Previously released functionality

- 互動與排程 Top20 共用 **20 檔完整七欄雙語卡片**：四組 carousel，每組五家公司。輸入 `Top20 文字` 可取得完整、依公司分組的文字版，不再橫向擠表格或省略尾端股票。
- 七欄：股票、近2年歷史年化報酬、近6個月歷史報酬、行業別、獲利簡述、目前訂單、未來訂單展望。沒有可靠證據就顯示未揭露／無可靠預估，不編造訂單總額、不把 LIMITED 升 HIGH。
- 指定 `qwen38-q6`，保留真實 canonical model ID、拒絕別名衝突／錯誤模型。既有 `127.0.0.1:8080` Router，單一模型；不另啟 llama-server、不改使用者 preset／持久推論參數。
- 封存發布：digest-bound bytes、pointer-last、物件讀回、損毀 replay 拒絕、持久失敗 journal、rollback／finalize。三個舊未封存寫入入口已 HTTP410。
- Windows **07:20／20:20 台北時間**產生並發布新封存資料；Worker **08:00／21:00**推送時間不變。排程採 Interactive owner、IgnoreNew、100分鐘上限與重試。請保持電腦／網路可用及使用者登入；鎖定桌面可執行，登出後不保證。

## 實際驗證與界線／Evidence and limits

2026-09-06 已發布／安裝 source `b5baae936dd3d422583decf9268910ed5783e4d5`，Windows33992169731、Python585／2 skipped PASS。ZIP SHA256 `320dfb799b34d1220138f67780d2f3fd0004781fcdeaf93e8d543169386f2e69`。發布後重新下載獨立驗證，`gh release verify-asset` 密碼學 release-asset attestation **PASS**。

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

免費路徑：workers.dev → 簽章短期 lease → TryCloudflare → Gateway → 既有 localhost:8080 Router。候選版單次 request 的 thinking／effort 依共同 profile；目前範本為 false／none，不是自動判定或 preset 變更。不放寬 stale／future／provenance／digest／privacy／IBKR 邊界，其餘舊消費端仍待審查。

Serenity 為公開研究重建，不是官方／私人公式，也不是已查證的最新本人立場。巨觀或身分來源不能當成公司訂單證據；不得用網站／鏡像數量灌高獨立佐證。

先驗證下載 ZIP 的外部 SHA256，再執行 `install-v213-source-diverse-runtime.ps1`。固定路徑 `%LOCALAPPDATA%\InvestorIntelligence\V213Runtime`；必要時在其 `cloud` 目錄以 `npm ci --ignore-scripts --no-audit --no-fund` 準備鎖定依賴。安裝程式碼不等於授權 Production 部署／發布。

歷史桌面入口為 **Investor Intelligence R75**；必須另核對實際 EXE、依賴鏈、所選模型與排程動作，舊捷徑不是目前的驗收證明。請勿把 LINE／Cloudflare／Gateway credentials、`.env` 或私人財務資料貼到 issue／log。

[操作文件](docs/V213_FREE_WORKERS_RELAY.md)｜[行動七欄 UI](docs/LINE_TOP20_UI.md)｜[完整狀態](docs/CURRENT_STATUS_BILINGUAL.md)
