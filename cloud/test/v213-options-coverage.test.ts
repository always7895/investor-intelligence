// G1A callers: the public, metadata-only global options SOURCE and GAP page (sealed lazy key v213:options-coverage:v1) through the real
// loader (loadOptionsCoverage), the real renderer (buildOptionsCoverageMessages) and the real rich-menu command route on a sealed
// MemoryKv snapshot. No network, no send, fake KV only. The Python builder side is tests/test_options_coverage_body.py.
//
// The body is built HERE from the Worker's own canonical inputs (the catalog JSON and the ADR map) exactly as the Python builder
// derives it, so every row checks the Worker's re-derivation, not a copy of one. The positive observed rows admit ONE synthetic
// provider id inside a test through a partial mock of the admission predicate (never in config); every other test keeps the real
// catalog decision (rights NONE).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import adrMap from "../../config/option-adr-map-v1.json";
import catalogJson from "../../config/public-options-provider-candidates.json";
import { parseQuery } from "../src/core";
import { assertLineMessages } from "../src/line-messages";
import { buildOptionsCoverageMessages, loadOptionsCoverage, OPTIONS_COVERAGE_KEY, type OptionsCoverageResult } from "../src/v213/options-coverage";
import * as admission from "../src/v213/public-options-admission";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";

vi.mock("../src/v213/public-options-admission", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/public-options-admission")>();
  return { ...real, admitPublicOption: vi.fn(real.admitPublicOption) };
});
const realAdmission = await vi.importActual<typeof import("../src/v213/public-options-admission")>("../src/v213/public-options-admission");

const SYNTHETIC_ID = "synthetic_g1a_test_only";
const IDENTITY = { provider_id: SYNTHETIC_ID, jurisdiction: "US", venue: "SYNTHVENUE", instrument_kind: "equity_option",
  quote_basis: "delayed", publication_scope: "public_line_quote" };
function admitSyntheticProvider(): void {
  vi.mocked(admission.admitPublicOption).mockImplementation((subject: unknown, nowMs?: number) => {
    const id = typeof subject === "object" && subject !== null ? (subject as { provider_id?: unknown }).provider_id : undefined;
    return id === SYNTHETIC_ID ? { ok: true, provider_id: SYNTHETIC_ID } : realAdmission.admitPublicOption(subject, nowMs);
  });
}

const RUN = "20260930T170000Z-abcdefabcde9";
const FIXED_NOW = Date.parse("2026-09-30T17:00:00Z");
const MAX_BODY_BYTES = 200_000;
const bridge = JSON.parse(readFileSync(resolve(__dirname, "fixtures/options-nonus-publisher.json"), "utf-8"));
type Json = Record<string, any>;

