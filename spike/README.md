# O6 Spike — state-legislative density as PMTiles on low-end mobile

**Verdict: GO.** Run `make spike` from repo root to reproduce (synthetic geometry,
no downloads needed — runs anywhere including CI).

## Result (2026-07-03, tippecanoe v2.80, synthetic CONUS-uniform density)

| Archive | Features | Size | Largest tile | Limit | Verdict |
|---|---|---|---|---|---|
| sldl (lower chambers) | 4,800 @ ~120 verts | 50 MB | **120 KB** (z4) | 500 KB | **PASS** |
| sldu (upper chambers) | 1,900 @ ~120 verts | 32 MB | **67 KB** (z4) | 500 KB | **PASS** |

- Worst tiles occur at z4 where the whole country is in frame; by z7+ tiles are <7 KB.
  `--coalesce-densest-as-needed` + `--detect-shared-borders` do the heavy lifting.
- The synthetic set is a **conservative overstatement**: uniform national coverage,
  whereas real SLDs concentrate vertex density in populated areas.
- 82 MB total for both chambers is nothing against R2's 10 GB free tier; CDs + states
  will add ~30–60 MB. Whole national tile set comfortably < 200 MB.

## Follow-on optimizations (not blockers)
1. Cap `--maximum-zoom=10` and let MapLibre overzoom to z12+ — ~290k near-empty
   high-zoom tiles per archive exist only to satisfy z12; cutting them shrinks
   archives dramatically with zero visual cost for polygon fills.
2. At real-data time, verify AK/HI/territories inset handling and CA senate districts
   (largest real SLDs) don't spike z4 tiles past ~250 KB. Margin is 4x; low risk.

## Place archive (WO-21)

`us-places-{vintage}.pmtiles`, layer `places`, properties `ocd_id, geoid, state, name, kind`
(data-contracts 8.5). Source: `cb_{V}_us_place_500k`. Not to be confused with the `places`
layer in `us-context` (Natural Earth city points): different archive, so MapLibre keeps them apart.

- **Incorporated places only.** The Census file mixes them with designated places (CDPs). Per the
  Bureau's feature catalog for the file, LSAD `57` is a CDP, and `55` (comunidad) / `62` (zona
  urbana) are the Puerto Rico equivalents; a feature is dropped if its LSAD or its descriptor says so.
- **z7 floor, z10 ceiling.** The other archives start at z3; a national view has no use for ~19.7k
  city polygons and the client will not draw them before z10. Same coalescing flags as the rest.
- **Duplicate ids fail the build.** The stamper exits non-zero, listing the GEOIDs, if two places
  stamp the same `ocd_id`. The 17 collision groups found in the Bureau's TIGERweb place layer (35
  places, PA/TX/WI/IL/OH/MN) are resolved in `PLACE_SLUG_OVERRIDES`, mirrored in `divisions.py`. If
  the first real build finds another, it is a new GEOID line in both places.
- **Real size: not measured yet.** GDAL and tippecanoe were not available where this was written, so
  there is no number to record. The `tiles-build` workflow now lists every archive's size and runs
  `measure_tiles.py` on the places archive (it fails the run past the 500 KB per-tile budget); record
  the archive size and largest tile from that log here after the first run.

**Known gaps** (a follow-on, not this work order):
- *Township and town states.* In the twelve states where the municipal government is a county
  subdivision rather than a "place" (CT, ME, MA, MI, MN, NH, NJ, NY, PA, RI, VT, WI), a place layer
  covers only part of the map. Incorporated places per the Bureau: CT 30, ME 23, MA 58, NH 13, RI 8,
  VT 40 (New England, where the town is the government and most towns are not places at all);
  NJ 323, NY 594, PA 1,014, MI 533, MN 856, WI 608 (boroughs, cities and villages are places;
  townships and towns are not). Needs the `cb_{V}_us_cousub_500k` file.
- *Consolidated "(balance)" places.* The Bureau's TIGERweb layer gives eight of them their full
  descriptor inside the name (e.g. `Nashville-Davidson metropolitan government (balance)`, GEOID
  4752006), with no separate descriptor. If the cartographic file does the same, those eight stamp
  an unwieldy slug and an empty `kind`, and a roster that slugs "Nashville-Davidson" will not match
  them. GEOIDs: 0947515, 1303440, 1304204, 1836003, 2028412, 2148006, 3011397, 4752006. The fix is a
  GEOID line in `PLACE_SLUG_OVERRIDES` once a roster for one of them exists.
- *Island areas.* The Bureau's TIGERweb layer lists 215 "villages" and "towns" in American Samoa, the
  Northern Marianas and the Virgin Islands as incorporated places. If the cartographic file carries
  them they stamp under `state:as` / `state:mp` / `state:vi`, as the other levels do; nothing here
  filters them.

## Files
- `generate_synthetic_sld.py` — synthetic geometry at contract-correct properties
- `run_spike.sh` / `measure_tiles.py` — build + per-zoom stats + pass/fail
- `fetch_tiger.sh` / `build_pmtiles.sh` / `publish_tiles.sh` — the real pipeline (E6-1/2)
