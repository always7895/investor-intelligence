# 專案查漏補缺與完整實作計畫 — Luna Max 交接

> **狀態：ASTRA REVIEW A／更新計畫後停止。** W0 文件與 W1 局部 guard 已提交；完整 W1／rollback 尚未完成。本文不是 release certificate，也不是部署、LINE 或換模授權。
> 最新指示：Astra 查漏補缺並更新本 PLAN，之後交給 Luna Max；本輪僅唯讀查核與文件更新。Luna Max 續作須遵守「非預期狀況或疑問立即停止，交 Astra 裁決」。
> 日期：2026-09-10。原始盤點 HEAD：`13bd043986c409ea2aaf54a5820acdc107686ed1`；本次 Astra 已 fetch 的實際 HEAD：`59bcd41f9b3164c8c88efc0c989f60b993f454a1`，開始查核時 working tree clean。
> **續作順序以第10節為準：先 W1-A0～A7，不得跳 W2、build 或正式安裝。** 第1節保留原始盤點切片，不是最新全面驗收。

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

### 1.1 原始13bd043盤點的事實（本次 W1 審查見第10節）

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

1. **本次 Astra 回合只准查核與更新 PLAN。** 交接後 Luna Max 依第10節續作；任何非預期失敗／疑問立即停止，不自行選方案、修 fixture、改預期或重試。只有事先列明且符合 oracle 的預期 RED 是正常開發步驟。mode 由使用者切換。
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
| G01 | P0 安装阻塞／未關閉 | 59bcd41 增加 guard，局部案例 PASS；ownership／path identity／copy 語義及交易仍有缺口 | 第10節 A01–A12 先重現／修正；不可把 guard PASS 視為 W1 結案 |
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

原始13bd043版本在不同 root 時直接 `/MIR`，沒有集中工作區保護；Luna 的隔離 RED 後續重現 runtime sentinel 被刪除，非正式資料損失。59bcd41 已加 topology／reparse／同名路徑 guard，保留局部 GREEN，但並未完成 ownership 或交易保證。Astra 本輪只讀程式／既存 logs，沒有執行 installer；新增發現與既定修正方向見第10節。

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

- 接手後重新 fetch／確認 HEAD、dirty、未完 CI、來源及 installed root；辨認前次已提交 W0/W1 與本次文件修訂，不能誤稱未提交修補，也不能覆蓋交接文件。
- 把 G01–G17 轉為可追踪條目，記 severity、evidence class、owner、測試、阻塞依賴及 scope。未知總數不得填零。
- 明確列出會變動的檔案與 protected 檔案；以實際 import／caller 判斷 active／legacy／dead，不按檔名猜。
- 檢查 PR39 的必要修正及 evidence failures，不整支合併或重用它的舊資格。
- 後續查核 Production、憑證使用、實裝、發送的執行權限須依當時使用者指令及契約確認；本文不是新的授权。

**完成条件**：明確工作根目錄、可重現風險清單、唯一 writer、無未解的權限／範圍衝突。

### W1 — 安裝安全／runtime 完整鏈（先隔離，不真裝）

**主要 caller**：`install-v213-runtime.ps1`、三個 source-diverse／Serenity installers、`activate-v213-seven-field-schedule-core.ps1`、launcher 安裝入口、R75 packager。
**既有 tests**：`tests/test_installer_model_authority.py`、`tests/test_v213_free_relay_package_payload.py`。

1. 在新隔離目錄重現 `/MIR`：目標含 `_workspace`／`_archive`／operator config／唯一 sentinel；source 為目標子目錄、目標為 source 子目錄；same-root、8.3 alias、UNC／extended path、junction、缺失檔、複製中斷。
2. **方案已裁決：受控 manifest＋完整 staging＋單一 coordinator／journal 的受隔離切換**，依第10節落實。禁止直接 copy 覆寫 live root 再期待 backup restore；不以加 exclusions 當完整解法。第一個寫入前檢查 filesystem identity、reparse、ownership 與 source/destination boundaries。
3. 對既存 operator/profile／資料／journal／rollback 採顯式保存規則；不能把 runtime 外的工作區當 managed files。
4. 確認 overlay 後的 canonical bytes 屬於 reviewed release；驗證完整依賴，不只十檔或 EXE。
5. 四個 caller 的 base／overlay／驗證只在同一 staging transaction 執行；僅最外層 coordinator commit。metadata、runtime 與外部 activation 分別列 rollback 狀態；兩次 rename 不是跨目錄／跨檔案 atomic transaction。安裝 metadata 仍不得選模型或證明 qualification。
6. 不更改 protected activation core 來繞过限制；若需升版先列出新的認證方案。

