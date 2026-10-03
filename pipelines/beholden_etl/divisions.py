"""OCD-division identifiers for office-holders (data-contracts v1 §2/§5).

This is the join key between the map tiles and the serving data: the ocd_id a
House member resolves to here MUST equal the ocd_id `spike/stamp_ocd_ids.py`
stamps onto the matching Census polygon, or the style feed won't color it.
Convention (shared with the stamper):
  state           ocd-division/country:us/state:{usps}
  congressional   ocd-division/country:us/state:{usps}/cd:{n}   (at-large & delegates -> cd:1)
  county          ocd-division/country:us/state:{usps}/county:{slug}   (AK borough:, LA parish:)
  place           ocd-division/country:us/state:{usps}/place:{slug}
  county seat     .../county:{slug}/council_district:{n}
  city ward       .../place:{slug}/ward:{n}
"""
from __future__ import annotations

import re


def state_ocd(usps: str) -> str:
    return f"ocd-division/country:us/state:{usps.lower()}"


def house_ocd(usps: str, district: object) -> tuple[str, bool]:
    """(ocd_id, at_large) for a U.S. House seat. congress.gov reports at-large
    and non-voting-delegate seats as district 0/None; both stamp to cd:1 so the
    key matches the polygon (Census CDFP 00/98 -> cd:1 in the tile stamper)."""
    d = int(district) if str(district).isdigit() else 0
    at_large = d == 0
    return f"{state_ocd(usps)}/cd:{1 if at_large else d}", at_large


_SLD_LEVEL = {"upper": "sldu", "lower": "sldl"}


def sld_ocd(usps: str, chamber: str, district: object) -> tuple[str, str] | None:
    """(ocd_id, level) for a state-legislative seat, or None if not mappable.
    chamber 'upper'->sldu, 'lower'->sldl. District is normalized identically to
    spike/stamp_ocd_ids.py (numeric -> int-string, else lowercased) so the key
    matches the polygon; states with named/lettered districts may not line up
    and simply stay uncolored until handled explicitly."""
    level = _SLD_LEVEL.get(chamber)
    if not level:
        return None
    d = str(district).strip()
    key = str(int(d)) if d.isdigit() else d.lower()
    if not key:
        return None
    return f"{state_ocd(usps)}/{level}:{key}", level


# ── Local divisions (WO-22) ─────────────────────────────────────────────────
# County-equivalents are not uniformly called counties: Alaska uses boroughs and
# Louisiana parishes, and the canonical ocd-division-ids registry reflects that
# in the id itself. The tile stamper keys this off Census FIPS; here we only have
# a USPS code, so the same two exceptions are spelled out by state.
_COUNTY_TYPE_BY_USPS: dict[str, str] = {"ak": "borough", "la": "parish"}


def _ocd_slug(name: str) -> str:
    """Slug a division NAME exactly as ocd-division-ids' make_id does.

    THIS MUST STAY BYTE-IDENTICAL to spike/stamp_ocd_ids.py:county_slug — the
    ocd_id built here is the join key against the polygon that file stamps, so a
    divergence silently leaves a division uncolored rather than raising. The
    duplication is deliberate (the stamper runs standalone in the tiles workflow,
    with no package on its path); test_local_slug_matches_tile_stamper pins the
    two implementations together across the punctuated cases that differ.

      'St. Clair' -> st_clair      "Prince George's" -> prince_george~s
      'Miami-Dade' -> miami-dade   "O'Brien"         -> o~brien
    """
    s = name.lower()
    s = re.sub(r"\.? ", "_", s)
    s = re.sub(r"[^\w0-9~_.-]", "~", s, flags=re.UNICODE)
    return s


def county_ocd(usps: str, name: str) -> str:
    """County/parish/borough division. `name` is the bare name as the Census and
    the canonical registry carry it ('Sumner', not 'Sumner County')."""
    usps = usps.lower()
    kind = _COUNTY_TYPE_BY_USPS.get(usps, "county")
    return f"{state_ocd(usps)}/{kind}:{_ocd_slug(name)}"


