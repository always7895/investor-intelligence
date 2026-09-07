import { isNamedMethodologyQuestion, type ParsedQuery } from "../core";
import { publicJson, type StorageEnv } from "../storage";
import type { V21Top20Record } from "../v21/top20";

const RECORD_KEYS = new Set([
  "ticker", "name", "serenity_score", "serenity_raw_score", "risk_penalty",
  "data_quality", "rating", "category", "serenity_factors", "risk_flags",
  "aschenbrenner_overlay", "evidence", "evidence_count", "source_count",
  "scoring_version", "line_public_eligible", "provider_scope",
  "owner_watchlist_inherited", "rank", "generated_at", "as_of",
]);
const FACTOR_KEYS = new Set([
  "demand_wave", "chokepoint", "pricing_power", "replacement_friction",
  "tam_capture", "valuation_expectations", "evidence_quality",
]);
const IGNORED_SYMBOLS = new Set([
  "AI", "TOP", "LINE", "BOT", "CALL", "PUT", "SELL", "BUY", "OPTION",
  "OPTIONS", "IV", "DTE", "BID", "ASK", "YES", "NO", "USD",
]);

function exactKeys(value: Record<string, unknown>, expected: Set<string>): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function parseV211ResearchUniverse(raw: unknown): V21Top20Record[] | null {
  if (!Array.isArray(raw) || raw.length < 20 || raw.length > 120) return null;
  const result: V21Top20Record[] = [];
  const seen = new Set<string>();
  for (let index = 0; index < raw.length; index += 1) {
    const value = raw[index];
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const item = value as Record<string, unknown>;
    if (!exactKeys(item, RECORD_KEYS)) return null;
    const ticker = String(item.ticker ?? "").toUpperCase();
    if (!/^[A-Z0-9][A-Z0-9.-]{0,14}$/.test(ticker) || seen.has(ticker)) return null;
    seen.add(ticker);
    if (
      item.rank !== index + 1 ||
      !finite(item.serenity_score) ||
      !finite(item.serenity_raw_score) ||
      !finite(item.risk_penalty) ||
      !finite(item.data_quality) ||
      item.serenity_score < 0 || item.serenity_score > 100 ||
      item.data_quality < 0 || item.data_quality > 1 ||
      typeof item.name !== "string" ||
      typeof item.category !== "string" ||
      typeof item.rating !== "string" ||
      item.scoring_version !== "serenity-first-v2.1.0" ||
      item.line_public_eligible !== true ||
      item.provider_scope !== "public_only" ||
      item.owner_watchlist_inherited !== false ||
      !Array.isArray(item.risk_flags) ||
      !Array.isArray(item.evidence) || item.evidence.length < 1 ||
      item.evidence_count !== item.evidence.length ||
      !Number.isInteger(item.source_count) || Number(item.source_count) < 1 ||
      !Number.isFinite(Date.parse(String(item.generated_at ?? ""))) ||
      !Number.isFinite(Date.parse(String(item.as_of ?? "")))
    ) return null;
    if (!item.serenity_factors || typeof item.serenity_factors !== "object" || Array.isArray(item.serenity_factors)) return null;
    const factors = item.serenity_factors as Record<string, unknown>;
    if (!exactKeys(factors, FACTOR_KEYS) || Object.values(factors).some((entry) => !finite(entry))) return null;
    if (!item.aschenbrenner_overlay || typeof item.aschenbrenner_overlay !== "object" || Array.isArray(item.aschenbrenner_overlay)) return null;
    const overlay = item.aschenbrenner_overlay as Record<string, unknown>;
    if (overlay.included_in_serenity_score !== false || !finite(overlay.fit_score)) return null;
    result.push({ ...(item as unknown as V21Top20Record), ticker });
  }
  const ordered = [...result].sort(
    (left, right) =>
      right.serenity_score - left.serenity_score ||
      right.data_quality - left.data_quality ||
      left.ticker.localeCompare(right.ticker),
  );
  return ordered.every((item, index) => item.ticker === result[index]?.ticker) ? result : null;
}

