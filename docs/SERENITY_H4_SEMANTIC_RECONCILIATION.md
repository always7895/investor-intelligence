# H4 semantic reconciliation

Real H4 v3 output passed all release gates, but post-pass inspection exposed three residual semantic defects that must be corrected before H5.

## 1. AAOI ATM event over-counting

The original ATM event key used a wide text window around ATM / sales-agreement references. In the real output it produced five supposed events from only two filing URLs, including keys with `$0.001`, `undated`, and `noamount` values.

Those are not acceptable financing-event identities. The semantic retry now requires an ATM/sales-agreement context, an actual action, an explicit date, and a material amount of at least $1 million. Repeated descriptions of the same action/date/amount are deduplicated across filings.

If two distinct material events are not independently recovered, `repeated_atm_or_material_dilution` is removed from the shadow thesis-killer set. This does not claim the company has no dilution risk; it only prevents an unverified repeated-event claim.

## 2. TSEM capacity-expansion false negative

H4's generic capacity filter correctly removed market/network capacity wording from LITE, but it was too restrictive for Tower Semiconductor. The real SEC-filed text explicitly said Tower announced a strategic capacity expansion in Japan with METI support. That is an observed company expansion event, not a hypothetical statement.

The semantic retry restores this signal only when an SEC-bound excerpt contains explicit eventive language such as `announces strategic capacity expansion`. It does not restore `may/could/if` risk-factor language.

## 3. SIVE company-capture sequencing

H4 added official Sivers primary evidence and a supported `customer_named_ramp` commercial signal after the base H3 record had already computed company-capture state. The result therefore remained `UNPROVEN` despite accepted company-level commercial evidence.

The semantic retry reconciles company capture to `POSITIVE` when the official-primary retry passed and `customer_named_ramp` is supported. This does **not** change SIVE's `dependency_role` or thesis class. Customer ramp and a GlobalFoundries relationship edge are not bottleneck proof.

## Safety boundary

This retry is shadow-only and cannot:

- create dependency signals;
- add supply-chain graph edges;
- change any dependency role;
- increase the hard-dependency count;
- change Production ranking, LINE, Worker, KV, secrets, or schedules.

After this reconciliation passes, H5 can focus on true new information: qualified substitutes, capacity/lead-time time series, and persistent Serenity source-view history.