async function sha(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
const bytes = (text: string) => new TextEncoder().encode(text).byteLength;

/** A provider the (audited) catalog enables for LINE display; the catalog audit already ties this to a rights review or the pinned decision. */
const admittedByCatalog = (provider: Json) => provider.runtime_enabled === true && provider.line_quote_eligible === true;

/** The catalog-derived sections, built the way scripts/publish_sealed_snapshot.py builds them. */
function derivedBody(generatedAt = "2026-09-30T17:00:00Z", link: Json | null = null, observed: Json[] = []): Json {
  const providers = (catalogJson as unknown as { providers: Json[] }).providers;
  const byCode = new Map<string, string[]>();
  for (const provider of providers) for (const code of provider.jurisdictions as string[]) byCode.set(code, [...(byCode.get(code) ?? []), provider.id as string]);
  const codes = [...byCode.keys()].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  return {
    schema: "v213-options-coverage-v1", generated_at: generatedAt, purpose: "SOURCE_COVERAGE_METADATA_ONLY", options_link: link,
    // V11: the catalog may enable the pinned operator-accepted provider, so the admitted count and the root selection follow the catalog.
    catalog_summary: { catalog_provider_count: providers.length, public_admitted_provider_count: providers.filter(admittedByCatalog).length,
      production_provider_selected: (catalogJson as unknown as { production_quote_provider_selected: boolean }).production_quote_provider_selected },
    providers: providers.map(provider => ({ provider_id: provider.id, name: provider.name, authority: provider.authority, jurisdictions: provider.jurisdictions,
      data_roles: provider.data_roles, rights_status: provider.rights_status, rights_reviewed_at: provider.rights_reviewed_at,
      adapter_status: provider.adapter_status, runtime_enabled: provider.runtime_enabled, line_quote_eligible: provider.line_quote_eligible,
      public_admission: admittedByCatalog(provider) ? "ADMITTED" : "NOT_ADMITTED", declared: "CATALOG_DECLARED_UNVERIFIED" })),
    jurisdictions: codes.map(code => ({ code, provider_ids: byCode.get(code)!, catalog_provider_count: byCode.get(code)!.length })),
    local_capabilities: Object.keys((adrMap as unknown as { covered_markets: Json }).covered_markets).sort().map(market => ({
      market, capability: "COVERED_CALL_DELAYED_LOCAL_CANDIDATE", status: "LOCAL_UNADMITTED_NO_CATALOG_IDENTITY" })),
    observed, data_completeness: "NOT_REAUDITED",
    notes: ["CATALOG_COUNT_IS_NOT_INDEPENDENT_CONFIRMATION", "DECLARED_IS_NOT_COLLECTED_OR_LIVE", "EOD_INDEX_AND_DELTA_NOT_ADMITTED_BY_THIS_VIEW",
      "NO_RAW_QUOTES_IN_THIS_OBJECT", "ORIGIN_LINEAGE_UNKNOWN_NO_CORROBORATION_METRIC", "UNCATALOGUED_JURISDICTIONS_ARE_NOT_COVERAGE"],
  };
}

/** The Python-produced covered-call cycles SYNTHUS00 and SYNTHUS01 (weekly + monthly) of the nonus bridge fixture, each stamped with the
 * synthetic provider identity and the given quote instant. The document clock is `generatedAt`. */
function optionsDocument(generatedAt = "2026-09-30T17:00:00Z", quoteAt = generatedAt, tickers = ["SYNTHUS00", "SYNTHUS01"]): Json {
  const source = JSON.parse(bridge.cases.dte_us_matrix.bodies.options).options as Json;
  const options: Json = {};
  for (const ticker of tickers) {
    options[ticker] = {};
    for (const period of ["weekly", "monthly"]) {
      options[ticker][period] = { ...clone(source[ticker.startsWith("SYNTHUS") ? ticker : "SYNTHUS00"][period]), ticker, ...IDENTITY, timestamp: quoteAt };
    }
  }
  return { schema: "v213-options-v2", generated_at: generatedAt, options };
}

async function sealedEnv(lazy: Record<string, string>, flex = false) {
  const kv = new MemoryKv();
  kv.values.set("v213:top20-report:latest", JSON.stringify({ synthetic: "report" }));
  kv.values.set("last_successful_pipeline_timestamp", new Date(FIXED_NOW - 60_000).toISOString().replace(/\.\d{3}Z$/, "Z"));
  await sealUnboundReport(kv, RUN);
  const sealKey = `snapshot:${RUN}:${SNAPSHOT_SEAL_KEY}`;
  const seal = JSON.parse(kv.values.get(sealKey)!);
  for (const [key, body] of Object.entries(lazy)) {
    const digest = await sha(body);
    seal.objects[key] = { sha256: digest, utf8_bytes: bytes(body) };
    kv.values.set(`blob:v1:${digest}`, body);
  }
  const sealText = JSON.stringify(seal);
  kv.values.set(sealKey, sealText);
  const pointer = JSON.parse(kv.values.get("snapshot:current")!);
  pointer.seal_sha256 = await sha(sealText);
  kv.values.set("snapshot:current", JSON.stringify(pointer));
  return { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V21_TOP20_MAX_AGE_SECONDS: "7200", V213_LINE_PRESENTATION: flex ? "flex" : "text" };
}

/** Seal the coverage body (and, when given, the options body it links to) and run the real loader on the pinned view. */
async function load(coverage: unknown, options?: unknown, now = FIXED_NOW) {
  const lazy: Record<string, string> = {};
  if (coverage !== undefined) lazy[OPTIONS_COVERAGE_KEY] = typeof coverage === "string" ? coverage : JSON.stringify(coverage);
  if (options !== undefined) lazy["v213:options:v2"] = typeof options === "string" ? options : JSON.stringify(options);
  const env = await sealedEnv(lazy);
  const result = await loadOptionsCoverage(await pinPublicSnapshot(env as never), now);
  return { env, result };
}
async function linkOf(options: unknown): Promise<Json> {
  const text = JSON.stringify(options);
  return { key: "v213:options:v2", sha256: await sha(text), utf8_bytes: bytes(text) };
}
const textOf = (messages: readonly { type: string; text?: string }[]) => messages.map(message => message.text ?? "").join("\n");
const CAVEAT_HEAD = "宣告 ≠ 已收集 ≠ 已准入 ≠ 即時";
const UNKNOWN_LINE = "已准入資料筆數與時間：未知";

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(FIXED_NOW);
  vi.mocked(admission.admitPublicOption).mockImplementation(realAdmission.admitPublicOption);
});
afterEach(() => { vi.useRealTimers(); vi.mocked(admission.admitPublicOption).mockImplementation(realAdmission.admitPublicOption); });

