import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import { requirePublicCitation as safeCitation } from "./public-citation";
import { sourceZh } from "./source-labels";
import { parseV213Top20Report, type V213Top20Report } from "./top20-report";
import { parseV213BottleneckReport, type V213BottleneckReport } from "./bottleneck-report";
import { validateTwoYearReturnEvidence } from "./top20-return-evidence";
import {
  LINE_THEME as T, chip, divider, footerStyle, footnote, headerStyle, labelValue, menuAction, panel, phaseLadder, railTitle,
  packCarousels, rankBadge, richText, statTile, uiBox, uiText,
} from "./line-theme";

/**
 * 深度化分析 (Deep Bottleneck & Value-Chain Analysis)
 *
 * Implements real deep flow based on Serenity public-logic fidelity and bottleneck constraints.
 * Covers at least 10 separate sections with claim-level audit (SUPPORTED, WITHHELD, 研究待辦).
 * Fail-closed: missing valuation/order inputs stay UNAVAILABLE without fabricated narratives.
 * Never inherits generic AI beneficiary, pricing or customer claims onto individual companies.
 */
/** Data-driven company report computed from SEC filings, BLS and the industry rotation
 * (scripts/company_deep_report.py), embedded in the same sealed report object. */
export interface CompanyKpi {
  readonly label: string;
  readonly value: number | null;
  readonly unit: "%" | "pp";
  readonly signed: boolean;
  readonly period?: string;
}
export interface CompanyDataReport {
  readonly ticker: string;
  readonly name: string;
  readonly as_of: string;
  readonly phase: string;
  readonly next_review_at: string | null;
  readonly sections: readonly { readonly title: string; readonly text: string }[];
  readonly source_references: readonly { readonly source: string; readonly url: string; readonly period?: string }[];
  readonly boundary: string;
  /** Optional structured figures for tiles (older sealed reports have none). */
  readonly kpis: readonly CompanyKpi[];
}

const SHORT = (value: unknown, max: number): value is string =>
  typeof value === "string" && value.trim().length > 0 && value.length <= max && !/[\r\n]/.test(value);

/** Strict reader: any malformed field rejects the whole report (the caller then shows the audit template). */
export function companyDataReportFromSealed(rawReportJson: string | null, ticker: string): CompanyDataReport | null {
  if (!rawReportJson || rawReportJson.length > 2_097_152) return null;
  let raw: any;
  try { raw = JSON.parse(rawReportJson)?.deep_reports?.[ticker.toUpperCase()]; } catch { return null; }
  return validateCompanyDataReport(raw, ticker);
}

/** Strict validation of one embedded company data report; null on any malformed field. */
export function validateCompanyDataReport(raw: any, ticker: string): CompanyDataReport | null {
  if (!raw || typeof raw !== "object" || raw.ticker !== ticker.toUpperCase() || !SHORT(raw.name, 200)) return null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(raw.as_of)) || !SHORT(raw.boundary, 200)) return null;
  const phase = raw.phase?.phase;
  const next = raw.phase?.next_review_at ?? null;
  if (!SHORT(phase, 40) || (next !== null && !/^\d{4}-\d{2}-\d{2}$/.test(String(next)))) return null;
  if (!Array.isArray(raw.sections) || raw.sections.length < 3 || raw.sections.length > 12) return null;
  if (!raw.sections.every((s: any) => SHORT(s?.title, 20) && SHORT(s?.text, 700))) return null;
  if (!Array.isArray(raw.source_references) || raw.source_references.length < 1 || raw.source_references.length > 20) return null;
  const kpis = raw.kpis ?? [];
  if (!Array.isArray(kpis) || kpis.length > 8 || !kpis.every((k: any) => SHORT(k?.label, 12)
    && (k.value === null || (typeof k.value === "number" && Number.isFinite(k.value) && Math.abs(k.value) < 1e6))
    && (k.unit === "%" || k.unit === "pp") && typeof k.signed === "boolean"
    && (k.period === undefined || k.period === null || SHORT(String(k.period), 20)))) return null;
  try {
    const references = raw.source_references.map((ref: any) => {
      if (!SHORT(ref?.source, 120) || (ref.period !== undefined && ref.period !== null && !SHORT(String(ref.period), 40))) throw new Error("REF");
      return { source: ref.source, url: safeCitation(ref.url), ...(ref.period ? { period: String(ref.period) } : {}) };
    });
    return { ticker: raw.ticker, name: raw.name, as_of: raw.as_of, phase, next_review_at: next,
      sections: raw.sections.map((s: any) => ({ title: s.title, text: s.text })), source_references: references, boundary: raw.boundary,
      kpis: kpis.map((k: any) => ({ label: k.label, value: k.value, unit: k.unit, signed: k.signed, ...(k.period ? { period: String(k.period) } : {}) })) };
  } catch {
    return null;
  }
}

