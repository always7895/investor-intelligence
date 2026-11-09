# Current state / 目前狀態

**As of 2026-11-09 (Asia/Taipei).** Branch **`integ/r2`** is the isolated Stage 1C integration candidate, continuing from Stage 1B **`29fe31eb7bc5e8b7aa00fc6c38d30b35017cf091`** on base **`65e8f5b`**, not an accepted release or deployment. Independent **ACCEPT_WITH_FIXES** is not release acceptance; status remains **IMPLEMENTED_UNVERIFIED** pending master re-review of the fixed snapshot and evidence. Release **`v3.3.0`** remains the earlier dual-accepted source snapshot **`8ff4b0722f71f983716b2accc1fadeb301e848e4`**, not the installed Worker version.

## Production and rollout

- **Live Worker (master-reported):** version `18c0a22d-4e06-4f76-b687-423e524dba32`; deployed **2026-11-05T00:54:48Z** from source **`0c33b33`**; LINE access mode **`owner_only`**. These are the accepted deployment identifiers supplied by the master, not a new live readback performed in this repository.
- **Combined all-friends rollout: PAUSED by the operator on 2026-11-08.** Do not silently switch to `all_friends` or treat a source build as deployed. Any new rollout requires a new plan, **master GO**, and **explicit current-session operator authorization**.
- CI, an offline test, or a successful build does not qualify fresh sealed market evidence, confirm the current model endpoint or authorize LINE/KV/Worker changes.

## Integrated source and acceptance scope

- **UI-R3:** reviewed LINE display design pass, with Chinese human-facing labels and raw-code safeguards; no claim that every source renderer is live in the installed Worker.
- **GAP-C:** completed MOD → THRM distribution on 2026-10-01 (0.44619 THRM shares per MOD share). Because adjusted entitlement prices are not independently proven, historical returns crossing the distribution are withheld as **unknown, not zero**, and the positive long-term history gate excludes MOD from V3 Top20 until qualified.
- **MIN-1:** documented minimization of obsolete paths, preserving required tests, install/release boundaries and source evidence.
- **Official-guides documentation:** README, AGENTS/CLAUDE, GitHub community files, SKILL and topic documents follow the official guides; every Markdown file is linked from `docs/README.md`.
- The public-data/IBKR separation, paid-fallback refusal, rights/admission gates, sealed-object digest, snapshot freshness and rollback requirements remain mandatory. Source acceptance is not Production acceptance: `publication_eligible` stays false until a new rollout produces its own live evidence.

## Stage 1 integration boundary

- Monthly selection uses the nearest standard expiry without a minimum DTE, through exchange-local expiry-day close. Missing nearest chains require bounded lookup and dated refusal, not a later-month or weekly substitution.
- Covered-call and cash-secured-put selection have no annualized-yield floor; conservative strike, delta and quote requirements remain. Low yield is a displayed fact, not a reason to suppress an otherwise eligible strategy.
- LINE push localization precedes admission sizing, digesting and serialization; visible machine-code checks cover shared rendered fixtures. Mixed date-only and precise same-day observations preserve listing priority.
- Catalog bytes are bound to the Worker pin with LF checkout protection. Original source refusal reasons remain visible rather than being rewritten into invented refreshed-meta explanations.
- The lane's `REPORT-STAGE1.txt` records commits, committed-tree gates, identical-input route scans and separately recorded producer-function replay. Historical samples, synthetic fixtures, new raw recordings and regenerated metadata are distinct evidence populations.
- No Stage 2/R2B artifact, push, release, Production change or rollout is included. Local gates do not replace independent acceptance or fresh source evidence.

### Stage 1B follow-through

- M1 separates genuine provider observation clocks from acquisition clocks, including conservative handling of legacy generation-time collisions and observation-only lookup ranking.
- M2 preserves precise per-strategy refusal reasons on validated monthly observations. Missing metadata is not proof of an absent put chain; diagnostic-only blocks do not suppress otherwise eligible prior-session carry.
- m1 restores positive localized refusal assertions for corrupted snapshots; m3 applies currency-aware quote precision to Top20 cross-check lines without changing source values.
- `REPORT-STAGE1B.txt` records the separate commits, bounded public acquisition, offline whole-universe function/sealer/Worker evidence and committed-tree gates. Fresh recordings, synthetic regressions and unchanged historical-corpus checks remain distinct populations; function replay is not producer-main, publication-gate or Production acceptance.
- M3 and Stage 2 remain outside this stage; no push, tag, merge, deployment or real LINE delivery is authorized by these changes.

### Stage 1C follow-through

- US/Stockholm CC, CSP and collar share quote-bounded midpoint LIMIT recommendations, liquidity warnings and visible LIMIT/conservative-side economics. Wide spread is no longer a refusal; delta, OTM, exact identity/strikes, expiry, freshness, rights, seals and no yield floor remain binding. One-sided references do not qualify two-sided carry.
- Findings 1–3 distinguish empty/untyped/unreadable/no-instrument sources, verify one consistent Nordic exchange root and exact grouped strikes, and seal/display actual US source observation dates without assigning acquisition dates to prices or option legs.
- `REPORT-STAGE1C.txt` is the lane handoff for immutable Stage 1B replay, all 28 original observations, all 13 Nordic findings, SIVE Text/Flex, the separately authorized regular-session recollection and committed-tree gates. Counts and execution HEADs belong to their recorded inputs; a new input set is not an equal-input improvement claim.
- Only one bounded, read-only public recollection is authorized by the Stage 1C addendum. This does not authorize Stage 2, producer-main/publication acceptance, push, tag, merge, deployment, Production mutation or real LINE delivery.


## Release acceptance (v3.3.0)

- **Writer:** complete H5 gate `rel1-g2` on `8ff4b07`: 346 modules, 326 PASS, 20 BLOCKED as ruled before launch (host-bound modules), 0 FAIL; verdict PASS_AS_RULED.
- **Independent reviewer:** separate ChatGPT review in its own clone: four gates, `cloud` typecheck and 2204 Vitest tests, release-scope Python modules all exit 0; no P0/P1. Receipts are kept in the local audit archive.

## Next actions

1. Re-review the Stage 1B fixed snapshot using `REPORT-STAGE1B.txt`; retain Stage 1 evidence separately. Unproved source-data cases remain open, and successful local commands do not grant release acceptance or permission to start Stage 2.
2. Any later combined rollout requires a new plan, **master GO** and **explicit current-session operator authorization**; do not activate deployments, schedules or `all_friends` access.

## Open follow-ups

- **MOD:** obtain verifiable entitlement-adjusted historical returns before allowing a crossing-window CAGR to count.
- **AGLT:** follow the listed-company lead, but respect the **365-day history admission gate**; listing is not immediate ranking eligibility.
- **Aschenbrenner 13F:** verify the **Q3 2026 13F after 2026-11-16**, using filing date and reporting period; do not infer current positions from an earlier filing.
- **LITE/MRVL:** next deal-state review `review_by=2026-12-07`; the merger remains a pending state until primary evidence changes it.

**Boundaries:** no secret, owner/portfolio/IBKR-to-LINE data, Production mutation, paid fallback, automated trading or unauthorized rollout. Prior evidence remains in Git (`git show 38860e7:state/STATUS.md`), not as competing current-status prose.