describe("G1A loader states", () => {
  it("an unsealed view is SNAPSHOT_UNAVAILABLE and the page says so without any catalog content", async () => {
    const env = { PUBLIC_CACHE: asKv(new MemoryKv()), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()) };
    const result = await loadOptionsCoverage(await pinPublicSnapshot(env as never), FIXED_NOW);
    expect(result.status).toBe("SNAPSHOT_UNAVAILABLE");
    const text = textOf(buildOptionsCoverageMessages(result));
    expect(text).toContain("OPTIONS_COVERAGE_UNAVAILABLE（SNAPSHOT_UNAVAILABLE）");
    expect(text).not.toContain("目錄宣告的來源");
  });

  it("a sealed snapshot without the object is COVERAGE_ABSENT (the builder's refusal reads the same)", async () => {
    const { result } = await load(undefined);
    expect(result.status).toBe("COVERAGE_ABSENT");
    expect(textOf(buildOptionsCoverageMessages(result))).toContain("OPTIONS_COVERAGE_UNAVAILABLE（COVERAGE_ABSENT）");
  });

  it("a body over 200000 UTF-8 bytes is refused BEFORE JSON.parse ever sees it", async () => {
    const padding = JSON.stringify({ ...derivedBody(), pad: "x".repeat(MAX_BODY_BYTES) });
    expect(padding.length).toBeGreaterThan(MAX_BODY_BYTES);
    // multi-byte text counts in UTF-8 bytes, not code units: about 200 KB of CJK is far fewer than 200000 code units
    const cjk = JSON.stringify({ ...derivedBody(), pad: "期".repeat(66_700) });
    expect(cjk.length).toBeLessThan(MAX_BODY_BYTES);
    expect(bytes(cjk)).toBeGreaterThan(MAX_BODY_BYTES);
    const views = [await pinPublicSnapshot((await sealedEnv({ [OPTIONS_COVERAGE_KEY]: padding })) as never),
      await pinPublicSnapshot((await sealedEnv({ [OPTIONS_COVERAGE_KEY]: cjk })) as never)];
    const parse = vi.spyOn(JSON, "parse");
    try {
      for (const view of views) expect((await loadOptionsCoverage(view, FIXED_NOW)).status).toBe("COVERAGE_SCHEMA_INVALID");
      expect(parse.mock.calls.some(([argument]) => typeof argument === "string" && argument.length > 60_000)).toBe(false);
    } finally {
      parse.mockRestore();
    }
    expect((await load(derivedBody())).result.status).toBe("OK");  // a body inside the bound is read
  });

  it("malformed JSON and a wrong shape are COVERAGE_SCHEMA_INVALID", async () => {
    expect((await load("{not json")).result.status).toBe("COVERAGE_SCHEMA_INVALID");
    expect((await load("[]")).result.status).toBe("COVERAGE_SCHEMA_INVALID");
    expect((await load({ ...derivedBody(), purpose: "SOMETHING_ELSE" })).result.status).toBe("COVERAGE_SCHEMA_INVALID");
    expect((await load({ ...derivedBody(), generated_at: "2026-02-30T00:00:00Z" })).result.status).toBe("COVERAGE_SCHEMA_INVALID");
  });

  it("every declared section must equal the Worker's own derivation: a forged or widened body is invalid, never merged", async () => {
    const forgeries: [string, (body: Json) => void][] = [
      ["provider name", body => { body.providers[0].name = "Forged Exchange Name"; }],
      ["rights status", body => { const row = body.providers.find((item: Json) => item.rights_status === "review_before_enable"); row.rights_status = "reviewed_public_access"; }],
      ["line eligibility", body => { body.providers[0].line_quote_eligible = !body.providers[0].line_quote_eligible; }],
      ["provider dropped", body => { body.providers.pop(); body.catalog_summary.catalog_provider_count -= 1; }],
      ["jurisdiction expanded", body => { body.jurisdictions.push({ code: "ZZ", provider_ids: [body.providers[0].provider_id], catalog_provider_count: 1 }); }],
      ["jurisdiction relation", body => { body.jurisdictions[0].provider_ids = [body.providers[0].provider_id]; body.jurisdictions[0].catalog_provider_count = 1; }],
      ["local market added", body => { body.local_capabilities.push({ market: "JAPAN", capability: "COVERED_CALL_DELAYED_LOCAL_CANDIDATE", status: "LOCAL_UNADMITTED_NO_CATALOG_IDENTITY" }); }],
      // V11: the catalog may now select a provider, so the forgery flips the derived value instead of forcing true
      ["production provider selected", body => { body.catalog_summary.production_provider_selected = !body.catalog_summary.production_provider_selected; }],
      ["extra top-level strike", body => { body.strike = 1; }],
      ["extra provider field", body => { body.providers[0].bid = 1; }],
      ["unknown note", body => { body.notes.push("INVENTED_NOTE"); }],
      ["completeness claim", body => { body.data_completeness = "AUDITED"; }],
    ];
    for (const [label, mutate] of forgeries) {
      const body = derivedBody();
      mutate(body);
      expect((await load(body)).result.status, label).toBe("COVERAGE_SCHEMA_INVALID");
    }
    expect((await load(derivedBody())).result.status).toBe("OK");  // the unforged body is accepted
  });

  it("an observed row with a forbidden field is refused by shape", async () => {
    const options = optionsDocument();
    const row = { ...IDENTITY, cycle_count: 4, ticker_key_count: 2, quote_as_of_max: "2026-09-30T17:00:00Z" };
    admitSyntheticProvider();
    expect((await load(derivedBody("2026-09-30T17:00:00Z", await linkOf(options), [row]), options)).result.status).toBe("OK");
    expect((await load(derivedBody("2026-09-30T17:00:00Z", await linkOf(options), [{ ...row, bid: 1.2 }]), options)).result.status).toBe("COVERAGE_SCHEMA_INVALID");
    expect((await load(derivedBody("2026-09-30T17:00:00Z", await linkOf(options), [{ ...row, instrument_kind: "index_option" }]), options)).result.status)
      .toBe("COVERAGE_SCHEMA_INVALID");
  });

  it("freshness: 6 hours is fresh, 6 hours and one second is COVERAGE_STALE; 5 minutes ahead is tolerated, one second more is invalid", async () => {
    expect((await load(derivedBody("2026-09-30T11:00:00Z"))).result.status).toBe("OK");
    const stale = (await load(derivedBody("2026-09-30T10:59:59Z"))).result;
    expect(stale.status).toBe("COVERAGE_STALE");
    expect(stale.generated_at).toBe("2026-09-30T10:59:59Z");
    expect(textOf(buildOptionsCoverageMessages(stale))).toContain("超過 6 小時有效上限");
    expect((await load(derivedBody("2026-09-30T17:05:00Z"))).result.status).toBe("OK");
    expect((await load(derivedBody("2026-09-30T17:05:01Z"))).result.status).toBe("COVERAGE_SCHEMA_INVALID");
  });
});

