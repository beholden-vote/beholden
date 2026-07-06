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
LEGS = [
    {"id": {"bioguide": "R000001", "icpsr": "11", "fec": ["H8TN06001"]},
     "name": {"first": "Jane", "last": "Rep", "official_full": "Jane Rep"},
     "bio": {"birthday": "1970-05-01"},
     "terms": [{"type": "rep", "start": "2025-01-03", "end": "2027-01-03", "state": "TN", "district": 6, "party": "Republican"}]},
    {"id": {"bioguide": "A000002", "icpsr": "22"}, "name": {"official_full": "Al Large"},
     "terms": [{"type": "rep", "start": "2025-01-03", "end": "2027-01-03", "state": "AK", "district": 0, "party": "Democrat"}]},
    {"id": {"bioguide": "S000003", "icpsr": "33"}, "name": {"official_full": "Sam Sen"},
     "terms": [{"type": "sen", "start": "2021-01-03", "end": "2027-01-03", "state": "TN", "party": "Republican", "class": 1}]},
]
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
}}

# A House PTR filing that name-matches Jane Rep (family "Rep", first "Jane").
HOUSE_PTR = [{"last": "Rep", "first": "Jane", "suffix": "", "state_dst": "TN06",
              "filed_on": "2025-05-01", "doc_id": "20099999", "year": 2025}]

# Two TN state legislators — one per chamber — to light up sldu/sldl (E4).
OPENSTATES_TN_CSV = (
    "id,name,current_party,current_district,current_chamber,given_name,family_name,image,birth_date,sources\n"
    "ocd-person/aaaa1111-1111-1111-1111-111111111111,Pat Upper,Republican,5,upper,Pat,Upper,https://img/pat.jpg,1975-03-02,https://capitol.tn.gov/pat\n"
    "ocd-person/bbbb2222-2222-2222-2222-222222222222,Dana Lower,Democratic,10,lower,Dana,Lower,,1982-07-11,https://capitol.tn.gov/dana\n"
)

# Jane's FEC candidate totals (dollars, as the API returns them -> stored cents).
FEC_TOTALS = {"H8TN06001": {"candidate_id": "H8TN06001", "cycle": 2026, "totals": {
    "receipts": 1234567.89, "disbursements": 900000.0,
    "last_cash_on_hand_end_period": 334567.89, "coverage_end_date": "2026-06-30T00:00:00"}}}

# Jane's FEC by_employer rollups (WO-3), as the API returns them: employers
# uppercased, totals in dollars, already -total-sorted. 12 rows to prove the
# dossier caps at 10; blank / "NOT EMPLOYED" / "RETIRED" are legitimate FEC
# categories kept verbatim (never editorialized or filtered).
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
        {"employer": "ETA HOLDINGS", "total": 5000.0, "count": 2},   # rank 11 -> capped
        {"employer": "THETA VENTURES", "total": 4000.0, "count": 1}, # rank 12 -> capped
    ]}}


