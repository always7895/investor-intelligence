import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { computeReceiptDigest, parseOrderForecastV3 } from "../src/v213/order-forecast";

// BATCH10C F8-N1: the Worker's receipt recompute mirrors the Python raw-unsafe-id rule (scripts/revenue_guidance.py
// raw_unsafe_document_id): a later-document id that is not a string, or carries userinfo ("@"), a query ("?") or a
// fragment ("#"), is never a usable freshness proof, whatever its disposition, unless it is the persisted form
// <shown>#sha256:<64 lowercase hex> (no "@", "?" or "#" in <shown>), which is a safe id (F8-AMEND1). The golden NVDA
// record is AVAILABLE with an empty later-document list; one item is added and the receipt digest recomputed, so only
// its id (and, for a reviewed item, the reviewed list) decides.
const REPORT_DAY = "2026-09-28";
const GOLDEN_GENERATED = "2026-09-28T15:00:00Z";
const ITEM = "https://investor.nvidia.com/news/press-release-details/2026/showcase/default.aspx";
const persisted = (raw: string) => `${raw.split(/[?#]/, 1)[0] ?? ""}#sha256:${createHash("sha256").update(raw).digest("hex")}`;

describe("receipt later-document id safety (BATCH10C F8-N1)", () => {
  const golden = JSON.parse(readFileSync("../tests/fixtures/v213-orders-v3-golden-sealed.json", "utf-8"));
  const nvda = golden["NVDA"];
  const withLater = (id: unknown, disposition = "IRRELEVANT", reviewed: any[] = []) => {
    const mut = JSON.parse(JSON.stringify(nvda.order_forecast_v3));
    const r = mut.evidence.latest_release_check;
    r.later_documents.push({ channel: "ISSUER_IR", date: "2026-09-01", id, label: "NVIDIA to Showcase Products",
      disposition });
    r.digest = computeReceiptDigest(r);
    mut.evidence.reviewed_later_documents.push(...reviewed);
    return parseOrderForecastV3(mut, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvda.order_forecast);
  };

  it("keeps a receipt with a clean irrelevant later document usable (control)", () => {
    expect(nvda.order_forecast_v3.evidence.latest_release_check.later_documents).toEqual([]);
    const res = withLater(ITEM);
    expect(res.m6.status).toBe("AVAILABLE");
  });

  it("fails closed for a raw id with userinfo, a query or a fragment, and for near misses of the persisted form", () => {
    const ids = [
      `${ITEM}?token=x`,
      `${ITEM}#x`,
      "https://reader:x@investor.nvidia.com/news/press-release-details/2026/showcase/default.aspx",
      `${ITEM}?x#sha256:${"a".repeat(64)}`,
      `reader@${ITEM}#sha256:${"a".repeat(64)}`,
      `${ITEM}#sha256:${"A".repeat(64)}`,
      `${ITEM}#sha256:${"a".repeat(63)}`,
      `${ITEM}#sha256:${"a".repeat(64)}#x`,
      `${ITEM}#sha256:${"a".repeat(65)}`,
      `${ITEM}#x#sha256:${"a".repeat(64)}`,
    ];
    for (const id of ids) {
      const res = withLater(id);
      expect(res.m6.status, id).toBe("UNAVAILABLE");
      expect(res.m6.reason, id).toBe("INVALID");
    }
  });

  it("keeps a receipt listing the persisted form usable, like a clean id (F8-AMEND1)", () => {
    for (const id of [`${ITEM}#sha256:${"a".repeat(64)}`, persisted(`${ITEM}?utm_source=feed`)]) {
      const res = withLater(id);
      expect(res.m6.status, id).toBe("AVAILABLE");
    }
  });

  it("links a reviewed raw id to its persisted form, never to the raw id itself (F8-AMEND1)", () => {
    const raw = `${ITEM}?utm_source=feed`;
    const review = { id: raw, disposition: "REVIEWED_IRRELEVANT", reviewed_at: "2026-09-28T10:25:00Z" };
    expect(withLater(persisted(raw), "REVIEWED_IRRELEVANT", [review]).m6.status).toBe("AVAILABLE");
    // without the review the reviewed disposition is unlinked; the raw id stays unsafe even when reviewed
    expect(withLater(persisted(raw), "REVIEWED_IRRELEVANT").m6.reason).toBe("INVALID");
    expect(withLater(raw, "REVIEWED_IRRELEVANT", [review]).m6.reason).toBe("INVALID");
  });

  it("fails closed for a non-string id that would otherwise read as text", () => {
    for (const id of [true, [ITEM], { href: ITEM }]) {
      const res = withLater(id);
      expect(res.m6.status, JSON.stringify(id)).toBe("UNAVAILABLE");
      expect(res.m6.reason, JSON.stringify(id)).toBe("INVALID");
    }
  });
});

