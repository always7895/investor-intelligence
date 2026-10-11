import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { BOTTLENECK_V3_KEY, loadBottleneckV3 } from "../src/v213/bottleneck-v3";
import type { PublicSnapshotView } from "../src/v213/public-snapshot";
import { GUIDANCE_BINDING_KEY } from "../src/v213/revenue-guidance-machine";
import { describe, expect, it } from "vitest";

// Synthetic, frozen, test-only. No genuine/native/live qualification or enablement.
// Rows pin DECLARED expectations only; Python D8-D11 are characterizations.
// M13, MT7, MT5-alone, and Scenario R are NOT_EXERCISED here.
const rawFixture = readFileSync(resolve(__dirname, "../../tests/fixtures/revenue-guidance-machine-nbis-auto-functional.json"));
const fixture = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(rawFixture)) as {
  scope: string; report: string; binding: string;
};
const NBIS_CUTOFF = "2032-02-20T13:00:00Z";
const H = (text: string) => createHash("sha256").update(text).digest("hex");
const clone = (value: any): any => JSON.parse(JSON.stringify(value));
const utf8 = (text: string) => new TextEncoder().encode(text).byteLength;
function canon(value: any): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(canon).join(",") + "]";
  return "{" + Object.keys(value).sort().map(k => JSON.stringify(k) + ":" + canon(value[k])).join(",") + "}";
}
function dash(value: any): any {
  if (Array.isArray(value)) return value.map(dash);
  if (value !== null && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, dash(v)]));
  return typeof value === "string" ? value.replaceAll("\u2013", "-") : value;
}
function extraTriple() {
  return {channel: "ISSUER_IR", id: "https://example.invalid/synthetic-g4b3-extra", date: "2032-02-19"};
}
function fixtureView(report: string, binding: string): PublicSnapshotView {
  return {
    runId: "synthetic-machine-barrier", kind: "snapshot", integrity: "sealed",
    hasSealedObject: key => key === BOTTLENECK_V3_KEY || key === GUIDANCE_BINDING_KEY,
    json: async () => { throw new Error("exact texts required"); },
    text: async keys => {
      if (keys.length !== 1) throw new Error("unexpected key selection");
      if (keys[0] === BOTTLENECK_V3_KEY) return report;
      if (keys[0] === GUIDANCE_BINDING_KEY) return binding;
      throw new Error("unexpected key");
    },
  };
}

