"""WO-23a: the full federal voting record - votes/, rollcalls/, bills/
(DATA-CONTRACTS 8.3). Runs offline on the shared synthetic slice."""
from __future__ import annotations

import json
import re

import httpx
import pytest

from beholden_etl import store
from beholden_etl.build import dossiers, key_votes, votes
from beholden_etl.jobs import build, fetch, transform
from beholden_etl.sources import congress_gov

KEY_RE = re.compile(r"[a-z0-9/._-]+")
PREFIXES = ("votes", "rollcalls", "bills")

# --- the slice, extended: a bill from a sponsor who has left, a roll call held
# before a member took office, a vote someone sat out, a bill never fetched ----
# Roll call 4 is on S. 7 and predates Al (cast code 0 = "not a member"); roll
# call 5 is on H.R. 999, whose congress.gov record never landed, and Jane did
# not vote on it (cast code 9).
ROLLCALLS_MORE = (
    "119,House,4,2025-01-10,1,13,15,6,S7,Passed,A bill from the other chamber,On Passage\n"
    "119,House,5,2025-06-01,1,14,10,11,HR999,Failed,,On Passage\n")
VOTES_MORE = ("119,House,4,11,1,99.0\n" "119,House,4,22,0,99.0\n"
              "119,House,5,11,9,99.0\n" "119,House,5,22,1,99.0\n")
# One landed record, in the shape congress.gov serves (bill-detail and
# cosponsors responses verified live 2026-10-03). The sponsor and one cosponsor
# are not in office; Sam cosponsored and then withdrew. Active cosponsors by
# party are D 3, I 1, R 2, chosen so alphabetical (D, I, R) differs from largest
# first (D, R, I) and from smallest first (I, R, D): the order cannot pass by luck.
BILL_S7 = {
    "bill_id": "us/119/s/7", "fetched_at": "2026-10-01T06:00:00+00:00",
    "bill": {
        "congress": 119, "type": "S", "number": "7", "title": "A Senate Bill",
        "introducedDate": "2025-01-09", "policyArea": {"name": "Taxation"},
        "latestAction": {"actionDate": "2025-01-10", "text": "Passed House."},
        "updateDate": "2026-09-19T23:26:15Z",
        "sponsors": [{"bioguideId": "D000009", "firstName": "Dee", "lastName": "Parted",
                      "fullName": "Sen. Parted, Dee [D-OH]", "party": "D", "state": "OH"}],
        "cosponsors": {"count": 6, "countIncludingWithdrawnCosponsors": 7}},
    "cosponsors": [
        {"bioguideId": "R000001", "firstName": "Jane", "lastName": "Rep", "party": "R",
         "state": "TN", "isOriginalCosponsor": True, "sponsorshipDate": "2025-01-09"},
        {"bioguideId": "S000003", "firstName": "Sam", "lastName": "Sen", "party": "R",
         "state": "TN", "isOriginalCosponsor": True, "sponsorshipDate": "2025-01-09",
         "sponsorshipWithdrawnDate": "2025-03-03"},
        {"bioguideId": "G000008", "firstName": "Gone", "lastName": "Away", "party": "R",
         "state": "TX", "isOriginalCosponsor": False, "sponsorshipDate": "2025-02-02"},
        {"bioguideId": "A000002", "firstName": "Al", "lastName": "Large", "party": "D",
         "state": "AK", "isOriginalCosponsor": False, "sponsorshipDate": "2025-02-02"},
        {"bioguideId": "D000020", "firstName": "Dan", "lastName": "Delta", "party": "D",
         "state": "CA", "isOriginalCosponsor": False, "sponsorshipDate": "2025-02-03"},
        {"bioguideId": "D000021", "firstName": "Dora", "lastName": "Dell", "party": "D",
         "state": "NY", "isOriginalCosponsor": False, "sponsorshipDate": "2025-02-03"},
        {"bioguideId": "I000030", "firstName": "Ivy", "lastName": "Indy", "party": "I",
         "state": "VT", "isOriginalCosponsor": False, "sponsorshipDate": "2025-02-04"}]}
