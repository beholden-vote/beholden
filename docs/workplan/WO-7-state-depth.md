# WO-7 — State depth: votes pilot + state-money source evaluation

**RESEARCH lane · independent · read `docs/workplan/README.md` + `AGENTS.md` first**
This WO is half evaluation, half build. Its first deliverable is a REPORT; build only after
the report's recommendation is accepted (by the coordinator/owner).

## Part A — State votes/bills pilot (OpenStates)

### Evaluate (report first)
- OpenStates API v3 (`OPENSTATES_KEY` secret exists): daily request limits vs. what
  5–10 states' current-session bills+votes require; vs. bulk exports
  (`https://open.pluralpolicy.com/data/session-csv/` — per-session CSV bundles: bills,
  votes, vote_people). Determine which path fits the nightly budget; verify vote_people rows
  carry the same `ocd-person` ids as our `openstates` crosswalk (they should — confirm).
- Pick pilot states by data quality + population (suggest: TX, CA, FL, NY, PA + TN).

### Build (after acceptance)
Ingest pilot-state bills/votes into the same `bills`/`roll_calls`/`vote_positions` tables
(`jurisdiction` = state; `bill_id = {st}/{session}/{type}/{num}`; roll_call_id
`{st}/{session}/{org}/{vote_id}`). Key-vote selection reuses WO-1's formula (import, don't
fork). State dossiers gain `legislative` (counts may be sponsor-less — publish what exists,
omit what doesn't). Provenance: openstates + link to the bill on the state site OR
openstates.org bill page.

## Part B — State campaign finance source evaluation (REPORT ONLY)
Evaluate **followthemoney.org (NIMSP)** API/bulk:
- Coverage (states × cycles), record shape (org rollups per candidate?), id crosswalk
  feasibility (their `eid`/candidate ids ↔ OpenStates people — name+state+office+cycle match
  quality), **licensing/attribution terms** (they require attribution; confirm redistribution
  of derived aggregates on a public site is permitted), rate limits, key acquisition.
- Alternatives to compare briefly: state disclosure portals (bulk quality varies),
  TransparencyUSA (scrape-only — likely reject).
- Deliver: `docs/research/state-money-evaluation.md` with a go/no-go + integration sketch.

## Files
- OWNED: NEW `docs/research/state-money-evaluation.md`, NEW `docs/research/state-votes-evaluation.md`;
  build phase: NEW `sources/openstates_votes.py` + marked insertions in jobs/tests (same
  pattern as WO-1).

## Acceptance
- Reports: concrete numbers (row counts, limits, license quotes), a recommendation, and a
  sized integration plan each.
- Build (if green-lit): pilot states' legislators show real vote records live, tests green.

## Out of scope
All 50 states at once; donor↔vote features; anything scraping-based.
