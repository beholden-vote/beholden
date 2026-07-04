#!/usr/bin/env bash
# E6-2: shapefiles -> OCD-stamped GeoJSONSeq -> PMTiles per data-contracts v1 §5.
#   us-states-$V.pmtiles  layer: states           props: ocd_id,name,geoid
#   us-cd-$V.pmtiles      layer: districts         props: ocd_id,state,district_num,at_large
#   us-sld-$V.pmtiles     layers: sldu, sldl       props: ocd_id,state,chamber,district_num
set -euo pipefail
V="${1:?vintage}"
cd "tiger/$V"
STAMP="python3 ../../spike/stamp_ocd_ids.py"
TIPPE=(--minimum-zoom=3 --maximum-zoom=10 --coalesce-densest-as-needed \
       --detect-shared-borders --force --quiet)

# shp prefix -> OCD-stamped newline-delimited GeoJSON for tippecanoe.
stamp () { # <shp-prefix> <level> <out.geojsonl>
  ogr2ogr -f GeoJSONSeq /vsistdout/ "$1.shp" | $STAMP "$2" > "$3"
}

stamp cb_${V}_us_state_500k  states states.geojsonl
stamp cb_${V}_us_cd119_500k  cd     cd.geojsonl
stamp cb_${V}_us_sldu_500k   sldu   sldu.geojsonl
stamp cb_${V}_us_sldl_500k   sldl   sldl.geojsonl

tippecanoe -o "../../us-states-$V.pmtiles" -l states   "${TIPPE[@]}" states.geojsonl
tippecanoe -o "../../us-cd-$V.pmtiles"     -l districts "${TIPPE[@]}" cd.geojsonl
# Both state-legislative chambers share one archive, one layer each (§5).
tippecanoe -o "../../us-sld-$V.pmtiles" \
  -L "sldu:sldu.geojsonl" -L "sldl:sldl.geojsonl" "${TIPPE[@]}"
