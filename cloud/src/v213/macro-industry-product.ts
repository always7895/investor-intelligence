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
import {
  LINE_THEME as T, chip, divider, footerStyle, footnote, headerStyle, menuAction, menuBox, menuText, meter, panel,
  packCarousels, railTitle, rankBadge, richText, stackedBar, statTile, timelineStep, uiBox, uiText,
} from "./line-theme";
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

/** "中文名稱 (English name)" -> [Chinese, English]; names without that shape stay whole. */
function splitName(name: string): [string, string | null] {
  const match = /^(.*?[一-鿿].*?)\s*[（(]([A-Za-z][^（）()]*)[）)]\s*$/.exec(name);
  return match ? [match[1]!.trim(), match[2]!.trim()] : [name, null];
}

type Rich = typeof richText;
const plain: Rich = (text, size = "xs", color = T.ink, extra = {}) => uiText(text, size, color, extra);
const byteSize = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length;
/** Highlighted figures when the bubble stays well under LINE's 30 KB cap; otherwise the same content without spans. */
function fitted<B>(build: (rt: Rich) => B): B {
  const rich = build(richText);
  return byteSize(rich) <= 24_000 ? rich : build(plain);
}

/** Small grey tag in front of a line (需求 / 瓶頸 / 定價). */
const tagged = (tag: string, text: string, rt: Rich = richText) => uiBox([
  uiBox([uiText(tag, "xxs", T.ink, { weight: "bold", align: "center" })], {
    backgroundColor: T.slateTint, cornerRadius: "sm", paddingTop: "xs", paddingBottom: "xs", width: "40px", flex: 0,
  }),
  rt(text, "xs", T.ink, { flex: 1 }),
], { layout: "horizontal", spacing: "sm" });

const SCORE_PARTS = [{ label: "需求能見度", weight: 25 }, { label: "瓶頸緊繃度", weight: 25 }, { label: "定價權", weight: 20 },
  { label: "價值鏈捕獲", weight: 15 }, { label: "催化劑清晰度", weight: 15 }] as const;

export function buildMacroOverviewBubble(overview: MacroTop5Overview) {
  const isShortfall = overview.status === "SHORTFALL_NOT_QUALIFIED" || overview.qualified_count < 5;
  const statusBadge = isShortfall
    ? `【未達准入門檻 · 短缺通報】合格產業僅 ${overview.qualified_count}/5`
    : `【正式准入 TOP5】基準日：${overview.generated_at}`;

  const rows = overview.industries.map(ind => {
    const [zh, en] = splitName(ind.industry_name);
    return uiBox([
      rankBadge(ind.rank !== null ? ind.rank : "—", ind.rank === 1),
      uiBox([
        uiText(zh, "sm", T.ink, { weight: "bold" }),
        ...(en ? [uiText(en, "xxs", T.subtle)] : []),
        uiBox([meter(ind.opportunity_score, 100, T.ink, true), uiText(`${ind.opportunity_score}`, "xs", T.ink, { weight: "bold", flex: 0 })],
          { layout: "horizontal", spacing: "sm", alignItems: "center" }),
      ], { flex: 1, spacing: "xs" }),
    ], { layout: "horizontal", spacing: "md" });
  });

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
    body: uiBox([
      uiBox([
        uiBox([chip(isShortfall ? `短缺 ${overview.qualified_count}/5` : "正式准入 TOP5", isShortfall ? T.negative : T.ink, T.onInk)],
          { layout: "horizontal" }),
        uiText(
          isShortfall
            ? `短缺通報：符合高標準市場成長率、瓶頸與價值鏈證據之合格產業候選僅 ${overview.qualified_count} 個（未達 5 個門檻）。系統拒絕假裝湊滿 5 個或捏造虛假排名。`
            : "本總覽由候選產業池依量化機會準則動態評選產生，非固定前五大產業清單，絕不以候選公司家數占比冒充市場成長率。",
          "xxs", isShortfall ? T.negative : T.muted,
        ),
      ], { backgroundColor: isShortfall ? T.paleNegative : T.soft, paddingAll: "md", cornerRadius: "md", spacing: "sm" }),
      railTitle("評選名單", "條長＝機會分數（0–100）"),
      ...(rows.length > 0 ? rows : [uiText("（當前無合格准入產業）", "xs", T.muted)]),
      divider(),
      railTitle("機會分數構成（System Operationalization）"),
      stackedBar(SCORE_PARTS),
      footnote("工程化排序指標，非投資成功機率。"),
    ], { paddingAll: "lg", spacing: "lg", backgroundColor: T.paper }),
    footer: menuBox([
      ...actionButtons,
      menuAction("宏觀數據要求", "宏觀資料說明"),
      menuAction("回功能選單", "選單"),
    ].slice(0, 4), { ...footerStyle }),
  };
}