// Full repin chain; original canonical equality checked BEFORE mutation/padding.
// Canon is a test-side reimplementation of the private MS:28 helper, not a bypass.
function repin(id: string, omitReportDigest = false): {report: string; binding: string} {
  const report = clone(JSON.parse(fixture.report)), binding = clone(JSON.parse(fixture.binding));
  const envelope = report.top[2].outlook.order_forecast_v3, m = envelope.machine;
  for (const key of ["decisions_canonical_json", "producer_canonical_json", "record_canonical_json"]) {
    if (canon(JSON.parse(m[key])) !== m[key]) throw new Error("CANONICAL_LOAD_MISMATCH " + key);
  }
  let decisions = JSON.parse(m.decisions_canonical_json), record = JSON.parse(m.record_canonical_json);
  const attempt = JSON.parse(m.producer_canonical_json), event = attempt.event;
  const auto = envelope.payload.evidence.auto_update, producerPin = auto.producer;
  const op = (kind: string): any => decisions.find((d: any) => d.kind === kind).operands;
  const pkg = event.packages.find((p: any) => p.accession === event.accession);
  const member = decisions.find((d: any) => d.kind === "MEMBERSHIP" && d.ref === pkg.accession).operands;
  let recordChanged = false;
  if (id === "M01") op("FY_RECONCILIATION").operand = clone(op("CALENDAR").proofs[0]);
  else if (id === "M02") op("CALENDAR").tagged_proofs.pop();
  else if (id === "M03") decisions.find((d: any) => d.kind === "ACTUAL" && d.ref.endsWith("-12-31")).operands.derivation.operation = "SIX_MONTHS_MINUS_FINAL_QUARTER";
  else if (id === "M04") delete member.link_accounts[pkg.statement];
  else if (id === "M05") op("ROUTING").consumed.push(extraTriple());
  else if (id === "M06") {
    decisions = dash(decisions); record = dash(record); recordChanged = true;
  } else if (id === "M06b") {
    // Change the ARR digit in the claim and positive range together. Retain
    // guidance_state.passage verbatim: consumer semantic binding must deny it.
    record.claims[0].passage = record.claims[0].passage.replace("$9.0B", "$8.0B");
    op("CLAIM").scope_context.quote = op("CLAIM").scope_context.quote.replace("$9.0B", "$8.0B");
    member.guidance_state.scope_context.quote = member.guidance_state.scope_context.quote.replace("$9.0B", "$8.0B");
    recordChanged = true;
  } else if (id === "M07c" || id === "M07") {
    const target = id === "M07c" ? 32 : 33, n = Object.keys(attempt.captures).length;
    const original = producerPin.captures.find((cap: any) => cap.key === pkg.statement);
    for (let i = 0; i < target - n; i++) {
      const key = "nbis:" + pkg.accession + ":member:pad" + i.toString().padStart(2, "0");
      attempt.captures[key] = original.raw_sha256;
      producerPin.captures.push({...clone(original), key});
    }
  } else if (id === "M08") producerPin.captures.find((cap: any) => cap.key === pkg.statement).role = "REPLAY_NBIS_ACTUALS_STATEMENT";
  else if (id === "M09") event.adapter = "SEC_8K_202_INLINE_XBRL_V1";
  else if (id === "M11") event.later_documents.push({...extraTriple(), label: "Synthetic later material", disposition: "POSSIBLY_RELEVANT"});
  else if (id === "M12") {
    const body = member.report_period.body[0]; body.quote = "X" + body.quote.slice(1);
  } else if (id === "M12q") {
    // Grammar-valid sentence naming another quarter; offsets keep the quote length.
    const body = member.report_period.body[0]; body.quote = body.quote.replace("fourth", "third");
    body.offsets = [body.offsets[0], body.offsets[0] + body.quote.length];
  } else if (!["C0", "M10c", "M10"].includes(id)) throw new Error("UNKNOWN_ROW");

  attempt.decisions = decisions; attempt.event = event;
  if (recordChanged) {
    attempt.record = record;
    attempt.record_sha256 = H(canon(record));
  }
  // Required emit order: decisions, producer, record.
  m.decisions_canonical_json = canon(decisions);
  m.producer_canonical_json = canon(attempt);
  m.record_canonical_json = canon(record);
  producerPin.decisions_sha256 = H(m.decisions_canonical_json);
  producerPin.attempt_sha256 = H(m.producer_canonical_json);
  producerPin.event_sha256 = H(canon(event));
  if (recordChanged) producerPin.record_sha256 = H(m.record_canonical_json);
  binding.issuers.NBIS.attempt_sha256 = producerPin.attempt_sha256;
  if (recordChanged) binding.issuers.NBIS.record_sha256 = producerPin.record_sha256;
  auto.decisions = decisions.map((d: any) => ({kind: d.kind, ref: d.ref, decision: d.decision, capture: d.capture, operands: d.operands}));
  auto.consumed = op("ROUTING").consumed.map((v: any) => [v.channel, v.id, v.date]).sort((a: any, b: any) => canon(a) < canon(b) ? -1 : canon(a) > canon(b) ? 1 : 0);
  if (recordChanged) {
    const evidence = envelope.payload.evidence;
    for (const key of ["documents", "claims", "reported_quarters", "forward_intervals"]) {
      evidence[key] = evidence[key].map((sealed: any, i: number) => Object.fromEntries(
        Object.keys(sealed).map(k => [k, Object.hasOwn(record[key][i], k) ? record[key][i][k] : null])));
    }
    evidence.release_channels = Object.fromEntries(Object.keys(evidence.release_channels).map(k => [k, record.release_channels[k] ?? null]));
    evidence.fy_reconciliation = clone(record.fy_reconciliation);
  }
  if (id === "M10c" || id === "M10") {
    const target = id === "M10c" ? 256000 : 256001;
    m.producer_canonical_json += " ".repeat(target - utf8(JSON.stringify(envelope)));
    producerPin.attempt_sha256 = H(m.producer_canonical_json);
    binding.issuers.NBIS.attempt_sha256 = producerPin.attempt_sha256;
    if (utf8(JSON.stringify(envelope)) !== target) throw new Error("PAD_LENGTH_MISMATCH");
  }
  const reportText = JSON.stringify(report);
  if (!omitReportDigest) binding.report_sha256 = H(reportText);
  return {report: reportText, binding: JSON.stringify(binding)};
}
async function tuple(texts: {report: string; binding: string}): Promise<[boolean | null, string | null]> {
  const result = await loadBottleneckV3(fixtureView(texts.report, texts.binding), {guidanceMachineEnabled: true});
  const forecast = result?.top.find(row => row.symbol === "NBIS")?.forecast;
  if (!forecast || forecast.machineAdmitted === undefined) return [null, null];
  return [forecast.machineAdmitted, forecast.revenueStatus ?? null];
}

