"""WO-34: facts about every county and city, offline against synthetic payloads.

The shapes below are the Bureau's documented ones: the Data API answers with a JSON array of
arrays (header row first, every value a string, annotations null unless the number is not a
plain estimate, geography columns last), and the 2024 Gazetteer is a tab-delimited file whose
last column is padded with spaces. Nothing here touches the network."""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from beholden_etl import rawlake
from beholden_etl.build import areas, dossiers
from beholden_etl.build.context import BuildContext
from beholden_etl.config import SOURCES
from beholden_etl.jobs import build, fetch
from beholden_etl.sources import census_areas as C

ACS_AT = "2026-10-01T04:00:00+00:00"
GAZ_AT = "2026-10-02T04:00:00+00:00"          # later on purpose: generated_at is the max
KEY = "SECRETKEY0123456789"


# -- A synthetic country: 50 states + DC, plus one territory that must be dropped ----
def acs_rec(name, geo, pop="1000", hh="400", inc="50000", age="38.5", **override):
    rec = {"NAME": name, **geo}
    for var, est, moe in (("B01003_001", pop, "-555555555"), ("B11001_001", hh, "40"),
                          ("B19013_001", inc, "1000"), ("B01002_001", age, "0.4")):
        rec[f"{var}E"], rec[f"{var}EA"], rec[f"{var}M"] = est, None, moe
        rec[f"{var}MA"] = "*****" if moe == "-555555555" else None
    rec.update(override)
    return rec


def acs_text(recs, geo):
    return json.dumps([list(C.ACS_COLUMNS) + list(geo)]
                      + [[r[c] for c in C.ACS_COLUMNS] + [r[g] for g in geo] for r in recs])


def gaz_text(level, rows):
    pad = " " * 60                                     # the real file pads its last column
    return "\n".join(["\t".join(C._GAZETTEER_HEADERS[level]) + pad]
                     + ["\t".join(map(str, r)) + pad for r in rows]) + "\n"


