"""Every Tennessee county's governing body, from the CTAS directory (WO-22b Part B).

SOURCE. The UT County Technical Assistance Service (CTAS) directory. CTAS stated in
writing that its directory data is public and may be republished with credit and a
link back to CTAS, and that the only bulk access is the public CSV export of each
county-office group (docs/research/ctas-permission-2026-10.md). So this module reads
exactly two of those exports, each once per run, through the roster framework's
shared-file source: the County Commissioners group and the County Executives and
Mayors group. Nothing else on the site is fetched by the pipeline.

CREDIT AND LINK BACK (condition 1). Every row's `source_row_url` is the CTAS
directory page of its county, so the dossier's source envelope links back to CTAS,
and `reported_by` puts "as reported by UT County Technical Assistance Service
(CTAS), retrieved <date>" on the provenance line.

WHAT IS PUBLISHED. Name, office title and county; plus an email ONLY when its domain
is a government domain (`official_email`). The exports also carry street addresses
(many of them home addresses), fax numbers and personal mailboxes. None of those is
published, and they are dropped in the split, before anything is landed. No photos.

SEATS. The export lists no district for a commissioner, so every member is an
`at_large` row of the body (the framework's "no seat label" member); the office reads
"Anderson County Commission", never a district we would have to invent.

THE GATE, per county. The expected size is the "Number of Commissioners" the county's
own CTAS page states (STATED_SIZE, read 2026-10-08). A county is WITHHELD when the
export lists fewer members than that (a partial roster), or no single executive. It
is published when the export lists more, with a plain source note on its coverage
entry ("roster lists 12; county page states 11"): the two CTAS pages disagree, and
the reader is told so. The ceiling is the statutory maximum of 25 members for a
county legislative body, so a county page that under-states its size never passes
a duplicated or merged export unnoticed.
The gate counts the executive too: seats = (stated + 1, ceiling + 1).

PARTY is not in the export: "U".

NO TERM DATES. The export publishes none, so none is served: `term_start` is the
internal sentinel 1900-01-01 (terms.start_date is NOT NULL in the spine). Roster
terms are always current (end_date NULL), and only ended terms are ever served
(build._previous_roles), so the sentinel never reaches a dossier or a pin; a test
holds that.

NOT FROM CTAS: Sumner County (its own roster, tn_local, carries districts) and
Davidson County (a consolidated government: its "commissioners" are Nashville's
Metro Council, published once through the cities source's Nashville entry).
"""
from __future__ import annotations

import csv
import io
import json
import re

from .. import divisions as D
from .roster import ADAPTERS, SHARED, Adapter, RosterError, RosterRow, RosterSpec, SharedSource, \
    SourceRef, slug

CTAS = "https://www.ctas.tennessee.edu"
COMMISSIONERS_CSV = f"{CTAS}/csv-county-commissioners?page&_format=csv"
EXECUTIVES_CSV = f"{CTAS}/csv-county-executives-and-mayors?page&_format=csv"
SHARED_KEY = "ctas_tn"
ADAPTER = "tn_ctas_county"
TERMS_REF = "docs/research/ctas-permission-2026-10.md"
REPORTED_BY = "UT County Technical Assistance Service (CTAS)"
USPS = "TN"

# Sumner: its own, finer source (districts). Davidson: consolidated with Nashville,
# whose Metro Council and mayor come from the cities source.
EXCLUDED = {"Sumner", "Davidson"}

