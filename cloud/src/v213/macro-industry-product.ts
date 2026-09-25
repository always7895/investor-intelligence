/**
 * Macro Industry Research Product (12-36M horizon).
 * Implements:
 * 1. Overview card titled "TOP5產業總覽" with navigation into each independent industry card.
 * 2. Independent industry cards (all qualified cards rendered, carousels <= 5 bubbles per LINE limits).
 * 3. Deep route "深度化分析" unfolding demand→supply→bottleneck→pricing→capex→competition→beneficiaries→catalysts→risks→killers with source refs.
 * 4. Deterministic shortfall reporting when <5 qualified candidates admitted (fails live TOP5 acceptance).
 * 5. Strict rejection of company-count percentage as market growth.
 * 6. Mobile layout enforcement: bubbles <= 5 per carousel, actions <= 4, chunks <= 5, chars <= 4900 via assertLineMessages.
 */

import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import { LINE_THEME as T, menuAction, menuBox, menuText, headerStyle, footerStyle } from "./line-theme";
import type {
  MacroDeepAnalysis,
  MacroGrowthRate,
  MacroIndustryCard,
  MacroTop5Overview,
} from "./market-product-schema";
import {
  validateMacroDeepAnalysis,
  validateMacroIndustryCard,
  validateMacroTop5Overview,
} from "./market-product-schema";

export const MACRO_PRODUCT_KEY = "v213:macro-industry:latest";

export function formatGrowthRate(growth: MacroGrowthRate | null): string {
  if (!growth) return "UNAVAILABLE（無已驗收來源之獨立市場成長率）";
  const sign = growth.rate_pct > 0 ? "+" : "";
  const pct = `${sign}${growth.rate_pct.toFixed(1)}${growth.units}`;
  const typeStr = growth.type === "forecast" ? "預估" : "實際";
  const srcId = growth.source_id ? `來源代號：${growth.source_id}｜` : "";
  return `${pct}（${growth.period}｜${typeStr}｜${srcId}發布者：${growth.publisher}｜日期：${growth.date}）`;
}

export function buildMacroOverviewBubble(overview: MacroTop5Overview) {
  const isShortfall = overview.status === "SHORTFALL_NOT_QUALIFIED" || overview.qualified_count < 5;
  const statusBadge = isShortfall
    ? `【未達准入門檻 · 短缺通報】合格產業僅 ${overview.qualified_count}/5`
    : `【正式准入 TOP5】基準日：${overview.generated_at}`;

  const summaryLines = overview.industries.map(
    ind => `• 第${ind.rank !== null ? ind.rank : "—"}名：${ind.industry_name}（機會分：${ind.opportunity_score}）`,
  );

  const actionButtons = overview.industries.slice(0, 3).map(ind =>
    menuAction(`第${ind.rank !== null ? ind.rank : "1"}名卡片`, `宏觀產業 卡片 ${ind.industry_id}`),
  );

  return {
    type: "bubble",
    size: "mega",
    header: menuBox([
      menuText("韭菜守護者 · 宏觀產業研究", "xs", T.headerMuted),
      { ...menuText(overview.title, "xl", T.headerText), weight: "bold" },
      menuText(`觀察週期：${overview.horizon}｜${statusBadge}`, "xs", isShortfall ? T.headerAlert : T.headerMuted),
    ], { ...headerStyle }),
    body: menuBox([
      menuBox([
        menuText("准入與短缺狀態說明", "xs", T.muted),
        menuText(
          isShortfall
            ? `短缺通報：符合高標準市場成長率、瓶頸與價值鏈證據之合格產業候選僅 ${overview.qualified_count} 個（未達 5 個門檻）。系統拒絕假裝湊滿 5 個或捏造虛假排名。`
            : "本總覽由候選產業池依量化機會準則動態評選產生，非固定前五大產業清單，絕不以候選公司家數占比冒充市場成長率。",
          "xs",
          isShortfall ? T.negative : T.ink,
        ),
      ], { backgroundColor: isShortfall ? T.paleNegative : T.soft, paddingAll: "sm", cornerRadius: "sm" }),
      menuBox([
        menuText("評選名單", "xs", T.muted),
        ...(summaryLines.length > 0 ? summaryLines.map(line => menuText(line, "sm", T.ink)) : [menuText("（當前無合格准入產業）", "xs", T.muted)]),
      ], { spacing: "xs" }),
      { type: "separator", color: T.border },
      menuBox([
        menuText("機會分數定義（System Operationalization）", "xs", T.muted),
        menuText("評分包含需求能見度(25)、瓶頸緊繃度(25)、定價權(20)、價值鏈捕獲(15)與催化劑清晰度(15)，為工程化排序指標，非投資成功機率。", "xxs", T.muted),
      ], { spacing: "xs" }),
    ], { paddingAll: "lg", spacing: "md", backgroundColor: T.paper }),
    footer: menuBox([
      ...actionButtons,
      menuAction("宏觀數據要求", "宏觀資料說明"),
      menuAction("回功能選單", "選單"),
    ].slice(0, 4), { paddingAll: "md", backgroundColor: T.soft }),
  };
}

