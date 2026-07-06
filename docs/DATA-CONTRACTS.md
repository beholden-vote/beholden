# Beholden — Data Contracts v1
**Status:** v1, deployed (the shipping pipeline + frontend implement these contracts) · Pairs with PRD v1.0 §7
**Conventions:** all timestamps UTC ISO-8601 · all money in integer USD cents where exact, bracket enums where disclosed · every serving-layer object carries a provenance envelope · schema changes are additive within a major version; breaking changes bump `schema_version`.

---

## 1. The Provenance Envelope (universal)

Every object served to the client embeds, at the section level:

```json
{
  "provenance": {
    "source": "congress.gov",            // enum, see §6
    "source_url": "https://...",          // deep link to the official record
    "retrieved_at": "2026-07-02T09:14:00Z",
    "pipeline_version": "2026.27.1",     // git tag of ETL release
    "methodology_id": "networth-band-v1" // nullable; links to /methodology#id
  }
}
```

Rule: **no provenance, no publish.** The dossier builder rejects sections missing this envelope.

---

## 2. Warehouse Spine (Postgres DDL, abridged)

```sql
-- ============ IDENTITY ============
CREATE TABLE persons (
  person_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  full_name     TEXT NOT NULL,
  given_name    TEXT, family_name TEXT,
  birth_year    SMALLINT,
  wikidata_qid  TEXT UNIQUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE person_identifiers (          -- the crosswalk
  person_id   UUID REFERENCES persons ON DELETE CASCADE,
  id_scheme   TEXT NOT NULL,               -- 'bioguide'|'fec'|'icpsr'|'openstates'|'ballotpedia'
  id_value    TEXT NOT NULL,
  is_primary  BOOLEAN DEFAULT true,
  PRIMARY KEY (id_scheme, id_value)
);
CREATE INDEX ON person_identifiers (person_id);

CREATE TABLE quarantine_identities (       -- unresolved records; never joined to prod
  quarantine_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  raw_payload   JSONB NOT NULL,
  source        TEXT NOT NULL,
  llm_suggestion JSONB,                    -- {person_id, confidence, rationale}
  resolved_by   TEXT, resolved_at TIMESTAMPTZ,
  resolution    TEXT CHECK (resolution IN ('matched','new_person','rejected'))
);

-- ============ GEOGRAPHY ============
CREATE TABLE divisions (
  ocd_id      TEXT PRIMARY KEY,            -- 'ocd-division/country:us/state:tn/cd:6'
  parent_ocd  TEXT REFERENCES divisions,
  level       TEXT NOT NULL,               -- 'country'|'state'|'cd'|'sldu'|'sldl'|'county' (shipped) | 'place' (P2-ready)
  name        TEXT NOT NULL,
  geoid       TEXT,                        -- Census GEOID crosslink
  valid_from  DATE NOT NULL,               -- redistricting-aware
  valid_to    DATE                         -- null = current
);

-- ============ OFFICE HOLDING (slowly-changing) ============
CREATE TABLE offices (
  office_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ocd_id      TEXT NOT NULL REFERENCES divisions,
  branch      TEXT NOT NULL,               -- 'legislative'|'executive'
  chamber     TEXT,                        -- 'senate'|'house'|'upper'|'lower'|null
  role        TEXT NOT NULL                -- 'senator'|'representative'|'governor'|'president'|...
);

CREATE TABLE terms (
  term_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  person_id   UUID NOT NULL REFERENCES persons,
  office_id   UUID NOT NULL REFERENCES offices,
  party       TEXT NOT NULL,               -- 'D'|'R'|'I'|'L'|'G'|'NP'|other coded
  start_date  DATE NOT NULL,
  end_date    DATE,                        -- null = incumbent
  end_reason  TEXT,                        -- 'term_end'|'resigned'|'died'|'expelled'|null
  is_vacant_marker BOOLEAN DEFAULT false   -- vacancy rows carry next special-election date in meta
);
CREATE INDEX ON terms (office_id) WHERE end_date IS NULL;  -- fast "current holder"
```

