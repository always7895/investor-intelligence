import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import { parseV213Top20Report, type V213Top20Report } from "./top20-report";

import { requirePublicCitation as safeCitation } from "./public-citation";

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
    `一、公司身分\n代號：${row.ticker}\n原文公司名稱：${row.name}\n行業：${row.industry}\n中文名稱／產品細項：本快照未提供已核對對照，不按代號猜譯或套用固定產業敘事。`,
    `二、歷史報酬口徑（不是未來預測）\n近兩年年化：${percent(row.long_term_return_pct)}\n近六個月：${percent(row.short_term_return_pct)}\n資料來源：${row.market_source}；調整收盤價口徑。\n兩年累積報酬：缺少實際起訖日期／價格，無法精確重算。不得直接把年化值乘二，也不把近兩年視為恰好兩年。含息再投資、稅費與匯率口徑未由此快照逐項核對。`,
    `三、快照所載的獲利與訂單資訊\n獲利摘要：${row.profit_summary}\n獲利來源標記：${row.profit_source}\n現有訂單：${row.current_orders}\n已載明的履約／認列展望：${row.future_orders_estimate}\n訂單資料日期：${row.orders_as_of || "未提供"}\n來源信心標記：${row.orders_confidence}\n摘要可能包含已披露的認列比例或期間，以上完整保留；文件日期不是交貨日，未披露確切履約日就不能猜日。\n逐筆訂單表尚未提供：須逐項核對客戶、合約類型、金額／數量／幣別、履約起訖與時間精度、取消條件、來源原文及修訂。RPO是剩餘履約義務，未必包含全部訂單；不得與backlog、預付款或已認列營收重複相加。來源標記不等於已驗證獨立佐證。`,
    "四、訂單轉成股價的分析缺口\n尚缺可重算鏈：逐期出貨／收入認列 → 利潤、稅、資本支出與營運資金 → 自由現金流及融資 → 稀釋後每股價值。每項假設需來源、日期、單位與適用期間；倍數需同時點可比依據，EV轉股權須扣淨負債及優先權益。\n情境價格報酬＝（情境每股價值／同時點參考股價－1）×100%；這是公式，不是已有足夠輸入。訂單增加不等於同幅度股價上升，不沿用寫死的樂觀漲幅。",
    ...["6 個月", "1 年", "2 年"].map(horizon => `${horizon}情境\n如期實現：尚無合格估值資料，不能給漲幅或目標價。\n延遲／部分實現：尚無合格敏感度資料，不能給小幅成長數字。\n未實現／失敗：尚無合格下檔估值，不能給損失比例。\n未估計不代表零報酬或沒有風險。`),
    "五、研究方法與來源追溯\n此入口只讀同輪七欄快照，未執行完整Serenity SKILL或即席模型研究。Serenity公開方法要求約束、有效替代供給、公司收益與融資稀釋的逐主張證據；Leopold Aschenbrenner只作CONTEXT_ONLY巨觀假設，不替公司訂單背書、不加分。\n以下區分現有訂單與展望的引用；同一公告的轉載不能算獨立證據。連結可供核查，並不表示本次已重新抓取全文。",
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
