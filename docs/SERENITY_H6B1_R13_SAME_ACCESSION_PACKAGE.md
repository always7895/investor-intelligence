# H6B1 R13 — Same-accession SEC filing-package enrichment

## Observed R12 result

R12 passed all same-source, immutable-fallback, canonical-wording, clause-safe,
zero-safe and Worker regressions. The real 20-row build also passed, but the final
acceptance gate still found NVDA future fulfillment as unavailable.

The real run therefore proved that the remaining problem is not current-order
binding or recursion. The source-view boundary is too narrow for some inline-XBRL
filings.

## NVIDIA filing shape

NVIDIA's 2026-08-26 Form 10-Q reports in the same accession package that:

- revenue related to remaining performance obligations from contracts greater
  than one year was about $3.2 billion; and
- approximately 39% will be recognized over the next twelve months.

SEC inline-XBRL filings can expose that disclosure through a generated report
page such as `R14.htm` even when the primary HTML occurrence selected for the
current RPO does not carry the complete fulfillment sentence in its bounded text
view.

Treating an SEC accession as unrelated URLs is therefore too strict. Treating
arbitrary documents as one source is too loose.

## R13 boundary

R13 uses the SEC accession directory as the provenance boundary.

It preserves R12's selected current-order metric and source. Only when:

1. current orders are `SUPPORTED`;
2. future orders remain `UNAVAILABLE`;
3. there is exactly one selected SEC current source;
4. `FilingSummary.xml` belongs to that exact accession directory; and
5. an `Rxx.htm` report from that same accession contains the same metric type and
   the same normalized unit-bearing amount

may the explicit fulfillment schedule be promoted to `INFERENCE`.

Different accessions, documents outside the accession directory, amounts, metric
types, or conflicting schedules fail closed.

## Important policy correction

A fixed quota such as `future_order_evidence_bound_rows >= 11` is not a valid
research-quality criterion. It can pressure the system to create false positives
when issuers simply do not disclose quantified fulfillment schedules.

H6B acceptance should therefore be semantic and provenance-based:

- every `INFERENCE` must have explicit evidence and provenance;
- every unsupported schedule must remain `UNAVAILABLE`;
- no minimum number of inferred schedules is required.

The R13 Windows runner still explicitly verifies the known NVDA 39% disclosure
because it is a concrete regression case, but it does not require an arbitrary
portfolio-wide inference count.

## Production boundary

R13 remains shadow-only. It does not send LINE, deploy Worker code, modify KV,
credentials, schedules, rankings, or Production state.
