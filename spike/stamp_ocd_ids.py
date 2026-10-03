#!/usr/bin/env python3
"""E6-2: stamp OCD-IDs onto Census cartographic-boundary features.

Reads a GeoJSONSeq stream (one GeoJSON Feature per line, as emitted by
`ogr2ogr -f GeoJSONSeq /vsistdout/`) on stdin, replaces each feature's
properties with the *tile contract* property set (data-contracts v1 §5),
and writes GeoJSONSeq to stdout for tippecanoe to consume.

Tiles carry geometry + OCD-ID **only** — no member/party data is ever baked
in. The client joins a style feed (`/stylefeeds/{layer}.json`) keyed on the
same `ocd_id` this script produces, so the OCD convention here MUST match the
convention the ETL uses when it assigns divisions to office-holders
(see beholden_etl.divisions). That shared key is the whole join.

Usage:  stamp_ocd_ids.py <level>       level ∈ {states,cd,sldu,sldl,county,place}
"""
from __future__ import annotations

import json
import re
import sys

# Census STATEFP (FIPS) -> USPS postal code, incl. DC + territories with
# congressional representation. Every layer carries STATEFP, so deriving the
# state slug from FIPS keeps the four layers uniform (STUSPS only ships on the
# state file).
FIPS_TO_USPS: dict[str, str] = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
    "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
    "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY", "60": "AS", "66": "GU", "69": "MP",
    "72": "PR", "78": "VI",
}


def _get(props: dict, *names: str) -> str | None:
    """Case-insensitive first-hit lookup; Census attribute casing varies."""
    lower = {k.lower(): v for k, v in props.items()}
    for n in names:
        v = lower.get(n.lower())
        if v not in (None, ""):
            return str(v)
    return None


def state_ocd(usps: str) -> str:
    return f"ocd-division/country:us/state:{usps.lower()}"


def cd_number(cdfp: str | None) -> tuple[int, bool]:
    """(district_num, at_large). Census CDxxxFP: '00' = at-large single seat,
    '98' = non-voting delegate seat (DC/territories), else the seat number."""
    n = int(cdfp) if (cdfp and cdfp.isdigit()) else 0
    if n in (0, 98):          # at-large and non-voting delegates -> seat 1
        return 1, (n == 0)
    return n, False


def sld_district(code: str | None) -> str:
    """State-leg district identifier for the OCD slug. Census SLDUST/SLDLST is
    a zero-padded code; a handful of states use non-numeric codes (kept as-is,
    lowercased). ZZZ = 'not defined'/at-large-of-record -> dropped by caller."""
    code = (code or "").strip()
    if code.isdigit():
        return str(int(code))     # strip leading zeros: '007' -> '7'
    return code.lower()


# County-equivalents are typed by state in the canonical ocd-division-ids repo:
# Alaska uses `borough`, Louisiana uses `parish`, everyone else uses `county`.
# STATEFP (FIPS) is the reliable discriminator (TIGER's LSAD encodes the same
# distinction but the FIPS-based rule is unambiguous and needs no LSAD table).
# Verified against
# https://raw.githubusercontent.com/opencivicdata/ocd-division-ids/master/identifiers/country-us.csv
# e.g. .../state:ak/borough:anchorage, .../state:la/parish:acadia,
#      .../state:tn/county:anderson  (the flat `county:` the WO assumed is wrong
#      for AK/LA — see the module report for the divergence).
COUNTY_TYPE_BY_FIPS: dict[str, str] = {"02": "borough", "22": "parish"}


def county_slug(name: str) -> str:
    """Slug a county/parish/borough NAME exactly as ocd-division-ids' make_id does
    (scripts/country-us/census_places.py): lowercase, an optional period + space
    collapses to '_', then any remaining non-[word/~/_/./-] char becomes '~'.

    Mirrors these real ids (spot-checked against the canonical repo):
      'St. Clair'       -> st_clair          'Miami-Dade'      -> miami-dade
      "St. Mary's"      -> st_mary~s         "O'Brien"         -> o~brien
      "Prince George's" -> prince_george~s   'Del Norte'       -> del_norte
    The TIGER NAME field is bare ('St. Clair', not 'St. Clair County'), so the
    ' County'/' Parish'/' Borough' suffix is already absent — no need to strip it.
    """
    s = name.lower()
    s = re.sub(r"\.? ", "_", s)                          # 'st. clair' -> 'st_clair'
    s = re.sub(r"[^\w0-9~_.-]", "~", s, flags=re.UNICODE)  # "mary's" -> 'mary~s'
    return s


