import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { BOTTLENECK_V3_KEY, loadBottleneckV3, parseBottleneckV3, type BottleneckV3 } from "../src/v213/bottleneck-v3";
import type { PublicSnapshotView } from "../src/v213/public-snapshot";

// The shared B3-WIRE-01 cross-language fixture (r2): the exact body strings the real Python lazy
// publisher emitted (tests/fixtures/revenue-guidance-wire-v1-functional.json), legacy and enveloped.
// The report's generated_at is aligned to the embedded golden evidence cutoff
// 2026-09-28T15:00:00Z, and the parser's now is pinned to that same historical instant (injected
// clock for functional replay, not fresh publication evidence). Ordinary positive/compatibility
// tests only: no malformed, adversarial, native or security cases in this phase.
const fixture = JSON.parse(
  readFileSync(resolve(__dirname, "..", "..", "tests", "fixtures", "revenue-guidance-wire-v1-functional.json"), "utf-8"),
) as {
  v3_nvda: { m6: { amount: number }; m12: { amount: number } };
  expected_legacy_body: Record<string, string>;
  expected_wire_body: Record<string, string>;
};

const getFixtureString = (record: Record<string, string>, key: string) => {
  const val = record[key];
  if (val === undefined) throw new Error(`Missing key ${key} in fixture`);
  return val;
};

const NOW = Date.parse("2026-09-28T15:00:00Z");
const legacyRaw = JSON.parse(getFixtureString(fixture.expected_legacy_body, BOTTLENECK_V3_KEY)) as unknown;
const wireRaw = JSON.parse(getFixtureString(fixture.expected_wire_body, BOTTLENECK_V3_KEY)) as unknown;
const requiredDoc = (doc: BottleneckV3 | null): BottleneckV3 => {
  if (doc === null) throw new Error("Required fixture document did not parse");
  return doc;
};
const entryOf = (doc: BottleneckV3, symbol: string) => {
  const entry = doc.top.find(e => e.symbol === symbol);
  if (!entry) throw new Error(`Entry ${symbol} missing`);
  return entry;
};
const forecastOf = (entry: BottleneckV3["top"][number]) => {
  const forecast = entry.forecast;
  if (forecast === undefined) throw new Error(`Forecast missing for ${entry.symbol}`);
  return forecast;
};
const forecastsOf = (doc: BottleneckV3) => doc.top.map(entry => forecastOf(entry));

