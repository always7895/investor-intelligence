import { beforeAll, describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import * as rules from "../src/v213/option-recommendation-rules";
import { validateCoveredCallCycle } from "../src/v213/covered-call";

interface MonthlyCase { name: string; as_of: string; expiries: string[]; expected: string | null; rule: string | null; expiry_day_open?: boolean }
const cases = JSON.parse(readFileSync(new URL("../../tests/fixtures/monthly_expiry_cases.json", import.meta.url), "utf8")) as MonthlyCase[];
interface WindowCase { dte: number; period: "weekly" | "monthly"; expected: boolean }
interface WindowObservation {
  producer_available: boolean; validator_available: boolean; produced_validated: boolean | null;
  produced: unknown; produced_at: string; probe: unknown; probe_at: string;
}
const windowCases = JSON.parse(readFileSync(new URL("../../tests/fixtures/options_window_cases.json", import.meta.url), "utf8")) as WindowCase[];
let pythonWindows: WindowObservation[];
let capturedAt: string;
let pythonChoices: ({ expiry: string; rule: string } | null)[];
let pythonConstants: { monthly_bucket: number[]; weekly_bucket: number[]; rules: string[]; fridays: string[] };

beforeAll(() => {
  const script = `import json, sys
from datetime import date
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import option_recommendation_rules as rules
from tests.test_monthly_options_fallback import STAMP, window_observations
data = json.load(sys.stdin)
def listed(row):
    days = []
    for text in row["expiries"]:
        try:
            days.append(date.fromisoformat(text))
        except ValueError:
            pass
    return days
choices = [rules.select_monthly(listed(row), date.fromisoformat(row["as_of"]), expiry_day_open_now=row.get("expiry_day_open", True)) for row in data["selection"]]
fridays = [rules.third_friday(year, month).isoformat() for year in range(2026, 2031) for month in range(1, 13)]
print(json.dumps({"constants": {"monthly_bucket": list(rules.MONTHLY_DTE_BUCKET), "weekly_bucket": list(rules.WEEKLY_DTE_BUCKET), "rules": list(rules.MONTHLY_RULES), "fridays": fridays},
                  "choices": [{"expiry": choice.expiry.isoformat(), "rule": choice.rule} if choice is not None else None for choice in choices],
                  "windows": window_observations(data["windows"]), "captured_at": STAMP}))
`;
  const python = process.env.PROJECT_PYTHON || (process.platform === "win32" ? "python" : "python3");
  const observed = JSON.parse(execFileSync(python, ["-I", "-B", "-c", script,
    fileURLToPath(new URL("../../scripts", import.meta.url)), fileURLToPath(new URL("../../", import.meta.url))], {
    input: JSON.stringify({ selection: cases, windows: windowCases }), encoding: "utf8", timeout: 30_000,
    env: { ...process.env, PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1" },
  }));
  pythonChoices = observed.choices;
  pythonConstants = observed.constants;
  pythonWindows = observed.windows;
  capturedAt = observed.captured_at;
}, 60_000);

describe("monthly rule constants Python/Worker parity", () => {
  it("pins the buckets, the rule names and the third-Friday calendar", () => {
    expect([...rules.MONTHLY_DTE_BUCKET]).toEqual(pythonConstants.monthly_bucket);
    expect([...rules.WEEKLY_DTE_BUCKET]).toEqual(pythonConstants.weekly_bucket);
    expect([...rules.MONTHLY_RULES]).toEqual(pythonConstants.rules);
    const fridays: string[] = [];
    for (let year = 2026; year <= 2030; year++) for (let month = 1; month <= 12; month++) fridays.push(rules.isoDay(rules.thirdFridayMs(year, month)));
    expect(fridays).toEqual(pythonConstants.fridays);
  });

  it("agrees on which expiries sit where a rule branch says", () => {
    expect(rules.monthlyRuleConsistent("2026-11-20", "THIRD_FRIDAY")).toBe(true);
    expect(rules.monthlyRuleConsistent("2026-11-19", "THIRD_FRIDAY")).toBe(false);
    expect(rules.monthlyRuleConsistent("2026-11-19", "HOLIDAY_SHIFT")).toBe(true);
    expect(rules.monthlyRuleConsistent("2026-11-20", "HOLIDAY_SHIFT")).toBe(false);
    expect(rules.monthlyRuleConsistent("2026-11-16", "HOLIDAY_SHIFT")).toBe(true);
    expect(rules.monthlyRuleConsistent("2026-11-15", "HOLIDAY_SHIFT")).toBe(false);
    expect(rules.monthlyRuleConsistent("2026-11-27", "LATER_LISTED")).toBe(false);
    expect(rules.monthlyRuleConsistent("2026-11-20", "LATER_LISTED")).toBe(true);
    expect(rules.monthlyRuleConsistent("2026-11-20", "OTHER")).toBe(false);
  });
});

describe("monthly expiry Python/Worker behavioral parity", () => {
  it.each(cases.map((row, index) => ({ ...row, index })))("$name", row => {
    const open = row.expiry_day_open ?? true;
    expect(rules.selectMonthlyExpiry(row.expiries, row.as_of, open)).toBe(row.expected);
    expect(rules.selectMonthly(row.expiries, row.as_of, open)?.rule ?? null).toBe(row.rule);
    expect(pythonChoices[row.index]?.expiry ?? null).toBe(row.expected);
    expect(pythonChoices[row.index]?.rule ?? null).toBe(row.rule);
  });
});

describe("producer / Python validator / Worker window admission parity", () => {
  it.each(windowCases.map((row, index) => ({ ...row, index })))("$period at $dte DTE", row => {
    const observed = pythonWindows[row.index];
    if (observed === undefined) throw new Error(`Missing Python observation for ${row.period} at ${row.dte} DTE`);
    expect(observed.producer_available).toBe(row.expected);
    expect(observed.validator_available).toBe(row.expected);
    expect(validateCoveredCallCycle(observed.probe, Date.parse(observed.probe_at), observed.probe_at, row.period) !== null).toBe(row.expected);
    if (row.expected) {
      expect(observed.produced_validated).toBe(true);
      expect(validateCoveredCallCycle(observed.produced, Date.parse(observed.produced_at), observed.produced_at, row.period)).not.toBeNull();
    }
  });
});
