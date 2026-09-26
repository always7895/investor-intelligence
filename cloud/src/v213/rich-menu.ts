import { parseQuery, type ParsedQuery } from "../core";
import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import {
  buildBottleneckDetail, buildBottleneckTop20Messages, buildIndustryExplosionMessages, findBottleneckEntry, loadBottleneckV3,
} from "./bottleneck-v3";
import { loadOptionObservation, optionTickerKeys } from "./market-observations";
import { buildCoveredCallMessages, validateCoveredCallCycle } from "./covered-call";
import { pinPublicSnapshot } from "./public-snapshot";
import { v213Top20LineAnswer } from "./top20-presentation";
import { loadV213FreshTop20Report, v213TimesAreFresh, v213EvidenceWithinWindow, V213_STALE_RECORDS_MESSAGE, type V213Top20Env } from "./top20-report";
import { LINE_THEME as T, footerStyle, menuAction, menuBox, menuText, productHeader, section, sectionTitle } from "./line-theme";
import {
  buildEducationalStrategyFlex,
  buildEducationalStrategyText,
} from "./educational-options";
import {
  buildMacroDeepAnalysisFlex,
  buildMacroDeepAnalysisText,
  buildMacroIndustryCardFlex,
  buildMacroIndustryCardText,
  buildMacroTop5OverviewFlex,
  buildMacroTop5OverviewText,
  MACRO_PRODUCT_KEY,
  macroShortfallReport,
} from "./macro-industry-product";
import type {
  MacroDeepAnalysis,
  MacroIndustryCard,
  MacroTop5Overview,
  OptionContractQuote,
} from "./market-product-schema";
import { validateMacroDeepAnalysis, validateMacroIndustryCard } from "./market-product-schema";
import {
  buildOrderRealizationFlex, buildOrderRealizationText, buildPotentialRankingFlex, buildPotentialRankingText, buildPotentialReport,
  validatePotentialRanking,
} from "./potential-ranking";
import {
  buildOptionContractFlex,
  buildOptionContractText,
  OPTIONS_PRODUCT_KEY,
  optionsUnavailableReport,
} from "./options-product";

type Env = V213Top20Env & { V213_LINE_PRESENTATION?: string };

/** Industry card and deep analysis travel inside the sealed TOP5 overview (the seal admits one macro
 * object); legacy per-industry keys are read only as a fallback. Invalid entries are ignored. */
async function sealedMacroEntry(view: Awaited<ReturnType<typeof pinPublicSnapshot>>, targetId: string, kind: "card" | "deep") {
  const overview = await view.json<Record<string, unknown>>([MACRO_PRODUCT_KEY]);
  try {
    if (overview && kind === "card" && Array.isArray(overview.industries)) {
      const raw = (overview.industries as Record<string, unknown>[]).find(row => String(row?.industry_id ?? "").toLowerCase() === targetId);
      if (raw) return validateMacroIndustryCard(raw);
    }
    const deep = overview?.deep_analyses as Record<string, unknown> | undefined;
    if (kind === "deep" && deep && typeof deep === "object" && targetId in deep) return validateMacroDeepAnalysis(deep[targetId]);
  } catch {
    return null;
  }
  return kind === "card"
    ? view.json<MacroIndustryCard>([`v213:macro-industry:${targetId}`])
    : view.json<MacroDeepAnalysis>([`v213:macro-deep:${targetId}`]);
}
export const RICH_MENU_ACTIONS = Object.freeze([
  { label: "每日 TOP20 榜單", text: "TOP20" },
  { label: "宏觀產業分析", text: "宏觀產業分析" },
  { label: "期權與個股快查", text: "期權" },
]);

function panelTextMessages(
  title: string,
  subtitle: string,
  paragraphs: readonly string[],
  actions: readonly (readonly [string, string])[],
): LineOutboundMessage[] {
  const header = `${title}｜${subtitle}`;
  const actionText = actions.length > 0
    ? "快捷指令：\n" + actions.map(([label, command]) => `• ${label}：${command}`).join("\n")
    : "";
  const blocks: string[] = [header, ...paragraphs, ...(actionText ? [actionText] : [])].filter(Boolean);

  for (const block of blocks) {
    if (block.length > 4900) throw new Error("V213_PANEL_BLOCK_TOO_LARGE");
  }

  const chunks: string[] = [];
  let current = "";
  for (const block of blocks) {
    if (!current) {
      current = block;
    } else if (current.length + 2 + block.length <= 4900) {
      current += "\n\n" + block;
    } else {
      chunks.push(current);
      current = block;
    }
  }
  if (current) chunks.push(current);

  if (chunks.length < 1 || chunks.length > 5) {
    throw new Error("V213_PANEL_MESSAGE_COUNT_EXCEEDED");
  }
  const messages: LineOutboundMessage[] = chunks.map(text => ({ type: "text", text }));
  assertLineMessages(messages);
  return messages;
}

