# Beholden — Expansion Plan: Deeper Data, Lower Levels, One Navigation Model

**Status:** Proposed roadmap (research-verified sources) · Pairs with PRD v1.0, DATA-CONTRACTS v1
**Thesis:** every step below is the same move repeated — *find the authoritative bulk source,
join it through the identity spine, publish it cited, and draw the connection as an evidenced
edge.* Nothing here requires new architecture; it fills structures the contracts already define.

---

## 0. Where we are (shipped)

Federal + state legislators (7,928 dossiers), party/ideology/legislative counts/FEC totals/
PTR filing links, private geocoding, layer control, zero-server publish. The dossier's
`graph_ref`, the `roll_calls`/`vote_positions`/`top_contributors` tables, and the §4 entity-graph
contract are **designed but empty** — they are this plan.

---

## 1. Deepen the data (federal first — sources verified)

### 1a. Individual voting records — THE next vertical
**Source (verified):** Voteview bulk CSVs, no key, already a registered source:
- `votes/HS119_votes.csv` — every member's position on every roll call, keyed by **ICPSR**
  (already in our crosswalk — the join is free).
- `rollcalls/HS119_rollcalls.csv` — per-vote metadata: date, question, result, yea/nay counts,
  `bill_number` (→ links into our `bills` spine and congress.gov).

**Pipeline:** ingest both → `roll_calls` + `vote_positions` (~537 × ~1,000 votes/session ≈ 500k
rows; DuckDB shrugs). **Key-vote selection** for the dossier's `key_votes[]` (top ~10): rank by
closeness (|yea−nay| small), salience (party-median split), and recency — a documented,
symmetric formula in the methodology page, never hand-picked.

**Serves:**
- Dossier: real `key_votes` with position + link to bill + roll-call record.
- **Co-voting similarity** ("votes with X 94% of the time"; party-median agreement) — computed
  pairwise per chamber; powers both a dossier stat and `cosponsorship`-class graph edges.
- Full per-member vote table later via a static per-person JSON (`/votes/{person_id}.json`).

### 1b. Itemized donors — the transparent money layer
**Source:** FEC API (key already in CI):
- `/schedules/schedule_a/by_employer/` + `/by_occupation/` per principal committee per cycle →
  fills the existing `top_contributors` table (org-level rollups, the OpenSecrets-style view).
- `/candidate/{id}/committees/` to resolve principal committees (we already store candidate ids).

**Contract care:** employer rollups are FEC's own aggregation of *itemized individual
contributions by reported employer* — describe them exactly that way (methodology page), never
as "corporate donations." Industry coding (NAICS-style buckets) is a later, clearly-labeled
derived layer (`source: internal`, methodology required).

**Serves:** dossier "Top contributors" (already in the UI contract); `shared_donor` graph edges
(same top-25 org across two members, evidence = the FEC aggregate rows).

### 1c. The entity graph — materialize §4
Nightly job computes typed, **evidence-carrying** edges from what 1a/1b land:
- `cosponsorship` (count of shared bills; evidence = bill list) — data already in spine
- `co_voting` (agreement % over shared roll calls; evidence = the roll-call sample)
- `committee` (shared assignments — needs committee sync, small congress.gov add)
- `shared_donor` (same top-org, same cycle; evidence = FEC aggregates; **caveat string required**)
Publish `/graph/neighborhood/{person_id}.json` (top ~25 edges per person, paginated evidence).
Client: lazy-loaded force-graph view (react-force-graph / sigma.js) reading static JSON — same
zero-server model. **Rule:** an edge with no receipts is a bug; correlation edges always carry
their caveat.

### 1d. Donor ↔ vote juxtaposition — last, and carefully
Only after 1a+1b exist. A dossier module: "Top contributors" beside "votes on bills in related
policy areas" — *side-by-side receipts, zero causal copy* (descriptive-not-prescriptive is the
legal and credibility shield). Bill→policy-area mapping already lands with E2 data.

### 1e. Federal rounding-out (cheap, high-value)
- **Committees + subcommittees** (congress.gov, small): fills dossier `committees[]` and
  `committee` edges; also unlocks PTR **committee_overlap** flags later.
- **Net-worth bands** (annual FD filings — same Clerk index we already parse, FilingType != P):
  publish the *filing links* now (like PTRs); banded estimates only with a methodology.
- **Senate eFD**: harder (session-gated site) — do after House proves the pattern.

---

## 2. Expand down: state → county → city

### 2a. State depth (now → next quarter)
- **Votes/bills:** OpenStates API v3 (key already in secrets) or per-session bulk exports —
  same shape as federal: bills, votes, sponsorships per state session. Start with 5–10 big
  states; scale by coverage quality. Feeds the same tables (`jurisdiction` column exists).
- **State campaign finance:** *the* gap in most tools. **followthemoney.org (NIMSP)** is the
  OpenStates-of-state-money — API + bulk, org-rolled contributions per state candidate.
  Evaluate licensing; it would light up `campaign_finance` on 7,400 state dossiers.
- **State ideology:** Shor–McCarty blocked on id crosswalk (documented); revisit only with a
  verified mapping. Co-voting similarity from OpenStates votes is our own honest substitute.

### 2b. County & municipal (the long tail — source-evaluation first)
**Reality:** ~90k local governments, no single national roster. Strategy = **structured sources
first, narrow scope first, scraping last**:
1. **Geometry & rosters of governments:** Census TIGER county polygons (same tile pipeline —
   trivial to add a `county` layer); Census *Governments* programs enumerate the units.
