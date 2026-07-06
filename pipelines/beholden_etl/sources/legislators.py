"""Crosswalk seed from unitedstates/congress-legislators (ticket E1-4).
Bioguide <-> FEC <-> ICPSR <-> Wikidata into person_identifiers; misses -> quarantine."""
from __future__ import annotations
import uuid

import httpx
import yaml
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import SOURCES, SPINE_RESOLUTION_MIN

URL = f"{SOURCES['unitedstates_legislators'].base_url}/legislators-current.yaml"
# Committee roster + current memberships (WO-6a). Same source family as the
# crosswalk above, so both land under the unitedstates_legislators envelope.
COMMITTEES_URL = f"{SOURCES['unitedstates_legislators'].base_url}/committees-current.yaml"
COMMITTEE_MEMBERSHIP_URL = (
    f"{SOURCES['unitedstates_legislators'].base_url}/committee-membership-current.yaml")
# WO-15: district offices + social handles. Published on GitHub Pages (not raw.
# githubusercontent like the YAML above), but the SAME source family/repo, so
# both land under the one unitedstates_legislators envelope — no new source key.
DISTRICT_OFFICES_URL = "https://unitedstates.github.io/congress-legislators/legislators-district-offices.json"
SOCIAL_MEDIA_URL = "https://unitedstates.github.io/congress-legislators/legislators-social-media.json"

SCHEMES = {"bioguide": "bioguide", "fec": "fec", "icpsr": "icpsr", "wikidata": "wikidata"}

# committee-membership-current.yaml spells titles out; the spine's role enum
# (002_legislative.sql) is {member,chair,ranking,vice_chair}. Map every stated
# title; anything not stated (incl. the common no-title member and "Ex Officio",
# which the DDL has no code for) collapses to 'member'. Applied identically
# regardless of party — symmetric by construction (rule #3).
_ROLE_BY_TITLE = {
    "chair": "chair", "chairman": "chair", "chairwoman": "chair", "cochairman": "chair",
    "ranking member": "ranking",
    "vice chair": "vice_chair", "vice chairman": "vice_chair", "vice chairwoman": "vice_chair",
}


def committee_role(title: str | None) -> str:
    """Source title -> DDL role enum. Unknown/absent -> 'member' (never a
    stronger claim than the source states)."""
    return _ROLE_BY_TITLE.get((title or "").strip().lower(), "member")

# congress-legislators spells parties in full; the spine stores coded values.
PARTY_CODE = {"Republican": "R", "Democrat": "D", "Democratic": "D",
              "Independent": "I", "Libertarian": "L", "Green": "G"}


def person_uuid(bioguide: str) -> str:
    """Deterministic person_id from bioguide — the anchor identifier. Stable
    across runs so nightly upserts don't churn ids, and lets any source that
    knows a bioguide resolve to the same person without a DB round-trip."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"bioguide:{bioguide}"))


def party_code(name: str | None) -> str:
    return PARTY_CODE.get((name or "").strip(), "NP")


def current_term(leg: dict) -> dict | None:
    """The legislator's active term = the last entry in terms[] (chronological)."""
    terms = leg.get("terms") or []
    return terms[-1] if terms else None


