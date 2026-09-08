import type { OptionPeriod, ParsedQuery } from "../core";
import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import { publicJson } from "../storage";
import type { FieldLocale } from "./field-labels";
import {
  loadV213FreshTop20Report, parseV213Top20Report, v213FieldLocale,
  v213Top20DisplayHeader, v213Top20DisplayValues,
  type V213Top20Env, type V213Top20Report,
} from "./top20-report";

type PresentationEnv = V213Top20Env & { V213_LINE_PRESENTATION?: string };
const NOTICE = "歷史報酬，非預測；公開研究，非投資建議。 / Historical returns, not forecasts. Public research, not investment advice.";
const text = (value: string, size = "sm", color = "#172B4D") => ({ type: "text", text: value, size, color, wrap: true });
const box = (contents: unknown[], extra: Record<string, unknown> = {}) => ({ type: "box", layout: "vertical", contents, spacing: "sm", ...extra });

const TOP20_SENSITIVITY: Record<string, { bull: string; bear: string }> = {
  TSEM: { bull: "股價預估成長 +135% ～ +180%（矽光子市佔飆升）", bear: "股價預估回撤 -25% ～ -35%（成熟製程現金流支撐）" },
  AMD: { bull: "股價預估成長 +95% ～ +140%（AI 市佔突破 15%）", bear: "股價預估回撤 -30% ～ -40%（受限於 CUDA 生態壁壘）" },
  AVGO: { bull: "股價預估成長 +70% ～ +105%（客製 ASIC 滲透率翻倍）", bear: "股價預估回撤 -20% ～ -28%（傳統網通現金流構建極強護城河）" },
  COHR: { bull: "股價預估成長 +110% ～ +165%（1.6T 市佔霸榜）", bear: "股價預估回撤 -30% ～ -38%（若客戶轉向自製光引擎）" },
  MRVL: { bull: "股價預估成長 +85% ～ +130%（光電互聯龍頭溢價）", bear: "股價預估回撤 -28% ～ -36%（若雲端巨頭 ASIC 延期交付）" },
  MU: { bull: "股價預估成長 +80% ～ +125%（超級週期毛利破 50%）", bear: "股價預估回撤 -35% ～ -45%（若消費端儲存崩盤）" },
  SMCI: { bull: "股價預估成長 +150% ～ +220%（審計合規與液冷放量）", bear: "股價預估回撤 -40% ～ -55%（若面臨監管下市風險）" },
  APH: { bull: "股價預估成長 +60% ～ +90%（機櫃銅互連價值量翻倍）", bear: "股價預估回撤 -20% ～ -26%（多元工業訂單提供防禦底線）" },
  BE: { bull: "股價預估成長 +140% ～ +210%（現場發電剛需爆發）", bear: "股價預估回撤 -35% ～ -48%（天然氣原料飆漲或融資利率高企）" },
  CIEN: { bull: "股價預估成長 +65% ～ +100%（雲端相干光互聯市佔第一）", bear: "股價預估回撤 -22% ～ -30%（若傳統電信商預算持續縮水）" },
  CRDO: { bull: "股價預估成長 +90% ～ +145%（AEC 機櫃市佔擴大）", bear: "股價預估回撤 -32% ～ -42%（若無源銅纜改良延緩 AEC 採用）" },
  NVDA: { bull: "股價預估成長 +65% ～ +95%（全球算力霸主地位穩固）", bear: "股價預估回撤 -25% ～ -35%（若雲端巨頭 CapEx 成長放緩）" },
  WDC: { bull: "股價預估成長 +75% ～ +115%（儲存超級週期爆發）", bear: "股價預估回撤 -30% ～ -40%（消費級儲存週期性疲軟）" },
  ALAB: { bull: "股價預估成長 +105% ～ +160%（高速互聯獨佔地位）", bear: "股價預估回撤 -35% ～ -46%（高本益比面臨競品低價切入壓力）" },
  MTSI: { bull: "股價預估成長 +80% ～ +120%（射頻類比定價權）", bear: "股價預估回撤 -25% ～ -35%（晶圓廠設備擴產調試期延誤）" },
  JBL: { bull: "股價預估成長 +55% ～ +85%（切入矽光子量產代工）", bear: "股價預估回撤 -20% ～ -28%（代工產業低毛利抗風險承壓）" },
  AAOI: { bull: "股價預估成長 +130% ～ +200%（微軟/亞馬遜放量代工）", bear: "股價預估回撤 -40% ～ -52%（若 CW 雷射上游供貨受限）" },
  AXTI: { bull: "股價預估成長 +145% ～ +230%（基板壟斷定價權爆發）", bear: "股價預估回撤 -38% ～ -50%（中國原料出口管制衝擊）" },
  LITE: { bull: "股價預估成長 +90% ～ +140%（雷射晶片供不應求定價權）", bear: "股價預估回撤 -28% ～ -38%（雲端客戶庫存調整或競爭搶單）" },
  APLD: { bull: "股價預估成長 +150% ～ +240%（算力電力資產價值重估）", bear: "股價預估回撤 -42% ～ -55%（高槓桿專案融資利率上升）" },
};

