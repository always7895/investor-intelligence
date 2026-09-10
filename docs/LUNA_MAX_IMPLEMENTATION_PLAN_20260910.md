# 專案查漏補缺與完整實作計畫 — Luna Max 交接

> **狀態：PLAN ONLY／尚未實作。** 本文不是 release certificate，也不是部署、發送 LINE 或變更模型的執行授權。
> 使用者最新指示：停止 build，唯讀查漏補缺，完成計畫後停止；由使用者手動切換 mode 給 Luna Max 才進入實作。
> 本計畫日期：2026-09-10。盤點基準 HEAD：`13bd043986c409ea2aaf54a5820acdc107686ed1`，分支 `fix/options-provenance-audit`／PR37。

## 0. 執行摘要與本輪停止點

目前已具備若干可靠的安全修復、同源 Q&A 證據及 Windows 發行鏈，但還不是完整產品。問題核心不再是多 build 一次，而是：

1. **安裝安全與真正安裝差異**：集中工作區與 runtime 共用外層目錄；安裝器的鏡像複製需要重新審查。候選 ZIP 成功並未更新實際程式鏈。
2. **資料與研究仍不完整**：財務 basis 檢查只是第一層；身份、負債、稀釋、訂單、產能、估值與跨來源獨立性仍需逐公司驗收。
3. **三種內容尚非完整產品**：卡片、資料詳報、因果分析必須真正不同，股票／期權／宏觀都要有實際 producer、封存及讀取路由。
4. **來源免費不等於可再散布**：目前合格 LINE 期權報價供應者仍為零；不得以私人券商資料、付費方案或虛構數字解決。
5. **模型與發布不可錯置**：none 的完整 Q&A 已有合格切片；自動適切 THINK、graded effort、真實安裝後呼叫與完整資料推論仍未驗收。
6. **發送真實 LINE 必須是最後階段**：需要免費用量預算、正確收件者、最新 sealed snapshot、傳送失敗／不確定結果處理，以及实际收件端檢查。

**本輪只讀查核與寫計畫／交接索引；不修任何上述缺口。** 不 build、不測試執行、不 dispatch CI、不呼叫模型、不建立雲端測試資源、不安裝、不恢復排程、不發送 LINE、不清理檔案、不 commit/push、不切換 mode。

完成本文後停止。下一位實作者不得把本文的待辦或預定驗收當成已通過。

---

## 1. 依據、範圍與可信度

### 1.1 此次唯讀查核的事實

| 項目 | 此次觀察 | 邊界 |
|---|---|---|
| Git | 已 fetch；HEAD 如上；開始盤點時 working tree clean | 沒有修改產品來源或執行 build |
| CI | `34422382127` completed/success，來源 `ec03f0443290a623aeb0173388475147d3773856` | 不等於正式安裝、現場資料或 LINE 驗收 |
| 進行中工作 | 查詢當下 repository in-progress／queued workflow 清單均空 | 不保證未來不會由其他人觸發；本輪未取消或新增工作 |
| Runtime 十檔 | 6 different、2 missing、2 equal，重新以檔案 SHA 比較 | 只覆蓋這十檔，不是全 runtime 或 EXE 全面驗證 |
| 两個 task | MorningRefresh／EveningRefresh 均 Disabled，各一個 action，指向預期 installed refresh script | 沒讀出或保存完整 task arguments；沒有啟用或執行 |
| Worktrees | 主線、review-baseline、review-source-views 分離 | 未合併 PR39，未修改其他 worktree |
| Source code | 查讀 installer、財務 extractor、snapshot／compact QA／broadcast、bundle、測試及 workflow | 是靜態盤點；新疑點未跑 RED 重現 |

重新確認的十檔：

- different：`run-v213-scheduled-refresh.ps1`、`scripts/v213_sealed_refresh.ps1`、`scripts/build_v212_top20_report.py`、`scripts/run_v213_local_llm_bridge_core.ps1`、`scripts/v213_local_llm_gateway.py`、`scripts/v213_compact_qa_gateway.py`。
- missing：`scripts/historical_return_evidence.py`、`scripts/v213_model_profile.py`。
- equal：`sync-v213-activation-bundle.ps1`、`scripts/build_v213_scheduled_top20_report.py`。

### 1.2 沿用但本輪未重跑的證據

- Sept10 Q5 none live receipt：`state/r75-qa-live-financial-basis-20260910.json`；由 `state/r75-qa-live-current.ref.json` 精確選取。
- 完整 CI、下載與 archive 獨立 verifier 的通過紀錄見 `state/STATUS.md` 及 `_workspace/audit-runtime/download-34422382127/`。
- 舊安裝隔離驗證、先前 readiness 404／500、KV 日寫入限制、長路徑 FileNotFoundError 等仍保留；本輪未 restamp，也未再驗證 Production 健康或免費餘額。
- PR39 目前入口的三個歷史 evidence 錯誤仍未解決；其較後方的歷史「P0=0／完成」段落不可取代現在的開放問題。

**證據有效性必須在實作及 shipping 時重算。** 本文不複製一份可變 release version 表；release identity 仍以 README 為權威。當前 receipt 的 source／profile／runtime／時間條件若改變，舊 PASS 不再資格化新候選。

### 1.3 已讀的主要依據

