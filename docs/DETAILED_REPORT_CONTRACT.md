# 卡片摘要與深度報告：資料驗收要求

這是待落實的資料／介面要求，不是已完成的深度分析或新發布資格。

## 已確認的缺口

現行七欄 schema2 沒有中／原文法定名稱、起訖價格與實際區間、逐筆訂單、完整財報、稀釋股數或情境估值。`numeric_total_order_estimate_prohibited=true` 仍有效。不能用模板、代號翻譯表、年化報酬乘二、固定 EPS／倍數或猜測訂單填滿畫面。

原卡片「完整文字版」全部送出 `Top20 文字`，實際只是同一七欄的文字格式。候選入口已改為「證據詳情」，並綁定公司、生成時間、快照標記及所儲存 UTF-8 七欄來源報告的 SHA256；同日期換內容、重新序列化或換輪都須更新卡片。讀取後的資料凍結，單純 formatter 輸入不產生可點詳情。這仍不是完整深報，也沒有封存三份不同輸出；下述新版 selector 另核對已提交的儲存物件集合，不把卡片內容 SHA 當來源真實性。

## 同一資料基礎、三種不同輸出

- 卡片：少量核心數字、日期、口徑、重要風險與公司專屬報告入口。
- 完整詳細資料報告：財報、產能、客戶／合約明細、資料日期／單位、可重算公式、情境表、來源及缺漏，供逐項查核；不是七欄文字重排。
- 完整文字分析：以問題→證據→因果推論→反方→條件結論展開，解釋資料代表什麼、何時成立及如何被推翻；不再逐欄貼卡片或整張資料表，也不為篇幅加入空話。必要數字可引用，但需增加有依據的解讀。
- 三者出自同一份驗證後研究資料，分別生成／儲存；以輸出類型區分 card_summary、data_report、narrative_analysis。每份參照包含 snapshot run ID、report ID、內容 SHA256 及標的身分。三個入口不可指向同一份文字；缺少詳報／分析時不得重導向摘要冒充。
- 快照汰換時拒絕把新報告冒充舊卡片內容；若沒有保留且允許讀取的原快照，就請使用者更新卡片。未知標的不得改查其他公司或未封存直接鍵。
- 同次查詢的報告與pipeline時間戳必須固定使用同一快照讀取上下文，不能各自重新解析pointer而混輪。現有pointer為空值、無效結構或衝突身分時，應拒絕讀取，不可冒充「不存在」而退回直接鍵。現行Top20查詢及排程候選路由共用 `v213/public-snapshot.ts`；排程的排名／報告／時間戳／防重複鍵固定同輪。缺少成功時間戳不得用生成時間代替；新鮮度使用實際執行時鐘，不用延遲cron的名義時間。`storage.ts` 公開讀取相容出口已委派同一 selector；私有函式及 `qa.ts` 不改。現行授權問題的整段處理共用一次 selection；其餘舊 entrypoint／外部直接呼叫仍需逐一核對 scope 或重新認證。卡片輸入 SHA 綁定不取代 sealed claim 完整性與三輸出封存。
- 詳報可分頁，但不得悄悄刪除尾段、來源或風險來迎合 LINE 長度限制。沒有完整資料時只顯示「證據／缺口」，不冠名完整分析。

### 明確產物要求不得降級（拒絕路由，不是三產物交付）

實際合成 activation→已配對簽名 webhook 反例：`Top20 數據詳報`／`Top20 深入分析` 仍送七欄 Flex；宏觀詳報落入即席模型回答，期權詳報也未保留要求的產物類型。原 RED 保留。

- 現行 `v213Top20LineAnswer` 在既有七欄／QA 路由前，共用 `research-product-request.ts` 的明確命令辨識。保留 stock/options/macro、card_summary/data_report/narrative_analysis、查詢代號／Top20 與週／月期權；不猜公司法定名稱、CIK、私有清單或完整證券身分。代號須完整吻合既有 parser，不將畸形或過長代號截成另一家公司。
- 支援例如 `Top20 數據詳報`、`股票 T00 深入分析`、`T00 每週期權 數據詳報`、`宏觀 完整文字分析`，以及對應 machine kind；可用「產物 標的」或「標的 產物」形式。單獨 kind 不猜領域／標的。這是有限明確命令文法，**不是全部自然語句、模糊／多產物要求或任意舊 entrypoint 的分類認證**。
- 現行 sealed set 尚無這三種獨立產物；辨識後明確回覆 `RESEARCH_PRODUCT_NOT_SEALED` 與所要求類型，不讀候選／直接鍵、不另選快照、不呼叫模型冒充。植入 `complete=true` 或 `publication_eligible=true` 的未封存物件不能啟用它。沒有假 manifest、資格開關、產品按鈕、可執行報價或新發布通道。
- `Top20`、`Top20 文字`、原卡片綁定的「證據詳情」，以及一般宏觀／Serenity／個股分析問題繼續原本路徑與門檻；例如「分析 CPI 與 FOMC 對航運的影響」不是正式產物命令。拒絕訊息僅告知可**另行要求**七欄摘要，不自動改送它。簽章／直接對話／免費 sender、認證 `qa.ts`、private 實作不變。
- 三領域×三類型的 parser 控制全是 **unavailable**，不是九格內容已完成。下一步仍須合格来源／權利與實質研究、正式 versioned 產物 admission/seal、同輪 subject/kind/run/report/content SHA 驗證與完整分頁，之後才可新增 LINE 可用入口。本修補不能代替這些工作或真實收件驗收。