```sql
-- ============ LEGISLATIVE ============
CREATE TABLE bills (
  bill_id      TEXT PRIMARY KEY,           -- 'us/119/hr/2384' | 'tn/2026/sb/512'
  jurisdiction TEXT NOT NULL,
  session      TEXT NOT NULL,
  title        TEXT NOT NULL,
  status       TEXT NOT NULL,              -- 'introduced'|'committee'|'passed_chamber'|'passed_both'|'law'|'vetoed'|'failed'
  introduced_on DATE,
  latest_action_on DATE,
  policy_areas TEXT[],
  embedding    VECTOR(1024)                -- pgvector, semantic search
);

CREATE TABLE sponsorships (
  bill_id     TEXT REFERENCES bills,
  person_id   UUID REFERENCES persons,
  role        TEXT NOT NULL,               -- 'sponsor'|'cosponsor'
  is_original BOOLEAN,
  sponsored_on DATE,
  withdrawn_on DATE,                       -- preserved, not deleted
  PRIMARY KEY (bill_id, person_id, role)
);

CREATE TABLE roll_calls (
  roll_call_id TEXT PRIMARY KEY,
  bill_id      TEXT REFERENCES bills,      -- nullable (procedural votes)
  chamber      TEXT NOT NULL,
  question     TEXT NOT NULL,
  held_at      TIMESTAMPTZ NOT NULL,
  result       TEXT NOT NULL,
  yea_count    INTEGER,                    -- WO-12: chamber-wide tallies, verbatim
  nay_count    INTEGER                     --        from source; NULL = unrecorded
);

CREATE TABLE vote_positions (
  roll_call_id TEXT REFERENCES roll_calls,
  person_id    UUID REFERENCES persons,
  position     TEXT NOT NULL,              -- 'yea'|'nay'|'present'|'not_voting'
  PRIMARY KEY (roll_call_id, person_id)
);

CREATE TABLE committees (
  committee_id TEXT PRIMARY KEY,           -- thomas/openstates code
  jurisdiction TEXT NOT NULL,
  chamber      TEXT, name TEXT NOT NULL, parent_id TEXT REFERENCES committees
);
CREATE TABLE committee_memberships (
  committee_id TEXT REFERENCES committees,
  person_id    UUID REFERENCES persons,
  congress     SMALLINT,                   -- or session key for states
  role         TEXT NOT NULL,              -- 'member'|'chair'|'ranking'|'vice_chair'
  PRIMARY KEY (committee_id, person_id, congress)
);

-- ============ IDEOLOGY ============
CREATE TABLE ideology_scores (
  person_id   UUID REFERENCES persons,
  scheme      TEXT NOT NULL,               -- 'dw_nominate_dim1'|'shor_mccarty'
  score       NUMERIC(6,4),                -- null with status='pending'
  status      TEXT NOT NULL DEFAULT 'ok',  -- 'ok'|'pending_insufficient_votes'
  scope       TEXT NOT NULL,               -- '119' (congress) | 'tn-2026'
  computed_as_of DATE NOT NULL,
  PRIMARY KEY (person_id, scheme, scope)
);
```

```sql
-- ============ MONEY ============
CREATE TYPE amount_bracket AS ENUM (
  '1k_15k','15k_50k','50k_100k','100k_250k','250k_500k',
  '500k_1m','1m_5m','5m_25m','25m_50m','over_50m','unknown'
);

CREATE TABLE trades (                      -- STOCK Act PTRs
  trade_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  person_id     UUID NOT NULL REFERENCES persons,
  filing_id     TEXT NOT NULL,             -- Clerk/eFD document ID
  filing_url    TEXT NOT NULL,             -- link to original PDF — REQUIRED
  ticker        TEXT,                      -- nullable (non-listed assets)
  asset_name    TEXT NOT NULL,
  asset_type    TEXT,                      -- 'stock'|'option'|'bond'|'crypto'|'fund'|'other'
  txn_type      TEXT NOT NULL,             -- 'purchase'|'sale_full'|'sale_partial'|'exchange'
  amount        amount_bracket NOT NULL,
  owner         TEXT,                      -- 'self'|'spouse'|'joint'|'dependent'
  transacted_on DATE NOT NULL,
  filed_on      DATE NOT NULL,
  late_by_days  SMALLINT GENERATED ALWAYS AS
                (GREATEST(0, (filed_on - transacted_on) - 45)) STORED,
  source        TEXT NOT NULL,             -- 'vendor:quiver'|'internal'
  extract_confidence NUMERIC(4,3),         -- internal parser only
  review_status TEXT DEFAULT 'auto'        -- 'auto'|'human_verified'|'quarantined'
);
-- Publish rule: review_status <> 'quarantined' AND
--   (source LIKE 'vendor:%' OR extract_confidence >= threshold OR review_status='human_verified')

CREATE TABLE net_worth_estimates (
  person_id    UUID REFERENCES persons,
  disclosure_year SMALLINT NOT NULL,
  min_cents    BIGINT NOT NULL,
  max_cents    BIGINT NOT NULL,            -- band, never a point: CHECK (max_cents >= min_cents)
  methodology_id TEXT NOT NULL,            -- 'networth-band-v1'
  filing_url   TEXT NOT NULL,
  PRIMARY KEY (person_id, disclosure_year, methodology_id)
);

CREATE TABLE campaign_finance_cycles (
  person_id     UUID REFERENCES persons,
  cycle         SMALLINT NOT NULL,         -- 2026
  fec_committee_id TEXT NOT NULL,
  total_raised_cents BIGINT, total_spent_cents BIGINT, cash_on_hand_cents BIGINT,
  as_of         DATE NOT NULL,
  PRIMARY KEY (person_id, cycle, fec_committee_id)
);
CREATE TABLE top_contributors (
  person_id   UUID, cycle SMALLINT,
  contributor_name TEXT NOT NULL,          -- employer/org rollup per FEC methodology
  total_cents BIGINT NOT NULL,
  rank        SMALLINT NOT NULL,
  PRIMARY KEY (person_id, cycle, rank)
);
```