- 外層及 source `AGENTS.md`、`state/STATUS.md`。
- `docs/DETAILED_REPORT_CONTRACT.md`、`MODEL_RUNTIME_MIGRATION.md`、`PUBLIC_SOURCE_COVERAGE.md`、`WORKSPACE_MAINTENANCE.md`、`FINAL_RELEASE_PLAN.md`。
- `skills/serenity-public-research/SKILL.md` 及完整 `RESEARCH_METHOD.md`、`CROSS_VALIDATION.md`；只用於規劃方法，不宣称這次已研究新公司或取得新來源權利。
- `.github/workflows/v213-r75-release.yml`。
- 本文各工作包列出的直接 caller／validator／tests。

不是全庫逐行審計。未閱讀、未執行或未重現部分一律不得標記已安全。

---

## 2. 不可變更的工程與費用邊界

1. **現在只准規劃。** 使用者切 mode 前不得實作，即使先前曾授權發送真實 LINE。切換由使用者操作，不自行設定 Luna Max 或其他模型。
2. **Luna Max 是下一個 coding agent，不是 runtime 換模指示。** 產品仍只使用既有 localhost:8080 Router 與核准 exact model；目前 Q5 profile 的 none 資格不延伸到其他 effort。
3. 永遠免費：不付費 API／升級 Cloudflare 或 LINE 方案／付費模型／付費報價／付費 tunnel／試用額度轉收費／另一帳戶規避限額。不接受需要綁卡才能保證工作的設計。
4. 收件者、tokens、cookies、憑證庫、LINE IDs、券商及持倉資料不得進入模型 context、計畫、Git、stdout 或 artifacts。只在獲准的執行路徑內最小化使用所需憑證。
5. 公開 LINE 的資料不得以 IBKR／owner portfolio／私人同步補洞。不執行交易；資料齊備時可提供明確條件式建議，但不虛構可執行價格。
6. 維持 scoring 權重、LIMITED、權利／freshness／provenance／publication gates；不為湊 20 檔、好看的 benchmark 或免費端點失敗而放寬。
7. `cloud/src/storage.ts`、`cloud/src/qa.ts` 及認證的 `activation-v2.ts` 等 protected bytes 不直接修改；如新功能觸及認證契約，使用正式升版與 recertification。
8. 不重播歷史 Production activation。新資料必須 immutable objects → 驗證／readback → pointer-last；replay／rollback／finalize 都要保留。
9. 一位 writer；PR39／baseline 保持隔離。其他 reviewer 只能讀，除非另獲無重疊 worktree 任務。
10. 不新增暫時平行發行工作流；使用既有 authoritative R75 pipeline、共享 validators 及鎖定依賴。
11. 不靠 `.gitignore`、clean checkout waiver、wildcard allowlist、放寬 hash 或清除 output dir 製造通過。失敗 bytes 與 log 原樣保留。
12. Pi 套件如未來確有必要，只能 project-local `pi install -l ...`；此次與預設實作計畫都不要求新增套件或清理 Pi。

---

## 3. 缺口登記冊與優先級

優先級是本次**建議的處理／出貨阻塞級別**，不是已完成 exploit 重現或完整 P0 計數。共列 17 個工作項；整體 P0/P1/P2 總數仍未完成評估，禁止宣稱 P0=0。

| ID | 建議級別 | 狀態與證據 | 風險／完成定義 |
|---|---|---|---|
| G01 | P0 安装阻塞 | installer 直接 `/MIR`，排除名單未包含 `_workspace`／`_archive`；現有測試是新建 sibling 暫存目錄 | 先用隔離 fixture 重現 ancestor／nested／junction／既存資料危害，修復保護，再准實裝 |
| G02 | P0 放行阻塞 | 實際 runtime 6 差異／2 缺失；候選安裝測試不等於現場 | 完整受控安裝、rollback、GUI／child／task action bytes 與行为一致 |
| G03 | P1 資料正確性 | 財務 latest selection 與 debt 計算只選部分資料；新 basis guard 仍有限 | context、currency／scale、restatement、分部、負債及股數可重算；缺漏可解釋 |
| G04 | P1 研究品質 | v21 Yahoo screeners 加權截取 seed；不是 v211 主題配額 caller | 開放 discovery 與逐階排除 receipt；不改最終 scoring 以掩蓋漏候選 |
| G05 | P0 發布阻塞 | 0 合格 LINE option quote providers；其他新來源多為 staged/discovery | 免費使用及再散布權利、同標的同時點品質逐來源通過；否則維持 blocked |
| G06 | P1 功能／資料 | 1 份 TSEM draft；20 家完整 identity／財報／訂單／稀釋／估值未驗收 | 真實一次研究快照，不灌樣本或固定 ticker；未知不當零或亂補 |
| G07 | P0 新功能放行阻塞 | 七欄 evidence action 不是三報告；schema4 只封七 payloads | 三種產物各自生成、封存、按同 snapshot 讀取；跨型／缺檔不 fallback |
| G08 | P0 候選，待重現 | compact QA 自行讀 pointer、stamp、URL；尚未共用全部 modern validators | 實際有效路徑的無效 pointer／衝突 alias／unsafe citation／混輪反例全部拒絕 |
| G09 | P1 模型能力 | manual THINK 有 UI；auto／graded effort 未實作或資格化 | 支援證據、可觀測品質與延遲矩陣；UNKNOWN 留 UNKNOWN、無默默降級 |
| G10 | P1 安全／品質 | 數據進 model 後的 claim attribution、對抗內容與完整答案仍需新報告測試 | 不把來源 prompt injection 當指令；無 unsupported 數字、無 private retrieval |
| G11 | P0 真實發送阻塞 | test slot 不走一般 dedupe；所讀 push helper 未見用量查核、timeout、retry key | audit 上層後補完整免費預算／冪等／不確定結果流程；禁止盲目重送 |
| G12 | P0 正式發布阻塞 | 新 datasets 尚未進 commit／rollback／finalize 契約 | 升版 migration matrix 與隔離交易故障注入全部通過 |
| G13 | P1 可用性 | 新一輪免費 KV 可寫，但歷史 quota／readiness 原因未完整定性 | 有免費資源預算、限速、觀測、停止条件；不以睡眠重試替代診斷 |
| G14 | P1 驗收證據 | final data／THINK／schema 再改就需更新 runtime-bound proof | 先收斂功能再一次資格化，避免逐修補重建所有 artifacts |
| G15 | P1 分支整合 | PR39 保留 evidence errors，與主線不同 HEAD | 獨立 triage→選擇必要 diff→合併後重新驗證，不接納歷史 PASS |
| G16 | P1 文件／交接 | MODEL_RUNTIME_MIGRATION 等仍敘述舊 proof／安裝器狀態；STATUS 有歷史未完成句 | current truth 唯一入口、明確 superseded 註記，不刪原失敗 |
| G17 | P2 維護 | 57 inventory errors、六 Pi registrations、兼容 wrappers 多 | 先證明無依賴／非 unique evidence 再清理；非正式發送前必要工作 |