export function buildMacroIndustryCardBubble(card: MacroIndustryCard) {
  const growthText = formatGrowthRate(card.growth);
  const confidenceBadge = `資料完整度 ${card.confidence.data_completeness}%｜來源獨立性 ${card.confidence.source_independence}%｜核驗：${card.confidence.verification_status}`;
  const rankLabel = card.rank !== null ? `第 ${card.rank} 名` : "未排定（未准入）";

  return {
    type: "bubble",
    size: "mega",
    header: menuBox([
      menuText(`宏觀產業 · ${rankLabel}`, "xs", T.headerMuted),
      { ...menuText(card.industry_name, "lg", T.headerText), weight: "bold" },
      menuText(`機會分數：${card.opportunity_score}/100（量化評分，非機率）`, "xs", T.headerSubtle),
    ], { ...headerStyle }),
    body: menuBox([
      menuBox([
        menuText("當前狀態與 12–36M 展望", "xs", T.muted),
        menuText(`現況：${card.current_state}`, "xs", T.ink),
        menuText(`展望：${card.outlook_12_36m}`, "xs", T.ink),
      ], { backgroundColor: T.soft, paddingAll: "sm", cornerRadius: "sm" }),
      menuBox([
        menuText("可查證市場成長率（RATE）", "xs", T.muted),
        { ...menuText(growthText, "xs", card.growth ? T.ink : T.negative), weight: "bold" },
      ], { spacing: "xs" }),
      { type: "separator", color: T.border },
      menuBox([
        menuText("需求驅動與供給瓶頸（Chokepoint）", "xs", T.muted),
        menuText(`需求：${card.demand_drivers.join("；")}`, "xs", T.ink),
        menuText(`瓶頸：${card.supply_constraint_chokepoint}`, "xs", T.ink),
        menuText(`定價權：${card.pricing}`, "xs", T.ink),
      ], { spacing: "xs" }),
      menuBox([
        menuText("價值鏈位置與主要受益者", "xs", T.muted),
        menuText(`位置：${card.value_chain_position}`, "xs", T.ink),
        menuText(`受益者/關鍵供應商：${card.beneficiaries_key_suppliers.join("、")}`, "xs", T.ink),
      ], { spacing: "xs" }),
      menuBox([
        menuText("催化劑時程（6M / 1Y / 2Y）", "xs", T.muted),
        menuText(`• 6M：${card.catalysts.m6}`, "xxs", T.ink),
        menuText(`• 1Y：${card.catalysts.y1}`, "xxs", T.ink),
        menuText(`• 2Y：${card.catalysts.y2}`, "xxs", T.ink),
      ], { backgroundColor: T.soft, paddingAll: "sm", cornerRadius: "sm", borderColor: T.frame, borderWidth: "light" }),
      menuBox([
        menuText("生命週期與風險", "xs", T.muted),
        menuText(card.risks_lifecycle, "xs", T.muted),
      ], { spacing: "xs" }),
    ], { paddingAll: "lg", spacing: "sm", backgroundColor: T.paper }),
    footer: menuBox([
      menuText(confidenceBadge, "xxs", T.muted),
      menuAction("深度化分析（10維因果）", `宏觀產業 深度化分析 ${card.industry_id}`),
      menuAction("回 TOP5 產業總覽", "TOP5產業總覽"),
      menuAction("回功能選單", "選單"),
    ], { paddingAll: "md", backgroundColor: T.soft }),
  };
}

