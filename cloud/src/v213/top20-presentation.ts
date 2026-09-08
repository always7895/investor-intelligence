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

interface StockResearchFact {
  industry: string;
  supplyDemand: string;
  bottleneck: string;
  synthesis: string;
}

const STOCK_RESEARCH_KNOWLEDGE_BASE: Record<string, StockResearchFact> = {
  AAOI: {
    industry: "光通訊與 800G/1.6T 光收發模組",
    supplyDemand: "北美超大規模 CSP（微軟、AWS）全面推動 AI 資料中心網路向 800G/1.6T 換代，模組供不應求，訂單能見度直通 2026-2027 年。",
    bottleneck: "關鍵瓶頸在於連續波（CW）雷射封裝良率與上游 InP 基板晶圓配額，高頻散熱與訊號完整性技術門檻極高。",
    synthesis: "SEC Form 10-Q 申報：德州工廠加速產能調度以承接 800G 規模放量；已獲大型雲端客戶採購承諾，正鎖定上游雷射供應鏈；需留意營運現金流與擴產資本開支。",
  },
  AXTI: {
    industry: "InP（磷化銦）與化合物半導體關鍵基板",
    supplyDemand: "AI 光互聯暴增引發全球 InP 晶圓短缺，受惠 800G/1.6T/3.2T 光模組與矽光子光源強勁剛需。",
    bottleneck: "全球 InP 襯底高純度長晶與 6 吋晶圓切割良率壁壘極高，產能被少數頭部廠商寡占，具備絕對定價權（ASP 連續調升）。",
    synthesis: "SEC Form 8-K/10-Q：獲 Lumentum 4,350 萬美元產能預留定金，及 Coherent 2,229 萬美元 3 年預付款協議；需提防中國關鍵金屬（鎵/鍺）出口限制及原料風險。",
  },
  COHR: {
    industry: "高意集團・光通訊收發器與先進光學雷射",
    supplyDemand: "全球光通訊雙雄之一，深度綁定 NVIDIA Blackwell 算力集群與超大規模雲端客戶，800G/1.6T 光學模組訂單滿載。",
    bottleneck: "垂直整合 InP/GaAs 磊晶、雷射晶片與光引擎組裝能力極度稀缺，是少數能滿足十萬卡集群低延遲互聯標準的廠商。",
    synthesis: "與 NVIDIA 簽署多年戰略合作協議，涵蓋數十億美元採購承諾與未來先進光網路產能權利；SEC 10-K 顯示研發 CapEx 擴大，毛利率進入上行週期。",
  },
  TSEM: {
    industry: "矽光子（SiPho）晶圓代工製造",
    supplyDemand: "國際一線晶片巨頭與光通訊模組大廠全面委外下單矽光子晶片，產能利用率逼近上限。",
    bottleneck: "矽光子晶圓製造、光波導蝕刻與片上雷射耦合良率門檻極高，全球具備商業化代工規模者屈指可數。",
    synthesis: "SEC Form 20-F 與官方公告：鎖定 2027 年達 13 億美元客戶合約，並已收取 2.9 億美元大額預付款定金，產能預計 2027Q4 全面放量；需留意台積電競爭。",
  },
  SIVE: {
    industry: "InP 光學連續波（CW）雷射與 CPO 核心組件",
    supplyDemand: "CPO 矽光子架構必備外置連續波光源（ELS），每台交換機需數十至上百顆雷射晶片，市場需求呈現指數級增長。",
    bottleneck: "蘇格蘭格拉斯哥晶圓廠為全球少數具備年產 1 億顆 CW DFB 雷射能力的量產線，高功率單模雷射良率為關鍵約束。",
    synthesis: "官方公告獲 ALL.SPACE 820 萬美元生產訂單，商機漏斗超過 12 億美元；需高度警惕多次折價現增、可轉債轉股對股權之攤薄，靜待 2027 年產能放量。",
  },
  NVDA: {
    industry: "AI 算力加速晶片與 NVLink 超大規模互聯",
    supplyDemand: "全球雲端巨頭與主權 AI 算力軍備競賽需求無上限，Blackwell 架構機櫃全面排單至未來數個季度。",
    bottleneck: "核心物理瓶頸在於台積電 CoWoS 封裝產能、高頻寬記憶體（HBM3e）配額與機櫃水冷散熱組件交期。",
    synthesis: "SEC Form 10-Q 揭露待履行訂單（RPO）約 32 億美元，單季營收年增 >70%；需關注光互聯交期與下游客戶推理貨幣化回收節奏。",
  },
  TSM: {
    industry: "全球先進半導體晶圓製造與 CoWoS 先進封裝",
    supplyDemand: "3nm/2nm 先進製程與 CoWoS/SoIC 封裝產能全數售罄，蘋果、NVIDIA、AMD、高通包攬全部產能。",
    bottleneck: "晶圓製造微縮物理極限、EUV 曝光機交期、先進封裝中介層（Interposer）產能為全球算力總閥門。",
    synthesis: "SEC Form 20-F：毛利率維持 54% 以上高位，具備強大轉嫁成本之定價權；需留意海外設廠（美、日、德）折舊成本與地緣政治波動。",
  },
  AMD: {
    industry: "高效能 CPU、GPU 算力晶片與自適應運算",
    supplyDemand: "MI300X / MI325X 獲微軟、Meta 等雲端大客戶規模部署，企業對雙供應商（Second Source）抗衡 NVIDIA 需求迫切。",
    bottleneck: "供應鏈約束在於台積電 CoWoS 產能獲取配額、HBM 供應鏈供貨速度及 ROCm 軟體生態兼容門檻。",
    synthesis: "SEC Form 10-Q 申報待履行訂單（RPO）達 2.22 億美元；資料中心事業部營收翻倍增長，需留意與 CUDA 生態之競爭壁壘。",
  },
  AVGO: {
    industry: "AI 乙太網交換晶片、光電通訊與客製化 ASIC",
    supplyDemand: "Tomahawk 5 / Jericho 3-AI 晶片霸占超大規模雲端資料中心網路，Google / Meta 客製化 TPU / ASIC 需求爆發。",
    bottleneck: "掌握高頻交換晶片底層物理 SerDes 專利、光電互聯封裝核心技術，客戶轉換成本極高。",
    synthesis: "SEC Form 10-Q 揭露待履行訂單（RPO）高達 1,646 億美元；非半導體與軟體整合帶來豐沛自由現金流，需留意雲端自研晶片競爭。",
  },
  MU: {
    industry: "HBM3e / HBM4 高頻寬記憶體與先進 DRAM",
    supplyDemand: "AI 伺服器對 HBM 需求吞噬全球晶圓產能，2026-2027 年 HBM 產能已全量被預訂一空。",
    bottleneck: "12 層 / 16 層 3D 堆疊良率、熱膨脹係數控制與 TSV 矽穿孔良率為核心物理天花板。",
    synthesis: "SEC Form 10-Q 揭露 RPO 達 50 億美元；日本經銷通路報告指出全球高階記憶體缺口達 40-60%，產品單價與毛利迎來超級週期。",
  },
  BE: {
    industry: "固態氧化物燃料電池（SOFC）現場自備能源",
    supplyDemand: "資料中心電網接入排隊期長達 4-7 年，雲端算力中心轉向「自備發電（Behind-the-Meter）」剛需爆發。",
    bottleneck: "大功率高溫燃料電池電堆製造良率、抗熱震材料壽命，以及現場微電網併網工程能力。",
    synthesis: "SEC Form 10-Q：獲美光與頂級 AI 資料中心巨額現場發電訂單，享有 15 年超長服務長約；需注意天然氣原料成本與資本開支周轉。",
  },
  ALAB: {
    industry: "PCIe Gen 5/6 與 CXL 智慧高速 Retimer 晶片",
    supplyDemand: "伺服器內部 GPU 與 CPU 高速互聯長度受物理信號衰減限制，每台 Blackwell 伺服器需搭載數十顆 Retimer。",
    bottleneck: "超高頻信號補償演算法、低延遲極限與各家主機板硬體兼容協議具備極高軟硬體護城河。",
    synthesis: "SEC Form 10-Q 揭露：毛利率超過 75%，獲一線伺服器 ODM 全面導入；需留意新進競品低價競爭。",
  },
  LITE: {
    industry: "EML 電吸收調製雷射與連續波（CW）雷射晶片",
    supplyDemand: "800G/1.6T 光模組不可或缺之上游雷射晶片，雲端資料中心長約採購持續放量。",
    bottleneck: "磷化銦（InP）高品質磊晶生長與雷射諧振腔高精度加工技術壁壘極高。",
    synthesis: "SEC Form 10-K：向 AXTI 預留數千萬美元 InP 基板產能，鎖定關鍵原料；需關注雲端大客戶採購節奏與拉貨週期。",
  },
  MRVL: {
    industry: "光通訊 PAM4 DSP 晶片與客製化 AI 雲端 ASIC",
    supplyDemand: "光模組內部電信號與光信號轉換大腦，5nm/3nm DSP 晶片需求隨 800G/1.6T 換代倍數擴張。",
    bottleneck: "極低功耗類比電路設計與超高速 DSP 演算法架構，進入門檻極高。",
    synthesis: "SEC Form 10-K：獲雲端巨頭多個 5nm/3nm 客製化晶片設計定案（Design Wins）；需關注研發費用支出與插槽份額。",
  },
  WDC: {
    industry: "大容量企業級 Enterprise SSD 與近線高密度 HDD",
    supplyDemand: "AI 大模型海量數據訓練集存儲與推理檢索（RAG）資料庫帶動企業級儲存爆發。",
    bottleneck: "3D NAND 高堆疊層數良率、近線硬碟磁頭定位精度與熱輔助磁記錄（HAMR）產能。",
    synthesis: "SEC Form 10-K：獲全球一線雲端大廠長期供貨協議，企業級產品佔比大幅提升；需留意消費級儲存週期干擾。",
  },
  SMCI: {
    industry: "AI 伺服器機櫃與浸沒式／直接水冷（DLC）散熱",
    supplyDemand: "十萬卡集群功耗飆破百千瓦，傳統氣冷失效，液冷伺服器出貨滲透率自 5% 躍升至 30%+。",
    bottleneck: "高密度伺服器冷卻管路防漏、分流歧管（Manifold）與冷卻液分配單元（CDU）工程交付能力。",
    synthesis: "SEC 申報待履行訂單達 26.1 億美元；需密切留意審計機構年報延遲審查風險與內部控制改善進度。",
  },
  APH: {
    industry: "AI 高頻銅互連纜線與高速背板連接器",
    supplyDemand: "NVLink 與伺服器內部機架高速銅互連需求隨 Blackwell 密鑰架構呈現暴增。",
    bottleneck: "224G 高速信號微波干擾屏蔽、金屬精密衝壓與特種高分子絕緣材料壁壘。",
    synthesis: "SEC Form 10-Q 申報未履行訂單高達 89 億美元；需關注長線「銅退光進（CPO）」對銅連接器份額之演進衝擊。",
  },
  CIEN: {
    industry: "資料中心互聯（DCI）與長途相干光傳輸系統",
    supplyDemand: "跨資料中心巨量資料同步與分散式集群訓練帶動 800G/1.6T DCI 傳輸設備擴建。",
    bottleneck: "WaveLogic 相干光電晶片與長距離低色散傳輸演算法，全球少數能提供端到端系統之龍頭。",
    synthesis: "SEC Form 10-Q：雲端客戶訂單佔比首度超越傳統電信商，毛利結構優化；需留意傳統電信市場支出疲弱。",
  },
  CRDO: {
    industry: "主動式電纜（AEC）與低功耗高速 SerDes",
    supplyDemand: "伺服器機櫃內部短距連接以 AEC 取代傳統光纖或無源銅纜，兼顧低成本、低功耗與柔軟度。",
    bottleneck: "晶片直接嵌入線纜內部封裝技術、信號重構演算法與高抗干擾專利。",
    synthesis: "SEC Form 10-Q 申報待履行訂單約 3,190 萬美元；正擴展微軟等超大規模客戶，需關注與光纖之成本博弈。",
  },
  MTSI: {
    industry: "高速類比驅動 IC、TIA 與 CW 連續波雷射封裝",
    supplyDemand: "800G/1.6T 光模組內部不可或缺的高頻類比放大晶片，需求維持高景氣度。",
    bottleneck: "磷化銦與砷化鎵射頻晶片精密製程、高線性度類比放大電路設計專利。",
    synthesis: "SEC Form 10-Q：營運利潤率穩步攀升，產能利用率滿載；需持續追蹤擴產設備調試進度。",
  },
  JBL: {
    industry: "光電精密製造、系統級封裝與代工組裝",
    supplyDemand: "雲端巨頭與光晶片新創尋求具備全套無塵室光學組裝與測試能力的製造夥伴。",
    bottleneck: "光纖自動耦合對準（Active Alignment）高精度設備與良率控制能力。",
    synthesis: "SEC Form 10-K：與 Sivers 蘇格蘭晶圓廠深化封測代工合作；需留意代工產業低毛利特性。",
  },
  APLD: {
    industry: "AI 高效能運算（HPC）超大規模資料中心基礎設施",
    supplyDemand: "科技巨頭爭奪具備數百兆瓦（MW）充裕電力配額之資料中心場地。",
    bottleneck: "關鍵約束在於已獲電網批准之高壓變電所電力容量與土地資源，具備天然排他性。",
    synthesis: "SEC Form 8-K：簽署長達 15 年期之超大規模長期租賃合約；需留意高槓桿專案融資利率與償債進度。",
  },
  IQE: {
    industry: "量子點雷射（Quantum Dot）與先進化合物半導體磊晶",
    supplyDemand: "矽光子晶圓需要高溫穩定性優異的量子點磊晶片作為晶圓級光源。",
    bottleneck: "分子束磊晶（MBE）超高真空長晶技術與晶格缺陷控制難度極大。",
    synthesis: "官方公告與 Quintessent 簽署晶圓採購協議；需密切關注 2028 年商業化進度與現金流融資需求。",
  },
  "3006.TW": {
    industry: "利基型成熟製程 DRAM（DDR2 / DDR3）",
    supplyDemand: "三大記憶體原廠將全部產能抽調至 HBM 與 DDR5，引發網通、電視與邊緣終端成熟 DRAM 結構性大缺貨。",
    bottleneck: "掌握成熟製程產能配額，在原廠退出市場之際享有現貨定價權與搶貨溢價。",
    synthesis: "台灣公開資訊觀測站（MOPS）營收申報：8 月營收出現爆發性倍數躍升；需注意原廠擴產週期與終端庫存調節。",
  },
};