### 3.1 新靜態發現的技術細節（實作前先重現）

**G01 — 安裝鏡像與工作區安全**

`install-v213-runtime.ps1` 在不同 root 時執行 `robocopy ... /MIR`；目前排除 `.git`、versions、node_modules 等，並無集中工作區保護。`GetFullPath` 與字串 same-root 判斷不等同檔案系統身份／reparse 安全。新建安裝 fixture 不會暴露「目標裡已有唯一資料」或「source 位於 destination 子目錄」的刪除問題。**本輪未執行此 installer，不宣稱已實際刪除任何東西。**

**G03 — 財務語義與證據可追溯**

- `v21_serenity_top20.py::latest_records()` 以 end／filed／accession 排序，`latest_value()` 只用 start 是否存在區分 duration，沒有在這層解決 quarter／YTD、分部或重複 context。
- `annual_values()` 以 `fiscal_year` 分組；應檢查 amendment／comparative facts 的 fiscal_year 與 measurement period 是否對應，不能只依 filing 所屬 FY。
- `metrics()` 的 debt 使用 `LongTermDebtCurrent`、`LongTermDebtNoncurrent`、`LongTermDebt` 清單第一筆；不保證為總負債／總借款，且目前列入 evidence 的迴圈未包含該 debt operand。
- `_same_filing_basis()` 已擋日期／單位／文件差異，但相同 accession 不自動代表相同會計／合併／分部 context。
- `_money_unit()` 目前檢查三個大寫字母的形狀，不是已驗證的幣別 registry，也未證明 scale 一致。
- 不相容的值目前可降為 None，但新詳報需要明確區分 UNAVAILABLE／NOT_COMPARABLE／CONFLICT，不讓資訊原因消失。

**G08 — 未遷移讀取鏈**

`compact-qa.ts::compactPublicContext()` 仍自行處理 `snapshot:current`，以 `run_id ?? runId` 取值，空文字時保留 direct prefix；內部 HTTPS checker 與 shared citation validator 不同。這些是靜態差異，需從真正 `compactGeneralAnswer` caller 重現，而非單測 helper 即宣稱已洩漏。`production-worker.ts` 已對三條 legacy admin direct-write URL 回 410，不能因 `admin.ts` 檔案仍存在就說它們目前對外可寫。

**G11 — 真實 LINE 的免費與不確定結果**

`broadcast.ts` 的 `slot='test'` 直接呼叫 push；`v21/line-push.ts` 已檢查 target 格式與消息形狀，但本函式未見免費訊息餘額、abort deadline 或 retry key。必須先查上層是否已有等效保護，再決定共享層修正；不能把 authenticated admin、HTTP200 或 scheduled dedupe 誤認為所有 send 都安全。

---

## 4. 目標架構與資料契約

### 4.1 單一資料鏈

`免費且獲准來源 → 身份解析／觀察 → claim ledger → reconciliation → 既有 scoring／publication admission → research snapshot → 三產物 → sealed manifest／交易 → pinned read view → GUI／LINE`

股票／期權／宏觀共用 provenance、權利、時間、快照與錯誤規則，但保留各自數據語義，不能拿同一 generic template 代替三領域。

不建立第二套 runtime、快取真相來源、selector 或 release workflow。先擴充現有 `source_observation`／registry／builder／v213 snapshot 介面，確有 schema break 才升版。

### 4.2 規劃中的最小資料概念

欄位名稱由 Luna Max 與現有 schema 對照後定稿，不可照本文直接宣稱已部署：

