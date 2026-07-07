# WA PDC reconciliation — findings, the deterministic rule, and its citation (WO-19)

**Status:** resolved deterministically, 2026-07-07. The fail-closed control-total gate
(`bulk/reconcile.py`, byte-identical) now passes on real current-cycle data. This
document records what was actually wrong, the rule that fixes it, where PDC documents
that rule, and the honest verdict on the filer→legislator crosswalk.

All live observations below were made 2026-07-07 against the open Socrata feeds
(no key): itemized `kv7h-kjye` ("Contributions to Candidates and Political
Committees") and summary `3h9x-7bvm` ("Campaign Finance Summary") on data.wa.gov.

## 1. Why the gate failed (it was right to)

The WO-9 contract reconciled Σ(itemized `amount`) against the summary's
`contributions_amount` grouped by **`(filer_id, election_year)`**. That group is broken
on two independent axes:

1. **The two feeds disagree on `filer_id` for the same campaign.** Live pair: the
   itemized feed labels Steve Ewing's 2025 campaign `filer_id = 'EWINS2 258'`
   (fund 26142); the summary feed labels the *same fund* `'EWINS  258'`. This is not
   corruption — PDC's own filer_id definition (both datasets' data dictionaries) says:
   > "The filer id is consistent across election years **with the exception that an
   > individual running for a second office in the same election year will receive a
   > second filer id. There is no correlation between the two filer ids.**"
   The itemized feed carries the second-office id; the summary carries the person's
   primary id. A join on filer_id text is therefore *documented* to be unreliable.
2. **`(filer_id, election_year)` is not even a well-defined group.** A filer can run
   several funds in one election year — live: `'EWINS  258'` has **two** 2025 summary
   rows (fund 25644 / $12,632.94 and fund 26142 / $1,570.00). Keying control totals by
   (filer, year) collapses them (last-writer-wins), so the group could never match.

A third failure source was our own pilot window, not the data: the fetch filtered
itemized rows by `election_year >= 2025`, but a campaign's rows can carry mixed
election_year labels while the summary total always covers the whole campaign. Live:
fund 27811 (David Stuebe, 2026) has 42 rows labeled 2026 ($29,757.68) **plus 13 labeled
2024 ($7,900.00)** — whole fund $37,657.68, exactly the summary total. A year-sliced
fund can never reconcile, no matter how it is grouped.

## 2. The deterministic rule

> **Group control totals by `fund_id`, and make the fetched itemized slice
> fund-complete (never split a fund at the window boundary).**

Citation — PDC's own data dictionary, identical on both datasets
(`https://data.wa.gov/api/views/kv7h-kjye.json` and
`https://data.wa.gov/api/views/3h9x-7bvm.json`, `columns[].description`):

> **fund_id** — "The unique identifier for all reporting and finance records associated
> with a single campaign. **This can be used to correlate records across different
> datasets.** For candidates and single-year committees, the fund_id is the same for
> everything reported for that campaign. For continuing political committees, their
> reporting is annual, and they have a unique fund_id for each reporting year."

And the summary's `contributions_amount` names the itemized dataset as its own
line-item companion:

> **contributions_amount** — "The sum total of all contributions reported. Refer to the
> 'Contributions to Candidates and Political Committees' data set for line-item details."

This is a documented, exact, shared key — not a normalization heuristic. No regex, no
format decoding of the `'EWINS2'` suffix is needed (and none was adopted: the suffix
behavior is documented only as "no correlation between the two filer ids", so any
textual normalization would be a guess).

**Live evidence (2026-07-07, epsilon 0):** grouping server-side aggregates by fund_id
over the current window, **2,670 of 2,670 fund-complete groups reconcile to the cent**
(2,667 immediately; the remaining 3 — funds 26513, 27811, 26004 — were window-split
funds that reconcile exactly once fund-complete: $4,175.00, $37,657.68, $601,026.31).
Zero itemized funds lacked a summary control row; summary fund_id was unique
throughout; zero null fund_id/committee_id/election_year in the window. The end-to-end
rerun of the real pipeline (fetch → unchanged gates) is recorded in the WO-19 report.

