-- 001_spine.sql · Identity + geography spine (data-contracts v1 §2)
-- Postgres-flavored canonical DDL. The free-tier DuckDB pipeline uses this file with
-- two shims applied at load time: gen_random_uuid()->uuid(), VECTOR(n)->FLOAT[n].

CREATE TABLE persons (
  person_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  full_name     TEXT NOT NULL,
  given_name    TEXT,
  family_name   TEXT,
  birth_year    SMALLINT,
  wikidata_qid  TEXT UNIQUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE person_identifiers (
  person_id   UUID NOT NULL REFERENCES persons(person_id) ON DELETE CASCADE,
  id_scheme   TEXT NOT NULL CHECK (id_scheme IN ('bioguide','fec','icpsr','openstates','ballotpedia')),
  id_value    TEXT NOT NULL,
  is_primary  BOOLEAN NOT NULL DEFAULT true,
  PRIMARY KEY (id_scheme, id_value)
);
CREATE INDEX idx_person_identifiers_person ON person_identifiers (person_id);

CREATE TABLE quarantine_identities (
  quarantine_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  raw_payload    JSONB NOT NULL,
  source         TEXT NOT NULL,
  llm_suggestion JSONB,
  resolved_by    TEXT,
  resolved_at    TIMESTAMPTZ,
  resolution     TEXT CHECK (resolution IN ('matched','new_person','rejected'))
);

CREATE TABLE divisions (
  ocd_id      TEXT PRIMARY KEY,
  parent_ocd  TEXT REFERENCES divisions(ocd_id),
  level       TEXT NOT NULL CHECK (level IN ('country','state','cd','sldu','sldl','county','place')),
  name        TEXT NOT NULL,
  geoid       TEXT,
  valid_from  DATE NOT NULL,
  valid_to    DATE
);

CREATE TABLE offices (
  office_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ocd_id      TEXT NOT NULL REFERENCES divisions(ocd_id),
  branch      TEXT NOT NULL CHECK (branch IN ('legislative','executive')),
  chamber     TEXT,
  role        TEXT NOT NULL
);

CREATE TABLE terms (
  term_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  person_id        UUID NOT NULL REFERENCES persons(person_id),
  office_id        UUID NOT NULL REFERENCES offices(office_id),
  party            TEXT NOT NULL,
  start_date       DATE NOT NULL,
  end_date         DATE,
  end_reason       TEXT,
  is_vacant_marker BOOLEAN NOT NULL DEFAULT false,
  meta             JSONB
);
CREATE INDEX idx_terms_current ON terms (office_id) WHERE end_date IS NULL;