**退出門檻**：第10節的 full-caller、path／ownership、crash／recovery 與 consumer isolation 矩陣全部通過，相關全套回歸完成；sentinels 零損失。正式 mixed root 從未作試驗或 swap 目標；完整 W1 未驗收不得進 W2。

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

## 9. 原始規劃回合審計紀錄（13bd043；最新見第10節）

**已執行（唯讀）**：Git fetch／HEAD／status／worktree；CI 歷史與 queued/in-progress 查詢；文件與 caller／tests 閱讀；十檔來源／安裝 hash 比較；兩個指定 task 的狀態、action 數量及預期 script 布林檢查。

**未執行**：任何 build／測試程序／模型推論／CI dispatch／cloud API provisioning／installer／sealed refresh／Production讀寫驗證／LINE send／task enable／cleanup／mode switch。未讀出憑證庫、raw LINE ID、broker data。

**文件變更範圍**：本文及 `state/STATUS.md` 的 planning-only 交接索引。沒有產品程式修改。未 commit 或 push；保留給使用者切 mode 後檢閱。

**原始停止點**：原計畫完成即停，之後使用者曾授權 Luna 開始 W0/W1。該階段提交2cd14b7／59bcd41，尚未完成 W1；目前停在 Astra 審查。接下來以第10節交接，不把原始 planning-only 的歷史敘述當成現在 W1 尚未修改的證明。

---

## 10. Astra Review A：W1 缺口裁決與 Luna Max 續作指令

**本節優先於原 W1 中尚未定案的選項。** 它提供明確的設計方案，不代表程式已修、測試已跑、正式遷移已獲准。W2–W12 的資料／免費／發布門檻維持不變。

### 10.1 先校正交接事實

1. Astra 已重新 fetch：HEAD=`59bcd41f9b3164c8c88efc0c989f60b993f454a1`，進入本輪時 working tree **clean**。W0 計畫已在 `2cd14b7` 提交；W1 installer／test／validator／STATUS 已在 `59bcd41` 提交。上一輪結尾「未提交修改仍在工作區」不符合目前 Git 狀態，不得沿用。
2. 只讀了既存結果：`w1-boundaries-tests.log` 5 tests OK；`w1-authority-tests.log` 2 tests OK；`w1-current-lane-tests.log` 11 tests OK。本輪沒有重跑。這些不是 full Python／Worker／Windows build，也不是完整 W1 或 current ZIP qualification。
3. 原始 `/MIR` RED 確實記錄隔離 sentinel 被刪；早期錯誤還包括 unittest module 載入、fixture 缺 identity、命令 quoting、路徑分隔符及 NUL split。全部保留；不要把 fixture failure 算成產品 RED，或把後續 GREEN 改寫前次 FAIL。
4. 當下 queued／in-progress CI 查詢為空。本輪沒有 task／runtime／Production／LINE 變更，沒有讀取憑證庫或執行 installer。
5. **W1 狀態：PARTIAL／NOT ACCEPTED。** G01/G02 未關閉；下表列12個 W1 子項，不額外灌成12個已確認 P0。除已留存的具體反例外，新增疑點是靜態發現，下一位須先重現。

### 10.2 W1 子缺口與處置

