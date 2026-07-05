-- 004_disclosure.sql · Trusted-extraction bulk disclosure (docs/TRUSTED-EXTRACTION.md)
-- First Tier-A source: Washington PDC itemized contributions (Socrata kv7h-kjye,
-- Public Domain). Rows are copied VERBATIM from a content-hashed snapshot — no model
-- in the path — and carry the §6 provenance envelope inline. The reconcile stage
-- (bulk/reconcile.py) fails the run closed before anything here is trusted downstream.
--
-- Entity resolution is deliberately deferred: rows land keyed by the WA filer_id only
-- (no fuzzy link to the person spine), so there is intentionally NO FK to persons here.
-- A deterministic filer<->person crosswalk is an explicit follow-on (WO-9 §out-of-scope).

CREATE TABLE disclosure_contributions (
  id                 TEXT PRIMARY KEY,        -- native Socrata record id (record_locator)
  source_id          TEXT NOT NULL,           -- provenance: SourceContract.source_id
  contract_version   TEXT NOT NULL,           -- provenance: pinned contract version
  file_sha256        TEXT NOT NULL,           -- provenance: SHA-256 of the exact snapshot bytes
  retrieved_at       TEXT NOT NULL,           -- provenance: retrieval timestamp (ISO-8601)
  source_record_url  TEXT NOT NULL,           -- provenance: per-record official filing link (url)
  report_number      TEXT,
  filer_id           TEXT NOT NULL,           -- WA PDC filer id (the only entity key we trust)
  filer_name         TEXT,
  office             TEXT,
  party              TEXT,
  legislative_district TEXT,
  election_year      SMALLINT NOT NULL,       -- reconciliation grouping key (with filer_id)
  amount_cents       BIGINT NOT NULL,         -- amount dollars -> integer cents (signed: refunds < 0)
  cash_or_in_kind    TEXT NOT NULL CHECK (cash_or_in_kind IN ('Cash','In-kind')),
  receipt_date       DATE,
  contributor_name   TEXT,
  contributor_city   TEXT,
  contributor_state  TEXT,
  contributor_occupation    TEXT,
  contributor_employer_name TEXT,
  raw_amount         TEXT NOT NULL,           -- verbatim source cell, retained forever (§6)
  raw_contributor_name TEXT                   -- verbatim source cell, retained forever (§6)
);
CREATE INDEX idx_disclosure_contributions_filer ON disclosure_contributions (filer_id, election_year);

-- Every input row is accounted for: published above, or quarantined here WITH a reason
-- (no-silent-drop invariant, §5). raw_payload keeps the whole verbatim row for review.
CREATE TABLE disclosure_quarantine (
  quarantine_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id      TEXT NOT NULL,
  contract_version TEXT NOT NULL,
  file_sha256    TEXT NOT NULL,
  record_locator TEXT,                        -- native id when present (may be absent on a bad row)
  reason         TEXT NOT NULL,               -- why it was quarantined (never coerced into range)
  raw_payload    JSONB NOT NULL               -- the verbatim source row
);