export function buildMacroDeepAnalysisBubble(analysis: MacroDeepAnalysis) {
  const sourcesText = analysis.source_references
    .map(s => `• ${s.source}：${s.url}${s.passage ? `（${s.passage}）` : ""}`)
    .join("\n");

  return {
    type: "bubble",
    size: "mega",
    header: menuBox([
      menuText("宏觀產業 · 深度化分析（10維因果鏈展開）", "xs", T.headerMuted),
      { ...menuText(analysis.industry_name, "lg", T.headerText), weight: "bold" },
      menuText("需求→供給→瓶頸→定價→資本支出→競爭→受益者→催化劑→風險→證偽", "xxs", T.headerMuted),
    ], { ...headerStyle }),
    body: menuBox([
      menuBox([
        menuText("1. 需求傳導 (Demand) 與 2. 供給現況 (Supply)", "xs", T.muted),
        menuText(`需求：${analysis.demand}`, "xs", T.ink),
        menuText(`供給：${analysis.supply}`, "xs", T.ink),
      ], { backgroundColor: T.soft, paddingAll: "sm", cornerRadius: "sm" }),
      menuBox([
        menuText("3. 核心瓶頸 (Bottleneck) 與 4. 定價機制 (Pricing)", "xs", T.muted),
        menuText(`瓶頸：${analysis.bottleneck}`, "xs", T.ink),
        menuText(`定價：${analysis.pricing}`, "xs", T.ink),
      ], { spacing: "xs" }),
      menuBox([
        menuText("5. 資本支出 (Capex) 與 6. 競爭格局 (Competition)", "xs", T.muted),
        menuText(`資本支出：${analysis.capex}`, "xs", T.ink),
        menuText(`競爭：${analysis.competition}`, "xs", T.ink),
      ], { spacing: "xs" }),
      menuBox([
        menuText("7. 核心受益廠商 (Beneficiaries)", "xs", T.muted),
        menuText(analysis.beneficiaries.join("、"), "xs", T.ink),
      ], { spacing: "xs" }),
      menuBox([
        menuText("8. 催化時程 (Catalysts: 6M / 1Y / 2Y)", "xs", T.muted),
        menuText(`6M: ${analysis.catalysts.m6}｜1Y: ${analysis.catalysts.y1}｜2Y: ${analysis.catalysts.y2}`, "xxs", T.ink),
      ], { backgroundColor: T.soft, paddingAll: "sm", cornerRadius: "sm", borderColor: T.frame, borderWidth: "light" }),
      menuBox([
        menuText("9. 主要產業風險 (Risks)", "xs", T.muted),
        ...analysis.risks.map(r => menuText(`• ${r}`, "xs", T.muted)),
      ], { spacing: "xs" }),
      menuBox([
        menuText("10. 邏輯證偽點 (Thesis Killers)", "xs", T.negative),
        ...analysis.killers.map(k => menuText(`⚠️ ${k}`, "xs", T.negative)),
      ], { backgroundColor: T.paleNegative, paddingAll: "sm", cornerRadius: "sm" }),
    ], { paddingAll: "lg", spacing: "sm", backgroundColor: T.paper }),
    footer: menuBox([
      menuText("【來源憑證依據】\n" + (sourcesText || "無外部引用"), "xxs", T.muted),
      menuAction("查看該產業卡片", `宏觀產業 卡片 ${analysis.industry_id}`),
      menuAction("回 TOP5 產業總覽", "TOP5產業總覽"),
      menuAction("回功能選單", "選單"),
    ], { paddingAll: "md", backgroundColor: T.soft }),
  };
}

export function buildMacroTop5OverviewFlex(overview: MacroTop5Overview): LineOutboundMessage[] {
  const validated = validateMacroTop5Overview(overview);
  const overviewBubble = buildMacroOverviewBubble(validated);
  // Carousel handles up to 5 bubbles per container per assertLineMessages
  // When >5 candidates, select top 5 ranked cards for primary display without losing overview disclosures
  const selectedCards = validated.industries.slice(0, 5);
  const cardBubbles = selectedCards.map(buildMacroIndustryCardBubble);

  const messages: LineOutboundMessage[] = [];

  const firstCarouselBubbles = [overviewBubble, ...cardBubbles.slice(0, 4)];
  messages.push({
    type: "flex",
    altText: `TOP5產業總覽（合格候選：${validated.qualified_count}家）`,
    contents: {
      type: "carousel",
      contents: firstCarouselBubbles,
    },
  });

  if (cardBubbles.length > 4) {
    messages.push({
      type: "flex",
      altText: `TOP5產業總覽 · 接續卡片`,
      contents: {
        type: "carousel",
        contents: cardBubbles.slice(4, 5),
      },
    });
  }

  assertLineMessages(messages);
  return messages;
}

