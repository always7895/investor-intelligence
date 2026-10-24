# Investor Intelligence v2.1.3 R75

[繁體中文](README.zh-TW.md) · [Documentation](docs/README.md) · [Current findings](state/STATUS.md) · [Latest immutable release](https://github.com/always7895/investor-intelligence/releases/latest)

Privacy-first public-market research and evidence-grounded conditional recommendations. No broker execution, guaranteed returns or paid fallback. Source development and an installed application are different acceptance scopes.

## Use and limits

- In current source, `Top20` opens Bottleneck Top20 V3 when its sealed data is fresh. `Top20 文字` opens its text edition; `七欄Top20` selects the legacy seven-field report. Plain `Top20` can fall back to that report when V3 is unavailable. Installed behavior depends on the accepted deployed snapshot.
- Legacy seven-field cards offer one `<ticker> 深度化分析` button, bound to the card's ticker, timestamp, snapshot and report SHA. The older `證據詳情` and `公司文字` commands remain compatible; the detail view is not a complete valuation report. Historical 2Y annualized / 6M returns are **not future price forecasts**.
- Order summaries keep disclosed amounts and recognition windows. RPO, backlog, prepayments, pipeline and revenue are not interchangeable or additive. A filing date is not a delivery date; undisclosed dates stay unknown.
- Future 6/12/24-month price scenarios need sourced operating inputs, financing/dilution and a reproducible valuation bridge; removed hard-coded bull/bear percentages are not restored as evidence ([requirements and audit](docs/RESEARCH_EXECUTION_AUDIT.md)).
- Missing, stale, conflicting or LIMITED evidence stays explicit. Direct public facts and independent thesis support are different evidence levels.

## Development vs released baseline

[STATUS](state/STATUS.md) is the only current defect/acceptance register; older disabled-task, no-deployment or all-zero-defect statements elsewhere never override later recorded evidence. Operator-reported LINE acceptance and publication are dated observations, not new-session verification or authorization. Natural morning/evening schedule acceptance and a newly qualified whole-product release are separate requirements.

The local public collector supports opt-in Fed/SEC/ECB announcements and TWSE/TPEx equity EOD, plus TAIFEX/Alpaca local imports. Access, rights, provenance and LINE publication each need their own gate; daily/indicative data is not executable NBBO ([source coverage](docs/PUBLIC_SOURCE_COVERAGE.md), [options review](docs/OPTIONS_SOURCE_REVIEW.md)).

The EXE candidate has manual model/THINK selection, not qualified automatic best-mode selection. A healthy Router or completed marker is not a research-quality result ([model contract](docs/MODEL_RUNTIME_MIGRATION.md)).

## Released identity (historical 2026-09-06 baseline)

Published/installed source `b5baae936dd3d422583decf9268910ed5783e4d5`; Windows CI [33992169731](https://github.com/always7895/investor-intelligence/actions/runs/33992169731); ZIP SHA256 `320dfb799b34d1220138f67780d2f3fd0004781fcdeaf93e8d543169386f2e69`.

The archive was independently downloaded and verified, and its release-asset attestation passed `gh release verify-asset`. This is **not SLSA workflow build attestation** (unavailable for that workflow), newer-source qualification or today's live market evidence. Each ZIP's own `HOTFIX-REFS.json`, external checksum and adjacent receipts identify its executable source and build run. Full historical observations: `git show 4ba2a606c9e459884e15354aa91798ec432df0ba:README.md` and [delivery history](state/FINAL_DELIVERY_REPORT_R75_FREE_RELAY.md).

## Architecture and authority

```text
LINE -> privacy/admission -> pinned public snapshot -> deterministic Top20
                         -> bounded compact public Q&A
workers.dev -> signed short-lived lease -> TryCloudflare -> Gateway
            -> auto-detected existing loopback model endpoint -> verified served model
```

Serenity is the primary public-method lens. Aschenbrenner's scaling thesis informs V3 industry ranking; his fund's effective 13F weight contributes to industry weight and company lead points. These are ranking inputs, not independent company proof or a permanent AI-sector filter ([V3 formula](docs/BOTTLENECK_TOP20_V3.md)). Public reconstruction is not either author's official formula, private process or current endorsement. The Pi research skill is on-demand; Top20 and compact Q&A do not execute it ([execution audit](docs/RESEARCH_EXECUTION_AUDIT.md)).

Preserve scoring, claim independence, LINE/IBKR separation, freshness and provenance. Publication needs sealed digest-bound objects, readback and pointer-last commit, with replay rejection, durable failure journals, rollback and finalize. Certified `cloud/src/qa.ts` blob: `94184bc8937b413eb327b3d773926db00e22b3b9`. No second model/server or preset change.

## Local runtime independence (development scope)

The LOCAL v213 gateway can run 100% local AI (`$0` paid inference, no cloud fallback) from one runtime config (`config/local-runtime-independence-v1.json`) with strict local-only flags (`LOCAL_AI_ONLY=true`, `PAID_INFERENCE_ALLOWED=false`, `CLOUD_AI_FALLBACK=false`). The decider router is retired in the shipped config (`decision_router.retired: true`): the decision gate uses source qualification alone. Pre-generation guards (source qualification, observed served-context, structured-JSON probe) fail closed to an explicit 503 with no product generation; the natural-prose LINE reply is unchanged. This is a LOCAL-gateway capability, not a Worker change and not a whole-product release. Roles, guards, evidence and PENDING gates: [LOCAL_RUNTIME_INDEPENDENCE](docs/LOCAL_RUNTIME_INDEPENDENCE.md).

## Install and develop

Follow [release/install boundaries](docs/FINAL_RELEASE.md) and [locked dependencies and validation](docs/DEPENDENCY_LOCKING.md). Verify the ZIP's external SHA256 before extraction; do not overwrite the mixed workspace or replay an old activation. The runtime location is an operator/install decision, not inferred from an old shortcut. Source work is `_workspace/source`; keep `_workspace` / `_archive` out of runtime packaging and data discovery.

CI is `production_mutation_by_ci=false`. Installing code does not authorize deployment, publication, schedule changes or real LINE delivery. Never paste credentials, LINE identifiers, broker data or `.env` contents into logs or issues.
