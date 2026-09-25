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
import { LINE_THEME as T, menuAction, menuBox, menuText, headerStyle, footerStyle } from "./line-theme";
import type { OptionContractQuote } from "./market-product-schema";
import { validateOptionContractQuote } from "./market-product-schema";

export const OPTIONS_PRODUCT_KEY = "v213:options-chain:latest";

function formatMoney(val: number): string {
  return `$${val.toFixed(2)}`;
}

export function buildOptionContractBubble(quote: OptionContractQuote) {
  const greeksStr = [
    `Delta: ${quote.delta !== null ? quote.delta.toFixed(3) : "UNAVAILABLE"}`,
    `IV: ${quote.iv !== null ? (quote.iv * 100).toFixed(1) + "%" : "UNAVAILABLE"}`,
  ].join("｜");

  const liquidityStr = [
    `OI: ${quote.oi !== null ? quote.oi : "UNAVAILABLE"}`,
    `成交量: ${quote.volume !== null ? quote.volume : "UNAVAILABLE"}`,
  ].join("｜");

  const nonexecTag = quote.quote_basis !== "realtime"
    ? "【非即時可執行報價 · 僅供參考】"
    : "【即時參考報價】";

  return {
    type: "bubble",
    size: "mega",
    header: menuBox([
      menuText(`公開期權報價 · 逐約核驗 ${nonexecTag}`, "xs", T.headerMuted),
      { ...menuText(`${quote.ticker} ${quote.expiry} ${quote.strike}${quote.type.toUpperCase()}`, "lg", T.headerText), weight: "bold" },
      menuText(`DTE: ${quote.dte} 天｜基準：${quote.quote_basis}｜幣別：${quote.currency}（乘數 ${quote.multiplier} 股/口）`, "xs", T.headerSubtle),
    ], { ...headerStyle }),
    body: menuBox([
      menuBox([
        menuText("雙邊行情與價差", "xs", T.muted),
        menuText(`Bid ${formatMoney(quote.bid)} ｜ Mid ${formatMoney(quote.mid)} ｜ Ask ${formatMoney(quote.ask)}`, "sm", T.ink),
        menuText(`Spread: ${formatMoney(quote.spread)}（未驗證委託保證成交）`, "xs", T.muted),
      ], { backgroundColor: T.soft, paddingAll: "sm", cornerRadius: "sm" }),
      menuBox([
        menuText("關鍵損益指標（需搭配具體策略與持倉成本）", "xs", T.muted),
        menuText("損益平衡：UNAVAILABLE（無定義策略）", "xs", T.ink),
        menuText("最大利潤：UNAVAILABLE（無定義策略）", "xs", T.ink),
        menuText("最大損失：UNAVAILABLE（無定義策略）", "xs", T.negative),
      ], { spacing: "xs" }),
      { type: "separator", color: T.border },
      menuBox([
        menuText("Greeks 與流動性", "xs", T.muted),
        menuText(greeksStr, "xs", T.ink),
        menuText(liquidityStr, "xs", T.ink),
      ], { spacing: "xs" }),
      menuBox([
        menuText("履約與流動性警語", "xs", T.muted),
        menuText(`• ${quote.assignment_risk}`, "xxs", T.muted),
        menuText(`• ${quote.liquidity_warning}`, "xxs", T.muted),
      ], { backgroundColor: T.soft, paddingAll: "sm", cornerRadius: "sm", borderColor: T.frame, borderWidth: "light" }),
    ], { paddingAll: "lg", spacing: "sm", backgroundColor: T.paper }),
    footer: menuBox([
      menuText(`時間戳記：${quote.timestamp}｜來源：${quote.source}｜憑證：${quote.provenance}｜權利：${quote.rights_status}`, "xxs", T.muted),
      menuText("本資料為公開行情觀察，非個人化投資建議、無委託下單功能。", "xxs", T.muted),
      menuAction("查看期權策略教學", "期權教學"),
      menuAction("回功能選單", "選單"),
    ], { paddingAll: "md", backgroundColor: T.soft }),
  };
}