2. **People:** evaluate in order — Plural/OpenStates municipal coverage; **Cicero API**
   (Melissa) and **BallotReady/CivicEngine** (commercial, address→official down to city level;
   check nonprofit tiers); state SOS officeholder bulk files; Wikidata/Ballotpedia for mayors
   of the top ~100 cities (verifiable one-by-one).
3. **Pilot shape:** top 25 metros + one full state (e.g., TN) end-to-end — mayor + council +
   county executive/commission — to prove contracts scale before national ambition.
4. **Scraping (Firecrawl-class tools):** only for the residual, and only through the existing
   `extract_confidence` / `review_status` / quarantine machinery. Never straight to publish.

**Schema is ready:** `divisions.level` already enumerates `county`/`place`; OCD ids exist for
both (`.../county:davidson`, `.../place:nashville`). Tiles: add `us-counties-{vintage}.pmtiles`
(+ optionally top-metro `place` polygons) with the same stamper.

---

## 3. Navigating levels — the UX model

**Principle:** *the map answers "where"; the panel answers "who at every level."* Users think
in places, not layers. So:

### 3a. Zoom-adaptive layers by default ("Auto"), manual override kept
- **z3–5 (national):** states + CD only (what ships today as defaults).
- **z6–8 (state):** state chambers fade in (sldu/sldl at reduced opacity beneath CD lines).
- **z9+ (metro):** county (and later place) boundaries join; CD stays as outlines.
- The existing Layers control gains an **"Auto" master toggle** (default ON). Any manual
  checkbox flip switches to manual mode (sticky, per device) — power users keep exact control,
  everyone else never sees the overlap soup. Smooth opacity transitions, no popping.
- **Selected level never auto-hides** — if you're reading a state-senate dossier, that layer
  stays until you close it.

### 3b. The stack panel is the real level-switcher
Click/locate always resolves **every** level at the point (it already does). Upgrades:
- **Level tabs/accordion** in the panel: Federal / State / County / City — collapsed sections
  with counts, so ten officials at a point stay scannable.
- **"My ballot" view:** after address/geolocation, a single ordered card — every office that
  point elects, top to bottom. This becomes the flagship shareable surface.
- **Permalinks:** `#/p/{person_id}` and `#/d/{ocd_id}` hash routes so any dossier/division is
  linkable (zero-server friendly; huge for journalists).
- **Search grows people-search:** the topbar searches addresses today; add name search over a
  small static index (minisearch is already a dependency, index ships as JSON).

### 3c. Cross-level affordances
- Dossier header gains a **jurisdiction breadcrumb** (US → TN → TN-6) — each crumb selects that
  division on the map.
- District pages (division-level view listing its officials + election dates) become the
  natural landing for `#/d/` links.

---

## 4. Transparency features (the moat)

1. **Methodology pages** (`/methodology#...`): one anchor per derived thing — key-vote formula,
   donor rollups, similarity math, ideology explainer. The dossier UI already links to these
   anchors; write them as the features land. *A formula we can't explain publicly doesn't ship.*
2. **Public coverage dashboard:** render the already-published `coverage.json` as a page —
   per-source freshness vs SLA, per-state coverage %, unmatched-district list. Honesty as UI.
3. **Corrections policy + report-an-error:** per-dossier "report an issue" link (GitHub issue
   template initially). Public-record corrections log.
4. **Open data:** document the JSON endpoints as a public read API (they already serve
   contract-versioned documents); publish the repo (already planned) — reproducibility is the
   credibility feature.
5. **Provenance everywhere, forever:** every new module keeps the section source-stamp pattern;
   correlation edges carry caveats; empty states say *why* data is absent. (These are the three
   rules — restated because every feature above will be tempted to violate one.)

---

## 5. Sequencing

| # | Slice | Effort | Unlocks |
|---|---|---|---|
| 1 | **Votes vertical** (1a: roll calls + positions + key votes + co-voting stat) | ~1 session | Biggest dossier upgrade; first graph edges |
| 2 | **Zoom-adaptive layers + panel level-sections** (3a/3b core) | ~1 session | UX ready for more levels before they arrive |
| 3 | **Itemized donors** (1b: top contributors) + methodology page | ~1 session | Money transparency; `shared_donor` edges |
| 4 | **Entity graph + neighborhood view** (1c) | 1–2 sessions | The connections product |
| 5 | **Permalinks + people search + "my ballot"** (3b) | ~1 session | Shareability; journalist adoption |
| 6 | **Committees + county tile layer** (1e + 2b-geometry) | ~1 session | Cheap breadth |
| 7 | **State votes pilot (5–10 states) + followthemoney evaluation** (2a) | 1–2 sessions | State depth |
| 8 | **Donor↔vote juxtaposition** (1d) + counsel review of copy | after 1+3 | The accountability payoff |
| 9 | **Local pilot: top-25 metros + 1 full state** (2b) | multi-session | The long-tail beachhead |

Each slice ships end-to-end (fetch→spine→build→UI→live validation) like every vertical so far.

---

*Prepared 2026-07-05. Sources verified this date: Voteview votes/rollcalls bulk (200, no key);
FEC schedule_a aggregates (keyed); OpenStates API/bulk (keyed/open); Census TIGER counties;
House Clerk FD index (in production). Shor–McCarty documented as blocked on crosswalk.*
