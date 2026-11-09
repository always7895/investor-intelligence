/**
 * Options Product Handler & Presentation.
 * Covers:
 * 1. Functional query: [TICKER] 每週期權 / 每月期權.
 * 2. Strict quote validation: rejection of crossed quotes, stale timestamps, negative bid/ask.
 * 3. Greeks missing remain unavailable (null); OI/volume missing != zero.
 * 4. Midpoint calculated strictly from valid bid/ask: (bid + ask) / 2.
 * 5. Standalone educational strategy cards integration:
 *    Covered Call, Cash-Secured Put, Bull Call Spread, Protective Put.
 * 6. Pinned public snapshot gate: fail-closed UNAVAILABLE when not sealed.
 * 7. Standalone quote/result -> period selector -> educational strategy card navigation.
 */

import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import { LINE_THEME as T, altSummary, chip, disclosureLine, menuAction, menuBox, headerStyle, footerStyle, uiBox, uiText, noticeBanner } from "./line-theme";
import { formatCurrency, formatTaipeiTimestamp } from "./line-formatters";
import { humanizeStatusText } from "./status-labels";
import type { OptionContractQuote } from "./market-product-schema";
import { validateOptionContractQuote } from "./market-product-schema";
import { admitPublicOption, OptionRightsNotAdmittedError } from "./public-options-admission";
import { quoteBasisZh, rightsZh, sourceZh } from "./source-labels";
import { shortDteNoticeZh } from "./option-recommendation-rules";

export const OPTIONS_PRODUCT_KEY = "v213:options-chain:latest";

function formatMoney(val: number, currency: string = "USD"): string {
  return formatCurrency(val, currency);
}

/** Independent public-rights guard for every renderer: the trusted catalog join decides; a rights label or an admission_status
 * carried by the object (even "ADMITTED") is never sufficient. Format validation stays reusable for local data. */
function requireAdmitted(quote: OptionContractQuote): void {
  // Always the real current clock: a caller-supplied evaluatedAt (or any payload time) can never extend a review window.
  if (!admitPublicOption(quote).ok) throw new OptionRightsNotAdmittedError();
}

/** Multiple quoted facts share one tile without inventing a strategy or a recommendation. */
function quoteTile(pairs: readonly (readonly [string, string])[]) {
  const valueText = pairs.map(([, value]) => value).join("/");
  return uiBox([{ type: "text", size: "xs", wrap: true, contents: [
    { type: "span", text: `${pairs.map(([label]) => label).join("/")}\n`, color: T.subtle, size: "xs" },
    { type: "span", text: valueText, color: pairs.every(([, value]) => value === "未取得" || value === "未取得 / 未取得") ? T.subtle : T.ink, size: valueText.length > 14 ? "xs" : "sm", weight: "bold" },
  ] }], { flex: 1, backgroundColor: T.accentTint, cornerRadius: "md", paddingAll: "sm" });
}