BILL_HR100 = {     # no `cosponsors` key at all: how the API says "none"
    "bill_id": "us/119/hr/100", "fetched_at": "2026-10-01T06:00:00+00:00",
    "bill": {"congress": 119, "type": "HR", "number": "100", "title": "A Bill To Do X",
             "introducedDate": "2025-02-01", "policyArea": {"name": "Health"},
             "latestAction": {"actionDate": "2025-06-01", "text": "Became Public Law No: 119-1."},
             "sponsors": [{"bioguideId": "R000001", "firstName": "Jane", "lastName": "Rep",
                           "party": "R", "state": "TN"}]},
    "cosponsors": []}


def _extend(raw):
    for name, more in (("rollcalls", ROLLCALLS_MORE), ("votes", VOTES_MORE)):
        with (raw / "voteview" / f"HS119_{name}.csv").open("a", encoding="utf-8") as f:
            f.write(more)


@pytest.fixture
def bill_dirs(slice_dirs):
    """The shared slice, re-run with the extra roll calls and S. 7 landed."""
    raw = slice_dirs / "raw"
    _extend(raw)
    path = raw / congress_gov.bill_snapshot_path("us/119/s/7")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(BILL_S7), encoding="utf-8")
    db = str(slice_dirs / "wh.duckdb")
    transform.run(raw_dir=raw, db_path=db)
    build.run(db_path=db, out_dir=slice_dirs / "data", raw_dir=raw)
    return slice_dirs


def _docs(root, prefix):
    """{object key without .json: document} for one served prefix."""
    base = root / "data" / prefix
    return {f.relative_to(base).as_posix()[:-len(".json")]:
            json.loads(f.read_text(encoding="utf-8"))
            for f in sorted(base.rglob("*.json"))}


def _record(root, name):
    people = json.loads((root / "data" / "search" / "people.json").read_text(encoding="utf-8"))
    pid = next(p["person_id"] for p in people if p["full_name"] == name)
    return _docs(root, "votes")[pid]


# --- votes/{person_id}.json --------------------------------------------------
def test_summary_arithmetic_holds_for_every_member(slice_dirs):
    """The four positions partition the record, and every party-decided vote is
    either with or against the party - for every member, including the one with
    no positions at all, whose file still carries every field."""
    records = _docs(slice_dirs, "votes")
    assert len(records) == 3                     # Jane, Al, Sam: every sitting member
    for pid, doc in records.items():
        s = doc["summary"]
        assert doc["person_id"] == pid and doc["scope"] == "119th Congress"
        assert s["yea"] + s["nay"] + s["present"] + s["not_voting"] == s["total"] == len(doc["votes"])
        assert s["with_party"] + s["against_party"] == s["party_decided"] <= s["yea"] + s["nay"]
    # Symmetric by construction: identical fields for every member and every vote.
    assert len({tuple(d) for d in records.values()}) == 1
    assert len({tuple(d["summary"]) for d in records.values()}) == 1
    assert len({tuple(v) for d in records.values() for v in d["votes"]}) == 1
    sam = _record(slice_dirs, "Sam Sen")         # a senator; the slice has no Senate votes
    assert sam["summary"]["total"] == 0 and sam["votes"] == []


