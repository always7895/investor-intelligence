# H4 SIVE official-primary identity retry

## Why this patch exists

The first H4 live shadow completed all seven symbols, claim-quality corrections,
SOI/Yahoo identity mismatch detection, and one independent graph edge, but the
release gate failed because both Sivers official pages returned no usable identity
attestation to the default `python-requests` client on the user's Windows machine.

This is an HTTP-client compatibility problem, not a Serenity methodology failure.
The same public Sivers pages are reachable in ordinary browser/web retrieval.

## Repair

The retry adapter:

1. uses ordinary browser-like headers for non-SEC public issuer pages;
2. tries stable Sivers investor/regulatory pages in addition to a collaboration page;
3. requires both company identity (`Sivers Semiconductors`) and an exchange/ticker
   marker (`Nasdaq Stockholm`, `STO:SIVE`, or `SIVE:ST`);
4. patches only the H4 identity-verification fields in a shadow report;
5. does **not** create dependency signals, bottleneck roles, scores, or Production
   changes.

Official Sivers URLs used:

- `https://www.sivers-semiconductors.com/investors/interim-reports/`
- `https://www.sivers-semiconductors.com/press/sivers-semiconductors-updates-financial-reporting-calendar/`
- `https://www.sivers-semiconductors.com/press/sivers-globalfoundries-advance-ai-data-center-optical-solutions/`

## Fail-closed behavior

If none of the official pages can be fetched **and** validated for both issuer and
exchange/ticker identity, the retry remains `DEGRADED`; it does not manufacture a
PASS from configuration alone.

This adapter remains shadow-only and cannot change the live LINE/Worker ranking.
