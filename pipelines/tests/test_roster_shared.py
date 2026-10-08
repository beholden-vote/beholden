"""WO-22b framework additions: at-large members and shared-file sources (§8.8, §8.10).

Offline. A synthetic two-county shared file stands in for a statewide export.
"""
from __future__ import annotations

import dataclasses
import json

import httpx
import pytest

from beholden_etl import divisions as D
from beholden_etl.build import coverage_divisions
from beholden_etl.jobs import build
from beholden_etl.sources import roster
from beholden_etl.sources.roster import RosterError, RosterRow

# ── a synthetic shared source: one JSON file, {locality_id: [names]} ─────────

URL = "https://example.test/export.json"


def _split(files: dict[str, bytes]) -> dict[str, bytes]:
    doc = json.loads(files["export.json"])          # a broken file raises here
    return {loc: json.dumps(names).encode() for loc, names in doc.items()}


def _parse(raw: bytes, spec) -> list[RosterRow]:
    return [RosterRow(name=n, office_title="Commissioner", seat_label=None, at_large=True)
            for n in json.loads(raw)]


def _note(spec, rows):
    return f"roster lists {len(rows)}; expected {spec.seats[0]}" if len(rows) > spec.seats[0] else None


roster.ADAPTERS["test_shared"] = roster.Adapter(_parse, note=_note)
roster.SHARED["test_export"] = roster.SharedSource("test_export", (("export.json", URL),), _split)


def _spec(name: str, seats=(3, 5)) -> roster.RosterSpec:
    return roster.RosterSpec(
        locality_id=f"tn-{name.lower()}", ocd_id=D.county_ocd("TN", name), level="county",
        name=name, body="County Commission",
        source=roster.SourceRef(f"test_{name.lower()}", f"https://example.test/{name}",
                                "test_shared", shared="test_export"),
        seats=seats, terms_ref="docs/research/ctas-permission-2026-10.md",
        chamber="county_commission", reported_by="Example", term_start="2026-09-01")


ALPHA, BETA = _spec("Alpha"), _spec("Beta")
GOOD = {"tn-alpha": ["A One", "A Two", "A Three"], "tn-beta": ["B One", "B Two", "B Three", "B Four"]}


@pytest.fixture
def served(monkeypatch):
    """Serve `body` for the export URL and count the requests."""
    calls = []
    state = {"body": json.dumps(GOOD).encode()}

    def get(url):
        calls.append(url)
        if isinstance(state["body"], Exception):
            raise state["body"]
        return state["body"]
    monkeypatch.setattr(roster, "_get", get)
    monkeypatch.setattr(roster, "SHARED_PAUSE_S", 0)
    monkeypatch.setattr(roster, "_shared_memo", {})
    return calls, state


def _fetch_all(raw, prior=None):
    return {s.locality_id: roster.fetch(s, raw, prior or {}) for s in (ALPHA, BETA)}


# ── at-large members ──────────────────────────────────────────────────────────

def test_at_large_members_are_people_not_duplicate_seats():
    rows = _parse(json.dumps(GOOD["tn-alpha"]).encode(), ALPHA)
    roster.check(ALPHA, rows)                                    # three, no seat labels: fine
    with pytest.raises(RosterError, match="same person"):
        roster.check(ALPHA, rows + [rows[0]])
    # The executive is still one per title.
    mayor = RosterRow(name="M", office_title="Mayor", seat_label=None)
    with pytest.raises(RosterError, match="more times than they exist"):
        roster.check(ALPHA, rows[:2] + [mayor, dataclasses.replace(mayor, name="N")])
    # Seat-labelled rows keep the duplicate check.
    seated = [RosterRow(name=f"S {n}", office_title="Commissioner", seat_label="District 1")
              for n in range(3)]
    with pytest.raises(RosterError, match="more times than they exist"):
        roster.check(ALPHA, seated)


def test_at_large_members_are_legislative_seats_of_the_locality():
    rows = _parse(json.dumps(GOOD["tn-alpha"]).encode(), ALPHA)
    mayor = RosterRow(name="M Ayor", office_title="County Mayor", seat_label=None)
    spine = roster.spine_rows(ALPHA, rows + [mayor])
    offices = {o["role"] + o["office_id"]: o for o in spine["offices"]}
    members = [o for o in offices.values() if o["role"] == "Commissioner"]
    assert len({o["office_id"] for o in members}) == 3                  # one office per person
    assert {(o["ocd_id"], o["branch"], o["chamber"]) for o in members} == \
        {(ALPHA.ocd_id, "legislative", "county_commission")}
    (exec_,) = [o for o in offices.values() if o["role"] == "County Mayor"]
    assert (exec_["branch"], exec_["chamber"]) == ("executive", None)
    displays = {t["meta"]["office_display"] for t in spine["terms"]}
    assert displays == {"Alpha County Commission", "County Mayor of Alpha"}