- **Instrument identity**：issuer_id、security_id、ticker、venue、share class／ADR ratio、法定名稱／譯名狀態、有效起訖、來源。
- **Source evidence**：publisher、lineage、source role、URL、publication／observation／retrieval clocks、精確支持片段、內容 hash、權利範圍與到期／複核狀態。只保存依法允許的內容量。
- **Claim**：claim_id、subject、predicate／metric、value 或 unavailable、unit／currency／scale、measurement period、accounting/context basis、source references。
- **Reconciliation**：CORROBORATED／PRIMARY_ONLY／CONFLICT／NOT_COMPARABLE／UNAVAILABLE；衝突與 superseded 鏈不擦除。
- **Calculation**：formula/version、operand claim IDs、使用的數值／口徑、精度與 rounding、結果或拒絕原因。不得只有漂亮公式而無 operands。
- **Inference**：premise IDs、明確假設、因果邊、反方、falsifiers、多軸 confidence；SUPPORTED 與 INFERENCE 分開，UNSUPPORTED 不入報告。
- **Research snapshot**：唯一 run ID、as-of cutoffs、instrument set、admitted evidence digest、policy/schema versions、每標的資料 completeness。
- **Output manifest**：domain、output_kind、report_id、security identity、snapshot ID、UTF-8 bytes SHA／大小、頁序、claim refs、missing sections。
- **Delivery receipt**：snapshot／manifest／artifact／model-profile identities、時間、結果 enum、非敏感 target role、用量決策、可安全保存的 request correlation；不得含 LINE ID 或原始憑證。

### 4.3 內容驗收不是換排版

| 領域 | card_summary | data_report | narrative_analysis |
|---|---|---|---|
| 股票 | 七欄相容摘要、關鍵日期／風險與獨立入口 | 身份、財報 bridge、產能、客戶／承諾、稀釋、回報與估值、公式／來源／缺漏 | 系統變化→瓶頸→公司捕獲→每股價值→反方→條件結論 |
| 期權 | 有資格才給策略概況／主要風險 | 合約、DTE、multiplier、BBO／Greeks、liquidity、payoff／費用、來源／時鐘 | 為何此策略、情境、指派／股利／跳空風險、何時不交易 |
| 宏觀 | 重要變化、vintage、影響路徑摘要 | 數列、release／period、revision、季調／實質口徑、敏感度 | 總體→需求／供給約束→公司經濟的前提、落差及反例 |

缺少某份產物必須明確 unavailable；不能改查另一公司、改讀最新一輪、重新導到摘要，或省略來源／風險尾段。完整長篇可分頁，但每頁必須有相同 manifest 身分與完整性檢查。

---

## 5. 分期實作與依賴順序

**只有使用者切 mode 後才能開始以下 W0–W12。每個工作包：先 RED／反例，再最小修正，再局部 GREEN／必要整體回歸，最後小 commit。** 不為每個小變更重跑雲端／整份 build。

依賴主線：

`W0 → W1 安全與基線 → W2 財務／身份 + W3 來源／discovery → W4 研究資料 → W5 三產物 → W6 封存／讀取 → W8 本機預演 → W9 最終 release → W10 正式發布 → W11 真實 LINE／排程`

`W7 模型能力` 可在 W2–W6 期間序列化研究，但正式品質測試依賴 W4/W5。W12 文件維護貫穿；清理放最後。不同工作包可先讀審，不代表允許多 writer 或並行大模型。

### W0 — 接手確認與缺陷 triage

**檔案／依據**：兩層 AGENTS、STATUS、本文、README、current QA ref、PR37／PR39 worktrees。

- 由使用者切 mode 後重新 fetch／確認 HEAD、dirty、未完 CI、來源及 installed root；不要覆蓋本次未提交的計畫。
- 把 G01–G17 轉為可追踪條目，記 severity、evidence class、owner、測試、阻塞依賴及 scope。未知總數不得填零。
- 明確列出會變動的檔案與 protected 檔案；以實際 import／caller 判斷 active／legacy／dead，不按檔名猜。
- 檢查 PR39 的必要修正及 evidence failures，不整支合併或重用它的舊資格。
- 後續查核 Production、憑證使用、實裝、發送的執行權限須依當時使用者指令及契約確認；本文不是新的授权。

**完成条件**：明確工作根目錄、可重現風險清單、唯一 writer、無未解的權限／範圍衝突。

### W1 — 安裝安全／runtime 完整鏈（先隔離，不真裝）

**主要 caller**：`install-v213-runtime.ps1`、三個 source-diverse／Serenity installers、`activate-v213-seven-field-schedule-core.ps1`、launcher 安裝入口、R75 packager。
**既有 tests**：`tests/test_installer_model_authority.py`、`tests/test_v213_free_relay_package_payload.py`。

1. 在新隔離目錄重現 `/MIR`：目標含 `_workspace`／`_archive`／operator config／唯一 sentinel；source 為目標子目錄、目標為 source 子目錄；same-root、8.3 alias、UNC／extended path、junction、缺失檔、複製中斷。
2. 選擇受控 manifest 安裝或明確拒絕不安全 topology；不以單純加幾個 exclusions 當完整解法。進入第一個寫入前檢查實際 filesystem identity、reparse 與 source/destination boundaries。
3. 對既存 operator/profile／資料／journal／rollback 採顯式保存規則；不能把 runtime 外的工作區當 managed files。
4. 確認 overlay 後的 canonical bytes 屬於 reviewed release；驗證完整依賴，不只十檔或 EXE。
5. 檔案集合與服務／task actions 使用可 rollback 的協調安裝；故障不能留下混合版本。安裝 metadata 仍不得選模型或證明 qualification。
6. 不更改 protected activation core 來繞过限制；若需升版先列出新的認證方案。

**退出門檻**：PS5.1／7 真正 installer caller 反例通過；sentinels 零損失；中斷後 originals 可恢復；正式 root 從未用作試驗目的地。