def first_took_office(leg: dict) -> str | None:
    terms = leg.get("terms") or []
    return min((t.get("start") for t in terms if t.get("start")), default=None)


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=60))
def fetch_current() -> list[dict]:
    """Retrying: the nightly runs unattended — a transient GitHub blip must not
    kill the run (freshness SLA, PRD G2)."""
    r = httpx.get(URL, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return yaml.safe_load(r.text)


# --- WO-15: contact (from the current term already fetched above) ----------
def contact_from_term(term: dict | None) -> dict:
    """{phone, website, contact_form, dc_office_address} verbatim from a
    congress-legislators term dict (address/office = DC office; url = website).
    Every key is omitted, never null/empty, when the source lacks it — honest
    absence over a fabricated placeholder. `office` is the AOC-style short form
    ("511 Hart Senate Office Building"); `address` is the full one-line mailing
    address — prefer `address` (matches district_offices' shape) falling back
    to `office` for older terms that only carry the short form."""
    term = term or {}
    out = {}
    if term.get("phone"):
        out["phone"] = term["phone"]
    if term.get("url"):
        out["website"] = term["url"]
    if term.get("contact_form"):
        out["contact_form"] = term["contact_form"]
    addr = term.get("address") or term.get("office")
    if addr:
        out["dc_office_address"] = addr
    return out


# --- WO-15: district offices (federal only) ---------------------------------
@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=60))
def fetch_district_offices() -> list[dict]:
    """legislators-district-offices.json: per-bioguide list of local offices
    (address/city/state/zip/phone/lat/lng). Same trusted family as the roster
    above (GitHub Pages mirror of the same repo) -> unitedstates_legislators
    envelope. Retrying like the other bulk pulls (nightly runs unattended)."""
    r = httpx.get(DISTRICT_OFFICES_URL, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return r.json()


_OFFICE_FIELDS = ("address", "city", "state", "zip", "phone", "latitude", "longitude")


def district_offices_by_bioguide(records: list[dict]) -> dict[str, list[dict]]:
    """bioguide -> [{address, city, state, zip, phone, latitude, longitude}],
    each dict carrying only the keys the source itself populated for that
    office — never a fabricated field. A record with no bioguide is skipped
    (can't key to the spine)."""
    out: dict[str, list[dict]] = {}
    for rec in records or []:
        bio = (rec.get("id") or {}).get("bioguide")
        if not bio:
            continue
        offices = []
        for o in rec.get("offices") or []:
            entry = {k: o[k] for k in _OFFICE_FIELDS if o.get(k) is not None}
            if entry:
                offices.append(entry)
        if offices:
            out[bio] = offices
    return out


# --- WO-15: social media handles ---------------------------------------------
@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=60))
def fetch_social_media() -> list[dict]:
    """legislators-social-media.json: per-bioguide handles (twitter/facebook/
    instagram/youtube/mastodon). Same trusted family as the roster -> the
    unitedstates_legislators envelope. Retrying like the other bulk pulls."""
    r = httpx.get(SOCIAL_MEDIA_URL, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return r.json()


_SOCIAL_FIELDS = ("twitter", "facebook", "instagram", "youtube", "mastodon")


def social_media_by_bioguide(records: list[dict]) -> dict[str, dict]:
    """bioguide -> {twitter?, facebook?, instagram?, youtube?, mastodon?},
    verbatim handles only — never a guessed/derived handle, and a field the
    source omits is simply absent from the dict (not published as null)."""
    out: dict[str, dict] = {}
    for rec in records or []:
        bio = (rec.get("id") or {}).get("bioguide")
        social = rec.get("social") or {}
        if not bio or not social:
            continue
        entry = {k: social[k] for k in _SOCIAL_FIELDS if social.get(k)}
        if entry:
            out[bio] = entry
    return out


def to_spine_rows(legislators: list[dict]):
    """Yield (person_row, identifier_rows, quarantine_row|None) per legislator."""
    resolved = 0
    for leg in legislators:
        ids = leg.get("id", {})
        name = leg.get("name", {})
        if not ids.get("bioguide"):
            yield None, [], {"raw_payload": leg, "source": "unitedstates_legislators"}
            continue
        person_id = person_uuid(ids["bioguide"])
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


# --- committees (WO-6a) -----------------------------------------------------
@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=60))
def fetch_committees() -> list[dict]:
    """committees-current.yaml: the committee/subcommittee roster (codes, names,
    chamber). Retrying like the crosswalk — the nightly runs unattended."""
    r = httpx.get(COMMITTEES_URL, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return yaml.safe_load(r.text)


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=60))
def fetch_committee_membership() -> dict:
    """committee-membership-current.yaml: current members per committee code,
    keyed by thomas_id (subcommittees = parent code + subcommittee thomas_id)."""
    r = httpx.get(COMMITTEE_MEMBERSHIP_URL, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return yaml.safe_load(r.text)


# committee `type` in the YAML -> the chamber value we store. Joint committees
# span both chambers; recorded as 'joint' (no chamber CHECK on the table).
_COMMITTEE_CHAMBER = {"house": "house", "senate": "senate", "joint": "joint"}


def committee_rows(committees: list[dict]):
    """Flatten the roster into committees-table rows (parent committees first,
    then their subcommittees). A subcommittee's committee_id is the parent
    thomas_id concatenated with the subcommittee thomas_id — exactly how the
    membership file keys subcommittees — so the two files join without guessing.
    parent_id links a subcommittee to its parent (self-referential FK, upheld by
    emitting parents before children)."""
    for c in committees:
        tid = c.get("thomas_id")
        if not tid:
            continue                       # no stable code -> can't key memberships
        chamber = _COMMITTEE_CHAMBER.get(c.get("type"))
        yield {"committee_id": tid, "jurisdiction": "us", "chamber": chamber,
               "name": c.get("name") or tid, "parent_id": None}
        for sub in c.get("subcommittees") or []:
            sub_tid = sub.get("thomas_id")
            if not sub_tid:
                continue
            yield {"committee_id": tid + sub_tid, "jurisdiction": "us",
                   "chamber": chamber, "name": sub.get("name") or (tid + sub_tid),
                   "parent_id": tid}


def membership_rows(membership: dict, congress: int, known_committee_ids: set[str],
                    bioguide_to_person):
    """Yield committee_memberships rows for the given congress. `membership` maps
    committee_id -> [ {bioguide, title?, party, rank?} ]. Rows are emitted only
    when both the committee (FK) and the member (crosswalk) resolve — an unknown
    code or a bioguide outside the spine is skipped, never invented. Role comes
    straight from the stated title via committee_role (symmetric mapping)."""
    for committee_id, members in membership.items():
        if committee_id not in known_committee_ids:
            continue                       # committee not in the roster -> skip (FK)
        for m in members or []:
            bio = m.get("bioguide")
            pid = bioguide_to_person.get(bio) if bio else None
            if not pid:
                continue                   # member not in the crosswalk spine
            yield {"committee_id": committee_id, "person_id": pid,
                   "congress": congress, "role": committee_role(m.get("title"))}