### What changed in code (contract `2026-07-07`)

- `sources/wa_pdc.py` — `control_total.group_by = ("fund_id",)`; `fund_id` and
  `committee_id` read as verbatim fields (fund_id a non-nullable key: no fund, no
  reconciliation basis → quarantine); `fetch_itemized` adds a fund-completion pass;
  `fetch_summary` fetches the whole (~58k-row) summary with the registry columns;
  the observed header now really is observed (Socrata metadata `columns[].fieldName`),
  never an echo of the contract. Layout fingerprint (37 columns) unchanged.
- `bulk/reconcile.py` — **byte-identical.** The gates did their job; the inputs were
  keyed wrong.
- Stricter, added check: two summary rows disagreeing on one fund's total now halt
  (`wa_pdc.control_totals_cents`) instead of last-writer-wins.

## 2b. The second real failure mode: control totals that postdate the snapshot

The first full live run (2026-07-07T15:33Z) halted on exactly one group — fund 27194
(OPEIU Local 8 PAC, a continuing committee): itemized $5,883.86 vs control $5,923.63.
Diagnosis, verified live:

- The **summary mirror syncs rows continuously** (fund 27194's summary row:
  Socrata `:updated_at` = 2026-07-07T15:28:39Z — five minutes before our fetch),
  while the **itemized mirror refreshes in periodic batches** (dataset
  `rowsUpdatedAt` = 2026-07-02T16:14Z at fetch time; the next batch landed at
  15:36Z, minutes after). At ~14:40Z the same summary row still said $5,883.86 —
  matching our itemized sum exactly.
- So for a window of hours around every summary resync, a freshly recalculated
  control total counts a report whose line items the itemized mirror does not
  carry yet. **A control total computed after the data snapshot cannot verify
  that snapshot.** This is chronic (it recurs after every new filing), so
  "retry tomorrow" is not a strategy.

**Rejected first fix — clock anchors.** Comparing the summary row's Socrata
`:updated_at` against the itemized dataset's `rowsUpdatedAt` looked sufficient but is
not: on the very next fetch, `rowsUpdatedAt` had bumped to 15:36Z while the itemized
snapshot bytes were **byte-identical** to the pre-"refresh" fetch — the mirror-level
clock overstates content currency (a batch export can publish without carrying the
newest upstream filings). No wall-clock anchor on the itemized side is trustworthy.

**Adopted rule — report-presence, fully content-based.** PDC publishes the per-report
registry itself: **"Campaign Finance Reporting History"** (Socrata `7qr9-q2c9`), which
lists every filed report per fund (`report_number`, `origin`, `amends_report`/
`amended_by_report`, `receipt_date`) and syncs as fast as the summary (the missing
report appeared there the same day). Both the itemized feed and the registry carry
`report_number`, so completeness is checkable exactly:

> Derive the snapshot's content cutoff = the newest `receipt_date` among registry
> reports that ARE present in the itemized snapshot. A fund is **deferred** iff the
> registry lists an unamended `C3` (cash-receipts) report for it, received on/after
> that cutoff, that is absent from the itemized rows — a control total that already
> counts a not-yet-mirrored report cannot be verified by this snapshot.

Deferral = every one of that fund's input rows quarantined with the missing report
number(s) recorded (`wa_pdc.deferred_funds_missing_reports`; the no-silent-drop
invariant still counts them); nothing of the fund publishes or crosswalks this run,
and it flows through the full gate next run. The recency scope matters: an OLD absent
C3 is legitimately line-item-free (440 window funds have one and reconcile exactly),
so only fresh unmirrored reports defer — live, the rule defers exactly the two funds
whose reports were filed the same day (27194/110370630, 27664/110370632). The
unchanged control-total gate then runs at epsilon 0 over every report-complete fund
and still halts on any mismatch among them — deferral can only ever *narrow* what
publishes, never let a mismatch through; a fund with **no** control row at all still
halts the run; and with no registry provided (`history_records=None`) nothing defers —
strict by default. A mid-fetch itemized refresh (detected via `rowsUpdatedAt`
before/after paging) aborts the snapshot outright.

