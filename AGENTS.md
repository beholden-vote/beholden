# AGENTS.md — instructions for AI agents & LLMs working on Beholden

This file is the entry point for any coding agent (Claude Code, Cursor, Copilot,
Codex, etc.). Read it before making changes. It is intentionally short; the
authoritative detail lives in [`docs/`](docs/).

## What Beholden is
A political-accountability map: every US federal and state elected official on one
interactive map, each openable into a fully-cited dossier. **Zero-server v1** — a
nightly GitHub Actions pipeline (DuckDB) ingests official government data, enforces
quality gates that fail closed, and publishes static JSON + PMTiles to Cloudflare
Pages/R2. The CDN is the database. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## The three rules that outrank everything
These are non-negotiable. A change that violates one is wrong even if it passes CI.
1. **No provenance, no publish.** Every published fact carries a source envelope; the
   dossier builder enforces this and refuses to emit violations. Never add a fact path
   that bypasses the provenance validator.
2. **Fail closed.** Quality-gate failures halt the pipeline. Never ship partial data,
   never lower a threshold to make a run pass, never `try/except` around a gate.
3. **Symmetric by construction.** No feature, copy, or presentation choice may apply
   asymmetrically by party. See [`docs/PRD.md`](docs/PRD.md) §2 and §9.

Full contributor rules: [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Repo map
```
.github/workflows/   etl-nightly (orchestrator) · tiles-build · deploy-web
db/migrations/       canonical DDL — 001_spine, 002_legislative, 003_money
pipelines/beholden_etl/
  config.py          sources registry, SLAs, thresholds (mirrors DATA-CONTRACTS §6)
  divisions.py       OCD-ID / division helpers
  store.py           DuckDB connection + schema application
  sources/           one adapter per source: congress_gov, legislators, voteview
  jobs/              pipeline stages: fetch → transform → build → publish
  build/             dossiers.py (builder + provenance validator), stylefeeds.py
  tests/             pytest suite (test_pipeline.py)
spike/               O6 tile-density spike + real TIGER→PMTiles scripts (PASS)
web/                 Vite + React + MapLibre GL + pmtiles static SPA
  src/main.tsx       entry: wires map engine ↔ React UI
  src/map.ts         MapLibre init, PMTiles, hover/click → representation stack
  src/ui/            App (search + stack panel), DossierView, Ideology scale
  src/lib/data.ts    pins/dossier fetch + caches; lib/lookup.ts Census geocoder
  src/strings.ts     THE approved string table (money/legal copy lives here only)
  src/types.ts       TS mirror of the dossier/pins contracts
docs/                product + engineering documentation (see below)
graphify-out/        knowledge graph of this repo (see "Knowledge graph" below)
```

## Documentation index
| Doc | What it covers |
|---|---|
| [`docs/PRD.md`](docs/PRD.md) | Product spec: principles, goals, dossier UX, phasing |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Free-tier hosting design, component map, scale-up path |
| [`docs/DATA-CONTRACTS.md`](docs/DATA-CONTRACTS.md) | Spine DDL, dossier JSON, entity graph, tile contracts |
| [`docs/workplan/README.md`](docs/workplan/README.md) | Work orders, lanes, and the live status board |
| [`docs/TRUSTED-EXTRACTION.md`](docs/TRUSTED-EXTRACTION.md) | How bulk public records become cited facts (no models in the path) |
| [`docs/BRAND.md`](docs/BRAND.md) | The `[B]` mark, colorways, avatar/social-card usage — the identity system |
| [`docs/SETUP.md`](docs/SETUP.md) | Zero-to-running: accounts, secrets, first pipeline run |
| [`spike/README.md`](spike/README.md) | O6 tile-density spike — PASS |

## Build, run, test
The pipeline is a Python package (`beholden_etl`, requires Python ≥3.11); the frontend
is a Vite SPA. Common entrypoints go through the [`Makefile`](Makefile):

```bash
# ETL (needs CONGRESS_GOV_API_KEY, FEC_API_KEY for live fetch)
pip install -e ./pipelines
make fetch transform build      # stages land in dist/data for inspection
make publish                    # pushes to Pages dir + R2

# Tiles (no API keys needed for the spike)
make spike                      # O6 density spike, synthetic geometry, runs anywhere
make tiles-fetch tiles-build tiles-publish   # real TIGER → PMTiles → R2

# Frontend
cd web && npm install && npm run dev   # dev server against staged data
npm run build                          # production build

# Tests / lint (run before committing pipeline changes)
cd pipelines && pytest && ruff check .
```
CI runs ruff, pytest, and contract validation on PRs — keep them green.

## Conventions
- **Python:** ruff defaults. **SQL:** canonical DDL lives in `db/migrations`; DuckDB
  shims are applied at load, never hand-forked into a second copy.
- **Data contracts are law.** A data-touching change must conform to
  [`docs/DATA-CONTRACTS.md`](docs/DATA-CONTRACTS.md); PRs should link the relevant
  section. A new source = registry entry in `config.py` + methodology entry +
  coverage-dashboard row + freshness SLA. CI rejects unregistered sources.
- **Money/legal copy** (net worth, late-filing flags) comes from the approved string
  table only — never composed inline.
- **Operational privacy (enforced):** commits use the project identity
  (`Beholden Maintainers <maintainers@beholden.vote>`) or GitHub noreply — never
  personal emails. No personal names, other-project references, or identifying brand
  language in code, docs, or commit messages.

## Knowledge graph (graphify)
This repo is indexed as a navigable knowledge graph in [`graphify-out/`](graphify-out/):
`graph.html` (interactive), `graph.json` (raw), `GRAPH_REPORT.md` (audit report).

Before answering an architecture / "how does X connect to Y" / data-flow question,
prefer querying the graph instead of re-reading files from scratch:
```bash
graphify query "how does the fetch stage feed the dossier builder?"
```
After changing code, refresh it incrementally:
```bash
graphify . --update
```
The graph is committed context — treat it as a fast index over the codebase, not a
source of truth that overrides the actual files.
