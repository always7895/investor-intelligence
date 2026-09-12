import { parseQuery, type ParsedQuery } from "../core";
import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import { pinPublicSnapshot } from "./public-snapshot";
import { v213Top20LineAnswer } from "./top20-presentation";
import { loadV213FreshTop20Report, v213TimesAreFresh, V213_STALE_RECORDS_MESSAGE, type V213Top20Env } from "./top20-report";
import { LINE_THEME as T, menuAction, menuBox, menuText } from "./line-theme";

type Env = V213Top20Env & { V213_LINE_PRESENTATION?: string };
export const RICH_MENU_ACTIONS = Object.freeze([
  { label: "每日 TOP20 榜單", text: "TOP20" },
  { label: "宏觀產業分析", text: "宏觀產業分析" },
  { label: "期權與個股快查", text: "期權" },
]);
function panel(title: string, subtitle: string, paragraphs: readonly string[], actions: readonly (readonly [string, string])[]): LineOutboundMessage[] {
  const messages: LineOutboundMessage[] = [{ type: "flex", altText: `${title}｜${subtitle}`, contents: { type: "carousel", contents: [{
    type: "bubble", size: "mega",
    header: menuBox([menuText("韭菜守護者 · 公開研究", "xs", "#D4D4D4"),
      { ...menuText(title, "xl", T.paper), weight: "bold" }], { backgroundColor: T.ink, paddingAll: "lg" }),
    body: menuBox([menuText(subtitle, "sm", T.green), ...paragraphs.map(p => menuText(p))], { backgroundColor: T.paper, paddingAll: "lg" }),
    footer: menuBox(actions.map(([label, command]) => menuAction(label, command)), { backgroundColor: T.paleGreen, paddingAll: "md" }),
  }] } }];
  assertLineMessages(messages);
  return messages;
}
const NAV = RICH_MENU_ACTIONS.map(a => [a.label, a.text] as const);

/** Exact rich-menu commands only. Runs AFTER real LINE admission/rate limiting,
 * in the same request-pinned public view as Top20. No model or private fallback.
 * The industry panel is a portfolio-of-candidates count, not a macro forecast.
 */
export async function v213PublicLineAnswer(env: Env, query: ParsedQuery): Promise<LineOutboundMessage[] | string | null> {
  const command = query.normalized;
  if (/^(?:選單|菜单|menu|功能導覽|功能导航)$/i.test(command)) {
    return panel("研究功能導覽", "三個入口 · 不連券商 · 不自動下單", [
      "A｜TOP20：當輪20家公司、歷史報酬、量化訂單線索及同輪證據。歷史報酬不是未來預測。",
      "B｜宏觀產業分析：先看當輪產業分布，再核對宏觀指標與產業傳導；未驗收的宏觀數值不輸出。",
      "C｜期權與個股快查：依股票代號查每週／每月公開報價；無報價不捏造Strike、Delta或收益。",
    ], NAV);
  }
  if (/^(?:宏觀產業分析|宏观产业分析)(?:\s*文字)?$/i.test(command)) {
    const report = await loadV213FreshTop20Report(env, parseQuery("Top20"));
    const actions = [["TOP20 公司證據", "TOP20"], ["宏觀數據要求", "宏觀資料說明"], ["回功能選單", "選單"]] as const;
    if (!report || typeof report === "string") return panel("宏觀產業分析", "當輪產業資料不可用", [typeof report === "string" ? report : "TOP20_UNAVAILABLE", "不以舊快照、候選宏觀資料或模型猜測補齊。"], actions);
    if (!v213TimesAreFresh(env, report.records.map(r => r.retrieved_at))) return panel("宏觀產業分析", "公司資料過期", [V213_STALE_RECORDS_MESSAGE], actions);
    const sectors = new Map<string, string[]>();
    for (const row of report.records) sectors.set(row.industry, [...(sectors.get(row.industry) ?? []), row.ticker]);
    const groups = [...sectors].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
    const lines = [
      `當輪時間：${report.generated_at}；樣本20家公司。`,
      ...groups.map(([industry, tickers]) => `${industry}｜${tickers.length}/20家（${(tickers.length / 20 * 100).toFixed(0)}%）\n${tickers.join("、")}`),
      "以上是候選公司家數占比，不是市值／營收權重，也不代表全球產業排名或投資配置比例。",
      "MACRO_PRODUCT_NOT_SEALED：目前尚無已驗收的獨立宏觀報告。GDP、CPI、利率、匯率等值不得由來源健康狀態或候選資料直接升格發布。",
      "傳導框架：需求→交付／產能→營收及毛利→現金流／融資→每股價值；每條關係均須另有公司證據。",
    ];
    if (/文字$/.test(command)) {
      const messages: LineOutboundMessage[] = [{ type: "text", text: "宏觀產業分析｜當輪產業分布（不是完整宏觀報告）\n\n" + lines.join("\n\n") }];
      assertLineMessages(messages); return messages;
    }
    return panel("宏觀產業分析", "當輪產業分布 · 宏觀深度報告待驗收", lines,
      [["完整產業分布文字", "宏觀產業分析 文字"], ...actions]);
  }
  if (/^(?:宏觀資料說明|宏观资料说明)$/.test(command)) return panel("宏觀數據要求", "數值、期間、單位、發布日期必須分開", [
    "GDP：實質／名目及年度／季度口徑；CPI：指數水準不能當年增率；利率：政策利率不能當公司融資成本；匯率：必須有貨幣對與報價方向。",
    "保留原始來源、資料期、修訂、取得時間與再散布資格；World Bank、BLS、ECB來源健康不代表最新數值已完成驗收。",
    "Serenity是主要公開研究視角；Leopold為CONTEXT_ONLY。宏觀情境不能直接證明單一公司訂單、瓶頸或股價漲幅。",
  ], NAV);
  if (/^(?:期權|期权|選擇權|选择权|期權與個股快查|期权与个股快查|options?)$/i.test(command)) {
    const view = await pinPublicSnapshot(env);
    const rows = view.kind !== "invalid" ? await view.json<unknown>(["options:latest", "latest_options"]) : null;
    const status = Array.isArray(rows) && rows.length > 0
      ? "快照存在，但本頁未判定可用：進入報價查詢仍須逐標的freshness與報價門檻。"
      : "OPTION_DATA_UNAVAILABLE：目前沒有當輪可讀取的公開期權快照，不代表權利金為0或沒有風險。";
    return panel("期權與個股快查", "股票代號 → 每週／每月 → 報價與風險", [
      status,
      "查詢例：NVDA 每週期權、AAPL 每月期權（僅格式範例，不是推薦）。個股資訊請輸入股票代號；完整深度產品仍須封存驗收。",
      "有合格資料才顯示到期日/DTE、Strike、Bid/Mid/Ask、Delta、OI/Volume及年化收益；限價與中間價不保證成交。",
      "無自動報價時可用「期權試算說明」做本次輸入的算術試算；結果標示未驗證，不存持倉、不連IBKR、不下單。",
    ], [["查公開期權報價", "最新期權"], ["期權試算說明", "期權試算說明"], ["TOP20 個股入口", "TOP20"], ["回功能選單", "選單"]]);
  }
  return v213Top20LineAnswer(env, query);
}
