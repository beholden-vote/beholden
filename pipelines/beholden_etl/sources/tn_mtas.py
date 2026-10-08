"""Tennessee municipal governing bodies from the UT MTAS public directory export (WO-22b Part B).

ONE public CSV, fetched once per run (roster._get caches per URL), serves ~344 city
specs. Each spec's adapter cuts the export down to its own city's governing-body rows
(`narrow`) BEFORE the gate, so only a small slice is landed per city and the export's
billing-address columns never leave the process.

TERMS: docs/research/mtas-authorization-2026-10.md. Owner-authorized, no written copy
on file; credit and link back on every record (reported_by + source_row_url), public CSV
export only, nightly at most, grade B. No determination covers a priced bulk dataset.

WHAT THE EXPORT DOES NOT SAY, and therefore what we never publish: party ("U"), ward or
district (members carry roster.MEMBER, no seat), term dates (stored as the
TERM_START sentinel, never served or displayed), vacancies (rows named VACANT are dropped).

SEAT-COUNT GATE. Neither the export nor the city table states a body's size, so the
only authority is the count in the export reviewed at adoption (`n`, pinned in
tn_mtas_cities.json beside the Census GEOID). Fewer than n is withheld (last good kept)
until the pin is updated in a reviewed PR; more than n publishes (a larger body is not
a half-parsed one) up to the absolute ceiling MAX_SEATS (Nashville is 41), and the
coverage reason should carry a plain "source lists more than expected" note (framework).
Never lower n to make a city pass.
Structural gate: at most one mayor.

PLACE IDS come from the Census GEOID in the table (divisions.place_ocd), the Gazetteer's
own NAME as the division name. A city with no unique Census match is not given a spec; it
is listed under "excluded" with a plain reason (Hendersonville: it ships from the city's
own roster in tn_local.py, which stays authoritative).
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections import defaultdict
from pathlib import Path

from .. import divisions as D
from .roster import (ADAPTERS, MEMBER, Adapter, RosterError, RosterRow, RosterSpec,
                     SourceRef, slug)

EXPORT_URL = "https://www.mtas.tennessee.edu/mtas_api/v1/csv/official"
DIRECTORY_URL = "https://www.mtas.tennessee.edu/directories/cities"   # link back, per record
TERMS_REF = "docs/research/mtas-authorization-2026-10.md"
REPORTED_BY = "UT Municipal Technical Advisory Service (MTAS) directory"
# terms.start_date is NOT NULL in the spine and a nullable column cannot be migrated
# (DuckDB cannot ALTER a table carrying idx_terms_current). So an unknown start is stored as this
# internal sentinel, never served: current terms are excluded from previous_roles and
# build._previous_roles nulls the sentinel if a term ever ends. The UI shows no date.
TERM_START = "1900-01-01"
MAX_SEATS = 45
TABLE = Path(__file__).with_name("tn_mtas_cities.json")

EXPORT_HEADER = ["Organization", "Salutation", "First", "Middle", "Last", "Generational",
                 "Credentials", "Preferred Name", "Title", "Phone", "Phone Extension", "Fax",
                 "Email", "Address", "City", "State", "Zip", "Billing Address", "Billing Zip"]
SLIM = ["Organization", "Name", "Title", "Phone", "Email"]    # all that is ever landed

_TITLE = re.compile(r"^(Mayor|Interim Mayor|Vice Mayor|Mayor Pro Tem|Alderman|Councilmember|"
                    r"Metro Councilmember|Commissioner)(?:,\s*(.+))?$")
MAYORS = ("Mayor", "Interim Mayor")
# kind -> (body, chamber), chosen by the title most members hold.
BODIES = {"Alderman": ("Board of Mayor and Aldermen", "board_of_aldermen"),
          "Councilmember": ("City Council", "city_council"),
          "Commissioner": ("City Commission", "city_commission"),
          "Metro Councilmember": ("Metropolitan Council", "metro_council")}
_GOV_SUFFIXES = (".gov", ".tn.us")


def official_email(email: str, city: str) -> bool:
    """Published only on an official government domain: *.gov (incl. *.tn.gov), *.tn.us, or
    a domain carrying the city's own name (greenbriertn.org for Greenbrier). Conservative:
    a city whose domain does not contain its name publishes no email. Never webmail."""
    domain = email.rsplit("@", 1)[-1].lower()
    own = slug(city).replace("-", "")[:6]
    return domain.endswith(_GOV_SUFFIXES) or (len(own) >= 4 and own in domain.replace("-", ""))


def _name(r: dict) -> str:
    n = " ".join((r["Preferred Name"] or f"{r['First']} {r['Last']}").split())
    return "" if n.upper() == "VACANT" else n


def narrow(raw: bytes, spec: RosterSpec) -> bytes:
    """The export -> this city's governing-body rows, five columns. A changed header is
    a schema break (ValueError, fails the run), not a gate."""
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if reader.fieldnames != EXPORT_HEADER:
        raise ValueError(f"MTAS export header changed: {reader.fieldnames}")
    org = _ORG[spec.source.source_key]
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(SLIM)
    for r in reader:
        if r["Organization"] != org:
            continue
        m = _TITLE.match(r["Title"].split(";")[0].strip())
        if not m or (m.group(2) and m.group(2) != org) or not _name(r):
            continue
        w.writerow([org, _name(r), m.group(1), r["Phone"].strip(), r["Email"].strip().lower()])
    return out.getvalue().encode("utf-8")


def parse(raw: bytes, spec: RosterSpec) -> list[RosterRow]:
    """Mayor first, then members, then vice mayor / pro tem; a person listed twice
    (a vice mayor who is also a member, a repeated line) is one row, first title wins."""
    rank = {t: 0 for t in MAYORS} | {"Vice Mayor": 2, "Mayor Pro Tem": 2}
    recs = sorted(csv.DictReader(io.StringIO(raw.decode("utf-8"))),
                  key=lambda r: (rank.get(r["Title"], 1), slug(r["Name"])))
    rows: dict[str, RosterRow] = {}
    for r in recs:
        contact = {k: v for k, v in (("phone", r["Phone"]), ("email", r["Email"])) if v}
        if "email" in contact and not official_email(contact["email"], spec.name):
            del contact["email"]
        key = slug(r["Name"])
        if key in rows:
            rows[key] = RosterRow(**{**rows[key].__dict__,
                                     "contact": {**contact, **rows[key].contact}})
            continue
        rows[key] = RosterRow(
            name=r["Name"], office_title=r["Title"],
            seat_label=None if r["Title"] in MAYORS else MEMBER,
            contact=contact, source_row_url=DIRECTORY_URL)
    return list(rows.values())


def check(rows: list[RosterRow]) -> None:
    mayors = [r.name for r in rows if r.seat_label is None]
    if len(mayors) > 1:
        raise RosterError(f"{len(mayors)} mayors listed ({mayors}); a city has one")
    if len(rows) > MAX_SEATS:
        raise RosterError(f"{len(rows)} seats listed, above the {MAX_SEATS} ceiling")


ADAPTERS["tn_mtas_city"] = Adapter(parse, check, narrow=narrow)


# -- The pinned city table -----------------------------------------------------------

_TABLE = json.loads(TABLE.read_text(encoding="utf-8"))
_ORG: dict[str, str] = {}
SPECS: list[RosterSpec] = []
for _c in _TABLE["cities"]:
    _key = f"mtas_{slug(_c['name']).replace('-', '_')}"
    _ORG[_key] = _c["org"]
    _body, _chamber = BODIES[_c["kind"]]
    SPECS.append(RosterSpec(
        locality_id=f"tn-{slug(_c['name'])}",
        ocd_id=D.place_ocd("TN", _c["name"], _c["geoid"]), level="place", name=_c["name"],
        body=_body, source=SourceRef(_key, EXPORT_URL, "tn_mtas_city"),
        seats=(_c["n"], MAX_SEATS), terms_ref=TERMS_REF, chamber=_chamber,
        reported_by=REPORTED_BY, term_start=TERM_START))


# -- Regenerating the table (reviewed PR only) ---------------------------------------
# python -c "from beholden_etl.sources import tn_mtas as m; m.regenerate('export.csv', 'gaz_place.txt')"

# MTAS spelling -> the one Census place it is, where the bare names differ. Each was
# checked by county against the export's own city file (2026-10-08).
ALIASES = {"Hartsville": "4732742", "LaFollette": "4740180", "Lynchburg": "4744382",
           "Mt. Juliet": "4750780", "Nashville": "4752006"}
EXCLUDED = {"Hendersonville": "ships from the city's own roster (sources/tn_local.py)"}
_CENSUS_SUFFIX = re.compile(r" (city|town|village|metropolitan government.*)(?: \(balance\))?$")


def regenerate(export_csv: str, gazetteer_place_txt: str) -> None:
    raw = Path(export_csv).read_bytes()
    gaz = [ln.split("\t") for ln in Path(gazetteer_place_txt).read_text(encoding="utf-8")
           .splitlines()[1:] if ln.startswith("TN\t")]
    by_name = defaultdict(list)
    for g in gaz:
        if g[5].strip() in ("A", "B") or (g[5].strip() == "F" and "(balance)" in g[3]):
            by_name[_CENSUS_SUFFIX.sub("", g[3].strip())].append((g[1], g[3].strip()))
    census = {g[1]: g[3].strip() for g in gaz}
    orgs = sorted({r["Organization"] for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))})
    cities, excluded = [], dict(EXCLUDED)
    for org in orgs:
        if org in EXCLUDED:
            continue
        hit = [(ALIASES[org], census[ALIASES[org]])] if org in ALIASES else by_name.get(org, [])
        if len(hit) != 1:
            excluded[org] = f"no unique Census place ({len(hit)} candidates)"
            continue
        geoid, cname = hit[0]
        # Consolidated governments: the Census name is the government's, readers say the city.
        name = org if org in ("Hartsville", "Lynchburg", "Nashville") else _CENSUS_SUFFIX.sub("", cname)
        cities.append({"org": org, "name": name, "geoid": geoid})
    _ORG.update({f"mtas_{slug(c['name']).replace('-', '_')}": c["org"] for c in cities})
    for c in cities:
        spec = RosterSpec(
            locality_id="x", ocd_id=D.place_ocd("TN", c["name"], c["geoid"]), level="place",
            name=c["name"], body="x", terms_ref=TERMS_REF, chamber="x", reported_by="x",
            term_start=TERM_START, seats=(1, MAX_SEATS),
            source=SourceRef(f"mtas_{slug(c['name']).replace('-', '_')}", EXPORT_URL, "tn_mtas_city"))
        rows = parse(narrow(raw, spec), spec)
        titles = defaultdict(int)
        for r in rows:
            titles[r.office_title] += r.seat_label == MEMBER and r.office_title in BODIES
        c["n"] = len(rows)
        c["kind"] = max(BODIES, key=lambda t: (titles[t], t == "Alderman"))
    TABLE.write_text(json.dumps({"as_of": "2026-10-08", "excluded": dict(sorted(excluded.items())),
                                 "cities": cities}, indent=1) + "\n", encoding="utf-8")