export function buildOptionContractFlex(quote: OptionContractQuote, validationOptions?: Parameters<typeof validateOptionContractQuote>[1]): LineOutboundMessage[] {
  const validated = validateOptionContractQuote(quote, validationOptions);
  const bubble = buildOptionContractBubble(validated);
  const messages: LineOutboundMessage[] = [{
    type: "flex",
    altText: `期權報價：${validated.ticker} ${validated.expiry} ${validated.strike}${validated.type.toUpperCase()}`,
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
  const nonexecTag = validated.quote_basis !== "realtime"
    ? "【非即時可執行報價 · 僅供參考】"
    : "【即時參考報價】";

  const text = [
    `【公開期權合約報價】${validated.ticker} ${validated.expiry} ${validated.strike}${validated.type.toUpperCase()}`,
    `報價性質：${nonexecTag}`,
    `DTE：${validated.dte} 天｜基準：${validated.quote_basis}｜來源：${validated.source}｜幣別：${validated.currency}（乘數 ${validated.multiplier}）`,
    `行情：Bid ${formatMoney(validated.bid)} ｜ Mid ${formatMoney(validated.mid)} ｜ Ask ${formatMoney(validated.ask)}`,
    `Spread：${formatMoney(validated.spread)}`,
    "損益平衡：UNAVAILABLE（無定義策略）",
    "最大利潤：UNAVAILABLE（無定義策略） ｜ 最大損失：UNAVAILABLE（無定義策略）",
    `Greeks：Delta ${validated.delta !== null ? validated.delta.toFixed(3) : "UNAVAILABLE"} ｜ IV ${validated.iv !== null ? (validated.iv * 100).toFixed(1) + "%" : "UNAVAILABLE"}`,
    `市場深度：OI ${validated.oi !== null ? validated.oi : "UNAVAILABLE"} ｜ 成交量 ${validated.volume !== null ? validated.volume : "UNAVAILABLE"}`,
    `指派風險：${validated.assignment_risk}`,
    `流動性提示：${validated.liquidity_warning}`,
    `報價時間：${validated.timestamp}｜憑證：${validated.provenance}｜權利審查：${validated.rights_status}`,
    "",
    "快捷指令：期權教學、期權試算說明、選單",
  ].filter(Boolean).join("\n");

  const messages: LineOutboundMessage[] = [{ type: "text", text }];
  assertLineMessages(messages);
  return messages;
}

export function optionsUnavailableReport(
  ticker: string,
  period: "weekly" | "monthly" | null,
  reason: string,
  isText = false,
): LineOutboundMessage[] {
  const periodLabel = period === "weekly" ? "每週期權" : period === "monthly" ? "每月期權" : "期權";
  const title = `期權報價不可用 · ${ticker} ${periodLabel}`;
  const lines = [
    `OPTION_DATA_UNAVAILABLE：查詢標的 ${ticker} 之 ${periodLabel} 目前無已封存驗收之公開報價。`,
    `原因說明：${reason}`,
    "系統嚴格拒絕使用模型推估、Black-Scholes 定價模型猜測或舊殘留快照冒充市場即時行情。",
    "無合格真實雙邊報價時，Strike、Bid/Mid/Ask、Delta、OI、Volume 等欄位維持 UNAVAILABLE。",
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
          menuText("韭菜守護者 · 期權查詢", "xs", T.headerMuted),
          { ...menuText("期權報價不可用", "xl", T.headerText), weight: "bold" },
          menuText(`${ticker} ${periodLabel}｜嚴格無猜測`, "xs", T.headerAlert),
        ], { ...headerStyle }),
        body: menuBox(lines.map(p => menuText(p, "sm", T.ink)), { backgroundColor: T.paper, paddingAll: "lg" }),
        footer: menuBox(actions.slice(0, 4).map(([label, cmd]) => menuAction(label, cmd)), { ...footerStyle }),
      }],
    },
  }];
  assertLineMessages(messages);
  return messages;
}
