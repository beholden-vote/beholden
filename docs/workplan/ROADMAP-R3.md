# Round 3 roadmap — complete the picture: state depth, local beachhead, new connections

Approved 2026-07-07. Fills the state-and-lower data gaps and adds new connection types,
within the three inviolable rules (no provenance no publish · fail closed · symmetric by
construction) and Tier A trusted extraction ([`TRUSTED-EXTRACTION.md`](../TRUSTED-EXTRACTION.md)).

## External landscape (verified 2026-07-07 — don't re-litigate)

- **State-money aggregators are dead as sources.** OpenSecrets discontinued its API
  April 2025; FollowTheMoney (CC BY-NC-SA + 1,000-rec/yr cap — NO-GO recorded in
  [`state-money-evaluation.md`](../research/state-money-evaluation.md)) is being sunsetted
  into OpenSecrets. Only path = per-state official portals (the WA PDC / WO-9 Tier A pattern).
- **OpenStates API v3 for state votes: GO** (recorded in
  [`state-votes-evaluation.md`](../research/state-votes-evaluation.md)) — exact `ocd-person`
  join, `/bills?include=votes`, fits nightly budget. Bulk session CSVs rejected (login-walled).
  `OPENSTATES_KEY` secret already set.
- **LegiScan**: 30k queries/mo free tier but proprietary-IP terms — same licensing posture
  that rejected Ballotpedia/VoteSmart. Do not adopt without counsel review. OpenStates suffices.
- **Local officials**: no unified open source exists (Google Civic representatives endpoint
  shut down April 2025; Cicero/BallotReady commercial). Per-city/county official portals only.

## Decisions (locked 2026-07-07)

1. State money: **pilot wave first** — fix WA reconciliation, then 3–5 best-portal states,
   then fan out in waves of ~5 (parallel authoring agents, one human-reviewed contract each).
2. Local officials: **beachhead** — top cities/counties with official structured sources;
   honest partial coverage, per-locality coverage rows.
3. New connection types: **all four** — state lobbying registries, in-app bill pages,
   deeper donor networks, voting-bloc analysis.

## Work orders

### Wave 1 — state voting records (biggest gap; GO verdict in hand)
- **WO-17** OpenStates v3 votes/bills ingestion. New `sources/openstates_votes.py`
  (`/bills?include=votes` incremental crawl, `OPENSTATES_KEY`); transform → `bills`,
  `roll_calls`, `vote_positions`, `sponsorships` (jurisdiction-scoped); votes→persons by
  exact `ocd-person` id, never name-match. Build: state legislators get the same
  `legislative` section shape as federal — the Record tab lights up for ~7,391 state
  legislators. Per-state honest-absent. Pilot 5 states, then all 52 slugs.
- **WO-18** State co-voting edges + party agreement (derived; cheap after WO-17). Extend
  `graph.py` co-voting to state chambers. Honest ideology substitute = co-voting similarity
  (methodology-anchored). Shor-McCarty stays deferred (fuzzy-match trap).

### Wave 2 — state money pilot
- **WO-19** WA PDC reconciliation fix + surface. Deterministic itemized↔summary filer_id
  crosswalk (investigate PDC's own filer registry for an exact join key; coarser
  deterministic grouping if none; never fuzzy). Then deterministic filer↔legislator
  crosswalk and surface WA contributions in the Money tab. `WA_PDC_ENABLED` re-enables only
  when the unchanged control-total gate passes on real data.
- **WO-20** Pilot wave, 3–5 states with best bulk portals. Evaluate first (contract +
  license determination before any code): CA CAL-ACCESS, TX TEC, NY BOE, FL DOS, CO/MN
  Socrata. Select on: documented layout + control totals available + public-domain terms.
  One authoring agent per state; human reviews every contract; gates identical to WA.

### Wave 3 — local beachhead
- **WO-21** Place geometry: Census TIGER incorporated-places tiles (`place` level is
  schema-ready), county-tile pattern, outline-only until officials exist.
- **WO-22** Officials rosters: Tier A extractors for top metros with official structured
  sources (start 5, evaluate toward ~25) + one full-state pilot (TN) for county officials
  where the state publishes a central roster. Rolling program; per-locality source key +
  coverage row; honest-absent elsewhere.

### Wave 4 — new dots
- **WO-23** In-app bill pages (`/bill/{id}` artifact: sponsors, cosponsors, actions,
  roll-call results) + full per-member voting record artifact (`/votes/{person_id}.json`).
  Federal first (already warehoused); state joins automatically after WO-17.
- **WO-24** Voting-bloc analysis: descriptive co-voting clusters + party-defection
  highlights, identical rendering by party (Rule 3 review mandatory), methodology page,
  descriptive language only (WO-8 caveat pattern).
- **WO-25** Donor networks deeper: multi-cycle FEC fetch (builder already publishes every
  warehoused cycle) → finance trends; PAC→candidate flows via FEC bulk (shared-donor caveat
  pattern); publish `fec_committee_id` + committee names as graph evidence.
- **WO-26** State lobbying registries: pilot with bulk public-domain registries (WA PDC
  lobbying datasets, CA SOS, TX). New spine tables (`lobbyist_registrations`,
  `lobbying_expenditures`); lobbyist-employer↔legislator edges only where the registry
  itself discloses the link — no inferred influence.
- **WO-27** Senate eFD filing links (chamber parity with House PTR links; no OCR). If the
  session-gated site proves unworkable in CI, document the blocker on the coverage
  dashboard instead of shipping a fragile scraper.

### Platform enablers (parallel, small)
- Tier B verifier: hand-rolled exact-substring-at-anchor check (TRUSTED-EXTRACTION §7);
  no framework. Build only when a Wave-2+ state actually needs it.
- Public API docs page (README already promises it).
- Coverage dashboard page (from coverage.json — data already published).
- Multi-congress ideology timeline (backlog).

## Sequencing

1. Wave 1 first — unlocks state edges (WO-18), state bill pages (WO-23), state blocs (WO-24).
2. Wave 2 parallel lane (independent of votes): WO-19 → WO-20.
3. WO-21 any time; WO-22 rolling — never blocks other waves.
4. Wave 4 order: WO-23 (cheapest big win — pure surfacing of warehoused data) → WO-24 →
   WO-25 → WO-26 → WO-27.

## Verification (every WO)

`cd pipelines && pytest && ruff check .` + golden fixtures per new contract + contract
validator green. Live after merge: coverage.json row (new source key, within_sla), dossier
spot-checks (state Record tab, WA money section, bill page), state-chamber graph edges,
pilot-metro pins. Gates stay untouched — a state that won't reconcile stays gated off like
WA, publicly listed as pending.