function panel(
  title: string,
  subtitle: string,
  paragraphs: readonly string[],
  actions: readonly (readonly [string, string])[],
  isText = false,
): LineOutboundMessage[] {
  if (isText) return panelTextMessages(title, subtitle, paragraphs, actions);
  const messages: LineOutboundMessage[] = [{ type: "flex", altText: `${title}｜${subtitle}`, contents: { type: "carousel", contents: [{
    type: "bubble", size: "mega",
    header: productHeader("韭菜守護者 · 公開研究", title),
    body: menuBox([section(subtitle, paragraphs.map(p => menuText(p)), "detail")], { backgroundColor: T.paper, paddingAll: "lg" }),
    footer: menuBox(actions.map(([label, command]) => menuAction(label, command)), { ...footerStyle }),
  }] } }];
  assertLineMessages(messages);
  return messages;
}
const NAV = RICH_MENU_ACTIONS.map(a => [a.label, a.text] as const);

const STRATEGY_ALIASES: Record<string, "covered_call" | "cash_secured_put" | "bull_call_spread" | "protective_put"> = {
  covered_call: "covered_call",
  coveredcall: "covered_call",
  cc: "covered_call",
  "掩護性買權": "covered_call",
  "現股配買權": "covered_call",

  cash_secured_put: "cash_secured_put",
  cashsecuredput: "cash_secured_put",
  csp: "cash_secured_put",
  "現金擔保賣權": "cash_secured_put",
  "現金擔保賣出賣權": "cash_secured_put",

  bull_call_spread: "bull_call_spread",
  bullcallspread: "bull_call_spread",
  bcs: "bull_call_spread",
  "買權多頭價差": "bull_call_spread",
  "多頭價差": "bull_call_spread",

  protective_put: "protective_put",
  protectiveput: "protective_put",
  pp: "protective_put",
  "保護性賣權": "protective_put",
  "現股配賣權": "protective_put",
};

/** Exact rich-menu commands only. Runs AFTER real LINE admission/rate limiting,
 * in the same request-pinned public view as Top20. No model or private fallback.
 * The primary macro home routes to TOP5 overview or shortfall report.
 */