describe("G1A observed rows", () => {
  it("a sealed options body with no admitted cycle is verified as no admitted rows, and a claimed positive count is refused", async () => {
    const options = optionsDocument();
    const link = await linkOf(options);
    const honest = await load(derivedBody("2026-09-30T17:00:00Z", link, []), options);
    expect(honest.result.status).toBe("OK");
    const honestText = textOf(buildOptionsCoverageMessages(honest.result));
    expect(honestText).toContain("沒有任何通過目錄准入的週期");
    expect(honestText).not.toContain(UNKNOWN_LINE);
    // a body that claims rows the Worker's own admission cannot reproduce is UNKNOWN, never printed
    const claimed = { ...IDENTITY, cycle_count: 4, ticker_key_count: 2, quote_as_of_max: "2026-09-30T17:00:00Z" };
    const forged = await load(derivedBody("2026-09-30T17:00:00Z", link, [claimed]), options);
    const forgedText = textOf(buildOptionsCoverageMessages(forged.result));
    expect(forgedText).toContain(UNKNOWN_LINE);
    expect(forgedText).not.toContain("SYNTHVENUE");
  });

  it("an admitted provider's rows are recomputed from the sealed options body and printed with counts and the latest quote time", async () => {
    admitSyntheticProvider();
    const options = optionsDocument();
    const row = { ...IDENTITY, cycle_count: 4, ticker_key_count: 2, quote_as_of_max: "2026-09-30T17:00:00Z" };
    const { result } = await load(derivedBody("2026-09-30T17:00:00Z", await linkOf(options), [row]), options);
    expect(result.status).toBe("OK");
    const text = textOf(buildOptionsCoverageMessages(result));
    expect(text).toContain("• synthetic_g1a_test_only｜US/SYNTHVENUE｜4 個週期、2 個代號鍵｜最新報價時間 2026-09-30T17:00:00Z");
    expect(text).toContain("標的數為封存期權文件的不同代號鍵，不是原生標的");
    expect(text).not.toContain(UNKNOWN_LINE);
    // the count is a count: a different claimed count or a different quote time is a mismatch
    for (const wrong of [{ ...row, cycle_count: 3 }, { ...row, ticker_key_count: 1 }, { ...row, quote_as_of_max: "2026-09-30T16:59:59Z" }]) {
      const mismatch = await load(derivedBody("2026-09-30T17:00:00Z", await linkOf(options), [wrong]), options);
      expect(textOf(buildOptionsCoverageMessages(mismatch.result))).toContain(UNKNOWN_LINE);
    }
  });

  it("the options link is checked by digest and byte length; a missing link or body is unknown, never zero", async () => {
    admitSyntheticProvider();
    const options = optionsDocument();
    const row = { ...IDENTITY, cycle_count: 4, ticker_key_count: 2, quote_as_of_max: "2026-09-30T17:00:00Z" };
    const link = await linkOf(options);
    for (const bad of [{ ...link, sha256: "0".repeat(64) }, { ...link, utf8_bytes: link.utf8_bytes + 1 }]) {
      const loaded = await load(derivedBody("2026-09-30T17:00:00Z", bad, [row]), options);
      expect(loaded.result.status).toBe("OK");
      expect(textOf(buildOptionsCoverageMessages(loaded.result))).toContain(UNKNOWN_LINE);
    }
    const noBody = await load(derivedBody("2026-09-30T17:00:00Z", link, [row]));  // link claimed, options body not sealed
    expect(textOf(buildOptionsCoverageMessages(noBody.result))).toContain(UNKNOWN_LINE);
    const noLink = await load(derivedBody("2026-09-30T17:00:00Z", null, []), options);
    const noLinkText = textOf(buildOptionsCoverageMessages(noLink.result));
    expect(noLinkText).toContain(UNKNOWN_LINE);
    expect(noLinkText).not.toContain("沒有任何通過目錄准入的週期");
  });

  it("a stale options document counts nothing: it is unknown, not a verified zero", async () => {
    admitSyntheticProvider();
    const options = optionsDocument("2026-09-30T10:59:59Z");
    const loaded = await load(derivedBody("2026-09-30T17:00:00Z", await linkOf(options), []), options);
    const text = textOf(buildOptionsCoverageMessages(loaded.result));
    expect(text).toContain(UNKNOWN_LINE);
    expect(text).not.toContain("沒有任何通過目錄准入的週期");
  });

  it("only the weekly and monthly keys of valid tickers are counted", async () => {
    admitSyntheticProvider();
    const options = optionsDocument();
    options.options["lowercase key"] = clone(options.options.SYNTHUS00);  // not a ticker syntax the loader accepts
    options.options.SYNTHUS02 = { daily: clone(options.options.SYNTHUS00.weekly) };  // no arbitrary period key
    options.options.UNAVAIL = { weekly: { unavailable: "producer says no" } };
    const row = { ...IDENTITY, cycle_count: 4, ticker_key_count: 2, quote_as_of_max: "2026-09-30T17:00:00Z" };
    const loaded = await load(derivedBody("2026-09-30T17:00:00Z", await linkOf(options), [row]), options);
    const text = textOf(buildOptionsCoverageMessages(loaded.result));
    expect(text).toContain("4 個週期、2 個代號鍵");
    expect(text).not.toContain(UNKNOWN_LINE);
  });

  it("a corrupt ticker entry makes the whole options document unprovable", async () => {
    admitSyntheticProvider();
    const options = optionsDocument();
    options.options.BROKEN = "not an object";
    const row = { ...IDENTITY, cycle_count: 4, ticker_key_count: 2, quote_as_of_max: "2026-09-30T17:00:00Z" };
    const loaded = await load(derivedBody("2026-09-30T17:00:00Z", await linkOf(options), [row]), options);
    expect(textOf(buildOptionsCoverageMessages(loaded.result))).toContain(UNKNOWN_LINE);
  });

  it("at most 24 observed rows are printed and the rest is counted explicitly; pages stay within 5 messages of 4400 characters", async () => {
    admitSyntheticProvider();
    const tickers = Array.from({ length: 30 }, (_, index) => `TCK${String(index).padStart(2, "0")}`);
    const options: Json = { schema: "v213-options-v2", generated_at: "2026-09-30T17:00:00Z", options: {} };
    const rows: Json[] = [];
    tickers.forEach((ticker, index) => {
      const venue = `V${String(index).padStart(2, "0")}`;
      const cycle = { ...clone(JSON.parse(bridge.cases.dte_us_matrix.bodies.options).options.SYNTHUS00.weekly), ticker, ...IDENTITY, venue,
        timestamp: "2026-09-30T17:00:00Z" };
      options.options[ticker] = { weekly: cycle };
      rows.push({ ...IDENTITY, venue, cycle_count: 1, ticker_key_count: 1, quote_as_of_max: "2026-09-30T17:00:00Z" });
    });
    const loaded = await load(derivedBody("2026-09-30T17:00:00Z", await linkOf(options), rows), options);
    expect(loaded.result.status).toBe("OK");
    const messages = buildOptionsCoverageMessages(loaded.result) as { type: string; text: string }[];
    assertLineMessages(messages as never);
    expect(messages.length).toBeGreaterThanOrEqual(1);
    expect(messages.length).toBeLessThanOrEqual(5);
    for (const message of messages) {
      expect(message.text.length).toBeLessThanOrEqual(4400);
      expect(message.text).toContain(CAVEAT_HEAD);  // the caveat is on every page
    }
    expect(messages[messages.length - 1]!.text).toContain("快捷指令：");
    const text = textOf(messages);
    expect(text).toContain("（共 30 列，顯示 24 列，另有 6 列未顯示）");
    expect(text).toContain("US/V23｜");
    expect(text).not.toContain("US/V24｜");
    expect((text.match(/個代號鍵｜最新報價時間/g) ?? []).length).toBe(24);
  });
});