export function buildMacroTop5OverviewText(overview: MacroTop5Overview): LineOutboundMessage[] {
  const validated = validateMacroTop5Overview(overview);
  const lines = [
    `【${validated.title}】`,
    `報告產生時間：${validated.generated_at}｜觀察週期：${validated.horizon}`,
    `准入狀態：${validated.status === "ADMITTED_TOP5" ? "合格准入 TOP5" : "未達准入門檻（短缺通報）"}`,
    `合格候選數：${validated.qualified_count}/5（短缺：${validated.shortfall}）`,
    "",
    ...(validated.shortfall > 0
      ? [
          "短缺通報：符合高標準市場成長率、瓶頸與價值鏈證據之合格產業候選不足 5 個。系統拒絕湊數假裝滿額。",
          "",
        ]
      : []),
    "評選名單摘要：",
    ...validated.industries.map(ind => {
      const g = formatGrowthRate(ind.growth);
      const rk = ind.rank !== null ? `第 ${ind.rank} 名` : "未定排名";
      return [
        `── ${rk}：${ind.industry_name}（機會分：${ind.opportunity_score}）──`,
        `現況：${ind.current_state}`,
        `12-36M 展望：${ind.outlook_12_36m}`,
        `市場成長率：${g}`,
        `需求驅動：${ind.demand_drivers.join("；")}`,
        `供給瓶頸：${ind.supply_constraint_chokepoint}`,
        `定價機制：${ind.pricing}`,
        `主要受益者：${ind.beneficiaries_key_suppliers.join("、")}`,
        `催化劑：6M ${ind.catalysts.m6}｜1Y ${ind.catalysts.y1}｜2Y ${ind.catalysts.y2}`,
        `生命週期與風險：${ind.risks_lifecycle}`,
      ].join("\n");
    }),
    "",
    "快捷指令：",
    ...validated.industries.map(ind => `• 查看卡片：宏觀產業 卡片 ${ind.industry_id}`),
    "• 深度化分析指令：宏觀產業 深度化分析 [ID]",
    "• 宏觀數據要求：宏觀資料說明",
    "• 回功能選單：選單",
  ];

  const fullText = lines.join("\n");
  if (fullText.length <= 4900) {
    const messages: LineOutboundMessage[] = [{ type: "text", text: fullText }];
    assertLineMessages(messages);
    return messages;
  }

  // Chunk if larger than 4900 chars
  const chunks: string[] = [];
  let cur = "";
  for (const block of lines) {
    if (!cur) cur = block;
    else if (cur.length + 1 + block.length <= 4800) cur += "\n" + block;
    else { chunks.push(cur); cur = block; }
  }
  if (cur) chunks.push(cur);

  const messages: LineOutboundMessage[] = chunks.map(text => ({ type: "text", text }));
  assertLineMessages(messages);
  return messages;
}

export function buildMacroIndustryCardFlex(card: MacroIndustryCard): LineOutboundMessage[] {
  const validated = validateMacroIndustryCard(card);
  const bubble = buildMacroIndustryCardBubble(validated);
  const rankLabel = validated.rank !== null ? `第${validated.rank}名` : "未定排名";
  const messages: LineOutboundMessage[] = [{
    type: "flex",
    altText: `宏觀產業卡片 · ${rankLabel}：${validated.industry_name}`,
    contents: {
      type: "carousel",
      contents: [bubble],
    },
  }];
  assertLineMessages(messages);
  return messages;
}

export function buildMacroIndustryCardText(card: MacroIndustryCard): LineOutboundMessage[] {
  const validated = validateMacroIndustryCard(card);
  const growth = formatGrowthRate(validated.growth);
  const rankLabel = validated.rank !== null ? `第 ${validated.rank} 名` : "未定排名";
  const text = [
    `【宏觀產業卡片 · ${rankLabel}】${validated.industry_name}`,
    `機會分數：${validated.opportunity_score}/100（System Operationalization 量化評分，非機率）`,
    `核驗狀態：${validated.confidence.verification_status}（完整度 ${validated.confidence.data_completeness}%，獨立性 ${validated.confidence.source_independence}%）`,
    "",
    `當前現況：${validated.current_state}`,
    `12–36M 展望：${validated.outlook_12_36m}`,
    `市場成長率：${growth}`,
    `需求驅動：${validated.demand_drivers.join("；")}`,
    `供給瓶頸：${validated.supply_constraint_chokepoint}`,
    `定價能力：${validated.pricing}`,
    `價值鏈位置：${validated.value_chain_position}`,
    `關鍵受益者：${validated.beneficiaries_key_suppliers.join("、")}`,
    `催化時程：6M ${validated.catalysts.m6}｜1Y ${validated.catalysts.y1}｜2Y ${validated.catalysts.y2}`,
    `風險與週期：${validated.risks_lifecycle}`,
    "",
    "快捷指令：",
    `• 深度化分析：宏觀產業 深度化分析 ${validated.industry_id}`,
    "• 回總覽：TOP5產業總覽",
    "• 回功能選單：選單",
  ].join("\n");

  const messages: LineOutboundMessage[] = [{ type: "text", text }];
  assertLineMessages(messages);
  return messages;
}