# GEOID -> slug for the places whose plain slug collides with another place in
# the same state (WO-21). MIRROR of spike/stamp_ocd_ids.py:PLACE_SLUG_OVERRIDES —
# the stamper runs standalone — and pinned equal by test_place_tiles. A roster
# for one of these places passes its `geoid` to place_ocd; with the name alone it
# slugs to an id no polygon carries, which is the safe failure.
PLACE_SLUG_OVERRIDES: dict[str, str] = {
    "1782088": "wilmington_1782088",  # IL Wilmington village
    "1782101": "wilmington_1782101",  # IL Wilmington city
    "1782309": "windsor_1782309",  # IL Windsor village
    "1782322": "windsor_1782322",  # IL Windsor city
    "2756680": "st_anthony_2756680",  # MN St. Anthony city
    "2756698": "st_anthony_2756698",  # MN St. Anthony city
    "3957750": "oakwood_3957750",  # OH Oakwood village
    "3957764": "oakwood_3957764",  # OH Oakwood city
    "3957792": "oakwood_3957792",  # OH Oakwood village
    "4212184": "centerville_4212184",  # PA Centerville borough
    "4212224": "centerville_4212224",  # PA Centerville borough
    "4214584": "coaldale_4214584",  # PA Coaldale borough
    "4214600": "coaldale_4214600",  # PA Coaldale borough
    "4227360": "franklin_4227360",  # PA Franklin borough
    "4227456": "franklin_4227456",  # PA Franklin city
    "4237880": "jefferson_4237880",  # PA Jefferson borough
    "4237944": "jefferson_4237944",  # PA Jefferson borough
    "4243064": "liberty_4243064",  # PA Liberty borough
    "4243128": "liberty_4243128",  # PA Liberty borough
    "4253336": "newburg_4253336",  # PA Newburg borough
    "4253344": "newburg_4253344",  # PA Newburg borough
    "4261496": "pleasantville_4261496",  # PA Pleasantville borough
    "4261512": "pleasantville_4261512",  # PA Pleasantville borough
    "4840738": "lakeside_4840738",  # TX Lakeside town
    "4840744": "lakeside_4840744",  # TX Lakeside town
    "4853154": "oak_ridge_4853154",  # TX Oak Ridge town
    "4853160": "oak_ridge_4853160",  # TX Oak Ridge town
    "4861592": "reno_4861592",  # TX Reno city
    "4861604": "reno_4861604",  # TX Reno city
    "5562240": "pewaukee_5562240",  # WI Pewaukee city
    "5562250": "pewaukee_5562250",  # WI Pewaukee village
    "5578650": "superior_5578650",  # WI Superior city
    "5578660": "superior_5578660",  # WI Superior village
    "5584250": "waukesha_5584250",  # WI Waukesha city
    "5584275": "waukesha_5584275",  # WI Waukesha village
    # Consolidated city-county governments. The Bureau names the place for the
    # government rather than the city ("Nashville-Davidson metropolitan government
    # (balance)"), which slugs to an id no roster would ever produce. Run against
    # the real cb_2025 file, that left Nashville, Louisville, Indianapolis, Augusta
    # and Athens unreachable. Slugs chosen for the city's common name; they are OUR
    # ids and have not been checked against the ocd-division-ids registry.
    "0947515": "milford",            # CT Milford city (balance)
    "1303440": "athens",             # GA Athens-Clarke County unified government (balance)
    "1304204": "augusta",            # GA Augusta-Richmond County consolidated government (balance)
    "1836003": "indianapolis",       # IN Indianapolis city (balance)
    "2028412": "greeley_county",     # KS Greeley County unified government (balance)
    # Not "louisville": the Bureau still carries the pre-merger Louisville city
    # (2148000) as its own place, and it holds the plain slug.
    "2148006": "louisville-jefferson_county",  # KY Louisville/Jefferson County metro government (balance)
    "3011397": "butte-silver_bow",   # MT Butte-Silver Bow (balance)
    "4732742": "hartsville",         # TN Hartsville/Trousdale County
    "4752006": "nashville",          # TN Nashville-Davidson metropolitan government (balance)
}


def place_ocd(usps: str, name: str, geoid: str | None = None) -> str:
    """Incorporated place (city/town). Census PLACE NAME is bare of its legal
    suffix in the cartographic files, matching the registry's slug. `geoid`
    (7-digit state+place FIPS) selects a PLACE_SLUG_OVERRIDES entry when the
    name alone is ambiguous within the state."""
    slug = PLACE_SLUG_OVERRIDES.get(geoid or "") or _ocd_slug(name)
    return f"{state_ocd(usps)}/place:{slug}"


def _seat_ocd(parent_ocd: str, kind: str, district: object) -> str | None:
    """Numbered seat inside a local division. Districts are normalized the same
    way sld_ocd does it (numeric -> int-string, else lowercased) so '01', '1' and
    1 all land on one id — a county that renumbers its own labels must not split
    a district in two."""
    d = str(district).strip()
    if not d:
        return None
    key = str(int(d)) if d.isdigit() else d.lower()
    return f"{parent_ocd}/{kind}:{key}"


def commission_district_ocd(county_ocd_id: str, district: object) -> str | None:
    """A county legislative seat (commission/supervisor district)."""
    return _seat_ocd(county_ocd_id, "council_district", district)


def ward_ocd(place_ocd_id: str, ward: object) -> str | None:
    """A municipal ward. Hendersonville elects two aldermen per ward, so this id
    is NOT unique per person — it is the division, and two terms point at it."""
    return _seat_ocd(place_ocd_id, "ward", ward)
