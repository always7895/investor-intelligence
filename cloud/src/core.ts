export type BotIntent =
  | "help"
  | "morning_report"
  | "evening_report"
  | "latest_report"
  | "options"
  | "portfolio"
  | "ranking"
  | "source_views"
  | "health"
  | "memory_status"
  | "memory_enable"
  | "memory_disable"
  | "memory_clear"
  | "delete_data"
  | "job_result"
  | "general_qa";

export function isNamedMethodologyQuestion(text: string): boolean {
  return /(serenity|aschenbrenner|leopold)/i.test(text)
    && /(方法|框架|分析|瓶頸|瓶颈|價值捕捉|价值捕捉|method|framework|bottleneck|capture)/i.test(text)
    && /[?？]|如何|為何|为何|怎麼|怎么|what|how|why/i.test(text);
}

export type OptionPeriod = "weekly" | "monthly" | null;

export interface ParsedQuery {
  intent: BotIntent;
  ticker: string | null;
  period: OptionPeriod;
  referenceId: string | null;
  normalized: string;
}

// Do not hard-code the repository owner's symbols, holdings or preferences into
// the shared bot. Explicit ticker symbols are parsed directly from each query.
const TICKER_ALIASES: Record<string, string> = {
  // 台灣代號與中文別名
  "台積電": "TSM",
  "聯發科": "2454.TW",
  "聯亞": "3081.TW",
  "聯亞光電": "3081.TW",
  "晶豪科": "3006.TW",
  "川湖": "2059.TW",
  "弘塑": "3131.TW",
  "弘塑科技": "3131.TW",
  "辛耘": "3583.TW",
  "辛耘企業": "3583.TW",
  "聯鈞": "3450.TW",
  "聯鈞光電": "3450.TW",
  "光聖": "6442.TW",
  "光聖科技": "6442.TW",
  "緯穎": "6669.TW",
  "台達電": "2308.TW",
  "2330": "TSM",
  "2330.tw": "TSM",
  "3006": "3006.TW",
  "3081": "3081.TW",
  "2059": "2059.TW",
  "3131": "3131.TW",
  "3583": "3583.TW",
  "3450": "3450.TW",
  "6442": "6442.TW",
  "6669": "6669.TW",
  "2308": "2308.TW",
  "2454": "2454.TW",
  // 瑞典標的與中文別名
  "sivers": "SIVE",
  "sive": "SIVE",
  "atlascopco": "ATCO",
  "atlas": "ATCO",
  "mycronic": "MYCR",
  "hexagon": "HEXA",
  // 英國標的
  "arm": "ARM",
  "安謀": "ARM",
  "iqe": "IQE",
  "renishaw": "REN",
  "雷尼紹": "REN",
  // 全球關鍵物理瓶頸
  "asml": "ASML",
  "艾司摩爾": "ASML",
  "vertiv": "VRT",
  "維諦": "VRT",
  "palantir": "PLTR",
  "synopsys": "SNPS",
  "新思科技": "SNPS",
  "camtek": "CAMT",
  "onto": "ONTO",
  "poet": "POET",
};
const EXPLICIT_TICKER_TOKEN = "[A-Za-z0-9]{1,8}(?:[.-][A-Za-z0-9]{1,4})?";
const CONTEXTUAL_TICKER_TOKEN = "[A-Za-z][A-Za-z0-9]{0,5}(?:[.-][A-Za-z0-9]{1,4})?";
const CHINESE_TICKER_CONTEXT =
  "(?:(?:的|之)?\\s*(?:每週|每周|週選|周選|每月|月選|選擇權|选择权|期權|期权|評分|评分|股票|股價|股价|新聞|新闻|消息|sell\\s*call|sell\\s*put|covered\\s*call|cash\\s*secured\\s*put|options?|call|put))";
const ENGLISH_TICKER_CONTEXT =
  "(?:weekly|monthly|options?|bid|ask|ranking|score|news|sell\\s*call|sell\\s*put|covered\\s*call|cash\\s*secured\\s*put|call|put)";
