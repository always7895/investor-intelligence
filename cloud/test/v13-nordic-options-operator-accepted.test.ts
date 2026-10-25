// V13 item 3b on the Worker: the operator-accepted (unlicensed) Nasdaq Nordic option provider, a second pinned provider beside Yahoo, through the REAL
// callers: admitPublicOption, validateCoveredCallCycle, loadDetailedOptionObservation, the renderer and processAuthorizedLineEvent on a sealed MemoryKv
// snapshot. The sealed options object is a slice of what the real Python producer and sealer emit (cloud/test/fixtures/v13-nordic-options.json, byte-pinned
// by tests/test_v13_nordic_options_operator_accepted.py). The catalog is the REPOSITORY catalog (vi.doMock, since the Worker imports it at build time) with
// mutations applied per row; clocks lie after the decision day 2026-10-17. Synthetic LINE credentials; every other network call throws.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";
import { SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";

const CATALOG_MODULE = "../../config/public-options-provider-candidates.json";
const repository = JSON.parse(readFileSync(resolve(__dirname, CATALOG_MODULE), "utf-8")) as Doc;
const fixture = JSON.parse(readFileSync(resolve(__dirname, "fixtures/v13-nordic-options.json"), "utf-8")) as Doc;
type Doc = Record<string, any>;
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

const NORDIC_ID = "nasdaq_nordic_option_chain";
const YAHOO_ID = "yahoo_finance_option_chain";
const NORDIC_SCOPE = { jurisdiction: "SE", venue: "NASDAQ_STOCKHOLM_OPTIONS", instrument_kind: "equity_option", quote_basis: "delayed", publication_scope: "public_line_quote" };
const YAHOO_SCOPE = { jurisdiction: "US", venue: "US_LISTED_OPTIONS", instrument_kind: "equity_option", quote_basis: "delayed", publication_scope: "public_line_quote" };
const NORDIC_CLAIM = { ...NORDIC_SCOPE, provider_id: NORDIC_ID };
const YAHOO_CLAIM = { ...YAHOO_SCOPE, provider_id: YAHOO_ID };
const DENIED = { ok: false, reason: "OPTION_RIGHTS_NOT_ADMITTED" };
const NOW = Date.parse("2026-10-19T08:05:00Z");         // 10:05 in Stockholm, five minutes after the producer run
const DOC = fixture.both.options as Doc;
const GENERATED_AT = fixture.both.generated_at as string;
const RUN = "20261019T080000Z-abcdefabcde3";

const entry = (doc: Doc, id: string): Doc => doc.providers.find((item: Doc) => item.id === id)!;
/** The repository catalog with optional per-row mutations (a deep copy; the root selection follows `selected` when given). */
function catalogWith(mutate?: (nordic: Doc, yahoo: Doc, doc: Doc) => void): Doc {
  const doc = clone(repository);
  mutate?.(entry(doc, NORDIC_ID), entry(doc, YAHOO_ID), doc);
  return doc;
}

async function world(catalogDoc: Doc) {
  vi.resetModules();
  vi.doMock(CATALOG_MODULE, () => ({ default: catalogDoc }));
  return {
    admission: await import("../src/v213/public-options-admission"),
    covered: await import("../src/v213/covered-call"),
    observations: await import("../src/v213/market-observations"),
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

async function sealedEnv(options: Doc, style: "text" | "flex" = "text") {
  const kv = new MemoryKv();
  kv.values.set("v213:top20-report:latest", JSON.stringify({ synthetic: "report" }));
  kv.values.set("last_successful_pipeline_timestamp", new Date(NOW - 60_000).toISOString().replace(/\.\d{3}Z$/, "Z"));
  await sealUnboundReport(kv, RUN);
  const body = JSON.stringify({ schema: "v213-options-v2", generated_at: GENERATED_AT, options });
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
async function lineReply(w: World, env: any, command: string): Promise<string> {
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
  { type: "message", replyToken: "SYNTHETIC_REPLY", timestamp: NOW, message: { id: "SYNTHETIC_MESSAGE", type: "text", text: command } }, "SYNTHETIC_TENANT");
  expect(network).toHaveBeenCalledTimes(1);
  return JSON.stringify(messages);
}

beforeEach(() => { vi.setSystemTime(NOW); });
afterEach(() => { vi.unstubAllGlobals(); vi.doUnmock(CATALOG_MODULE); });

describe("the repository catalog carries exactly the two pinned operator-accepted providers", () => {
  it("lists the Nordic entry as the pinned decision and Yahoo is unchanged", () => {
    const nordic = entry(repository, NORDIC_ID);
    expect(nordic.rights_status).toBe("operator_accepted_unlicensed");
    expect(nordic.automated_access_allowed).toBeNull();
    expect(nordic.jurisdictions).toEqual(["SE"]);
    expect(nordic.admitted_scopes).toEqual([NORDIC_SCOPE]);                   // delayed only: no carry-forward basis
    expect(nordic.operator_decision).toEqual({ decision_id: "OPERATOR-DECISION-OPTIONS-NORDIC-DISPLAY-20261017", decided_at: "2026-10-17", record: "docs/PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW.md" });
    expect(nordic.review_valid_through).toBe("2027-10-17");
    expect(nordic.rights_evidence_url).toBe("https://www.nasdaq.com/legal");
    expect(nordic.review_notes).toContain("NOT a rights review and NOT a licence");
    const yahoo = entry(repository, YAHOO_ID);
    expect(yahoo.operator_decision.decision_id).toBe("OPERATOR-DECISION-OPTIONS-DISPLAY-ALL-20261013");
    expect(yahoo.admitted_scopes).toEqual([YAHOO_SCOPE, { ...YAHOO_SCOPE, quote_basis: "previous_session_last" }]);
    const enabled = repository.providers.filter((item: Doc) => item.runtime_enabled === true).map((item: Doc) => item.id).sort();
    expect(enabled).toEqual([NORDIC_ID, YAHOO_ID].sort());
  });
});

describe("admission: the pinned Nordic decision, through the catalog", () => {
  it("admits the claimed Nordic identity (delayed) flagged as operator-accepted, and Yahoo exactly as before", async () => {
    const { admission } = await world(catalogWith());
    expect(admission.admitPublicOption(NORDIC_CLAIM, NOW)).toEqual({ ok: true, provider_id: NORDIC_ID, operator_accepted: true });
    expect(admission.admitPublicOption(YAHOO_CLAIM, NOW)).toEqual({ ok: true, provider_id: YAHOO_ID, operator_accepted: true });
    expect(admission.admitPublicOption({ ...YAHOO_CLAIM, quote_basis: "previous_session_last" }, NOW)).toEqual({ ok: true, provider_id: YAHOO_ID, operator_accepted: true });
    // the producer's real output carries exactly this claimed identity
    const cycle = DOC["SIVE.ST"].monthly;
    expect({ provider_id: cycle.provider_id, jurisdiction: cycle.jurisdiction, venue: cycle.venue, instrument_kind: cycle.instrument_kind, publication_scope: cycle.publication_scope })
      .toEqual({ provider_id: NORDIC_ID, jurisdiction: "SE", venue: "NASDAQ_STOCKHOLM_OPTIONS", instrument_kind: "equity_option", publication_scope: "public_line_quote" });
    expect(admission.admitPublicOption(cycle, NOW)).toEqual({ ok: true, provider_id: NORDIC_ID, operator_accepted: true });
  });

  it("denies every other claim and keeps the two identities apart", async () => {
    const { admission } = await world(catalogWith());
    const mixes: Doc[] = [
      { quote_basis: "previous_session_last" }, { quote_basis: "realtime" }, { quote_basis: "asof_close" }, { jurisdiction: "US" }, { jurisdiction: "NO" },
      { venue: "US_LISTED_OPTIONS" }, { venue: "STOCKHOLM" }, { venue: "NASDAQ_STOCKHOLM_OPTIONS " }, { instrument_kind: "eod_index" },
      { publication_scope: "local_research" }, { provider_id: `${NORDIC_ID} ` }, { provider_id: YAHOO_ID }, { provider_id: "nasdaq_public_option_chain" },
    ];
    for (const change of mixes) expect(admission.admitPublicOption({ ...NORDIC_CLAIM, ...change }, NOW), JSON.stringify(change)).toEqual(DENIED);
    for (const change of [{ provider_id: NORDIC_ID }, { jurisdiction: "SE" }, { venue: "NASDAQ_STOCKHOLM_OPTIONS" }]) {
      expect(admission.admitPublicOption({ ...YAHOO_CLAIM, ...change }, NOW), JSON.stringify(change)).toEqual(DENIED);
    }
    for (const key of Object.keys(NORDIC_CLAIM)) {
      expect(admission.admitPublicOption({ ...NORDIC_CLAIM, [key]: undefined }, NOW)).toEqual(DENIED);
      expect(admission.admitPublicOption({ ...NORDIC_CLAIM, [key]: 1 }, NOW)).toEqual(DENIED);
    }
    expect(admission.admitPublicOption({ rights_status: "operator_accepted_unlicensed", admission_status: "ADMITTED", source: "Nasdaq Nordic option chain" }, NOW)).toEqual(DENIED);
  });

  it("refuses a forged or altered Nordic entry: the whole catalog becomes unusable, Yahoo included", async () => {
    const mutations: Record<string, (nordic: Doc) => void> = {
      "decision id": nordic => { nordic.operator_decision.decision_id = "OPERATOR-DECISION-SOMETHING-ELSE"; },
      "the Yahoo decision id": nordic => { nordic.operator_decision.decision_id = "OPERATOR-DECISION-OPTIONS-DISPLAY-ALL-20261013"; },
      "decision date": nordic => { nordic.operator_decision.decided_at = "2026-10-13"; },
      "decision record": nordic => { nordic.operator_decision.record = "docs/README.md"; },
      "extra decision key": nordic => { nordic.operator_decision.approved_by = "someone"; },
      "decision removed": nordic => { delete nordic.operator_decision; },
      "review date": nordic => { nordic.rights_reviewed_at = "2026-10-16"; },
      "claims automation": nordic => { nordic.automated_access_allowed = true; },
      "no adapter": nordic => { nordic.adapter_status = "not_implemented"; },
      "foreign venue scope": nordic => { nordic.admitted_scopes[0].venue = "OTHERVENUE"; },
      "yahoo venue scope": nordic => { nordic.admitted_scopes[0].venue = "US_LISTED_OPTIONS"; },
      "carried basis scope": nordic => { nordic.admitted_scopes.push({ ...NORDIC_SCOPE, quote_basis: "previous_session_last" }); },
      "scope outside the pin": nordic => { nordic.admitted_scopes.push({ ...NORDIC_SCOPE, venue: "NASDAQ_STOCKHOLM_OPTIONS_EXTRA" }); },
      "scope of another jurisdiction": nordic => { nordic.jurisdictions.push("US"); nordic.admitted_scopes.push({ ...YAHOO_SCOPE }); },
      "no scopes": nordic => { nordic.admitted_scopes = []; },
      "reviewed status without review": nordic => { nordic.rights_status = "reviewed_public_access"; },
      "window closed": nordic => { nordic.review_valid_through = "2026-10-18"; },
      "partial activation": nordic => { nordic.line_quote_eligible = false; },
    };
    for (const [name, mutate] of Object.entries(mutations)) {
      const { admission } = await world(catalogWith(nordic => mutate(nordic)));
      expect(admission.admitPublicOption(NORDIC_CLAIM, NOW), name).toEqual(DENIED);
      expect(admission.admitPublicOption(YAHOO_CLAIM, NOW), name).toEqual(DENIED);
    }
    // the two decisions cannot be swapped between the providers
    const swapped = await world(catalogWith((nordic, yahoo) => { yahoo.operator_decision = clone(nordic.operator_decision); yahoo.rights_reviewed_at = "2026-10-17"; }));
    expect(swapped.admission.admitPublicOption(YAHOO_CLAIM, NOW)).toEqual(DENIED);
    const swappedScope = await world(catalogWith((nordic, yahoo) => { yahoo.admitted_scopes = clone(nordic.admitted_scopes); yahoo.jurisdictions = ["SE"]; }));
    expect(swappedScope.admission.admitPublicOption(YAHOO_CLAIM, NOW)).toEqual(DENIED);
    const nordicWithYahooScope = await world(catalogWith((nordic, yahoo) => { nordic.admitted_scopes = clone(yahoo.admitted_scopes); nordic.jurisdictions = ["US"]; }));
    expect(nordicWithYahooScope.admission.admitPublicOption(NORDIC_CLAIM, NOW)).toEqual(DENIED);
  });

  it("a second provider claiming the Nordic id or the operator status invalidates the catalog, whatever it copies", async () => {
    const duplicate = await world(catalogWith((nordic, _yahoo, doc) => { doc.providers.push(clone(nordic)); }));
    expect(duplicate.admission.admitPublicOption(NORDIC_CLAIM, NOW)).toEqual(DENIED);
    const others = repository.providers.map((item: Doc) => item.id as string).filter((id: string) => id !== NORDIC_ID && id !== YAHOO_ID);
    expect(others.length).toBeGreaterThanOrEqual(12);
    for (const id of others) {
      const doc = catalogWith((nordic, _yahoo, root) => {
        const forged = entry(root, id);
        Object.assign(forged, clone(nordic), { id: forged.id, name: forged.name, authority: forged.authority, data_roles: forged.data_roles,
          official_url: forged.official_url, rights_evidence_url: forged.rights_evidence_url, review_notes: forged.review_notes });
      });
      const { admission } = await world(doc);
      expect(admission.admitPublicOption(NORDIC_CLAIM, NOW).ok, id).toBe(false);
      expect(admission.admitPublicOption({ ...NORDIC_CLAIM, provider_id: id }, NOW).ok, id).toBe(false);
    }
    const reviewedWithDecision = await world(catalogWith((nordic, _yahoo, doc) => { entry(doc, "taifex_public_options").operator_decision = clone(nordic.operator_decision); }));
    expect(reviewedWithDecision.admission.admitPublicOption(NORDIC_CLAIM, NOW).ok).toBe(false);
  });

  it("the documented revert: Nordic flags off together leave Yahoo admitted; both off with the selection off admit nothing", async () => {
    const nordicOff = await world(catalogWith(nordic => { nordic.runtime_enabled = false; nordic.line_quote_eligible = false; }));
    expect(nordicOff.admission.admitPublicOption(NORDIC_CLAIM, NOW)).toEqual(DENIED);
    expect(nordicOff.admission.admitPublicOption(YAHOO_CLAIM, NOW)).toEqual({ ok: true, provider_id: YAHOO_ID, operator_accepted: true });
    const bothOff = await world(catalogWith((nordic, yahoo, doc) => {
      for (const provider of [nordic, yahoo]) { provider.runtime_enabled = false; provider.line_quote_eligible = false; }
      doc.production_quote_provider_selected = false;
    }));
    expect(bothOff.admission.admitPublicOption(NORDIC_CLAIM, NOW)).toEqual(DENIED);
    expect(bothOff.admission.admitPublicOption(YAHOO_CLAIM, NOW)).toEqual(DENIED);
    const rootStillSelected = await world(catalogWith((nordic, yahoo) => {
      for (const provider of [nordic, yahoo]) { provider.runtime_enabled = false; provider.line_quote_eligible = false; }
    }));
    expect(rootStillSelected.admission.admitPublicOption(NORDIC_CLAIM, NOW)).toEqual(DENIED);
  });

  it("the review window is judged against the request clock", async () => {
    const { admission } = await world(catalogWith());
    expect(admission.admitPublicOption(NORDIC_CLAIM, Date.parse("2026-10-16T23:59:59Z"))).toEqual(DENIED);                   // before the decision day
    expect(admission.admitPublicOption(NORDIC_CLAIM, Date.parse("2026-10-17T00:00:00Z")).ok).toBe(true);                     // the decision day
    expect(admission.admitPublicOption(NORDIC_CLAIM, Date.parse("2027-10-13T23:59:59Z")).ok).toBe(true);                     // last Yahoo day
    expect(admission.admitPublicOption(NORDIC_CLAIM, Date.parse("2027-10-14T00:00:00Z"))).toEqual(DENIED);                   // Yahoo window closed: whole catalog
    const renewed = await world(catalogWith((_nordic, yahoo) => { yahoo.review_valid_through = "2028-10-13"; }));
    expect(renewed.admission.admitPublicOption(NORDIC_CLAIM, Date.parse("2027-10-17T23:59:59Z")).ok).toBe(true);             // Nordic's own last day
    expect(renewed.admission.admitPublicOption(NORDIC_CLAIM, Date.parse("2027-10-18T00:00:00Z"))).toEqual(DENIED);           // Nordic window closed
  });
});

describe("the Worker readers accept an admitted SEK cycle and refuse a mismatched one", () => {
  it("validates the producer's Stockholm cycle and never carries it forward", async () => {
    const { covered } = await world(catalogWith());
    for (const period of ["weekly", "monthly"] as const) {
      const cycle = covered.validateCoveredCallCycle(clone(DOC["SIVE.ST"][period]), NOW, GENERATED_AT, period);
      expect(cycle, period).not.toBeNull();
      expect(cycle!.currency).toBe("SEK");
      expect(cycle!.quote_basis).toBe("delayed");
    }
    expect(covered.validateCoveredCallCycle(clone(DOC.SYNTHUS00.monthly), NOW, GENERATED_AT, "monthly")).not.toBeNull();   // Yahoo unchanged
    // a Nordic cycle is never carried forward: the carried basis is refused whatever the opt-in
    const carriedSek = { ...clone(DOC["SIVE.ST"].monthly), quote_basis: "previous_session_last" };
    expect(covered.validateCoveredCallCycle(carriedSek, NOW, GENERATED_AT, "monthly", { allowPreviousSession: true })).toBeNull();
  });

  it("the loader returns the admitted Stockholm quote and denies it when the catalog does not carry Nordic", async () => {
    const w = await world(catalogWith());
    const view = await w.snapshot.pinPublicSnapshot(await sealedEnv(DOC) as never);
    const found = await w.observations.loadDetailedOptionObservation(view, "SIVE.ST", "monthly", NOW);
    expect(found.status).toBe("FOUND");
    expect(found.quote?.currency).toBe("SEK");
    const denied = await world(catalogWith(nordic => { nordic.runtime_enabled = false; nordic.line_quote_eligible = false; }));
    const deniedView = await denied.snapshot.pinPublicSnapshot(await sealedEnv(DOC) as never);
    expect((await denied.observations.loadDetailedOptionObservation(deniedView, "SIVE.ST", "monthly", NOW)).status).toBe("RIGHTS_NOT_ADMITTED");
    expect((await denied.observations.loadDetailedOptionObservation(deniedView, "SYNTHUS00", "monthly", NOW)).status).toBe("FOUND");  // Yahoo unchanged
  });

  it("a Nordic cycle claiming the Yahoo identity, or a US cycle claiming the Nordic one, is never shown (admitted by identity, refused by market coherence)", async () => {
    const w = await world(catalogWith());
    const sekAsYahoo = { ...clone(DOC["SIVE.ST"].monthly), provider_id: YAHOO_ID, jurisdiction: "US", venue: "US_LISTED_OPTIONS" };
    const usdAsNordic = { ...clone(DOC.SYNTHUS00.monthly), provider_id: NORDIC_ID, jurisdiction: "SE", venue: "NASDAQ_STOCKHOLM_OPTIONS" };
    const view = await w.snapshot.pinPublicSnapshot(await sealedEnv({ "SIVE.ST": { monthly: sekAsYahoo }, SYNTHUS00: { monthly: usdAsNordic } }) as never);
    expect((await w.observations.loadDetailedOptionObservation(view, "SIVE.ST", "monthly", NOW)).status).toBe("QUOTE_INVALID_OR_STALE");
    expect((await w.observations.loadDetailedOptionObservation(view, "SYNTHUS00", "monthly", NOW)).status).toBe("QUOTE_INVALID_OR_STALE");
    const text = await lineReply(w, await sealedEnv({ "SIVE.ST": { monthly: sekAsYahoo } }), "SIVE.ST 每月期權");
    expect(text).not.toContain("13.70");
  });
});

describe("through the real LINE entry", () => {
  for (const style of ["text", "flex"] as const) {
    it(`${style}: an admitted SIVE.ST cycle shows the SEK quote, the Nasdaq Nordic source, the delay and the operator-decision line`, async () => {
      const w = await world(catalogWith());
      const env = await sealedEnv(DOC, style);
      for (const command of ["SIVE.ST 每月期權", "SIVE.ST 每週期權"]) {
        const reply = await lineReply(w, env, command);
        expect(reply, command).toContain("SIVE.ST");
        expect(reply).toContain(" SEK");
        expect(reply).toContain("Nasdaq Nordic 期權鏈（交易所公開網頁 API，非官方授權，延遲）");
        expect(reply).toContain(w.covered.OPERATOR_ACCEPTED_NOTICE_ZH);
        expect(reply).toContain("依營運者決定顯示；本資料未取得再散布授權。");
        expect(reply).not.toContain("OPTION_RIGHTS_NOT_ADMITTED");
        expect(reply).not.toContain("前一交易時段最後報價");
      }
    });
  }

  it("without the Nordic entry the same sealed bytes show the rights denial and no quote; the Yahoo answer is unchanged", async () => {
    const without = await world(catalogWith(nordic => { nordic.runtime_enabled = false; nordic.line_quote_eligible = false; }));
    const env = await sealedEnv(DOC);
    const denied = await lineReply(without, env, "SIVE.ST 每月期權");
    expect(denied).toContain("OPTION_RIGHTS_NOT_ADMITTED");
    expect(denied).not.toContain(" SEK");
    expect(denied).not.toContain(without.covered.OPERATOR_ACCEPTED_NOTICE_ZH);
    const yahoo = await lineReply(without, env, "SYNTHUS00 每月期權");
    expect(yahoo).toContain("Yahoo Finance 期權鏈（非官方，延遲）");
    expect(yahoo).toContain(without.covered.OPERATOR_ACCEPTED_NOTICE_ZH);
  });

  it("the renderer re-checks admission independently and the LINE payload limits hold", async () => {
    const w = await world(catalogWith());
    const cycle = w.covered.validateCoveredCallCycle(clone(DOC["SIVE.ST"].monthly), NOW, GENERATED_AT, "monthly")!;
    for (const style of ["text", "flex"] as const) expect(() => w.covered.buildCoveredCallMessages(cycle, "每月期權", style)).not.toThrow();
    const denied = await world(catalogWith(nordic => { nordic.runtime_enabled = false; nordic.line_quote_eligible = false; }));
    const again = denied.covered.validateCoveredCallCycle(clone(DOC["SIVE.ST"].monthly), NOW, GENERATED_AT, "monthly")!;
    expect(() => denied.covered.buildCoveredCallMessages(again, "每月期權", "text")).toThrow(denied.admission.OptionRightsNotAdmittedError);
  });
});
