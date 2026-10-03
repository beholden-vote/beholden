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
    "methodology_id": "networth-band-v1", // nullable; links to /methodology#id
    "grade": "A",                        // enum A|B|C|D — see §1.1
    "grade_reason": "official_structured" // registered reason implying the grade
  }
}
```

Rule: **no provenance, no publish.** The dossier builder rejects sections missing this envelope.

### 1.1 Credibility grades

`grade` says how a fact was **obtained**; `methodology_id` says how it was **computed**. A DW-NOMINATE score is grade `A` (its inputs are bulk official records) *and* carries a methodology anchor (the number is ours).

| Grade | Reason (registered enum) | Meaning |
|---|---|---|
| `A` | `official_structured` | Bulk feed, API, or a link to an official filing. Deterministic, no model in the path. |
| `B` | `official_document_text` | Official document, born-digital text. Fixed-rule parse, verified, reconciled against a control total the document carries. |
| `C` | `official_document_ocr` | Official document whose text was recovered by OCR, then anchor-verified and reconciled. |
| `D` | `derived_geometry`, `inferred_from_roster`, `crowd_edited` | Derived or inferred — our reasoning over official inputs, not a transcription. |

Rules:

1. **A grade describes extraction method, never a failed validation.** Data that fails a quality gate is withheld and quarantined, *never* downgraded and published. A control-total mismatch means the numbers are wrong, not low-confidence — the fail-closed rule is unchanged by grading.
2. **The pair is validated, not just the grade.** `grade` must equal the grade its `grade_reason` implies (`config.GRADE_REASONS`), so an envelope cannot claim `A` for an OCR'd fact.
3. **A source may emit several grades.** Minutes are `B` for a printed roll call and `D` for a position inferred from a present roster. The source registry supplies the default; the builder takes a per-section override.
4. **Ungraded is a publish failure**, treated exactly as a null `retrieved_at`.
5. **Grades are presentation-neutral (Rule 0).** They must not correlate with party, and must never render as a verdict on an official or a locality. Grade symmetry is covered by the quarterly neutral-presentation audit.

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
  bill_id      TEXT PRIMARY KEY,           -- 'us/119/hr/2384' | 'tn/114/sb-512' (see id note below)
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

**Legislative id formats (additive note, WO-17).** Federal bills keep
`us/{congress}/{type-slug}/{number}` (e.g. `us/119/hr/2384`). State bills
(OpenStates v3 ingest) use `{state}/{session}/{identifier-slug}` where both the
session identifier and the bill identifier are lowercased with whitespace runs
collapsed to `-` — TN's "SB 512" in session "114" is `tn/114/sb-512`
(`sources/openstates_votes.state_bill_id`). Roll calls follow the same split:
federal `us/{congress}/{chamber}/{rollnumber}`, state
`{state}/{session}/{chamber}/{ocd-vote-uuid}` (the uuid tail of the API's own
`ocd-vote` id). The two families never collide, so bills, roll_calls,
sponsorships and vote_positions hold both jurisdictions in the same tables,
disambiguated by `jurisdiction` / the id prefix.

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
| `tiles/us-places-{vintage}.pmtiles` | `places` | `ocd_id`, `geoid`, `state`, `name`, `kind` — see §8.5 |

**Join rule:** tiles carry geometry + OCD-ID **only** — no member data baked in. The client joins a tiny "style feed" (`/stylefeeds/{layer}.json`: `ocd_id → {party, ideology_dim1, vacant}`) to color polygons. This keeps tiles immutable for a full redistricting cycle while colors update daily, and it is the mechanism that keeps map state and dossier data from ever disagreeing.

Pin layer: `/pins/{layer}.json` — `[{ person_id, ocd_id, lat, lng (division centroid or office point), photo_url, party }]`, deck.gl IconLayer with clustering client-side.

---

## 6. Source Registry (enum)

`congress.gov` · `unitedstates_legislators` · `voteview` · `shor_mccarty` · `openstates` · `house_clerk` · `senate_efd` · `vendor:quiver|fmp|finnhub` (one selected per O1) · `fec` · `census_tiger` · `census_acs` · `census_gazetteer` · `wikidata` · `wa_pdc` · `gsa_plumbook` (Phase 2) · `internal` (derived; must reference upstream sources in methodology).

**Local sources are registered per locality** (WO-22): `sumner_county` · `hendersonville`. There is no national roster of local officials, so coverage, freshness and grade are only meaningful per government — one registry row, one coverage row, one SLA each. Local person identifiers are namespaced `local:<locality>` rather than enumerated in the `person_identifiers.id_scheme` CHECK, because no identifier authority exists below the state level.

Adding a source = adding an enum value + a methodology entry + a freshness SLA row in the coverage dashboard + **a default `grade_reason` (§1.1)**. No unregistered source may appear in a provenance envelope, and no source may publish without a registered grade reason (both enforced by dossier-builder validation).

---

## 7. Versioning & Compatibility

- Dossier and graph documents carry `schema_version`; clients pin a major version. Additive fields allowed within a major; removals/renames bump it, and both versions publish in parallel for ≥60 days.
- ETL releases are git-tagged; `pipeline_version` in every envelope makes any published fact reproducible from the raw lake.
- The public API (P1) serves these same contracts verbatim — internal and external consumers read identical documents, so the API costs nothing extra to keep honest.

---

## 8. v1.1 additions (in progress)

Everything in this section is **additive** — no v1 field is removed or renamed, so
`schema_version` stays `1.0`. Each subsection names the work order that ships it and is
normative for that work order. A subsection describes shipped behaviour only once its
status line says **shipped**; until then it is the target, not a description of production.

### 8.1 Stamps, and what "unchanged" means — WO-33 · **shipped**

Three values in a served document record *when* rather than *what*:

| Stamp | Where |
|---|---|
| `generated_at` | top level of every document |
| `pipeline_version`, `retrieved_at` | inside every provenance envelope: a dict stored under exactly one of the keys `provenance`, `votes_provenance`, `committees_provenance` |
| `as_of` | top level of a graph neighborhood |

Until WO-33, every one of them changed on every run, so no document was ever byte-identical
to the previous night's and every object was rewritten nightly whether or not a single fact
had moved.

**Rule.** A served object is replaced only when its content **excluding stamps** changes. The
publish stage computes a digest over the canonical JSON with exactly the stamps above
removed, stores it as object metadata, and skips the write when the stored digest matches.

**Consequence, stated plainly because it changes what a reader is told.** A document's stamps
now read *"as of the run in which this document last changed"*, not *"as of last night"*. A
dossier whose facts have not moved since 12 September carries 12 September stamps even
though the source was re-checked every night since. *Last checked* is therefore a separate
fact with a separate home: `coverage.json → sources[<source>].retrieved_at`, rewritten every
run. A client shows both — **"checked ‹coverage date› · unchanged since ‹envelope date›"** —
and never presents the envelope date alone as the time of the last check.

**The direction that must never be wrong.** Excluding a field from the digest means a change
to it will not be published. That is correct for a stamp and a silent staleness bug for a
fact. The stamp list above is closed: nothing is added to it without a contract change, and
any field carrying a fact — including fact-bearing dates such as an ideology score's
`as_of` — stays in the digest.

The three envelope keys are part of that closed list and are matched by exact name, not by
a `*provenance` suffix. The failure is chosen: an envelope written under a new key is not
recognised, so its stamps stay in the digest and every document carrying it is re-uploaded
nightly — visible in the write-budget line and failed by name in
`test_publish_stability.py` — instead of a suffix rule quietly excluding fields of a key
nobody reviewed. `legislative.votes_provenance` and `legislative.committees_provenance`
are in the list because the legislative section cites more than one source and carries
an envelope for each.

Non-JSON objects (tiles, `robots.txt`) are compared on their raw bytes, as before.

> **Optional `changed_at` (WO-37).** `coverage.json → sources[<source>]` may carry
> `changed_at`, the date that source's published content last changed. A client with both
> dates shows "checked ‹retrieved_at› · unchanged since ‹changed_at›"; without it, only
> "checked". Additive; no pipeline change is required for clients to read it.

### 8.2 Pins — WO-32 · **shipped**

`/pins/{layer}.json` rows gain `term_ends`: the ISO date the current term ends, or `null`
where the source publishes none. Never inferred.

### 8.3 Votes, roll calls, bills — WO-23a · **shipped**

Three artifacts, all keyed by ids the warehouse already uses. Ids are path-like and are used
**as the object key verbatim**; they contain only `[a-z0-9/._-]`, a test pins that, and the
writer refuses to publish a key outside that set. A bill id is `us/{congress}/{type}/{number}`
(`us/119/hr/2384`). A roll-call id is `us/{congress}/{house|senate}/{n}` (`us/119/house/312`),
where `n` is Voteview's congress-cumulative roll number — not the clerk's per-session number,
which appears only inside the official `url`.

**`/votes/{person_id}.json`** — one member's complete record for the current scope. Every
sitting member of the House and Senate has one; a member with no recorded position gets
`total: 0` and `votes: []`, never a missing file, and every member's file has the same fields.

```jsonc
{
  "schema_version": "1.0", "person_id": "…", "generated_at": "…",
  "scope": "119th Congress",
  "summary": {
    "total": 1042, "yea": 610, "nay": 380, "present": 2, "not_voting": 50,
    "party_decided": 990,      // yea/nay votes on roll calls where the member's party had a majority position
    "with_party": 930, "against_party": 60
  },
  "votes": [                   // every roll call the member was eligible for, newest first
    { "roll_call_id": "us/119/house/312", "held_at": "2026-06-12", "question": "On Passage",
      "position": "yea",       // 'yea' | 'nay' | 'present' | 'not_voting'
      "party_position": "yea", // the member's party's majority position; null if tied or absent
      "result": "Passed", "yea_count": 220, "nay_count": 210,
      "bill_id": "us/119/hr/2384", "bill_title": "…", "policy_area": "Health" }
  ],
  "provenance": { "source": "voteview", "methodology_id": "co-voting", … }
}
```

- **Eligibility.** `votes` holds the roll calls the member holds a position row for. Voteview
  separates "not a member of the chamber for this vote" (cast code 0) from "not voting" (9):
  only the second is a position. A roll call held before the member took office is absent from
  the list and from every count; it is never an absence. Voteview's paired and announced
  casts fold into `yea` / `nay`.
- **Order.** Newest first by `held_at` (a calendar date, `YYYY-MM-DD`; Voteview carries no
  time of day), ties broken by higher roll number first.
- **Votes that are not on a bill** — nominations, procedural motions, quorum calls — stay in
  the record with `bill_id`, `bill_title` and `policy_area` all `null`, and the question the
  source gives. A record that omitted them would misstate attendance. The same three fields
  are `null` while a roll call's bill has no congress.gov record in the warehouse yet (see
  *Landing*).
- **Computed fields.** `party_position`, `with_party`, `against_party` and `party_decided` use
  the published party-agreement rule and nothing else (`/methodology#co-voting`, hence the
  envelope's `methodology_id`): only the member's `yea` / `nay` votes, only on roll calls where
  their party had a majority; a party split evenly has no majority and the vote counts toward
  neither side. So `with_party + against_party == party_decided` always, and
  `with_party / party_decided` is the dossier's `party_agreement_pct` — the dossier withholds
  that percentage below `key_votes.MIN_AGREEMENT_VOTES`, these counts are always exact.
  `present` and `not_voting` count toward neither. No new measure is introduced here.

