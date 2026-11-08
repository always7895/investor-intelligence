# Contributing

This repository is maintained through reviewed, bounded changes. An issue or PR is a proposal, **not** approval to deploy, access credentials or send messages.

## Before a change

- Read [README](README.md), [AGENTS](AGENTS.md), [current status](state/STATUS.md) and the relevant topic in [docs](docs/README.md).
- For a bug or a documentation correction, supply a reproducible, **sanitized** example, the expected behavior and the source/code line that supports it. Never share actual LINE IDs, portfolio/broker data, .env contents, secret-bearing logs, private messages or paid-source text.
- Open a GitHub issue if issue creation is enabled and you have access. For vulnerabilities follow [SECURITY](SECURITY.md), **not** a public issue.

## Implement and check

Keep changes small and branch-scoped. Python checks, boundaries and Worker scripts are listed with exact commands in [AGENTS](AGENTS.md) and [dependency locking](docs/DEPENDENCY_LOCKING.md). All new Markdown must be linked from [docs/README.md](docs/README.md) and pass both documentation gates.

Use Conventional Commits (e.g. `docs(scope): clarify operator workflow`). PR description should say what changed, what code establishes the claim, tests run including their exit codes, unknowns, risk, and a non-Production rollback plan. State explicitly if no live test was authorized. Do not delete historical evidence without a path-reference and required-tests review.

## Maintainer review

A reviewer may accept or request changes; publication and Production mutation are separately authorized. No PR or GitHub Actions PASS alone promises a release, data rights, a live market feed or an executed trade.
