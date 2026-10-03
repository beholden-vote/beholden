# WO-33 — Publish only what changed

**Lane P · prereq: WO-32 (merged) · read `AGENTS.md`, `docs/workplan/README.md`, and
`docs/DATA-CONTRACTS.md` §8.1 first. §8.1 is normative for this work order.**

## Why this exists

PR #10 taught `publish` to skip an upload when R2 already held identical bytes. In
production it skips almost nothing:

```
publish: 15876/15883 serving (7 unchanged, skipped) + 2158 raw + 2158 latest-pointer
```

The comparison is right and the inputs defeat it. Every dossier embeds a per-run
`generated_at` (`build/dossiers.py:71`) and a per-run `pipeline_version` in every envelope
(`jobs/build.py` `_provenance`; `config.pipeline_version()` reads env `PIPELINE_VERSION`,
which CI sets to `etl-$(date -u +%Y.%W.%H%M)`). No document is ever byte-identical to last
night's, so all ~15,900 are rewritten nightly: about 600k class-A operations a month against
a 1,000,000 free ceiling, before the local tier grows by a single official. Everything else
on the roadmap adds objects. This has to hold first.

## Objective

A served object is rewritten only when its content, **excluding stamps**, changes. After
this lands, a quiet night uploads a few hundred objects, not sixteen thousand.

## The design, and the one thing that must not go wrong

Do **not** change what build writes. Build keeps stamping every document fresh. The change is
in how `publish` decides two objects are "the same":

1. For a `.json` object, compute a **stable digest**: parse it, remove exactly the stamps
   listed in §8.1, serialise canonically (`sort_keys=True`, fixed separators), SHA-256.
   - top-level `generated_at`
   - `pipeline_version` and `retrieved_at` **inside a dict stored under the key `provenance`**
     (at any depth) — nowhere else
   - top-level `as_of`, **only** for keys under `graph/`
2. For any other object, the digest is SHA-256 of the raw bytes.
3. On upload, store the digest as object metadata (`Metadata={"stable-sha256": …}`).
4. Before upload, `HEAD` the object; if its stored digest equals the local one, skip.

Because an unchanged object is never rewritten, it keeps the stamps it had when it last
changed — which is exactly the semantics §8.1 defines.

**The dangerous direction.** A field left out of the digest is a field whose changes are
never published. For a stamp that is the point; for a fact it is silent staleness, the
failure rule #2 exists to prevent. So:

