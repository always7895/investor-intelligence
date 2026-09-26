/** IN-MEMORY SYNTHETIC UNIT FIXTURE ONLY. No real admissions, source truth,
 * signature, current freshness or Production authority is established here. */
import { MemoryKv, asKv } from "./fake-kv";
import { buildSnapshotSeal, SNAPSHOT_OBJECT_KEYS, SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { v213EvidencePolicyDigest, type V213Top20Env } from "../src/v213/top20-report";
import type { V213BottleneckReport } from "../src/v213/bottleneck-report";
import contract from "../../config/v213-r75-publication-mode-v1.json";
import policy from "../../config/v213-serenity-evidence-freshness-policy.json";

export const SYNTHETIC_RUN = "20260915T120000Z-012345abcdef";
export const SYNTHETIC_STAMP = "2026-09-15T12:00:00Z";
export const SYNTHETIC_NOW = "2026-09-15T13:00:00Z";
const TX = "3".repeat(32);

export async function buildSyntheticSealedReplay() {
  const report: V213BottleneckReport = {
    schema_version: 1, policy_id: "system-bottleneck-explosion-v1", product_version: "2.1.3",
    status: "QUALIFIED", publication_status: "PUBLICATION_QUALIFIED", live_qualification: "DEFERRED",
    generated_at: SYNTHETIC_STAMP, evidence_capture_at: SYNTHETIC_STAMP,
    freshness_policy: { policy_id: policy.policy_id, policy_sha256: await v213EvidencePolicyDigest() },
    admitted_count: 2, ranked_count: 2, total_evaluated: 2, provider_scope: "public_only",
    // Qualified-SHAPE test data, not producer-verified claims or actual admissions.
    records: ["SYNTHA", "SYNTHB"].map((ticker, index) => ({
      schema_version: 1, rank: index + 1, ticker, name: `Synthetic fixture entity ${index + 1}`,
      industry: "Synthetic test industry", bottleneck_role: "SYNTHETIC_TEST",
      system_bottleneck_explosion_score: 80 - index * 10,
      dependency_score: 10, scarcity_score: 10, pricing_power_score: 10, company_capture_score: 10,
      long_term_return_pct: 10, short_term_return_pct: 2,
      profit_summary: "Synthetic fixture only", current_orders: "Synthetic fixture only",
      future_orders_estimate: "No real estimate; synthetic fixture only",
      current_order_source_urls: ["https://example.com/synthetic/orders"], future_order_source_urls: [],
      retrieved_at: SYNTHETIC_STAMP, orders_state_as_of: SYNTHETIC_STAMP,
      evidence_class: "structural_claim", freshness_policy_key: "structural_claim_max_age_days",
      test_only_admission: true, admission_status: "ADMITTED", score_qualified: true,
      candidate_assessment_mode: "RANKING_QUALIFIED",
      claims_audit: { supported_claim_count: 2, conflicted_claim_count: 0, all_material_claims_supported: true },
    })),
  };
  const reportRaw = JSON.stringify(report);
  const bodies: [string, string][] = SNAPSHOT_OBJECT_KEYS.map(key => [key, JSON.stringify({ synthetic_fixture: true, key, authority: "NONE" })]);
  bodies.find(([key]) => key === "last_successful_pipeline_timestamp")![1] = SYNTHETIC_STAMP;
  bodies.find(([key]) => key === "v213:top20-report:latest")![1] = reportRaw;
  bodies.find(([key]) => key === "v213:activation-claim")![1] = JSON.stringify({
    schema_version: 1, transaction_id: TX, run_id: SYNTHETIC_RUN,
    payload_digests: Object.fromEntries(contract.payload_names.map(name => [name, "a".repeat(64)])),
    claimed_at: SYNTHETIC_STAMP,
  });
  const seal = await buildSnapshotSeal({ run_id: SYNTHETIC_RUN, transaction_id: TX,
    generated_at: SYNTHETIC_STAMP, public_data_as_of: SYNTHETIC_STAMP }, bodies);
  const kv = new MemoryKv();
  for (const [key, value] of bodies) kv.values.set(`snapshot:${SYNTHETIC_RUN}:${key}`, value);
  kv.values.set(`snapshot:${SYNTHETIC_RUN}:${SNAPSHOT_SEAL_KEY}`, seal.text);
  // Last insertion only: not a claim about real storage atomicity or publication.
  kv.values.set("snapshot:current", JSON.stringify({ schema_version: 2, run_id: SYNTHETIC_RUN,
    transaction_id: TX, seal_sha256: seal.sha256, public_data_as_of: SYNTHETIC_STAMP,
    promoted_at: SYNTHETIC_STAMP, provider_scope: "public_only", owner_watchlist_inherited: false }));
  return { kv, reportRaw, seal };
}

class ForbiddenReadKv extends MemoryKv {
  reads = 0;
  override async get<T = string>(): Promise<T | string | null> {
    this.reads++;
    throw new Error("OFFLINE_REPLAY_PRIVATE_READ_FORBIDDEN");
  }
}

export function makeOfflineEnv(kv: MemoryKv) {
  const privateKv = new ForbiddenReadKv();
  const securityKv = new ForbiddenReadKv();
  const env: V213Top20Env = { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(privateKv),
    EPHEMERAL_SECURITY_CACHE: asKv(securityKv), V213_FIELD_LOCALE: "en", V21_TOP20_MAX_AGE_SECONDS: "86400" };
  return { env, privateKv, securityKv };
}
