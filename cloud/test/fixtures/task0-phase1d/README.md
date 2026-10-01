# task0-phase1d fixture — sealed snapshot (byte-identical copy)

Source: local acceptance run `state/v213-snapshots/20260917T092410Z-d9f86bda2053/`
(accepted 2026-09-17, ChatGPT Pro signed; run bound to pointer last).

- `objects.json` — 15 sealed object bodies (core 13 + `v213:macro-industry:latest` + seal manifest), copied byte-identical.
  SHA-256 `5f775cdd52198594cdff0b121f4daf5278db5ca35e8159574a9d640e5b6ce4b5` (18625 bytes)
- `pointer.raw.json` — sealed pointer (run `20260917T092410Z-d9f86bda2053`, seal `891b671a`, public_data_as_of 2026-09-17T09:24:10Z), copied byte-identical.
  SHA-256 `8d3125b9a668f226249e23baab6a725c92057ccc6c09322c5665d918d5554e0f` (339 bytes)

Nature: this is a DIFF fixture of an EXISTING sealed snapshot (byte-identical copy of the acceptance run). It is not a snapshot publication, not evidence of runtime liveness; freshness is simulated by the deterministic clock in the consumer tests only.
The production `state/v213-snapshots/` directory itself remains uncommitted (ignored); this fixture dir is the only committed copy and must not be replaced by snapshot-dir commits.