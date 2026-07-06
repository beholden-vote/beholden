# WO-10 — Resilient, incremental, parallel fetch

**Lane P · no hard prereq (touches only `jobs/fetch.py` + sources + a new raw-lake
module) · read `docs/workplan/README.md` + `AGENTS.md` first**

## Why this exists
The nightly full rebuild is a **monolithic ~2-hour fetch with no checkpointing**: it walks
congress.gov sponsored-legislation per member (~19 min) then FEC totals + committee +
by-employer per candidate (~1.5 h, paced under the 1k/hr key cap), sequentially, making
thousands of API calls. Any single hiccup among those calls throws away the entire run.
In one evening it failed three distinct ways, each now patched but none *structurally*
fixed:

1. **120-min job timeout** (raised to 330) — the run simply didn't fit.
2. **OOM SIGKILL** — FEC throttle (0.5 s ⇒ 7,200/hr) blew the 1,000/hr cap, a 429 storm
   stalled ~2 h and grew memory until the runner killed it (paced to 3.7 s).
3. **Unhandled `ReadTimeout`** — a transient congress.gov slow patch exhausted 5 retries;
   `RetryError` propagated and sank the run (clients hardened to 60 s / 8 retries).

The patches bought reliability; they didn't remove the fragility. **A 2-hour, no-checkpoint,
serial fetch will keep failing at the tail of the run and losing everything.** This WO makes
the fetch resumable, parallel, and incremental — and turns a transient source failure into
"slightly stale but correct" instead of "whole run lost" or (worse) a fabricated zero.

## Objective
1. **Persist the raw lake to R2 and reuse it.** `publish` already uploads `dist/raw` to
   `R2 /raw/{date}/`. Add a **last-good** pointer (`/raw/latest/`) and, at fetch start, hydrate
   `dist/raw` from it. Each source then re-fetches only when its snapshot is **older than its
   `freshness_sla_hours`** (already declared per source in `config.SOURCES`) — otherwise the
   cached snapshot is kept. A from-scratch run is still possible (`--full` / a dispatch input).
2. **Resumability.** A source (or per-member/per-candidate item) that already has a fresh
   snapshot this run is skipped. A killed/retried run **resumes** from the hydrated lake instead
   of restarting the 2-hour crawl.
3. **Parallelism across independent rate limits.** congress.gov (5,000/hr) and FEC (1,000/hr)
   are *separate* services — run their loops **concurrently** so wall-clock ≈ max(loops), not
   sum. Keep each source's own governor (congress ~0.79 s, FEC ~3.7 s) so neither exceeds its
   cap. Voteview/OpenStates/House-Clerk/WA-PDC are independent bulk pulls — fan them out too.
4. **Fail-closed preserved, fabrication impossible.** On a transient per-item failure, **fall
   back to that item's last-good snapshot** from R2 (correct, slightly stale) rather than
   dropping it. Only hard-fail closed if there is *no* prior snapshot **and** absence would
   fabricate a value (e.g. legislation counts, where missing ⇒ a false "sponsored 0"). Where
   absence is honest (FEC totals/contributors ⇒ no money section), a missing item may stay
   absent. Document which sources are which.

## Files
- OWNED: NEW `pipelines/beholden_etl/rawlake.py` (R2 hydrate/sync of `dist/raw`, freshness
  check per source against `config.SOURCES[...].freshness_sla_hours`, last-good fallback for a
  single item), rewrite of `pipelines/beholden_etl/jobs/fetch.py` (per-source fetch functions +
  a parallel orchestrator + a manifest that records per-source **status, item counts, and
  wall-time**).
- SHARED (marked insertions only): `pipelines/beholden_etl/jobs/publish.py` (write the
  `/raw/latest/` pointer after a successful publish), `.github/workflows/etl-nightly.yml` (a
  `full_rebuild` dispatch input; keep `PYTHONUNBUFFERED`; the 330-min ceiling can drop back once
  incremental lands), `pipelines/tests/test_pipeline.py` (append tests).
- Do **not** touch `transform.py`/`build.py` semantics, `web/`, `spike/`.

## Implementation notes
- **Concurrency:** a small thread pool (or `asyncio`) — one worker per independent source; the
  per-source rate governor stays inside each client (already there). Congress-legislation and
  FEC are the two long poles; running them in parallel roughly halves wall-clock.
- **Freshness policy:** reuse `config.SOURCES[src].freshness_sla_hours` (already the alert SLA)
  as the re-fetch threshold. Fast movers (votes, PTR, FEC) re-fetch nightly; slow movers
  (committees, member roster, tiles) far less often. This is the PRD G2 sub-daily-freshness path.
- **Determinism/provenance unchanged:** the manifest still stamps `retrieved_at`/`source_url`
  per source; a reused snapshot carries its **original** `retrieved_at` (honesty — don't restamp
  cached data as freshly fetched). Every published fact still traces to a real snapshot.
- **Progress + observability:** keep the per-50 progress prints; add a per-source timing line to
  the manifest so a slow source is visible without log spelunking.

## Acceptance
- A run whose fetch is interrupted and re-dispatched **resumes** (skips already-fresh snapshots)
  rather than re-crawling from zero.
- Congress + FEC loops run concurrently; a full run's wall-clock is meaningfully below the serial
  sum (target: comfortably under ~90 min).
- **Simulated single-source `ReadTimeout` with a prior snapshot ⇒ run completes** using the
  cached snapshot (test). **No prior snapshot + fabricating absence ⇒ still fails closed** (test).
- A reused snapshot keeps its original `retrieved_at` (test). All existing tests stay green;
  `pytest -q` + `ruff check .` clean.

## Out of scope
Transform/build changes; new data sources; the frontend. Sub-daily *scheduling* (a second cron)
can follow once incremental fetch proves the freshness policy.
