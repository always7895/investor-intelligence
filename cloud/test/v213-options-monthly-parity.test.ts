import { beforeAll, describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import * as rules from "../src/v213/option-recommendation-rules";
import { validateCoveredCallCycle } from "../src/v213/covered-call";

interface MonthlyCase { name: string; as_of: string; expiries: string[]; expected: string | null }
const cases = JSON.parse(readFileSync(new URL("../../tests/fixtures/monthly_expiry_cases.json", import.meta.url), "utf8")) as MonthlyCase[];
interface WindowCase { dte: number; period: "weekly" | "monthly"; expected: boolean }
interface WindowObservation {
  producer_available: boolean; validator_available: boolean; produced_validated: boolean | null;
  produced: unknown; probe: unknown;
}
const windowCases = JSON.parse(readFileSync(new URL("../../tests/fixtures/options_window_cases.json", import.meta.url), "utf8")) as WindowCase[];
let pythonWindows: WindowObservation[];
let capturedAt: string;
let pythonChoices: (string | null)[];

beforeAll(() => {
  const script = `import json, sys
from datetime import date
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import option_recommendation_rules as rules
from tests.test_monthly_options_fallback import STAMP, window_observations
data = json.load(sys.stdin)
choices = [rules.select_monthly_expiry([date.fromisoformat(e) for e in row["expiries"]], date.fromisoformat(row["as_of"])) for row in data["selection"]]
print(json.dumps({"choices": [choice.isoformat() if choice is not None else None for choice in choices],
                  "windows": window_observations(data["windows"]), "captured_at": STAMP}))
`;
  const python = process.env.PROJECT_PYTHON || (process.platform === "win32" ? "python" : "python3");
  const observed = JSON.parse(execFileSync(python, ["-I", "-B", "-c", script,
    fileURLToPath(new URL("../../scripts", import.meta.url)), fileURLToPath(new URL("../../", import.meta.url))], {
    input: JSON.stringify({ selection: cases, windows: windowCases }), encoding: "utf8", timeout: 30_000,
    env: { ...process.env, PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1" },
  }));
  pythonChoices = observed.choices;
  pythonWindows = observed.windows;
  capturedAt = observed.captured_at;
});

describe("monthly expiry Python/Worker behavioral parity", () => {
  it.each(cases.map((row, index) => ({ ...row, index })))("$name", row => {
    expect(rules.selectMonthlyExpiry(row.expiries, row.as_of)).toBe(row.expected);
    expect(pythonChoices[row.index]).toBe(row.expected);
  });
});

describe("producer / Python validator / Worker window admission parity", () => {
  it.each(windowCases.map((row, index) => ({ ...row, index })))("$period at $dte DTE", row => {
    const observed = pythonWindows[row.index];
    if (observed === undefined) throw new Error(`Missing Python observation for ${row.period} at ${row.dte} DTE`);
    expect(observed.producer_available).toBe(row.expected);
    expect(observed.validator_available).toBe(row.expected);
    expect(validateCoveredCallCycle(observed.probe, Date.parse(capturedAt), capturedAt, row.period) !== null).toBe(row.expected);
    if (row.expected) {
      expect(observed.produced_validated).toBe(true);
      expect(validateCoveredCallCycle(observed.produced, Date.parse(capturedAt), capturedAt, row.period)).not.toBeNull();
    }
  });
});
