# State campaign-finance source evaluation — FollowTheMoney.org (NIMSP)

**WO-7 Part B · research deliverable · REPORT ONLY (no ingest)**
Author: Beholden Maintainers. Verification date: **2026-07-05** (all URLs/terms probed with
`curl`/fetch on that date; anything not directly observed is flagged as such).

## TL;DR / recommendation

**Conditional NO-GO on the current plan; NO-GO outright unless a license exception is secured
in writing.** FollowTheMoney (FTM / the former National Institute on Money in State Politics,
NIMSP) has the coverage and the record shape we want, and a working free JSON API. **But its
data is published under Creative Commons Attribution-NonCommercial-ShareAlike 3.0 US, with a
hard "up to 1,000 records per year" default cap and an explicit "shall not be... sold to third
parties" clause.** Redistributing derived aggregates across ~7,400 state dossiers on a public
site is (a) far beyond 1,000 records and (b) legally gated by the NonCommercial + ShareAlike
terms. This is a **licensing blocker, not a technical one.** Go only after FTM grants an
expanded-access / redistribution exception in writing; otherwise defer state money.

---

## 1. What FTM is and what was verified (observations, 2026-07-05)

FTM/NIMSP is the standard aggregator of **state** campaign-finance disclosure — the
"OpenStates of state money." It normalizes 50-state disclosure filings into candidate-level
totals and contributor rollups (by donor and by economic interest / sector).

### 1a. API exists, is free, JSON-capable — VERIFIED
- `https://www.followthemoney.org/our-data/apis` (fetched 2026-07-05): "The Institute's APIs
  are **immediately available for use after you create a free myFollowTheMoney account**" and
  are pitched to "**Create tables of state-level campaign-donor data to display on your blog or
  website.**"
- Documentation (`/our-data/apis/documentation`, fetched 2026-07-05) gives the base call shape:
  `http://api.followthemoney.org/entity.php?eid=#######&APIKey=XXXXXXXX&mode=xml`, and states
  `"mode=xml" can be replaced by "mode=json" if you desire json output.` Full parameter tables
  live in a PDF: `/assets/FollowTheMoney-API.pdf` (referenced, not parsed in this run).
- **Live probe (2026-07-05):** `curl "https://api.followthemoney.org/?s=TX&y=2022&f-fc=2&mode=json&APIKey="`
  → **HTTP 200** with body `{"error":"Invalid API Key"}`. This confirms the aggregate endpoint
  is up, honors `mode=json`, and requires a key. (`entity.php` over `http://` returned an SSL
  redirect notice — use HTTPS.)

### 1b. Record shape — org rollups per candidate: YES (per FTM's own docs/examples)
FTM's "Ask Anything" aggregate API groups contributions and returns candidate-level records
plus rollups by contributor and by economic interest/sector. Their own materials note "Unique
Candidate ID has been replaced by **Entity ID** (`eid`)", and that consumers "display the
candidate's overall total, as well as the candidate's total from top economic sectors" — i.e.
**org/sector rollups per candidate are the native output**, which is exactly the
`top_contributors` / `campaign_finance_cycles` shape our schema wants. (Exact parameter names
for filtering by state/office/cycle are in the PDF and were not fully enumerated here — flag as
a build-time detail, not a blocker.)

### 1c. Coverage
FTM covers **all 50 states**, multiple cycles, current through the **2024 election year** (per
FTM search results, 2026-07-05). This is the single most complete free state-money source and
would light up `campaign_finance` on the ~7,400 state dossiers the expansion plan targets.

### 1d. Rate / usage limit — VERIFIED and restrictive
From FTM's Terms of Data Use (`/our-data/terms-of-data-use`, fetched 2026-07-05):
> "The Institute provides web access and **downloads of up to 1,000 records per year** to all
> users."

Expanded access is discretionary: "A completed exemption form must be submitted to be
considered for expanded access," reviewed for "accredited academic institutions, journalism
organizations, and registered 501(c)(3), 501(c)(5) and 501(c)(6) entities."

---

## 2. Licensing / attribution — THE deciding factor (VERIFIED verbatim, 2026-07-05)

Source: FollowTheMoney.org **Terms of Data Use** (`/our-data/terms-of-data-use`).

- **License:** "Creative Commons **Attribution-Noncommercial-Share Alike 3.0 United States
  License**" (CC BY-NC-SA 3.0 US).
- **Attribution (required):** "Users must give appropriate credit to the Institute for all
  reports, articles, mashups, or **other visual displays** that use Institute data." → A public
  map/dossier is a "visual display"; a visible "Source: FollowTheMoney.org / National Institute
  on Money in State Politics" credit on every state money panel would be mandatory.
- **Derivative works / redistribution:** "You may copy, distribute, display, remix, build on,
  and perform work—and **derivative works based upon the NIMP database**—**for non-commercial
  purposes only.**"
- **Hard restrictions:** "The data **shall not be used for political campaigns, solicitation of
  contributions, or sold to third parties.**"
- **ShareAlike:** the CC "Share Alike" term means derived aggregates we publish would have to
  be offered under the same CC BY-NC-SA license — a constraint on our own data terms.

**Why this is a blocker for our plan, not just a footnote:**
1. **Volume vs. 1,000-records/yr cap.** Backfilling org-rollup aggregates for ~7,400 candidates
   across multiple cycles is orders of magnitude past 1,000 records/year. We *must* obtain an
   expansion/exemption first; without it, bulk ingestion violates the stated limit.
