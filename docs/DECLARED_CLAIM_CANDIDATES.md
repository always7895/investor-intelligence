# Declared Claim Candidate Profile (NARROW EXPLICIT)

This document describes a **NARROW EXPLICIT CANDIDATE PROFILE**, not general
canonical qualification. It routes exactly one explicitly approved declared
claim class to candidate sources and reports the result as
`CANDIDATES_ONLY` metadata.

## Scope

The profile supports exactly one approved pair:

- **Claim class:** `MACRO`
- **Profile:** `statistical-series-v1`

That pair is a **fixed, code-owned mapping** to the legacy claim family
`macro_indicator`. It is an explicitly approved statistical-series candidate
subset. It is **not** a caller-selected mapping and **not** complete `MACRO`
support. Any other claim class or profile is refused.

The code-owned constants are:

| Constant       | Value                  |
| -------------- | ---------------------- |
| `CLAIM_CLASS`  | `MACRO`                |
| `PROFILE`      | `statistical-series-v1`|
| `MAPPED_FAMILY`| `macro_indicator`      |

## Commands

The CLI is `scripts/source_declared_candidates.py`. `--claim-class` and
`--profile` are required. The path options default to the repository config.

### Default (repository config)

```bash
python scripts/source_declared_candidates.py \
  --claim-class MACRO \
  --profile statistical-series-v1
```

### Owned fixtures (custom catalog)

```bash
python scripts/source_declared_candidates.py \
  --claim-class MACRO \
  --profile statistical-series-v1 \
  --catalog-dir <path-to-catalog-dir>
```

Optional path options (all default to the repository config):

| Option                | Default                                          |
| --------------------- | ------------------------------------------------ |
| `--catalog-dir`       | `config/sources`                                 |
| `--taxonomy`          | `config/source-claim-taxonomy.json`              |
| `--claim-policy`      | `config/source-claim-coverage-policy.json`       |
| `--federation-policy` | `config/v213-source-federation-policy.json`      |

The registry is loaded with the existing `load_registry`; the config JSON is
loaded with the existing `load_json_strict`.

## What the profile does

1. Requires the exact approved pair `MACRO` + `statistical-series-v1`
   (strict strings).
2. Validates the declaration through the existing
   `source_claim_taxonomy_inventory.inventory` helper and ensures `MACRO` is
   declared.
3. Requires a valid existing federation ceiling through
   `source_registry.activation_max_age`; the ceiling is never dropped.
4. Delegates candidate routing to the existing
   `source_registry.route_claim` helper with the fixed code-owned family
   `macro_indicator`, `runtime_only=True`, and the supplied federation policy.
   No predicates are cloned and no returned route metadata is altered.
5. Returns the unchanged delegated route inside a `CANDIDATES_ONLY` envelope.

## Envelope

```json
{
  "stage": "CANDIDATES_ONLY",
  "claim_class": "MACRO",
  "profile": "statistical-series-v1",
  "mapped_family": "macro_indicator",
  "route_performed": true,
  "qualification_performed": false,
  "subject_binding_performed": false,
  "geographic_binding_performed": false,
  "publication_eligible": false,
  "route": "<unchanged delegated route_claim envelope>"
}
```

The envelope carries **no** `IMPLEMENTED`, `QUALIFIED`, or `LIVE_SUPPORTED`
labels.

## Candidate vs qualification / subject / geography limitations

This profile performs **candidate routing only**. It explicitly does **not**:

- perform evidence qualification (`qualification_performed=false`);
- perform subject binding (`subject_binding_performed=false`);
- perform geographic binding (`geographic_binding_performed=false`);
- decide publication eligibility (`publication_eligible=false`);
- apply capability/health overrides or geographic filtering;
- create or intake observations, `ParsedBatch`, or `FetchReceipt`;
- fetch, score, admit sources, or touch settings or the network.

The required fields, lineages, TTL, and fallback values inside `route` remain
**delegated metadata**, not validated claims. They are passed through unchanged
from `route_claim`.

## General canonical qualification still pending

General canonical qualification (arbitrary claim classes, subject binding,
geographic binding, evidence qualification, and publication eligibility) is
**still pending** and is **not** provided by this profile. This profile is a
narrow, explicitly approved statistical-series candidate subset for `MACRO`
only.

## Errors

All invalid arguments, config, profile, or missing paths produce a fixed
private-safe error on stderr and a non-zero exit code. Argparse never echoes
unknown arguments or private inputs.