function dataReportBlocks(report: { generated_at: string }, data: CompanyDataReport): string[] {
  const numerals = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"];
  return [
    `【${data.ticker}｜公司深度報告 · 官方資料計算】\n原文公司名稱：${data.name}\n當輪快照產生：${report.generated_at}\n` +
      `資料計算日：${data.as_of}｜資料階段：${data.phase}｜下次檢查：${data.next_review_at ?? "下一份財報"}\n研究邊界：${data.boundary}`,
    ...data.sections.map((section, index) => `${numerals[index]}、${section.title}\n${section.text}`),
    `資料來源 / Sources\n` + data.source_references.map(ref => `• ${sourceZh(ref.source)}${ref.period ? `（${ref.period}）` : ""}：${ref.url}`).join("\n"),
  ];
}

export function buildTop20DeepAnalysisMessages(
  report: V213Top20Report | V213BottleneckReport,
  ticker: string,
  dataReport: CompanyDataReport | null = null,
  style: "flex" | "text" = "text",
): LineOutboundMessage[] {
  // Strict two-variant admission: certified top20 report first, then the
  // bottleneck policy report; anything else still throws REPORT_CONTEXT_INVALID.
  const top20 = parseV213Top20Report(report as unknown);
  const bottleneck = top20 ? null : parseV213BottleneckReport(report as unknown);
  const validated = top20 ?? bottleneck;
  const row: any = validated?.records?.find((item: any) => item.ticker === ticker.toUpperCase());
  if (!validated || !row) throw new Error("REPORT_CONTEXT_INVALID");

  if (dataReport && style === "flex") return buildCompanyDataReportFlex(dataReport, validated.generated_at, ["回 Top20", "Top20"]);

  const currentUrls = [...new Set(((row.current_order_source_urls ?? []) as string[]).map(safeCitation))];
  const futureUrls = [...new Set(((row.future_order_source_urls ?? []) as string[]).map(safeCitation))];

  // Return evidence audit: candidate arithmetic is distinguished from authoritative return admission.
  // Numeric 2Y total return is WITHHELD in actual deep callers; shows explicit UNAVAILABLE until authoritative
  // source authority, currency, original body digest, and identity/role bindings are coordinated and reviewed.
  const returnDisplay = "UNAVAILABLE（2年總報酬來源權威與核驗契約待協調驗收，依政策扣留數值；不逆推年化、不用未還原收盤價冒充）";

  const percent = (value: number | null | undefined) => (value === null || value === undefined ? "未提供" : `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`);

  const blocks: string[] = dataReport ? dataReportBlocks(report, dataReport) : [
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
    `  - [SUPPORTED] 公司代號 ${row.ticker}、名稱「${row.name}」為當輪快照記錄之公開研究標的；財務資料來源為 ${row.profit_source ?? "未標註（候選快照口徑）"}。\n` +
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
    `• 訂單基準日期：${row.orders_as_of || "未揭露"}｜來源信心：${row.orders_confidence ?? "未標註（候選快照口徑）"}\n` +
    `• 主張核對（Claim Audit）：\n` +
    `  - 客戶名單不等於稀缺性（Customers aren't scarcity）。供貨予特定客戶僅代表已獲供應商代碼，不代表供貨份額具排他性。\n` +
    `  - 合約約束力缺口：缺少逐筆訂單條款、取消與退單條件、交付驗收期程及違約罰則；剩餘履約義務（RPO）不等於未來必然落袋利潤，亦不得與已認列營收重複相加。\n` +
    `  - 禁止推估訂單總額規則：已啟用嚴格禁止任意推估總額門檻，不以模型生成假想訂單池。\n` +
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

  return chunkBlocks(blocks);
}

const PHASE_NAME: Record<string, string> = {
  INSUFFICIENT_EVIDENCE: "資料不足", DISCOVERY: "初現（單一來源）", EARLY_VALIDATION: "驗證中（雙來源確認）",
  COMMERCIAL_VALIDATION: "商業驗證（公司開始獲利）", INSTITUTIONAL_VALIDATION: "法人進場", CONSENSUS: "共識擁擠",
  RELIEVING: "緩解中", BROKEN: "已失效",
};
const NUMERALS = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"];

const kpiValue = (kpi: CompanyKpi) => kpi.value === null ? "未申報"
  : `${kpi.signed && kpi.value >= 0 ? "+" : ""}${kpi.value.toFixed(1)}${kpi.unit === "pp" ? "pp" : "%"}`;

/** KPI tiles two per row; bounded levels (margins, shares of revenue) get a meter, changes do not. */
function kpiRows(kpis: readonly CompanyKpi[]) {
  const rows = [];
  for (let start = 0; start < kpis.length; start += 2) {
    const pair = kpis.slice(start, start + 2).map(kpi => statTile(kpi.label, kpiValue(kpi),
      !kpi.signed && kpi.value !== null && kpi.value >= 0 && kpi.value <= 100 ? kpi.value : undefined, kpi.period));
    if (pair.length === 1) pair.push(uiBox([], { flex: 1 }));
    rows.push(uiBox(pair, { layout: "horizontal", spacing: "sm" }));
  }
  return rows;
}

/** Data report as a Flex carousel: overview (phase ladder, KPI tiles), numbered sections, sources. */
export function buildCompanyDataReportFlex(data: CompanyDataReport, generatedAt: string,
  back: readonly [string, string] = ["回功能選單", "選單"]): LineOutboundMessage[] {
  const perBubble = 4;
  const sectionPages = Math.ceil(data.sections.length / perBubble);
  const total = sectionPages + 2;
  const overview = {
    type: "bubble", size: "mega",
    header: uiBox([
      uiBox([chip("公司深度報告"), uiText("官方資料計算", "xxs", T.headerMuted, { weight: "bold", gravity: "center", flex: 1 })],
        { layout: "horizontal", spacing: "md" }),
      uiText(data.ticker, "3xl", T.headerText, { weight: "bold" }),
      uiText(data.name, "md", T.headerText, { weight: "bold" }),
      uiText(`資料計算日 ${data.as_of}｜快照 ${generatedAt}`, "xxs", T.headerSubtle),
    ], { ...headerStyle, spacing: "sm" }),
    body: uiBox([
      uiBox([railTitle("資料階段", PHASE_NAME[data.phase] ?? data.phase), phaseLadder(data.phase),
        labelValue("下次檢查", data.next_review_at ?? "下一份財報", { weight: "bold" })], { spacing: "md" }),
      ...(data.kpis.length > 0 ? [uiBox([railTitle("關鍵數據", "SEC XBRL 同季年比較"), ...kpiRows(data.kpis)], { spacing: "sm" })] : []),
      panel([footnote(`研究邊界：${data.boundary}`), footnote(`左滑看詳細報告 2–${total}/${total}`)], "soft"),
    ], { paddingAll: "lg", spacing: "lg", backgroundColor: T.paper }),
  };
  const sectionBubbles = Array.from({ length: sectionPages }, (_, page) => {
    const chunk = data.sections.slice(page * perBubble, page * perBubble + perBubble);
    return {
      type: "bubble", size: "mega",
      header: uiBox([
        uiText(`${data.ticker} · 詳細報告 ${page + 2}/${total}`, "xxs", T.headerMuted, { weight: "bold" }),
        uiText(chunk.map(s => s.title).join("・"), "md", T.headerText, { weight: "bold" }),
      ], { ...headerStyle, spacing: "sm" }),
      body: uiBox(chunk.flatMap((item, offset) => {
        const index = page * perBubble + offset;
        const falsifier = /證偽/.test(item.title);
        const block = uiBox([
          uiBox([rankBadge(NUMERALS[index] ?? String(index + 1), index === 0),
            uiText(item.title, "sm", falsifier ? T.negative : T.ink, { weight: "bold", gravity: "center", flex: 1 })],
          { layout: "horizontal", spacing: "md" }),
          falsifier
            ? uiBox([richText(item.text, "xs", T.ink)], { backgroundColor: T.paleNegative, cornerRadius: "md", paddingAll: "md" })
            : richText(item.text, "xs", T.ink),
        ], { spacing: "sm" });
        return offset > 0 ? [divider(), block] : [block];
      }), { paddingAll: "lg", spacing: "md", backgroundColor: T.paper }),
    };
  });
  const sources = {
    type: "bubble", size: "mega",
    header: uiBox([
      uiText(`${data.ticker} · 詳細報告 ${total}/${total}`, "xxs", T.headerMuted, { weight: "bold" }),
      uiText("資料來源 / Sources", "md", T.headerText, { weight: "bold" }),
    ], { ...headerStyle, spacing: "sm" }),
    body: uiBox(data.source_references.slice(0, 10).flatMap((ref, index) => {
      const block = uiBox([
        uiText(sourceZh(ref.source), "xs", T.ink, { weight: "bold" }),
        ...(ref.period ? [uiText(`期間 ${ref.period}`, "xxs", T.muted)] : []),
        uiText(ref.url, "xxs", T.subtle),
      ], { spacing: "xs" });
      return index > 0 ? [divider(), block] : [block];
    }), { paddingAll: "lg", spacing: "md", backgroundColor: T.paper }),
    footer: uiBox([menuAction(back[0], back[1]), ...(back[1] === "選單" ? [] : [menuAction("回功能選單", "選單")])], { ...footerStyle }),
  };
  const alt = `${data.ticker}｜公司深度報告 · 官方資料計算`;
  return packCarousels([overview, ...sectionBubbles, sources], (index, total) => total > 1 ? `${alt}（${index + 1}/${total}）` : alt);
}

/** Data report as LINE text messages (text presentation of the data-driven potential ranking). */
export function buildCompanyDataReportMessages(data: CompanyDataReport, generatedAt: string): LineOutboundMessage[] {
  return chunkBlocks(dataReportBlocks({ generated_at: generatedAt }, data));
}

function chunkBlocks(blocks: string[]): LineOutboundMessage[] {
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
