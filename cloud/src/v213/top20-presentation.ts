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
      const block = `\n\n── ${record.rank}/20 ──\n` + v213Top20DisplayValues(record).map((value, i) => `${labels[i]}：${value}`).join("\n");
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
      ], { paddingAll: "lg", spacing: "lg", backgroundColor: "#FFFFFF" }),
      footer: box([
        text(generated, "xs", "#475569"), text(NOTICE, "xs", "#475569"),
        { type: "button", style: "link", height: "sm", action: { type: "message", label: "完整文字版 / Full text", text: "Top20 文字" } },
      ], { paddingAll: "md", backgroundColor: "#F8FAFC" }),
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
      landscape: "全球四大 CSP 巨頭（微軟、Google、Meta、AWS）加速建置十萬卡級超大規模叢集，推論算力需求首度超越訓練。",
      bottleneck: "集群互聯頻寬飽和、交換機散熱功耗牆（Power Wall）、低延遲光電轉換傳輸極限。",
      capex: "2026-2027 年全球四大雲端巨頭合計資本支出（CapEx）預估突破 3,500 億美元（年增 +35%～45%）。",
      revenue: "客製化 ASIC 與光電互聯交換晶片複合成長率（CAGR）高於整體硬體，定價權向實體供應鏈傾斜。",
    },
    {
      title: "光通訊、CPO 與矽光子",
      sub: "Optical Interconnect & Silicon Photonics",
      icon: "⚡",
      landscape: "800G 光模組進入交付高峰，1.6T 加速於 2026H2 放量，3.2T 光電共封裝（CPO）啟動產能鎖定。",
      bottleneck: "InP（磷化銦）高品質基板產能耗盡、連續波（CW）雷射良率與年產能缺口達 40%～60%。",
      capex: "光模組與光引擎採購支出佔整體 AI 機櫃 BOM 比例從過往 8% 攀升至 15%～18%。",
      revenue: "上游基板與磊晶廠獲一線大廠（Lumentum、Coherent、NVIDIA）多年預付款與長約保證，ASP 具抗跌定價權。",
    },
    {
      title: "AI 電力設施與現場發電",
      sub: "On-Site Power & Grid Deficit",
      icon: "🔋",
      landscape: "美國資料中心電網接入等待期長達 4 至 7 年，自備電源（Behind-the-Meter）成為超大規模資料中心落地的唯一解方。",
      bottleneck: "大功率固態氧化物燃料電池（SOFC）、小型模組化核反應爐（SMR）審批，以及升壓變壓器交期長達 120 週。",
      capex: "微軟、Google、亞馬遜簽訂之 15-20 年超長 PPA 電力採購與現場微電網合約累計承諾已逾 650 億美元。",
      revenue: "現場能源服務商享有長達 15 年的不可撤銷合約與通膨轉嫁條款，營運現金流極度確定。",
    },
    {
      title: "先進封裝與高頻寬記憶體",
      sub: "CoWoS & HBM Supercycle",
      icon: "📦",
      landscape: "先進封裝 CoWoS 與 SoIC 產能供不應求，HBM3e/HBM4 產能被晶片巨頭提前包攬至 2027 年底。",
      bottleneck: "三大原廠將產能全面移轉至 HBM 與 DDR5，導致成熟製程 DDR3/DDR2 出現結構性產能真空。",
      capex: "晶圓代工龍頭與記憶體大廠之先進封裝與矽穿孔（TSV）專項 CapEx 佔比提升至 30% 以上。",
      revenue: "具備成熟記憶體現貨產能（如利基型 DRAM）及封測代工廠享有現貨價跳漲與產能溢價利益。",
    },
    {
      title: "人形機器人與物理致動",
      sub: "Humanoid Robotics & Actuation",
      icon: "🦾",
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
      { type: "button", style: "link", height: "sm", action: { type: "message", label: "查看 TOP 20 標的榜單", text: "TOP20" } },
      { type: "button", style: "link", height: "sm", action: { type: "message", label: "最新報告完整文字版", text: "最新報告 文字" } },
    ], { paddingAll: "sm", backgroundColor: "#F8FAFC" }),
  }));

  const messages: LineOutboundMessage[] = [
    {
      type: "flex",
      altText: "【韭菜守護者・最新宏觀產業深度審查報告】AI算力、光通訊、現場發電、先進封裝與機器人五大賽道",
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
        const dist = typeof candidate.distance_from_spot_pct === "number" ? `${candidate.distance_from_spot_pct > 0 ? "+" : ""}${candidate.distance_from_spot_pct.toFixed(1)}%` : "";
        const yields = (candidate.annualized_yield_pct ?? {}) as Record<string, unknown>;
        const midYield = typeof yields.mid === "number" ? `${yields.mid.toFixed(1)}%` : "N/A";
        const bidYield = typeof yields.bid === "number" ? `${yields.bid.toFixed(1)}%` : "N/A";
        const iv = typeof candidate.implied_volatility_pct === "number" ? `${candidate.implied_volatility_pct.toFixed(1)}%` : "N/A";
        const limitBand = typeof candidate.recommended_limit_band === "object" && candidate.recommended_limit_band
          ? `${currency} ${(candidate.recommended_limit_band as any).min?.toFixed(2)} ～ ${(candidate.recommended_limit_band as any).max?.toFixed(2)}`
          : `${currency} ${bid} ～ ${mid}`;

        const tierBadge = isCall
          ? (cIdx === 0 ? "🛡️【不賣股首選・高履約價防守收租】" : "⚡【次選參考・較近價外較高權利金】")
          : "🟡 " + label;

        bodyContents.push(
          box([
            text(tierBadge, "xs", isCall ? (cIdx === 0 ? "#15803D" : "#B45309") : "#B45309", { weight: "bold" }),
            text(`• 履約價 K ${currency} ${strike}${dist ? ` (價外 ${dist})` : ""}`, "sm", "#1E293B", { weight: "bold" }),
            text(`  Bid ${currency} ${bid} ｜ Ask ${currency} ${ask} ｜ Mid ${currency} ${mid}`, "xs", "#475569"),
            box([
              text(`💡 推薦限價區間：${limitBand}`, "xs", isCall ? (cIdx === 0 ? "#15803D" : "#B45309") : "#B45309", { weight: "bold" }),
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

export async function v213Top20LineAnswer(env: PresentationEnv, query: ParsedQuery): Promise<LineOutboundMessage[] | string | null> {
  const style = /文字|text/i.test(query.normalized) || env.V213_LINE_PRESENTATION === "text" ? "text" : "flex";

  if (query.intent === "latest_report" || query.intent === "morning_report" || query.intent === "evening_report") {
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
    if (style === "flex") {
      if (!query.ticker) {
        try {
          return buildOptionsGuideFlexMessages();
        } catch {
          return null;
        }
      }
      try {
        const publicOptions = await publicJson<unknown>(env, ["options:latest", "latest_options"]);
        if (Array.isArray(publicOptions)) {
          const norm = query.ticker.toUpperCase();
          const record = publicOptions.find(
            (item) => item && typeof item === "object" && String((item as any).ticker ?? "").toUpperCase() === norm,
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
  }

  const result = await loadV213FreshTop20Report(env, query);
  if (!result || typeof result === "string") return result;
  return buildV213Top20Messages(result, v213FieldLocale(env.V213_FIELD_LOCALE), style);
}