| ID | 審查結果 | Luna 必須採取的處置 |
|---|---|---|
| A01 | handoff／STATUS 的「未提交／待 commit」與59bcd41不符，且局部 guard 被概括成 ownership PASS | 接手先核對 HEAD／diff；使用本節 PARTIAL 狀態，不 reset／重播 commit |
| A02 | `Get-V213ManagedRelativePaths()` 以新 source 的相對檔名集合當 ownership；同名可覆蓋 operator 改過的檔案；三個 generated receipt 只依名字例外 | ownership 必须来自先前可信安裝紀錄＋舊 effective manifest／實際 bytes／root identity，不是新檔案同名或 marker 存在 |
| A03 | `/MIR` 仍直接寫目的地；base 完成後 wrapper 可再 copy／失敗；base 提前寫 AppData metadata | 統一 staging transaction，所有 overlay／validators完成後才由外層 commit；任何內層不得更新 live／metadata或宣告整體 PASS |
| A04 | drive/share root 尾分隔符及 `StartsWith` 拼接、extended/device/UNC 表示、existing ancestor 是 file 等尚無完整證據；HashSet 回傳可能被 PowerShell pipeline 展開 | 明確 filesystem admission、root canonical identity及集合型別；測0／1／多元素與case；不用字串看似相同當 filesystem 證明 |
| A05 | reparse pre-scan 與 copy 間仍有 TOCTOU；hardlink 非 reparse；tree scan 未見界限；metadata父目錄未纳入同等前置檢查 | 鎖定、ACL／identity recheck、link政策及有界 inventory；unknown／不可讀／變動即拒絕，不跟隨外部物件 |
| A06 | guard 只跳過第一層 excluded 名稱，robocopy `/XD` 的目錄匹配與之不同；`/XF` 依basename會作用於子目錄，未綁實際 generated paths | 以一份精確 typed manifest 定義 copy／保留／generated paths，測 nested dependencies；移除靠同名例外的管理語義 |
| A07 | same package reinstall 通過不代表升版、已修改同名檔案、半途失敗或舊layout可以復原 | 增加不同 old/new fixture manifest、碰撞、process kill、磁碟不足、rollback failure；禁止只測新空目錄 |
| A08 | activation core 先 deploy／commit cloud pointer，再 install/register tasks；catch有 pointer/task/config/Worker restore，未見完整 runtime tree及installer metadata restore | 以版本化 coordinator 整合 local prepare/commit/rollback/finalize；舊core不能用註解或 `production_restored=true` 證明本機已恢復 |
| A09 | `v213_operation_lock.ps1` 使用 `Local\...` mutex；當前 cross-process test 不證明跨Windows session／服務帳號；abandoned lock也不等於沒有未決交易 | 延伸共享 lock協定覆盖實際mutation participants及session；先恢復／阻擋未決journal，不把取得鎖當新裝许可 |
| A10 | boundary tests 以shell缺失時continue；8.3假設always不同；junction cleanup未檢查exit；部分名稱宣稱before-any-creation但沒檢查metadata/local目錄 | 收斂fixture oracle及前後inventory；環境缺能力標SKIP/BLOCKED，必需的native acceptance不准靜默PASS；精確檢查cleanup |
| A11 | `test_v213_windows_security.py` 只抽取robocopy第一行，現在命令已多行；其測試也繞過新的guard | 必须測實際共享copy/installer caller或完整AST範圍，不以擷取第一行／補預期文字掩蓋回歸；先保留真實RED |
| A12 | 前輪遇到非預期fixture／命令錯誤仍自行修與重跑，不符合使用者要求 | 嚴格採10.9停止協定；只有事前列明的產品RED／故障注入可以照計畫進行 |

補充證據限制：legacy `VERSION-REFS.json` 存在時會跳過 HOTFIX-REFS 的該段檢查；這不代表已驗證 package bytes。installer 應把既有可信 archive verification 接到不可變輸入，而非信任任意 identity JSON。不得為測試 synthetic package 放寬真實發行的 trust chain。

### 10.3 決策 D1：選 staging；不選直接覆寫後 restore

**正式採用候選方案1的受控版本：完整 staging＋單一 transaction coordinator＋journal＋隔離切換。** 不再讓 Luna 在兩個方案間自行選擇。

- source 僅讀；所有 managed code、config模板及四caller所需 overlays，都先組裝至新的唯一 staging 目錄並完成驗證。
- 活躍 root 不作 `/MIR` 目的地，不先逐檔覆寫 live 再用 backup救援。若有 bounded copy工具，只能用於本交易新建且未被consumer使用的 staging。
- 新／舊 generations 分別完整，切換只處理受管理的專用 runtime；原 generation 保留作 recovery，不把全家目錄複製到不明備份位置。
- **兩次 rename（live→old，stage→live）不是單一 atomic directory exchange。** 各次rename及metadata replacement只能在已驗證的檔案系統條件下提供其個別語義；中間可能缺 live path，跨 metadata／Worker／KV 更不是一個原子事務。
- 正確承諾是：切換期間 consumer 不可讀新舊混合內容；任一中斷有可辨識、可拒絕使用、可復原的狀態。不能承諾未知平台上的斷電零風險或無停機。
- backup／old generation 是 recovery input，不是另一個 live server；不新增 junction／symlink作 live alias、不啟第二模型或第二永久 runtime。
- rename因檔案鎖、ACL、不同 volume 或其他原因不能安全完成時 **fail closed**；禁止自動退回方案2（直接copy live）、force-unlock、UAC、搬資料或改ACL。

