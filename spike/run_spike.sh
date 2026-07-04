#!/usr/bin/env bash
# O6 spike: can state-legislative density serve as PMTiles within mobile budgets?
# Pass criteria (from ticket E6-3):
#   - largest tile at any zoom <= 500 KB (compressed)   [mobile decode budget]
#   - full archive small enough for R2 free tier         [<10 GB, expect << 1 GB]
set -euo pipefail
DIR="${1:-.}"
cd "$DIR"

build () { # name, geojsonl, layer
  tippecanoe -o "$1.pmtiles" -l "$3" \
    --minimum-zoom=3 --maximum-zoom=12 \
    --coalesce-densest-as-needed --simplification=4 \
    --detect-shared-borders --force --quiet "$2"
  du -h "$1.pmtiles" | awk '{print "'"$1"'.pmtiles archive: "$1}'
}

build sldl synthetic_sldl.geojsonl sldl
build sldu synthetic_sldu.geojsonl sldu

python3 measure_tiles.py sldl.pmtiles sldu.pmtiles
