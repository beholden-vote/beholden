# WO-32 — Contracts and rails for the local / votes / reader-flow round

**Integrator lane · merged**

## Why this exists

The round that follows runs up to five lanes at once. Left as it was, the repo funnels every
one of them through the same three places: `jobs/build.run()` (one hand-wired block per
artifact), the 3,300-line `pipelines/tests/test_pipeline.py` (every test appended to the
end), and an unwritten idea of what each new artifact looks like. Five branches editing the
same forty lines is five merge conflicts and no contract.

## What it shipped

- **`docs/DATA-CONTRACTS.md` §8** — the v1.1 additions: what a stamp is and what "unchanged"
  means (§8.1), `term_ends` on pins (§8.2), the votes / roll-call / bill artifacts (§8.3),
  area facts (§8.4), place tiles (§8.5), and the client route table and history rules
  (§8.6). Each subsection names the work order that ships it and is normative for it.
- **`beholden_etl/build/context.py` + `jobs/build.ARTIFACT_WRITERS`** — a writer is a module
  with `publish(ctx)`, registered by one line. It gets build's own provenance factory through
  the context, so a new artifact cannot hand-assemble an envelope around rule #1.
- **`pipelines/tests/conftest.py`** — re-exports the `slice_dirs` and `local_dirs` fixtures,
  so each lane's tests live in their own file.
- **`term_ends` on every pin** — additive; lets a list of officials say when a term ends
  without opening each dossier.
- **Work-order files** for the wave that follows. WO-17 through WO-28 were executed from
  roadmap bullets alone and never had one; an agent starting cold had nothing to read.

## Not in it

Any behaviour a reader can see, other than nothing: `term_ends` is published but not yet
rendered (WO-35).
