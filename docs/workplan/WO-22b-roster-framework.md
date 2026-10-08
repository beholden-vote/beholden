# WO-22b — Roster framework, then all of Tennessee

**Lane P · prereq: WO-33, WO-32 (merged) · read `AGENTS.md`, `docs/workplan/README.md`,
`docs/TRUSTED-EXTRACTION.md` (gates), and `docs/DATA-CONTRACTS.md` §8.1, §8.2, §8.8, §8.10 and
§8.11 first. Those sections are normative for this work order.**

## Why this exists

Two Tennessee governments are covered by two hand-written adapters in
`sources/tn_local.py`, and one county's fetch error currently sinks the whole nightly. At a
hundred localities that is a nightly outage; at ten thousand objects it is also a write-budget
problem. The same roster interface has to carry Tennessee's statewide directories now and the
metro councils (WO-39) at the same time, so it comes first and stands alone.

## This work order has two parts, and only the first can start

**Part A — framework. Unblocked.** Everything below up to *Part B*.

**Part B — statewide Tennessee. BLOCKED** until `docs/research/` records, in writing, UT's
answer on CTAS and MTAS reuse and the owner has signed off in chat. Both sites state that
their content is copyrighted and permission is required. **Do not fetch either site beyond
reading its published terms, do not write a spec that points at it, and do not publish
anything derived from it before that determination exists.** Part B is a separate PR.

## Part A — Objective

1. **`sources/roster.py`**: `RosterSpec`, `RosterRow` and the adapter signature of §8.8. A
   spec without a `terms_ref` does not load (a test proves it).
2. **One spec-driven adapter replaces the two.** Sumner County and Hendersonville become two
   spec records plus their existing parsers, registered as adapter ids; their published output
   (dossiers, pins, graph neighbourhoods, ids aside) must be unchanged except where §8.8
   changes it, and each such change is listed in the PR. `SOURCES`, the fetchers, the transform
   loop, office titles and the Sources page rows are generated from the spec list.
3. **Per-locality isolation.** A locality that fails its gate is *withheld*: the run continues
   and last-good data for it is retained and still served. Any non-gate failure still fails
   the build — only `RosterError`-class gate failures are isolated, and each is logged by name.
4. **Person-keyed ids** (§8.8). Sumner's are seat-keyed today; migrate, keeping a one-time
   mapping so the old keys are not misreported as stale departures.
5. **Stale deletion must respect withholding.** `jobs/publish.py`'s stale-object logic treats a
   withheld locality's keys as live. A test proves a withheld locality is not deleted while an
   officials-who-really-left object still is.
6. **Coverage state and sharded pins.** New writers for `/coverage/{st}.json` (§8.10) and
   `/pins/county/{st}.json`, `/pins/place/{st}.json` (§8.11), registered in `ARTIFACT_WRITERS`;
   `coverage.json` gains the three locality counts. The monolithic county pins keep publishing.
7. **No graph documents** for an official with no edges.
8. **A deliberately broken spec** (a fixture whose seat count is wrong) withholds exactly one
   locality while every other artifact still builds and publishes.

## Files

**OWNED** — new `pipelines/beholden_etl/sources/roster.py` · `pipelines/beholden_etl/sources/tn_local.py`
(rewritten onto the framework) · new `pipelines/beholden_etl/build/coverage_divisions.py` ·
new `pipelines/beholden_etl/build/pin_shards.py` · new `pipelines/tests/test_roster.py`

**SHARED — marked insertion points only** — `pipelines/beholden_etl/config.py` (`SOURCES` rows
generated from specs) · `pipelines/beholden_etl/jobs/fetch.py` (the local-roster fetcher
registration only) · `pipelines/beholden_etl/jobs/transform.py` (the local-roster loop only) ·
`pipelines/beholden_etl/jobs/build.py` (**imports and lines in `ARTIFACT_WRITERS`**; the
dossier/graph/pin emission points that must honour withholding and the no-empty-graph rule —
keep every diff minimal and say which in the PR) · `pipelines/beholden_etl/jobs/publish.py`
(the stale-keep rule only) · `web/src/ui/chrome.tsx` (Sources rows, generated or minimal) ·
`docs/DATA-CONTRACTS.md` (§8.8, §8.10, §8.11 status lines and any corrections)

## Constraints

- **Fail closed, per locality** — and only per locality. Never widen what counts as an isolated
  failure to make a run pass; never lower a seat-count gate.
- **No licence, no ship.** The framework ships with only the two governments that already
  ship. Adding a locality is a spec plus a fixture plus a `terms_ref`.
- **Party is `"U"` unless the source states one.** Never inferred, never `"NP"`.
- **Deterministic output** (WO-33): sorted, stable keys; the framework's own rebuild is
  byte-identical, and the existing Sumner and Hendersonville objects do not churn except for
  the id migration.
- **Write budget.** The change must not raise nightly class-A writes beyond the new shard and
  coverage objects (≈ 100 files). State the projected delta in the PR.
- Nothing here adds a server or a Worker in front of `data.beholden.vote` (ARCHITECTURE §5.1).

## Acceptance

1. All three house gates green; `test_roster.py` offline and covers: spec without `terms_ref`
   rejected; both existing localities reproduce their previous rows from fixtures; a broken
   spec withholds one locality and the rest build; last-good served for a withheld locality;
   stale deletion spares it; the id migration; coverage and shard files match §8.10/§8.11
   byte-for-byte on a fixture; two builds identical.
2. A local full build over real landed Sumner and Hendersonville data produces the same
   dossier set as `main` apart from the listed, intended differences.
3. Live, after merge and one nightly: `coverage/tn.json` lists both localities `covered`;
   `pins/county/tn.json` exists; the nightly's `publish:` line shows the large majority skipped.

## Part B — Tennessee statewide (after the sign-off)

CTAS (95 counties) and MTAS (345 cities) specs and fixtures against the framework. Done when
every Tennessee county opens with a full commission and the coverage file reports honestly for
every city MTAS lists. Out of scope for this PR set until then.

## Out of scope

Any UI (WO-37) · votes for local bodies (WO-39, same artifact grammar §8.9) · other states
(WO-22c) · local campaign finance · commission-district geometry.