// Python/Worker parity (ROLLOUT-PERSISTED-ID-PARITY-VECTORS, ENDPHASE-CS4-LONE-SURROGATE): the frozen vectors of
// tests/fixtures/receipt-id-persisted-form-vectors.json are checked by tests/test_revenue_guidance_receipt_id_safety.py
// against scripts/revenue_guidance.py persisted_document_id (UTF-8 surrogatepass of the exact original, shown part at
// most 200 code points). Here the Worker is exercised through the only place it applies the transform: a reviewed raw
// id must link the frozen persisted id the checker writes (a hash or cut that differs misses the link and fails closed).
describe("persisted-form parity vectors shared with Python", () => {
  const golden = JSON.parse(readFileSync("../tests/fixtures/v213-orders-v3-golden-sealed.json", "utf-8"));
  const nvda = golden["NVDA"];
  const vectors: Array<{ name: string; raw: string; persisted: string; raw_unsafe: boolean; persisted_clean_text: boolean }> =
    JSON.parse(readFileSync("../tests/fixtures/receipt-id-persisted-form-vectors.json", "utf-8")).vectors;
  const hasLoneSurrogate = (text: string) => /[\ud800-\udfff]/u.test(text);
  const listed = (id: string, disposition = "IRRELEVANT", reviewed: any[] = []) => {
    const mut = JSON.parse(JSON.stringify(nvda.order_forecast_v3));
    const r = mut.evidence.latest_release_check;
    r.later_documents.push({ channel: "ISSUER_IR", date: "2026-09-01", id, label: "NVIDIA to Showcase Products", disposition });
    r.digest = computeReceiptDigest(r);
    mut.evidence.reviewed_later_documents.push(...reviewed);
    return parseOrderForecastV3(mut, REPORT_DAY, "NVDA", GOLDEN_GENERATED, nvda.order_forecast);
  };
  const review = (raw: string) => ({ id: raw, disposition: "REVIEWED_IRRELEVANT", reviewed_at: "2026-09-28T10:25:00Z" });

  it("carries the vector classes the contract names, including lone surrogates and the 200 code point cut", () => {
    expect(vectors.length).toBeGreaterThanOrEqual(30);
    expect(vectors.some((v) => hasLoneSurrogate(v.raw))).toBe(true);
    expect(vectors.some((v) => Array.from(v.raw.split(/[?#]/, 1)[0] ?? "").length > 200)).toBe(true);
    expect(vectors.some((v) => v.raw.includes("\u{1F600}"))).toBe(true);
    expect(new Set(vectors.map((v) => v.name)).size).toBe(vectors.length);
  });

  it("keeps a receipt listing the frozen persisted id usable, the way the checker writes it", () => {
    for (const v of vectors.filter((x) => x.persisted_clean_text)) {
      expect(listed(v.persisted).m6.status, v.name).toBe("AVAILABLE");
    }
  });

  it("fails closed for every raw-unsafe vector listed raw, reviewed or not, and for a persisted id with a lone surrogate in its shown part", () => {
    for (const v of vectors.filter((x) => x.raw_unsafe)) {
      expect(listed(v.raw).m6.reason, v.name).toBe("INVALID");
      expect(listed(v.raw, "REVIEWED_IRRELEVANT", [review(v.raw)]).m6.reason, v.name).toBe("INVALID");
    }
    for (const v of vectors.filter((x) => !x.persisted_clean_text)) {
      expect(listed(v.persisted).m6.reason, v.name).toBe("INVALID");
    }
  });

  it("links a reviewed raw id to exactly the frozen persisted id (hash, cut, lone surrogate bytes)", () => {
    const linkable = vectors.filter((v) => v.raw_unsafe && v.persisted_clean_text);
    expect(linkable.length).toBeGreaterThanOrEqual(25);
    for (const v of linkable) {
      expect(listed(v.persisted, "REVIEWED_IRRELEVANT", [review(v.raw)]).m6.status, v.name).toBe("AVAILABLE");
      expect(listed(v.persisted, "REVIEWED_IRRELEVANT").m6.reason, v.name).toBe("INVALID"); // no review, no link
    }
  });

  it("links a reviewed raw id only to its own persisted id (a neighbour vector does not link)", () => {
    const linkable = vectors.filter((v) => v.raw_unsafe && v.persisted_clean_text);
    linkable.forEach((v, i) => {
      const other = linkable[(i + 1) % linkable.length]!;
      expect(listed(v.persisted, "REVIEWED_IRRELEVANT", [review(other.raw)]).m6.reason, v.name).toBe("INVALID");
    });
  });

  it("is sensitive to the lone-surrogate bytes: the replacement-character digest of the same id is not the frozen one", () => {
    const lone = vectors.filter((v) => hasLoneSurrogate(v.raw) && v.persisted_clean_text);
    expect(lone.length).toBeGreaterThanOrEqual(3);
    // the literal Python computes (surrogatepass: 0xED 0xA0 0x80 for U+D800) and the one Node's string encoder gives (U+FFFD)
    const one = vectors.find((v) => v.name === "lone-high-after-query")!;
    expect(one.persisted.endsWith("#sha256:b348245d7885e90c93531848b86e39be698433705a1a1ea853f20144939b4b11")).toBe(true);
    expect(persisted(one.raw).endsWith("#sha256:126d57611770b3571c965f256c4942b259351403f44831956483f571f9e81ea0")).toBe(true);
    for (const v of lone) {
      expect(persisted(v.raw), v.name).not.toBe(v.persisted);
      expect(listed(persisted(v.raw), "REVIEWED_IRRELEVANT", [review(v.raw)]).m6.reason, v.name).toBe("INVALID");
    }
  });
});
