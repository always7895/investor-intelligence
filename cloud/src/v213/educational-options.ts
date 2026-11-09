/**
 * Four Standalone Educational Strategy Cards.
 * Mandatory even when live market quotes are unavailable.
 * Strictly SYNTHETIC / EDUCATIONAL, never real market quotes, recommendations,
 * broker execution, or stored public market datasets. Zero private/network reads.
 */

import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import { LINE_THEME as T, altSummary, detailsButton, disclosureGroups, menuAction, menuBox, menuText, headerStyle, uiBox } from "./line-theme";
import type { OptionEducationalStrategyCard } from "./market-product-schema";

export const EDUCATIONAL_DISCLAIMER = "教學範例，非推薦" as const;
export const EDUCATIONAL_STATUS = "SYNTHETIC_EDUCATIONAL" as const;
export const SIMULATED_AS_OF = "2026-09-14T00:00:00Z" as const;

export const EDUCATIONAL_STRATEGIES: readonly OptionEducationalStrategyCard[] = Object.freeze([
  {
    strategy_id: "covered_call",
    strategy_name: "Covered Call（掩護性買權 / 現股配買權）",
    illustrative_ticker: "EXAMPLE",
    expiry_dte: "30天（DTE 30）",
    strikes: "持有現股成本 $100，賣出 1 口 $105 Call（權利金收 $3.00）",
    debit_credit: "淨收入權利金 $3.00/股（每口合約收 $300.00）",
    breakeven: "$97.00/股（購買成本 $100.00 扣除收取之權利金 $3.00）",
    maxprofit: "$8.00/股（每口合約 $800.00；履約價差 $5.00 + 權利金 $3.00）",
    maxloss: "$97.00/股（每口合約 $9,700.00；若標的股價歸零）",
    assignment_exercise_risk: "若股價高於 $105，買權將被履約指派，必須依 $105 出售持有之 100 股現股，無法享有 $105 以上漲幅。",
    appropriate_scenarios: "中性偏溫和看多，預期標的股價緩漲或區間震盪，希望藉由賣出買權收取權利金提高總收益。",
    inappropriate_scenarios: "強烈看多（股價大幅上漲時收益被封頂截斷），或強烈看空（僅 $3 權利金緩衝，無法防範股價大幅下跌虧損）。",
    disclaimer: EDUCATIONAL_DISCLAIMER,
    status: EDUCATIONAL_STATUS,
    simulated_as_of: SIMULATED_AS_OF,
    payoff_reference: {
      underlying_cost_basis: 100.0,
      contract_multiplier: 100,
      strike: 105.0,
      premium: 3.0,
      breakeven_price: 97.0,
      max_profit_amount: 800.0,
      max_loss_amount: 9700.0,
      net_credit_debit: 300.0,
    },
    assumptions: {
      quantity_multiplier: "標準美股選擇權 1 口合約 = 100 股現股。",
      cost_basis: "假定現股買入成本為 $100.00/股（100 股本金 $10,000.00）。",
      collateral: "以持有之 100 股現股作為完全掩護擔保，無保證金追繳壓力。",
      premium_fees: "假定收取權利金 $3.00/股，未計手續費、交易所規費與滑價成本。",
      exercise_assignment_tax: "到期美式選擇權可提前指派；履約處分現股可能產生資本利得或股利稅負。",
      specific_caveats: "掩護性買權之上檔收益封頂，下檔僅有收受權利金提供極有限緩衝，仍承擔實質現股下行風險。",
    },
  },
  {
    strategy_id: "cash_secured_put",
    strategy_name: "Cash-Secured Put（現金擔保賣出賣權）",
    illustrative_ticker: "EXAMPLE",
    expiry_dte: "30天（DTE 30）",
    strikes: "賣出 1 口 $90 Put（收取權利金 $2.50），現價 $100",
    debit_credit: "淨收入權利金 $2.50/股（每口合約收 $250.00）",
    breakeven: "$87.50/股（履約價 $90.00 扣除收取之權利金 $2.50）",
    maxprofit: "$2.50/股（每口合約 $250.00；最大利潤即為全數保留權利金）",
    maxloss: "$87.50/股（每口合約 $8,750.00；若標的股價跌至 $0 歸零）",
    assignment_exercise_risk: "若到期股價跌破 $90，買方行使賣權，賣方必須依 $90.00 買入 100 股現股（扣除權利金實際持股成本 $87.50）。",
    appropriate_scenarios: "中性偏溫和看多，樂意在特定折價價位（$90）買入該股票，並於等待期間收取權利金增強收益。",
    inappropriate_scenarios: "強烈看空（被迫高於市價接刀接盤承擔巨額虧損），或無意持有標的股票。",
    disclaimer: EDUCATIONAL_DISCLAIMER,
    status: EDUCATIONAL_STATUS,
    simulated_as_of: SIMULATED_AS_OF,
    payoff_reference: {
      underlying_cost_basis: 100.0,
      contract_multiplier: 100,
      strike: 90.0,
      premium: 2.5,
      breakeven_price: 87.5,
      max_profit_amount: 250.0,
      max_loss_amount: 8750.0,
      net_credit_debit: 250.0,
    },
    assumptions: {
      quantity_multiplier: "標準美股選擇權 1 口合約 = 100 股現股。",
      cost_basis: "若被指派，每股有效取得成本為 $90.00 - $2.50 = $87.50/股。",
      collateral: "必須準備 100% 全額現金擔保 $9,000.00（$90 × 100 股），凍結於帳戶不得挪作他用。",
      premium_fees: "假定收取權利金 $2.50/股，未計利息機會成本、交易手續費與稅金。",
      exercise_assignment_tax: "到期日實值賣權將由 OCC 自動執行指派；接股後轉為現股多頭部位。",
      specific_caveats: "現金擔保賣權要求鎖定全額現金，存在資金機會成本；下檔實質承擔接股後跌至 0 的巨大風險。",
    },
  },
  {
    strategy_id: "bull_call_spread",
    strategy_name: "Bull Call Spread（買權多頭價差 / Debit Spread）",
    illustrative_ticker: "EXAMPLE",
    expiry_dte: "30天（DTE 30）",
    strikes: "買入 1 口 $100 Call（付 $4.00）+ 賣出 1 口 $110 Call（收 $1.50）",
    debit_credit: "淨付出權利金 $2.50/股（Net Debit，每口合約付 $250.00）",
    breakeven: "$102.50/股（低履約價 $100.00 + 淨權利金成本 $2.50）",
    maxprofit: "$7.50/股（每口合約 $750.00；價差寬度 $10.00 扣除淨成本 $2.50）",
    maxloss: "$2.50/股（每口合約 $250.00；標的股價 <= $100 時全數損失權利金）",
    assignment_exercise_risk: "短腿 $110 Call 若被提前行使（尤其除息日前夕），將面臨空頭指派風險；到期股價落在兩履約價之間存在 Pin Risk。",
    appropriate_scenarios: "溫和看多至履約價 $110 附近，希望以明確受控的有限風險降低單買買權的高昂權利金負擔。",
    inappropriate_scenarios: "強烈暴漲預期（$110 以上漲幅完全無法獲利），或行情橫盤／下跌（支付的 Debit 淨成本全損）。",
    disclaimer: EDUCATIONAL_DISCLAIMER,
    status: EDUCATIONAL_STATUS,
    simulated_as_of: SIMULATED_AS_OF,
    payoff_reference: {
      underlying_cost_basis: 100.0,
      contract_multiplier: 100,
      strike: 100.0,
      premium: 2.5,
      breakeven_price: 102.5,
      max_profit_amount: 750.0,
      max_loss_amount: 250.0,
      net_credit_debit: -250.0,
    },
    assumptions: {
      quantity_multiplier: "1 口垂直價差 = 同時買進與賣出各 1 口同月份不同履約價之合約（對應 100 股）。",
      cost_basis: "開倉最大淨支出為 $2.50/股（合約 $250.00）。",
      collateral: "作為淨支出型垂直價差（Debit Spread），不需額外保證金，已支付權利金即為最大風險。",
      premium_fees: "兩腿各有一筆買進與賣出交易手續費與價差滑價摩擦成本。",
      exercise_assignment_tax: "雙腿組合可能因各腿不同時平倉引發提前指派、交割不對稱與洗售規則（Wash Sale）稅務影響。",
      specific_caveats: "價差交易涉及雙腿成交滑價；短腿提前指派與到期履約不對稱可能引發保證金衝擊（Legging Risk）。",
    },
  },
  {
    strategy_id: "protective_put",
    strategy_name: "Protective Put（保護性賣權 / Married Put 現股配賣權）",
    illustrative_ticker: "EXAMPLE",
    expiry_dte: "30天（DTE 30）",
    strikes: "持有現股 $100，買入 1 口 $95 Put 作為保險（權利金付出 $3.00）",
    debit_credit: "淨付出權利金 $3.00/股（每口保險費用 $300.00）",
    breakeven: "$103.00/股（現股成本 $100.00 + 買權利金保險成本 $3.00）",
    maxprofit: "UNBOUNDED（理論無限）",
    maxloss: "$8.00/股（每口合約 $800.00；現股跌幅由 $100 至 $95 損失 $5.00 + 保險費 $3.00）",
    assignment_exercise_risk: "買方擁有賣出股票的權利而非義務。若股價跌破 $95，可主動行使賣權以 $95 賣出股票止損，無被動指派風險。",
    appropriate_scenarios: "長期堅定看多標的，但面臨短期重大事件不確定性（如財報或宏觀危機），願支付確定保險費鎖定最大下檔虧損。",
    inappropriate_scenarios: "低波動率橫盤整理市場；持續購買賣權將產生嚴重的時間價值損耗（Premium Drag），侵蝕長期投資組合回報。",
    disclaimer: EDUCATIONAL_DISCLAIMER,
    status: EDUCATIONAL_STATUS,
    simulated_as_of: SIMULATED_AS_OF,
    payoff_reference: {
      underlying_cost_basis: 100.0,
      contract_multiplier: 100,
      strike: 95.0,
      premium: 3.0,
      breakeven_price: 103.0,
      max_profit_amount: "UNBOUNDED",
      max_loss_amount: 800.0,
      net_credit_debit: -300.0,
    },
    assumptions: {
      quantity_multiplier: "1 口保護性賣權對應 100 股長線持有之現股。",
      cost_basis: "現股成本 $100.00/股，加計保險成本後保本門檻為 $103.00/股。",
      collateral: "現股全額持有，支付賣權權利金即可，無衍生品空頭保證金需求。",
      premium_fees: "假定付出權利金 $3.00/股，未計手續費；保險到期未行使則權利金全損。",
      exercise_assignment_tax: "若行使賣權出售現股，賣出價格視為 $95 扣除（或加計）相關權利金規定計算資本損益。",
      specific_caveats: "保護性賣權存在長期時間耗損（Premium Drag）；若持續滾動避險，即使股價不跌，淨資產仍會因保費支出持續減少。",
    },
  },
]);


