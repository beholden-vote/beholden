# Graph Report - .  (2026-07-04)

## Corpus Check
- Corpus is ~21,119 words - fits in a single context window. You may not need a graph.

## Summary
- 333 nodes · 402 edges · 36 communities (21 shown, 15 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 14 edges (avg confidence: 0.85)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Nightly ETL Orchestration & Provenance Rules|Nightly ETL Orchestration & Provenance Rules]]
- [[_COMMUNITY_PRD, Contracts & Architecture Principles|PRD, Contracts & Architecture Principles]]
- [[_COMMUNITY_Web Dependencies (package.json)|Web Dependencies (package.json)]]
- [[_COMMUNITY_Free-Tier Hosting & Map Delivery|Free-Tier Hosting & Map Delivery]]
- [[_COMMUNITY_Fetch Job & Source Registry|Fetch Job & Source Registry]]
- [[_COMMUNITY_TS App Compiler Config|TS App Compiler Config]]
- [[_COMMUNITY_ETL Test Suite|ETL Test Suite]]
- [[_COMMUNITY_TS Node Compiler Config|TS Node Compiler Config]]
- [[_COMMUNITY_Dossier Builder|Dossier Builder]]
- [[_COMMUNITY_Transform & OCD Divisions|Transform & OCD Divisions]]
- [[_COMMUNITY_Tile OCD-ID Stamper|Tile OCD-ID Stamper]]
- [[_COMMUNITY_Web Map Frontend|Web Map Frontend]]
- [[_COMMUNITY_DuckDB Store|DuckDB Store]]
- [[_COMMUNITY_Legislators Crosswalk|Legislators Crosswalk]]
- [[_COMMUNITY_Publish Job (R2 + Raw Lake)|Publish Job (R2 + Raw Lake)]]
- [[_COMMUNITY_Congress.gov API Client|Congress.gov API Client]]
- [[_COMMUNITY_Synthetic SLD Generator|Synthetic SLD Generator]]
- [[_COMMUNITY_Tile Publish Script|Tile Publish Script]]
- [[_COMMUNITY_PMTiles Build Script|PMTiles Build Script]]
- [[_COMMUNITY_Spike Runner|Spike Runner]]
- [[_COMMUNITY_TS Root Config|TS Root Config]]
- [[_COMMUNITY_Money Pipeline (STOCK Act)|Money Pipeline (STOCK Act)]]
- [[_COMMUNITY_Jobs Package Init|Jobs Package Init]]
- [[_COMMUNITY_Sources Package Init|Sources Package Init]]
- [[_COMMUNITY_TIGER Fetch Script|TIGER Fetch Script]]
- [[_COMMUNITY_Operational Privacy|Operational Privacy]]
- [[_COMMUNITY_Static Search Index|Static Search Index]]
- [[_COMMUNITY_Legislators Source|Legislators Source]]
- [[_COMMUNITY_FEC Source|FEC Source]]
- [[_COMMUNITY_OpenStates Source|OpenStates Source]]
- [[_COMMUNITY_GitHub Actions Secrets|GitHub Actions Secrets]]
- [[_COMMUNITY_ETL Package Metadata|ETL Package Metadata]]

## God Nodes (most connected - your core abstractions)
1. `compilerOptions` - 18 edges
2. `compilerOptions` - 16 edges
3. `Production Readiness Review 2026-07-04` - 12 edges
4. `Beholden PRD v1.0` - 11 edges
5. `run()` - 9 edges
6. `PMTiles Map Tile Archives` - 8 edges
7. `Provenance Envelope` - 8 edges
8. `CongressGovClient` - 7 edges
9. `feature_props()` - 7 edges
10. `AGENTS.md Agent Instructions` - 7 edges

## Surprising Connections (you probably didn't know these)
- `Concurrency Group (etl-nightly)` --references--> `Production Readiness Review 2026-07-04`  [INFERRED]
  .github/workflows/etl-nightly.yml → docs/PRODUCTION-REVIEW-PLAN.md
- `No Provenance, No Publish` --conceptually_related_to--> `Rule: No Provenance, No Publish`  [EXTRACTED]
  docs/DATA-CONTRACTS.md → CONTRIBUTING.md
- `Dossier Validator Truthy-Key Tightening` --implements--> `Rule: No Provenance, No Publish`  [EXTRACTED]
  docs/PRODUCTION-REVIEW-PLAN.md → CONTRIBUTING.md
- `Rule: Fail Closed` --conceptually_related_to--> `Data Quality Gates`  [EXTRACTED]
  CONTRIBUTING.md → docs/PRD.md
- `Beholden (Political Accountability Map)` --references--> `Zero-Server Architecture`  [EXTRACTED]
  AGENTS.md → README.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Nightly ETL Pipeline Flow (fetch→transform→build→publish)** — _github_workflows_etl_nightly, docs_architecture_github_actions_orchestration, docs_architecture_duckdb_transform, docs_architecture_cloudflare_r2, docs_architecture_cloudflare_pages [EXTRACTED 1.00]