#### 支援拓撲與舊 runtime

1. 第一版只接受可證明本機、同 volume 的受管理 NTFS 切換。source 可位於另一 volume，但 stage/live/old/journal的交易位置必須符合定案的同volume與identity條件。
2. same-root、ancestor/descendant overlap、drive/share root、reparse根／祖先／子項、跨volume切換拒絕。UNC/SMB/遠端或未知檔案系統先回明確 UNSUPPORTED；本輪不以UNC正例迫使擴張範圍。
3. `\\?\` 本機長路徑與8.3是表示法，不是另一個root：先驗證namespace、canonical volume/file identity再比较；`\\.\` 等device namespace拒絕。不能僅刪prefix或小寫化字串。
4. 新裝只在獲准的不存在／空專用目標進行；空目錄也要驗證owner／ACL／ancestor／file identity。存在非空目標只有可信舊manifest、receipt與實際bytes／身份一致才可升版。
5. **正式 `D:\Investor-Intelligence-LINE-Pi` 是 mixed-use root，含 `_workspace`／`_archive`，不准整棵 rename/swap／mirror／建立 ownership marker把它收編。** W1只用隔離fixture。W10須另有該實際layout的顯式遷移mapping及授權，不能因預設 `%LOCALAPPDATA%\InvestorIntelligence\V213Runtime` 可用就自動把排程或資料改指那裡。
6. 舊 runtime 無可信 ownership，或含 mutable cache/data／operator檔案／未知檔案：保持原樣並回 MIGRATION_REQUIRED／OWNERSHIP_UNPROVEN，不自動收編或刪除。獨立專用候選可先組裝，但這不等於完成舊layout升級。
7. 不掃描 `_workspace`／`_archive` 全樹來證明它們不屬於 runtime：先辨識reserved roots並拒絕不合格安裝拓撲。不能在實際root試錯。

### 10.4 決策 D2：四個入口，一個 transaction owner

保留四個公開入口名稱及現有 ProjectRoot／RuntimeRoot 基本介面：

- `install-v213-runtime.ps1`
- `install-v213-source-diverse-runtime.ps1`
- `install-v213-source-diverse-runtime-v2.ps1`
- `install-v213-serenity-latest-runtime.ps1`

將其收斂成明確profile的薄入口，委派**同一個共享 installer coordinator**。此模組屬於既有R75流程，不是新的平行installer產品或release workflow。

- coordinator先產生有序安裝plan（base→所選overlay→全部validators→effective manifest），再執行一次transaction。共用phase是內部函式／不可變context，不再一層公開wrapper呼叫另一層公開wrapper而各自commit。
- 每個profile保留自己的相容性／marker與實際驗證義務；Serenity-latest歷史fixture不能當當前R75資格。輸入／profile不相容即在prepare前拒絕，不自動選更寬鬆profile。
- 内部phase只准寫coordinator提供的staging scope；不dot-source整份有副作用的base installer以借用其變數，不共用任意全域RuntimeRoot，不接受任意journal／backup path作跳過驗證的公開flag。
- 不新增 `-Force`／`-SkipOwnership`／`-SkipValidation`／`-IgnoreRollback` 類bypass；testing fault injection只能在受控fixture／內部test seam，不得讓production CLI繞過流程。
- 所有final validators必须針對**overlay後**的實際bytes，而不是base中途結果、presence或幾個字符串。
- standalone正常安裝由coordinator完成local verify／commit／finalize才回 local-install PASS；若外層activation需持有rollback，回結構化 PREPARED／COMMITTED_PENDING_FINALIZE，不輸出誤導的整體PASS。
- 內層不得寫 `%LOCALAPPDATA%\InvestorIntelligence\v213-runtime-state.json`、runtime外的profile或正式receipt；metadata在交易commit階段由唯一owner寫，根路徑指final runtime，不指staging。
- PUBLIC installer通過不等於release_qualified=true；preferred_model=null、model_selection_authority=runtime_model_profile、model_profile_qualified=false繼續維持。

#### Manifest與ownership

- 區分 archive原始檔案manifest、所選overlay後effective immutable file manifest、generated non-secret metadata。不能期待被overlay替換的canonical file等於archive原位置檔案；必須綁到明確source file／digest／profile transformation。
- manifest每entry需精確相對path、file/directory類型、size/hash與role；拒絕絕對path、`..`、ADS、case-colliding或正規化後重複entries、超量／過大inventory及未知檔案類型。
- `source有同名`不構成destination ownership。升版讀可信**舊manifest**對照舊bytes，並驗root identity、app/profile及receipt；新manifest只描述新generation。
- marker或 `V213-RUNTIME-MANIFEST.json` 檔名只是尋址，不是自我認證。偽造／未知／僅schema正確的marker不能認領資料。
- expected old bytes被人工改過、或unknown file插入時停止；不以「目標在產品目錄內」授權覆蓋。metadata缺失也不等於可重建成功receipt。
- 不從live root複製不受管dependencies到stage。對目前 `cloud/node_modules` 等依賴先辨識真正runtime用途：僅驗收依賴應留在隔離測試scope；執行必要依賴須綁hash-locked provisioning／manifest，不能因目錄叫node_modules就信任。無法歸類就停交Astra。
- 應有manifest self-hash規則，避免manifest把自己的digest再遞迴納入；effective manifest digest由外部transaction/receipt綁定。

### 10.5 決策 D3：鎖、journal、metadata與crash recovery

#### 鎖與存取隔離

- 先在共享 `scripts/v213_operation_lock.ps1` 框架內設計participant鎖協定，不另做互不認識的臨時mutex。`Local\...` mutex不能被稱為跨session保證。
- coordinator需對將修改的runtime root及non-secret metadata位置取得跨process/session有效的exclusive ownership。不同runtime如果共用同一metadata也不能同時寫；不能只把root+metadata拼成不同pair的鎖名而漏掉共享資源。
- 採受保護、精確定位的participant lock files／排他handles等可驗證機制，固定排序取得locks以避免deadlock；不得降低ACL至Everyone或自動提權。可重入只限同一transaction/context，不能依單純depth或同PID讓其他operation進來。
- 無權取得、scope不支援、有人執行、abandoned lock或存在未決journal：回BUSY／RECOVERY_REQUIRED；不能直接當新裝開始。
- 所有新路徑reader／launcher／refresh需有維護barrier或generation pinning；未升級的consumer無法配合時，W1只驗fixture，W10必須明確停妥相關project程序後再切換。不擅自停止Router、其他runner或任意同名process。
- locked EXE／仍開啟的檔案無法rename时拒絕，不強制關閉不明process。journal/recovery程式必須由live root之外的可信來源執行，避免root暫時缺失時無法復原。
- pre-scan後可能變動，必須在copy/rename/rollback前重查root/parent identity與manifest；針對可寫來源先建立驗證過的不可變staging input。hardlink/link-count或其他無法排除外部alias的物件預設拒絕。無法排除非協作writer即停止，不宣稱單靠lock防住任意管理員變更。

#### 狀態機（名稱可與既有 schema 對齊，語義不可削弱）

| 狀態 | 所有權／允许動作 | 中斷時的默认行为 |
|---|---|---|
| PREFLIGHT／LOCKED | roots、scope、來源／舊bytes與未決交易查核；尚未寫stage/live/metadata | 拒絕即零live／metadata變更；鎖本身的建立須有預先驗證的位置 |
| PREPARED | journal綁transaction、paths/identities、manifest；完整stage及所有overlay validators PASS | 舊live／metadata保持；stage不可被reader選用 |
| COMMIT_INTENT | 持久寫入將採取的rename步驟與expected identities；再次比對舊live／metadata | reader維持barrier；recovery讀指定journal，不找最新dir |
| OLD_RETAINED | 舊live已rename到本transaction的old generation；可能暫無live | 根據實際old/stage/live identities判定；保守恢復verified old，不以空live判新裝 |
| NEW_PRESENT | stage已成為live，但metadata可能仍舊或未寫 | 尚不可serve；對新live再驗digest，完成或精確rollback |
| LOCAL_COMMITTED_PENDING_FINALIZE | local root與metadata一致；outer activation尚可要求回復 | 舊generation與metadata original保留；普通consumer未全面放行前不結束barrier |
| FINALIZED | 完整caller／必要外層coordinator接受同一transaction | 只表示本次協定的成功；不表示LINE／排程或全產品完成；backup依保留政策不立即刪 |
| ROLLED_BACK | old root identity/bytes與old metadata存在／不存在狀態已readback一致 | 回失敗但記已驗證恢復，不寫安裝成功receipt |
| RECOVERY_REQUIRED | 任何不符、disk/ACL失敗、ambiguous state或恢復失敗 | 保留old/new/journal、barrier與原始錯誤；非零退出並停交Astra |

- 每次破壞性操作前必須有durable intent，後有實際結果記錄；journal寫入本身需bounded schema、duplicate/type/path檢查、atomic replacement與flush策略。原始FAILED試驗證據另外immutable保存，不因journal狀態推進而改寫。
- crash可能落在OS操作成功但journal未更新之間。recovery必須比對實際directory/file identities、digest與該transaction預期，不能只信最後state字串。
- journal recovery入口用exact transaction/reference選取；沒有可信reference就RECOVERY_REQUIRED，禁用「挑最新backup／掃所有tmp猜一個」。
- 原live不存在時，新裝失敗須回到原不存在狀態；只可移走／隔離本transaction證明擁有的新generation，不得刪除後來出現的不明同路徑資料。
- live→old或stage→live任何一步失敗都不自動降級copy。若old移回也失敗，留recovery資料並停止，不回 `production_restored=true`。
- 不以finally無条件刪stage/backup；只釋放本次持有的handles/locks。失敗generation隔離保留，cleanup另依ownership、evidence與W12安全協定執行。

#### metadata也屬transaction

- 只處理明確schema的non-secret installer metadata；不備份／dump整份UserData、DPAPI/token/cookie設定或credential-store。
- 在受保護交易區保存原metadata的**存在狀態與原始bytes**及需要保留的ACL等資訊；若内容不符合可安全保存的schema，停止，不把未知設定複製進journal。
- 新metadata用同transaction綁定，先安全寫temp再replacement。跨volume metadata不宣稱與directory rename原子；使用journal的participant狀態精確恢復。
- rollback只在當前metadata仍是old或本transaction預期new時恢復原bytes／原不存在狀態；若已被其他writer修改，回RECOVERY_REQUIRED，不能覆寫對方資料。
- original不存在不是「刪除目前這個檔即可」：必須先證明目前檔仍由本transaction寫入。
- code root、metadata、Worker、pointer、tasks各自有驗證結果；整體成功／恢復要所有必要participants一致，不用單一bool掩蓋局部失敗。

### 10.6 決策 D4：舊 activation 與 mixed root 的處置

靜態查核 `activate-v213-seven-field-schedule-core.ps1` 的實際順序是 cloud commit 後再 install／register tasks。其catch未提供本機完整runtime／installer metadata rollback，且會宣稱production_restored。**不要在這個core外加try/catch就假裝已達分散式原子更新。**

- W1先完成純本機coordinator及外層協定的mock/fixture契約；不調用舊core去Production測installer。
- W10採版本化協調入口整合 `Prepare → local/remote commit orchestration → Verify → Finalize`，local rollback與Worker/pointer rollback各自回傳完整結果。舊core保持歷史契約；新caller wiring、manifest、preflight、allowlist、tests要一同review／recertify，不能直接放寬protected checks。
- 在remote變更之前完成所有可離線完成的local prepare／ownership／stage檢查。跨local／cloud不是ACID：必須有maintenance fence、明確次序、故障補償與readback，不承諾不存在部分成功。
- 若任何後段local／remote驗證失敗，保持consumer／發送barrier，按journal只回復該transaction所有受影響participants；一項無法驗證就整體RECOVERY_REQUIRED。outer finalize之前local不得丟棄rollback originals。
- task activation從此與installer commit分離；W10不得呼叫會提前啟用排程的舊路徑，W11才准恢復恰好兩個指定tasks。task與資料原始狀態要按實際scope保存／核對，不藉驗收重播Production歷史狀態。
- 實際D: mixed root遷往何處、mutable data/config該如何保留、現有task/launcher如何改指，仍是W10前需提出的**顯式現場遷移計畫**。目前只裁決「不得whole-root swap／不得自動收編」，不授權搬動現場或替使用者指定新正式根。

### 10.7 W1-A0～A7：具體續作順序

每步都有退出條件；Luna不得一次把所有架構猜完後直接跑大build。

| 步驟 | 允許的工作 | 退出條件 |
|---|---|---|
| W1-A0 | 重新fetch／HEAD／dirty／既存logs；確認本Review A修訂；將A01–A12對應具體tests/檔案 | 沒有未識別dirty變更或authority衝突；承認59bcd41只局部PASS |
| W1-A1 | 先建立ownership、root/path/exclusion及A11真實caller回歸RED；重用既有fixture技巧但不吞環境錯誤 | 失敗確實到達目標assertion；fixture準備錯誤不算RED，須停Astra |
| W1-A2 | 落實D1/D2的共享manifest／context與四入口thin adapters；去掉對live的mirror／內層metadata寫入 | 四種profile有效輸入能完成stage；overlay任一步失敗舊root／metadata完全不變 |
| W1-A3 | 落實D3的participant locks、journal、commit／rollback／resume、metadata記錄 | root/metadata/cross-session競爭及每個mutation邊界故障矩陣通過；不將catch當crash proof |
| W1-A4 | 新generation驗證與read-barrier；外層activation prepare/commit/rollback/finalize介面採fixture驗證 | consumer只能完整舊／完整新或明確blocked；outer fail也能恢復，tasks仍未真啟用 |
| W1-A5 | existing tests整合：native copy、四installers、model authority、package/allowlist/完整依賴；未知檔案／operator同名修改等 | 保留既有安全與相容義務；不刪反例、不開wildcard，legacy lane不被當新資格 |
| W1-A6 | 局部通過後跑工程契約要求的完整離線gates／Python／typecheck／Worker／PS5.1/7；必要時僅獲准Windows validation-only | 所有command exit與skip原因記錄；任何非預期失敗立即停止，不自動repair或dispatch full build |
| W1-A7 | 更新STATUS與本節結果；小reviewable commits；只讀獨立review | G01候選反例關閉、W1退出條件全通過、尚未完成的mixed-root遷移/Production門檻明确。才可申報W1完成並按主線進W2 |

檔案範圍：四個installer、共享installer/lock模組、相應tests、packager/validator的必要依賴與exact-path admission、STATUS/本PLAN。新共享模組的檔名可依repo命名慣例定義，但不得生出第二個自動工作流、直接改certified core、或跳到實際migration。遇到需擴張此範圍先停Astra。

### 10.8 必要驗收矩陣與更精確的 oracle

下列都是**待執行**項目；已有5個boundary tests只能cover其中少數。

| 類別 | 必測情境 | oracle（不只比error字串） |
|---|---|---|
| 新裝/升版 | 新專用root、可信old→不同new、四profiles、多次重入 | effective bytes/receipt一致；只有最外層一次commit；重入不得另啟第二transaction |
| ownership | 同名但old bytes被改、偽造marker、未知dir/file、old manifest缺／衝突、新manifest移除舊檔 | before-first-mutation拒絕；sentinel／原metadata存在狀態不變，不重新收編 |
| 拓撲 | same-root、雙向nested、drive root、share root、source missing、parent為file、mixed `_workspace/_archive` | 不深入保護tree、不create live/metadata、不mirror；明確unsupported／overlap |
| alias/namespace | native/8.3/本機extended同identity、case差、near-prefix但不同dir、UNC/SMB/device | 同物件不能當獨立source/live；合法near-prefix不被誤判；未知FS不進copy |
| link/競態 | source或dest/metadata ancestor junction、子項link、dangling link、hardlink、scan後替換 | 不跟隨外部target；有界時間／inventory；無法證明即blocked |
| 集合/複製語義 | 0/1/many entries、大小寫、typed directories、nested node_modules、generated同basename | HashSet不被pipeline意外轉型造成不同語義；copy完全按同一精確manifest；原依賴保存義務或有明確遷移，不吞舊測試 |
| stage失败 | 缺overlay／hash不符／validator不通／來源中途改／磁碟不足 | live、metadata原bytes/absence未變；stage failure不打印overall PASS |
| rename/crash | 第一rename前後、第二rename前後、journal前後、metadata replacement前後kill fixture子process | 新process用exact transaction恢復；不依finally；實際 identities與journal能對帳 |
| rollback失败 | old移回被鎖、new被外部改、journal torn/missing、backup identity不符、metadata第三方改 | RECOVERY_REQUIRED、原始錯誤保留、zero盲目刪除／覆寫／自動重試 |
| locks/consumers | same target雙installer、共用metadata不同target、GUI與service sessions、reader多檔讀取中切換 | 互斥、固定lock順序、無混輪；無可用cross-session測試環境時native acceptance標BLOCKED |
| metadata | old present/absent、合法non-secret、未知schema、父目錄reparse、I/O失敗 | original raw bytes/absence按本transaction恢復；不用新JSON序列化冒充原bytes；不dump settings |
| 外層失敗 | stage成功後remote失敗、local commit後outer驗證失敗、finalize失敗 | 全participants逐项readback；task仍Disabled；pending/failed不誤報complete |
| 回歸 | `test_v213_windows_security.py`、installer model authority、full payload、PS5.1/7 | 測真正caller與所有參數，不抽第一行、不刪測試、不把synthetic PE當真的EXE驗收 |

Fixture規則：

- 先設好合法且明確標為synthetic的package identity／必要檔，確保到達要測的產品邊界；不能用缺檔導致拒絕就宣稱topology guard通過。
- missing shell／沒有short-name／權限不允許junction等屬環境能力：清楚SKIP/BLOCKED並停交Astra決定；不能簡單continue後讓suite顯示全PASS，也不能自行提權開功能。
- junction cleanup必須檢查exit與link消失，外部target sentinel保持；不能finally無視失敗後讓TemporaryDirectory递迴碰外部target。
- 每項before-write反例都檢查live root、LOCALAPPDATA metadata、protected fixture dirs及stage/journal（若已允許建立）的實際前後狀態。test名稱不構成證明。
- 熱路徑不跑實際installed script；只執行新建隔離fixture內的版本。child kill只能針對本次fixture的精確PID／context，絕不按process name清場。
- 分開保存各次log，exit code如實記錄；不得把失敗的Python退出用`exit 0`包裝成總成功。negative harness可期待非零，但其scope與oracle必须明確。

### 10.9 停止與交接協定（使用者要求，非可選）

**可照計畫繼續的失敗**：執行前已列明、fixture正確、到達目標產品assertion且符合预期的RED／故障注入。這些是正常實作步驟，不是忽略錯誤。

**下列任何一項立即停止**：

- unittest載入錯、syntax／quoting／NUL解析錯、fixture未備妥、unexpected exit/error code或未預期assertion。
- permission、short-path／filesystem行為與計畫不符、unknown data、cleanup不確定、非fixture資源受影響。
- 要更換設計、新增fallback、改欄位語義／測試期望、放寬guard、擴張檔案範圍、改protected caller／schema。
- runtime/metadata/journal/remote state無法對帳、lock不支援實際sessions、same-name process歸屬不明。
- 碰到免費quota或權利不足、需要付費／提權／新帳戶／不同模型，或有其他未定問題。

停止後只准做最小唯讀狀態確認、保留日誌／原始bytes與已明確可安全完成的本次fixture清理；ownership或cleanup本身有疑問則保留，不再猜。不得自行修一行、重跑、切換方案或繼續下個工作包，即使修法看似顯而易見。

交接報告固定包含：HEAD/dirty檔、W1-A步驟、原預期、實際結果/exit、log路徑、受影響scope、已完成/未完成cleanup、是否有任何正式變更、需要Astra裁決的單一問題。勿貼secret／raw identifiers。使用者切Astra并給出修訂方案後，Luna才依更新PLAN續作。

### 10.10 本次 Astra 回合結論／交接

- **已裁決**：staging＋shared coordinator＋可恢復journal＋consumer isolation；直接覆寫live後restore不是fallback。metadata必須參與交易；兩次rename不是整體atomic；mixed outer root不准whole-tree swap。
- **已校正**：59bcd41已提交且本輪起始clean；W1目前僅局部tests PASS，不是ownership／完整rollback／full regression或最新release PASS。
- **已發現並納入**：A01–A12；包含shared lock跨session、native copy test多行回歸、canonical path/collection/exclusion語義、raw metadata恢复及舊activation未restore本機runtime等。
- **本輪只做文件**：只讀Git、code/tests、既有logs、CI清單；不執行任何新的tests/build/installer/provisioning／LINE／task／model／cleanup，不修59bcd41產品程式，不commit/push。
- **Luna下一步**：使用者交回後先W1-A0→A1，核對本次PLAN/STATUS文件diff；不先改rollback code，不直接進W2或重跑full CI。若實作發現任何新問題，遵守10.9停止。