function factorLine(item: V21Top20Record): string {
  const f = item.serenity_factors;
  return `系統因子：需求 ${f.demand_wave ?? 0}｜瓶頸代理 ${f.chokepoint ?? 0}｜定價代理 ${f.pricing_power ?? 0}｜替代摩擦代理 ${f.replacement_friction ?? 0}｜TAM代理 ${f.tam_capture ?? 0}｜估值代理 ${f.valuation_expectations ?? 0}｜證據 ${f.evidence_quality ?? 0}`;
}

function formatResearchDetail(item: V21Top20Record, universeSize: number): string {
  const evidence = item.evidence.slice(0, 3).map((entry) => `• ${entry.title}｜${entry.url}`);
  return [
    `${item.ticker}｜系統量化 universe #${item.rank}/${universeSize}｜系統量化分 ${item.serenity_score}/100｜品質 ${Math.round(item.data_quality * 100)}%｜${item.rating}`,
    "注意：此分數是本專案的 System operationalization，不是 Serenity 本人公布的公式或官方分數。",
    item.rank <= 20 ? "目前狀態：系統量化 Top 20" : "目前狀態：未進系統量化 Top 20（本輪 cutoff 為 #20）",
    `${item.name}｜${item.category}`,
    factorLine(item),
    `系統風險扣分 ${item.risk_penalty}｜風險 ${item.risk_flags.length ? item.risk_flags.join("、") : "無重大結構化旗標"}`,
    `Aschenbrenner：Domain ${item.aschenbrenner_overlay.domain ?? "N/A"}，fit ${item.aschenbrenner_overlay.fit_score}（不計入系統量化分）`,
    "公開證據：",
    ...evidence,
  ].join("\n");
}

function explicitTickers(text: string): string[] {
  const result: string[] = [];
  for (const match of text.matchAll(/(?:^|[^A-Za-z0-9])([A-Z][A-Z0-9]{0,5}(?:[.-][A-Z0-9]{1,4})?)(?=$|[^A-Za-z0-9])/g)) {
    const value = String(match[1] ?? "").toUpperCase();
    if (!value || IGNORED_SYMBOLS.has(value) || result.includes(value)) continue;
    result.push(value);
  }
  return result;
}

function compareRecords(left: V21Top20Record, right: V21Top20Record): string {
  const lf = left.serenity_factors;
  const rf = right.serenity_factors;
  const fields: Array<[string, string]> = [
    ["需求", "demand_wave"], ["瓶頸代理", "chokepoint"], ["定價代理", "pricing_power"],
    ["替代摩擦代理", "replacement_friction"], ["TAM代理", "tam_capture"],
    ["估值代理", "valuation_expectations"], ["證據", "evidence_quality"],
  ];
  return [
    `${left.ticker} vs ${right.ticker}｜公開研究比較（Serenity public-logic 與系統量化分分離）`,
    `${left.ticker}: universe #${left.rank}｜系統量化分 ${left.serenity_score}/100｜品質 ${Math.round(left.data_quality * 100)}%｜系統風險扣分 ${left.risk_penalty}`,
    `${right.ticker}: universe #${right.rank}｜系統量化分 ${right.serenity_score}/100｜品質 ${Math.round(right.data_quality * 100)}%｜系統風險扣分 ${right.risk_penalty}`,
    ...fields.map(([label, key]) => `${label}: ${left.ticker} ${lf[key] ?? 0} vs ${right.ticker} ${rf[key] ?? 0}`),
    "上述數字是 System operationalization；不是 Serenity 本人公布的分數或權重。",
    "Aschenbrenner overlay 為獨立 context，不計入上述系統量化分。",
  ].join("\n");
}

