"""Offline regression suite for the federal ETL slice. Runs with no network,
no API keys, and no GDAL — synthetic fixtures exercise the real code paths.

    cd pipelines && pytest        # or: pytest pipelines/tests
"""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from beholden_etl import store
from beholden_etl.build import dossiers
from beholden_etl.jobs import build, transform
from beholden_etl.sources import legislators

REPO = Path(__file__).resolve().parents[2]


# --- tile OCD stamper (lives in spike/, imported by path) -------------------
def _load_stamper():
    spec = importlib.util.spec_from_file_location("stamp_ocd_ids", REPO / "spike" / "stamp_ocd_ids.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_stamp_ocd_ids_conventions():
    s = _load_stamper()
    assert s.feature_props("states", {"STATEFP": "47", "NAME": "Tennessee", "GEOID": "47"}) == {
        "ocd_id": "ocd-division/country:us/state:tn", "name": "Tennessee", "geoid": "47"}
    # at-large (CDFP 00) and delegate (98) both collapse to cd:1 -> matches the ETL key
    assert s.feature_props("cd", {"STATEFP": "02", "CD119FP": "00"})["ocd_id"] == \
        "ocd-division/country:us/state:ak/cd:1"
    assert s.feature_props("cd", {"STATEFP": "47", "CD119FP": "06"})["ocd_id"] == \
        "ocd-division/country:us/state:tn/cd:6"
    assert s.feature_props("sldl", {"STATEFP": "48", "SLDLST": "ZZZ"}) is None   # undefined dropped
    assert s.feature_props("states", {"STATEFP": "99"}) is None                  # foreign FIPS dropped


def test_stamp_county_slug_rule():
    """County slugs must mirror ocd-division-ids' make_id EXACTLY, and the
    division type is state-dependent (AK=borough, LA=parish, else county).
    Slug spot-checks verified against the canonical country-us.csv."""
    s = _load_stamper()
    # plain name
    assert s.feature_props("county", {"STATEFP": "47", "NAME": "Anderson", "GEOID": "47001"}) == {
        "ocd_id": "ocd-division/country:us/state:tn/county:anderson",
        "state": "TN", "name": "Anderson", "geoid": "47001"}
    # 'St. Clair' -> st_clair  (period+space collapses to one underscore)
    assert s.feature_props("county", {"STATEFP": "01", "NAME": "St. Clair"})["ocd_id"] == \
        "ocd-division/country:us/state:al/county:st_clair"
    # apostrophe -> '~' :  "Prince George's" -> prince_george~s
    assert s.feature_props("county", {"STATEFP": "24", "NAME": "Prince George's"})["ocd_id"] == \
        "ocd-division/country:us/state:md/county:prince_george~s"
    # hyphen kept:  'Miami-Dade' -> miami-dade
    assert s.feature_props("county", {"STATEFP": "12", "NAME": "Miami-Dade"})["ocd_id"] == \
        "ocd-division/country:us/state:fl/county:miami-dade"
    # Alaska is a BOROUGH, not a county, in the canonical ids
    assert s.feature_props("county", {"STATEFP": "02", "NAME": "Anchorage"})["ocd_id"] == \
        "ocd-division/country:us/state:ak/borough:anchorage"
    # Louisiana is a PARISH
    assert s.feature_props("county", {"STATEFP": "22", "NAME": "Acadia"})["ocd_id"] == \
        "ocd-division/country:us/state:la/parish:acadia"
    # foreign / unknown FIPS dropped
    assert s.feature_props("county", {"STATEFP": "99", "NAME": "Nowhere"}) is None


def test_stamp_cli_entrypoint():
    """Exercise the actual CLI (stdin->stdout) as build_pmtiles.sh invokes it."""
    import subprocess
    import sys
    feat = '{"type":"Feature","properties":{"STATEFP":"47","NAME":"Tennessee","GEOID":"47"},"geometry":null}\n'
    r = subprocess.run([sys.executable, str(REPO / "spike" / "stamp_ocd_ids.py"), "states"],
                       input=feat, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert '"ocd-division/country:us/state:tn"' in r.stdout


# --- DuckDB warehouse -------------------------------------------------------
def test_schema_loads_with_generated_column():
    con = store.connect()
    store.init_schema(con)
    store.insert(con, "persons", [{"person_id": "11111111-1111-1111-1111-111111111111", "full_name": "X"}])
    store.insert(con, "trades", [{
        "trade_id": "44444444-4444-4444-4444-444444444444",
        "person_id": "11111111-1111-1111-1111-111111111111", "filing_id": "F", "filing_url": "http://x",
        "asset_name": "A", "txn_type": "purchase", "amount": "15k_50k",
        "transacted_on": "2026-01-01", "filed_on": "2026-03-20", "source": "internal"}])
    assert con.execute("SELECT late_by_days FROM trades").fetchone()[0] == 33  # 78 days - 45


# --- transform + build vertical slice ---------------------------------------
# Jane carries a PAST term (2023-2025, a prior AK-at-large stint before TN-06 —
# unrealistic geographically but exercises previous_roles without new fixture
# plumbing) plus a wikidata id, so she is the WO-15 happy path: contact,
# district offices, social, previous_roles, birth_year, education all present.
# Al and Sam carry NO wikidata id and Jane's current term carries no phone/
# contact_form — the honest-absence paths (WO-15 test coverage).
LEGS = [
    {"id": {"bioguide": "R000001", "icpsr": "11", "fec": ["H8TN06001"], "wikidata": "Q123456"},
     "name": {"first": "Jane", "last": "Rep", "official_full": "Jane Rep"},
     "bio": {"birthday": "1970-05-01"},
     "terms": [
         {"type": "rep", "start": "2023-01-03", "end": "2025-01-03", "state": "AK", "district": 0, "party": "Democrat"},
         {"type": "rep", "start": "2025-01-03", "end": "2027-01-03", "state": "TN", "district": 6, "party": "Republican",
          "phone": "202-225-0001", "url": "https://rep.house.gov", "contact_form": "https://rep.house.gov/contact",
          "address": "1234 Longworth House Office Building Washington DC 20515"}]},
    {"id": {"bioguide": "A000002", "icpsr": "22"}, "name": {"official_full": "Al Large"},
     "terms": [{"type": "rep", "start": "2025-01-03", "end": "2027-01-03", "state": "AK", "district": 0, "party": "Democrat"}]},
    # Sam DOES have a wikidata_qid but the fixture's claims file gives him a
    # blank P69 (below) -> education must be an ABSENT key on his dossier, not
    # a fabricated empty array (WO-15 fail-closed/honest-absence coverage).
    {"id": {"bioguide": "S000003", "icpsr": "33", "wikidata": "Q999999"}, "name": {"official_full": "Sam Sen"},
     "terms": [{"type": "sen", "start": "2021-01-03", "end": "2027-01-03", "state": "TN", "party": "Republican", "class": 1}]},
]

# --- WO-15: district offices + social media (federal, keyed by bioguide) ---
DISTRICT_OFFICES = [
    {"id": {"bioguide": "R000001"}, "offices": [
        {"id": "R000001-x", "address": "100 Main St", "city": "Nashville", "state": "TN",
         "zip": "37201", "phone": "615-555-0100", "latitude": 36.16, "longitude": -86.78}]},
]
SOCIAL_MEDIA = [
    {"id": {"bioguide": "R000001"}, "social": {"twitter": "JaneRep", "mastodon": "@janerep@mastodon.social"}},
]

# --- WO-15: congress.gov member-detail (bioguide -> record) -----------------
MEMBER_DETAIL = {
    "R000001": {
        "birthYear": "1970",
        "leadership": [{"type": "Chair", "congress": 119}],
        "partyHistory": [{"partyName": "Republican", "startYear": 2025, "endYear": None}],
        "addressInformation": {"officeAddress": "1234 Longworth HOB", "city": "Washington",
                                "zipCode": "20515", "phoneNumber": "202-225-0001"},
    },
    # Al: honest-absence path — no member-detail file at all this run.
}

# --- WO-15: Wikidata education (claims by qid + batched labels) -------------
WIKIDATA_CLAIMS = {
    "Q123456": [{"institution_qid": "Q1", "degree_qid": "Q2", "end_year": 1992},
                {"institution_qid": "Q3"}],   # no degree/year -> both omitted
    "Q999999": [],   # Sam: a qid resolved, but a blank P69 -> empty claims list
}
WIKIDATA_LABELS = {"Q1": "Test University", "Q2": "Bachelor of Arts", "Q3": "Night School"}
# Mirrors real Voteview columns: no congress_end_date exists in HSxxx_members.csv,
# so computed_as_of must come from the fetch manifest (or the congress boundary).
VOTEVIEW = ("congress,chamber,icpsr,nominate_dim1,nominate_number_of_votes\n"
            "119,House,11,0.512,300\n"
            "119,House,22,-0.301,250\n"
            "119,Senate,33,0.488,5\n"               # Sam: <20 votes -> pending
            "119,President,,0.9,10\n")              # blank icpsr: skipped, never crashes

# Dynamic (1h ago) so within_sla assertions never rot as wall-clock advances.
RETRIEVED_AT = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
MANIFEST = {"generated_at": RETRIEVED_AT, "congress": 119, "sources": {
    "unitedstates_legislators": {"retrieved_at": RETRIEVED_AT, "source_url": "https://x", "count": 3},
    "congress.gov": {"retrieved_at": RETRIEVED_AT, "source_url": "https://x", "count": 3},
    "voteview": {"retrieved_at": RETRIEVED_AT, "source_url": "https://x", "count": 4},
    "fec": {"retrieved_at": RETRIEVED_AT, "source_url": "https://x", "count": 1},
    "openstates": {"retrieved_at": RETRIEVED_AT, "source_url": "https://openstates.org/", "count": 2},
    "house_clerk": {"retrieved_at": RETRIEVED_AT, "source_url": "https://x", "count": 1},
    "wikidata": {"retrieved_at": RETRIEVED_AT, "source_url": "https://www.wikidata.org", "count": 1},
}}

# A House PTR filing that name-matches Jane Rep (family "Rep", first "Jane").
HOUSE_PTR = [{"last": "Rep", "first": "Jane", "suffix": "", "state_dst": "TN06",
              "filed_on": "2025-05-01", "doc_id": "20099999", "year": 2025}]

# Two TN state legislators — one per chamber — to light up sldu/sldl (E4).
# Pat carries contact + social columns (WO-15 happy path); Dana carries NEITHER
# (honest-absence path for a state legislator: identity.contact/social simply
# omitted, never a fabricated empty object).
OPENSTATES_TN_CSV = (
    "id,name,current_party,current_district,current_chamber,given_name,family_name,image,birth_date,sources,"
    "email,capitol_address,capitol_voice,capitol_fax,district_address,district_voice,district_fax,"
    "twitter,youtube,instagram,facebook\n"
    "ocd-person/aaaa1111-1111-1111-1111-111111111111,Pat Upper,Republican,5,upper,Pat,Upper,https://img/pat.jpg,1975-03-02,https://capitol.tn.gov/pat,"
    "pat.upper@leg.tn.gov,301 Capitol,615-555-0001,,88 District Rd,615-555-0002,,patupper,,patupper_ig,patupper.fb\n"
    "ocd-person/bbbb2222-2222-2222-2222-222222222222,Dana Lower,Democratic,10,lower,Dana,Lower,,1982-07-11,https://capitol.tn.gov/dana,"
    ",,,,,,,,,,\n"
)

# WO-17: a WA state legislator whose state has NO landed votes snapshot — the
# honest-absent path: identity-only dossier, no legislative section, never a
# fabricated zero count.
OPENSTATES_WA_CSV = (
    "id,name,current_party,current_district,current_chamber,given_name,family_name,image,birth_date,sources,"
    "email,capitol_address,capitol_voice,capitol_fax,district_address,district_voice,district_fax,"
    "twitter,youtube,instagram,facebook\n"
    "ocd-person/dddd4444-4444-4444-4444-444444444444,Wanda West,Democratic,3,lower,Wanda,West,,,https://leg.wa.gov/wanda,"
    ",,,,,,,,,,\n"
)

# WO-17: the TN state-votes lake snapshot (raw/openstates/votes/tn.json) —
# shaped like sources/openstates_votes.crawl_state output, bill records shaped
# per the v3 OpenAPI spec (research-doc-derived; the live key is not available
# to the test suite, per repo convention of synthetic no-network fixtures).
#   SB 512: sponsored by Pat (primary), cosponsored by Dana, plus an
#     org-sponsorship with no person id (skipped, never name-matched). One
#     upper-chamber vote: Pat yes, an UNKNOWN ocd-person no (-> quarantined),
#     and a voter the source itself couldn't resolve (voter=None -> skipped).
#   HB 7: sponsored by Dana, signed into law (-> became_law). One lower-chamber
#     vote: Dana no.
STATE_VOTES_TN = {
    "state": "tn", "created_since": "2025-01-01",
    "cursor": "2026-07-06T04:00:00+00:00", "retrieved_at": RETRIEVED_AT, "fetched": 2,
    "bills": {
        "ocd-bill/11112222-3333-4444-5555-666677778888": {
            "id": "ocd-bill/11112222-3333-4444-5555-666677778888",
            "identifier": "SB 512", "session": "114", "title": "Education Savings Act",
            "subject": ["Education"],
            "openstates_url": "https://openstates.org/tn/bills/114/SB512/",
            "sources": [{"url": "https://wapp.capitol.tn.gov/apps/BillInfo/default.aspx?BillNumber=SB0512"}],
            "first_action_date": "2025-02-01", "latest_action_date": "2025-03-01",
            "updated_at": "2025-03-02T00:00:00+00:00",
            "actions": [
                {"description": "Introduced", "date": "2025-02-01",
                 "classification": ["introduction"], "organization": {"classification": "upper"}},
                {"description": "Passed Senate", "date": "2025-03-01",
                 "classification": ["passage"], "organization": {"classification": "upper"}},
            ],
            "sponsorships": [
                {"name": "Pat Upper", "primary": True, "classification": "primary",
                 "person": {"id": "ocd-person/aaaa1111-1111-1111-1111-111111111111", "name": "Pat Upper"}},
                {"name": "Dana Lower", "primary": False, "classification": "cosponsor",
                 "person": {"id": "ocd-person/bbbb2222-2222-2222-2222-222222222222", "name": "Dana Lower"}},
                {"name": "Cmte on Education", "primary": False, "classification": "cosponsor",
                 "person": None},                       # org sponsor: no id -> skipped
            ],
            "votes": [
                {"id": "ocd-vote/cccc3333-3333-3333-3333-333333333333",
                 "motion_text": "Third Reading", "start_date": "2025-03-01",
                 "result": "pass", "organization": {"classification": "upper"},
                 "counts": [{"option": "yes", "value": 17}, {"option": "no", "value": 14}],
                 "sources": [{"url": "https://wapp.capitol.tn.gov/votes/sb512-third-reading"}],
                 "votes": [
                     {"option": "yes", "voter_name": "Pat Upper",
                      "voter": {"id": "ocd-person/aaaa1111-1111-1111-1111-111111111111"}},
                     {"option": "no", "voter_name": "Gone Member",
                      "voter": {"id": "ocd-person/9999dead-dead-dead-dead-deaddeaddead"}},
                     {"option": "yes", "voter_name": "Unresolved Name", "voter": None},
                 ]},
            ],
        },
        "ocd-bill/99998888-7777-6666-5555-444433332222": {
            "id": "ocd-bill/99998888-7777-6666-5555-444433332222",
            "identifier": "HB 7", "session": "114", "title": "Road Naming Act",
            "subject": [],
            "openstates_url": "https://openstates.org/tn/bills/114/HB7/",
            "sources": [],
            "first_action_date": "2025-01-20", "latest_action_date": "2025-05-10",
            "updated_at": "2025-05-11T00:00:00+00:00",
            "actions": [
                {"description": "Introduced", "date": "2025-01-20",
                 "classification": ["introduction"], "organization": {"classification": "lower"}},
                {"description": "Passed House", "date": "2025-03-10",
                 "classification": ["passage"], "organization": {"classification": "lower"}},
                {"description": "Passed Senate", "date": "2025-04-20",
                 "classification": ["passage"], "organization": {"classification": "upper"}},
                {"description": "Signed by Governor", "date": "2025-05-10",
                 "classification": ["executive-signature"], "organization": {"classification": "executive"}},
            ],
            "sponsorships": [
                {"name": "Dana Lower", "primary": True, "classification": "primary",
                 "person": {"id": "ocd-person/bbbb2222-2222-2222-2222-222222222222", "name": "Dana Lower"}},
            ],
            "votes": [
                {"id": "ocd-vote/eeee5555-5555-5555-5555-555555555555",
                 "motion_text": "Passage", "start_date": "2025-03-10",
                 "result": "pass", "organization": {"classification": "lower"},
                 "counts": [{"option": "yes", "value": 60}, {"option": "no", "value": 30}],
                 "sources": [],
                 "votes": [
                     {"option": "no", "voter_name": "Dana Lower",
                      "voter": {"id": "ocd-person/bbbb2222-2222-2222-2222-222222222222"}},
                 ]},
            ],
        },
    },
}

# Jane's FEC candidate totals (dollars, as the API returns them -> stored cents).
FEC_TOTALS = {"H8TN06001": {"candidate_id": "H8TN06001", "cycle": 2026, "totals": {
    "receipts": 1234567.89, "disbursements": 900000.0,
    "last_cash_on_hand_end_period": 334567.89, "coverage_end_date": "2026-06-30T00:00:00"}}}

# Jane's FEC by_employer rollups (WO-3), as the API returns them: employers
# uppercased, totals in dollars, already -total-sorted. 27 rows to prove the
# dossier caps at 25 (WO-12; ranks 26-27 fall off); blank / "NOT EMPLOYED" /
# "RETIRED" are legitimate FEC categories kept verbatim (never editorialized
# or filtered).
FEC_CONTRIBUTORS = {"H8TN06001": {
    "candidate_id": "H8TN06001", "cycle": 2026, "committee_id": "C00CANDJANE",
    "by_employer": [
        {"employer": "N/A", "total": 50000.0, "count": 900},
        {"employer": "SELF-EMPLOYED", "total": 40000.0, "count": 300},
        {"employer": "RETIRED", "total": 30000.0, "count": 250},
        {"employer": "NOT EMPLOYED", "total": 20000.0, "count": 120},
        {"employer": "ACME CORP", "total": 15000.0, "count": 10},
        {"employer": "BETA LLC", "total": 12000.0, "count": 8},
        {"employer": "GAMMA INC", "total": 9000.0, "count": 6},
        {"employer": "DELTA CO", "total": 8000.0, "count": 5},
        {"employer": "EPSILON GROUP", "total": 7000.0, "count": 4},
        {"employer": "ZETA PARTNERS", "total": 6000.0, "count": 3},
        {"employer": "ETA HOLDINGS", "total": 5000.0, "count": 2},
        {"employer": "THETA VENTURES", "total": 4000.0, "count": 1},
    ] + [  # ranks 13..27, still -total-sorted; 26 and 27 exceed the 25 cap
        {"employer": f"FIRM {i:02d}", "total": 3000.0 - i, "count": 1}
        for i in range(13, 28)
    ]}}


# --- roll-call votes (WO-1) -------------------------------------------------
# 3 House roll calls for the 119th. RC1 links to Jane's law HR100 (bill_number
# "HR100" -> us/119/hr/100). RC2 is procedural (blank bill_number -> NULL FK).
# RC3 is a lopsided vote. Al (icpsr 22) is the other House member; Sam (icpsr 33,
# Senate) and the President (blank icpsr) never appear in these House rows.
# Tallies drive the closeness score: RC2 (11 v 10) is the tightest, RC1 (12 v 9)
# next, RC3 (20 v 1) least — so key-vote order should be RC2, RC1, RC3.
# WO-12: RC1/RC2 carry a vote_desc that differs from vote_question (-> published
# as description); RC3's vote_desc is blank (-> no description, honest absence).
VOTEVIEW_ROLLCALLS = (
    "congress,chamber,rollnumber,date,session,clerk_rollnumber,yea_count,nay_count,"
    "bill_number,vote_result,vote_desc,vote_question\n"
    "119,House,1,2025-02-01,1,10,12,9,HR100,Passed,Passage of HR100,On Passage\n"
    "119,House,2,2025-03-01,1,11,11,10,,Agreed to,A procedural motion,On the Motion\n"
    "119,House,3,2025-04-01,1,12,20,1,,Passed,,On Agreeing\n"
)
# Per-member cast codes. cast_code: 1=yea, 6=nay(variant), 9=not voting, 0=not a
# member. Jane (11): yea/yea/nay. Al (22): nay/yea/yea. Rows for icpsr 99 (not in
# the crosswalk) and cast_code 0 must be skipped without crashing.
VOTEVIEW_VOTES = (
    "congress,chamber,rollnumber,icpsr,cast_code,prob\n"
    "119,House,1,11,1,99.0\n"
    "119,House,1,22,6,99.0\n"
    "119,House,2,11,1,99.0\n"
    "119,House,2,22,1,99.0\n"
    "119,House,3,11,6,99.0\n"
    "119,House,3,22,1,99.0\n"
    "119,House,1,99,1,99.0\n"      # icpsr not in crosswalk -> skipped
    "119,House,3,33,0,99.0\n"      # cast_code 0 (not a member) -> skipped
)


# Jane (R000001) sponsored two bills, one now law; Sam has no legislation file
# at all -> exercises the zero-legislation path (counts 0, still contract-valid).
LEGISLATION = {
    "R000001": {"bioguide": "R000001", "cosponsored_count": 42, "sponsored": [
        {"congress": 119, "type": "HR", "number": "100", "title": "A Bill To Do X",
         "introducedDate": "2025-02-01", "policyArea": {"name": "Health"},
         "latestAction": {"actionDate": "2025-06-01", "text": "Became Public Law No: 119-1."}},
        {"congress": 119, "type": "HR", "number": "200", "title": "A Bill To Do Y",
         "introducedDate": "2025-03-01",
         "latestAction": {"actionDate": "2025-04-01", "text": "Referred to the Committee on Ways and Means."}},
    ]},
}


# --- WO-6a committees ------------------------------------------------------
# Roster mirrors committees-current.yaml: two top-level committees, each with a
# subcommittee (a subcommittee's code = parent thomas_id + subcommittee
# thomas_id, exactly how the membership file keys them). HSAG has no thomas_id-
# less rows; every committee carries one. WO-12: HSAG carries the source's own
# `url` (as 47/49 real committees do, verified live 2026-07-06); HSWM has none
# (like the 2 real select committees) -> committee_id only, never a constructed
# link. Real subcommittees never carry a url.
COMMITTEES = [
    {"type": "house", "name": "House Committee on Agriculture", "thomas_id": "HSAG",
     "url": "https://agriculture.house.gov/",
     "subcommittees": [{"name": "Forestry and Horticulture", "thomas_id": "15"},
                       {"name": "Livestock, Dairy, and Poultry", "thomas_id": "29"}]},
    {"type": "house", "name": "House Committee on Ways and Means", "thomas_id": "HSWM",
     "subcommittees": [{"name": "Health", "thomas_id": "02"}]},
    {"type": "senate", "name": "Senate Committee on the Budget", "thomas_id": "SSBU",
     "subcommittees": []},
    {"name": "Committee Without A Code",             # no thomas_id -> skipped by mapper
     "type": "house", "subcommittees": []},
]
# Membership mirrors committee-membership-current.yaml: keyed by committee code,
# each value a list of {bioguide, title?, party, rank?}. Jane chairs HSAG and its
# Forestry subcommittee, and is a plain member of Ways and Means. Al is Ranking
# Member of HSAG and a member of its Livestock subcommittee (parent membership
# present -> no orphan sub). An unknown code and a non-crosswalk bioguide prove
# both are skipped without crashing. Sam (Senate) is on nothing -> empty path.
COMMITTEE_MEMBERSHIP = {
    "HSAG": [{"name": "Jane Rep", "party": "majority", "rank": 1, "title": "Chair", "bioguide": "R000001"},
             {"name": "Al Large", "party": "minority", "rank": 1, "title": "Ranking Member", "bioguide": "A000002"}],
    "HSAG15": [{"name": "Jane Rep", "party": "majority", "rank": 1, "title": "Chairman", "bioguide": "R000001"}],
    "HSAG29": [{"name": "Al Large", "party": "minority", "rank": 1, "bioguide": "A000002"}],  # no title -> member
    "HSWM": [{"name": "Jane Rep", "party": "majority", "rank": 5, "bioguide": "R000001"}],   # no title -> member
    "HSWM02": [{"name": "Ghost Member", "party": "majority", "rank": 1, "bioguide": "Z999999"}],  # not in crosswalk
    "XXZZ": [{"name": "Jane Rep", "party": "majority", "rank": 1, "bioguide": "R000001"}],  # unknown code -> skipped
}


@pytest.fixture
def slice_dirs(tmp_path):
    raw = tmp_path / "raw"
    (raw / "unitedstates_legislators").mkdir(parents=True)
    (raw / "voteview").mkdir(parents=True)
    (raw / "congress.gov" / "legislation").mkdir(parents=True)
    (raw / "unitedstates_legislators" / "legislators-current.json").write_text(json.dumps(LEGS))
    (raw / "unitedstates_legislators" / "committees-current.json").write_text(json.dumps(COMMITTEES))
    (raw / "unitedstates_legislators" / "committee-membership-current.json").write_text(
        json.dumps(COMMITTEE_MEMBERSHIP))
    (raw / "voteview" / "HS119_members.csv").write_text(VOTEVIEW)
    (raw / "voteview" / "HS119_rollcalls.csv").write_text(VOTEVIEW_ROLLCALLS)
    (raw / "voteview" / "HS119_votes.csv").write_text(VOTEVIEW_VOTES)
    (raw / "fec" / "totals").mkdir(parents=True)
    (raw / "fec" / "contributors").mkdir(parents=True)
    for bio, rec in LEGISLATION.items():
        (raw / "congress.gov" / "legislation" / f"{bio}.json").write_text(json.dumps(rec))
    for cand, rec in FEC_TOTALS.items():
        (raw / "fec" / "totals" / f"{cand}.json").write_text(json.dumps(rec))
    for cand, rec in FEC_CONTRIBUTORS.items():
        (raw / "fec" / "contributors" / f"{cand}.json").write_text(json.dumps(rec))
    (raw / "openstates" / "people").mkdir(parents=True)
    (raw / "openstates" / "people" / "tn.csv").write_text(OPENSTATES_TN_CSV)
    # WO-17: WA people land but NO votes snapshot for WA (honest-absent state);
    # TN lands both, so TN legislators get the legislative section.
    (raw / "openstates" / "people" / "wa.csv").write_text(OPENSTATES_WA_CSV)
    (raw / "openstates" / "votes").mkdir(parents=True)
    (raw / "openstates" / "votes" / "tn.json").write_text(json.dumps(STATE_VOTES_TN))
    (raw / "house_clerk").mkdir(parents=True)
    (raw / "house_clerk" / "ptr.json").write_text(json.dumps(HOUSE_PTR))
    # WO-15: district offices + social media (federal, unitedstates_legislators
    # family), congress.gov member-detail (one file per bioguide — Al
    # deliberately has none, the honest-absence path), and Wikidata claims +
    # batched labels (Jane only — Al/Sam have no wikidata_qid).
    (raw / "unitedstates_legislators" / "legislators-district-offices.json").write_text(
        json.dumps(DISTRICT_OFFICES))
    (raw / "unitedstates_legislators" / "legislators-social-media.json").write_text(
        json.dumps(SOCIAL_MEDIA))
    (raw / "congress.gov" / "member-detail").mkdir(parents=True)
    for bio, rec in MEMBER_DETAIL.items():
        (raw / "congress.gov" / "member-detail" / f"{bio}.json").write_text(json.dumps(rec))
    (raw / "wikidata" / "claims").mkdir(parents=True)
    (raw / "wikidata" / "claims" / "educated_at.json").write_text(json.dumps(WIKIDATA_CLAIMS))
    (raw / "wikidata" / "labels.json").write_text(json.dumps(WIKIDATA_LABELS))
    (raw / "manifest.json").write_text(json.dumps(MANIFEST))   # fetch always writes one
    db = str(tmp_path / "wh.duckdb")
    transform.run(raw_dir=raw, db_path=db)
    build.run(db_path=db, out_dir=tmp_path / "data", raw_dir=raw)
    return tmp_path


def _dossier_named(slice_dirs, name):
    return next(json.loads(f.read_text()) for f in (slice_dirs / "data" / "dossiers").glob("*.json")
               if json.loads(f.read_text())["identity"]["full_name"] == name)


def test_stylefeed_keys_match_cd_ocd(slice_dirs):
    feed = json.loads((slice_dirs / "data" / "stylefeeds" / "cd.json").read_text())
    assert feed["ocd-division/country:us/state:tn/cd:6"]["party"] == "R"
    assert feed["ocd-division/country:us/state:ak/cd:1"]["party"] == "D"  # at-large joins cd:1


def test_pins_carry_display_fields(slice_dirs):
    """Pins label polygons on hover/stack views without dossier fan-out."""
    cd = json.loads((slice_dirs / "data" / "pins" / "cd.json").read_text())
    jane = next(p for p in cd if p["full_name"] == "Jane Rep")
    assert jane["office"] == "U.S. House · TN-6"
    assert jane["party"] == "R" and jane["vacant"] is False
    states = json.loads((slice_dirs / "data" / "pins" / "states.json").read_text())
    assert {p["chamber"] for p in states} == {"senate"}


def test_people_search_index_emitted(slice_dirs):
    """search/people.json is a flat name index (WO-5): one row per current
    officeholder across every layer, each carrying the fields the client search
    needs to jump to a dossier. Same fields for every official (symmetric)."""
    people = json.loads((slice_dirs / "data" / "search" / "people.json").read_text())
    # 3 federal + 3 state legislators (TN×2 + WA×1, WO-17), all with names.
    assert len(people) == 6
    for row in people:
        assert set(row) == {"person_id", "full_name", "office", "party", "ocd_id"}
    jane = next(p for p in people if p["full_name"] == "Jane Rep")
    assert jane["office"] == "U.S. House · TN-6"
    assert jane["ocd_id"] == "ocd-division/country:us/state:tn/cd:6"
    assert jane["party"] == "R"
    # a state legislator is indexed identically (no federal-only special-casing).
    pat = next(p for p in people if p["full_name"] == "Pat Upper")
    assert pat["office"] == "TN State Senate · District 5"
    # sorted by name for a stable, diff-friendly artifact.
    assert [p["full_name"] for p in people] == sorted(p["full_name"] for p in people)


def test_every_dossier_is_contract_valid(slice_dirs):
    files = list((slice_dirs / "data" / "dossiers").glob("*.json"))
    assert len(files) == 6              # 3 federal + 3 state legislators (WO-17 adds WA)
    for f in files:
        d = json.loads(f.read_text())
        dossiers.validate(d)                       # no provenance, no publish
        assert d["schema_version"] == "1.0"
        assert set(d["identity"]["party"]) == {"code", "display"}


def test_pending_ideology_when_insufficient_votes(slice_dirs):
    sam = next(json.loads(f.read_text()) for f in (slice_dirs / "data" / "dossiers").glob("*.json")
               if json.loads(f.read_text())["identity"]["full_name"] == "Sam Sen")
    assert sam["ideology"]["status"] == "pending_insufficient_votes"
    assert sam["ideology"]["score"] is None


def test_spine_gate_fails_closed():
    """Below SPINE_RESOLUTION_MIN the crosswalk raises rather than publish partial."""
    bad = [{"id": {}, "name": {"first": "No", "last": "Id"}} for _ in range(10)]
    with pytest.raises(RuntimeError, match="spine resolution"):
        list(legislators.to_spine_rows(bad))


def test_ideology_computed_as_of_is_retrieval_date(slice_dirs):
    """DW-NOMINATE is re-estimated as votes accrue: the manifest's retrieved_at
    (not the congress start) is the honest as-of for a published score."""
    jane = next(json.loads(f.read_text()) for f in (slice_dirs / "data" / "dossiers").glob("*.json")
                if json.loads(f.read_text())["identity"]["full_name"] == "Jane Rep")
    assert jane["ideology"]["provenance"]["retrieved_at"] == RETRIEVED_AT
    assert jane["ideology"]["score"] == 0.512


def test_build_provenance_fails_closed_without_manifest(tmp_path):
    """No manifest = no vouched retrieval time: build must refuse to fabricate
    freshness (rule #1: no provenance, no publish)."""
    raw = tmp_path / "raw"
    (raw / "unitedstates_legislators").mkdir(parents=True)
    (raw / "unitedstates_legislators" / "legislators-current.json").write_text(json.dumps(LEGS))
    db = str(tmp_path / "wh.duckdb")
    transform.run(raw_dir=raw, db_path=db)
    with pytest.raises(dossiers.ProvenanceError, match="retrieved_at"):
        build.run(db_path=db, out_dir=tmp_path / "data", raw_dir=raw)


def test_coverage_reports_freshness_vs_sla(slice_dirs):
    """coverage.json computes age_hours/within_sla, not just echoed timestamps
    (SETUP §6: 'all sources within SLA' must be checkable from the dashboard)."""
    cov = json.loads((slice_dirs / "data" / "coverage.json").read_text())
    for k, row in cov["sources"].items():
        assert row["retrieved_at"] == RETRIEVED_AT
        assert isinstance(row["age_hours"], (int, float))
        assert isinstance(row["within_sla"], bool)
    # snapshot is 1h old — within every registered SLA (tightest is 24h)
    assert all(row["within_sla"] for row in cov["sources"].values())


# --- E2 legislative sync ----------------------------------------------------
def test_bill_normalization():
    from beholden_etl.sources import congress_gov as cg
    law = {"congress": 119, "type": "HR", "number": "100",
           "latestAction": {"text": "Became Public Law No: 119-1."}}
    assert cg.bill_id(law) == "us/119/hr/100"
    assert cg.derive_status(law) == "law"
    assert cg.derive_status({"latestAction": {"text": "Referred to the Committee"}}) == "committee"
    assert cg.derive_status({}) == "introduced"                 # conservative default
    assert cg.bill_public_url("us/119/hr/100") == \
        "https://www.congress.gov/bill/119th-congress/house-bill/100"


def test_legislative_counts_from_spine(slice_dirs):
    """Sponsored + became-law + recent bills come from the bills spine; the
    cosponsored total from the landed snapshot. Members with no legislation
    file report honest zeros and stay contract-valid."""
    leg = _dossier_named(slice_dirs, "Jane Rep")["legislative"]
    assert leg["counts"] == {"sponsored": 2, "cosponsored": 42, "became_law": 1}
    assert len(leg["recent_bills"]) == 2
    assert leg["recent_bills"][0]["url"].startswith(
        "https://www.congress.gov/bill/119th-congress/house-bill/")
    # Sam has no legislation snapshot -> zeros, not fabricated activity
    assert _dossier_named(slice_dirs, "Sam Sen")["legislative"]["counts"] == \
        {"sponsored": 0, "cosponsored": 0, "became_law": 0}


# --- E3 campaign finance ----------------------------------------------------
def test_fec_dollars_to_cents():
    from beholden_etl.sources import fec
    assert fec.to_cents(1234567.89) == 123456789
    assert fec.to_cents(None) is None
    row = fec.cycle_row("p1", "H8TN06001", 2026,
                        {"receipts": 100.0, "coverage_end_date": "2026-06-30T00:00:00"}, None)
    assert row["total_raised_cents"] == 10000 and row["as_of"] == "2026-06-30"
    # no coverage date and no fallback -> unpublishable row (as_of is NOT NULL)
    assert fec.cycle_row("p1", "C1", 2026, {"receipts": 1.0}, None) is None


def test_campaign_finance_only_when_real(slice_dirs):
    """money publishes for members with FEC data; absent for those without, so
    the UI shows an honest 'pending' rather than a fabricated $0."""
    jane = _dossier_named(slice_dirs, "Jane Rep")
    cf = jane["money"]["campaign_finance"]
    assert cf["cycles"][0] == {"cycle": 2026, "total_raised_cents": 123456789,
                               "total_spent_cents": 90000000,
                               "cash_on_hand_cents": 33456789, "as_of": "2026-06-30"}
    assert cf["provenance"]["source"] == "fec"
    # Sam has no FEC id/totals -> no money section at all
    assert "money" not in _dossier_named(slice_dirs, "Sam Sen")


# --- WO-3 itemized donors (FEC top contributors) ----------------------------
def test_fec_contributor_rows_map_to_cents_and_rank():
    """by_employer rollups -> top_contributors rows: employer verbatim, dollars
    to integer cents, ranked 1..N in FEC's (-total) order. Blank/NOT EMPLOYED/
    RETIRED are legitimate categories, kept as-is; a row missing a total drops."""
    from beholden_etl.sources import fec
    rows = fec.contributor_rows("p1", 2026, [
        {"employer": "ACME CORP", "total": 15000.0, "count": 10},
        {"employer": "RETIRED", "total": 30000.5, "count": 250},
        {"employer": "", "total": 100.0, "count": 1},          # blank kept verbatim
        {"employer": "NO TOTAL", "count": 3},                   # missing total -> dropped
    ])
    assert [r["rank"] for r in rows] == [1, 2, 3]              # dropped row doesn't skew ranks
    assert rows[0] == {"person_id": "p1", "cycle": 2026,
                       "contributor_name": "ACME CORP", "total_cents": 1500000, "rank": 1}
    assert rows[1]["total_cents"] == 3000050                    # cents rounding
    assert rows[2]["contributor_name"] == ""                    # blank employer preserved
    # empty input -> no rows (absent != zero)
    assert fec.contributor_rows("p1", 2026, []) == []


def test_committee_resolution_prefers_principal_then_authorized():
    """principal_committee returns the designation-P committee; when none is
    filed it falls back to any authorized committee; None when there is none."""
    from beholden_etl.sources import fec

    class FakeClient(fec.FECClient):
        def __init__(self, script):
            self._script = script          # list of results lists, popped in call order
        def get(self, path, **params):
            return {"results": self._script.pop(0)}

    # P present -> used directly (single call).
    c = FakeClient([[{"committee_id": "C_P"}]])
    assert c.principal_committee("H0", 2026) == "C_P"
    # No P -> second call returns an authorized committee.
    c = FakeClient([[], [{"committee_id": "C_AUTH"}]])
    assert c.principal_committee("H0", 2026) == "C_AUTH"
    # Neither -> None (member gets no top_contributors; absent != zero).
    c = FakeClient([[], []])
    assert c.principal_committee("H0", 2026) is None


def test_top_contributors_land_in_spine_ranked(slice_dirs):
    """The transform fills top_contributors from the by_employer rollups, ranked
    1..N in FEC order, keyed to the crosswalk person; a candidate with no
    contributors file gets no rows."""
    con = store.connect(str(slice_dirs / "wh.duckdb"))
    n = con.execute("SELECT count(*) FROM top_contributors").fetchone()[0]
    assert n == 27                                             # all 27 fixture rows land
    top = con.execute(
        """SELECT contributor_name, total_cents FROM top_contributors
           ORDER BY rank LIMIT 1""").fetchone()
    assert top == ("N/A", 5000000)                            # rank 1, $50,000 -> cents
    con.close()


def test_dossier_top_contributors_capped_and_provenanced(slice_dirs):
    """Jane's money.campaign_finance carries top_contributors[0..24] (capped at
    25, WO-12) with name + total_cents + rank, under the same FEC envelope. rank
    is the warehoused FEC -total position so the UI can show 10 and expand. FEC
    categories like N/A / RETIRED / NOT EMPLOYED are surfaced verbatim, not
    filtered."""
    jane = _dossier_named(slice_dirs, "Jane Rep")
    cf = jane["money"]["campaign_finance"]
    tc = cf["top_contributors"]
    assert len(tc) == 25                                       # 27 rollups capped to 25
    assert tc[0] == {"name": "N/A", "total_cents": 5000000, "rank": 1}
    assert [c["name"] for c in tc[:4]] == ["N/A", "SELF-EMPLOYED", "RETIRED", "NOT EMPLOYED"]
    assert set(tc[0]) == {"name", "total_cents", "rank"}      # exactly the contract shape
    assert [c["rank"] for c in tc] == list(range(1, 26))      # 1..25, no gaps past the cap
    # monotonically non-increasing (FEC -total order preserved through the cap)
    assert all(tc[i]["total_cents"] >= tc[i + 1]["total_cents"] for i in range(len(tc) - 1))
    assert cf["provenance"]["source"] == "fec"                # same envelope as totals


def test_top_contributors_absent_when_no_committee(slice_dirs):
    """A member with campaign_finance but no contributors file has no
    top_contributors key — absent is not an empty list, never fabricated.
    (Sam has no FEC data at all, so no money section; assert Jane is the only
    one carrying contributors here.)"""
    # Al Large: House member with no FEC id -> no money section, hence no key.
    al = _dossier_named(slice_dirs, "Al Large")
    assert "top_contributors" not in al.get("money", {}).get("campaign_finance", {})


# --- E4 state legislators ---------------------------------------------------
def test_state_legislators_light_up_state_layers(slice_dirs):
    """OpenStates people populate the sldu/sldl feeds + dossiers, keyed on the
    OCD ids the tile stamper produces. Ideology stays federal-only (omitted, not
    faked); since WO-17 a covered state's legislators also carry a legislative
    section (asserted in the WO-17 tests below), while an uncovered state's
    dossier stays identity-only — and both validate."""
    sldu = json.loads((slice_dirs / "data" / "stylefeeds" / "sldu.json").read_text())
    sldl = json.loads((slice_dirs / "data" / "stylefeeds" / "sldl.json").read_text())
    assert sldu["ocd-division/country:us/state:tn/sldu:5"]["party"] == "R"
    assert sldl["ocd-division/country:us/state:tn/sldl:10"]["party"] == "D"

    pins = json.loads((slice_dirs / "data" / "pins" / "sldu.json").read_text())
    pat = next(p for p in pins if p["full_name"] == "Pat Upper")
    assert pat["office"] == "TN State Senate · District 5"
    assert pat["photo_url"] == "https://img/pat.jpg"

    doss = _dossier_named(slice_dirs, "Pat Upper")
    dossiers.validate(doss)
    assert "ideology" not in doss               # DW-NOMINATE is federal-only
    assert doss["identity"]["provenance"]["source"] == "openstates"
    assert doss["identity"]["office"]["chamber"] == "upper"

    # WA landed people but no votes snapshot -> identity-only, contract-valid.
    wanda = _dossier_named(slice_dirs, "Wanda West")
    dossiers.validate(wanda)
    assert "ideology" not in wanda and "legislative" not in wanda


# --- WO-1 roll-call votes ---------------------------------------------------
def test_cast_code_and_bill_normalization():
    """cast_code families map to positions; Voteview bill tokens normalize to the
    bills-spine id (or None for procedural votes with no bill number)."""
    from beholden_etl.sources import voteview as vv
    assert vv.CAST_CODE_POSITION[1] == "yea" and vv.CAST_CODE_POSITION[3] == "yea"
    assert vv.CAST_CODE_POSITION[6] == "nay" and vv.CAST_CODE_POSITION[9] == "not_voting"
    assert 0 not in vv.CAST_CODE_POSITION            # "not a member" -> skipped, never a position
    assert vv.normalize_bill_id("HR100", 119) == "us/119/hr/100"
    assert vv.normalize_bill_id("HRES5", 119) == "us/119/hres/5"
    assert vv.normalize_bill_id("", 119) is None      # speaker election: no bill
    assert vv.normalize_bill_id("PN123", 119) == "us/119/pn/123"  # normalizes but won't match a bills row


def test_roll_call_public_urls_both_chambers():
    """Both official-record URL patterns (verified live 2026-07-05). House keys on
    year+clerk_rollnumber; Senate on congress/session/clerk_rollnumber (zero-padded)."""
    from beholden_etl.sources import voteview as vv
    assert vv.roll_call_public_url("house", 119, 1, 12, "2025-04-01") == \
        "https://clerk.house.gov/Votes/202512"
    assert vv.roll_call_public_url("senate", 119, 1, 1, "2025-01-09") == \
        ("https://www.senate.gov/legislative/LIS/roll_call_votes/"
         "vote1191/vote_119_1_00001.htm")


def test_key_vote_selection_is_by_closeness_and_recency():
    """Salience = closeness + recency_bonus, top-N, deterministic. RC2 (11v10) is
    tightest, RC1 (12v9) next, RC3 (20v1) least -> selection order RC2,RC1,RC3;
    output is re-sorted newest-first."""
    from beholden_etl.build import key_votes as kv
    meta = {"a": {"yea": 12, "nay": 9, "date": "2025-02-01", "url": "http://a"},
            "b": {"yea": 11, "nay": 10, "date": "2025-03-01", "url": "http://b"},
            "c": {"yea": 20, "nay": 1, "date": "2025-04-01", "url": "http://c"}}
    votes = [
        {"roll_call_id": "a", "position": "yea", "question": "Q-a", "result": "Passed",
         "held_at": "2025-02-01 00:00:00+00", "bill_id": "us/119/hr/100"},
        {"roll_call_id": "b", "position": "yea", "question": "Q-b", "result": "Agreed",
         "held_at": "2025-03-01 00:00:00+00", "bill_id": None},
        {"roll_call_id": "c", "position": "nay", "question": "Q-c", "result": "Passed",
         "held_at": "2025-04-01 00:00:00+00", "bill_id": None},
        {"roll_call_id": "d", "position": "present", "question": "Q-d", "result": "x",
         "held_at": "2025-05-01 00:00:00+00", "bill_id": None},   # present: never a key vote
    ]
    top2 = kv.select_key_votes(votes, meta, limit=2)
    assert [v["roll_call_id"] for v in top2] == ["b", "a"]        # newest-first among {b,a}
    assert top2[0]["url"] == "http://b" and top2[1]["bill_id"] == "us/119/hr/100"
    # present/not_voting excluded; only decided votes are eligible
    all_selected = kv.select_key_votes(votes, meta, limit=10)
    assert {v["roll_call_id"] for v in all_selected} == {"a", "b", "c"}


def test_party_agreement_math_and_min_votes():
    """Agreement = % matching the party majority over decided votes; None below
    MIN_AGREEMENT_VOTES so a tiny denominator can't publish a false precision."""
    from beholden_etl.build import key_votes as kv
    # Two R members: majority follows the 2-of-3 side per roll call.
    rows = [{"roll_call_id": "r1", "party": "R", "position": "yea"},
            {"roll_call_id": "r1", "party": "R", "position": "yea"},
            {"roll_call_id": "r1", "party": "R", "position": "nay"},
            {"roll_call_id": "r2", "party": "R", "position": "yea"},
            {"roll_call_id": "r2", "party": "R", "position": "nay"}]  # tie -> no majority
    maj = kv.party_majority_positions(rows)
    assert maj["r1\tR"] == "yea"
    assert "r2\tR" not in maj                        # equal split -> excluded
    # Below the min-vote gate: even a perfect record returns None.
    member = [{"roll_call_id": "r1", "position": "yea"}]
    assert kv.agreement_pct(member, "R", maj) is None
    # At/above the gate, percentage is published. 21 votes, 20 agree -> 95.2%.
    big_maj = {f"m{i}\tR": "yea" for i in range(21)}
    member = [{"roll_call_id": f"m{i}", "position": "yea"} for i in range(20)]
    member.append({"roll_call_id": "m20", "position": "nay"})
    assert kv.agreement_pct(member, "R", big_maj) == 95.2


def test_dossier_key_votes_populated_and_provenanced(slice_dirs):
    """Jane's dossier carries her decided votes as key_votes[], each with position,
    question, held_at, result, url; RC1 links to her law HR100, procedural votes
    link NULL. The vote-derived facts carry a Voteview provenance envelope."""
    leg = _dossier_named(slice_dirs, "Jane Rep")["legislative"]
    kvs = leg["key_votes"]
    assert len(kvs) == 3                             # 3 decided House votes
    for v in kvs:
        assert v["position"] in ("yea", "nay")
        assert v["question"] and v["held_at"] and v["result"] and v["url"]
    by_rc = {v["roll_call_id"]: v for v in kvs}
    assert by_rc["us/119/house/1"]["position"] == "yea"
    assert by_rc["us/119/house/1"]["bill_id"] == "us/119/hr/100"   # links to Jane's law
    assert by_rc["us/119/house/1"]["url"] == "https://clerk.house.gov/Votes/202510"
    assert by_rc["us/119/house/1"]["bill_url"] == \
        "https://www.congress.gov/bill/119th-congress/house-bill/100"
    assert by_rc["us/119/house/2"]["bill_id"] is None              # procedural -> NULL
    assert leg["votes_provenance"]["source"] == "voteview"
    # Only 3 votes (< MIN_AGREEMENT_VOTES) -> agreement omitted, not faked.
    assert leg["party_agreement_pct"] is None


def test_roll_calls_and_positions_land_in_spine(slice_dirs):
    """The transform fills roll_calls + vote_positions; non-crosswalk ICPSRs and
    cast_code 0 rows are dropped without breaking FK integrity. (Counts scope to
    the federal 'us/…' ids — WO-17 lands state roll calls in the same tables,
    asserted separately in the WO-17 tests.)"""
    con = store.connect(str(slice_dirs / "wh.duckdb"))
    assert con.execute(
        "SELECT count(*) FROM roll_calls WHERE roll_call_id LIKE 'us/%'").fetchone()[0] == 3
    # 6 valid casts (Jane x3, Al x3); icpsr 99 + cast_code 0 rows are excluded.
    assert con.execute(
        "SELECT count(*) FROM vote_positions WHERE roll_call_id LIKE 'us/%'").fetchone()[0] == 6
    # RC1 links to the existing bills row; procedural RC2/RC3 keep NULL bill_id.
    linked = con.execute(
        "SELECT bill_id FROM roll_calls WHERE roll_call_id='us/119/house/1'").fetchone()[0]
    assert linked == "us/119/hr/100"
    assert con.execute(
        "SELECT bill_id FROM roll_calls WHERE roll_call_id='us/119/house/2'").fetchone()[0] is None
    con.close()


def test_senate_dossier_has_no_key_votes_without_positions(slice_dirs):
    """Sam (Senate) has no roll-call positions in the fixture -> empty key_votes,
    no agreement, and no orphan votes_provenance. Still contract-valid."""
    leg = _dossier_named(slice_dirs, "Sam Sen")["legislative"]
    assert leg["key_votes"] == []
    assert leg["party_agreement_pct"] is None
    assert leg["votes_provenance"] is None


# --- STOCK Act disclosures --------------------------------------------------
def test_stock_act_disclosures_link_official_filings(slice_dirs):
    """House PTR filings are name-matched and published as links to the official
    PDFs (each carries filing_url — no provenance, no publish)."""
    jane = _dossier_named(slice_dirs, "Jane Rep")
    disc = jane["money"]["disclosures"]
    assert disc["count"] == 1
    assert disc["filings"][0]["filing_url"].endswith("/ptr-pdfs/2025/20099999.pdf")
    assert disc["filings"][0]["filed_on"] == "2025-05-01"
    assert disc["provenance"]["source"] == "house_clerk"
    # a member with no filing has no disclosures section
    assert "disclosures" not in _dossier_named(slice_dirs, "Al Large").get("money", {})


# --- WO-6a committee memberships --------------------------------------------
def test_committee_role_mapping_and_flatten():
    """Titles map to the DDL role enum (member|chair|ranking|vice_chair);
    unknown/absent -> member (never a stronger claim). committee_rows flattens
    the roster parents-before-subcommittees with sub code = parent + sub
    thomas_id, and drops a committee with no thomas_id (can't key memberships)."""
    from beholden_etl.sources import legislators as L
    assert L.committee_role("Chair") == "chair"
    assert L.committee_role("Chairman") == "chair"
    assert L.committee_role("Chairwoman") == "chair"
    assert L.committee_role("Cochairman") == "chair"
    assert L.committee_role("Ranking Member") == "ranking"
    assert L.committee_role("Vice Chair") == "vice_chair"
    assert L.committee_role("Vice Chairman") == "vice_chair"
    assert L.committee_role("Ex Officio") == "member"      # no DDL code -> member
    assert L.committee_role(None) == "member"
    assert L.committee_role("") == "member"

    rows = list(L.committee_rows(COMMITTEES))
    ids = [r["committee_id"] for r in rows]
    assert "HSAG" in ids and "HSAG15" in ids and "HSAG29" in ids    # parent + subs
    # subcommittee code = parent thomas_id + subcommittee thomas_id
    forestry = next(r for r in rows if r["committee_id"] == "HSAG15")
    assert forestry["parent_id"] == "HSAG" and forestry["name"] == "Forestry and Horticulture"
    # parent emitted before its subcommittees (self-referential FK ordering)
    assert ids.index("HSAG") < ids.index("HSAG15")
    # a committee with no thomas_id is dropped (can't key memberships)
    assert all(r["name"] != "Committee Without A Code" for r in rows)


def test_membership_rows_gated_on_committee_and_crosswalk():
    """membership_rows emits a row only when both the committee (FK) and the
    member (crosswalk) resolve. Unknown committee codes and bioguides outside the
    spine are skipped — never invented. Role comes from the stated title."""
    from beholden_etl.sources import legislators as L
    known = {r["committee_id"] for r in L.committee_rows(COMMITTEES)}
    bio_to_person = {"R000001": "p-jane", "A000002": "p-al"}   # Z999999 absent
    rows = list(L.membership_rows(COMMITTEE_MEMBERSHIP, 119, known, bio_to_person))
    # Jane: HSAG(chair), HSAG15(chair), HSWM(member). Al: HSAG(ranking), HSAG29(member).
    # XXZZ (unknown code) and HSWM02 (Ghost, not in crosswalk) contribute nothing.
    got = {(r["committee_id"], r["person_id"], r["role"]) for r in rows}
    assert got == {
        ("HSAG", "p-jane", "chair"), ("HSAG15", "p-jane", "chair"),
        ("HSWM", "p-jane", "member"),
        ("HSAG", "p-al", "ranking"), ("HSAG29", "p-al", "member")}
    assert all(r["congress"] == 119 for r in rows)


def test_committees_land_in_spine(slice_dirs):
    """The transform fills committees + committee_memberships; unknown codes and
    non-crosswalk members are excluded without breaking FK integrity, and the
    self-referential parent_id links subcommittees to their parent."""
    con = store.connect(str(slice_dirs / "wh.duckdb"))
    # 3 real parents (HSAG, HSWM, SSBU) + 3 subs (HSAG15, HSAG29, HSWM02) land;
    # the code-less committee is dropped.
    assert con.execute("SELECT count(*) FROM committees").fetchone()[0] == 6
    # 5 valid memberships (Jane x3, Al x2); XXZZ + Ghost excluded.
    assert con.execute("SELECT count(*) FROM committee_memberships").fetchone()[0] == 5
    assert con.execute(
        "SELECT parent_id FROM committees WHERE committee_id='HSAG15'").fetchone()[0] == "HSAG"
    assert con.execute(
        "SELECT parent_id FROM committees WHERE committee_id='HSAG'").fetchone()[0] is None
    con.close()


def test_dossier_committees_nest_subcommittees_and_provenanced(slice_dirs):
    """Jane's legislative.committees lists her top-level committees (alphabetical),
    each with role, nesting the subcommittees she also sits on. The memberships
    carry a dedicated unitedstates_legislators provenance envelope."""
    leg = _dossier_named(slice_dirs, "Jane Rep")["legislative"]
    coms = leg["committees"]
    names = [c["name"] for c in coms]
    # deterministic alphabetical order, party-agnostic (rule #3)
    assert names == ["House Committee on Agriculture", "House Committee on Ways and Means"]
    ag = next(c for c in coms if c["name"] == "House Committee on Agriculture")
    assert ag["role"] == "chair"
    assert ag["subcommittees"] == [
        {"committee_id": "HSAG15", "name": "Forestry and Horticulture", "role": "chair"}]
    wm = next(c for c in coms if c["name"] == "House Committee on Ways and Means")
    assert wm["role"] == "member"
    assert "subcommittees" not in wm                       # no sub membership -> key omitted
    assert leg["committees_provenance"]["source"] == "unitedstates_legislators"


def test_dossier_committees_role_and_subcommittee_only_when_parent(slice_dirs):
    """Al is Ranking Member of Agriculture and a plain member of its Livestock
    subcommittee (parent membership present -> the sub nests, no orphan)."""
    leg = _dossier_named(slice_dirs, "Al Large")["legislative"]
    coms = leg["committees"]
    assert [c["name"] for c in coms] == ["House Committee on Agriculture"]
    ag = coms[0]
    assert ag["role"] == "ranking"
    assert ag["subcommittees"] == [
        {"committee_id": "HSAG29", "name": "Livestock, Dairy, and Poultry", "role": "member"}]


def test_dossier_committees_empty_when_none(slice_dirs):
    """A member on no committee gets committees=[] and no committees_provenance
    stamp — absent is honest, never a fabricated membership. Still contract-valid.
    Sam (Senate) sits on nothing in the fixture."""
    leg = _dossier_named(slice_dirs, "Sam Sen")["legislative"]
    assert leg["committees"] == []
    assert leg["committees_provenance"] is None
    dossiers.validate(_dossier_named(slice_dirs, "Sam Sen"))


# --- WO-4 entity graph ------------------------------------------------------
# All edge math is unit-tested against build.graph directly (it takes plain
# dicts, so no warehouse round-trip is needed to prove the arithmetic), then the
# whole pipeline is exercised on the slice fixture to prove the emitter wiring.
def test_graph_cosponsorship_edge_counts_shared_bills():
    """A cosponsorship edge exists only for a SHARED bill_id (exact deterministic
    id, never a name guess). weight = shared count; evidence lists the shared bill
    refs, capped at 25 with evidence_total carrying the true count."""
    from beholden_etl.build import graph
    spons = {
        "p-a": [{"bill_id": f"us/119/hr/{i}", "url": f"http://b/{i}"} for i in range(30)],
        "p-b": [{"bill_id": f"us/119/hr/{i}", "url": f"http://b/{i}"} for i in range(27)],
        "p-c": [{"bill_id": "us/119/hr/999", "url": "http://b/999"}],   # shares nothing
    }
    edges = graph.cosponsorship_edges(["p-a", "p-b", "p-c"], spons, "119th Congress")
    assert len(edges) == 1                                    # only a~b share bills
    e = edges[0]
    assert (e["a"], e["b"]) == ("p-a", "p-b")               # canonical (sorted) pair
    assert e["type"] == "cosponsorship"
    assert e["weight"] == 27 and e["evidence_total"] == 27   # bills 0..26 in common
    assert len(e["evidence"]) == 25                          # inline cap
    assert all(ev["kind"] == "bill" and ev["url"] for ev in e["evidence"])


def test_graph_co_voting_agreement_and_min_shared():
    """co_voting weight = agreement % over shared decided votes; published only at
    or above MIN_SHARED_VOTES so a tiny overlap can't fake precision. Only yea/nay
    positions on the SAME roll_call_id count."""
    from beholden_etl.build import graph
    # a & b share 100 decided votes, agree on 94 -> 94.0%.
    pa = {f"rc{i}": ("yea" if i % 2 == 0 else "nay") for i in range(100)}
    pb = dict(pa)
    for i in range(6):                                       # flip 6 -> 94 agree
        pb[f"rc{i}"] = "yea" if pa[f"rc{i}"] == "nay" else "nay"
    # c shares only 10 votes with a -> below the gate, no edge.
    pc = {f"rc{i}": "yea" for i in range(10)}
    refs = {f"rc{i}": {"kind": "roll_call", "id": f"rc{i}", "url": f"http://v/{i}"}
            for i in range(100)}
    edges = graph.co_voting_edges(["p-a", "p-b", "p-c"],
                                  {"p-a": pa, "p-b": pb, "p-c": pc}, refs, "119th Congress")
    assert len(edges) == 1                                   # only a~b clear 50 shared
    e = edges[0]
    assert (e["a"], e["b"]) == ("p-a", "p-b")
    assert e["weight"] == 94.0 and e["evidence_total"] == 100
    assert len(e["evidence"]) == 25                          # sample cap
    assert e["method"] == graph.CO_VOTING_METHOD             # formula stated inline


def test_graph_shared_donor_edge_matches_verbatim_and_carries_caveat():
    """shared_donor edge is an EXACT contributor_name match (verbatim FEC employer
    string) — 'ACME CORP' != 'Acme Corp', no fuzzy collapse. Evidence carries both
    members' aggregate rows; the verbatim caveat is mandatory."""
    from beholden_etl.build import graph
    contribs = {
        "p-a": [{"name": "ACME CORP", "total_cents": 1500000},
                {"name": "BETA LLC", "total_cents": 1200000}],
        "p-b": [{"name": "ACME CORP", "total_cents": 900000},
                {"name": "Acme Corp", "total_cents": 100}],   # different case -> NOT shared
    }
    edges = graph.shared_donor_edges(["p-a", "p-b"], contribs, 2026, "cycle 2026")
    assert len(edges) == 1
    e = edges[0]
    assert e["weight"] == 1 and e["evidence_total"] == 1     # only "ACME CORP" matches
    ev = e["evidence"][0]
    assert ev == {"kind": "fec_employer", "name": "ACME CORP",
                  "a_total_cents": 1500000, "b_total_cents": 900000}
    assert e["caveat"] == (
        "shared top contributors are reported-employer aggregates; no coordination is implied")
    assert e["cycle"] == 2026


def test_graph_no_edge_lacks_provenance_evidence():
    """PROOF that no published edge can lack receipts: graph.validate rejects an
    edge with empty evidence, and a shared_donor edge missing its verbatim caveat.
    (This is the graph analogue of 'no provenance, no publish'.)"""
    from beholden_etl.build import graph
    node = {"person_id": "p-a", "name": "A", "party": "R",
            "office_display": "U.S. House · TN-6", "ideology_dim1": None}
    node_b = {**node, "person_id": "p-b"}
    good = {"center": "p-a", "as_of": "2026-07-05", "nodes": [node, node_b],
            "edges": [{"type": "cosponsorship", "a": "p-a", "b": "p-b", "weight": 1,
                       "window": "119th Congress",
                       "evidence": [{"kind": "bill", "id": "x", "url": "u"}],
                       "evidence_total": 1}]}
    graph.validate(good)                                     # passes
    no_ev = {**good, "edges": [{**good["edges"][0], "evidence": [], "evidence_total": 0}]}
    with pytest.raises(ValueError, match="no evidence"):
        graph.validate(no_ev)
    # a correlation edge without its caveat is refused
    bad_donor = {**good, "edges": [{
        "type": "shared_donor", "a": "p-a", "b": "p-b", "weight": 1, "window": "cycle 2026",
        "evidence": [{"kind": "fec_employer", "name": "X", "a_total_cents": 1, "b_total_cents": 2}],
        "evidence_total": 1}]}                               # caveat missing
    with pytest.raises(ValueError, match="caveat"):
        graph.validate(bad_donor)


def test_graph_symmetric_truncation_keeps_strongest_edges():
    """Each neighborhood keeps its top-N strongest edges by a single formula
    applied to everyone (symmetric by construction): heavier weight first, then a
    deterministic tiebreak. The truncation rule is party-agnostic."""
    from beholden_etl.build import graph
    members = [{"person_id": f"p{i}", "name": f"N{i}", "party": "R" if i % 2 else "D",
                "office_display": "U.S. House · X", "ideology_dim1": None} for i in range(5)]
    # p0 links to p1..p4 with increasing weights; cap at 2 must keep the two heaviest.
    edges = [{"type": "cosponsorship", "a": "p0", "b": f"p{j}", "weight": j,
              "window": "119th Congress",
              "evidence": [{"kind": "bill", "id": f"b{j}", "url": "u"}], "evidence_total": j}
             for j in range(1, 5)]
    docs = graph.neighborhoods(members, edges, "2026-07-05", edges_per_person=2)
    kept = docs["p0"]["edges"]
    assert [e["weight"] for e in kept] == [4, 3]             # strongest-first, top-2
    # nodes are exactly the surviving endpoints plus the center (p0, p3, p4)
    assert {n["person_id"] for n in docs["p0"]["nodes"]} == {"p0", "p3", "p4"}
    # every edge still carries receipts after truncation
    graph.validate(docs["p0"])


def test_graph_empty_input_yields_no_edges_but_valid_docs():
    """The empty/no-edges path: members with no shared facts get an edge-free
    neighborhood that still validates (absent connections != a broken document)."""
    from beholden_etl.build import graph
    members = [{"person_id": "p-a", "name": "A", "party": "R",
                "office_display": "U.S. House · X", "ideology_dim1": None}]
    docs = graph.neighborhoods(members, [], "2026-07-05")
    assert docs["p-a"]["edges"] == []
    assert [n["person_id"] for n in docs["p-a"]["nodes"]] == ["p-a"]
    graph.validate(docs["p-a"])                              # edge-free doc is valid


def test_graph_neighborhood_emitted_with_committee_edge(slice_dirs):
    """End-to-end: the build emits graph/neighborhood/{person_id}.json for every
    member. Jane and Al both sit on HSAG (a SHARED committee_id — deterministic),
    so their neighborhoods carry a committee edge citing that committee; Sam and
    the state legislators (no shared facts) get valid edge-free docs."""
    from beholden_etl.build import graph
    gdir = slice_dirs / "data" / "graph" / "neighborhood"
    files = list(gdir.glob("*.json"))
    assert len(files) == 6                       # one per current holder (WO-17 adds WA)
    docs = {json.loads(f.read_text())["center"]: json.loads(f.read_text()) for f in files}
    for d in docs.values():
        graph.validate(d)                                    # no receipts, no publish

    def by_name(doc, pid):
        return next(n["name"] for n in doc["nodes"] if n["person_id"] == pid)

    jane_id = next(d["center"] for d in docs.values()
                   if any(n["name"] == "Jane Rep" and n["person_id"] == d["center"]
                          for n in d["nodes"]))
    jane = docs[jane_id]
    com = [e for e in jane["edges"] if e["type"] == "committee"]
    assert len(com) == 1
    e = com[0]
    assert e["weight"] == 1 and e["evidence_total"] == 1
    assert e["evidence"][0]["kind"] == "committee" and e["evidence"][0]["id"] == "HSAG"
    assert {by_name(jane, e["a"]), by_name(jane, e["b"])} == {"Jane Rep", "Al Large"}
    # Nodes carry the contract fields (party as data, office display, ideology).
    jane_node = next(n for n in jane["nodes"] if n["person_id"] == jane_id)
    assert set(jane_node) == {"person_id", "name", "party", "office_display", "ideology_dim1"}
    # Sam (Senate, shares nothing with the House pair) -> edge-free but valid.
    sam_id = next(d["center"] for d in docs.values()
                  if any(n["name"] == "Sam Sen" and n["person_id"] == d["center"]
                         for n in d["nodes"]))
    assert docs[sam_id]["edges"] == []


def test_graph_dossier_graph_ref_resolves_to_neighborhood(slice_dirs):
    """Every dossier's graph_ref points at a file the build actually wrote, so the
    UI's Connections view always resolves (contract §3/§4 wiring)."""
    gdir = slice_dirs / "data" / "graph" / "neighborhood"
    for f in (slice_dirs / "data" / "dossiers").glob("*.json"):
        d = json.loads(f.read_text())
        ref = d["graph_ref"]                                 # "/graph/neighborhood/{id}"
        assert ref == f"/graph/neighborhood/{d['person_id']}"
        assert (gdir / f"{d['person_id']}.json").exists()


# --- WO-9 WA PDC trusted extraction (Tier A) --------------------------------
# Fixtures mirror the real feed, verified live 2026-07-05: filer 24THLD 362 in
# election_year 2025 has six itemized cash contributions summing to $2,183.00,
# exactly the summary feed's contributions_amount for that (filer, year). No model
# is in this path; the whole framework is deterministic parse + fail-closed gates.
from beholden_etl.sources import wa_pdc as _wa            # noqa: E402
from beholden_etl.bulk import contract as _bulk_contract  # noqa: E402
from beholden_etl.bulk import reconcile as _bulk_reconcile  # noqa: E402
from beholden_etl.jobs import transform as _transform      # noqa: E402

# A snapshot's exact-bytes SHA-256 and retrieval time are provenance inputs; fixed
# here so the envelope + idempotence assertions are stable.
_WA_SHA = "0" * 64
_WA_RETRIEVED = "2026-07-05T00:00:00+00:00"


def _wa_record(**over):
    """One itemized record shaped like the real Socrata JSON (url as {'url': ...})."""
    rec = {
        "id": "20318665", "report_number": "110314712", "filer_id": "24THLD 362",
        "filer_name": "24th LD Dem", "office": "", "party": "DEMOCRATIC",
        "legislative_district": "24", "election_year": "2025", "amount": "500.00",
        "cash_or_in_kind": "Cash", "receipt_date": "2025-09-15T00:00:00.000",
        "contributor_name": "Makah Tribal Council", "contributor_city": "Neah Bay",
        "contributor_state": "WA", "contributor_occupation": "",
        "contributor_employer_name": "",
        "url": {"url": "https://my.pdc.wa.gov/public/registrations/campaign-finance-report/110314712"},
    }
    rec.update(over)
    return rec


# Six real-shaped itemized rows for (24THLD 362, 2025): 500+250+250+400+383+400 = 2183.00.
_WA_ITEMIZED = [
    _wa_record(id="20318665", amount="500.00", contributor_name="Makah Tribal Council"),
    _wa_record(id="20318664", amount="250.00", contributor_name="Washburn's General Store"),
    _wa_record(id="20318666", amount="250.00", contributor_name="Neah Bay Grocery"),
    _wa_record(id="20318667", amount="400.00", contributor_name="Local 21 PAC", cash_or_in_kind="In-kind"),
    _wa_record(id="20318668", amount="383.00", contributor_name="A. Donor"),
    _wa_record(id="20318669", amount="400.00", contributor_name="B. Donor"),
]
# The companion control-total feed: one summary row per (filer, year).
_WA_SUMMARY = [{"filer_id": "24THLD 362", "election_year": "2025",
                "contributions_amount": "2183.00"}]


def _wa_warehouse():
    con = store.connect()
    store.init_schema(con)
    return con


def test_wa_pdc_contract_is_public_domain_and_reconcilable():
    """The pinned contract records the verified license, keys, and the control-total
    field actually used (summary contributions_amount grouped by filer/year)."""
    c = _wa.CONTRACT
    assert c.source_id == "wa_pdc" and c.license_is_public_domain
    assert c.license == "Public Domain"
    assert c.record_locator == "id" and c.source_record_url == "url"
    assert c.control_total.total_field == "contributions_amount"
    assert c.control_total.group_by == ("filer_id", "election_year")
    assert c.control_total.epsilon_cents == 0
    assert c.jurisdiction == "ocd-division/country:us/state:wa"
    # the enum domain is exactly what the live feed contains
    assert c.domain("cash_or_in_kind") == ("Cash", "In-kind")


def test_wa_pdc_copy_only_mappers_and_provenance():
    """Mappers copy verbatim cells (only dollars->cents and date parse), attaching
    the §6 envelope with the native id, per-record url, and retained raw values."""
    row, q = _wa.map_row(_wa_record(), file_sha256=_WA_SHA, retrieved_at=_WA_RETRIEVED)
    assert q is None
    assert row["id"] == "20318665" and row["filer_id"] == "24THLD 362"
    assert row["amount_cents"] == 50000 and row["raw_amount"] == "500.00"  # verbatim retained
    assert row["receipt_date"] == "2025-09-15"
    assert row["contributor_name"] == "Makah Tribal Council"
    assert row["raw_contributor_name"] == "Makah Tribal Council"
    assert row["source_record_url"].endswith("/campaign-finance-report/110314712")
    assert row["file_sha256"] == _WA_SHA and row["retrieved_at"] == _WA_RETRIEVED
    assert row["contract_version"] == _wa.CONTRACT.contract_version
    # negative amounts (refunds/corrections) are legitimate and preserved, not clamped
    neg, qn = _wa.map_row(_wa_record(id="R1", amount="-100.00"),
                          file_sha256=_WA_SHA, retrieved_at=_WA_RETRIEVED)
    assert qn is None and neg["amount_cents"] == -10000


def test_wa_pdc_clean_parse_matching_control_total_lands(tmp_path):
    """(a) Clean parse + a matching control total -> every row lands, none quarantined."""
    con = _wa_warehouse()
    stats = _transform.ingest_wa_pdc(con, _WA_ITEMIZED, _WA_SUMMARY,
                                     list(_wa.CONTRACT.header), _WA_SHA, _WA_RETRIEVED)
    assert stats == {"input": 6, "inserted": 6, "quarantined": 0}
    n = con.execute("SELECT count(*) FROM disclosure_contributions").fetchone()[0]
    assert n == 6
    total = con.execute("SELECT sum(amount_cents) FROM disclosure_contributions").fetchone()[0]
    assert total == 218300                                  # reconciles to the summary cent
    assert con.execute("SELECT count(*) FROM disclosure_quarantine").fetchone()[0] == 0
    con.close()


def test_wa_pdc_control_total_mismatch_halts(tmp_path):
    """(b) A control-total mismatch fails closed — the gate raises, nothing lands."""
    con = _wa_warehouse()
    bad_summary = [{"filer_id": "24THLD 362", "election_year": "2025",
                    "contributions_amount": "9999.00"}]   # != itemized $2,183.00
    with pytest.raises(_bulk_reconcile.ControlTotalError, match="control-total gate"):
        _transform.ingest_wa_pdc(con, _WA_ITEMIZED, bad_summary,
                                 list(_wa.CONTRACT.header), _WA_SHA, _WA_RETRIEVED)
    con.close()


def test_wa_pdc_missing_control_total_halts():
    """A filer/year present in the itemized data with NO control total is itself a
    failure — we never ship itemized data without a reconciliation basis (WO-9)."""
    with pytest.raises(_bulk_reconcile.ControlTotalError, match="NO control total"):
        _bulk_reconcile.control_total_gate({("F", 2025): 100}, {}, 0, "wa_pdc")


def test_wa_pdc_drifted_header_halts():
    """(c) A drifted header fails the schema-drift gate before any row is parsed —
    a changed layout is never best-effort parsed."""
    drifted = list(_wa.CONTRACT.header)
    drifted[18] = "amount_usd"                              # 'amount' renamed upstream
    con = _wa_warehouse()
    with pytest.raises(_bulk_reconcile.SchemaDriftError, match="schema-drift gate"):
        _transform.ingest_wa_pdc(con, _WA_ITEMIZED, _WA_SUMMARY,
                                 drifted, _WA_SHA, _WA_RETRIEVED)
    con.close()
    # a reordered header (same fields) is also drift — never silently accepted
    reordered = [_wa.CONTRACT.header[1], _wa.CONTRACT.header[0], *_wa.CONTRACT.header[2:]]
    drift = _bulk_contract.check_schema_drift(_wa.CONTRACT, reordered)
    assert drift is not None and drift.reordered
    assert _bulk_contract.check_schema_drift(_wa.CONTRACT, _wa.CONTRACT.header) is None


def test_wa_pdc_out_of_domain_value_quarantined_with_reason():
    """(d) An out-of-domain value is quarantined WITH a reason, never coerced; the
    no-silent-drop invariant input == inserted + quarantined still holds.

    A control total that matches only the good rows proves quarantined rows are
    excluded from the reconciled sum, not silently dropped."""
    con = _wa_warehouse()
    rows = [
        _wa_record(id="G1", amount="500.00"),                          # good
        _wa_record(id="B1", cash_or_in_kind="Loan"),                   # bad enum
        _wa_record(id="B2", amount="not-a-number"),                    # non-numeric amount
        _wa_record(id="B3", receipt_date="15th of Never"),             # unparseable date
        _wa_record(id="B4", election_year="soon"),                     # non-integer year
        {"filer_id": "24THLD 362", "amount": "1.00", "cash_or_in_kind": "Cash",
         "election_year": "2025", "url": {"url": "http://x"}},         # missing native id
    ]
    # only the one good row ($500) reconciles against the summary total for the group
    summary = [{"filer_id": "24THLD 362", "election_year": "2025",
                "contributions_amount": "500.00"}]
    stats = _transform.ingest_wa_pdc(con, rows, summary,
                                     list(_wa.CONTRACT.header), _WA_SHA, _WA_RETRIEVED)
    assert stats["input"] == 6 and stats["inserted"] == 1 and stats["quarantined"] == 5
    assert stats["input"] == stats["inserted"] + stats["quarantined"]   # no-silent-drop
    reasons = [r[0] for r in con.execute(
        "SELECT reason FROM disclosure_quarantine ORDER BY reason").fetchall()]
    assert any("cash_or_in_kind out of domain" in r for r in reasons)
    assert any("amount not numeric" in r for r in reasons)
    assert any("receipt_date unparseable" in r for r in reasons)
    assert any("election_year not an integer" in r for r in reasons)
    assert any("missing native id" in r for r in reasons)
    # the bad enum was quarantined verbatim, never coerced into the domain
    assert con.execute(
        "SELECT count(*) FROM disclosure_contributions WHERE cash_or_in_kind='Loan'"
    ).fetchone()[0] == 0
    con.close()


def test_wa_pdc_no_silent_drop_gate_catches_unaccounted():
    """The invariant is a hard gate: an input row neither inserted nor quarantined
    raises, so nothing can silently vanish."""
    with pytest.raises(_bulk_reconcile.SilentDropError, match="no-silent-drop gate"):
        _bulk_reconcile.no_silent_drop_gate(10, 7, 2, "wa_pdc")   # 7+2 != 10
    _bulk_reconcile.no_silent_drop_gate(10, 7, 3, "wa_pdc")       # 7+3 == 10, no raise


def test_wa_pdc_idempotent_reparse_is_identical():
    """(e) Re-parsing the identical snapshot yields byte-identical rows, and a second
    ingest into the same warehouse is a no-op (id PK + ON CONFLICT DO NOTHING)."""
    first = [_wa.map_row(r, file_sha256=_WA_SHA, retrieved_at=_WA_RETRIEVED)[0]
             for r in _WA_ITEMIZED]
    second = [_wa.map_row(r, file_sha256=_WA_SHA, retrieved_at=_WA_RETRIEVED)[0]
              for r in _WA_ITEMIZED]
    assert first == second                                  # deterministic, no drift

    con = _wa_warehouse()
    _transform.ingest_wa_pdc(con, _WA_ITEMIZED, _WA_SUMMARY,
                             list(_wa.CONTRACT.header), _WA_SHA, _WA_RETRIEVED)
    _transform.ingest_wa_pdc(con, _WA_ITEMIZED, _WA_SUMMARY,
                             list(_wa.CONTRACT.header), _WA_SHA, _WA_RETRIEVED)
    assert con.execute("SELECT count(*) FROM disclosure_contributions").fetchone()[0] == 6
    con.close()


# --- WO-8 donor↔vote juxtaposition + methodology wiring ---------------------
def test_key_votes_carry_congress_policy_areas(slice_dirs):
    """A key vote whose decided bill has a congress.gov policy area carries it
    verbatim as policy_areas[] (the money-&-votes chip source); procedural votes
    with no bill carry policy_areas=None. This is congress.gov's OWN taxonomy —
    Beholden adds no classification (build._bill_policy_areas reads it straight
    from the bills spine, sourced from item['policyArea']['name'])."""
    leg = _dossier_named(slice_dirs, "Jane Rep")["legislative"]
    by_rc = {v["roll_call_id"]: v for v in leg["key_votes"]}
    # RC1 decided HR100, which the fixture classifies policyArea "Health".
    assert by_rc["us/119/house/1"]["bill_id"] == "us/119/hr/100"
    assert by_rc["us/119/house/1"]["policy_areas"] == ["Health"]
    # Procedural RC2 has no bill -> no chip, and never an invented one.
    assert by_rc["us/119/house/2"]["bill_id"] is None
    assert by_rc["us/119/house/2"]["policy_areas"] is None


def test_bill_policy_areas_helper_skips_empty(slice_dirs):
    """_bill_policy_areas returns bill_id -> non-empty policy-area list only; a
    bill with no policy area (HR200 in the fixture) is absent, never []."""
    con = store.connect(str(slice_dirs / "wh.duckdb"))
    try:
        from beholden_etl.jobs.build import _bill_policy_areas
        pa = _bill_policy_areas(con)
    finally:
        con.close()
    assert pa["us/119/hr/100"] == ["Health"]
    assert "us/119/hr/200" not in pa                 # HR200 has no policyArea -> absent


def test_methodology_ids_wire_computed_metrics(slice_dirs):
    """WO-8: every provenance envelope over a Beholden-computed metric carries the
    matching /methodology anchor in methodology_id; verbatim source facts carry
    None. Anchors MUST match the methodology page's section ids."""
    jane = _dossier_named(slice_dirs, "Jane Rep")
    # Ideology score -> dw-nominate.
    assert jane["ideology"]["provenance"]["methodology_id"] == "dw-nominate"
    # Vote-derived facts: Jane has only 3 decided votes (< MIN_AGREEMENT_VOTES),
    # so agreement is omitted and the votes envelope points at key-vote selection.
    assert jane["legislative"]["party_agreement_pct"] is None
    assert jane["legislative"]["votes_provenance"]["methodology_id"] == "key-votes"
    # Top-contributor rollups -> donor-rollups; the raw legislative counts envelope
    # (congress.gov) stays None (verbatim facts, no Beholden metric).
    assert jane["money"]["campaign_finance"]["provenance"]["methodology_id"] == "donor-rollups"
    assert jane["legislative"]["provenance"]["methodology_id"] is None
    # Identity is a verbatim source fact -> no methodology id.
    assert jane["identity"]["provenance"]["methodology_id"] is None


def test_agreement_envelope_points_at_co_voting_when_published():
    """When party_agreement_pct IS published (>= MIN_AGREEMENT_VOTES), the votes
    envelope points at the co-voting anchor instead of key-votes. Unit-level over
    the same branch build._dossier takes, so it doesn't need 20+ fixture votes."""
    from beholden_etl.build import key_votes as kv
    # Build a member with 20 decided votes all matching a 20-strong party majority.
    maj = {f"m{i}\tR": "yea" for i in range(20)}
    member = [{"roll_call_id": f"m{i}", "position": "yea"} for i in range(20)]
    agreement = kv.agreement_pct(member, "R", maj)
    assert agreement == 100.0                         # >= gate -> published
    anchor = "co-voting" if agreement is not None else "key-votes"
    assert anchor == "co-voting"


def test_money_and_votes_both_present_for_juxtaposition(slice_dirs):
    """The juxtaposition module renders only when BOTH sides exist. Jane carries
    top_contributors AND key_votes, so both facts are published side-by-side as
    independent, each-cited records — the UI gate (hasMoneyVotes) is satisfiable
    without any donor→vote linkage in the data."""
    jane = _dossier_named(slice_dirs, "Jane Rep")
    assert len(jane["money"]["campaign_finance"]["top_contributors"]) == 25
    assert len(jane["legislative"]["key_votes"]) == 3
    # The two sides share no linking field — they are independent cited facts.
    kv0 = jane["legislative"]["key_votes"][0]
    assert "contributor" not in kv0 and "donor" not in kv0


# --- ICPSR crosswalk augmentation from Voteview (votes/ideology coverage fix) ---
def test_voteview_member_icpsr_to_bioguide_fills_crosswalk():
    """Voteview's members file maps every current member's icpsr<->bioguide, so it
    can fill the ICPSR crosswalk for members whose congress-legislators entry has no
    id.icpsr yet. icpsr must be normalized exactly as the score/vote joins key it
    (str(int(float(...)))), House/Senate only, rows missing either id skipped."""
    from beholden_etl.sources import voteview
    csv_text = (
        "chamber,icpsr,bioguide_id,bioname\n"
        "House,20301.0,R000575,\"ROGERS, Mike\"\n"      # icpsr normalizes 20301.0 -> 20301
        "Senate,21102,S001185,\"SEWELL, Terri\"\n"
        "President,99999,P999999,\"PREZ\"\n"            # non-legislator -> skipped
        "House,,B000000,\"NO ICPSR\"\n"                  # missing icpsr -> skipped
        "House,42424,,\"NO BIOGUIDE\"\n"                 # missing bioguide -> skipped
    )
    m = voteview.member_icpsr_to_bioguide(csv_text)
    assert m == {"20301": "R000575", "21102": "S001185"}


# --- WO-10 resilient / incremental / parallel fetch -------------------------
# The rawlake decisions (freshness, last-good fallback, graceful no-R2
# degradation) and the fetch orchestrator's fail-closed policy are unit-tested
# with fixtures/monkeypatch — the real R2 round-trip is validated in CI (no creds
# here). No source client's network behavior is exercised; the tests stub the
# per-source fetchers so only the resilience wiring is under test.
from httpx import ReadTimeout as _ReadTimeout             # noqa: E402
from beholden_etl import rawlake as _rawlake              # noqa: E402
from beholden_etl.jobs import fetch as _fetch             # noqa: E402


def test_rawlake_freshness_uses_config_sla():
    """A source snapshot younger than its config.SOURCES freshness_sla_hours is
    'fresh' (re-fetch may be skipped); older, missing, or unparseable is not."""
    now = datetime.now(timezone.utc)
    # congress.gov SLA is 24h. 1h old -> fresh; 48h old -> stale.
    fresh_ts = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    stale_ts = (now - timedelta(hours=48)).isoformat(timespec="seconds")
    assert _rawlake.is_fresh("congress.gov", fresh_ts, now=now) is True
    assert _rawlake.is_fresh("congress.gov", stale_ts, now=now) is False
    assert _rawlake.is_fresh("congress.gov", None, now=now) is False
    assert _rawlake.is_fresh("congress.gov", "not-a-timestamp", now=now) is False
    # Unknown source has no SLA -> never fresh (always fetch).
    assert _rawlake.is_fresh("no_such_source", fresh_ts, now=now) is False
    # A naive (tz-less) stamp is tolerated as UTC, not a crash.
    naive = (now - timedelta(hours=2)).replace(tzinfo=None).isoformat(timespec="seconds")
    assert _rawlake.age_hours(naive, now=now) == pytest.approx(2, abs=0.1)


def test_rawlake_source_is_fresh_reads_prior_manifest():
    """source_is_fresh reads a source's retrieved_at from an already-loaded prior
    manifest and applies its SLA."""
    now = datetime.now(timezone.utc)
    prior = {"sources": {
        "voteview": {"retrieved_at": (now - timedelta(hours=1)).isoformat(), "count": 5},
        "house_clerk": {"retrieved_at": (now - timedelta(hours=48)).isoformat(), "count": 9}}}
    # voteview SLA is 60 days -> 1h is fresh; house_clerk SLA 24h -> 48h is stale.
    assert _rawlake.source_is_fresh(prior, "voteview", now=now) is True
    assert _rawlake.source_is_fresh(prior, "house_clerk", now=now) is False
    # a source absent from the prior manifest is not fresh (must fetch)
    assert _rawlake.source_is_fresh(prior, "fec", now=now) is False


def test_rawlake_hydrate_degrades_without_r2(tmp_path, monkeypatch):
    """No R2 credentials -> hydration is a graceful no-op (returns 0), so local
    runs and CI unit tests fetch everything live."""
    for k in _rawlake.REQUIRED_ENV:
        monkeypatch.delenv(k, raising=False)
    assert _rawlake.r2_available() is False
    assert _rawlake.hydrate(tmp_path / "raw") == 0


def test_rawlake_hydrate_populates_from_mock_r2(tmp_path):
    """With a mock R2 client, hydrate pulls every raw/latest/ object into the lake
    at its lake-relative path (the last-good pointer -> resumable fetch)."""
    objects = {
        "raw/latest/manifest.json": b'{"sources":{}}',
        "raw/latest/congress.gov/legislation/R000001.json": b'{"bioguide":"R000001"}',
    }

    class FakeBody:
        def __init__(self, data):
            self._data = data

        def read(self):
            return self._data

    class FakePaginator:
        def paginate(self, **_):
            yield {"Contents": [{"Key": k} for k in objects]}

    class FakeClient:
        def get_paginator(self, _name):
            return FakePaginator()

        def get_object(self, Bucket, Key):
            return {"Body": FakeBody(objects[Key])}

    raw = tmp_path / "raw"
    n = _rawlake.hydrate(raw, client=FakeClient())
    assert n == 2
    assert (raw / "manifest.json").read_bytes() == b'{"sources":{}}'
    assert (raw / "congress.gov" / "legislation" / "R000001.json").exists()
    # the hydrated manifest is then readable for the freshness basis
    assert _rawlake.hydrated_manifest(raw) == {"sources": {}}


def test_rawlake_last_good_returns_snapshot_or_none(tmp_path):
    """last_good returns a single hydrated item, or None when it is absent — the
    per-item fallback the fetch fail-closed policy consults."""
    raw = tmp_path / "raw"
    rel = Path("congress.gov") / "legislation" / "R000001.json"
    (raw / rel).parent.mkdir(parents=True)
    (raw / rel).write_text(json.dumps({"bioguide": "R000001", "sponsored": [1, 2]}))
    assert _rawlake.last_good(raw, rel)["bioguide"] == "R000001"
    assert _rawlake.has_snapshot(raw, rel) is True
    assert _rawlake.last_good(raw, "congress.gov/legislation/NOPE.json") is None
    assert _rawlake.has_snapshot(raw, "congress.gov/legislation/NOPE.json") is False


def _stub_fetchers(monkeypatch, calls):
    """Replace every per-source fetcher with a fast stub that records the call and
    writes a marker file, so the orchestrator runs offline. `calls` is populated
    with the source keys that actually fetched."""
    def make(key):
        def fn(raw, prior):
            calls.add(key)
            _fetch._write_json(Path(raw) / key / "stub.json", {"k": key})
            return {"retrieved_at": _fetch._now(), "source_url": f"https://{key}", "count": 1}
        return fn
    stubs = {k: make(k) for k in _fetch._FETCHERS}
    monkeypatch.setattr(_fetch, "_FETCHERS", stubs)


def test_fetch_orchestrator_runs_all_sources_and_records_timings(tmp_path, monkeypatch):
    """A full run fans every source out concurrently and writes a manifest with a
    per-source status + count and a fetch_timings block (status + wall-time)."""
    calls: set[str] = set()
    _stub_fetchers(monkeypatch, calls)
    manifest = _fetch.run(tmp_path / "raw", full=True)
    # every source fetcher ran (wa_pdc's stub returns a fragment here; the real
    # fetcher returns None when disabled — covered separately below).
    assert calls == {"unitedstates_legislators", "congress.gov", "voteview",
                     "fec", "openstates", "house_clerk", "wa_pdc", "wikidata"}
    for meta in manifest["sources"].values():
        assert meta["count"] == 1 and "retrieved_at" in meta
    timings = manifest["fetch_timings"]
    assert timings["congress.gov"]["status"] == "fetched"
    for t in timings.values():
        assert isinstance(t["seconds"], (int, float))


def test_fetch_wa_pdc_absent_when_disabled(tmp_path):
    """The real wa_pdc fetcher returns None when gated off (config.WA_PDC_ENABLED
    is False), so the orchestrator marks it 'absent' and omits it from sources —
    the pre-WO-10 behavior, preserved."""
    assert _fetch.fetch_wa_pdc(tmp_path / "raw", prior={}) is None


def test_fetch_incremental_skips_fresh_and_keeps_original_retrieved_at(tmp_path, monkeypatch):
    """A hydrated snapshot still within its SLA is REUSED (status 'fresh') and
    carries its ORIGINAL retrieved_at — cached data is never restamped as freshly
    fetched. Stale/absent sources still fetch."""
    now = datetime.now(timezone.utc)
    fresh_ts = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "manifest.json").write_text(json.dumps({"sources": {
        "voteview": {"retrieved_at": fresh_ts, "source_url": "https://vv", "count": 42}}}))
    monkeypatch.setattr(_rawlake, "hydrate", lambda *a, **k: 0)   # lake already seeded
    calls: set[str] = set()
    _stub_fetchers(monkeypatch, calls)

    manifest = _fetch.run(raw, full=False)
    # voteview was fresh -> NOT re-fetched, and kept its original stamp + count
    assert "voteview" not in calls
    assert manifest["sources"]["voteview"]["retrieved_at"] == fresh_ts
    assert manifest["sources"]["voteview"]["count"] == 42
    assert manifest["fetch_timings"]["voteview"]["status"] == "fresh"
    # a stale/absent source (fec) still fetched fresh
    assert "fec" in calls
    assert manifest["fetch_timings"]["fec"]["status"] == "fetched"


def test_fetch_full_rebuild_ignores_fresh_snapshot(tmp_path, monkeypatch):
    """full=True bypasses the freshness gate — even a fresh snapshot is re-fetched."""
    now = datetime.now(timezone.utc)
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "manifest.json").write_text(json.dumps({"sources": {
        "voteview": {"retrieved_at": now.isoformat(timespec="seconds"),
                     "source_url": "https://vv", "count": 42}}}))
    monkeypatch.setattr(_rawlake, "hydrate", lambda *a, **k: 0)
    calls: set[str] = set()
    _stub_fetchers(monkeypatch, calls)
    _fetch.run(raw, full=True)
    assert "voteview" in calls                          # full rebuild re-fetches it


