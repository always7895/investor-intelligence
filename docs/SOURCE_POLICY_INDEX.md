# Source Policy Index

## Current source-of-truth order

1. `docs/GLOBAL_SOURCE_FEDERATION.md`
2. `config/sources/registry-policy.json`
3. `scripts/source_registry.py`
4. `config/sources/**/*.json`
5. `docs/FREE_DATA_SOURCE_PLAN.md`

Any earlier wording that refers to an eight-source, fixed-source or finite-source design is superseded.

The current enforceable rule is:

```text
NO_ARTIFICIAL_SOURCE_COUNT_LIMIT
```

Sources may be added without changing application code, but no discovered source is trusted or enabled automatically. Every source must remain lawful, free, attributable, health-checked, correction-aware and independently governed.

A large source catalog does not weaken evidence standards:

- T1 primary authority for direct official facts;
- independent corroboration for material interpretation;
- T3 media only as lead/context;
- T4 quarantined;
- unresolved conflicts cannot drive automatic score changes;
- no paywall, authentication, CAPTCHA or terms bypass;
- no paid fallback;
- no tenant-private data in the public source federation.