### W2 — 財務與身份正確性

**主要路徑**：`scripts/v213_v21_progress_runner.py`、`v21_serenity_top20.py`、`adapters/sec_edgar.py`、issuer_directory／source_observation；tests 對應。

- 身份版本：ticker 重用、更名、上市地、普通股／ADR、官方中文／譯名／未知；禁止永久翻譯表猜公司。
- 日期：原始 end/start/filed 嚴格；加入 measurement start ≤ end、as-of cutoff、未來 filings、period freshness 与 publication freshness 的分別處理。
- Context：quarter vs YTD／annual、instant vs duration、consolidated vs segment、GAAP vs adjusted、units／scale、amendments 與 restatements。
- 金額：非有限、bool、任意 numeric string、負分母／零分母等都以明確契約處理；幣別 identity 與 FX conversion 不混用。
- 負債：先定義 metric 是 total debt 還是 long-term debt；按可證明且不重複的 components 計算，含 source references。不把第一個 tag 當總額。
- 股數：basic／diluted、期末／加權平均、ADR ratio、SBC／warrants／convertibles，各有適用時點與不重複規則。
- 確保每個衍生 operand 都進入 evidence；保留不可比／衝突原因，不只 None。
- 維持評分權重；如果修正資料語義改變結果，給前後差異與原因，不調權重補回舊排名。

**退出門檻**：真實公開樣本 + synthetic 邊界皆可重算；不相容不能相除；舊合法同 basis golden arithmetic 不變；測試從實際 metrics／CLI 到 consumer。

### W3 — 免費來源、權利與動態 discovery

**路徑**：`source_registry.py`、`source_observation.py`、`authoritative_source_catalog.py`、`config/authoritative-sources/`、public-options registry／gate、v21 candidate discovery。

- 先按資料能力建立矩陣：身份、財報、訂單、產能、歷史價格、BBO、macro vintage、新聞線索。分别記 access、terms、redistribution、attribution、delay、quota、retention、adapter、lineage、runtime admission。
- 不把既有 101 catalog 或 116 candidate 的數字視為覆蓋度。新增／啟用來源走原有 gate；必要時正式升版 contract，而非把 reviewed count 放寬。
- 動態 discovery 結合獲准 issuer directories、監管／客戶／產業事件；給每階段 coverage／exclusions。先查 v21 caller 的 weighted T3 seeding，再判斷 v211 legacy 是否仍有別的活躍用途。
- 不永久偏好 AI／某 ticker，不改 scoring、不以 source views 的名人效應加分。
- 公開報導／SEC Companyfacts／issuer release／exchange mirror 的共同 lineage 不重算獨立數量。
- TLS、redirect、SSRF／DNS、port、userinfo、控制字元、response cap、timeout、JSON duplicate、壓縮／XML 等入口規則用共享驗證；拒絕時不 echo 原始憑證 URL。
- 免费 historical data 與 option quotes 若無合法 LINE 再散布來源，保持 UNAVAILABLE。不同交易所、EOD vs realtime、indicative vs executable 不能互相代替。

**退出門檻**：至少達到宣稱功能所需的免費合法能力與真實 caller 證據；逐 claim 覆蓋，而非 endpoint 成功率而已。找不到免費權利則 G05 仍 blocked，不擅自宣告完整功能。

### W4 — 真正的研究快照與 20 公司資料

**依據**：完整研究 skill、`docs/DETAILED_REPORT_CONTRACT.md`、TSEM draft 的內容深度（不是固定候選 seed）。

- 先凍結單一 as-of；保存當時 universe 與各階段納入／排除理由。
- 每家公司：身份、期間財報／cash bridge、產品／產能／有效替代、客戶／集中度、訂單分類、融資／股東捕獲、稀釋、正反方、時序及 confidence。
- 不把 customer relationship 當 bottleneck；不把 prepayment、backlog、RPO、design win、run-rate、management model 加成一個總訂單。
- 歷史 24／6 個月：使用 `historical_return_evidence.py`，补同 instrument、幣別、公司行動、股利／總報酬、交易日／時區、license 及最新 observation 可用性。短區間不能冒充完整兩年。
- 未來 6m／1y／2y：explicit scenario assumptions→收入→利潤→FCF→資金／稀釋→EV/equity bridge→每股值。無資料則不估，不用固定 EPS／倍數／機率或歷史 CAGR 當預測。
- 公開 Serenity source view 需 original passage/date/lifecycle；Leopold 僅 CONTEXT_ONLY。未取得新原文不可聲稱最新立場。
- 20 家逐一人工／獨立只讀 review；不足 20 合格者揭露缺額並阻擋宣稱，不補 fixture 或 stale ticker。

**退出門檻**：一次真實、可追溯 snapshot；每個重大論點有支持／推論／缺漏與反方。允許依法及政策明確表示未知，不等於允許虛构訂單來完成欄位。

### W5 — 三領域 × 三產物

**路徑**：既有 top20 builder／presentation、`company-evidence-report.ts`、`top20-report.ts`、`v211/worker.ts` 授權訊息路由；新 schema 的檔名實作時決定，不先建立第二套 pipeline。

