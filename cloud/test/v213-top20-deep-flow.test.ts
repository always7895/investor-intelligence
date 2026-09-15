import { afterEach, describe, expect, it, vi } from "vitest";
import { assertLineMessages } from "../src/line-messages";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { parseQuery } from "../src/core";
import {
  parseV213Top20Report,
  V213_NO_CURRENT_ORDERS,
  V213_NO_FUTURE_ORDER_ESTIMATE,
  V213_TOP20_DISPLAY_COLUMNS,
} from "../src/v213/top20-report";
import { validateTwoYearReturnEvidence, type TwoYearReturnEvidence } from "../src/v213/top20-return-evidence";
import { buildTop20DeepAnalysisMessages } from "../src/v213/deep-analysis";
import { asKv, MemoryKv } from "./fake-kv";
import { SNAPSHOT_OBJECT_KEYS, SNAPSHOT_SEAL_KEY, buildSnapshotSeal } from "../src/v213/snapshot-seal";
import sealContract from "../../config/v213-r75-publication-mode-v1.json";

function makeReturnEvidence(ticker: string, overrides: Partial<TwoYearReturnEvidence> = {}): TwoYearReturnEvidence {
  return {
    ticker,
    window: "two_year",
    actual_start: "2024-09-09",
    actual_end: "2026-09-09",
    start_adjusted_close: 80.0,
    end_adjusted_close: 120.0,
    elapsed_days: 730,
    total_return_pct: 50.0,
    market_source: "yfinance",
    basis: "adjusted_close",
    dividend_split_semantics: "auto_adjusted",
    ...overrides,
  };
}

async function fixture(opts: { withReturnEvidence?: boolean } = {}) {
  const publicKv = new MemoryKv();
  const stamp = new Date().toISOString();
  const report = {
    schema_version: 2,
    product_version: "2.1.3",
    generated_at: stamp,
    display_columns: V213_TOP20_DISPLAY_COLUMNS,
    long_term_definition: "trailing_2y_adjusted_close_cagr",
    short_term_definition: "trailing_6m_adjusted_close_price_return",
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
    records: Array.from({ length: 20 }, (_, i) => {
      const ticker = `T${i.toString().padStart(2, "0")}`;
      const rec: any = {
        schema_version: 2,
        rank: i + 1,
        ticker,
        name: `Synthetic Bottleneck Co ${i}`,
        industry: i < 10 ? "半導體材料" : "光電元件",
        profit_summary: "獲利；營收年增 +18.5%，營業利益率 22.3%",
        current_orders: i === 0 ? "2027年固定交付合約 2.5 億美元" : V213_NO_CURRENT_ORDERS,
        future_orders_estimate: i === 0 ? "客戶擴產需求強勁但不預估總額" : V213_NO_FUTURE_ORDER_ESTIMATE,
        long_term_return_pct: 22.5,
        short_term_return_pct: 10.0,
        long_term_window: "2y_cagr",
        short_term_window: "6m_price_return",
        market_source: "yfinance",
        profit_source: "sec_edgar",
        orders_as_of: stamp,
        orders_confidence: i === 0 ? "EVIDENCE_BOUND" : "UNAVAILABLE",
        current_order_source_urls: i === 0 ? ["https://www.sec.gov/Archives/edgar/data/example/current"] : [],
        future_order_source_urls: i === 0 ? ["https://www.sec.gov/Archives/edgar/data/example/future"] : [],
        numeric_total_order_estimate_prohibited: true,
        retrieved_at: stamp,
        provider_scope: "public_only",
        owner_watchlist_inherited: false,
      };
      if (opts.withReturnEvidence && i === 0) {
        rec.two_year_total_return_pct = 50.0;
        rec.two_year_return_evidence = makeReturnEvidence(ticker);
      }
      return rec;
    }),
  };

  const save = async () => {
    const RUN_ID = "20260910T100000Z-123456789abc";
    const TX_ID = "1".repeat(32);
    const bodies: [string, string][] = SNAPSHOT_OBJECT_KEYS.map(key => [key, JSON.stringify({ synthetic: key })]);
    bodies.find(([key]) => key === "last_successful_pipeline_timestamp")![1] = report.generated_at;
    bodies.find(([key]) => key === "v213:top20-report:latest")![1] = JSON.stringify(report);
    bodies.find(([key]) => key === "v213:activation-claim")![1] = JSON.stringify({ schema_version: 1, transaction_id: TX_ID, run_id: RUN_ID, payload_digests: Object.fromEntries(sealContract.payload_names.map((name) => [name, "a".repeat(64)])), claimed_at: report.generated_at });
    const seal = await buildSnapshotSeal({ run_id: RUN_ID, transaction_id: TX_ID, generated_at: report.generated_at, public_data_as_of: report.generated_at }, bodies);
    for (const [key, body] of bodies) publicKv.values.set(`snapshot:${RUN_ID}:${key}`, body);
    publicKv.values.set(`snapshot:${RUN_ID}:${SNAPSHOT_SEAL_KEY}`, seal.text);
    publicKv.values.set("snapshot:current", JSON.stringify({ schema_version: 2, run_id: RUN_ID, transaction_id: TX_ID, seal_sha256: seal.sha256, public_data_as_of: report.generated_at, promoted_at: report.generated_at, provider_scope: "public_only", owner_watchlist_inherited: false }));

  };
  await save();

  class NoPrivateKv extends MemoryKv {
    override async get<T = string>(): Promise<T | null> {
      throw new Error("PRIVATE_READ_FORBIDDEN");
    }
  }

  return {
    publicKv,
    report,
    save,
    env: {
      PUBLIC_CACHE: asKv(publicKv),
      TENANT_PRIVATE_CACHE: asKv(new NoPrivateKv()),
      EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
      LINE_CHANNEL_SECRET: "EXAMPLE_NOT_REAL",
      LINE_CHANNEL_ACCESS_TOKEN: "EXAMPLE_NOT_REAL",
      CURRENT_PUBLIC_DATA_ENABLED: "true",
    },
  };
}