describe("G1A render-time safety", () => {
  it("a result the module did not issue renders as unavailable: spread, JSON clone and hand-built objects", async () => {
    const { result } = await load(derivedBody());
    expect(result.status).toBe("OK");
    expect(Object.isFrozen(result)).toBe(true);
    expect(textOf(buildOptionsCoverageMessages(result))).toContain("目錄宣告的來源");
    const handBuilt: OptionsCoverageResult = { status: "OK", generated_at: "2026-09-30T17:00:00Z" };
    for (const forged of [{ ...result }, JSON.parse(JSON.stringify(result)) as OptionsCoverageResult, handBuilt, structuredClone(result)]) {
      const text = textOf(buildOptionsCoverageMessages(forged));
      expect(text).toContain("OPTIONS_COVERAGE_UNAVAILABLE（COVERAGE_SCHEMA_INVALID）");
      expect(text).not.toContain("目錄宣告的來源");
    }
    expect(textOf(buildOptionsCoverageMessages(null as unknown as OptionsCoverageResult))).toContain("COVERAGE_SCHEMA_INVALID");
    expect(textOf(buildOptionsCoverageMessages(result))).toContain("目錄宣告的來源");  // the issued wrapper is unaffected
  });

  it("the real clock is rechecked at render time: a verified page does not outlive 6 hours", async () => {
    const { result } = await load(derivedBody());
    vi.setSystemTime(FIXED_NOW + 6 * 3600_000);
    expect(textOf(buildOptionsCoverageMessages(result))).toContain("目錄宣告的來源");  // exactly at the limit is still valid
    vi.setSystemTime(FIXED_NOW + 6 * 3600_000 + 1);
    const text = textOf(buildOptionsCoverageMessages(result));
    expect(text).toContain("OPTIONS_COVERAGE_UNAVAILABLE（COVERAGE_STALE）");
    expect(text).not.toContain("目錄宣告的來源");
  });

  it("a counted cycle that ages out after loading drops the count to unknown without a late stale-positive row", async () => {
    admitSyntheticProvider();
    const options = optionsDocument("2026-09-30T12:00:00Z");  // five hours old at load time, valid for one more hour
    const row = { ...IDENTITY, cycle_count: 4, ticker_key_count: 2, quote_as_of_max: "2026-09-30T12:00:00Z" };
    const { result } = await load(derivedBody("2026-09-30T17:00:00Z", await linkOf(options), [row]), options);
    expect(result.status).toBe("OK");
    expect(textOf(buildOptionsCoverageMessages(result))).toContain("4 個週期、2 個代號鍵");
    vi.setSystemTime(Date.parse("2026-09-30T18:00:01Z"));
    const later = textOf(buildOptionsCoverageMessages(result));
    expect(later).toContain(UNKNOWN_LINE);
    expect(later).not.toContain("SYNTHVENUE");
    expect(later).toContain("目錄宣告的來源");  // the catalog part of the page is still within its own window
  });

  it("an admission window that closes after loading also drops the counted row", async () => {
    admitSyntheticProvider();
    const options = optionsDocument();
    const row = { ...IDENTITY, cycle_count: 4, ticker_key_count: 2, quote_as_of_max: "2026-09-30T17:00:00Z" };
    const { result } = await load(derivedBody("2026-09-30T17:00:00Z", await linkOf(options), [row]), options);
    expect(textOf(buildOptionsCoverageMessages(result))).toContain("SYNTHVENUE");
    vi.mocked(admission.admitPublicOption).mockImplementation(realAdmission.admitPublicOption);  // the provider is no longer admitted
    const text = textOf(buildOptionsCoverageMessages(result));
    expect(text).toContain(UNKNOWN_LINE);
    expect(text).not.toContain("SYNTHVENUE");
  });
});