# --- WO-10 §4 fail-closed policy for the congress.gov legislation loop -------
class _FlakyCongress:
    """A congress.gov client stand-in whose per-member calls raise ReadTimeout, to
    exercise the last-good fallback vs hard-fail decision without any network."""
    def __init__(self, members):
        self._members = members

    def current_members(self, _congress):
        return iter(self._members)

    def sponsored_legislation(self, _bio):
        raise _ReadTimeout("simulated slow patch")

    def cosponsored_count(self, _bio):
        raise _ReadTimeout("simulated slow patch")


def _install_flaky_congress(monkeypatch, members):
    monkeypatch.setattr(_fetch.congress_gov, "CongressGovClient",
                        lambda *a, **k: _FlakyCongress(members))


def test_congress_gov_per_item_falls_back_to_last_good_snapshot(tmp_path, monkeypatch):
    """A transient per-member ReadTimeout WITH a prior snapshot in the lake ->
    the run completes using the cached (slightly stale) snapshot rather than
    dropping the member (which would fabricate a false 'sponsored 0')."""
    raw = tmp_path / "raw"
    members = [{"bioguideId": "R000001"}]
    _install_flaky_congress(monkeypatch, members)
    rel = raw / "congress.gov" / "legislation" / "R000001.json"
    rel.parent.mkdir(parents=True)
    cached = {"bioguide": "R000001", "sponsored": [{"x": 1}], "cosponsored_count": 7}
    rel.write_text(json.dumps(cached))

    meta = _fetch.fetch_congress_gov(raw, prior={})
    # the failing member's file is the last-good snapshot, not dropped/zeroed
    assert json.loads(rel.read_text()) == cached
    assert meta["legislation_reused"] == 1
    assert meta["count"] == 1