### 已提交快照的逐物件完整性（不提高資料資格）

實際 activation→Top20 查詢反例：封存後改寫報告，舊 reader 仍顯示新文字並賦予新內容 SHA。現行 `activation-v3.ts` 與 `public-snapshot.ts` 共用 `snapshot-seal.ts` 修補：

- Upload schema4、七個原始 payload、簽名與來源／LIMITED／freshness gates 不變。新增 `snapshot:<run>:v213:snapshot-seal:v1`（manifest schema1／contract `v213-stored-snapshot-v1`），逐一綁定**實際驗證／轉換後儲存的13個物件**，包含 ranking、衍生 scores/source views、plan、三個 report aliases、pipeline stamp、五／七欄報告、federation、independence、activation claim。加 manifest 共14個物件；原始 upload digest 與正規化 stored digest 分開，不能互相冒充。
- Pointer升 schema2，精確綁定 run、transaction、manifest UTF-8 SHA、public-data-as-of、promotion time 和公開邊界。每個物件≤2MiB、總集≤8MiB、manifest≤8KiB；控制文件要求 Worker 原生 JSON.stringify spelling，重複／escaped重複鍵、BOM、非有限／非整數 byte count、異常 UTF-16、額外／缺少物件均拒絕。這是現行固定控制格式，不宣稱通用 JSON canonicalization。
- 在任何 mutation 前建立／限制物件集合；manifest 隨全套寫入、讀回，既有執行時鐘門檻通過後才 pointer-last，pointer 必須精確回讀。正常 replay 只驗證、不寫入／更新時間；缺 manifest、舊 pointer 或內容不符不能就地補 seal。已 finalize／無對應 journal 的現行 run 不重建 rollback handle。
- Selector 先核對 pointer→manifest→全部13個物件的 bytes/size/SHA、claim run/transaction、pipeline stamp，再交出 `integrity=sealed` 的固定 view。同次 answer 僅用已驗證 bytes，不重新取得物件，也不讀未列入集合的 key；任一成員缺失／改動使整個 view unavailable。這不自動證明 HTTP 原文、報價權利、財報 context 或當下 freshness，消費端仍須原本的時間與內容門檻。
- Finalize 先重新核對所有物件及精確 current pointer，才刪 journal；失敗保留 handle。Rollback 仍只按授權控制恢復原 pointer bytes，**不保證舊 pointer 可通過新版 reader**。任何版本遷移須新鮮的新交易，不能拿舊 activation 重放／改 pointer 取得資格。
- 舊 metadata pointer（schema1）、transaction-format run ID 缺 seal、留下 claim／manifest 卻改成簡化 pointer，都不能降為 bootstrap。真正無 pointer 或非交易格式的歷史簡化 pointer 保留明示 `integrity=legacy` 相容讀取，**不是新封存接受證明**。歷史 activation-v2／單檔 helpers 不改；公開 storage 相容出口按下節移植，但不把所有舊 caller 或 legacy 資料宣稱為已封存／已重新認證。
- Trust anchor 仍是受控 PUBLIC_CACHE 的 committed pointer；這不是抵抗能同時重寫 pointer/manifest/全部 objects 的特權攻擊者之簽章，也不是 KV 串列化、跨交易鎖、原子讀取或 native Cloudflare certification。雲端沒有新增候選財務產物／options keys、可交付三產物入口、配額或 Production 操作；明確要求尚缺產物時採上節拒絕路由。

合成 KV／日期、假免費 entitlement／provider acceptance、legacy compatibility 與真實來源／原生交易／手機收件是不同驗收。新版實際 ingestion→讀取→既有推送 caller 有獨立測試；舊未封存 fixture 的時鐘／呈現／防重複控制不得冒稱新封存或 exactly-once 收件證明。

### QA 公開讀取移植與單一問題 scope

