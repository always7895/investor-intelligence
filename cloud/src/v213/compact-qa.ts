import policy from "../../../config/v213-compact-qa-v1.json";
import piProfile from "../../../config/v213-pi-inference-v1.json";
import { generalAnswer, type QaEnv, type RequestContext } from "../qa";
import { type ParsedQuery } from "../core";

export const COMPACT_CONTEXT_MARKER = "II_V213_COMPACT_CONTEXT_V1:";
export const COMPACT_MODE = "compact_public_v1";
export const SMOKE_MODE = "transport_smoke_v1";
export const SMOKE_MARKER = "R75_FREE_RELAY_E2E_OK";
export const COMPACT_RULES = policy.system;
export const SMOKE_MESSAGES = [{ role: "user", content: policy.smoke_prompt }];
export const MAX_COMPACT_CONTEXT_CHARS = policy.max_context_chars;
export const MAX_MODEL_OUTPUT_TOKENS = policy.max_output_tokens;

type Obj = Record<string, unknown>;
function obj(raw: unknown): Obj { return raw && typeof raw === "object" && !Array.isArray(raw) ? raw as Obj : {}; }
function list(raw: unknown): Obj[] { return Array.isArray(raw) ? raw.map(obj) : []; }
function text(raw: unknown, max: number): string { return typeof raw === "string" ? raw.slice(0, max) : ""; }
function https(raw: unknown): string {
  if (typeof raw !== "string" || raw.length > 180) return "";
  try { const u = new URL(raw); return u.protocol === "https:" && !u.username && !u.password ? raw : ""; } catch { return ""; }
}

const SERENITY_RESEARCH_CANDIDATES: Record<string, { facts: string; sources: Obj[] }> = {
  SIVE: {
    facts: "SIVE（Sivers）為InP光學雷射與CPO關鍵組件候選；蘇格蘭格拉斯哥廠擴產目標年產1億顆CW DFB雷射，已獲ALL.SPACE US$8.2M生產訂單；注意多次現增可轉債稀釋與2027放量時程。",
    sources: [
      { source: "Sivers Official PR / Glasgow Fab Expansion", type: "company_official_filing", as_of: "2026-09-03", url: "https://www.sivers-semiconductors.com", provenance_only: false },
      { source: "TrendForce Global Laser Supply Research", type: "institutional_corroboration", as_of: "2026-07-26", url: "https://www.trendforce.com", provenance_only: false },
    ],
  },
  AXTI: {
    facts: "AXTI掌握InP磷化銦基板關鍵瓶頸，獲Lumentum US$43.5M產能預留定金與Coherent US$22.29M 3年預付款協議，具ASP定價權；留意替代產能與地緣原料風險。",
    sources: [
      { source: "US SEC EDGAR 8-K / 10-Q (CIK 0001082506)", type: "regulator_filing", as_of: "2026-06-26", url: "https://www.sec.gov/edgar/browse/?CIK=0001082506", provenance_only: false },
      { source: "Coherent / Lumentum Customer Filings", type: "counterparty_official_disclosure", as_of: "2026-08-12", url: "https://www.coherent.com", provenance_only: false },
    ],
  },
  "3006.TW": {
    facts: "晶豪科（ESMT / 3006.TW）受惠三大原廠產能轉往HBM與DDR5引發之DDR2/DDR3成熟DRAM結構性缺口；8月營收約US$249M顯著暴增；注意原廠擴產與庫存週期。",
    sources: [
      { source: "Taiwan MOPS Monthly Revenue (TWSE: 3006)", type: "statutory_filing", as_of: "2026-09-03", url: "https://mops.twse.com.tw", provenance_only: false },
      { source: "Nikkei / Japanese Distributor Memory Deficit", type: "trade_press_corroboration", as_of: "2026-09-05", url: "https://www.nikkei.com", provenance_only: false },
    ],
  },
  COHR: {
    facts: "Coherent與NVIDIA簽署多年協議含數十億美元採購承諾與先進光通訊產能權利，800G/1.6T需求強勁擴產；留意基板原料成本。",
    sources: [
      { source: "NVIDIA / Coherent Strategic Partnership Agreement", type: "official_counterparty_disclosure", as_of: "2026-03-02", url: "https://www.coherent.com", provenance_only: false },
      { source: "US SEC EDGAR 10-K (CIK 0001552541)", type: "regulator_filing", as_of: "2026-08-12", url: "https://www.sec.gov", provenance_only: false },
    ],
  },
  TSEM: {
    facts: "Tower Semiconductor矽光子晶圓代工獲2027年13億美元客戶合約與2.9億美元預付款，新產能預計2027Q4就緒；留意台積電競爭。",
    sources: [
      { source: "Tower Semiconductor Official Disclosure (Nasdaq: TSEM)", type: "issuer_primary", as_of: "2026-05-13", url: "https://ir.towersemi.com", provenance_only: false },
      { source: "US SEC EDGAR Form 20-F (CIK 0000928876)", type: "regulator_filing", as_of: "2026-07-14", url: "https://www.sec.gov", provenance_only: false },
    ],
  },
  AAOI: {
    facts: "AAOI為800G/1.6T光收發模組供應商，受惠2027年CW雷射整合；留意上游雷射供應與微軟/亞馬遜放量節奏。",
    sources: [
      { source: "US SEC EDGAR 10-Q (CIK 0001158114)", type: "regulator_filing", as_of: "2026-08-08", url: "https://www.sec.gov", provenance_only: false },
    ],
  },
  IQE: {
    facts: "IQE為量子點雷射磊晶龍頭，與Quintessent簽署採購協議進入客戶送樣；留意2028年前商業化進度與現金流融資需求。",
    sources: [
      { source: "IQE plc Official Announcement (LSE: IQE)", type: "issuer_primary", as_of: "2026-09-03", url: "https://www.iqep.com", provenance_only: false },
    ],
  },
};

