"""OCD-division identifiers for office-holders (data-contracts v1 §2/§5).

This is the join key between the map tiles and the serving data: the ocd_id a
House member resolves to here MUST equal the ocd_id `spike/stamp_ocd_ids.py`
stamps onto the matching Census polygon, or the style feed won't color it.
Convention (shared with the stamper):
  state           ocd-division/country:us/state:{usps}
  congressional   ocd-division/country:us/state:{usps}/cd:{n}   (at-large & delegates -> cd:1)
"""
from __future__ import annotations


def state_ocd(usps: str) -> str:
    return f"ocd-division/country:us/state:{usps.lower()}"


def house_ocd(usps: str, district: object) -> tuple[str, bool]:
    """(ocd_id, at_large) for a U.S. House seat. congress.gov reports at-large
    and non-voting-delegate seats as district 0/None; both stamp to cd:1 so the
    key matches the polygon (Census CDFP 00/98 -> cd:1 in the tile stamper)."""
    d = int(district) if str(district).isdigit() else 0
    at_large = d == 0
    return f"{state_ocd(usps)}/cd:{1 if at_large else d}", at_large
