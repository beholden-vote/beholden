"""WO-22b Part B: Tennessee cities from the MTAS public export. Offline, from a trimmed
real export (fixtures/roster/mtas_official.csv, retrieved 2026-10-08, billing columns blanked)."""
from __future__ import annotations

import csv
import dataclasses
import io
import json
from pathlib import Path

import pytest

from beholden_etl import divisions as D
from beholden_etl.jobs import build, transform
from beholden_etl.sources import roster, tn_mtas
from test_pipeline import LEGS, MANIFEST

REPO = Path(__file__).resolve().parents[2]
EXPORT = (Path(__file__).parent / "fixtures" / "roster" / "mtas_official.csv").read_bytes()
BY_ORG = {c["org"]: s for c, s in zip(tn_mtas._TABLE["cities"], tn_mtas.SPECS)}
FIXTURE_ORGS = ["Ashland City", "Doyle", "Greenbrier", "Hartsville", "Hollow Rock", "Mt. Juliet",
                "Nashville", "Orme", "Sharon"]
SPECS = [BY_ORG[o] for o in FIXTURE_ORGS]
AS_OF = "2026-10-08T06:00:00+00:00"


@pytest.fixture(autouse=True)
def _fresh_memo():
    roster._shared_memo.clear()
    yield
    roster._shared_memo.clear()


def _serve(monkeypatch, body: bytes) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(roster, "_get", lambda url: calls.append(url) or body)
    roster._shared_memo.clear()
    return calls


def _fetch(raw: Path, prior: dict, specs=SPECS) -> dict:
    out = {"sources": {}}
    for s in specs:
        frag = roster.fetch(s, raw, prior)
        if frag:
            out["sources"][s.source.source_key] = {**frag, "retrieved_at": AS_OF}
    return out


def _without(org: str, title: str, n: int) -> bytes:
    """The export with n of an organization's rows of one title removed."""
    rows = list(csv.reader(io.StringIO(EXPORT.decode("utf-8"))))
    drop = [i for i, r in enumerate(rows) if r[0] == org and r[8].startswith(title)][:n]
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(r for i, r in enumerate(rows) if i not in drop)
    return out.getvalue().encode("utf-8")


