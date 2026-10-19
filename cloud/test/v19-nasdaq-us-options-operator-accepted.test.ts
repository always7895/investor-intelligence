// V19 A1 on the Worker: the operator-accepted (unlicensed) Nasdaq US option chain (the Yahoo fallback), a third pinned provider beside Yahoo and Nasdaq
// Nordic, through the REAL callers: admitPublicOption, validateCoveredCallCycle, loadDetailedOptionObservation, the renderer and processAuthorizedLineEvent
// on a sealed MemoryKv snapshot. The sealed options object is a slice of what the real Python producer and sealer emit
// (cloud/test/fixtures/v19-nasdaq-us-options.json, byte-pinned by tests/test_v19_nasdaq_us_options_operator_accepted.py). The catalog is the REPOSITORY
// catalog (vi.doMock, since the Worker imports it at build time) with mutations applied per row; clocks lie after the decision day 2026-10-19.
// Synthetic LINE credentials; every other network call throws.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";
import { SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";

const CATALOG_MODULE = "../../config/public-options-provider-candidates.json";
const repository = JSON.parse(readFileSync(resolve(__dirname, CATALOG_MODULE), "utf-8")) as Doc;
const fixture = JSON.parse(readFileSync(resolve(__dirname, "fixtures/v19-nasdaq-us-options.json"), "utf-8")) as Doc;
type Doc = Record<string, any>;
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

const NASDAQ_ID = "nasdaq_public_option_chain";
const NORDIC_ID = "nasdaq_nordic_option_chain";
const YAHOO_ID = "yahoo_finance_option_chain";
const NASDAQ_DECISION = { decision_id: "OPERATOR-DECISION-V18-BOUNDARY-ITEMS-A1-A4-C1-C3-20261019", decided_at: "2026-10-19", record: "docs/PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW.md" };
const US_SCOPE = { jurisdiction: "US", venue: "US_LISTED_OPTIONS", instrument_kind: "equity_option", quote_basis: "delayed", publication_scope: "public_line_quote" };
const NORDIC_SCOPE = { jurisdiction: "SE", venue: "NASDAQ_STOCKHOLM_OPTIONS", instrument_kind: "equity_option", quote_basis: "delayed", publication_scope: "public_line_quote" };
const NASDAQ_CLAIM = { ...US_SCOPE, provider_id: NASDAQ_ID };
const YAHOO_CLAIM = { ...US_SCOPE, provider_id: YAHOO_ID };
const NORDIC_CLAIM = { ...NORDIC_SCOPE, provider_id: NORDIC_ID };
const DENIED = { ok: false, reason: "OPTION_RIGHTS_NOT_ADMITTED" };
const ADMITTED = (id: string) => ({ ok: true, provider_id: id, operator_accepted: true });
const NOW = Date.parse("2026-10-19T14:05:00Z");         // 10:05 in New York, five minutes after the producer run
const DOC = fixture.all.options as Doc;
const GENERATED_AT = fixture.all.generated_at as string;
const RUN = "20261019T140000Z-abcdefabcde4";
const NQ = "SYNTHNQ00";

const entry = (doc: Doc, id: string): Doc => doc.providers.find((item: Doc) => item.id === id)!;
/** The repository catalog with optional per-row mutations (a deep copy). */
function catalogWith(mutate?: (nasdaq: Doc, yahoo: Doc, doc: Doc) => void): Doc {
  const doc = clone(repository);
  mutate?.(entry(doc, NASDAQ_ID), entry(doc, YAHOO_ID), doc);
  return doc;
}
const revert = (nasdaq: Doc) => { nasdaq.runtime_enabled = false; nasdaq.line_quote_eligible = false; };

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

describe("the repository catalog carries exactly the three pinned operator-accepted providers", () => {
  it("lists the Nasdaq US entry as the pinned decision and the other two are unchanged", () => {
    const nasdaq = entry(repository, NASDAQ_ID);
    expect(nasdaq.rights_status).toBe("operator_accepted_unlicensed");
    expect(nasdaq.automated_access_allowed).toBeNull();
    expect(nasdaq.jurisdictions).toEqual(["US"]);
    expect(nasdaq.admitted_scopes).toEqual([US_SCOPE]);                       // delayed only: no carry-forward basis
    expect(nasdaq.operator_decision).toEqual(NASDAQ_DECISION);
    expect(nasdaq.review_valid_through).toBe("2027-10-19");
    expect(nasdaq.data_roles).toContain("delayed_option_quotes");
    expect(nasdaq.review_notes).toContain("NOT a rights review and NOT a licence");
    expect(nasdaq.review_notes).toContain("Revert: set runtime_enabled and line_quote_eligible to false together");
    expect(entry(repository, YAHOO_ID).operator_decision.decision_id).toBe("OPERATOR-DECISION-OPTIONS-DISPLAY-ALL-20261013");
    expect(entry(repository, NORDIC_ID).operator_decision.decision_id).toBe("OPERATOR-DECISION-OPTIONS-NORDIC-DISPLAY-20261017");
    const enabled = repository.providers.filter((item: Doc) => item.runtime_enabled === true).map((item: Doc) => item.id).sort();
    expect(enabled).toEqual([NASDAQ_ID, NORDIC_ID, YAHOO_ID].sort());
  });
});

describe("admission: the pinned Nasdaq US decision, through the catalog", () => {
  it("admits the claimed Nasdaq US identity (delayed) flagged as operator-accepted, and the other two exactly as before", async () => {
    const { admission } = await world(catalogWith());
    expect(admission.admitPublicOption(NASDAQ_CLAIM, NOW)).toEqual(ADMITTED(NASDAQ_ID));
    expect(admission.admitPublicOption(YAHOO_CLAIM, NOW)).toEqual(ADMITTED(YAHOO_ID));
    expect(admission.admitPublicOption({ ...YAHOO_CLAIM, quote_basis: "previous_session_last" }, NOW)).toEqual(ADMITTED(YAHOO_ID));
    expect(admission.admitPublicOption(NORDIC_CLAIM, NOW)).toEqual(ADMITTED(NORDIC_ID));
    const cycle = DOC[NQ].monthly;   // the producer's real output carries exactly this claimed identity
    expect({ provider_id: cycle.provider_id, jurisdiction: cycle.jurisdiction, venue: cycle.venue, instrument_kind: cycle.instrument_kind, publication_scope: cycle.publication_scope })
      .toEqual({ provider_id: NASDAQ_ID, jurisdiction: "US", venue: "US_LISTED_OPTIONS", instrument_kind: "equity_option", publication_scope: "public_line_quote" });
    expect(admission.admitPublicOption(cycle, NOW)).toEqual(ADMITTED(NASDAQ_ID));
  });

  it("denies every other claim and keeps the identities apart", async () => {
    const { admission } = await world(catalogWith());
    const mixes: Doc[] = [
      { quote_basis: "previous_session_last" }, { quote_basis: "realtime" }, { quote_basis: "asof_close" }, { jurisdiction: "SE" }, { jurisdiction: "NO" },
      { venue: "NASDAQ_STOCKHOLM_OPTIONS" }, { venue: "US_LISTED_OPTIONS " }, { venue: "OTHERVENUE" }, { instrument_kind: "eod_index" },
      { publication_scope: "local_research" }, { provider_id: `${NASDAQ_ID} ` }, { provider_id: "nyse_options_reference" }, { provider_id: "nasdaq_us_option_chain" },
    ];
    for (const change of mixes) expect(admission.admitPublicOption({ ...NASDAQ_CLAIM, ...change }, NOW), JSON.stringify(change)).toEqual(DENIED);
    for (const key of Object.keys(NASDAQ_CLAIM)) {
      expect(admission.admitPublicOption({ ...NASDAQ_CLAIM, [key]: undefined }, NOW)).toEqual(DENIED);
      expect(admission.admitPublicOption({ ...NASDAQ_CLAIM, [key]: 1 }, NOW)).toEqual(DENIED);
    }
    // a label, source text or flag never admits
    expect(admission.admitPublicOption({ rights_status: "operator_accepted_unlicensed", admission_status: "ADMITTED", source: "Nasdaq US option chain" }, NOW)).toEqual(DENIED);
  });

  it("refuses a forged or altered Nasdaq US entry: the whole catalog becomes unusable, the other two included", async () => {
    const mutations: Record<string, (nasdaq: Doc) => void> = {
      "decision id": nasdaq => { nasdaq.operator_decision.decision_id = "OPERATOR-DECISION-SOMETHING-ELSE"; },
      "the Nordic decision id": nasdaq => { nasdaq.operator_decision.decision_id = "OPERATOR-DECISION-OPTIONS-NORDIC-DISPLAY-20261017"; },
      "decision date": nasdaq => { nasdaq.operator_decision.decided_at = "2026-10-17"; },
      "decision record": nasdaq => { nasdaq.operator_decision.record = "docs/README.md"; },
      "extra decision key": nasdaq => { nasdaq.operator_decision.approved_by = "someone"; },
      "decision removed": nasdaq => { delete nasdaq.operator_decision; },
      "review date": nasdaq => { nasdaq.rights_reviewed_at = "2026-10-18"; },
      "claims automation": nasdaq => { nasdaq.automated_access_allowed = true; },
      "no adapter": nasdaq => { nasdaq.adapter_status = "not_implemented"; },
      "foreign venue scope": nasdaq => { nasdaq.admitted_scopes[0].venue = "OTHERVENUE"; },
      "foreign basis scope": nasdaq => { nasdaq.admitted_scopes[0].quote_basis = "realtime"; },
      "carried basis scope": nasdaq => { nasdaq.admitted_scopes.push({ ...US_SCOPE, quote_basis: "previous_session_last" }); },
      "scope outside the pin": nasdaq => { nasdaq.admitted_scopes.push({ ...US_SCOPE, venue: "US_LISTED_OPTIONS_EXTRA" }); },
      "no scopes": nasdaq => { nasdaq.admitted_scopes = []; },
      "reviewed status without review": nasdaq => { nasdaq.rights_status = "reviewed_public_access"; },
      "window closed": nasdaq => { nasdaq.review_valid_through = "2026-10-18"; },
      "partial activation": nasdaq => { nasdaq.line_quote_eligible = false; },
    };
    for (const [name, mutate] of Object.entries(mutations)) {
      const { admission } = await world(catalogWith(nasdaq => mutate(nasdaq)));
      expect(admission.admitPublicOption(NASDAQ_CLAIM, NOW), name).toEqual(DENIED);
      expect(admission.admitPublicOption(YAHOO_CLAIM, NOW), name).toEqual(DENIED);
      expect(admission.admitPublicOption(NORDIC_CLAIM, NOW), name).toEqual(DENIED);
    }
    const swapped = await world(catalogWith((nasdaq, yahoo) => { yahoo.operator_decision = clone(nasdaq.operator_decision); yahoo.rights_reviewed_at = "2026-10-19"; }));
    expect(swapped.admission.admitPublicOption(YAHOO_CLAIM, NOW)).toEqual(DENIED);
  });

  it("a second provider claiming the Nasdaq US id or the operator status invalidates the catalog, whatever it copies", async () => {
    const duplicate = await world(catalogWith((nasdaq, _yahoo, doc) => { doc.providers.push(clone(nasdaq)); }));
    expect(duplicate.admission.admitPublicOption(NASDAQ_CLAIM, NOW)).toEqual(DENIED);
    const others = repository.providers.map((item: Doc) => item.id as string).filter((id: string) => ![NASDAQ_ID, NORDIC_ID, YAHOO_ID].includes(id));
    expect(others.length).toBeGreaterThanOrEqual(10);
    for (const id of others) {
      const doc = catalogWith((nasdaq, _yahoo, root) => {
        const forged = entry(root, id);
        Object.assign(forged, clone(nasdaq), { id: forged.id, name: forged.name, authority: forged.authority, data_roles: forged.data_roles,
          official_url: forged.official_url, rights_evidence_url: forged.rights_evidence_url, review_notes: forged.review_notes });
      });
      const { admission } = await world(doc);
      expect(admission.admitPublicOption(NASDAQ_CLAIM, NOW).ok, id).toBe(false);
      expect(admission.admitPublicOption({ ...NASDAQ_CLAIM, provider_id: id }, NOW).ok, id).toBe(false);
    }
  });

  it("catalog row present but the TypeScript pin missing: every provider is denied (the row and the Worker ship in one build)", async () => {
    // the same operator-accepted row under an id the Worker does not pin is an unpinned operator-accepted provider
    const unpinned = await world(catalogWith(nasdaq => { nasdaq.id = "nasdaq_us_option_chain_unpinned"; }));
    expect(unpinned.admission.admitPublicOption(NASDAQ_CLAIM, NOW)).toEqual(DENIED);
    expect(unpinned.admission.admitPublicOption({ ...NASDAQ_CLAIM, provider_id: "nasdaq_us_option_chain_unpinned" }, NOW)).toEqual(DENIED);
    expect(unpinned.admission.admitPublicOption(YAHOO_CLAIM, NOW)).toEqual(DENIED);
    expect(unpinned.admission.admitPublicOption(NORDIC_CLAIM, NOW)).toEqual(DENIED);
  });

  it("the documented revert: Nasdaq US flags off together leave the others admitted; all off with the selection off admit nothing", async () => {
    const off = await world(catalogWith(revert));
    expect(off.admission.admitPublicOption(NASDAQ_CLAIM, NOW)).toEqual(DENIED);
    expect(off.admission.admitPublicOption(YAHOO_CLAIM, NOW)).toEqual(ADMITTED(YAHOO_ID));
    expect(off.admission.admitPublicOption(NORDIC_CLAIM, NOW)).toEqual(ADMITTED(NORDIC_ID));
    const allOff = await world(catalogWith((nasdaq, yahoo, doc) => {
      for (const provider of [nasdaq, yahoo, entry(doc, NORDIC_ID)]) { provider.runtime_enabled = false; provider.line_quote_eligible = false; }
      doc.production_quote_provider_selected = false;
    }));
    for (const claim of [NASDAQ_CLAIM, YAHOO_CLAIM, NORDIC_CLAIM]) expect(allOff.admission.admitPublicOption(claim, NOW)).toEqual(DENIED);
  });

  it("the review window is judged against the request clock", async () => {
    const { admission } = await world(catalogWith());
    expect(admission.admitPublicOption(NASDAQ_CLAIM, Date.parse("2026-10-18T23:59:59Z"))).toEqual(DENIED);                   // before the decision day
    expect(admission.admitPublicOption(NASDAQ_CLAIM, Date.parse("2026-10-19T00:00:00Z")).ok).toBe(true);                     // the decision day
    expect(admission.admitPublicOption(NASDAQ_CLAIM, Date.parse("2027-10-13T23:59:59Z")).ok).toBe(true);                     // last Yahoo day
    expect(admission.admitPublicOption(NASDAQ_CLAIM, Date.parse("2027-10-14T00:00:00Z"))).toEqual(DENIED);                   // Yahoo window closed: whole catalog
  });
});

describe("the Worker readers accept an admitted Nasdaq US cycle and never carry it forward", () => {
  it("validates the producer's fallback cycles", async () => {
    const { covered, admission } = await world(catalogWith());
    for (const period of ["weekly", "monthly"] as const) {
      const cycle = covered.validateCoveredCallCycle(clone(DOC[NQ][period]), NOW, GENERATED_AT, period);
      expect(cycle, period).not.toBeNull();
      expect(cycle!.currency).toBe("USD");
      expect(cycle!.quote_basis).toBe("delayed");
    }
    const carried = { ...clone(DOC[NQ].monthly), quote_basis: "previous_session_last" };
    expect(admission.admitPublicOption(carried, NOW)).toEqual(DENIED);   // the carried basis belongs to Yahoo alone: the rights gate refuses it
  });

  it("the loader returns the admitted quote and denies it when the catalog row is reverted", async () => {
    const w = await world(catalogWith());
    const view = await w.snapshot.pinPublicSnapshot(await sealedEnv(DOC) as never);
    const found = await w.observations.loadDetailedOptionObservation(view, NQ, "monthly", NOW);
    expect(found.status).toBe("FOUND");
    const denied = await world(catalogWith(revert));
    const deniedView = await denied.snapshot.pinPublicSnapshot(await sealedEnv(DOC) as never);
    expect((await denied.observations.loadDetailedOptionObservation(deniedView, NQ, "monthly", NOW)).status).toBe("RIGHTS_NOT_ADMITTED");
    expect((await denied.observations.loadDetailedOptionObservation(deniedView, "SYNTHUS00", "monthly", NOW)).status).toBe("FOUND");  // Yahoo unchanged
  });
});

describe("through the real LINE entry", () => {
  for (const style of ["text", "flex"] as const) {
    it(`${style}: an admitted fallback cycle shows the quote, the Nasdaq US source with the unofficial-licence wording, and the operator-decision line`, async () => {
      const w = await world(catalogWith());
      const env = await sealedEnv(DOC, style);
      for (const command of [`${NQ} 每月期權`, `${NQ} 每週期權`]) {
        const reply = await lineReply(w, env, command);
        expect(reply, command).toContain(NQ);
        expect(reply).toContain("Nasdaq 美股期權鏈（公開報價頁 API，非官方授權，延遲；Yahoo 備援）");
        expect(reply).toContain(w.covered.OPERATOR_ACCEPTED_NOTICE_ZH);
        expect(reply).toContain("依營運者決定顯示；本資料未取得再散布授權。");
        expect(reply).not.toContain("OPTION_RIGHTS_NOT_ADMITTED");
        expect(reply).not.toContain("前一交易時段最後報價");
      }
    });
  }

  it("with the row reverted the same sealed bytes show the rights denial and no quote; the Yahoo answer is unchanged", async () => {
    const without = await world(catalogWith(revert));
    const env = await sealedEnv(DOC);
    const denied = await lineReply(without, env, `${NQ} 每月期權`);
    expect(denied).toContain("OPTION_RIGHTS_NOT_ADMITTED");
    expect(denied).not.toContain(without.covered.OPERATOR_ACCEPTED_NOTICE_ZH);
    const yahoo = await lineReply(without, env, "SYNTHUS00 每月期權");
    expect(yahoo).toContain("Yahoo Finance 期權鏈（非官方，延遲）");
    expect(yahoo).toContain(without.covered.OPERATOR_ACCEPTED_NOTICE_ZH);
  });

  it("the renderer re-checks admission independently", async () => {
    const w = await world(catalogWith());
    const cycle = w.covered.validateCoveredCallCycle(clone(DOC[NQ].monthly), NOW, GENERATED_AT, "monthly")!;
    for (const style of ["text", "flex"] as const) expect(() => w.covered.buildCoveredCallMessages(cycle, "每月期權", style)).not.toThrow();
    const denied = await world(catalogWith(revert));
    const again = denied.covered.validateCoveredCallCycle(clone(DOC[NQ].monthly), NOW, GENERATED_AT, "monthly")!;
    expect(() => denied.covered.buildCoveredCallMessages(again, "每月期權", "text")).toThrow(denied.admission.OptionRightsNotAdmittedError);
  });
});
