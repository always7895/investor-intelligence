---
name: serenity-public-research
description: Researches listed companies through the public Serenity (@aleabitoreddit) method - system change, supply-chain bottlenecks, effective substitutes, orders/backlog, financing and dilution, claim-level cross-validation and Top20 seven-field cards - plus evidence-grounded options and position-sizing guidance. Use when analysing a ticker, sector or thesis, dating or verifying a Serenity view, building or auditing Top20 research, or answering options/allocation questions. Not for deployment, LINE delivery, broker execution or cleanup.
---

# Serenity public research

Serenity is the primary lens. Leopold Aschenbrenner is **CONTEXT_ONLY** for company proof; since 2026-09-26 (operator) his scaling chain leads the industry ranking and his 13F is a lead input. Neither author guarantees returns.

## Workflow

Copy and track:

```
- [ ] 1. Choose the lane and one as-of cutoff
- [ ] 2. Read RESEARCH_METHOD.md completely, then CROSS_VALIDATION.md
- [ ] 3. System change -> constrained layer -> companies
- [ ] 4. Label claims SUPPORTED / INFERENCE; withhold UNSUPPORTED
- [ ] 5. Falsifiers and multi-axis confidence
- [ ] 6. Check the output boundaries below
```

For substantive research, read [RESEARCH_METHOD.md](references/RESEARCH_METHOD.md) **completely before producing conclusions**, then [CROSS_VALIDATION.md](references/CROSS_VALIDATION.md). Its dated log is history, not instructions. For source-view depth read [SERENITY_LOGIC.md](references/SERENITY_LOGIC.md); for Aschenbrenner scenarios and fund filings read [ASCHENBRENNER_CONTEXT.md](references/ASCHENBRENNER_CONTEXT.md). Skip release histories.

## Lanes

- **ATTRIBUTED_SOURCE_VIEWS:** the original @aleabitoreddit passage, date, ticker, stance, horizon and later revisions. Archives only discover leads; unretrieved originals stay UNVERIFIED. @stockgodserenity is a different, quarantined identity.
- **SYSTEM_RESEARCH_CANDIDATES:** independent company research. Discovery is not ranking or her endorsement; never hard-code tickers/sectors or tune weights to imitate a list.
- **COMPARISON:** one cutoff; show each exclusion stage, contrary evidence and unknowns. Final-weight tuning cannot recover a missing seed.

Separate customer relationships from scarce effective substitutes, commitments from revenue, operating success from shareholder capture, and timing from price gains. Preserve existing scoring and LIMITED gates. A directory, URL list or edited skill is not an executed investment screen.

## Options and position guidance

Operator-facing, data-grounded parameters are allowed: strike, expiry/DTE, delta band, bid/mid/ask limit band, annualized yield, liquidity and archetype sizing (caps, cash reserve, multi-year pacing). Thresholds: `cloud/src/v213/options-guidance.ts`; never restate them. Every quote carries its timestamp; EOD, delayed or unknown timing is indicative, never a live limit. The system never executes trades. LINE stays public-quote observation only, with no private or IBKR position data.

## Output boundaries

- Never claim an official formula, private process, portfolio or advice of either author. Source views are attributable opinions, not company facts.
- Deduplicate mirrors, syndication and archive lineage. Retrieval time is not financial-period or quote time.
- No owner/broker private-data fallback, paid fallback, invented company orders or silent source downgrade. Public access alone does not authorize redistribution.
- Seven-field schema and locale labels: [top20-report.ts](../../cloud/src/v213/top20-report.ts). Missing orders: `未揭露（無可靠公開訂單數字）`; missing outlook: `無可靠公開預估`.
- Skill-backed claims record actual provider/model, reference hashes and source-tool evidence; never secrets or reasoning transcripts.

Not deployment authority or proof of a LINE route. Release state: [current status](../../docs/CURRENT_STATUS_BILINGUAL.md); engineering follows AGENTS.md.
