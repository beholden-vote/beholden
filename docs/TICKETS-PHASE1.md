# Beholden — Phase 1 Engineering Ticket Breakdown
**Scope:** PRD v1.0 P0 set (federal-complete + state layer) · **Target:** 12 weeks · **Estimates:** ideal eng-days (d). Team capacity is an open input — at ~70% realized capacity, this plan needs ≈2.5–3 FTE engineers or a scope cut at the flagged lines.

**Sprint goal (one sentence):** Ship a public map of every federal and state elected official where any pin opens a fully-cited dossier in under 300ms.

---

## Dependency graph (critical path in bold)

```
**E1 Spine** ─→ **E2 Ingestion(fed)** ─→ **E5 Dossier build** ─→ **E7 Sidebar**
     │              ├→ E3 Money pipeline ──┘                        │
     │              └→ E4 State (OpenStates) ─→ E5                  │
**E6 Geometry/Tiles** ─────────────→ **E7 Map frontend** ──────────┴→ **E9 Launch**
E8 Quality/Ops runs continuously from wk 3
```

---

## E1 — Identity Spine (wk 1–2)

| ID | Ticket | AC (abridged) | Est | Deps |
|---|---|---|---|---|
| E1-1 | Repo, IaC, environments (S3/R2, Postgres, CI, secrets) | `main` deploys to staging; raw bucket versioned + write-once policy | 2d | — |
| E1-2 | Core DDL: `persons`, `person_identifiers`, `divisions`, `offices`, `terms` (see data-contracts doc) | Migrations run clean; slowly-changing `terms` supports historical queries (P2 insurance) | 2d | E1-1 |
| E1-3 | OCD division ID loader (country→state→cd→sldu/sldl) | All 50 states + territories + 435 CDs + state chambers loaded; uniqueness enforced | 1d | E1-2 |
| E1-4 | Crosswalk seed from `unitedstates/congress-legislators` (bioguide↔FEC↔ICPSR↔Wikidata) | ≥99.5% of sitting members resolve to all four IDs; misses land in `quarantine_identities` | 2d | E1-2 |
| E1-5 | Quarantine workflow + resolution CLI (LLM-suggested matches, human confirm) | No fuzzy match ever writes to production tables; audit log per resolution | 2d | E1-4 |

## E2 — Federal Ingestion (wk 2–4)

| ID | Ticket | AC | Est | Deps |
|---|---|---|---|---|
| E2-1 | Congress.gov v3 client (keyed, rate-limited 5k/hr, paginated 250, retry/backoff) | Golden-file tests; 429/5xx resilient; requests logged | 2d | E1-1 |
| E2-2 | Members sync → spine (roster, party, district, photos via bioguide URLs) | Nightly diff-sync; roster change reflected ≤24h (G2 SLA test) | 2d | E2-1, E1-4 |
| E2-3 | Bills + sponsorship ingest (current Congress backfill, then incremental `updatedSince`) | Sponsor/cosponsor rows keyed to spine; withdrawn cosponsors preserved | 3d | E2-2 |
| E2-4 | Roll-call votes + member positions | Vote positions joinable to bills + members; voice votes marked unavailable, not zero | 3d | E2-3 |
| E2-5 | Committees + memberships (incl. chair/ranking flags) | Committee history retained per Congress | 2d | E2-2 |
| E2-6 | Voteview DW-NOMINATE loader (CSV bulk, per-Congress) | Dim-1 scores joined via ICPSR; members <20 votes flagged `pending` | 1d | E1-4 |
| E2-7 | FEC ingest: totals, cash-on-hand, top contributors/employers per candidate committee | Cycle-scoped; committee↔person mapping via crosswalk; industry field nullable (Open Q O4) | 3d | E1-4 |

## E3 — Money Pipeline (wk 3–6) — highest-severity error class