- **Immutable Tile + Daily Style Feed Join** — docs_data_contracts_tile_style_feed_join, docs_architecture_pmtiles, docs_data_contracts_ocd_division, _github_workflows_tiles_build [INFERRED 0.85]
- **Provenance-First Discipline Across Layers** — docs_prd_provenance_over_polish, docs_data_contracts_provenance_envelope, contributing_no_provenance_no_publish, docs_data_contracts_source_registry [INFERRED 0.85]
- **ETL Pipeline Stage Flow (fetch to publish)** — _github_workflows_etl_nightly_fetch_stage, _github_workflows_etl_nightly_transform_stage, _github_workflows_etl_nightly_build_stage, _github_workflows_etl_nightly_publish_stage [EXTRACTED 1.00]
- **Three Rules Governance Across Agent Docs** — agents_three_rules, contributing_no_provenance_no_publish, contributing_fail_closed, contributing_symmetric_by_construction, claude_claude_md [EXTRACTED 1.00]
- **Provenance and Freshness Violation Findings** — docs_production_review_plan_missing_pipeline_version, docs_production_review_plan_fabricated_retrieved_at, docs_production_review_plan_wrong_computed_as_of, docs_production_review_plan_raw_lake_never_landed [EXTRACTED 1.00]

## Communities (36 total, 15 thin omitted)

### Community 0 - "Nightly ETL Orchestration & Provenance Rules"
Cohesion: 0.07
Nodes (44): Build Stage (make build), Concurrency Group (etl-nightly), etl-nightly Workflow, Fetch Stage (make fetch), Intra-day Freshness Cron (G2 SLA), Pipeline Version, Publish Stage (make publish), Immutable Raw Lake (R2 /raw/{date}/) (+36 more)

### Community 1 - "PRD, Contracts & Architecture Principles"
Cohesion: 0.09
Nodes (25): The CDN Is the Database, Free-Tier Launch Architecture, Static-First Best Practice, Amount Bracket Enum, Dossier JSON Contract, Entity Graph Contract, Beholden PRD v1.0, Congress.gov API v3 (+17 more)

### Community 2 - "Web Dependencies (package.json)"
Cohesion: 0.09
Nodes (22): dependencies, deck.gl, @deck.gl/mapbox, maplibre-gl, minisearch, pmtiles, react, react-dom (+14 more)

### Community 3 - "Free-Tier Hosting & Map Delivery"
Cohesion: 0.11
Nodes (22): deploy-web Workflow, tiles-build Workflow, Beholden (Political Accountability Map), Census Geocoder + queryRenderedFeatures Lookup, Cloudflare Pages Published Data, Vite + React + MapLibre + deck.gl SPA, PMTiles Map Tile Archives, OCD Division ID (+14 more)

### Community 4 - "Fetch Job & Source Registry"
Cohesion: 0.14
Nodes (16): Source registry + SLAs. Mirrors data-contracts v1 §6 — adding a source here requ, Source, _now(), Path, Stage 1 — land raw snapshots (immutable) into dist/raw/{source}/.  Pulls the fed, run(), _write_json(), Congress.gov v3 client (ticket E2-1). Keyed, rate-limited (5,000 req/hr), pagina (+8 more)

### Community 5 - "TS App Compiler Config"
Cohesion: 0.10
Nodes (19): compilerOptions, allowImportingTsExtensions, jsx, lib, module, moduleDetection, moduleResolution, noEmit (+11 more)

### Community 6 - "ETL Test Suite"
Cohesion: 0.11
Nodes (13): _load_stamper(), Offline regression suite for the federal ETL slice. Runs with no network, no API, Below SPINE_RESOLUTION_MIN the crosswalk raises rather than publish partial., DW-NOMINATE is re-estimated as votes accrue: the manifest's retrieved_at     (no, No manifest = no vouched retrieval time: build must refuse to fabricate     fres, coverage.json computes age_hours/within_sla, not just echoed timestamps     (SET, Exercise the actual CLI (stdin->stdout) as build_pmtiles.sh invokes it., test_build_provenance_fails_closed_without_manifest() (+5 more)

### Community 7 - "TS Node Compiler Config"
Cohesion: 0.11
Nodes (17): compilerOptions, allowImportingTsExtensions, lib, module, moduleDetection, moduleResolution, noEmit, noFallthroughCasesInSwitch (+9 more)

### Community 8 - "Dossier Builder"
Cohesion: 0.21
Nodes (16): pipeline_version(), git tag of the ETL release, stamped into every provenance envelope.     CI sets, _current_holders(), _dossier(), _load_manifest(), _medians(), _now(), _office_display() (+8 more)

