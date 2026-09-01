# Serenity H5 — Fidelity Deepening Shadow

H5 begins only after the H4 v4 semantic reconciliation has passed.  It is still
**shadow-only** and does not alter the live Worker, LINE bot, KV data, schedules or
Production ranking.

## Why H5 exists

Review of the real H4 v4 JSON showed that the remaining fidelity gaps are no
longer simple parser bugs.  They are longitudinal / comparative research gaps:

1. financing-program lineage instead of counting repeated ATM mentions;
2. qualified substitutes versus *effective* substitute capacity at the current ramp;
3. non-US financing context and architecture evidence;
4. persistent public Serenity source-view history with explicit staleness/delta.

## AAOI — financing lineage, not mention counting

The accepted H4 v4 report still represented three ATM event keys, but the actual
2026 Q2 filing describes a more precise lineage:

- Feb 26, 2026 — First Equity Distribution Agreement, up to $250m;
- Mar 12 — Amendment No. 1 raises the *same* First EDA to $500m;
- Apr 2 — First ATM completed (~4.8m shares / ~$490m net);
- May 14 — a separate Second EDA, up to $600m.

H5 therefore models **two financing programs + one amendment**, and supports the
financing disconfirmation from actual material issuance: 7,775,523 ATM shares in
H1 2026 and ~$1.029bn net proceeds, rather than from a raw event-count heuristic.

## AXTI — substitutes and capacity tightness are separate questions

AXT's filings disclose that a customer/prospect typically has at least two
qualified substrate suppliers and that Sumitomo and JX compete in InP.  This
prevents an automatic `SEMI_MONOPOLY` conclusion.

At the same time, 2026 agreements provide evidence of strong capacity demand:

- Coherent — three-year 6-inch InP development/supply commitment and $22.2885m
  prepayment;
- Lumentum — six-year InP capacity reservation;
- Casela — fixed 2027 purchase/capacity-priority arrangement.

H5 records this as a `capacity_tightness_candidate`, while
`effective_capacity_substitutability_at_current_ramp` stays `UNPROVEN` and the hard
`dependency_role` is not promoted.

This distinction is important when comparing factual evidence against Serenity's
Mar 17 public description of AXTI/SOI as favored substrate-level
"semi-monopoly"-like exposures.  The public source view is preserved, but is not
silently converted into factual dependency proof.

## SIVE — material dilution is not automatically toxic financing

Official 2026 sources disclose two directed institutional raises:

- Apr — 8.62m shares / SEK 125m / ~2.5% fully diluted impact;
- Jul — 12.280701m shares / SEK 700m / ~3.3% fully diluted impact.

The June/July issue was an accelerated institutional bookbuild and the official
pricing context is preserved.  H5 therefore records **material equity-capture
pressure**, but does not label it toxic without evidence of the retail-to-insider
value-transfer pattern that Serenity has publicly criticized in other companies.

Production-readiness and customer-ramp evidence from Sivers Q1/Q2 is recorded in a
separate capacity series.

## SOI / Soitec — architecture identity is official, exclusivity is not

Official Soitec Photonics-SOI and Smart Cut pages establish silicon-photonics
substrate relevance.  H5 can repair the architecture evidence while keeping
`dependency_role=UNPROVEN`; product relevance is not proof of market exclusivity.

## Append-only Serenity source history

H5 seeds a small set of direct public X source views that were verified during
development:

- financing/dilution disconfirmation (Jan 21, 2026);
- short-interest de-emphasis when fundamentals are strong (Feb 10);
- relative ticker view including AXTI/SOI/TSEM/COHR/SIVE/AAOI (Mar 17);
- Photonics/Memory supercycle framing (Mar 19).

The local history file is JSONL with a SHA-256 hash chain. Existing rows are never
rewritten. Running H5 again verifies the chain and does not duplicate known
source IDs.

A source view is explicitly **not factual dependency evidence**. New company facts
that occur after a source-view timestamp create a `requires_updated_serenity_view`
flag rather than guessing Serenity's current opinion.

## Production boundary

H5 may write two shadow artifacts:

- H5 fidelity-deepening report;
- append-only Serenity public source-history JSONL.

It does **not** deploy the Worker, sync KV, update LINE/Cloudflare credentials,
modify scheduled tasks, or replace Production rankings.
