-- 002_legislative.sql · Bills, votes, committees, ideology (data-contracts v1 §2)

CREATE TABLE bills (
  bill_id          TEXT PRIMARY KEY,
  jurisdiction     TEXT NOT NULL,
  session          TEXT NOT NULL,
  title            TEXT NOT NULL,
  status           TEXT NOT NULL CHECK (status IN
    ('introduced','committee','passed_chamber','passed_both','law','vetoed','failed')),
  introduced_on    DATE,
  latest_action_on DATE,
  policy_areas     TEXT[],
  embedding        VECTOR(1024)
);

CREATE TABLE sponsorships (
  bill_id      TEXT NOT NULL REFERENCES bills(bill_id),
  person_id    UUID NOT NULL REFERENCES persons(person_id),
  role         TEXT NOT NULL CHECK (role IN ('sponsor','cosponsor')),
  is_original  BOOLEAN,
  sponsored_on DATE,
  withdrawn_on DATE,
  PRIMARY KEY (bill_id, person_id, role)
);

CREATE TABLE roll_calls (
  roll_call_id TEXT PRIMARY KEY,
  bill_id      TEXT REFERENCES bills(bill_id),
  chamber      TEXT NOT NULL,
  question     TEXT NOT NULL,
  held_at      TIMESTAMPTZ NOT NULL,
  result       TEXT NOT NULL
);

CREATE TABLE vote_positions (
  roll_call_id TEXT NOT NULL REFERENCES roll_calls(roll_call_id),
  person_id    UUID NOT NULL REFERENCES persons(person_id),
  position     TEXT NOT NULL CHECK (position IN ('yea','nay','present','not_voting')),
  PRIMARY KEY (roll_call_id, person_id)
);

CREATE TABLE committees (
  committee_id TEXT PRIMARY KEY,
  jurisdiction TEXT NOT NULL,
  chamber      TEXT,
  name         TEXT NOT NULL,
  parent_id    TEXT REFERENCES committees(committee_id)
);

CREATE TABLE committee_memberships (
  committee_id TEXT NOT NULL REFERENCES committees(committee_id),
  person_id    UUID NOT NULL REFERENCES persons(person_id),
  congress     SMALLINT NOT NULL,
  role         TEXT NOT NULL CHECK (role IN ('member','chair','ranking','vice_chair')),
  PRIMARY KEY (committee_id, person_id, congress)
);

CREATE TABLE ideology_scores (
  person_id      UUID NOT NULL REFERENCES persons(person_id),
  scheme         TEXT NOT NULL CHECK (scheme IN ('dw_nominate_dim1','shor_mccarty')),
  score          NUMERIC(6,4),
  status         TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok','pending_insufficient_votes')),
  scope          TEXT NOT NULL,
  computed_as_of DATE NOT NULL,
  PRIMARY KEY (person_id, scheme, scope)
);