function wrapFlexRow(text: string, max = 40): string {
  const lines: string[] = [];
  let line = "";
  for (const part of text.split(/(?<=\s)|(?<=[｜，；。+])/u).filter(Boolean)) {
    if (Array.from(line + part).length <= max) { line += part; continue; }
    if (line) lines.push(line.trimEnd());
    line = part.trimStart();
    while (Array.from(line).length > max) {
      const points = Array.from(line);
      lines.push(points.slice(0, max).join(""));
      line = points.slice(max).join("");
    }
  }
  if (line) lines.push(line.trimEnd());
  return lines.join("\n");
}

function riskDisclosure(card: OptionEducationalStrategyCard): string {
  switch (card.strategy_id) {
    case "covered_call": return "手續費、規費與滑價未計；美式買權可提前指派並可能涉稅；上檔封頂、權利金緩衝有限，仍承受正股下行。";
    case "cash_secured_put": return "未計利息機會成本、手續費與稅；到期實值賣權由OCC自動指派接股；全額現金鎖定，接股後可能跌至$0。";
    case "bull_call_spread": return "兩腿計手續費與滑價；短腿$110 Call可提前指派；到期介於履約價有 Pin Risk、交割不對稱及 Wash Sale／保證金風險。";
    case "protective_put": return "未計手續費；未行使則權利金全損；行使按$95售股；長期滾動耗損，持續保費可令淨資產減少。";
  }
}