# "Number of Commissioners" from each county's CTAS page, read 2026-10-08.
STATED_SIZE = {
    "Anderson": 16, "Bedford": 18, "Benton": 18, "Bledsoe": 13, "Blount": 21, "Bradley": 14,
    "Campbell": 15, "Cannon": 10, "Carroll": 21, "Carter": 24, "Cheatham": 12, "Chester": 18,
    "Claiborne": 21, "Clay": 10, "Cocke": 14, "Coffee": 18, "Crockett": 24, "Cumberland": 18,
    "Davidson": 35, "Decatur": 18, "DeKalb": 14, "Dickson": 12, "Dyer": 20, "Fayette": 19,
    "Fentress": 10, "Franklin": 16, "Gibson": 25, "Giles": 21, "Grainger": 15, "Greene": 21,
    "Grundy": 9, "Hamblen": 14, "Hamilton": 11, "Hancock": 17, "Hardeman": 16, "Hardin": 20,
    "Hawkins": 14, "Haywood": 20, "Henderson": 14, "Henry": 15, "Hickman": 14, "Houston": 14,
    "Humphreys": 14, "Jackson": 18, "Jefferson": 21, "Johnson": 15, "Knox": 11, "Lake": 9,
    "Lauderdale": 24, "Lawrence": 18, "Lewis": 9, "Lincoln": 24, "Loudon": 10, "Macon": 20,
    "Madison": 25, "Marion": 15, "Marshall": 18, "Maury": 22, "McMinn": 10, "McNairy": 21,
    "Meigs": 11, "Monroe": 10, "Montgomery": 21, "Moore": 15, "Morgan": 18, "Obion": 21,
    "Overton": 15, "Perry": 12, "Pickett": 12, "Polk": 10, "Putnam": 24, "Rhea": 9,
    "Roane": 15, "Robertson": 24, "Rutherford": 21, "Scott": 14, "Sequatchie": 18,
    "Sevier": 25, "Shelby": 13, "Smith": 24, "Stewart": 14, "Sullivan": 24, "Sumner": 24,
    "Tipton": 18, "Trousdale": 21, "Unicoi": 9, "Union": 16, "Van Buren": 10, "Warren": 24,
    "Washington": 15, "Wayne": 14, "Weakley": 18, "White": 14, "Williamson": 24, "Wilson": 25,
}
# The size ceiling: a county legislative body has at most 25 members (Tenn. Code Ann.
# § 5-5-102).
STATUTORY_CEILING = 25
# The body each export title names. Moore is a metropolitan government.
BODY = {"County Commissioner": "County Commission", "Metro Councilmember": "Metropolitan Council"}
METRO = {"Moore"}
EXECUTIVE_TITLES = {"County Mayor", "County Executive", "Metro Mayor", "Metro Executive"}
# The export publishes no term dates. Internal sentinel, never served (module doc).
TERM_START = "1900-01-01"

# ── Email allow-rule (owner decision 2026-10-08) ─────────────────────────────
# An email is published only when its domain is a government domain: any *.gov,
# any *.tn.us, or the county's own website domain as the CTAS county-websites page
# lists it (read 2026-10-08), where that site is the county government's (chamber
# of commerce and tourism sites listed there are left out). Anything else (webmail,
# an employer, a typo such as "...countytn.go") is dropped: the row still publishes,
# with no contact.
GOV_SUFFIXES = (".gov", ".tn.us")
COUNTY_DOMAINS = {
    "Blount": "blounttn.org", "Chester": "chestercountytn.org", "Clay": "claycountytngov.com",
    "Coffee": "coffeecountytn.org", "Decatur": "decaturcountytn.org",
    "Dyer": "dyercountygov.com", "Fayette": "fayettetn.us", "Franklin": "franklincotn.us",
    "Gibson": "gibsoncountytn.com", "Grainger": "graingercountytn.com",
    "Greene": "greenecountytngov.com", "Grundy": "grundycountytn.net",
    "Hancock": "hancockcountytn.com", "Hardeman": "hardemancounty.org",
    "Henry": "henrycountytn.org", "Knox": "knoxcounty.org",
    "Lauderdale": "lauderdalecountytn.org", "Lewis": "lewiscountytn.com",
    "Marion": "marioncountytn.net", "McNairy": "mcnairycountytn.org",
    "Meigs": "meigscountytn.org", "Monroe": "monroetn.com", "Montgomery": "mcgtn.org",
    "Moore": "metromoorecounty.org", "Overton": "overtoncountytn.com",
    "Perry": "perrycountytn.com", "Polk": "polkgovernment.com", "Rhea": "rheacountytn.com",
    "Robertson": "robertsoncountytn.org", "Scott": "scottcounty.com",
    "Sevier": "seviercountytn.org", "Stewart": "stewartcogov.com", "Tipton": "tiptonco.com",
    "Unicoi": "unicoicountytn.com", "Van Buren": "vanburencountytn.com",
    "Washington": "washingtoncountytn.org", "Wayne": "waynecountytn.org",
}
_EMAIL = re.compile(r"^[A-Za-z0-9._%+'-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)$")


