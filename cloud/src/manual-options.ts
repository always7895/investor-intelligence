export type ManualOptionType = "call" | "put";

export interface ManualOptionInput {
  ticker: string;
  optionType: ManualOptionType;
  spot: number;
  strike: number;
  bid: number;
  ask: number;
  dte: number;
  currency: string;
}

const COMMAND = /^(?:期權試算|期权试算|option(?:s)?\s+calc(?:ulator)?)(?:\s+|$)/i;
const HELP = /^(?:期權試算說明|期权试算说明|option(?:s)?\s+calc(?:ulator)?\s+help)$/i;
const DECIMAL = /^(?:0|[1-9]\d*)(?:\.\d+)?$/;
const INTEGER = /^(?:0|[1-9]\d*)$/;
const TICKER = /^[A-Z][A-Z0-9]{0,7}(?:[.-][A-Z0-9]{1,4})?$/;
const CURRENCY = /^[A-Z]{3}$/;

const FIELD_ALIASES: Record<string, keyof ManualOptionInput> = {
  ticker: "ticker",
  symbol: "ticker",
  代號: "ticker",
  代码: "ticker",
  type: "optionType",
  optiontype: "optionType",
  類型: "optionType",
  类型: "optionType",
  spot: "spot",
  price: "spot",
  現價: "spot",
  现价: "spot",
  strike: "strike",
  k: "strike",
  履約價: "strike",
  行权价: "strike",
  bid: "bid",
  買價: "bid",
  买价: "bid",
  ask: "ask",
  賣價: "ask",
  卖价: "ask",
  dte: "dte",
  days: "dte",
  天數: "dte",
  天数: "dte",
  currency: "currency",
  ccy: "currency",
  幣別: "currency",
  币别: "currency",
};

const PRIVATE_FIELDS = new Set([
  "account",
  "accountid",
  "portfolio",
  "position",
  "positions",
  "holding",
  "holdings",
  "shares",
  "quantity",
  "contracts",
  "cost",
  "costbasis",
  "averageprice",
  "pnl",
  "margin",
  "buyingpower",
  "帳戶",
  "账户",
  "持倉",
  "持仓",
  "持有",
  "股數",
  "股数",
  "口數",
  "口数",
  "成本",
  "損益",
  "损益",
  "保證金",
  "保证金",
]);

function usage(): string {
  return [
    "手動期權試算格式：",
    "期權試算 ticker=ALPHA type=call spot=100 strike=110 bid=2.50 ask=2.80 dte=7 currency=USD",
    "",
    "type 只接受 call / put；currency 可省略，預設 USD。",
    "輸入值只用於本次即時計算，不會查詢券商、持倉或帳戶，也不會成為公開行情快照。",
  ].join("\n");
}

function error(reason: string): string {
  return `手動期權試算輸入錯誤：${reason}\n\n${usage()}`;
}

function strictNumber(value: string, field: string): number | string {
  if (!DECIMAL.test(value)) return `${field} 必須是非負十進位數字`;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return `${field} 超出可計算範圍`;
  return parsed;
}

function optionType(value: string): ManualOptionType | null {
  const normalized = value.toLowerCase();
  if (["call", "c", "買權", "买权"].includes(normalized)) return "call";
  if (["put", "p", "賣權", "卖权"].includes(normalized)) return "put";
  return null;
}

function round(value: number, digits = 2): number {
  const factor = 10 ** digits;
  return Math.round((value + Number.EPSILON) * factor) / factor;
}

function money(value: number, currency: string): string {
  return `${currency} ${round(value).toFixed(2)}`;
}

function percent(value: number): string {
  return `${round(value).toFixed(2)}%`;
}

function annualized(credit: number, capital: number, dte: number): number {
  if (credit < 0 || capital <= 0 || dte <= 0) return 0;
  return (credit / capital) * (365 / dte) * 100;
}

function periodLabel(dte: number): string {
  if (dte >= 3 && dte <= 14) return "每週觀察區間";
  if (dte >= 21 && dte <= 45) return "每月觀察區間";
  return "自訂到期區間";
}