class World:
    """Mutable synthetic payloads. Tests tweak a row, then land() or render."""

    def __init__(self):
        self.counties, self.places, self.gaz_counties, self.gaz_places = {}, {}, {}, {}
        self.state_pop: dict[str, str] = {}               # FIPS -> a figure that disagrees with the counties
        for fips, st in C.STATES.items():
            if fips == "47":
                self.add_county(fips, "165", "Sumner County", pop="205000", hh="76000",
                                inc="78000", age="39.4",
                                B11001_001M="900", B19013_001M="2100", B01002_001M="0.3")
                self.add_county(fips, "001", "Anderson County", hh="-666666666",
                                B19013_001E="-999999999", B19013_001EA="N",
                                B01002_001E="-888888888", B01002_001EA="(X)")
                # Inserted out of GEOID order on purpose: output must still be sorted.
                self.add_place(fips, "33280", "Hendersonville city", "25", "A",
                               B11001_001M="-888888888", B11001_001MA="(X)",
                               B19013_001M="-222222222", B19013_001MA="**",
                               B01002_001M="-333333333", B01002_001MA="***")
                self.add_place(fips, "28540", "Gallatin city", "25", "A",
                               B19013_001E="250001", B19013_001EA="median+")
                # Nashville-shaped: the consolidated government exists in the Gazetteer only as
                # the "(balance)" row, LSAD 00, functional status F (the real row, 2024 file).
                self.add_place(fips, "52006", "Nashville-Davidson metropolitan government (balance)",
                               "00", "F")
            elif fips == "35":
                self.add_county(fips, "013", "Doña Ana County")
                self.add_place(fips, "10000", "Alpha city", "25", "A")
            elif fips == "22":
                self.add_county(fips, "001", "LA County")
                self.add_place(fips, "05000", "Baton Rouge city", "25", "B")     # active, partly consolidated
                self.add_place(fips, "10000", "Alpha city", "25", "A")
            else:
                self.add_county(fips, "001", f"{st.upper()} County")
                self.add_place(fips, "10000", "Alpha city", "25", "A")
            self.add_place(fips, "20000", "Beta CDP", "57", "S")                  # no government
            self.add_place(fips, "30000", "Gamma remainder", "00", "F")          # F without "(balance)": no government
        # Puerto Rico is out of scope: present in both sources, must be dropped from both.
        self.add_county("72", "001", "Adjuntas Municipio", usps="PR")
        self.add_place("72", "10000", "Adjuntas zona urbana", "62", "S", usps="PR")

    def add_county(self, fips, county, name, usps=None, **kw):
        geoid = fips + county
        self.counties[geoid] = acs_rec(f"{name}, X", {"state": fips, "county": county}, **kw)
        self.gaz_counties[geoid] = [usps or C.STATES[fips].upper(), geoid, "1", name,
                                    5, 1, "529.425", "9.9", "36.1", "-86.4"]

    def add_place(self, fips, place, name, lsad, funcstat, usps=None, **kw):
        geoid = fips + place
        self.places[geoid] = acs_rec(f"{name}, X", {"state": fips, "place": place}, **kw)
        self.gaz_places[geoid] = [usps or C.STATES[fips].upper(), geoid, "1", name, lsad,
                                  funcstat, 5, 1, "7.891", "0.", "36.1", "-86.4"]

    # -- renderings: exactly what the Bureau would send ------------------------------
    def state_recs(self):
        out = []
        for fips in C.STATES:
            total = sum(int(r["B01003_001E"]) for g, r in self.counties.items() if g.startswith(fips))
            out.append(acs_rec(f"State {fips}", {"state": fips}, pop=self.state_pop.get(fips, str(total))))
        return out

    def county_text(self):
        return acs_text(list(self.counties.values()), ("state", "county"))

    def state_text(self):
        return acs_text(self.state_recs(), ("state",))

    def place_text(self, fips):
        return acs_text([r for g, r in self.places.items() if g.startswith(fips)], ("state", "place"))

    def gaz_county_text(self):
        return gaz_text("county", self.gaz_counties.values())

    def gaz_place_text(self):
        return gaz_text("place", self.gaz_places.values())

    def land(self, raw: Path):
        (raw / "census_acs" / "place").mkdir(parents=True, exist_ok=True)
        (raw / "census_gazetteer").mkdir(parents=True, exist_ok=True)
        (raw / "census_acs" / "county.json").write_text(self.county_text(), encoding="utf-8")
        (raw / "census_acs" / "state.json").write_text(self.state_text(), encoding="utf-8")
        for fips in C.STATES:
            (raw / "census_acs" / "place" / f"{fips}.json").write_text(
                self.place_text(fips), encoding="utf-8")
        (raw / "census_gazetteer" / "county.txt").write_text(self.gaz_county_text(), encoding="utf-8")
        (raw / "census_gazetteer" / "place.txt").write_text(self.gaz_place_text(), encoding="utf-8")


def manifest(**drop):
    sources = {"census_acs": {"retrieved_at": ACS_AT, "source_url": C.ACS_SOURCE_URL, "count": 1,
                              "vintage": C.ACS_YEAR},
               "census_gazetteer": {"retrieved_at": GAZ_AT, "source_url": C.GAZETTEER_SOURCE_URL,
                                    "count": 1, "vintage": C.GAZETTEER_VINTAGE}}
    for k in drop:
        sources.pop(k)
    return {"sources": sources}


def build_areas(tmp_path, world, name="out", man=None):
    raw = tmp_path / f"raw-{name}"
    world.land(raw)
    out = tmp_path / name
    ctx = BuildContext(db_path="", raw_dir=raw, out=out, manifest=man or manifest(), holders=[],
                       _provenance=build._provenance)
    return areas.publish(ctx), out