---

## 3. Dossier JSON Contract (serving layer)

One document per official, CDN-cached at `/dossiers/{person_id}.json`. This is the sidebar's entire data source — **the client makes zero additional calls to render a dossier.**

```jsonc
{
  "schema_version": "1.0",
  "person_id": "8f3c…",
  "generated_at": "2026-07-03T06:00:12Z",

  "identity": {
    "full_name": "…", "photo_url": "…",
    "office": { "role": "representative", "ocd_id": "ocd-division/country:us/state:tn/cd:6",
                "display": "U.S. House · TN-6", "chamber": "house" },
    "party": { "code": "R", "display": "Republican" },
    "tenure": { "first_took_office": "2019-01-03", "current_term_ends": "2027-01-03" },
    "next_election": "2026-11-03",
    "status": "incumbent",                      // 'incumbent'|'vacant'|'delegate_nonvoting'
    "official_links": [{ "type": "official_site", "url": "…" }],
    "provenance": { … }
  },

  "ideology": {
    "scheme": "dw_nominate_dim1",
    "score": 0.512,                             // null when status != 'ok'
    "status": "ok",                             // 'ok'|'pending_insufficient_votes'
    "context": { "party_median": 0.48, "chamber_median": 0.09 },
    "scope": "119th Congress",
    "explainer_url": "/methodology#dw-nominate",
    "provenance": { "source": "voteview", … }
  },

  "known_for": {
    "bullets": [
      { "text": "Primary sponsor of H.R. 2384, signed into law June 2025.",
        "citations": [{ "type": "bill", "id": "us/119/hr/2384", "url": "https://congress.gov/…" }] }
    ],
    "generation": { "model_run_id": "kf-2026.27-…", "inputs_hash": "…", "policy": "descriptive-v1" },
    "provenance": { … }
  },

  "legislative": {
    "counts": { "sponsored": 24, "cosponsored": 312, "became_law": 3 },
    "recent_bills": [ { "bill_id": "…", "title": "…", "role": "sponsor",
                        "status": "law", "url": "…" } ],       // top 10; full list via API
    "key_votes": [ { "roll_call_id": "…", "question": "…", "position": "yea",
                     "held_at": "…", "url": "…" } ],           // top 10 by salience score
    "committees": [ { "name": "Energy & Commerce", "role": "member",
                      "subcommittees": ["Health"] } ],
    "provenance": { … }
  },

  "money": {
    "net_worth": {
      "band": { "min_cents": 210050000, "max_cents": 1834000000 },
      "display": "$2.1M – $18.3M (estimate)",   // pre-formatted, counsel-approved template
      "disclosure_year": 2025,
      "methodology_id": "networth-band-v1",
      "filing_url": "…", "provenance": { … }
    },
    "trades": {
      "summary": { "count_12mo": 14, "last_filed_on": "2026-06-21", "late_filings": 1 },
      "items": [ {
        "ticker": "PFE", "asset_name": "Pfizer Inc.", "txn_type": "purchase",
        "amount_bracket": "15k_50k", "owner": "spouse",
        "transacted_on": "2026-05-02", "filed_on": "2026-06-20",
        "late_by_days": 4,
        "committee_overlap": ["Energy & Commerce / Health"],   // committees held on txn date
        "filing_url": "…"                                       // REQUIRED per row
      } ],
      "empty_state": null,                       // or "no_trades_disclosed"
      "provenance": { … }
    },
    "campaign": {
      "cycle": 2026,
      "totals": { "raised_cents": …, "spent_cents": …, "cash_on_hand_cents": … },
      "top_contributors": [ { "name": "…", "total_cents": …, "rank": 1 } ],
      "industries_available": false,             // Open Q O4
      "provenance": { "source": "fec", … }
    }
  },

  "graph_ref": "/graph/neighborhood/{person_id}"  // network view fetches separately
}
```