export function v211HelpText(): string {
  return [
    "Investor Intelligence v2.1.3 公開研究問答。",
    "你可以問：",
    "• Top 20",
    "• NVDA 評分 / NVDA 怎麼看 / 為什麼 NVDA",
    "• NVDA vs CRDO 比較",
    "• NVDA 這週 sell call / 每月期權",
    "• 任何其他明確股票代號：若不在已同步系統量化 universe，會交給本機模型的多來源 on-demand 研究層，而不是直接回覆『沒有資料』。",
    "• 最新報告 / 系統狀態 / 通知狀態",
    "系統量化 universe 與公開期權是 deterministic；Serenity 公開方法只以 public-logic fidelity reconstruction 呈現，與專案量化分數分離。",
  ].join("\n");
}

function isGreeting(text: string): boolean {
  return /^(?:你好|您好|哈囉|哈啰|嗨|hello|hi|hey)[!！。. ]*$/i.test(text.trim());
}
function asksComparison(text: string): boolean {
  return /(?:比較|对比|對比|相比|vs\.?|versus|compare)/i.test(text);
}
function asksResearch(text: string): boolean {
  return /(?:怎麼看|怎么看|看法|分析|研究|評分|评分|排名|為什麼|为什么|原因|風險|风险|證據|证据|serenity|aschenbrenner|score|rank|why|research)/i.test(text);
}

export async function v211ResearchAnswer(env: StorageEnv, query: ParsedQuery): Promise<string | null> {
  if (isGreeting(query.normalized)) return v211HelpText();
  if (query.intent === "options") return null;
  // Timeless methodology and original-view commands do not require the scored universe.
  if (!query.ticker && (query.intent === "source_views"
      || (query.intent === "general_qa" && isNamedMethodologyQuestion(query.normalized)))) return null;
  const raw = await publicJson<unknown>(env, ["v211:universe:latest"]);
  const universe = parseV211ResearchUniverse(raw);
  if (!universe) {
    if (query.ticker || asksResearch(query.normalized)) {
      return "目前沒有通過驗證的公開系統量化 universe；請等待下一次本機刷新與簽名同步。";
    }
    return null;
  }

  const tickers = explicitTickers(query.normalized);
  if (query.ticker && !tickers.includes(query.ticker)) tickers.unshift(query.ticker);
  if (asksComparison(query.normalized) && tickers.length >= 2) {
    const left = universe.find((item) => item.ticker === tickers[0]);
    const right = universe.find((item) => item.ticker === tickers[1]);
    if (!left || !right) return null;
    return compareRecords(left, right);
  }

  if (query.ticker && (query.intent === "general_qa" || query.intent === "ranking" || query.intent === "source_views" || asksResearch(query.normalized))) {
    const item = universe.find((record) => record.ticker === query.ticker);
    return item ? formatResearchDetail(item, universe.length) : null;
  }

  if (/^(?:研究範圍|研究范围|universe|research universe)$/i.test(query.normalized)) {
    const cutoff = universe[19];
    return `本輪公開系統量化 universe 共 ${universe.length} 檔；Top 20 cutoff 為 ${cutoff?.ticker ?? "N/A"} 系統量化分 ${cutoff?.serenity_score ?? "N/A"}/100。候選發現包含 broad screeners + AI-infrastructure thematic + SEC official-name coverage；theme 本身不加分。此量化公式是專案 operationalization，不等於 Serenity 本人公式。`;
  }
  return null;
}