const IGNORED_TICKER_TOKENS = new Set([
  "FOR",
  "OF",
  "THE",
  "AND",
  "TO",
  "IN",
  "ON",
  "AT",
  "BY",
  "WITH",
  "FROM",
  "IS",
  "ARE",
  "WAS",
  "WERE",
  "WHAT",
  "HOW",
  "WHO",
  "WHERE",
  "WHEN",
  "WHY",
  "DO",
  "DOES",
  "DID",
  "HAVE",
  "HAS",
  "HAD",
  "GET",
  "GIVE",
  "TAKE",
  "MAKE",
  "BID",
  "ASK",
  "IV",
  "DTE",
  "LINE",
  "BOT",
  "AI",
  "ETF",
  "CAGR",
  "HELP",
  "STATUS",
  "CALL",
  "PUT",
  "OPTION",
  "OPTIONS",
  "WEEK",
  "WEEKLY",
  "MONTH",
  "MONTHLY",
  "PRICE",
  "PRICES",
  "VALUE",
  "MARKET",
  "STOCK",
  "SHARE",
  "SHARES",
  "SELL",
  "BUY",
  "TOP",
  "FOR",
  "THE",
  "AND",
  "WHAT",
  "WHY",
  "HOW",
  "NEWS",
  "TODAY",
  "LATEST",
  "CURRENT",
]);

const KNOWN_UNIVERSE_TICKERS = new Set([
  "AAOI",
  "AXTI",
  "COHR",
  "TSEM",
  "SIVE",
  "SIVE.ST",
  "NVDA",
  "TSM",
  "AMD",
  "AVGO",
  "MU",
  "BE",
  "ALAB",
  "LITE",
  "MRVL",
  "WDC",
  "SMCI",
  "APH",
  "CIEN",
  "CRDO",
  "MTSI",
  "JBL",
  "APLD",
  "IQE",
  "IQE.L",
  "3006.TW",
  "6775.TW",
  "ESMT",
  // 擴充台灣核心物理瓶頸鏈
  "3081.TW",
  "2059.TW",
  "3131.TW",
  "3583.TW",
  "3450.TW",
  "6442.TW",
  "6669.TW",
  "2308.TW",
  "2454.TW",
  // 擴充英國與瑞典核心標的
  "ARM",
  "ATCO",
  "MYCR",
  "HEXA",
  "REN",
  // 擴充全球關鍵半導體與 AI 瓶頸
  "ASML",
  "VRT",
  "PLTR",
  "SNPS",
  "ONTO",
  "CAMT",
  "POET",
]);

export function normalizeText(text: string): string {
  return text.normalize("NFKC").trim().replace(/\s+/g, " ");
}

function normalizedTickerCandidate(raw: string | undefined): string | null {
  const candidate = String(raw ?? "").replace(/^\$/, "").toUpperCase();
  if (!candidate || /^\d+$/.test(candidate) || /^TOP\d+$/.test(candidate) || IGNORED_TICKER_TOKENS.has(candidate)) {
    return null;
  }
  if (!new RegExp(`^${EXPLICIT_TICKER_TOKEN}$`, "i").test(candidate)) return null;
  return candidate;
}