| ID | Ticket | AC | Est | Deps |
|---|---|---|---|---|
| E3-1 | Vendor PTR feed integration (per O1 decision) behind a source-adapter interface | Trades land in canonical `trades` schema with `source='vendor'`; license terms recorded | 2d | O1 closed |
| E3-2 | House Clerk + Senate eFD index scrapers (filing metadata + PDF URLs) | Daily republish detected; new PTR metadata ≤24h (G2) | 3d | E1-1 |
| E3-3 | Own PTR parser v0: digital PDFs (ticker, type, bracket, dates) | ≥98% field accuracy on digital-filing test set; `source='internal'` | 4d | E3-2 |
| E3-4 | OCR + LLM extraction for scanned/handwritten filings, confidence-scored | Below-threshold extractions route to review queue; nothing below threshold publishes | 4d | E3-3 |
| E3-5 | Dual-run diff: vendor vs. internal, nightly report + alarm | Discrepancy rate dashboarded; per-row provenance retained | 2d | E3-1, E3-3 |
| E3-6 | Late-filing flag (transaction date vs. filing date > 45d statutory) | Flag copy = statutory statement, from counsel-approved strings (O3) | 1d | E3-3 |
| E3-7 | Annual disclosure ingest → net-worth **band** computation (min/max by bracket arithmetic) | Output is always a range + methodology version ID; unit tests on bracket math | 3d | E3-4 |
| E3-8 | Human review queue UI (internal): approve/correct extractions | Reviewer actions audited; corrections retrain test set | 3d | E3-4 |

*Scope-cut line: if capacity-constrained, ship vendor-only (cut E3-3/4/5/8 to Phase 2) — but keep E3-2 so raw filings and links still come from official sources.*

## E4 — State Layer (wk 4–6)

| ID | Ticket | AC | Est | Deps |
|---|---|---|---|---|
| E4-1 | OpenStates people sync → spine (person IDs into crosswalk) | ≥95% of state legislators loaded; per-state coverage metric computed | 3d | E1-4 |
| E4-2 | Shor-McCarty score loader | Scores joined where match exists; staleness date stored for in-product label | 1d | E4-1 |
| E4-3 | State bills/votes (best-effort per state) | Coverage badge thresholds defined; below-threshold states labeled `partial` | 3d | E4-1 |

## E5 — Transform & Serving (wk 5–8)

| ID | Ticket | AC | Est | Deps |
|---|---|---|---|---|
| E5-1 | dbt project over lake (DuckDB) → Postgres marts; tests on every model | Referential integrity + row-count tests gate promotion | 3d | E2, E3, E4 |
| E5-2 | Dossier JSON builder (per-official, per data-contract v1) + CDN publish | JSON validates against schema; rebuild nightly + patch-on-event (votes, PTRs) | 3d | E5-1 |
| E5-3 | pgvector embeddings for bills + officials; hybrid search endpoint | "water rights" style semantic query returns relevant officials <500ms | 2d | E5-1 |
| E5-4 | Entity graph materialization: cosponsor, committee, donor, ticker-cluster edges | Edges carry typed evidence arrays (see contracts); nightly build <30min | 3d | E5-1 |
| E5-5 | "Known for" generation job (structured inputs → cited bullets, banned-adjective lint, cache) | Every bullet has ≥1 citation; lint blocks publish; regeneration diffs logged | 3d | E5-2, O3 |
| E5-6 | Thin API: search, filters, graph neighborhood, address→stack | p95 <300ms on staged load test | 3d | E5-2/3/4 |

## E6 — Geometry & Tiles (wk 1–3, parallel track)

| ID | Ticket | AC | Est | Deps |
|---|---|---|---|---|
| E6-1 | TIGER/cartographic boundary pipeline: states, CDs, SLDU/SLDL → simplified GeoJSON | Topology-preserving simplification; OCD-ID stamped on every feature | 3d | E1-3 |
| E6-2 | PMTiles build + CDN hosting + protocol handler wiring | Single-archive tiles served; no tile server | 2d | E6-1 |
| E6-3 | **Spike (O6):** state-legislative density on low-end mobile | Go/no-go + LOD strategy documented by end wk 1 | 2d | E6-1 |
| E6-4 | Address → point → containing divisions (Census geocoder + point-in-polygon) | Full OCD stack returned for any valid US address; territory edge cases tested | 2d | E6-1 |

## E7 — Frontend (wk 5–10)

