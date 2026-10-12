# WO-41 — Keep the raw lake inside the free tier

**Lane P · prereq: WO-33 (merged) · read `AGENTS.md`, `docs/workplan/README.md`,
`docs/ARCHITECTURE.md` §5.1, `pipelines/beholden_etl/rawlake.py` and
`pipelines/beholden_etl/jobs/publish.py` first.**

## Why this exists

Every nightly writes about 80 MB of dated raw snapshots to `raw/` (about 2.4 GB a month, never
pruned) against R2's 10 GB free tier, and uploads ~3,600 raw objects (class-A) each night even
when nothing changed. At this rate storage is exhausted in a few months and the nightly's
write count is dominated by raw objects, not by anything readers see.

## Objective

1. **Measure first.** Report current `raw/` size, object count, per-source breakdown, and how
   much is byte-identical to the previous night's snapshot (list R2 with the existing client;
   read-only). Put the numbers in the PR.
2. **Do not re-upload unchanged raw files.** A raw object whose content hash matches the object
   already stored is skipped (same idea as WO-33's stamp-insensitive digest, but raw bytes are
   already immutable, so a plain content hash in object metadata is enough). Target: class-A
   writes for raw drop to near the number of genuinely new files.
3. **Retention for dated snapshots.** Keep `raw/latest/` (the hydration source) untouched.
   For dated snapshots keep the last N nights (default 14) plus one per month, delete older ones
   with a capped, logged, dry-run-first pass. `NEVER_DELETE` (`raw/` is protected today) must
   be changed deliberately and narrowly: only the dated snapshot prefix, only via this retention
   pass, never `raw/latest/`, never `tiles/`, never `fonts/`.
4. **Safety.** The pass refuses to run if `raw/latest/` is missing or smaller than the previous
   run's manifest count, deletes at most a fixed number of objects per run (log when capped), and
   prints every prefix it would delete before deleting. First merge ships it in **dry-run only**
   (listing, no deletes); a second, one-line PR flips it on after the owner has read one
   night's listing.

## Files

**OWNED** — new `pipelines/beholden_etl/jobs/retention.py` · new `pipelines/tests/test_retention.py`

**SHARED — marked insertion points only** — `pipelines/beholden_etl/rawlake.py` (the skip-
unchanged upload only) · `pipelines/beholden_etl/jobs/publish.py` (call the retention pass;
`NEVER_DELETE` narrowing) · `.github/workflows/etl-nightly.yml` (one flag, dry-run by default) ·
`docs/ARCHITECTURE.md` (storage-budget paragraph) · `docs/DATA-CONTRACTS.md` only if layout is
documented there

## Constraints

- Fail closed: any doubt (listing error, count mismatch, unexpected prefix) means no delete.
- No production access beyond read-only listing during development; tests are offline against a
  fake client. Never use or print credentials; tests must not see R2 variables (conftest strips
  them).
- Must not change what readers can see: serving objects untouched.
- State the projected class-A and storage numbers before/after in the PR.

## Acceptance

Gates green; tests cover skip-unchanged, retention windows, the never-delete guards, the cap,
and the missing-latest refusal; PR body carries the measurements; dry-run output demonstrated
on a fake bucket.

## Out of scope

Serving-object deletion (WO-33) · changing hydration · moving the lake off R2.