def load(out, level, st):
    return json.loads((out / "areas" / level / f"{st}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    counts, out = build_areas(tmp_path_factory.mktemp("areas"), World())
    return counts, out


# -- Sentinels: the Bureau's placeholders must never reach a reader ------------------
@pytest.mark.parametrize("sentinel", ["-666666666", "-999999999", "-888888888",
                                      "-222222222", "-333333333", "-555555555"])
def test_every_documented_sentinel_withholds_an_estimate_and_nulls_a_margin(sentinel):
    assert C.value(sentinel, None, "x") is None
    rec = acs_rec("x", {}, inc=sentinel, B19013_001M=sentinel)
    assert "median_household_income" not in C.survey_fields(rec, "x")       # estimate withheld
    rec = acs_rec("x", {}, inc="78000", B19013_001M=sentinel)
    assert C.survey_fields(rec, "x")["median_household_income"] == {"estimate": 78000, "moe": None}


def test_annotated_or_missing_values_are_withheld_even_when_a_number_is_present():
    # median+ carries the open interval's bound (250,001), which is not an estimate.
    assert C.value("250001", "median+", "x") is None
    assert C.value("2499", "median-", "x") is None
    assert C.value(None, None, "x") is None          # null = no data for the geography
    assert C.value("39.4", None, "x") == 39.4 and C.value("205000", None, "x") == 205000


def test_an_undocumented_negative_halts_instead_of_publishing_or_guessing():
    with pytest.raises(C.CensusError, match="undocumented negative"):
        C.value("-123456789", None, "x")
    with pytest.raises(C.CensusError, match="not a number"):
        C.value("lots", None, "x")


def test_published_files_carry_withheld_values_as_omissions_and_nulls(built):
    _, out = built
    tn = load(out, "county", "tn")["areas"]
    assert tn["47001"]["population"]["estimate"] == 1000              # Anderson: only what survived
    assert not {"households", "median_household_income", "median_age"} & set(tn["47001"])
    place = load(out, "place", "tn")["areas"]
    assert place["4733280"]["median_household_income"] == {"estimate": 50000, "moe": None}
    assert place["4733280"]["population"]["moe"] is None              # controlled: no margin
    assert "median_household_income" not in place["4728540"]          # open-ended median
    for f in (out / "areas").rglob("*.json"):
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"-\d{9}", text), f"a sentinel reached {f.name}"


# -- The writer ------------------------------------------------------------------------
def test_county_file_matches_the_contract_shape(built):
    counts, out = built
    doc = load(out, "county", "tn")
    assert doc["level"] == "county" and doc["state"] == "tn" and doc["schema_version"] == "1.0"
    assert doc["geography"]["vintage"] == 2024 and doc["survey"]["vintage"] == "2020-2024"
    assert list(doc["areas"]) == ["47001", "47165"]                   # sorted by GEOID
    assert doc["areas"]["47165"] == {
        "name": "Sumner County", "land_sqmi": 529.425,
        "population": {"estimate": 205000, "moe": None},
        "households": {"estimate": 76000, "moe": 900},
        "median_household_income": {"estimate": 78000, "moe": 2100},
        "median_age": {"estimate": 39.4, "moe": 0.3}}
    assert doc["generated_at"] == GAZ_AT                              # snapshot time, not the clock
    assert counts == {"area_counties": 52, "area_places": 54}       # TN has a 2nd county; TN two more cities, LA one


def test_every_state_and_dc_gets_both_files_and_territories_are_dropped(built):
    _, out = built
    for level in ("county", "place"):
        assert {p.stem for p in (out / "areas" / level).glob("*.json")} == set(C.STATES.values())
    assert not (out / "areas" / "county" / "pr.json").exists()
    assert '"72001"' not in "".join(p.read_text(encoding="utf-8") for p in (out / "areas").rglob("*.json"))


def test_places_are_incorporated_governments_only(built):
    _, out = built
    names = {a["name"] for a in load(out, "place", "tn")["areas"].values()}
    assert names == {"Hendersonville city", "Gallatin city",          # no CDP, no bare F row
                     "Nashville-Davidson metropolitan government (balance)"}
    assert "Baton Rouge city" in {a["name"] for a in load(out, "place", "la")["areas"].values()}
    assert list(load(out, "place", "tn")["areas"]) == ["4728540", "4733280", "4752006"]


def test_a_consolidated_city_county_is_published_with_its_facts(built):
    """Nashville is in the tile layer only as 4752006; clicking it must find a row."""
    _, out = built
    nashville = load(out, "place", "tn")["areas"]["4752006"]
    assert nashville["name"] == "Nashville-Davidson metropolitan government (balance)"
    assert nashville["land_sqmi"] == 7.891
    assert nashville["population"] == {"estimate": 1000, "moe": None}
    assert nashville["median_household_income"] == {"estimate": 50000, "moe": 1000}


def test_has_government_is_a_rule_over_funcstat_and_name_not_a_list():
    assert C.has_government("A", "Hendersonville city") and C.has_government("B", "Baton Rouge city")
    for geoid, name in [("0947515", "Milford city (balance)"),
                        ("1303440", "Athens-Clarke County unified government (balance)"),
                        ("1304204", "Augusta-Richmond County consolidated government (balance)"),
                        ("1836003", "Indianapolis city (balance)"),
                        ("2028412", "Greeley County unified government (balance)"),
                        ("2148006", "Louisville/Jefferson County metro government (balance)"),
                        ("3011397", "Butte-Silver Bow (balance)"),
                        ("4752006", "Nashville-Davidson metropolitan government (balance)")]:
        assert C.has_government("F", name), geoid
    assert not C.has_government("F", "Gamma remainder")             # fictitious, but not a "(balance)"
    assert not C.has_government("S", "Gamma city (balance)")        # "(balance)" alone is not enough
    assert not C.has_government("S", "Beta CDP")
    assert not C.has_government("I", "Old town") and not C.has_government("N", "Dormant village")


def test_non_ascii_names_survive_the_round_trip(built):
    _, out = built
    assert load(out, "county", "nm")["areas"]["35013"]["name"] == "Doña Ana County"


def test_each_block_is_cited_by_its_own_valid_envelope(built):
    _, out = built
    doc = load(out, "county", "tn")
    for block, source in (("geography", "census_gazetteer"), ("survey", "census_acs")):
        prov = doc[block]["provenance"]
        assert dossiers.REQUIRED_PROVENANCE <= set(prov) and all(prov[k] for k in dossiers.REQUIRED_PROVENANCE)
        assert prov["source"] == source and prov["grade"] == "A" and prov["grade_reason"] == "official_structured"
        dossiers._check_provenance(doc, block)
    assert doc["geography"]["provenance"]["retrieved_at"] == GAZ_AT
    assert doc["survey"]["provenance"]["retrieved_at"] == ACS_AT


def test_two_builds_are_byte_identical(tmp_path):
    _, a = build_areas(tmp_path, World(), "a")
    _, b = build_areas(tmp_path, World(), "b")
    files = sorted(p.relative_to(a) for p in a.rglob("*.json"))
    assert len(files) == 102
    assert files == sorted(p.relative_to(b) for p in b.rglob("*.json"))
    assert all((a / f).read_bytes() == (b / f).read_bytes() for f in files)


def test_writer_refuses_a_source_the_manifest_cannot_vouch_for(tmp_path):
    with pytest.raises(C.CensusError, match="census_gazetteer"):
        build_areas(tmp_path, World(), man=manifest(census_gazetteer=1))
    bad = manifest()
    bad["sources"]["census_acs"]["retrieved_at"] = None
    with pytest.raises(dossiers.ProvenanceError):
        build_areas(tmp_path, World(), "p", man=bad)


def test_without_a_survey_nothing_publishes_and_counts_say_so(tmp_path):
    counts, out = build_areas(tmp_path, World(), man=manifest(census_acs=1))
    assert counts == {"area_counties": 0, "area_places": 0} and not (out / "areas").exists()


def tree(out):
    """{relative path: (bytes, mtime_ns)} for every file under areas/."""
    return {p.relative_to(out).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted((out / "areas").rglob("*.json"))}


def test_a_night_without_the_key_leaves_an_already_published_tree_untouched(tmp_path):
    """The stale-snapshot, no-key night: the manifest drops census_acs (the fetcher returned
    None) while last night's snapshot is still on disk, and `out` already holds good files."""
    _, out = build_areas(tmp_path, World(), "pub")
    before = tree(out)
    assert len(before) == 102
    counts, again = build_areas(tmp_path, World(), "pub", man=manifest(census_acs=1))
    assert again == out and counts == {"area_counties": 0, "area_places": 0}
    assert tree(out) == before                          # same files, same bytes, not even rewritten


def test_a_failed_check_writes_no_partial_tree(tmp_path, monkeypatch):
    """A check that fails on the seventh file must not leave six new ones behind, whether
    `out` is empty or already holds a good published tree."""
    _, pub = build_areas(tmp_path, World(), "pub")
    before = tree(pub)
    real, seen = dossiers._check_provenance, []

    def fails_on_the_seventh(doc, section):
        seen.append(section)
        if len(seen) == 7:
            raise dossiers.ProvenanceError("synthetic failure")
        return real(doc, section)
    monkeypatch.setattr(dossiers, "_check_provenance", fails_on_the_seventh)
    with pytest.raises(dossiers.ProvenanceError, match="synthetic"):
        build_areas(tmp_path, World(), "pub")
    assert tree(pub) == before                          # nothing replaced
    seen.clear()
    with pytest.raises(dossiers.ProvenanceError, match="synthetic"):
        build_areas(tmp_path, World(), "empty")
    assert not (tmp_path / "empty" / "areas").exists()  # nothing half-written


def test_a_snapshot_of_another_vintage_halts(tmp_path):
    bad = manifest()
    bad["sources"]["census_acs"]["vintage"] = C.ACS_YEAR - 1
    with pytest.raises(C.CensusError, match="vintage"):
        build_areas(tmp_path, World(), man=bad)


def test_the_registry_runs_the_writer_and_its_counts_reach_coverage(slice_dirs):
    """Through the real ARTIFACT_WRITERS and build.run, not a hand-built context."""
    data = slice_dirs / "data"
    assert json.loads((data / "coverage.json").read_text())["counts"]["area_counties"] == 0   # no survey landed
    World().land(slice_dirs / "raw")
    man = json.loads((slice_dirs / "raw" / "manifest.json").read_text())
    man["sources"].update(manifest()["sources"])
    (slice_dirs / "raw" / "manifest.json").write_text(json.dumps(man))
    cov = build.run(db_path=str(slice_dirs / "wh.duckdb"), out_dir=data, raw_dir=slice_dirs / "raw")
    assert cov["counts"]["area_counties"] == 52 and cov["counts"]["area_places"] == 54
    assert {"census_acs", "census_gazetteer"} <= set(cov["sources"])
    assert load(data, "county", "tn")["areas"]["47165"]["population"]["estimate"] == 205000
    assert "Hendersonville city" in {a["name"] for a in load(data, "place", "tn")["areas"].values()}


# -- Gates fail closed -----------------------------------------------------------------
def test_control_total_gate_halts_when_counties_do_not_sum_to_the_state():
    w = World()
    counties, states = C.parse_acs(w.county_text(), ("state", "county"), "c"), C.parse_acs(
        w.state_text(), ("state",), "s")
    C.check_control_totals(counties, states)                              # agrees: passes
    states["47"]["B01003_001E"] = "206002"                                # within rounding: passes
    C.check_control_totals(counties, states)
    states["47"]["B01003_001E"] = "300000"                                # a lost or doubled county
    with pytest.raises(C.CensusError, match="sum to"):
        C.check_control_totals(counties, states)
    states["47"]["B01003_001E"] = "-666666666"                            # withheld: cannot reconcile
    with pytest.raises(C.CensusError, match="withheld"):
        C.check_control_totals(counties, states)


def test_control_total_gate_stops_the_build_and_the_fetch(tmp_path, monkeypatch):
    w = World()
    w.state_pop["47"] = "300000"                                          # the state's own figure disagrees
    with pytest.raises(C.CensusError, match="TN.*sum to"):
        build_areas(tmp_path, w)
    monkeypatch.setenv("CENSUS_API_KEY", KEY)
    monkeypatch.setattr(C, "_get_text", fake_api(w))
    with pytest.raises(C.CensusError, match="TN.*sum to"):
        C.fetch_acs(tmp_path / "raw", {})


def test_row_count_gate_halts_on_any_disagreement_between_survey_and_gazetteer(tmp_path):
    w = World()
    del w.counties["47001"]                                               # survey lost a county
    with pytest.raises(C.CensusError, match="TN county"):
        build_areas(tmp_path, w)
    w = World()
    del w.places["4733280"]                                               # a city we would publish
    with pytest.raises(C.CensusError, match="TN place"):
        build_areas(tmp_path, w, "b")
    w = World()
    del w.places["4752006"]                                               # so is a consolidated city-county
    with pytest.raises(C.CensusError, match="TN place.*4752006"):
        build_areas(tmp_path, w, "b2")
    w = World()
    del w.gaz_places["4733280"]                                           # survey knows a GEOID the Gazetteer never heard of
    with pytest.raises(C.CensusError, match="TN place"):
        build_areas(tmp_path, w, "c")
    w = World()
    del w.places["4720000"]                                               # a CDP missing from the survey is harmless
    build_areas(tmp_path, w, "d")


def test_value_domain_gate_halts_on_a_negative_that_is_not_a_documented_sentinel(tmp_path):
    w = World()
    w.counties["47165"]["B19013_001E"] = "-12345"
    with pytest.raises(C.CensusError, match="undocumented negative"):
        build_areas(tmp_path, w)
    w = World()
    w.gaz_counties["47165"][6] = "-1.5"
    with pytest.raises(C.CensusError, match="negative land area"):
        build_areas(tmp_path, w, "b")


def test_an_active_government_that_is_also_a_cdp_halts(tmp_path):
    w = World()
    w.gaz_places["0110000"][3] = "Odd CDP"
    with pytest.raises(C.CensusError, match="census designated place"):
        build_areas(tmp_path, w)
    w = World()
    w.gaz_places["0110000"][5] = "Z"
    with pytest.raises(C.CensusError, match="FUNCSTAT"):
        build_areas(tmp_path, w, "b")


def test_schema_drift_halts_rather_than_best_effort_parsing():
    w = World()
    reordered = json.loads(w.county_text())
    reordered[0][1], reordered[0][2] = reordered[0][2], reordered[0][1]
    with pytest.raises(C.CensusError, match="schema drift"):
        C.parse_acs(json.dumps(reordered), ("state", "county"), "c")
    with pytest.raises(C.CensusError, match="schema drift"):            # the 2025 layout: pipe-delimited + GEOIDFQ
        C.parse_gazetteer("USPS|GEOID|GEOIDFQ|ANSICODE|NAME|ALAND|AWATER|ALAND_SQMI|AWATER_SQMI"
                          "|INTPTLAT|INTPTLONG\nTN|47165|0500000US47165|1|Sumner County|1|1|529.4|1|1|1\n",
                          "county")
    truncated = json.loads(w.county_text())
    truncated[1] = truncated[1][:-1]
    with pytest.raises(C.CensusError, match="cells under"):
        C.parse_acs(json.dumps(truncated), ("state", "county"), "c")


def test_a_missing_key_page_is_a_clear_failure_not_a_json_error():
    html = "<html><head><title>Missing Key</title></head></html>"       # the Bureau answers HTTP 200 with this
    with pytest.raises(C.CensusError, match="CENSUS_API_KEY"):
        C.parse_acs(html, ("state",), "ACS state")


# -- Fetch -------------------------------------------------------------------------------
def fake_api(world, calls=None):
    def get(url):
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        if calls is not None:
            calls.append(url)
        if q["for"] == "county:*":
            return world.county_text()
        if q["for"] == "state:*":
            return world.state_text()
        return world.place_text(q["in"].split(":")[1])
    return get


def test_fetch_acs_lands_snapshots_and_the_key_goes_nowhere_public(tmp_path, monkeypatch):
    monkeypatch.setenv("CENSUS_API_KEY", KEY)
    calls: list[str] = []
    monkeypatch.setattr(C, "_get_text", fake_api(World(), calls))
    raw = tmp_path / "raw"
    frag = C.fetch_acs(raw, {})
    assert len(calls) == 1 + 1 + 51 and all(f"key={KEY}" in u for u in calls)     # one national, one state, 51 places
    assert any("for=county:*" in u for u in calls) and any("in=state:47" in u for u in calls)
    assert {"retrieved_at", "source_url", "count", "vintage", "file_sha256"} <= set(frag)
    assert frag["vintage"] == 2024 and frag["count"] > 0
    blob = json.dumps(frag) + "".join(p.read_text(encoding="utf-8") for p in raw.rglob("*") if p.is_file())
    assert KEY not in blob and "key=" not in blob
    assert len(list((raw / "census_acs" / "place").glob("*.json"))) == 51


def test_fetch_acs_without_a_key_is_absent_not_a_crash_and_says_so_loudly(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(C, "_get_text", lambda url: pytest.fail("a keyless request was sent"))
    assert C.fetch_acs(tmp_path / "raw", {}) is None
    line = capsys.readouterr().out.strip()
    assert len(line.splitlines()) == 1 and line.startswith("fetch: WARNING CENSUS_API_KEY is NOT SET")
    assert "SKIPPED" in line and "left untouched" in line
    monkeypatch.setenv("GITHUB_ACTIONS", "true")                          # becomes a run annotation
    C.fetch_acs(tmp_path / "raw", {})
    assert capsys.readouterr().out.startswith("::warning title=census_acs skipped::CENSUS_API_KEY is NOT SET")


def test_without_a_key_a_fresh_snapshot_is_reused_and_a_stale_one_drops_out_of_the_manifest(
        tmp_path, monkeypatch):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    now = datetime.now(timezone.utc)

    def prior(days):
        return {"sources": {"census_acs": {"retrieved_at": (now - timedelta(days=days)).isoformat(),
                                           "count": 7}}}
    with monkeypatch.context() as m:                                      # inside the 90-day SLA: no fetch at all
        m.setitem(fetch._FETCHERS, "census_acs", lambda *a: pytest.fail("fetched a fresh snapshot"))
        key, frag, status, _ = fetch._run_source("census_acs", tmp_path, prior(30), full=False)
    assert status == "fresh" and frag["count"] == 7
    key, frag, status, _ = fetch._run_source("census_acs", tmp_path, prior(120), full=False)
    assert (status, frag) == ("absent", None)                             # due, no key: not in the manifest
    key, frag, status, _ = fetch._run_source("census_acs", tmp_path, prior(30), full=True)
    assert (status, frag) == ("absent", None)                             # --full bypasses freshness too


def test_http_errors_never_echo_the_key(monkeypatch):
    monkeypatch.setenv("CENSUS_API_KEY", KEY)
    req = httpx.Request("GET", f"https://api.census.gov/data/2024/acs/acs5?get=NAME&key={KEY}")

    def boom(url):
        raise httpx.HTTPStatusError(f"Client error for url '{req.url}'", request=req,
                                    response=httpx.Response(400, request=req))
    monkeypatch.setattr(C, "_get", boom)
    with pytest.raises(C.CensusError) as e:
        C._get_text(C._acs_url(**{"for": "state:*"}))
    assert KEY not in str(e.value) and "<CENSUS_API_KEY>" in str(e.value)


def test_fetch_gazetteer_unpacks_the_zips_and_gates_what_it_lands(tmp_path, monkeypatch):
    w = World()
    names = {"counties": w.gaz_county_text(), "place": w.gaz_place_text()}

    def zipped(url):
        name = re.search(r"2024_Gaz_(\w+)_national\.zip", url).group(1)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(f"2024_Gaz_{name}_national.txt", names[name].encode("utf-8"))
        return buf.getvalue()
    monkeypatch.setattr(C, "_get_bytes", zipped)
    frag = C.fetch_gazetteer(tmp_path / "raw", {})
    assert frag["vintage"] == 2024 and frag["source_url"] == C.GAZETTEER_SOURCE_URL
    assert (tmp_path / "raw" / "census_gazetteer" / "place.txt").read_bytes() == names["place"].encode("utf-8")
    names["place"] = names["place"].replace("INTPTLAT", "LATITUDE")        # drifted layout
    with pytest.raises(C.CensusError, match="schema drift"):
        C.fetch_gazetteer(tmp_path / "raw2", {})


# -- Registration and freshness (WO-10 rules) ---------------------------------------------
def test_both_sources_are_registered_with_long_slas_and_a_default_grade():
    for key in ("census_acs", "census_gazetteer"):
        assert key in fetch._FETCHERS and key in SOURCES
        assert SOURCES[key].grade_reason == "official_structured" and SOURCES[key].freshness_sla_hours >= 24 * 90
    assert SOURCES["census_acs"].requires_api_key is True


def test_cold_start_fetches_and_a_young_snapshot_is_kept_with_its_original_stamp():
    assert rawlake.source_is_fresh({}, "census_acs") is False             # nothing hydrated: fetch
    now = datetime.now(timezone.utc)
    prior = {"sources": {"census_acs": {"retrieved_at": (now - timedelta(days=30)).isoformat()},
                         "census_gazetteer": {"retrieved_at": (now - timedelta(days=400)).isoformat()}}}
    assert rawlake.source_is_fresh(prior, "census_acs", now=now) is True        # 30d < 90d: re-fetch skipped
    assert rawlake.source_is_fresh(prior, "census_gazetteer", now=now) is False  # a year old: re-checked