- 實際反例：舊 `storage.publicText` 令未修改的 `qa.ts` 顯示封存後被改寫的報告；compact reader 則信任被改成 HIGH／EVIDENCE_QUALIFIED 的 audit。兩者現在都經現行逐物件 selector，不用另一套 pointer parser。`storage.publicJson/publicText/snapshotStatus` 保留 API；加密、epoch、記憶、工作與刪除函式不改。
- `scopePublicSnapshot(env)` 建立新 env 副本及 module-private lazy state，不在共用 Worker env／KV binding 上快取。現行 `processAuthorizedLineEvent` 在授權／限流與早期本機控制之後，為**每個問題**建立一次 scope；報告路由、研究、deterministic／general QA 及其非同步 completion 共用它。併行讀取共用 pending promise；invalid／rejected 結果也保留，不因 pointer 變更而在本題內重試或修復。下一題／事件重新選取。
- Sealed view 使用整套已驗 bytes；legacy scope **只固定 pointer，不能保證舊 mutable bodies 不變**。直接呼叫函式若未建立 scope，每次讀取仍獨立驗證，不可宣稱跨呼叫同輪。這不是分散式鎖、KV 原子性或任意舊 worker 的全面遷移。
- `compactPublicContext` 先驗共同 view 再取 stamp／audit／Top20，保留投影、LIMITED、freshness 門檻與 model profile；新鮮度改用讀取／驗證後的執行時鐘，避免等待跨過截止仍拿函式進入時刻報 FRESH。原 stamp 不變，歷史-clock 反例不是 fresh-source proof。只有原有 absent-pointer bootstrap 或新 sealed view 可進該投影；不把非交易 legacy pointer 新增為 compact admission。純方法問題仍不讀市場快照。投影交給原 `qa.ts` 的記憶內 virtual KV 僅含固定精簡內容／stamp，沒有持倉／期權鏈／任意 raw report，也不冒充另一份封存。
- `qa.ts` bytes、認證的 privacy guards、模型／免費 transport 與 LINE sender 不改；舊憑證不等於新依賴行為已完成 live recertification。新增 actual ingestion→signed paired webhook 證明只用合成資料及 model／LINE doubles：改寫後的當前問題不呼叫模型；同一題不混輪，下一題可讀新輪。非法簽章不啟動公用讀取或模型。這不是實際模型答案／LINE收件／來源權利證明。
- 相容 H6B2 的舊 transaction-format 未封存 fixture 明確拒絕；歷史 preview／order controls 另標 legacy synthetic，未改其內容 SHA 或 sender。不得將這些控制當成當前可發布報告。

### 最終排序與候選檔綁定（本機；不是封存交易）

既有 Serenity pipeline 在多次評分／正規化後，仍由 `v213_finalize_rank_coupled_order.py` 完成最終名次對齊，不新增平行工作流。中間步驟可能已改寫五欄報告，舊 companion 此時**不匹配且不可使用**；不得跳過最終驗證，或把單一階段 PASS 當成完整產物就緒。

- 預設要求同目錄既有 return evidence、financial evidence、financial products 三份候選；自訂 producer 輸出須以同名 CLI 旗標提供確切路径。缺件、重複／硬連結／reparse／非普通檔、私有擴充或錯誤成員拒絕，沒有舊版／摘要 fallback。
- 以先前 product manifest 的 ticker 順序還原**僅名次／排列**。只接受 `build_v212_top20_report.json_bytes` 得到的完整原報告 UTF-8 SHA 與原 financial basis 精確相符，且原 products 通過既有 validator；任何欄值、原始時鐘、cutoff、主體或 header 改動均不能借用舊依據。不猜原檔空白、不從已四捨五入摘要反推數字。
- 更新三份候選對最終報告的 hash／snapshot binding；ticker/kind 的穩定 report ID、內容／分頁 SHA、原始運算元、日期、來源、缺漏及失敗狀態保留。新取得時間、評分、HTTP 資料、sealed run ID、發布资格均不產生。
- Return companion 另核對封閉 schema、原始起訖價／日數公式與顯示投影；失敗窗口不從兩價救回。這只驗證**提供給 finalizer 的本機輸入**與算術，沒有獨立綁定其歷史 HTTP body，也不證明整段歷史選點、價格真實性、權利或原始 provider acquisition。比率相同不能證明原始價格來源；mutable hash 不是認證。
- 先以既有五欄 schema 驗證原始輸入（含 rank 型別／序列），不能先修好錯誤 rank 再驗證。全部五份 rank-coupled 文件及三份候選驗證後，再檢查輸入未變，逐檔替換、五欄報告最後、核對實際磁碟 bytes；未變時不寫。不再以記憶體排序冒充 readback。中途失敗不回報 PASS、不假裝 rollback，不自動修復不匹配的半寫入候選。
- **沒有跨檔 atomicity、consumer lock、TOCTOU 防護、耐久原件／journal／recovery 或發布資格。**部分替換仍可能存在，須保留失敗；既有完整輸入 validator 必須拒絕不匹配。正式三產物封存／pinned reader 尚未接入，不能把此候選操作當 Production pointer-last transaction。

