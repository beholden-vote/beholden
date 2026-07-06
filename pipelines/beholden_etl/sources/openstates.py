"""OpenStates current state legislators (ticket E4).

Bulk CSV per state — no API key, no rate limit:
  data.openstates.org/people/current/{state}.csv
Gives every sitting state legislator with party, chamber (upper/lower), district,
photo and official-source links. Mapped to the sldu/sldl map layers through the
shared OCD convention (beholden_etl.divisions.sld_ocd).
"""
from __future__ import annotations

import csv
import io

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import SOURCES

# States + DC + PR with OpenStates coverage (lowercase USPS slugs).
STATE_SLUGS = [
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
    "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
    "wi", "wy", "dc", "pr",
]


def people_url(state: str) -> str:
    return f"{SOURCES['openstates'].base_url}/people/current/{state}.csv"


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=60))
def fetch_people_csv(state: str) -> str:
    r = httpx.get(people_url(state), timeout=60, follow_redirects=True)
    r.raise_for_status()
    return r.text


def to_person_rows(csv_text: str):
    """Yield one normalized dict per current state legislator (upper/lower only)."""
    for row in csv.DictReader(io.StringIO(csv_text)):
        pid = row.get("id")                       # ocd-person/<uuid>
        chamber = row.get("current_chamber")      # 'upper' | 'lower'
        district = row.get("current_district")
        if not pid or chamber not in ("upper", "lower") or not district:
            continue
        srcs = [s for s in (row.get("sources") or "").split(";") if s.strip()]
        yield {
            "ocd_person": pid,
            "name": (row.get("name")
                     or f"{row.get('given_name', '')} {row.get('family_name', '')}".strip()),
            "given": row.get("given_name") or None,
            "family": row.get("family_name") or None,
            "party": row.get("current_party"),
            "chamber": chamber,
            "district": district,
            "image": row.get("image") or None,
            "birth_date": row.get("birth_date") or None,
            "source_url": srcs[0] if srcs else None,
            # WO-15: contact + social straight from the CSV's own columns —
            # verbatim, present only when the row itself has a value (never a
            # fabricated blank). Kept as nested dicts so build.py can drop them
            # into identity.contact / identity.social unchanged.
            "contact": contact_from_row(row),
            "social": social_from_row(row),
        }


# WO-15: OpenStates' own contact columns (verified live against
# data.openstates.org/people/current/{state}.csv). Congress has no per-member
# email; state legislators DO carry one here, so it publishes for state only.
_CONTACT_COLUMNS = {
    "email": "email", "capitol_address": "capitol_address",
    "capitol_voice": "capitol_voice", "district_address": "district_address",
    "district_voice": "district_voice",
}
_SOCIAL_COLUMNS = ("twitter", "youtube", "instagram", "facebook")


def contact_from_row(row: dict) -> dict:
    return {out_key: row[col] for col, out_key in _CONTACT_COLUMNS.items() if row.get(col)}


def social_from_row(row: dict) -> dict:
    return {col: row[col] for col in _SOCIAL_COLUMNS if row.get(col)}