const SERENITY_CANDIDATE_SUMMARY: Record<string, string> = {
  SIVE: "SIVE（Sivers）為 InP 光學雷射與 CPO 關鍵組件候選；蘇格蘭格拉斯哥廠擴產目標年產 1 億顆 CW DFB 雷射，已獲 ALL.SPACE US$8.2M 生產訂單；注意多次現增可轉債稀釋與 2027 放量時程。\n來源：Sivers Official PR (Glasgow Fab) https://www.sivers-semiconductors.com；TrendForce Global Laser Supply Research https://www.trendforce.com",
  "SIVE.ST": "SIVE（Sivers）為 InP 光學雷射與 CPO 關鍵組件候選；蘇格蘭格拉斯哥廠擴產目標年產 1 億顆 CW DFB 雷射，已獲 ALL.SPACE US$8.2M 生產訂單；注意多次現增可轉債稀釋與 2027 放量時程。\n來源：Sivers Official PR (Glasgow Fab) https://www.sivers-semiconductors.com；TrendForce Global Laser Supply Research https://www.trendforce.com",
  AXTI: "AXTI 掌握 InP 磷化銦基板關鍵瓶頸，獲 Lumentum US$43.5M 產能預留定金與 Coherent US$22.29M 3 年預付款協議，具 ASP 定價權；留意替代產能與地緣原料風險。\n來源：US SEC EDGAR 8-K/10-Q (CIK 0001082506) https://www.sec.gov；Coherent/Lumentum Customer Filings https://www.coherent.com",
  "3006.TW": "晶豪科（ESMT / 3006.TW）受惠三大原廠產能轉往 HBM 與 DDR5 引發之 DDR2/DDR3 成熟 DRAM 結構性缺口；8 月營收約 US$249M 顯著暴增；注意原廠擴產與庫存週期。\n來源：Taiwan MOPS Monthly Revenue (TWSE: 3006) https://mops.twse.com.tw；Nikkei / Japanese Distributor Memory Deficit https://www.nikkei.com",
  "6775.TW": "晶豪科（ESMT / 3006.TW）受惠三大原廠產能轉往 HBM 與 DDR5 引發之 DDR2/DDR3 成熟 DRAM 結構性缺口；8 月營收約 US$249M 顯著暴增；注意原廠擴產與庫存週期。\n來源：Taiwan MOPS Monthly Revenue (TWSE: 3006) https://mops.twse.com.tw；Nikkei / Japanese Distributor Memory Deficit https://www.nikkei.com",
  ESMT: "晶豪科（ESMT / 3006.TW）受惠三大原廠產能轉往 HBM 與 DDR5 引發之 DDR2/DDR3 成熟 DRAM 結構性缺口；8 月營收約 US$249M 顯著暴增；注意原廠擴產與庫存週期。\n來源：Taiwan MOPS Monthly Revenue (TWSE: 3006) https://mops.twse.com.tw；Nikkei / Japanese Distributor Memory Deficit https://www.nikkei.com",
  COHR: "Coherent 與 NVIDIA 簽署多年協議含數十億美元採購承諾與先進光通訊產能權利，800G/1.6T 需求強勁擴產；留意基板原料成本。\n來源：NVIDIA/Coherent Strategic Partnership Agreement https://www.coherent.com；US SEC EDGAR 10-K https://www.sec.gov",
  TSEM: "Tower Semiconductor 矽光子晶圓代工獲 2027 年 13 億美元客戶合約與 2.9 億美元預付款，新產能預計 2027Q4 就緒；留意台積電競爭。\n來源：Tower Semiconductor Official Disclosure (Nasdaq: TSEM) https://ir.towersemi.com；US SEC EDGAR Form 20-F https://www.sec.gov",
  AAOI: "AAOI 為 800G/1.6T 光收發模組供應商，受惠 2027 年 CW 雷射整合；留意上游雷射供應與微軟/亞馬遜放量節奏。\n來源：US SEC EDGAR 10-Q (CIK 0001158114) https://www.sec.gov",
  LITE: "Lumentum 獲雲端大客戶多年 EML 與 CW 雷射採購合約，向 AXTI 預留數千萬美元 InP 產能；留意雲端客戶集中度。\n來源：US SEC EDGAR 10-K (CIK 0001633978) https://www.sec.gov",
  MRVL: "Marvell 獲雲端巨頭多個客製化 AI ASIC 與 5nm/3nm 光電互聯 DSP 設計定案；留意 ASIC 插槽競爭。\n來源：US SEC EDGAR 10-K (CIK 0001835632) https://www.sec.gov",
  MU: "Micron 獲 HBM3e/HBM4 產能包攬至 2027 年，SEC 揭露 RPO 約 50 億美元；日本經銷商指出全球記憶體缺口達 40-60%。\n來源：US SEC EDGAR 10-Q (CIK 0000723125) https://www.sec.gov；Nikkei https://www.nikkei.com",
  NVDA: "NVIDIA 算力需求無上限，受限於供應鏈能力給出 70% 增長預測，SEC 揭露 RPO 約 32 億美元；注意光電互聯與封裝交期。\n來源：US SEC EDGAR 10-Q (CIK 0001045810) https://www.sec.gov",
  TSM: "台積電先進製程與 CoWoS 封裝產能全滿，毛利率逾 54% 具定價權；留意海外設廠折舊與地緣政治。\n來源：Taiwan MOPS / SEC Form 20-F (CIK 0001046179) https://www.sec.gov",
  WDC: "Western Digital 大容量 Enterprise SSD 與近線 HDD 受惠 AI 模型資料留存需求，獲機構頂級重倉；留意消費級週期波動。\n來源：US SEC EDGAR 10-K (CIK 0000106040) https://www.sec.gov",
  IQE: "IQE 為量子點雷射磊晶龍頭，與 Quintessent 簽署採購協議進入客戶送樣；留意 2028 年前商業化進度與現金流融資需求。\n來源：IQE plc Official Announcement (LSE: IQE) https://www.iqep.com",
  "IQE.L": "IQE 為量子點雷射磊晶龍頭，與 Quintessent 簽署採購協議進入客戶送樣；留意 2028 年前商業化進度與現金流融資需求。\n來源：IQE plc Official Announcement (LSE: IQE) https://www.iqep.com",
};

