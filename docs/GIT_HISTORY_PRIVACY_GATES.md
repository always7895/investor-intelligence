# Git-history privacy gates

The repository deliberately separates two different operations.

## Non-destructive inventory

`full-history-privacy-inventory.yml` runs automatically for the active hardening branch and pull request. It scans the available refs, records only stable finding codes, object prefixes and one-way locator hashes, and never prints matched content, paths or e-mail addresses.

The inventory is allowed to complete when remediation is still required. A non-clean inventory must keep `release_ready=false` and the history-remediation release gate outside `PASS`. It does not rewrite history, force-push or rotate credentials.

## Final clean release gate

`full-history-clean-release-gate.yml` is manual and exact-SHA-bound. It is the only workflow that invokes the scanner with `--require-clean`. It should run only after an offline backup and explicit owner approval for any required destructive history remediation.

A clean history result is necessary but not sufficient for release. It does not update release status, deploy services, admit LINE users, install credentials or enable billing.

## Privacy of evidence

Both modes are required to keep these values false:

- `matched_content_in_report`
- `raw_paths_in_report`
- `raw_email_addresses_in_report`

Reports are ephemeral and removed from the self-hosted runner after the workflow step.