export function buildOptionContractBubble(quote: OptionContractQuote, period: "weekly" | "monthly" | undefined) {
  requireAdmitted(quote);
  const nonexecTag = quote.quote_basis !== "realtime"
    ? "【非即時可執行報價】"
    : "【即時參考報價】";
  const monthlyNotice = period === "monthly" ? shortDteNoticeZh(quote.dte) : null;

  return {
    type: "bubble",
    size: "mega",
    header: menuBox([{ type: "text", size: "xs", wrap: true, contents: [
      { type: "span", text: `公開期權${nonexecTag}\n`, size: "xs", color: T.headerMuted },
      { type: "span", text: `${quote.ticker} ${quote.expiry} ${quote.strike}${quote.type.toUpperCase()}`, size: "lg", color: T.headerText, weight: "bold" },
      { type: "span", text: `\nDTE ${quote.dte}｜基準：${quoteBasisZh(quote.quote_basis)}｜${quote.currency}（${quote.multiplier}股/口）`, size: "xs", color: T.headerSubtle },
    ] }, ...(monthlyNotice ? [chip(monthlyNotice, T.cycleCaution, T.cycleCautionText)] : [])], { ...headerStyle }),
    body: uiBox([
      ...(quote.quote_basis !== "realtime" ? [noticeBanner("info", "延遲報價", "非即時成交；委託前向券商核對")]: []),
      uiBox([
      { type: "text", size: "3xl", weight: "bold", wrap: true, contents: [
        { type: "span", text: "中價權利金\n", size: "xs", color: T.subtle, weight: "regular" },
        { type: "span", text: formatMoney(quote.mid, quote.currency), size: "3xl", color: T.ink, weight: "bold" },
        { type: "span", text: "\n年化報酬：未提供", size: "xs", color: T.subtle, weight: "regular" },
      ] },
      ], { spacing: "sm" }),
      uiBox([
        quoteTile([["Bid", formatMoney(quote.bid, quote.currency)], ["Ask", formatMoney(quote.ask, quote.currency)], ["Spread", formatMoney(quote.spread, quote.currency)]]),
        quoteTile([["Delta", quote.delta !== null ? quote.delta.toFixed(3) : "未取得"],
          ["IV", quote.iv !== null ? `${(quote.iv * 100).toFixed(1)}%` : "未取得"]]),
        quoteTile([["OI / 量", `${quote.oi ?? "未取得"} / ${quote.volume ?? "未取得"}`]]),
      ], { layout: "horizontal", spacing: "sm" }),
    ], { paddingAll: "lg", spacing: "sm", backgroundColor: T.paper }),
    footer: uiBox([
      { type: "text", size: "xxs", color: T.subtle, wrap: true, contents: [
        { type: "span", text: "來源｜", color: T.subtle, weight: "bold" },
        { type: "span", text: `${formatTaipeiTimestamp(quote.timestamp)}｜${sourceZh(quote.source)}\n`, color: T.subtle },
        { type: "span", text: "權利｜", color: T.subtle, weight: "bold" },
        { type: "span", text: `${rightsZh(quote.rights_status)}｜出處 ${quote.provenance}\n`, color: T.subtle },
        { type: "span", text: "風險｜", color: T.subtle, weight: "bold" },
        { type: "span", text: `指派：${humanizeStatusText(quote.assignment_risk)}；流動性：${humanizeStatusText(quote.liquidity_warning)}；成交不保證；非投資建議、不下單`, color: T.subtle },
      ] },
      menuAction("查看期權策略教學", "期權教學"),
      menuAction("回功能選單", "選單"),
    ], { ...footerStyle }),
  };
}

export function buildOptionContractFlex(quote: OptionContractQuote, validationOptions?: Parameters<typeof validateOptionContractQuote>[1]): LineOutboundMessage[] {
  const validated = validateOptionContractQuote(quote, validationOptions);
  requireAdmitted(validated);
  const bubble = buildOptionContractBubble(validated, validationOptions?.period);
  const messages: LineOutboundMessage[] = [{
    type: "flex",
    altText: altSummary({ topic: `${validated.ticker} ${validated.expiry} ${validated.strike}${validated.type.toUpperCase()} 期權報價`,
      status: validated.quote_basis !== "realtime" ? "非即時可執行，僅供參考" : "即時參考報價", next: "點選查看期權策略教學", date: validated.timestamp }),
    contents: {
      type: "carousel",
      contents: [bubble],
    },
  }];
  assertLineMessages(messages);
  return messages;
}

