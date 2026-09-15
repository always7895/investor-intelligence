import { afterEach, describe, expect, it, vi } from "vitest";
import { parseQuery } from "../src/core";
import { assertLineMessages } from "../src/line-messages";
import { processAuthorizedLineEvent } from "../src/v211/worker";
import { freeRelayRequestEnv } from "../src/v213/production-worker";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import {
  loadV213FreshTop20Report,
  type V213Top20Env,
  V213_TOP20_DISPLAY_COLUMNS,
  V213_NO_CURRENT_ORDERS,
  V213_NO_FUTURE_ORDER_ESTIMATE,
} from "../src/v213/top20-report";
import {
  readV213BottleneckReport,
  parseV213BottleneckReport,
  INSUFFICIENT_EVIDENCE_MESSAGE,
  type V213BottleneckReport,
} from "../src/v213/bottleneck-report";
import { buildV213Top20Messages, v213Top20LineAnswer } from "../src/v213/top20-presentation";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { buildSnapshotSeal, SNAPSHOT_OBJECT_KEYS, SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import contract from "../../config/v213-r75-publication-mode-v1.json";
import { MemoryKv, asKv } from "./fake-kv";

function legacy20Fixture() {
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
    records: Array.from({ length: 20 }, (_, i) => ({
      schema_version: 2,
      rank: i + 1,
      ticker: `LEGACY${i.toString().padStart(2, "0")}`,
      name: `Legacy Company ${i}`,
      industry: "舊能源",
      profit_summary: "獲利",
      current_orders: V213_NO_CURRENT_ORDERS,
      future_orders_estimate: V213_NO_FUTURE_ORDER_ESTIMATE,
      long_term_return_pct: 12.0,
      short_term_return_pct: 5.0,
      long_term_window: "2y_cagr",
      short_term_window: "6m_price_return",
      market_source: "yfinance",
      profit_source: "sec_edgar",
      orders_as_of: stamp,
      orders_confidence: "UNAVAILABLE",
      current_order_source_urls: [],
      future_order_source_urls: [],
      numeric_total_order_estimate_prohibited: true,
      retrieved_at: stamp,
      provider_scope: "public_only",
      owner_watchlist_inherited: false,
    })),
  };
  publicKv.values.set("v213:top20-report:latest", JSON.stringify(report));
  publicKv.values.set("last_successful_pipeline_timestamp", stamp);

  class NoPrivateReads extends MemoryKv {
    override async get<T = string>(): Promise<T | null> {
      throw new Error("PRIVATE_READ_FORBIDDEN");
    }
  }

  const env = {
    PUBLIC_CACHE: asKv(publicKv),
    TENANT_PRIVATE_CACHE: asKv(new NoPrivateReads()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    LINE_CHANNEL_SECRET: "EXAMPLE_NOT_REAL",
    LINE_CHANNEL_ACCESS_TOKEN: "EXAMPLE_NOT_REAL",
    CURRENT_PUBLIC_DATA_ENABLED: "true",
    V21_TOP20_MAX_AGE_SECONDS: "7200",
  };
  return { publicKv, env, report, stamp };
}

async function sealedBottleneckFixture(bottleneckReport: V213BottleneckReport) {
  const RUN = "20260910T100000Z-123456789abc";
  const TX = "1".repeat(32);
  const TIME = bottleneckReport.generated_at;
  const meta = { run_id: RUN, transaction_id: TX, generated_at: TIME, public_data_as_of: TIME };
  const bodies: [string, string][] = SNAPSHOT_OBJECT_KEYS.map(key => [key, JSON.stringify({ synthetic: key })]);
  bodies.find(([key]) => key === "last_successful_pipeline_timestamp")![1] = TIME;
  bodies.find(([key]) => key === "v213:top20-report:latest")![1] = JSON.stringify(bottleneckReport);
  bodies.find(([key]) => key === "v213:activation-claim")![1] = JSON.stringify({
    schema_version: 1,
    run_id: RUN,
    transaction_id: TX,
    payload_digests: Object.fromEntries(contract.payload_names.map(key => [key, "a".repeat(64)])),
    claimed_at: TIME,
  });
  const seal = await buildSnapshotSeal(meta, bodies);
  const pointer = {
    schema_version: 2,
    run_id: RUN,
    transaction_id: TX,
    seal_sha256: seal.sha256,
    public_data_as_of: TIME,
    promoted_at: TIME,
    provider_scope: "public_only",
    owner_watchlist_inherited: false,
  };
  const kv = new MemoryKv();
  const prefix = `snapshot:${RUN}:`;
  for (const [key, body] of bodies) kv.values.set(prefix + key, body);
  kv.values.set(prefix + SNAPSHOT_SEAL_KEY, seal.text);
  kv.values.set("snapshot:current", JSON.stringify(pointer));
  const env = {
    PUBLIC_CACHE: asKv(kv),
    TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V21_TOP20_MAX_AGE_SECONDS: "7200",
  };
  return { env, pointer, seal, bottleneckReport };
}

describe("v213 bottleneck takeover acceptance review: real caller & factor authority", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("DEFECT 1 RED: actual authorized LINE caller with fresh legacy 20 and no new key must fail closed with INSUFFICIENT_EVIDENCE, not return old list", async () => {
    const f = legacy20Fixture();
    let lineReplies: any[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
      lineReplies = JSON.parse(String(init.body)).messages;
      return new Response("{}", { status: 200 });
    }));

    const workerEnv = await freeRelayRequestEnv(f.env as any);
    await processAuthorizedLineEvent(
      workerEnv,
      { waitUntil() { throw new Error("MODEL_JOB_FORBIDDEN"); } } as unknown as ExecutionContext,
      {
        type: "message",
        replyToken: "SYNTHETIC_REPLY",
        timestamp: Date.now(),
        message: { id: "SYNTHETIC_MESSAGE", type: "text", text: "TOP20" },
      },
      "SYNTHETIC_TENANT",
    );

    assertLineMessages(lineReplies);
    const textBody = JSON.stringify(lineReplies);
    // Under new policy takeover, fresh legacy 20 must NOT be returned!
    // Must return INSUFFICIENT_EVIDENCE message.
    expect(textBody).toContain("INSUFFICIENT_EVIDENCE");
    expect(textBody).not.toContain("LEGACY00");
  });

  it("DEFECT 1 RED: loadV213FreshTop20Report with qualified new report must NOT borrow old rows", async () => {
    const stamp = new Date().toISOString();
    const bottleneckReport: V213BottleneckReport = {
      schema_version: 1,
      policy_id: "system-bottleneck-explosion-v1",
      product_version: "2.1.3",
      status: "QUALIFIED",
      publication_status: "PUBLICATION_QUALIFIED",
      live_qualification: "ACTIVE",
      generated_at: stamp,
      admitted_count: 1,
      ranked_count: 1,
      total_evaluated: 20,
      records: [
        {
          schema_version: 1,
          rank: 1,
          ticker: "NEWCHOKE",
          name: "Chokepoint Tech",
          industry: "半導體",
          bottleneck_role: "SINGLE_SOURCE",
          system_bottleneck_explosion_score: 85.0,
          dependency_score: 12.0,
          scarcity_score: 14.0,
          pricing_power_score: 12.0,
          company_capture_score: 12.0,
          long_term_return_pct: 50.0,
          short_term_return_pct: 20.0,
          profit_summary: "營業利益率 40%",
          current_orders: "$2B 確定積壓",
          future_orders_estimate: "無可靠公開預估",
          retrieved_at: stamp,
          admission_status: "ADMITTED",
          score_qualified: true,
          candidate_assessment_mode: "RANKING_QUALIFIED",
          claims_audit: {
            supported_claim_count: 4,
            conflicted_claim_count: 0,
            all_material_claims_supported: true,
          },
        },
      ],
      provider_scope: "public_only",
    };

    const f = await sealedBottleneckFixture(bottleneckReport);
    const result = await loadV213FreshTop20Report(f.env as any, parseQuery("TOP20"));
    expect(typeof result).not.toBe("string");
    const loaded = result as any;
    // Must return the new qualified bottleneck records, NOT the legacy 20 rows!
    expect(loaded.records).toHaveLength(1);
    expect(loaded.records[0].ticker).toBe("NEWCHOKE");
    expect(loaded.records[0].ticker).not.toBe("LEGACY00");

    // UI presentation renders Flex cards for qualified records with 2Y total UNAVAILABLE
    const flexMessages = buildV213Top20Messages(loaded, "zh-TW", "flex");
    expect(flexMessages.length).toBeGreaterThan(0);
    const flexStr = JSON.stringify(flexMessages);
    expect(flexStr).toContain("NEWCHOKE");
    expect(flexStr).toContain("UNAVAILABLE");
    expect(flexStr).toContain("深度化分析");
    expect(flexStr).not.toContain("LEGACY00");
  });

  it("DEFECT 2 RED: unsealed/legacy view must NOT confer authority on new bottleneck rankings", async () => {
    const f = legacy20Fixture();
    // In unsealed legacy view (runId === null, integrity === 'legacy')
    const view = await pinPublicSnapshot(f.env as any);
    expect(view.integrity).toBe("legacy");

    // Even if raw unsealed key exists in KV, unsealed view must be rejected!
    const stamp = "2026-09-10T10:00:00.000Z";
    const bottleneckReport: V213BottleneckReport = {
      schema_version: 1,
      policy_id: "system-bottleneck-explosion-v1",
      product_version: "2.1.3",
      status: "QUALIFIED",
      publication_status: "PUBLICATION_QUALIFIED",
      live_qualification: "ACTIVE",
      generated_at: stamp,
      admitted_count: 1,
      ranked_count: 1,
      total_evaluated: 20,
      records: [
        {
          schema_version: 1,
          rank: 1,
          ticker: "CHOKE01",
          name: "Choke Corp",
          industry: "半導體",
          bottleneck_role: "SINGLE_SOURCE",
          system_bottleneck_explosion_score: 80.0,
          dependency_score: 12.0,
          scarcity_score: 14.0,
          pricing_power_score: 12.0,
          company_capture_score: 12.0,
          profit_summary: "獲利",
          current_orders: "確定積壓",
          future_orders_estimate: "無預估",
          retrieved_at: stamp,
          admission_status: "ADMITTED",
          score_qualified: true,
          candidate_assessment_mode: "RANKING_QUALIFIED",
          claims_audit: {
            supported_claim_count: 4,
            conflicted_claim_count: 0,
            all_material_claims_supported: true,
          },
        },
      ],
      provider_scope: "public_only",
    };
    f.publicKv.values.set("v213:bottleneck-report:latest", JSON.stringify(bottleneckReport));

    // readV213BottleneckReport must reject unsealed legacy view
    const report = await readV213BottleneckReport(view);
    expect(report).toBeNull();
  });

  it("DEFECT 5 RED: parser must reject invalid factor bounds, counts inconsistencies, and unverified dates", () => {
    const invalidDoc = {
      schema_version: 1,
      policy_id: "system-bottleneck-explosion-v1",
      product_version: "2.1.3",
      status: "QUALIFIED",
      publication_status: "PUBLICATION_QUALIFIED",
      live_qualification: "ACTIVE",
      generated_at: "2026-02-31T00:00:00Z", // Impossible calendar date!
      admitted_count: "1", // String count instead of integer number
      ranked_count: 1,
      total_evaluated: 20,
      records: [
        {
          schema_version: 1,
          rank: 1,
          ticker: "BAD01",
          name: "Bad Corp",
          industry: "半導體",
          bottleneck_role: "SINGLE_SOURCE",
          system_bottleneck_explosion_score: 80.0,
          dependency_score: -5.0, // Negative factor score!
          scarcity_score: 14.0,
          pricing_power_score: 12.0,
          company_capture_score: 12.0,
          profit_summary: "獲利",
          current_orders: "訂單",
          future_orders_estimate: "預估",
          retrieved_at: "2026-09-15T01:41:08Z",
          admission_status: "ADMITTED",
          score_qualified: true,
          candidate_assessment_mode: "RANKING_QUALIFIED",
          claims_audit: {
            supported_claim_count: 0, // 0 supported claims!
            conflicted_claim_count: 0,
            all_material_claims_supported: true, // Promotes flag with 0 claims!
          },
        },
      ],
      provider_scope: "public_only",
    };

    expect(parseV213BottleneckReport(invalidDoc)).toBeNull();
  });

  it("ALL TOP20 aliases route to new policy gate and return INSUFFICIENT_EVIDENCE without old fallback", async () => {
    const f = legacy20Fixture();
    const aliases = ["TOP20", "Top 20", "top20", "前20", "排行", "排名", "TOP20 文字"];
    for (const alias of aliases) {
      const res = await v213PublicLineAnswer(f.env as any, parseQuery(alias));
      const text = typeof res === "string" ? res : JSON.stringify(res);
      expect(text).toContain("INSUFFICIENT_EVIDENCE");
      expect(text).not.toContain("LEGACY00");
    }
  });
});