| ID | Ticket | AC | Est | Deps |
|---|---|---|---|---|
| E7-1 | App shell: Next.js RSC, MapLibre base, sonar basemap style | TTI <2s on throttled 4G (G3); Lighthouse perf ≥85 mobile | 3d | E6-2 |
| E7-2 | Layer rail + zoom-semantic layer logic + deck.gl pin/cluster layers | Layer toggle <1s; pins cluster below zoom 6; party-vs-ideology fill toggle | 4d | E7-1 |
| E7-3 | District polygon interactions (hover, tap, at-large + delegate edge cases) | Vacant seats render per spec; delegates labeled | 2d | E7-2 |
| E7-4 | Address search + "Your representation" stack card | E2E test: address → highlighted stack across enabled layers | 2d | E6-4, E7-2 |
| E7-5 | Dossier sidebar: identity, lean slider + explainer modal, legislative record | Opens <300ms from CDN; empty/pending states per spec | 4d | E5-2 |
| E7-6 | Dossier money sections: net-worth band viz, PTR timeline w/ committee overlay, FEC | Every row links to original filing; late flags render; band never a point | 4d | E7-5, E3 |
| E7-7 | Provenance footers + methodology page + corrections page | Every section shows source + timestamp; pages live and linked | 2d | E7-5 |
| E7-8 | Network view **behind flag** (deck.gl graph, typed edge toggles, edge receipts) | Stable on top-500 officials or stays flagged (resolves O2) | 4d | E5-4 |
| E7-9 | Compare mode *(P1 — build only if ahead of schedule)* | Aligned-row split view | 3d | E7-5 |

## E8 — Quality, Ops, Trust (continuous from wk 3)

| ID | Ticket | AC | Est | Deps |
|---|---|---|---|---|
| E8-1 | Freshness + SLA monitoring, alerting (roster 24h, votes 24h, PTR 24h) | Synthetic checks fail loudly; on-call doc | 2d | E2 |
| E8-2 | Public coverage dashboard (per-state completeness, source freshness, parse confidence) | Live page; numbers match warehouse | 2d | E5-1 |
| E8-3 | Privacy-respecting analytics (self-hosted PostHog/Plausible), event taxonomy for G5 metrics | Dossier-open + layer-toggle events tracked without individual profiles | 1d | E7-1 |
| E8-4 | Load test + CDN cache tuning to G3 targets | p75 map TTI <2s, sidebar p95 <300ms under 10× expected launch load | 2d | E7 |
| E8-5 | Symmetric-presentation audit checklist v1 + run | Documented pass before launch | 1d | E7 |

## E9 — Launch (wk 10–12)

| ID | Ticket | AC | Est | Deps |
|---|---|---|---|---|
| E9-1 | Counsel review integration (O3 strings: net-worth, late-flags, Known-for policy) | Approved copy in string tables; no launch without | 1d + external | E3-6, E5-5 |
| E9-2 | Private beta (50–100 users incl. journalists), structured feedback + error-report flow | Corrections pipeline exercised end-to-end at least once | 2d | all |
| E9-3 | OG cards / deep links per official | Shareable dossier URLs unfurl correctly | 1d | E7-5 |
| E9-4 | Launch runbook, rollback plan, postmortem template | Dry-run complete | 1d | E8 |

---

## Totals & buffer
Sum ≈ **118 eng-days** (excluding E7-9). At 70–80% realized capacity across 12 weeks that is ~2.5–3 FTE. **Pre-identified cuts, in order:** E7-8 network view (–4d), E3 internal-parser track (–13d, vendor-only), E7-9 already stretch.

## Key dates
| Wk | Milestone |
|---|---|
| 1 | O6 tile spike decision; O1 vendor selected |
| 4 | Federal data complete in warehouse (demo: query any member's full record) |
| 6 | Money pipeline dual-run live; state layer loaded |
| 8 | Internal demo: map + sidebar end-to-end on staging |
| 10 | Feature-complete; counsel copy in; beta starts |
| 12 | Launch go/no-go |

## Definition of Done (every ticket)
Code reviewed · tests passing (incl. dbt tests for data tickets) · provenance fields populated · dashboards/alerts updated if a new source or SLA · spec-section reference linked in PR.
