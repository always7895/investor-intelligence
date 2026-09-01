# H5 source-time precision boundary

The direct public X pages used to seed the append-only Serenity source-history
expose dates and UI clock times, but the development retrieval surface does not
provide a trustworthy UTC offset for those displayed times.

H5 therefore **must not invent UTC timestamps**.

The H5 v2 entrypoint stores:

- `published_at`: ISO date only (`YYYY-MM-DD`);
- `time_precision`: `DATE_ONLY`.

The direct source URL and date remain attributable, while the unavailable timezone
precision is represented honestly.

This correction does not change any factual company evidence, dependency role,
Production ranking or Worker behavior.  It only hardens the provenance semantics
of the shadow source-history file.
