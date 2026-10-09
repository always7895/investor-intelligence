// T11-F1A: Python/TypeScript parity vector for the phase_knowledge_withheld block.
import { describe, expect, it } from "vitest";
import { validatePhaseKnowledgeWithheld } from "../src/v213/market-product-schema";
import parity from "./fixtures/phase-knowledge-withheld-parity-v1.json";

interface Vector { id: string; json: string; py: string; ts: string }
const vectors: Vector[] = parity.vectors as Vector[];

function outcome(text: string): [string, unknown] {
  try {
    return ["RETURNED", validatePhaseKnowledgeWithheld(JSON.parse(text))];
  } catch (e) {
    return ["RAISED", e instanceof Error ? e.message : String(e)];
  }
}

describe("phase_knowledge_withheld Python/TS parity", () => {
  it("every vector has the declared TS outcome", () => {
    for (const v of vectors) {
      const expected = v.ts === "ACCEPT" ? ["RETURNED", JSON.parse(v.json)] : ["RAISED", "INVALID_PHASE_KNOWLEDGE_WITHHELD"];
      expect([v.id, outcome(v.json)]).toEqual([v.id, expected]);
    }
  });

  it("lists the 19 vector ids and the single declared divergence", () => {
    expect(vectors.map(v => v.id)).toEqual([
      "v01-zero", "v02-positive", "v03-one-one", "v04-max-safe", "v05-over-safe",
      "v06-zero-affected-positive-signals", "v07-positive-affected-zero-signals", "v08-affected-exceeds-signals",
      "v09-negative", "v10-strings", "v11-booleans", "v12-float-integral", "v13-fractional", "v14-extra-key",
      "v15-missing-signals", "v16-empty-object", "v17-null", "v18-array", "v19-string",
    ]);
    expect(vectors.filter(v => v.py !== v.ts).map(v => v.id)).toEqual(["v12-float-integral"]);
  });
});
