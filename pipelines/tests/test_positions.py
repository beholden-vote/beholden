"""WO-36: position profile - positions/{chamber}.json (DATA-CONTRACTS 8.7).
Runs offline: the shared synthetic slice plus a hand-built chamber."""
from __future__ import annotations

import json
import random
import re

import pytest

from beholden_etl import store
from beholden_etl.build import key_votes, measures, positions
from beholden_etl.build.context import BuildContext
from beholden_etl.jobs import build
from beholden_etl.sources import voteview

COMPOSITE = re.compile(r"score|rating|rank|grade", re.I)
STAMPS = ("generated_at",)


def _load(dirs, chamber):
    return json.loads((dirs / "data" / "positions" / f"{chamber}.json").read_text())


def _keys(node, skip=("provenance",)):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in skip:
                continue
            yield k
            yield from _keys(v, skip)
    elif isinstance(node, list):
        for v in node:
            yield from _keys(v, skip)


# --- a hand-built chamber: 30 D, 30 R, 1 I, 80 roll calls, two blocs ----------
def _chamber(swap: bool = False):
    rng = random.Random(7)
    flip = {"D": "R", "R": "D"} if swap else {}
    members, cast_by, rows = [], {}, []
    for i in range(61):
        party = "I" if i == 60 else ("D" if i % 2 else "R")
        pid = f"p{i:03d}"
        members.append({"person_id": pid, "name": f"M {i}", "party": flip.get(party, party),
                        "state": "TN"})
        lean = 0.85 if party == "D" else 0.15 if party == "R" else 0.5
        votes = []
        for r in range(80):
            rcid = f"us/119/house/{r + 1}"
            x = rng.random()
            pos = "not_voting" if x > 0.97 else ("yea" if rng.random() < lean else "nay")
            if i == 59 and r >= 10:           # p059 joined late: below every floor
                continue
            votes.append((rcid, pos))
            rows.append({"roll_call_id": rcid, "party": flip.get(party, party), "position": pos})
        cast_by[pid] = votes
    majority = key_votes.party_majority_positions(rows)
    rc_area = {f"us/119/house/{r + 1}": ("Health" if r % 2 else "Taxation") if r % 5 else None
               for r in range(80)}
    nominate = {"p000": (0.41, -0.12)}
    return positions.chamber_members(members, cast_by, majority, rc_area, nominate)


def test_party_swap_leaves_every_measure_equal():
    a, b = _chamber(), _chamber(swap=True)
    assert [m["party"] for m in a] != [m["party"] for m in b]
    for x, y in zip(a, b):
        assert x["person_id"] == y["person_id"]
        assert x["measures"] == y["measures"]
        assert x["layout"] == y["layout"]
        assert x["nominate"] == y["nominate"]


def test_two_builds_are_byte_identical():
    assert json.dumps(_chamber()) == json.dumps(_chamber())


def test_independent_gets_null_other_party_and_floors_apply():
    by_id = {m["person_id"]: m for m in _chamber()}
    assert by_id["p060"]["measures"]["with_other_party"] is None
    assert by_id["p001"]["measures"]["with_other_party"]["pct"] is not None
    late = by_id["p059"]
    assert late["layout"] is None
    assert late["measures"]["with_own_party"]["pct"] is None       # of < floor
    assert late["measures"]["with_own_party"]["of"] > 0              # n, of exact
    assert late["measures"]["party_line_by_policy_area"] == []       # areas below floor omitted
    assert by_id["p000"]["nominate"] == {"dim1": 0.41, "dim2": -0.12}
    assert by_id["p001"]["nominate"] == {"dim1": None, "dim2": None}  # never 0-filled


def test_layout_is_scaled_and_rounded():
    placed = [m["layout"] for m in _chamber() if m["layout"]]
    assert len(placed) == 60
    for axis in ("x", "y"):
        vals = [p[axis] for p in placed]
        assert max(abs(v) for v in vals) == 1.0
        assert all(round(v, 3) == v for v in vals)
    # Orientation rule: the first placed member by person_id is non-negative.
    first = next(m for m in _chamber() if m["layout"])
    assert first["layout"]["x"] >= 0 and first["layout"]["y"] >= 0


def test_with_other_party_on_a_hand_built_split():
    maj = {"r1\tD": "yea", "r1\tR": "nay",     # split: counts
           "r2\tD": "yea", "r2\tR": "yea",     # agree: excluded
           "r3\tD": "nay",                     # R tied: excluded
           "r4\tD": "nay", "r4\tR": "yea"}     # split: counts
    votes = [{"roll_call_id": "r1", "position": "nay", "party_position": "yea"},
             {"roll_call_id": "r2", "position": "nay", "party_position": "yea"},
             {"roll_call_id": "r3", "position": "yea", "party_position": "nay"},
             {"roll_call_id": "r4", "position": "nay", "party_position": "nay"},
             {"roll_call_id": "r1", "position": "present", "party_position": "yea"}]
    assert measures.with_other_party(votes, "D", maj) == {"n": 1, "of": 2, "pct": None}
    assert measures.with_other_party(votes, "I", maj) is None
    big = votes[:1] * 15 + votes[3:4] * 5            # 15 with R, 5 with own: of = 20
    assert measures.with_other_party(big, "D", maj) == {"n": 15, "of": 20, "pct": 75.0}


