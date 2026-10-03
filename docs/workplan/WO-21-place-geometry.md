# WO-21 — City boundaries, nationwide

**Lane T · prereq: WO-32 (merged) · read `AGENTS.md`, `docs/workplan/README.md`, and
`docs/DATA-CONTRACTS.md` §5 and §8.5 first. §8.5 is normative for this work order.**

## Why this exists

The pipeline already publishes city officials — a mayor and a board of aldermen — and the map
has nowhere to put them. There is no incorporated-place geometry, so `pins/place.json` is
built and never fetched, and those officials are reachable only by name search. The layer
rail in the UI lists "City" as *not mapped yet*.

The geometry is one public-domain file. The Census Bureau publishes a national cartographic
boundary file for places at the same 1:500,000 scale the other archives use:
`cb_{V}_us_place_500k` under `https://www2.census.gov/geo/tiger/GENZ{V}/shp/`.

## Objective

Ship `tiles/us-places-{vintage}.pmtiles`, layer `places`, incorporated places only, with the
properties in §8.5. Geometry and identifiers only — no member data, same as every other
archive.

## Files

**OWNED** — `spike/fetch_tiger.sh` · `spike/build_pmtiles.sh` · `spike/stamp_ocd_ids.py` ·
`spike/README.md` · `.github/workflows/tiles-build.yml` · new
`pipelines/tests/test_place_tiles.py`

**SHARED — marked insertion points only** — `pipelines/beholden_etl/divisions.py` (only if
`place_ocd` needs an override hook; see below) · `docs/DATA-CONTRACTS.md` (§5 table, §8.5
status)

**NOT TOUCHED** — anything under `web/`. Adding the layer to the client is WO-37.

## Implementation notes

**Fetch.** One line in `spike/fetch_tiger.sh` beside the other `cb_{V}_us_*_500k` files.

**Stamp.** `spike/stamp_ocd_ids.py:feature_props` currently exits on any level other than
`states|cd|sldu|sldl|county`. Add `place`:

| Property | From |
|---|---|
| `ocd_id` | state + slug of `NAME`, byte-identical to `beholden_etl.divisions.place_ocd` |
| `geoid` | `GEOID` (7 digits) |
| `state` | USPS, via the existing `FIPS_TO_USPS` |
| `name` | `NAME` (bare: `Hendersonville`) |
| `kind` | `NAMELSAD` with the `NAME` prefix removed, lowercased, `(balance)` stripped |

Drop Census designated places — they are statistical areas with no government. In the
cartographic file that is `LSAD == "57"`; confirm against the file's own documentation
rather than trusting this line, and drop on the descriptor (`… CDP`) as a second check.

**The slug must agree with the pipeline.** Roster adapters build a place's `ocd_id` with
`divisions.place_ocd(state, name)`, and pins are joined to polygons on that id. If the
stamper slugs a name differently, the city's officials silently vanish from the map. The
county level has this exact guard — `test_local_slug_matches_tile_stamper` in
`pipelines/tests/test_pipeline.py`, which loads the stamper by path. Write the equivalent for
places over names that break naive slugging: `St. Louis`, `Winston-Salem`, `Coeur d'Alene`,
`Ho-Ho-Kus`, `Truth or Consequences`, `Ste. Genevieve`, `O'Fallon`, `La Cañada Flintridge`,
`Nashville-Davidson`.

**Collisions fail the build.** Two incorporated places in one state can slug to the same id.
The stamper must detect a duplicate `ocd_id` across the file and exit non-zero listing the
GEOIDs. Resolution is an explicit override table keyed on GEOID, mirrored between the
stamper and `divisions.py` and pinned equal by a test — never "keep the first one".

**Build.** In `spike/build_pmtiles.sh`, one more `tippecanoe` invocation into
`us-places-$V.pmtiles`, layer `places`. Places are small: a national view has no use for
them, so start the archive at a higher minimum zoom than the others (z7 is a reasonable
start; the client will not draw them before z10). Stay inside the existing per-tile budget
(`spike/measure_tiles.py`, 500 KB) and record the real archive size in `spike/README.md` —
the README currently holds only synthetic estimates. `spike/publish_tiles.sh` globs
`us-*-$V.pmtiles`, so the new archive uploads with no change there, and already sets the
immutable cache header.

**You probably cannot run the real build locally** (it needs GDAL and tippecanoe). Test the
stamper in Python against a small synthetic GeoJSONSeq fixture; the workflow runs the real
build, and the integrator dispatches it after merge.

## Acceptance

1. `PYTHONPATH=pipelines python -m pytest pipelines/tests -q` green, including: CDPs
   dropped; every §8.5 property present and typed; place slug parity with
   `divisions.place_ocd`; a duplicate `ocd_id` makes the stamper exit non-zero.
2. `python -m ruff check pipelines/` clean; `bash -n` clean on both shell scripts.
3. Live, after the integrator dispatches `tiles-build`:
   `https://data.beholden.vote/tiles/us-places-2025.pmtiles` returns 200 with
   `cache-control: public, max-age=31536000, immutable`, and the other five archives are
   unchanged in size.

## Out of scope

The client layer and city gate (WO-37) · county subdivisions for the township states, where
the town rather than the "place" is the municipal government — New England in particular.
That is a real gap this work order leaves open: note in `spike/README.md` which states it
affects, as the input to a follow-on. · any officials data.
