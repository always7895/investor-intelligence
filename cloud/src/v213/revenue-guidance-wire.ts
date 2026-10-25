/** B3-WIRE-01: the disabled versioned transport envelope for the existing v3 order forecast
 * (docs/REVENUE_GUIDANCE_AUTOUPDATE.md, B3-WIRE-01 section).
 *
 * The envelope is a versioned wrapper around the complete existing v3 forecast, not a new admission
 * mode: ADMISSION_MODE is a fixed protocol label, not a permission or enablement flag, and an
 * envelope never converts machine evidence into human-approved evidence. `unwrapTransportV1` is the
 * reader-side decode: a recognized envelope yields its payload for the existing strict
 * `parseOrderForecastV3`; every other value (legacy v3, absent) passes through unchanged, so the
 * strict parser remains the sole source of forecast admission and availability.
 */
export const TRANSPORT_V1_SCHEMA = "v213-order-forecast-transport-v1";
export const TRANSPORT_V1_ADMISSION_MODE = "EXISTING_V3_ONLY";

/** Unwrap one transport-v1 envelope (schema + non-null payload) to its payload; any other value is
 * returned unchanged so the legacy v3 value and the strict parser's invalid results are untouched. */
export function unwrapTransportV1(raw: unknown): unknown {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const value = raw as { schema?: unknown; payload?: unknown };
    if (value.schema === TRANSPORT_V1_SCHEMA && value.payload && typeof value.payload === "object") {
      return value.payload;
    }
  }
  return raw;
}
