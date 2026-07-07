-- 006_disclosure_crosswalk.sql · WA PDC reconciliation fix + deterministic
-- filer<->person crosswalk (WO-19; docs/TRUSTED-EXTRACTION.md §5/§9,
-- docs/research/wa-pdc-reconciliation-findings.md).
--
-- committee_id / fund_id come VERBATIM from the itemized feed (contract
-- 2026-07-07). fund_id is PDC's own documented cross-dataset correlation key
-- ("the unique identifier for all reporting and finance records associated with
-- a single campaign") and is the control-total reconciliation group — the old
-- (filer_id, election_year) grouping was rejected by the gate on real data
-- because the two feeds disagree on filer_id format and a filer can run several
-- funds per year.

ALTER TABLE disclosure_contributions ADD COLUMN committee_id TEXT;
ALTER TABLE disclosure_contributions ADD COLUMN fund_id TEXT;  -- NOT NULL enforced by map_row quarantine
CREATE INDEX idx_disclosure_contributions_fund ON disclosure_contributions (fund_id);

-- The PUBLISHED half of the crosswalk: one row per (linked person, PDC fund).
-- Rows exist ONLY for allowlist entries — a committed, human-reviewed exact-id
-- mapping (bulk/wa_pdc_allowlist.json) from PDC person_id (their "preferred id
-- for identifying a natural person") to an OpenStates ocd-person id already in
-- the spine. NO name matching feeds this table (§9: publish on deterministic
-- keys only). Cycle totals are verbatim summary-feed cells; the §6 envelope
-- (file_sha256 = the summary snapshot) rides inline like disclosure_contributions.
CREATE TABLE disclosure_filer_links (
  fund_id            TEXT PRIMARY KEY,        -- PDC fund (one campaign's finance records)
  person_id          UUID NOT NULL REFERENCES persons(person_id),
  wa_pdc_person_id   TEXT NOT NULL,           -- PDC person_id (allowlist key)
  filer_id           TEXT NOT NULL,           -- verbatim summary filer_id
  committee_id       TEXT,
  election_year      SMALLINT NOT NULL,
  filer_name         TEXT,
  contributions_amount_cents BIGINT NOT NULL, -- verbatim summary contributions_amount
  expenditures_amount_cents  BIGINT,          -- verbatim summary expenditures_amount
  summary_updated_at TEXT,                    -- PDC's own last-recalculated stamp
  evidence_url       TEXT NOT NULL,           -- the allowlist entry's human-review evidence
  source_id          TEXT NOT NULL,           -- provenance (§6, summary snapshot)
  contract_version   TEXT NOT NULL,
  file_sha256        TEXT NOT NULL,
  retrieved_at       TEXT NOT NULL,
  source_record_url  TEXT NOT NULL            -- summary row's own url (C1 registration)
);
CREATE INDEX idx_disclosure_filer_links_person ON disclosure_filer_links (person_id);

-- The QUARANTINED half: scored link candidates for HUMAN review — never read by
-- the build stage, never published (§9: fuzzy name/employer matches go to a
-- scored candidate table; promotion requires the reviewed allowlist). One row
-- per state-legislative candidacy fund observed in the ingested slice, carrying
-- the seat's current spine holder (matched on chamber+district) and a
-- deterministic name-equality flag as review context.
CREATE TABLE disclosure_link_candidates (
  candidate_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id          TEXT NOT NULL,
  contract_version   TEXT NOT NULL,
  file_sha256        TEXT NOT NULL,
  wa_pdc_person_id   TEXT,                    -- PDC person_id when the summary carries one
  filer_id           TEXT,
  fund_id            TEXT,
  election_year      SMALLINT,
  filer_name         TEXT,                    -- verbatim
  office             TEXT,                    -- verbatim itemized office
  legislative_district TEXT,                  -- verbatim itemized district
  matched_person_id  UUID,                    -- current seat holder in our spine, if any
  matched_ocd_person TEXT,
  matched_name       TEXT,
  match_basis        TEXT NOT NULL            -- e.g. 'seat:upper/33 name_exact=false' | 'allowlist_unresolved: ...'
);
