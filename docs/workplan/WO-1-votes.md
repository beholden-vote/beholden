# WO-1 — Roll-call votes vertical (federal)

**Lane P · no prerequisites · read `docs/workplan/README.md` + `AGENTS.md` first**

## Objective
Every federal dossier shows real key votes (position + question + result + date + link to the
bill/roll call), and a co-voting agreement stat. Fills the empty `roll_calls` +
`vote_positions` tables and the dossier's `key_votes: []`.

## Data source (verified 2026-07-05, no key)
- `https://voteview.com/static/data/out/votes/HS119_votes.csv`
  cols: `congress,chamber,rollnumber,icpsr,cast_code,prob` (~500k rows).
  cast_code: 1/2/3 = yea-family, 4/5/6 = nay-family, 7/8/9 = present/abstain, 0 = not member.
  Map: 1–3→`yea`, 4–6→`nay`, 7–8→`present`, 9→`not_voting` (document in methodology).
- `https://voteview.com/static/data/out/rollcalls/HS119_rollcalls.csv`
  cols incl. `date, session, clerk_rollnumber, yea_count, nay_count, bill_number,
  vote_result, vote_desc, vote_question`.
- Join to persons through the existing `icpsr` crosswalk (`person_identifiers`).
- Roll-call public URL: House `https://clerk.house.gov/Votes/{year}{clerk_rollnumber}`;
  Senate `https://www.senate.gov/legislative/LIS/roll_call_votes/vote{congress}{session}/vote_{congress}_{session}_{rollnumber:05d}.htm` — verify both resolve before shipping; if one
  doesn't, link the Voteview rollcall page instead (still official-record adjacent, note it).

## Files
- OWNED: `pipelines/beholden_etl/sources/voteview.py` (add votes/rollcalls fetchers + row
  mappers), NEW `pipelines/beholden_etl/build/key_votes.py` (selection + agreement math).
- SHARED (marked insertions only): `jobs/fetch.py` (land 2 CSVs + manifest count),
  `jobs/transform.py` (ingest → `roll_calls`, `vote_positions`; dedupe PKs),
  `jobs/build.py` (populate `key_votes` in the legislative section + an `agreement` stat),
  `pipelines/tests/test_pipeline.py` (fixtures + tests), `web/src/types.ts` +
  `web/src/ui/DossierView.tsx` only if the key-vote item shape needs a field the UI lacks
  (it already renders `key_votes`).

## Implementation notes
- `roll_calls.roll_call_id`: `us/{congress}/{chamber}/{rollnumber}`. `bill_id` FK: link only
  when `bill_number` normalizes to an existing `bills` row (e.g. "HR 1234" → `us/119/hr/1234`);
  else NULL (procedural votes are legitimate).
- `held_at`: date from rollcalls CSV (midnight UTC).
- **Key-vote selection (symmetric, documented):** score = closeness (1 − |yea−nay|/(yea+nay))
  + recency bonus; take top 10 per member where the member voted yea/nay. No hand-picking, no
  topic weighting. Put the formula in a docstring AND surface it later via /methodology.
- **Agreement stat:** for each member, % agreement with their party's majority position over
  roll calls where they voted yea/nay (min 20 votes else omit). Add to the legislative section
  as `party_agreement_pct: number | null` — additive, schema-compatible.
- 500k rows: bulk-insert via `store.insert` in chunks; keep transform under ~2 min.

## Acceptance
- Tests: fixture with 2 members × 3 roll calls proving position mapping, key-vote selection,
  bill linking, agreement math, and pending/omission behavior. All existing tests stay green.
- Live (after merge + etl dispatch): a House dossier at
  `data.beholden.vote/dossiers/{id}.json` has ≥1 `key_votes[]` entry with `position`,
  `question`, `held_at`, `url`; `legislative.provenance` intact.

## Out of scope
State votes (WO-7), the graph (WO-4), per-member full vote-history JSON (note as follow-on).