def test_congress_gov_per_item_hard_fails_without_prior_snapshot(tmp_path, monkeypatch):
    """A transient per-member failure with NO prior snapshot AND where absence
    would fabricate (legislation counts) MUST fail closed — the exception
    propagates rather than publish a false 'sponsored 0'."""
    raw = tmp_path / "raw"
    members = [{"bioguideId": "R000001"}]
    _install_flaky_congress(monkeypatch, members)
    with pytest.raises(_ReadTimeout):                   # no cached snapshot -> fail closed
        _fetch.fetch_congress_gov(raw, prior={})


def test_fec_absence_is_honest_not_fail_closed(tmp_path, monkeypatch):
    """FEC per-candidate failure is skipped (absence is honest -> no money
    section, never a fabricated $0). The loop completes and the source stays
    present with an honest count, no last-good fallback needed."""
    raw = tmp_path / "raw"
    (raw / "unitedstates_legislators").mkdir(parents=True)
    (raw / "unitedstates_legislators" / "legislators-current.json").write_text(
        json.dumps([{"id": {"fec": ["H8TN06001"]}}]))

    class _FlakyFEC:
        def candidate_totals(self, *a, **k):
            raise _ReadTimeout("boom")

        def principal_committee(self, *a, **k):
            raise _ReadTimeout("boom")

        def top_contributors_by_employer(self, *a, **k):
            return []
    monkeypatch.setattr(_fetch.fec, "FECClient", lambda *a, **k: _FlakyFEC())

    meta = _fetch.fetch_fec(raw, prior={})              # does NOT raise
    assert meta["count"] == 0 and meta["contributors"] == 0


