# Beholden Workplan — parallel execution guide

Work orders (WO-1 … WO-9) implementing [`docs/EXPANSION-PLAN.md`](../EXPANSION-PLAN.md)
and [`docs/TRUSTED-EXTRACTION.md`](../TRUSTED-EXTRACTION.md) (WO-9).
Each WO is **self-contained**: an agent with no prior context can execute it after reading
[`AGENTS.md`](../../AGENTS.md) (mandatory — the three rules outrank everything) + its WO file.

## Lanes & dependencies

```
LANE P (pipeline, serialize within lane):   WO-1 → WO-3 → WO-6a
LANE F (frontend, serialize within lane):   WO-2 → WO-5
LANE T (tiles, independent):                WO-6b
INTEGRATION (after prerequisites):          WO-4 (needs WO-1, WO-3) → WO-8 (needs WO-4)
RESEARCH (independent):                     WO-7
LANE P (independent, no prereq):            WO-9 (SOS bulk-disclosure pilot, WA PDC)
```

WO-9 is pipeline-lane but touches only new `bulk/`, a new source adapter, a new migration,
and marked insertions in `jobs/` — coordinate its `jobs/*.py` insertions with any other
in-flight pipeline WO to avoid a shared-file collision.

Lanes P, F, T, and WO-7 can run **in parallel** (different agents). *Within* a lane, run
sequentially — the WOs touch the same files.

## Ground rules for every agent

1. **Read [`AGENTS.md`](../../AGENTS.md) first.** No provenance no publish · fail closed ·
   symmetric by construction · commit as `Beholden Maintainers <maintainers@beholden.vote>`,
   no personal/tool references in commits.
2. **File ownership is law.** Each WO lists OWNED files (free to edit) and SHARED files
   (edit only the marked insertion points; keep diffs minimal). Never touch another WO's
   owned files.
3. **Verification gates (all must pass before commit):**
   - `PYTHONPATH=pipelines python -m pytest pipelines/tests -q` (all green, including your new tests)
   - `python -m ruff check pipelines/`
   - `cd web && npm run build` (if you touched web/)
4. **Branch per WO** (`wo-1-votes` …), PR against `main`, merge in lane order. Rebase on
   `main` before opening the PR.
5. **Live validation:** after merge, dispatch `etl-nightly` (pipeline WOs) or let
   `deploy-web` run (frontend WOs), and verify the acceptance URLs in the WO. A WO is not
   done until its live checks pass.
6. **Data honesty:** if a source turns out different than documented (404, schema drift),
   STOP and report — do not improvise a lower-quality source or fake/zero the data.
7. **Don't grow scope.** Each WO's "Out of scope" section is binding.

## Environment facts (all WOs)

- Pipeline: Python ≥3.11, `pip install -e "./pipelines[dev]"`, stages `fetch → transform →
  build → publish` via `Makefile`; DuckDB warehouse at `dist/warehouse.duckdb`; artifacts in
  `dist/data/`; tests use synthetic fixtures (no network, no keys).
