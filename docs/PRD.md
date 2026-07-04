# Beholden — Product Requirements Document
**Working name:** Beholden (candidate names: Periscope, Sunlight, Ledger)
**Version:** 1.0 Draft · July 2026
**Author:** Beholden Maintainers
**Status:** For review — architecture validated against current data landscape (July 2026)

---

## 1. Problem Statement

Americans cannot easily answer the question "who represents me, and what are they actually doing?" The public data exists — votes, bills, financial disclosures, campaign finance, ideology scores — but it is scattered across a dozen government systems, academic datasets, and paywalled aggregators, each with different identifiers, formats, and freshness. The cost of this fragmentation is civic: accountability requires effort most citizens can't spend, and the officials closest to daily life (state and local) are the least visible of all.

Beholden aggregates exclusively public-record data into a single interactive map of American representation — every federally and state-elected official plotted in the geography they represent, each one openable into a full accountability dossier: party, ideology score, legislative record, financial disclosures, and funding. It is a **political microscope built on provenance**: every fact on screen traces to an official source.

---

## 2. Product Principles

These are load-bearing. Every design and data decision gets tested against them.

1. **Provenance over polish.** Every displayed fact carries a source citation and a fetched-at timestamp. If we can't cite it, we don't show it.
2. **Ranges are ranges.** Financial disclosures are filed in dollar brackets with 30–45 day lag. We display bands, never fabricated precision. Credibility of the entire product depends on this.
3. **Descriptive, not prescriptive.** We show DW-NOMINATE scores, vote records, and trade filings. We do not label anyone "corrupt," "extreme," or "good." The user draws conclusions; we supply evidence.
4. **Symmetric by construction.** Every feature applies identically to every official regardless of party. No feature ships if it can only embarrass one side by design.
5. **Speed is a feature.** The "bounce around quickly" feel is core product identity. All joins happen at ETL time; the client never waits on an upstream API.

---

## 3. Goals

- **G1 — Coverage:** 100% of federal elected officials (541: President/VP, 100 senators, 435 representatives + 6 delegates) and ≥95% of state legislators (~7,400) plotted with complete dossiers at launch.
- **G2 — Freshness:** Votes and bill actions ≤24h stale; STOCK Act trade filings surfaced within 24h of publication by the Clerk/eFD; member roster changes within 24h.
- **G3 — Performance:** Time-to-interactive map <2s on 4G mobile; official sidebar opens with full dossier <300ms after tap (pre-joined data, no waterfall).
- **G4 — Trust:** Every fact in a dossier has a visible source link. Target: zero substantiated accuracy corrections per quarter that survive our methodology (i.e., errors from our pipeline, not from source data).
- **G5 — Engagement:** ≥40% of sessions open at least one official dossier; ≥15% of sessions use a layer toggle or the network view (validates the "microscope" thesis vs. a static directory).

## 4. Non-Goals (v1)

- **Local officials (city council, school board, county).** No free unified national dataset exists post Google Civic API shutdown (April 2025). This is Phase 3, via licensed data (Ballotpedia/Cicero/BallotReady) or a crowdsourcing program. Designing the schema to accept them from day one is in scope; ingesting them is not.
- **Editorial content / news aggregation.** No op-eds, no news feed, no "controversy" sections. Provenance discipline breaks down immediately with news.
- **User accounts, alerts, and personalization.** v1 is anonymous and read-only. Watchlists/alerts are Phase 2 — they're a retention engine but not needed to validate the core.
- **Predictive analytics.** No election forecasts, no "likelihood to vote yes" models. Descriptive only.
- **Non-US governments.** Architecture (OCD-IDs) supports international expansion; product does not.
- **Direct action tooling (contact-your-rep, petitions).** Deep-link out to official contact pages instead. Keeps us a lens, not a lobby.

---

## 5. Users & Stories

**Personas:** the Curious Citizen (came from a news story, wants "who is this person"), the Watchdog (journalist/researcher, wants depth, export, and receipts), the Educator (wants a classroom-safe, neutral civics tool), the Builder (wants our normalized data via API).

Priority-ordered stories:

- As a **citizen**, I want to enter my address (or use location) and instantly see everyone who represents me, from President down to state legislator, so that I understand my full representation stack in one view.
- As a **citizen**, I want to tap any official's pin and see their party, tenure, ideology position, notable legislation, and financial disclosures in a sidebar, so that I can evaluate them without visiting six websites.
- As a **watchdog**, I want to see an official's stock trades on a timeline next to their committee assignments and votes, so that I can identify patterns worth investigating — with links to the original filings.
- As a **watchdog**, I want to filter the map by layer (Senate, House, governors, state legislatures, executive appointees) and by attributes (party, ideology range, trading activity), so that I can ask questions like "show me every member who traded pharma stock while sitting on a health committee."
- As a **citizen**, I want the left/right lean slider to be explained in one tap (what DW-NOMINATE is, how it's computed), so that I trust it isn't the app's opinion.
- As an **educator**, I want to compare two officials side-by-side, so that students can see how representation differs across districts.
- As a **builder**, I want a documented public API of the normalized, cross-walked dataset, so that the commons we build compounds.
- **Edge cases:** vacant seats display as "Vacant (special election: date)"; officials with no PTR filings show "No trades disclosed" (not blank); at-large districts render as full-state fill; delegates/non-voting members are labeled as such; newly sworn-in members with <20 votes show "Ideology score pending (insufficient votes)."

---

## 6. Core Experience Specification

### 6.1 The Map (home surface)
- Full-bleed US map, dark "sonar" aesthetic (depth-graded basemap, cyan→magenta accent ramp reserved for data encoding, not decoration).
- **Zoom-semantic layers:** national zoom shows executive + Senate; state zoom adds House districts; deeper zoom adds state legislative chambers. User can override with explicit layer toggles.
- **Layer rail** (left edge): Executive · Senate · House · Governors · State Senate · State House · Agencies (Phase 2). Multi-select. Each layer renders as a distinct pin/choropleth treatment.
- Districts render as **vector tile polygons** (Census TIGER, cartographic boundary files) colored by party or by ideology gradient (user toggle). Pins are official avatars clustered at low zoom.
- **Address search / geolocate** resolves to the full OCD-ID division stack and highlights every polygon containing the point, with a "Your representation" stack card.

### 6.2 The Dossier Sidebar
Slides in on pin/district tap. Sections, in order:

1. **Identity:** photo, name, office, party, state/district, tenure, next election date, official links.
2. **Lean slider:** DW-NOMINATE dim-1 rendered on a −1…+1 track with party median markers for context. Tap-to-explain modal with methodology + Voteview citation. State legislators use Shor-McCarty scores (labeled as such, noting update cadence).
3. **Known for:** 3–5 bullet summary of signature legislation and committee roles. **Generation policy:** LLM-drafted from structured inputs only (sponsored bills that became law, committee chairs/rankings, leadership roles), every bullet carrying an inline citation to the underlying record; regenerated only when inputs change; cached and human-spot-checked (see §9).
4. **Legislative record:** sponsored/cosponsored bills (filterable by status: introduced → law), recent key votes with position, committee assignments. Links to Congress.gov / OpenStates records.
5. **Money — Disclosures:** estimated net worth as a **min–max band** (OpenSecrets-style methodology, disclosed), asset composition by category, liabilities. Source: parsed annual financial disclosures.
6. **Money — Trades:** STOCK Act PTR timeline — ticker, buy/sell, amount bracket, transaction date vs. filing date (late filings flagged per statutory 45-day rule). Overlay toggle: committee assignments on the same timeline. Every row links to the original PDF filing.
7. **Money — Campaign:** top contributors and industries (FEC, via ETL), cycle totals, cash on hand.
8. **Provenance footer:** every section lists source + last-refreshed timestamp.

### 6.3 The Network View (the "connected" in connected dataset)
- Toggle from map to a force/graph view centered on a selected official: edges to co-sponsors (weighted by frequency), committee co-members, shared top donors, and same-ticker trade clusters.
- Edges are typed and toggleable; clicking an edge shows the receipts (the actual bills/filings that constitute it).
- This is the exploratory research surface — rendered with deck.gl GraphLayer over the same entity graph that powers the sidebar.

### 6.4 Compare Mode
Pin two officials → split dossier with aligned rows (lean, key votes on the same bills, trading volume, funding sources). P1.

---

## 7. Data Architecture

### 7.1 Identity spine
**OCD Division IDs** are the geographic primary key (`ocd-division/country:us/state:tn/cd:6`); **person identity** is a crosswalk table keyed on an internal UUID mapping: bioguide ID (federal) ↔ FEC candidate IDs ↔ Voteview ICPSR ↔ OpenStates person ID ↔ Wikidata QID. The `congress-legislators` repo ships most of this crosswalk for federal; we maintain the extension. Every ingested record must resolve to spine IDs or it lands in a quarantine table for manual/agent resolution — never silently dropped, never fuzzy-matched into production.

### 7.2 Sources by tier (validated July 2026)

| Domain | Source | Access | Freshness | Notes |
|---|---|---|---|---|
| Members, bills, votes (federal) | **Congress.gov API v3** | Free key, 5,000 req/hr, 250/page | ≤ daily | The system of record. ProPublica API is closed to new keys; GovTrack API discontinued 2026 — do not build on either. |
| Member metadata, photos, socials | **unitedstates/congress-legislators** (GitHub) | Free, YAML/JSON bulk | Community-maintained | Also the bioguide↔FEC↔ICPSR crosswalk seed. |
| Ideology (federal) | **Voteview DW-NOMINATE** | Free CSV bulk | Per-Congress updates | Dim-1 score powers the lean slider. Academic gold standard; citable. |
| Ideology (state) | **Shor-McCarty** | Free academic release | ~Annual | Label the staleness in-product. |
| State legislators, bills | **OpenStates / Plural** | Free API + bulk | Varies by state | Best free state source; completeness varies — track per-state coverage as a published metric. |
| Trades (PTRs) | House Clerk + Senate eFD, via parsing layer | Official: free. Parsers: Quiver / FMP / Finnhub (paid) or self-built | Filings lag trades 30–45 days by law | v1: license one commercial feed for speed + build our own parser in parallel; cut over when parity reached. Dual-run validates both. |
| Annual disclosures / net worth bands | House Clerk annual index + Senate eFD | Free (index republished daily); PDFs need parsing | Annual + amendments | Some filings are scanned/handwritten → OCR + LLM extraction pipeline with human review queue (see §7.4). |
| Campaign finance | **FEC API** | Free key | Rolling | Contributors, industries (industry coding via OpenSecrets categories if licensed, else FEC raw). |
| District geometry | **Census TIGER/Line + cartographic boundary files** | Free shapefiles | Redistricting cycles | Congressional + state legislative (SLDU/SLDL). |
| Executive appointees (Phase 2) | **Plum Book (GSA data)** + Congress.gov nominations | Free | Per administration + rolling | Renders the FDA/EPA layer; confirmation votes link appointees back to senators. |
| Local officials (Phase 3) | Ballotpedia / Cicero / BallotReady | **Licensed** | Vendor SLA | Schema-ready in v1; ingested in Phase 3. |

### 7.3 Pipeline (bleeding-edge, but boring where it counts)
- **Ingestion:** scheduled + event-driven jobs (GitHub Actions or Temporal for orchestration with retries/backfills). Each source lands raw in **S3 (immutable, versioned)** — raw blobs are untrusted until validated.
- **Transform:** **DuckDB/dbt** over the lake for typed, tested transforms → **Postgres** as the serving store. **pgvector** columns on bills and officials power semantic search ("find officials active on water rights") and the entity-resolution agent.
- **Entity graph:** co-sponsorship, committee, donor, and trade-cluster edges materialized nightly into an adjacency store (Postgres first; graph DB only if traversal depth demands it — don't buy Neo4j on day one).
- **Serving:** the client never queries upstream. Per-official dossier JSON is pre-built and CDN-cached; map geometry ships as **PMTiles** (single-file vector tile archives on S3/CDN — no tile server to run). Nightly rebuild + intra-day patch on trade filings and votes.
- **LLM layer (agentic, bounded):** three sanctioned jobs — (1) disclosure PDF extraction with confidence scores and a human review queue below threshold, (2) "Known for" drafting from structured inputs with mandatory citations, (3) entity-resolution suggestions for the quarantine table. LLM output is never published without either deterministic validation or human review. Model calls logged; prompts versioned in git.

This mirrors the three-layer model proven in Fish: git/S3 for slow-moving immutable truth, Postgres+pgvector for structured and semantic serving, raw blobs quarantined until validated.

### 7.4 Data quality gates
- Row-count and referential-integrity checks on every transform (dbt tests); pipeline halts on spine-ID resolution rate <99.5%.
- **Dual-source validation** where possible (e.g., our PTR parser vs. licensed feed diffed nightly; discrepancies alarmed).
- Published **coverage dashboard** (public): per-state completeness, per-source freshness, parse-confidence distributions. Transparency about our own data is the brand.

---

## 8. Technical Stack

- **Frontend:** Next.js (App Router, RSC) + **MapLibre GL** for the basemap + **deck.gl** for pin, network, and heat layers. PMTiles via protocol handler — zero tile-server ops. Sidebar and compare views are server components hydrating from CDN-cached dossier JSON.
- **Mobile:** responsive web first; the map + sidebar interaction model is designed thumb-first. Native wrapper is P2.
- **Backend:** thin API layer (tRPC or REST) over Postgres for search, filters, and the network view; everything hot-path is pre-computed.
- **Search:** Postgres FTS + pgvector hybrid for officials/bills; Typesense/Meilisearch only if latency demands.
- **Infra:** S3 + CloudFront (or Cloudflare R2/CDN), Postgres (RDS/Neon), job orchestration (Temporal Cloud or Actions cron), IaC from day one.
- **Public API (P1):** read-only, keyed, rate-limited access to the normalized dataset. This is the ecosystem play — we become the thing the Google Civic shutdown left missing.

---

## 9. Trust, Neutrality & Legal

- **Methodology page** shipped at launch: how lean scores work, how net-worth bands are computed, what disclosure lag means, how "Known for" is generated. Every in-product number links here.
- **Corrections policy** with a public changelog. Errors acknowledged and timestamped, not silently patched.
- **"Known for" governance:** generated only from structured legislative facts; adjectives banned by prompt contract and lint (no "controversial," "champion," "notorious"); every bullet cites a record; regeneration diffs reviewed for the top-500-traffic officials.
- **Defamation posture:** we republish official records with sourcing and display estimates as labeled estimates. Counsel review of the net-worth methodology language and trade-flagging copy (late-filing flags state the statutory rule, not an accusation) before launch. *(Open question O3.)*
- **Neutral presentation audits:** quarterly check that color, ordering, and layout treat parties symmetrically (e.g., ideology gradient is a diverging ramp with neutral midpoint, not red-coded-as-danger).
- **No dark patterns:** no engagement-bait framing ("You won't believe what your senator traded"). Notifications (Phase 2) are factual: "New PTR filed by [name]."

---

## 10. Requirements

### P0 — Cannot ship without
| # | Requirement | Acceptance criteria (abridged) |
|---|---|---|
| P0-1 | Interactive US map with Senate + House + Governor layers, district polygons, official pins | Given national zoom, when user toggles House layer, then 435 districts render party-colored in <1s; pins cluster below zoom 6 |
| P0-2 | Address → representation stack | Given a valid US address, when submitted, then all containing divisions highlight and the stack card lists every official across enabled layers with correct OCD-ID resolution |
| P0-3 | Dossier sidebar with all §6.2 sections for federal officials | Given any federal official pin tap, then sidebar renders complete dossier in <300ms from CDN cache; every section shows source + timestamp; officials with no trades show explicit empty state |
| P0-4 | Lean slider (DW-NOMINATE) with explainer | Given a member with ≥20 roll-call votes, then dim-1 score renders with party medians; given fewer, then "pending" state; explainer modal cites Voteview |
| P0-5 | STOCK Act trade timeline with filing links | Given a member with PTRs, then each trade shows ticker, type, bracket, transaction + filing dates, late flag when >45 days, and a working link to the original filing |
| P0-6 | Net worth as labeled band | Then net worth always renders as min–max range with "estimate" label and methodology link; never a single number |
| P0-7 | ETL pipeline with quality gates | Given a nightly run, then dbt tests pass, spine resolution ≥99.5%, and freshness SLAs (§3 G2) are met or alerting fires |
| P0-8 | State legislature layer (OpenStates) | Given state zoom, then state legislators render with per-state coverage badge; states below completeness threshold labeled "partial data" |
| P0-9 | Methodology + corrections pages | Live at launch, linked from every dossier footer |

### P1 — Fast follow
Compare mode (§6.4) · Network view full release (§6.3 — ship behind a flag in v1 if stable) · Public read API · Cross-filter queries (committee × ticker × timeframe) · Executive/agency layer via Plum Book + nomination chains · Shareable deep links / OG cards per official · CSV export in dossiers.

### P2 — Architectural insurance
Local officials ingestion (schema must accept arbitrary OCD division depth now) · Watchlists + factual alerts · Historical time-scrubbing (map state at any past Congress — store slowly-changing dimensions now) · Native apps · i18n (Spanish first).

---

## 11. Success Metrics

**Leading (first 30–60 days):** dossier-open rate ≥40% of sessions (success) / 55% (stretch) · layer-toggle or network usage ≥15% of sessions · map TTI p75 <2s · sidebar p95 <300ms · D7 return rate ≥12% · data-error reports <5/week substantiated.
**Lagging (quarter+):** organic share of traffic (deep links to dossiers becoming citations in journalism/social) · API keys issued and active (ecosystem adoption) · per-state coverage climbing toward 100% · press citations with zero accuracy retractions.
**Measurement:** privacy-respecting analytics (no individual tracking — a transparency product should not surveil its users); Plausible/PostHog self-hosted.

## 12. Timeline & Phasing

- **Phase 1 (launch, ~12 wks eng):** federal-complete + state layer, P0 set. Wk 1–3 spine + ingestion for Congress.gov/legislators/Voteview/TIGER; wk 3–6 disclosure parsing (licensed feed live, own parser in dual-run) + FEC; wk 5–9 map/sidebar frontend; wk 8–10 quality gates + methodology content; wk 10–12 perf, counsel review, beta.
- **Phase 2 (quarter 2):** network view GA, compare, public API, agency layer, alerts.
- **Phase 3:** local officials via licensed data — go/no-go on vendor pricing vs. crowdsourcing program.
- **External timing:** November 2026 midterms are the natural traffic moment and the hard-ish deadline worth planning against; post-election roster churn is also the first big test of the 24h roster SLA.

## 13. Open Questions

- **O1 (data/cost, blocking Phase-1 vendor selection):** Quiver vs. FMP vs. Finnhub for the interim PTR feed — pricing, license terms for public display, and redistribution rights.
- **O2 (product):** Does v1 ship the network view behind a flag or hold entirely for Phase 2? Depends on graph materialization stability by wk 8.
- **O3 (legal, blocking launch copy):** Counsel sign-off on net-worth-band language, late-filing flags, and "Known for" generation policy.
- **O4 (data):** OpenSecrets industry-coding license for donor categorization, or ship FEC raw categories in v1?
- **O5 (design):** How the sonar/depth aesthetic handles the party-color problem — red/blue is legible but loaded; explore encoding party by pin form and reserving the cyan→magenta ramp for ideology.
- **O6 (eng):** PMTiles at state-legislative polygon density on low-end mobile — needs a spike in wk 1.

## 14. Risks

- **Source volatility** (the ProPublica/GovTrack/Google Civic pattern): mitigated by raw-lake immutability, dual-sourcing where possible, and building on official government sources first.
- **Parse errors in scanned disclosures** → wrong money data on a named person: mitigated by confidence-thresholded human review and dual-run vs. licensed feed; this is the single highest-severity error class.
- **Perceived bias**: mitigated by symmetric design audits, academic scoring, methodology transparency — and by never editorializing.
- **Scope gravity toward local**: the most-requested feature will be the one we explicitly deferred; hold the line with the public coverage roadmap.