async function reply(command: string, f?: Awaited<ReturnType<typeof fixture>>) {
  if (!f) f = await fixture();

  let messages: any[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    expect(url).toBe("https://api.line.me/v2/bot/message/reply");
    messages = JSON.parse(String(init.body)).messages;
    return new Response("{}", { status: 200 });
  }));
  await processAuthorizedLineEvent(
    await freeRelayRequestEnv(f.env),
    {
      waitUntil() {
        throw new Error("MODEL_JOB_FORBIDDEN");
      },
    } as unknown as ExecutionContext,
    {
      type: "message",
      replyToken: "SYNTHETIC_REPLY",
      timestamp: Date.now(),
      message: { id: "SYNTHETIC_MSG", type: "text", text: command },
    },
    "SYNTHETIC_TENANT",
  );
  assertLineMessages(messages);
  return messages;
}

afterEach(() => vi.unstubAllGlobals());

describe("v2.1.3 Top20 deep flow and 2Y total return UI contract", () => {
  it("renders mobile Flex with 3 readable return boxes, exactly 1 deep button, and no redundant card action", async () => {
    const f = await fixture({ withReturnEvidence: true });
    const messages = await reply("Top20", f);
    expect(messages.length).toBe(4); // 4 carousels (20 cards)

    const firstBubble = messages[0].contents.contents[0];
    const headerStr = JSON.stringify(firstBubble.header);
    expect(headerStr).toContain("歷史報酬，非預測");
    expect(headerStr).toContain("未完成來源核對");

    // Check footer buttons: exactly 1 button, labelled 深度化分析
    const buttons = firstBubble.footer.contents.filter((c: any) => c.type === "button");
    expect(buttons).toHaveLength(1);
    expect(buttons[0].action.label).toContain("深度化分析");
    expect(buttons[0].action.text).toContain("Top20 深度化分析 T00");
    // Duplicate card action removed
    expect(JSON.stringify(firstBubble.footer)).not.toContain("本公司七欄文字");
    expect(JSON.stringify(firstBubble.footer)).not.toContain("Top20 公司文字");

    // Check body contains three return boxes
    const bodyStr = JSON.stringify(firstBubble.body);
    expect(bodyStr).toContain("2Y 總報酬");
    expect(bodyStr).toContain("2年年化");
    expect(bodyStr).toContain("6個月");
    // In accordance with source authority review, numeric 2Y total return is withheld in actual LINE cards: UNAVAILABLE
    expect(bodyStr).toContain("UNAVAILABLE");
    expect(bodyStr).not.toContain("+50.0%");
    // Legacy returns (2Y CAGR and 6M) are preserved and unchanged
    expect(bodyStr).toContain("+22.5%");
    expect(bodyStr).toContain("+10.0%");
    // T01 also shows UNAVAILABLE
    const secondBubble = messages[0].contents.contents[1];
    expect(JSON.stringify(secondBubble.body)).toContain("UNAVAILABLE");
  });

  it("triggers deep flow from button command with at least 10 sections and explicit bottleneck boundaries", async () => {
    const f = await fixture({ withReturnEvidence: true });
    const cards = await reply("Top20", f);
    const deepCommand = cards[0].contents.contents[0].footer.contents.find((c: any) => c.type === "button").action.text;
    expect(deepCommand).toMatch(/^Top20\s+深度化分析\s+T00\s+/);

    const deepMessages = await reply(deepCommand, f);
    expect(deepMessages.length).toBeGreaterThanOrEqual(1);
    expect(deepMessages.length).toBeLessThanOrEqual(5);

    const fullText = deepMessages.map((m: any) => m.text).join("\n\n");

    // At least 10 separate sections
    expect(fullText).toContain("一、供應鏈瓶頸定位與價值鏈角色");
    expect(fullText).toContain("二、未來結構性缺口");
    expect(fullText).toContain("三、需求／供給／定價權分析");
    expect(fullText).toContain("四、公司捕捉度與毛利槓桿");
    expect(fullText).toContain("五、合約、訂單、資本支出、產能與客戶證據");
    expect(fullText).toContain("六、6個月／1年／2年催化劑與情境分析");
    expect(fullText).toContain("七、假說殺手與下檔風險");
    expect(fullText).toContain("八、多軸證據信心與來源品質");
    expect(fullText).toContain("九、候選排位說明與為何為第N名");
    expect(fullText).toContain("十、明確未明與待查事項");

    // Claim-level tags
    expect(fullText).toContain("[SUPPORTED]");
    expect(fullText).toContain("[INFERENCE]");
    expect(fullText).toContain("[WITHHELD]");

    // Essential analytical boundaries
    expect(fullText).toContain("Customers aren't scarcity");
    expect(fullText).toContain("Margin isn't pricing power");
    expect(fullText).toContain("CapEx alone isn't a choke");
    expect(fullText).toContain("X/source view not company proof");

    // System Bottleneck Explosion Score is UNAVAILABLE / UNRANKED
    expect(fullText).toContain("System Bottleneck Explosion Score");
    expect(fullText).toContain("UNAVAILABLE / UNRANKED");

    // Rank rationale: legacy candidate display position, not qualified bottleneck rank
    expect(fullText).toContain("舊版候選展示序位");
    expect(fullText).toContain("絕非");
    expect(fullText).toContain("System Bottleneck Explosion Rank");

    // Return evidence in section 10 withholds numeric 2Y total and shows explicit UNAVAILABLE
    expect(fullText).toContain("兩年總報酬還原端點：UNAVAILABLE");
    expect(fullText).not.toContain("+50.0%");
    // Legacy CAGR and 6M remain in section 10
    expect(fullText).toContain("近兩年年化 +22.5%");
    expect(fullText).toContain("近六個月 +10.0%");
  });

  it("preserves compatibility commands for direct text queries without card link", async () => {
    const f = await fixture({ withReturnEvidence: true });
    const cards = await reply("Top20", f);
    const deepCommand = cards[0].contents.contents[0].footer.contents.find((c: any) => c.type === "button").action.text;

    // Compatibility command 1: Top20 公司文字
    const companyTextCmd = deepCommand.replace("深度化分析", "公司文字");
    const textMessages = await reply(companyTextCmd, f);
    expect(textMessages).toHaveLength(1);
    expect(textMessages[0].text).toContain("本公司七欄摘要");
    expect(textMessages[0].text).toContain("T00");

    // Compatibility command 2: Top20 證據詳情 routes cleanly
    const evidenceCmd = deepCommand.replace("深度化分析", "證據詳情");
    const evidenceMessages = await reply(evidenceCmd, f);
    expect(evidenceMessages.length).toBeGreaterThanOrEqual(1);
    expect(evidenceMessages[0].text).toContain("深度化分析");

    // Text fallback: Top20 文字
    const allText = await reply("Top20 文字", f);
    const fullSummary = allText.map((m: any) => m.text).join("\n");
    expect(fullSummary).toContain("Top20 · 七欄摘要");
    expect(fullSummary).toContain("T00");
    expect(fullSummary).toContain("T19");
  });

  it("validates two-year return candidate evidence and rejects forged/scalar-only/stale values", async () => {
    const valid = makeReturnEvidence("NVDA");
    const res = validateTwoYearReturnEvidence(valid, "NVDA", "2026-09-10T00:00:00Z");
    expect(res.valid).toBe(true);
    expect(res.totalReturnPct).toBe(50.0);
    expect(res.display).toBe("+50.0%");
    expect(res.admitted).toBe(false);

    // Scalar only / missing evidence
    expect(validateTwoYearReturnEvidence(null, "NVDA").valid).toBe(false);
    expect(validateTwoYearReturnEvidence(undefined, "NVDA").valid).toBe(false);
    expect(validateTwoYearReturnEvidence(50.0, "NVDA").valid).toBe(false);

    // Mismatched ticker
    expect(validateTwoYearReturnEvidence(makeReturnEvidence("AAPL"), "NVDA").valid).toBe(false);

    // Mismatched calculation (calc != total_return_pct)
    expect(validateTwoYearReturnEvidence(makeReturnEvidence("NVDA", { total_return_pct: 100.0 }), "NVDA").valid).toBe(false);

    // Non-adjusted basis
    expect(validateTwoYearReturnEvidence(makeReturnEvidence("NVDA", { basis: "raw_close" as any }), "NVDA").valid).toBe(false);

    // Future end date
    expect(validateTwoYearReturnEvidence(makeReturnEvidence("NVDA", { actual_end: "2099-01-01" }), "NVDA").valid).toBe(false);

    // Incomplete elapsed days
    expect(validateTwoYearReturnEvidence(makeReturnEvidence("NVDA", { elapsed_days: 500 }), "NVDA").valid).toBe(false);

    // Negative return is valid
    const negative = makeReturnEvidence("DOWN", {
      start_adjusted_close: 100.0,
      end_adjusted_close: 70.0,
      total_return_pct: -30.0,
    });
    const negRes = validateTwoYearReturnEvidence(negative, "DOWN");
    expect(negRes.valid).toBe(true);
    expect(negRes.display).toBe("-30.0%");
  });

  it("rejects scalar-only injected return in parseV213Top20Report without evidence", async () => {
    const f = await fixture();
    const badReport = JSON.parse(JSON.stringify(f.report));
    badReport.records[0].two_year_total_return_pct = 50.0;
    // Missing two_year_return_evidence
    expect(parseV213Top20Report(badReport)).toBeNull();
  });

  it("fails closed on stale data or altered snapshot reference", async () => {
    const f = await fixture();
    const cards = await reply("Top20", f);
    const deepCommand = cards[0].contents.contents[0].footer.contents.find((c: any) => c.type === "button").action.text;

    // Mutated hash
    const parts = deepCommand.split(" ");
    parts[parts.length - 1] = "f".repeat(64);
    const mutated = parts.join(" ");

    const result = await v213PublicLineAnswer(f.env, parseQuery(mutated));
    expect(result).toContain("內容不符");
  });
});
