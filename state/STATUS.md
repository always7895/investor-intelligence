# Current state / 目前狀態

**As of 2026-11-08 (Asia/Taipei).** The integrated development source is `feat/v33-options-trend`, **HEAD `947b24a970d4914cace1a83d4c58959de5c77fc2`** (the source baseline at this review). The branch contains reviewed integration work, but its HEAD is **not** the installed Worker version. Recheck `git rev-parse HEAD` after subsequent integrations; this page records the project, not a task log.

## Production and rollout

- **Live Worker (master-reported):** version `18c0a22d-4e06-4f76-b687-423e524dba32`; deployed **2026-11-05T00:54:48Z** from source **`0c33b33`**; LINE access mode **`owner_only`**. These are the accepted deployment identifiers supplied by the master, not a new live readback performed in this repository.
- **Combined all-friends rollout: PAUSED by the operator on 2026-11-08.** Do not silently switch to `all_friends` or treat a source build as deployed. Any new rollout requires a new plan, **master GO**, and **explicit current-session operator authorization**.
- CI, an offline test, or a successful build does not qualify fresh sealed market evidence, confirm the current model endpoint or authorize LINE/KV/Worker changes.

## Integrated source and acceptance scope

- **UI-R3:** reviewed LINE display design pass, with Chinese human-facing labels and raw-code safeguards; no claim that every source renderer is live in the installed Worker.
- **GAP-C:** completed MOD → THRM distribution on 2026-10-01 (0.44619 THRM shares per MOD share). Because adjusted entitlement prices are not independently proven, historical returns crossing the distribution are withheld as **unknown, not zero**, and the positive long-term history gate excludes MOD from V3 Top20 until qualified.
- **MIN-1:** documented minimization of obsolete paths, preserving required tests, install/release boundaries and source evidence.
- **Official-guides documentation:** README, AGENTS/CLAUDE, GitHub community files, SKILL and topic documents were rewritten and checked on an isolated documentation branch; the master must integrate that patch into the final source head before release qualification.
- The public-data/IBKR separation, paid-fallback refusal, rights/admission gates, sealed-object digest, snapshot freshness and rollback requirements remain mandatory. **`publication_eligible=false` until the final integrated HEAD satisfies its release evidence.** Source completion alone is not Production acceptance.

## Next release actions

1. **Complete the full H5 gate on the final integrated HEAD**, including the relevant Windows/live, fail-closed and source-bound acceptance evidence. Treat missing, blocked or stale evidence as not qualified.
2. After acceptance, **merge to `main`, create the requested tag and GitHub release** (operator requested); preserve immutable build/source identities and independent archive checks. This item is a release plan, not authorization for this documentation editor to perform the GitHub operations.
3. Propose a **new rollout plan** for the combined product. Do not activate any deployment, schedule or `all_friends` access without the **master's GO and the operator's current-session approval**.

## Open follow-ups

- **MOD:** obtain verifiable entitlement-adjusted historical returns before allowing a crossing-window CAGR to count.
- **AGLT:** follow the listed-company lead, but respect the **365-day history admission gate**; listing is not immediate ranking eligibility.
- **Aschenbrenner 13F:** verify the **Q3 2026 13F after 2026-11-16**, using filing date and reporting period; do not infer current positions from an earlier filing.
- **LITE/MRVL:** next deal-state review `review_by=2026-12-07`; the merger remains a pending state until primary evidence changes it.

**Boundaries:** no secret, owner/portfolio/IBKR-to-LINE data, Production mutation, paid fallback, automated trading or unauthorized rollout. Prior evidence remains in Git (`git show 38860e7:state/STATUS.md`), not as competing current-status prose.
