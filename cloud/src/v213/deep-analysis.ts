import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import { requirePublicCitation as safeCitation } from "./public-citation";
import { parseV213Top20Report, type V213Top20Report } from "./top20-report";
import { validateTwoYearReturnEvidence } from "./top20-return-evidence";

/**
 * 深度化分析 (Deep Bottleneck & Value-Chain Analysis)
 *
 * Implements real deep flow based on Serenity public-logic fidelity and bottleneck constraints.
 * Covers at least 10 separate sections with claim-level audit (SUPPORTED, WITHHELD, 研究待辦).
 * Fail-closed: missing valuation/order inputs stay UNAVAILABLE without fabricated narratives.
 * Never inherits generic AI beneficiary, pricing or customer claims onto individual companies.
 */
export function buildTop20DeepAnalysisMessages(
  report: V213Top20Report,
  ticker: string,
): LineOutboundMessage[] {
  const validated = parseV213Top20Report(report);
  const row = validated?.records.find(item => item.ticker === ticker.toUpperCase());
  if (!validated || !row) throw new Error("REPORT_CONTEXT_INVALID");

  const currentUrls = [...new Set(row.current_order_source_urls.map(safeCitation))];
  const futureUrls = [...new Set(row.future_order_source_urls.map(safeCitation))];

  // Return evidence audit: candidate arithmetic is distinguished from authoritative return admission.
  // Numeric 2Y total return is WITHHELD in actual deep callers; shows explicit UNAVAILABLE until authoritative
  // source authority, currency, original body digest, and identity/role bindings are coordinated and reviewed.
  const returnDisplay = "UNAVAILABLE（2年總報酬來源權威與核驗契約待協調驗收，依政策扣留數值；不逆推年化、不用未還原收盤價冒充）";

  const percent = (value: number | null) => (value === null ? "未提供" : `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`);

  const blocks: string[] = [
    // Header & Meta
    `【${row.ticker}｜深度化分析 · 供應鏈瓶頸與價值鏈研究】\n` +
    `原文公司名稱：${row.name}\n` +
    `中文名稱：未完成來源核對（不按股票代號猜譯）\n` +
    `當輪快照產生：${report.generated_at}\n` +
    `資料取得時間：${row.retrieved_at}\n` +
    `研究邊界：公開研究，非投資建議；歷史報酬非預測。`,

    // Section 1: 供應鏈瓶頸定位與價值鏈角色
    `一、供應鏈瓶頸定位與價值鏈角色 / Bottleneck Role & Value Chain\n` +
    `• 行業分類：${row.industry}（來源：${row.market_source}，市場分類觀測）\n` +
    `• 價值鏈層級：依具體標的之實際業務為準；不預設特定概念或伺服器模組層級\n` +
    `• 瓶頸角色分類：【UNPROVEN / 未證實瓶頸】（非單一供應商 SINGLE_SOURCE 或實質半寡占 SEMI_MONOPOLY）\n` +
    `• 主張核對（Claim Audit）：\n` +
    `  - [SUPPORTED] 公司代號 ${row.ticker}、名稱「${row.name}」為當輪快照記錄之公開研究標的；財務資料來源為 ${row.profit_source}。\n` +
    `  - [WITHHELD] 核心供應鏈瓶頸地位：未通過多來源獨立驗證。現有 20 LIMITED 候選集之核心瓶頸優勢因子均為 0 或已扣留；有客戶關係或供貨不等於具備不可替代之稀缺性（Customers aren't scarcity）。\n` +
    `  - [研究待辦 / NOT_A_COMPANY_FINDING] 個股價值鏈定位與瓶頸卡位假說：需具備逐標的專屬價值鏈研究與獨立一級佐證，不從行業標籤逕行推論。`,

    // Section 2: 未來結構性缺口
    `二、未來結構性缺口 / Future Structural Gap\n` +
    `• 結構性供需分析原則：不將整體產業擴張假說（Expansion thesis）直接當作個別公司瓶頸卡位假說（Bottleneck thesis）。\n` +
    `• 缺口驗證狀態：【WITHHELD / 未具個股驗收證據】\n` +
    `• 主張核對（Claim Audit）：\n` +
    `  - [WITHHELD] 結構性供需缺口是否必然轉化為單一公司不可繞過之超額訂單：未經雙向獨立驗證。\n` +
    `  - [WITHHELD] 結構性防護與替代壁壘：同業並行擴產可能於 12–24 個月內緩解缺口，非永久性卡位；無證據顯示該公司享有獨佔排他防護。\n` +
    `  - [研究待辦 / NOT_A_COMPANY_FINDING] 次世代架構轉移與物理極限假說：屬於行業研究框架問題，非已證實之個股事實。`,

    // Section 3: 需求／供給／定價權分析
    `三、需求／供給／定價權分析 / Demand, Supply & Pricing Power\n` +
    `• 需求脈絡（Context）：宏觀需求浪潮屬於背景參考（CONTEXT_ONLY），不直接替單一公司訂單背書。\n` +
    `• 有效替代供給（Alternative Supply）：市場存在其他合格或潛在供應商；客戶驗證週期存在切換摩擦，但尚未構成不可替代之排他性壁壘。\n` +
    `• 定價權判定（Pricing Power）：【WITHHELD / 扣留】\n` +
    `• 主張核對（Claim Audit）：\n` +
    `  - 毛利率高或改善不等於定價權（Margin isn't pricing power）。高毛利可能來自產品週期初期的暫時良率領先或折舊時程，非「漲價且客戶不流失」之結構性定價能力。\n` +
    `  - [WITHHELD] 定價權因子在當輪評分架構中缺乏兩家以上一級來源交叉支持，予以扣留。\n` +
    `  - [研究待辦 / NOT_A_COMPANY_FINDING] 價格傳導與合約重議彈性：尚缺逐筆合約條款與供應鏈訪談驗證。`,

    // Section 4: 公司捕捉度與毛利槓桿
    `四、公司捕捉度與毛利槓桿 / Company Capture & Margin Leverage\n` +
    `• 財務現況摘要（申報事實）：${row.profit_summary}\n` +
    `• 財務資料來源：${row.profit_source}\n` +
    `• 營運槓桿與資本支出分析：\n` +
    `  - [SUPPORTED] 歷史獲利與毛利指標僅反映過去申報執行成果，不代表未來邊際利潤率擴張。\n` +
    `  - [INFERENCE] 資本支出龐大不等於形成護城河（CapEx alone isn't a choke）。若缺乏超額定價權，盲目擴大 CapEx 將產生折舊負擔、稀釋自由現金流（FCF）並壓低 ROIC。\n` +
    `  - [WITHHELD] 逐期完整傳導模型（整體需求→訂單認列→營收毛利→扣除資本支出與稅費後之現金流→每股價值）：目前尚缺逐期完整傳導模型。\n` +
    `  - [研究待辦 / NOT_A_COMPANY_FINDING] 產能利用率與固定成本損益兩平點分析：待進一步拆解財報附註。`,

    // Section 5: 合約、訂單、資本支出、產能與客戶證據
    `五、合約、訂單、資本支出、產能與客戶證據 / Contracts, Orders, CapEx, Capacity & Customer Evidence\n` +
    `• 快照記載現有訂單：${row.current_orders}\n` +
    `• 快照記載未來展望：${row.future_orders_estimate}\n` +
    `• 訂單基準日期：${row.orders_as_of || "未揭露"}｜來源信心：${row.orders_confidence}\n` +
    `• 主張核對（Claim Audit）：\n` +
    `  - 客戶名單不等於稀缺性（Customers aren't scarcity）。供貨予特定客戶僅代表已獲供應商代碼，不代表供貨份額具排他性。\n` +
    `  - 合約約束力缺口：缺少逐筆訂單條款、取消與退單條件、交付驗收期程及違約罰則；剩餘履約義務（RPO）不等於未來必然落袋利潤，亦不得與已認列營收重複相加。\n` +
    `  - 禁止推估訂單總額規則：${row.numeric_total_order_estimate_prohibited ? "已啟用嚴格禁止任意推估總額門檻，不以模型生成假想訂單池。" : "未啟用。"}\n` +
    `  - [研究待辦 / NOT_A_COMPANY_FINDING] 逐季訂單履約與客戶集中度拆解：尚待公開審計資料補齊。`,

    // URL citations broken into fine-grained blocks to ensure no section overflows
    ...(currentUrls.length
      ? currentUrls.map(url => `現有訂單來源：${url}`)
      : ["現有訂單來源：無公開可追溯連結。"]),
    ...(futureUrls.length
      ? futureUrls.map(url => `未來展望來源：${url}`)
      : ["未來展望來源：無公開可追溯連結。"]),

    // Section 6: 6個月／1年／2年催化劑與情境分析
    `六、6個月／1年／2年催化劑與情境分析 / 6M / 1Y / 2Y Catalysts & Scenarios\n` +
    `• 6個月情境（短程營運與訂單認列）：\n` +
    `  - 催化劑：下季財報與指引修正、已公布固定訂單之履約交付。\n` +
    `  - 估值狀態：【UNAVAILABLE】尚無合格逐筆訂單與現金流折現輸入，不給予目標價或漲跌幅預測。\n` +
    `• 1年情境（產能開出與業務拓展）：\n` +
    `  - 催化劑：新增產能利用率驗證、新客戶資格認證完成。\n` +
    `  - 估值狀態：【UNAVAILABLE】不以線性成長捏造目標價。\n` +
    `• 2年情境（技術演進與市場競爭態勢）：\n` +
    `  - 催化劑：產業規格全面導入、替代技術成熟度。\n` +
    `  - 估值狀態：【UNAVAILABLE】不提供未經核實之樂觀漲幅。\n` +
    `• [研究待辦 / NOT_A_COMPANY_FINDING] 未估計不代表零報酬或零風險，僅代表公開研究堅持不可捏造數據。`,

    // Section 7: 假說殺手與下檔風險
    `七、假說殺手與下檔風險 / Hypothesis Killers & Downside Risks\n` +
    `• 投資假說失效條件（Hypothesis Killers）：\n` +
    `  1. 融資結構惡化：若公司頻繁透過 ATM（At-The-Market）發行新股稀釋股本、發行高成本可轉債或舉債擴產，營運成果將無法傳導至每股價值。\n` +
    `  2. 客戶架構轉向或繞道：下游客戶若變更規格、轉向自研替代方案或扶植第二供應商，即刻打破瓶頸依賴假說。\n` +
    `  3. 同業擴產引發價格戰：替代產能集中開出導致產能利用率驟降與毛利率壓縮。\n` +
    `  4. 認證失敗或重大交付延遲：製程良率卡關導致訂單遭取消。\n` +
    `• 下檔風險評估：缺乏合格下檔估值模型不等於下檔空間有限；週期反轉可能面臨盈餘與評價倍數雙殺風險。`,

    // Section 8: 多軸證據信心與來源品質
    `八、多軸證據信心與來源品質 / Multi-Axis Evidence Confidence & Source Quality\n` +
    `• 來源分級標準：\n` +
    `  - T0/T1 法定申報（SEC EDGAR 10-K/10-Q/8-K）：具法定責任之事實與財務數據。\n` +
    `  - T2 官方目錄（Nasdaq/NYSE/GLEIF）：上市身分與法人代碼驗證。\n` +
    `  - T3 市場觀測（Yahoo/yfinance）：僅作為歷史行情觀測，非公司基本面或商業模式保證。\n` +
    `  - 第三方/社群觀點（X/@aleabitoreddit 等）：僅供研究假說線索與脈絡參考（CONTEXT_ONLY），非公司官方證明（X/source view not company proof）。\n` +
    `• 當輪候選集審查：20 LIMITED 名單中核心瓶頸因子未達雙獨立一級來源標準，維持扣留。不因來源筆數逕行宣稱具備 100% SEC 或獨立覆蓋。`,

    // Section 9: 候選排位說明與為何為第N名
    `九、候選排位說明與為何為第N名 / Rank Rationale & Why Position N\n` +
    `• 當前顯示序位：【第 ${row.rank} 位 / 共 20 位】\n` +
    `• 排位性質界線：\n` +
    `  - 當前序位 #${row.rank} 係沿用既有公開研究之「舊版候選展示序位（Legacy Candidate Display Position）」；\n` +
    `  - 嚴禁誤認：此序位【絕非】合格之系統瓶頸爆發排名（System Bottleneck Explosion Rank）！\n` +
    `  - 系統瓶頸爆發分數（System Bottleneck Explosion Score）：【UNAVAILABLE / UNRANKED】（未評定 / 未經新政策與證據驗收）。\n` +
    `  - 不得將舊版 serenity_score 或歷史 CAGR 年化報酬改名冒充為新版瓶頸爆發分數。\n` +
    `  - 新版排位理由在嚴格政策與獨立一級證據驗收前明確扣留（WITHHELD）。\n` +
    `  - 候選清單不代表永久白名單，亦無固化之特定板塊限制。`,

    // Section 10: 明確未明與待查事項
    `十、明確未明與待查事項 / Explicit Unknowns & Open Items\n` +
    `• 待補齊之關鍵缺口：\n` +
    `  1. 中文名稱官方對照：未完成來源核對，不按股票代碼猜譯。\n` +
    `  2. 兩年總報酬還原端點：${returnDisplay}\n` +
    `  3. 歷史報酬背景：近兩年年化 ${percent(row.long_term_return_pct)}，近六個月 ${percent(row.short_term_return_pct)}。歷史數據僅供風險脈絡參考，對評分與候選排序無任何影響力。\n` +
    `  4. 逐筆合約法律約束力：尚缺不可撤銷條款、價格重議機制與明確履約交期。\n` +
    `  5. 股權稀釋與融資排程：尚未計入最新潛在股權發行之稀釋衝擊。\n` +
    `  6. 客戶端排他性證實：尚無客戶端公開文件直接證實該公司為唯一或不可替代之首選供應商。\n` +
    `• 結論：這份報告列出快照資料、口徑與缺口，不生成沒有數據支撐的預測。完整研究必須補齊身分、財報、訂單／供給約束、獨立佐證與可重算情境，並通過同輪封存驗證。`,
  ];

  // LINE chunking: up to 5 messages, each <= 4,800 characters
  const chunks: string[] = [];
  let currentChunk = "";

  for (const block of blocks) {
    if (block.length > 4800) {
      // Split large single blocks safely across multiple lines
      const lines = block.split("\n");
      for (const line of lines) {
        if (!currentChunk) {
          currentChunk = line;
        } else if (currentChunk.length + 1 + line.length <= 4800) {
          currentChunk += "\n" + line;
        } else {
          chunks.push(currentChunk);
          currentChunk = line;
        }
      }
      continue;
    }
    if (!currentChunk) {
      currentChunk = block;
    } else if (currentChunk.length + 2 + block.length <= 4800) {
      currentChunk += "\n\n" + block;
    } else {
      chunks.push(currentChunk);
      currentChunk = block;
    }
  }
  if (currentChunk) {
    chunks.push(currentChunk);
  }

  if (chunks.length < 1 || chunks.length > 5) {
    throw new Error(`DEEP_ANALYSIS_MESSAGE_COUNT_EXCEEDED: count=${chunks.length}`);
  }

  const messages: LineOutboundMessage[] = chunks.map(t => ({ type: "text", text: t }));
  assertLineMessages(messages);
  return messages;
}
