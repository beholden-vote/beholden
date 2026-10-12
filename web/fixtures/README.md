# Fixtures

A local stand-in for `data.beholden.vote`, so frontend work never waits on a nightly.

    cd web
    npm run dev:fixtures        # serves fixtures on :5199 and starts Vite pointed at it

Or by hand: `node fixtures/serve.mjs` and `VITE_DATA_BASE=http://localhost:5199 npm run dev`.
A path with no file answers 404, like the real host; a loader must treat that as "nothing
published", not as an error.

## What is real and what is not

| Path | Origin |
|---|---|
| `votes/{id}.json` (first 60 of 674 votes), `rollcalls/us/119/house/67{2,3,4}.json` (first 40 positions), `coverage.json`, `pins/cd.json` (first 60) | Copied from the live site on 2026-10-03 |
| `bills/…`, `bills/index.json` | **Synthetic.** Live bill pages did not exist yet; shaped by `DATA-CONTRACTS.md` 8.3 around a real roll call; cosponsor names are placeholders |
| `areas/…` | **Synthetic**, shaped by 8.4; numbers are plausible, not Census figures |
| `coverage/tn.json` | **Synthetic**, shaped by 8.10: one `covered`, one `withheld`, one `partial` |
| `pins/county/tn.json`, `pins/place/tn.json` | **Synthetic**, 8.11 |
| `coverage.json` → `sources.{census_gazetteer,sumner_county,fec}.changed_at` | **Added for WO-37**: an optional per-source "last changed" date so the coverage page can be exercised with checked and changed dates that differ (and one pair that match). The contract defines no such field yet; see the WO-37 PR |
| `positions/house.json` | **Synthetic**, 8.7; three placeholder members including an independent (`with_other_party: null`) |
| `positions/senate.json` | **Synthetic**, 8.7 (WO-38); twelve "Fixture Senator" members: two independents (`with_other_party: null`), one not placed (`layout: null`, pct withheld below the floor), one with no Voteview coordinates. Shaped like the live file, which was checked once against it |
| `votes/fixture-0001.json`, `votes/fixture-0002.json` | **Synthetic** (WO-38): the first 60 real roll calls of the copied votes file under placeholder ids, the second with some positions changed, so `#/c/fixture-0001/fixture-0002` has a hand-countable answer (41 of 54 shared decided roll calls) |
| `dossiers/fixture-*.json` | **Synthetic** (WO-38): identity and ideology only, enough to open the profile card for a House member, an independent and a Senator |

Synthetic names read "Fixture Member …" on purpose. Never present fixture numbers as facts.
When a lane's real artifact goes live, replace its fixture with a copy of the live file and
update this table in the same PR.