- 先鎖定共同 research snapshot 介面，再分三個 producers；用 data contract 驅動而非先寫通用長文章。
- 卡片保留既有七欄相容性；report links 帶 domain／kind／report／run／security identity／digest。
- data_report 必須包含可重算表格和原始 basis；narrative 必須解釋公司特有的因果、前提、反方与推翻條件。
- 明確禁止三個入口指向同一文字，也不能要求每句都重複不同。測試「內容任務不同」而非只比不同 hash。
- LINE 文字／Flex／分頁使用相同已封存 bytes，測多語、CJK、長 URL、最大消息量、末頁來源／風險保留。
- 新資料未資格化時仍叫 evidence/gaps，不冠名完整研究。

**退出門檻**：9 個 domain×kind cell 各有真實 caller 驗收；缺功能單獨列 blocked，不能只用股票 PASS 宣稱整組完成。

### W6 — 升版 sealed contracts、共享讀取與安全路由

**路徑**：`build_v213_activation_bundle_v2.py::build_bundle`、`activation-v3.ts`／下一個正式版本、`public-snapshot.ts`、compact QA、production worker、sealed refresh／sync、preflight、archive verifier。

1. 決定 versioned manifest 如何承載三產物／options／universe；列出 builder→policy→preflight→commit→readback→reader→rollback→finalize→ZIP 的完整 migration matrix。
2. 不直接在 schema4 的七 payload 外偷寫新 direct keys；舊讀者需明確 compatible／reject，不可部分理解新格式。
3. read context 一次 pin pointer＋claim；驗證 object bytes／digest、報告 identity、合格授權與 clock。SHA 相符不等於有發布授權。
4. compact QA、各種 Top20／detail／broadcast／legacy callers 逐路遷移；區分 pointer 缺失、空字串、null、invalid、衝突 run_id/runId；malformed 不得 resurrect legacy。
5. 更新一半、併發發送／pointer 切換、物件缺失／遭改、claim 不符、readback lag、過期 snapshot 都拒絕混輪。
6. 保留 active route 的 legacy single-object 410；不用刪除 compatibility files 證明關閉。
7. 序列化 transaction scope，immutable objects 完整驗證後最後提交 pointer；rollback 僅可恢復該 transaction 的 exact originals；finalize 前保留 recovery handle。

**退出門檻**：fail-closed 矩陣及隔離 KV transaction/replay/rollback/finalize 全部通过；protected hashes 未變或已正式 recertified。

### W7 — 模型能力、自動適切 THINK 與輸出品質

**路徑**：launcher、shared model profile Python/Worker validators、bridge cores、local／compact gateways、live QA gate。

- 先定義任務類別與衡量指標：資料抽取、計算檢查、因果分析、反方、短問答。最佳只能指測過的任務／預算，不能泛稱最強。
- 在原 Router／核准 exact model 上序列 probe；除 none 外先判 declared support，再觀察是否有完整答案與品質差異。任何未證明的 minimal～max 均保持 UNKNOWN／UNQUALIFIED。
- 不輸出或保存 reasoning transcripts；保存 effort、timing、finish state、可公開答案 rubric／錯誤類別與 profile/hash。
- cold model load、已載入但 prompt-cache cold、warm request 分開；不得靠 warmup 把 cold-load 宣稱為通過。
- auto mode 只能在已資格化集合做顯式策略選擇，提供 task class／selected profile／依據；改 profile 即使是降到 none 也不是偷偷 fallback。
- 不支援或超時時 fail closed／要求明確 operator 決策；不能換模型、改 timeout／token budget 或 preset 製造 PASS。
- 檢查命令注入、上下文注入、來源文本 prompt injection、偽造 claim refs、錯數據計算、截斷／reasoning-only、HTTP200 空答案。

**退出門檻**：機器可讀能力矩陣＋任務 rubric＋完整 caller EXE→PS→gateway→Worker→reference completion；UI save、模型 endpoint healthy 或 marker 不替代品質驗收。

### W8 — 離線整合與現場安裝預演

- 功能收斂後才執行一次完整本機回歸；早期每個工作包先跑相關 tests，節省免費資源與編譯成本。
- 驗證 actual user-facing callers，不僅 formatter／擷取字符串；Native PS5.1／7、compiled EXE 流程與每個 installer 各自測。
- 全套：security／documentation／workflow supply-chain／Actions storage／KV isolation／owner LINE delivery gates；完整 Python、Worker、typecheck。
- 最终 ZIP 在隔離 runtime 安裝；simulated existing workspace 的保護／rollback 不能只靠空目錄。
- 檢查外層 AGENTS 不會被 source-only instructions 覆蓋；_workspace／_archive 永遠不是市場輸入或 runtime payload。

**退出門檻**：所有確定 P0 關閉，完整 inventory 可對帳；剩餘 P1/P2 逐項說明與是否允許出貨，不把 UNKNOWN 寫成零。

### W9 — 最終來源凍結、免費 live proof、Windows／ZIP 驗證

- 先凍結 source／schema／profile，再安排一次有預算的 isolated live proof；必要故障診斷與 qualification 分開輸出、禁止覆寫。
- 在任何會消耗 KV／模型／LINE 用量的動作前估算、限制與保留安全餘額。quota 不足就停止，等免費額度恢復；不換帳戶或升級。
- verify cleanup/source/preset unchanged；精確 committed reference，≤允許 freshness、runtime manifest 相符。無效 ref 永不 newest-file fallback。
- 新 receipt 走 exact reviewed path admission；可用回歸防漏，但不開 state wildcard、不動 protected baseline。
- 只跑 authoritative R75 full workflow；CI delivery/Production mutation flags 維持 false。
- 產物以 exact SHA／run ID 命名，ZIP／receipts／QA sidecar／checksum／manifest／SBOM 綁定；長路徑以可靠 filesystem semantics 處理，不忽略讀取失敗。
- 下載後用可信 source verifier 驗實際 ZIP；再做下載物的隔離安裝，不拿 CI 產生的 PASS JSON 當獨立驗證。

