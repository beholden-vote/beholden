"""WO-21: the incorporated-place tile level of spike/stamp_ocd_ids.py.

The real tile build needs GDAL and tippecanoe, so it only runs in the tiles-build
workflow. Everything the stamper decides, though, is plain Python over a
GeoJSONSeq stream, and that is what these tests exercise: which features survive
(incorporated places, never Census designated places), the property set of
data-contracts 8.5, the slug that joins a polygon to the officials pinned to it,
and the build failure on a duplicate ocd_id.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys

import pytest

from beholden_etl import divisions
from beholden_etl.sources import tn_local
from test_pipeline import REPO, _load_stamper


def _feature(geoid: str, name: str, namelsad: str, lsad: str = "25") -> dict:
    """One feature as `ogr2ogr -f GeoJSONSeq` emits it from cb_*_us_place_500k:
    the Bureau's attribute set, with the geometry we never touch."""
    return {
        "type": "Feature",
        "properties": {
            "STATEFP": geoid[:2], "PLACEFP": geoid[2:], "GEOID": geoid,
            "NAME": name, "NAMELSAD": namelsad, "LSAD": lsad,
            "ALAND": 1000, "AWATER": 0,
        },
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
    }


def _stamp(stamper, *features: dict) -> list[dict]:
    """Run features through stamp_stream('place') and return what it wrote."""
    lines = [json.dumps(f) for f in features]
    out = io.StringIO()
    stamper.stamp_stream("place", lines, out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


# --- the slug is the pipeline's slug -----------------------------------------
# name -> (state FIPS, the slug both sides must produce). The slugs are pinned
# literally as well as compared, so the two implementations cannot drift together.
SLUG_CASES = {
    "St. Louis": ("29", "st_louis"),
    "Winston-Salem": ("37", "winston-salem"),
    "Coeur d'Alene": ("16", "coeur_d~alene"),
    "Ho-Ho-Kus": ("34", "ho-ho-kus"),
    "Truth or Consequences": ("35", "truth_or_consequences"),
    "Ste. Genevieve": ("29", "ste_genevieve"),
    "O'Fallon": ("17", "o~fallon"),
    "La Cañada Flintridge": ("06", "la_cañada_flintridge"),
    "Nashville-Davidson": ("47", "nashville-davidson"),
}


def test_place_slug_matches_pipeline_place_ocd():
    """THE join-key invariant, for places. Roster adapters build an official's
    ocd_id with divisions.place_ocd; the pin is found by matching it to the
    polygon this stamper emits. They are separate implementations (the stamper
    runs standalone, with no package on its path) and a divergence does not
    raise: the city's officials silently vanish from the map. So the two are
    pinned together over exactly the names a naive slug gets wrong."""
    stamper = _load_stamper()
    for i, (name, (fips, slug)) in enumerate(SLUG_CASES.items(), start=1):
        usps = stamper.FIPS_TO_USPS[fips]
        props = stamper.feature_props("place", _feature(f"{fips}9{i:04d}", name, f"{name} city")["properties"])
        assert props["ocd_id"] == divisions.place_ocd(usps, name), name
        assert props["ocd_id"] == f"ocd-division/country:us/state:{usps.lower()}/place:{slug}", name


# --- incorporated places only ------------------------------------------------
def test_designated_places_are_dropped():
    stamper = _load_stamper()
    kept = _stamp(
        stamper,
        _feature("4737640", "Hendersonville", "Hendersonville city", "25"),
        _feature("1571550", "Honolulu", "Honolulu CDP", "57"),                  # CDP by LSAD and descriptor
        _feature("7200470", "Aguas Claras", "Aguas Claras comunidad", "55"),    # Puerto Rico CDP
        _feature("7200941", "Adjuntas", "Adjuntas zona urbana", "62"),          # Puerto Rico CDP
        _feature("0600001", "Sample Heights", "Sample Heights CDP", "25"),      # descriptor alone says CDP
        _feature("0600002", "Sample Park", "Sample Park city", "57"),           # LSAD alone says CDP
        _feature("9900001", "Nowhere", "Nowhere city", "25"),                   # foreign FIPS
    )
    assert [f["properties"]["geoid"] for f in kept] == ["4737640"]


# --- every 8.5 property, present and typed -----------------------------------
# (feature, expected kind). The Bureau's descriptor, lowercased; blank when the
# Bureau gives none; '(balance)' stripped.
KIND_CASES = [
    (_feature("4737640", "Hendersonville", "Hendersonville city", "25"), "city"),
    (_feature("4227360", "Franklin", "Franklin borough", "21"), "borough"),
    (_feature("5584275", "Waukesha", "Waukesha village", "47"), "village"),
    (_feature("4840738", "Lakeside", "Lakeside town", "43"), "town"),
    (_feature("0236400", "Juneau", "Juneau city and borough", "53"), "city and borough"),
    (_feature("0947515", "Milford", "Milford city (balance)", "00"), "city"),
    (_feature("4752006", "Nashville-Davidson", "Nashville-Davidson metropolitan government (balance)", "MG"),
     "metropolitan government"),
    (_feature("3209700", "Carson City", "Carson City", "00"), ""),
]


def test_every_place_property_is_present_and_typed():
    stamper = _load_stamper()
    out = _stamp(stamper, *(f for f, _ in KIND_CASES))
    assert len(out) == len(KIND_CASES)
    for feat, (src, kind) in zip(out, KIND_CASES):
        props = feat["properties"]
        # Exactly the contract's set: no Census attribute leaks into a tile.
        assert set(props) == {"ocd_id", "geoid", "state", "name", "kind"}
        assert all(isinstance(v, str) for v in props.values())
        assert props["geoid"] == src["properties"]["GEOID"] and len(props["geoid"]) == 7
        assert props["state"] == stamper.FIPS_TO_USPS[props["geoid"][:2]]
        assert props["name"] == src["properties"]["NAME"]
        assert props["kind"] == kind
        assert props["ocd_id"].startswith(f"ocd-division/country:us/state:{props['state'].lower()}/place:")
        assert feat["geometry"] == src["geometry"]            # geometry passes through untouched


def test_the_stamped_example_from_the_contract():
    stamper = _load_stamper()
    [feat] = _stamp(stamper, _feature("4737640", "Hendersonville", "Hendersonville city"))
    assert feat["properties"] == {
        "ocd_id": "ocd-division/country:us/state:tn/place:hendersonville",
        "geoid": "4737640", "state": "TN", "name": "Hendersonville", "kind": "city"}
    # ...and it is the id the one published city roster pins its officials to.
    assert feat["properties"]["ocd_id"] == divisions.place_ocd("TN", tn_local.HENDERSONVILLE_PLACE_NAME)


def test_a_place_feature_that_is_not_what_we_think_stops_the_build():
    stamper = _load_stamper()
    bad_geoid = _feature("4737640", "Hendersonville", "Hendersonville city")
    bad_geoid["properties"]["GEOID"] = "47"
    for src in (bad_geoid["properties"],
                {"STATEFP": "47", "GEOID": "4737640", "NAME": "Hendersonville"},          # no NAMELSAD
                {"STATEFP": "47", "GEOID": "4737640", "NAME": "Hendersonville",
                 "NAMELSAD": "Gallatin city"}):                                           # not NAME + descriptor
        with pytest.raises(SystemExit):
            stamper.feature_props("place", src)


# --- a duplicate ocd_id fails the build --------------------------------------
# Real groups of incorporated places that share a name within a state, from the
# Bureau's TIGERweb place layer: (GEOID, NAME, NAMELSAD). Every member must be
# resolved by an override; the plain slug is published for none of them.
REAL_COLLISIONS = [
    ("1782088", "Wilmington", "Wilmington village"),
    ("1782101", "Wilmington", "Wilmington city"),
    ("1782309", "Windsor", "Windsor village"),
    ("1782322", "Windsor", "Windsor city"),
    ("2756680", "St. Anthony", "St. Anthony city"),
    ("2756698", "St. Anthony", "St. Anthony city"),
    ("3957750", "Oakwood", "Oakwood village"),
    ("3957764", "Oakwood", "Oakwood city"),
    ("3957792", "Oakwood", "Oakwood village"),
    ("4212184", "Centerville", "Centerville borough"),
    ("4212224", "Centerville", "Centerville borough"),
    ("4214584", "Coaldale", "Coaldale borough"),
    ("4214600", "Coaldale", "Coaldale borough"),
    ("4227360", "Franklin", "Franklin borough"),
    ("4227456", "Franklin", "Franklin city"),
    ("4237880", "Jefferson", "Jefferson borough"),
    ("4237944", "Jefferson", "Jefferson borough"),
    ("4243064", "Liberty", "Liberty borough"),
    ("4243128", "Liberty", "Liberty borough"),
    ("4253336", "Newburg", "Newburg borough"),
    ("4253344", "Newburg", "Newburg borough"),
    ("4261496", "Pleasantville", "Pleasantville borough"),
    ("4261512", "Pleasantville", "Pleasantville borough"),
    ("4840738", "Lakeside", "Lakeside town"),
    ("4840744", "Lakeside", "Lakeside town"),
    ("4853154", "Oak Ridge", "Oak Ridge town"),
    ("4853160", "Oak Ridge", "Oak Ridge town"),
    ("4861592", "Reno", "Reno city"),
    ("4861604", "Reno", "Reno city"),
    ("5562240", "Pewaukee", "Pewaukee city"),
    ("5562250", "Pewaukee", "Pewaukee village"),
    ("5578650", "Superior", "Superior city"),
    ("5578660", "Superior", "Superior village"),
    ("5584250", "Waukesha", "Waukesha city"),
    ("5584275", "Waukesha", "Waukesha village"),
]


def test_a_duplicate_ocd_id_fails_the_stamper_and_names_the_geoids():
    stamper = _load_stamper()
    twins = [_feature("4212184", "Centerville", "Centerville borough", "21"),
             _feature("4212224", "Centerville", "Centerville borough", "21")]
    stamper.PLACE_SLUG_OVERRIDES = {}      # the module is loaded fresh per call; no restore needed
    with pytest.raises(SystemExit) as exc:
        _stamp(stamper, *twins)
    msg = str(exc.value)
    assert "4212184" in msg and "4212224" in msg
    assert "ocd-division/country:us/state:pa/place:centerville" in msg


def test_the_stamper_process_exits_non_zero_on_a_duplicate():
    """What the shell sees: the build's `ogr2ogr | stamp_ocd_ids.py > file` only
    aborts if the process itself exits non-zero, and CI reads its stderr."""
    twins = "\n".join(json.dumps(_feature(g, "Springfield", "Springfield city")) for g in ("1700001", "1700002"))
    run = subprocess.run([sys.executable, str(REPO / "spike" / "stamp_ocd_ids.py"), "place"],
                         input=twins, capture_output=True, text=True, encoding="utf-8")
    assert run.returncode != 0
    assert "1700001" in run.stderr and "1700002" in run.stderr


def test_every_known_collision_is_resolved_by_an_override():
    stamper = _load_stamper()
    out = _stamp(stamper, *(_feature(g, n, nl, "25") for g, n, nl in REAL_COLLISIONS))
    ids = [f["properties"]["ocd_id"] for f in out]
    assert len(ids) == len(REAL_COLLISIONS) == len(set(ids))
    # ...and it is the table that does it: without it the same input must fail.
    stamper.PLACE_SLUG_OVERRIDES = {}
    with pytest.raises(SystemExit):
        _stamp(stamper, *(_feature(g, n, nl, "25") for g, n, nl in REAL_COLLISIONS))


# --- the override table is one table, in two places --------------------------
def test_override_table_is_mirrored_between_stamper_and_divisions():
    stamper = _load_stamper()
    assert stamper.PLACE_SLUG_OVERRIDES == divisions.PLACE_SLUG_OVERRIDES
    # The table holds exactly two kinds of entry: same-name collisions and
    # consolidated governments. Anything else in it is unexplained.
    assert ({g for g, _, _ in REAL_COLLISIONS} | {g for g, *_ in CONSOLIDATED}
            == set(divisions.PLACE_SLUG_OVERRIDES))
    # Distinct ids, or the table would be the collision it exists to resolve.
    assert len(set(divisions.PLACE_SLUG_OVERRIDES.values())) == len(divisions.PLACE_SLUG_OVERRIDES)
    # And place_ocd with a geoid lands on the id the stamper puts on that polygon.
    for geoid, name, namelsad in REAL_COLLISIONS:
        usps = stamper.FIPS_TO_USPS[geoid[:2]]
        [feat] = _stamp(stamper, _feature(geoid, name, namelsad))
        assert feat["properties"]["ocd_id"] == divisions.place_ocd(usps, name, geoid)
        assert divisions.place_ocd(usps, name) != feat["properties"]["ocd_id"]   # name alone matches no polygon


# --- consolidated governments -------------------------------------------------
# (GEOID, the Bureau's NAME — which is also its NAMELSAD at LSAD 00 —, the slug,
# the display name, the kind). Taken from the real cb_2025_us_place_500k
# attribute table, where every one of these stamped an id no roster could
# produce ("place:nashville-davidson_metropolitan_government_~balance~") and an
# empty kind.
CONSOLIDATED = [
    ("0947515", "Milford city (balance)", "milford", "Milford", "city"),
    ("1303440", "Athens-Clarke County unified government (balance)", "athens",
     "Athens-Clarke County", "unified government"),
    ("1304204", "Augusta-Richmond County consolidated government (balance)", "augusta",
     "Augusta-Richmond County", "consolidated government"),
    ("1836003", "Indianapolis city (balance)", "indianapolis", "Indianapolis", "city"),
    ("2028412", "Greeley County unified government (balance)", "greeley_county",
     "Greeley County", "unified government"),
    ("2148006", "Louisville/Jefferson County metro government (balance)",
     "louisville-jefferson_county", "Louisville/Jefferson County", "metro government"),
    ("3011397", "Butte-Silver Bow (balance)", "butte-silver_bow", "Butte-Silver Bow", ""),
    ("4732742", "Hartsville/Trousdale County", "hartsville", "Hartsville/Trousdale County", ""),
    ("4752006", "Nashville-Davidson metropolitan government (balance)", "nashville",
     "Nashville-Davidson", "metropolitan government"),
]


def test_consolidated_governments_get_a_usable_id_name_and_kind():
    """The Bureau names a consolidated city-county for its government, not the
    city. Stamped as-is, Nashville's polygon carried an id built from that whole
    title, so officials pinned to "Nashville" matched nothing and the city was
    unreachable from the map."""
    stamper = _load_stamper()
    for geoid, bureau_name, slug, display, kind in CONSOLIDATED:
        props = stamper.feature_props(
            "place", _feature(geoid, bureau_name, bureau_name, "00")["properties"])
        assert props["ocd_id"].endswith(f"/place:{slug}"), geoid
        assert (props["name"], props["kind"]) == (display, kind), geoid
        assert "balance" not in props["ocd_id"] and "balance" not in props["name"]
        # ...and the pipeline, given the geoid, lands on the same polygon.
        assert divisions.place_ocd(props["state"], display, geoid=geoid) == props["ocd_id"]


def test_a_descriptor_is_split_off_only_when_it_is_one():
    """'Carson City' ends in a word that is also a descriptor. It is a name; the
    match is on the Bureau's lowercase descriptor, so it is left whole."""
    stamper = _load_stamper()
    props = stamper.feature_props("place", _feature("3209700", "Carson City", "Carson City", "00")["properties"])
    assert (props["name"], props["kind"]) == ("Carson City", "")
    # An ordinary place is untouched by any of this.
    props = stamper.feature_props("place", _feature("4737640", "Hendersonville", "Hendersonville city")["properties"])
    assert (props["name"], props["kind"]) == ("Hendersonville", "city")


def test_no_override_slug_uses_the_apostrophe_marker_as_a_separator():
    """In an OCD slug '~' stands for an apostrophe (o~fallon) and the client
    renders it as one, so a collision suffix written 'wilmington~1782088' would
    display as Wilmington'1782088."""
    import re
    assert not [v for v in divisions.PLACE_SLUG_OVERRIDES.values() if re.search(r"~\d", v)]
