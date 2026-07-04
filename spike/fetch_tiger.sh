#!/usr/bin/env bash
# E6-1: fetch Census cartographic boundary files (500k) for a vintage.
set -euo pipefail
V="${1:?vintage, e.g. 2024}"
BASE="https://www2.census.gov/geo/tiger/GENZ${V}/shp"
mkdir -p tiger/$V && cd tiger/$V
for f in cb_${V}_us_state_500k cb_${V}_us_cd119_500k cb_${V}_us_sldu_500k cb_${V}_us_sldl_500k; do
  curl -fsSLO "$BASE/$f.zip" && unzip -oq "$f.zip"
done
