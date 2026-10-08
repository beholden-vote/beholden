"""WO-22b Part B: Tennessee counties from the CTAS directory exports. Offline.

Fixtures (tests/fixtures/roster/ctas_*.csv) are the two real public CTAS exports
fetched 2026-10-08, trimmed to nine counties and redacted: street address, city,
ZIP, fax and phone blanked, and the local part of every non-government email
replaced by "redacted" (the domain, which is all the allow-rule reads, is kept).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from beholden_etl.build import coverage_divisions
from beholden_etl.jobs import build, transform
from beholden_etl.sources import roster, tn_ctas
from test_pipeline import LEGS, MANIFEST, ROSTER_FIXTURES

AS_OF = "2026-10-08T06:00:00+00:00"
COMMISSIONERS = (ROSTER_FIXTURES / "ctas_commissioners.csv").read_bytes()
EXECUTIVES = (ROSTER_FIXTURES / "ctas_executives.csv").read_bytes()
SPEC = {s.name: s for s in tn_ctas.SPECS}
# In the fixture: lists >= the county page's size, one executive each.
COVERED = {"Grundy", "Hamilton", "Lake", "Meigs", "Unicoi", "Wilson"}


def _serve(monkeypatch, commissioners: bytes = COMMISSIONERS) -> list[str]:
    calls: list[str] = []
    body = {tn_ctas.COMMISSIONERS_CSV: commissioners, tn_ctas.EXECUTIVES_CSV: EXECUTIVES}

    def get(url):
        calls.append(url)
        return body[url]
    monkeypatch.setattr(roster, "_get", get)
    monkeypatch.setattr(roster, "SHARED_PAUSE_S", 0)
    monkeypatch.setattr(roster, "_shared_memo", {})
    return calls


def _fetch(raw: Path, prior: dict | None = None) -> dict:
    return {s.source.source_key: f for s in tn_ctas.SPECS
            if (f := roster.fetch(s, raw, prior or {})) is not None}


def _pipeline(tmp: Path, monkeypatch, commissioners: bytes = COMMISSIONERS,
              prior: dict | None = None) -> tuple[Path, dict]:
    raw = tmp / "raw"
    _serve(monkeypatch, commissioners)
    frags = _fetch(raw, prior)
    (raw / "unitedstates_legislators").mkdir(parents=True, exist_ok=True)
    (raw / "unitedstates_legislators" / "legislators-current.json").write_text(
        json.dumps(LEGS), encoding="utf-8")
    manifest = json.loads(json.dumps(MANIFEST))
    for k, f in frags.items():
        manifest["sources"][k] = {**f, "retrieved_at": f["retrieved_at"] if prior else AS_OF}
    (raw / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    db = str(tmp / "wh.duckdb")
    transform.run(raw_dir=raw, db_path=db)
    build.run(db_path=db, out_dir=tmp / "data", raw_dir=raw)
    return tmp / "data", manifest


def _ctas_docs(data: Path) -> dict[str, dict]:
    keys = {s.source.source_key for s in tn_ctas.SPECS}
    out = {}
    for f in (data / "dossiers").glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d["identity"]["provenance"]["source"] in keys:
            out[d["person_id"]] = d
    return out


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    try:
        tmp = tmp_path_factory.mktemp("ctas")
        data, manifest = _pipeline(tmp, mp)
        return data, manifest
    finally:
        mp.undo()


# ── specs ─────────────────────────────────────────────────────────────────────

def test_ninety_three_counties_sumner_and_davidson_left_to_their_own_sources():
    assert len(tn_ctas.SPECS) == 93 and not {"Sumner", "Davidson"} & set(SPEC)
    assert len({s.source.source_key for s in tn_ctas.SPECS}) == 93
    assert len({s.ocd_id for s in tn_ctas.SPECS}) == 93
    assert all(s in roster.specs() for s in tn_ctas.SPECS)


def test_each_gate_is_the_stated_size_up_to_the_ceiling_plus_the_executive():
    for name, s in SPEC.items():
        stated = tn_ctas.STATED_SIZE[name]
        assert s.seats == (stated + 1, max(25, stated) + 1)
    assert SPEC["Knox"].seats == (12, 26)


def test_every_spec_credits_and_links_back_to_ctas():
    from beholden_etl.config import SOURCES
    for s in tn_ctas.SPECS:
        assert s.source.url == f"https://www.ctas.tennessee.edu/county/{roster.slug(s.name)}"
        assert s.reported_by == "UT County Technical Assistance Service (CTAS)"
        assert s.terms_ref == "docs/research/ctas-permission-2026-10.md" and not s.photos
        assert SOURCES[s.source.source_key].grade_reason == "official_web_roster"
    assert SPEC["Van Buren"].source.url.endswith("/county/van-buren")


# ── privacy: what may be published ──────────────────────────────────────────

@pytest.mark.parametrize("county,email,published", [
    ("Davidson", "Burkley.Allen@nashville.gov", True),     # *.gov
    ("Hamilton", "x@hamiltontn.gov", True),
    ("Lake", "x@lakecountytn.gov", True),
    ("Knox", "x@knoxcounty.org", True),                    # Knox's own site, as CTAS lists it
    ("Anderson", "x@co.anderson.tn.us", True),             # *.tn.us
    ("Grundy", "x@knoxcounty.org", False),                 # another county's domain
    ("Wilson", "x@gmail.com", False),                      # webmail
    ("Grundy", "x@yahoo.com", False),
    ("Wilson", "x@wilsoncountytn.go", False),              # a typo, not a government domain
    ("Wilson", "x@lebanontn.org", False),                  # not .gov, not the county's site
    ("Lake", "x@tiptonvillecityhall.com", False),
    ("Lake", "", False), ("Lake", None, False), ("Lake", "not an email", False),
])
def test_email_allow_rule(county, email, published):
    assert (tn_ctas.official_email(county, email) is not None) is published


def test_the_split_keeps_only_publishable_fields():
    slices = tn_ctas.split({"commissioners.csv": COMMISSIONERS, "executives.csv": EXECUTIVES})
    assert set(slices) == {tn_ctas.locality_id(c)
                           for c in COVERED | {"Knox", "Sumner", "Davidson"}}
    for body in slices.values():
        doc = json.loads(body)
        for p in doc["members"] + doc["executives"]:
            assert set(p) == {"name", "title", "email"}
            assert p["email"] is None or "redacted" not in p["email"]
    davidson = json.loads(slices["tn-davidson-county"])        # in the export, not a spec
    assert len(davidson["members"]) == 40
    assert davidson["executives"] == [{"email": "mayor@nashville.gov",
                                       "name": "Freddie O'Connell", "title": "Metro Mayor"}]


def test_a_changed_export_withholds_every_county(tmp_path, monkeypatch):
    _serve(monkeypatch, b"County,Name\nLake,Someone\n")      # columns gone
    assert _fetch(tmp_path) == {}                              # nothing landed, nothing fabricated


# ── gates and coverage ──────────────────────────────────────────────────────

def test_shared_exports_are_fetched_once_each_for_all_93_counties(tmp_path, monkeypatch):
    calls = _serve(monkeypatch)
    frags = _fetch(tmp_path)
    assert calls == [tn_ctas.COMMISSIONERS_CSV, tn_ctas.EXECUTIVES_CSV]
    assert {k.removeprefix("ctas_") for k in frags} == {roster.slug(c).replace("-", "_")
                                                         for c in COVERED}
    # Knox lists 4 of the 11 its county page states: withheld, and with no last
    # good anywhere it is absent rather than published partial.
    assert "ctas_knox" not in frags


def test_coverage_names_each_county_and_its_source_note(built):
    data, _ = built
    cov = json.loads((data / "coverage" / "tn.json").read_text(encoding="utf-8"))["divisions"]
    ctas = {k: v for k, v in cov.items() if v["source"].startswith("ctas_")}
    assert {SPEC[n].ocd_id for n in COVERED} == set(ctas)
    assert all(v["state"] == "covered" for v in ctas.values())
    meigs = cov[SPEC["Meigs"].ocd_id]
    assert (meigs["reason"], meigs["seats_listed"], meigs["seats_expected"]) == \
        ("roster lists 12; county page states 11", 13, 12)
    assert "ocd-division/country:us/state:tn/county:davidson" not in cov
    assert cov[SPEC["Grundy"].ocd_id]["reason"] is None
    assert SPEC["Knox"].ocd_id not in cov


# ── dossiers ──────────────────────────────────────────────────────────────────

def test_every_dossier_credits_ctas_and_links_to_its_county_page(built):
    data, _ = built
    docs = _ctas_docs(data)
    assert len(docs) == 9 + 11 + 9 + 12 + 9 + 25 + 6          # members + one executive each
    for d in docs.values():
        prov = d["identity"]["provenance"]
        county = d["identity"]["office"]["display"]
        assert prov["reported_by"] == "UT County Technical Assistance Service (CTAS)"
        assert prov["source_url"].startswith("https://www.ctas.tennessee.edu/county/")
        assert (prov["grade"], prov["grade_reason"]) == ("B", "official_web_roster")
        assert d["identity"]["party"]["code"] == "U"
        assert d["identity"]["photo_url"] is None, county


def test_no_address_fax_or_personal_email_is_published(built):
    data, _ = built
    text = "\n".join(json.dumps(d) for d in _ctas_docs(data).values())
    assert "redacted" not in text
    emails = {d["identity"]["contact"].get("email") for d in _ctas_docs(data).values()
              if (d["identity"].get("contact") or {}).get("email")}
    own = set(tn_ctas.COUNTY_DOMAINS.values())
    assert emails and all(e.lower().endswith((".gov", ".tn.us"))
                          or e.lower().split("@")[1] in own for e in emails)
    assert any(e.lower().endswith("@meigscountytn.org") for e in emails)   # Meigs's own site


def test_offices_read_as_the_body_and_the_mayor(built):
    data, _ = built
    displays = {d["identity"]["office"]["display"] for d in _ctas_docs(data).values()}
    assert {"Grundy County Commission", "County Mayor of Grundy"} <= displays
    assert not any("Davidson" in x for x in displays)


def test_county_pins_carry_the_commission_and_the_mayor(built):
    data, _ = built
    pins = json.loads((data / "pins" / "county" / "tn.json").read_text(encoding="utf-8"))
    grundy = [p for p in pins if p["ocd_id"] == SPEC["Grundy"].ocd_id]
    assert len(grundy) == 10


# ── a deliberately broken county ───────────────────────────────────────────────

def test_a_broken_county_withholds_exactly_one_county(built, tmp_path, monkeypatch):
    """The next night's export drops a Grundy commissioner (8 of the 9 its page
    states). Grundy alone is withheld and served from its last good roster;
    every other county still covered; the same dossiers publish."""
    good, manifest = built
    lines = COMMISSIONERS.decode("utf-8").splitlines(keepends=True)
    drop = next(i for i, ln in enumerate(lines) if ln.startswith("Grundy,"))
    broken = "".join(lines[:drop] + lines[drop + 1:]).encode("utf-8")
    # Last good: the healthy run's landed slices.
    import shutil
    shutil.copytree(good.parent / "raw", tmp_path / "raw")
    data, _ = _pipeline(tmp_path, monkeypatch, broken, prior=manifest)
    cov = json.loads((data / "coverage" / "tn.json").read_text(encoding="utf-8"))["divisions"]
    states = {n: cov[SPEC[n].ocd_id]["state"] for n in COVERED}
    assert states == {**{n: "covered" for n in COVERED}, "Grundy": "withheld"}
    assert "9 seats listed, expected 10" in cov[SPEC["Grundy"].ocd_id]["reason"]
    assert sorted(_ctas_docs(data)) == sorted(_ctas_docs(good))
    hints = json.loads((data.parent / coverage_divisions.HINTS_FILE).read_text(encoding="utf-8"))
    assert len(hints["live"]) == 10                            # Grundy's 9 + its mayor


def test_no_term_date_is_invented(built):
    """The export publishes no term dates; the spine's NOT NULL start_date holds
    an internal sentinel that no served object may carry."""
    data, _ = built
    assert {s.term_start for s in tn_ctas.SPECS} == {"1900-01-01"}
    served = list(data.rglob("*.json"))
    assert served
    for p in served:
        assert "1900-01-01" not in p.read_text(encoding="utf-8"), p.relative_to(data)
    for d in _ctas_docs(data).values():
        assert d["identity"]["tenure"]["first_took_office"] is None
        assert not d.get("previous_roles")