# --- roll-call votes (WO-1) -------------------------------------------------
# 3 House roll calls for the 119th. RC1 links to Jane's law HR100 (bill_number
# "HR100" -> us/119/hr/100). RC2 is procedural (blank bill_number -> NULL FK).
# RC3 is a lopsided vote. Al (icpsr 22) is the other House member; Sam (icpsr 33,
# Senate) and the President (blank icpsr) never appear in these House rows.
# Tallies drive the closeness score: RC2 (11 v 10) is the tightest, RC1 (12 v 9)
# next, RC3 (20 v 1) least — so key-vote order should be RC2, RC1, RC3.
VOTEVIEW_ROLLCALLS = (
    "congress,chamber,rollnumber,date,session,clerk_rollnumber,yea_count,nay_count,"
    "bill_number,vote_result,vote_desc,vote_question\n"
    "119,House,1,2025-02-01,1,10,12,9,HR100,Passed,Passage of HR100,On Passage\n"
    "119,House,2,2025-03-01,1,11,11,10,,Agreed to,A procedural motion,On the Motion\n"
    "119,House,3,2025-04-01,1,12,20,1,,Passed,A lopsided vote,On Agreeing\n"
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
# less rows; every committee carries one.
COMMITTEES = [
    {"type": "house", "name": "House Committee on Agriculture", "thomas_id": "HSAG",
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
    (raw / "house_clerk").mkdir(parents=True)
    (raw / "house_clerk" / "ptr.json").write_text(json.dumps(HOUSE_PTR))
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
    # 3 federal + 2 state legislators, all with names.
    assert len(people) == 5
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
    assert len(files) == 5                          # 3 federal + 2 state legislators
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
    assert n == 12                                             # all 12 fixture rows land
    top = con.execute(
        """SELECT contributor_name, total_cents FROM top_contributors
           ORDER BY rank LIMIT 1""").fetchone()
    assert top == ("N/A", 5000000)                            # rank 1, $50,000 -> cents
    con.close()


def test_dossier_top_contributors_capped_and_provenanced(slice_dirs):
    """Jane's money.campaign_finance carries top_contributors[0..9] (capped at 10)
    with name + total_cents, under the same FEC envelope. FEC categories like
    N/A / RETIRED / NOT EMPLOYED are surfaced verbatim, not filtered."""
    jane = _dossier_named(slice_dirs, "Jane Rep")
    cf = jane["money"]["campaign_finance"]
    tc = cf["top_contributors"]
    assert len(tc) == 10                                       # 12 rollups capped to 10
    assert tc[0] == {"name": "N/A", "total_cents": 5000000}
    assert [c["name"] for c in tc[:4]] == ["N/A", "SELF-EMPLOYED", "RETIRED", "NOT EMPLOYED"]
    assert set(tc[0]) == {"name", "total_cents"}              # exactly the contract shape
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
    """OpenStates people populate the sldu/sldl feeds + identity-only dossiers,
    keyed on the OCD ids the tile stamper produces. Ideology/legislative are
    omitted (not faked), and the dossier still validates."""
    sldu = json.loads((slice_dirs / "data" / "stylefeeds" / "sldu.json").read_text())
    sldl = json.loads((slice_dirs / "data" / "stylefeeds" / "sldl.json").read_text())
    assert sldu["ocd-division/country:us/state:tn/sldu:5"]["party"] == "R"
    assert sldl["ocd-division/country:us/state:tn/sldl:10"]["party"] == "D"

    pins = json.loads((slice_dirs / "data" / "pins" / "sldu.json").read_text())
    pat = next(p for p in pins if p["full_name"] == "Pat Upper")
    assert pat["office"] == "TN State Senate · District 5"
    assert pat["photo_url"] == "https://img/pat.jpg"

    doss = _dossier_named(slice_dirs, "Pat Upper")
    dossiers.validate(doss)                     # identity-only is contract-valid
    assert "ideology" not in doss and "legislative" not in doss
    assert doss["identity"]["provenance"]["source"] == "openstates"
    assert doss["identity"]["office"]["chamber"] == "upper"


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
    cast_code 0 rows are dropped without breaking FK integrity."""
    con = store.connect(str(slice_dirs / "wh.duckdb"))
    assert con.execute("SELECT count(*) FROM roll_calls").fetchone()[0] == 3
    # 6 valid casts (Jane x3, Al x3); icpsr 99 + cast_code 0 rows are excluded.
    assert con.execute("SELECT count(*) FROM vote_positions").fetchone()[0] == 6
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
    assert ag["subcommittees"] == [{"name": "Forestry and Horticulture", "role": "chair"}]
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
    assert ag["subcommittees"] == [{"name": "Livestock, Dairy, and Poultry", "role": "member"}]


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
    assert len(files) == 5                                   # one per current holder
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
    assert len(jane["money"]["campaign_finance"]["top_contributors"]) == 10
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
                     "fec", "openstates", "house_clerk", "wa_pdc"}
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