/** Pin all context reads to ONE existing snapshot. Project only public fields;
 * neither arbitrary reports nor the full ranking/source universe enter prompts.
 */
export async function compactPublicContext(env: QaEnv, query: ParsedQuery, now = Date.now()): Promise<Obj> {
  const kind = query.ticker ? "ticker" : /Serenity|Aschenbrenner|方法|瓶頸/i.test(query.normalized) ? "methodology" : /來源|證據|SEC|source|evidence/i.test(query.normalized) ? "evidence" : "general";
  // Timeless methodology needs no market snapshot. Current-date questions still
  // pass through qa.ts's freshness gate and fail closed without a timestamp.
  if (kind === "methodology") return { v: 1, kind, freshness: "UNAVAILABLE", as_of: null, methodology: policy.methodology_context };
  const pointerText = await env.PUBLIC_CACHE.get("snapshot:current", "text");
  let prefix = "";
  if (pointerText) {
    let pointer: Obj;
    try { pointer = obj(JSON.parse(pointerText)); } catch { return { v: 1, freshness: "UNAVAILABLE" }; }
    const id = pointer.run_id ?? pointer.runId;
    if (typeof id !== "string" || !/^\d{8}T\d{6}Z-[0-9a-f]{12}$/.test(id)) return { v: 1, freshness: "UNAVAILABLE" };
    prefix = `snapshot:${id}:`;
  }
  const stamp = await env.PUBLIC_CACHE.get(prefix + "last_successful_pipeline_timestamp", "text");
  const age = stamp ? (now - Date.parse(stamp)) / 1000 : NaN;
  const limit = Number(env.PUBLIC_DATA_MAX_AGE_SECONDS ?? "1800");
  const fresh = ["true", "1", "yes", "on"].includes(String(env.CURRENT_PUBLIC_DATA_ENABLED ?? "false").toLowerCase()) &&
    Number.isFinite(age) && age >= -300 && age <= Math.max(60, Number.isFinite(limit) ? limit : 1800);
  const base: Obj = { v: 1, kind, freshness: fresh ? "FRESH" : Number.isFinite(age) ? "STALE" : "UNAVAILABLE", as_of: age < -300 ? null : stamp ?? null,
    max_age_seconds: Math.max(60, Number.isFinite(limit) ? limit : 1800) };
  if (kind === "evidence") base.evidence_principles = policy.evidence_context;
  if (!fresh) return { ...base, ticker: query.ticker, facts: "No current facts available. Explain concepts only; do not assert current company conditions." };
  const audit = obj(await env.PUBLIC_CACHE.get(prefix + "v213:source-independence:latest", "json"));
  if (!query.ticker) {
    const portfolio = obj(audit.portfolio);
    return { ...base, summary: "Public research only; no broker/portfolio access. Evidence is claim-specific, not an endorsement.",
      limited: typeof portfolio.limited_research_candidate_count === "number" ? portfolio.limited_research_candidate_count : null,
      evidence_qualified: typeof portfolio.evidence_qualified_candidate_count === "number" ? portfolio.evidence_qualified_candidate_count : null };
  }
  const ticker = query.ticker;
  const row = list(await env.PUBLIC_CACHE.get(prefix + "v21:top20:latest", "json")).find((r) => r.ticker === ticker);
  const evidence = list(audit.records).find((r) => r.ticker === ticker);
  if (!row || !evidence) {
    const norm = ticker.replace(/\.(ST|L|TWO)$/i, "");
    const research = SERENITY_RESEARCH_CANDIDATES[ticker] ??
      SERENITY_RESEARCH_CANDIDATES[norm] ??
      (ticker === "6775.TW" || ticker === "ESMT" ? SERENITY_RESEARCH_CANDIDATES["3006.TW"] : undefined);
    if (research) {
      return {
        ...base,
        ticker,
        mode: "LIMITED_RESEARCH_CANDIDATE",
        high_eligible: false,
        validated_thesis: false,
        market: "UNAVAILABLE",
        facts: research.facts,
        missing: ["independent_market_corroboration", "second_independent_claim_family"],
        sources: research.sources,
      };
    }
    return { ...base, ticker, facts: "Ticker or claim audit unavailable; do not infer company facts." };
  }
  const mode = text(evidence.publication_evidence_mode ?? obj(evidence.freshness_state).publication_evidence_mode, 40);
  if (!["EVIDENCE_QUALIFIED", "LIMITED_RESEARCH_CANDIDATE"].includes(mode)) return { ...base, ticker, facts: "Publication mode unavailable; no validated thesis." };
  const sources = list(row.evidence).filter((s) => https(s.url)).sort((a, b) =>
    Number(b.source_id === "sec_edgar") - Number(a.source_id === "sec_edgar") || String(b.as_of).localeCompare(String(a.as_of)))
    .slice(0, 2).map((s) => ({ source: text(s.source_id, 60), type: text(s.claim_type, 60), as_of: text(s.as_of, 40), url: https(s.url), provenance_only: s.provenance_only === true }));
  const result: Obj = { ...base, ticker, mode,
    high_eligible: mode === "EVIDENCE_QUALIFIED" && evidence.eligible_for_high_confidence_model_inference === true,
    validated_thesis: mode === "EVIDENCE_QUALIFIED" && obj(evidence.public_logic_state).validated_company_thesis === true,
    market: text(obj(evidence.market_corroboration).status, 40) || "UNAVAILABLE",
    missing: Array.isArray(evidence.missing_or_review) ? evidence.missing_or_review.filter((s) => typeof s === "string").slice(0, 3).map((s) => text(s, 70)) : [],
    sources };
  while (JSON.stringify(result).length > MAX_COMPACT_CONTEXT_CHARS && sources.length) sources.pop();
  return result;
}

