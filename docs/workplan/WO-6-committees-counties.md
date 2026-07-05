# WO-6 — Committees sync (6a) + county tile layer (6b)

Two independent halves; may be two agents. Read `docs/workplan/README.md` + `AGENTS.md` first.

---

## 6a — Committee memberships (Lane P, AFTER WO-3 merges)

### Objective
Fill dossier `legislative.committees[]` (UI already renders it) and the `committees` +
`committee_memberships` tables, enabling WO-4's `committee` edges and future PTR
committee-overlap flags.

### Source
congress.gov API (client exists: `sources/congress_gov.py`, keyed, throttled):
- `GET /committee/{congress}/{chamber}` (paged) → committee list (code, name, parent).
- Membership: current member detail (`/member/{bioguide}`) does NOT reliably include
  committees; instead use the committee detail endpoints or the `unitedstates/congress-legislators`
  repo's `committee-membership-current.yaml` (same source family as the crosswalk —
  `https://raw.githubusercontent.com/unitedstates/congress-legislators/main/committee-membership-current.yaml`,
  keyed by bioguide + thomas_id, includes rank/title). **Prefer the YAML** — bulk, no
  pagination, already-registered source family. Verify it's current before building.

### Files
OWNED: `sources/legislators.py` (add committee-membership fetch/mappers — same source).
SHARED (marked insertions): `jobs/fetch.py`, `jobs/transform.py` (→ `committees`,
`committee_memberships`; map roles to the DDL enum `member|chair|ranking|vice_chair`,
unknown→`member`), `jobs/build.py` (attach `committees: [{name, role, subcommittees?}]`),
`tests/test_pipeline.py`.

### Acceptance
Tests for mapping/dedupe/role-enum. Live: a dossier's legislative section lists committees
with the congress.gov/unitedstates source stamp intact.

---

## 6b — County tile layer (Lane T, independent)

### Objective
`us-counties-{vintage}.pmtiles` published to R2 and registered (hidden by default) in the map —
the geometric foundation for the local expansion. No county *people* data yet.

### Steps
1. `spike/fetch_tiger.sh`: add `cb_{V}_us_county_500k` to the download list.
2. `spike/stamp_ocd_ids.py`: add level `county` →
   `ocd_id = ocd-division/country:us/state:{usps}/county:{slug}` where slug = county NAME
   lowercased, spaces/punctuation → underscores (match OCD-division conventions:
   `st._clair` style — check 2–3 real examples against the official ocd-division-ids repo
   `https://raw.githubusercontent.com/opencivicdata/ocd-division-ids/master/identifiers/country-us.csv`
   and mirror exactly; document the slug rule in the docstring). Props: `ocd_id`, `state`,
   `name`, `geoid`.
3. `spike/build_pmtiles.sh`: build `us-counties-$V.pmtiles`, layer `counties`, maxzoom 10.
4. `web/src/map.ts`: register archive + `counties` layer, `DEFAULT_VISIBLE.counties=false`,
   line-only styling (no fill until data exists), minzoom ~7. Add checkbox to LayerControl
   (label "Counties"). Coordinate with WO-2 if it has merged (auto-mode registration point).
5. Run `tiles-build` workflow; verify Range-request 206 on the new archive.

### Files
OWNED: `spike/*` (stamper: add level only — don't disturb existing levels), plus the marked
layer-registration block in `web/src/map.ts` / `chrome.tsx`.
Tests: extend the stamper test in `tests/test_pipeline.py` for the county slug rule.

### Acceptance
`data.beholden.vote/tiles/us-counties-2024.pmtiles` serves 206; counties toggle renders
boundaries; slug spot-checks match ocd-division-ids for ≥3 counties incl. a punctuated name.
