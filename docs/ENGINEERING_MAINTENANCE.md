# Engineering documentation and maintenance / 工程文件維護

> **Check:** Source, reviewed patch and installed artifacts are different snapshots; verify separately.

**Source of truth:** the executable code and reviewed configuration at a fixed commit. [STATUS](../state/STATUS.md) is the only current acceptance/defect/next-action ledger; [docs/README](README.md) lists technical contracts. Dated claims in older documents are historical, not permission to run them.

## How to edit

1. Keep [README](../README.md) for what, why, setup, support and maintainers; keep [AGENTS](../AGENTS.md) for exact coding-agent commands/boundaries; [CLAUDE](../CLAUDE.md) imports the shared instructions.
2. Put multi-step procedures in topic docs and on-demand methodology in [SKILL](../skills/serenity-public-research/SKILL.md) with its own front matter. Do not repeat technical thresholds in multiple entrypoints.
3. Preserve normative identifiers (LINE/privacy, IBKR, cost), reviewed sources, unknown/fail-closed semantics and exact test pins. Migrate a link only after locating all code/CI/manifest references.
4. For every new Markdown, add a link to [docs/README](README.md); run `scripts/documentation_structure_gate.py` and `scripts/documentation_boundary_gate.py`. A link check does not verify external URLs or current factual claims.
5. Source maintenance is **not** permission to install, delete an archive, register a task, push, publish KV, send LINE or change model settings.

## Official design and platform references

- [GitHub README guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes) and [healthy contribution files](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions).
- [AGENTS.md format](https://agents.md/) and [Claude Code instruction memory and imports](https://code.claude.com/docs/en/memory).
- [LINE Messaging API reference](https://developers.line.biz/en/reference/messaging-api/) and [Flex layout guidance](https://developers.line.biz/en/docs/messaging-api/using-flex-messages/). The product's own limits can be **stricter** than LINE's published maxima.

See [the detailed official-guide mapping](README.md) and [worktree deletion safeguards](WORKSPACE_MAINTENANCE.md).
