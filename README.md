# Beholden

**See who they answer to.** · [beholden.vote](https://beholden.vote)

A political microscope built on provenance: every US federal and state elected official
on one interactive map, each openable into a fully-cited accountability dossier —
party, ideology (DW-NOMINATE), legislative record, STOCK Act trades, financial
disclosures, and campaign funding. Every fact on screen traces to an official source.

## How it works
Zero-server architecture: a nightly GitHub Actions pipeline (DuckDB) ingests official
government data sources, enforces quality gates that **fail closed**, and publishes
static JSON + PMTiles to Cloudflare Pages/R2. There is no runtime backend in v1 —
the CDN is the database. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Documentation
| Doc | What it covers |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Entry point for AI agents/LLMs — rules, repo map, commands |
| [`docs/PRD.md`](docs/PRD.md) | Product spec: principles, goals, dossier UX, phasing |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Free-tier hosting design, component map, scale-up path |
| [`docs/DATA-CONTRACTS.md`](docs/DATA-CONTRACTS.md) | Spine DDL, dossier JSON, entity graph, tile contracts |
| [`docs/TICKETS-PHASE1.md`](docs/TICKETS-PHASE1.md) | 12-week engineering breakdown (~118 eng-days) |
| [`docs/SETUP.md`](docs/SETUP.md) | Zero-to-running: accounts, secrets, first pipeline run |
| [`spike/README.md`](spike/README.md) | O6 tile-density spike — **PASS**, state layers are GO |

## Quickstart
```bash
make spike                      # reproduce the tile-density spike (no keys needed)
cd web && npm install && npm run dev   # frontend against staged data
pip install -e ./pipelines && make fetch transform build   # pipeline (needs API keys)
```

## Repo map
```
.github/workflows/   nightly ETL (the orchestrator), tile builds, Pages deploy
db/migrations/       canonical DDL — the identity spine, legislative, money tables
pipelines/           Python ETL: source adapters, quality gates, dossier builder
spike/               O6 density spike + real TIGER->PMTiles scripts
web/                 Vite + React + MapLibre static SPA
docs/                product + engineering documentation
```

## Principles (short version)
Provenance over polish · ranges are ranges · descriptive, not prescriptive ·
symmetric by construction · speed is a feature. Full version in the PRD.

## Data sources
Congress.gov v3 · unitedstates/congress-legislators · Voteview (DW-NOMINATE) ·
OpenStates/Plural · FEC · House Clerk + Senate eFD (STOCK Act) · Census TIGER.
All public record. Private repo during buildout; intended to be public at launch —
a reproducible pipeline is itself a credibility feature.
