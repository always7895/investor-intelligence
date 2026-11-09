import { exchangeDate, expiryDayOpen, type OptionVenue } from "../../src/v213/option-recommendation-rules";

/** Synthetic third-Friday expiry, computed independently of the production selector. */
export function standardMonthlyFixture(nowMs: number, venue: OptionVenue = "US"): { expiry: string; dte: number } {
  const now = new Date(exchangeDate(nowMs, venue) + "T00:00:00Z");
  const dayMs = 86_400_000;
  const today = now.getTime();
  let month = now.getUTCMonth();
  let expiryMs: number;
  do {
    const fifteenth = Date.UTC(now.getUTCFullYear(), month++, 15);
    expiryMs = fifteenth + (5 - new Date(fifteenth).getUTCDay() + 7) % 7 * dayMs;
  } while (expiryMs < today || (expiryMs === today && !expiryDayOpen(nowMs, venue)));
  return { expiry: new Date(expiryMs).toISOString().slice(0, 10), dte: (expiryMs - today) / dayMs };
}
