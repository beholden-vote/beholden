"""Crosswalk seed from unitedstates/congress-legislators (ticket E1-4).
Bioguide <-> FEC <-> ICPSR <-> Wikidata into person_identifiers; misses -> quarantine."""
from __future__ import annotations
import httpx, yaml, uuid
from ..config import SOURCES, SPINE_RESOLUTION_MIN

URL = f"{SOURCES['unitedstates_legislators'].base_url}/legislators-current.yaml"

SCHEMES = {"bioguide": "bioguide", "fec": "fec", "icpsr": "icpsr", "wikidata": "wikidata"}


def fetch_current() -> list[dict]:
    r = httpx.get(URL, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return yaml.safe_load(r.text)


def to_spine_rows(legislators: list[dict]):
    """Yield (person_row, identifier_rows, quarantine_row|None) per legislator."""
    resolved = 0
    for leg in legislators:
        ids = leg.get("id", {})
        name = leg.get("name", {})
        if not ids.get("bioguide"):
            yield None, [], {"raw_payload": leg, "source": "unitedstates_legislators"}
            continue
        person_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"bioguide:{ids['bioguide']}"))
        person = {
            "person_id": person_id,
            "full_name": name.get("official_full") or f"{name.get('first','')} {name.get('last','')}".strip(),
            "given_name": name.get("first"), "family_name": name.get("last"),
            "birth_year": int(leg["bio"]["birthday"][:4]) if leg.get("bio", {}).get("birthday") else None,
            "wikidata_qid": ids.get("wikidata"),
        }
        idents = [{"person_id": person_id, "id_scheme": s, "id_value": str(v)}
                  for k, s in SCHEMES.items() if s != "wikidata"
                  for v in ([ids[k]] if isinstance(ids.get(k), (str, int)) else ids.get(k, []) or [])]
        resolved += 1
        yield person, idents, None
    rate = resolved / max(len(legislators), 1)
    if rate < SPINE_RESOLUTION_MIN:  # fail closed (quality gate E1/E8)
        raise RuntimeError(f"spine resolution {rate:.4f} < {SPINE_RESOLUTION_MIN}")
