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

Usage:  stamp_ocd_ids.py <level>       level ∈ {states,cd,sldu,sldl,county}
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

    raise SystemExit(f"unknown level: {level!r} (want states|cd|sldu|sldl|county)")


def stamp_stream(level: str, lines, out) -> int:
    """Transform a GeoJSONSeq stream. Returns count of features written."""
    written = 0
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