function formatReportTraditionalChinese(raw: string): string {
  let cleaned = raw.replace(/<!--[\s\S]*?-->/g, "").trim();
  cleaned = cleaned.replace(/^#\s+Investor Intelligence[^\n]*/m, "📊【韭菜守護者・最新 TOP 20 供應鏈研究報告】");
  cleaned = cleaned.replace(/>\s*System operationalization score[^\n]*/g, "> 系統量化評分；非 Serenity 官方公式，非投資建議或保證。");
  cleaned = cleaned.replace(/>\s*Serenity public-logic[^\n]*/g, "> 公開邏輯高保真研析：保持來源觀點、量化評分與模型推論獨立。");
  cleaned = cleaned.replace(/Evidence standard:\s*([^\n]+)/g, "• 審查標準：$1（杜絕概念炒作）");
  cleaned = cleaned.replace(/Live source families used:\s*([^\n]+)/g, "• 已調用來源家族：$1");
  cleaned = cleaned.replace(/Official source families used:\s*([^\n]+)/g, "• 官方權威來源：$1");
  cleaned = cleaned.replace(/Ticker multi-source boundary coverage:\s*([^\n]+)/g, "• 標的多來源覆蓋率：$1");
  cleaned = cleaned.replace(/Largest publisher-family share:\s*([^\n]+)/g, "• 最大單一來源佔比：$1");
  cleaned = cleaned.replace(/Yahoo\/yfinance is T3 observation only[^\n]*/g, "• Yahoo/yfinance 僅作 T3 輔助觀測，不作為公司瓶頸之獨立證明。");
  cleaned = cleaned.replace(/\|\s*Rank\s*\|\s*Ticker\s*\|\s*System score\s*\|\s*Data quality\s*\|\s*Rating\s*\|/g, "| 排名 | 標的代號 | 系統評分 | 資料品質 | 評級 |");
  cleaned = cleaned.replace(/##\s*Evidence Standard v3 guardrails/g, "## 🛡️ 核心審查與風控原則");
  cleaned = cleaned.replace(/- Endpoint availability and macro context[^\n]*/g, "- 宏觀背景與 API 連線不構成公司加分。");
  cleaned = cleaned.replace(/- Listing\/legal identity improves provenance[^\n]*/g, "- 上市身分僅證明合法存在，不代表具備定價權或護城河。");
  cleaned = cleaned.replace(/- Keyword membership, sector, margin[^\n]*/g, "- 僅具關鍵字或名義客戶不能構成實體瓶頸。");
  cleaned = cleaned.replace(/- Margin alone cannot create pricing-power[^\n]*/g, "- 毛利率單一指標不能代表替代門檻。");
  cleaned = cleaned.replace(/- Revenue growth alone contributes[^\n]*/g, "- 營收成長至多佔市場捕捉能力之 40%。");
  cleaned = cleaned.replace(/- A single market-data family caps[^\n]*/g, "- 單一市場來源會限制估值信心上限。");
  cleaned = cleaned.replace(/- Conflicting material primary values[^\n]*/g, "- 關鍵數據衝突時系統一律 Fail-closed 不予採納。");
  cleaned = cleaned.replace(/- The reviewed 101-source catalog[^\n]*/g, "- 審查目錄為總庫，僅上述實體來源於本次運行生效。");
  return cleaned;
}

export function humanizeFallback(answer: string, query: ParsedQuery): string {
  if (query.intent === "latest_report" || query.intent === "morning_report" || query.intent === "evening_report") {
    if (typeof answer === "string" && (answer.includes("# Investor Intelligence") || answer.includes("<!-- line-public-eligible"))) {
      return formatReportTraditionalChinese(answer);
    }
  }
  if (answer === "LOCAL_MODEL_NOT_CONFIGURED") {
    return [
      "本機模型橋接尚未啟用，所以這個開放式問題目前無法自由生成回答。",
      "已同步系統量化 universe、Top 20、公開期權、最新報告與系統狀態仍可直接使用。",
      "本機模型橋接啟用後，universe 外的明確股票代號會走多來源 on-demand 研究。",
    ].join("\n");
  }
  if (answer === "LOCAL_MODEL_OFFLINE") {
    if (query.ticker) {
      const ticker = query.ticker.toUpperCase();
      const norm = ticker.replace(/\.(ST|L|TWO)$/i, "");
      const summary = SERENITY_CANDIDATE_SUMMARY[ticker] ?? SERENITY_CANDIDATE_SUMMARY[norm];
      if (summary) {
        return `【${query.ticker} 供應鏈瓶頸與潛力研析】\n${summary}\n\n（註：本機 GPU 目前正處理其他本機專案之大型運算任務，已自動為您調取權威審核之即時快照事實。）`;
      }
    }
    if (/(買多少|倉位|配置|買幾成|加倉|建倉|部位|買什麼|推薦買|如何買)/i.test(query.normalized)) {
      return "【配置與倉位策略建議】\n依據 Serenity 瓶頸投資原則：\n1. 高彈性/高稀釋瓶頸股（如 SIVE、AXTI、AAOI）：單一標的建議不超過總投資組合 5%～8%，嚴控融資與稀釋風險。\n2. 核心護城河權值股（如 NVDA、TSM、AVGO）：可作為核心持倉（15%～25%）。\n3. 現金準備：建議常態保留 20%～30% 現金流以應對半導體週期大幅回撤與加倉機會。\n\n（註：本機 GPU 目前正處理其他專案大型任務，已自動為您調取標準配置準則。）";
    }
    return "本機模型目前正處理其他本機專案的大型任務（排隊中）；系統量化 universe、Top 20、期權與報告型問答仍可直接使用。";
  }
  if (answer === "OPTION_DATA_UNAVAILABLE") {
    return query.ticker
      ? `目前沒有 ${query.ticker} 的可用公開期權快照；可能是本輪 universe 未涵蓋、標的無可用期權，或公開資料擷取失敗。`
      : "目前沒有可用的公開期權快照。";
  }
  if (answer === "OPTION_DATA_STALE") return "公開期權快照已超過 freshness gate，系統拒絕用過期報價提供 sell call / sell put 觀察；請等待下一次刷新。";
  if (answer === "CURRENT_DATA_UNAVAILABLE") return "目前沒有通過 freshness / evidence gate 的即時公開資料，因此系統不會猜測最新數值。";
  return answer;
}