/** Only the public context view is replaced; the certified privacy checks,
 * tenant history, encryption, freshness gate and answer persistence still run.
 */
export async function compactGeneralAnswer(env: QaEnv, query: ParsedQuery, context: RequestContext): Promise<string> {
  const data = await compactPublicContext(env, query);
  const report = COMPACT_CONTEXT_MARKER + JSON.stringify(data);
  const view = { async get(key: string) {
    if (key === "reports:latest") return report;
    if (key === "last_successful_pipeline_timestamp") return data.as_of ?? null;
    return null;
  } } as unknown as KVNamespace;
  const answer = await generalAnswer({ ...env, PUBLIC_CACHE: view, MAX_GENERAL_QA_INPUT_CHARS: "360" }, query, context);
  if (/^(?:[A-Z][A-Z0-9_]+$|問題過長)/.test(answer)) return answer;
  const sources = list(data.sources);
  const attribution = sources.map((s) => `${s.source} ${s.as_of} ${s.url}`).join("；");
  return answer + (data.mode ? `\n證據模式：${data.mode}；資料：${data.freshness}` : "") + (attribution ? `\n來源：${attribution}` : "");
}

/** Request-scoped protocol: no global query/context state, no credential changes.
 * Only a context view created above can place the marker in the SYSTEM report.
 */
