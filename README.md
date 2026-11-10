# Investor Intelligence

[繁體中文](README.zh-TW.md) · [Documentation](docs/README.md) · [Changelog](CHANGELOG.md) · [Current source and release status](state/STATUS.md) · [Support](SUPPORT.md)

Privacy-first public-market research with evidence-gated, indicative LINE views. It helps compare bottleneck industries, issuers, disclosed orders, historical returns and conditional revenue/price scenarios. It does **not** execute broker trades, expose a private portfolio in LINE, guarantee returns or buy paid data when a free source fails.

## What the project provides

- Python collectors and source-validation/ranking gates (`scripts/`), a Cloudflare Worker LINE response layer (`cloud/`), and Windows local runtime/install tooling (`launcher/`, root PowerShell scripts).
- `Top20` prefers the fresh, sealed Bottleneck Top20 v3 and falls back to the legacy seven-field view where the reader allows. `瓶頸詳情 代號` looks up an **admitted** v3 Top20 issuer; an excluded company is not a ranked company. `產業爆發榜` shows the layer analysis. Actual deployed behavior depends on the accepted snapshot.
- Research separates a company's published facts from social-media/source views, backlog from revenue, shareholders' returns from operating growth and source publication date from market price time. Unsupported facts stay missing, never zero.
- Serenity is a public research *lens*, and Leopold Aschenbrenner a contextual scaling/13F input, not a proprietary formula, endorsement or primary proof of orders.

## Get started — development only

Prerequisites: 64-bit CPython **3.12.10** for locked Python acceptance, Node.js **>=20** for the Worker, Git and PowerShell on the relevant Windows workflows. See [dependency/validation instructions](docs/DEPENDENCY_LOCKING.md) before using any installer.

From the cloned source root (diagnostic smoke check; this is not Production or a release qualification):

```powershell
$env:PYTHONUTF8 = '1'
python scripts/security_check.py
python scripts/documentation_boundary_gate.py
python scripts/documentation_structure_gate.py
python scripts/workflow_supply_chain_gate.py
```

For the hash-locked Python test interpreter and full offline suite, use [DEPENDENCY_LOCKING](docs/DEPENDENCY_LOCKING.md). For the Worker, run `npm ci --ignore-scripts --no-audit --no-fund`, `npm run typecheck` and `npm test` **from `cloud/`**. No command here deploys, publishes snapshots, registers schedules or sends a real LINE message.

## Delivery status and required follow-through

Consult [current acceptance and open gates](state/STATUS.md) and [dated source changes](CHANGELOG.md); neither the checked-out source nor historical release notes prove a downloadable or deployed artifact.

## Release, safety and help

The source revision is not an installed or released artifact. [STATUS](state/STATUS.md) records what is currently verified, any last *recorded* Production observation and the next acceptance action. A release requires immutable source-bound evidence, verified ZIP/checksums, an independent reviewer and separate operator authorization; see [release/install boundaries](docs/FINAL_RELEASE.md).

Security/privacy: LINE is public-input only; IBKR is **local read-only** and never feeds shared Worker/LINE/public KV; no owner IDs, account details, credentials or paid fallback. For routine questions open a [GitHub issue](SUPPORT.md) if the repository enables issues; for vulnerabilities see [SECURITY](SECURITY.md), never a public credential disclosure.

Maintained through this repository's reviewed maintainer workflow. Contribution rules: [CONTRIBUTING](CONTRIBUTING.md); conduct: [CODE_OF_CONDUCT](CODE_OF_CONDUCT.md). The [documentation index](docs/README.md) links detailed contracts and historical evidence without presenting them as live authority.