describe("B3-WIRE-01 transport-v1 through the real bottleneck-v3 reader", () => {
  // Negotiation validation is explicitly deferred by B3-WIRE-01. These are
  // negative admission tests, NOT permission to enable machine or trust labels.
  it.each([undefined, "UNKNOWN", "DISABLED"])("admission_mode=%s cannot enable transport or machine admission", async mode => {
    const raw = JSON.parse(getFixtureString(fixture.expected_wire_body, BOTTLENECK_V3_KEY));
    for (const row of raw.top) {
      if (mode === undefined) delete row.outlook.order_forecast_v3.admission_mode;
      else row.outlook.order_forecast_v3.admission_mode = mode;
    }
    const disabled = requiredDoc(parseBottleneckV3(raw, NOW));
    for (const entry of disabled.top) {
      expect(forecastOf(entry).m6).toMatchObject({ status: "UNAVAILABLE", reason: "INVALID" });
      expect(forecastOf(entry).m12).toMatchObject({ status: "UNAVAILABLE", reason: "INVALID" });
    }
    // The label is currently ignored, but the independent explicit option and
    // untouched strict payload parser are still required. Lock this limitation.
    const enabled = requiredDoc(parseBottleneckV3(raw, NOW, { guidanceWireEnabled: true }));
    expect(forecastsOf(enabled)).toEqual(forecastsOf(requiredDoc(parseBottleneckV3(legacyRaw, NOW))));
    expect(enabled.top.every(e => e.forecast?.machineAdmitted !== true)).toBe(true);

    // A spoofed label never rescues an invalid payload or falls back to valid sibling v2.
    for (const row of raw.top) row.outlook.order_forecast_v3.payload = { version: 3, issuer: "FOREIGN" };
    const invalid = requiredDoc(parseBottleneckV3(raw, NOW, { guidanceWireEnabled: true }));
    for (const entry of invalid.top) {
      expect(forecastOf(entry).m6).toMatchObject({ status: "UNAVAILABLE", reason: "INVALID" });
      expect(forecastOf(entry).m12).toMatchObject({ status: "UNAVAILABLE", reason: "INVALID" });
    }
  });

  it("legacy body parses identically with options omitted, explicit false and true", () => {
    const omitted = requiredDoc(parseBottleneckV3(legacyRaw, NOW));
    const disabled = parseBottleneckV3(legacyRaw, NOW, { guidanceWireEnabled: false });
    const enabledOnLegacy = parseBottleneckV3(legacyRaw, NOW, { guidanceWireEnabled: true });
    expect(omitted).not.toBeNull();
    // Normal backwards compatibility: the legacy v3 value passes the same strict parser on every path.
    expect(omitted).toEqual(disabled);
    expect(omitted).toEqual(enabledOnLegacy);
    // Report values stay intact (generated_at aligned to the golden evidence cutoff).
    expect(omitted.generated_at).toBe("2026-09-28T15:00:00Z");
    expect(omitted.top).toHaveLength(10);
    expect(omitted.top.map(entry => entry.symbol)).toEqual(
      ["NVDA", "SNDK", "SYM3", "SYM4", "SYM5", "SYM6", "SYM7", "SYM8", "SYM9", "SYM10"],
    );
    // The ordinary available branch: real NVDA available values (amounts from the shared fixture).
    const nvda = entryOf(omitted, "NVDA");
    const nvdaForecast = forecastOf(nvda);
    expect(nvdaForecast.m6.status).toBe("AVAILABLE");
    expect(nvdaForecast.m12.status).toBe("AVAILABLE");
    if (nvdaForecast.m6.status !== "AVAILABLE" || nvdaForecast.m12.status !== "AVAILABLE") {
      throw new Error("NVDA fixture requires both AVAILABLE horizons");
    }
    expect(nvdaForecast.m6.amount).toBe(fixture.v3_nvda.m6.amount);
    expect(nvdaForecast.m12.amount).toBe(fixture.v3_nvda.m12.amount);
    // The ordinary unavailable branch: SNDK's FRESHNESS_UNVERIFIED stays unchanged.
    const sndk = entryOf(omitted, "SNDK");
    const sndkForecast = forecastOf(sndk);
    expect(sndkForecast.m6.status).toBe("UNAVAILABLE");
    if (sndkForecast.m6.status === "UNAVAILABLE") expect(sndkForecast.m6.reason).toBe("FRESHNESS_UNVERIFIED");
    if (sndkForecast.m12.status === "UNAVAILABLE") expect(sndkForecast.m12.reason).toBe("FRESHNESS_UNVERIFIED");
  });

  it("enabled transport body normalizes to the same forecasts as the strict legacy parse", () => {
    const legacyDoc = requiredDoc(parseBottleneckV3(legacyRaw, NOW));
    const wireDoc = requiredDoc(parseBottleneckV3(wireRaw, NOW, { guidanceWireEnabled: true }));
    expect(legacyDoc).not.toBeNull();
    expect(wireDoc).not.toBeNull();
    // The opt-in decode feeds the full payload (plus the unchanged sibling v2) into the untouched
    // parseOrderForecastV3: per-entry normalized forecasts are identical.
    expect(forecastsOf(wireDoc)).toEqual(forecastsOf(legacyDoc));
    // On the enabled route too: real NVDA available values and SNDK's ordinary FRESHNESS_UNVERIFIED.
    const wireNvda = entryOf(wireDoc, "NVDA");
    const wireNvdaForecast = forecastOf(wireNvda);
    expect(wireNvdaForecast.m6.status).toBe("AVAILABLE");
    if (wireNvdaForecast.m6.status === "AVAILABLE") expect(wireNvdaForecast.m6.amount).toBe(fixture.v3_nvda.m6.amount);
    if (wireNvdaForecast.m12.status === "AVAILABLE") expect(wireNvdaForecast.m12.amount).toBe(fixture.v3_nvda.m12.amount);
    const wireSndk = entryOf(wireDoc, "SNDK");
    const wireSndkForecast = forecastOf(wireSndk);
    if (wireSndkForecast.m6.status === "UNAVAILABLE") expect(wireSndkForecast.m6.reason).toBe("FRESHNESS_UNVERIFIED");
    if (wireSndkForecast.m12.status === "UNAVAILABLE") expect(wireSndkForecast.m12.reason).toBe("FRESHNESS_UNVERIFIED");
    // The disabled reader of the same enveloped body keeps the existing invalid-v3 result (no fallback):
    // the envelope has no version, so the strict parser yields its standard INVALID horizons.
    const disabledOnWire = requiredDoc(parseBottleneckV3(wireRaw, NOW));
    expect(disabledOnWire).not.toBeNull();
    for (const entry of disabledOnWire.top) {
      const f = forecastOf(entry);
      if (f.m6.status === "UNAVAILABLE") expect(f.m6.reason).toBe("INVALID");
      if (f.m12.status === "UNAVAILABLE") expect(f.m12.reason).toBe("INVALID");
    }
  });

  it("loadBottleneckV3 consumes the exact sealed body through the normal loader route", async () => {
    const requested: string[][] = [];
    // An in-memory already-sealed PublicSnapshotView stand-in for the loader's sealed-view
    // prerequisite; it proves the loader->parser route and key request, not sealed-view integrity.
    const view: PublicSnapshotView = {
      runId: "wire-fixture",
      kind: "snapshot",
      integrity: "sealed",
      json: async <T>(logicalKeys: string[]): Promise<T | null> => {
        requested.push([...logicalKeys]);
        return JSON.parse(getFixtureString(fixture.expected_wire_body, BOTTLENECK_V3_KEY)) as T;
      },
      text: async () => null,
      hasSealedObject: () => true,
    };
    // The loader keeps its production current-time default (Date.now); pin the declared historical
    // clock for this replay and restore the real one. The reader/parser are never stubbed.
    const realNow = Date.now;
    Date.now = () => NOW;
    try {
      const loaded = requiredDoc(await loadBottleneckV3(view, { guidanceWireEnabled: true }));
      expect(requested).toEqual([[BOTTLENECK_V3_KEY]]);
      expect(loaded).not.toBeNull();
      const legacyDoc = requiredDoc(parseBottleneckV3(legacyRaw, NOW));
      expect(forecastsOf(loaded)).toEqual(forecastsOf(legacyDoc));
      // Through the loader route as well: real NVDA available values and SNDK's FRESHNESS_UNVERIFIED.
      const loadedNvda = entryOf(loaded, "NVDA");
      const loadedNvdaForecast = forecastOf(loadedNvda);
      expect(loadedNvdaForecast.m6.status).toBe("AVAILABLE");
      if (loadedNvdaForecast.m6.status === "AVAILABLE") expect(loadedNvdaForecast.m6.amount).toBe(fixture.v3_nvda.m6.amount);
      if (loadedNvdaForecast.m12.status === "AVAILABLE") expect(loadedNvdaForecast.m12.amount).toBe(fixture.v3_nvda.m12.amount);
      const loadedSndk = entryOf(loaded, "SNDK");
      const loadedSndkForecast = forecastOf(loadedSndk);
      if (loadedSndkForecast.m6.status === "UNAVAILABLE") expect(loadedSndkForecast.m6.reason).toBe("FRESHNESS_UNVERIFIED");
      if (loadedSndkForecast.m12.status === "UNAVAILABLE") expect(loadedSndkForecast.m12.reason).toBe("FRESHNESS_UNVERIFIED");
    } finally {
      Date.now = realNow;
    }
  });
});