describe("G1A page content", () => {
  it("prints the catalog's own providers and literal jurisdiction codes with the caveats, and adds no market or price", async () => {
    const { result } = await load(derivedBody());
    const messages = buildOptionsCoverageMessages(result) as { type: string; text: string }[];
    assertLineMessages(messages as never);
    expect(messages.length).toBeLessThanOrEqual(5);
    const text = textOf(messages);
    const providers = (catalogJson as unknown as { providers: Json[] }).providers;
    expect(text).toContain(`目錄宣告的來源（共 ${providers.length} 筆）：`);
    for (const provider of providers) expect(text).toContain(`• ${provider.id}｜${provider.authority}｜${(provider.jurisdictions as string[]).join("/")}｜權利:${provider.rights_status}｜轉接:${provider.adapter_status}｜宣告未驗證`);
    expect(text).toContain("GLOBAL 只是角色代碼，不代表所有國家");
    expect(text).toContain("本機路由宣告（來自備兌買權路由設定，不是觀察到的資料");
    expect(text).toContain("SWEDEN、US");  // the covered_markets KEYS, sorted
    expect(text).toContain("未列出的國家或地區：沒有目錄來源或屬未知，未列出不代表涵蓋");
    expect(text).toContain("目錄筆數只是目錄筆數，不是獨立佐證");
    expect(text).toContain("本服務不下單");
    expect(text).not.toMatch(/\d+\.\d\d (?:USD|SEK)/);  // no price
    for (const message of messages) expect(message.text).toContain(CAVEAT_HEAD);
  });
});