**`/rollcalls/{roll_call_id}.json`** — one vote, every sitting member's position.

```jsonc
{
  "schema_version": "1.0", "roll_call_id": "us/119/house/312", "generated_at": "…",
  "chamber": "house", "held_at": "2026-06-12", "question": "On Passage",
  "description": "…",          // Voteview's second text field; null when blank or the same as `question`
  "result": "Passed", "url": "https://clerk.house.gov/…",
  "bill_id": "us/119/hr/2384", "bill_title": "…", "policy_area": "Health",
  "totals": { "yea": 220, "nay": 210 },                                  // the official tally
  "by_party": [ { "party": "D", "yea": 4, "nay": 208, "present": 0, "not_voting": 2 } ],
  "positions": [ { "person_id": "…", "name": "…", "party": "R", "state": "TN",
                   "ocd_id": "…", "position": "yea" } ],
  "positions_cover": "current_members",
  "provenance": { "source": "voteview", … }
}
```

`by_party` is ordered alphabetically by party code — the same party-agnostic rule as the map
legend, never by size. `positions` is ordered by family name (then given name, then
`person_id`). `totals` is the chamber's official tally as Voteview publishes it: `yea` and
`nay` only, because its roll-call table carries no present or not-voting tally and a figure
the source does not give is omitted, never computed (a blank cell is `null`, never `0`).
`positions` and `by_party` cover only members currently in office — those are the positions
the warehouse holds — so they legitimately do not sum to `totals`, and `positions_cover` says
why. A client must not present either as the complete roll, and nothing is scaled or inferred
to make them agree. `url` is the official record (House Clerk or Senate), built from the
session and clerk numbers Voteview carries; where it cannot be built it is `null` and the
envelope cites Voteview's chamber page instead. `bill_id` is `null` for a roll call whose
bill is not in the warehouse, exactly as for the member's own record.