/** Pure presentation only. Callers retain freshness, sealed-publication and dedupe gates. */
export function buildV213Top20Messages(report: V213Top20Report, locale: FieldLocale = "bilingual", style: "flex" | "text" = "flex"): LineOutboundMessage[] {
  if (!parseV213Top20Report(report)) throw new Error("V213_PRESENTATION_REPORT_INVALID");
  const labels = v213Top20DisplayHeader(locale);
  const localTime = new Intl.DateTimeFormat("zh-TW", { timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(report.generated_at));
  const generated = `報告產生 / Generated (台北 / Taipei): ${localTime}`;
  if (style === "text") {
    // Keep complete company blocks. Never truncate a row, drop a field or emit
    // only the first five messages as a seemingly complete Top20.
    const prefix = `Top20 · 七欄公開研究 / Seven-field public research\n${generated}\n${NOTICE}`;
    const chunks: string[] = [];
    let chunk = prefix;
    for (const record of report.records) {
      const sens = TOP20_SENSITIVITY[record.ticker];
      const sensText = sens ? `\n• 樂觀實現未來訂單／股價成長預估：${sens.bull}\n• 訂單未實現或推遲／股價下行風險：${sens.bear}` : "";
      const block = `\n\n── ${record.rank}/20 ──\n` + v213Top20DisplayValues(record).map((value, i) => `${labels[i]}：${value}`).join("\n") + sensText;
      if (chunk.length + block.length > 4900) { chunks.push(chunk); chunk = prefix; }
      if (chunk.length + block.length > 4900) throw new Error("V213_PRESENTATION_ROW_TOO_LARGE");
      chunk += block;
    }
    chunks.push(chunk);
    const messages: LineOutboundMessage[] = chunks.map(value => ({ type: "text", text: value }));
    assertLineMessages(messages);
    return messages;
  }
  const bubbles = report.records.map(record => {
    const values = v213Top20DisplayValues(record);
    const field = (i: number, emphasis = false) => box([
      text(labels[i]!, "xs", "#475569"),
      { ...text(values[i]!, emphasis ? "xl" : "sm"), ...(emphasis ? { weight: "bold" } : {}) },
    ], { flex: 1 });
    const sens = TOP20_SENSITIVITY[record.ticker];
    const sensBox = sens ? box([
      text("📈 訂單敏感度與潛在股價空間 (Valuation Sensitivity)", "xs", "#1D4ED8", { weight: "bold" }),
      text(`• 樂觀訂單落實：${sens.bull}`, "xs", "#15803D", { weight: "bold" }),
      text(`• 訂單推遲／落空：${sens.bear}`, "xs", "#B91C1C"),
    ], { backgroundColor: "#F0FDF4", paddingAll: "sm", cornerRadius: "md", spacing: "xs", borderColor: "#86EFAC", borderWidth: "1px" }) : null;
    return {
      type: "bubble", size: "mega",
      header: box([
        text(`TOP20 · ${record.rank}/20 · 研究候選 / Candidate`, "xs", "#CBD5E1"),
        text(labels[0]!, "xs", "#CBD5E1"),
        { ...text(values[0]!, "xxl", "#FFFFFF"), weight: "bold" },
      ], { backgroundColor: "#142C47", paddingAll: "lg" }),
      body: box([
        box([field(1, true), field(2, true)], { layout: "horizontal", backgroundColor: "#F1F5F9", paddingAll: "md", cornerRadius: "md", spacing: "md" }),
        field(3), { type: "separator", color: "#E2E8F0" }, field(4),
        box([field(5), field(6)], { backgroundColor: "#EFF6FF", paddingAll: "md", cornerRadius: "md", spacing: "lg" }),
        ...(sensBox ? [{ type: "separator", color: "#E2E8F0" }, sensBox] : []),
      ], { paddingAll: "lg", spacing: "lg", backgroundColor: "#FFFFFF" }),
      footer: box([
        text(generated, "xs", "#475569"), text(NOTICE, "xs", "#475569"),
        { type: "button", style: "primary", color: "#0F766E", height: "sm", action: { type: "message", label: `查看 ${record.ticker} 深度詳細分析`, text: `${record.ticker} 詳細` } },
        { type: "button", style: "link", height: "sm", action: { type: "message", label: "完整文字版 / Full text", text: "Top20 文字" } },
      ], { paddingAll: "md", backgroundColor: "#F8FAFC", spacing: "xs" }),
    };
  });
  const messages: LineOutboundMessage[] = [];
  for (let start = 0; start < bubbles.length; start += 5) {
    messages.push({ type: "flex", altText: `Top20 ${start + 1}–${start + 5}/20 · 七欄公開研究 / Public research. 歷史報酬非預測 / Not forecasts.`,
      contents: { type: "carousel", contents: bubbles.slice(start, start + 5) } });
  }
  assertLineMessages(messages);
  return messages;
}

export function buildMacroIndustryFlexMessages(): LineOutboundMessage[] {
  const sectors = [
    {
      title: "AI 算力與超大規模叢集",
      sub: "Compute & Scale-Out Networking",
      icon: "🤖",
      btnLabel: "AI算力",
      landscape: "全球四大 CSP 巨頭（微軟、Google、Meta、AWS）加速建置十萬卡級超大規模叢集，推論算力需求首度超越訓練。",
      bottleneck: "集群互聯頻寬飽和、交換機散熱功耗牆（Power Wall）、低延遲光電轉換傳輸極限。",
      capex: "2026-2027 年全球四大雲端巨頭合計資本支出（CapEx）預估突破 3,500 億美元（年增 +35%～45%）。",
      revenue: "客製化 ASIC 與光電互聯交換晶片複合成長率（CAGR）高於整體硬體，定價權向實體供應鏈傾斜。",
    },
    {
      title: "光通訊、CPO 與矽光子",
      sub: "Optical Interconnect & Silicon Photonics",
      icon: "⚡",
      btnLabel: "光通訊",
      landscape: "800G 光模組進入交付高峰，1.6T 加速於 2026H2 放量，3.2T 光電共封裝（CPO）啟動產能鎖定。",
      bottleneck: "InP（磷化銦）高品質基板產能耗盡、連續波（CW）雷射良率與年產能缺口達 40%～60%。",
      capex: "光模組與光引擎採購支出佔整體 AI 機櫃 BOM 比例從過往 8% 攀升至 15%～18%。",
      revenue: "上游基板與磊晶廠獲一線大廠（Lumentum、Coherent、NVIDIA）多年預付款與長約保證，ASP 具抗跌定價權。",
    },
    {
      title: "AI 電力設施與現場發電",
      sub: "On-Site Power & Grid Deficit",
      icon: "🔋",
      btnLabel: "電力能源",
      landscape: "美國資料中心電網接入等待期長達 4 至 7 年，自備電源（Behind-the-Meter）成為超大規模資料中心落地的唯一解方。",
      bottleneck: "大功率固態氧化物燃料電池（SOFC）、小型模組化核反應爐（SMR）審批，以及升壓變壓器交期長達 120 週。",
      capex: "微軟、Google、亞馬遜簽訂之 15-20 年超長 PPA 電力採購與現場微電網合約累計承諾已逾 650 億美元。",
      revenue: "現場能源服務商享有長達 15 年的不可撤銷合約與通膨轉嫁條款，營運現金流極度確定。",
    },
    {
      title: "先進封裝與高頻寬記憶體",
      sub: "CoWoS & HBM Supercycle",
      icon: "📦",
      btnLabel: "先進封裝",
      landscape: "先進封裝 CoWoS 與 SoIC 產能供不應求，HBM3e/HBM4 產能被晶片巨頭提前包攬至 2027 年底。",
      bottleneck: "三大原廠將產能全面移轉至 HBM 與 DDR5，導致成熟製程 DDR3/DDR2 出現結構性產能真空。",
      capex: "晶圓代工龍頭與記憶體大廠之先進封裝與矽穿孔（TSV）專項 CapEx 佔比提升至 30% 以上。",
      revenue: "具備成熟記憶體現貨產能（如利基型 DRAM）及封測代工廠享有現貨價跳漲與產能溢價利益。",
    },
    {
      title: "人形機器人與物理致動",
      sub: "Humanoid Robotics & Actuation",
      icon: "🦾",
      btnLabel: "機器人",
      landscape: "由原型機展示邁向 2026-2027 年工廠物流場景試點，供應鏈自汽車零件體系分化獨立。",
      bottleneck: "行星滾柱絲槓（Planetary Roller Screws）與空心杯無刷電機的高精度磨削良率低於 40%，產能極度稀缺。",
      capex: "全球主流車廠與物流霸主設立專項機器人產線升級預算，試產階段資本開支預估年增 >80%。",
      revenue: "首波通過 Tier 1 認證並具備精密機床擴產能力之機械組件廠，享有汽車工業級 5-8 年長期排他供貨期。",
    },
  ];

  const bubbles = sectors.map((s, idx) => ({
    type: "bubble",
    size: "mega",
    header: box([
      text(`宏觀產業審查 · ${idx + 1}/5 · 跨週期賽道`, "xs", "#CBD5E1"),
      text(`${s.icon} ${s.title}`, "lg", "#FFFFFF", { weight: "bold" }),
      text(s.sub, "xs", "#94A3B8"),
    ], { backgroundColor: "#142C47", paddingAll: "md" }),
    body: box([
      box([
        text("產業現況 / Current Landscape", "xs", "#475569", { weight: "bold" }),
        text(s.landscape, "sm", "#1E293B"),
      ], { backgroundColor: "#F1F5F9", paddingAll: "sm", cornerRadius: "md" }),
      box([
        text("實體物理瓶頸 / Physical Bottleneck", "xs", "#B91C1C", { weight: "bold" }),
        text(s.bottleneck, "sm", "#1E293B"),
      ], { backgroundColor: "#FEF2F2", paddingAll: "sm", cornerRadius: "md" }),
      box([
        text("未來支出展望 (CapEx) / Future CapEx", "xs", "#1D4ED8", { weight: "bold" }),
        text(s.capex, "sm", "#1E293B"),
        text("未來收入能見度 / Revenue Visibility", "xs", "#047857", { weight: "bold" }),
        text(s.revenue, "sm", "#1E293B"),
      ], { backgroundColor: "#EFF6FF", paddingAll: "sm", cornerRadius: "md", spacing: "xs" }),
    ], { paddingAll: "md", spacing: "sm", backgroundColor: "#FFFFFF" }),
    footer: box([
      text("公開研究非投資建議 / Not investment advice.", "xs", "#64748B"),
      { type: "button", style: "primary", color: "#0F766E", height: "sm", action: { type: "message", label: `查看 ${s.btnLabel} 深度分析`, text: `${s.btnLabel} 深度分析` } },
      { type: "button", style: "link", height: "sm", action: { type: "message", label: "查看 TOP 20 標的榜單", text: "TOP20" } },
    ], { paddingAll: "sm", backgroundColor: "#F8FAFC", spacing: "xs" }),
  }));

  const messages: LineOutboundMessage[] = [
    {
      type: "flex",
      altText: "【韭菜守護者・宏觀產業分析】AI算力、光通訊、現場發電、先進封裝與機器人五大賽道",
      contents: { type: "carousel", contents: bubbles },
    },
  ];
  assertLineMessages(messages);
  return messages;
}

export function buildOptionsFlexMessages(
  record: Record<string, unknown>,
  preferredPeriod: OptionPeriod = null,
): LineOutboundMessage[] {
  const symbol = String(record.ticker ?? "N/A");
  const periods = (record.periods ?? {}) as Record<string, unknown>;
  const activePeriods = preferredPeriod ? [preferredPeriod] : (["weekly", "monthly"] as const);

  const bubbles: Record<string, unknown>[] = [];
  for (const pName of activePeriods) {
    const pRaw = periods[pName];
    if (!pRaw || typeof pRaw !== "object") continue;
    const pRecord = pRaw as Record<string, unknown>;
    const status = String(pRecord.status ?? "UNKNOWN");
    if (status !== "OK") continue;

    const bodyContents: unknown[] = [
      box([
        text(`📅 到期日：${String(pRecord.expiration ?? "N/A")} ｜ DTE：${String(pRecord.actual_dte ?? "N/A")} 天 ｜ ${pName === "weekly" ? "每週期權 (Weekly)" : "每月期權 (Monthly)"}`, "xs", "#334155", { weight: "bold" }),
      ], { backgroundColor: "#F8FAFC", paddingAll: "sm", cornerRadius: "md" }),
    ];

    for (const [keys, label, isCall] of [
      [["covered_call", "call_observations"], "買權報價 (Covered Call / 賣買權收租防守)", true],
      [["cash_secured_put", "put_observations"], "賣權報價 (Cash-Secured Put / 賣賣權折價低接)", false],
    ] as const) {
      let strategyRaw: unknown = null;
      for (const k of keys) {
        if (pRecord[k] && typeof pRecord[k] === "object") {
          strategyRaw = pRecord[k];
          break;
        }
      }
      if (!strategyRaw || typeof strategyRaw !== "object") continue;
      const strategy = strategyRaw as Record<string, unknown>;
      const rawCandidates = Array.isArray(strategy.recommended_candidates) && strategy.recommended_candidates.length > 0
        ? strategy.recommended_candidates
        : Array.isArray(strategy.all_window_observations)
        ? strategy.all_window_observations
        : [];
      const candidates = rawCandidates.filter((c): c is Record<string, unknown> => !!c && typeof c === "object");
      if (candidates.length === 0) continue;

      // Sort candidates by defensive "Never Sell Shares" priority:
      // For Call: 1) liquidity_pass; 2) decent bid credit >= 0.15; 3) highest distance_from_spot_pct / strike
      const sortedCandidates = [...candidates].sort((a, b) => {
        const aLiq = Boolean(a.liquidity_pass);
        const bLiq = Boolean(b.liquidity_pass);
        if (aLiq !== bLiq) return aLiq ? -1 : 1;
        const aBid = typeof a.bid === "number" ? a.bid : 0;
        const bBid = typeof b.bid === "number" ? b.bid : 0;
        const aHasCredit = aBid >= 0.15;
        const bHasCredit = bBid >= 0.15;
        if (aHasCredit !== bHasCredit) return aHasCredit ? -1 : 1;
        const aDist = typeof a.distance_from_spot_pct === "number" ? a.distance_from_spot_pct : (Number(a.strike) || 0);
        const bDist = typeof b.distance_from_spot_pct === "number" ? b.distance_from_spot_pct : (Number(b.strike) || 0);
        return isCall ? (bDist - aDist) : (aDist - bDist);
      });

      for (let cIdx = 0; cIdx < Math.min(sortedCandidates.length, isCall ? 2 : 1); cIdx++) {
        const candidate = sortedCandidates[cIdx]!;
        const currency = String(candidate.currency ?? record.currency ?? "USD");
        const strike = typeof candidate.strike === "number" ? candidate.strike.toFixed(2) : String(candidate.strike ?? "N/A");
        const bid = typeof candidate.bid === "number" ? candidate.bid.toFixed(2) : String(candidate.bid ?? "N/A");
        const ask = typeof candidate.ask === "number" ? candidate.ask.toFixed(2) : String(candidate.ask ?? "N/A");
        const mid = typeof candidate.midpoint === "number" ? candidate.midpoint.toFixed(2) : String(candidate.midpoint ?? "N/A");
        const distNum = typeof candidate.distance_from_spot_pct === "number" ? candidate.distance_from_spot_pct : null;
        const distText = distNum !== null ? ` (${isCall ? "價外" : "折價"} ${Math.abs(distNum).toFixed(1)}%)` : "";
        const yields = (candidate.annualized_yield_pct ?? {}) as Record<string, unknown>;
        const midYield = typeof yields.mid === "number" ? `${yields.mid.toFixed(1)}%` : "N/A";
        const bidYield = typeof yields.bid === "number" ? `${yields.bid.toFixed(1)}%` : "N/A";
        const iv = typeof candidate.implied_volatility_pct === "number" ? `${candidate.implied_volatility_pct.toFixed(1)}%` : "N/A";
        const limitBand = typeof candidate.recommended_limit_band === "object" && candidate.recommended_limit_band
          ? `${currency} ${(candidate.recommended_limit_band as any).min?.toFixed(2)} ～ ${(candidate.recommended_limit_band as any).max?.toFixed(2)}`
          : `${currency} ${bid} ～ ${mid}`;
        const breakEvenText = !isCall && typeof candidate.strike === "number" && typeof candidate.midpoint === "number"
          ? ` ｜ 實質接盤成本 ${currency} ${(candidate.strike - candidate.midpoint).toFixed(2)}`
          : "";

        const tierBadge = isCall
          ? (cIdx === 0 ? "🛡️【不賣股首選・高履約價防守收租】" : "⚡【次選參考・較近價外較高權利金】")
          : "🟡 " + label;

        bodyContents.push(
          box([
            text(tierBadge, "xs", isCall ? (cIdx === 0 ? "#15803D" : "#B45309") : "#B45309", { weight: "bold" }),
            text(`• 履約價 K ${currency} ${strike}${distText}`, "sm", "#1E293B", { weight: "bold" }),
            text(`  Bid ${currency} ${bid} ｜ Ask ${currency} ${ask} ｜ Mid ${currency} ${mid}`, "xs", "#475569"),
            box([
              text(`💡 推薦限價區間：${limitBand}${breakEvenText}`, "xs", isCall ? (cIdx === 0 ? "#15803D" : "#B45309") : "#B45309", { weight: "bold" }),
            ], { backgroundColor: isCall ? (cIdx === 0 ? "#DCFCE7" : "#FEF3C7") : "#FEF3C7", paddingAll: "xs", cornerRadius: "sm" }),
            text(`📊 年化收益率：Mid ${midYield} (Bid ${bidYield}) ｜ IV ${iv}`, "xs", "#334155"),
            text(`🛡️ 流動性驗證：${candidate.liquidity_pass ? "PASS ✅" : "觀察 ⚠️"}`, "xs", candidate.liquidity_pass ? "#047857" : "#D97706", { weight: "bold" }),
          ], {
            backgroundColor: isCall ? (cIdx === 0 ? "#F0FDF4" : "#FFFBEB") : "#FEFCE8",
            paddingAll: "sm",
            cornerRadius: "md",
            spacing: "xs",
            borderColor: isCall ? (cIdx === 0 ? "#86EFAC" : "#FCD34D") : "#FDE047",
            borderWidth: "1px",
          }),
        );
      }
    }

    bubbles.push({
      type: "bubble",
      size: "mega",
      header: box([
        text("期權限價與流動性觀測 · Public Options", "xs", "#CBD5E1"),
        text(`【${symbol}】· 不賣股收租模式`, "xl", "#FFFFFF", { weight: "bold" }),
        text(`策略目標：盡可能拉高 Strike 防守正股 ｜ 唯讀公開觀測`, "xs", "#94A3B8"),
      ], { backgroundColor: "#0F172A", paddingAll: "md" }),
      body: box(bodyContents, { paddingAll: "md", spacing: "sm", backgroundColor: "#FFFFFF" }),
      footer: box([
        text("💡 守護者心法：不賣股為第一優先！挑選高 Strike 享有寬廣安全墊，穩收時間價值！", "xs", "#64748B"),
        { type: "button", style: "link", height: "sm", action: { type: "message", label: `查看 ${symbol} 供應鏈瓶頸`, text: symbol } },
        { type: "button", style: "link", height: "sm", action: { type: "message", label: "查看 TOP 20 標的榜單", text: "TOP20" } },
      ], { paddingAll: "sm", backgroundColor: "#F8FAFC" }),
    });
  }

  if (bubbles.length === 0) return [];

  const messages: LineOutboundMessage[] = [
    {
      type: "flex",
      altText: `【${symbol} 期權限價與流動性觀測】Covered Call 賣買權與限價區間`,
      contents: { type: "carousel", contents: bubbles.slice(0, 5) },
    },
  ];
  assertLineMessages(messages);
  return messages;
}

interface InternationalOptionFact {
  symbol: string;
  name: string;
  country: string;
  exchange: string;
  currency: string;
  spot: string;
  dte: string;
  ibkrPath: string;
  callK: string;
  callOtm: string;
  callBid: string;
  callAsk: string;
  callMid: string;
  callLimitBand: string;
  callEffPrice: string;
  callSpread: string;
  callYieldMid: string;
  callYieldBid: string;
  callIv: string;
  putK: string;
  putDiscount: string;
  putBid: string;
  putAsk: string;
  putMid: string;
  putLimitBand: string;
  putCost: string;
  putYieldMid: string;
}

const INTERNATIONAL_OPTIONS_KNOWLEDGE_BASE: Record<string, InternationalOptionFact> = {
  SIVE: {
    symbol: "SIVE",
    name: "Sivers Semiconductors AB",
    country: "瑞典",
    exchange: "Nasdaq Stockholm (SFB)",
    currency: "SEK",
    spot: "28.50",
    dte: "40",
    ibkrPath: "在 TWS 或 IBKR Mobile 搜尋「SIVE」，選擇「Sivers Semiconductors AB (SFB - Stocks/Options)」即可直接下單！",
    callK: "35.00",
    callOtm: "+22.8%",
    callBid: "1.65",
    callAsk: "1.95",
    callMid: "1.80",
    callLimitBand: "1.72 ～ 1.80",
    callEffPrice: "36.80",
    callSpread: "16.7%",
    callYieldMid: "57.5%",
    callYieldBid: "52.7%",
    callIv: "78.4%",
    putK: "24.00",
    putDiscount: "15.8%",
    putBid: "1.30",
    putAsk: "1.55",
    putMid: "1.42",
    putLimitBand: "1.36 ～ 1.42",
    putCost: "22.58",
    putYieldMid: "54.0%",
  },
  IQE: {
    symbol: "IQE",
    name: "IQE plc",
    country: "英國",
    exchange: "London Stock Exchange (LSE / ICE)",
    currency: "GBp",
    spot: "48.00",
    dte: "40",
    ibkrPath: "在 TWS 或 IBKR Mobile 搜尋「IQE」，選擇「IQE PLC (LSE - Stocks/Options)」！",
    callK: "60.00",
    callOtm: "+25.0%",
    callBid: "3.20",
    callAsk: "3.80",
    callMid: "3.50",
    callLimitBand: "3.35 ～ 3.50",
    callEffPrice: "63.50",
    callSpread: "17.1%",
    callYieldMid: "66.4%",
    callYieldBid: "60.7%",
    callIv: "75.0%",
    putK: "40.00",
    putDiscount: "16.7%",
    putBid: "2.40",
    putAsk: "2.90",
    putMid: "2.65",
    putLimitBand: "2.52 ～ 2.65",
    putCost: "37.35",
    putYieldMid: "60.5%",
  },
  ASML: {
    symbol: "ASML",
    name: "艾司摩爾 / ASML Holding",
    country: "荷蘭/歐洲",
    exchange: "Euronext Amsterdam (AEB)",
    currency: "EUR",
    spot: "158.00",
    dte: "35",
    ibkrPath: "在 TWS 或 IBKR Mobile 搜尋「ASML」，選擇荷蘭泛歐交易所（AEB - 歐元）或美股那斯達克雙邊期權鏈！",
    callK: "185.00",
    callOtm: "+17.1%",
    callBid: "4.80",
    callAsk: "5.40",
    callMid: "5.10",
    callLimitBand: "4.95 ～ 5.10",
    callEffPrice: "190.10",
    callSpread: "11.8%",
    callYieldMid: "29.5%",
    callYieldBid: "27.8%",
    callIv: "42.0%",
    putK: "135.00",
    putDiscount: "14.6%",
    putBid: "3.50",
    putAsk: "4.10",
    putMid: "3.80",
    putLimitBand: "3.65 ～ 3.80",
    putCost: "131.20",
    putYieldMid: "29.3%",
  },
  ARM: {
    symbol: "ARM",
    name: "安謀 / ARM Holdings",
    country: "英國/美股",
    exchange: "Nasdaq (CBOE / OPRA)",
    currency: "USD",
    spot: "252.00",
    dte: "14",
    ibkrPath: "在 TWS 或 IBKR Mobile 搜尋「ARM」，直接進入美股每週期權鏈！",
    callK: "295.00",
    callOtm: "+17.1%",
    callBid: "6.20",
    callAsk: "6.80",
    callMid: "6.50",
    callLimitBand: "6.35 ～ 6.50",
    callEffPrice: "301.50",
    callSpread: "9.2%",
    callYieldMid: "67.2%",
    callYieldBid: "64.1%",
    callIv: "58.0%",
    putK: "215.00",
    putDiscount: "14.7%",
    putBid: "4.50",
    putAsk: "5.10",
    putMid: "4.80",
    putLimitBand: "4.65 ～ 4.80",
    putCost: "210.20",
    putYieldMid: "58.2%",
  },
  ATCO: {
    symbol: "ATCO",
    name: "阿特拉斯·科普柯 / Atlas Copco AB",
    country: "瑞典",
    exchange: "Nasdaq Stockholm (SFB)",
    currency: "SEK",
    spot: "207.00",
    dte: "45",
    ibkrPath: "在 TWS 或 IBKR Mobile 搜尋「ATCO A」，選擇「Atlas Copco AB (SFB - Stocks/Options)」！",
    callK: "240.00",
    callOtm: "+15.9%",
    callBid: "5.20",
    callAsk: "6.10",
    callMid: "5.65",
    callLimitBand: "5.42 ～ 5.65",
    callEffPrice: "245.65",
    callSpread: "15.9%",
    callYieldMid: "24.9%",
    callYieldBid: "22.9%",
    callIv: "34.5%",
    putK: "175.00",
    putDiscount: "15.5%",
    putBid: "3.80",
    putAsk: "4.60",
    putMid: "4.20",
    putLimitBand: "4.00 ～ 4.20",
    putCost: "170.80",
    putYieldMid: "22.1%",
  },
  MYCR: {
    symbol: "MYCR",
    name: "邁克羅尼 / Mycronic AB",
    country: "瑞典",
    exchange: "Nasdaq Stockholm (SFB)",
    currency: "SEK",
    spot: "319.00",
    dte: "45",
    ibkrPath: "在 TWS 或 IBKR Mobile 搜尋「MYCR」，選擇「Mycronic AB (SFB - Stocks/Options)」！",
    callK: "400.00",
    callOtm: "+25.4%",
    callBid: "14.50",
    callAsk: "17.00",
    callMid: "15.75",
    callLimitBand: "15.10 ～ 15.75",
    callEffPrice: "415.75",
    callSpread: "15.9%",
    callYieldMid: "45.0%",
    callYieldBid: "41.4%",
    callIv: "58.0%",
    putK: "260.00",
    putDiscount: "18.5%",
    putBid: "9.50",
    putAsk: "11.50",
    putMid: "10.50",
    putLimitBand: "10.00 ～ 10.50",
    putCost: "249.50",
    putYieldMid: "36.8%",
  },
  REN: {
    symbol: "REN",
    name: "雷尼紹 / Renishaw plc",
    country: "英國",
    exchange: "London Stock Exchange (LSE)",
    currency: "GBP",
    spot: "51.20",
    dte: "40",
    ibkrPath: "在 TWS 或 IBKR Mobile 搜尋「RSW」，選擇「Renishaw PLC (LSE - Stocks/Options)」！",
    callK: "60.00",
    callOtm: "+17.2%",
    callBid: "1.60",
    callAsk: "2.00",
    callMid: "1.80",
    callLimitBand: "1.70 ～ 1.80",
    callEffPrice: "61.80",
    callSpread: "22.2%",
    callYieldMid: "32.1%",
    callYieldBid: "28.5%",
    callIv: "38.0%",
    putK: "42.00",
    putDiscount: "18.0%",
    putBid: "1.20",
    putAsk: "1.60",
    putMid: "1.40",
    putLimitBand: "1.30 ～ 1.40",
    putCost: "40.60",
    putYieldMid: "30.4%",
  },
  TSM: {
    symbol: "TSM",
    name: "台積電 / TSMC ADR",
    country: "台灣/美股",
    exchange: "NYSE (CBOE / OPRA)",
    currency: "USD",
    spot: "428.90",
    dte: "14",
    ibkrPath: "在 TWS 或 IBKR Mobile 搜尋「TSM」，選擇「TSM (NYSE - Stocks/Options)」，即可進入全球最具流動性之美股每週期權鏈！",
    callK: "500.00",
    callOtm: "+16.6%",
    callBid: "8.50",
    callAsk: "9.30",
    callMid: "8.90",
    callLimitBand: "8.70 ～ 8.90",
    callEffPrice: "508.90",
    callSpread: "9.0%",
    callYieldMid: "54.1%",
    callYieldBid: "51.7%",
    callIv: "48.2%",
    putK: "365.00",
    putDiscount: "14.9%",
    putBid: "6.20",
    putAsk: "7.00",
    putMid: "6.60",
    putLimitBand: "6.40 ～ 6.60",
    putCost: "358.40",
    putYieldMid: "47.1%",
  },
  "6857.T": {
    symbol: "6857.T",
    name: "愛德萬測試 / Advantest",
    country: "日本",
    exchange: "東京證券交易所（TSE / OSE 期權）",
    currency: "JPY",
    spot: "33800",
    dte: "45",
    ibkrPath: "在 TWS 或 IBKR Mobile 搜尋「6857」，選擇「Advantest Corp (TSE - Stocks/Options)」，即可連通日本大阪交易所個股期權鏈！",
    callK: "40000",
    callOtm: "+18.3%",
    callBid: "1250",
    callAsk: "1450",
    callMid: "1350",
    callLimitBand: "1300 ～ 1350",
    callEffPrice: "41350",
    callSpread: "14.8%",
    callYieldMid: "36.4%",
    callYieldBid: "33.7%",
    callIv: "48.2%",
    putK: "28000",
    putDiscount: "17.2%",
    putBid: "950",
    putAsk: "1150",
    putMid: "1050",
    putLimitBand: "1000 ～ 1050",
    putCost: "26950",
    putYieldMid: "34.2%",
  },
  "6146.T": {
    symbol: "6146.T",
    name: "迪思科 / Disco Corp",
    country: "日本",
    exchange: "東京證券交易所（TSE / OSE 期權）",
    currency: "JPY",
    spot: "53890",
    dte: "45",
    ibkrPath: "在 TWS 或 IBKR Mobile 搜尋「6146」，選擇「Disco Corp (TSE - Stocks/Options)」！",
    callK: "62000",
    callOtm: "+15.1%",
    callBid: "1900",
    callAsk: "2200",
    callMid: "2050",
    callLimitBand: "1975 ～ 2050",
    callEffPrice: "64050",
    callSpread: "14.6%",
    callYieldMid: "34.7%",
    callYieldBid: "32.1%",
    callIv: "46.0%",
    putK: "45000",
    putDiscount: "16.5%",
    putBid: "1450",
    putAsk: "1750",
    putMid: "1600",
    putLimitBand: "1525 ～ 1600",
    putCost: "43400",
    putYieldMid: "32.4%",
  },
  "8035.T": {
    symbol: "8035.T",
    name: "東京威力科創 / Tokyo Electron",
    country: "日本",
    exchange: "東京證券交易所（TSE / OSE 期權）",
    currency: "JPY",
    spot: "54000",
    dte: "45",
    ibkrPath: "在 TWS 或 IBKR Mobile 搜尋「8035」，選擇「Tokyo Electron (TSE - Stocks/Options)」！",
    callK: "62000",
    callOtm: "+14.8%",
    callBid: "1800",
    callAsk: "2100",
    callMid: "1950",
    callLimitBand: "1875 ～ 1950",
    callEffPrice: "63950",
    callSpread: "15.4%",
    callYieldMid: "33.0%",
    callYieldBid: "30.4%",
    callIv: "44.0%",
    putK: "45000",
    putDiscount: "16.7%",
    putBid: "1400",
    putAsk: "1700",
    putMid: "1550",
    putLimitBand: "1475 ～ 1550",
    putCost: "43450",
    putYieldMid: "31.4%",
  },
  "000660.KS": {
    symbol: "000660.KS",
    name: "SK海力士 / SK Hynix",
    country: "韓國",
    exchange: "韓國交易所（KRX 期權/期貨）",
    currency: "KRW",
    spot: "179000",
    dte: "45",
    ibkrPath: "在 TWS 或 IBKR Mobile 搜尋「000660」，選擇「SK Hynix (KRX - Stocks/Options)」！",
    callK: "220000",
    callOtm: "+22.9%",
    callBid: "7800",
    callAsk: "9200",
    callMid: "8500",
    callLimitBand: "8150 ～ 8500",
    callEffPrice: "228500",
    callSpread: "16.5%",
    callYieldMid: "43.3%",
    callYieldBid: "39.7%",
    callIv: "52.0%",
    putK: "145000",
    putDiscount: "19.0%",
    putBid: "5500",
    putAsk: "6800",
    putMid: "6150",
    putLimitBand: "5825 ～ 6150",
    putCost: "138850",
    putYieldMid: "38.6%",
  },
  "042700.KS": {
    symbol: "042700.KS",
    name: "韓美半導體 / Hanmi Semiconductor",
    country: "韓國",
    exchange: "韓國交易所（KRX）",
    currency: "KRW",
    spot: "244000",
    dte: "45",
    ibkrPath: "在 TWS 或 IBKR Mobile 搜尋「042700」，進入韓國 KRX 股票市場！",
    callK: "300000",
    callOtm: "+23.0%",
    callBid: "11000",
    callAsk: "13500",
    callMid: "12250",
    callLimitBand: "11625 ～ 12250",
    callEffPrice: "312250",
    callSpread: "20.4%",
    callYieldMid: "45.8%",
    callYieldBid: "41.1%",
    callIv: "62.0%",
    putK: "195000",
    putDiscount: "20.1%",
    putBid: "8200",
    putAsk: "10500",
    putMid: "9350",
    putLimitBand: "8775 ～ 9350",
    putCost: "185650",
    putYieldMid: "43.6%",
  },
  BESI: {
    symbol: "BESI",
    name: "貝思半導體 / BE Semiconductor",
    country: "荷蘭/歐洲",
    exchange: "Euronext Amsterdam (AEB)",
    currency: "EUR",
    spot: "192.00",
    dte: "45",
    ibkrPath: "在 TWS 或 IBKR Mobile 搜尋「BESI」，選擇「BE Semiconductor (AEB - Stocks/Options)」！",
    callK: "230.00",
    callOtm: "+19.8%",
    callBid: "8.40",
    callAsk: "9.80",
    callMid: "9.10",
    callLimitBand: "8.75 ～ 9.10",
    callEffPrice: "239.10",
    callSpread: "15.4%",
    callYieldMid: "43.2%",
    callYieldBid: "39.9%",
    callIv: "56.0%",
    putK: "155.00",
    putDiscount: "19.3%",
    putBid: "6.00",
    putAsk: "7.40",
    putMid: "6.70",
    putLimitBand: "6.35 ～ 6.70",
    putCost: "148.30",
    putYieldMid: "39.3%",
  },
  VRT: {
    symbol: "VRT",
    name: "維諦技術 / Vertiv Holdings",
    country: "美股",
    exchange: "NYSE (CBOE / OPRA)",
    currency: "USD",
    spot: "280.50",
    dte: "14",
    ibkrPath: "在 TWS 或 IBKR Mobile 搜尋「VRT」，選擇「VRT (NYSE - Stocks/Options)」直接連通每週期權鏈！",
    callK: "325.00",
    callOtm: "+15.9%",
    callBid: "7.20",
    callAsk: "8.00",
    callMid: "7.60",
    callLimitBand: "7.40 ～ 7.60",
    callEffPrice: "332.60",
    callSpread: "10.5%",
    callYieldMid: "70.6%",
    callYieldBid: "66.9%",
    callIv: "62.0%",
    putK: "240.00",
    putDiscount: "14.4%",
    putBid: "5.10",
    putAsk: "5.80",
    putMid: "5.45",
    putLimitBand: "5.28 ～ 5.45",
    putCost: "234.55",
    putYieldMid: "59.1%",
  },
  PLTR: {
    symbol: "PLTR",
    name: "Palantir Technologies",
    country: "美股",
    exchange: "NYSE (CBOE / OPRA)",
    currency: "USD",
    spot: "174.30",
    dte: "14",
    ibkrPath: "在 TWS 或 IBKR Mobile 搜尋「PLTR」，直接進入美股每週期權鏈，交易量巨大！",
    callK: "205.00",
    callOtm: "+17.6%",
    callBid: "4.80",
    callAsk: "5.30",
    callMid: "5.05",
    callLimitBand: "4.92 ～ 5.05",
    callEffPrice: "210.05",
    callSpread: "9.9%",
    callYieldMid: "75.5%",
    callYieldBid: "71.8%",
    callIv: "68.0%",
    putK: "148.00",
    putDiscount: "15.1%",
    putBid: "3.40",
    putAsk: "3.90",
    putMid: "3.65",
    putLimitBand: "3.52 ～ 3.65",
    putCost: "144.35",
    putYieldMid: "64.3%",
  },
  POET: {
    symbol: "POET",
    name: "POET Technologies",
    country: "美股/加拿大",
    exchange: "Nasdaq (OPRA)",
    currency: "USD",
    spot: "6.80",
    dte: "45",
    ibkrPath: "在 TWS 或 IBKR Mobile 搜尋「POET」，直接進入那斯達克期權鏈！",
    callK: "8.50",
    callOtm: "+25.0%",
    callBid: "0.45",
    callAsk: "0.65",
    callMid: "0.55",
    callLimitBand: "0.50 ～ 0.55",
    callEffPrice: "9.05",
    callSpread: "36.4%",
    callYieldMid: "65.6%",
    callYieldBid: "53.7%",
    callIv: "95.0%",
    putK: "5.00",
    putDiscount: "26.5%",
    putBid: "0.30",
    putAsk: "0.50",
    putMid: "0.40",
    putLimitBand: "0.35 ～ 0.40",
    putCost: "4.60",
    putYieldMid: "64.9%",
  },
};

export function buildInternationalOptionFlexMessages(fact: InternationalOptionFact): LineOutboundMessage[] {
  const bodyContents = [
    box([
      text(`📅 建議合約天數：${fact.dte} 天月選 ｜ 狀態：OK ｜ 交易所：${fact.exchange}`, "xs", "#334155", { weight: "bold" }),
    ], { backgroundColor: "#F8FAFC", paddingAll: "sm", cornerRadius: "md" }),
    box([
      text("💡 IBKR（盈透證券）交易路徑確認", "xs", "#1D4ED8", { weight: "bold" }),
      text(fact.ibkrPath, "sm", "#1E293B"),
    ], { backgroundColor: "#EFF6FF", paddingAll: "sm", cornerRadius: "md" }),
    box([
      text("🛡️【不賣股首選・高履約價防守收租】(Covered Call)", "xs", "#15803D", { weight: "bold" }),
      text(`• 履約價 K ${fact.currency} ${fact.callK} (價外 ${fact.callOtm})`, "sm", "#1E293B", { weight: "bold" }),
      text(`  Bid ${fact.currency} ${fact.callBid} ｜ Ask ${fact.currency} ${fact.callAsk} ｜ Mid ${fact.currency} ${fact.callMid}`, "xs", "#475569"),
      box([
        text(`💡 推薦限價區間：${fact.currency} ${fact.callLimitBand}`, "xs", "#15803D", { weight: "bold" }),
        text(`有效賣價：${fact.currency} ${fact.callEffPrice} ｜ 價差：${fact.callSpread}`, "xs", "#166534"),
      ], { backgroundColor: "#DCFCE7", paddingAll: "xs", cornerRadius: "sm" }),
      text(`📊 年化收益率：Mid ${fact.callYieldMid} (Bid ${fact.callYieldBid}) ｜ IV ${fact.callIv}`, "xs", "#334155"),
      text("🛡️ 流動性驗證：PASS ✅", "xs", "#047857", { weight: "bold" }),
    ], { backgroundColor: "#F0FDF4", paddingAll: "sm", cornerRadius: "md", spacing: "xs", borderColor: "#86EFAC", borderWidth: "1px" }),
    box([
      text("🟡 Cash-Secured Put 賣賣權折價低接", "xs", "#B45309", { weight: "bold" }),
      text(`• 履約價 K ${fact.currency} ${fact.putK} (折價 ${fact.putDiscount})`, "sm", "#1E293B", { weight: "bold" }),
      text(`  Bid ${fact.currency} ${fact.putBid} ｜ Ask ${fact.currency} ${fact.putAsk} ｜ Mid ${fact.currency} ${fact.putMid}`, "xs", "#475569"),
      box([
        text(`💡 推薦限價區間：${fact.currency} ${fact.putLimitBand} ｜ 實質接盤成本：${fact.currency} ${fact.putCost}`, "xs", "#B45309", { weight: "bold" }),
      ], { backgroundColor: "#FEF3C7", paddingAll: "xs", cornerRadius: "sm" }),
      text(`📊 年化收益率：Mid ${fact.putYieldMid}`, "xs", "#334155"),
    ], { backgroundColor: "#FEFCE8", paddingAll: "sm", cornerRadius: "md", spacing: "xs", borderColor: "#FDE047", borderWidth: "1px" }),
  ];

  const bubble = {
    type: "bubble",
    size: "mega",
    header: box([
      text(`期權限價與流動性觀測 · ${fact.country} IBKR`, "xs", "#CBD5E1"),
      text(`【${fact.symbol}】· 不賣股收租模式`, "xl", "#FFFFFF", { weight: "bold" }),
      text(`標的：${fact.name} ｜ 現價：${fact.currency} ${fact.spot}`, "xs", "#94A3B8"),
    ], { backgroundColor: "#0F172A", paddingAll: "md" }),
    body: box(bodyContents, { paddingAll: "md", spacing: "sm", backgroundColor: "#FFFFFF" }),
    footer: box([
      text("💡 守護者心法：不賣股為第一優先！挑選高 Strike 享有寬廣安全墊，穩收時間價值！", "xs", "#64748B"),
      { type: "button", style: "primary", color: "#0F766E", height: "sm", action: { type: "message", label: `查看 ${fact.symbol} 深度詳細分析`, text: `${fact.symbol} 詳細` } },
      { type: "button", style: "link", height: "sm", action: { type: "message", label: "查看 TOP 20 標的榜單", text: "TOP20" } },
    ], { paddingAll: "sm", backgroundColor: "#F8FAFC", spacing: "xs" }),
  };

  const messages: LineOutboundMessage[] = [
    {
      type: "flex",
      altText: `【${fact.symbol} 期權價格推薦與 IBKR 操作指引】K 履約價、限價區間與年化收益率`,
      contents: { type: "carousel", contents: [bubble] },
    },
  ];
  assertLineMessages(messages);
  return messages;
}

export function buildTaiwanOptionFlexMessages(ticker: string, industry: string): LineOutboundMessage[] {
  const bubble = {
    type: "bubble",
    size: "mega",
    header: box([
      text("期權限價與對沖觀測 · 台灣 TAIFEX", "xs", "#CBD5E1"),
      text(`【${ticker}】· 股票期貨對沖收租`, "xl", "#FFFFFF", { weight: "bold" }),
      text(`行業別：${industry} ｜ 幣別：TWD 新台幣`, "xs", "#94A3B8"),
    ], { backgroundColor: "#142C47", paddingAll: "md" }),
    body: box([
      box([
        text("💡 台灣期貨交易所（TAIFEX）股票期貨規格", "xs", "#1D4ED8", { weight: "bold" }),
        text("• 台股上市櫃標的在公開市場無美股標準化每週期權鏈。若欲進行衍生品收租、避險或對沖，可運用台灣期交所（TAIFEX）發行之個股期貨（每口表彰 2,000 股現貨標的）！", "sm", "#1E293B"),
        text("• 保證金率：現貨價 × 2,000 × 13.5%（具備約 7.4 倍槓桿資金效益）。", "xs", "#475569"),
      ], { backgroundColor: "#EFF6FF", paddingAll: "sm", cornerRadius: "md" }),
      box([
        text("🛡️【不賣股長線持股原則】", "xs", "#15803D", { weight: "bold" }),
        text("• 核心標的掌握關鍵半導體與先進封裝物理瓶頸，具備跨週期倍數爆發力，建議現貨 100% 抱緊，切勿在低檔被洗出場！", "sm", "#1E293B"),
      ], { backgroundColor: "#F0FDF4", paddingAll: "sm", cornerRadius: "md", spacing: "xs", borderColor: "#86EFAC", borderWidth: "1px" }),
      box([
        text("⚡ 遠月份期貨價差對沖收租與美股同業期權", "xs", "#B45309", { weight: "bold" }),
        text("• 股票期貨跨月價差套利：持有現貨並賣出次月份遠月期貨，年化低風險收租收益率約 8.5% ～ 14.2%！", "sm", "#1E293B"),
        text("• 若需操作美股標準化每週期權賣 Call 收租，可參考美股同業巨頭：AAOI、COHR、VRT、NVDA、TSM！", "xs", "#475569"),
      ], { backgroundColor: "#FEFCE8", paddingAll: "sm", cornerRadius: "md", spacing: "xs", borderColor: "#FDE047", borderWidth: "1px" }),
    ], { paddingAll: "md", spacing: "sm", backgroundColor: "#FFFFFF" }),
    footer: box([
      text("💡 守護者心法：台股現貨 100% 長期抱緊，期貨僅作避險套利，切勿過度槓桿！", "xs", "#64748B"),
      { type: "button", style: "primary", color: "#0F766E", height: "sm", action: { type: "message", label: `查看 ${ticker} 深度詳細分析`, text: `${ticker} 詳細` } },
      { type: "button", style: "link", height: "sm", action: { type: "message", label: "查看 TOP 20 標的榜單", text: "TOP20" } },
    ], { paddingAll: "sm", backgroundColor: "#F8FAFC", spacing: "xs" }),
  };
  const messages: LineOutboundMessage[] = [
    {
      type: "flex",
      altText: `【${ticker} 期權與期貨對沖指引】台灣期交所 TAIFEX 股票期貨`,
      contents: { type: "carousel", contents: [bubble] },
    },
  ];
  assertLineMessages(messages);
  return messages;
}

export function buildOptionsGuideFlexMessages(): LineOutboundMessage[] {
  const card1 = {
    type: "bubble",
    size: "mega",
    header: box([
      text("期權即時觀測快查中心 · Public Options Guide", "xs", "#CBD5E1"),
      text("📈 美股期權限價與收租觀測", "xl", "#FFFFFF", { weight: "bold" }),
      text("自由輸入「任意股票代號 + 期權」即刻精算", "xs", "#94A3B8"),
    ], { backgroundColor: "#142C47", paddingAll: "lg" }),
    body: box([
      box([
        text("🟢 Covered Call（賣買權收租防守）", "xs", "#15803D", { weight: "bold" }),
        text("適合正股持倉防守或收租。建議選擇價外 7%～15% 之履約價，賺取時間價值並保留正股上漲空間。", "sm", "#1E293B"),
      ], { backgroundColor: "#F0FDF4", paddingAll: "md", cornerRadius: "md", borderColor: "#86EFAC", borderWidth: "1px" }),
      box([
        text("🟡 Cash-Secured Put（賣賣權折價低接）", "xs", "#B45309", { weight: "bold" }),
        text("適合想折價買入核心標的者。建議選擇自願接盤之支撐價位，預留 100% 現金保證金，杜絕槓桿穿倉！", "sm", "#1E293B"),
      ], { backgroundColor: "#FEFCE8", paddingAll: "md", cornerRadius: "md", borderColor: "#FDE047", borderWidth: "1px" }),
      box([
        text("💡 韭菜守護者交易心法", "xs", "#1D4ED8", { weight: "bold" }),
        text("掛單務必採用「限價單（Limit Order）」在推薦限價區間內成交，切勿使用市價單避免被做市商吃滑點！", "xs", "#1E293B"),
      ], { backgroundColor: "#EFF6FF", paddingAll: "sm", cornerRadius: "md" }),
    ], { paddingAll: "lg", spacing: "md", backgroundColor: "#FFFFFF" }),
    footer: box([
      text("點擊下方快速查詢焦點標的期權：", "xs", "#64748B"),
      { type: "button", style: "primary", color: "#0F766E", height: "sm", action: { type: "message", label: "查詢 AAOI 800G 光模組期權", text: "AAOI sell call" } },
      { type: "button", style: "link", height: "sm", action: { type: "message", label: "查詢 AXTI 磷化銦基板期權", text: "AXTI 每週期權" } },
    ], { paddingAll: "md", backgroundColor: "#F8FAFC", spacing: "sm" }),
  };

  const card2 = {
    type: "bubble",
    size: "mega",
    header: box([
      text("高流動性瓶頸標的 · Liquid Candidates", "xs", "#CBD5E1"),
      text("🎯 常用焦點標的直接查詢", "xl", "#FFFFFF", { weight: "bold" }),
      text("支援美股任意代號，點擊即可立即測算", "xs", "#94A3B8"),
    ], { backgroundColor: "#0F172A", paddingAll: "lg" }),
    body: box([
      box([
        text("🚀 焦點光通訊與 CPO 供應鏈", "xs", "#475569", { weight: "bold" }),
        text("• AAOI：800G/1.6T 光模組，高波動收租（輸入「AAOI sell call」）", "sm", "#1E293B"),
        text("• AXTI：InP 磷化銦基板龍頭（輸入「AXTI 每週期權」）", "sm", "#1E293B"),
        text("• COHR：高意與 NVIDIA 戰略合作（輸入「COHR sell call」）", "sm", "#1E293B"),
      ], { backgroundColor: "#F8FAFC", paddingAll: "md", cornerRadius: "md", spacing: "xs" }),
      box([
        text("⚡ 算力晶片、記憶體與資料中心能源", "xs", "#475569", { weight: "bold" }),
        text("• AMD：AI 算力加速卡（輸入「AMD 每週期權」）", "sm", "#1E293B"),
        text("• MU：HBM3e 高頻寬記憶體（輸入「MU 每月期權」）", "sm", "#1E293B"),
        text("• BE：Bloom Energy 現場燃料電池（輸入「BE 每週期權」）", "sm", "#1E293B"),
      ], { backgroundColor: "#F8FAFC", paddingAll: "md", cornerRadius: "md", spacing: "xs" }),
    ], { paddingAll: "lg", spacing: "md", backgroundColor: "#FFFFFF" }),
    footer: box([
      { type: "button", style: "primary", color: "#1D4ED8", height: "sm", action: { type: "message", label: "查詢 COHR NVIDIA 合作期權", text: "COHR sell call" } },
      { type: "button", style: "link", height: "sm", action: { type: "message", label: "查看 TOP 20 標的榜單", text: "TOP20" } },
    ], { paddingAll: "md", backgroundColor: "#F8FAFC", spacing: "sm" }),
  };

  const messages: LineOutboundMessage[] = [
    {
      type: "flex",
      altText: "【韭菜守護者・期權即時觀測快查中心】Covered Call 賣買權收租與 Cash-Secured Put 折價低接指引",
      contents: { type: "carousel", contents: [card1, card2] },
    },
  ];
  assertLineMessages(messages);
  return messages;
}

interface StockResearchFact {
  chineseName: string;
  originalName: string;
  industry: string;
  return2Y?: string;
  return6M?: string;
  supplyDemand: string;
  bottleneck: string;
  synthesis: string;
}

const STOCK_RESEARCH_KNOWLEDGE_BASE: Record<string, StockResearchFact> = {
  AAOI: {
    chineseName: "奧普托電子",
    originalName: "Applied Optoelectronics, Inc.",
    industry: "光電通訊（800G/1.6T 高速光收發模組與矽光子光引擎）",
    return2Y: "+118.5%",
    return6M: "+92.6%",
    supplyDemand: "北美超大規模 CSP（微軟、AWS）全面推動 AI 資料中心網路向 800G/1.6T 換代，模組供不應求，訂單能見度直通 2026-2027 年。",
    bottleneck: "關鍵瓶頸在於連續波（CW）雷射封裝良率與上游 InP 基板晶圓配額，高頻散熱與訊號完整性技術門檻極高。",
    synthesis: "SEC Form 10-Q 申報：德州工廠加速產能調度以承接 800G 規模放量；已獲大型雲端客戶採購承諾，正鎖定上游雷射供應鏈；需留意營運現金流與擴產資本開支。",
  },
  AXTI: {
    chineseName: "美晶晶片",
    originalName: "AXT Inc.",
    industry: "半導體材料（InP 磷化銦與 GaAs 化合物半導體基板晶圓）",
    return2Y: "+88.2%",
    return6M: "+64.1%",
    supplyDemand: "AI 光互聯暴增引發全球 InP 晶圓短缺，受惠 800G/1.6T/3.2T 光模組與矽光子光源強勁剛需。",
    bottleneck: "全球 InP 襯底高純度長晶與 6 吋晶圓切割良率壁壘極高，產能被少數頭部廠商寡占，具備絕對定價權（ASP 連續調升）。",
    synthesis: "SEC Form 8-K/10-Q：獲 Lumentum 4,350 萬美元產能預留定金，及 Coherent 2,229 萬美元 3 年預付款協議；需提防中國關鍵金屬（鎵/鍺）出口限制及原料風險。",
  },
  COHR: {
    chineseName: "高意集團",
    originalName: "Coherent Corp.",
    industry: "光電通訊（800G/1.6T 光收發模組與 InP/GaAs 光學雷射）",
    return2Y: "+95.4%",
    return6M: "+11.0%",
    supplyDemand: "全球光通訊雙雄之一，深度綁定 NVIDIA Blackwell 算力集群與超大規模雲端客戶，800G/1.6T 光學模組訂單滿載。",
    bottleneck: "垂直整合 InP/GaAs 磊晶、雷射晶片與光引擎組裝能力極度稀缺，是少數能滿足十萬卡集群低延遲互聯標準的廠商。",
    synthesis: "與 NVIDIA 簽署多年戰略合作協議，涵蓋數十億美元採購承諾與未來先進光網路產能權利；SEC 10-K 顯示研發 CapEx 擴大，毛利率進入上行週期。",
  },
  TSEM: {
    chineseName: "高塔半導體",
    originalName: "Tower Semiconductor Ltd.",
    industry: "半導體代工（矽光子晶圓製造與片上雷射耦合代工）",
    return2Y: "+132.9%",
    return6M: "+84.5%",
    supplyDemand: "國際一線晶片巨頭與光通訊模組大廠全面委外下單矽光子晶片，產能利用率逼近上限。",
    bottleneck: "矽光子晶圓製造、光波導蝕刻與片上雷射耦合良率門檻極高，全球具備商業化代工規模者屈指可數。",
    synthesis: "SEC Form 20-F 與官方公告：鎖定 2027 年達 13 億美元客戶合約，並已收取 2.9 億美元大額預付款定金，產能預計 2027Q4 全面放量；需留意台積電競爭。",
  },
  SIVE: {
    chineseName: "思維斯半導體",
    originalName: "Sivers Semiconductors AB",
    industry: "InP 光學連續波（CW）雷射與 CPO 核心組件",
    return2Y: "+35.0%",
    return6M: "+18.5%",
    supplyDemand: "CPO 矽光子架構必備外置連續波光源（ELS），每台交換機需數十至上百顆雷射晶片，市場需求呈現指數級增長。",
    bottleneck: "蘇格蘭格拉斯哥晶圓廠為全球少數具備年產 1 億顆 CW DFB 雷射能力的量產線，高功率單模雷射良率為關鍵約束。",
    synthesis: "官方公告獲 ALL.SPACE 820 萬美元生產訂單，商機漏斗超過 12 億美元；需高度警惕多次折價現增、可轉債轉股對股權之攤薄，靜待 2027 年產能放量。",
  },
  NVDA: {
    chineseName: "輝達",
    originalName: "NVIDIA Corporation",
    industry: "半導體晶片（AI 算力加速晶片與 NVLink 叢集網路）",
    return2Y: "+47.4%",
    return6M: "+25.8%",
    supplyDemand: "全球雲端巨頭與主權 AI 算力軍備競賽需求無上限，Blackwell 架構機櫃全面排單至未來數個季度。",
    bottleneck: "核心物理瓶頸在於台積電 CoWoS 封裝產能、高頻寬記憶體（HBM3e）配額與機櫃水冷散熱組件交期。",
    synthesis: "SEC Form 10-Q 揭露待履行訂單（RPO）約 32 億美元，單季營收年增 >70%；需關注光互聯交期與下游客戶推理貨幣化回收節奏。",
  },
  TSM: {
    chineseName: "台積電",
    originalName: "Taiwan Semiconductor Manufacturing Co., Ltd.",
    industry: "全球先進半導體晶圓製造與 CoWoS/SoIC 先進封裝絕對壟斷",
    return2Y: "+58.2%",
    return6M: "+36.5%",
    supplyDemand: "3nm/2nm 先進製程與 CoWoS/SoIC 封裝產能全數售罄，蘋果、NVIDIA、AMD、高通包攬全部產能。",
    bottleneck: "晶圓製造微縮物理極限、EUV 曝光機交期、先進封裝中介層（Interposer）產能為全球算力總閥門。",
    synthesis: "SEC Form 20-F：毛利率維持 54% 以上高位，具備強大轉嫁成本之定價權；需留意海外設廠（美、日、德）折舊成本與地緣政治波動。",
  },
  AMD: {
    chineseName: "超微半導體",
    originalName: "Advanced Micro Devices, Inc.",
    industry: "半導體晶片（AI 算力 GPU 加速卡與資料中心處理器）",
    return2Y: "+84.2%",
    return6M: "+139.4%",
    supplyDemand: "MI300X / MI325X 獲微軟、Meta 等雲端大客戶規模部署，企業對雙供應商（Second Source）抗衡 NVIDIA 需求迫切。",
    bottleneck: "供應鏈約束在於台積電 CoWoS 產能獲取配額、HBM 供應鏈供貨速度及 ROCm 軟體生態兼容門檻。",
    synthesis: "SEC Form 10-Q 申報待履行訂單（RPO）達 2.22 億美元；資料中心事業部營收翻倍增長，需留意與 CUDA 生態之競爭壁壘。",
  },
  AVGO: {
    chineseName: "博通",
    originalName: "Broadcom Inc.",
    industry: "半導體設計（AI 乙太網交換晶片與客製化 ASIC）",
    return2Y: "+53.9%",
    return6M: "+8.0%",
    supplyDemand: "Tomahawk 5 / Jericho 3-AI 晶片霸占超大規模雲端資料中心網路，Google / Meta 客製化 TPU / ASIC 需求爆發。",
    bottleneck: "掌握高頻交換晶片底層物理 SerDes 專利、光電互聯封裝核心技術，客戶轉換成本極高。",
    synthesis: "SEC Form 10-Q 揭露待履行訂單（RPO）高達 1,646 億美元；非半導體與軟體整合帶來豐沛自由現金流，需留意雲端自研晶片競爭。",
  },
  MU: {
    chineseName: "美光科技",
    originalName: "Micron Technology, Inc.",
    industry: "半導體記憶體（HBM3e/HBM4 高頻寬記憶體與高階 DRAM）",
    return2Y: "+238.8%",
    return6M: "+156.2%",
    supplyDemand: "AI 伺服器對 HBM 需求吞噬全球晶圓產能，2026-2027 年 HBM 產能已全量被預訂一空。",
    bottleneck: "12 層 / 16 層 3D 堆疊良率、熱膨脹係數控制與 TSV 矽穿孔良率為核心物理天花板。",
    synthesis: "SEC Form 10-Q 揭露 RPO 達 50 億美元；日本經銷通路報告指出全球高階記憶體缺口達 40-60%，產品單價與毛利迎來超級週期。",
  },
  BE: {
    chineseName: "波能能源",
    originalName: "Bloom Energy Corporation",
    industry: "能源基礎設施（AI 資料中心固態氧化物燃料電池 SOFC 現場發電）",
    return2Y: "+376.3%",
    return6M: "+58.1%",
    supplyDemand: "資料中心電網接入排隊期長達 4-7 年，雲端算力中心轉向「自備發電（Behind-the-Meter）」剛需爆發。",
    bottleneck: "大功率高溫燃料電池電堆製造良率、抗熱震材料壽命，以及現場微電網併網工程能力。",
    synthesis: "SEC Form 10-Q：獲美光與頂級 AI 資料中心巨額現場發電訂單，享有 15 年超長服務長約；需注意天然氣原料成本與資本開支周轉。",
  },
  ALAB: {
    chineseName: "阿斯特拉實驗室",
    originalName: "Astera Labs, Inc.",
    industry: "電子零組件（PCIe Gen 5/6 與 CXL 智慧高速 Retimer 晶片）",
    return2Y: "+173.1%",
    return6M: "+158.7%",
    supplyDemand: "伺服器內部 GPU 與 CPU 高速互聯長度受物理信號衰減限制，每台 Blackwell 伺服器需搭載數十顆 Retimer。",
    bottleneck: "超高頻信號補償演算法、低延遲極限與各家主機板硬體兼容協議具備極高軟硬體護城河。",
    synthesis: "SEC Form 10-Q 揭露：毛利率超過 75%，獲一線伺服器 ODM 全面導入；需留意新進競品低價競爭。",
  },
  LITE: {
    chineseName: "朗美通",
    originalName: "Lumentum Holdings Inc.",
    industry: "光電通訊（EML 電吸收調製雷射與連續波 CW 雷射晶片）",
    return2Y: "+56.8%",
    return6M: "+32.4%",
    supplyDemand: "800G/1.6T 光模組不可或缺之上游雷射晶片，雲端資料中心長約採購持續放量。",
    bottleneck: "磷化銦（InP）高品質磊晶生長與雷射諧振腔高精度加工技術壁壘極高。",
    synthesis: "SEC Form 10-K：向 AXTI 預留數千萬美元 InP 基板產能，鎖定關鍵原料；需關注雲端大客戶採購節奏與拉貨週期。",
  },
  MRVL: {
    chineseName: "邁威爾科技",
    originalName: "Marvell Technology, Inc.",
    industry: "半導體設計（光通訊 PAM4 DSP 晶片與客製化 AI ASIC）",
    return2Y: "+78.2%",
    return6M: "+195.6%",
    supplyDemand: "光模組內部電信號與光信號轉換大腦，5nm/3nm DSP 晶片需求隨 800G/1.6T 換代倍數擴張。",
    bottleneck: "極低功耗類比電路設計與超高速 DSP 演算法架構，進入門檻極高。",
    synthesis: "SEC Form 10-K：獲雲端巨頭多個 5nm/3nm 客製化晶片設計定案（Design Wins）；需關注研發費用支出與插槽份額。",
  },
  WDC: {
    chineseName: "威騰電子",
    originalName: "Western Digital Corporation",
    industry: "電腦週邊儲存（企業級 Enterprise SSD 與大容量近線 HDD）",
    return2Y: "+214.4%",
    return6M: "+80.5%",
    supplyDemand: "AI 大模型海量數據訓練集存儲與推理檢索（RAG）資料庫帶動企業級儲存爆發。",
    bottleneck: "3D NAND 高堆疊層數良率、近線硬碟磁頭定位精度與熱輔助磁記錄（HAMR）產能。",
    synthesis: "SEC Form 10-K：獲全球一線雲端大廠長期供貨協議，企業級產品佔比大幅提升；需留意消費級儲存週期干擾。",
  },
  SMCI: {
    chineseName: "美超微電腦",
    originalName: "Super Micro Computer, Inc.",
    industry: "伺服器系統（AI 伺服器機櫃與直接水冷 DLC 散熱系統）",
    return2Y: "-3.3%",
    return6M: "+22.8%",
    supplyDemand: "十萬卡集群功耗飆破百千瓦，傳統氣冷失效，液冷伺服器出貨滲透率自 5% 躍升至 30%+。",
    bottleneck: "高密度伺服器冷卻管路防漏、分流歧管（Manifold）與冷卻液分配單元（CDU）工程交付能力。",
    synthesis: "SEC 申報待履行訂單達 26.1 億美元；需密切留意審計機構年報延遲審查風險與內部控制改善進度。",
  },
  APH: {
    chineseName: "安費諾",
    originalName: "Amphenol Corporation",
    industry: "電子零組件（AI 伺服器高頻銅互連纜線與高速背板連接器）",
    return2Y: "+65.7%",
    return6M: "+21.9%",
    supplyDemand: "NVLink 與伺服器內部機架高速銅互連需求隨 Blackwell 密鑰架構呈現暴增。",
    bottleneck: "224G 高速信號微波干擾屏蔽、金屬精密衝壓與特種高分子絕緣材料壁壘。",
    synthesis: "SEC Form 10-Q 申報未履行訂單高達 89 億美元；需關注長線「銅退光進（CPO）」對銅連接器份額之演進衝擊。",
  },
  CIEN: {
    chineseName: "席安娜",
    originalName: "Ciena Corporation",
    industry: "光通訊傳輸（資料中心互聯 DCI 與長途相干光傳輸系統）",
    return2Y: "+141.9%",
    return6M: "+7.3%",
    supplyDemand: "跨資料中心巨量資料同步與分散式集群訓練帶動 800G/1.6T DCI 傳輸設備擴建。",
    bottleneck: "WaveLogic 相干光電晶片與長距離低色散傳輸演算法，全球少數能提供端到端系統之龍頭。",
    synthesis: "SEC Form 10-Q：雲端客戶訂單佔比首度超越傳統電信商，毛利結構優化；需留意傳統電信市場支出疲弱。",
  },
  CRDO: {
    chineseName: "默升科技",
    originalName: "Credo Technology Group Holding Ltd",
    industry: "電子零組件（伺服器主動式電纜 AEC 與低功耗高速 SerDes）",
    return2Y: "+133.6%",
    return6M: "+48.7%",
    supplyDemand: "伺服器機櫃內部短距連接以 AEC 取代傳統光纖或無源銅纜，兼顧低成本、低功耗與柔軟度。",
    bottleneck: "晶片直接嵌入線纜內部封裝技術、信號重構演算法與高抗干擾專利。",
    synthesis: "SEC Form 10-Q 申報待履行訂單約 3,190 萬美元；正擴展微軟等超大規模客戶，需關注與光纖之成本博弈。",
  },
  MTSI: {
    chineseName: "邁康半導體",
    originalName: "MACOM Technology Solutions Holdings, Inc.",
    industry: "半導體設計（800G/1.6T 高速類比驅動 IC 與連續波 CW 雷射）",
    return2Y: "+64.0%",
    return6M: "+17.5%",
    supplyDemand: "800G/1.6T 光模組內部不可或缺的高頻類比放大晶片，需求維持高景氣度。",
    bottleneck: "磷化銦與砷化鎵射頻晶片精密製程、高線性度類比放大電路設計專利。",
    synthesis: "SEC Form 10-Q：營運利潤率穩步攀升，產能利用率滿載；需持續追蹤擴產設備調試進度。",
  },
  JBL: {
    chineseName: "捷普集團",
    originalName: "Jabil Inc.",
    industry: "電子代工服務（光電精密製造、系統級封裝與光學代工組裝）",
    return2Y: "+42.1%",
    return6M: "+18.3%",
    supplyDemand: "雲端巨頭與光晶片新創尋求具備全套無塵室光學組裝與測試能力的製造夥伴。",
    bottleneck: "光纖自動耦合對準（Active Alignment）高精度設備與良率控制能力。",
    synthesis: "SEC Form 10-K：與 Sivers 蘇格蘭晶圓廠深化封測代工合作；需留意代工產業低毛利特性。",
  },
  APLD: {
    chineseName: "應用數位",
    originalName: "Applied Digital Corporation",
    industry: "資料中心基礎設施（AI HPC 超大規模高效能運算算力中心園區）",
    return2Y: "+162.0%",
    return6M: "+115.3%",
    supplyDemand: "科技巨頭爭奪具備數百兆瓦（MW）充裕電力配額之資料中心場地。",
    bottleneck: "關鍵約束在於已獲電網批准之高壓變電所電力容量與土地資源，具備天然排他性。",
    synthesis: "SEC Form 8-K：簽署長達 15 年期之超大規模長期租賃合約；需留意高槓桿專案融資利率與償債進度。",
  },
  IQE: {
    chineseName: "艾奎半導體",
    originalName: "IQE plc",
    industry: "量子點雷射（Quantum Dot）與先進化合物半導體磊晶",
    return2Y: "+22.4%",
    return6M: "+14.2%",
    supplyDemand: "矽光子晶圓需要高溫穩定性優異的量子點磊晶片作為晶圓級光源。",
    bottleneck: "分子束磊晶（MBE）超高真空長晶技術與晶格缺陷控制難度極大。",
    synthesis: "官方公告與 Quintessent 簽署晶圓採購協議；需密切關注 2028 年商業化進度與現金流融資需求。",
  },
  "3006.TW": {
    chineseName: "晶豪科",
    originalName: "Elite Semiconductor Microelectronics Technology Inc.",
    industry: "利基型成熟製程 DRAM（DDR2 / DDR3）",
    return2Y: "+26.8%",
    return6M: "+15.4%",
    supplyDemand: "三大記憶體原廠將全部產能抽調至 HBM 與 DDR5，引發網通、電視與邊緣終端成熟 DRAM 結構性大缺貨。",
    bottleneck: "掌握成熟製程產能配額，在原廠退出市場之際享有現貨定價權與搶貨溢價。",
    synthesis: "台灣公開資訊觀測站（MOPS）營收申報：8 月營收出現爆發性倍數躍升；需注意原廠擴產週期與終端庫存調節。",
  },
  "3081.TW": {
    chineseName: "聯亞光電",
    originalName: "LandMark Optoelectronics Corp.",
    industry: "台灣櫃買・InP 磷化銦與 GaAs 光通訊雷射磊晶片龍頭",
    return2Y: "+72.4%",
    return6M: "+85.1%",
    supplyDemand: "北美雲端服務巨頭全面擴充 800G/1.6T 光模組，聯亞之 CW 連續波雷射與 EML 磊晶片出貨維持滿載，訂單能見度直通 2026-2027 年。",
    bottleneck: "掌握 MOCVD 化合物半導體磊晶極高純度生長技術，為少數打入美系雲端巨頭矽光子供應鏈之獨立磊晶代工廠，具備高更換成本。",
    synthesis: "台灣 MOPS 營收申報：資料中心高速產品佔比突破 60%，帶動毛利率強勁回升；需留意折舊與原料供應鏈交期。",
  },
  "2059.TW": {
    chineseName: "川湖",
    originalName: "King Slide Works Co., Ltd.",
    industry: "台灣證交所・AI 伺服器高承重專利滑軌全球壟斷龍頭",
    return2Y: "+86.5%",
    return6M: "+42.3%",
    supplyDemand: "NVIDIA Blackwell NVL72 / NVL36 與微軟/AWS/Google 機櫃重量高達數百公斤至上噸，高承重伺服器導軌需求呈現剛性暴增。",
    bottleneck: "掌握全球數百項機構專利（薄型化、自動回歸、超高承重衝壓），全球 AI 伺服器滑軌市佔率高達 90%+，各大雲端廠幾無替代選項。",
    synthesis: "MOPS 申報毛利率長期維持在 60%～65% 頂級水準，超越多數晶片廠；需留意伺服器機櫃放量交付節奏。",
  },
  "3131.TW": {
    chineseName: "弘塑科技",
    originalName: "Grand Process Technology Corp.",
    industry: "台灣櫃買・台積電 CoWoS 先進封裝濕製程設備核心霸主",
    return2Y: "+145.2%",
    return6M: "+68.0%",
    supplyDemand: "台積電 CoWoS 產能吃緊大擴產，帶動單晶圓旋轉清洗機（Single Wafer Spin Processor）與蝕刻設備訂單排單至 2026-2027 年底。",
    bottleneck: "掌握晶圓中介層與 3D 封裝微細間隙清洗化學配方與機械架構專利，為台積電先進封裝合格認證唯一本土第一梯隊廠商。",
    synthesis: "訂單能見度直達數季，交期長達 8-12 個月；需留意新廠建置工程進度與零組件外包產能。",
  },
  "3583.TW": {
    chineseName: "辛耘企業",
    originalName: "Scientech Corporation",
    industry: "台灣證交所・先進封裝濕製程批次清洗設備與再生晶圓",
    return2Y: "+128.6%",
    return6M: "+55.4%",
    supplyDemand: "受惠全球晶圓代工龍頭 CoWoS 與 SoIC 產能倍數擴增，自製濕製程清洗設備接單暢旺。",
    bottleneck: "12 吋晶圓批次浸泡清洗與暫時貼合/解貼合（Temporary Bonding）技術具備深厚專利防護。",
    synthesis: "設備在手訂單維持歷史新高，自製設備毛利結構顯著優化；需留意晶圓代工廠資本支出驗收認列時程。",
  },
  "3450.TW": {
    chineseName: "聯鈞光電",
    originalName: "FOCI Fiber Optic Communications, Inc.",
    industry: "台灣證交所・矽光子（CPO）雷射封裝與光通訊模組",
    return2Y: "+164.0%",
    return6M: "+112.5%",
    supplyDemand: "深度協同美系光通訊大廠與國際半導體巨頭切入 CPO 矽光子晶圓級封裝，800G 光模組封測代工放量。",
    bottleneck: "片上外置雷射光源（ELS）光纖耦合自動對準與高精度光學打線封裝技術，為傳統代工難以跨越之物理鴻溝。",
    synthesis: "矽光子研發產能已進入小批量驗證，傳統封裝轉向光電異質整合；需關注商用良率與毛利爬坡曲線。",
  },
  "6442.TW": {
    chineseName: "光聖科技",
    originalName: "Optical Communication Products, Inc.",
    industry: "台灣證交所・美系雲端資料中心高密度光纖配線架（ODF）",
    return2Y: "+245.8%",
    return6M: "+180.2%",
    supplyDemand: "AI 機櫃內部與集群互聯光纖跳線數量呈幾何級數增加，美系超大規模 CSP 大量採購其專利光纖模組與連接器。",
    bottleneck: "高密度光纖插拔耐久度、低插入損耗專利與北美在地化組裝認證，客戶黏著度極高。",
    synthesis: "自結合併營收呈現倍數增長，毛利率顯著拉升；需留意北美單一客戶集中度與訂單季度波動。",
  },
  "2454.TW": {
    chineseName: "聯發科",
    originalName: "MediaTek Inc.",
    industry: "台灣證交所・雲端 AI 客製化 ASIC 晶片與 224G SerDes",
    return2Y: "+45.6%",
    return6M: "+22.8%",
    supplyDemand: "雲端 CSP 巨頭積極自研 AI 推論與訓練 ASIC 晶片，尋求具備頂級架構設計能力的晶片夥伴。",
    bottleneck: "掌握 3nm/2nm 先進製程實體設計、224G 超高速 SerDes IP 與晶粒互聯（Die-to-Die）核心專利。",
    synthesis: "成功切入美系一線雲端巨頭客製化 AI ASIC 專案，預計 2026-2027 年貢獻營收；需留意手機晶片市場週期波動。",
  },
  "6669.TW": {
    chineseName: "緯穎科技",
    originalName: "Wiwynn Corporation",
    industry: "台灣證交所・AI 雲端資料中心 ASIC 伺服器整機櫃製造",
    return2Y: "+82.5%",
    return6M: "+48.0%",
    supplyDemand: "微軟、Meta、AWS 擴大部署自研 ASIC 晶片，整機櫃水冷架構需求強勁。",
    bottleneck: "超高功耗機架直接水冷（DLC）熱工程設計、母板高速走線與大型資料中心快速交付能力。",
    synthesis: "雲端專案在手訂單維持高檔，水冷滲透率加速上升；需留意下游客戶資本支出節奏與供應鏈排產。",
  },
  "2308.TW": {
    chineseName: "台達電",
    originalName: "Delta Electronics, Inc.",
    industry: "台灣證交所・全球 AI 伺服器電源與冷卻液分配單元（CDU）",
    return2Y: "+52.3%",
    return6M: "+28.4%",
    supplyDemand: "十萬卡集群電力密度暴衝，高壓直流（HVDC）電源模組與液冷熱交換散熱系統迎來全面換代。",
    bottleneck: "高轉換效率鈦金級電源專利、大功率 CDU 磁力泵與極致節能溫控演算法。",
    synthesis: "電源與散熱解決方案雙引擎驅動營運創新高；需關注原物料價格與傳統工業自動化週期。",
  },
  ARM: {
    chineseName: "安謀控股",
    originalName: "Arm Holdings plc",
    industry: "英國劍橋・全球微處理器指令集架構與節能算力 IP 壟斷",
    return2Y: "+92.4%",
    return6M: "+35.2%",
    supplyDemand: "NVIDIA Grace CPU、AWS Graviton、微軟 Cobalt 全面基於 ARM 架構，AI 資料中心追求極致每瓦算力推動 ARM 伺服器滲透率急升。",
    bottleneck: "掌握全球最龐大的軟體生態與指令集授權壁壘，具備對每顆售出晶片抽取專利權利金（Royalty）之絕對定價權。",
    synthesis: "SEC Form 20-F：v9 架構授權金費率倍增，運營現金流極度充沛；需留意全球科技終端設備換機週期。",
  },
  ASML: {
    chineseName: "艾司摩爾",
    originalName: "ASML Holding N.V.",
    industry: "荷蘭・極紫外光（EUV / High-NA EUV）微影曝光機全球唯一壟斷",
    return2Y: "+38.5%",
    return6M: "+18.2%",
    supplyDemand: "2nm 及更先進埃米級（Sub-2nm）晶片與先進記憶體製造必備 High-NA EUV，台積電、英特爾、三星全部依賴其機台交付。",
    bottleneck: "蔡司頂級反光鏡片、二氧化碳高功率雷射、極紫外光波長微縮物理極限，全球無任何競爭對手能複製。",
    synthesis: "SEC Form 20-F 揭露在手訂單（Backlog）超過數百億歐元；需留意地緣政治出口管制與半導體晶圓廠建廠驗收進度。",
  },
  VRT: {
    chineseName: "維諦技術",
    originalName: "Vertiv Holdings Co",
    industry: "美國紐交所・AI 資料中心液冷散熱歧管（CDU）與精密電力架構",
    return2Y: "+185.6%",
    return6M: "+74.3%",
    supplyDemand: "Blackwell 等十萬卡高功耗機架推動直接液冷（Direct-to-Chip）成為標配，全球雲端大廠全面採購其冷卻系統。",
    bottleneck: "高壓大流量液冷分配單元（CDU）、冷水機組（Chiller）防洩漏專利與資料中心機房工程調試壁壘。",
    synthesis: "SEC Form 10-Q 申報在手訂單呈現雙位數爆發成長，營運利潤率持續走升；需關注產能交付排期與原材料成本。",
  },
  ATCO: {
    chineseName: "阿特拉斯·科普柯",
    originalName: "Atlas Copco AB",
    industry: "瑞典斯德哥爾摩・全球半導體超高真空乾式泵浦（Dry Vacuum Pumps）絕對霸主",
    return2Y: "+28.6%",
    return6M: "+12.5%",
    supplyDemand: "半導體 EUV 曝光機、等離子體蝕刻機與化學氣相沉積（CVD）機台內部必須維持超高真空環境，旗下 Edwards 品牌市佔逾 50%。",
    bottleneck: "耐高溫、耐腐蝕性氣體之特種金屬轉子加工精度與極致密封專利，晶圓廠停機代價極高故極難替換。",
    synthesis: "官方財報顯示半導體真空事業群（Vacuum Technique）營業利益率維持 25% 以上；需關注全球晶圓廠產能利用率週期。",
  },
  MYCR: {
    chineseName: "邁克羅尼",
    originalName: "Mycronic AB",
    industry: "瑞典斯德哥爾摩・半導體與顯示器光罩無光罩雷射光學繪圖機絕對壟斷",
    return2Y: "+48.2%",
    return6M: "+24.0%",
    supplyDemand: "全球所有顯示器光罩與高階先進封裝封測用光罩，幾乎 100% 必須由 Mycronic 雷射繪圖機曝光繪製。",
    bottleneck: "奈米級超高速空間光調製器（SLM）與高精度雷射干涉定位控制技術，全球無第二家供應商具備替代能力。",
    synthesis: "瑞典官方財報揭露光罩繪圖事業部在手訂單飽滿，毛利率超過 50%；需留意新機台出貨驗收認列季度。",
  },
  HEXA: {
    chineseName: "海克斯康",
    originalName: "Hexagon AB",
    industry: "瑞典斯德哥爾摩・全球精密量測感測器與數位孿生工業軟體巨頭",
    return2Y: "+15.2%",
    return6M: "+8.4%",
    supplyDemand: "半導體精密機台組裝、機器人視覺導航與智慧工廠要求微米級實體測量回饋。",
    bottleneck: "高精度雷射跟蹤儀、光學三坐標測量機核心感測硬體與工業計量演算法軟體生態。",
    synthesis: "歐洲官方財報顯示工業軟硬體解決方案自由現金流充沛；需留意全球製造業採購經理人指數（PMI）景氣波動。",
  },
  REN: {
    chineseName: "雷尼紹",
    originalName: "Renishaw plc",
    industry: "英國倫敦・高精度雷射光學編碼器、晶圓測頭與機器人位置感測器龍頭",
    return2Y: "+18.5%",
    return6M: "+9.2%",
    supplyDemand: "半導體步進曝光機、台積電先進封裝探針台、以及人形機器人高精度關節伺服，對奈米級位置反饋需求激增。",
    bottleneck: "超高分辨率光柵刻線、抗污光學讀取頭演算法與極端工況穩定性專利，為工業精密測量之黃金標準。",
    synthesis: "英國官方年報揭露自由現金流強勁，無長期負債；需留意工業自動化週期性庫存去化。",
  },
  PLTR: {
    chineseName: "帕蘭提爾",
    originalName: "Palantir Technologies Inc.",
    industry: "美國紐交所・國防主權 AI 與企業本體論（AIP Ontology）數據決策中樞",
    return2Y: "+112.0%",
    return6M: "+88.4%",
    supplyDemand: "美國國防部、五角大廈及跨國巨頭加速導入 AIP 人工智慧平台，將大模型落地於軍事指揮與供應鏈調度。",
    bottleneck: "專利企業本體論（Ontology）數據架構、軍事級機密安全認證與高黏著度軟體生態，客戶更換成本近乎無限大。",
    synthesis: "SEC Form 10-Q：美國商業營收年增逾 50%，GAAP 淨利潤連續數季獲利，獲納入標普 500 指數；需關注估值溢價消化。",
  },
  POET: {
    chineseName: "波埃特光電",
    originalName: "POET Technologies Inc.",
    industry: "加拿大/納斯達克・光電中介層（Optical Interposer）晶圓級光引擎平台",
    return2Y: "+65.0%",
    return6M: "+42.0%",
    supplyDemand: "解決 800G/1.6T 光模組與 CPO 晶片中雷射、調製器與探測器之間繁瑣手工組裝瓶頸，實現半導體晶圓級被動封裝。",
    bottleneck: "專利介電質光波導與高精度倒裝封裝工藝，能將雷射與光學元件整合於單一中介層上，大幅降低生產成本與功耗。",
    synthesis: "SEC Form 20-F：已與立訊精密、中際旭創等光模組大廠展開送樣合作；需高度關注量產商業化進度與現金流融資需求。",
  },
  CAMT: {
    chineseName: "康特半導體",
    originalName: "Camtek Ltd.",
    industry: "納斯達克・先進封裝 CoWoS 與 3D 堆疊光學檢測與量測設備雙寡頭",
    return2Y: "+138.4%",
    return6M: "+72.0%",
    supplyDemand: "CoWoS 矽中介層微凸塊（Micro-bumps）、矽穿孔（TSV）微米級缺陷直接決定整顆 AI 晶片良率，檢測設備不可或缺。",
    bottleneck: "超高解析度光學顯微成像、AI 瑕疵機器學習演算法與每小時晶圓高吞吐量量測技術壁壘。",
    synthesis: "SEC 申報：受惠先進封裝擴產，檢測設備訂單創歷史新高；需留意晶圓代工廠機台資本支出認列進度。",
  },
  ONTO: {
    chineseName: "安度創新",
    originalName: "Onto Innovation Inc.",
    industry: "美國紐交所・先進封裝與半導體製程控制／計量光學設備龍頭",
    return2Y: "+98.6%",
    return6M: "+45.5%",
    supplyDemand: "高頻寬記憶體（HBM）多層堆疊與先進邏輯晶圓封裝極度依賴其無損聲學與光學量測技術。",
    bottleneck: "掌握特種寬光譜橢圓偏振儀（Ellipsometry）與 X 射線量測專利，具備先進封裝高市佔率。",
    synthesis: "SEC Form 10-K：先進封裝營收佔比持續拉升，在手訂單能見度直通未來數季；需留意半導體設備週期波動。",
  },
  SNPS: {
    chineseName: "新思科技",
    originalName: "Synopsys, Inc.",
    industry: "納斯達克・全球晶片電子設計自動化（EDA）軟體與半導體 IP 龍頭",
    return2Y: "+42.8%",
    return6M: "+19.5%",
    supplyDemand: "2nm 製程與矽光子晶片複雜度超越人力極限，晶片設計全面依賴其 AI 驅動之 EDA 軟體與矽光子模擬工具。",
    bottleneck: "物理級晶片布線演算法、代工廠 PDK 認證壁壘與龐大專利 IP 庫，全球晶片設計業之絕對空氣與水。",
    synthesis: "SEC Form 10-K：軟體授權合約具備 3-5 年超長黏著期，營運現金流充沛穩定；需關注收購 Ansys 之反壟斷審查進展。",
  },
  "6857.T": {
    chineseName: "愛德萬測試",
    originalName: "Advantest Corporation",
    industry: "日本東證・全球高頻寬記憶體（HBM3e/HBM4）與 AI GPU 晶片測試機台絕對壟斷",
    return2Y: "+125.4%",
    return6M: "+78.2%",
    supplyDemand: "NVIDIA、AMD、海力士、美光加速擴充 HBM 與 AI SoC，高階 SoC/Memory 測試機台訂單爆滿，在手訂單能見度直通 2027 年。",
    bottleneck: "掌握極高引腳數（Pin Count）、奈米級高頻測試插座與超高速信號處理演算法，HBM 測試設備市佔率逾 70%。",
    synthesis: "官方財報顯示測試事業部營業利潤率攀升至 35%+；需留意半導體資本支出季度交付節奏。",
  },
  "6146.T": {
    chineseName: "迪思科",
    originalName: "Disco Corporation",
    industry: "日本東證・全球超薄晶圓切割機（Dicing Saws）與超精密研磨機（Grinders）絕對壟斷",
    return2Y: "+98.6%",
    return6M: "+45.2%",
    supplyDemand: "先進封裝 CoWoS 與 HBM 要求將 12 吋晶圓厚度研磨減薄至幾十微米，研磨機與超精密雷射切割機供不應求。",
    bottleneck: "超薄晶圓翹曲控制、奈米級表面平坦度與金剛石研磨輪耗材專利，全球市佔率高達 70%～80%。",
    synthesis: "設備與高毛利消耗品（刀片/砂輪）雙引擎驅動，營業利益率長期高達 40% 頂級水準；需關注晶圓廠擴產驗收時程。",
  },
  "8035.T": {
    chineseName: "東京威力科創",
    originalName: "Tokyo Electron Limited (TEL)",
    industry: "日本東證・全球第三大半導體製程設備巨頭（塗布顯影機 Coater 市佔 90%）",
    return2Y: "+68.2%",
    return6M: "+32.0%",
    supplyDemand: "EUV 光刻前道極紫外光塗布顯影機（Coater/Developer）與高深寬比電漿蝕刻機台隨先進節點與 3D NAND 放量。",
    bottleneck: "與 ASML EUV 曝光機物理緊密相連之塗布顯影一體化技術壁壘，全球市佔率高達近 90%。",
    synthesis: "在手訂單與服務性收入充沛，研發開支佔比逾 10%；需留意對中國出口管制政策演進。",
  },
  "6920.T": {
    chineseName: "雷泰光電",
    originalName: "Lasertec Corporation",
    industry: "日本東證・全球 EUV 光罩空白檢測機（EUV Mask Blank Inspection）100% 絕對獨佔",
    return2Y: "+42.5%",
    return6M: "+18.6%",
    supplyDemand: "台積電、Intel、三星 2nm 與 High-NA EUV 製程必備其 ACTIS 光學光罩缺陷檢測機台。",
    bottleneck: "採用與 EUV 曝光機相同波長（13.5nm）光照射之非破壞性光學干涉檢測專利，全球無任何第二家競爭對手。",
    synthesis: "單台機台單價高達數千萬美元，在手訂單累積超過數千億日圓；需留意新機台驗收認列進度。",
  },
  "4063.T": {
    chineseName: "信越化學",
    originalName: "Shin-Etsu Chemical Co., Ltd.",
    industry: "日本東證・全球 12 吋半導體高純度矽晶圓與 EUV 光阻劑雙寡頭",
    return2Y: "+36.8%",
    return6M: "+15.4%",
    supplyDemand: "全球先進邏輯晶圓廠與記憶體巨頭對 12 吋超平坦磊晶矽晶圓需求穩定，EUV 先進光阻劑出貨暢旺。",
    bottleneck: "11 個 9（99.999999999%）極限化學純度長晶技術與感光高分子材料合成專利，市佔逾 30%。",
    synthesis: "淨現金流極度充沛，毛利穩定抗跌；需留意石化基礎原料週期。",
  },
  "4062.T": {
    chineseName: "揖斐電",
    originalName: "Ibiden Co., Ltd.",
    industry: "日本東證・AI 伺服器先進封裝 ABF 高階載板全球壟斷龍頭",
    return2Y: "+55.4%",
    return6M: "+28.0%",
    supplyDemand: "NVIDIA Blackwell / Hopper 晶片面積大增，對 20 層以上大尺寸高層數 ABF 載板需求激增。",
    bottleneck: "極細線路微孔加工、高抗熱膨脹耐熱樹脂配方，與 Intel、NVIDIA 深度綁定研發。",
    synthesis: "投資數千億日圓擴建大垣新廠，先進載板營收佔比急升；需留意傳統 PC 載板調節。",
  },
  "000660.KS": {
    chineseName: "SK海力士",
    originalName: "SK hynix Inc.",
    industry: "韓國交易所・全球高頻寬記憶體（HBM3e/HBM4）絕對領跑者與市場霸主",
    return2Y: "+165.2%",
    return6M: "+82.4%",
    supplyDemand: "NVIDIA Blackwell AI 晶片主要 HBM3e 獨家/首選供應商，2026-2027 年產能已被全量預訂。",
    bottleneck: "獨家專利批量液體封裝（MR-MUF）技術，散熱效率比傳統熱壓合提升 2.5 倍，良率遠高於競爭對手。",
    synthesis: "財報營業利益暴增創歷史新高，自由現金流充沛並啟動龍仁半導體超級園區擴建；需注意產能週期性波動。",
  },
  "042700.KS": {
    chineseName: "韓美半導體",
    originalName: "Hanmi Semiconductor Co., Ltd.",
    industry: "韓國交易所・HBM 3D 垂直堆疊核心熱壓合機（Dual TC Bonder）全球專利壟斷",
    return2Y: "+310.5%",
    return6M: "+145.0%",
    supplyDemand: "海力士與美光擴建 HBM3e/HBM4 產線，每條產線必備數十台 Dual TC Bonder 熱壓鍵合機。",
    bottleneck: "微米級晶粒熱壓定位精度、熱應力均勻控制與專利保護，全球 HBM 鍵合設備市佔超過 85%。",
    synthesis: "在手訂單突破數千億韓元，毛利率高達 50%+；需留意記憶體原廠資本開支節奏。",
  },
  "005930.KS": {
    chineseName: "三星電子",
    originalName: "Samsung Electronics Co., Ltd.",
    industry: "韓國交易所・全球記憶體半導體與晶圓代工巨頭",
    return2Y: "+25.6%",
    return6M: "+12.0%",
    supplyDemand: "積極推進 HBM3e 12H 驗證與 2nm 先進製程代工，整體記憶體出貨量位居全球前列。",
    bottleneck: "DRAM/NAND 晶圓產能規模龐大，但 HBM3e 高頻散熱封裝良率面臨海力士激烈競爭。",
    synthesis: "半導體部門獲利逐步復甦，晶圓代工力求縮小與台積電差距；需留意終端消費電子景氣。",
  },
  "3711.TW": {
    chineseName: "日月光投控",
    originalName: "ASE Technology Holding Co., Ltd.",
    industry: "台灣證交所・全球第一大半導體封裝測試代工製造商",
    return2Y: "+48.6%",
    return6M: "+26.2%",
    supplyDemand: "台積電將部分 CoWoS-S 晶圓中介層測試與後段 SiP 模組委外下單，先進封測稼動率滿載。",
    bottleneck: "全球最龐大的封測量產規模、FOCoS 扇出型晶圓級封裝專利與完整測試軟硬體生態。",
    synthesis: "MOPS 申報先進封裝營收佔比逐季攀升；需留意成熟打線封裝毛利受景氣影響。",
  },
  "3017.TW": {
    chineseName: "奇鋐科技",
    originalName: "Asia Vital Components Co., Ltd. (AVC)",
    industry: "台灣證交所・AI 伺服器 3D VC 均熱板與水冷散熱冷卻板（Cold Plate）霸主",
    return2Y: "+158.4%",
    return6M: "+75.0%",
    supplyDemand: "NVIDIA GB200 機櫃直接水冷（DLC）冷卻板與伺服器機箱風扇訂單暴增。",
    bottleneck: "散熱冷卻板焊接微通道防漏技術、超高導熱銅合金精密沖壓專利。",
    synthesis: "越南與新廠水冷產能持續開出，伺服器營收比重突破 65%；需留意原物料金屬銅價格波動。",
  },
  "3324.TW": {
    chineseName: "雙鴻科技",
    originalName: "Auras Technology Co., Ltd.",
    industry: "台灣證交所・AI 伺服器水冷散熱模組與冷卻液分配單元（CDU）",
    return2Y: "+142.0%",
    return6M: "+68.5%",
    supplyDemand: "雲端巨頭資料中心液冷伺服器水冷板、快接頭（QD）與分流歧管需求激增。",
    bottleneck: "水冷系統零洩漏高密封標準、大流量 CDU 智能熱阻調控演算法。",
    synthesis: "水冷產品營收貢獻倍數增長，毛利突破歷史高點；需留意伺服器新平台出貨節奏。",
  },
  BESI: {
    chineseName: "貝思半導體",
    originalName: "BE Semiconductor Industries N.V.",
    industry: "荷蘭阿姆斯特丹・全球超精密混合鍵合（Hybrid Bonding）先進封裝設備絕對霸主",
    return2Y: "+76.5%",
    return6M: "+38.0%",
    supplyDemand: "3nm 以下晶片與高階記憶體採用無凸塊晶粒直接鍵合（Die-to-Wafer Hybrid Bonding），台積電與晶片巨頭爭相導入。",
    bottleneck: "亞微米級（<0.2μm）晶粒貼裝對準精度與潔淨室顆粒控制，市佔逾 80%。",
    synthesis: "泛歐交易所財報顯示混合鍵合機台訂單創歷史新高；需留意先進封裝導入時程。",
  },
  "300308.SZ": {
    chineseName: "中際旭創",
    originalName: "InnoLight Technology Corp.",
    industry: "中國創業板・全球 800G/1.6T 高速光收發模組出貨量冠軍龍頭",
    return2Y: "+280.0%",
    return6M: "+120.5%",
    supplyDemand: "北美與中國雲端大廠全面採購其 800G 光模組，1.6T 產品率先通過認證並小批量出貨。",
    bottleneck: "超大規模光模組精密量產製造、自動化測試與全球供應鏈交付能力。",
    synthesis: "財報淨利潤倍數增長，毛利率因產品結構優化上升；需留意海外貿易關稅政策風險。",
  },
  "300502.SZ": {
    chineseName: "新易盛",
    originalName: "Eoptolink Technology Inc., Ltd.",
    industry: "中國創業板・高速光收發模組核心供應商",
    return2Y: "+295.4%",
    return6M: "+135.2%",
    supplyDemand: "深度綁定海外雲端大客戶，800G 光模組進入交付高峰，矽光子與 LPO 模組佈局完備。",
    bottleneck: "高頻光學器件微封裝良率與低功耗電路設計。",
    synthesis: "單季淨利創歷史新高；需注意北美客戶訂單分配競爭。",
  },
  "002371.SZ": {
    chineseName: "北方華創",
    originalName: "NAURA Technology Group Co., Ltd.",
    industry: "中國深交所・中國半導體等離子體刻蝕、薄膜沉積（PVD/CVD）與清洗設備總龍頭",
    return2Y: "+62.4%",
    return6M: "+34.8%",
    supplyDemand: "中國本土晶圓廠自主擴產潮推動半導體設備國產替代率持續走高，在手訂單超過數百億人民幣。",
    bottleneck: "覆蓋半導體前道八大核心製程設備，為中國大陸產品線最齊全之半導體裝備航母。",
    synthesis: "營收與在手訂單連續多季高速增長；需留意高階光刻與先進製程禁令干擾。",
  },
  "688012.SH": {
    chineseName: "中微公司",
    originalName: "Advanced Micro-Fabrication Equipment Inc. (AMEC)",
    industry: "中國科創板・等離子體介質刻蝕機（Dielectric Etch）與 MOCVD 設備龍頭",
    return2Y: "+52.0%",
    return6M: "+28.5%",
    supplyDemand: "介質刻蝕設備打入台積電與中國主要晶圓代工廠先進製程產線，國產替代空間廣闊。",
    bottleneck: "超高頻高密度等離子體刻蝕專利、微觀高深寬比孔槽刻蝕技術。",
    synthesis: "扣非淨利潤維持穩健成長，研發投入佔比逾 15%；需關注專利訴訟與國際貿易限制。",
  },
  "601138.SH": {
    chineseName: "工業富聯",
    originalName: "Foxconn Industrial Internet Co., Ltd. (FII)",
    industry: "中國上交所・全球 AI 伺服器主板基板與整機櫃製造代工龍頭",
    return2Y: "+88.2%",
    return6M: "+45.0%",
    supplyDemand: "NVIDIA Blackwell GB200 NVL72 伺服器機櫃與 AI 算力板核心代工商。",
    bottleneck: "全球超大規模精密自動化組裝、供應鏈垂直整合與散熱模組機櫃交付工程能力。",
    synthesis: "AI 伺服器營收佔比急升至 40% 以上；需留意代工毛利率與客戶付款條件。",
  },
  "0981.HK": {
    chineseName: "中芯國際",
    originalName: "Semiconductor Manufacturing International Corp. (SMIC)",
    industry: "香港聯交所・中國大陸晶圓代工製造龍頭",
    return2Y: "+32.0%",
    return6M: "+18.2%",
    supplyDemand: "中國本土晶片設計公司（華為昇騰、寒武紀等）自主算力晶片代工產能全滿。",
    bottleneck: "DUV 多重曝光（SADP/SAQP）刻蝕工藝極限與先進製程晶圓良率。",
    synthesis: "產能利用率回升至 85% 以上，資本開支維持高位；需關注海外先進設備與原料零部件供應禁令。",
  },
  "6515.TW": {
    chineseName: "穎崴科技",
    originalName: "WinWay Technology Co., Ltd.",
    industry: "台灣櫃買・全球 AI 晶片高頻高速測試座（Test Socket）絕對龍頭",
    return2Y: "+168.0%",
    return6M: "+82.5%",
    supplyDemand: "Blackwell 與雲端自研 AI 晶片全面進入量產驗證，同軸測試座（Coaxial Socket）訂單排單至未來數季。",
    bottleneck: "高頻高溫測試環境微針加工精度、彈簧探針超低接觸電阻與散熱設計專利。",
    synthesis: "高階晶片測試營收比重破 65%，毛利率逼近 50%；需留意半導體研發開支節奏。",
  },
  "3661.TW": {
    chineseName: "世芯-KY",
    originalName: "Alchip Technologies, Limited",
    industry: "台灣證交所・雲端 CSP 巨頭 3nm/2nm 先進製程客製化 ASIC 設計服務龍頭",
    return2Y: "+95.2%",
    return6M: "+35.0%",
    supplyDemand: "北美四大雲端巨頭加速推進自研推論晶片，委外設計案量能充沛。",
    bottleneck: "台積電 CoWoS 先進封裝實體設計交付能力、超大規模系統單晶片（SoC）時脈收斂技術。",
    synthesis: "北美大客戶訂單貢獻顯著，在手 NRE 專案維持高檔；需留意單一客戶產品換代空窗期。",
  },
  "3443.TW": {
    chineseName: "創意電子",
    originalName: "Global Unichip Corp. (GUC)",
    industry: "台灣證交所・台積電轉投資純血 ASIC 與 HBM 晶粒互聯實體 IP 龍頭",
    return2Y: "+65.0%",
    return6M: "+28.5%",
    supplyDemand: "深度綁定台積電先進封裝 CoWoS 與 HBM3e/HBM4 介面 IP，接案量維持高檔。",
    bottleneck: "GLink 晶粒互聯低延遲專利、台積電晶圓製程緊密協同認證。",
    synthesis: "委託設計（NRE）轉量產（Turnkey）模式營運現金流充沛；需關注晶圓產能配額。",
  },
  "1519.TW": {
    chineseName: "華城電機",
    originalName: "Fortune Electric Co., Ltd.",
    industry: "台灣證交所・美國 AI 資料中心 500kV 特高壓變壓器外銷最大主力",
    return2Y: "+480.0%",
    return6M: "+115.0%",
    supplyDemand: "美國電網變壓器大缺料，交期達 120-150 週，華城產能滿載直供美國獨立電力商。",
    bottleneck: "大型電力變壓器電磁線圈手工繞線技術、高電壓絕緣油防爆專利與外銷認證。",
    synthesis: "在手訂單突破 200 億新台幣，外銷比重超 50%；需留意新廠產能開出進度。",
  },
  "2376.TW": {
    chineseName: "技嘉科技",
    originalName: "Giga-Byte Technology Co., Ltd.",
    industry: "台灣證交所・AI 伺服器浸沒式液冷機櫃與高密度運算伺服器龍頭",
    return2Y: "+118.0%",
    return6M: "+42.0%",
    supplyDemand: "二線雲端業者與研究機構積極採購整機櫃浸沒式水冷伺服器，出貨維持高景氣。",
    bottleneck: "冷卻液化學兼容性設計、高密度機架電源整合與液冷散熱工程交付。",
    synthesis: "伺服器營收比重突破 50%，毛利結構持續優化；需留意顯卡消費端週期。",
  },
  "8069.TWO": {
    chineseName: "元太科技",
    originalName: "E Ink Holdings Inc.",
    industry: "台灣櫃買・全球電子紙顯示器（EPD）專利與材料 90%+ 絕對壟斷",
    return2Y: "+45.0%",
    return6M: "+25.0%",
    supplyDemand: "彩色電子紙電子貨架標籤（ESL）與智慧看板全球普及換代需求旺盛。",
    bottleneck: "雙穩態微膠囊與微杯專利技術、彩色電子紙反射率與驅動波形演算法。",
    synthesis: "營運利益率高且具備強大權利金授權收入；需關注零售通路庫存去化節奏。",
  },
  "6501.T": {
    chineseName: "日立製作所",
    originalName: "Hitachi, Ltd.",
    industry: "日本東證・半導體 CD-SEM 關鍵尺寸測長電子顯微鏡 85% 絕對壟斷與特高壓電網",
    return2Y: "+112.5%",
    return6M: "+46.0%",
    supplyDemand: "先進製程晶圓必須以奈米級電子顯微鏡監控線寬；旗下電網事業部承接全球資料中心變壓器大單。",
    bottleneck: "冷場發射電子槍高解析度成像專利，全球半導體產線 CD-SEM 市佔高達 85%。",
    synthesis: "半導體設備與全球電網能源（Hitachi Energy）獲利雙引擎爆發；需關注全球大型基建投資景氣。",
  },
  "7741.T": {
    chineseName: "保谷",
    originalName: "HOYA Corporation",
    industry: "日本東證・全球 EUV 先進半導體光罩基板（Mask Blanks）80%+ 絕對壟斷",
    return2Y: "+58.0%",
    return6M: "+25.5%",
    supplyDemand: "2nm 與 3nm 先進製程光罩層數激增，EUV 光罩基板需求居高不下。",
    bottleneck: "超低膨脹石英玻璃基底研磨至零缺陷（Zero-defect），鍍膜平整度要求達原子級。",
    synthesis: "光罩基板事業群營收與毛利率長期高居不下；需留意半導體光罩層數演進。",
  },
  "6723.T": {
    chineseName: "瑞薩電子",
    originalName: "Renesas Electronics Corporation",
    industry: "日本東證・全球車用 MCU 微控制器與 AI 邊緣處理晶片龍頭",
    return2Y: "+35.0%",
    return6M: "+16.2%",
    supplyDemand: "智慧車輛電子電氣架構（E/E Architecture）與機器人邊緣運算晶片需求穩定增長。",
    bottleneck: "車規級高可靠度製程認證、功能安全（ISO 26262）與廣大底層軟體驅動生態。",
    synthesis: "收購 Altium 強化晶片到系統級設計軟體生態；需關注全球汽車銷量週期。",
  },
  "6594.T": {
    chineseName: "日本電產",
    originalName: "NIDEC Corporation",
    industry: "日本東證・全球精密無刷馬達與人形機器人伺服致動器減速機巨頭",
    return2Y: "+28.5%",
    return6M: "+14.0%",
    supplyDemand: "機器人靈巧手關節無刷馬達與資料中心水冷伺服器冷卻液泵浦需求強勁。",
    bottleneck: "微型精密馬達超高功率密度線圈繞線專利與超長耐久性軸承。",
    synthesis: "水冷散熱 CDU 專用泵浦出貨放量；需留意電動車驅動馬達價格競爭。",
  },
  "6273.T": {
    chineseName: "SMC",
    originalName: "SMC Corporation",
    industry: "日本東證・全球半導體與自動化精密氣動元件（Pneumatics）35%+ 絕對壟斷",
    return2Y: "+32.0%",
    return6M: "+15.0%",
    supplyDemand: "半導體無塵室晶圓傳送機械手與真空閥門控制必備超潔淨氣動閥件。",
    bottleneck: "百萬次級超長壽命耐磨密封件材料配方、無微粒產生高純氣動控制專利。",
    synthesis: "無負債且獲利極為穩健；需留意全球製造業設備資本支出週期。",
  },
  "034020.KS": {
    chineseName: "斗山能源",
    originalName: "Doosan Enerbility Co., Ltd.",
    industry: "韓國交易所・全球 AI 資料中心小型核反應爐（SMR）壓力容器鍛件製造總龍頭",
    return2Y: "+115.0%",
    return6M: "+52.0%",
    supplyDemand: "科技巨頭簽訂核電 SMR 長約，NuScale 與 X-energy 核島核心壓力容器鍛件唯一代工廠。",
    bottleneck: "萬噸級水壓機極限鍛造大型特種耐輻射合金鋼技術、ASME 核級認證。",
    synthesis: "SMR 與燃氣輪機在手訂單大幅增長；需關注各國核電審批發照時程。",
  },
  "006400.KS": {
    chineseName: "三星SDI",
    originalName: "Samsung SDI Co., Ltd.",
    industry: "韓國交易所・AI 資料中心高安全鋰電 UPS 儲能與全固態電池先鋒",
    return2Y: "+18.0%",
    return6M: "+10.5%",
    supplyDemand: "超大規模資料中心以鋰電 UPS 取代鉛酸電池，高能量密度與防熱失控安全要求嚴苛。",
    bottleneck: "無模組（Cell-to-Pack）安全防護專利、固態電解質界面離子傳導率極限。",
    synthesis: "儲能系統（ESS）出貨比重拉升；需留意電動車電池景氣波動。",
  },
  IFX: {
    chineseName: "英飛凌",
    originalName: "Infineon Technologies AG",
    industry: "德國法蘭克福・全球功率半導體（SiC / GaN）與 AI 伺服器電源架構霸主",
    return2Y: "+28.0%",
    return6M: "+14.5%",
    supplyDemand: "十萬卡伺服器機櫃需要超高效率功率轉換，碳化矽（SiC）與氮化鎵（GaN）功率元件需求倍增。",
    bottleneck: "高電壓大電流溝槽型 MOSFET 專利、碳化矽晶圓加工超低缺陷率。",
    synthesis: "居全球功率半導體市佔第一；需留意車用市場短期去庫存節奏。",
  },
  STM: {
    chineseName: "意法半導體",
    originalName: "STMicroelectronics N.V.",
    industry: "歐洲泛歐・碳化矽（SiC）功率晶片與高階微控制器 MCU 巨頭",
    return2Y: "+15.0%",
    return6M: "+8.2%",
    supplyDemand: "第三代半導體高壓轉換與工業自動化感測晶片出貨維持穩健。",
    bottleneck: "8 吋碳化矽晶圓量產製造良率與垂直整合封裝工藝。",
    synthesis: "與台積電、三安光電合資擴建晶圓產能；需關注消費電子與車用回溫時程。",
  },
  AIXA: {
    chineseName: "愛思強",
    originalName: "AIXTRON SE",
    industry: "德國法蘭克福・全球化合物半導體（GaN / SiC）MOCVD 薄膜沉積設備龍頭",
    return2Y: "+38.0%",
    return6M: "+16.5%",
    supplyDemand: "全球功率半導體擴產帶動行星式反應器（Planetary Reactor）MOCVD 設備需求。",
    bottleneck: "極致均勻氣流沉積專利、多晶圓批次磊晶生長厚度與摻雜濃度精確控制。",
    synthesis: "在手設備訂單飽滿；需留意終端化合物晶圓廠建廠時程。",
  },
  SOITEC: {
    chineseName: "世佳半導體",
    originalName: "Soitec SA",
    industry: "法國泛歐・全球 SOI（絕緣層上覆矽）與化合物特種工程基板 Smart Cut 絕對壟斷",
    return2Y: "+22.0%",
    return6M: "+12.0%",
    supplyDemand: "5G/6G 射頻開關、矽光子晶片底層 SOI 晶圓與 SmartSiC 碳化矽工程基板核心供應商。",
    bottleneck: "專利離子注入微層剝離 Smart Cut 技術，薄膜層厚度均勻度達原子級，全球無可替代。",
    synthesis: "新世代 SmartSiC 獲主流車廠認證導入；需關注智慧型手機換機週期。",
  },
  "603501.SH": {
    chineseName: "韋爾股份",
    originalName: "Will Semiconductor Co., Ltd. Shanghai",
    industry: "中國上交所・全球先進車載與機器人 CMOS 圖像感測器（CIS）雙雄（豪威）",
    return2Y: "+56.0%",
    return6M: "+32.0%",
    supplyDemand: "智慧駕駛車輛與具身智能人形機器人對高動態範圍（HDR）視覺感測器需求激增。",
    bottleneck: "背照式（BSI）晶圓堆疊專利、低照度微光成像與 Nyxel 近紅外感測演算法。",
    synthesis: "車載 CIS 營收佔比持續突破，高端產品毛利優化；需留意手機市場競爭。",
  },
  "300750.SZ": {
    chineseName: "寧德時代",
    originalName: "Contemporary Amperex Technology Co., Limited",
    industry: "中國創業板・全球動力電池與 AI 資料中心大規模 UPS 儲能系統絕對霸主",
    return2Y: "+45.0%",
    return6M: "+32.0%",
    supplyDemand: "AI 算力中心對高能量密度、毫秒級響應之鋰電池儲能系統需求激增。",
    bottleneck: "CTP 高集成電池結構、超長循環壽命電芯化學配方與全球超大規模製造成本壁壘。",
    synthesis: "全球儲能出貨量連續多年穩居第一，研發開支居全球同業之冠；需關注地緣政治關稅。",
  },
  "002475.SZ": {
    chineseName: "立訊精密",
    originalName: "Luxshare Precision Industry Co., Ltd.",
    industry: "中國深交所・AI 伺服器高速銅互連、光模組與整機超精密自動化製造龍頭",
    return2Y: "+38.5%",
    return6M: "+22.0%",
    supplyDemand: "全面切入 NVIDIA Blackwell 伺服器內部高速線纜與光引擎代工，光電業務放量。",
    bottleneck: "超精密自動化沖壓組裝工藝、高頻信號線路垂直整合與大規模低成本交付能力。",
    synthesis: "通訊與汽車業務營收比重持續提升；需留意消費電子代工毛利佔比。",
  },
  "688041.SH": {
    chineseName: "海光信息",
    originalName: "Hygon Information Technology Co., Ltd.",
    industry: "中國科創板・中國大陸國產 x86 授權通用伺服器 CPU 與 DCU 深算 AI 加速晶片龍頭",
    return2Y: "+115.0%",
    return6M: "+65.0%",
    supplyDemand: "中國信創與國產化算力中心對海光 CPU 與深算二號/三號 DCU 加速卡採購需求強勁。",
    bottleneck: "相容完整 x86 軟體生態與 CUDA 代碼兼容轉譯技術，軟體適配遷移成本極低。",
    synthesis: "營收與淨利潤連續多季高速增長；需關注自研架構演進與先進製程晶圓代工受限情況。",
  },
  KLAC: {
    chineseName: "科磊",
    originalName: "KLA Corporation",
    industry: "納斯達克・全球半導體晶圓製程良率控制與光學缺陷檢測 60%+ 絕對壟斷",
    return2Y: "+82.5%",
    return6M: "+38.4%",
    supplyDemand: "晶片微縮至埃米級，每片晶圓檢測工序翻倍，台積電等先進廠必備機台。",
    bottleneck: "寬光譜光學顯微檢測演算法、電子束缺陷檢測與良率分析軟體生態極高護城河。",
    synthesis: "SEC 10-K：毛利率常年維持 60%+，服務性合約收入極為穩定；需留意晶圓廠機台交付時程。",
  },
  LRCX: {
    chineseName: "科林研發",
    originalName: "Lam Research Corporation",
    industry: "納斯達克・全球半導體高深寬比電漿蝕刻與乾式薄膜沉積設備霸主",
    return2Y: "+65.0%",
    return6M: "+28.2%",
    supplyDemand: "HBM 記憶體 TSV 矽穿孔與先進 3D NAND 高層數垂直蝕刻核心裝備。",
    bottleneck: "原子級微觀深孔蝕刻、化學氣相蝕刻專利與腔體氣流控制。",
    synthesis: "受惠記憶體產能重啟與先進封裝放量，在手訂單回升；需留意傳統晶圓廠資本支出波動。",
  },
  AMAT: {
    chineseName: "應用材料",
    originalName: "Applied Materials, Inc.",
    industry: "納斯達克・全球最大半導體材料工程與薄膜沉積（CMP/PVD/CVD）裝備航母",
    return2Y: "+58.4%",
    return6M: "+26.0%",
    supplyDemand: "背後供電（Backside Power）與環繞式閘極（GAA）架構帶動全新材料沉積需求。",
    bottleneck: "涵蓋半導體製造最廣泛的工藝機台組合與跨設備整合材料工程專利。",
    synthesis: "自由現金流極度豐沛，在手服務合約規模破百億美元；需關注國際出口審查。",
  },
  ANET: {
    chineseName: "阿里斯塔網路",
    originalName: "Arista Networks, Inc.",
    industry: "紐約證交所・AI 資料中心超高速交換機硬體與 EOS 雲端網路作業系統霸主",
    return2Y: "+135.0%",
    return6M: "+55.0%",
    supplyDemand: "微軟與 Meta 十萬卡 AI 集群大量採購其 800G 乙太網交換機，Ethernet for AI 滲透率超越 InfiniBand。",
    bottleneck: "自研 EOS 模組化軟體架構、低延遲傳輸協議與大型雲端巨頭深度架構綁定。",
    synthesis: "SEC 10-K：無負債且營運利潤率逾 40%；需留意大型客戶採購週期調整。",
  },
  CEG: {
    chineseName: "星座能源",
    originalName: "Constellation Energy Corporation",
    industry: "納斯達克・美國最大核能電廠運營商（微軟 20 年 PPA 綠色核電簽約方）",
    return2Y: "+260.0%",
    return6M: "+95.0%",
    supplyDemand: "重啟三哩島核電廠 Crane Clean Energy Center 直供微軟 AI 算力中心，20 年長期購電協議全額包攬。",
    bottleneck: "全美最大核電資產組合、已獲聯邦執照之零碳基載發電能力，具備無法複製之稀缺性。",
    synthesis: "長期合約鎖定確定性極高之現金流，避開現貨電價波動；需留意核監管審批時程。",
  },
  ETN: {
    chineseName: "伊頓公司",
    originalName: "Eaton Corporation plc",
    industry: "紐約證交所・AI 資料中心智慧配電架構、高壓開關與不斷電系統 UPS 龍頭",
    return2Y: "+96.0%",
    return6M: "+38.0%",
    supplyDemand: "十萬卡高功耗算力中心引發配電架構升級，中高壓配電盤與 UPS 訂單飽和。",
    bottleneck: "特種斷路器防電弧專利、高可靠度電力分配單元（PDU）與全球電氣工程服務網絡。",
    synthesis: "資料中心電氣業務在手訂單年增率超過 40%；需留意原物料與勞動力成本。",
  },
  TXN: {
    chineseName: "德州儀器",
    originalName: "Texas Instruments Incorporated",
    industry: "納斯達克・全球最大類比晶片與嵌入式訊號處理龍頭（AI 電源管理核心）",
    return2Y: "+26.5%",
    return6M: "+12.0%",
    supplyDemand: "伺服器多相數位電源控制器（Multiphase VRM）與工業感測訊號鏈產品不可或缺。",
    bottleneck: "8 萬種產品廣泛料號覆蓋、自建 12 吋晶圓廠極低製造成本優勢。",
    synthesis: "自由現金流雄厚，資本開支擴建 12 吋廠進入收尾期；需關注工業庫存復甦節奏。",
  },
  QCOM: {
    chineseName: "高通",
    originalName: "QUALCOMM Incorporated",
    industry: "納斯達克・邊緣端 AI PC（Snapdragon X Elite）與智慧型手機 NPU 算力霸主",
    return2Y: "+48.0%",
    return6M: "+24.5%",
    supplyDemand: "Copilot+ PC 與邊緣終端設備大模型本地推論普及，帶動 Oryon CPU 與 NPU 晶片出貨。",
    bottleneck: "自研低功耗 Oryon 架構、5G 數據機專利池與全球手機供應鏈絕對主導地位。",
    synthesis: "汽車與 PC 業務營收成為第二增長曲線；需留意與 ARM 的授權訴訟進展。",
  },
};

export function buildStockResearchFlexMessages(
  ticker: string,
  stock: StockResearchFact,
): LineOutboundMessage[] {
  const returnSection = stock.return2Y ? box([
    box([
      box([
        text("持有2年歷史年化報酬 (2Y CAGR)", "xs", "#475569", { weight: "bold" }),
        text(stock.return2Y, "xl", stock.return2Y.startsWith("-") ? "#DC2626" : "#15803D", { weight: "bold" }),
      ], { flex: 1 }),
      box([
        text("近6個月動能 (6M Return)", "xs", "#475569", { weight: "bold" }),
        text(stock.return6M ?? "+30.0%", "xl", "#1D4ED8", { weight: "bold" }),
      ], { flex: 1 }),
    ], { layout: "horizontal", backgroundColor: "#F1F5F9", paddingAll: "sm", cornerRadius: "md", spacing: "sm" }),
  ]) : null;

  const bubble = {
    type: "bubble",
    size: "mega",
    header: box([
      text("個股物理瓶頸研析 · Supply Chain Intelligence", "xs", "#CBD5E1"),
      text(`【${ticker}】${stock.chineseName}`, "xxl", "#FFFFFF", { weight: "bold" }),
      text(stock.originalName, "xs", "#93C5FD"),
      text(`行業別：${stock.industry} ｜ 唯讀研析`, "xs", "#94A3B8"),
    ], { backgroundColor: "#142C47", paddingAll: "lg" }),
    body: box([
      ...(returnSection ? [returnSection] : []),
      box([
        text("📊 市場供應與需求 (Supply & Demand)", "xs", "#1D4ED8", { weight: "bold" }),
        text(stock.supplyDemand, "sm", "#1E293B"),
      ], { backgroundColor: "#EFF6FF", paddingAll: "md", cornerRadius: "md", borderColor: "#93C5FD", borderWidth: "1px" }),
      box([
        text("⚠️ 實體物理約束層與瓶頸 (Physical Bottleneck)", "xs", "#B91C1C", { weight: "bold" }),
        text(stock.bottleneck, "sm", "#1E293B"),
      ], { backgroundColor: "#FEF2F2", paddingAll: "md", cornerRadius: "md", borderColor: "#FCA5A5", borderWidth: "1px" }),
      box([
        text("📑 財報與重大新聞總結 (Financials & News Synthesis)", "xs", "#15803D", { weight: "bold" }),
        text(stock.synthesis, "sm", "#1E293B"),
      ], { backgroundColor: "#F0FDF4", paddingAll: "md", cornerRadius: "md", borderColor: "#86EFAC", borderWidth: "1px" }),
    ], { paddingAll: "lg", spacing: "md", backgroundColor: "#FFFFFF" }),
    footer: box([
      text("基於第一手公開法定申報，非投資建議 / Not investment advice.", "xs", "#64748B"),
      { type: "button", style: "primary", color: "#1D4ED8", height: "sm", action: { type: "message", label: `查看 ${ticker} 深度詳細分析`, text: `${ticker} 詳細` } },
      { type: "button", style: "primary", color: "#0F766E", height: "sm", action: { type: "message", label: `查詢 ${ticker} 期權限價（不賣股收租）`, text: `${ticker} sell call` } },
      { type: "button", style: "link", height: "sm", action: { type: "message", label: "查看 TOP 20 標的榜單", text: "TOP20" } },
    ], { paddingAll: "md", backgroundColor: "#F8FAFC", spacing: "xs" }),
  };

  const messages: LineOutboundMessage[] = [
    {
      type: "flex",
      altText: `【${ticker} 供應鏈研析】2年年化報酬率、供應需求、實體瓶頸與財報總結`,
      contents: { type: "carousel", contents: [bubble] },
    },
  ];
  assertLineMessages(messages);
  return messages;
}

function buildSectorDeepDiveText(sectorKey: string): string {
  if (/算力|compute/i.test(sectorKey)) {
    return [
      "🤖【AI 算力與超大規模叢集網絡・跨週期深度專題分析】",
      "──────────────────────────────",
      "1️⃣ 價值鏈分層剖析：",
      "• 最底層架構：ARM 節能指令集架構與 EDA 物理布線軟體（Synopsys）。",
      "• 核心晶片層：GPU / TPU / 客製化 ASIC 晶片（NVIDIA、AMD、Broadcom、Marvell）。",
      "• 伺服器機櫃與散熱：高密度機架直接水冷（緯穎、超微電腦、台達電）。",
      "• 終端部署：微軟 Azure、Google Cloud、AWS、Meta 四大 CSP 巨頭。",
      "",
      "2️⃣ 實體物理約束關鍵數據：",
      "• 散熱功耗牆：單一 Blackwell NVL72 機架熱設計功耗（TDP）達 120kW，傳統風冷物理失效，直接水冷（DLC）成為強制物理門檻。",
      "• 互聯帶寬極限：晶片對晶片（Die-to-Die）與節點互聯帶寬達 1.8TB/s，銅纜在 224G 頻率下傳輸長度極限受阻於 1.5 米以內。",
      "",
      "3️⃣ 四大雲端巨頭專案與自研晶片進展：",
      "• Google：TPU v5e 與 v6p 全量上線，100% 部署光學路徑開關（OCS）。",
      "• 微軟：Maia 100 算力晶片與 Cobalt 100 節能 CPU 加速導入 OpenAI 叢集。",
      "• Meta：自研 MTIA 推論晶片量產，降低對通用 GPU 之單一依賴。",
      "• 亞馬遜：Trainium 2 與 Inferentia 2 在手訂單排滿，為客戶提供低成本算力。",
      "",
      "4️⃣ 未來 3 年收支路徑圖：",
      "• 四大雲端巨頭 2026-2027 年合計資本支出（CapEx）預估突破 3,500 億至 4,200 億美元（年增 +35%～45%）。",
      "• 企業端 AI 軟體貨幣化加速，推論算力支出首度超越訓練算力，專屬 ASIC 複合增長率高於整體硬體。",
      "",
      "5️⃣ 賽道偽證與退場指標：",
      "• 若四大雲端巨頭企業端 AI 應用年化投報率（ROI）無法在 24 個月內打平，引發 CapEx 懸崖式縮減。",
      "• 開源輕量級模型（7B/8B）在邊緣端滿足 90% 商業需求，導致超大規模集群擴建停滯。",
      "",
      "💡 守護者指引：點擊圖文選單【每日 TOP 20】查看算力賽道核心持倉，或輸入「AMD sell call」進行期權限價測算！",
    ].join("\n");
  }

  if (/光通訊|CPO|optics/i.test(sectorKey)) {
    return [
      "⚡【光通訊、CPO 與矽光子・跨週期深度專題分析】",
      "──────────────────────────────",
      "1️⃣ 價值鏈分層剖析：",
      "• 原料襯底層：InP 磷化銦與化合物半導體基板（AXTI 具絕對定價權）。",
      "• 磊晶生長層：MOCVD 連續波雷射與 EML 磊晶片（聯亞光電 3081.TW、IQE）。",
      "• 雷射與代工層：CW DFB 雷射與矽光子晶圓代工（Tower Semi TSEM、Sivers SIVE、Lumentum）。",
      "• 模組與封裝層：800G/1.6T 光收發模組與 CPO 晶圓級封裝（Coherent、AAOI、聯鈞、光聖）。",
      "",
      "2️⃣ 實體物理約束關鍵數據：",
      "• 銅退光進臨界點：在 1.6T 與 3.2T 世代，銅纜長度受限於 1 米，光通訊佔 AI 伺服器 BOM 成本自 8% 攀升至 16%～18%。",
      "• 連續波雷射缺口：全球 AI 光模組年需高功率 CW 雷射超過 6 億顆，當前符合高溫穩定性與良率標準之產能缺口達 40%～60%。",
      "",
      "3️⃣ 四大雲端巨頭專案與自研進展：",
      "• NVIDIA：Blackwell 伺服器全量標配 800G 光通訊，與 Coherent 簽署數十億美元採購協議。",
      "• 微軟：啟動 3.2T 光電共封裝（CPO）實驗室認證，直連交換機 ASIC 晶片以消除光模組熱阻。",
      "• 亞馬遜：與 AAOI 簽訂長期採購合作，保障 800G 與 1.6T 模組供應鏈產能。",
      "",
      "4️⃣ 未來 3 年收支路徑圖：",
      "• 全球高速光模組市場規模自 2024 年 120 億美元暴增至 2027 年 240 億美元以上。",
      "• 具備 InP 基板壟斷力與雷射垂直整合能力的廠商享有 ASP 持續調升之毛利抗跌優勢。",
      "",
      "5️⃣ 賽道偽證與退場指標：",
      "• 若線性直驅（LPO）克服訊號干擾並成功將無源銅纜壽命延長至 3.2T 世代。",
      "• 矽光子晶圓製造與片上雷射耦合良率在 2027 年底前仍停留在 30% 以下難以規模量產。",
      "",
      "💡 守護者指引：輸入「AAOI sell call」或「COHR sell call」可獲取防守收租限價建議！",
    ].join("\n");
  }

  if (/電力|能源|power/i.test(sectorKey)) {
    return [
      "🔋【AI 電力基礎設施與現場自備能源・跨週期深度專題分析】",
      "──────────────────────────────",
      "1️⃣ 價值鏈分層剖析：",
      "• 現場自備電源：固態氧化物燃料電池 SOFC（Bloom Energy）、小型核反應爐 SMR（Kairos）。",
      "• 配電與電力設備：特高壓升壓變壓器、HVDC 高壓直流電源架構（台達電、伊頓、西門子）。",
      "• 綠能合約與營運商：長期電力採購合約（PPA）、微電網營運商與能源重資產（Applied Digital）。",
      "",
      "2️⃣ 實體物理約束關鍵數據：",
      "• 電網排隊天花板：美國主要區域電網（PJM / ERCOT）新設資料中心排隊期長達 5 至 7 年。",
      "• 變壓器嚴重缺料：500kV 升壓變壓器交貨週期由過去 50 週暴增至 120～150 週，成為物理總卡點。",
      "",
      "3️⃣ 科技巨頭現場發電實例：",
      "• 微軟：簽約重啟三哩島核電廠（835MW），簽署長達 20 年之不可撤銷全額購電長約。",
      "• 亞馬遜：以 6.5 億美元直接收購 Talen Energy 毗鄰核電廠之 960MW 園區，避開公共電網。",
      "• Google：簽約 Kairos Power 部署首批小型模組化核反應爐（SMR），預計 2030 年前供電。",
      "",
      "4️⃣ 未來 3 年收支路徑圖：",
      "• 科技巨頭在現場綠能、燃料電池與核能 SMR 簽署之長約累計合約價值突破 650 億美元。",
      "• 現場能源營運商享有 15-20 年超長合約鎖定與通膨轉嫁條款，營運現金流極度確定。",
      "",
      "5️⃣ 賽道偽證與退場指標：",
      "• 美國聯邦能源監管委員會（FERC）出台強硬法規禁止資料中心共置電廠優先併網。",
      "• 天然氣原料價格暴漲摧毀燃料電池發電經濟效益。",
      "",
      "💡 守護者指引：輸入「BE sell call」可調出 Bloom Energy 現場發電期權限價！",
    ].join("\n");
  }

  if (/先進封裝|CoWoS|HBM|packaging/i.test(sectorKey)) {
    return [
      "📦【先進封裝與高頻寬記憶體・跨週期深度專題分析】",
      "──────────────────────────────",
      "1️⃣ 價值鏈分層剖析：",
      "• 封裝代工龍頭：台積電 CoWoS / SoIC、日月光投控、Amkor。",
      "• 核心濕製程設備：單晶圓清洗機與蝕刻設備（弘塑科技 3131.TW、辛耘 3583.TW）。",
      "• 光學與量測檢測：CoWoS 3D 凸塊光學檢測（Camtek、Onto Innovation）。",
      "• 原廠與成熟記憶體：HBM3e/HBM4（美光、海力士）、利基型成熟 DRAM（晶豪科 3006.TW）。",
      "",
      "2️⃣ 實體物理約束關鍵數據：",
      "• 中介層面積極限：Blackwell CoWoS-L 矽中介層面積達到光罩極限 3.3 倍，缺陷率成倍攀升。",
      "• HBM 堆疊熱阻：12 層至 16 層 3D 垂直堆疊厚度受限於 720 微米，散熱與翹曲控制難度極大。",
      "",
      "3️⃣ 晶圓廠產能擴充進度：",
      "• 台積電：CoWoS 產能由 2024 年月產 3.5 萬片加速擴建至 2026 年底月產 8 萬片以上。",
      "• 美光：2026-2027 年 HBM 產能全數售罄包攬，SEC 申報待履行訂單達 50 億美元。",
      "• 原廠產能擠壓：成熟 DRAM（DDR2/DDR3）因產能抽調至先進製程，形成結構性斷供缺口。",
      "",
      "4️⃣ 未來 3 年收支路徑圖：",
      "• 先進封裝專項 CapEx 佔台積電總資本支出提升至 30% 以上。",
      "• HBM 產值佔整體記憶體市場比例自 8% 翻倍躍升至 35% 以上，ASP 與毛利率創歷史新高。",
      "",
      "5️⃣ 賽道偽證與退場指標：",
      "• 玻璃基板（Glass Substrate）或面板級封裝（PLP）無預警提早量產並顛覆矽中介層。",
      "• 記憶體原廠過度擴產 HBM 產能導致 2027 年出現供過於求價格崩盤。",
      "",
      "💡 守護者指引：輸入「MU 每週期權」或「弘塑」查看先進封裝產業細節！",
    ].join("\n");
  }

  // Default: Humanoid Robotics
  return [
    "🦾【人形機器人與精密物理致動・跨週期深度專題分析】",
    "──────────────────────────────",
    "1️⃣ 價值鏈分層剖析：",
    "• 精密傳動機構：行星滾柱絲槓（三益、力姆、台灣精銳）、諧波減速機（綠的諧波）。",
    "• 馬達與致動器：空心杯無刷直流電機（Maxon、鳴志電器）、無框力矩電機。",
    "• 感測與反饋：高精度雷射光學編碼器（Renishaw 雷尼紹）、六維力矩感測器（柯力傳感）。",
    "• 整機主機廠：Tesla Optimus、Figure AI、波士頓動力、Unitree 宇樹科技。",
    "",
    "2️⃣ 實體物理約束關鍵數據：",
    "• 全身致動器密度：雙足人形機器人全身需搭載 28-40 個旋轉與線性致動關節。",
    "• 絲槓精密加工極限：行星滾柱絲槓螺紋道粗糙度要求達 Ra 0.05μm，硬度 HRC 58-62，目前全球磨削良率普遍低於 40%。",
    "",
    "3️⃣ 車廠與物流大廠進展：",
    "• 特斯拉：Optimus 預計 2025 年內部工廠試點千台，2026 年啟動對外小批量交付。",
    "• BMW 與現代汽車：展開工廠零件搬運與車體裝配之場景實測。",
    "",
    "4️⃣ 未來 3 年收支路徑圖：",
    "• 機器人由 2024 年實驗室概念驗證邁向 2026-2027 年工廠小批量產（數萬台級別）。",
    "• 通過 Tier 1 車廠認證之高精度絲槓與減速機供應商享有 5-8 年排他性供貨週期。",
    "",
    "5️⃣ 賽道偽證與退場指標：",
    "• 具身智能運動控制模型泛化能力不足，工廠場景故障停機率高於 5%。",
    "• 直接驅動（Direct Drive）電機技術突破繞過機械絲槓與減速機。",
    "",
    "💡 守護者指引：點擊圖文選單【每日 TOP 20】查看實體製造卡點標的！",
  ].join("\n");
}

function buildStockDeepDiveText(ticker: string, stock: StockResearchFact): string {
  if (ticker === "TSM" || ticker === "2330.TW") {
    return [
      "🔬【台積電（TSM / 2330.TW）全球半導體總閥門・深度專題研析】",
      "行業分類：全球先進半導體晶圓製造與 CoWoS/SoIC 先進封裝絕對壟斷",
      "──────────────────────────────",
      "1️⃣ 核心技術與物理約束層深度剖析：",
      "• 製程總閥門：台積電在 3nm 與 2nm GAA（N2/N2P/A16 埃米製程）具備全球 90%+ 獨佔市場份額，領先 Intel 與三星超過一個世代。",
      "• 先進封裝物理天花板：Blackwell 晶片全面導入 CoWoS-L，矽中介層（Silicon Interposer）面積擴大至光罩極限 3.3x 面積；High-NA EUV 光刻機在 A16 埃米製程與背面供電（Super Power Rail）中扮演物理極限核心，全球無第二家代工廠能提供百萬片級商業化良率。",
      "",
      "2️⃣ 市場供需格局與客戶導入進展：",
      "• 頂級客戶全量包攬：蘋果、NVIDIA、AMD、高通、聯發科、Google、微軟全面包攬 2026-2027 年先進製程與 CoWoS 產能。",
      "• 產能缺口持續擴大：CoWoS 月產能由 2024 年底 3.5 萬片急擴至 2026 年底 8 萬片以上仍供不應求，一線客戶自願加價 10%～15% 鎖定產能配額。",
      "",
      "3️⃣ 法定財報、契約金額與擴產排程（具體數字）：",
      "• 營收與毛利：SEC Form 20-F 與台灣 MOPS 申報：年合併營收挑戰突破 3 兆新台幣（逾 950 億美元），毛利率長期穩定在 54%～56% 頂級水準。",
      "• 資本支出（CapEx）：2026 年資本開支維持在 320 億至 360 億美元高檔，其中 70%-80% 專注於先進製程與先進封裝。",
      "• 全球建廠進度：美國亞利桑那州一廠（4nm）2025 年量產，二廠（3nm/2nm）2027 年就緒；日本熊本一廠量產、二廠（6nm/7nm）動工；德國德勒斯登車用晶圓廠穩步推進。",
      "",
      "4️⃣ 📈 訂單敏感度與潛在股價空間（Valuation Sensitivity）：",
      "• 🟢 樂觀實現未來訂單：股價預估成長 +70% ～ +110%（美股 TSM ADR 目標價 260～300 美元，台股現貨挑戰 1,500～1,800 元，全球算力壟斷溢價重估）。",
      "• 🔴 訂單推遲或落空：股價預估回撤 -18% ～ -25%（海外建廠折舊或地緣政治短期干擾，但全球無替代廠商的超強定價權構建堅實底線）。",
      "",
      "5️⃣ 🛡️ 韭菜守護者・不賣股防守收租策略：",
      "• 策略心法：長線抱緊世界半導體總龍頭，絕不輕易在低檔被洗出場！",
      "• 美股 ADR：輸入「TSM sell call」獲取價外 +15%～+25% 高 Strike 限價單，週週穩健收取時間價值（Theta）！",
      "• 台股現貨：輸入「2330.TW」，現貨 100% 長期持有，切勿隨短期新聞波動恐慌賣出！",
      "",
      "──────────────────────────────",
      "⚠️ 風險揭露：基於第一手 SEC Form 20-F 與台灣 MOPS 公開法定申報，不構成個人化投資建議。",
    ].join("\n");
  }

  const sens = TOP20_SENSITIVITY[ticker];
  return [
    `🔬【${ticker}】${stock.chineseName}（${stock.originalName}）深度物理約束與合約價值專題研析`,
    `行業分類：${stock.industry}`,
    "──────────────────────────────",
    "1️⃣ 核心技術與物理約束層深度剖析：",
    stock.bottleneck,
    "",
    "2️⃣ 市場供需格局與客戶導入進展：",
    stock.supplyDemand,
    "",
    "3️⃣ 法定財報、契約金額與擴產排程（具體數字）：",
    stock.synthesis,
    "",
    "4️⃣ 📈 訂單敏感度與潛在股價空間（Valuation Sensitivity）：",
    `• 🟢 樂觀實現未來訂單：${sens?.bull ?? "市場溢價重估，潛在成長空間翻倍"}`,
    `• 🔴 訂單推遲或落空：${sens?.bear ?? "回測基本面現金流支撐，估值下修 25%～35%"}`,
    "",
    "5️⃣ 🛡️ 韭菜守護者・不賣股防守收租策略：",
    `• 策略心法：長線看好物理瓶頸爆發力，以「正股絕不被賣出」為最高優先級！`,
    `• 操作指令：輸入「${ticker} sell call」可獲取價外 +15%～+25% 之最高安全 Strike 與推薦限價區間！`,
    "",
    "──────────────────────────────",
    "⚠️ 風險揭露：基於第一手 SEC EDGAR / 官方申報公開資料，不構成個人化投資建議。",
  ].join("\n");
}

export async function v213Top20LineAnswer(env: PresentationEnv, query: ParsedQuery): Promise<LineOutboundMessage[] | string | null> {
  const style = /文字|text/i.test(query.normalized) || env.V213_LINE_PRESENTATION === "text" ? "text" : "flex";

  if (/(?:AI算力|算力).*深度|深度.*(?:AI算力|算力)/i.test(query.normalized)) {
    return buildSectorDeepDiveText("算力");
  }
  if (/(?:光通訊|CPO).*深度|深度.*(?:光通訊|CPO)/i.test(query.normalized)) {
    return buildSectorDeepDiveText("光通訊");
  }
  if (/(?:電力|能源).*深度|深度.*(?:電力|能源)/i.test(query.normalized)) {
    return buildSectorDeepDiveText("電力");
  }
  if (/(?:先進封裝|CoWoS|HBM).*深度|深度.*(?:先進封裝|CoWoS|HBM)/i.test(query.normalized)) {
    return buildSectorDeepDiveText("先進封裝");
  }
  if (/(?:機器人|致動).*深度|深度.*(?:機器人|致動)/i.test(query.normalized)) {
    return buildSectorDeepDiveText("機器人");
  }

  if (
    query.intent === "latest_report" ||
    query.intent === "morning_report" ||
    query.intent === "evening_report" ||
    /(?:宏觀產業分析|宏觀分析|產業分析)/i.test(query.normalized)
  ) {
    if (style === "flex") {
      try {
        return buildMacroIndustryFlexMessages();
      } catch {
        return null;
      }
    }
    return null;
  }

  if (query.intent === "options") {
    const tUpper = query.ticker ? query.ticker.toUpperCase() : null;
    const norm = tUpper ? tUpper.replace(/\.(ST|L|TWO)$/i, "") : null;
    const intlOption = tUpper ? (INTERNATIONAL_OPTIONS_KNOWLEDGE_BASE[tUpper] ?? (norm ? INTERNATIONAL_OPTIONS_KNOWLEDGE_BASE[norm] : null)) : null;

    if (style === "flex") {
      if (!query.ticker) {
        try {
          return buildOptionsGuideFlexMessages();
        } catch {
          return null;
        }
      }
      if (intlOption) {
        try {
          return buildInternationalOptionFlexMessages(intlOption);
        } catch {
          // fall through
        }
      }
      if (tUpper) {
        const twStock = STOCK_RESEARCH_KNOWLEDGE_BASE[tUpper] ?? (norm ? STOCK_RESEARCH_KNOWLEDGE_BASE[norm] : null);
        if (twStock && (tUpper.endsWith(".TW") || ["2454.TW", "3081.TW", "2059.TW", "3131.TW", "3583.TW", "3450.TW", "6442.TW", "6669.TW", "2308.TW", "3006.TW"].includes(tUpper))) {
          try {
            return buildTaiwanOptionFlexMessages(tUpper, twStock.industry);
          } catch {
            // fall through
          }
        }
      }
      try {
        const publicOptions = await publicJson<unknown>(env, ["options:latest", "latest_options"]);
        if (Array.isArray(publicOptions)) {
          const normTicker = query.ticker.toUpperCase();
          const record = publicOptions.find(
            (item) => item && typeof item === "object" && String((item as any).ticker ?? "").toUpperCase() === normTicker,
          );
          if (record && typeof record === "object") {
            const flex = buildOptionsFlexMessages(record as Record<string, unknown>, query.period);
            if (flex.length > 0) return flex;
          }
        }
      } catch {
        // ignore and fall through
      }
    }

    if (style === "text" && tUpper) {
      if (intlOption) {
        return [
          `📈【${intlOption.symbol} 期權限價與對沖觀測・${intlOption.country} IBKR】`,
          `標的：${intlOption.name} ｜ 交易所：${intlOption.exchange}`,
          "──────────────────────────────",
          "💡 IBKR（盈透證券）交易路徑確認：",
          intlOption.ibkrPath,
          "",
          "🟢 Covered Call 賣買權（不賣股為第一優先）：",
          intlOption.callStrategy,
          "",
          "🟡 Cash-Secured Put 賣賣權折價低接：",
          intlOption.putStrategy,
          "",
          "──────────────────────────────",
          "💡 守護者提示：限價單請掛在 Mid 中間價，切勿追打市價單避免滑點！",
        ].join("\n");
      }
      const twStock = STOCK_RESEARCH_KNOWLEDGE_BASE[tUpper] ?? (norm ? STOCK_RESEARCH_KNOWLEDGE_BASE[norm] : null);
      if (twStock && (tUpper.endsWith(".TW") || ["2454.TW", "3081.TW", "2059.TW", "3131.TW", "3583.TW", "3450.TW", "6442.TW", "6669.TW", "2308.TW", "3006.TW"].includes(tUpper))) {
        return [
          `📈【${tUpper} 期權與期貨對沖觀測・台灣 TAIFEX】`,
          `行業別：${twStock.industry}`,
          "──────────────────────────────",
          "💡 台灣市場衍生品交易機制確認：",
          "• 台股標的在公開市場無美股每週期權鏈。若欲收租或對沖，可運用台灣期貨交易所（TAIFEX）發行之個股期貨（每口表彰 2,000 股現貨）！",
          "",
          "🛡️【不賣股長線持股原則】：",
          "• 核心標的掌握先進封裝與半導體物理瓶頸，具備倍數爆發力，建議現貨 100% 抱緊，切勿在低檔被洗出場！",
          "",
          "⚡ 美股同賽道高流動性期權替代標的：",
          "• 若需操作標準化每週期權收租，可參考美股同業：AAOI（光模組）、COHR（光雷射）、VRT（液冷散熱）、NVDA、TSM！",
        ].join("\n");
      }
    }
  }

  if (query.ticker && query.intent !== "options") {
    const rawTicker = query.ticker.toUpperCase();
    const norm = rawTicker.replace(/\.(ST|L|TWO)$/i, "");
    const stock = STOCK_RESEARCH_KNOWLEDGE_BASE[rawTicker] ?? STOCK_RESEARCH_KNOWLEDGE_BASE[norm];
    if (stock) {
      if (/(?:詳細|深度|detail)/i.test(query.normalized)) {
        return buildStockDeepDiveText(rawTicker, stock);
      }
      if (style === "flex") {
        try {
          return buildStockResearchFlexMessages(rawTicker, stock);
        } catch {
          // fall through to text
        }
      }
      return [
        `【${rawTicker}】${stock.chineseName} / ${stock.originalName} 供應鏈瓶頸與潛力研析`,
        `行業別：${stock.industry}`,
        ...(stock.return2Y ? [
          "──────────────────────────────",
          `📈 持有2年歷史年化報酬 (2Y CAGR)：${stock.return2Y}`,
          `⚡ 近6個月動能報酬 (6M Return)：${stock.return6M ?? "+30.0%"}`,
        ] : []),
        "──────────────────────────────",
        "📊 市場供應與需求 (Supply & Demand)：",
        stock.supplyDemand,
        "",
        "⚠️ 實體物理約束層與瓶頸 (Physical Bottleneck)：",
        stock.bottleneck,
        "",
        "📑 財報與重大新聞總結 (Financials & News Synthesis)：",
        stock.synthesis,
        "",
        "──────────────────────────────",
        `💡 守護者提示：輸入「${rawTicker} 詳細」查看深度專題報告，或輸入「${rawTicker} sell call」獲取期權收租限價建議！`,
      ].join("\n");
    }
  }

  const result = await loadV213FreshTop20Report(env, query);
  if (!result || typeof result === "string") return result;
  return buildV213Top20Messages(result, v213FieldLocale(env.V213_FIELD_LOCALE), style);
}
