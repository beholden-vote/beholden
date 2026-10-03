"""WO-23a: the full federal voting record - votes/, rollcalls/, bills/
(DATA-CONTRACTS 8.3). Runs offline on the shared synthetic slice."""
from __future__ import annotations

import json
import re

import pytest

from beholden_etl.build import dossiers, key_votes, votes
from beholden_etl.jobs import build

KEY_RE = re.compile(r"[a-z0-9/._-]+")
PREFIXES = ("votes", "rollcalls", "bills")


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


def test_two_builds_differ_only_in_their_stamps(slice_dirs, tmp_path_factory):
    """Stable ordering everywhere, so a recess week rewrites nothing."""
    first = _unstamped(slice_dirs)
    again = tmp_path_factory.mktemp("again")
    build.run(db_path=str(slice_dirs / "wh.duckdb"), out_dir=again / "data",
              raw_dir=slice_dirs / "raw")
    assert _unstamped(again) == first and len(first) == 7


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