// ROWTABLE-BEGIN
const ROW_TABLE = [
  {
    "id": "C0",
    "kind": "CTRL",
    "py_a": [
      "RESULT",
      null
    ],
    "py_b": [
      "RESULT",
      [
        "AUTO_VERIFIED",
        null
      ]
    ],
    "ts": [
      true,
      "AVAILABLE"
    ]
  },
  {
    "id": "M01",
    "kind": "CHAR",
    "py_a": [
      "RESULT",
      null
    ],
    "py_b": [
      "RESULT",
      [
        "BLOCKED",
        "APPROVAL_BINDING"
      ]
    ],
    "ts": [
      false,
      "UNAVAILABLE"
    ]
  },
  {
    "id": "M02",
    "kind": "NEG",
    "py_a": [
      "RAISED",
      "StateError",
      "ATTEMPT_NBIS_SCHEMA"
    ],
    "py_b": [
      "RESULT",
      [
        "BLOCKED",
        "STATE_CORRUPT"
      ]
    ],
    "ts": [
      false,
      "UNAVAILABLE"
    ]
  },
  {
    "id": "M03",
    "kind": "NEG",
    "py_a": [
      "RAISED",
      "StateError",
      "ATTEMPT_NBIS_SCHEMA"
    ],
    "py_b": [
      "RESULT",
      [
        "BLOCKED",
        "STATE_CORRUPT"
      ]
    ],
    "ts": [
      false,
      "UNAVAILABLE"
    ]
  },
  {
    "id": "M04",
    "kind": "NEG",
    "py_a": [
      "RAISED",
      "StateError",
      "ATTEMPT_NBIS_SCHEMA"
    ],
    "py_b": [
      "RESULT",
      [
        "BLOCKED",
        "STATE_CORRUPT"
      ]
    ],
    "ts": [
      false,
      "UNAVAILABLE"
    ]
  },
  {
    "id": "M05",
    "kind": "CHAR",
    "py_a": [
      "RESULT",
      null
    ],
    "py_b": [
      "RESULT",
      [
        "BLOCKED",
        "APPROVAL_BINDING"
      ]
    ],
    "ts": [
      false,
      "UNAVAILABLE"
    ]
  },
  {
    "id": "M06",
    "kind": "NEG",
    "py_a": [
      "RAISED",
      "StateError",
      "ATTEMPT_NBIS_SCHEMA"
    ],
    "py_b": [
      "RESULT",
      [
        "BLOCKED",
        "STATE_CORRUPT"
      ]
    ],
    "ts": [
      false,
      "UNAVAILABLE"
    ]
  },
  {
    "id": "M06b",
    "kind": "CHAR",
    "py_a": [
      "RESULT",
      null
    ],
    "py_b": [
      "RESULT",
      [
        "BLOCKED",
        "APPROVAL_BINDING"
      ]
    ],
    "ts": [
      false,
      "UNAVAILABLE"
    ]
  },
  {
    "id": "M07c",
    "kind": "CTRL",
    "py_a": [
      "RESULT",
      null
    ],
    "py_b": [
      "RESULT",
      [
        "AUTO_VERIFIED",
        null
      ]
    ],
    "ts": [
      true,
      "AVAILABLE"
    ]
  },
  {
    "id": "M07",
    "kind": "NEG",
    "py_a": [
      "RAISED",
      "StateError",
      "ATTEMPT_CAPTURES"
    ],
    "py_b": [
      "RESULT",
      [
        "BLOCKED",
        "STATE_CORRUPT"
      ]
    ],
    "ts": [
      false,
      "UNAVAILABLE"
    ]
  },
  {
    "id": "M08",
    "kind": "NEG",
    "py_a": [
      "RESULT",
      null
    ],
    "py_b": [
      "RESULT",
      [
        "BLOCKED",
        "APPROVAL_BINDING"
      ]
    ],
    "ts": [
      false,
      "UNAVAILABLE"
    ]
  },
  {
    "id": "M09",
    "kind": "NEG",
    "py_a": [
      "RAISED",
      "StateError",
      "ATTEMPT_CAPTURES"
    ],
    "py_b": [
      "RESULT",
      [
        "BLOCKED",
        "STATE_CORRUPT"
      ]
    ],
    "ts": [
      false,
      "UNAVAILABLE"
    ]
  },
  {
    "id": "M10c",
    "kind": "CTRL",
    "py_a": [
      "RESULT",
      "dict"
    ],
    "py_b": null,
    "ts": [
      true,
      "AVAILABLE"
    ]
  },
  {
    "id": "M10",
    "kind": "NEG",
    "py_a": [
      "RAISED",
      "MachinePublicationBlocked",
      "MACHINE_EVIDENCE_LIMIT"
    ],
    "py_b": null,
    "ts": [
      false,
      "UNAVAILABLE"
    ]
  },
  {
    "id": "M11",
    "kind": "CHAR",
    "py_a": [
      "RESULT",
      null
    ],
    "py_b": [
      "RESULT",
      [
        "BLOCKED",
        "APPROVAL_BINDING"
      ]
    ],
    "ts": [
      false,
      "UNAVAILABLE"
    ]
  },
  {
    "id": "M12",
    "kind": "NEG",
    "py_a": [
      "RESULT",
      null
    ],
    "py_b": [
      "RESULT",
      [
        "BLOCKED",
        "APPROVAL_BINDING"
      ]
    ],
    "ts": [
      false,
      "UNAVAILABLE"
    ]
  },
  {
    "id": "M12q",
    "kind": "NEG",
    "py_a": [
      "RESULT",
      null
    ],
    "py_b": [
      "RESULT",
      [
        "BLOCKED",
        "APPROVAL_BINDING"
      ]
    ],
    "ts": [
      false,
      "UNAVAILABLE"
    ]
  }
];
// ROWTABLE-END