def test_publish_writes_last_good_pointer_dry_run(tmp_path):
    """publish mirrors the raw lake to raw/latest/ (the last-good pointer fetch
    hydrates from). Keys use the stable latest/ prefix, not a dated partition."""
    from beholden_etl.jobs import publish as _publish
    raw = tmp_path / "raw"
    (raw / "congress.gov").mkdir(parents=True)
    (raw / "manifest.json").write_text('{"generated_at":"2026-07-06T00:00:00+00:00"}')
    (raw / "congress.gov" / "members-119.json").write_text("[]")
    latest = _publish._latest_batch(raw)
    keys = {k for _, k in latest}
    assert "raw/latest/manifest.json" in keys
    assert "raw/latest/congress.gov/members-119.json" in keys
    assert all(k.startswith("raw/latest/") for k in keys)


# --- WO-12 cited drill-down data ---------------------------------------------
def test_question_and_description_rule():
    """`question` keeps the WO-1 first-non-blank rule; `description` carries the
    OTHER Voteview text VERBATIM only when it is non-blank and differs from the
    chosen question (adds information) — otherwise None, never padded/invented."""
    from beholden_etl.sources import voteview as vv
    # both present and different -> question from vote_question, desc published
    assert vv.question_and_description(
        {"vote_question": "On Passage", "vote_desc": "Passage of HR100"}) == \
        ("On Passage", "Passage of HR100")
    # blank vote_desc -> no description (honest absence)
    assert vv.question_and_description(
        {"vote_question": "On Agreeing", "vote_desc": ""}) == ("On Agreeing", None)
    # identical texts -> desc adds nothing -> None
    assert vv.question_and_description(
        {"vote_question": "On Passage", "vote_desc": "On Passage"}) == ("On Passage", None)
    # blank vote_question -> question falls back to vote_desc, and the "other"
    # text (the blank question) is never published as a description
    assert vv.question_and_description(
        {"vote_question": "", "vote_desc": "A procedural motion"}) == \
        ("A procedural motion", None)
    assert vv.question_and_description({}) == ("", None)


