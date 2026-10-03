# WO-36 — Position profile: published measures, never a score

**Lane P · prereq: WO-23a (merged) · read `AGENTS.md`, `docs/workplan/README.md`,
`docs/TRUSTED-EXTRACTION.md` (gates), `docs/DATA-CONTRACTS.md` §8.3 and §8.7 first. §8.7 is
normative for this work order.**

## Why this exists

The dossier shows one left–right bar. A single position on one axis is a choice of weights
presented as a fact, and the repo's own rules ("descriptive, not prescriptive", "a formula we
can't explain publicly doesn't ship") rule out a single score. What the data supports instead
is a *profile*: where a member sits on Voteview's two dimensions, four plain measures with
published formulas, and how alike members' votes are. Two inputs already exist and are thrown
away: `nominate_dim2` is in the landed Voteview CSV and never read, and
`build/graph.py:co_voting_edges` computes the full agreement matrix and keeps only the edges.

## Objective

Publish `positions/house.json` and `positions/senate.json` to the §8.7 contract, plus a
methodology entry per measure. The UI that draws them is WO-38 (Wave 3); this work order
ships data and its documentation only.

## Files

**OWNED** — new `pipelines/beholden_etl/build/positions.py` · new
`pipelines/beholden_etl/build/measures.py` (the four measures as pure functions of the
roll-call positions) · new `pipelines/tests/test_positions.py`

**SHARED — marked insertion points only** — `pipelines/beholden_etl/jobs/build.py` (**one
import and one line in `ARTIFACT_WRITERS`** — do not edit `run()`) ·
`pipelines/beholden_etl/sources/voteview.py` (read `nominate_dim2`, nothing else) · the
warehouse schema (`pipelines/beholden_etl/db/migrations/`: **a new migration file** if
`nominate_dim2` needs a column; never edit an existing migration) ·
`pipelines/beholden_etl/build/graph.py` (expose the agreement matrix as a function the new
writer calls — a refactor that leaves every existing graph document byte-identical, proven
by the existing tests) · `web/src/ui/Methodology.tsx` (new entries only, one per measure) ·
`docs/DATA-CONTRACTS.md` (§8.7 status line only, and corrections if the contract proves wrong)

## Implementation notes

- **Reuse the agreement rule; do not restate it.** `key_votes.party_majority_positions` and the
  rule §8.3 cites define "decided" and "party position". `with_own_party` must equal the
  `with_party` / `party_decided` already published in each `votes/{person_id}.json` — a test
  pins the two equal for every member of the fixture.
- **`with_other_party`** is the new measure: see §8.7 for the exact population (roll calls where
  both major parties had a majority and the majorities differed). Independents and minor-party
  members get `null`, not a guess; write the reason into the methodology entry.
- **Layout** is a deterministic embedding of the 1 − agreement distance matrix. Use what is
  already installed (numpy if present; otherwise pure Python — 540 members is small). Seed
  anything random with a constant. Fix the sign and orientation of axes by a rule that does not
  look at party (e.g. the first member by `person_id` lands in a fixed half-plane), so a
  rebuild never flips the picture. Members below the vote floor get `layout: null`.
- **Determinism** is load-bearing (WO-33's digest skip): sort members by `person_id`, round
  every float at a stated precision, stable key order. Two builds must be byte-identical.
- **Provenance** via `ctx.provenance(...)`. Methodology ids point at the new entries.
- Return `{"positions_house": n, "positions_senate": m}` so the counts reach `coverage.json`.

## Constraints

- **No composite number.** Nothing here sums, averages or ranks measures into one value, and no
  field named score, rating, rank, grade or similar is published. Review would fail it.
- **Symmetric by construction.** A test builds the artifact twice from a fixture, the second
  time with party labels swapped, and requires the measures (not the labels) to be equal.
- **Fail closed.** Control totals: `Σ yea+nay+present+not_voting` per member equals `votes`
  `summary.total`; every sitting member of the chamber has an entry; `pct` within [0, 100].
  A failure raises. Never `try` around a gate.
- No new network source. Everything is derived from data already landed.

## Acceptance

1. All three house gates green. `test_positions.py` runs offline and covers: the equality with
   the published `votes/` summary; `with_other_party` on a hand-built split; floors → `null`;
   independent → `null`; party-swap symmetry; two builds byte-identical; no key matching
   `score|rating|rank|grade` anywhere in the output.
2. A hand computation for one real member from the landed Voteview CSV matches the published
   `with_own_party` exactly (record the member and the arithmetic in the PR).
3. Live, after the next nightly following merge: `positions/house.json` lists every sitting
   member; the counts appear in `coverage.json`; publish-stability still reports unchanged
   objects skipped.

## Out of scope

Any UI (WO-38) · state legislatures (WO-17b) · naming, colouring or labelling clusters ·
anything predictive · changing `key_votes` or the dossier's existing agreement figure.
