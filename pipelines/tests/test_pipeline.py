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


@pytest.fixture
def slice_dirs(tmp_path):
    raw = tmp_path / "raw"
    (raw / "unitedstates_legislators").mkdir(parents=True)
    (raw / "voteview").mkdir(parents=True)
    (raw / "congress.gov" / "legislation").mkdir(parents=True)
    (raw / "unitedstates_legislators" / "legislators-current.json").write_text(json.dumps(LEGS))
    (raw / "voteview" / "HS119_members.csv").write_text(VOTEVIEW)
    (raw / "voteview" / "HS119_rollcalls.csv").write_text(VOTEVIEW_ROLLCALLS)
    (raw / "voteview" / "HS119_votes.csv").write_text(VOTEVIEW_VOTES)
    (raw / "fec" / "totals").mkdir(parents=True)
    for bio, rec in LEGISLATION.items():
        (raw / "congress.gov" / "legislation" / f"{bio}.json").write_text(json.dumps(rec))
    for cand, rec in FEC_TOTALS.items():
        (raw / "fec" / "totals" / f"{cand}.json").write_text(json.dumps(rec))
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
