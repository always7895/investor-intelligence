# task0-phase1d fixture — sealed snapshot (byte-identical copy)

Source: local acceptance run `state/v213-snapshots/20260917T092410Z-d9f86bda2053/`
(accepted 2026-09-17, ChatGPT Pro signed; run bound to pointer last).

- `objects.json` — 15 sealed object bodies (core 13 + `v213:macro-industry:latest` + seal manifest), copied byte-identical.
  SHA-256 `5f775cdd52198594cdff0b121f4daf5278db5ca35e8159574a9d640e5b6ce4b5` (18625 bytes)
- `pointer.raw.json` — sealed pointer (run `20260917T092410Z-d9f86bda2053`, seal `891b671a`, public_data_as_of 2026-09-17T09:24:10Z), copied byte-identical.
  SHA-256 `8d3125b9a668f226249e23baab6a725c92057ccc6c09322c5665d918d5554e0f` (339 bytes)

Nature: this is a DIFF fixture of an EXISTING sealed snapshot (byte-identical copy of the acceptance run). It is not a snapshot publication, not evidence of runtime liveness; freshness is simulated by the deterministic clock in the consumer tests only.
The production `state/v213-snapshots/` directory itself remains uncommitted (ignored); this fixture dir is the only committed copy and must not be replaced by snapshot-dir commits.

## BATCH05 synthetic fresh acquisition (2026-10-07)

`fresh-objects.json` and `fresh-pointer.raw.json` are separate TEST-ONLY fixtures, generated through
`publish_sealed_snapshot.main` by `tests/test_batch05_task0_fixture.py` inside the offline H5 gate.
The synthetic acquisition is 2026-09-17T09:00:00Z; assembly is 09:24:10Z; the consumer clock is
10:24:10Z. The producer computes all activation digests, the seal and the pointer (no hand-edited digests).
Macro/deep-report input boundaries reuse the original fixture; no ambient cache, network or live data is admitted.
These clocks are invented test inputs, not new evidence for the historical GEV/6501 corpus.

- `fresh-objects.json`: SHA256 `4f218e1329adc348ea3dbb53f90ed11bb578b9a2f8d591c3aeb5ddb9086af093`, 18645 bytes.
- `fresh-pointer.raw.json`: SHA256 `71a9df09be8a8b243e109b6abc1cecda504ff662d7c166ce228a5a6f480831aa`, 339 bytes.

The original two files above remain byte-identical. Their row age is computed directly from the UTC strings:
(2026-09-17T10:24:10Z - 2026-09-15T11:00:00Z) / 1 h = 47.4027778 h (> 14 h);
the formal dispatcher negative now requires Top20 refusal while Macro still completes. The positive
keeps its original no-lease Top20/Macro intent with rows inside the documented 14 h bound.
This tests a user-visible refusal change; it is not Production rollout or live recertification.