**`/bills/{bill_id}.json`** — one per bill that has had **at least one roll call**. Bills that
never reached a vote are linked out to congress.gov, not mirrored. Only the eight measure
types congress.gov serves have a page; a Senate nomination is not a bill.

```jsonc
{
  "schema_version": "1.0", "bill_id": "us/119/hr/2384", "generated_at": "…",
  "number": "H.R. 2384", "title": "…", "policy_area": "Health",
  "introduced_on": "2025-03-27", "status": "passed_chamber", "url": "https://www.congress.gov/…",
  "sponsor": { "person_id": "…", "name": "…", "party": "R", "state": "TN" },
  "cosponsors": { "total": 42,
                  "by_party": [ { "party": "D", "count": 10 }, { "party": "R", "count": 32 } ],
                  "members": [ { "person_id": "…", "name": "…", "party": "D", "state": "CA" } ] },
  "roll_calls": [ { "roll_call_id": "us/119/house/312", "held_at": "2026-06-12",
                    "question": "On Passage", "result": "Passed",
                    "yea_count": 220, "nay_count": 210 } ],
  "provenance": { "source": "congress.gov", … }
}
```

`status` is the spine's `bills.status` enum (§2), derived conservatively from congress.gov's
latest-action text. `sponsor` is `null` when congress.gov lists none; it and every cosponsor
carry the same four fields. `person_id` is `null` for a sponsor or cosponsor who is not a
current officeholder; the name still publishes. A `person_id` is linked by bioguide id only,
never by name. `cosponsors.total` counts current cosponsors — one who withdrew is neither
counted nor listed. `members` is ordered by family name, `by_party` alphabetically by party
code (never by size), `roll_calls` newest first.