def test_roll_call_rows_carry_tallies_and_blank_is_null():
    """to_roll_call_rows persists the CSV's yea/nay tallies verbatim (migration
    005 columns); a blank tally cell lands as NULL, never a fabricated 0."""
    from beholden_etl.sources import voteview as vv
    header = ("congress,chamber,rollnumber,date,session,clerk_rollnumber,"
              "yea_count,nay_count,bill_number,vote_result,vote_desc,vote_question\n")
    rows = list(vv.to_roll_call_rows(
        header + "119,House,7,2025-05-01,1,13,217,213,,Passed,Something,On Passage\n"
               + "119,House,8,2025-05-02,1,14,,,,Passed,Another,On Passage\n", 119, set()))
    assert (rows[0]["yea_count"], rows[0]["nay_count"]) == (217, 213)
    assert rows[1]["yea_count"] is None and rows[1]["nay_count"] is None


def test_roll_call_tallies_land_in_spine(slice_dirs):
    """The transform persists yea_count/nay_count on roll_calls (WO-12,
    005_roll_call_tallies.sql), verbatim from the rollcalls CSV."""
    con = store.connect(str(slice_dirs / "wh.duckdb"))
    tallies = dict((rcid, (y, n)) for rcid, y, n in con.execute(
        "SELECT roll_call_id, yea_count, nay_count FROM roll_calls").fetchall())
    con.close()
    assert tallies["us/119/house/1"] == (12, 9)
    assert tallies["us/119/house/2"] == (11, 10)
    assert tallies["us/119/house/3"] == (20, 1)


