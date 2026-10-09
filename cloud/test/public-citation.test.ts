import { describe, expect, it } from "vitest";
import { isPublicCitationUrl, requirePublicCitation } from "../src/v213/public-citation";

describe("shared public citation admission", () => {
  it.each([
    "https://www.sec.gov/Archives/report.htm",
    "https://ir.example.com/AMD%20Q2%202026.pdf",
    "https://example.com/growth100%25.pdf",
    "https://example.com:443/report?year=2026#financials",
  ])("preserves legitimate public reference %s", value => {
    expect(isPublicCitationUrl(value)).toBe(true);
    expect(requirePublicCitation(value)).toBe(value);
  });
  it.each([
    "http://example.com/report", "https://fixture@example.com/report",
    "https://127.0.0.1/report", "https://2130706433/report",
    "https://[::ffff:127.0.0.1]/report", "https://localhost/report",
    "https://example.local/report", "https://example.com:8080/report",
    "https://example.com/report?token=fixture", "https://example.com/report#api%5fkey=fixture",
    "https://example.com/report?access%255ftoken=fixture",
    "https://example.com/report?next=https%3A%2F%2Fexample.org%2F%3Fkey%3Dfixture",
    "https://example.com/report?X-Amz-Credential=fixture",
    "https://example.com/report?auth=fixture", "https://example.com/report?session_id=fixture",
    "https://example.com/report%0a", "https://example.com\\report",
  ])("rejects unsafe shapes without echoing input %s", value => {
    expect(isPublicCitationUrl(value)).toBe(false);
    expect(() => requirePublicCitation(value)).toThrow(/^UNSAFE_REPORT_CITATION$/);
  });
});