A page exists only once the bill's congress.gov record has landed. A roll-call bill that could
not be fetched tonight has no page and no index row, is retried by the next fetch, and is
never published from whatever fields the warehouse happens to hold.

**`/bills/index.json`** — `{ schema_version, generated_at, bills, provenance }`, where `bills`
lists every mirrored bill (`bill_id`, `number`, `title`, `policy_area`, `last_vote_at`) in bill
id order, for client-side search.

**Counts, crawl policy.** `coverage.json → counts` gains `votes` (members with a file),
`rollcalls` and `bills` (bill pages; the index is not counted). `/votes/`, `/rollcalls/` and
`/bills/` are `Disallow`ed in `robots.txt`, inside its one group: thousands of small objects
under a guessable key, the same shape as `/dossiers/`.

**Landing.** The warehouse held only bills a sitting member sponsored, and no cosponsors.
Fetch now lands one raw record per distinct bill a current-Congress roll call references
(`raw/congress.gov/bills/{congress}-{type}-{number}.json`: `{bill_id, fetched_at, bill,
cosponsors}` — the bill-detail response and the complete cosponsor list). It resumes from the
hydrated lake, fetches what is new, and re-fetches a landed bill only when a single "bills
updated since" sweep, anchored on the cursor `roll_call_bills_swept_at` in the manifest's
congress.gov row, names it. It is paced by the one shared congress.gov client, a failed bill
keeps its last-good record or stays absent without costing the run anything else, and a
cosponsor list whose length matches neither of the bill detail's counts is refused. Transform
loads every landed record into `bills` (the sponsored-list row wins where both exist) and the
federal `cosponsor` role of `sponsorships`, again by bioguide id only. The dossier's own
`legislative` block and `key_votes` do not change.

