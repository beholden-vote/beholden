# WO-34 — Facts about every county and city

**Lane P · prereq: WO-32 (merged) · read `AGENTS.md`, `docs/workplan/README.md`,
`docs/TRUSTED-EXTRACTION.md` (gates), and `docs/DATA-CONTRACTS.md` §8.4 first. §8.4 is
normative for this work order.**

## Why this exists

Clicking a county tells a reader its name, its FIPS code, and — for 3,142 of 3,143 counties —
that Beholden does not cover its officials. Officials can only arrive state by state; facts
about the place itself can arrive everywhere at once, from one public-domain publisher.

## Objective

Publish `areas/county/{st}.json` and `areas/place/{st}.json` for all 50 states and DC: name,
land area, and four survey estimates with their margins of error. One file per state per
level, keyed by Census GEOID.

## Data source

- **American Community Survey 5-year**, via the Census Data API:
  `https://api.census.gov/data/{YEAR}/acs/acs5?get=NAME,…&for=county:*` (one national call)
  and `…&for=place:*&in=state:{FIPS}` (one call per state). Tables: `B01003_001` total
  population, `B11001_001` households, `B19013_001` median household income, `B01002_001`
  median age — each as estimate (`E`) and margin of error (`M`). Use the most recent 5-year
  release the API serves; pin it as a constant, do not discover it at run time. Keyless
  access is rate-limited per IP per day, far above the ~55 calls a refresh makes; honour an
  optional `CENSUS_API_KEY` env var.
- **Gazetteer files** for names and land area (`ALAND_SQMI`):
  `https://www2.census.gov/geo/docs/maps-data/data/gazetteer/` — the national counties and
  places files for the matching vintage.

Both are works of the US Government. Verify the access pattern and record the terms the
Bureau states for API users before relying on this paragraph — including the notice it asks
API consumers to display, which goes on the public Sources page.

## Files

**OWNED** — new `pipelines/beholden_etl/sources/census_areas.py` · new
`pipelines/beholden_etl/build/areas.py` · new `pipelines/tests/test_areas.py`

**SHARED — marked insertion points only** — `pipelines/beholden_etl/config.py` (two
`SOURCES` rows: `census_acs`, `census_gazetteer`) · `pipelines/beholden_etl/jobs/fetch.py`
(register the fetcher, following the existing `_FETCHERS` pattern and the WO-10 freshness
rules) · `pipelines/beholden_etl/jobs/build.py` (**one import and one line in
`ARTIFACT_WRITERS`** — do not edit `run()`) · `web/src/ui/chrome.tsx` (two rows in the
Sources table, plus the Bureau's API notice — nothing else in that file) ·
`docs/DATA-CONTRACTS.md` (§6 enum, §8.4 status)

## Implementation notes

**The writer.** `build/areas.py` exposes `publish(ctx: BuildContext) -> dict[str, int]`
(see `beholden_etl/build/context.py`). Get envelopes from `ctx.provenance(...)`, never by
hand — it is what enforces "no provenance, no publish". Return
`{"area_counties": n, "area_places": m}`; the counts land in `coverage.json`.

**Sentinels are the trap.** The API reports a withheld estimate as a large negative number
(`-666666666` and relatives) and annotates margins the same way. Published as-is, that is a
median household income of minus six hundred million dollars — a fabricated fact with a
citation on it. Map every documented sentinel: a withheld **estimate** omits the field for
that area; a not-applicable **margin** becomes `null`. Test with a fixture row that carries
each sentinel you find in the Bureau's documentation.

**Ranges are ranges.** Every estimate is published as `{ "estimate": …, "moe": … }`. Do not
drop the margin to make the JSON smaller — PRD principle 2.

**Incorporated places only.** The place universe includes Census designated places, which
have no government. Keep places with an active government (the Gazetteer's functional-status
column distinguishes them) so this file describes the same set of places as the tile layer
in WO-21. A mismatch at the edges is harmless — a polygon without a row shows no facts — but
do not ship thousands of statistical areas as if they were cities.

**Fail-closed gates** (TRUSTED-EXTRACTION): a control total — the sum of county populations
in a state must equal the state figure from the same API within a small tolerance, because
the Bureau publishes both; a row count per state against the Gazetteer's; value-domain
checks (no negative population, land area, or income). A gate failure raises. Never `try`
around one.

**Deterministic output.** Sort areas by GEOID and serialise with stable key order, so an
unchanged vintage produces byte-identical files night after night.

**Freshness.** This data changes once a year. Give both sources a long SLA so the nightly
re-fetches rarely — but it must still fetch on a cold start.

## Acceptance

1. `PYTHONPATH=pipelines python -m pytest pipelines/tests -q` green. `test_areas.py` runs
   offline against synthetic API payloads and covers: sentinel handling (estimate withheld →
   field omitted; margin not applicable → `null`); the control-total gate failing closed;
   CDPs excluded; envelopes present on both blocks and valid under
   `dossiers.REQUIRED_PROVENANCE`; two builds byte-identical.
2. `python -m ruff check pipelines/` clean; `cd web && npm run build` clean.
3. Live, after the next nightly: `https://data.beholden.vote/areas/county/tn.json` lists 95
   counties; Sumner County (`47165`) carries a population estimate; `areas/place/tn.json`
   contains Hendersonville; `coverage.json` reports both sources and the two counts.

## Out of scope

Any UI (WO-37) · county budgets and spending from the Census of Governments · election
results · school districts and other special districts · territories.
