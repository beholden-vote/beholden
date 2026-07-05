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
| 9 | SOS bulk-disclosure pilot (WA PDC, Tier A) | P (independent) | merged |

**All work orders merged (2026-07-05).** Open follow-ons (not WOs yet): surface WA
disclosure data once a deterministic filer↔legislator crosswalk exists; build the
state-votes vertical (OpenStates API v3 — GO per `docs/research/state-votes-evaluation.md`);
committees CI needs Python 3.11.
