import policy from "../../../config/v213-compact-qa-v1.json";
import { configuredModelProfile, validateModelProfile, modelProfileSha256, type ModelProfileEnv } from './model-profile';
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
  const base: Obj = { v: 1, kind, freshness: fresh ? "FRESH" : Number.isFinite(age) ? "STALE" : "UNAVAILABLE", as_of: age < -300 ? null : stamp ?? null };
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
  if (!row || !evidence) return { ...base, ticker, facts: "Ticker or claim audit unavailable; do not infer company facts." };
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
export async function compactGeneralAnswer(env: QaEnv & ModelProfileEnv, query: ParsedQuery, context: RequestContext): Promise<string> {
  const profile = configuredModelProfile(env);
  const data = await compactPublicContext(env, query);
  const report = COMPACT_CONTEXT_MARKER + JSON.stringify({ ...data, ...(profile ? { runtime_model_profile: profile } : {}) });
  const view = { async get(key: string) {
    if (key === "reports:latest") return report;
    if (key === "last_successful_pipeline_timestamp") return data.as_of ?? null;
    return null;
  } } as unknown as KVNamespace;
  const answer = await generalAnswer({ ...env, ...(profile ? { LOCAL_LLM_MODEL: profile.model } : {}), PUBLIC_CACHE: view, MAX_GENERAL_QA_INPUT_CHARS: "360" }, query, context);
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
  let data: Obj;
  try { data = obj(JSON.parse(system.slice(index + marker.length))); } catch { throw new Error("V213_COMPACT_CONTEXT_INVALID"); }
  const profile = data.runtime_model_profile === undefined ? undefined : validateModelProfile(data.runtime_model_profile);
  delete data.runtime_model_profile;
  if (body.model !== (profile?.model ?? policy.model)) throw new Error('V213_COMPACT_MODEL_MISMATCH');
  if (data.v !== 1 || JSON.stringify(data).length > MAX_COMPACT_CONTEXT_CHARS) throw new Error("V213_COMPACT_CONTEXT_INVALID");
  const last = messages.at(-1);
  if (last?.role !== "user" || typeof last.content !== "string" || last.content.length > 360) throw new Error("V213_COMPACT_QUERY_INVALID");
  // Bounded opt-in history remains tenant-isolated; never concatenate all turns.
  const history = messages.slice(1, -1).filter((m) => ["user", "assistant"].includes(String(m.role)))
    .slice(-2).map((m) => ({ role: m.role, content: text(m.content, 120) }));
  return { model: profile?.model ?? policy.model, ...(profile ? { ii_model_profile: profile } : {}), messages: [{ role: "system", content: COMPACT_RULES + "\nDATA=" + JSON.stringify(data) }, ...history, last],
    temperature: 0.2, max_tokens: profile?.max_output_tokens ?? MAX_MODEL_OUTPUT_TOKENS, stream: false, cache_prompt: true, ii_context_mode: COMPACT_MODE };
}

/** Minimal transport probe, independent of snapshot size and research context. */
export async function minimalModelSmoke(env: QaEnv & ModelProfileEnv): Promise<boolean> {
  const profile = configuredModelProfile(env);
  const selected = profile?.model ?? policy.model;
  if ((!profile && env.LOCAL_LLM_MODEL !== selected) || !env.LOCAL_LLM_BASE_URL || !env.LOCAL_LLM_SHARED_SECRET) throw new Error("FREE_RELAY_SMOKE_MODEL_CONFIG_INVALID");
  const endpoint = new URL("/v1/chat/completions", env.LOCAL_LLM_BASE_URL);
  if (endpoint.protocol !== "https:" || endpoint.username || endpoint.password || endpoint.port ||
      !String(env.LOCAL_LLM_ALLOWED_HOSTS ?? "").split(",").map((s) => s.trim()).includes(endpoint.hostname)) throw new Error("FREE_RELAY_SMOKE_HOST_INVALID");
  const response = await fetch(endpoint, { method: "POST", redirect: "manual",
    headers: { "content-type": "application/json", "cache-control": "no-store", "x-investor-shared-secret": env.LOCAL_LLM_SHARED_SECRET },
    body: JSON.stringify({ model: selected, ...(profile ? { ii_model_profile: profile } : {}), messages: SMOKE_MESSAGES, ii_context_mode: SMOKE_MODE, max_tokens: profile?.smoke_output_tokens ?? policy.smoke_output_tokens, cache_prompt: true, stream: false }),
    signal: AbortSignal.timeout(profile?.timeout_ms ?? policy.timeout_ms) });
  if (!response.ok) return false;
  const result = obj(await response.json());
  const pin = obj(result.ii_exact_model_pin);
  const choice = list(result.choices)[0];
  const message = obj(choice?.message);
  return (!profile || pin.model_profile_sha256 === await modelProfileSha256(profile)) && choice?.finish_reason === "stop" && pin.selected_model === selected && pin.request_model_substitution_allowed === false &&
    typeof message.content === "string" && message.content.trim() === SMOKE_MARKER;
}
