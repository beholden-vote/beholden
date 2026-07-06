"""Wikidata education lookups (WO-15, identity.education, federal only).

Wikidata is a crowd-edited encyclopedia — NOT an official government source.
It is used for exactly one fact this pipeline cannot get anywhere trustworthy
otherwise: education history (P69 "educated at" + P512/P582 qualifiers). Every
value here MUST publish under its own `wikidata` provenance envelope
(config.SOURCES["wikidata"]) carrying the verbatim crowd-sourced caveat —
never presented with the same unqualified trust as an official source
(docs/workplan/README.md WO-15; the user's explicit, deliberate choice).

Resolution path per person with a stored `wikidata_qid` (see sources/legislators
.py's `wikidata` id handling and the `persons.wikidata_qid` column):
  1. GET Special:EntityData/{QID}.json -> claim P69 (each claim = one
     "educated at" item id, with qualifiers P512 = academic degree item id,
     P582 = end time = graduation year).
  2. Batch EVERY item id referenced by EVERY person (institutions + degrees)
     into as few wbgetentities calls as possible (Wikidata's documented
     anonymous cap is 50 ids/request) and resolve to an English label.

Wikimedia's edge rejects requests with no identifying User-Agent (verified
live: an empty/default UA gets HTTP 403 with a link to the bot policy) — every
call here sends a descriptive UA per https://w.wiki/4wJS.

Copy-only: institution/degree labels are resolved verbatim; the graduation
year is the verbatim P582 value's year component. A field the claim lacks is
omitted, never invented.
"""
from __future__ import annotations

import re

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import SOURCES

BASE = SOURCES["wikidata"].base_url
USER_AGENT = "BeholdenETL/1.0 (https://beholden.vote; maintainers@beholden.vote)"
_HEADERS = {"User-Agent": USER_AGENT}

# Wikidata's anonymous wbgetentities cap (verified live via action=help): 50
# ids per request without an allowlisted higher-limit client. Chunk to stay
# under it regardless of how many persons/claims are being resolved.
WBGETENTITIES_MAX_IDS = 50

CREDIBILITY_NOTE = (
    "Sourced from Wikidata, a publicly edited encyclopedia — verify against "
    "the member's official biography.")


def entity_url(qid: str) -> str:
    return f"{BASE}/wiki/Special:EntityData/{qid}.json"


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=60))
def fetch_entity(qid: str) -> dict:
    """The full Wikidata entity document for one QID (one call per person with
    a stored wikidata_qid). Retrying: a transient blip must not sink the
    unattended nightly run."""
    r = httpx.get(entity_url(qid), headers=_HEADERS, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.json()


def educated_at_claims(entity: dict, qid: str) -> list[dict]:
    """Raw P69 claims for `qid` -> [{institution_qid, degree_qid?, end_year?}],
    reading only claim/qualifier ids (no labels yet — those are batched
    separately). A claim with no resolvable institution item id is skipped."""
    claims = (((entity.get("entities") or {}).get(qid) or {}).get("claims") or {})
    out = []
    for claim in claims.get("P69") or []:
        inst_id = _entity_id(((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value"))
        if not inst_id:
            continue
        quals = claim.get("qualifiers") or {}
        degree_id = None
        for q in quals.get("P512") or []:
            degree_id = _entity_id((q.get("datavalue") or {}).get("value"))
            if degree_id:
                break
        end_year = None
        for q in quals.get("P582") or []:
            end_year = _time_year((q.get("datavalue") or {}).get("value"))
            if end_year:
                break
        entry = {"institution_qid": inst_id}
        if degree_id:
            entry["degree_qid"] = degree_id
        if end_year:
            entry["end_year"] = end_year
        out.append(entry)
    return out


def _entity_id(value: dict | None) -> str | None:
    if not isinstance(value, dict):
        return None
    return value.get("id")


_TIME_RE = re.compile(r"^([+-])(\d{1,})-\d\d-\d\dT")


def _time_year(value: dict | None) -> int | None:
    """A Wikidata time snak's `time` field is like '+1980-00-00T00:00:00Z' —
    pull the year verbatim; a zero/blank year (precision below 'year') or an
    unparseable string yields None (never a fabricated year)."""
    if not isinstance(value, dict):
        return None
    m = _TIME_RE.match(value.get("time") or "")
    if not m:
        return None
    sign, digits = m.groups()
    year = int(digits)
    return -year if sign == "-" else year


def chunk_ids(ids: list[str], size: int = WBGETENTITIES_MAX_IDS) -> list[list[str]]:
    return [ids[i:i + size] for i in range(0, len(ids), size)]


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=60))
def fetch_labels(ids: list[str]) -> dict[str, str]:
    """One wbgetentities call for up to WBGETENTITIES_MAX_IDS item ids ->
    {qid: english_label}. An id Wikidata has no English label for is simply
    absent from the result (never a fabricated label)."""
    if not ids:
        return {}
    params = {"action": "wbgetentities", "ids": "|".join(ids),
              "props": "labels", "languages": "en", "format": "json"}
    r = httpx.get(f"{BASE}/w/api.php", params=params, headers=_HEADERS,
                  timeout=30, follow_redirects=True)
    r.raise_for_status()
    data = r.json()
    out = {}
    for qid, ent in (data.get("entities") or {}).items():
        label = ((ent.get("labels") or {}).get("en") or {}).get("value")
        if label:
            out[qid] = label
    return out


def resolve_labels(all_ids: set[str]) -> dict[str, str]:
    """Resolve every item id across ALL persons in as few HTTP calls as
    possible — chunks the full id set once rather than one call per person."""
    out: dict[str, str] = {}
    for chunk in chunk_ids(sorted(all_ids)):
        out.update(fetch_labels(chunk))
    return out


def education_rows(claims: list[dict], labels: dict[str, str]) -> list[dict]:
    """[{institution_qid -> institution, degree_qid -> degree, end_year ->
    year}] claims resolved to display labels. `institution`/`degree` are
    omitted (never null) when Wikidata has no English label for that item;
    `year` is omitted when the claim carried no P582. A claim whose institution
    item has no label at all is dropped entirely — publishing an education
    entry with no institution name would be worse than omitting it."""
    out = []
    for c in claims:
        institution = labels.get(c["institution_qid"])
        if not institution:
            continue
        entry = {"institution": institution}
        degree_qid = c.get("degree_qid")
        if degree_qid and labels.get(degree_qid):
            entry["degree"] = labels[degree_qid]
        if c.get("end_year"):
            entry["year"] = c["end_year"]
        out.append(entry)
    return out