def test_summary_counts_match_the_published_agreement_formula():
    """with_party / party_decided IS the dossier party_agreement_pct - one
    formula, not a second measure. 30 decided votes: 24 with the party, 6
    against; plus a not-voting row and a row where the party split evenly, which
    count toward neither."""
    majority = {f"rc{i}\tR": "yea" for i in range(31)}
    rows = ([{"roll_call_id": f"rc{i}", "position": "yea"} for i in range(24)]
            + [{"roll_call_id": f"rc{i}", "position": "nay"} for i in range(24, 30)]
            + [{"roll_call_id": "rc30", "position": "not_voting"},
               {"roll_call_id": "tied", "position": "yea"}])
    for r in rows:
        r["party_position"] = majority.get(r["roll_call_id"] + "\tR")
    s = votes.summarize(rows)
    assert (s["total"], s["yea"], s["nay"], s["not_voting"]) == (32, 25, 6, 1)
    assert (s["party_decided"], s["with_party"], s["against_party"]) == (30, 24, 6)
    assert key_votes.agreement_pct(rows, "R", majority) == round(
        100 * s["with_party"] / s["party_decided"], 1)


def test_votes_not_on_a_bill_stay_in_the_record(slice_dirs):
    """A procedural vote has no bill. Dropping it would misstate attendance, so
    it publishes with bill_id null and the question the source gives."""
    jane = _record(slice_dirs, "Jane Rep")
    assert [v["roll_call_id"] for v in jane["votes"]] == [
        "us/119/house/3", "us/119/house/2", "us/119/house/1"]          # newest first
    motion = jane["votes"][1]
    assert (motion["bill_id"], motion["bill_title"], motion["policy_area"]) == (None, None, None)
    assert motion["question"] == "On the Motion" and motion["position"] == "yea"
    assert motion["held_at"] == "2025-03-01"     # the date, whatever zone the builder is in
    passage = jane["votes"][2]
    assert (passage["bill_id"], passage["bill_title"], passage["policy_area"]) == (
        "us/119/hr/100", "A Bill To Do X", "Health")
    assert (passage["result"], passage["yea_count"], passage["nay_count"]) == ("Passed", 12, 9)


# --- rollcalls/{roll_call_id}.json -------------------------------------------
def test_roll_call_lists_positions_without_passing_them_off_as_the_roll(slice_dirs):
    """totals is the official tally; positions and by_party cover only members in
    office today and are NOT scaled to match it. Parties are alphabetical, never
    by size; positions are ordered by family name."""
    rcs = _docs(slice_dirs, "rollcalls")
    assert set(rcs) == {"us/119/house/1", "us/119/house/2", "us/119/house/3"}
    rc = rcs["us/119/house/1"]
    assert rc["totals"] == {"yea": 12, "nay": 9}                       # the chamber: 21 votes
    assert rc["positions_cover"] == "current_members" and len(rc["positions"]) == 2
    assert [p["party"] for p in rc["by_party"]] == ["D", "R"]
    assert rc["by_party"][0] == {"party": "D", "yea": 0, "nay": 1, "present": 0, "not_voting": 0}
    assert [p["name"] for p in rc["positions"]] == ["Al Large", "Jane Rep"]
    assert rc["positions"][1] == {
        "person_id": rc["positions"][1]["person_id"], "name": "Jane Rep", "party": "R",
        "state": "TN", "ocd_id": "ocd-division/country:us/state:tn/cd:6", "position": "yea"}
    assert (rc["chamber"], rc["held_at"], rc["question"]) == ("house", "2025-02-01", "On Passage")
    assert rc["description"] == "Passage of HR100"
    assert rc["url"] == "https://clerk.house.gov/Votes/202510"
    assert rcs["us/119/house/3"]["description"] is None                # blank in the source
    for doc in rcs.values():
        assert [p["party"] for p in doc["by_party"]] == sorted(p["party"] for p in doc["by_party"])