### 已接入 CLI 的財務部分產物（未封存）

既有 `build_v212_top20_report.py` 現在透過 `company_financial_products.py`，另輸出 `.financial-products-candidate.json`。不增加 collector、模型或發布通道；現行 LINE 七欄卡片／證據入口不變。

- `card_summary`：少量財務比率、各自期間及重要限制，**不是取代七欄的正式新卡片**。
- `data_report`：逐項列出利潤率分子／分母，以及現金流／PPE支出／股份基礎給付／加權股數的原始值、XBRL tag、單位、start/end、filed、accession、公式與結果，保留未取得／不相容／衝突狀態和來源。
- `narrative_analysis`：同分母營益率／淨利率比較，另可根據同文件現金流／PPE支出、CFO／正淨利、稀釋／基本加權平均股數展開條件解讀、反方及推翻條件。沒有利潤率仍可有數據支持的現金流或下節流動項目比較；所有組件皆缺少可比較輸入才 `UNAVAILABLE`，不改送摘要。利息、稅、營運資金等只是待查原因，不作已證實歸因。

輸入為原報告與財務依據的固定 UTF-8 bytes，先核对 SHA、標的集合、cutoff、公開邊界及既有計算規則；保留失敗狀態，不因重算可得就將衝突重新放行。每個產物與分頁都有型態、report ID、ticker／CIK、兩份輸入 SHA、內容 SHA 和候選 snapshot 身分。分頁完整重組原文；CJK／非BMP字元按 UTF-16 長度計算，超限拒絕而非刪去末頁風險／來源。CLI 寫後回讀並用相同規則重建比較，這是本機一致性檢查，不是獨立來源審查或跨檔案原子交易。

目前 `scope=financial_evidence_only`、`complete=false`、`publication_eligible=false`、`snapshot_run_id=null`。候選 snapshot ID 不是正式 run ID；不得用這些產物、列數、不同 SHA 或段落長度宣告完整三產物完成。完整現金流調節／產能／客戶訂單／融資稀釋條款／情境估值、完整證券身分、來源新鮮度與權利，以及股票／期權／宏觀各自的完整內容仍待補齊。只有正式升版並通過封存／讀取驗收後，才能給 LINE 可用入口；禁止從候選檔偷接 direct key。

## 股票：逐欄資料與計算

### 公司身分

保留 ticker、交易所、證券／股別、CIK／LEI／交易所公司識別、原文法定名稱、中文名稱、名稱生效日期、來源。中文名稱區分官方中文、經審核譯名、未知；不得把品牌當法定實體、把 ADR 當普通股、憑 ticker 猜譯或硬編一張永久公司表。更名、拆股與 ADR 比例需有版本和時點。

### 歷史報酬

保存實際起訖交易日期／價格、幣別、公司行動處理、現金股利與再投資口徑、資料來源和取得時間。缺少完整兩年歷史就標記不足，不以較短區間冒充。

- 累積價格報酬：`(P_end / P_start - 1) × 100%`。
- 年化：`((P_end / P_start)^(1 / actual_years) - 1) × 100%`，年長慣例須明確，例如實際日數／365.25。
- 六個月：以明確的六個月起點及交易日對齊規則計算，不能把兩年 CAGR 除四。
- 調整價格代理、未調整價格報酬、含息再投資總報酬要分別標明；缺少口徑不能一律叫「總報酬」。單憑已四捨五入的 CAGR 且未知實際區間，不能精確倒算兩年累積報酬。
- 費用、稅與匯率若未計入，須明確揭露。歷史績效不作未來情境的預設成長率。

### 已實作的計算候選，不是已交付資料

`build_v212_top20_report.py` 現在共用 `historical_return_evidence.py`：以最新實際觀察日往回24／6個日曆月，選目標日當天或之前最多7天內的最後可用觀察；月底／閏年採日期夾限，年化用實際日數／365.25。不再把600／120天不足區間標成兩年／六個月。這是明示的資料對齊規則，並非交易所行事曆認證。

原CLI同步產生 `.return-evidence-candidate.json`，保存實際起訖日／調整價、累積與年化報酬及對應報告檔案SHA。缺值、重複／逆序日期與非有限數值失敗關閉；不插值或以舊有效價格偷偷替換缺失的最後觀察。保留來源調整、股利、幣別及交易所行事曆未驗證狀態。