export async function v213PublicLineAnswer(env: Env, query: ParsedQuery): Promise<LineOutboundMessage[] | string | null> {
  const isEnvText = env.V213_LINE_PRESENTATION === "text";
  // Trailing punctuation never changes a command ("TOP20。", "NVDA 每月期權！"; NFKC already folded full-width forms).
  const command = query.normalized.replace(/[\s。.!?~～]+$/u, "");
  const commandText = isEnvText || /文字\s*$/i.test(command);

  // --- Bottleneck-explosion Top20 v3 and the Leopold-led industry ranking (sealed lazy object) ---
  // It replaced the original ranking, so the plain ranking words lead here too ("七欄Top20" keeps the old report).
  if (/^(?:top\s*20|瓶頸爆發榜|瓶頸\s*top\s*20|瓶頸(?:排名|排行|榜)|前\s*(?:20|二十)\s*名?|排名|排行榜?)(?:\s*文字)?$/i.test(command)) {
    const doc = await loadBottleneckV3(await pinPublicSnapshot(env));
    if (doc) return buildBottleneckTop20Messages(doc, commandText ? "text" : "flex");
  }
  const bottleneckDetail = /^(?:瓶頸詳情|瓶颈详情|瓶頸|瓶颈)\s*([A-Za-z0-9][A-Za-z0-9.\-]{0,15})(?:\s*文字)?$/i.exec(command);
  if (bottleneckDetail) {
    const doc = await loadBottleneckV3(await pinPublicSnapshot(env));
    return doc ? buildBottleneckDetail(doc, bottleneckDetail[1]!, commandText ? "text" : "flex")
      : "瓶頸爆發 TOP20 目前沒有已封存且在時效內的資料，未以舊資料替代。";
  }
  // "NVDA 詳情" opens the detail only for a current Top20 company; any other ticker keeps its research answer.
  const tickerDetail = /^([A-Za-z0-9][A-Za-z0-9.\-]{0,15})\s*(?:詳情|详情)(?:\s*文字)?$/i.exec(command);
  if (tickerDetail) {
    const doc = await loadBottleneckV3(await pinPublicSnapshot(env));
    if (doc && findBottleneckEntry(doc, tickerDetail[1]!)) return buildBottleneckDetail(doc, tickerDetail[1]!, commandText ? "text" : "flex");
  }
  if (/^(?:產業爆發榜|产业爆发榜|產業爆發|产业爆发|產業(?:排名|排行榜?|榜)|产业(?:排名|排行榜?|榜))(?:\s*文字)?$/i.test(command)) {
    const doc = await loadBottleneckV3(await pinPublicSnapshot(env));
    return doc ? buildIndustryExplosionMessages(doc, commandText ? "text" : "flex") : "產業爆發榜目前沒有已封存且在時效內的資料，未以舊資料替代。";
  }
  if (/^(?:七欄\s*top\s*20|舊版\s*top\s*20)(?:\s*文字)?$/i.test(command)) {
    return v213Top20LineAnswer(env, { ...query, normalized: /文字\s*$/.test(command) ? "Top20 文字" : "Top20" });
  }
  if (/^(?:選單|菜单|menu|功能導覽|功能导航)$/i.test(command)) {
    return panel("研究功能導覽", "三個入口 · 不連券商 · 不自動下單", [
      "A｜TOP20：瓶頸爆發 TOP20（Serenity／Leopold 線索＋財報、訂單與交易所報價）；輸入「瓶頸詳情 代號」（例：瓶頸詳情 NVDA）看單一公司完整卡片。歷史報酬不是未來預測。",
      "B｜宏觀產業分析：TOP5產業總覽與12–36M因果鏈分析；輸入「產業爆發榜」看 Leopold 因果鏈產業排序。",
      "C｜期權與個股快查：輸入「代號 每月期權」或「代號 每週期權」（例：NVDA 每月期權，格式範例非推薦）看備兌買權建議；直接輸入代號或名稱（例：2330、SIVE）查延遲報價；「期權教學」看策略範例。",
      "D｜資料驅動潛力榜：輸入「潛力榜」；依官方資料每日重算，輸入「潛力報告 代號」看逐項數據報告，「訂單實現榜」看已簽約訂單覆蓋排序。",
      "E｜舊版七欄榜請輸入「七欄Top20」。本服務不連券商、不下單，內容非投資建議。",
    ], NAV, isEnvText);
  }

  // --- Primary Macro Home Entry: 宏觀產業分析 & TOP5 產業總覽 ---
  if (/^(?:宏觀產業分析|宏观产业分析)(?:\s*文字)?$/i.test(command)) {
    const isText = isEnvText || /文字\s*$/i.test(command);
    const view = await pinPublicSnapshot(env);

    // 1. If sealed snapshot has admitted TOP5 overview, show it
    if (view.integrity === "sealed") {
      const overview = await view.json<MacroTop5Overview>([MACRO_PRODUCT_KEY]);
      if (overview && overview.status === "ADMITTED_TOP5" && overview.qualified_count >= 5) {
        return isText ? buildMacroTop5OverviewText(overview) : buildMacroTop5OverviewFlex(overview);
      }
    }

    // 2. Check Top20 fresh report for company industry distribution context
    const report = await loadV213FreshTop20Report(env, parseQuery("Top20"));
    const navActions = [
      ["TOP5 產業總覽", "TOP5產業總覽"],
      ["TOP20 公司證據", "TOP20"],
      ["宏觀數據要求", "宏觀資料說明"],
      ["回功能選單", "選單"],
    ] as const;

    if (!report || typeof report === "string") {
      const errLines = [
        "MACRO_TOP5_SHORTFALL：目前尚無已驗收封存之 TOP5 宏觀產業報告（短缺通報：5/5）。",
        `當輪產業資料不可用：${typeof report === "string" ? report : "TOP20_UNAVAILABLE"}。`,
        "不以舊快照、候選宏觀資料或模型猜測補齊。",
        "工程規範：系統拒絕捏造未查證之行業、拒絕以候選公司家數占比冒充市場成長率、拒絕湊數發布偽 TOP5。",
      ];
      return panel("宏觀產業分析", "當輪產業資料不可用 · 短缺通報", errLines, navActions, isText);
    }

    if (!(await v213EvidenceWithinWindow(report.records.map(r => ({ freshAsOf: r.orders_state_as_of, retrievedAt: r.retrieved_at, evidenceClass: r.evidence_class, sealTime: report.generated_at }))))) {
      const staleLines = [
        "MACRO_TOP5_SHORTFALL：目前尚無已驗收封存之 TOP5 宏觀產業報告（短缺通報：5/5）。",
        "公司資料過期：" + V213_STALE_RECORDS_MESSAGE,
      ];
      return panel("宏觀產業分析", "公司資料過期 · 短缺通報", staleLines, navActions, isText);
    }

    // Report is fresh: compute candidate distribution with explicit disclaimers
    const sectors = new Map<string, string[]>();
    for (const row of report.records) sectors.set(row.industry, [...(sectors.get(row.industry) ?? []), row.ticker]);
    const groups = [...sectors].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));

    const visibleGroups = groups.slice(0, 5);
    const lines = [
      "TOP5 宏觀產業總覽准入門檻未達成（MACRO_TOP5_SHORTFALL：短缺通報 5/5）。",
      "MACRO_PRODUCT_NOT_SEALED：目前尚無已驗收的獨立宏觀報告。GDP、CPI、利率、匯率等值不得由來源健康狀態或候選資料直接升格發布。",
      "以下僅為當輪候選公司家數占比（參考資訊，不是市值／營收權重，不代表全球產業排名，非 TOP5 宏觀產業分析）：",
      `當輪時間：${report.generated_at}；樣本20家公司。`,
      ...(groups.length > visibleGroups.length
        ? [`摘要顯示${visibleGroups.length}/${groups.length}類；其餘${groups.length - visibleGroups.length}類請看完整文字`] : []),
      ...visibleGroups.map(([industry, tickers]) => `${industry}｜${tickers.length}/20家（${(tickers.length / 20 * 100).toFixed(0)}%）\n${tickers.join("、")}`),
      "傳導框架：需求→交付／產能→營收及毛利→現金流／融資→每股價值；每條關係均須另有公司證據。",
    ];

    if (isText) {
      const fullLines = [
        "【宏觀產業分析｜TOP5 准入門檻未達成 · 短缺通報】",
        "TOP5 宏觀產業總覽准入門檻未達成（MACRO_TOP5_SHORTFALL：短缺通報 5/5）。",
        "MACRO_PRODUCT_NOT_SEALED：目前尚無已驗收的獨立宏觀報告。GDP、CPI、利率、匯率等值不得由來源健康狀態或候選資料直接升格發布。",
        "以下僅為當輪候選公司家數占比（參考資訊，不是市值／營收權重，不代表全球產業排名，非 TOP5 宏觀產業分析）：",
        `當輪時間：${report.generated_at}；樣本20家公司。`,
        ...groups.map(([industry, tickers]) => `${industry}｜${tickers.length}/20家（${(tickers.length / 20 * 100).toFixed(0)}%）\n${tickers.join("、")}`),
        "傳導框架：需求→交付／產能→營收及毛利→現金流／融資→每股價值；每條關係均須另有公司證據。",
        "",
        "快捷指令：",
        ...navActions.map(([label, cmd]) => `• ${label}：${cmd}`),
      ];
      return [{ type: "text", text: fullLines.join("\n") }];
    }

    return panel("宏觀產業分析", "TOP5 准入門檻未達成 · 短缺通報", lines, navActions, false);
  }

  // --- Direct TOP5 產業總覽 ---
  if (/^(?:TOP5(?:產業總覽|產業)?|宏觀(?:產業)?總覽)(?:\s*文字)?$/i.test(command)) {
    const isText = isEnvText || /文字\s*$/i.test(command);
    const view = await pinPublicSnapshot(env);
    if (view.integrity === "sealed") {
      const overview = await view.json<MacroTop5Overview>([MACRO_PRODUCT_KEY]);
      if (overview && overview.status === "ADMITTED_TOP5" && overview.qualified_count >= 5) {
        return isText ? buildMacroTop5OverviewText(overview) : buildMacroTop5OverviewFlex(overview);
      }
    }
    return macroShortfallReport(0, isText);
  }

  // Compatibility route: 当轮候选公司产业分布 (preserved separately)
  if (/^(?:當輪產業分布|当轮产业分布|產業分布|产业分布|TOP20產業分布)(?:\s*文字)?$/i.test(command)) {
    const macroText = isEnvText || /文字\s*$/i.test(command);
    const report = await loadV213FreshTop20Report(env, parseQuery("Top20"));
    const actions = [["TOP20 公司證據", "TOP20"], ["宏觀產業分析", "宏觀產業分析"], ["回功能選單", "選單"]] as const;
    if (!report || typeof report === "string") {
      return panel("當輪產業分布", "當輪產業資料不可用", [
        typeof report === "string" ? report : "TOP20_UNAVAILABLE",
        "不以舊快照、候選宏觀資料或模型猜測補齊。",
      ], actions, macroText);
    }
    if (!(await v213EvidenceWithinWindow(report.records.map(r => ({ freshAsOf: r.orders_state_as_of, retrievedAt: r.retrieved_at, evidenceClass: r.evidence_class, sealTime: report.generated_at }))))) {
      return panel("當輪產業分布", "公司資料過期", [V213_STALE_RECORDS_MESSAGE], actions, macroText);
    }
    const sectors = new Map<string, string[]>();
    for (const row of report.records) sectors.set(row.industry, [...(sectors.get(row.industry) ?? []), row.ticker]);
    const groups = [...sectors].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
    if (macroText) {
      const lines = [
        "MACRO_PRODUCT_NOT_SEALED：目前尚無已驗收的獨立宏觀報告。GDP、CPI、利率、匯率等值不得由來源健康狀態或候選資料直接升格發布。",
        "以上是候選公司家數占比，不是市值／營收權重，也不代表全球產業排名或投資配置比例。",
        `當輪時間：${report.generated_at}；樣本20家公司。`,
        ...groups.map(([industry, tickers]) => `${industry}｜${tickers.length}/20家（${(tickers.length / 20 * 100).toFixed(0)}%）\n${tickers.join("、")}`),
        "傳導框架：需求→交付／產能→營收及毛利→現金流／融資→每股價值；每條關係均須另有公司證據。",
      ];
      return panel("當輪產業分布", "當輪候選公司分布 · 宏觀深度報告請看宏觀產業分析", lines, actions, true);
    }
    const visibleGroups = groups.slice(0, 5);
    const lines = [
      "MACRO_PRODUCT_NOT_SEALED：目前尚無已驗收的獨立宏觀報告。GDP、CPI、利率、匯率等值不得由來源健康狀態或候選資料直接升格發布。",
      "以上是候選公司家數占比，不是市值／營收權重，也不代表全球產業排名或投資配置比例。",
      `當輪時間：${report.generated_at}；樣本20家公司。`,
      ...(groups.length > visibleGroups.length
        ? [`摘要顯示${visibleGroups.length}/${groups.length}類；其餘${groups.length - visibleGroups.length}類請看完整文字`] : []),
      ...visibleGroups.map(([industry, tickers]) => `${industry}｜${tickers.length}/20家（${(tickers.length / 20 * 100).toFixed(0)}%）\n${tickers.join("、")}`),
      "傳導框架：需求→交付／產能→營收及毛利→現金流／融資→每股價值；每條關係均須另有公司證據。",
    ];
    return panel("當輪產業分布", "當輪候選公司分布 · 宏觀深度報告請看宏觀產業分析", lines,
      [["完整產業分布文字", "當輪產業分布 文字"], ...actions], false);
  }

  if (/^(?:宏觀資料說明|宏观资料说明)$/.test(command)) return panel("宏觀數據要求", "數值、期間、單位、發布日期必須分開", [
    "GDP：實質／名目及年度／季度口徑；CPI：指數水準不能當年增率；利率：政策利率不能當公司融資成本；匯率：必須有貨幣對與報價方向。",
    "保留原始來源、資料期、修訂、取得時間與再散布資格；World Bank、BLS、ECB來源健康不代表最新數值已完成驗收。",
    "Serenity是主要公開研究視角；Leopold為CONTEXT_ONLY。宏觀情境不能直接證明單一公司訂單、瓶頸或股價漲幅。",
  ], NAV, isEnvText);

  // --- Primary Options Entry: 期權 / 期權與個股快查 ---
  if (/^(?:期權|期权|選擇權|选择权|期權與個股快查|期权与个股快查)(?:\s*文字)?$/i.test(command)) {
    const isText = isEnvText || /文字\s*$/i.test(command);
    const view = await pinPublicSnapshot(env);
    const statusText = view.integrity === "sealed"
      ? "備兌買權建議（持有100股賣買權收權利金）：觀察清單內美股（Yahoo Finance，延遲、非官方）與 Nasdaq Stockholm（交易所公開 API，延遲）每小時更新；每個週期給兩個價格：高履約價（不易被賣掉）與平衡型。清單外標的或無雙邊報價時維持不可用。"
      : "OPTION_DATA_UNAVAILABLE：目前沒有已封存驗收的公開期權快照；舊鍵 options:latest／latest_options 殘留或存在本身不計為可用，不代表權利金為0或沒有風險。";

    const navActions = [
      ["範例：NVDA 每月期權", "NVDA 每月期權"],
      ["期權試算說明", "期權試算說明"],
      ["TOP20 個股入口", "TOP20"],
      ["回功能選單", "選單"],
    ] as const;

    if (isText) {
      const overviewMessages = panelTextMessages("期權與個股快查", "股票代號 → 每週／每月 → 報價與風險", [
        statusText,
        "查詢例：NVDA 每週期權、AAPL 每月期權（僅格式範例，不是推薦）。個股資訊請輸入股票代號；完整深度產品仍須封存驗收。",
        "「代號 每週期權／每月期權」只顯示已封存的延遲觀察：到期日/DTE、履約價、Bid/Ask、建議賣出限價、Delta、OI/成交量及年化收益；限價不保證成交。未註明週期時顯示每週。",
        "無自動報價時可用「期權試算說明」做本次輸入的算術試算；結果標示未驗證，不存持倉、不連IBKR、不下單。",
        "以下提供 4 種標準期權教學策略卡片（教學範例，非推薦）：",
      ], navActions);

      const eduMessages = buildEducationalStrategyText();
      const combined = [overviewMessages[0]!, ...eduMessages.slice(0, 4)];
      assertLineMessages(combined);
      return combined;
    }

    const overviewBubble = {
      type: "bubble" as const,
      size: "mega" as const,
      header: productHeader("韭菜守護者 · 公開研究", "期權與個股快查"),
      body: menuBox([
        sectionTitle("股票代號 → 每週／每月 → 報價與風險"),
        menuText(statusText, "sm", T.ink),
        menuText("本入口整合逐約報價查詢與 4 種標準期權策略教學範例；請向右滑動查看教學卡片。", "xs", T.subtle),
      ], { backgroundColor: T.paper, paddingAll: "xl" }),
      footer: menuBox(navActions.map(([label, cmd]) => menuAction(label, cmd)), { ...footerStyle }),
    };

    const eduFlex = buildEducationalStrategyFlex();
    const eduBubbles = (eduFlex[0] as any).contents.contents;
    const allBubbles = [overviewBubble, ...eduBubbles.slice(0, 4)];

    const messages: LineOutboundMessage[] = [{
      type: "flex",
      altText: "期權與個股快查｜策略教學與公開報價",
      contents: {
        type: "carousel",
        contents: allBubbles,
      },
    }];
    assertLineMessages(messages);
    return messages;
  }

  // --- Legacy / Direct latest options command ---
  if (/^(?:最新期權|最新期权)(?:\s*文字)?$/i.test(command)) {
    const isText = isEnvText || /文字\s*$/i.test(command);
    const view = await pinPublicSnapshot(env);
    return optionsUnavailableReport(
      "MARKET",
      null,
      view.integrity === "sealed"
        ? "當輪已封存快照的契約物件集合不含期權物件（OPTION_DATA_NOT_ADMITTED）；未封存殘留鍵不構成可用報價。"
        : "目前沒有已封存驗收的公開期權快照（OPTION_DATA_UNAVAILABLE）；舊殘留鍵不構成可用報價。",
      isText,
    );
  }

  // --- Data-driven potential ranking, sealed inside the TOP5 overview object ---
  const potentialReport = /^(?:潛力報告|潜力报告)\s*([A-Za-z]{1,5})(?:\s*文字)?$/i.exec(command);
  const orderView = /^(?:訂單實現榜|订单实现榜|訂單榜)(?:\s*文字)?$/i.test(command);
  if (potentialReport || orderView || /^(?:潛力榜|潜力榜|資料驅動潛力榜|潛力\s*top\s*20)(?:\s*文字)?$/i.test(command)) {
    const isText = isEnvText || /文字\s*$/i.test(command);
    const view = await pinPublicSnapshot(env);
    const overview = view.integrity === "sealed" ? await view.json<Record<string, unknown>>([MACRO_PRODUCT_KEY]) : null;
    const ranking = validatePotentialRanking(overview?.potential_ranking);
    if (!ranking) {
      return panel("資料驅動潛力榜", "本輪未封存", [
        "POTENTIAL_RANKING_UNAVAILABLE：本輪封存快照沒有可驗證的資料驅動潛力榜。",
        "不以模型生成、舊資料或其他清單代替。",
      ], [["TOP5 產業總覽", "TOP5產業總覽"], ["回功能選單", "選單"]], isText);
    }
    if (potentialReport) return buildPotentialReport(ranking, potentialReport[1]!, String(overview?.generated_at ?? ranking.as_of), isText);
    if (orderView) return isText ? buildOrderRealizationText(ranking) : buildOrderRealizationFlex(ranking);
    return isText ? buildPotentialRankingText(ranking) : buildPotentialRankingFlex(ranking);
  }

  const cardMatch = /^(?:宏觀產業\s*卡片|宏觀產業卡片)\s+([A-Za-z0-9_-]+)(?:\s*文字)?$/i.exec(command);
  if (cardMatch) {
    const isText = isEnvText || /文字\s*$/i.test(command);
    const targetId = cardMatch[1]!.toLowerCase();
    const view = await pinPublicSnapshot(env);
    if (view.integrity === "sealed") {
      const card = await sealedMacroEntry(view, targetId, "card") as MacroIndustryCard | null;
      if (card) {
        return isText ? buildMacroIndustryCardText(card) : buildMacroIndustryCardFlex(card);
      }
    }
    const lines = [
      `MACRO_CARD_UNAVAILABLE：宏觀產業卡片「${targetId}」目前未在已驗收封存快照中。`,
      "不以模型生成、未經審查草稿或推測數據替代正式產業卡片。",
    ];
    return panel("宏觀產業卡片", "卡片未封存准入", lines, [["回 TOP5 產業總覽", "TOP5產業總覽"], ["回功能選單", "選單"]], isText);
  }

  const deepMatch = /^(?:宏觀產業\s*深度化分析|宏觀產業深度化分析)\s+([A-Za-z0-9_-]+)(?:\s*文字)?$/i.exec(command);
  if (deepMatch) {
    const isText = isEnvText || /文字\s*$/i.test(command);
    const targetId = deepMatch[1]!.toLowerCase();
    const view = await pinPublicSnapshot(env);
    if (view.integrity === "sealed") {
      const deep = await sealedMacroEntry(view, targetId, "deep") as MacroDeepAnalysis | null;
      if (deep) {
        return isText ? buildMacroDeepAnalysisText(deep) : buildMacroDeepAnalysisFlex(deep);
      }
    }
    const lines = [
      `MACRO_DEEP_UNAVAILABLE：產業「${targetId}」深度化分析未在已驗收封存快照中。`,
      "深度化分析必須具備需求→供給→瓶頸→定價→資本支出→競爭→受益者→催化劑→風險→證偽10維完整展開與公開文獻引用。",
    ];
    return panel("宏觀產業深度化分析", "深度報告未封存准入", lines, [["回 TOP5 產業總覽", "TOP5產業總覽"], ["回功能選單", "選單"]], isText);
  }

  // --- Standalone Educational Options Strategies ---
  const eduMatch = /^(?:期權教學|期權策略教學|期權教學範例|期權策略範例)(?:\s+([a-zA-Z0-9_\u4e00-\u9fa5]+))?(?:\s*文字)?$/i.exec(command);
  if (eduMatch) {
    const isText = isEnvText || /文字\s*$/i.test(command);
    const rawStrat = eduMatch[1]?.trim().toLowerCase();
    if (!rawStrat) {
      return isText ? buildEducationalStrategyText() : buildEducationalStrategyFlex();
    }
    const canonicalId = STRATEGY_ALIASES[rawStrat];
    if (!canonicalId) {
      const errLines = [
        `UNKNOWN_STRATEGY：未知的期權策略代號「${rawStrat}」。`,
        "系統僅提供以下四種標準教學範例策略：",
        "• covered_call（Covered Call / 掩護性買權）",
        "• cash_secured_put（Cash-Secured Put / 現金擔保賣權）",
        "• bull_call_spread（Bull Call Spread / 買權多頭價差）",
        "• protective_put（Protective Put / 保護性賣權）",
      ];
      return panel("期權策略教學", "未知策略代號", errLines, [["查看全部教學", "期權教學"], ["回功能選單", "選單"]], isText);
    }
    return isText ? buildEducationalStrategyText(canonicalId) : buildEducationalStrategyFlex(canonicalId);
  }

  // --- Options Quote Functional Queries ---
  // A ticker may carry a share class after a space as the stock lookup shows it (VOLV B, NDA SE, OCTV SDB).
  // Without a cycle word only the Chinese option words count after a ticker ("NVDA 期權"), so English such as
  // "call options" is never read as a ticker.
  const quoteMatch = /^([A-Z0-9][A-Z0-9./-]{0,14}(?: [A-Z]{1,3})?)\s*(每週|每周|每月|weekly|monthly)\s*(?:期權|期权|選擇權|选择权|options?)(?:\s*文字)?$/i.exec(command)
    || /^([A-Z0-9][A-Z0-9./-]{0,14}(?: [A-Z]{1,3})?)\s*()(?:期權|期权|選擇權|选择权)(?:\s*文字)?$/i.exec(command)
    || /^(?:(?:期權|期权|選擇權|选择权)\s*|options?\s+)([A-Z0-9][A-Z0-9./-]{0,14}(?: [A-Z]{1,3})?)\s*(每週|每周|每月|weekly|monthly)?(?:\s*文字)?$/i.exec(command);
  if (quoteMatch) {
    const isText = isEnvText || /文字\s*$/i.test(command);
    const ticker = quoteMatch[1]!.toUpperCase();
    const periodRaw = quoteMatch[2];  // both forms: group 1 ticker, group 2 period (optional after 期權; weekly by default)
    const period = periodRaw && /每月|monthly/i.test(periodRaw) ? "monthly" : "weekly";

    // Non-ticker words filter
    if (!["教學", "試算說明", "HELP", "TOP20"].includes(ticker)) {
      const view = await pinPublicSnapshot(env);
      if (view.integrity === "sealed") {
        // Sealed delayed observations of the watch universe (US options and Nasdaq Stockholm options).
        const observed = await loadOptionObservation(view, optionTickerKeys(ticker), period);
        if (observed && "unavailable" in observed) {
          return optionsUnavailableReport(ticker, period, `${observed.unavailable}（已封存之公開觀察）`, isText);
        }
        if (observed && "quote" in observed) {
          const cycle = validateCoveredCallCycle(observed.quote);
          return cycle ? buildCoveredCallMessages(cycle, period === "weekly" ? "每週期權" : "每月期權", isText ? "text" : "flex")
            : optionsUnavailableReport(ticker, period, "封存之期權觀察未通過驗證，已拒絕顯示。", isText);
        }
        const quote = await view.json<OptionContractQuote>([`options:${ticker}:${period}:latest`]);
        if (quote) {
          return isText ? buildOptionContractText(quote) : buildOptionContractFlex(quote);
        }
      }
      return optionsUnavailableReport(
        ticker,
        period,
        view.integrity === "sealed"
          ? "當輪已封存快照不含期權物件（OPTION_DATA_NOT_ADMITTED）；無已驗證之公開報價。"
          : "目前無已封存驗收之公開期權快照（OPTION_DATA_UNAVAILABLE）；殘留鍵不構成可用報價。",
        isText,
      );
    }
  }

  return v213Top20LineAnswer(env, query);
}
