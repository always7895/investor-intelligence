# Serenity H4 — independent corroboration and non-US primary shadow

H4 is still shadow-only. It was designed after reviewing the real H3 Pass1/Pass2 output.

## Real H3 defects H4 must correct

1. Generic issuer risk language can look like an observed event.
   - AAOI: "whether the design win..." was a generic sales-cycle sentence, not an actual design win.
   - AXTI: "If we fail to meet ... qualification..." was a generic risk statement, not an observed qualification constraint.
   - COHR: "Any failure or delay in obtaining ... qualification..." was hypothetical, not an actual qualification delay.
2. Market/network capacity can be confused with focal-company manufacturing capacity.
   - LITE's "capacity expansion across DCIs/metro/long-haul networks" is market infrastructure language.
3. Distinct SEC filing URLs do not necessarily mean distinct ATM financing events.
   H4 extracts event keys (action/date/amount) and refuses to double-count periodic restatements of one ATM program.
4. Foreign ticker identity can be wrong.
   - H3's SOI market lead resolved to Yahoo ZQM.SI (Soilbuild), not Soitec.
   H4 uses an official issuer identity profile and treats incompatible market symbols as mismatches.
5. Non-US primary evidence was missing.
   - SIVE and SOI had zero SEC primary evidence.
   H4 adds official issuer investor/regulatory pages as primary issuer evidence.
6. Independent counterparties are required before a supply-chain relationship is treated as independently corroborated.
   H4 attempts official-counterparty and counterparty-SEC corroboration for bounded archetypes.

## Important boundary

Independent collaboration is not the same as a bottleneck. H4 may add an evidence-bound supply-chain graph edge, but it still does not emit SINGLE_SOURCE / SEMI_MONOPOLY / QUALIFICATION_CONSTRAINED / CAPACITY_BOTTLENECK unless independent evidence supports the scarcity/qualification claim itself.

## Initial foreign identity profiles

- SIVE = Sivers Semiconductors AB, Nasdaq Stockholm.
- SOI = Soitec S.A., Euronext Paris.

These profiles are source-identity adapters for shadow validation, not a production ticker whitelist or ranking preference.

## Production

No Production mutation. No Worker deploy, KV sync, LINE/Cloudflare secret change, task change, or ranking replacement.