# --- cross-cutting -----------------------------------------------------------
def test_every_emitted_id_is_a_servable_key(slice_dirs, tmp_path):
    """Ids are object keys verbatim; one character outside [a-z0-9/._-] and the
    object is unreachable. Checked on what was written AND enforced on write."""
    for prefix in PREFIXES:
        docs = _docs(slice_dirs, prefix)
        assert docs
        for key, doc in docs.items():
            assert KEY_RE.fullmatch(key), key
            ids = [doc.get("person_id"), doc.get("roll_call_id"), doc.get("bill_id")]
            ids += [v["roll_call_id"] for v in doc.get("votes", [])]
            ids += [p["person_id"] for p in doc.get("positions", [])]
            assert all(KEY_RE.fullmatch(i) for i in ids if i is not None), key
    ok = {"provenance": _docs(slice_dirs, "bills")["index"]["provenance"]}
    with pytest.raises(ValueError, match="servable object key"):
        votes._write(tmp_path, "rollcalls", "us/119/House/1 A", ok)
    assert not (tmp_path / "rollcalls").exists()


def test_every_document_carries_a_valid_envelope(slice_dirs):
    """No provenance, no publish - and the computed party fields point at the
    methodology anchor that documents their formula."""
    for prefix in PREFIXES:
        for key, doc in _docs(slice_dirs, prefix).items():
            dossiers._check_provenance({"person_id": key, "doc": doc}, "doc")
            assert doc["schema_version"] == "1.0" and doc["generated_at"]
    for doc in _docs(slice_dirs, "votes").values():
        assert doc["provenance"]["source"] == "voteview"
        assert doc["provenance"]["methodology_id"] == build.METHODOLOGY_AGREEMENT == "co-voting"
    with pytest.raises(dossiers.ProvenanceError):                       # the validator bites
        votes._write(slice_dirs, "votes", "x", {"provenance": {"source": "voteview"}})


def _unstamped(root):
    out = {}
    for prefix in PREFIXES:
        for key, doc in _docs(root, prefix).items():
            doc.pop("generated_at")
            for stamp in ("retrieved_at", "pipeline_version"):
                doc["provenance"].pop(stamp)
            out[f"{prefix}/{key}"] = json.dumps(doc, separators=(",", ":"))
    return out


def test_two_builds_differ_only_in_their_stamps(bill_dirs, tmp_path_factory):
    """Stable ordering everywhere, so a recess week rewrites nothing. On the
    extended slice, so a bill page (cosponsors, parties, roll calls) is in it."""
    first = _unstamped(bill_dirs)
    again = tmp_path_factory.mktemp("again")
    build.run(db_path=str(bill_dirs / "wh.duckdb"), out_dir=again / "data",
              raw_dir=bill_dirs / "raw")
    assert _unstamped(again) == first
    assert len(first) == 3 + 5 + 2                  # votes + rollcalls + (bill + index)


def test_counts_reach_coverage_and_crawlers_are_told(slice_dirs):
    counts = json.loads((slice_dirs / "data" / "coverage.json").read_text())["counts"]
    assert (counts["votes"], counts["rollcalls"], counts["bills"]) == (3, 3, 0)
    robots = (slice_dirs / "data" / "robots.txt").read_text(encoding="utf-8")
    assert robots.count("User-agent:") == 1                             # still ONE group
    for path in ("/votes/", "/rollcalls/", "/bills/"):
        assert f"Disallow: {path}\n" in robots


def test_a_bill_whose_record_never_landed_has_no_page(slice_dirs):
    """H.R. 100 is in the warehouse (a sitting member sponsored it) and a roll
    call links to it, but its congress.gov bill record was never fetched. It is
    absent - not published from the fields we happen to hold - and the index
    says so by not listing it."""
    bills = _docs(slice_dirs, "bills")
    assert set(bills) == {"index"} and bills["index"]["bills"] == []


