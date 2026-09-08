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


def place_ocd(usps: str, name: str) -> str:
    """Incorporated place (city/town). Census PLACE NAME is bare of its legal
    suffix in the cartographic files, matching the registry's slug."""
    return f"{state_ocd(usps)}/place:{_ocd_slug(name)}"


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
