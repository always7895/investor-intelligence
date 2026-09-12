# Investor Intelligence v2.1.3 R75

[繁體中文](README.zh-TW.md) · [Documentation](docs/README.md) · [Current findings](state/STATUS.md) · [Latest immutable release](https://github.com/always7895/investor-intelligence/releases/latest)

Privacy-first public-market research and evidence-grounded conditional recommendations. No broker execution, guaranteed returns or paid fallback. Source development and an installed application are different acceptance scopes.

## Use and limits

- `Top20`: 20 complete seven-field bilingual cards, four carousels of five. Historical 2Y annualized / 6M returns are **not future price forecasts**.
- `Top20 文字`: all companies in full seven-field text. Candidate cards also offer **本公司七欄文字** and **證據詳情**, bound to the card's ticker, timestamp, snapshot and report SHA. Neither is a complete valuation report.
- Order summaries retain disclosed amounts and recognition windows. RPO, backlog, prepayments, pipeline and revenue are not interchangeable or additive. A filing date is not a delivery date; undisclosed dates remain unknown.
- Future 6/12/24-month price scenarios require sourced operating inputs, financing/dilution and a reproducible valuation bridge. Removed hard-coded bull/bear percentages are not restored as evidence. [Requirements and audit](docs/RESEARCH_EXECUTION_AUDIT.md).
- Missing, stale, conflicting or LIMITED evidence stays explicit. Direct public facts and independent investment-thesis support are different evidence levels.

## Current development vs released baseline

[STATUS](state/STATUS.md) is the only current defect/acceptance register. Historical disabled-task, no-deployment and all-zero-defect statements elsewhere must not override later recorded evidence. Prior operator-reported LINE acceptance and publication are dated observations, not new-session verification or authorization. Natural morning/evening schedule acceptance and a newly qualified whole-product release remain separate requirements.

The local public collector supports opt-in Fed/SEC/ECB announcements and TWSE/TPEx equity EOD, plus TAIFEX/Alpaca local imports. Access, rights, provenance and LINE publication each require their own gates; daily/indicative data is not executable NBBO. See [source coverage](docs/PUBLIC_SOURCE_COVERAGE.md) and [options review](docs/OPTIONS_SOURCE_REVIEW.md).

The EXE candidate has manual model/THINK selection, not qualified automatic best-mode selection. A healthy Router or completed marker is not a research-quality result. [Model contract](docs/MODEL_RUNTIME_MIGRATION.md).

## Released identity — historical 2026-09-06 baseline

Published/installed source: `b5baae936dd3d422583decf9268910ed5783e4d5`; Windows CI [33992169731](https://github.com/always7895/investor-intelligence/actions/runs/33992169731). ZIP SHA256: `320dfb799b34d1220138f67780d2f3fd0004781fcdeaf93e8d543169386f2e69`.

The published archive was independently downloaded/verified; GitHub release-asset attestation passed `gh release verify-asset`. This is **not SLSA workflow build attestation** (unavailable for that workflow), newer-source qualification or today's live market evidence. For each ZIP, its own `HOTFIX-REFS.json`, external checksum and adjacent receipts identify the executable source and build run. Full historical observations: `git show 4ba2a606c9e459884e15354aa91798ec432df0ba:README.md` and [delivery history](state/FINAL_DELIVERY_REPORT_R75_FREE_RELAY.md).

## Architecture and authority

```text
LINE -> privacy/admission -> pinned public snapshot -> deterministic Top20
                         -> bounded compact public Q&A
workers.dev -> signed short-lived lease -> TryCloudflare -> Gateway
            -> existing localhost:8080 Router -> exact approved model
```

Serenity is the primary public-method lens; Leopold Aschenbrenner is CONTEXT_ONLY, not an extra score or permanent AI-sector filter. Public reconstruction is not either author's official formula, private process or current endorsement. The Pi research skill is on-demand; Top20 and compact Q&A do not execute the full skill. [Execution audit](docs/RESEARCH_EXECUTION_AUDIT.md) distinguishes actual callers from file-presence checks.

Preserve scoring, claim independence, LINE/IBKR separation, freshness and provenance. Publication requires sealed digest-bound objects, readback and pointer-last commit, with replay rejection, durable failure journals, rollback and finalize. Certified `cloud/src/qa.ts` blob: `94184bc8937b413eb327b3d773926db00e22b3b9`. No second model/server or preset change.

## Install / develop

Follow [release/install boundaries](docs/FINAL_RELEASE.md). Verify the ZIP's external SHA256 before extraction; do not overwrite the mixed workspace or replay an old activation. Runtime location is an operator/install decision, not inferred from an old shortcut. Source work is `_workspace/source`; retain `_workspace` / `_archive` outside runtime packaging and data discovery.

Use [locked dependencies and validation](docs/DEPENDENCY_LOCKING.md). CI is `production_mutation_by_ci=false`. Installing code does not authorize deployment, publication, schedule changes or real LINE delivery. Never paste credentials, LINE identifiers, broker data or `.env` contents into logs/issues.