def test_key_votes_carry_title_description_and_tallies(slice_dirs):
    """Each key vote publishes the drill-down facts (WO-12): the decided bill's
    warehoused title (null for procedural votes — honest absence, never an
    invented title), Voteview's secondary text as description only when it adds
    information (blank vote_desc -> None), and the persisted chamber tallies."""
    leg = _dossier_named(slice_dirs, "Jane Rep")["legislative"]
    by_rc = {v["roll_call_id"]: v for v in leg["key_votes"]}
    rc1, rc2, rc3 = (by_rc[f"us/119/house/{i}"] for i in (1, 2, 3))
    # RC1 decided HR100 -> its spine title, verbatim from congress.gov
    assert rc1["bill_title"] == "A Bill To Do X"
    assert rc1["description"] == "Passage of HR100"           # vote_desc != question
    assert (rc1["yea_count"], rc1["nay_count"]) == (12, 9)
    # RC2 is procedural (no bill) -> bill_title null, never invented
    assert rc2["bill_id"] is None and rc2["bill_title"] is None
    assert rc2["description"] == "A procedural motion"
    assert (rc2["yea_count"], rc2["nay_count"]) == (11, 10)
    # RC3's vote_desc is blank in the fixture -> no description (honest absence)
    assert rc3["description"] is None
    assert (rc3["yea_count"], rc3["nay_count"]) == (20, 1)
    # existing citation fields are untouched alongside the new ones
    assert rc1["url"] == "https://clerk.house.gov/Votes/202510"
    assert rc1["bill_url"] == "https://www.congress.gov/bill/119th-congress/house-bill/100"


def test_recent_bills_carry_dates(slice_dirs):
    """recent_bills publishes introduced_on / latest_action_on (WO-12) — the
    warehoused congress.gov dates already used for the recency sort — verbatim
    per bill, newest action first."""
    leg = _dossier_named(slice_dirs, "Jane Rep")["legislative"]
    by_bill = {b["bill_id"]: b for b in leg["recent_bills"]}
    assert by_bill["us/119/hr/100"]["introduced_on"] == "2025-02-01"
    assert by_bill["us/119/hr/100"]["latest_action_on"] == "2025-06-01"
    assert by_bill["us/119/hr/200"]["introduced_on"] == "2025-03-01"
    assert by_bill["us/119/hr/200"]["latest_action_on"] == "2025-04-01"
    # ordering (latest action desc) is unchanged by the added fields
    assert [b["bill_id"] for b in leg["recent_bills"]] == ["us/119/hr/100", "us/119/hr/200"]


def test_dossier_committees_carry_id_and_source_url_only(slice_dirs):
    """Committee items publish the deterministic committee_id plus the official
    url ONLY when the source roster provides one (WO-12): HSAG carries its yaml
    url; HSWM (no url in the roster) publishes committee_id alone — never a
    constructed/unverified link; subcommittees (never url'd in the source) carry
    committee_id alone. Same lookup for every committee (rule #3)."""
    leg = _dossier_named(slice_dirs, "Jane Rep")["legislative"]
    ag = next(c for c in leg["committees"] if c["name"] == "House Committee on Agriculture")
    assert ag["committee_id"] == "HSAG"
    assert ag["url"] == "https://agriculture.house.gov/"      # source-provided, verbatim
    wm = next(c for c in leg["committees"] if c["name"] == "House Committee on Ways and Means")
    assert wm["committee_id"] == "HSWM"
    assert "url" not in wm                                    # no source url -> id only
    sub = ag["subcommittees"][0]
    assert sub["committee_id"] == "HSAG15" and "url" not in sub


def test_committee_urls_helper_reads_source_roster_only(slice_dirs):
    """_committee_urls maps committee_id -> the roster's OWN url field; a
    committee without one is simply absent (no fallback pattern), and a missing
    roster file degrades to an empty map rather than inventing links."""
    from beholden_etl.jobs.build import _committee_urls
    urls = _committee_urls(slice_dirs / "raw")
    assert urls == {"HSAG": "https://agriculture.house.gov/"}
    assert _committee_urls(slice_dirs / "nonexistent") == {}


# --- WO-14 Senate delegation stylefeed (states.json) --------------------------
def _sen(state: str, party: str, vacant: bool = False) -> dict:
    """A senate holder row as build.run feeds the delegation rule: the senator's
    division IS the state division (both seats share one ocd_id)."""
    return {"ocd_id": f"ocd-division/country:us/state:{state}", "party": party,
            "is_vacant_marker": vacant}


def test_senate_delegation_same_party_colors_the_state():
    """Both seated senators the same party -> that party code, not vacant.
    Asserted for BOTH major parties with the identical rule (rule #3)."""
    from beholden_etl.build import stylefeeds
    feed = stylefeeds.build_senate_delegation_feed(
        [_sen("tn", "R"), _sen("tn", "R"), _sen("vt", "D"), _sen("vt", "D")])
    assert feed["ocd-division/country:us/state:tn"] == \
        {"party": "R", "ideology_dim1": None, "vacant": False}
    assert feed["ocd-division/country:us/state:vt"] == \
        {"party": "D", "ideology_dim1": None, "vacant": False}