export function buildMacroIndustryCardBubble(card: MacroIndustryCard) {
  return fitted(rt => industryCardBubble(card, rt));
}

function industryCardBubble(card: MacroIndustryCard, rt: Rich) {
  const growthText = formatGrowthRate(card.growth);
  const confidenceBadge = `資料完整度 ${card.confidence.data_completeness}%｜來源獨立性 ${card.confidence.source_independence}%｜核驗：${card.confidence.verification_status}`;
  const rankLabel = card.rank !== null ? `第 ${card.rank} 名` : "未排定（未准入）";
  const [zh, en] = splitName(card.industry_name);
  const growthValue = card.growth
    ? `${card.growth.rate_pct > 0 ? "+" : ""}${card.growth.rate_pct.toFixed(1)}${card.growth.units.trim().startsWith("%") ? "%" : ""}`
    : "未取得";

  return {
    type: "bubble",
    size: "mega",
    header: menuBox([
      uiBox([chip(rankLabel), uiText("宏觀產業", "xxs", T.headerMuted, { weight: "bold", gravity: "center", flex: 1 })],
        { layout: "horizontal", spacing: "md" }),
      { ...menuText(zh, "xl", T.headerText), weight: "bold" },
      ...(en ? [menuText(en, "xxs", T.headerSubtle)] : []),
      menuText(`機會分數：${card.opportunity_score}/100（量化評分，非機率）`, "xs", T.headerSubtle),
    ], { ...headerStyle }),
    body: uiBox([
      uiBox([
        statTile("市場成長率", growthValue, undefined, card.growth?.period),
        statTile("資料完整度", `${card.confidence.data_completeness}%`, card.confidence.data_completeness),
        statTile("來源獨立性", `${card.confidence.source_independence}%`, card.confidence.source_independence),
      ], { layout: "horizontal", spacing: "sm" }),
      uiBox([railTitle("當前狀態與 12–36M 展望"), rt(`現況：${card.current_state}`), rt(`展望：${card.outlook_12_36m}`)]),
      uiBox([railTitle("可查證市場成長率（RATE）"), uiText(growthText, "xxs", card.growth ? T.muted : T.negative)]),
      divider(),
      uiBox([railTitle("需求驅動與供給瓶頸（Chokepoint）"),
        tagged("需求", card.demand_drivers.join("；"), rt), tagged("瓶頸", card.supply_constraint_chokepoint, rt), tagged("定價", card.pricing, rt)]),
      uiBox([railTitle("價值鏈位置與主要受益者"), tagged("位置", card.value_chain_position, rt),
        tagged("受益", card.beneficiaries_key_suppliers.join("、"), rt)]),
      uiBox([railTitle("催化劑時程（6M / 1Y / 2Y）"),
        uiBox([
          timelineStep("6M", [rt(card.catalysts.m6, "xxs")], false, true),
          timelineStep("1Y", [rt(card.catalysts.y1, "xxs")]),
          timelineStep("2Y", [rt(card.catalysts.y2, "xxs")], true),
        ], { spacing: "none", paddingTop: "sm" })]),
      panel([uiText("生命週期與風險", "xxs", T.caution, { weight: "bold" }), rt(card.risks_lifecycle, "xs", T.muted)], "caution"),
    ], { paddingAll: "lg", spacing: "lg", backgroundColor: T.paper }),
    footer: menuBox([
      menuText(confidenceBadge, "xxs", T.muted),
      menuAction("深度化分析（10維因果）", `宏觀產業 深度化分析 ${card.industry_id}`),
      menuAction("回 TOP5 產業總覽", "TOP5產業總覽"),
      menuAction("回功能選單", "選單"),
    ], { ...footerStyle }),
  };
}