- CI: `.github/workflows/etl-nightly.yml` (nightly + manual dispatch), `deploy-web.yml`
  (on web/** push), `tiles-build.yml` (manual). Secrets already set (Congress, FEC, R2, CF).
- Data serves from `https://data.beholden.vote/...`; site at `https://beholden.vote`.
- Identity spine: `persons` keyed by deterministic UUID5; crosswalk `person_identifiers`
  (`bioguide`, `icpsr`, `fec`, `openstates`). ICPSR ids exist for current members.
- Contracts: [`docs/DATA-CONTRACTS.md`](../DATA-CONTRACTS.md). Frontend contract mirror:
  `web/src/types.ts`. Design system: [`web/DESIGN.md`](../../web/DESIGN.md).

## Status board (update on merge)

| WO | Title | Lane | Status |
|---|---|---|---|
| 1 | Roll-call votes vertical | P | merged |
| 2 | Zoom-adaptive layers + panel level sections | F | merged |
| 3 | Itemized donors (FEC top contributors) | P (after 1) | merged |
| 4 | Entity graph + neighborhood view | INT (after 1,3) | merged |
| 5 | Permalinks, people search, "my ballot" | F (after 2) | merged |
| 6 | Committees sync (6a) + county tile layer (6b) | P / T | merged |
| 7 | State votes pilot + state-money source evaluation | R | merged (state-money = NO-GO, use WO-9) |
| 8 | Donor↔vote juxtaposition + methodology pages | INT (after 4) | merged |
| 9 | SOS bulk-disclosure pilot (WA PDC, Tier A) | P (independent) | merged (source gated off pending reconciliation fix) |
| 10 | Resilient · incremental · parallel fetch | P (independent) | merged |
| 11 | Tabbed dossier + surface published depth | F | merged |
| 12 | Cited drill-down data (bill titles on votes, dates, committee links, tallies) | P | merged |
| 13 | Interactive connections graph (d3-force) | F (after 11) | merged |
| 14 | Map fills by level (Senate delegation stylefeed) | P+map (after 12) | merged |
| 15 | Contact · social · previous-roles · bio · education data | P (after 12) | merged |
| 16 | Header action row + Overview bio/education + Social tab | F (after 11, 15) | merged |
| 17 | State votes/bills via OpenStates API v3 | P | in review (pilot ca/tx/ny/fl/tn) |
| 18 | State co-voting edges + party agreement | P (after 17) | open |
| 19 | WA PDC reconciliation fix + surface in Money tab | P (independent) | open |
| 20 | State-money pilot wave (3–5 best-portal states) | P (after 19) | open |
| 21 | Place geometry (TIGER incorporated-places tiles) | T | open |
| 22 | Local officials beachhead (top metros + one full state) | P (rolling) | open |
| 23 | In-app bill pages + full voting-record artifacts | P+F (federal now; state after 17) | open |
| 24 | Voting-bloc analysis (descriptive, symmetric) | P+F (after 23) | open |
| 25 | Donor networks deeper (multi-cycle, PAC flows) | P (independent) | open |
| 26 | State lobbying registries (WA/CA/TX pilot) | P (after 19) | open |
| 27 | Senate eFD filing links (chamber parity) | P (independent) | open |

**WO-1…16 merged (2026-07-06).** WO-11…16 were the depth round: dossier tabs, cited
drill-downs, an interactive connections graph, per-level map fills, and the
contact/social/biography layer. Sources verified 2026-07-06: `legislators-current`
contact fields (phone 536/537, website 536, contact_form 89 — Congress publishes no
direct email), `legislators-social-media.json` (X 506 · FB 490 · IG 407 · YT 255),
`legislators-district-offices.json` (1,312 local offices w/ phone + lat/lng),
congress.gov member detail (official birthYear · partyHistory · leadership · DC
office/phone), OpenStates CSV contact/social/biography columns, own warehoused term
history for previous roles. Federal education ships from **Wikidata** (P69 + degree/
year qualifiers, resolved via our stored wikidata_qid) under a DEDICATED wikidata
envelope with a verbatim crowd-edited credibility note rendered wherever it appears —
the official source (Bioguide) is bot-walled, and the user accepted labeled Wikidata
over omission. Ballotpedia/VoteSmart rejected (restrictive licensing).

**WO-17…27 are Round 3** — state depth, local beachhead, and new connection types. Full
context, external-landscape verdicts (aggregators dead; OpenStates v3 GO; LegiScan
licensing-risky), locked user decisions, and per-WO scope live in
[`ROADMAP-R3.md`](ROADMAP-R3.md). Remaining small follow-ons: multi-congress ideology
timeline; committees CI needs Python 3.11; Tier B verifier (build when a Wave-2 state
needs it); public API docs page; coverage dashboard page.