export function extractTicker(text: string): string | null {
  const normalized = normalizeText(text);
  const compact = normalized.toLowerCase().replace(/[^a-z0-9.]/g, "");
  for (const [alias, ticker] of Object.entries(TICKER_ALIASES)) {
    if (compact.includes(alias)) return ticker;
  }

  // 1. Direct match for known universe tickers (case-insensitive)
  const standaloneWord = normalized.replace(/^[\$#]/, "").trim();
  const upperStandalone = standaloneWord.toUpperCase();
  if (KNOWN_UNIVERSE_TICKERS.has(upperStandalone)) {
    return upperStandalone;
  }

  const candidatePatterns = [
    new RegExp(`\\$(${EXPLICIT_TICKER_TOKEN})`, "gi"),
    new RegExp(
      `(?:ticker|symbol|stock|代號|代码|股票)\\s*(?:(?:is|為|是)\\s*)?[:：]?\\s*\\$?(${EXPLICIT_TICKER_TOKEN})`,
      "gi",
    ),
    new RegExp(
      `(?:^|[^A-Za-z0-9])(${CONTEXTUAL_TICKER_TOKEN})\\s*(?=${CHINESE_TICKER_CONTEXT})`,
      "gi",
    ),
    new RegExp(
      `(?:^|[^A-Za-z0-9])(${CONTEXTUAL_TICKER_TOKEN})\\s+(?=${ENGLISH_TICKER_CONTEXT})`,
      "gi",
    ),
    new RegExp(
      `${CHINESE_TICKER_CONTEXT}\\s*(?:for|of|[:：])?\\s*\\$?(${CONTEXTUAL_TICKER_TOKEN})(?=$|[^A-Za-z0-9])`,
      "gi",
    ),
    new RegExp(
      `${ENGLISH_TICKER_CONTEXT}\\s+(?:for|of|[:：])\\s*\\$?(${CONTEXTUAL_TICKER_TOKEN})(?=$|[^A-Za-z0-9])`,
      "gi",
    ),
  ];
  for (const pattern of candidatePatterns) {
    for (const match of normalized.matchAll(pattern)) {
      const candidate = normalizedTickerCandidate(match[1]);
      if (candidate) return candidate;
    }
  }

  // 2. Known universe ticker contained within query as a standalone token (case-insensitive)
  const words = normalized.split(/[^A-Za-z0-9.]+/);
  for (const w of words) {
    const up = w.toUpperCase();
    if (KNOWN_UNIVERSE_TICKERS.has(up)) {
      return up;
    }
  }

  // 3. A deliberately uppercase standalone token is an explicit symbol signal.
  // Do not uppercase arbitrary prose before matching: doing so turns ordinary
  // words such as "opto" into fake tickers and can select unrelated snapshots.
  const uppercasePattern =
    /(?:^|[^A-Za-z0-9])([A-Z][A-Z0-9]{0,5}(?:[.-][A-Z0-9]{1,4})?)(?=$|[^A-Za-z0-9])/g;
  for (const match of normalized.matchAll(uppercasePattern)) {
    const candidate = normalizedTickerCandidate(match[1]);
    if (candidate) return candidate;
  }
  return null;
}

export function extractPeriod(text: string): OptionPeriod {
  const normalized = normalizeText(text).toLowerCase();
  if (/(每週|每周|週選|周選|weekly|week)/i.test(normalized)) return "weekly";
  if (/(每月|月選|monthly|month)/i.test(normalized)) return "monthly";
  return null;
}

export function parseQuery(text: string): ParsedQuery {
  const normalized = normalizeText(text);
  const lowered = normalized.toLowerCase();
  const ticker = extractTicker(normalized);
  const period = extractPeriod(normalized);
  const resultMatch = normalized.match(/(?:查看結果|查看结果|result)\s+([A-Z0-9]{6,16})/i);
  const referenceId = resultMatch?.[1]?.toUpperCase() ?? null;

  let intent: BotIntent = "general_qa";
  if (/^(help|幫助|帮助|功能|選單|菜单|menu|指令|怎麼用|怎么用)$/i.test(normalized)) {
    intent = "help";
  } else if (/^(記憶狀態|记忆状态|memory status)$/i.test(normalized)) {
    intent = "memory_status";
  } else if (/^(開啟記憶|开启记忆|enable memory)$/i.test(normalized)) {
    intent = "memory_enable";
  } else if (/^(關閉記憶|关闭记忆|disable memory)$/i.test(normalized)) {
    intent = "memory_disable";
  } else if (/^(清除本次對話|清除本次对话|清除對話|清除对话|clear conversation)$/i.test(normalized)) {
    intent = "memory_clear";
  } else if (/^(刪除我的資料|删除我的资料|delete my data)$/i.test(normalized)) {
    intent = "delete_data";
  } else if (referenceId) {
    intent = "job_result";
  } else if (/(早報|早报|morning report|morning briefing)/i.test(lowered)) {
    intent = "morning_report";
  } else if (/(晚報|晚报|evening report|evening briefing|盤前報告|盘前报告)/i.test(lowered)) {
    intent = "evening_report";
  } else if (
    /(最新報告|最新报告|今日報告|今日报告|daily report|briefing|宏觀產業分析|宏觀產業|宏觀分析|產業分析)/i.test(
      lowered,
    )
  ) {
    intent = "latest_report";
  } else if (
    /(選擇權|选择权|期權|期权|option|covered call|sell call|sell put|cash secured put|\bbid\b|\bask\b)/i.test(
      lowered,
    )
  ) {
    intent = "options";
  } else if (/(持倉|持仓|部位|portfolio|position|我持有|資產配置|资产配置)/i.test(lowered)) {
    intent = "portfolio";
  } else if (/(排名|評分|评分|score|ranking|top\s*\d*)/i.test(lowered)) {
    intent = "ranking";
  } else if (isNamedMethodologyQuestion(lowered)) {
    // Methodology questions must reach public Q&A, not the cached source-view command.
    // Plain names and explicit original-view commands retain their existing route.
    intent = "general_qa";
  } else if (/(serenity|aschenbrenner|leopold|來源觀點|来源观点|原始觀點|原始观点)/i.test(lowered)) {
    intent = "source_views";
  } else if (/^(健康|狀態|状态|health|status|系統狀態|系统状态)$/i.test(normalized)) {
    intent = "health";
  }

  return { intent, ticker, period, referenceId, normalized };
}

export function splitLineText(text: string, maxLength = 4900, maxMessages = 5): string[] {
  if (maxLength < 100) throw new Error("maxLength is too small");
  const normalized = text.trim();
  if (!normalized) return ["目前沒有可顯示的內容。"];

  const chunks: string[] = [];
  let current = "";
  const paragraphs = normalized.split(/\n{2,}/);
  const pushCurrent = () => {
    if (current.trim()) chunks.push(current.trim());
    current = "";
  };

  for (const paragraph of paragraphs) {
    if (paragraph.length > maxLength) {
      pushCurrent();
      for (let start = 0; start < paragraph.length; start += maxLength) {
        chunks.push(paragraph.slice(start, start + maxLength));
      }
      continue;
    }
    const candidate = current ? `${current}\n\n${paragraph}` : paragraph;
    if (candidate.length > maxLength) {
      pushCurrent();
      current = paragraph;
    } else {
      current = candidate;
    }
  }
  pushCurrent();

  if (chunks.length <= maxMessages) return chunks;
  const limited = chunks.slice(0, maxMessages);
  const suffix = "\n\n[內容過長，已截斷。請縮小問題範圍或指定股票／期間。]";
  limited[maxMessages - 1] = `${limited[maxMessages - 1]!.slice(0, maxLength - suffix.length)}${suffix}`;
  return limited;
}

function num(value: unknown): number | null {
  const result = typeof value === "number" ? value : Number(value);
  return Number.isFinite(result) ? result : null;
}

function money(value: unknown, currency = "USD"): string {
  const parsed = num(value);
  return parsed === null ? "N/A" : `${currency} ${parsed.toFixed(2)}`;
}

function percent(value: unknown, alreadyPercent = false): string {
  const parsed = num(value);
  if (parsed === null) return "N/A";
  return `${(alreadyPercent ? parsed : parsed * 100).toFixed(1)}%`;
}

function timestamp(value: unknown): string {
  if (!value) return "時間未知";
  const parsed = new Date(String(value));
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toISOString();
}

function limitObservation(candidate: Record<string, unknown>, currency: string): string {
  const value = candidate.sell_limit_observation;
  if (!value || typeof value !== "object") return "無可用參考";
  const low = num((value as Record<string, unknown>).observed_limit_low);
  const high = num((value as Record<string, unknown>).observed_limit_high);
  if (low === null || high === null) return "無可用參考";
  return `${currency} ${low.toFixed(2)}–${high.toFixed(2)}`;
}

function optionCandidateLines(
  candidate: Record<string, unknown>,
  currency: string,
): string[] {
  const yields = (candidate.annualized_yield_pct ?? {}) as Record<string, unknown>;
  const dist = num(candidate.distance_from_spot_pct);
  const distText = dist !== null ? `價外 ${dist.toFixed(1)}%` : "";
  const effPrice = candidate.effective_sale_price as Record<string, unknown> | undefined;
  const breakEven = candidate.put_break_even as Record<string, unknown> | undefined;
  const effText = effPrice?.mid != null ? `有效賣價 ${money(effPrice.mid, currency)}` : breakEven?.mid != null ? `損益平衡 ${money(breakEven.mid, currency)}` : "";
  return [
    `  ▫️ 履約價 K ${money(candidate.strike, currency)}${distText ? ` (${distText})` : ""} ｜ Bid ${money(candidate.bid, currency)} ｜ Ask ${money(candidate.ask, currency)} ｜ Mid ${money(candidate.midpoint, currency)}`,
    `    💡 推薦限價區間：${limitObservation(candidate, currency)}${effText ? ` ｜ ${effText}` : ""} ｜ Spread ${percent(candidate.spread_pct_of_mid, true)}`,
    `    📊 IV ${percent(candidate.implied_volatility_pct, true)} ｜ Delta ${candidate.delta ?? "N/A"} ｜ Mid 年化收益 ${percent(yields.mid, true)} (Bid ${percent(yields.bid, true)}) ｜ 流動性 ${candidate.liquidity_pass ? "PASS ✅" : "觀察 ⚠️"}`,
  ];
}

export function formatOptionsAnswer(
  raw: unknown,
  ticker: string | null,
  period: OptionPeriod,
): string {
  if (!Array.isArray(raw)) return "目前沒有可讀取的公開期權資料。";
  const normalizedTicker = ticker?.toUpperCase() ?? null;

  if (!normalizedTicker) {
    return [
      "📈【韭菜守護者・期權即時觀測快查】",
      "您可自由輸入「任意美股代號 + 期權」獲取精準的履約價、Bid/Ask、推薦限價區間與年化收益率！",
      "",
      "👉 常用查詢範例（支援任意標的）：",
      "• 【AAOI sell call】（800G 光模組，價外 7-13% 賣買權收租）",
      "• 【AXTI 每週期權】（磷化銦基板瓶頸，最新每週期權鏈）",
      "• 【COHR sell call】（NVIDIA 光通訊戰略合作大廠）",
      "• 【AMD 每週期權】或【MU 每月期權】",
      "• 【TSM 選擇權】或【AVGO 每週期權】",
      "• 【TSEM 期權】或【BE sell put】",
      "",
      "💡 韭菜守護者提示：",
      "• 掛單務必採用「限價單（Limit Order）」在推薦限價區間內成交，避免被做市商吃滑點！",
      "• 請直接輸入股票代號（例如：AAOI sell call），守護者立即為您測算！",
    ].join("\n");
  }

  const records = raw.filter(
    (item): item is Record<string, unknown> =>
      !!item &&
      typeof item === "object" &&
      String((item as Record<string, unknown>).ticker ?? "").toUpperCase() === normalizedTicker,
  );
  if (records.length === 0) {
    return `目前沒有 ${normalizedTicker} 的公開期權資料。資料來源可能未涵蓋該市場或標的無公開標準化期權。`;
  }

  const lines: string[] = [];
  for (const record of records) {
    const symbol = String(record.ticker ?? "N/A");
    lines.push(
      `📈【韭菜守護者・${symbol} 期權限價與流動性觀測】`,
      `🎯 標的：【${symbol}】｜狀態：${String(record.status ?? "OK")}｜資料時間：${timestamp(record.retrieved_at)}`,
      "公開期權 BID / ASK 報價觀察（唯讀、不下單）",
      "──────────────────────────────",
      "🛡️ 只使用獨立公共資料快照；不含持倉、帳戶、覆蓋口數或 IBKR 資料。限價單請在推薦區間內掛單，切勿追打市價單！",
    );
    const periods = (record.periods ?? {}) as Record<string, unknown>;
    for (const periodName of period ? [period] : ["weekly", "monthly"]) {
      const periodRaw = periods[periodName];
      if (!periodRaw || typeof periodRaw !== "object") {
        lines.push(`\n${periodName === "weekly" ? "每週" : "每月"}：無可用合約資料`);
        continue;
      }
      const periodRecord = periodRaw as Record<string, unknown>;
      const status = String(periodRecord.status ?? "UNKNOWN");
      const expPart = periodRecord.expiration ? `｜到期 ${String(periodRecord.expiration)}` : "";
      const dtePart = periodRecord.actual_dte != null ? `｜DTE ${String(periodRecord.actual_dte)}` : "";
      lines.push(
        `\n📅 【${periodName === "weekly" ? "每週期權 (Weekly)" : "每月期權 (Monthly)"}】${periodName === "weekly" ? "每週" : "每月"}｜${status}${expPart}${dtePart}`,
      );
      if (status !== "OK") continue;
      for (const [keys, label, emoji] of [
        [["covered_call", "call_observations"], "買權報價", "🟢"],
        [["cash_secured_put", "put_observations"], "賣權報價", "🟡"],
      ] as const) {
        let strategyRaw: unknown = null;
        for (const k of keys) {
          if (periodRecord[k] && typeof periodRecord[k] === "object") {
            strategyRaw = periodRecord[k];
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
        lines.push(`\n${emoji} ${label}｜${String(strategy.status ?? "OK")}${label === "買權報價" ? " (Covered Call / 賣買權收租防守)" : " (Cash-Secured Put / 賣賣權折價低接)"}`);
        if (candidates.length === 0) {
          lines.push("  ▫️ 無符合公開資料與流動性條件的候選報價");
          continue;
        }
        const isCall = label === "買權報價";
        const sorted = isCall
          ? [...candidates].sort((a, b) => {
              const aLiq = Boolean(a.liquidity_pass);
              const bLiq = Boolean(b.liquidity_pass);
              if (aLiq !== bLiq) return aLiq ? -1 : 1;
              const aDist = typeof a.distance_from_spot_pct === "number" ? a.distance_from_spot_pct : (Number(a.strike) || 0);
              const bDist = typeof b.distance_from_spot_pct === "number" ? b.distance_from_spot_pct : (Number(b.strike) || 0);
              return bDist - aDist;
            })
          : candidates;
        for (const candidate of sorted.slice(0, 3)) {
          const currency = String(candidate.currency ?? record.currency ?? "USD");
          if (!candidate.retrieved_at && record.retrieved_at) candidate.retrieved_at = record.retrieved_at;
          lines.push(...optionCandidateLines(candidate, currency));
        }
      }
    }
  }

  lines.push(
    "",
    "──────────────────────────────",
    "💡 韭菜守護者交易心法（不賣股為第一原則）：",
    "• 核心目標：長線看好物理瓶頸爆發力，「正股不被賣出」為最高優先級！",
    "• 履約價挑選：優先選擇「價外幅度最高（OTM +12%～+25%）」且權利金仍豐厚之合約，兼具安全厚墊與高額現金流。",
    "• 避開短兵相接：避免選擇價外低於 8% 之近價合約，防止單日爆發性漲勢導致正股被強行履約。",
    "• 遇暴漲防守法：若正股急漲逼近履約價，在到期日前以「平倉當週 + 往後移倉至下週更高 Strike（Roll Up & Out）」爭取時間並保持正股持倉！",
  );

  return lines.join("\n");
}

export function helpText(): string {
  return [
    "Investor Intelligence LINE Bot（公開資料模式）",
    "",
    "可用自然語言提問，例如：",
    "• 早報 / 晚報 / 最新報告",
    "• ALPHA 每週期權 BID ASK",
    "• BETA 每月期權",
    "• 目前排名 / ALPHA 評分",
    "• Serenity 原始觀點",
    "• Aschenbrenner 原始觀點",
    "• 系統狀態",
    "• 記憶狀態 / 開啟記憶 / 關閉記憶",
    "• 清除本次對話 / 刪除我的資料",
    "• 查看結果 ABC12345",
    "• 其他一般問題",
    "",
    "LINE 只讀取公開研究與公開期權快照，不具備 IBKR、券商帳戶、持倉或私人同步功能。記憶預設關閉且依租戶隔離；資料不足時會明確說明，不會捏造。",
  ].join("\n");
}