### 8.4 Area facts — WO-34 · **shipped**

Facts about a place, as distinct from the people who represent it. Packed **one file per
state per level** — roughly a hundred objects nationally instead of one per county and city,
which would be some 22,000 objects rewritten whenever the Census revises anything.

**`/areas/county/{st}.json`**, **`/areas/place/{st}.json`** (`st` = lowercase USPS code):

```jsonc
{
  "schema_version": "1.0", "level": "county", "state": "tn", "generated_at": "…",
  "geography": { "vintage": 2024,        "provenance": { "source": "census_gazetteer", … } },
  "survey":    { "vintage": "2020-2024", "provenance": { "source": "census_acs", … } },
  "areas": {
    "47165": {                                   // keyed by Census GEOID
      "name": "Sumner County", "land_sqmi": 529.4,                    // ← geography
      "population":              { "estimate": 205000, "moe": null }, // ← survey, and below
      "households":              { "estimate": 76000,  "moe": 900 },
      "median_household_income": { "estimate": 78000,  "moe": 2100 },
      "median_age":              { "estimate": 39.4,   "moe": 0.3 }
    }
  }
}
```

Two sources feed one file, so it carries two envelopes: `name` and `land_sqmi` are cited by
`geography.provenance`; every `{estimate, moe}` pair by `survey.provenance`.

Areas are keyed by **GEOID**, not OCD id: the clicked polygon already carries its `geoid` as
a tile property (§5), so the join needs no name-slug agreement between the tile build and
this file. Every survey estimate travels with its margin of error (`moe`, same units, `null`
where the Bureau publishes none) — PRD principle 2, *ranges are ranges*: a client shows the
margin or does not show the number. A fact the Bureau withholds for an area is **omitted**,
never published as the Bureau's sentinel value.

**Sources and terms.** `census_acs` is the Census Data API, ACS 5-year, tables `B01003`,
`B11001`, `B19013`, `B01002` (estimate and margin of each); `census_gazetteer` is the national
counties and places Gazetteer files. Both are works of the U.S. Government, grade `A`
(`official_structured`). Both vintages are **pinned constants** in
`sources/census_areas.py` (ACS 2020-2024 is the newest the API serves; the Gazetteer vintage
matches the ACS *geography* year, 2024, so both describe the same set of places) — never
discovered at run time, and a snapshot of any other vintage halts the build. The Bureau's
terms for API users (`census.gov/data/developers/about/terms-of-service`) ask that a service
display *"This product uses the Census Bureau Data API but is not endorsed or certified by the
Census Bureau"* (on the Sources page) and forbid modifying content while still crediting the
Bureau, which is why nothing here computes or repairs a value. **The API requires a key**
(`CENSUS_API_KEY`; a keyless data call is answered with an HTML page, not data — observed
2026-10-03). When a fetch is due and it is unset, the fetch prints one loud `CENSUS_API_KEY is
NOT SET` line (a workflow annotation in Actions) and skips; the build then writes **no**
`areas/` object — the publish stage only ever PUTs, so the files already published stay exactly
as they are — and `coverage.json` reports `area_counties: 0` for that run. A snapshot still
inside its SLA is reused without a key. Nothing is written until every file has been validated,
so a failed check never leaves a partial tree.