export function buildMacroDeepAnalysisFlex(analysis: MacroDeepAnalysis): LineOutboundMessage[] {
  const validated = validateMacroDeepAnalysis(analysis);
  const bubble = buildMacroDeepAnalysisBubble(validated);
  const messages: LineOutboundMessage[] = [{
    type: "flex",
    altText: `宏觀產業深度化分析 · ${validated.industry_name}`,
    contents: {
      type: "carousel",
      contents: [bubble],
    },
  }];
  assertLineMessages(messages);
  return messages;
}

export function buildMacroDeepAnalysisText(analysis: MacroDeepAnalysis): LineOutboundMessage[] {
  const validated = validateMacroDeepAnalysis(analysis);
  const sourcesText = validated.source_references
    .map(s => `• ${s.source}：${s.url}${s.passage ? `（${s.passage}）` : ""}`)
    .join("\n");

  const text = [
    `【宏觀產業 深度化分析】${validated.industry_name}`,
    "10維因果鏈展開：需求→供給→瓶頸→定價→資本支出→競爭→受益者→催化劑→風險→證偽",
    "",
    `1. 需求傳導 (Demand)：${validated.demand}`,
    `2. 供給現況 (Supply)：${validated.supply}`,
    `3. 核心瓶頸 (Bottleneck)：${validated.bottleneck}`,
    `4. 定價機制 (Pricing)：${validated.pricing}`,
    `5. 資本支出 (Capex)：${validated.capex}`,
    `6. 競爭格局 (Competition)：${validated.competition}`,
    `7. 關鍵受益廠商 (Beneficiaries)：${validated.beneficiaries.join("、")}`,
    `8. 催化時程 (Catalysts)：6M ${validated.catalysts.m6}｜1Y ${validated.catalysts.y1}｜2Y ${validated.catalysts.y2}`,
    "9. 產業風險 (Risks)：",
    ...validated.risks.map(r => `• ${r}`),
    "10. 證偽指標 (Thesis Killers)：",
    ...validated.killers.map(k => `⚠️ ${k}`),
    "",
    "【來源憑證】",
    sourcesText || "無外部引用",
    "",
    `快捷指令：查看卡片「宏觀產業 卡片 ${validated.industry_id}」、回總覽「TOP5產業總覽」、回選單「選單」`,
  ].join("\n");

  const messages: LineOutboundMessage[] = [{ type: "text", text }];
  assertLineMessages(messages);
  return messages;
}

export function macroShortfallReport(
  admittedCount: number,
  isText = false,
): LineOutboundMessage[] {
  const title = "TOP5產業總覽 · 准入門檻未達成";
  const lines = [
    `MACRO_TOP5_SHORTFALL：當輪合格產業候選僅 ${admittedCount} 個（不足 5 個）。`,
    "依據工程規範，系統拒絕捏造未查證之行業、拒絕以公司家數占比冒充市場成長率、拒絕湊數發布偽 TOP5。",
    "必須具備發布者、日期、計算期間、口徑與成長率 RATE 之客觀公開文獻，方可准入評選。",
    "目前正式封存契約尚未包含已驗收的 5 個產業產物。",
  ];
  const actions = [["宏觀數據要求", "宏觀資料說明"], ["回功能選單", "選單"]] as const;

  if (isText) {
    const text = [
      `【${title}】`,
      ...lines,
      "",
      "快捷指令：",
      "• 宏觀數據要求：宏觀資料說明",
      "• 回功能選單：選單",
    ].join("\n");
    const messages: LineOutboundMessage[] = [{ type: "text", text }];
    assertLineMessages(messages);
    return messages;
  }

  const messages: LineOutboundMessage[] = [{
    type: "flex",
    altText: title,
    contents: {
      type: "carousel",
      contents: [{
        type: "bubble",
        size: "mega",
        header: menuBox([
          menuText("韭菜守護者 · 宏觀產業研究", "xs", T.headerMuted),
          { ...menuText("TOP5 准入門檻未達成", "xl", T.headerText), weight: "bold" },
          menuText(`短缺通報：合格僅 ${admittedCount}/5 個`, "xs", T.headerAlert),
        ], { ...headerStyle }),
        body: menuBox(lines.map(p => menuText(p, "sm", T.ink)), { backgroundColor: T.paper, paddingAll: "lg" }),
        footer: menuBox(actions.map(([label, cmd]) => menuAction(label, cmd)), { ...footerStyle }),
      }],
    },
  }];
  assertLineMessages(messages);
  return messages;
}