export function buildOptionContractText(quote: OptionContractQuote, validationOptions?: Parameters<typeof validateOptionContractQuote>[1]): LineOutboundMessage[] {
  const validated = validateOptionContractQuote(quote, validationOptions);
  requireAdmitted(validated);
  const nonexecTag = validated.quote_basis !== "realtime"
    ? "【非即時可執行報價 · 僅供參考】"
    : "【即時參考報價】";

  const monthlyNotice = validationOptions?.period === "monthly" ? shortDteNoticeZh(validated.dte) : null;
  const text = [
    `【公開期權合約報價】${validated.ticker} ${validated.expiry} ${validated.strike}${validated.type.toUpperCase()}`,
    `報價性質：${nonexecTag}`,
    `DTE：${validated.dte} 天｜基準：${quoteBasisZh(validated.quote_basis)}｜來源：${sourceZh(validated.source)}｜幣別：${validated.currency}（乘數 ${validated.multiplier}）`,
    ...(monthlyNotice ? [monthlyNotice] : []),
    `行情：Bid ${formatMoney(validated.bid, validated.currency)} ｜ Mid ${formatMoney(validated.mid, validated.currency)} ｜ Ask ${formatMoney(validated.ask, validated.currency)}`,
    `Spread：${formatMoney(validated.spread, validated.currency)}`,
    `Greeks：Delta ${validated.delta !== null ? validated.delta.toFixed(3) : "未提供"} ｜ IV ${validated.iv !== null ? (validated.iv * 100).toFixed(1) + "%" : "未提供"}`,
    `市場深度：OI ${validated.oi !== null ? validated.oi : "未提供"} ｜ 成交量 ${validated.volume !== null ? validated.volume : "未提供"}`,
    `指派風險：${validated.assignment_risk}`,
    `流動性提示：${validated.liquidity_warning}`,
    `報價時間：${formatTaipeiTimestamp(validated.timestamp)}｜憑證：${validated.provenance}｜權利審查：${rightsZh(validated.rights_status)}`,
    "",
    "快捷指令：期權教學、期權試算說明、選單",
  ].filter(Boolean).join("\n");

  const messages: LineOutboundMessage[] = [{ type: "text", text }];
  assertLineMessages(messages);
  return messages;
}

// A diagnostic can exceed LINE's hard payload limits. Mark truncation; the text route retains more detail.
function clipDiagnostic(text: string, limit: number): string {
  if (text.length <= limit) return text;
  const chars = Array.from(text);
  return chars.length <= limit ? text : `${chars.slice(0, limit - 1).join("")}…`;
}

/** Old cached failure reasons are not valid statements about today's standard monthly screen.
 * Do not pretend to have refetched the chain; invalidate the obsolete diagnostic only. */
export function normalizeOptionsUnavailableReason(reason: string, period: "weekly" | "monthly" | null): string {
  if (period === "monthly" && /(?:21\s*[-–~至]\s*45|14\s*[-–~至]\s*60)\s*天/u.test(reason))
    return "此封存資料按已淘汰的月份天數窗產製；需重新核對最近距到期至少7天、第三個星期五或交易所假期調整的標準月選；不能據此推定未上市";
  if (/6\s*%\s*(?:年化|權利金|門檻)|年化[^。；]*6\s*%/u.test(reason))
    return "此封存觀察以已淘汰的6%策略收益門檻拒絕；須重新取得有日期的實際買賣報價，低於門檻應標示報價觀察，不能推定無上市期權";
  return reason;
}

