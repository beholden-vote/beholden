# WO-9 — SOS bulk-disclosure pilot (Washington PDC, Tier A)

**Lane P · prereq: none (independent of WO-1..WO-8) · read `docs/workplan/README.md`,
`AGENTS.md`, and `docs/TRUSTED-EXTRACTION.md` first**

## Objective
Prove the trusted-extraction framework (`docs/TRUSTED-EXTRACTION.md`) end to end on one
license-clean, well-structured state source — **Washington Public Disclosure Commission
(PDC)** itemized contributions — landing deterministically extracted, fully-cited donor
records with fail-closed reconciliation. No model in the extraction path. This is the
reference implementation every later state adapter copies; correctness of the *framework*
matters more than breadth of data.

## Data source (verified 2026-07-05, no key)
- **Itemized contributions** (primary): Socrata dataset `kv7h-kjye` on `data.wa.gov`.
  - Bulk: `https://data.wa.gov/api/views/kv7h-kjye/rows.csv?accessType=DOWNLOAD`
    (or the SoQL JSON endpoint `https://data.wa.gov/resource/kv7h-kjye.json` with
    `$limit/$offset` paging).
  - **License: Public Domain.** Attribution: Public Disclosure Commission. (Record in the
    contract verbatim.)
  - 37 fields. Keys/fields we use: `id` (native record id), `report_number`, `filer_id`,
    `filer_name`, `office`, `party`, `legislative_district`, `election_year`, `amount`,
    `cash_or_in_kind`, `receipt_date`, `contributor_name`, `contributor_city`,
    `contributor_state`, `contributor_occupation`, `contributor_employer_name`,
    `url` (per-record official link — use as `source_record_url`).
- **Control totals** (reconciliation): Socrata dataset `3h9x-7bvm` — "Campaign Finance
  Summary". Use the per-filer/per-report contribution totals as the control the itemized
  sum must reconcile against. Verify the exact total field name against the dataset
  metadata before wiring; **if a matching control total can't be established, STOP and
  report** (do not ship the itemized data without a reconciliation basis).

If any endpoint, field name, or license string differs from the above on the day of
implementation — **STOP and report, do not guess or fabricate.**

## Files
- NEW `pipelines/beholden_etl/bulk/contract.py` — `SourceContract` type + load/validate
  (schema-drift check via header/field fingerprint).
- NEW `pipelines/beholden_etl/bulk/reconcile.py` — the fail-closed gates: schema-drift,
  control-total, no-silent-drop invariant, value-domain.
- NEW `pipelines/beholden_etl/sources/wa_pdc.py` — the WA PDC adapter: declares its
  `SourceContract`, fetch (paged/bulk + SHA-256 snapshot), and deterministic row mappers
  (copy-only, per-row provenance envelope).
- NEW `db/migrations/00N_disclosure.sql` — `disclosure_contributions`
  (native id PK, filer_id, contributor fields, amount_cents, receipt_date, source_record_url,
  provenance columns) + `disclosure_quarantine` (row + reason). Follow the existing
  migration style; remember `store.init_schema` loads `db/migrations/*.sql` in sorted order
  and self-referential/partial-index shims live in `store._shim`.
- SHARED (marked insertions only): `jobs/fetch.py` (land the two WA snapshots + manifest
  counts/hash), `jobs/transform.py` (parse → reconcile gates → `disclosure_contributions`;
  quarantine the rest), `pipelines/tests/test_pipeline.py` (fixtures + tests).
- Do **not** touch `web/`, `spike/`, `.github/` in this WO. Dossier surfacing of WA state
  donor data is a deliberate follow-on (needs the state-legislator ↔ filer link, §below).

## Implementation notes
- **Extraction is copy-only.** Mappers convert `amount` dollars → integer `amount_cents`
  and parse `receipt_date` to a date; they do **not** normalize names, infer, or compute
  anything else. Every row carries the §6 provenance envelope (`file_sha256`,
  `contract_version`, native `id` as `record_locator`, `url` as `source_record_url`,
  and the raw `amount`/`contributor_name` retained).
- **Gates (all fail-closed, per `docs/TRUSTED-EXTRACTION.md` §5):**
  - schema-drift: the CSV/JSON header must match the pinned contract field set exactly.
  - control-total: Σ(`amount`) grouped as the summary feed groups it must equal the
    summary total within a declared rounding epsilon.
  - no-silent-drop: `input == inserted + quarantined`, asserted at end of transform.
  - value-domain: bad `cash_or_in_kind` enum / unparseable date / non-numeric amount →
    quarantine with reason, never coerced.
- **Entity resolution (deterministic only).** Do NOT fuzzy-match `filer_name` to the
  person spine in this WO. Land the data keyed by WA `filer_id`; a filer↔person crosswalk
  (deterministic, via OpenStates/OCD ids where WA PDC exposes them, else left unlinked) is
  an explicit follow-on. Unlinked is honest; a wrong link is not.
- Keep transform bounded: page/stream the itemized feed; chunk-insert via `store.insert`.

## Acceptance
- **Framework tests (the point of the WO):** fixtures exercising (a) a clean parse with a
  matching control total → rows land; (b) a control-total mismatch → gate halts;
  (c) a drifted header → schema gate halts; (d) an out-of-domain value → quarantined with
  reason, `input == inserted + quarantined` holds; (e) idempotent re-parse is identical.
- `cd pipelines && ../.venv/Scripts/python.exe -m pytest -q` all green (existing + new);
  `../.venv/Scripts/python.exe -m ruff check .` clean.
- A short note appended to `docs/TRUSTED-EXTRACTION.md` (or a sibling) recording the WA PDC
  contract as the first real `SourceContract` (source_id, endpoints, license, control-total
  field actually used, contract_version).

## Out of scope (note as follow-ons)
- Dossier UI surfacing of WA donor data and the deterministic filer↔legislator crosswalk.
- Any second state (each is its own contract + adapter).
- Tier B (form-PDF grounded extraction) and Tier C (scanned/free-text) — not attempted.