### Community 9 - "Transform & OCD Divisions"
Cohesion: 0.17
Nodes (12): house_ocd(), OCD-division identifiers for office-holders (data-contracts v1 §2/§5).  This is, (ocd_id, at_large) for a U.S. House seat. congress.gov reports at-large     and, state_ocd(), Beholden ETL. Contracts live in /docs; this package enforces them., _office_and_division(), _office_id(), Path (+4 more)

### Community 10 - "Tile OCD-ID Stamper"
Cohesion: 0.23
Nodes (12): cd_number(), feature_props(), _get(), main(), Transform a GeoJSONSeq stream. Returns count of features written., Case-insensitive first-hit lookup; Census attribute casing varies., (district_num, at_large). Census CDxxxFP: '00' = at-large single seat,     '98', State-leg district identifier for the OCD slug. Census SLDUST/SLDLST is     a ze (+4 more)

### Community 11 - "Web Map Frontend"
Cohesion: 0.17
Nodes (10): applyFeed(), ARCHIVE_FILE, ArchiveId, fillFor(), LayerDef, LAYERS, PARTY_COLORS, protocol (+2 more)

### Community 12 - "DuckDB Store"
Cohesion: 0.24
Nodes (11): Any, DuckDBPyConnection, _coerce(), connect(), init_schema(), insert(), DuckDB warehouse (free-tier arch §1.2): load the canonical Postgres DDL from db/, Split a migration into individual statements (strip line comments first). (+3 more)

### Community 13 - "Legislators Crosswalk"
Cohesion: 0.18
Nodes (9): current_term(), fetch_current(), person_uuid(), Crosswalk seed from unitedstates/congress-legislators (ticket E1-4). Bioguide <-, Deterministic person_id from bioguide — the anchor identifier. Stable     across, The legislator's active term = the last entry in terms[] (chronological)., Retrying: the nightly runs unattended — a transient GitHub blip must not     kil, Yield (person_row, identifier_rows, quarantine_row|None) per legislator. (+1 more)

### Community 14 - "Publish Job (R2 + Raw Lake)"
Cohesion: 0.33
Nodes (9): _client(), _content_type(), _ensure_cors(), Path, Stage 4 — push serving artifacts (dist/data) + raw lake (dist/raw) to R2.  The C, Set the bucket CORS policy so the SPA can read cross-origin. Non-fatal:     the, (file, bucket_key) pairs landing the raw lake at raw/{date}/{source}/…     (immu, _raw_batch() (+1 more)

### Community 16 - "Synthetic SLD Generator"
Cohesion: 0.47
Nodes (5): emit_layer(), hex_grid(), noisy_hexagon(), Yield (cx, cy, r) hex centers approximating n_target cells over CONUS., Hexagon with jittered, subdivided edges -> ~120 vertices.

### Community 17 - "Tile Publish Script"
Cohesion: 0.40
Nodes (4): AWS_ACCESS_KEY_ID, AWS_DEFAULT_REGION, AWS_SECRET_ACCESS_KEY, publish_tiles.sh script

## Knowledge Gaps
- **91 isolated node(s):** `Source`, `beholden-etl`, `fetch_tiger.sh script`, `publish_tiles.sh script`, `AWS_ACCESS_KEY_ID` (+86 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **15 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Beholden PRD v1.0` connect `PRD, Contracts & Architecture Principles` to `Nightly ETL Orchestration & Provenance Rules`?**
  _High betweenness centrality (0.024) - this node is a cross-community bridge._
- **Why does `PMTiles Map Tile Archives` connect `Free-Tier Hosting & Map Delivery` to `Nightly ETL Orchestration & Provenance Rules`?**
  _High betweenness centrality (0.023) - this node is a cross-community bridge._
- **Why does `Beholden (Political Accountability Map)` connect `Free-Tier Hosting & Map Delivery` to `Nightly ETL Orchestration & Provenance Rules`, `PRD, Contracts & Architecture Principles`?**
  _High betweenness centrality (0.019) - this node is a cross-community bridge._
- **What connects `Beholden ETL. Contracts live in /docs; this package enforces them.`, `Source`, `Source registry + SLAs. Mirrors data-contracts v1 §6 — adding a source here requ` to the rest of the system?**
  _146 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Nightly ETL Orchestration & Provenance Rules` be split into smaller, more focused modules?**
  _Cohesion score 0.06871035940803383 - nodes in this community are weakly interconnected._
- **Should `PRD, Contracts & Architecture Principles` be split into smaller, more focused modules?**
  _Cohesion score 0.09 - nodes in this community are weakly interconnected._
- **Should `Web Dependencies (package.json)` be split into smaller, more focused modules?**
  _Cohesion score 0.08695652173913043 - nodes in this community are weakly interconnected._