# ── shared-file sources ──────────────────────────────────────────────────────

def test_a_shared_file_is_fetched_once_and_each_locality_lands_its_own_slice(tmp_path, served):
    calls, _ = served
    frags = _fetch_all(tmp_path)
    assert calls == [URL]                                        # once, for both localities
    assert frags["tn-alpha"]["count"] == 3 and frags["tn-beta"]["count"] == 4
    assert frags["tn-alpha"]["source_url"] == ALPHA.source.url   # the locality's own page
    for s in (ALPHA, BETA):
        assert json.loads(roster.landed(s, tmp_path).read_bytes()) == GOOD[s.locality_id]
    assert not (tmp_path / "test_export").exists()               # only the slices are kept


def test_one_locality_failing_its_gate_withholds_only_that_locality(tmp_path, served):
    _, state = served
    first = _fetch_all(tmp_path)
    prior = {"sources": {s.source.source_key: first[s.locality_id] for s in (ALPHA, BETA)}}
    roster._shared_memo.clear()                                  # the next night
    state["body"] = json.dumps({**GOOD, "tn-beta": ["B One"]}).encode()
    frags = _fetch_all(tmp_path, prior)
    assert "withheld" not in frags["tn-alpha"]
    assert "1 seats listed, expected 3-5" in frags["tn-beta"]["withheld"]
    assert frags["tn-beta"]["retrieved_at"] == first["tn-beta"]["retrieved_at"]
    assert json.loads(roster.landed(BETA, tmp_path).read_bytes()) == GOOD["tn-beta"]


@pytest.mark.parametrize("failure", [httpx.ConnectError("down"), b"{not json"])
def test_a_shared_file_that_fails_withholds_all_its_localities_and_the_run_continues(
        tmp_path, served, failure):
    calls, state = served
    first = _fetch_all(tmp_path)
    prior = {"sources": {s.source.source_key: first[s.locality_id] for s in (ALPHA, BETA)}}
    roster._shared_memo.clear()
    calls.clear()
    state["body"] = failure
    frags = _fetch_all(tmp_path, prior)
    assert len(calls) == 1                                       # not retried per locality
    for s in (ALPHA, BETA):
        f = frags[s.locality_id]
        assert "shared source file could not be read" in f["withheld"]
        assert f["retrieved_at"] == first[s.locality_id]["retrieved_at"]   # never restamped
        assert json.loads(roster.landed(s, tmp_path).read_bytes()) == GOOD[s.locality_id]


def test_no_last_good_anywhere_is_absent_not_withheld(tmp_path, served):
    _, state = served
    state["body"] = httpx.ConnectError("down")
    assert _fetch_all(tmp_path) == {"tn-alpha": None, "tn-beta": None}


def test_a_locality_missing_from_the_shared_file_is_withheld(tmp_path, served):
    _, state = served
    state["body"] = json.dumps({"tn-alpha": GOOD["tn-alpha"]}).encode()
    frags = _fetch_all(tmp_path)
    assert frags["tn-alpha"]["count"] == 3 and frags["tn-beta"] is None


def test_a_page_source_still_fails_the_run_on_a_network_error(tmp_path, monkeypatch):
    def down(url):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(roster, "_get", down)
    page_spec = dataclasses.replace(ALPHA, source=dataclasses.replace(ALPHA.source, shared=None))
    with pytest.raises(httpx.ConnectError):
        roster.fetch(page_spec, tmp_path, {})


# ── a covered locality can carry a plain source note ─────────────────────────

def test_covered_entry_carries_the_source_note(tmp_path, served, monkeypatch):
    frags = _fetch_all(tmp_path)
    manifest = {"sources": {s.source.source_key: frags[s.locality_id] for s in (ALPHA, BETA)}}
    monkeypatch.setattr(roster, "specs", lambda: [ALPHA, BETA])
    out = tmp_path / "data"
    ctx = build.BuildContext(db_path="", raw_dir=tmp_path, out=out, manifest=manifest,
                             holders=[], _provenance=build._provenance)
    assert coverage_divisions.publish(ctx)["localities_covered"] == 2
    cov = json.loads((out / "coverage" / "tn.json").read_text(encoding="utf-8"))["divisions"]
    assert cov[ALPHA.ocd_id]["reason"] is None
    beta = cov[BETA.ocd_id]
    assert (beta["state"], beta["reason"]) == ("covered", "roster lists 4; expected 3")