def test_validate_refuses_a_composite_key_and_a_missing_member():
    doc = {"chamber": "house", "members": _chamber()}
    sitting = {m["person_id"] for m in doc["members"]}
    positions.validate(doc, sitting)
    with pytest.raises(ValueError, match="sitting"):
        positions.validate(doc, sitting | {"absent"})
    doc["members"][0]["measures"]["with_own_party"]["pct"] = 101.0
    with pytest.raises(ValueError, match="out of range"):
        positions.validate(doc, sitting)
    doc["members"][0]["measures"]["with_own_party"]["pct"] = 50.0
    doc["members"][0]["overall_score"] = 1
    with pytest.raises(ValueError, match="composite"):
        positions.validate(doc, sitting)


def test_score_rows_read_dim2_and_never_zero_fill():
    csv_text = ("congress,chamber,icpsr,nominate_dim1,nominate_dim2,nominate_number_of_votes\n"
                "119,House,11,0.5,-0.25,300\n119,House,22,-0.3,,300\n119,House,33,0.1,0.2,5\n")
    rows = {r["person_id"]: r for r in voteview.to_score_rows(
        csv_text, 119, {"11": "a", "22": "b", "33": "c"})}
    assert rows["a"]["nominate_dim2"] == -0.25
    assert rows["b"]["nominate_dim2"] is None
    assert rows["c"]["nominate_dim2"] is None                   # below the floor


# --- the slice ----------------------------------------------------------------
def test_with_own_party_equals_the_published_votes_summary(slice_dirs):
    seen = 0
    for chamber in ("house", "senate"):
        for m in _load(slice_dirs, chamber)["members"]:
            summary = json.loads((slice_dirs / "data" / "votes" / f"{m['person_id']}.json")
                                 .read_text())["summary"]
            assert m["measures"]["with_own_party"]["n"] == summary["with_party"]
            assert m["measures"]["with_own_party"]["of"] == summary["party_decided"]
            assert m["measures"]["missed"]["n"] == summary["not_voting"]
            assert m["measures"]["missed"]["of"] == summary["total"]
            seen += 1
    assert seen


def test_every_sitting_member_listed_and_counts_reach_coverage(slice_dirs):
    con = store.connect(str(slice_dirs / "wh.duckdb"))
    holders = build._current_holders(con)
    con.close()
    coverage = json.loads((slice_dirs / "data" / "coverage.json").read_text())
    for chamber in ("house", "senate"):
        doc = _load(slice_dirs, chamber)
        sitting = {h["person_id"] for h in holders
                   if h["chamber"] == chamber and not h["is_vacant_marker"]}
        ids = [m["person_id"] for m in doc["members"]]
        assert set(ids) == sitting and ids == sorted(ids)
        assert coverage["counts"][f"positions_{chamber}"] == len(sitting)
        assert doc["provenance"]["source"] == "voteview"
        assert doc["provenance"]["methodology_id"] == positions.METHODOLOGY_PROFILE
        assert set(doc["methodology_ids"]) == {"with_own_party", "with_other_party",
                                               "missed", "party_line", "layout"}
        for m in doc["members"]:
            assert set(m) == {"person_id", "name", "party", "state", "nominate",
                              "measures", "layout"}
            # The slice is tiny: every pct is below the floor, every layout null.
            assert m["measures"]["with_own_party"]["pct"] is None
            assert m["layout"] is None


def test_no_composite_key_anywhere_in_the_output(slice_dirs):
    for chamber in ("house", "senate"):
        bad = [k for k in _keys(_load(slice_dirs, chamber)) if COMPOSITE.search(k)]
        assert bad == []


def test_rebuild_is_byte_identical_apart_from_stamps(slice_dirs, tmp_path):
    con = store.connect(str(slice_dirs / "wh.duckdb"))
    holders = build._current_holders(con)
    con.close()
    raw = slice_dirs / "raw"
    manifest = build._load_manifest(raw)
    outs = []
    for name in ("a", "b"):
        ctx = BuildContext(db_path=str(slice_dirs / "wh.duckdb"), raw_dir=raw,
                           out=tmp_path / name, manifest=manifest, holders=holders,
                           _provenance=build._provenance)
        positions.publish(ctx)
        docs = []
        for chamber in ("house", "senate"):
            doc = json.loads((tmp_path / name / "positions" / f"{chamber}.json").read_text())
            for k in STAMPS:
                doc.pop(k)
            doc["provenance"].pop("pipeline_version")
            docs.append(json.dumps(doc))
        outs.append(docs)
    assert outs[0] == outs[1]
