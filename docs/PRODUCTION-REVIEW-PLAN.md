# Production Readiness Review & Plan — 2026-07-04

Graphify-assisted comprehensive review of the codebase ahead of the first
production build. Graph inputs: `graphify-out/GRAPH_REPORT.md` (284 nodes /
326 edges / 34 communities), god-node and knowledge-gap analysis; every flagged
community was then read in full. Status legend: ☑ fixed in this pass · ☐ follow-up.

## A. Review method
1. Rebuilt the knowledge graph (AST + semantic) and used its communities as the
   review checklist — every pipeline community (Fetch & Publish Jobs, Dossier
   Builder, Transform & OCD Divisions, DuckDB Store, Legislators Crosswalk,
   Congress.gov API Client, Web Map Frontend) was read end-to-end.
2. Graph "surprising connections" (`etl-nightly --implements--> Rule: Fail
   Closed`) were treated as invariants and each implementation audited against
   the rule it claims to implement. That audit is what surfaced findings 1–3.
3. Verification gates: `pytest` (offline suite), `ruff check`, `npm run build`.

## B. Findings & fixes

### Provenance & freshness (rule #1 / #2 violations — the serious ones)
1. ☑ **CI never sets `PIPELINE_VERSION`.** `etl-nightly.yml` tags the release
   *after* publish but never exports the tag during build, so every production
   dossier ships `pipeline_version: dev-0.1.0` — untraceable provenance.
   **Fix:** compute the version into `$GITHUB_ENV` before build; tag the same
   value after publish.
2. ☑ **Fabricated `retrieved_at`.** `build.py::_provenance` falls back to
   `_now()` when the manifest lacks a source — stamping a retrieval that never
   happened. **Fix:** fail closed (`ProvenanceError`) when the manifest can't
   vouch for a source; test fixture now writes a real manifest like fetch does.
3. ☑ **Wrong `computed_as_of` on ideology scores.** Real Voteview CSVs carry no
   `congress_end_date` column, so the fallback *always* fired and stamped the
   congress **start** (2025-01-03) as the as-of date. **Fix:** transform passes
   the manifest's `retrieved_at` (the honest as-of for a continuously updated
   score); boundary fallback corrected start → end of congress. Fixture updated
   to mirror real Voteview columns.
4. ☑ **Raw lake never landed in R2.** Architecture §3 promises raw snapshots →
   `r2://…/raw/{date}/{source}/…` (immutable, reproducible); fetch only wrote
   locally. **Fix:** publish stage now uploads `dist/raw` under an immutable
   `raw/{YYYY-MM-DD}/` prefix (long-lived cache headers), dry-run aware.

### Robustness (nightly job survives the real internet)
5. ☑ **No retries on legislators/Voteview fetches** — a transient reset kills
   the nightly. **Fix:** tenacity retry (exponential backoff) on both.
6. ☑ **congress.gov client gaps:** tenacity retried only `HTTPStatusError`
   (transport errors/timeouts un-retried); 429 ignored `Retry-After`;
   `sort="updateDate+desc"` URL-encodes `+` as `%2B` (literal plus — wrong
   query); missing API key raised a bare `KeyError`. All four fixed.
7. ☑ **Blank/malformed ICPSR row crashed transform** (`int(float(""))`).
   Now skipped and counted; the spine-resolution gate still fails closed on
   systemic gaps — a single junk row is a data gap, not an outage.
8. ☑ **Hardcoded `_CONGRESS_START`** in transform — now derived from
   `config.CONGRESS` so a congress bump can't drift.
8b. ☑ **Voteview CSV read/written with platform-default encoding** — bionames
    carry accents; cp1252 (Windows local runs) would corrupt or crash. Both
    sides now explicit UTF-8.
9. ☑ **Overlapping runs:** nightly + intra-day crons could race a publish.
   **Fix:** workflow-level `concurrency` group, no cancel-in-progress.

### Data quality visibility
10. ☑ **coverage.json now computes freshness**: per-source `age_hours` and
    `within_sla` (SETUP §6 checklist expects "all sources within SLA" to be
    checkable from the dashboard JSON — previously it only echoed timestamps).
11. ☑ **Dossier validator tightened:** provenance keys must be present *and*
    truthy (a `retrieved_at: null` previously validated).

### Hygiene
12. ☑ ruff: 3 × E401 (multi-imports) in `legislators.py` / `voteview.py`.
13. ☑ Web bundle was a single 1.08 MB chunk; `manualChunks` now splits
    maplibre-gl vendor code for cacheability and faster TTI (PRD: map <2s).
14. ☑ Stale comment in `etl-nightly.yml` ("small files -> Pages deploy dir")
    aligned with the implementation (all serving JSON → R2).

## C. Verification gates (all must pass before push)
- [x] `pytest pipelines/tests` — including 2 new tests: build-time provenance
      fail-closed; coverage SLA computation.
- [x] `ruff check pipelines` — clean.
- [x] `cd web && npm run build` — clean, chunked.
- [x] graphify graph refreshed (`--update`) so the committed graph matches HEAD.

## D. Release steps
1. Commit in logical units (docs/graph · etl fixes · web · ci), project
   identity per CONTRIBUTING.
2. Push to `origin/main`.
3. Post-push (operator, not automatable here): trigger `tiles-build` once per
   vintage, then `etl-nightly` via workflow_dispatch; verify SETUP §6 checklist.

## E. Follow-ups (out of scope for this pass)
- ☑ *(2026-07-04, later same day)* **E7 dossier UI shipped**: hover/click →
  representation stack → full cited dossier panel (identity, tenure, lean
  scale w/ medians, legislative, provenance footers). Money + vote sections
  render automatically when their pipelines publish; stub data shows honest
  "syncing" states, never fabricated zeros. Pins feed enriched with
  full_name/office/chamber/vacant so the map labels without dossier fan-out.
- ☐ E2 legislative sync: bills/votes/committees still stubbed to zero counts
  (ships with valid provenance by design). **Now the top data gap the UI
  exposes** — key votes + sponsorship power the deepest dossier sections.
- ☐ `states` style feed is not built (senate = 2 seats/state — coloring is a
  product decision; PRD §5 discussion needed).
- ☐ Money pipeline (STOCK Act E3 + FEC totals): schema + validator + UI
  sections all exist and are dormant — ingestion is the remaining piece for
  net worth / trades / campaign finance on every profile.
- ☐ Graphify knowledge gaps: 83 weakly-connected nodes — mostly spike scripts
  and TS config; re-check after E2/E3 land real code.
- ☐ Local dev venv is Python 3.10 vs `requires-python >=3.11` — rebuild venv.
- ☐ Consider `search-index/` + `graph/` build outputs promised by ARCHITECTURE
  §3 but not yet emitted by `jobs/build.py`.
