// V11 W1 + W2 on the Worker: the operator-accepted (unlicensed) Yahoo option provider admitted through the catalog, and the previous-session
// carry-forward basis, through the REAL callers: admitPublicOption, validateCoveredCallCycle, loadDetailedOptionObservation, the renderer and
// processAuthorizedLineEvent on a sealed MemoryKv snapshot. The sealed options object is a slice of what the real Python producer and sealer emit
// (cloud/test/fixtures/v11-options-carry.json, byte-pinned by tests/test_v11_options_carry_forward.py).
//
// The catalog is the REPOSITORY catalog with the test copy of the pinned operator-accepted entry applied through vi.doMock (the Worker imports the
// catalog JSON at build time), so these rows prove the target state without depending on the repository catalog edit; the parity row compares
// the copy with config/public-options-provider-candidates.json when the entry is there. Synthetic LINE credentials; every other network call throws.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";
import { effectiveDays, exchangeDate, usRegularSessionOpen, weeklyWeekFor, dayMs } from "../src/v213/option-recommendation-rules";
import { SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";

const CATALOG_MODULE = "../../config/public-options-provider-candidates.json";
const repository = JSON.parse(readFileSync(resolve(__dirname, CATALOG_MODULE), "utf-8")) as Doc;
const fixture = JSON.parse(readFileSync(resolve(__dirname, "fixtures/v11-options-carry.json"), "utf-8")) as Doc;
type Doc = Record<string, any>;
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

const YAHOO_ID = "yahoo_finance_option_chain";
const DECISION = { decision_id: "OPERATOR-DECISION-OPTIONS-DISPLAY-ALL-20261013", decided_at: "2026-10-13", record: "docs/PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW.md" };
const SCOPE = { jurisdiction: "US", venue: "US_LISTED_OPTIONS", instrument_kind: "equity_option", quote_basis: "delayed", publication_scope: "public_line_quote" };
const YAHOO_ENTRY: Doc = {
  id: YAHOO_ID, name: "Yahoo Finance US option chains (unofficial, delayed; operator-accepted display)", authority: "Yahoo Finance", jurisdictions: ["US"],
  data_roles: ["delayed_option_quotes"], official_url: "https://finance.yahoo.com/", rights_evidence_url: "https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
  rights_status: "operator_accepted_unlicensed", automated_access_allowed: null, rights_reviewed_at: "2026-10-13",
  review_notes: "TEST COPY: not a rights review and not a licence; the operator decision of 2026-10-13 accepts the exposure.",
  adapter_status: "candidate_implemented", runtime_enabled: true, line_quote_eligible: true, review_valid_through: "2027-10-13",
  admitted_scopes: [SCOPE, { ...SCOPE, quote_basis: "previous_session_last" }], operator_decision: DECISION,
};

/** The repository catalog with the test copy of the Yahoo entry (replacing a repository one) and the matching root selection. */
function catalogWith(mutate?: (yahoo: Doc, doc: Doc) => void, withYahoo = true): Doc {
  const doc = clone(repository);
  // V13: the Nasdaq Nordic entry (decided 2026-10-17) lies after this file's 2026-10-13 clocks, where it would make the whole catalog unusable;
  // its own rows live in v13-nordic-options-operator-accepted.test.ts. Dropping it here keeps these rows proving the Yahoo behaviour alone.
  doc.providers = doc.providers.filter((item: Doc) => item.id !== YAHOO_ID && item.id !== "nasdaq_nordic_option_chain");
  const yahoo = clone(YAHOO_ENTRY);
  if (withYahoo) doc.providers.push(yahoo);
  doc.production_quote_provider_selected = withYahoo;
  mutate?.(yahoo, doc);
  return doc;
}

const RUN = "20261013T140000Z-abcdefabcde3";
const IN_NOW = Date.parse("2026-10-13T15:05:00Z");     // 11:05 New York, five minutes after the in-session run
const OFF_NOW = Date.parse("2026-10-13T21:35:00Z");    // 17:35 New York, after the close
const IN_DOC = fixture.in_session.options as Doc;
const OFF_DOC = fixture.off_session.options as Doc;

async function world(catalogDoc: Doc) {
  vi.resetModules();
  vi.doMock(CATALOG_MODULE, () => ({ default: catalogDoc }));
  return {
    admission: await import("../src/v213/public-options-admission"),
    covered: await import("../src/v213/covered-call"),
    observations: await import("../src/v213/market-observations"),
    coverage: await import("../src/v213/options-coverage"),
    snapshot: await import("../src/v213/public-snapshot"),
    worker: await import("../src/v211/worker"),
    production: await import("../src/v213/production-worker"),
  };
}
type World = Awaited<ReturnType<typeof world>>;

async function sha(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

async function sealedEnv(options: Doc, generatedAt: string, now: number, style: "text" | "flex" = "text") {
  const kv = new MemoryKv();
  kv.values.set("v213:top20-report:latest", JSON.stringify({ synthetic: "report" }));
  kv.values.set("last_successful_pipeline_timestamp", new Date(now - 60_000).toISOString().replace(/\.\d{3}Z$/, "Z"));
  await sealUnboundReport(kv, RUN);
  const body = JSON.stringify({ schema: "v213-options-v2", generated_at: generatedAt, options });
  const sealKey = `snapshot:${RUN}:${SNAPSHOT_SEAL_KEY}`;
  const seal = JSON.parse(kv.values.get(sealKey)!);
  const digest = await sha(body);
  seal.objects["v213:options:v2"] = { sha256: digest, utf8_bytes: new TextEncoder().encode(body).byteLength };
  kv.values.set(`blob:v1:${digest}`, body);
  const sealText = JSON.stringify(seal);
  kv.values.set(sealKey, sealText);
  const pointer = JSON.parse(kv.values.get("snapshot:current")!);
  pointer.seal_sha256 = await sha(sealText);
  kv.values.set("snapshot:current", JSON.stringify(pointer));
  return {
    PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V21_TOP20_MAX_AGE_SECONDS: "7200", V213_LINE_PRESENTATION: style,
  };
}

/** The production LINE entry, fetch stubbed to capture the reply: the messages LINE would receive. */
async function lineReply(w: World, env: any, command: string, now: number): Promise<string> {
  let messages: any[] = [];
  const network = vi.fn(async (url: string, init: RequestInit) => {
    if (url !== "https://api.line.me/v2/bot/message/reply") throw new Error("NETWORK_FORBIDDEN");
    messages = JSON.parse(String(init.body)).messages;
    return new Response("{}", { status: 200 });
  });
  vi.stubGlobal("fetch", network);
  await w.worker.processAuthorizedLineEvent(await w.production.freeRelayRequestEnv({
    ...env, LINE_CHANNEL_SECRET: "SYNTHETIC_NOT_REAL", LINE_CHANNEL_ACCESS_TOKEN: "SYNTHETIC_NOT_REAL", CURRENT_PUBLIC_DATA_ENABLED: "true",
  }), { waitUntil() { throw new Error("MODEL_JOB_FORBIDDEN"); } } as any,
  { type: "message", replyToken: "SYNTHETIC_REPLY", timestamp: now, message: { id: "SYNTHETIC_MESSAGE", type: "text", text: command } }, "SYNTHETIC_TENANT");
  expect(network).toHaveBeenCalledTimes(1);
  return JSON.stringify(messages);
}

/** A capture moved to another instant with every figure kept consistent (asof_date, dte, weekly marker, annualized yield). */
function captureAt(base: Doc, timestamp: string, expiry: string, period: "weekly" | "monthly" = "weekly"): Doc {
  const cycle = clone(base);
  const asof = exchangeDate(Date.parse(timestamp), "US");
  const dte = Math.round((dayMs(expiry)! - dayMs(asof)!) / 86_400_000);
  Object.assign(cycle, { timestamp, expiry, asof_date: asof, dte });
  if (period === "weekly") cycle.weekly_week = weeklyWeekFor(expiry, asof);
  for (const item of [...cycle.suggestions, ...(cycle.middle_suggestion ? [cycle.middle_suggestion] : [])]) {
    item.annualized_yield = item.limit_price / cycle.spot * 365 / effectiveDays(dte);
  }
  return cycle;
}

const carried = (name = "T00", period = "weekly"): Doc => clone(OFF_DOC[name][period]);
const live = (name = "T00", period = "weekly"): Doc => clone(IN_DOC[name][period]);
const UNVERIFIED = "封存之期權觀察未通過驗證";
const LABEL = "前一交易時段最後報價（2026-10-13 11:00 美東）；開盤後價格會變動";

beforeEach(() => { vi.setSystemTime(OFF_NOW); });
afterEach(() => { vi.unstubAllGlobals(); vi.doUnmock(CATALOG_MODULE); });

describe("W1 admission: the pinned operator decision, through the catalog", () => {
  it("admits the claimed Yahoo identity for the delayed and the previous-session basis, flagged as operator-accepted", async () => {
    const { admission } = await world(catalogWith());
    for (const quote_basis of ["delayed", "previous_session_last"]) {
      expect(admission.admitPublicOption({ ...SCOPE, provider_id: YAHOO_ID, quote_basis }, IN_NOW)).toEqual({ ok: true, provider_id: YAHOO_ID, operator_accepted: true });
    }
    // the fixture's real producer output carries exactly this claimed identity
    const cycle = live();
    expect({ provider_id: cycle.provider_id, jurisdiction: cycle.jurisdiction, venue: cycle.venue, instrument_kind: cycle.instrument_kind, publication_scope: cycle.publication_scope })
      .toEqual({ provider_id: YAHOO_ID, jurisdiction: "US", venue: "US_LISTED_OPTIONS", instrument_kind: "equity_option", publication_scope: "public_line_quote" });
    expect(admission.admitPublicOption(cycle, IN_NOW)).toEqual({ ok: true, provider_id: YAHOO_ID, operator_accepted: true });
  });

  it("denies every other claim: another scope, provider, basis or a bare label, and every other provider decision stays rejected", async () => {
    const { admission } = await world(catalogWith());
    const denied = { ok: false, reason: "OPTION_RIGHTS_NOT_ADMITTED" };
    const claim = { ...SCOPE, provider_id: YAHOO_ID };
    for (const change of [{ venue: "NASDAQ_STOCKHOLM" }, { jurisdiction: "SE" }, { instrument_kind: "eod_index" }, { quote_basis: "realtime" }, { quote_basis: "asof_close" },
      { publication_scope: "local_research" }, { provider_id: `${YAHOO_ID} ` }, { provider_id: "yahoo_finance_unreviewed" }]) {
      expect(admission.admitPublicOption({ ...claim, ...change }, IN_NOW)).toEqual(denied);
    }
    for (const key of Object.keys(claim)) {
      expect(admission.admitPublicOption({ ...claim, [key]: undefined }, IN_NOW)).toEqual(denied);
      expect(admission.admitPublicOption({ ...claim, [key]: 1 }, IN_NOW)).toEqual(denied);
    }
    expect(admission.admitPublicOption({ rights_status: "reviewed_public_access", admission_status: "ADMITTED", source: "Yahoo Finance option chain" }, IN_NOW)).toEqual(denied);
    for (const provider of repository.providers.filter((item: Doc) => item.id !== YAHOO_ID)) {
      expect(admission.admitPublicOption({ ...claim, provider_id: provider.id }, IN_NOW)).toEqual(denied);
    }
  });

  it("refuses a forged or altered entry (the whole catalog becomes unusable), and a revert admits nothing", async () => {
    const mutations: Record<string, (yahoo: Doc, doc: Doc) => void> = {
      "decision id": yahoo => { yahoo.operator_decision.decision_id = "OPERATOR-DECISION-SOMETHING-ELSE"; },
      "decision date": yahoo => { yahoo.operator_decision.decided_at = "2026-10-12"; },
      "extra decision key": yahoo => { yahoo.operator_decision.approved_by = "someone"; },
      "decision removed": yahoo => { delete yahoo.operator_decision; },
      "review date": yahoo => { yahoo.rights_reviewed_at = "2026-10-12"; },
      "claims automation": yahoo => { yahoo.automated_access_allowed = true; },
      "no adapter": yahoo => { yahoo.adapter_status = "not_implemented"; },
      "foreign venue scope": yahoo => { yahoo.admitted_scopes[0].venue = "OTHERVENUE"; },
      "scope outside the pin": yahoo => { yahoo.admitted_scopes.push({ ...SCOPE, jurisdiction: "SE" }); yahoo.jurisdictions.push("SE"); },
      "no scopes": yahoo => { yahoo.admitted_scopes = []; },
      "review window closed": yahoo => { yahoo.review_valid_through = "2026-10-12"; },
      "root selection off": (_yahoo, doc) => { doc.production_quote_provider_selected = false; },
      "reviewed status without review": yahoo => { yahoo.rights_status = "reviewed_public_access"; },
      "revert: both flags off but still selected": yahoo => { yahoo.runtime_enabled = false; yahoo.line_quote_eligible = false; },
      "partial activation": yahoo => { yahoo.line_quote_eligible = false; },
    };
    for (const [name, mutate] of Object.entries(mutations)) {
      const { admission } = await world(catalogWith(mutate));
      expect(admission.admitPublicOption({ ...SCOPE, provider_id: YAHOO_ID }, IN_NOW), name).toEqual({ ok: false, reason: "OPTION_RIGHTS_NOT_ADMITTED" });
    }
    // The documented revert (flags off together, selection off) leaves a valid catalog that admits nothing.
    const reverted = await world(catalogWith((yahoo, doc) => { yahoo.runtime_enabled = false; yahoo.line_quote_eligible = false; doc.production_quote_provider_selected = false; }));
    expect(reverted.admission.admitPublicOption({ ...SCOPE, provider_id: YAHOO_ID }, IN_NOW).ok).toBe(false);
    // The review window is judged against the real request clock, not a payload time.
    const { admission } = await world(catalogWith());
    expect(admission.admitPublicOption({ ...SCOPE, provider_id: YAHOO_ID }, Date.parse("2027-10-13T00:00:00Z")).ok).toBe(true);
    expect(admission.admitPublicOption({ ...SCOPE, provider_id: YAHOO_ID }, Date.parse("2027-10-14T00:00:00Z")).ok).toBe(false);
  });

  it("any other provider claiming the operator status invalidates the catalog, whatever it copies", async () => {
    const others = repository.providers.filter((item: Doc) => item.id !== YAHOO_ID && item.id !== "nasdaq_nordic_option_chain").map((item: Doc) => item.id as string);
    expect(others.length).toBeGreaterThanOrEqual(12);
    for (const id of others) {
      const doc = catalogWith((_yahoo, root) => {
        const forged = root.providers.find((item: Doc) => item.id === id)!;
        Object.assign(forged, clone(YAHOO_ENTRY), { id: forged.id, name: forged.name, authority: forged.authority, jurisdictions: forged.jurisdictions,
          data_roles: forged.data_roles, official_url: forged.official_url, rights_evidence_url: forged.rights_evidence_url, review_notes: forged.review_notes });
      });
      const { admission } = await world(doc);
      expect(admission.admitPublicOption({ ...SCOPE, provider_id: YAHOO_ID }, IN_NOW).ok, id).toBe(false);
      expect(admission.admitPublicOption({ ...SCOPE, provider_id: id }, IN_NOW).ok, id).toBe(false);
    }
    const reviewedWithDecision = await world(catalogWith((_yahoo, doc) => {
      doc.providers.find((item: Doc) => item.id === "taifex_public_options")!.operator_decision = clone(DECISION);
    }));
    expect(reviewedWithDecision.admission.admitPublicOption({ ...SCOPE, provider_id: YAHOO_ID }, IN_NOW).ok).toBe(false);
  });

  it("the repository catalog entry equals the pinned copy when it is present (and the file as it stands admits nothing wrongly)", async () => {
    const entry = repository.providers.find((item: Doc) => item.id === YAHOO_ID);
    if (!entry) return;  // the repository catalog does not carry the operator-accepted entry yet
    const strip = (doc: Doc) => { const { name: _name, review_notes: _notes, ...rest } = doc; return rest; };
    expect(strip(entry)).toEqual(strip(YAHOO_ENTRY));
    expect(repository.production_quote_provider_selected).toBe(true);
  });
});

describe("W2 validation of the previous-session basis", () => {
  it("accepts the producer's carried cycle only with the opt-in and a clock, and refuses it otherwise", async () => {
    const { covered } = await world(catalogWith());
    const cycle = carried();
    expect(cycle.quote_basis).toBe("previous_session_last");
    expect(covered.validateCoveredCallCycle(clone(cycle), OFF_NOW, fixture.off_session.generated_at, "weekly", { allowPreviousSession: true })).not.toBeNull();
    expect(covered.validateCoveredCallCycle(clone(cycle), OFF_NOW, fixture.off_session.generated_at, "weekly")).toBeNull();                          // no opt-in
    expect(covered.validateCoveredCallCycle(clone(cycle), OFF_NOW, fixture.off_session.generated_at, "weekly", { allowPreviousSession: false })).toBeNull();
    expect(covered.validateCoveredCallCycle(clone(cycle), undefined, undefined, undefined, { allowPreviousSession: true })).toBeNull();                // no clock
    expect(covered.validateCoveredCallCycle(clone(cycle), OFF_NOW, fixture.off_session.generated_at, "monthly", { allowPreviousSession: true })).toBeNull();  // wrong period bucket
    expect(covered.validateCoveredCallCycle(live(), IN_NOW, fixture.in_session.generated_at, "weekly")).not.toBeNull();                              // live rows unchanged
    expect(covered.validateCoveredCallCycle({ ...live(), quote_basis: "realtime" }, IN_NOW, undefined, "weekly", { allowPreviousSession: true })).toBeNull();
  });

  it("applies its own four-day age bound while a live row keeps the six-hour bound", async () => {
    const { covered } = await world(catalogWith());
    const opts = { allowPreviousSession: true };
    const edge = Date.parse("2026-10-17T15:00:00Z");  // exactly four days after the capture
    const accepted = covered.validateCoveredCallCycle(captureAt(carried(), "2026-10-13T15:00:00Z", "2026-10-23"), edge, undefined, "weekly", opts);
    expect(accepted).not.toBeNull();
    expect(covered.validateCoveredCallCycle(captureAt(carried(), "2026-10-13T15:00:00Z", "2026-10-23"), edge + 1000, undefined, "weekly", opts)).toBeNull();
    // a live row at the same age (6.6 hours) is refused as before
    expect(covered.validateCoveredCallCycle(live(), OFF_NOW, fixture.in_session.generated_at, "weekly")).toBeNull();
    // a capture in the future beyond the clock tolerance is refused
    expect(covered.validateCoveredCallCycle(captureAt(carried(), "2026-10-13T15:00:00Z", "2026-10-16"), Date.parse("2026-10-13T14:50:00Z"), undefined, "weekly", opts)).toBeNull();
  });

  it("refuses a capture that was not taken in a regular US session", async () => {
    const { covered } = await world(catalogWith());
    const opts = { allowPreviousSession: true };
    for (const timestamp of ["2026-10-13T13:29:00Z", "2026-10-13T20:00:00Z", "2026-10-10T15:00:00Z", "2026-10-11T15:00:00Z"]) {
      expect(covered.validateCoveredCallCycle(captureAt(carried(), timestamp, "2026-10-16"), OFF_NOW, undefined, "weekly", opts), timestamp).toBeNull();
    }
    for (const timestamp of ["2026-10-13T13:30:00Z", "2026-10-13T19:59:00Z", "2026-10-12T15:00:00Z"]) {
      expect(covered.validateCoveredCallCycle(captureAt(carried(), timestamp, "2026-10-16"), OFF_NOW, undefined, "weekly", opts), timestamp).not.toBeNull();
    }
  });

  it("refuses an expired contract, an expiry day after the close and every non-US or tampered shape", async () => {
    const { covered } = await world(catalogWith());
    const opts = { allowPreviousSession: true };
    const monday = "2026-10-12T15:00:00Z";
    expect(covered.validateCoveredCallCycle(captureAt(carried(), monday, "2026-10-12"), OFF_NOW, undefined, "weekly", opts)).toBeNull();           // expired yesterday
    expect(covered.validateCoveredCallCycle(captureAt(carried(), "2026-10-13T15:00:00Z", "2026-10-13"), OFF_NOW, undefined, "weekly", opts)).toBeNull();  // expiry day, closed
    expect(covered.validateCoveredCallCycle(captureAt(carried(), "2026-10-13T15:00:00Z", "2026-10-13"), Date.parse("2026-10-13T19:00:00Z"), undefined, "weekly", opts)).not.toBeNull();  // open
    expect(covered.validateCoveredCallCycle({ ...carried(), currency: "SEK" }, OFF_NOW, undefined, "weekly", opts)).toBeNull();
    const noAsof = carried(); delete noAsof.asof_date;
    expect(covered.validateCoveredCallCycle(noAsof, OFF_NOW, undefined, "weekly", opts)).toBeNull();
    const tampered = carried(); tampered.suggestions[0].limit_price = tampered.suggestions[0].ask + 1;
    expect(covered.validateCoveredCallCycle(tampered, OFF_NOW, undefined, "weekly", opts)).toBeNull();
    const yieldChanged = carried(); yieldChanged.suggestions[0].annualized_yield *= 2;
    expect(covered.validateCoveredCallCycle(yieldChanged, OFF_NOW, undefined, "weekly", opts)).toBeNull();
    expect(covered.validateCoveredCallCycle({ ...carried(), asof_date: "2026-10-12" }, OFF_NOW, undefined, "weekly", opts)).toBeNull();            // dte/asof inconsistent
  });

  it("mirrors the Python session clock and the label format", async () => {
    const { covered } = await world(catalogWith());
    const table: Array<[string, boolean]> = [
      ["2026-10-13T13:29:00Z", false], ["2026-10-13T13:30:00Z", true], ["2026-10-13T19:59:00Z", true], ["2026-10-13T20:00:00Z", false],
      ["2026-12-15T14:29:00Z", false], ["2026-12-15T14:30:00Z", true], ["2026-12-15T20:59:00Z", true], ["2026-12-15T21:00:00Z", false],
      ["2026-10-17T15:00:00Z", false], ["2026-10-18T15:00:00Z", false], ["2026-10-12T15:00:00Z", true], ["2026-10-16T15:00:00Z", true],
    ];
    for (const [instant, open] of table) expect(usRegularSessionOpen(Date.parse(instant)), instant).toBe(open);
    expect(covered.previousSessionLabelZh("2026-10-13T15:00:00Z")).toBe(LABEL);
    expect(covered.previousSessionLabelZh("2026-12-15T15:55:00Z")).toBe("前一交易時段最後報價（2026-12-15 10:55 美東）；開盤後價格會變動");
    expect(covered.previousSessionLabelZh("2026-10-13T13:30:00Z")).toBe("前一交易時段最後報價（2026-10-13 09:30 美東）；開盤後價格會變動");
  });
});

describe("W1 + W2 through the real LINE entry", () => {
  for (const style of ["text", "flex"] as const) {
    it(`${style}: a live cycle shows the quote, the unofficial-and-delayed source and the operator-decision line`, async () => {
      const w = await world(catalogWith());
      vi.setSystemTime(IN_NOW);
      const env = await sealedEnv(IN_DOC, fixture.in_session.generated_at, IN_NOW, style);
      for (const command of ["T00 每週期權", "T00 每月期權"]) {
        const reply = await lineReply(w, env, command, IN_NOW);
        expect(reply, command).toContain("T00");
        expect(reply).toContain("115.00");
        expect(reply).toContain("Yahoo Finance 期權鏈（非官方，延遲）");
        expect(reply).toContain(w.covered.OPERATOR_ACCEPTED_NOTICE_ZH);
        expect(reply).not.toContain("前一交易時段最後報價");
        expect(reply).not.toContain("OPTION_RIGHTS_NOT_ADMITTED");
      }
    });

    it(`${style}: a carried cycle shows the exact previous-session label with the capture time in New York, and still the operator line`, async () => {
      const w = await world(catalogWith());
      const env = await sealedEnv(OFF_DOC, fixture.off_session.generated_at, OFF_NOW, style);
      for (const command of ["T00 每週期權", "T01 每月期權"]) {
        const reply = await lineReply(w, env, command, OFF_NOW);
        expect(reply, command).toContain(LABEL);
        expect(reply).toContain("115.00");                        // the capture's own strike and quotes, not recomputed
        expect(reply).toContain("2026-10-13T15:00:00Z");           // the capture instant is shown, never relabelled as fresh
        expect(reply).toContain("Yahoo Finance 期權鏈（非官方，延遲）");
        expect(reply).toContain(w.covered.OPERATOR_ACCEPTED_NOTICE_ZH);
        expect(reply).not.toContain(UNVERIFIED);
      }
      // GOOD0 is a healthy live chain without a suggestion: the honest producer reason, not a carried quote
      const good = await lineReply(w, env, "GOOD0 每週期權", OFF_NOW);
      expect(good).toContain("沒有年化權利金達 6%");
      expect(good).not.toContain("前一交易時段最後報價");
    });
  }

  it("a carried cycle in flex also labels the header and the alt text", async () => {
    const w = await world(catalogWith());
    const env = await sealedEnv(OFF_DOC, fixture.off_session.generated_at, OFF_NOW, "flex");
    const reply = JSON.parse(await lineReply(w, env, "T00 每週期權", OFF_NOW));
    expect(reply[0].type).toBe("flex");
    expect(reply[0].altText).toContain("前一時段報價");
    expect(JSON.stringify(reply[0].contents)).toContain("前一時段報價");
    expect(JSON.stringify(reply[0].contents)).toContain(LABEL);
  });

  it("the older sealed bytes (no identity, delayed basis) and a catalog without the entry keep the rights denial and show no quote", async () => {
    const without = await world(catalogWith(undefined, false));
    const env = await sealedEnv(IN_DOC, fixture.in_session.generated_at, IN_NOW);
    vi.setSystemTime(IN_NOW);
    const denied = await lineReply(without, env, "T00 每週期權", IN_NOW);
    expect(denied).toContain("OPTION_RIGHTS_NOT_ADMITTED");
    expect(denied).not.toContain("115.00");
    expect(denied).not.toContain(without.covered.OPERATOR_ACCEPTED_NOTICE_ZH);
    // a cycle that claims no identity (an older producer, the Nasdaq fallback) is denied even under the full catalog
    const bare = live(); for (const key of ["provider_id", "jurisdiction", "venue", "instrument_kind", "publication_scope"]) delete bare[key];
    const w = await world(catalogWith());
    const bareEnv = await sealedEnv({ T00: { weekly: bare } }, fixture.in_session.generated_at, IN_NOW);
    const bareReply = await lineReply(w, bareEnv, "T00 每週期權", IN_NOW);
    expect(bareReply).toContain("OPTION_RIGHTS_NOT_ADMITTED");
    expect(bareReply).not.toContain("115.00");
  });

  it("an unknown or unadmitted carried basis never reaches a quote: refused by validation, by admission and by an older catalog", async () => {
    const w = await world(catalogWith());
    const cases: Record<string, Doc> = {
      "older than four days": captureAt(carried(), "2026-10-09T15:00:00Z", "2026-10-16"),
      "not in session": captureAt(carried(), "2026-10-13T13:00:00Z", "2026-10-16"),
      "expired expiry": captureAt(carried(), "2026-10-12T15:00:00Z", "2026-10-12"),
      "expiry day after the close": captureAt(carried(), "2026-10-13T15:00:00Z", "2026-10-13"),
      "tampered quote": (() => { const c = carried(); c.suggestions[0].limit_price = 99; return c; })(),
      "SEK carried": { ...carried(), currency: "SEK" },
    };
    for (const [name, cycle] of Object.entries(cases)) {
      const env = await sealedEnv({ T00: { weekly: cycle } }, fixture.off_session.generated_at, OFF_NOW);
      const reply = await lineReply(w, env, "T00 每週期權", OFF_NOW);
      expect(reply, name).toContain(UNVERIFIED);
      expect(reply, name).not.toContain("前一交易時段最後報價");
      expect(reply, name).not.toContain("115.00");
    }
    // The catalog stops admitting the carried basis (its scope removed): rights denial, no quote.
    const delayedOnly = await world(catalogWith(yahoo => { yahoo.admitted_scopes.pop(); }));
    const reply = await lineReply(delayedOnly, await sealedEnv(OFF_DOC, fixture.off_session.generated_at, OFF_NOW), "T00 每週期權", OFF_NOW);
    expect(reply).toContain("OPTION_RIGHTS_NOT_ADMITTED");
    expect(reply).not.toContain("115.00");
    // The renderer re-checks admission independently (no loader in front of it).
    const { covered, admission } = delayedOnly;
    const cycle = covered.validateCoveredCallCycle(carried(), OFF_NOW, fixture.off_session.generated_at, "weekly", { allowPreviousSession: true });
    expect(cycle).not.toBeNull();
    expect(() => covered.buildCoveredCallMessages(cycle!, "每週期權", "text")).toThrow(admission.OptionRightsNotAdmittedError);
  });

  it("the loader reads the carried basis only through its own opt-in; the coverage page never counts a carried row", async () => {
    const w = await world(catalogWith());
    const view = await w.snapshot.pinPublicSnapshot(await sealedEnv(OFF_DOC, fixture.off_session.generated_at, OFF_NOW) as never);
    const detailed = await w.observations.loadDetailedOptionObservation(view, "T00", "weekly", OFF_NOW);
    expect(detailed.status).toBe("FOUND");
    expect(detailed.quote?.quote_basis).toBe("previous_session_last");
    const good = await w.observations.loadDetailedOptionObservation(view, "GOOD0", "weekly", OFF_NOW);
    expect(good.status).toBe("PERIOD_UNAVAILABLE");
    // validateCoveredCallCycle without the opt-in (the coverage recomputation and every format-only caller) refuses the same row
    expect(w.covered.validateCoveredCallCycle(clone(OFF_DOC.T00.weekly), OFF_NOW, fixture.off_session.generated_at, "weekly")).toBeNull();
    expect(w.coverage.OPTIONS_COVERAGE_KEY).toBe("v213:options-coverage:v1");
  });
});
