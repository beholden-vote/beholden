# WO-39 — Metro councils through Legistar

**Lane P · prereq: WO-22b Part A, WO-23a, research R-B · read `AGENTS.md`,
`docs/workplan/README.md`, `docs/TRUSTED-EXTRACTION.md`, and `docs/DATA-CONTRACTS.md` §8.3,
§8.8, §8.9 and §8.10 first.**

## STATUS: GATED — do not start

This work order is written so it is ready when two things exist, and not before:

1. **Research R-B** (`docs/research/metro-platforms.md`): for the fifty largest cities and thirty
   largest counties, which legislative platform each runs and whether its Legistar API answers
   without a token.
2. **The owner's written sign-off, in chat, per jurisdiction.** Granicus publishes no API terms
   and each client government owns its content, so the determination is per jurisdiction. A
   jurisdiction without a recorded determination is not a candidate. Record each one under
   `docs/research/` with the verbatim wording relied on.

## Why this exists

Large cities are where most people live and where there is a recorded roll call to drill into.
Many of them run the same platform, so one adapter on the roster interface can yield both the
council roster and the council's votes for each — the same artifacts as federal, one grammar.

## Objective

One adapter, `sources/legistar.py`, registered on the §8.8 interface, taking a spec per
jurisdiction (`client` slug, body names to include, seat gate, `terms_ref`). It produces:

- the roster, via the framework (no new roster path);
- votes: event items with recorded roll calls become `rollcalls/{id}.json`, `votes/{person_id}.json`
  rows and `bills/{id}.json` (an ordinance or resolution) under the §8.9 grammar, written
  through the same writers as federal — a `build/` module per artifact family is extended only
  through its marked extension point, or a sibling module is added and registered;
- coverage state per §8.10, `votes: true` only when roll calls publish.

First ten jurisdictions by population from R-B's list that have a determination. **A client
that demands a token is skipped, never worked around.**

## Files

**OWNED** — new `pipelines/beholden_etl/sources/legistar.py` · new
`pipelines/beholden_etl/build/local_votes.py` · new `pipelines/tests/test_legistar.py` · new
`pipelines/beholden_etl/specs/` (one spec per jurisdiction, each with its `terms_ref`)

**SHARED — marked insertion points only** — `config.py` (`SOURCES` rows) · `jobs/fetch.py` and
`jobs/transform.py` (registration only) · `jobs/build.py` (one line in `ARTIFACT_WRITERS`) ·
`docs/DATA-CONTRACTS.md` (§8.9, §8.10 status) · `web/src/ui/chrome.tsx` (Sources rows)

## Constraints

- Everything in WO-22b's constraints applies: per-locality isolation, no inferred party,
  deterministic output, no licence no ship.
- **Be a polite client.** The shared client paces requests, identifies itself honestly, caches
  with conditional requests, and stops a jurisdiction on repeated errors. No rotating agents,
  no token bypass, no scraping of pages the API does not serve.
- **Votes are the council's own record.** A vote is published only with its source meeting item
  as the envelope's URL; a member with no recorded position is absent, not "not voting"; a
  roll call whose recorded tally disagrees with the sum of positions is refused and that item
  withheld, loudly.
- Write budget: state the projected class-A delta per jurisdiction before merging; the
  tripwire stays at 700k/month.

## Acceptance

1. Gates green; offline fixtures per jurisdiction; token-demanding client skipped (test);
   tally mismatch refused (test).
2. One metro council member's page lists votes that match the council's own published record
   (check three items by hand against the city's own site; record them in the PR).
3. The nightly still finishes inside its 330-minute limit.

## Out of scope

Metros not on Legistar (they wait for a per-state roster, WO-22c) · committees and
subcommittees · anything the API does not serve · UI.
