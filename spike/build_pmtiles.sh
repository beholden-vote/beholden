#!/usr/bin/env bash
# E6-2: shapefiles -> GeoJSON (OCD-ID stamped) -> PMTiles per data-contracts §5.
set -euo pipefail
V="${1:?vintage}"
cd tiger/$V
build () { # shp prefix, layer name, ocd python expr file handled by stamp script
  ogr2ogr -f GeoJSONSeq /vsistdout/ "$1.shp" | python3 ../../stamp_ocd_ids.py "$2" \
    | tippecanoe -o "../../us-$2-$V.pmtiles" -l "$2" \
        --minimum-zoom=3 --maximum-zoom=10 \
        --coalesce-densest-as-needed --detect-shared-borders --force --quiet
}
build cb_${V}_us_state_500k states
build cb_${V}_us_cd119_500k cd
build cb_${V}_us_sldu_500k sldu
build cb_${V}_us_sldl_500k sldl
