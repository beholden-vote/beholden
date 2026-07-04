-- 003_money.sql · STOCK Act trades, disclosures, campaign finance (data-contracts v1 §2)

CREATE TYPE amount_bracket AS ENUM (
  '1k_15k','15k_50k','50k_100k','100k_250k','250k_500k',
  '500k_1m','1m_5m','5m_25m','25m_50m','over_50m','unknown');

CREATE TABLE trades (
  trade_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  person_id          UUID NOT NULL REFERENCES persons(person_id),
  filing_id          TEXT NOT NULL,
  filing_url         TEXT NOT NULL,           -- REQUIRED: link to original filing
  ticker             TEXT,
  asset_name         TEXT NOT NULL,
  asset_type         TEXT,
  txn_type           TEXT NOT NULL CHECK (txn_type IN ('purchase','sale_full','sale_partial','exchange')),
  amount             amount_bracket NOT NULL,
  owner              TEXT CHECK (owner IN ('self','spouse','joint','dependent')),
  transacted_on      DATE NOT NULL,
  filed_on           DATE NOT NULL,
  late_by_days       SMALLINT GENERATED ALWAYS AS
                       (GREATEST(0, (filed_on - transacted_on) - 45)) STORED,
  source             TEXT NOT NULL,           -- 'internal' | 'community:<name>' | 'vendor:<name>'
  extract_confidence NUMERIC(4,3),
  review_status      TEXT NOT NULL DEFAULT 'auto'
                       CHECK (review_status IN ('auto','human_verified','quarantined'))
);
-- Publish rule (enforced in build layer): never publish review_status='quarantined';
-- internal-source rows require extract_confidence >= threshold OR human_verified.

CREATE TABLE net_worth_estimates (
  person_id       UUID NOT NULL REFERENCES persons(person_id),
  disclosure_year SMALLINT NOT NULL,
  min_cents       BIGINT NOT NULL,
  max_cents       BIGINT NOT NULL CHECK (max_cents >= min_cents),
  methodology_id  TEXT NOT NULL,
  filing_url      TEXT NOT NULL,
  PRIMARY KEY (person_id, disclosure_year, methodology_id)
);

CREATE TABLE campaign_finance_cycles (
  person_id          UUID NOT NULL REFERENCES persons(person_id),
  cycle              SMALLINT NOT NULL,
  fec_committee_id   TEXT NOT NULL,
  total_raised_cents BIGINT,
  total_spent_cents  BIGINT,
  cash_on_hand_cents BIGINT,
  as_of              DATE NOT NULL,
  PRIMARY KEY (person_id, cycle, fec_committee_id)
);

CREATE TABLE top_contributors (
  person_id        UUID NOT NULL REFERENCES persons(person_id),
  cycle            SMALLINT NOT NULL,
  contributor_name TEXT NOT NULL,
  total_cents      BIGINT NOT NULL,
  rank             SMALLINT NOT NULL,
  PRIMARY KEY (person_id, cycle, rank)
);