**Withheld values.** The Bureau reports them as `-666666666`, `-999999999`, `-888888888`
(estimates) and `-222222222`, `-333333333`, `-555555555` (margins; `-555555555` marks a
controlled estimate such as a county's population, which has no sampling error), annotates
them, and annotates an open-ended median (`median+`/`median-`) whose number is a bound, not an
estimate. A withheld or annotated **estimate** omits that field for that area; a withheld
**margin** is `null`. Any other negative number halts the run as an undocumented sentinel.

**Places.** Only places with a government: Gazetteer `FUNCSTAT` `A` or `B`, **plus** every
consolidated city-county government. The Gazetteer carries those only as a `(balance)` row
with `FUNCSTAT` `F` (Nashville-Davidson, Indianapolis, Louisville/Jefferson, Augusta-Richmond,
Athens-Clarke, Butte-Silver Bow, Greeley County, Milford — eight rows in the 2024 file), and
the place tiles ship exactly those polygons (§8.5), so they publish by one rule: `FUNCSTAT`
`F` and `(balance)` in the `NAME`, never a list of GEOIDs. Census designated places (`S`),
any other `F` row and inactive or nonfunctioning entities (`I`, `N`) are dropped. `name` is
the Gazetteer's verbatim `NAME` (`Sumner County`, `Hendersonville city`,
`Nashville-Davidson metropolitan government (balance)`); the tile layer's bare name is a
presentation choice made there.

**Gates**, all fail-closed: pinned ACS and Gazetteer headers; per state, Σ county population
equals the state's own figure from the same API (to rounding); no negative population,
households, income, age, margin or land area (each runs at fetch and again at build); and,
at build, per state, the survey and Gazetteer agree on which counties exist and every place
that would publish has a survey row. `generated_at` is the snapshot's retrieval time, so an unchanged snapshot rebuilds
byte-identically.

### 8.5 Place tiles — WO-21 · **shipped**

