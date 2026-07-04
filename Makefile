# Beholden — free-tier pipeline entrypoints (see ARCHITECTURE.md §3)
PY := python3 -m beholden_etl

.PHONY: fetch transform build publish tiles-fetch tiles-build tiles-publish spike web dev

fetch:          ## land raw snapshots in R2 (immutable)
	$(PY).jobs.fetch

transform:      ## DuckDB models + quality gates (fails closed)
	$(PY).jobs.transform

build:          ## dossiers, stylefeeds, pins, graph, search index, coverage
	$(PY).jobs.build

publish:        ## push artifacts to Pages dir + R2
	$(PY).jobs.publish

tiles-fetch:
	bash spike/fetch_tiger.sh 2024

tiles-build:
	bash spike/build_pmtiles.sh 2024

tiles-publish:
	bash spike/publish_tiles.sh 2024

spike:          ## O6 density spike with synthetic geometry (runs anywhere, no downloads)
	python3 spike/generate_synthetic_sld.py && bash spike/run_spike.sh

web:
	cd web && npm run build

dev:
	cd web && npm run dev