## 3. Windows and scope

The pilot window is now defined as: *every fund with at least one itemized row in
`election_year >= 2025`, fetched whole.* The completion pass is a batched
`fund_id in (...) AND election_year < 2025` sweep (currently returns a handful of
rows). The summary is fetched whole — it is small (57,731 rows all-time) and this
guarantees every seen fund finds its control row regardless of year labels.

## 4. Filer → legislator crosswalk: no native shared id exists

Checked exhaustively 2026-07-07:

- **PDC side.** The Campaign Finance Summary is PDC's de-facto filer/candidacy
  registry (`filer_id`, `committee_id`, `fund_id`, `person_id`, `filer_type`). Their
  `person_id` is documented as "the preferred id for identifying a natural person" —
  but it is PDC-internal. No PDC dataset on data.wa.gov carries an external person
  identifier (searched the Socrata catalog for filer/candidacy/candidates/registration/
  pdc; datasets enumerated in the WO-19 session log).
- **OpenStates side.** The bulk people CSV (`data.openstates.org/people/current/wa.csv`)
  carries `id` (ocd-person), names, district/chamber, contacts, and `wikidata` — no PDC id.
- **Wikidata bridge.** No Wikidata property exists for WA PDC ids
  (`wbsearchentities` for "Public Disclosure Commission" and "Washington State
  Legislature" property types: zero results), so the ocd-person↔wikidata chain has no
  PDC endpoint.

Per the WO and TRUSTED-EXTRACTION §9, name/office/year joins are fuzzy and forbidden
for publication (and PDC filer_name strings confirm why —
`"Robert D. Hicks (Robert (Chili) Hicks)"`). Therefore:

- **Published links** exist only via `bulk/wa_pdc_allowlist.json` — a committed,
  human-reviewed mapping `wa_pdc_person_id → ocd_person` (+ evidence URL). It ships
  **empty**. The transform joins it exactly (PDC person_id → candidate funds; ocd-person
  → spine via `person_identifiers`), landing `disclosure_filer_links` rows that carry
  the fund's gate-reconciled summary totals and the §6 envelope.
- **Every state-legislative candidacy** observed in the slice (itemized `office` ∈
  {STATE SENATOR, STATE REPRESENTATIVE}) is scored deterministically against the seat's
  current spine holder (exact chamber+district; name-equality flag as context) into
  `disclosure_link_candidates` — a quarantine table the build stage never reads. A human
  reviews a candidate, verifies the PDC registration, and promotes it by adding an
  allowlist entry; money then surfaces on the next run with no code change.

**Consequence:** until the first allowlist entries are reviewed in, **zero** WA
legislators publish a Money section from PDC data. Unlinked is honest; a wrong link is
not. The full surfacing path (dossier `money.campaign_finance` with cycles = verbatim
reconciled fund totals + the fixed symmetric employer rollup, methodology anchor
`state-donor-rollups`) is built and tested end-to-end with a fixture allowlist.

## 5. What would falsify this design

- PDC re-keys funds or ships duplicate fund_id summary rows with different totals →
  the run halts (conflicting-basis check / control-total gate).
- The itemized layout changes → schema-drift gate halts (the observed header is now
  fetched from dataset metadata, so drift is really observed).
- The itemized mirror refreshes mid-fetch → the snapshot is refused (fetch skip;
  a hydrated prior snapshot remains the basis).
- A time-consistent fund that still mismatches (a genuine parse or upstream error,
  not mirror lag) → control-total gate halts, exactly as before. The deferral rule
  (§2b) is timestamp-scoped and cannot absorb it.
- The reverse lag (itemized rows newer than their summary recalculation) is not
  deferrable per-fund and would halt the run honestly; it was not observed — the
  summary mirror syncs far more frequently than the itemized one.
