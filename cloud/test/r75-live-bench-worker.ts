// Isolated test entrypoint only. NEVER referenced by production wrangler config.
// No schedules, broadcast binding, real LINE credentials or activation endpoint.
import production, { freeRelayRequestEnv } from "../src/v213/production-worker";
import { compactGeneralAnswer } from "../src/v213/compact-qa";
import { parseQuery } from "../src/core";
import { processAuthorizedLineEvent, V211_GENERAL_QA } from "../src/v211/worker";
import { getJob } from "../src/storage";
import { V213_TOP20_DISPLAY_COLUMNS, V213_NO_CURRENT_ORDERS, V213_NO_FUTURE_ORDER_ESTIMATE, parseV213Top20Report, v213Top20DisplayHeader, v213Top20DisplayValues } from "../src/v213/top20-report";
import { inspectSevenFieldFlex } from "./r75-line-presentation-proof";
export { V213FreeRelayRoute } from "../src/v213/free-relay";

const realFetch = globalThis.fetch;
const replies: string[] = [];
const linePayloads: any[] = [];
globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
  const url = input instanceof Request ? input.url : String(input);
  if (url.startsWith("https://api.line.me/")) {
    if (url !== "https://api.line.me/v2/bot/message/reply") throw new Error("TEST_LINE_PUSH_FORBIDDEN");
    const messages = JSON.parse(String(init?.body)).messages;
    linePayloads.push(...messages);
    replies.push(...messages.filter((m: any) => m.type === "text").map((m: any) => m.text));
    return Promise.resolve(new Response("{}")); // no request ever leaves this isolate
  }
  return realFetch(input, init);
}) as typeof fetch;
const questions: Record<string, string> = {
  general: "什麼是自由現金流？它與淨利有何差異？",
  ticker: "NVDA有哪些需要驗證的公司風險？",
  methodology: "Serenity 的瓶頸與公司價值捕捉有何差別？",
  evidence: "如何判斷來源證據能否支持公司定價權？",
};
export default {
  async fetch(request: Request, env: any, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/v213/readiness" || url.pathname === "/health") return production.fetch(request, env, ctx);
    if (url.pathname === "/v213/admin/free-relay-route" || url.pathname === "/v213/admin/free-relay-smoke") return production.fetch(request, env, ctx);
    if (request.headers.get("authorization") !== `Bearer ${env.V21_SYNC_HMAC_SECRET}`) return new Response("Unauthorized", { status: 401 });
    if (url.pathname === "/setup" && request.method === "POST") {
      await env.PUBLIC_CACHE.put("last_successful_pipeline_timestamp", new Date().toISOString());
      await env.PUBLIC_CACHE.put("v21:top20:latest", JSON.stringify([{ ticker: "NVDA", evidence: [{ source_id: "sec_edgar", claim_type: "filing_publication_provenance", as_of: "2026-08-01", url: "https://www.sec.gov/Archives/edgar/data/1000000/", provenance_only: true }] }]));
      await env.PUBLIC_CACHE.put("v213:source-independence:latest", JSON.stringify({ portfolio: { limited_research_candidate_count: 20, evidence_qualified_candidate_count: 0 }, records: [{ ticker: "NVDA", publication_evidence_mode: "LIMITED_RESEARCH_CANDIDATE", eligible_for_high_confidence_model_inference: false, public_logic_state: { validated_company_thesis: false }, market_corroboration: { status: "UNAVAILABLE" }, missing_or_review: ["INDEPENDENT_CLAIM_CORROBORATION"] }] }));
      const stamp = new Date().toISOString();
      // Signed-universe-shaped fixture WITHOUT NVDA: a structurally valid
      // descending-score universe so the deterministic ticker lane does not
      // short-circuit, letting ticker/evidence questions fall through to the
      // local model lane (the Pi path) for qualification. No signature is
      // verified at read time; only structure/scoring_version is.
      const universe = Array.from({ length: 20 }, (_, n) => {
        const i = n + 1;
        return {
          ticker: `BENCH${String(i).padStart(2, "0")}`,
          name: `Synthetic Bench ${i}`,
          serenity_score: 90 - i,
          serenity_raw_score: 95 - i,
          risk_penalty: 5,
          data_quality: 0.9,
          rating: "A",
          category: "Synthetic",
          serenity_factors: { demand_wave: 1, chokepoint: 1, pricing_power: 1, replacement_friction: 1, tam_capture: 1, valuation_expectations: 1, evidence_quality: 1 },
          risk_flags: [],
          aschenbrenner_overlay: { included_in_serenity_score: false, fit_score: 50 },
          evidence: [{ title: "Synthetic filing", url: "https://www.sec.gov/Archives/edgar/data/1000000/" }],
          evidence_count: 1,
          source_count: 1,
          scoring_version: "serenity-first-v2.1.0",
          line_public_eligible: true,
          provider_scope: "public_only",
          owner_watchlist_inherited: false,
          rank: i,
          generated_at: stamp,
          as_of: stamp,
        };
      });
      await env.PUBLIC_CACHE.put("v211:universe:latest", JSON.stringify(universe), { expirationTtl: 259200 });
      await env.PUBLIC_CACHE.put("v213:top20-report:latest", JSON.stringify({
        schema_version: 2, product_version: "2.1.3", generated_at: stamp, display_columns: V213_TOP20_DISPLAY_COLUMNS,
        long_term_definition: "trailing_2y_adjusted_close_cagr", short_term_definition: "trailing_6m_adjusted_close_price_return", provider_scope: "public_only", owner_watchlist_inherited: false,
        records: Array.from({length:20},(_,i)=>({schema_version:2,rank:i+1,ticker:`T${String(i).padStart(2,"0")}`,long_term_return_pct:null,short_term_return_pct:null,industry:"合成測試",profit_summary:"未提供測試數值",current_orders:V213_NO_CURRENT_ORDERS,future_orders_estimate:V213_NO_FUTURE_ORDER_ESTIMATE,long_term_window:"2y_cagr",short_term_window:"6m_price_return",market_source:"yfinance",profit_source:"sec_edgar",orders_as_of:stamp,orders_confidence:"UNAVAILABLE",current_order_source_urls:[],future_order_source_urls:[],numeric_total_order_estimate_prohibited:true,retrieved_at:stamp,provider_scope:"public_only",owner_watchlist_inherited:false}))
      }));
      return Response.json({ synthetic_fixture: true });
    }
    if (url.pathname === "/qa") {
      const question = questions[url.searchParams.get("case") ?? ""];
      if (!question) return new Response("Fixed cases only", { status: 400 });
      const started = Date.now();
      const answer = await compactGeneralAnswer(await freeRelayRequestEnv(env), parseQuery(question), { tenantId: "synthetic-bench", chatType: "group" });
      return Response.json({ answer, elapsed_ms: Date.now() - started, synthetic_fixture: true }, { headers: { "cache-control": "no-store" } });
    }
    if (url.pathname === "/top20-check") {
      replies.length = 0;
      linePayloads.length = 0;
      await processAuthorizedLineEvent(await freeRelayRequestEnv(env), ctx, {type:"message",replyToken:"SYNTHETIC_REPLY",source:{type:"user",userId:"SYNTHETIC_USER"},message:{type:"text",text:"Top20"},timestamp:Date.now()}, "synthetic-top20-tenant");
      const expected = parseV213Top20Report(await env.PUBLIC_CACHE.get("v213:top20-report:latest", "json"));
      if (!expected) throw new Error("SYNTHETIC_REPORT_INVALID");
      const proof = inspectSevenFieldFlex(linePayloads, expected);
      linePayloads.length = 0;
      await processAuthorizedLineEvent(await freeRelayRequestEnv(env), ctx, {type:"message",replyToken:"SYNTHETIC_TEXT_REPLY",source:{type:"user",userId:"SYNTHETIC_USER"},message:{type:"text",text:"Top20 文字"},timestamp:Date.now()}, "synthetic-top20-tenant");
      const labels = v213Top20DisplayHeader("bilingual");
      const fullText = linePayloads.map(m => m.text ?? "").join("\n");
      let previous = -1;
      const complete = linePayloads.length > 0 && linePayloads.length <= 5 && linePayloads.every(m => m.type === "text") && expected.records.every(row => {
        const fragment = `── ${row.rank}/20 ──\n` + v213Top20DisplayValues(row).map((value, i) => `${labels[i]}：${value}`).join("\n");
        const index = fullText.indexOf(fragment);
        const ordered = index > previous; previous = index;
        return ordered;
      });
      return Response.json({ ...proof, text_fallback_values_match: complete, text_message_count: linePayloads.length, real_line_sent:false });
    }
    if (url.pathname === "/reference-start") {
      // Drive the REAL production LINE path (processAuthorizedLineEvent) for a
      // fixed case. `floor` (test-only) delays the QA promise so the 7s race
      // deterministically takes the reference-number/waitUntil branch; the real
      // inference runs in parallel via Promise.all, so total = max(floor, infer).
      const caseName = url.searchParams.get("case") ?? "general";
      const question = questions[caseName];
      if (!question) return new Response("Fixed cases only", { status: 400 });
      const floor = Number(url.searchParams.get("floor") ?? 0);
      if (!Number.isInteger(floor) || floor < 0 || floor > 30000) return new Response("floor out of range", { status: 400 });
      const scoped = await freeRelayRequestEnv(env);
      if (floor > 0) {
        const real = scoped[V211_GENERAL_QA];
        if (!real) throw new Error("BENCH_GENERAL_QA_UNAVAILABLE");
        scoped[V211_GENERAL_QA] = async (e, q, c) => {
          const [answer] = await Promise.all([real(e, q, c), new Promise(r => setTimeout(r, floor))]);
          return answer; // test-only floor forces the actual 7s/waitUntil branch
        };
      }
      replies.length = 0;
      await processAuthorizedLineEvent(scoped, ctx, { type: "message", replyToken: "SYNTHETIC_REPLY", source: { type: "user", userId: "SYNTHETIC_USER" }, message: { type: "text", text: question }, timestamp: Date.now() }, "synthetic-bench");
      const reply = replies[0] ?? "";
      const referenceId = (reply.match(/參考編號 ([A-Z0-9]+)/) || [])[1] as string | undefined;
      return Response.json({ reply, referenceId, case: caseName, test_only_floor_ms: floor, real_line_sent: false });
    }
    if (url.pathname === "/reference-result") return Response.json(await getJob(env, "synthetic-bench", url.searchParams.get("id") ?? ""));
    return new Response("Test endpoint not allowed", { status: 404 });
  },
};
