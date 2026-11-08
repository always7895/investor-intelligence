# Security policy

## Supported scope

Only the **currently accepted and independently verified** release, if any, has an actionable release status in [STATUS](state/STATUS.md) and its immutable release receipts. This source branch or a historical ZIP is not automatically a supported Production version. No response-time SLA or continuing support for old releases is promised here.

## Report a vulnerability privately

Use the repository's **private vulnerability reporting** workflow if it is enabled. Otherwise contact the repository maintainers using an existing approved private channel; there is **no verified public security mailbox in this repository**, so none is invented. Do **not** publish credentials, account identifiers, private portfolio/LINE details, exploitable secrets or full proof-of-concept payloads in a public GitHub issue.

Provide the affected source revision, impact, minimal non-secret reproduction and mitigation recommendation. The maintainers review severity, scope and disclosure before remediation/release. Ordinary documentation or behavior questions belong in [SUPPORT](SUPPORT.md).

## Non-negotiable boundaries

LINE and Worker use public-only research data; IBKR is local read-only with no link to LINE, public KV or model context. There is no autonomous trading and no paid API fallback. Real credential changes, KV writes, production schedules, live LINE messages and deployments require **explicit current-session authorization**. Consult [security operations](docs/SECURITY.md) and [privacy policy](docs/PRIVACY_MULTI_TENANT_POLICY.md); this page is guidance, not an execution mandate.