**退出門檻**：fresh proof＋Windows self-hosted＋immutable archive＋獨立 download／receipt／install 全部一致。這仍不是真實 Production 或 LINE PASS。

### W10 — 正式協調安裝與新鮮封存發布

此階段會改正式狀態，只有所有前置條件及當時有效授權都明確後執行。

- 先確認原有 journal／rollback 狀态及兩 task 保持 Disabled；不列印 token 或收件者。
- 從已驗證 ZIP 安裝完整鏈，保留 operator settings／資料與可回復 originals；不只換 EXE，不拿實際 root 做故障試驗。
- 實際 GUI save／Test reply／source refresh child 必須使用同模型 profile／同 runtime bytes。操作人 profile 與 package 不一致時明確停止。
- 完成一次真實免費資料更新與 W4/W5/rights admission；失敗不更新 last_success、不 carry-forward 舊 options/universe，不以 NoSync 稱已發布。
- 新 bundle／new transaction only；完成 readiness/version、seal verification、pointer-last、readback/claim/object equality、rollback/finalize。
- finalization 前後的失敗恢復策略已由隔離演練證明；不得為表面一致把新的資料降回舊版本而不留狀態。

**退出門檻**：正式 installed chain／Worker／profile／新 snapshot 對齊，資料仍新鮮，沒有半更新；尚不啟動大範圍或週期推送。

### W11 — 真實 LINE、免費預算與恰好兩個排程

- 先確認現在使用的 LINE／Cloudflare 方案、免費餘額與計費邊界（用獲准的最小只讀查核，不讀出憑證）。無法證明不會產生費用就不發。
- 驗證已配對且授權的 operator direct-chat target、channel 所屬、仍可收件；不得猜 ID、列印 ID、發到 group／room／所有 followers。
- 透過既有 authenticated 路由發送最小完整代表性消息；不可繞過應用 guard 直接 curl LINE API 以製造成功。
- 保護 test slot：單次 operation identity、服務支援的 idempotency、局部 timeout、模糊送達時查核而非重發；不保證不存在網路不確定性。
- 記錄 `attempted`、`provider_accepted`、`delivery_unknown`、`observed_received` 等分層結果。HTTP200 僅代表服務受理；未見實際裝置／對話呈現不得聲稱已讀或視覺驗收。
- 在合法控制且不暴露他人訊息的收件端，確認摘要／詳報／分析按鈕能讀到同輪內容，分頁與來源／風險完整；若沒有可用收件端觀察，保留 blocked，不能偽造截圖或 receipt。
- 真實 LINE 驗證後，只恢復：`InvestorIntelligence-v21-MorningRefresh` 與 `InvestorIntelligence-v21-EveningRefresh`。其他 task/service 不動。
- 核對台北08:00／21:00 的 refresh→publish→push ownership，Windows tasks 與 Worker cron 不重複發送；需成功新鮮資料才允許推送。任意手動 run 不等於真正 scheduled trigger。
- 觀察兩個 slot 的實際 scheduled execution；task action、exit/result、snapshot run、dedupe、LINE 結果一致。錯過時段等待下一次免費正常排程，不造歷史 clock PASS。

**退出門檻**：有真實 LINE 受理與收件呈現證據、無私人資料、無付費、無重複；兩個實際排程完成。若仅 API accepted 或僅一個 slot 完成，記錄部分驗收，不宣稱全部完成。

### W12 — 文件、維護與最终交付

- 將 MODEL_RUNTIME_MIGRATION／bilingual status／STATUS 中 obsolete 的 current 宣稱修成歷史／指向唯一 current reference；不要到處複製 version／PASS 表。
- STATUS 保持≤12000 bytes，AGENTS≤6000、skill≤4000；保留历史 Git reference，不刪 immutable failure receipts 來省空間。
- 新 receipt path 不應讓下一次發行又漏 allowlist；維持 exact review 與 regression，而非對整個資料夾放行。
- PR39 如有必要整合，整合後 evidence source/hash／policy／tests 全部重新對帳；未合併不代表遺失，亦不能宣稱其缺陷已解決。
- Pi／舊 wrappers／歷史 directories 清理非 critical path；只有 ownership、dependency、junction、uniqueness、reproducibility 全確認才做。
- 最終交付列：已完成、實測證據、剩餘 defect counts、已知限制、免費配額行為、回復方法、如何檢查完整報告／排程。不得用某次 hotfix PASS 當全產品完成。

---

## 6. 測試矩陣（未執行，供實作時排程）