**Contract rules:** money values are integer cents; trade amounts are bracket enums only; `filing_url` is non-nullable on every trade row and every net-worth object; empty states are explicit strings, never missing keys; `display` strings for sensitive copy (net worth, late flags) come from the counsel-approved string table, not composed client-side.

---

## 4. Entity Graph Contract

Materialized nightly. Neighborhood endpoint returns nodes + typed edges; **every edge carries evidence** — an edge with no receipts is a bug.

```jsonc
{
  "center": "8f3c…",
  "as_of": "2026-07-03",
  "nodes": [ { "person_id": "…", "name": "…", "party": "R",
               "office_display": "U.S. House · TN-6", "ideology_dim1": 0.51 } ],
  "edges": [
    {
      "type": "cosponsorship",                 // 'cosponsorship'|'committee'|'shared_donor'|'trade_cluster'
      "a": "8f3c…", "b": "77aa…",
      "weight": 18,                            // type-specific: bill count / shared committees / $ overlap rank / co-traded tickers
      "window": "119th Congress",
      "evidence": [
        { "kind": "bill", "id": "us/119/hr/2384", "url": "…" }
        // capped at 25 inline; "evidence_total": 18 and API paging for the rest
      ],
      "evidence_total": 18
    },
    {
      "type": "trade_cluster",
      "a": "8f3c…", "b": "19bd…",
      "weight": 3,
      "window": "P12M",
      "evidence": [ { "kind": "trade_pair", "ticker": "PFE",
                      "a_trade_id": "…", "b_trade_id": "…",
                      "a_filing_url": "…", "b_filing_url": "…" } ],
      "evidence_total": 3,
      "caveat": "co-trading is temporal coincidence in public filings; no causal claim"
      // caveat string is part of the contract for this edge type and must render in UI
    }
  ]
}
```

Edge-type definitions (methodology page mirrors these): **cosponsorship** = count of bills where both appear as sponsor/cosponsor in window; **committee** = count of shared committee assignments in current congress/session; **shared_donor** = both persons have the same top-25 contributor org in the same cycle; **trade_cluster** = same ticker traded within a 30-day window by both. Trade-cluster and shared-donor edges always carry their `caveat` string.

---

## 5. Map Tile & Layer Contract

PMTiles archives on CDN, one per geometry family, redistricting-versioned in the path:

| Archive | Layers | Feature properties (every feature) |
|---|---|---|
| `tiles/us-states-{vintage}.pmtiles` | `states` | `ocd_id`, `name`, `geoid` |
| `tiles/us-cd-{vintage}.pmtiles` | `districts` | `ocd_id`, `state`, `district_num`, `at_large` (bool) |
| `tiles/us-sld-{vintage}.pmtiles` | `sldu`, `sldl` | `ocd_id`, `state`, `chamber`, `district_num` |

**Join rule:** tiles carry geometry + OCD-ID **only** — no member data baked in. The client joins a tiny "style feed" (`/stylefeeds/{layer}.json`: `ocd_id → {party, ideology_dim1, vacant}`) to color polygons. This keeps tiles immutable for a full redistricting cycle while colors update daily, and it is the mechanism that keeps map state and dossier data from ever disagreeing.

Pin layer: `/pins/{layer}.json` — `[{ person_id, ocd_id, lat, lng (division centroid or office point), photo_url, party }]`, deck.gl IconLayer with clustering client-side.

---

## 6. Source Registry (enum)

`congress.gov` · `unitedstates_legislators` · `voteview` · `shor_mccarty` · `openstates` · `house_clerk` · `senate_efd` · `vendor:quiver|fmp|finnhub` (one selected per O1) · `fec` · `census_tiger` · `gsa_plumbook` (Phase 2) · `internal` (derived; must reference upstream sources in methodology).

Adding a source = adding an enum value + a methodology entry + a freshness SLA row in the coverage dashboard. No unregistered source may appear in a provenance envelope (enforced by dossier-builder validation).

---

## 7. Versioning & Compatibility

- Dossier and graph documents carry `schema_version`; clients pin a major version. Additive fields allowed within a major; removals/renames bump it, and both versions publish in parallel for ≥60 days.
- ETL releases are git-tagged; `pipeline_version` in every envelope makes any published fact reproducible from the raw lake.
- The public API (P1) serves these same contracts verbatim — internal and external consumers read identical documents, so the API costs nothing extra to keep honest.