describe("G1A rich-menu command through the real handler", () => {
  it("the exact command and its aliases answer the verified page on a sealed MemoryKv env, in text and flex mode", async () => {
    for (const flex of [false, true]) {
      const env = await sealedEnv({ [OPTIONS_COVERAGE_KEY]: JSON.stringify(derivedBody()) }, flex);
      for (const command of ["全球期權來源與缺口", "全球期權來源", "期權來源與缺口", "全球期權來源與缺口 文字", "  全球期權來源與缺口  "]) {
        const messages = await v213PublicLineAnswer(env as never, parseQuery(command)) as { type: string; text?: string }[];
        expect(messages, command).toBeDefined();
        assertLineMessages(messages as never);
        expect(messages.every(message => message.type === "text"), command).toBe(true);
        const text = textOf(messages);
        expect(text, command).toContain("【全球期權來源與缺口】來源狀態說明（非即時報價、非涵蓋保證）");
        expect(text, command).toContain("目錄宣告的來源");
        expect(text, command).not.toContain("OPTIONS_COVERAGE_UNAVAILABLE");
      }
    }
  });

  it("the command reports the unavailable states instead of falling through to generic options routing", async () => {
    const absent = await sealedEnv({});
    const absentText = textOf(await v213PublicLineAnswer(absent as never, parseQuery("全球期權來源與缺口")) as { type: string; text?: string }[]);
    expect(absentText).toContain("OPTIONS_COVERAGE_UNAVAILABLE（COVERAGE_ABSENT）");
    const forged = await sealedEnv({ [OPTIONS_COVERAGE_KEY]: JSON.stringify({ ...derivedBody(), purpose: "X" }) });
    expect(textOf(await v213PublicLineAnswer(forged as never, parseQuery("全球期權來源與缺口")) as { type: string; text?: string }[]))
      .toContain("OPTIONS_COVERAGE_UNAVAILABLE（COVERAGE_SCHEMA_INVALID）");
    const empty = { PUBLIC_CACHE: asKv(new MemoryKv()), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()) };
    expect(textOf(await v213PublicLineAnswer(empty as never, parseQuery("全球期權來源與缺口")) as { type: string; text?: string }[]))
      .toContain("OPTIONS_COVERAGE_UNAVAILABLE（SNAPSHOT_UNAVAILABLE）");
  });

  it("a near-miss text is not the command and does not produce the source page", async () => {
    const env = await sealedEnv({ [OPTIONS_COVERAGE_KEY]: JSON.stringify(derivedBody()) });
    for (const command of ["全球期權來源與缺口嗎", "全球期權", "期權來源"]) {
      const answer = await v213PublicLineAnswer(env as never, parseQuery(command));
      const text = typeof answer === "string" ? answer : Array.isArray(answer) ? textOf(answer as { type: string; text?: string }[]) : "";
      expect(text, command).not.toContain("【全球期權來源與缺口】來源狀態說明");
    }
  });
});