describe("G4b-3 synthetic NBIS paired declarations", () => {
  it("T0 frozen synthetic fixture SHA256 and scope", () => {
    expect(createHash("sha256").update(rawFixture).digest("hex")).toBe("0d10abfd3f8de37c1e4cbf7c01128b5f3be2f93a5c0968b6b8df5a7982db51de");
    expect(fixture.scope).toBe("SYNTHETIC_NBIS_AUTO_NOT_GENUINE_NATIVE_OR_LIVE");
  });
  for (const row of ROW_TABLE) it(row.id + " " + row.kind, async () => {
    const savedNow = Date.now;
    Date.now = () => Date.parse(NBIS_CUTOFF);
    try {
      // Every negative/characterization requires its own no-op C0 in this test.
      expect(await tuple(repin("C0"))).toEqual([true, "AVAILABLE"]);
      // M12/M12q: the TS form-body grammar and quarter deny the edited body quote.
      expect(await tuple(repin(row.id))).toEqual(row.ts);
    } finally { Date.now = savedNow; }
  });
  it("D0 stale report digest withholds the whole report", async () => {
    const savedNow = Date.now;
    Date.now = () => Date.parse(NBIS_CUTOFF);
    try {
      // The repin report digest is load-bearing: a stale one never reaches a row,
      // so no [false, "UNAVAILABLE"] negative above is a stale-digest artefact.
      expect(await tuple(repin("C0", true))).toEqual([null, null]);
      expect(await tuple(repin("C0"))).toEqual([true, "AVAILABLE"]);
    } finally { Date.now = savedNow; }
  });
});
