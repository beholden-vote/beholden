#!/usr/bin/env bash
# E6-1: fetch Census cartographic boundary files (500k) for a vintage, plus
# Natural Earth 10m context layers (public domain: city points + major roads).
set -euo pipefail
V="${1:?vintage, e.g. 2024}"
BASE="https://www2.census.gov/geo/tiger/GENZ${V}/shp"
NE="https://naciscdn.org/naturalearth/10m/cultural"
mkdir -p tiger/$V && cd tiger/$V
for f in cb_${V}_us_state_500k cb_${V}_us_cd119_500k cb_${V}_us_sldu_500k cb_${V}_us_sldl_500k cb_${V}_us_county_500k; do
  curl -fsSLO "$BASE/$f.zip" && unzip -oq "$f.zip"
done
for f in ne_10m_populated_places_simple ne_10m_roads; do
  curl -fsSLO "$NE/$f.zip" && unzip -oq "$f.zip"
done
