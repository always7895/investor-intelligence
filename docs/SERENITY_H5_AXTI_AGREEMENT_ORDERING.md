# H5 v5 — AXTI agreement-ordering repair

## Runtime failure

H5 v4 reached the AXTI qualified-substitute/capacity layer and failed with:

`required evidence not found: AXTI-Coherent 6-inch InP agreement`

The filing was fetched successfully.  The failure was a parser-order assumption.

## Filed Coherent wording

AXT's June 26, 2026 Form 8-K first identifies `6-inch indium phosphide (InP)
wafer substrates`, then states that the Agreement has an `initial term of three
(3) years`.  The H5 base regex expected the opposite order inside one bounded
window.

H5 v5 validates the evidence as independent semantic anchors instead:

- 6-inch InP wafer-substrate product;
- initial three-year term;
- US$22,288,500 prepayment;
- minimum-order-quantity mechanics;
- manufacturing-capacity expansion during 2026-2028.

It also strengthens the other two AXTI commitments:

- Lumentum: six-year minimum annual capacity reservation and two US$43.5m deposits;
- Casela: 2027 fixed aggregate quantity, RMB173m total contract price and at least
  80% minimum purchase.

## Fidelity boundary

The agreements create evidence-bound order/capacity visibility.  They do not prove
that qualified alternatives lack effective capacity at the current AI/photonics
ramp.  AXTI must therefore remain dependency_role=UNPROVEN until independent
capacity/substitute evidence closes that gap.

The order-outlook text may describe signed visibility, but a total future-order
number across all customers remains prohibited unless directly supported by public
contract terms.
