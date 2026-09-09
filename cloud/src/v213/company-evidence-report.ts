import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import { parseV213Top20Report, type V213Top20Report } from "./top20-report";

function safeCitation(value: string): string {
  const url = new URL(value);
  let credentialParameter = false;
  const inspect = (_value: string, key: string) => {
    if (/(?:access[_-]?token|api[_-]?key|authorization|password|secret|signature)/i.test(key)) credentialParameter = true;
  };
  url.searchParams.forEach(inspect);
  new URLSearchParams(url.hash.slice(1)).forEach(inspect);
  if (credentialParameter || url.protocol !== "https:" || url.username || url.password ||
      (url.port && url.port !== "443") || !url.hostname.includes(".") ||
      /^[\d.]+$/.test(url.hostname) || /\.(local|localhost)$/i.test(url.hostname) ||
      /[\s\u0000-\u001f]/.test(value) ||
      /(?:access_token|api_key|apikey|authorization|password|secret|signature)=/i.test(value)) {
    throw new Error("UNSAFE_REPORT_CITATION");
  }
  return value;
}

/** Evidence inspection, NOT a fabricated valuation report from seven short fields. */
export function buildCompanyEvidenceMessages(
  report: V213Top20Report, ticker: string,
): LineOutboundMessage[] {
  const validated = parseV213Top20Report(report);
  const row = validated?.records.find(item => item.ticker === ticker);
  if (!validated || !row) throw new Error("REPORT_CONTEXT_INVALID");
  const percent = (value: number | null) => value === null ? "未提供" : `${value.toFixed(1)}%`;
  const current = [...new Set(row.current_order_source_urls.map(safeCitation))];
  const future = [...new Set(row.future_order_source_urls.map(safeCitation))];
  const blocks = [
    `${row.ticker}｜本輪 Top20 #${row.rank}｜證據詳情\n資料層級：七欄快照，尚非完整深度估值報告。\n快照產生：${report.generated_at}\n資料取得：${row.retrieved_at}`,
    `一、公司身分\n代號：${row.ticker}\n行業：${row.industry}\n中文名稱／原文法定名稱：本契約未提供已核對對照，不按代號猜譯。`,
    `二、歷史報酬口徑（不是未來預測）\n近兩年年化：${percent(row.long_term_return_pct)}\n近六個月：${percent(row.short_term_return_pct)}\n資料來源：${row.market_source}；調整收盤價口徑。\n兩年累積報酬：缺少實際起訖日期／價格，無法精確重算。不得直接把年化值乘二，也不把近兩年視為恰好兩年。含息再投資、稅費與匯率口徑未由此快照逐項核對。`,
    `三、快照所載的獲利與訂單資訊\n獲利摘要：${row.profit_summary}\n獲利來源標記：${row.profit_source}\n現有訂單：${row.current_orders}\n未來訂單展望：${row.future_orders_estimate}\n訂單資料日期：${row.orders_as_of || "未提供"}\n來源信心標記：${row.orders_confidence}\n此快照未提供可逐項重算的訂單表、履約／取消條件或收入認列時程；不把摘要中的金額相加成總訂單。來源標記不等於已驗證獨立佐證。`,
    "四、訂單轉成股價的分析缺口\n尚缺：出貨及收入認列時程、毛利／營業利潤、稅負、資本支出與現金流、稀釋後股數，以及各情境估值基準。訂單增加不等於同幅度股價上升。",
    ...["6 個月", "1 年", "2 年"].map(horizon => `${horizon}情境\n如期實現：尚無合格估值資料，不能給漲幅或目標價。\n延遲／部分實現：尚無合格敏感度資料，不能給小幅成長數字。\n未實現／失敗：尚無合格下檔估值，不能給損失比例。\n未估計不代表零報酬或沒有風險。`),
    "五、來源追溯\n以下區分現有訂單與展望的引用；同一公告的轉載不能算獨立證據。連結可供核查，並不表示本次已重新抓取全文。",
    ...(current.length ? current.map(url => `現有訂單來源：${url}`) : ["現有訂單：沒有可追溯來源連結。"]),
    ...(future.length ? future.map(url => `未來展望來源：${url}`) : ["未來展望：沒有可追溯來源連結。"]),
    "結論：這份報告列出快照資料、口徑與缺口，不生成沒有數據支撐的預測。完整研究必須補齊身分、財報、訂單／供給約束、獨立佐證與可重算情境，並通過同輪封存驗證。",
  ];
  const messages: LineOutboundMessage[] = [];
  let chunk = "";
  for (const block of blocks) {
    if (block.length > 4800) throw new Error("REPORT_SECTION_TOO_LARGE");
    if (chunk && chunk.length + block.length + 2 > 4800) {
      messages.push({ type: "text", text: chunk }); chunk = "";
    }
    chunk += (chunk ? "\n\n" : "") + block;
  }
  if (chunk) messages.push({ type: "text", text: chunk });
  assertLineMessages(messages);
  return messages;
}