function cardToBubble(card: OptionEducationalStrategyCard) {
  const net = card.payoff_reference.net_credit_debit;
  const profit = card.payoff_reference.max_profit_amount === "UNBOUNDED"
    ? "UNBOUNDED（理論無限）" : `$${card.payoff_reference.max_profit_amount.toFixed(2)}/口`;
  const architecture = `${card.strikes}${card.strategy_id === "bull_call_spread" ? "；每口100股" : ""}`;
  const status = `${card.status}（模擬基準日：${card.simulated_as_of}）；合成教學假設；非報價、非投資建議、不下單`;
  const contract = card.strategy_id === "covered_call" ? "持有100股擔保；每口對應100股；費用與稅務細節見文字版"
    : card.strategy_id === "cash_secured_put" ? `${card.assumptions.collateral}；每口${card.payoff_reference.contract_multiplier}股；機會成本見文字版`
      : card.strategy_id === "bull_call_spread" ? "兩腿各1口、同月不同履約價；乘數100股；淨權利金為最大虧損"
        : "持有100股並買進1口Put；支付保費；未行使則權利金全損";
  const risk = riskDisclosure(card);
  return {
    type: "bubble",
    size: "mega",
    header: menuBox([
      menuText(`【${card.disclaimer}】`, "xs", T.headerMuted),
      { ...menuText(card.strategy_name, "md", T.headerText), weight: "bold" },
      menuText(`模擬標的：${card.illustrative_ticker}｜${card.expiry_dte}`, "xs", T.headerMuted),
    ], { ...headerStyle }),
    body: uiBox([
      uiBox([
        menuText(wrapFlexRow(architecture), "xs", T.ink),
        menuText(wrapFlexRow(`淨${net >= 0 ? "收" : "付"} $${Math.abs(net).toFixed(2)}/口｜損平 $${card.payoff_reference.breakeven_price.toFixed(2)}/股`), "xs", T.ink),
        menuText(wrapFlexRow(`獲利 ${profit}｜最大損失 $${card.payoff_reference.max_loss_amount.toFixed(2)}/口`), "xs", T.ink),
      ], { spacing: "sm" }),
    ], { paddingAll: "lg", spacing: "sm", backgroundColor: T.paper }),
    footer: uiBox([
      ...disclosureGroups([
        { label: "狀態", text: status },
        { label: "合約", text: contract },
        { label: "風險", text: risk },
      ]),
      detailsButton("查看適用情境與假設", `期權教學 ${card.strategy_id} 文字`),
      menuAction("範例：NVDA 每月期權", "NVDA 每月期權"),
    ], { paddingAll: "md", spacing: "sm", backgroundColor: T.soft }),
  };
}