# --- eligibility, and the bill page ------------------------------------------
def test_a_roll_call_before_a_member_took_office_is_not_in_their_record(bill_dirs):
    """Voteview separates "not a member" (0) from "not voting" (9). Only the
    second is the member's to answer for: it is counted, the first is absent."""
    al, jane = _record(bill_dirs, "Al Large"), _record(bill_dirs, "Jane Rep")
    assert "us/119/house/4" not in [v["roll_call_id"] for v in al["votes"]]
    assert (al["summary"]["total"], al["summary"]["not_voting"]) == (4, 0)
    assert (jane["summary"]["total"], jane["summary"]["not_voting"]) == (5, 1)
    assert jane["votes"][0]["roll_call_id"] == "us/119/house/5"
    assert jane["votes"][0]["position"] == "not_voting"
    rc = _docs(bill_dirs, "rollcalls")["us/119/house/4"]
    assert [p["name"] for p in rc["positions"]] == ["Jane Rep"]
    assert [p["party"] for p in rc["by_party"]] == ["R"]
    assert rc["totals"] == {"yea": 15, "nay": 6}


def test_a_vote_on_a_departed_sponsors_bill_now_has_its_title_and_topic(bill_dirs):
    """The gap this closes: `bills` held only bills a SITTING member sponsored,
    so a roll call on anyone else's bill linked to nothing."""
    vote = _record(bill_dirs, "Jane Rep")["votes"][-1]                   # oldest: roll call 4
    assert (vote["roll_call_id"], vote["bill_id"]) == ("us/119/house/4", "us/119/s/7")
    assert (vote["bill_title"], vote["policy_area"]) == ("A Senate Bill", "Taxation")
    # H.R. 999 was never fetched, so the transform has no bill to link: the vote
    # is kept, on no bill, rather than given an invented one.
    unfetched = _docs(bill_dirs, "rollcalls")["us/119/house/5"]
    assert (unfetched["bill_id"], unfetched["bill_title"]) == (None, None)


def test_bill_page_names_departed_legislators_without_linking_them(bill_dirs):
    """A sponsor or cosponsor who has left publishes by name with person_id
    null. A person_id is linked by bioguide id only - never by name."""
    bills = _docs(bill_dirs, "bills")
    assert set(bills) == {"index", "us/119/s/7"}
    bill = bills["us/119/s/7"]
    assert (bill["number"], bill["title"], bill["policy_area"]) == ("S. 7", "A Senate Bill", "Taxation")
    assert (bill["introduced_on"], bill["status"]) == ("2025-01-09", "passed_chamber")
    assert bill["url"] == "https://www.congress.gov/bill/119th-congress/senate-bill/7"
    assert bill["sponsor"] == {"person_id": None, "name": "Dee Parted", "party": "D", "state": "OH"}

    co = bill["cosponsors"]
    assert co["total"] == 6 == len(co["members"])                       # Sam withdrew
    # Alphabetical by party code - not largest first (D, R, I), not smallest first.
    assert co["by_party"] == [{"party": "D", "count": 3}, {"party": "I", "count": 1},
                              {"party": "R", "count": 2}]
    assert [m["name"] for m in co["members"]] == [          # by family name
        "Gone Away", "Dora Dell", "Dan Delta", "Ivy Indy", "Al Large", "Jane Rep"]
    assert co["members"][0] == {"person_id": None, "name": "Gone Away", "party": "R", "state": "TX"}
    people = {p["full_name"]: p["person_id"] for p in json.loads(
        (bill_dirs / "data" / "search" / "people.json").read_text(encoding="utf-8"))}
    assert [m["person_id"] for m in co["members"]] == [
        None, None, None, None, people["Al Large"], people["Jane Rep"]]
    assert len({tuple(m) for m in co["members"]} | {tuple(bill["sponsor"])}) == 1   # same fields

    assert bill["roll_calls"] == [{"roll_call_id": "us/119/house/4", "held_at": "2025-01-10",
                                   "question": "On Passage", "result": "Passed",
                                   "yea_count": 15, "nay_count": 6}]
    assert bill["provenance"]["source"] == "congress.gov"
    assert bill["provenance"]["source_url"] == bill["url"]
    assert bills["index"]["bills"] == [{
        "bill_id": "us/119/s/7", "number": "S. 7", "title": "A Senate Bill",
        "policy_area": "Taxation", "last_vote_at": "2025-01-10"}]
    counts = json.loads((bill_dirs / "data" / "coverage.json").read_text())["counts"]
    assert (counts["votes"], counts["rollcalls"], counts["bills"]) == (3, 5, 1)


