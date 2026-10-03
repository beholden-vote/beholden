"""Sumner County + Hendersonville, TN — two roster specs and their parsers (WO-22, WO-22b).

There is no national roster of county and municipal officials, and the aggregators
that sell one were rejected on licensing. So each locality is its own source contract:
since WO-22b, a `roster.RosterSpec` record plus a parser registered as an adapter id.
The fetcher, gates, spine rows, source-registry row and office display are generated
by `sources/roster.py`.

WHY GRADE B, NOT A: both rosters are published by the government that runs the
election, but as web pages rather than a bulk feed, so we parse a document instead of
reading a dataset. The markup is structured, not prose: Hendersonville publishes an
h-card microformat directory, Sumner one WordPress post per commissioner with a stable
per-person permalink. Neither parse guesses at layout.

THE GATE is the body's own seat count: Sumner has 24 single-member districts;
Hendersonville a mayor plus six wards electing two aldermen each. A duplicate seat, a
gap or the wrong count means the page changed shape under us, and the locality is
withheld rather than published partial (roster.py).

PARTY IS NOT PUBLISHED by either source, so it is "U", never "NP".

Terms of reuse: docs/research/tn-local-roster-terms.md.
"""
from __future__ import annotations

import html as _html
import re
import uuid

from .. import divisions as D
from .roster import ADAPTERS, Adapter, RosterError, RosterRow, RosterSpec, SourceRef, slug

SUMNER_URL = "https://sumnercountytn.gov/government/county-commission/"
HENDERSONVILLE_URL = "https://www.hvilletn.org/409/Board-of-Mayor-Aldermen"

USPS = "TN"
SUMNER_COUNTY_NAME = "Sumner"          # bare name, as the canonical registry slugs it
HENDERSONVILLE_PLACE_NAME = "Hendersonville"

# Seat structure, verified against the official pages 2026-09-08.
SUMNER_DISTRICTS = 24
HENDERSONVILLE_WARDS = 6
HENDERSONVILLE_ALDERMEN_PER_WARD = 2

TERMS_REF = "docs/research/tn-local-roster-terms.md"

_ORDINAL_DISTRICT = re.compile(r"^\s*(\d+)(?:st|nd|rd|th)?\s+District\s*$", re.IGNORECASE)
_WARD_TITLE = re.compile(r"^\s*Alderman\s*[-–—]\s*Ward\s+(\d+)\s*$", re.IGNORECASE)


