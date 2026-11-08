# Official documentation sources / 官方指南來源

**Checked 2026-11-08 (UTC+08).** The following are external design/reference authorities; they are not proof that a project feature is live. Repo-specific code, policy and the bounded [current ledger](../state/STATUS.md) are authoritative for actual behavior.

| Topic | Official source | Applied here |
| --- | --- | --- |
| README and relative links | [GitHub About READMEs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes) | Short [human overview](../README.md); link to deeper pages rather than copying status tables |
| Community health | [GitHub healthy contributions](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions) | [CONTRIBUTING](../CONTRIBUTING.md), [SUPPORT](../SUPPORT.md), [CODE_OF_CONDUCT](../CODE_OF_CONDUCT.md) |
| Security disclosure | [GitHub security policy](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/add-security-policy) | [SECURITY](../SECURITY.md); no invented contact address, do not put vulnerabilities in public issues |
| Issue / PR templates | [GitHub templates](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/about-issue-and-pull-request-templates) | [Issue template](../.github/ISSUE_TEMPLATE/bug_report.md) and [PR template](../.github/PULL_REQUEST_TEMPLATE.md); GitHub activates them only when on the default branch |
| Coding agent instructions | [AGENTS.md](https://agents.md/) | Concise [AGENTS](../AGENTS.md) with repository-specific commands, coding rules, tests and permission boundaries |
| Claude Code memory/imports | [Anthropic Claude Code](https://code.claude.com/docs/en/memory) | [CLAUDE.md](../CLAUDE.md) imports `@AGENTS.md`; no duplicate instructions or reliance on unspecified agent runtime |
| LINE Flex / fallback | [Flex guide](https://developers.line.biz/en/docs/messaging-api/using-flex-messages/), [API reference](https://developers.line.biz/en/reference/messaging-api/) | `altText` is required. Official reference permits up to 1500 characters; `cloud/src/line-messages.ts` intentionally enforces a **stricter 400 UTF-16-unit** local cap, five bubbles per carousel and bounded bytes |
| LINE quick replies | [Quick reply guide](https://developers.line.biz/en/docs/messaging-api/using-quick-reply/) | Official platform permits up to 13 quick-reply buttons; this is a platform rule, not a claim that this repository sends 13 |
| LINE rich menus | [Rich menus overview](https://developers.line.biz/en/docs/messaging-api/rich-menus-overview/) | Rich menus are not shown in LINE for PC; source command menus are separate from a claim that a rich menu was installed |

## Validation practice

Before asserting a behavior, locate the exact source implementation and guard; distinguish official API maxima from this product's stricter local validator. This work did not send to LINE, run Worker/KV, install rich menus, use private data, or authorize Production.

- `cloud/src/line-messages.ts` validates Flex message alt text, bubble size and carousel bounds; `cloud/src/v213/line-theme.ts` uses a smaller packaging byte budget.
- `config/runtime-policy.json` gates public-only, direct-chat/allowlist and free-only behavior in source; the installed configuration is a separate verification task.
- `scripts/documentation_structure_gate.py` checks paths and budgets but not external content validity, semantics or actual deployment. Do not treat a link PASS as a live integration test.
