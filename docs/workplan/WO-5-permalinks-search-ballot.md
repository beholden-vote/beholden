# WO-5 — Permalinks, people search, "My ballot"

**Lane F, AFTER WO-2 merges · read `docs/workplan/README.md` + `AGENTS.md` first**

## Objective
Make Beholden shareable and navigable: hash routes for people/divisions, name search, and a
"My ballot" card after locating.

## Features
1. **Permalinks (hash routing, zero-server):**
   - `#/p/{person_id}` → open that dossier (fetch directly; fly map to their division via the
     pin index once loaded).
   - `#/d/{ocd_id}` → select that division: fly to it and open the stack panel for its point
     (use the division's rendered polygon; a small static centroid index may be emitted by the
     pipeline if needed — see Files).
   - Existing `#about|#privacy|#sources` keep working (they're flat hashes; route only `#/`-
     prefixed paths). Update `location.hash` as the user opens dossiers (replaceState — no
     history spam). Escape/close clears to `#`.
2. **People search:** extend the existing topbar search — if the query doesn't look like an
   address (heuristic: no digits) OR after address search finds nothing, search a static name
   index with `minisearch` (already a dependency). Pipeline emits
   `dist/data/search/people.json`: `[{person_id, full_name, office, party, ocd_id}]` for all
   7,928 — ~500KB raw, acceptable lazy-loaded on first keystroke; suggestions dropdown reuses
   `.suggest` styles, grouped Addresses / People.
3. **"My ballot" view:** after geolocate/address selection, panel header offers
   "Your ballot ↗": the stack rendered as one ordered card (Federal → State → …), each row
   linking to its dossier permalink. Copy-link button (`#/d/{smallest-division}`).

## Files
- OWNED: NEW `web/src/router.ts`, NEW `web/src/ui/Ballot.tsx`, `web/src/ui/App.tsx`
  (routing glue, search extension — coordinate: this lane owns App.tsx),
  `web/src/lib/data.ts` (people-index loader), `web/src/styles.css` (additions).
- SHARED (marked insertion): `pipelines/beholden_etl/jobs/build.py` — emit
  `search/people.json` (+ optionally `search/centroids.json` `{ocd_id:[lng,lat]}` computed
  from pins or tile bounds; if centroids are non-trivial, `#/d/` may resolve via the first
  pin's division and fly to the *person's* location instead — document the choice),
  `tests/test_pipeline.py` (index emission test).

## Constraints
- Keep main-chunk growth minimal: lazy-load minisearch + the index on first people-query.
- Design per `web/DESIGN.md`; every new user-facing string symmetric and product-specific.
- `npm run build` green.

## Acceptance
- Local: `#/p/{known-id}` deep-link opens the dossier on load; name query shows grouped
  suggestions; picking a person opens dossier + updates hash; ballot view lists all levels
  at a point with working permalinks.
- Live: a shared `beholden.vote/#/p/{id}` link opens straight to the dossier.

## Out of scope
Server-side rendering/OG preview images (note as follow-on), fuzzy nickname matching.