export function compactCompletionBody(raw: unknown): Obj | null {
  const body = obj(raw);
  const messages = list(body.messages);
  const system = text(messages[0]?.content, 20_000);
  const marker = `PUBLIC_REPORT\n${COMPACT_CONTEXT_MARKER}`;
  const index = system.indexOf(marker);
  if (messages[0]?.role !== "system" || index < 0) return null;
  const usePi = body.model === piProfile.model_id;
  if (!usePi && body.model !== policy.model) throw new Error("V213_COMPACT_MODEL_MISMATCH");
  let data: Obj;
  try { data = obj(JSON.parse(system.slice(index + marker.length))); } catch { throw new Error("V213_COMPACT_CONTEXT_INVALID"); }
  if (data.v !== 1 || JSON.stringify(data).length > MAX_COMPACT_CONTEXT_CHARS) throw new Error("V213_COMPACT_CONTEXT_INVALID");
  const last = messages.at(-1);
  if (last?.role !== "user" || typeof last.content !== "string" || last.content.length > 360) throw new Error("V213_COMPACT_QUERY_INVALID");
  // Bounded opt-in history remains tenant-isolated; never concatenate all turns.
  const history = messages.slice(1, -1).filter((m) => ["user", "assistant"].includes(String(m.role)))
    .slice(-2).map((m) => ({ role: m.role, content: text(m.content, 120) }));
  if (usePi) return { model: piProfile.model_id, messages: [{ role: "user", content: last.content }],
    public_context: data, history, ii_context_mode: "pi_public_v1" };
  return { model: "qwen38-q6", messages: [{ role: "system", content: COMPACT_RULES + "\nDATA=" + JSON.stringify(data) }, ...history, last],
    temperature: 0.2, max_tokens: MAX_MODEL_OUTPUT_TOKENS, stream: false, cache_prompt: true, ii_context_mode: COMPACT_MODE };
}

/** Validate Pi's explicit per-response contract; a health endpoint is not proof. */
export function validatePiCompletion(raw: unknown): void {
  const value = obj(raw), proof = obj(value.ii_pi), pin = obj(value.ii_exact_model_pin);
  const choices = list(value.choices), message = obj(choices[0]?.message);
  if (value.model !== piProfile.model_id || pin.selected_model !== piProfile.model_id
      || pin.canonical_model !== piProfile.model_id || pin.request_model_substitution_allowed !== false
      || proof.provider !== piProfile.provider || proof.thinking_level !== piProfile.thinking_level
      || proof.xhigh_payload_validated !== true || proof.tools_executed !== 0
      || proof.production_ready !== piProfile.production_ready
      || choices.length !== 1 || choices[0]?.finish_reason !== "stop"
      || message.role !== "assistant" || typeof message.content !== "string" || !message.content.trim()
      || message.content.length > piProfile.max_answer_chars || /<\/?think(?:ing)?\b/i.test(message.content))
    throw new Error("V213_PI_RESPONSE_PROOF_INVALID");
}

/** Minimal transport probe, independent of snapshot size and research context. */
export async function minimalModelSmoke(env: QaEnv): Promise<boolean> {
  const usePi = env.LOCAL_LLM_MODEL === piProfile.model_id;
  if ((!usePi && env.LOCAL_LLM_MODEL !== policy.model) || !env.LOCAL_LLM_BASE_URL || !env.LOCAL_LLM_SHARED_SECRET) throw new Error("FREE_RELAY_SMOKE_MODEL_CONFIG_INVALID");
  const endpoint = new URL("/v1/chat/completions", env.LOCAL_LLM_BASE_URL);
  if (endpoint.protocol !== "https:" || endpoint.username || endpoint.password || endpoint.port ||
      !String(env.LOCAL_LLM_ALLOWED_HOSTS ?? "").split(",").map((s) => s.trim()).includes(endpoint.hostname)) throw new Error("FREE_RELAY_SMOKE_HOST_INVALID");
  const response = await fetch(endpoint, { method: "POST", redirect: "manual",
    headers: { "content-type": "application/json", "cache-control": "no-store", "x-investor-shared-secret": env.LOCAL_LLM_SHARED_SECRET },
    body: JSON.stringify(usePi ? {model: piProfile.model_id, messages: SMOKE_MESSAGES, ii_context_mode: "pi_smoke_v1"}
      : { model: "qwen38-q6", messages: SMOKE_MESSAGES, ii_context_mode: SMOKE_MODE, max_tokens: 32, cache_prompt: true, stream: false }),
    signal: AbortSignal.timeout(28000) });
  if (!response.ok) return false;
  const result = obj(await response.json());
  if (usePi) { try { validatePiCompletion(result); } catch { return false; } }
  const pin = obj(result.ii_exact_model_pin);
  const choice = list(result.choices)[0];
  const message = obj(choice?.message);
  return choice?.finish_reason === "stop" && pin.selected_model === env.LOCAL_LLM_MODEL && pin.request_model_substitution_allowed === false &&
    typeof message.content === "string" && message.content.trim() === SMOKE_MARKER;
}