候選檔 `publication_eligible=false`，不加入現行公開七欄或 sealed payload。報告檔案SHA不是完整run／sealed發布證明；市場權利、當前交易時段新鮮度、幣別及封存升版仍須完成。此修復不代表已重新取得20檔真實歷史價格，也不代表LINE已交付累積報酬。

### 獲利、現有訂單及未來訂單

財報保留期間、單位、幣別、GAAP／調整後、合併／部門口徑及來源。

現行 v2.1.3 SEC 轉換入口已加入嚴格日期反例：SEC 的 end／start／filed 日期不得截取前綴救回畸形字串；只有同一文件 URL、tag、期間的 filing date 能對應原證據，同一鍵日期衝突即失敗。另一文件不能替缺少 filing date 的資料補上較新日期。缺少日期仍維持未知，不以取得時間補造。利潤率與既有負債比率另檢查同期間、幣別、文件／accession；缺漏或不一致即留未知，不以兩邊都缺失當作相符。年度營收成長須為相鄰完整日曆年度或52／53週年度、同單位及同標籤；保留原本已報導數字公式，不冒充週數標準化成長。這仍不等於完整負債組成、重編／會計政策、部門口徑或全部財報重算已驗收。
**報告入口的口徑候選修正：**前段 preselection 的暫時 metrics hook 不會傳到另一個 Python 報告程序。`build_v212_top20_report.py` 現在明確使用 `profitability_evidence`／既有 `publication_aware_metrics`，再由排程七欄 builder 沿用摘要；不再用舊計算重新混除期間、幣別或文件。合法同口徑算式不變；零淨利率標示損益兩平。選中數值互相矛盾、數值型別不符、CIK／公開 SEC locator 不符、缺少或超過 cutoff 的 filing date 等保持未知，不能用另一個舊數值補回。

同一 CLI 另產生 `.financial-evidence-candidate.json`，以原報告 UTF-8 SHA 綁定，保存每项利潤率及年度營收成長的全部分子／分母、公式、原始值、單位、start/end/filed、accession、CIK 及公開來源；不受舊五筆 citation 上限截斷。缺少／不相容／衝突各留狀態，不保留上次成功計算冒充本輪。數值為 ratio，顯示百分比須乘100，不把四捨五入摘要當輸入。CIK 是發行人識別，不是完整交易所／股別／ADR 身分。

此檔仍為 `publication_eligible=false`，不是三個完整產物或 sealed payload。CLI 的 company schema4 承接 schema3，保留同次 SEC receipt 的原始取得時間、URL、body SHA、CIK、adapter records SHA及 `DIRECT_HTTP`／`BOUND_CACHE`；無 receipt 則未知，`source_refresh_verified=false` 不改。純財務 helpers／舊版公司候選及內嵌 cashflow schema1 未自行取得來源，不另造時鐘。產品核對 receipt／顯示值參照及原始算式，不代表已獨立逐fact核對 HTTP 原文或最新揭露完整性。cache 不冒充本輪 HTTP；財報 context、重編、單位登錄、完整營運／融資／估值仍待補齊；SEC API 與 filing 仍只有一個揭露血緣。新檔禁止直接接雲端鍵／完整詳報入口；七 payload 名稱及交易協定不變，新封存須另通過下述時間門檻。

### 既有公開 JSON 取得／快取邊界

`v21_serenity_top20.get_json` 的 SEC reference、Companyfacts 與既有 World Bank 序列共用同一修正，不新增 collector 或改評分公式。

- 僅允許三類已審核的精確 HTTPS URL；SEC 使用既有有效聯絡設定，不記錄 request headers／聯絡內容。關閉 ambient proxy／netrc、cookies、redirect 與 transport retry；403／429 封鎖同一 session 後續同來源家族請求，不能改用 SEC 的另一端點試過關。獨立 World Bank 來源不因此停用。不增加訂阅、權限或付費 fallback。
- 僅 HTTP200、JSON content type、UTF-8、無重複鍵／非有限數值、符合來源外層形狀及 CIK 才可保留；解壓後 body 上限20MB，connect/read socket timeout為5／20秒，**不是硬性總耗時保證**。錯誤 body、聯絡內容回顯及原始 exception 不寫入快取／診斷。
- `<legacy-cache>.source-v1.json` 保存精確解壓後 HTTP body 的 UTF-8 bytes對應文字／SHA、URL、原取得時間與最新嘗試狀態；舊 raw cache 不刪除、不拿 mtime 當來源證明。開始請求先寫 `PENDING`，成功後才 `AVAILABLE`；失敗寫 `FAILED`，保留前次成功僅供歷史核對，不將其回傳成本次結果。失敗狀態持久化也可能失敗，不得掩蓋主要錯誤或宣稱安裝／發布交易已驗收。
- 使用快取不更新原取得時間。過期須重新取得，URL／body hash／時間／schema 不一致則拒絕，不靠修改 mtime 修復。此單檔可變本機 envelope 不是 immutable HTTP archive、完整 freshness／真實性認證、跨程序鎖或 sealed pointer-last transaction；後一次明確呼叫仍可發起新讀取，沒有新增背景重試器。

