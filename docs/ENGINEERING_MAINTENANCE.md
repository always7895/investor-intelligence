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

## Synthetic output isolation

The legacy v2.1/v2.1.1 engine tests previously wrote synthetic records to the checkout's default public cache/report paths. A passing regression run did not make those files usable research inputs. Current observations and preserved hashes belong in [STATUS](../state/STATUS.md); do not silently relabel, publish or restore fabricated market snapshots.

- `--self-test` uses an owned temporary output directory, without mutating module path globals.
- Explicit synthetic runs require `--synthetic --output-root <owned-fixture-directory>`; missing or default public/report destinations are refused before providers/writes. The output override is not accepted for live runs. The v213 progress CLI forwards this same contract.
- The retained coverage wrapper forwards the output root and checks the returned plan path against the independently resolved destination before reading/writing it. It must not accidentally update the default source plan.
- Tests execute the actual CLI parsers with child-process defaults redirected to sentinel fixtures, so a failing test cannot corrupt the actual checkout. Scoring/discovery calculations and live default destinations are unchanged; no wrapper is deleted.
- This is bounded output isolation, not a general filesystem or network sandbox. `run_offline_tests.py` is not a network sandbox either. Keep publication gates and source-bound live acceptance separate.