def test_cosponsors_reach_the_warehouse_by_bioguide_only(bill_dirs):
    """The federal `cosponsor` role is finally filled - for people the spine
    knows. A cosponsor with no persons row gets no sponsorships row; nobody is
    resolved by name. The dossier's own cosponsored count is untouched."""
    con = store.connect(str(bill_dirs / "wh.duckdb"))
    try:
        rows = con.execute(
            """SELECT p.full_name, s.is_original, s.sponsored_on::VARCHAR, s.withdrawn_on::VARCHAR
               FROM sponsorships s JOIN persons p USING(person_id)
               WHERE s.bill_id = 'us/119/s/7' AND s.role = 'cosponsor' ORDER BY 1""").fetchall()
        linked = dict(con.execute(
            "SELECT roll_call_id, bill_id FROM roll_calls WHERE roll_call_id LIKE 'us/119/%'").fetchall())
    finally:
        con.close()
    assert rows == [("Al Large", False, "2025-02-02", None),
                    ("Jane Rep", True, "2025-01-09", None),
                    ("Sam Sen", True, "2025-01-09", "2025-03-03")]
    assert linked["us/119/house/4"] == "us/119/s/7" and linked["us/119/house/5"] is None
    jane = next(json.loads(f.read_text()) for f in (bill_dirs / "data" / "dossiers").glob("*.json")
                if json.loads(f.read_text())["identity"]["full_name"] == "Jane Rep")
    assert jane["legislative"]["counts"] == {"sponsored": 2, "cosponsored": 42, "became_law": 1}


# --- fetch: resumable, paced by the shared client, one bill cannot sink a run --
class _Bills:
    """Offline stand-in for the congress.gov client: serves landed-shape records
    and records every call, so a test can assert what was NOT fetched."""

    def __init__(self, records, *, updated=(), failing=()):
        self.records = {r["bill_id"]: r for r in records}
        self.updated, self.failing, self.calls = list(updated), set(failing), []

    def _serve(self, kind, congress, bill_type, number):
        bill_id = f"us/{congress}/{bill_type}/{number}"
        self.calls.append((kind, bill_id))
        if bill_id in self.failing or bill_id not in self.records:
            raise TimeoutError(f"simulated: {bill_id}")
        return self.records[bill_id]

    def bill_detail(self, congress, bill_type, number):
        return self._serve("detail", congress, bill_type, number)["bill"]

    def bill_cosponsors(self, congress, bill_type, number):
        return self._serve("cosponsors", congress, bill_type, number)["cosponsors"]

    def bills_updated_since(self, congress, since):
        self.calls.append(("sweep", since))
        return iter(self.updated)


def _lake(tmp_path):
    """A lake holding only the roll-call table: H.R. 100, S. 7, H.R. 999, a
    Senate nomination and a vote on no measure at all."""
    raw = tmp_path / "raw"
    (raw / "voteview").mkdir(parents=True)
    (raw / "voteview" / "HS119_rollcalls.csv").write_text(
        "congress,chamber,rollnumber,date,session,clerk_rollnumber,yea_count,nay_count,"
        "bill_number,vote_result,vote_desc,vote_question\n"
        "119,House,1,2025-02-01,1,10,12,9,HR100,Passed,Passage of HR100,On Passage\n"
        "119,House,2,2025-03-01,1,11,11,10,,Agreed to,A procedural motion,On the Motion\n"
        "119,Senate,1,2025-03-02,1,1,52,48,PN12,Nomination Confirmed,A nominee,On the Nomination\n"
        + ROLLCALLS_MORE, encoding="utf-8")
    return raw