### 取得時間的下游傳遞與封存拒絕

原先三小時 cache／零 HTTP卻重蓋 row時間的 RED 保留。現有 CLI／進度入口共同使用 `report_source_acquisition.py`，不以新 envelope 隱藏舊值：

- `get_json` 清空並在同次成功結果填入 receipt；Companyfacts 再綁定 CIK與實際 adapter records摘要，builder 不另讀可變 cache 猜時間。失敗／未知不繼承上次 receipt。
- 五欄報告／row 升 schema2，保留 `calculation_cutoff`，完成後才記 `generated_at`。四個資料欄各有顯示值綁定的 `KNOWN`／`UNKNOWN`／`UNAVAILABLE` clock及證據摘要；row取已知適用欄的最早時間。任何有值欄時間未知、或全無已知欄，row時間為 null，不改生成時間。摘要hash是參照／一致性證明，不是來源真實性。
- yfinance 的函式返回只記 `observed_at`；library cache／provider原始取得時點未獲證明，因此 `retrieved_at=null`、`UNKNOWN_PROVIDER_ACQUISITION_TIME`。保留本機數值研究，不虛構目前報價、新鮮度或權利。
- 七欄 builder 沿用此時間；有訂單主張時再與保留 baseline row時間取較早者，缺失為未知。baseline時間只是保守沿用，**不是補做訂單 HTTP receipt認證**；不拿 `orders_as_of`／新生成時間當取得時間。預設可寫明示 CANDIDATE、未知時間的本機研究檔；`--require-known-acquisition` 在未知時於寫檔前拒絕，並不授予發布權限。
- 本機 sealed builder與實際 Worker activation-v3要求來源感知五欄 schema2、已知欄時鐘、五／七欄值一致且七欄不得更新五欄取得時間；所有顯示 row 都須通過既有兩小時門檻。Worker在任何交易寫入前及 pointer-last commit前再核對執行時鐘；中途過期保留交易／failed evidence，不宣稱自動 rollback。舊五欄 schema1仍可明示讀取，但不得降版取得新 v3 seal；歷史 activation-v2不改寫。
- 五／七欄文字、卡片及舊五欄推送別名採固定 snapshot讀取並檢查所有顯示 row時鐘；缺失成功時間戳不以生成時間代替。已封存不等於查詢當下仍新鮮，讀取端繼續拒絕過期。

這些是來源時間保留／失敗關閉，不是完整來源真實性、證券身分、最新公告／附註、訂單、報價權利或實際 LINE 發布驗收。未知市場時鐘仍阻擋受影響發布；不刪去資料欄、偷偷換來源或以新 run續命。

### 已接入的現金流／股數計算部分

實際 SEC adapter 把 wire 日期轉成午夜 UTC timestamp；既有 `v21_serenity_top20.validate_sec_adapter` 的指標邊界現在只將精確 `YYYY-MM-DDT00:00:00+00:00` 還原為日期，拒絕其他時間／時區／尾綴，不弱化下游日期驗證。每筆 fact 另以 CIK＋accession 的官方 archive 目錄作 filing locator，保留原 adapter 的 `source_request_url`；不同 filing 不再因共用 Companyfacts collection URL 被誤判為同文件日期衝突。同一 accession 的衝突仍拒絕。目錄 locator 不是已取得的 primary-document 原文／頁碼／佐證，也不新增獨立血緣。

company financial schema2 保留原利潤率並加入 `cashflow_bridge` schema1；schema3 增加上述來源 receipt；schema4 再加入下節時點流動性。舊 company schema1／2／3仍可明示讀取，不自動補造現金流、流動性或時鐘。五／七個顯示欄位、scoring body、七個 sealed payload 名稱與 LINE route 不變；報告及封存的時間驗證依上述來源感知契約。

