# Engineering maintenance / 精簡依據

Reviewed 2026-09-12. These are engineering recommendations, not new investment facts or deployment authority.

| Direct source | Applicable guidance | Decision here |
| --- | --- | --- |
| [Diátaxis](https://diataxis.fr/) | Separate tutorials, how-to guides, technical reference and explanation by reader need | Short entrypoints; one current STATUS; preserve technical contracts and historical evidence |
| [npm ci](https://docs.npmjs.com/cli/v11/commands/npm-ci/) | Frozen lock install; existing node_modules removed; ignore-scripts does not prevent explicit test/run commands | Keep exact locks and existing install flags; correct stale documentation, no package upgrades |
| [GitHub required checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks) | Workflow path/branch skips can leave required checks Pending | No blind paths-ignore or deletion of required checks; retain existing R75 lane |

## Scope and measurements

The source inventory initially contained 92 tracked Markdown files. The largest historical handoff plan was 120396 bytes; STATUS was 12122 bytes, exceeding its tested 12000-byte limit. Before/after measurements and executed checks belong in [STATUS](../state/STATUS.md), not permanent performance claims.

The offline [documentation structure gate](../scripts/documentation_structure_gate.py) inventories Git Markdown, checks local inline/reference-style file links and entrypoint sizes, and requires every page in [the index](README.md). It adds no packages or network calls. External URL availability, heading anchors, HTML and factual accuracy require separate review; link PASS is not semantic certification. Existing privacy/documentation gates remain intact.

Do not simplify away per-order values, dates, evidence, negative cases or required future scenario horizons. [Research execution audit](RESEARCH_EXECUTION_AUDIT.md) distinguishes genuine lost fields from removed unsourced constants. Historical narratives may become bounded summaries linked to immutable Git history; evidence JSON, receipts, locks, wrappers and schemas are not deleted.

No disk cleanup, package install/update, model change, new workflow, production mutation or paid fallback is part of this source cleanup. The existing unrelated untracked installer inputs are retained.