export function optionsUnavailableReport(
  ticker: string,
  period: "weekly" | "monthly" | null,
  reason: string,
  isText = false,
): LineOutboundMessage[] {
  const periodLabel = period === "weekly" ? "每週期權" : period === "monthly" ? "每月期權" : "期權";
  const cleanReason = normalizeOptionsUnavailableReason(reason,period);
  // Only explicit expiry diagnostics; a date/age elsewhere is not an expiry.
  const expiryContext = cleanReason.includes("最近到期") ? cleanReason.slice(cleanReason.indexOf("最近到期"))
    : /本次回應有 \d{4}-\d{2}-\d{2}\s*[（(]\s*\d{1,4}\s*天\s*[）)](?:週選)?(?:上市)?買權/.exec(cleanReason)?.[0] ?? "";
  const listedExpiries = [...expiryContext.matchAll(/(\d{4}-\d{2}-\d{2})\s*[（(]\s*(\d{1,4})\s*天\s*[）)]/g)]
    .slice(0, 6).map(match => `${match[1]} · DTE ${match[2]}`);
  const title = `期權報價不可用 · ${ticker} ${periodLabel}`;
  const lines = [
    `【注意】查詢標的 ${ticker} 之 ${periodLabel} 目前無已封存驗收之公開報價。`,
    `原因說明：${clipDiagnostic(humanizeStatusText(cleanReason), 9000)}`,
    "系統嚴格拒絕使用模型推估、Black-Scholes 定價模型猜測或舊殘留快照冒充市場即時行情。",
    "無合格真實雙邊報價時，Strike、Bid/Mid/Ask、Delta、OI、Volume 等欄位維持未提供。",
    "您可使用下方「期權教學」查看標準策略教學卡片，或使用「期權試算說明」進行無持倉算術試算。",
  ];

  const actions: (readonly [string, string])[] = [];
  if (period === "weekly") {
    actions.push([`查 ${ticker} 每月期權`, `${ticker} 每月期權`]);
  } else if (period === "monthly") {
    actions.push([`查 ${ticker} 每週期權`, `${ticker} 每週期權`]);
  }
  actions.push(["期權策略教學", "期權教學"]);
  actions.push(["期權試算說明", "期權試算說明"]);
  actions.push(["TOP20 個股入口", "TOP20"]);
  actions.push(["回功能選單", "選單"]);

  if (isText) {
    const text = [
      `【${title}】`,
      ...lines,
      "",
      "快捷指令：",
      ...actions.map(([label, cmd]) => `• ${label}：${cmd}`),
    ].join("\n");
    // Keep long diagnostics readable across LINE's text-message limit.
    const messages: LineOutboundMessage[] = [];
    for (let start = 0; start < text.length;) {
      let end = Math.min(start + 4800, text.length);
      if (end < text.length && /[\uD800-\uDBFF]/.test(text[end - 1]!)) end--;
      messages.push({ type: "text", text: text.slice(start, end) });
      start = end;
    }
    assertLineMessages(messages);
    return messages;
  }

  const messages: LineOutboundMessage[] = [{
    type: "flex",
    altText: altSummary({ topic: title, status: "無已封存驗收之公開報價", next: actions[0]?.[0] ?? "期權策略教學" }),
    contents: {
      type: "carousel",
      contents: [{
        type: "bubble",
        size: "mega",
        header: menuBox([{ type: "text", size: "xs", wrap: true, contents: [
          { type: "span", text: "韭菜守護者 · 期權查詢\n", size: "xs", color: T.headerMuted },
          { type: "span", text: "期權報價不可用", size: "xl", color: T.headerText, weight: "bold" },
          { type: "span", text: `\n${ticker} ${periodLabel}｜嚴格無猜測`, size: "xs", color: T.headerAlert },
        ] }], { ...headerStyle }),
        body: uiBox([
          noticeBanner("caution", `暫無${period === "weekly" ? "每週" : period === "monthly" ? "每月" : ""}候選報價`,
            "無已驗收的封存報價；不以模型價格替代"),
          uiText("未驗收欄位維持未提供；不以舊報價或模型推算補齊", "xs", T.subtle),
          ...(listedExpiries.length ? [
            uiText("已列到期（非報價）", "xxs", T.subtle),
            ...Array.from({ length: Math.ceil(listedExpiries.length / 2) }, (_, index) =>
              uiBox(listedExpiries.slice(index * 2, index * 2 + 2).map(value => chip(value, T.soft, T.ink)),
                { layout: "horizontal", spacing: "sm" })),
          ] : []),
        ], { backgroundColor: T.paper, paddingAll: "lg", spacing: "sm" }),
        footer: menuBox([
          disclosureLine([`原因：${clipDiagnostic(humanizeStatusText(reason), 2000)}`, "拒用模型／Black-Scholes 猜價", "缺值欄位維持未提供", "非投資建議、不下單"]),
          ...actions.slice(0, 2).map(([label, cmd]) => menuAction(label, cmd)),
        ], { ...footerStyle }),
      }],
    },
  }];
  assertLineMessages(messages);
  return messages;
}
