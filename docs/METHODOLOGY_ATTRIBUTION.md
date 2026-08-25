# Methodology Attribution Policy

This project must distinguish four different kinds of content. They may appear in the same report, but they must never be presented as if they came from the same author.

## 1. Source view

A **source view** is a faithful, time-stamped summary of what the named source actually published.

Requirements:

- identify the author/account and the original URL;
- preserve uncertainty, scope, time horizon and company-specific context;
- distinguish direct statements from paraphrases;
- never turn one company-specific comment into a universal rule;
- never invent a quote, threshold, position size, holding period or trade instruction;
- treat social-media views as time-sensitive and subject to later revision.

The source-view layer is descriptive. It does not calculate a portfolio score and does not imply that the author endorses this repository.

## 2. System operationalization

A **system operationalization** is a rule created by this repository to make research reproducible. Examples include numerical thresholds, evidence gates, score weights, entry/exit cutoffs and the Power/Compute/Components taxonomy.

Every such rule must be labelled:

> System operationalization — not a verbatim rule or recommendation from Serenity or Leopold Aschenbrenner.

The operationalization may be inspired by source material, but it is authored by this project and can be changed through review and tests.

## 3. User preference overlay

The repository owner's preference to assess suitability for a holding period of at least two years is a **user preference**, not a Serenity or Leopold Aschenbrenner view.

The long-term overlay:

- is calculated only after source views and the system research score are shown;
- does not modify source quotations or source summaries;
- does not modify the methodology-research score;
- must be titled `User-defined long-term suitability overlay`;
- evaluates durability, financing, dilution, balance sheet, customer concentration, cyclicality and evidence quality;
- is an analytical annotation, not a trade instruction or return forecast.

## 4. Model inference

A **model inference** is a conclusion produced by code or an AI model from available evidence. It must be labelled as an inference and include the evidence used, data timestamp, missing-data warnings and confidence.

## Prohibited attribution

The project must not attribute any of the following to Serenity or Leopold Aschenbrenner unless an exact primary source supports it:

- a blanket two-year or longer holding rule;
- the repository's five-layer score weights;
- fixed revenue-growth, market-cap, P/S or margin cutoffs;
- automatic entry/exit thresholds;
- the Power/Compute/Components stock-screen taxonomy;
- specific position sizes;
- options prescriptions;
- endorsement of any ticker in the current watchlist;
- the repository's projected returns, ratings or long-term suitability labels.

## Primary source registry

### Serenity (`@aleabitoreddit`)

The account publishes time-sensitive, company-specific market views. Representative source posts used to establish the current attribution boundary include:

- short-term entry points can materially affect outcomes for some names: https://x.com/aleabitoreddit/status/2045965735386820934
- the approach is described as discretionary and includes a company-specific AXTI/InP thesis: https://x.com/aleabitoreddit/status/2063465386960736396
- a company-specific long-term revenue/operating-income thesis can remain despite a drawdown: https://x.com/aleabitoreddit/status/2075496116481884524
- repeated ATM issuance can weaken support for a company: https://x.com/aleabitoreddit/status/2090903631793127644

These posts do not establish a universal two-year holding mandate or a formal seven-trigger/four-exclusion checklist.

### Leopold Aschenbrenner

The primary source is *Situational Awareness: The Decade Ahead* (June 2024):

- series introduction: https://situational-awareness.ai/
- AGI trendline argument: https://situational-awareness.ai/from-gpt-4-to-agi/
- compute, datacenter, power and infrastructure buildout: https://situational-awareness.ai/racing-to-the-trillion-dollar-cluster/

The essay advances macro and AI-development arguments. It does not present this repository's stock-screen thresholds, portfolio sizing rules or a blanket two-year holding recommendation.

## Report ordering

Every generated report must use this order:

1. source-derived views with provenance;
2. system operationalization and research score;
3. data/evidence confidence and contrary evidence;
4. user-defined long-term suitability overlay;
5. limitations and disconfirmation conditions.