const DEEP_STEPS = [
  ["需求傳導", "Demand"], ["供給現況", "Supply"], ["核心瓶頸", "Bottleneck"], ["定價機制", "Pricing"], ["資本支出", "Capex"],
  ["競爭格局", "Competition"], ["核心受益廠商", "Beneficiaries"], ["催化時程", "Catalysts"], ["主要產業風險", "Risks"],
] as const;

export function buildMacroDeepAnalysisBubble(analysis: MacroDeepAnalysis) {
  return fitted(rt => deepAnalysisBubble(analysis, rt));
}

function deepAnalysisBubble(analysis: MacroDeepAnalysis, rt: Rich) {
  const sourcesText = analysis.source_references
    .map(s => `• ${s.source}：${s.url}${s.passage ? `（${s.passage}）` : ""}`)
    .join("\n");
  const bodies: unknown[][] = [
    [rt(analysis.demand)], [rt(analysis.supply)], [rt(analysis.bottleneck)], [rt(analysis.pricing)],
    [rt(analysis.capex)], [rt(analysis.competition)], [rt(analysis.beneficiaries.join("、"))],
    [tagged("6M", analysis.catalysts.m6, rt), tagged("1Y", analysis.catalysts.y1, rt), tagged("2Y", analysis.catalysts.y2, rt)],
    analysis.risks.map(r => rt(`• ${r}`, "xs", T.muted)),
  ];
  const [zh, en] = splitName(analysis.industry_name);

  return {
    type: "bubble",
    size: "mega",
    header: menuBox([
      menuText("宏觀產業 · 深度化分析（10維因果鏈展開）", "xs", T.headerMuted),
      { ...menuText(zh, "xl", T.headerText), weight: "bold" },
      ...(en ? [menuText(en, "xxs", T.headerSubtle)] : []),
      menuText("需求→供給→瓶頸→定價→資本支出→競爭→受益者→催化劑→風險→證偽", "xxs", T.headerMuted),
    ], { ...headerStyle }),
    body: uiBox([
      ...DEEP_STEPS.map(([title, english], index) => timelineStep(String(index + 1), [
        uiBox([uiText(title, "sm", T.ink, { weight: "bold", flex: 0 }), uiText(english, "xxs", T.subtle, { gravity: "center" })],
          { layout: "horizontal", spacing: "sm" }),
        ...bodies[index]!,
      ], false, index === 2)),
      timelineStep("10", [
        uiText("邏輯證偽點 (Thesis Killers)", "sm", T.negative, { weight: "bold" }),
        uiBox(analysis.killers.map(k => rt(`⚠️ ${k}`, "xs", T.negative)), {
          backgroundColor: T.paleNegative, paddingAll: "md", cornerRadius: "md", spacing: "sm" }),
      ], true),
    ], { paddingAll: "lg", spacing: "none", backgroundColor: T.paper }),
    footer: menuBox([
      menuText("【來源憑證依據】\n" + (sourcesText || "無外部引用"), "xxs", T.muted),
      menuAction("查看該產業卡片", `宏觀產業 卡片 ${analysis.industry_id}`),
      menuAction("回 TOP5 產業總覽", "TOP5產業總覽"),
      menuAction("回功能選單", "選單"),
    ], { ...footerStyle }),
  };
}

export function buildMacroTop5OverviewFlex(overview: MacroTop5Overview): LineOutboundMessage[] {
  const validated = validateMacroTop5Overview(overview);
  const overviewBubble = buildMacroOverviewBubble(validated);
  // Carousel handles up to 5 bubbles per container per assertLineMessages
  // When >5 candidates, select top 5 ranked cards for primary display without losing overview disclosures
  const selectedCards = validated.industries.slice(0, 5);
  const cardBubbles = selectedCards.map(card => buildMacroIndustryCardBubble(card));

  // At most five bubbles and 46 KB per carousel; the overview always opens the first one.
  const messages = packCarousels([overviewBubble, ...cardBubbles], (index) => index === 0
    ? `TOP5產業總覽（合格候選：${validated.qualified_count}家）` : "TOP5產業總覽 · 接續卡片");
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
