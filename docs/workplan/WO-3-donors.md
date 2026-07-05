# WO-3 — Itemized donors: FEC top contributors

**Lane P, AFTER WO-1 merges · read `docs/workplan/README.md` + `AGENTS.md` first**

## Objective
Federal dossiers' money section gains "Top contributors" — FEC's own employer/occupation
rollups of itemized individual contributions — filling the existing `top_contributors` table
and the UI block that already renders `money.campaign_finance.top_contributors`.

## Data source (FEC API, key `FEC_API_KEY` in CI; client exists: `sources/fec.py`)
1. Resolve each candidate's principal committee:
   `GET /candidate/{candidate_id}/committees/?designation=P&cycle={FEC_CYCLE}` (fall back to
   authorized committees if no P).
2. `GET /schedules/schedule_a/by_employer/?committee_id={cid}&cycle={FEC_CYCLE}&sort=-total&per_page=25`
   → rows `{employer, total, count}`. (`by_occupation` optional follow-on — skip.)
3. Respect the existing throttle (~0.5s/call); ~537×2 calls ≈ well within limits.

## Files
- OWNED: `pipelines/beholden_etl/sources/fec.py` (add `principal_committee()`,
  `top_contributors_by_employer()`, row mapper to integer cents).
- SHARED (marked insertions): `jobs/fetch.py` (land per-candidate JSON under
  `dist/raw/fec/contributors/`), `jobs/transform.py` (→ `top_contributors` rows:
  person_id, cycle, contributor_name=employer (uppercased as FEC returns), total_cents,
  rank 1..25; dedupe PK), `jobs/build.py` (attach `top_contributors` into the existing
  `money.campaign_finance` block, capped at 10 for the dossier), `tests/test_pipeline.py`.
- Frontend: none — `DossierView` already renders `top_contributors` when present; verify only.

## Contract care (binding)
- Money in **integer cents** (`fec.to_cents`).
- These are *employer rollups of individual contributions as reported* — the section note
  copy comes from `web/src/strings.ts` (`campaignFinanceNote`); do NOT write copy implying
  corporate donations. If you add any string, it goes in strings.ts, symmetric for everyone.
- Rows with blank/`"NOT EMPLOYED"/"RETIRED"` employers are legitimate categories — keep them
  as FEC reports them; do not editorialize or filter.

## Acceptance
- Tests: fixture proving committee resolution fallback, cents conversion, rank capping,
  dedupe, and that a member without a committee gets no `top_contributors` (absent ≠ zero).
- Live: some `dossiers/{id}.json` shows `money.campaign_finance.top_contributors[0..9]` with
  `name` + `total_cents`, and the dossier renders it under Campaign finance with the FEC
  source stamp.

## Out of scope
Industry/NAICS coding (derived layer, needs methodology page first), state money (WO-7),
graph edges (WO-4).