- 沿用同次 Companyfacts records 與共用 operand 驗證，保留 CFO、PPE現金支出、所選淨利、ShareBasedCompensation、基本／稀釋加權平均股數。不新增 collector 或以 market／private data 補位。
- 以最新 CFO 的 end／filed cohort 作 anchor；同 cohort 有單季和YTD時只選相同 start 的比較項。anchor 本身多期間／多單位／多文件不明則 `AMBIGUOUS_OPERAND`。不以排序挑一個值、不退較舊 filing、不把投資活動淨現金流當 capex；最新無效值與衝突不救回。比較還須同幣別／單位、start/end、filed、form、fiscal year、CIK、accession及locator。
- `cash_after_ppe = operating_cashflow - ppe_payments`，保留負值及 currency；PPE支出必須非負，缺少不填零、不取絕對值。這不是標準化FCF、全部投資、可分配股東現金或每股現金收益。
- `cash_conversion = operating_cashflow / net_income` 只在所選淨利為正時算 ratio；虧損／零分母留 withheld。比率高不直接證明獲利品質，預收款／營運資金／非現金調整需附註核對。
- `diluted_share_increment = diluted_shares / basic_shares - 1` 使用同文件正加權平均股數，稀釋數小於基本數則拒絕。這不是新發股比例、未來完全稀釋股數或ADR換算；零差也不排除反稀釋工具。SBC僅保留披露數值，原報表位置及是否已列CFO調整仍須查附註；不再機械扣CFO或當現金支出／完整授予價值。
- 三種財務內容引用同份依據；數據表保留原值及公式，解讀隨現金盈餘／缺口／零值改變，列明其他投資、債務到期、租賃、受限現金及融資條款缺口。未知不是零；這仍不是完整股東收益橋、營運論點或估值。

### 已接入 CLI 的時點流動性（部分組件，未封存）

實際合成 SEC wire→既有報告 CLI 反例：`AssetsCurrent`、`LiabilitiesCurrent`、`CashAndCashEquivalentsAtCarryingValue` 原值被丟棄；即使有可比較資產負債時點，仍全部拒絕文字分析。Company4 沿用同次 records／receipt，加入 `liquidity_bridge` schema1，不新增 collector、scorer、雲端 key 或發布開關。

- 共用 `financial_operand(..., instant=True)`；只接受明示 `start=null` 的時點，不補造年度起日、不拿 duration 當 instant。原獲利／現金流呼叫預設仍要求合法 duration；CIK、tag、公開 locator、accession、form、fiscal year、end/filed/cutoff、安全數值驗證沿用。三種餘額須非負、幣別已知；未知／無效不是零。
- 每個指定 tag 先選提供資料中的最新 end/filed cohort 再驗證；同鍵衝突、同時點多幣別／多文件／口徑歧義拒絕，不因排序挑值、不救回較舊數值。完全相同重複可去重。這不是最新完整披露／context 認證。沒有分類式報表時，不用 `Assets`／`Liabilities` 代替流動項目，也不拿 `RestrictedCash` 當自由現金。
- `working_capital = current_assets - current_liabilities` [currency]；`current_ratio = current_assets / current_liabilities` [ratio]。只在相同 end、filed、form、fiscal year、CIK、taxonomy、accession、locator、unit 時比較。差額保留正／負／零；零分母留 withheld，不變成無限償債能力；超出安全範圍或非零下溢不冒充可用數值。現金披露另列自己的時點／單位，沒有混成第三個分子。
- card_summary 顯示餘額／日期與少量比率；data_report 保留原值、tag、時點、filed、accession、公式及失敗狀態；narrative_analysis 解釋存量缺口／正差／零差、反方、資產變現品質與待核融資條件，不貼一張表冒充分析。缺獲利／CFO 仍可有基於可比較流動項目的 **AVAILABLE_PARTIAL** 分析；只有現金披露或缺少可比流動負債時不猜流動性比率／結論，亦不得撤掉另有可比利潤率支持的分析。刷新缺值覆蓋前次候選，不沿用舊分析。
- 營運資金不是本期現金流，流動資產不等於可立即變現現金，現金披露不證明無限制／可分配。負差不自動宣告破產，正差不自動證明擴產／還債／配息能力；不機械產生融資續航月數、淨債務、評分或目標價。仍須債務到期／契約、受限現金、應收／存貨與預付款履約等附註。
- 驗證器重算封閉 operands／metrics 並保留 failed states；原 receipt／body SHA／取得時間不變，內嵌 bridge 不另造時鐘。Company1–3 不因新版 renderer 增加流動性內容；最終排序仍用既有 rank-only binder，不改內容／日期／失敗狀態。原始來源真實性／權利／最新披露與完整三產物封存、LINE實送均尚未取得资格。

訂單逐項保存客戶／交易對手、合約或承諾類型、数量／金額、履約期間、取消條件、認列階段、日期及直接證據。

Backlog、RPO、預付款、產能預約、設計採用、意向書與已認列營收不是同一件事；重疊項不得相加。管理層指引和自行估計分開。缺少未來數量／單價／成交機率等依據時，不輸出猜測的總訂單數字。新數字契約須經驗證及封存流程升版，不能直接取消現行禁止旗標。