def _text(fragment: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


# ── Parsers (pure: HTML in, rows out) ───────────────────────────────────────

def parse_sumner(page_html: str) -> list[dict]:
    """One row per commissioner. Anchors on the post-title widget and reads the
    sibling excerpt (the district) and contact block; the per-person permalink
    becomes that row's source_record_url."""
    rows: list[dict] = []
    chunks = re.split(r"(?=elementor-widget-theme-post-title)", page_html)
    for prev, block in zip(chunks, chunks[1:]):
        title = re.search(r'<h3[^>]*><a href="([^"]+)"[^>]*>(.*?)</a></h3>', block, re.DOTALL)
        excerpt = re.search(
            r'theme-post-excerpt.*?<div class="elementor-widget-container">\s*(.*?)\s*</div>',
            block, re.DOTALL)
        if not title or not excerpt:
            continue
        district = _ORDINAL_DISTRICT.match(_html.unescape(excerpt.group(1)).strip())
        if not district:
            continue                    # not a district post (page furniture)
        email = re.search(r'mailto:([^"\']+)', block)
        # The page renders each post's image BEFORE its title widget, so this
        # person's photo is the last <img> of the chunk that precedes the title.
        # Reading the first <img> of the title's own chunk gives the NEXT person's.
        photos = re.findall(r'<img[^>]+src="([^"]+)"', prev)
        photo = photos[-1] if photos else None
        rows.append({
            "full_name": _text(title.group(2)),
            "district": int(district.group(1)),
            "email": email.group(1).strip() if email else None,
            "photo_url": photo,
            "source_record_url": title.group(1),
        })
    return rows


def parse_hendersonville(page_html: str) -> list[dict]:
    """One row per member of the Board of Mayor and Aldermen, from the h-card
    microformat (p-name / p-job-title / u-email / p-tel / u-photo). `ward` is
    None for the mayor, who is elected at large."""
    rows: list[dict] = []
    for card in re.findall(r'<li class="widgetItem h-card">(.*?)</li>', page_html, re.DOTALL):
        name = re.search(r'class="widgetTitle field p-name">\s*(.*?)\s*(?:<|\n)', card, re.DOTALL)
        role = re.search(r'class="field p-job-title">(.*?)</div>', card, re.DOTALL)
        if not name or not role:
            continue
        role_text = _text(role.group(1))
        ward_match = _WARD_TITLE.match(role_text)
        if not ward_match and role_text.lower() != "mayor":
            continue                    # a board/committee card, not a BOMA seat
        email = re.search(r'mailto:([^"\']+)', card)
        phone = re.search(r'href="tel:([^"]+)"', card)
        photo = re.search(r'<img[^>]+src="([^"]+)"', card)
        rows.append({
            "full_name": _html.unescape(name.group(1)).strip(),
            "role_title": role_text,
            "ward": int(ward_match.group(1)) if ward_match else None,
            "email": email.group(1).strip() if email else None,
            "phone": phone.group(1).strip() if phone else None,
            "photo_url": photo.group(1) if photo else None,
            "source_record_url": HENDERSONVILLE_URL,
        })
    return rows


def _contact(r: dict) -> dict:
    return {k: r[k] for k in ("email", "phone") if r.get(k)}


def sumner_adapter(raw: bytes, spec: RosterSpec) -> list[RosterRow]:
    return [RosterRow(name=r["full_name"], office_title="County Commissioner",
                      seat_label=f"District {r['district']}", contact=_contact(r),
                      source_row_url=r["source_record_url"], photo_url=r["photo_url"])
            for r in parse_sumner(raw.decode("utf-8"))]


def hendersonville_adapter(raw: bytes, spec: RosterSpec) -> list[RosterRow]:
    return [RosterRow(name=r["full_name"],
                      office_title="Mayor" if r["ward"] is None else "Alderman",
                      seat_label=None if r["ward"] is None else f"Ward {r['ward']}",
                      contact=_contact(r), source_row_url=r["source_record_url"],
                      photo_url=r["photo_url"])
            for r in parse_hendersonville(raw.decode("utf-8"))]


# ── Structural gates (beyond roster.check's generic ones) ───────────────────

def _seat_numbers(rows: list[RosterRow]) -> list[int]:
    return [int(r.seat_label.split()[-1]) for r in rows if r.seat_label]


def check_sumner_roster(rows: list[RosterRow]) -> None:
    seats = _seat_numbers(rows)
    expected = set(range(1, SUMNER_DISTRICTS + 1))
    dupes = sorted({d for d in seats if seats.count(d) > 1})
    missing = sorted(expected - set(seats))
    unexpected = sorted(set(seats) - expected)
    if dupes or missing or unexpected or len(rows) != SUMNER_DISTRICTS:
        raise RosterError(
            f"Sumner commission roster failed its completeness gate: parsed "
            f"{len(rows)} of {SUMNER_DISTRICTS} seats; missing districts "
            f"{missing}; duplicated {dupes}; unexpected {unexpected}.")


def check_hendersonville_roster(rows: list[RosterRow]) -> None:
    mayors = [r for r in rows if r.seat_label is None]
    by_ward: dict[int, int] = {}
    for w in _seat_numbers(rows):
        by_ward[w] = by_ward.get(w, 0) + 1
    expected = set(range(1, HENDERSONVILLE_WARDS + 1))
    wrong = {w: n for w, n in sorted(by_ward.items())
             if n != HENDERSONVILLE_ALDERMEN_PER_WARD}
    missing = sorted(expected - set(by_ward))
    if len(mayors) != 1 or missing or wrong or set(by_ward) - expected:
        raise RosterError(
            f"Hendersonville BOMA roster failed its completeness gate: "
            f"{len(mayors)} mayor(s); missing wards {missing}; wards with the "
            f"wrong number of aldermen {wrong}. Expected 1 mayor and "
            f"{HENDERSONVILLE_WARDS} wards x {HENDERSONVILLE_ALDERMEN_PER_WARD} aldermen.")


# ── WO-22b one-time id migration: the seat-keyed ids published before ──────

def person_uuid(scheme: str, key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"person:{scheme}:{key}"))


def _sumner_legacy(r: RosterRow) -> str:
    return person_uuid("local:sumner_county", f"commission-district-{_seat_numbers([r])[0]}")


def _hendersonville_legacy(r: RosterRow) -> str:
    key = (f"mayor-{slug(r.name)}" if r.seat_label is None
           else f"ward-{_seat_numbers([r])[0]}-{slug(r.name)}")
    return person_uuid("local:hendersonville", key)


ADAPTERS["tn_sumner_commission"] = Adapter(sumner_adapter, check_sumner_roster, _sumner_legacy)
ADAPTERS["tn_hendersonville_boma"] = Adapter(hendersonville_adapter,
                                             check_hendersonville_roster,
                                             _hendersonville_legacy)

SPECS = [
    RosterSpec(
        locality_id="tn-sumner-county", ocd_id=D.county_ocd(USPS, SUMNER_COUNTY_NAME),
        level="county", name=SUMNER_COUNTY_NAME, body="County Commission",
        source=SourceRef("sumner_county", SUMNER_URL, "tn_sumner_commission"),
        seats=(SUMNER_DISTRICTS, SUMNER_DISTRICTS), terms_ref=TERMS_REF,
        chamber="county_commission",
        term_start="2024-09-01"),        # TN county terms begin Sept 1 after the August election
    RosterSpec(
        locality_id="tn-hendersonville", ocd_id=D.place_ocd(USPS, HENDERSONVILLE_PLACE_NAME),
        level="place", name=HENDERSONVILLE_PLACE_NAME, body="Board of Aldermen",
        source=SourceRef("hendersonville", HENDERSONVILLE_URL, "tn_hendersonville_boma"),
        seats=(13, 13), seat_size=HENDERSONVILLE_ALDERMEN_PER_WARD, terms_ref=TERMS_REF,
        chamber="board_of_aldermen",
        term_start="2024-11-18"),        # BOMA seated after the November 2024 city election
]
