# WO-23a — The full federal voting record, down to the bill

**Lane P · prereq: WO-32 (merged) · read `AGENTS.md`, `docs/workplan/README.md`, and
`docs/DATA-CONTRACTS.md` §8.3 first. §8.3 is normative for this work order.**

## Why this exists

A dossier shows ten "key votes" and nothing else. The warehouse already holds every position
cast by every sitting member on every roll call of the current Congress — it is simply never
published. A reader cannot see a member's whole record, cannot open a bill, and cannot ask
the most natural question the site could answer: *how did my representatives vote on this?*

Two gaps in the data sit underneath that, and both are larger than the roadmap assumed
("federal first — already warehoused" is true of positions and false of the rest):

- `bills` holds only bills **sponsored by a sitting member** (`jobs/transform.py`, the bills
  block). A roll call links to a bill only if that bill is in the table, so a vote on a bill
  sponsored by someone who has since left has no title and no topic.
- **Cosponsors are not fetched at all** — only a count. The `sponsorships` table has a
  `cosponsor` role that nothing federal ever fills.

## Objective

Publish three artifacts (§8.3): `votes/{person_id}.json` for every sitting member of
Congress, `rollcalls/{roll_call_id}.json` for every roll call of the current Congress, and
`bills/{bill_id}.json` plus `bills/index.json` for every bill that has had at least one roll
call. The dossier's existing `key_votes` block does not change.

## Data sources

Both already registered: `voteview` (roll calls and positions) and `congress.gov` (bill
metadata). The new calls are to the Congress.gov API's bill detail and cosponsor endpoints.
Confirm the exact paths, fields (`policyArea`, `sponsors`, `cosponsors`, `latestAction`,
`introducedDate`) and the documented rate limit against the live API documentation before
writing the client code — `sources/congress_gov.py` records 5,000 requests/hour.

## Files

**OWNED** — new `pipelines/beholden_etl/build/votes.py` · new
`pipelines/tests/test_votes.py`

**SHARED — marked insertion points only** — `pipelines/beholden_etl/sources/congress_gov.py`
(new client methods; `bills_updated_since` exists there unused) ·
`pipelines/beholden_etl/jobs/fetch.py` (land bill detail + cosponsors for roll-call bills) ·
`pipelines/beholden_etl/jobs/transform.py` (the bills and sponsorships blocks) ·
`pipelines/beholden_etl/jobs/build.py` (**one import and one line in `ARTIFACT_WRITERS`**,
plus three `Disallow` lines in `ROBOTS_TXT` — do not edit `run()`) · a new migration under
`db/` only if a column is genuinely missing · `docs/DATA-CONTRACTS.md` §8.3 status

## Implementation notes

**The writer.** `build/votes.py` exposes `publish(ctx: BuildContext) -> dict[str, int]`.
Open your own connection from `ctx.db_path`. Reuse what build already has rather than
re-deriving it: `key_votes.party_majority_positions` for `party_position`; the queries
behind `_vote_records`, `_roll_call_tallies`, `_bill_titles`, `_bill_policy_areas` and the
raw-CSV reader `_rollcall_meta` in `jobs/build.py` show where each field lives. If you need
one of those helpers, import it or move it into a shared module in `beholden_etl/build/` —
do not copy it.

**Which bills.** Every distinct bill referenced by a roll call of the current Congress —
several hundred, not the tens of thousands introduced. For each: one detail call and one
cosponsors call. That is a one-time backfill of a couple of thousand requests and then a
trickle. It **must** follow the WO-10 discipline in `jobs/fetch.py`: land raw responses in
the lake, resume from what is already landed, re-fetch only what is stale or new, pace under
the rate limit, and never let one failed bill discard the run's other work. A bill that
cannot be fetched is absent tonight and retried tomorrow — it is not published with invented
fields.

**Votes that are not on bills.** Nominations, procedural motions and quorum calls have no
bill. They belong in a member's record with `bill_id: null` and the question and description
the source gives. Do not drop them: a record that silently omits procedural votes misstates
attendance.

**Eligibility.** A member is not "not voting" on roll calls held before they took office.
Voteview distinguishes "not a member" from "not voting"; only the latter belongs in the
record or the `not_voting` count.

**Sponsors and cosponsors who have left.** Publish the name with `person_id: null`. Link a
`person_id` only by deterministic id (bioguide) — no name matching, per TRUSTED-EXTRACTION.

**`positions` is not the whole roll.** The warehouse holds positions for sitting members
only. `totals` is the official tally; `positions` and `by_party` cover current members and
will not sum to it once anyone has left. The contract carries `positions_cover` to say so.
Do not "fix" the mismatch by scaling or inferring.

**Symmetry.** `by_party` and the cosponsor breakdown are ordered alphabetically by party
code, never by size. Every member's file has the same fields.

**Keys.** Ids are used as object keys verbatim (`rollcalls/us/119/h/312.json`). Assert in a
test that every id you emit matches `[a-z0-9/._-]+` — one unexpected character and the object
is unreachable.

**Methodology.** `party_position`, `with_party` and `against_party` are computed, so their
envelope needs a `methodology_id` whose anchor already exists on the methodology page. Use
the existing agreement anchor (`METHODOLOGY_AGREEMENT`) and the existing formula; do not
introduce a new measure here (that is WO-36).

**Deterministic output.** Stable ordering everywhere, so a recess week rewrites nothing.

**Crawl policy.** Add `Disallow: /votes/`, `/rollcalls/` and `/bills/` to `ROBOTS_TXT` in
`jobs/build.py`, in the existing single group. These are the same shape of path as
`/dossiers/`: thousands of small objects under a guessable key.

## Acceptance

1. `PYTHONPATH=pipelines python -m pytest pipelines/tests -q` green. `test_votes.py` runs
   offline on the synthetic fixtures and covers: summary arithmetic (`yea + nay + present +
   not_voting == total`, `with_party + against_party == party_decided`); a pre-tenure roll
   call excluded; a non-bill vote retained with `bill_id: null`; a departed sponsor published
   with `person_id: null`; party ordering alphabetical; id character set; envelopes valid;
   two builds byte-identical apart from stamps.
2. `python -m ruff check pipelines/` clean.
3. Live, after the next nightly: a sitting member's `votes/{id}.json` lists every roll call
   of the Congress in their chamber since they took office; one roll call's `totals` match
   the chamber's own published tally for that vote; one bill page lists its cosponsors and
   its roll calls; `coverage.json` reports the three counts.

## Out of scope

Any UI (WO-23b) · state and local votes (WO-17b, WO-39 — but write the writer so a non-`us/`
roll call would flow through it unchanged) · new measures or scores (WO-36) · bills that
never reached a vote · amendments as first-class pages · previous Congresses.