def test_senate_delegation_split_is_split_either_order():
    """A split delegation publishes the dedicated SPLIT code — never one of the
    two parties — and the outcome is identical whichever senator comes first
    (symmetric by construction). Third-party pairings split the same way."""
    from beholden_etl.build import stylefeeds
    for pair in (("D", "R"), ("R", "D"), ("I", "R"), ("D", "I")):
        feed = stylefeeds.build_senate_delegation_feed(
            [_sen("pa", pair[0]), _sen("pa", pair[1])])
        assert feed["ocd-division/country:us/state:pa"] == \
            {"party": "SPLIT", "ideology_dim1": None, "vacant": False}, pair


def test_senate_delegation_vacancy_handling():
    """One seat vacant (marker row) or simply absent from the warehouse -> the
    seated senator's party with vacant=true (color what we know, flag what we
    don't — the second seat is never invented); both seats vacant -> NP+vacant."""
    from beholden_etl.build import stylefeeds
    feed = stylefeeds.build_senate_delegation_feed([
        _sen("oh", "D"), _sen("oh", "NP", vacant=True),   # explicit vacant marker
        _sen("wy", "R"),                                  # lone row, no marker
        _sen("ak", "NP", vacant=True), _sen("ak", "NP", vacant=True),
    ])
    assert feed["ocd-division/country:us/state:oh"] == \
        {"party": "D", "ideology_dim1": None, "vacant": True}
    assert feed["ocd-division/country:us/state:wy"] == \
        {"party": "R", "ideology_dim1": None, "vacant": True}
    assert feed["ocd-division/country:us/state:ak"] == \
        {"party": "NP", "ideology_dim1": None, "vacant": True}


def test_states_stylefeed_emitted_keyed_by_state_ocd(slice_dirs):
    """build.run now publishes a REAL stylefeeds/states.json (it shipped empty
    before WO-14): keyed by the state's ocd_id, StyleRow-shaped, ideology always
    null (a delegation has no single score). The fixture warehouse knows one TN
    senator (R), so TN colors R with the honest vacancy flag."""
    feed = json.loads((slice_dirs / "data" / "stylefeeds" / "states.json").read_text())
    assert feed == {"ocd-division/country:us/state:tn":
                    {"party": "R", "ideology_dim1": None, "vacant": True}}
    cov = json.loads((slice_dirs / "data" / "coverage.json").read_text())
    assert cov["counts"]["states_stylefeed"] == 1


# --- WO-15: contact · social · previous-roles · bio · education ------------
def test_legislators_contact_from_term_omits_absent_fields():
    """contact_from_term publishes only the keys the term actually carries —
    never a null placeholder — and prefers `address` over the short `office`
    form when both are present."""
    from beholden_etl.sources import legislators as L
    full = {"phone": "202-225-0001", "url": "https://x.house.gov",
            "contact_form": "https://x.house.gov/contact", "address": "123 Main St"}
    assert L.contact_from_term(full) == {
        "phone": "202-225-0001", "website": "https://x.house.gov",
        "contact_form": "https://x.house.gov/contact", "dc_office_address": "123 Main St"}
    assert L.contact_from_term({}) == {}          # no term data -> empty, never fabricated
    assert L.contact_from_term(None) == {}         # no current term at all
    # `office` (short form) used only when `address` is absent.
    assert L.contact_from_term({"office": "511 Hart SOB"}) == {"dc_office_address": "511 Hart SOB"}


def test_legislators_district_offices_by_bioguide_keeps_only_populated_fields():
    from beholden_etl.sources import legislators as L
    records = [
        {"id": {"bioguide": "X000001"}, "offices": [
            {"id": "o1", "address": "1 St", "city": "Town", "state": "TN",
             "zip": "37000", "phone": "615-555-0000", "latitude": 1.0, "longitude": -2.0,
             "id_field_not_in_allowlist": "ignored"},
            {"id": "o2"},                          # no useful fields -> dropped entirely
        ]},
        {"offices": [{"id": "o3", "address": "no bioguide"}]},   # no bioguide -> skipped
    ]
    out = L.district_offices_by_bioguide(records)
    assert list(out.keys()) == ["X000001"]
    assert out["X000001"] == [{"address": "1 St", "city": "Town", "state": "TN",
                                "zip": "37000", "phone": "615-555-0000",
                                "latitude": 1.0, "longitude": -2.0}]


def test_legislators_social_media_by_bioguide_verbatim_handles_only():
    from beholden_etl.sources import legislators as L
    records = [
        {"id": {"bioguide": "X000001"}, "social": {
            "twitter": "xrep", "twitter_id": "999", "mastodon": "@xrep@mastodon.social"}},
        {"id": {"bioguide": "Y000002"}, "social": {}},   # empty social -> absent, not published
    ]
    out = L.social_media_by_bioguide(records)
    assert out == {"X000001": {"twitter": "xrep", "mastodon": "@xrep@mastodon.social"}}
    assert "twitter_id" not in out["X000001"]      # only the allow-listed handle fields publish
    assert "Y000002" not in out


def test_openstates_contact_and_social_from_row_are_column_verbatim():
    from beholden_etl.sources import openstates
    row = {"email": "a@leg.state.gov", "capitol_address": "1 Capitol",
           "capitol_voice": "555-0001", "district_address": "", "district_voice": "",
           "twitter": "stateleg", "youtube": "", "instagram": "", "facebook": ""}
    assert openstates.contact_from_row(row) == {
        "email": "a@leg.state.gov", "capitol_address": "1 Capitol", "capitol_voice": "555-0001"}
    assert openstates.social_from_row(row) == {"twitter": "stateleg"}
    assert openstates.contact_from_row({}) == {}
    assert openstates.social_from_row({}) == {}


def test_congress_gov_member_detail_normalizers():
    from beholden_etl.sources import congress_gov as C
    detail = {"birthYear": "1965",
              "leadership": [{"type": "Chair", "congress": 119}, {"congress": 118}],
              "partyHistory": [{"partyName": "Democratic", "startYear": 2019, "endYear": None}],
              "addressInformation": {"officeAddress": "100 X St", "city": "Washington",
                                     "zipCode": "20515", "phoneNumber": "202-225-9999"}}
    assert C.birth_year(detail) == 1965
    assert C.birth_year({}) is None
    assert C.birth_year({"birthYear": "not-a-year"}) is None
    assert C.leadership_roles(detail) == [{"role": "Chair", "congress": 119}]   # no-role entry dropped
    assert C.party_history(detail) == [{"party": "Democratic", "start_year": 2019, "end_year": None}]
    assert C.dc_office_from_detail(detail) == {
        "dc_office_address": "100 X St, Washington, 20515", "phone": "202-225-9999"}
    assert C.dc_office_from_detail({}) == {}


def test_wikidata_educated_at_claims_and_time_year_parsing():
    from beholden_etl.sources import wikidata as W
    entity = {"entities": {"Q1": {"claims": {"P69": [
        {"mainsnak": {"datavalue": {"value": {"id": "Q10"}}},
         "qualifiers": {"P512": [{"datavalue": {"value": {"id": "Q20"}}}],
                        "P582": [{"datavalue": {"value": {"time": "+1990-00-00T00:00:00Z"}}}]}},
        {"mainsnak": {"datavalue": {"value": {"id": "Q30"}}}},   # no qualifiers at all
    ]}}}}
    claims = W.educated_at_claims(entity, "Q1")
    assert claims == [
        {"institution_qid": "Q10", "degree_qid": "Q20", "end_year": 1990},
        {"institution_qid": "Q30"},
    ]
    assert W.educated_at_claims({"entities": {}}, "Q1") == []   # unknown qid -> empty, never crashes
    # A real entity with no P69 statement at all (most Wikidata people items) ->
    # an empty list, never an error or a fabricated entry.
    no_p69 = {"entities": {"Q9": {"claims": {"P106": [{"mainsnak": {}}]}}}}
    assert W.educated_at_claims(no_p69, "Q9") == []


def test_wikidata_chunking_respects_the_documented_cap():
    from beholden_etl.sources import wikidata as W
    ids = [f"Q{i}" for i in range(120)]
    chunks = W.chunk_ids(ids)
    assert len(chunks) == 3 and all(len(c) <= W.WBGETENTITIES_MAX_IDS for c in chunks)
    assert sum(len(c) for c in chunks) == 120


def test_wikidata_education_rows_drops_unlabeled_institution_never_invents():
    from beholden_etl.sources import wikidata as W
    claims = [{"institution_qid": "Q1", "degree_qid": "Q2", "end_year": 1999},
              {"institution_qid": "Q3"},                 # no label for Q3 -> dropped entirely
              {"institution_qid": "Q4", "degree_qid": "Q5"}]   # no label for Q5 -> degree omitted
    labels = {"Q1": "Acme University", "Q2": "PhD", "Q4": "Beta College"}
    rows = W.education_rows(claims, labels)
    assert rows == [
        {"institution": "Acme University", "degree": "PhD", "year": 1999},
        {"institution": "Beta College"},
    ]


def test_dossier_contact_district_offices_social_previous_roles_education(slice_dirs):
    """The WO-15 happy path, all six groups on one federal officeholder (Jane):
    contact (federal term fields), district_offices (verbatim per-office dicts),
    social (unitedstates handles), previous_roles (our own warehoused past
    term), birth_year (congress.gov member-detail), and education (Wikidata,
    with its OWN provenance envelope + the verbatim crowd-sourced caveat)."""
    ident = _dossier_named(slice_dirs, "Jane Rep")["identity"]

    assert ident["contact"] == {
        "phone": "202-225-0001", "website": "https://rep.house.gov",
        "contact_form": "https://rep.house.gov/contact",
        "dc_office_address": "1234 Longworth House Office Building Washington DC 20515"}

    assert ident["district_offices"] == [
        {"address": "100 Main St", "city": "Nashville", "state": "TN", "zip": "37201",
         "phone": "615-555-0100", "latitude": 36.16, "longitude": -86.78}]

    assert ident["social"] == {"twitter": "JaneRep", "mastodon": "@janerep@mastodon.social"}

    assert ident["previous_roles"] == [
        {"role": "representative", "chamber": "house",
         "start_date": "2023-01-03", "end_date": "2025-01-03", "party": "D"}]

    assert ident["birth_year"] == 1970   # congress.gov member-detail's own field

    edu = ident["education"]
    assert edu["items"] == [{"institution": "Test University", "degree": "Bachelor of Arts", "year": 1992},
                            {"institution": "Night School"}]
    assert edu["credibility_note"] == (
        "Sourced from Wikidata, a publicly edited encyclopedia — verify against "
        "the member's official biography.")
    assert edu["provenance"]["source"] == "wikidata"          # its OWN envelope, never identity's
    assert edu["provenance"]["retrieved_at"]                  # no provenance, no publish


def test_dossier_honest_absence_no_phone_no_wikidata_no_district_offices(slice_dirs):
    """Al: no wikidata_qid (education key entirely absent — never an empty
    array), no member-detail file (birth_year falls back to the warehoused
    unitedstates value), no district-offices entry, no social entry, no
    previous term (previous_roles key entirely absent), and no contact fields
    on his single current term (contact key entirely absent)."""
    ident = _dossier_named(slice_dirs, "Al Large")["identity"]
    assert "education" not in ident
    assert "district_offices" not in ident
    assert "social" not in ident
    assert "previous_roles" not in ident
    assert "contact" not in ident
    assert "birth_year" not in ident   # Al's fixture carries no bio.birthday either


def test_dossier_education_absent_when_wikidata_qid_resolves_to_blank_p69(slice_dirs):
    """Sam DOES carry a wikidata_qid (unlike Al), but his claims fixture is a
    blank P69 (empty list) — the dossier must publish NO education key at all,
    never an empty {"items": []} block (fail-closed: a resolved-but-empty
    claim is not a fact to publish)."""
    ident = _dossier_named(slice_dirs, "Sam Sen")["identity"]
    assert "education" not in ident


def test_dossier_state_legislator_gets_state_shaped_contact_and_social(slice_dirs):
    """Pat (TN state senator) publishes OpenStates' own contact/social columns —
    a DIFFERENT shape than the federal contact block (email + capitol/district
    address+voice, vs. phone/website/contact_form/dc_office_address) — never
    federal-shaped fields on a state dossier. Dana (same chamber, blank
    columns) proves the honest-absence path for state too."""
    docs = [json.loads(f.read_text()) for f in (slice_dirs / "data" / "dossiers").glob("*.json")]
    pat = next(d for d in docs if d["identity"]["full_name"] == "Pat Upper")["identity"]
    assert pat["contact"] == {
        "email": "pat.upper@leg.tn.gov", "capitol_address": "301 Capitol",
        "capitol_voice": "615-555-0001", "district_address": "88 District Rd",
        "district_voice": "615-555-0002"}
    assert pat["social"] == {"twitter": "patupper", "instagram": "patupper_ig", "facebook": "patupper.fb"}
    assert "phone" not in pat["contact"] and "website" not in pat["contact"]   # never federal-shaped
    assert "district_offices" not in pat and "education" not in pat   # federal-only groups, state omits

    dana = next(d for d in docs if d["identity"]["full_name"] == "Dana Lower")["identity"]
    assert "contact" not in dana        # blank CSV columns -> honest absence, not a fabricated {}
    assert "social" not in dana


def test_previous_roles_reads_from_our_own_warehoused_terms(slice_dirs):
    """previous_roles is sourced from the SAME `terms` table transform.py
    warehouses for current terms — not re-derived from raw at build time —
    ordered most-recent-first (only one past term in the fixture, but the
    ordering contract is asserted directly against _previous_roles)."""
    from beholden_etl import store
    from beholden_etl.jobs.build import _previous_roles
    con = store.connect(str(slice_dirs / "wh.duckdb"))
    try:
        by_person = _previous_roles(con)
    finally:
        con.close()
    # Jane's person_id is deterministic from her bioguide.
    from beholden_etl.sources import legislators as L
    jane_id = L.person_uuid("R000001")
    assert by_person[jane_id] == [{"role": "representative", "chamber": "house",
                                   "start_date": "2023-01-03", "end_date": "2025-01-03",
                                   "party": "D"}]
    # No past terms for Al/Sam -> no key at all (never an empty list published
    # as if it were a checked-and-empty fact).
    al_id = L.person_uuid("A000002")
    assert al_id not in by_person


def test_fetch_wikidata_batches_labels_and_skips_persons_without_entity(tmp_path, monkeypatch):
    """fetch_wikidata reads the landed legislators snapshot for wikidata qids,
    fetches one entity per qid, and batches EVERY referenced item id (across
    every person) into resolve_labels in as few calls as possible — a
    per-person entity failure is skipped (education absence is honest), never
    sinking the run."""
    from beholden_etl.jobs import fetch as _fetch
    from beholden_etl.sources import wikidata as W

    raw = tmp_path / "raw"
    (raw / "unitedstates_legislators").mkdir(parents=True)
    legs = [{"id": {"bioguide": "R000001", "wikidata": "Q1"}},
            {"id": {"bioguide": "R000002", "wikidata": "Q2"}},
            {"id": {"bioguide": "R000003"}}]                 # no wikidata id -> excluded from qids
    (raw / "unitedstates_legislators" / "legislators-current.json").write_text(json.dumps(legs))

    def fake_fetch_entity(qid):
        if qid == "Q2":
            raise RuntimeError("simulated transient failure")
        return {"entities": {"Q1": {"claims": {"P69": [
            {"mainsnak": {"datavalue": {"value": {"id": "Q100"}}}}]}}}}

    resolve_calls = []

    def fake_resolve_labels(ids):
        resolve_calls.append(set(ids))
        return {"Q100": "Acme U"}

    monkeypatch.setattr(W, "fetch_entity", fake_fetch_entity)
    monkeypatch.setattr(W, "resolve_labels", fake_resolve_labels)

    meta = _fetch.fetch_wikidata(raw, prior={})
    assert meta["count"] == 1 and meta["skipped"] == 1     # Q1 ok, Q2 skipped
    assert meta["labels"] == 1
    assert resolve_calls == [{"Q100"}]                     # ONE batched call, not one per person

    claims = json.loads((raw / "wikidata" / "claims" / "educated_at.json").read_text())
    assert claims == {"Q1": [{"institution_qid": "Q100"}]}
    assert "Q2" not in claims                              # failed entity -> no claims entry
    labels = json.loads((raw / "wikidata" / "labels.json").read_text())
    assert labels == {"Q100": "Acme U"}


# --- WO-17: state votes/bills via OpenStates API v3 ---------------------------
from beholden_etl.sources import openstates_votes as _osv  # noqa: E402

_PAT_OCD = "ocd-person/aaaa1111-1111-1111-1111-111111111111"
_DANA_OCD = "ocd-person/bbbb2222-2222-2222-2222-222222222222"
_UNKNOWN_OCD = "ocd-person/9999dead-dead-dead-dead-deaddeaddead"
_SB512_RC = "tn/114/upper/cccc3333-3333-3333-3333-333333333333"


def _state_person_id(ocd_person: str) -> str:
    import uuid
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"openstates:{ocd_person}"))


def test_openstates_votes_id_formats():
    """State bill_id = '{state}/{session}/{identifier-slug}' — lowercase,
    whitespace runs -> '-' (DATA-CONTRACTS §2 additive note). Roll calls key on
    the API's own ocd-vote uuid, so ids are deterministic and collision-free."""
    assert _osv.state_bill_id("TN", "114", "SB 512") == "tn/114/sb-512"
    assert _osv.state_bill_id("ca", "20252026", " AB 1 ") == "ca/20252026/ab-1"
    assert _osv.state_bill_id("tx", "89 1", "HB  21") == "tx/89-1/hb-21"
    assert _osv.state_roll_call_id("tn", "114", "upper", "ocd-vote/abc-123") == \
        "tn/114/upper/abc-123"
    # DC and PR are districts/territories, not states, in OCD jurisdiction ids.
    assert _osv.jurisdiction_id("tn") == "ocd-jurisdiction/country:us/state:tn/government"
    assert _osv.jurisdiction_id("dc") == "ocd-jurisdiction/country:us/district:dc/government"
    assert _osv.jurisdiction_id("pr") == "ocd-jurisdiction/country:us/territory:pr/government"