def _build(tmp: Path, manifest: dict) -> Path:
    raw = tmp / "raw"
    (raw / "unitedstates_legislators").mkdir(parents=True, exist_ok=True)
    (raw / "unitedstates_legislators" / "legislators-current.json").write_text(
        json.dumps(LEGS), encoding="utf-8")
    m = json.loads(json.dumps(MANIFEST))
    m["sources"].update(manifest["sources"])
    (raw / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    db = str(tmp / "wh.duckdb")
    transform.run(raw_dir=raw, db_path=db)
    build.run(db_path=db, out_dir=tmp / "data", raw_dir=raw)
    return tmp / "data"


def _coverage(data: Path) -> dict:
    return json.loads((data / "coverage" / "tn.json").read_text(encoding="utf-8"))["divisions"]


# --- the table ---------------------------------------------------------------------

def test_table_is_one_spec_per_city_with_exactly_one_census_place():
    t = tn_mtas._TABLE
    assert len(tn_mtas.SPECS) == len(t["cities"]) == 344
    assert set(t["excluded"]) == {"Hendersonville"}          # it ships from its own roster
    assert len({s.ocd_id for s in tn_mtas.SPECS}) == 344
    assert len({s.source.source_key for s in tn_mtas.SPECS}) == 344
    assert len({c["geoid"] for c in t["cities"]}) == 344
    for s in tn_mtas.SPECS:
        assert s.terms_ref == tn_mtas.TERMS_REF and (REPO / s.terms_ref).exists()
        assert s.seats[0] >= 1 and s.seats[1] == tn_mtas.MAX_SEATS
    # GEOIDs resolve the consolidated governments and the collisions.
    assert BY_ORG["Nashville"].ocd_id == D.place_ocd("TN", "Nashville", "4752006")
    assert BY_ORG["Nashville"].ocd_id.endswith("/place:nashville")
    assert BY_ORG["Hartsville"].ocd_id.endswith("/place:hartsville")
    assert BY_ORG["Mt. Juliet"].ocd_id.endswith("/place:mount_juliet")


def test_authorization_record_says_what_the_owner_said_and_no_more():
    doc = (REPO / tn_mtas.TERMS_REF).read_text(encoding="utf-8")
    assert "no written copy on file" in doc
    assert "No determination covers a priced bulk dataset." in doc


# --- fetch, split, parse -----------------------------------------------------------

def test_one_request_serves_every_city(tmp_path, monkeypatch):
    calls = _serve(monkeypatch, EXPORT)
    got = _fetch(tmp_path, {})
    assert calls == [tn_mtas.EXPORT_URL]
    assert set(got["sources"]) == {s.source.source_key for s in SPECS if s.name != "Sharon"}


def test_landed_slice_carries_no_billing_or_address_columns(tmp_path, monkeypatch):
    _serve(monkeypatch, EXPORT)
    _fetch(tmp_path, {})
    page = roster.landed(BY_ORG["Greenbrier"], tmp_path).read_text(encoding="utf-8")
    assert page.splitlines()[0] == ",".join(tn_mtas.SLIM)
    assert "Address" not in page and "Billing" not in page


def test_rows_are_clean_symmetric_and_private(tmp_path, monkeypatch):
    _serve(monkeypatch, EXPORT)
    _fetch(tmp_path, {})
    gb = roster.load(BY_ORG["Greenbrier"], tmp_path, {})[0]
    assert len(gb) == 7                                       # the repeated alderman is one row
    assert [r.office_title for r in gb].count("Mayor") == 1
    doyle = roster.load(BY_ORG["Doyle"], tmp_path, {})[0]
    assert len(doyle) == 5 and all(r.name != "VACANT" for r in doyle)
    assert {r.office_title for r in doyle} >= {"Mayor", "Alderman", "Vice Mayor"}
    for spec in SPECS:
        for r in roster.load(spec, tmp_path, {})[0] or []:
            assert r.party is None and r.photo_url is None
            assert set(r.contact) <= {"phone", "email"}
            if "email" in r.contact:
                assert tn_mtas.official_email(r.contact["email"], spec.name)
            assert r.source_row_url == tn_mtas.DIRECTORY_URL
    # A vice mayor's personal webmail address is not published.
    assert not any("email" in r.contact and "hotmail" in r.contact["email"] for r in doyle)


def test_official_email_rule():
    assert tn_mtas.official_email("a@cityofx.gov", "X")
    assert tn_mtas.official_email("a@x.tn.us", "Y")
    assert tn_mtas.official_email("a@greenbriertn.org", "Greenbrier")
    assert not tn_mtas.official_email("a@gmail.com", "Greenbrier")
    assert not tn_mtas.official_email("a@yahoo.com", "Yahoo City")


def test_a_city_with_two_mayors_is_withheld_not_published(tmp_path, monkeypatch, capsys):
    _serve(monkeypatch, EXPORT)
    assert roster.fetch(BY_ORG["Sharon"], tmp_path, {}) is None   # nothing good ever: absent
    assert "Mayor at large" in capsys.readouterr().out


def test_fewer_members_than_reviewed_withholds_and_more_publishes_with_a_note(tmp_path, monkeypatch):
    _serve(monkeypatch, EXPORT)
    gb = BY_ORG["Greenbrier"]
    good = roster.fetch(gb, tmp_path, {})
    assert good["count"] == gb.seats[0]
    _serve(monkeypatch, _without("Greenbrier", "Alderman", 1))
    again = roster.fetch(gb, tmp_path, {"sources": {gb.source.source_key: good}})
    assert "6 seats listed, expected 7" in again["withheld"]
    rows = roster.load(gb, tmp_path, {"sources": {gb.source.source_key: again}})[0]
    assert len(rows) == 7                                     # last good still served
    smaller = dataclasses.replace(gb, seats=(6, tn_mtas.MAX_SEATS))
    assert "lists 7 officials; 6 at review" in roster.note(smaller, rows)
    assert roster.note(gb, rows) is None


def test_header_drift_withholds_every_city_and_keeps_last_good(tmp_path, monkeypatch):
    _serve(monkeypatch, EXPORT)
    good = _fetch(tmp_path, {})
    _serve(monkeypatch, EXPORT.replace(b"Organization", b"Org", 1))
    again = _fetch(tmp_path, good)
    assert set(again["sources"]) == set(good["sources"])
    assert all("withheld" in v for v in again["sources"].values())
    assert len(roster.load(BY_ORG["Ashland City"], tmp_path, again)[0]) > 0


# --- the build: one broken city withholds exactly one city -----------------------------

@pytest.fixture(scope="module")
def built(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    tmp = tmp_path_factory.mktemp("mtas")
    try:
        _serve(mp, EXPORT)
        good = _fetch(tmp / "raw", {})
        # Next night one city's alderman rows come back short of the reviewed size.
        _serve(mp, _without("Greenbrier", "Alderman", 2))
        manifest = _fetch(tmp / "raw", good)
        return _build(tmp, manifest), manifest
    finally:
        mp.undo()


def test_exactly_one_city_is_withheld_and_the_rest_build(built):
    data, manifest = built
    cov = _coverage(data)
    withheld = [o for o, v in cov.items() if v["state"] == "withheld"]
    assert withheld == [BY_ORG["Greenbrier"].ocd_id]
    assert "5 seats listed, expected 7" in cov[withheld[0]]["reason"]
    others = [v for o, v in cov.items() if o != withheld[0]]
    assert len(others) == len(FIXTURE_ORGS) - 2 and {v["state"] for v in others} == {"covered"}
    hints = json.loads((data.parent / "publish_hints.json").read_text(encoding="utf-8"))
    assert len(hints["live"]) == 7                            # last good kept live for publish
    counts = json.loads((data / "coverage.json").read_text(encoding="utf-8"))["counts"]
    assert counts["localities_withheld"] == 1


def test_dossiers_credit_mtas_and_link_back_grade_b_party_u(built):
    data, _ = built
    seen = 0
    for f in (data / "dossiers").glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        prov = d["identity"]["provenance"]
        if not prov["source"].startswith("mtas_"):
            continue
        seen += 1
        assert prov["reported_by"] == tn_mtas.REPORTED_BY
        assert prov["source_url"] == tn_mtas.DIRECTORY_URL
        assert prov["grade"] == "B"
        assert d["identity"]["party"]["code"] == "U"
        assert d["identity"]["tenure"]["first_took_office"] is None
    assert seen > 40


def test_no_served_object_carries_the_unknown_term_start(built):
    data, _ = built
    for f in data.rglob("*"):
        if f.is_file():
            assert "1900-01-01" not in f.read_text(encoding="utf-8", errors="ignore"), f