| 範圍 | 必要正例 | 必要反例／故障注入 | 必須測的實際邊界 |
|---|---|---|---|
| Installer | 合法新裝、受控 upgrade、完整 chain | nested roots／junction／8.3／既存唯一資料／copy中斷／overlay缺失 | 四 installer callers + packaged installer |
| 身份／財務 | 同 context、annual／52/53 week、正確 amendment | ticker reuse／ADR、Q vs YTD、unit／scale、segment、debt duplicate、future filed、非有限值 | SEC adapter→metrics→report |
| 權利／provenance | 獲准 source + 正確 lineage | UNKNOWN／expired terms、mirror充數、wrong role、SSRF URL、credential URL | collector→admission→activation |
| 報酬／估值 | 日曆範圍完整、可重算情境 | 停牌／上市不足、缺末價、corporate action不明、幣別差、負盈餘套PE、稀釋重複 | 實際 builder CLI |
| 三產物 | 同 snapshot、內容任務不同、全頁可讀 | 缺報告、unknown ticker、跨domain／kind、截掉風險、同文冒充三份 | 真按鈕→授權router→reader |
| Snapshot／交易 | 全物件完整後 pointer commit | invalid/null/alias conflict、改hash／claim、partial put、并發、stale、replay、rollback冲突、finalize失敗 | production Worker實際 route + isolated KV |
| 模型 | exact profile、完整答案、rubric合格 | HTTP200無答案、reasoning-only、unsupported effort、profile drift、timeout、prompt injection | EXE→PS→gateway→Worker→reference |
| 免費用量／LINE | 餘額明確且足夠、單一允許target | quota未知／耗盡、錯channel／unpaired、group／room、超長message、受理後斷線、重送 | 實際send caller；早期用synthetic sink |
| 排程 | 兩個實際slot、fresh snapshot | 延遲cron、NoSync、refresh失敗、model不在、double scheduler、sleep/resume | installed task actions + Worker dedupe |
| Release | exact-source fresh proof及ZIP | expired／tampered ref、wrong source/run/model、archive missing file、long path、dirty checkout | authoritative CI + independent downloaded bytes |

單元／mock 測試、native process、隔離 live、正式 installed、真實 LINE 是不同層級。不能把其中任一層的 PASS 往上繼承。

---

## 7. 免費資源策略與不可完成時的處理

1. 設定每次開發／驗收的 request、KV write、模型 token／時間、artifact storage、LINE message 預算；以當時實際免費方案限制為準，不在文件硬編可能過時的額度。
2. 所有 collector 有明确 payload／timeout／rate 限制；只有來源允許的 conditional requests／cache reuse。失敗不能更新 last-success，也不重刷舊內容的 freshness。
3. build 與 QA 先局部後全量，功能凍結後再 fresh proof／full CI，避免對每個文件或小修補重建雲端。
4. quota／服務狀態未知與確定不足分開。讀取查核本身也需在預算內；診斷新 run 永遠不改寫舊 FAIL。
5. 沒有合法免費 option feed、沒有新鮮資料、免費 LINE quota 不夠、無法驗證收件者時：保留功能 unavailable／出貨 blocked；不改用付費、不偽裝完成，也不擅自把目標刪掉。
6. 本計畫不保證所有外部限制一定能在免費條件下解除。若需要使用者縮減產品範圍，必須列出缺失與影响並取得明確決策，不能由 agent 自行降規。

---

## 8. 最終 Definition of Done

以下全部滿足才可稱完整正式版；否則只回報相應 slice：

- [ ] 已知 P0 已逐項結案，整體 inventory 可稽核；不是 UNKNOWN→0。
- [ ] 實際 installed root 的完整程式／依賴／profile／GUI／task action 驗證；受保護工作區及operator資料未被覆寫。
- [ ] 真實、合法、可追溯的研究 snapshot；20 家資格及缺漏透明；未造公司、訂單、EPS、歷史報酬或目標價。
- [ ] 股票／期權／宏觀各三種產物真正不同、同輪封存、實際入口可讀；未完成 cell 不冒充完成。
- [ ] 新 sealed schema 的製造、驗證、發布、讀取、replay、rollback、finalize 全鏈通過。
- [ ] auto THINK 與被允許 modes 的能力／任務品質／延遲可證明，無 silent downgrade。
- [ ] 安全／文件／workflow／Python／Worker／typecheck／PS5.1/7 全套通過；source-bound live proof 新鮮且受信。
- [ ] exact-source Windows、不可變 ZIP、獨立下載／archive／receipt／隔離安裝驗證通过。
- [ ] 正式新資料已發布並 readback；沒有舊activation replay或NoSync冒充publication。
- [ ] 真實 LINE 以核准 target 與免費額度發送，結果分層保存，收件呈現／按鈕驗證完成。
- [ ] 恰好兩個指定排程恢復，兩個真實 slot 完成，無重複發送。
- [ ] 所有已執行流程沒有付費替代／方案升級／越權憑證或私人券商資料流入。
- [ ] README release identity、STATUS 現況與原始 receipts 一致；原失敗保留。

## 9. 本輪審計紀錄與交接停止指令

**已執行（唯讀）**：Git fetch／HEAD／status／worktree；CI 歷史與 queued/in-progress 查詢；文件與 caller／tests 閱讀；十檔來源／安裝 hash 比較；兩個指定 task 的狀態、action 數量及預期 script 布林檢查。

**未執行**：任何 build／測試程序／模型推論／CI dispatch／cloud API provisioning／installer／sealed refresh／Production讀寫驗證／LINE send／task enable／cleanup／mode switch。未讀出憑證庫、raw LINE ID、broker data。

**文件變更範圍**：本文及 `state/STATUS.md` 的 planning-only 交接索引。沒有產品程式修改。未 commit 或 push；保留給使用者切 mode 後檢閱。

**停止點**：計畫完成即停止。Luna Max 接手的第一步是 W0，不能直接執行 W9 build 或 W11 LINE，也不能因前一輪的發送授權而跳過這次最新的 planning-only 指令。