2. **NonCommercial + "not sold to third parties."** Beholden is a public, free civic site — a
   good NC fit *in spirit* — but the repo does not self-describe as a registered 501(c)(3), and
   the NC clause plus "not sold to third parties" require care around any future
   monetization/redistribution. This is a **legal-counsel + written-permission question**, and
   `AGENTS.md` rule 1 ("no provenance, no publish") plus the repo's licensing-conscious posture
   (PRD's "license terms for public display, and redistribution rights" language) mean we do
   **not** ship third-party licensed data on assumption.
3. **ShareAlike downstream obligation** would attach a CC BY-NC-SA license to the derived money
   layer, affecting how we can license the rest of the published dataset.

---

## 3. Alternatives (brief)

| Source | Verdict | Notes |
|---|---|---|
| **State SOS / disclosure portals (bulk)** | Viable but heavy | Each state publishes its own bulk filings; quality/format varies wildly (50 bespoke parsers, entity-resolution per state). No single license issue, fully public-record data — but a large, ongoing engineering cost. This is the honest long-term path if FTM licensing fails; scope it per-state, not all-50. |
| **TransparencyUSA** | **Reject** | Scrape-only, no API/bulk license for redistribution. Excluded by WO ("no scraping"). |
| **OpenSecrets / FEC** | Not applicable to state | FEC (already in our stack) is **federal only**; OpenSecrets state coverage derives from... NIMSP/FTM. Neither fills the state gap independently. |

There is **no free, redistribution-clean, API-delivered state-money source** other than FTM
(licensing-gated) or per-state public disclosure bulk (engineering-gated). That is the real
finding: the state-money gap is gated on *permission or parsing effort*, not on data existence.

---

## 4. Integration sketch (IF green-lit after a written license exception)

Would reuse the existing money tables (`db/migrations/003_money.sql`) — no schema change:
- `campaign_finance_cycles` ← FTM candidate totals per `(person_id, cycle)`
  (`total_raised_cents`; `fec_committee_id` slot repurposed or nulled for state — confirm).
- `top_contributors` ← FTM org/sector rollups per candidate/cycle (`contributor_name`,
  `total_cents`, `rank`).

**ID crosswalk (the hard technical part):** FTM's `eid` is **not** an `ocd-person` id, so there
is no direct join to our OpenStates-keyed state spine. Match would be **fuzzy** on
name + state + office + cycle, exactly the low-confidence path the expansion plan already flags
("Shor–McCarty blocked on id crosswalk"). Any match below a confidence threshold must route to
`quarantine_identities` (fail-closed on ambiguous identity, never publish a guessed money→person
link — rule 1). Expect meaningful manual review; this is not a clean automated join like the
OpenStates votes path.

**Provenance + attribution:** every emitted money fact carries `source='followthemoney'` + the
FTM entity URL, and the money panel renders the required "National Institute on Money in State
Politics / FollowTheMoney.org" credit (money/legal copy via the approved string table only, per
`AGENTS.md`).

**Registry:** new `followthemoney` entry in `config.py` `SOURCES` + methodology entry +
coverage-dashboard row + freshness SLA, with the license terms and the granted exemption
recorded alongside (PRD convention: "license terms recorded").

---

## 5. Go / No-Go

**NO-GO as currently scoped.** The technical fit is good (free JSON API, native org rollups,
50-state coverage), but three verified license facts block public redistribution of derived
aggregates at our scale: **CC BY-NC-SA 3.0 US (NonCommercial + ShareAlike)**, a **1,000
records/year** default cap, and an explicit **"shall not be... sold to third parties"** clause.

**Path to GO:** submit FTM's exemption/expanded-access form, obtain **written permission** to
redistribute derived aggregates on a public non-commercial civic site at scale, and get counsel
sign-off on the NC/ShareAlike downstream obligations. Only then build (§4). If permission is
declined, fall back to per-state SOS bulk disclosure (public record, no redistribution license
needed) scoped state-by-state — accepting the higher parser cost.

### Single most important risk
**Licensing.** Ingesting FTM aggregates for ~7,400 dossiers without a written exception would
breach both the 1,000-records/year cap and the NonCommercial/"not sold to third parties" terms
— a rule-1 ("no provenance, no publish" / licensing-honest) violation, not a mere quota issue.
Do not build until permission is in hand.

---

### Sources (all fetched 2026-07-05)
- FTM Terms of Data Use (license, attribution, 1,000-records cap, "not sold to third parties")
  — https://www.followthemoney.org/our-data/terms-of-data-use
- FTM APIs landing (free account, "display on your blog or website")
  — https://www.followthemoney.org/our-data/apis
- FTM API documentation (`entity.php` / `mode=json`, base call shape)
  — https://www.followthemoney.org/our-data/apis/documentation
- FTM API PDF (full parameter tables — referenced, not parsed here)
  — https://www.followthemoney.org/assets/FollowTheMoney-API.pdf
- Live aggregate endpoint probe → HTTP 200 `{"error":"Invalid API Key"}`
  — https://api.followthemoney.org/
- Coverage current through 2024 — https://www.followthemoney.org/
- Repo money schema — `db/migrations/003_money.sql`; PRD licensing posture — `docs/PRD.md`