- The stamp list is closed and narrow. Match `provenance` envelopes structurally, not by
  searching for key names anywhere — a fact field that happens to be called `retrieved_at`
  or `as_of` somewhere else (an ideology score's `as_of` is a real date) **stays in**.
- Keep the existing fail-open rule: any HEAD error, a missing object, missing metadata, a
  body that does not parse as JSON — all upload. Skipping is only ever the answer when the
  digests positively match.
- `--force-all` still writes everything, and a `full_rebuild` dispatch still passes it.

The first run after deploy finds no stored digests and rewrites everything once. That is
expected; the **second** run is the proof.

## Also in scope

**Deterministic ordering.** `_current_holders` (`jobs/build.py`) has no `ORDER BY` and drives
pin order and style-feed key order; the `recent_bills` query in `_legislative_stats` has no
outer `ORDER BY`. Add stable orderings so the index files stop churning on row order alone.

**`raw/latest/` mirror.** `_copy_batch_to_latest` issues a server-side copy for every raw
file every night. Skip the copy when `raw/latest/<key>` already holds the same bytes (compare
ETag to the local MD5 — raw files are single-part). The dated partition `raw/{date}/…` is the
reproducibility record and is **not** changed here.

**Stale objects.** `publish` never deletes, so an official who left office is still served as
an incumbent. After a successful serving upload, list the bucket under each **managed
prefix** and delete keys the current build did not produce.
- Managed = a top-level directory that exists under the local serving root (`dossiers/`,
  `graph/`, `pins/`, …). Never `raw/`, `tiles/`, `fonts/` — hard-code that refusal as well as
  deriving the managed set, so a future artifact named badly cannot widen it.
- Tripwire: if the stale set under any prefix exceeds `max(25, 2% of that prefix)`, **raise**
  and delete nothing, unless `--allow-mass-delete` is passed. A bug in build must not be able
  to empty the bucket.
- Dry-run prints what would be deleted.

**Write budget line.** Count class-A operations per run (PUT, COPY, LIST) and print
`publish: class-A this run = N (≈ N×30 per month of 1,000,000 free)`. Emit a GitHub
`::warning::` when the projection passes 700,000. Raise before writing anything if a single
run would exceed 200,000 writes without `--force-all` or `--allow-bulk-writes` — at that size
it is a bug, not a release.

**What the reader is told.** With stamps now meaning "last changed", the UI must stop
presenting the envelope date as the time of the last check.
- `web/src/lib/data.ts`: a memoised `loadCoverage()` for `/coverage.json`.
- `web/src/ui/bits.tsx` (the provenance line, near `:71`): render
  **"checked ‹coverage.sources[source].retrieved_at› · unchanged since ‹envelope date›"**;
  when coverage is unavailable, render **"unchanged since ‹envelope date›"** — never the
  envelope date alone under a "fetched"/"retrieved" label.
- `web/src/ui/DossierView.tsx` (footer, near `:540`): "Last changed ‹generated_at›".
- Any copy on the Methodology or Sources overlays that describes these dates.

## Files

**OWNED** — `pipelines/beholden_etl/jobs/publish.py` · new
`pipelines/tests/test_publish_stability.py`

**SHARED — smallest possible diff, at the points named above** —
`pipelines/beholden_etl/jobs/build.py` (the two `ORDER BY`s only) ·
`pipelines/tests/test_pipeline.py` (the existing publish tests and `_FakeR2`, which assert
the old ETag semantics) · `.github/workflows/etl-nightly.yml` · `web/src/lib/data.ts` ·
`web/src/ui/bits.tsx` (provenance line only — `HeaderActions` in the same file belongs to
WO-35) · `web/src/ui/DossierView.tsx` (footer only) · `docs/DATA-CONTRACTS.md` §8.1 status ·
`docs/ARCHITECTURE.md` (the write budget, corrected)

## Acceptance

Tests, in the new file:
1. Two builds of the same warehouse under different `PIPELINE_VERSION` values and different
   clock times produce **different bytes and the same stable digest** for every dossier and
   graph document.
2. Changing one fact changes the digest.
3. Changing **only** a fact-bearing date outside an envelope changes the digest; changing
   only an envelope's `retrieved_at` does not.
4. Against a fake client that stores metadata: a second publish of an unchanged tree uploads
   nothing; an object with no stored digest uploads; a HEAD error uploads.
5. Stale deletion removes only managed-prefix keys absent locally, never touches
   `raw/`, `tiles/`, `fonts/`, and raises past the tripwire.
6. Two builds of the same warehouse produce byte-identical `pins/*.json`,
   `stylefeeds/*.json` and `search/people.json`.

Gates: `PYTHONPATH=pipelines python -m pytest pipelines/tests -q` ·
`python -m ruff check pipelines/` · `cd web && npm run build`.

Live (run by the integrator after merge): two consecutive nightlies. The first rewrites
everything; the **second** must report well under 1,000 serving uploads. Until that line is
seen, this work order is not done — the previous attempt was declared finished on unit tests
alone and was wrong.

## Out of scope

Changing what build stamps or how `pipeline_version` is derived · de-duplicating the dated
raw partition (worth doing — note the numbers you observe as a follow-on) · keying person ids
on the person rather than the seat, and dropping edge-free graph documents (both WO-22b) ·
anything under `web/src/ui/` beyond the three label changes above.