`tiles/us-places-{vintage}.pmtiles`, layer `places`, **incorporated places only** — Census
designated places are statistical areas with no government and are dropped (LSAD `57`, and
`55` / `62`, the Puerto Rico equivalents, per the Bureau's feature catalog for the file). The
archive starts at z7 (the others at z3) and shares their maxzoom of 10.

| Property | Meaning |
|---|---|
| `ocd_id` | `ocd-division/country:us/state:{st}/place:{slug}`, by the same slug rule as `divisions.place_ocd` |
| `geoid` | 7-digit state + place FIPS — the join key to §8.4 |
| `state` | USPS code |
| `name` | bare name (`Hendersonville`) |
| `kind` | the Bureau's descriptor, lowercased (`city`, `town`, `village`, `borough`, …); `(balance)` stripped; empty when the Bureau gives none |

Two places in one state that slug to the same `ocd_id` are a **build failure**, resolved by an
explicit override keyed on GEOID — never by silently keeping one. The table is
`PLACE_SLUG_OVERRIDES`, in `spike/stamp_ocd_ids.py` and mirrored in `divisions.py` (a test pins
them equal); every member of a colliding group is listed, and a roster for one of them passes its
GEOID: `place_ocd(st, name, geoid)`.

The tile table in §5 also omits `tiles/us-counties-{vintage}.pmtiles` (layer `counties`:
`ocd_id`, `state`, `name`, `geoid`) and the non-interactive context archive; both ship.

### 8.6 Client routes — WO-35 · **shipped**

Hash routes, extending the existing `#/p/` and `#/d/` scheme. Ids are written with
`encodeURIComponent`, as today.

| Route | Opens |
|---|---|
| `#/p/{person_id}[/{tab}]` | a dossier (unchanged) |
| `#/d/{ocd_id}` | a place: its facts and everyone who represents it (unchanged) |
| `#/b/{bill_id}` | a bill |
| `#/v/{roll_call_id}` | a roll call |
| `#/c/{person_id}/{person_id}` | two officials compared |

Moving between altitudes — place, person, record — **pushes** a history entry, so the
browser's Back button steps up one level. Changing a tab within a dossier **replaces** it. A
reader's own location is never written into a URL: a place is addressed by division id, and a
remembered place is kept in the browser's storage only.

### 8.7 Position profile — WO-36 · *target*

**`/positions/{chamber}.json`**, `chamber` = `house` | `senate`. One file per chamber, every
sitting member, every member the same fields. There is **no composite score** and none is ever
added: each measure is published on its own, with its own formula at `/methodology`.

```jsonc
{
  "schema_version": "1.0", "chamber": "house", "generated_at": "…", "scope": "119th Congress",
  "members": [                       // ordered by person_id
    { "person_id": "…", "name": "…", "party": "R", "state": "TN",
      "nominate": { "dim1": 0.41, "dim2": -0.12 },   // Voteview; either may be null, never 0-filled
      "measures": {
        "with_own_party":   { "n": 930, "of": 990,  "pct": 93.9 },
        "with_other_party": { "n": 12,  "of": 140,  "pct": 8.6  },
        "missed":           { "n": 50,  "of": 1042, "pct": 4.8  },
        "party_line_by_policy_area": [               // ordered by policy_area, alphabetically
          { "policy_area": "Health", "n": 41, "of": 44, "pct": 93.2 } ]
      },
      "layout": { "x": -0.318, "y": 0.742 } }        // similarity map; null when below the vote floor
  ],
  "methodology_ids": { "with_own_party": "…", "with_other_party": "…", "missed": "…",
                       "party_line": "…", "layout": "…" },
  "provenance": { "source": "voteview", … }
}
```

- **Definitions** reuse §8.3's party-agreement rule: decided votes are `yea`/`nay` only; a
  party's position is its majority; an evenly split party has none and that vote counts toward
  neither side. `with_own_party` = votes with the member's own party majority, of the votes
  where it had one. `with_other_party` = of the roll calls where **both major parties had a
  majority and the majorities differed**, the votes that matched the *other* party's majority;
  it is `null` for a member of neither major party, never imputed. `missed` = `not_voting` of
  all roll calls the member was eligible for (§8.3 *Eligibility*). `party_line_by_policy_area`
  is `with_own_party` computed per bill policy area; roll calls with no policy area are left
  out of it and nowhere else.
- **Floors.** Any `pct` whose `of` is below `key_votes.MIN_AGREEMENT_VOTES` is `null`; `n` and
  `of` are always exact. A policy area below the floor is omitted for that member.
- **Layout.** A deterministic 2-D embedding of the agreement matrix `build/graph.py`
  `co_voting_edges` already computes: no randomness that is not seeded, coordinates rounded to
  3 decimals and scaled into `[-1, 1]` on both axes, the same procedure for both parties and
  both chambers. Axes carry no meaning; the file names no cluster, bloc or label and a client
  must not invent one.
- **Symmetry.** Every field is defined identically for every member regardless of party; a
  test builds the artifact from a fixture with parties swapped and requires equal measures.

### 8.8 Roster spec — WO-22b / WO-39 · *target*

Local rosters (Tennessee through CTAS and MTAS; metros through Legistar) are built against
**one** interface in `pipelines/beholden_etl/sources/roster.py`, so a new locality is a spec
and a fixture, not a new adapter. The module, not this document, is the source of truth for
names; this section fixes the shape.

- **`RosterSpec`** (frozen record): `locality_id` (stable slug, e.g. `tn-sumner-county`), `ocd_id`
  (the division, built with `divisions.place_ocd` / the county rule; a place sharing its name
  with another passes its GEOID), `level` (`county` | `place`), `name`, `body` (display name of
  the body, e.g. `County Commission`), `source` (`source_key` from `config.SOURCES`, `url`,
  `adapter` id), `seats` (`min`, `max` — the gate), `terms_ref` (pointer into
  `docs/research/` naming the licence determination this spec relies on — **a spec without one
  does not load**), `grade` (§credibility, `A`–`D`).
- **An adapter** is `parse(raw: bytes, spec) -> list[RosterRow]`, pure and offline-testable.
  `RosterRow`: `name`, `office_title`, `seat_label` (or `null` for at-large), `party` (`null` when
  the source does not state one — never `"NP"` or inferred), `term_start`, `term_end` (each
  `null` when not published), `contact` (any of `phone`, `email`, `url`), `source_row_url`.
- **Gates**, fail-closed per locality: seat count within `seats`, no duplicate `(office_title,
  seat_label)`, no blank name. A gate failure **withholds that locality** (see 8.10) and never
  stops the run; any other error class (a bug, a schema break in shared code) still fails the build.
- **Last-good retention.** A withheld locality keeps its previously published dossiers, pins
  and graph objects; they are not stale (WO-33's stale-deletion manifest must treat a withheld
  locality's keys as live) and its coverage state says `withheld` with the date of the roster
  being served.
- **Ids.** A person's id is keyed on the person within the locality — name, and the locality's
  `ocd_id` — not on the seat, so a member who changes districts keeps one dossier.
- **No empty graph documents** for an official with no edges.

### 8.9 Roll-call and bill ids beyond the federal government — WO-22b / WO-39 · *target*

§8.3's ids generalise to `{scope}/{session}/{body}/{n}` (roll call) and
`{scope}/{session}/{type}/{number}` (bill), four `/`-separated segments, characters
`[a-z0-9._-]` only, used verbatim as the object key under `/rollcalls/` and `/bills/`.

| Segment | Federal (today) | State | Local |
|---|---|---|---|
| `scope` | `us` | USPS code, lowercase (`tn`) | `{st}.{place-or-county-slug}` — the slug of the division's `ocd_id`, `slug_GEOID` where `PLACE_SLUG_OVERRIDES` applies (`tn.hendersonville`, `tn.sumner`) |
| `session` | Congress number (`119`) | the legislature's own session slug (`2025`, `2025-2026`) | calendar year of the meeting |
| `body` | `house` \| `senate` | `house` \| `senate` \| `assembly` | the body's slug (`council`, `commission`) |
| `n` | Voteview roll number | source's roll number | per body per session, assigned in meeting order and **never reassigned** |

The grammar guarantees no id of one kind can equal an id of another: `scope` never contains `/`
and the federal scope is exactly `us`. A writer refuses a key outside the character set or
without exactly four segments. `/votes/{person_id}.json` is unchanged; its rows carry the
roll-call id verbatim. A roll call whose `positions` cover fewer than all seated members says so
in `positions_cover`, as §8.3 already requires.

### 8.10 Coverage state per division — WO-22b · *target*

Who we cover, said plainly. **`/coverage/{st}.json`** (one file per state that has at least one
locality attempted; absence of a division means *not covered*):

```jsonc
{
  "schema_version": "1.0", "state": "tn", "generated_at": "…",
  "divisions": {                               // keyed by ocd_id
    "ocd-division/country:us/state:tn/county:sumner": {
      "state": "covered",                      // 'covered' | 'partial' | 'withheld'
      "seats_listed": 24, "seats_expected": 24,
      "roster_as_of": "2026-10-02",            // date of the roster being served
      "reason": null,                          // plain-language string when 'withheld' or 'partial'
      "source": "census-style source key", "votes": false } } }
```

`covered` = the gate passed this run. `withheld` = the gate failed this run and the last good
roster is still served (`reason` says which gate); if no last-good exists the division is
absent, not `withheld`. `partial` = some seats published, others not (e.g. vacant seats
declared by the source). `votes` is true only when roll calls for that body are published.
Divisions with no attempt do not appear: a client treats absence as **not covered yet** and
colours the polygon by that. Local polygons are never coloured by party (the sources do not
publish local party); coverage state is their fill. `coverage.json → counts` gains
`localities_covered`, `localities_partial` and `localities_withheld`.

### 8.11 State-sharded pins — WO-22b (feed) / WO-37 (loader) · *target*

Today every pin in the country is fetched at startup. Adding every county commission and city
council multiplies the rows, so the two local layers are sharded by state:

**`/pins/county/{st}.json`**, **`/pins/place/{st}.json`** — rows identical to today's pins
(§8.2 included), only the rows whose division is in that state; ordered as the monolithic file
is. A state with no rows has no file; a client treats 404 as an empty list. `states`, `cd`,
`sldu` and `sldl` stay monolithic. The monolithic `/pins/county.json` keeps publishing until
WO-37's loader has shipped and been verified live; removing it is then a separate, one-line
follow-up. The loader fetches a state's shard when the map first shows a division of that state
(or the reader's place resolves into it), caches it for the session, and never fetches a shard
for a state the reader has not reached.