export function parseManualOptionInput(text: string): ManualOptionInput | string | null {
  const normalized = text.normalize("NFKC").trim();
  if (HELP.test(normalized)) return usage();
  if (!COMMAND.test(normalized)) return null;

  if (
    /(?:我(?:目前)?(?:持有|持倉|持仓)|我的(?:帳戶|账户|持倉|持仓|成本|損益|损益|保證金|保证金)|\bmy\s+(?:account|portfolio|position|holdings?|cost\s+basis|p&l|margin)\b)/i.test(
      normalized,
    )
  ) {
    return error("不接受個人持倉、帳戶、成本、損益或保證金資料");
  }

  const body = normalized.replace(COMMAND, "").trim();
  if (!body) return usage();
  const raw: Partial<Record<keyof ManualOptionInput, string>> = {};
  for (const token of body.split(/\s+/)) {
    const separator = token.indexOf("=");
    if (separator <= 0 || separator === token.length - 1) {
      return error("所有欄位都必須使用 key=value 且以空格分隔");
    }
    const rawKey = token.slice(0, separator).toLowerCase().replace(/[_-]/g, "");
    const rawValue = token.slice(separator + 1);
    if (PRIVATE_FIELDS.has(rawKey)) {
      return error("不接受任何持倉、帳戶或個人財務欄位");
    }
    const canonical = FIELD_ALIASES[rawKey];
    if (!canonical) return error(`未知欄位 ${rawKey}`);
    if (raw[canonical] !== undefined) return error(`欄位 ${rawKey} 重複`);
    raw[canonical] = rawValue;
  }

  for (const required of ["ticker", "optionType", "spot", "strike", "bid", "ask", "dte"] as const) {
    if (raw[required] === undefined) return error(`缺少必要欄位 ${required}`);
  }

  const ticker = String(raw.ticker).toUpperCase();
  if (!TICKER.test(ticker)) return error("ticker 格式無效");
  const parsedType = optionType(String(raw.optionType));
  if (!parsedType) return error("type 只接受 call 或 put");

  const spot = strictNumber(String(raw.spot), "spot");
  if (typeof spot === "string") return error(spot);
  const strike = strictNumber(String(raw.strike), "strike");
  if (typeof strike === "string") return error(strike);
  const bid = strictNumber(String(raw.bid), "bid");
  if (typeof bid === "string") return error(bid);
  const ask = strictNumber(String(raw.ask), "ask");
  if (typeof ask === "string") return error(ask);
  if (!INTEGER.test(String(raw.dte))) return error("dte 必須是整數天數");
  const dte = Number(raw.dte);

  if (spot <= 0 || spot > 1_000_000) return error("spot 必須大於 0 且在合理範圍內");
  if (strike <= 0 || strike > 1_000_000) return error("strike 必須大於 0 且在合理範圍內");
  if (bid < 0 || ask <= 0 || ask > 1_000_000) return error("bid / ask 超出合理範圍");
  if (ask < bid) return error("ask 不得小於 bid");
  if (dte < 1 || dte > 730) return error("dte 必須介於 1 到 730 天");

  const currency = String(raw.currency ?? "USD").toUpperCase();
  if (!CURRENCY.test(currency)) return error("currency 必須是三碼英文字母");

  return {
    ticker,
    optionType: parsedType,
    spot,
    strike,
    bid,
    ask,
    dte,
    currency,
  };
}

export function formatManualOptionQuote(input: ManualOptionInput): string {
  const midpoint = (input.bid + input.ask) / 2;
  const spread = input.ask - input.bid;
  const spreadPct = midpoint > 0 ? (spread / midpoint) * 100 : 0;
  const observedLow = input.bid + spread * 0.25;
  const capital = input.optionType === "call" ? input.spot : input.strike;
  const yields = [input.bid, midpoint, input.ask].map((value) =>
    annualized(value, capital, input.dte),
  );
  const distance =
    input.optionType === "call"
      ? (input.strike / input.spot - 1) * 100
      : (1 - input.strike / input.spot) * 100;
  const liquidity =
    input.bid > 0 && spreadPct <= 40
      ? "僅通過基本雙邊價差檢查；尚無 OI、成交量或報價時間可驗證"
      : "基本雙邊價差檢查未通過；不可視為具流動性的報價";

  const lines = [
    "手動期權報價試算（USER_SUPPLIED_NOT_VERIFIED）",
    `【${input.ticker}】${input.optionType.toUpperCase()}｜DTE ${input.dte}｜${periodLabel(input.dte)}`,
    `現價 ${money(input.spot, input.currency)}｜履約價 ${money(input.strike, input.currency)}｜距現價 ${percent(distance)}`,
    `Bid ${money(input.bid, input.currency)}｜Ask ${money(input.ask, input.currency)}｜Mid ${money(midpoint, input.currency)}`,
    `Spread ${money(spread, input.currency)}｜Spread / Mid ${percent(spreadPct)}`,
    `非約束性限價觀察 ${money(observedLow, input.currency)}–${money(midpoint, input.currency)}`,
    `Bid / Mid / Ask 年化權利金觀察 ${percent(yields[0]!)} / ${percent(yields[1]!)} / ${percent(yields[2]!)}`,
  ];

  if (input.optionType === "call") {
    lines.push(
      `履約時每股有效出售價觀察 ${money(input.strike + input.bid, input.currency)} / ${money(input.strike + midpoint, input.currency)} / ${money(input.strike + input.ask, input.currency)}`,
    );
  } else {
    lines.push(
      `每股損益平衡觀察 ${money(input.strike - input.bid, input.currency)} / ${money(input.strike - midpoint, input.currency)} / ${money(input.strike - input.ask, input.currency)}`,
      `標準一口現金履約額 ${money(input.strike * 100, input.currency)}`,
    );
  }

  lines.push(
    `流動性：${liquidity}`,
    "資料完全由本次訊息提供；系統沒有抓取或驗證行情，不連接券商、不讀取持倉、不下單，也不保存成公開快照。",
    "此結果是算術觀察，不是推薦、成交保證或個人化投資建議。",
  );
  return lines.join("\n");
}

export function manualOptionQuoteAnswer(text: string): string | null {
  const parsed = parseManualOptionInput(text);
  if (parsed === null || typeof parsed === "string") return parsed;
  return formatManualOptionQuote(parsed);
}
