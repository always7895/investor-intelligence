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