export function buildEducationalStrategyFlex(
  strategyId?: "covered_call" | "cash_secured_put" | "bull_call_spread" | "protective_put",
): LineOutboundMessage[] {
  const cards = strategyId
    ? EDUCATIONAL_STRATEGIES.filter(c => c.strategy_id === strategyId)
    : EDUCATIONAL_STRATEGIES;

  if (cards.length === 0) throw new Error("UNKNOWN_STRATEGY_ID");

  const bubbles = cards.map(cardToBubble);
  // LINE Flex carousel allows at most 5 bubbles in assertLineMessages
  const messages: LineOutboundMessage[] = [{
    type: "flex",
    altText: altSummary({ topic: cards.length === 1 ? `${cards[0]!.strategy_name.split("（")[0]} 期權策略教學` : `期權策略教學範例（共${cards.length}種）`,
      status: EDUCATIONAL_DISCLAIMER, next: "點選查看適用情境與假設" }),
    contents: {
      type: "carousel",
      contents: bubbles,
    },
  }];
  assertLineMessages(messages);
  return messages;
}

export function buildEducationalStrategyText(
  strategyId?: "covered_call" | "cash_secured_put" | "bull_call_spread" | "protective_put",
): LineOutboundMessage[] {
  const cards = strategyId
    ? EDUCATIONAL_STRATEGIES.filter(c => c.strategy_id === strategyId)
    : EDUCATIONAL_STRATEGIES;

  if (cards.length === 0) throw new Error("UNKNOWN_STRATEGY_ID");

  const chunks: string[] = [];
  for (const card of cards) {
    const lines = [
      `【${card.disclaimer}】${card.strategy_name}`,
      `狀態：${card.status}｜模擬基準日：${card.simulated_as_of}`,
      `標的與週期：${card.illustrative_ticker}｜${card.expiry_dte}`,
      `架構：${card.strikes}`,
      `淨收支：${card.debit_credit}`,
      `損益平衡：${card.breakeven}`,
      `最大獲利：${card.maxprofit}`,
      `最大損失：${card.maxloss}`,
      `算術驗證參考：現股成本 $${card.payoff_reference.underlying_cost_basis.toFixed(2)}｜合約乘數 ${card.payoff_reference.contract_multiplier} 股｜損益平衡價 $${card.payoff_reference.breakeven_price.toFixed(2)}`,
      `履約與指派風險：${card.assignment_exercise_risk}`,
      `適用情境：${card.appropriate_scenarios}`,
      `不適用情境：${card.inappropriate_scenarios}`,
      "假設與限制：",
      `• 合約單位：${card.assumptions.quantity_multiplier}`,
      `• 成本與擔保：${card.assumptions.cost_basis}；${card.assumptions.collateral}`,
      `• 稅費與摩擦：${card.assumptions.premium_fees}；${card.assumptions.exercise_assignment_tax}`,
      `• 策略特有風險：${card.assumptions.specific_caveats}`,
      "───",
      "本內容僅為選擇權原理與算術教學，絕非投資建議、行情快照或下單指示。",
      "快捷指令：代號 每月期權（例：NVDA 每月期權）、期權試算說明、選單",
    ];
    chunks.push(lines.join("\n"));
  }

  // Ensure chunks fit within 5 messages and 4900 characters per message
  if (chunks.length > 5) throw new Error("EDUCATIONAL_TEXT_EXCEEDS_5_MESSAGES");
  for (const chunk of chunks) {
    if (chunk.length > 4900) throw new Error("EDUCATIONAL_TEXT_CHUNK_TOO_LARGE");
  }

  const messages: LineOutboundMessage[] = chunks.map(text => ({ type: "text", text }));
  assertLineMessages(messages);
  return messages;
}
