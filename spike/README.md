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

## Files
- `generate_synthetic_sld.py` — synthetic geometry at contract-correct properties
- `run_spike.sh` / `measure_tiles.py` — build + per-zoom stats + pass/fail
- `fetch_tiger.sh` / `build_pmtiles.sh` / `publish_tiles.sh` — the real pipeline (E6-1/2)