def _landed(raw, bill_id):
    path = raw / congress_gov.bill_snapshot_path(bill_id)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def test_fetch_lands_each_roll_call_bill_and_a_failure_costs_only_itself(tmp_path):
    raw = _lake(tmp_path)
    client = _Bills([BILL_S7, BILL_HR100])            # H.R. 999 times out
    meta = fetch.fetch_roll_call_bills(client, raw, prior={})

    s7 = _landed(raw, "us/119/s/7")
    assert s7["bill"] == BILL_S7["bill"] and s7["cosponsors"] == BILL_S7["cosponsors"]
    assert s7["fetched_at"] and _landed(raw, "us/119/hr/100")["cosponsors"] == []
    assert _landed(raw, "us/119/hr/999") is None      # absent tonight, retried tomorrow
    assert (meta["roll_call_bills"], meta["roll_call_bills_wanted"]) == (2, 3)
    assert (meta["roll_call_bills_fetched"], meta["roll_call_bills_failed"]) == (2, 1)
    assert meta["roll_call_bills_swept_at"]
    # Only bills are asked for: the nomination is not one, and a bill whose
    # detail says it has no cosponsors costs one call, not two.
    assert {b for _, b in client.calls} == {"us/119/s/7", "us/119/hr/100", "us/119/hr/999"}
    assert ("cosponsors", "us/119/hr/100") not in client.calls
    assert ("sweep",) not in {c[:1] for c in client.calls}              # nothing landed yet
    assert set(congress_gov.landed_bills(raw)) == {"us/119/s/7", "us/119/hr/100"}


def test_fetch_resumes_and_refetches_only_what_congress_gov_says_changed(tmp_path):
    """Second night: two bills are landed, the cursor is in the hydrated
    manifest. One sweep names what changed; an unchanged landed bill costs no
    call at all, and the bill that failed last night is tried again."""
    raw = _lake(tmp_path)
    fetch.fetch_roll_call_bills(_Bills([BILL_S7, BILL_HR100]), raw, prior={})
    before = _landed(raw, "us/119/hr/100")
    prior = {"sources": {"congress.gov": {"roll_call_bills_swept_at": "2026-10-02T06:05:00+00:00"}}}
    hr999 = {"bill_id": "us/119/hr/999", "cosponsors": [],
             "bill": {"congress": 119, "type": "HR", "number": "999", "title": "Late"}}
    amended = json.loads(json.dumps(BILL_S7))
    amended["bill"]["title"] = "A Senate Bill, As Amended"
    updated = [{"congress": 119, "type": "S", "number": "7", "updateDate": "2026-10-02"},
               {"congress": 119, "type": "HR", "number": "4242", "updateDate": "2026-10-02"}]
    client = _Bills([amended, BILL_HR100, hr999], updated=updated)
    meta = fetch.fetch_roll_call_bills(client, raw, prior)

    assert client.calls[0] == ("sweep", "2026-10-01T06:05:00Z")          # cursor minus the overlap
    assert {b for kind, b in client.calls if kind == "detail"} == {"us/119/s/7", "us/119/hr/999"}
    assert _landed(raw, "us/119/hr/100") == before                       # untouched
    assert _landed(raw, "us/119/s/7")["bill"]["title"] == "A Senate Bill, As Amended"
    assert (meta["roll_call_bills"], meta["roll_call_bills_fetched"]) == (3, 2)
    assert meta["roll_call_bills_swept_at"] > prior["sources"]["congress.gov"]["roll_call_bills_swept_at"]

    # Third night: the refresh of S. 7 fails. Its last-good record stays, and the
    # cursor does NOT advance, so tomorrow's sweep names it again.
    prior = {"sources": {"congress.gov": {"roll_call_bills_swept_at": meta["roll_call_bills_swept_at"]}}}
    client = _Bills([BILL_HR100, hr999], updated=updated, failing={"us/119/s/7"})
    meta3 = fetch.fetch_roll_call_bills(client, raw, prior)
    assert _landed(raw, "us/119/s/7")["bill"]["title"] == "A Senate Bill, As Amended"
    assert (meta3["roll_call_bills"], meta3["roll_call_bills_failed"]) == (3, 1)
    assert meta3["roll_call_bills_swept_at"] == meta["roll_call_bills_swept_at"]