def test_openstates_votes_status_derivation():
    """bills.status derives from OpenStates' own action classifications with a
    fixed precedence, conservative default 'introduced' (mirror of the federal
    congress_gov.derive_status: unknown never becomes a stronger claim)."""
    st = _osv.derive_status
    assert st([]) == "introduced"
    assert st([{"classification": ["introduction"]}]) == "introduced"
    assert st([{"classification": ["referral-committee"]}]) == "committee"
    assert st([{"classification": ["passage"],
                "organization": {"classification": "lower"}}]) == "passed_chamber"
    assert st([{"classification": ["passage"], "organization": {"classification": "lower"}},
               {"classification": ["passage"], "organization": {"classification": "upper"}},
               ]) == "passed_both"
    # Nebraska-style unicameral passage stays passed_chamber, never passed_both.
    assert st([{"classification": ["passage"],
                "organization": {"classification": "legislature"}}]) == "passed_chamber"
    assert st([{"classification": ["passage"], "organization": {"classification": "lower"}},
               {"classification": ["executive-signature"]}]) == "law"
    assert st([{"classification": ["became-law"]}]) == "law"
    assert st([{"classification": ["executive-veto"]}]) == "vetoed"
    assert st([{"classification": ["failure"]}]) == "failed"


def test_openstates_votes_parse_bill_rows_and_source_skips():
    """parse_bill maps a v3 record to spine-shaped rows: options to the
    positions CHECK enum, tallies verbatim, sponsorships by ocd-person id only.
    Source-side unlinkable records (org sponsorships with no person id; voters
    the SOURCE couldn't resolve) are skipped AND counted — never name-matched."""
    parsed = _osv.parse_bill(
        "tn", STATE_VOTES_TN["bills"]["ocd-bill/11112222-3333-4444-5555-666677778888"])
    assert parsed["bill"]["bill_id"] == "tn/114/sb-512"
    assert parsed["bill"]["jurisdiction"] == "tn" and parsed["bill"]["session"] == "114"
    assert parsed["bill"]["status"] == "passed_chamber"
    assert parsed["bill"]["policy_areas"] == ["Education"]   # the state's own subjects
    assert parsed["bill"]["introduced_on"] == "2025-02-01"
    # sponsorships: Pat primary -> sponsor, Dana -> cosponsor; org sponsor skipped
    assert parsed["sponsorships"] == [
        {"bill_id": "tn/114/sb-512", "ocd_person": _PAT_OCD, "role": "sponsor"},
        {"bill_id": "tn/114/sb-512", "ocd_person": _DANA_OCD, "role": "cosponsor"}]
    rc = parsed["roll_calls"][0]
    assert rc["roll_call_id"] == _SB512_RC and rc["chamber"] == "upper"
    assert rc["question"] == "Third Reading" and rc["result"] == "pass"
    assert (rc["yea_count"], rc["nay_count"]) == (17, 14)    # verbatim tallies
    # positions keep the raw ocd-person ref (transform owns join + quarantine);
    # the voter=None row is skipped (source itself couldn't resolve the person).
    assert parsed["positions"] == [
        {"roll_call_id": _SB512_RC, "ocd_person": _PAT_OCD, "position": "yea"},
        {"roll_call_id": _SB512_RC, "ocd_person": _UNKNOWN_OCD, "position": "nay"}]
    assert parsed["skipped"] == {"sponsorships": 1, "positions": 1}
    # citation URLs are source-provided: state page first, openstates fallback
    assert parsed["bill_url"].startswith("https://wapp.capitol.tn.gov/")
    assert parsed["rc_urls"][_SB512_RC] == "https://wapp.capitol.tn.gov/votes/sb512-third-reading"


def test_openstates_votes_option_mapping_never_guesses():
    """Every mapped option lands in the vote_positions CHECK enum; an option
    outside the documented map (e.g. 'paired') is skipped and counted, never
    guessed into a side the member didn't take."""
    votes = [{"option": o, "voter_name": f"V{i}", "voter": {"id": f"ocd-person/{i}"}}
             for i, o in enumerate(
                 ["yes", "no", "abstain", "absent", "excused", "not voting", "paired"])]
    record = {"id": "ocd-bill/x", "identifier": "SB 1", "session": "114",
              "title": "T", "openstates_url": "https://openstates.org/x",
              "votes": [{"id": "ocd-vote/v1", "motion_text": "M", "start_date": "2025-01-01",
                         "result": "pass", "organization": {"classification": "upper"},
                         "counts": [], "sources": [], "votes": votes}]}
    parsed = _osv.parse_bill("tn", record)
    assert [p["position"] for p in parsed["positions"]] == \
        ["yea", "nay", "present", "not_voting", "not_voting", "not_voting"]
    assert parsed["skipped"]["positions"] == 1               # 'paired' skipped, counted
    rc = parsed["roll_calls"][0]
    assert rc["yea_count"] is None and rc["nay_count"] is None  # absent tallies stay NULL


def test_openstates_votes_schema_drift_halts():
    """A PRESENT record missing a required field is schema drift — parse_bill
    raises (and the transform lets it halt the run) rather than publishing a
    half-parsed state. Absent data is honest; drifted data is not."""
    good = json.loads(json.dumps(
        STATE_VOTES_TN["bills"]["ocd-bill/11112222-3333-4444-5555-666677778888"]))
    no_ident = json.loads(json.dumps(good))
    del no_ident["identifier"]
    with pytest.raises(_osv.SchemaDriftError, match="identifier"):
        _osv.parse_bill("tn", no_ident)
    no_motion = json.loads(json.dumps(good))
    del no_motion["votes"][0]["motion_text"]
    with pytest.raises(_osv.SchemaDriftError, match="motion_text"):
        _osv.parse_bill("tn", no_motion)
    no_result = json.loads(json.dumps(good))
    no_result["votes"][0]["result"] = None
    with pytest.raises(_osv.SchemaDriftError, match="result"):
        _osv.parse_bill("tn", no_result)


def test_openstates_votes_crawl_incremental_cursor_and_merge():
    """The since-cursor design: an incremental crawl passes the persisted cursor
    as updated_since and merges the delta into the prior snapshot by ocd-bill
    id; the next cursor is the crawl's own START minus a skew lap (so records
    that move mid-crawl are re-covered next night). A prior snapshot from a
    DIFFERENT biennium window is discarded — full recrawl."""
    calls = []

    class _Client:
        def bills(self, jurisdiction, created_since, updated_since=None):
            calls.append((jurisdiction, created_since, updated_since))
            yield {"id": "ocd-bill/new", "identifier": "SB 1", "session": "114"}

    now = datetime(2026, 7, 7, 6, 0, 0, tzinfo=timezone.utc)
    prior = {"created_since": "2025-01-01", "cursor": "2026-07-01T00:00:00+00:00",
             "bills": {"ocd-bill/old": {"id": "ocd-bill/old"}}}
    doc = _osv.crawl_state(_Client(), "tn", "2025-01-01", prior, now=now)
    assert calls[-1] == ("ocd-jurisdiction/country:us/state:tn/government",
                         "2025-01-01", "2026-07-01T00:00:00+00:00")
    assert set(doc["bills"]) == {"ocd-bill/old", "ocd-bill/new"}   # merged, not replaced
    assert doc["cursor"] == "2026-07-07T05:00:00+00:00"            # start minus skew lap
    assert doc["fetched"] == 1
    # New biennium window -> prior discarded, no updated_since (full recrawl).
    doc2 = _osv.crawl_state(_Client(), "tn", "2027-01-01", prior, now=now)
    assert calls[-1][2] is None
    assert set(doc2["bills"]) == {"ocd-bill/new"}


def test_state_votes_land_in_spine(slice_dirs):
    """Ingest round-trip: the landed tn.json fills bills/sponsorships/
    roll_calls (with verbatim tallies)/vote_positions, joined to persons by
    exact ocd-person id through the openstates crosswalk."""
    con = store.connect(str(slice_dirs / "wh.duckdb"))
    try:
        b = dict(con.execute(
            "SELECT bill_id, status FROM bills WHERE jurisdiction='tn'").fetchall())
        assert b == {"tn/114/sb-512": "passed_chamber", "tn/114/hb-7": "law"}
        sp = set(con.execute(
            """SELECT bill_id, person_id::VARCHAR, role FROM sponsorships
               WHERE bill_id LIKE 'tn/%'""").fetchall())
        pat, dana = _state_person_id(_PAT_OCD), _state_person_id(_DANA_OCD)
        assert sp == {("tn/114/sb-512", pat, "sponsor"),
                      ("tn/114/sb-512", dana, "cosponsor"),
                      ("tn/114/hb-7", dana, "sponsor")}
        tallies = con.execute(
            "SELECT yea_count, nay_count FROM roll_calls WHERE roll_call_id = ?",
            [_SB512_RC]).fetchone()
        assert tallies == (17, 14)
        vp = set(con.execute(
            """SELECT roll_call_id, person_id::VARCHAR, position FROM vote_positions
               WHERE roll_call_id NOT LIKE 'us/%'""").fetchall())
        assert vp == {(_SB512_RC, pat, "yea"),
                      ("tn/114/lower/eeee5555-5555-5555-5555-555555555555", dana, "nay")}
    finally:
        con.close()


def test_state_votes_unknown_person_quarantined_never_guessed(slice_dirs):
    """A vote cast by an ocd-person absent from the crosswalk (mid-session
    turnover) is quarantined with its contexts — one row per distinct unknown
    id, never joined by name, never silently lost."""
    con = store.connect(str(slice_dirs / "wh.duckdb"))
    try:
        rows = con.execute(
            "SELECT raw_payload FROM quarantine_identities WHERE source='openstates'").fetchall()
        assert len(rows) == 1
        payload = json.loads(rows[0][0])
        assert payload["id_value"] == _UNKNOWN_OCD
        assert payload["states"] == ["tn"]
        assert payload["vote_positions"] == 1 and payload["sponsorships"] == 0
        # ...and no vote_positions row was invented for the unknown person.
        n = con.execute(
            """SELECT count(*) FROM vote_positions vp
               WHERE vp.roll_call_id NOT LIKE 'us/%'""").fetchone()[0]
        assert n == 2                                        # Pat + Dana only
    finally:
        con.close()


def test_state_dossier_publishes_legislative_section(slice_dirs):
    """WO-17 acceptance: a covered state's legislator publishes the SAME
    legislative section shape as a federal member — counts, recent_bills,
    key_votes (yea/nay tallies + official source URL), party_agreement_pct,
    committees [] — under openstates provenance, so the frontend Record tab
    (which gates purely on `legislative` existing) lights up unchanged."""
    pat = _dossier_named(slice_dirs, "Pat Upper")
    dossiers.validate(pat)
    assert "ideology" not in pat                             # federal-only, still
    leg = pat["legislative"]
    assert set(leg) == {"counts", "recent_bills", "key_votes", "party_agreement_pct",
                        "committees", "provenance", "votes_provenance",
                        "committees_provenance"}              # federal-identical shape
    assert leg["counts"] == {"sponsored": 1, "cosponsored": 0, "became_law": 0}
    assert leg["committees"] == [] and leg["committees_provenance"] is None
    rb = leg["recent_bills"][0]
    assert rb["bill_id"] == "tn/114/sb-512" and rb["status"] == "passed_chamber"
    assert rb["url"].startswith("https://wapp.capitol.tn.gov/")   # source-provided link
    [kv] = leg["key_votes"]
    assert kv["roll_call_id"] == _SB512_RC and kv["position"] == "yea"
    assert (kv["yea_count"], kv["nay_count"]) == (17, 14)     # tallies, verbatim
    assert kv["url"] == "https://wapp.capitol.tn.gov/votes/sb512-third-reading"
    assert kv["bill_title"] == "Education Savings Act"
    assert kv["bill_url"].startswith("https://wapp.capitol.tn.gov/")
    assert kv["policy_areas"] == ["Education"]
    assert kv["description"] is None                          # honest absence (state)
    # 1 decided vote < MIN_AGREEMENT_VOTES -> agreement omitted, not faked; the
    # votes envelope then anchors key-vote selection (same rule as federal).
    assert leg["party_agreement_pct"] is None
    assert leg["provenance"]["source"] == "openstates"
    assert leg["provenance"]["methodology_id"] is None        # verbatim counts
    assert leg["votes_provenance"]["source"] == "openstates"
    assert leg["votes_provenance"]["methodology_id"] == "key-votes"

    dana = _dossier_named(slice_dirs, "Dana Lower")
    dleg = dana["legislative"]
    # cosponsored comes from the WAREHOUSED cosponsor rows for states (federal
    # reads its per-member raw count instead); became_law counts HB 7.
    assert dleg["counts"] == {"sponsored": 1, "cosponsored": 1, "became_law": 1}
    [dkv] = dleg["key_votes"]
    assert dkv["position"] == "nay"
    # HB 7 shipped no state source URL -> openstates.org bill page fallback.
    assert dleg["recent_bills"][0]["url"] == "https://openstates.org/tn/bills/114/HB7/"


def test_state_dossier_honest_absent_without_votes_snapshot(slice_dirs):
    """WA landed people but NO votes snapshot: Wanda keeps an identity-only
    dossier — no legislative section, no zero counts fabricated from absence."""
    wanda = _dossier_named(slice_dirs, "Wanda West")
    dossiers.validate(wanda)
    assert "legislative" not in wanda and "ideology" not in wanda


def test_state_votes_coverage_counts(slice_dirs):
    """coverage.json carries the state-votes counters (live verification hooks
    for the pilot) and the openstates family stays ONE source row within SLA."""
    coverage = json.loads((slice_dirs / "data" / "coverage.json").read_text())
    c = coverage["counts"]
    assert c["state_votes_states"] == 1
    assert c["state_bills"] == 2
    assert c["state_roll_calls"] == 2
    assert c["state_vote_positions"] == 2
    assert coverage["sources"]["openstates"]["within_sla"] is True


def test_state_nodes_stay_edge_free_in_graph(slice_dirs):
    """State-chamber graph EDGES are WO-18's scope: with state votes now
    warehoused, state members must still emit valid, edge-free neighborhoods
    (their graph_ref resolves; nothing new is computed for them yet)."""
    from beholden_etl.build import graph
    pat_id = _state_person_id(_PAT_OCD)
    doc = json.loads((slice_dirs / "data" / "graph" / "neighborhood" / f"{pat_id}.json").read_text())
    graph.validate(doc)
    assert doc["edges"] == []


def test_fetch_openstates_votes_skipped_without_key(tmp_path, monkeypatch):
    """Without OPENSTATES_KEY the votes crawl is skipped entirely — every pilot
    state stays honest-absent (identity-only dossiers) and the people CSVs
    still land. No fabricated zero, no run failure."""
    from beholden_etl.jobs import fetch as _f
    from beholden_etl.sources import openstates as _os
    monkeypatch.delenv("OPENSTATES_KEY", raising=False)
    monkeypatch.setattr(_os, "STATE_SLUGS", ["tn"])
    monkeypatch.setattr(_os, "fetch_people_csv", lambda s: "id,name\nx,Y\n")
    raw = tmp_path / "raw"
    meta = _f.fetch_openstates(raw, prior={})
    assert meta["count"] == 1                        # people landed regardless
    assert "votes_states" not in meta                # votes honestly absent
    assert not (raw / "openstates" / "votes").exists()


def test_fetch_openstates_votes_crawls_and_per_state_failure_skips(tmp_path, monkeypatch):
    """With the key present, the votes crawl fans the pilot states out on one
    shared client and lands raw/openstates/votes/{state}.json per state. A
    per-state failure skips THAT state only (honest-absent, prior snapshot
    untouched) while the rest land — the run never sinks on one state."""
    from beholden_etl.jobs import fetch as _f
    from beholden_etl.sources import openstates as _os
    from beholden_etl.sources import openstates_votes as osv_mod

    monkeypatch.setenv("OPENSTATES_KEY", "test-key")
    monkeypatch.setattr(_f, "STATE_VOTES_SLUGS", ["tn", "wa"])
    monkeypatch.setattr(_os, "STATE_SLUGS", ["tn", "wa"])
    monkeypatch.setattr(_os, "fetch_people_csv", lambda s: "id,name\nx,Y\n")

    record = STATE_VOTES_TN["bills"]["ocd-bill/11112222-3333-4444-5555-666677778888"]

    class _StubClient:
        def __init__(self, api_key=None):
            pass

        def bills(self, jurisdiction, created_since, updated_since=None):
            if "wa" in jurisdiction:
                raise RuntimeError("simulated per-state failure")
            yield record

    monkeypatch.setattr(osv_mod, "OpenStatesVotesClient", _StubClient)

    raw = tmp_path / "raw"
    meta = _f.fetch_openstates(raw, prior={})
    assert meta["votes_states"] == ["tn"]            # WA skipped, TN landed
    assert meta["votes_bills"] == 1 and meta["votes_fetched"] == 1
    doc = json.loads((raw / "openstates" / "votes" / "tn.json").read_text())
    assert doc["state"] == "tn" and record["id"] in doc["bills"]
    assert doc["created_since"] == "2025-01-01"      # current-biennium bound
    assert not (raw / "openstates" / "votes" / "wa.json").exists()
