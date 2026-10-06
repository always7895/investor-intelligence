import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { parseOrderForecastV3Machine } from "../src/v213/order-forecast";
import {
  MACHINE_SCHEMA,
  machineContextIsValid,
  resolveSealedMachineBindings,
  validateMachineEnvelope,
  type MachineBindings,
  type MachineCallbacks,
} from "../src/v213/revenue-guidance-machine";

// TYPEFIX1 regression: the typed fail-closed checks must keep a valid sealed selection and a valid
// barrier envelope unchanged, and must deny a missing issuer pin, a missing binding or a mismatched
// cutoff. Synthetic in-memory inputs only; no network, credentials or runtime.
const CUTOFF = "2026-09-28T15:00:00Z";
const SYMBOLS = ["NVDA", "SNDK", "SYM3", "SYM4", "SYM5", "SYM6", "SYM7", "SYM8", "SYM9", "SYM10"];
const IDENTITY = {
  verifier_version: null, normalizer_version: null, implementation_sha256: null, profiles_sha256: null,
  baseline_registry_sha256: null, baseline_approval_sha256: null,
};
const sha = (text: string) => createHash("sha256").update(text).digest("hex");
const reportText = JSON.stringify({
  schema: "v213-bottleneck-top20-v3-sealed", generated_at: CUTOFF, top: SYMBOLS.map(symbol => ({ symbol })),
});
const waitingPin = (symbol: string) => ({
  symbol, disposition: "WAITING", reason: null, admission_kind: null, identity: { ...IDENTITY },
  attempt_sha256: null, record_sha256: null, receipt_digest: null,
});
const bindingValue = (symbols: readonly string[]) => ({
  schema: "revenue-guidance-public-binding-v1", report_sha256: sha(reportText), cutoff: CUTOFF,
  revision: `gir1:${"a".repeat(64)}`, input_digest: "b".repeat(64), generation_id: null, generation_sha256: null,
  source_manifest_sha256: "c".repeat(64), issuers: Object.fromEntries(symbols.map(s => [s, waitingPin(s)])),
});
const callbacks: MachineCallbacks = {
  digest: sha,
  receiptDigest: () => { throw new Error("not reached for a barrier envelope"); },
  receiptStatus: () => { throw new Error("not reached for a barrier envelope"); },
};
const barrierEnvelope = (issuer: string) => ({
  schema: MACHINE_SCHEMA,
  admission_mode: "B1_MACHINE_V1",
  machine: {
    schema: "revenue-guidance-machine-evidence-v1", issuer, cutoff: CUTOFF, input_digest: "b".repeat(64),
    generation_id: null, generation_sha256: null, identity: { ...IDENTITY },
    record_canonical_json: null, producer_canonical_json: null, decisions_canonical_json: null, receipt_history: [],
  },
  payload: {
    issuer, version: 3, cutoff: CUTOFF, revenue_status: "UNAVAILABLE", revenue_reason: "STALE",
    evidence: {
      cutoff: CUTOFF, approval_sha256: null, approval_approved_at: null, approval_decisions: null,
      auto_update: {
        version: "auto-admission-evidence-v1", issuer, disposition: "WAITING", reason: null, admission_kind: null,
        generation_id: null, identity: { ...IDENTITY }, producer: null, decisions: [], consumed: [], detections: [],
        overflow: false, receipt: null, cutoff: CUTOFF, input_digest: "b".repeat(64), generation_sha256: null,
      },
    },
  },
});
const requiredBindings = (): MachineBindings => {
  const bindings = resolveSealedMachineBindings(reportText, JSON.stringify(bindingValue(SYMBOLS)));
  if (bindings === null) throw new Error("valid synthetic binding did not resolve");
  return bindings;
};

describe("TYPEFIX1 revenue-guidance machine fail-closed typing", () => {
  it("a valid sealed selection still resolves and is frozen", () => {
    const bindings = requiredBindings();
    expect(Object.keys(bindings.issuers).sort()).toEqual([...SYMBOLS].sort());
    expect(bindings.issuers.NVDA?.disposition).toBe("WAITING");
    expect(Object.isFrozen(bindings)).toBe(true);
  });

  it("a selection missing an issuer or with a different report hash is denied", () => {
    expect(resolveSealedMachineBindings(reportText, JSON.stringify(bindingValue(SYMBOLS.slice(1))))).toBeNull();
    expect(resolveSealedMachineBindings(reportText + " ", JSON.stringify(bindingValue(SYMBOLS)))).toBeNull();
    expect(resolveSealedMachineBindings(reportText, "{not json")).toBeNull();
  });

  it("a valid barrier envelope keeps its unchanged barrier context", () => {
    const ctx = validateMachineEnvelope(barrierEnvelope("NVDA"), requiredBindings(), "NVDA", CUTOFF, callbacks);
    expect(ctx).not.toBeNull();
    expect(machineContextIsValid(ctx)).toBe(true);
    expect(ctx?.kind).toBe("BARRIER");
    expect(ctx?.barrierReason).toBe("STALE");
    expect(ctx?.receiptDigest).toBeNull();
    expect(ctx?.rawReceiptStatus).toBeNull();
  });

  it("a missing sealed issuer pin stays denied without a default pin", () => {
    const { NVDA: _removed, ...rest } = requiredBindings().issuers;
    const withoutPin: MachineBindings = { ...requiredBindings(), issuers: rest };
    expect(validateMachineEnvelope(barrierEnvelope("NVDA"), withoutPin, "NVDA", CUTOFF, callbacks)).toBeNull();
    expect(validateMachineEnvelope(barrierEnvelope("ZZZZ"), requiredBindings(), "ZZZZ", CUTOFF, callbacks)).toBeNull();
  });

  it("an absent binding or a mismatched cutoff is denied", () => {
    expect(validateMachineEnvelope(barrierEnvelope("NVDA"), undefined, "NVDA", CUTOFF, callbacks)).toBeNull();
    expect(validateMachineEnvelope(barrierEnvelope("NVDA"), requiredBindings(), "NVDA", undefined, callbacks)).toBeNull();
    expect(validateMachineEnvelope(barrierEnvelope("NVDA"), requiredBindings(), "NVDA", "2026-09-28T15:00:01Z", callbacks)).toBeNull();
  });

  it("the machine fallback keeps an absent cutoff null and names its diagnostic", () => {
    const absent = parseOrderForecastV3Machine(null, "2026-09-28", "NVDA");
    expect(absent.cutoff).toBeNull();
    expect(absent.revenueStatus).toBe("UNAVAILABLE");
    expect(absent.revenueReason).toBe("FRESHNESS_UNVERIFIED");
    expect(absent.revenueDiagnostic).toBe("MACHINE_INPUTS_UNAVAILABLE");
    expect(absent.machineAdmitted).toBe(false);
    const dated = parseOrderForecastV3Machine(null, "2026-09-28", "NVDA", CUTOFF);
    expect(dated.cutoff).toBe(CUTOFF);
    expect(dated.revenueDiagnostic).toBe("MACHINE_INPUTS_UNAVAILABLE");
  });
});