# --- incorporated places (WO-21, data-contracts 8.5) ------------------------
# The place file mixes incorporated places with Census designated places, which
# are statistical areas with no government. The Bureau's own feature catalog for
# cb_*_us_place_500k lists the LSAD codes: 57 = CDP, and 55 (comunidad) / 62
# (zona urbana) are the Puerto Rico equivalents. A place is dropped if its LSAD
# is one of those OR its descriptor (NAMELSAD minus NAME) is, so a Bureau change
# to either field alone cannot let a CDP through.
CDP_LSAD = frozenset({"55", "57", "62"})
CDP_KINDS = frozenset({"cdp", "comunidad", "zona urbana"})

# GEOID -> slug. Two places in one state can slug to the same ocd_id (PA has
# two Centerville boroughs; WI has a Waukesha city and a Waukesha village). A
# duplicate fails the build (stamp_stream); it is resolved HERE, per GEOID, and
# never by keeping one. Every member of a colliding group is listed, so the
# plain slug is published for none of them and a roster that slugs by name
# alone matches no polygon rather than the wrong one. Mirrored in
# beholden_etl.divisions.PLACE_SLUG_OVERRIDES (the stamper runs standalone);
# test_place_tiles pins the two equal. Seeded from the Bureau's TIGERweb place
# layer; a collision the first real build finds is a new line here and there.
PLACE_SLUG_OVERRIDES: dict[str, str] = {
    "1782088": "wilmington~1782088",  # IL Wilmington village
    "1782101": "wilmington~1782101",  # IL Wilmington city
    "1782309": "windsor~1782309",  # IL Windsor village
    "1782322": "windsor~1782322",  # IL Windsor city
    "2756680": "st_anthony~2756680",  # MN St. Anthony city
    "2756698": "st_anthony~2756698",  # MN St. Anthony city
    "3957750": "oakwood~3957750",  # OH Oakwood village
    "3957764": "oakwood~3957764",  # OH Oakwood city
    "3957792": "oakwood~3957792",  # OH Oakwood village
    "4212184": "centerville~4212184",  # PA Centerville borough
    "4212224": "centerville~4212224",  # PA Centerville borough
    "4214584": "coaldale~4214584",  # PA Coaldale borough
    "4214600": "coaldale~4214600",  # PA Coaldale borough
    "4227360": "franklin~4227360",  # PA Franklin borough
    "4227456": "franklin~4227456",  # PA Franklin city
    "4237880": "jefferson~4237880",  # PA Jefferson borough
    "4237944": "jefferson~4237944",  # PA Jefferson borough
    "4243064": "liberty~4243064",  # PA Liberty borough
    "4243128": "liberty~4243128",  # PA Liberty borough
    "4253336": "newburg~4253336",  # PA Newburg borough
    "4253344": "newburg~4253344",  # PA Newburg borough
    "4261496": "pleasantville~4261496",  # PA Pleasantville borough
    "4261512": "pleasantville~4261512",  # PA Pleasantville borough
    "4840738": "lakeside~4840738",  # TX Lakeside town
    "4840744": "lakeside~4840744",  # TX Lakeside town
    "4853154": "oak_ridge~4853154",  # TX Oak Ridge town
    "4853160": "oak_ridge~4853160",  # TX Oak Ridge town
    "4861592": "reno~4861592",  # TX Reno city
    "4861604": "reno~4861604",  # TX Reno city
    "5562240": "pewaukee~5562240",  # WI Pewaukee city
    "5562250": "pewaukee~5562250",  # WI Pewaukee village
    "5578650": "superior~5578650",  # WI Superior city
    "5578660": "superior~5578660",  # WI Superior village
    "5584250": "waukesha~5584250",  # WI Waukesha city
    "5584275": "waukesha~5584275",  # WI Waukesha village
}


def place_kind(name: str, namelsad: str) -> str:
    """The Bureau's descriptor for a place: NAMELSAD with the NAME prefix removed,
    '(balance)' stripped, lowercased -- 'Hendersonville city' -> 'city', and
    'Milford city (balance)' with NAME 'Milford' -> 'city'. Empty when the Bureau
    gives no descriptor (LSAD 00). NAMELSAD is NAME + descriptor by construction,
    so a mismatch means the file is not what we think it is: stop."""
    if not namelsad.startswith(name):
        raise SystemExit(f"stamp_ocd_ids: place NAMELSAD {namelsad!r} does not start with NAME {name!r}")
    return " ".join(namelsad[len(name):].replace("(balance)", "").split()).lower()


