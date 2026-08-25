# Global Authoritative Source Federation

## Design objective

Investor Intelligence does **not** impose a fixed source count such as eight, twenty or one hundred. The registry is directory-based and may grow to any number of admitted sources without changing application code.

The absence of a count limit does not mean indiscriminate scraping. Every source must pass authority, identity, legal-access, zero-cost, provenance, freshness, parser and health gates before it can influence a report or score.

```text
NO_ARTIFICIAL_SOURCE_COUNT_LIMIT
+ STRICT_SOURCE_ADMISSION
+ BOUNDED_PER-HOST_CONCURRENCY
+ PRIMARY-EVIDENCE-FIRST
+ FAIL-CLOSED_CORRECTNESS
```

## Eligible source families

The federation may include any lawful, free and publicly accessible source belonging to one or more of these families:

- securities regulators and statutory filing systems;
- regulated stock exchanges and official announcement systems;
- central banks, finance ministries and treasuries;
- national statistics offices and government open-data portals;
- international organizations and multilateral institutions;
- public court, patent, procurement, customs, trade and sanctions databases;
- official company investor-relations sites, filings and press releases;
- licensed or regulated brokers providing data already available to the authenticated user without a new paid subscription;
- public academic, standards, patent and scientific repositories;
- reputable global newswires, public-service broadcasters and financial publications when public access and terms permit;
- industry regulators, energy agencies, geological surveys, grid operators and other authoritative sector bodies;
- public supply-chain, shipping, aviation, spectrum, telecommunications and environmental datasets;
- additional authoritative sources discovered later and approved through the same admission process.

A source is not admitted merely because it is popular, has a government-like domain, appears in search results or is quoted by another website.

## Trust tiers

### T1 — Primary official authority

The organization is the legal owner or statutory publisher of the fact: regulator filing, exchange announcement, central-bank release, government statistic, court record, patent office record, issuer filing or official corporate release.

A T1 source may support a direct factual claim within its authority. It does not automatically support an investment conclusion or causal inference.

### T2 — Regulated or institutionally authoritative corroboration

Examples include a regulated exchange data service, recognized intergovernmental institution, licensed broker data available to the user, established academic repository, standards body or reputable newswire with transparent attribution.

A T2 source normally corroborates a T1 fact or supports a claim when at least two independent organizations agree.

### T3 — Reputable secondary lead

Established financial publications, aggregators, research summaries and public market-data conveniences may be used as discovery leads or secondary context. They cannot replace missing primary evidence for material company facts.

### T4 — Unverified or low-authority source

Forums, anonymous posts, copied content, SEO farms, unsourced social posts and unverifiable datasets are quarantined. They cannot affect scoring, recommendations or factual report sections.

## Source admission lifecycle

Every new source follows this lifecycle:

```text
DISCOVERED
  -> IDENTITY_VERIFIED
  -> LEGAL_AND_FREE_ACCESS_APPROVED
  -> ADAPTER_CONTRACT_VALIDATED
  -> PROVENANCE_VALIDATED
  -> PARSER_CANARY_PASS
  -> HEALTH_SOAK_PASS
  -> RUNTIME_ENABLED
```

Failure at any gate produces one of:

```text
QUARANTINED
DISABLED_PAYMENT_REQUIRED
DISABLED_TERMS_INCOMPATIBLE
DISABLED_IDENTITY_UNVERIFIED
DISABLED_SCHEMA_UNSTABLE
DISABLED_HEALTH_FAILURE
DISABLED_FREE_ONLY_POLICY
```

Discovery never auto-enables a source.

## Registry architecture

The loader recursively reads every JSON document under:

```text
config/sources/**/*.json
```

There is no `maximum_sources` field. Additional jurisdictions, sectors and source families are added by placing another validated registry file in that directory.

Runtime work is bounded by operational controls rather than by total source count:

- per-host concurrency;
- per-host request rate;
- bounded retry and exponential backoff;
- circuit breakers;
- daily free-quota budgets;
- priority queues;
- crawl windows and cache TTLs;
- source-specific terms and robots/access controls.

This allows the catalog to grow without creating an uncontrolled request storm.

## Provenance record

Every accepted observation carries at least:

```text
source_id
source_family
authority_class
trust_tier
canonical_url
jurisdiction
language
published_at
retrieved_at
content_hash
parser_id
parser_version
claim_type
evidence_role
freshness_status
source_health
correction_status
```

A model-generated summary is never treated as source evidence.

## Claim verification policy

### Direct official facts

A current T1 record can establish a fact within the publisher's authority, such as a filed revenue value, policy rate, official employment figure or exchange announcement.

### Secondary or interpretive claims

Material interpretations require either:

- one relevant T1 source plus independent corroboration; or
- at least two independent T2 organizations whose evidence can be traced to original material.

### Conflicting evidence

The system does not average contradictory facts. It records the conflict and applies this order:

1. corrected/restated primary source;
2. current primary source within its legal authority;
3. official exchange/regulator mirror;
4. independent institutional corroboration;
5. reputable secondary coverage.

If the conflict remains unresolved, the report says so and the disputed field cannot drive an automatic score change.

## Stability and correctness controls

- Store the last known good normalized record separately from raw retrieval attempts.
- Use content hashes and immutable retrieval timestamps.
- Reject impossible future publication times and malformed chronology.
- Detect parser/schema drift with canary fixtures and field-completeness checks.
- Quarantine sudden outliers until confirmed by primary evidence.
- Preserve corrections, restatements and superseded versions instead of silently overwriting them.
- Label delayed, stale, preliminary, revised and final data explicitly.
- Never convert a source outage into a zero value.
- Never substitute a lower-trust source without changing the evidence label.
- Keep public source cache separate from every tenant-private namespace.
- Treat retrieved HTML, PDF, feed and document text as untrusted data for prompt-injection purposes.

## Coverage strategy

Coverage is measured by gaps, not by a target source count. The coverage ledger tracks:

- jurisdiction;
- asset class;
- company/issuer;
- macroeconomic series;
- sector and supply-chain layer;
- claim type;
- language;
- primary-source availability;
- independent corroboration availability;
- freshness and health.

A new source is prioritized when it closes a real evidence gap or improves resilience, not simply to increase a number.

## Zero-cost boundary

A required source must not require:

- a paid API key;
- a premium subscription;
- a credit card that can roll into paid billing;
- bypassing a paywall, login, CAPTCHA or access control;
- prohibited scraping;
- a paid market-data package.

A licensed broker source may be used only when the authenticated user already has lawful access and no new purchase is required. It remains tenant-private and cannot become a global public feed.

## Release gates

Before a source can be enabled in production:

1. registry schema validation passes;
2. official ownership/domain is verified;
3. access terms and zero-cost status are reviewed;
4. adapter returns deterministic normalized output;
5. provenance fields are complete;
6. stale/revision/correction handling is tested;
7. rate limit and circuit breaker are tested;
8. malformed and hostile content tests pass;
9. source outage preserves the last known good state;
10. no private tenant data is transmitted to the source;
11. no paid fallback is reachable;
12. the source is represented in the coverage ledger.

## Non-goal

The system does not promise that every public website on Earth is continuously scraped. It promises that there is no artificial source-count ceiling and that every admitted source remains traceable, lawful, free, independently governed and safe to use.