def official_email(county: str, email: str | None) -> str | None:
    m = _EMAIL.match((email or "").strip())
    if not m:
        return None
    domain = m.group(1).lower()
    own = COUNTY_DOMAINS.get(county)
    if domain.endswith(GOV_SUFFIXES) or (own and (domain == own or domain.endswith("." + own))):
        return m.group(0)
    return None


# ── The shared file: two exports -> one slice per county ─────────────────────

REQUIRED = ("County", "Name", "Title", "Email Address")


def _rows(body: bytes) -> list[dict]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"CTAS export is missing columns {missing}")
    return list(reader)


def _person(r: dict) -> dict:
    county = r["County"].strip()
    return {"name": " ".join(r["Name"].split()), "title": r["Title"].strip(),
            "email": official_email(county, r["Email Address"])}


def split(files: dict[str, bytes]) -> dict[str, bytes]:
    """{locality_id: slice}. A slice holds only what may be published (name,
    title, an allowed email): addresses, fax and other mailboxes never land."""
    out: dict[str, dict] = {}
    for group, name in (("members", "commissioners.csv"), ("executives", "executives.csv")):
        for r in _rows(files[name]):
            county = r["County"].strip()
            if county:
                out.setdefault(locality_id(county), {"members": [], "executives": []})[group] \
                    .append(_person(r))
    return {loc: json.dumps(doc, sort_keys=True, indent=1).encode("utf-8")
            for loc, doc in sorted(out.items())}


def county_url(county: str) -> str:
    return f"{CTAS}/county/{slug(county)}"


def adapter(raw: bytes, spec: RosterSpec) -> list[RosterRow]:
    doc = json.loads(raw)
    url = county_url(spec.name)
    return [RosterRow(name=p["name"], office_title=p["title"], seat_label=None,
                      at_large=group == "members", source_row_url=url,
                      contact={"email": p["email"]} if p["email"] else {})
            for group in ("members", "executives") for p in doc[group]]


def check(rows: list[RosterRow]) -> None:
    execs = [r for r in rows if not r.at_large]
    titles = sorted({r.office_title for r in rows if r.at_large} - set(BODY))
    if len(execs) != 1 or titles or any(r.office_title not in EXECUTIVE_TITLES for r in execs):
        raise RosterError(f"CTAS roster: {len(execs)} county executive(s) listed (expected 1); "
                          f"unrecognised member titles {titles}")


def note(spec: RosterSpec, rows: list[RosterRow]) -> str | None:
    listed, stated = sum(r.at_large for r in rows), STATED_SIZE[spec.name]
    return f"roster lists {listed}; county page states {stated}" if listed > stated else None


def locality_id(county: str) -> str:
    return f"tn-{slug(county)}-county"


ADAPTERS[ADAPTER] = Adapter(adapter, check, note=note)
SHARED[SHARED_KEY] = SharedSource(
    SHARED_KEY, (("commissioners.csv", COMMISSIONERS_CSV), ("executives.csv", EXECUTIVES_CSV)),
    split)


def _spec(county: str) -> RosterSpec:
    stated = STATED_SIZE[county]
    ceiling = max(STATUTORY_CEILING, stated)
    metro = county in METRO
    return RosterSpec(
        locality_id=locality_id(county), ocd_id=D.county_ocd(USPS, county), level="county",
        name=county, body="Metropolitan Council" if metro else "County Commission",
        source=SourceRef(f"ctas_{slug(county).replace('-', '_')}", county_url(county),
                         ADAPTER, shared=SHARED_KEY),
        seats=(stated + 1, ceiling + 1),          # members + the one executive
        terms_ref=TERMS_REF, chamber="county_commission", reported_by=REPORTED_BY,
        term_start=TERM_START)


SPECS = [_spec(c) for c in sorted(STATED_SIZE) if c not in EXCLUDED]