def feature_props(level: str, src: dict) -> dict | None:
    """Map raw Census attributes -> tile-contract properties, or None to drop
    the feature (e.g. undefined SLD districts that carry no representation)."""
    statefp = _get(src, "STATEFP", "STATE")
    usps = FIPS_TO_USPS.get(statefp or "")
    if not usps:
        return None               # unknown/foreign FIPS -> not a US division

    if level == "states":
        return {
            "ocd_id": state_ocd(usps),
            "name": _get(src, "NAME", "NAMELSAD") or usps,
            "geoid": _get(src, "GEOID", "STATEFP"),
        }

    if level == "cd":
        num, at_large = cd_number(_get(src, "CD119FP", "CD118FP", "CDFP", "CD"))
        return {
            "ocd_id": f"{state_ocd(usps)}/cd:{num}",
            "state": usps,
            "district_num": num,
            "at_large": at_large,
        }

    if level in ("sldu", "sldl"):
        code = _get(src, "SLDUST" if level == "sldu" else "SLDLST", "GEOID")
        district = sld_district(code)
        if not district or district in ("zzz", "0"):
            return None
        return {
            "ocd_id": f"{state_ocd(usps)}/{level}:{district}",
            "state": usps,
            "chamber": "upper" if level == "sldu" else "lower",
            "district_num": district,
        }

    if level == "county":
        name = _get(src, "NAME", "NAMELSAD")
        if not name:
            return None
        div_type = COUNTY_TYPE_BY_FIPS.get(statefp or "", "county")
        return {
            "ocd_id": f"{state_ocd(usps)}/{div_type}:{county_slug(name)}",
            "state": usps,
            "name": name,
            "geoid": _get(src, "GEOID"),   # 5-digit STATEFP+COUNTYFP
        }

    if level == "place":
        name, geoid, namelsad = (_get(src, k) for k in ("NAME", "GEOID", "NAMELSAD"))
        if not (name and namelsad and re.fullmatch(r"\d{7}", geoid or "")):
            raise SystemExit(f"stamp_ocd_ids: place without NAME, NAMELSAD and a 7-digit GEOID: {src!r}")
        kind = place_kind(name, namelsad)
        if _get(src, "LSAD") in CDP_LSAD or kind in CDP_KINDS:
            return None           # statistical area, no government
        # The county slug rule IS the place slug rule (divisions._ocd_slug serves both).
        slug = PLACE_SLUG_OVERRIDES.get(geoid) or county_slug(name)
        return {
            "ocd_id": f"{state_ocd(usps)}/place:{slug}",
            "geoid": geoid,            # STATEFP+PLACEFP, the join key to the area facts
            "state": usps,
            "name": name,
            "kind": kind,
        }

    raise SystemExit(f"unknown level: {level!r} (want states|cd|sldu|sldl|county|place)")


def stamp_stream(level: str, lines, out) -> int:
    """Transform a GeoJSONSeq stream. Returns count of features written. Exits
    non-zero if two places stamp the same ocd_id (see PLACE_SLUG_OVERRIDES)."""
    written = 0
    place_geoids: dict[str, list[str]] = {}      # place ocd_id -> GEOIDs claiming it
    for raw in lines:
        raw = raw.strip().lstrip("\x1e")   # tolerate RFC 8142 record separators
        if not raw:
            continue
        feat = json.loads(raw)
        props = feature_props(level, feat.get("properties") or {})
        if props is None:
            continue
        feat["properties"] = props
        out.write(json.dumps(feat, separators=(",", ":")) + "\n")
        written += 1
        if level == "place":
            place_geoids.setdefault(props["ocd_id"], []).append(props["geoid"])
    dupes = {k: v for k, v in place_geoids.items() if len(v) > 1}
    if dupes:
        raise SystemExit(
            "stamp_ocd_ids: duplicate place ocd_id; add each GEOID to PLACE_SLUG_OVERRIDES "
            "(here and in beholden_etl.divisions): "
            + "; ".join(f"{k} <- {', '.join(g)}" for k, g in sorted(dupes.items())))
    return written


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write(__doc__ or "")
        return 2
    n = stamp_stream(argv[0], sys.stdin, sys.stdout)
    sys.stderr.write(f"stamp_ocd_ids: wrote {n} {argv[0]} features\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