export function buildStockResearchFlexMessages(
  ticker: string,
  stock: StockResearchFact,
): LineOutboundMessage[] {
  const bubble = {
    type: "bubble",
    size: "mega",
    header: box([
      text("個股物理瓶頸研析 · Supply Chain Intelligence", "xs", "#CBD5E1"),
      text(`【${ticker}】`, "xxl", "#FFFFFF", { weight: "bold" }),
      text(`行業別：${stock.industry} ｜ 唯讀研析`, "xs", "#94A3B8"),
    ], { backgroundColor: "#142C47", paddingAll: "lg" }),
    body: box([
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
      { type: "button", style: "primary", color: "#0F766E", height: "sm", action: { type: "message", label: `查詢 ${ticker} 期權限價（不賣股收租）`, text: `${ticker} sell call` } },
      { type: "button", style: "link", height: "sm", action: { type: "message", label: "查看 TOP 20 標的榜單", text: "TOP20" } },
    ], { paddingAll: "md", backgroundColor: "#F8FAFC", spacing: "sm" }),
  };

  const messages: LineOutboundMessage[] = [
    {
      type: "flex",
      altText: `【${ticker} 供應鏈研析】供應需求、實體瓶頸與財報總結`,
      contents: { type: "carousel", contents: [bubble] },
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

  if (query.ticker && query.intent !== "options") {
    const rawTicker = query.ticker.toUpperCase();
    const norm = rawTicker.replace(/\.(ST|L|TWO)$/i, "");
    const stock = STOCK_RESEARCH_KNOWLEDGE_BASE[rawTicker] ?? STOCK_RESEARCH_KNOWLEDGE_BASE[norm];
    if (stock) {
      if (style === "flex") {
        try {
          return buildStockResearchFlexMessages(rawTicker, stock);
        } catch {
          // fall through to text
        }
      }
      return [
        `【${rawTicker} 供應鏈瓶頸與潛力研析】`,
        `行業別：${stock.industry}`,
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
        `💡 守護者提示：輸入「${rawTicker} sell call」可即刻獲取不賣股高履約價期權限價建議！`,
      ].join("\n");
    }
  }

  const result = await loadV213FreshTop20Report(env, query);
  if (!result || typeof result === "string") return result;
  return buildV213Top20Messages(result, v213FieldLocale(env.V213_FIELD_LOCALE), style);
}
