#!/usr/bin/env bash
# E6-2: shapefiles -> OCD-stamped GeoJSONSeq -> PMTiles per data-contracts v1 §5.
#   us-states-$V.pmtiles    layer: states           props: ocd_id,name,geoid
#   us-cd-$V.pmtiles        layer: districts         props: ocd_id,state,district_num,at_large
#   us-sld-$V.pmtiles       layers: sldu, sldl       props: ocd_id,state,chamber,district_num
#   us-counties-$V.pmtiles  layer: counties          props: ocd_id,state,name,geoid
#   us-places-$V.pmtiles    layer: places            props: ocd_id,geoid,state,name,kind  (WO-21)
set -euo pipefail
V="${1:?vintage}"
cd "tiger/$V"
STAMP="python3 ../../spike/stamp_ocd_ids.py"
TIPPE_COMMON=(--maximum-zoom=10 --coalesce-densest-as-needed \
              --detect-shared-borders --force --quiet)
TIPPE=(--minimum-zoom=3 "${TIPPE_COMMON[@]}")

# shp prefix -> OCD-stamped newline-delimited GeoJSON for tippecanoe.
stamp () { # <shp-prefix> <level> <out.geojsonl>
  ogr2ogr -f GeoJSONSeq /vsistdout/ "$1.shp" | $STAMP "$2" > "$3"
}

stamp cb_${V}_us_state_500k  states states.geojsonl
stamp cb_${V}_us_cd119_500k  cd     cd.geojsonl
stamp cb_${V}_us_sldu_500k   sldu   sldu.geojsonl
stamp cb_${V}_us_sldl_500k   sldl   sldl.geojsonl
stamp cb_${V}_us_county_500k county county.geojsonl
# Incorporated places only (CDPs dropped). Exits non-zero on a duplicate ocd_id,
# which aborts the build here (pipefail + errexit) before anything is tiled.
# Not places.geojsonl: that name is the Natural Earth context layer below.
stamp cb_${V}_us_place_500k  place  incorporated.geojsonl

tippecanoe -o "../../us-states-$V.pmtiles" -l states   "${TIPPE[@]}" states.geojsonl
tippecanoe -o "../../us-cd-$V.pmtiles"     -l districts "${TIPPE[@]}" cd.geojsonl
# Both state-legislative chambers share one archive, one layer each (§5).
tippecanoe -o "../../us-sld-$V.pmtiles" \
  -L "sldu:sldu.geojsonl" -L "sldl:sldl.geojsonl" "${TIPPE[@]}"
# Counties: the local-tier geometric foundation (WO-6b). Geometry + OCD-ID only,
# no member data yet; the client fades it in at high zoom (map.ts). maxzoom 10
# like the other district archives.
tippecanoe -o "../../us-counties-$V.pmtiles" -l counties "${TIPPE[@]}" county.geojsonl
# Places (WO-21): ~19.7k incorporated places. A national view has no use for them
# and the client will not draw them before z10, so the archive starts at z7 and
# skips the z3-z6 tiles the others carry. Same maxzoom and coalescing as the rest.
tippecanoe -o "../../us-places-$V.pmtiles" -l places --minimum-zoom=7 "${TIPPE_COMMON[@]}" incorporated.geojsonl

# Orientation context (Natural Earth, public domain): US city points + major
# roads, one archive, two layers. Points need -r1 so tippecanoe never drops
# sparse city labels at low zoom.
CTX="python3 ../../spike/context_layers.py"
ogr2ogr -f GeoJSONSeq /vsistdout/ ne_10m_populated_places_simple.shp | $CTX places > places.geojsonl
ogr2ogr -f GeoJSONSeq /vsistdout/ ne_10m_roads.shp | $CTX roads > roads.geojsonl
tippecanoe -o "../../us-context-$V.pmtiles" \
  -L "places:places.geojsonl" -L "roads:roads.geojsonl" \
  --minimum-zoom=3 --maximum-zoom=10 -r1 --force --quiet