def test_fetch_refuses_a_cosponsor_list_that_contradicts_the_bill(tmp_path):
    """The paginator stops at a short page, so a truncated list looks complete.
    The bill detail carries the count; a list that matches neither count is not
    landed - and a wrong bill in the response is not landed under this id."""
    raw = _lake(tmp_path)
    short = json.loads(json.dumps(BILL_S7))
    short["cosponsors"] = short["cosponsors"][:2]                        # says 3 (4 with withdrawn)
    wrong = json.loads(json.dumps(BILL_HR100))
    wrong["bill"]["number"] = "101"
    meta = fetch.fetch_roll_call_bills(_Bills([short, wrong]), raw, prior={})
    assert congress_gov.landed_bills(raw) == {} and meta["roll_call_bills_failed"] == 3


def test_fetch_stops_early_on_an_outage_and_never_raises(tmp_path, monkeypatch):
    """Every call failing is an outage, not 500 unlucky bills: the breaker stops
    the step, and the congress.gov member slice it rides on is still returned."""
    raw = _lake(tmp_path)
    monkeypatch.setattr(fetch, "ROLL_CALL_BILLS_MAX_FAILURE_STREAK", 1)
    meta = fetch.fetch_roll_call_bills(_Bills([]), raw, prior={})
    assert meta["roll_call_bills"] == 0 and 1 <= meta["roll_call_bills_failed"] <= 3

    # With the breaker back at its real setting, one failing bill is just one
    # failing bill: the others land and the counters join the congress.gov row.
    monkeypatch.setattr(fetch, "ROLL_CALL_BILLS_MAX_FAILURE_STREAK", 10)

    class _Members(_Bills):
        def current_members(self, congress):
            return iter([])

    def boom(*a, **k):
        raise RuntimeError("a bug in the bill step")
    monkeypatch.setattr(fetch.congress_gov, "CongressGovClient", lambda *a, **k: _Members([BILL_S7]))
    landed = fetch.fetch_congress_gov(raw, prior={})
    assert landed["roll_call_bills"] == 1 and landed["count"] == 0       # merged into the one row
    monkeypatch.setattr(fetch, "fetch_roll_call_bills", boom)
    assert fetch.fetch_congress_gov(raw, prior={})["count"] == 0         # skipped, not fatal


def test_client_methods_use_the_documented_paths_under_the_one_throttle(monkeypatch):
    """bill_detail and bill_cosponsors go through get(), so every call they make
    is paced by the shared client's rate governor - there is no second path. The
    cosponsor list walks every page: a bill with 253 cosponsors is two calls."""
    seen = []

    def handler(request):
        seen.append((request.url.path, request.url.params.get("offset")))
        if request.url.path.endswith("/cosponsors"):
            n = 250 if request.url.params["offset"] == "0" else 3
            return httpx.Response(200, json={"cosponsors": [{"bioguideId": "X"}] * n})
        return httpx.Response(200, json={"bill": {"congress": 119, "type": "HR", "number": "1"}})

    client = congress_gov.CongressGovClient(api_key="test")
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    paced = []
    monkeypatch.setattr(client, "_throttle", lambda: paced.append(1))
    assert client.bill_detail(119, "hr", 1)["number"] == "1"
    assert len(client.bill_cosponsors(119, "s", 5)) == 253
    assert seen == [("/v3/bill/119/hr/1", None),
                    ("/v3/bill/119/s/5/cosponsors", "0"), ("/v3/bill/119/s/5/cosponsors", "250")]
    assert len(paced) == len(seen)