### 公司營運詳報不能省略的分析

「完整文字敘述」指資料密度及推導增加，不是把七欄換成段落。逐公司展開：

- **產能：**逐廠／產品的名目與有效產能、單位、良率、稼動率、認證、已預約量、擴產成本及投產時程；區分自有、合資、共用。未知不得用工廠數推算。
- **實際訂單：**合約、預付款與出貨／認列的對照表；避免預付款、backlog、RPO重複加總，標明取消與履約條件的未知。
- **管理層展望：**原公告日期、目標期間、區間、後續修訂及已實現偏差；run-rate不是全年已實現營收，營運模型不是簽約訂單。
- **客戶群：**已證實客戶、未具名群體、應用、集中度和量產階段。下游客戶名單不自動成為上游的直接客戶；活躍客戶數不證明營收分散。
- **經濟轉換：**產能／交貨→營收→利潤→擴產與營運資金→每股現金收益，顯示可重算數字。收到預付款既是需求訊號，也可能附有交貨／退款義務。
- **反方與未來訂單：**同規格、客戶資格、有效替代產能及時間；分辨已簽承諾、管理層需求預測與研究假設，列出會下修結論的證據。

每段需有適用於該公司的事實及有前提的解讀；缺少證據就揭露，不堆疊通用產業文字。數字齊全也不自動取得發布資格。[TSEM實際營運研究底稿](research/TSEM-20260909.md)示範內容深度及反方處理，仍未接入卡片、未封存、非20家公司完成證明；不是新增固定篩選種子。

### 未來6個月／1年／2年情境

每個期間均需分列如期實現、延遲／部分實現、失敗／需求逆轉，不預設失敗只會小幅下跌。

1. 銜接有證據的產能、良率、履約及收入認列時程。
2. 推導毛利、營業費用、稅、資本支出、營運資金與自由現金流；不能把訂單當淨利。
3. 計入融資需求、可轉債、認股權、SBC及稀釋後股數。
4. 選擇適合該企業的估值法：虧損公司不套用正本益比；情境倍數須有同時點可比資料或明確假設，不能指定一個「標準倍數」。
5. 企業價值轉股權價值時明列淨負債、優先權益及非營運資產，避免現金重複加計；再除以相應稀釋股數。
6. 以有日期的參考股價計算情境價格報酬；若納入股利，另列總報酬。顯示敏感度、下檔與可推翻條件。無校準依據不填情境機率或機率加權目標價。

這些是可重算的條件情境，不是「訂單實現後必在某日上漲某百分比」的承諾。未估計不等於零風險；需要輸入缺失時不得輸出數字。

## 期權詳報

除摘要策略外，需有合約識別、交易所、到期日／實際DTE、履約價、權利型態、幣別、交割／合約乘數、同時點標的價格和 Bid/Mid/Ask、報價時間及延遲、成交量／OI的各自日期。不能把最後成交時間冒充目前 BBO 時間。

揭露 Greeks／IV 的來源或計算模型、流動性、滑價、費用、損益兩平、最大獲利及損失是否有限、提前指派／股利／跳空風險。短天期收益機械年化不代表可持續複利；展期假設與成本要獨立揭露。不得假設每種合約都是100股，或讀取私人持倉補公開報告。沒有合格來源與新鮮報價就不產生可執行價格。

## 宏觀／產業詳報

保存數列定義、原始發布機關、發布時間、觀察期間、修訂 vintage、頻率、季調／名目／實質與幣別。將總體→需求→供給約束→公司收益的每條傳導關係標示為事實或推論，附時間落差、反例與相反數據。新聞標題或宏觀資料不能單獨證明公司订单或定價權。

## 共同放行條件

- 每個重大投資論點都有相關且獨立的公司級證據；轉載／同一原始揭露只算一個來源血緣。
- 發布時間、財報期間、報價時間、取得時間分開；失敗與過期不能被新的報告日期覆蓋。
- 引用網址的憑證／控制字元檢查必須在報告schema與activation寫入前執行，不只在文字渲染時執行。共同URL形狀驗證不代表網域權威、DNS安全、資料授權或主張已獲佐證；仍須各自驗收。
- 市場身分、來源權利、資料品質與現有 LIMITED／出版門檻不降低；模型不得補造來源、公司名稱、訂單、EPS或價格。
- 測試實際卡片按鈕→授權訊息路由→同輪報告，包含快照汰換、未知公司、過期資料、缺失估值、惡意來源網址與最大訊息容量。
- 股票、期權、宏觀各自驗收摘要／資料詳報／文字分析；實際點開確認不同內容、同輪來源綁定及缺失拒絕，不只測按鈕存在。只有股票證據入口通過，不得宣稱全部深度分析完成。
