# Rollback jars (local only)

`pointer-<run>.before-honesty-backup.raw.json` = exact production snapshot:current body captured
IMMEDIATELY before the evidence-honesty re-point session (2026-09-16).
Restore procedure: OVERRIDE_ONLY LaneR sync the body to snapshot:current (pointer only);
verify reader replay of that run before and after. Never write objects out of band.
