"""Local rosters behind one interface (WO-22b, DATA-CONTRACTS §8.8).

A locality is a `RosterSpec` plus an adapter: `parse(raw: bytes, spec) -> list[RosterRow]`,
pure and offline-testable. Everything else — the fetcher, the gates, the spine rows the
transform loads, the source registry row, the office display — is generated here from
the spec, so adding a government is a spec, a fixture and a `terms_ref`, not an adapter.

FAIL CLOSED, PER LOCALITY, AND ONLY PER LOCALITY. A roster that fails its gate raises
`RosterError`, and that class alone is isolated: the locality is *withheld* — its last
good roster keeps being served, coverage says so — and the run continues. Anything else
(a network error, a parse bug, a schema break in shared code) propagates and fails the
build, exactly as before. Never catch a broader class to make a run pass.

LAST GOOD, BY CONSTRUCTION. The fetcher lands `roster.html` only after the page passed
its gate, so the landed page is always the last good roster. A page that fails is kept
beside it as `rejected.html` for diagnosis and never read again. The transform re-parses
the landed page, never the network.

PARTY is `"U"` (not published by the source) unless a row states one. Never inferred,
never `"NP"`.
"""
from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from .. import divisions as D

PARTY_NOT_PUBLISHED = "U"
LEVELS = ("county", "place")
TERMS_PREFIX = "docs/research/"


class RosterError(RuntimeError):
    """A roster failed a gate. The ONLY failure isolated per locality."""


@dataclass(frozen=True)
class RosterRow:
    name: str
    office_title: str                 # "County Commissioner", "Alderman", "Mayor"
    seat_label: str | None            # "District 3", "Ward 1"; None = at large
    party: str | None = None          # None when the source states none
    term_start: str | None = None
    term_end: str | None = None
    contact: dict = field(default_factory=dict)    # any of phone / email / url
    source_row_url: str | None = None
    photo_url: str | None = None      # linked, never re-hosted (see the terms_ref)


@dataclass(frozen=True)
class SourceRef:
    source_key: str                   # the config.SOURCES key this spec generates
    url: str                          # the roster page
    adapter: str                      # an ADAPTERS id


@dataclass(frozen=True)
class RosterSpec:
    locality_id: str                  # stable slug, e.g. "tn-sumner-county"
    ocd_id: str
    level: str                        # "county" | "place"
    name: str                         # bare division name: "Sumner", "Hendersonville"
    body: str                         # "County Commission", "Board of Aldermen"
    source: SourceRef
    seats: tuple[int, int]            # (min, max): the gate
    terms_ref: str                    # docs/research/… licence determination
    chamber: str                      # offices.chamber of a seated (non-at-large) member
    term_start: str                   # date the current body took office; never today
    seat_size: int = 1                # members elected per seat label (2 per ward)
    grade_reason: str = "official_web_roster"
    sla_hours: int = 24 * 7

    def __post_init__(self):
        # No licence, no ship: a spec that cannot name the determination it
        # relies on does not load at all.
        if not (self.terms_ref or "").startswith(TERMS_PREFIX):
            raise ValueError(f"roster spec {self.locality_id!r} has no terms_ref under "
                             f"{TERMS_PREFIX} — no licence determination, no spec")
        if self.level not in LEVELS:
            raise ValueError(f"roster spec {self.locality_id!r}: level {self.level!r}")
        if not 0 < self.seats[0] <= self.seats[1]:
            raise ValueError(f"roster spec {self.locality_id!r}: seats {self.seats}")

    @property
    def state(self) -> str:
        return self.ocd_id.split("state:")[1].split("/")[0]

    @property
    def base_url(self) -> str:
        u = urlsplit(self.source.url)
        return f"{u.scheme}://{u.netloc}"


@dataclass(frozen=True)
class Adapter:
    parse: Callable[[bytes, RosterSpec], list[RosterRow]]
    # Structural gate the body defines beyond the generic one (every district
    # exactly once, two aldermen per ward). Raises RosterError.
    check: Callable[[list[RosterRow]], None] | None = None
    # WO-22b one-time id migration: the seat-keyed id a row was published under
    # before ids became person-keyed. Delete once the old keys are gone.
    legacy_person_id: Callable[[RosterRow], str] | None = None


ADAPTERS: dict[str, Adapter] = {}


def specs() -> list[RosterSpec]:
    """Every registered locality, in a stable order."""
    from . import tn_local
    return list(tn_local.SPECS)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# ── Gates (fail closed per locality) ────────────────────────────────────────

def check(spec: RosterSpec, rows: list[RosterRow]) -> None:
    lo, hi = spec.seats
    if not lo <= len(rows) <= hi:
        raise RosterError(f"{spec.name} {spec.body}: {len(rows)} seats listed, expected "
                          f"{lo}" + (f"-{hi}" if hi != lo else ""))
    if any(not r.name.strip() for r in rows):
        raise RosterError(f"{spec.name} {spec.body}: a seat is listed with no name")
    names = [n for n, c in Counter(slug(r.name) for r in rows).items() if c > 1]
    if names:
        raise RosterError(f"{spec.name} {spec.body}: the same person is listed twice ({names})")
    seats = Counter((r.office_title, r.seat_label) for r in rows)
    over = sorted(f"{t} {s or 'at large'}" for (t, s), c in seats.items()
                  if c > (spec.seat_size if s else 1))
    if over:
        raise RosterError(f"{spec.name} {spec.body}: seats listed more times than they "
                          f"exist: {over}")
    extra = ADAPTERS[spec.source.adapter].check
    if extra:
        extra(rows)


def parse(spec: RosterSpec, raw: bytes) -> list[RosterRow]:
    return ADAPTERS[spec.source.adapter].parse(raw, spec)


# ── Landed state ────────────────────────────────────────────────────────────

def landed(spec: RosterSpec, raw_dir: str | Path) -> Path:
    return Path(raw_dir) / spec.source.source_key / "roster.html"


def load(spec: RosterSpec, raw_dir: str | Path, manifest: dict) -> tuple[list[RosterRow] | None, str | None]:
    """(rows being served, withheld reason). rows is None when nothing good has
    ever landed: the locality is then absent, not withheld (§8.10).

    Withheld when this run's fetch failed the gate (the manifest says why), or
    when the landed last-good page fails the gate as the spec now reads. Either
    way the landed page is what the reader was last shown, so it is what keeps
    being served; the reason travels to the coverage file."""
    f = landed(spec, raw_dir)
    if not f.exists():
        return None, None
    rows = parse(spec, f.read_bytes())
    reason = (manifest.get("sources", {}).get(spec.source.source_key) or {}).get("withheld")
    try:
        check(spec, rows)
    except RosterError as e:
        reason = str(e)
    return rows, reason


# ── Fetch (network) ─────────────────────────────────────────────────────────

def _get(url: str) -> bytes:
    import httpx
    r = httpx.get(url, timeout=30.0, follow_redirects=True,
                  headers={"User-Agent": "beholden.vote ETL (+https://beholden.vote)"})
    r.raise_for_status()
    return r.content


def fetch(spec: RosterSpec, raw: Path, prior: dict) -> dict | None:
    """Land the page only if it passes its gate. A gate failure withholds the
    locality: the last good page stays landed and the manifest row keeps its
    ORIGINAL retrieved_at, plus the reason. Any other error propagates."""
    key = spec.source.source_key
    page = _get(spec.source.url)
    rows = parse(spec, page)
    d = Path(raw) / key
    d.mkdir(parents=True, exist_ok=True)
    try:
        check(spec, rows)
    except RosterError as e:
        (d / "rejected.html").write_bytes(page)
        print(f"fetch: roster {spec.locality_id} WITHHELD: {e}")
        last = (prior.get("sources") or {}).get(key)
        if not last or not landed(spec, raw).exists():
            return None                 # nothing good ever landed: absent
        return {**{k: v for k, v in last.items() if k != "withheld"}, "withheld": str(e)}
    landed(spec, raw).write_bytes(page)
    (d / "rejected.html").unlink(missing_ok=True)
    (d / "roster.json").write_text(json.dumps([asdict(r) for r in rows], indent=1),
                                   encoding="utf-8")
    return {"retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_url": spec.source.url, "count": len(rows)}


# ── Spine rows ──────────────────────────────────────────────────────────────

_SEAT = re.compile(r"^(District|Ward)\s+(\d+)$")


def person_id(spec: RosterSpec, name: str) -> str:
    """Keyed on the person within the locality, not the seat (§8.8): a member
    who changes districts keeps one dossier."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"person:{spec.ocd_id}:{slug(name)}"))


def seat_ocd(spec: RosterSpec, label: str | None) -> str:
    if label is None:
        return spec.ocd_id
    m = _SEAT.match(label)
    if not m:
        raise ValueError(f"{spec.locality_id}: no division rule for seat {label!r}")
    fn = D.commission_district_ocd if m.group(1) == "District" else D.ward_ocd
    return fn(spec.ocd_id, int(m.group(2)))


def office_display(spec: RosterSpec, row: RosterRow) -> str:
    if row.seat_label is None:
        return f"{row.office_title} of {spec.name}"
    return f"{spec.name} {spec.body} · {row.seat_label}"


def spine_rows(spec: RosterSpec, rows: list[RosterRow]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"divisions": [], "offices": [], "persons": [],
                                  "person_identifiers": [], "terms": []}
    parent = D.state_ocd(spec.state)
    out["divisions"].append({
        "ocd_id": spec.ocd_id, "parent_ocd": parent, "level": spec.level,
        "name": f"{spec.name} County" if spec.level == "county" else spec.name,
        "geoid": None, "valid_from": spec.term_start, "valid_to": None})
    for r in rows:
        ocd = seat_ocd(spec, r.seat_label)
        pid = person_id(spec, r.name)
        if ocd != spec.ocd_id:
            out["divisions"].append({
                "ocd_id": ocd, "parent_ocd": spec.ocd_id, "level": spec.level,
                "name": f"{spec.name} {spec.body} {r.seat_label}",
                "geoid": None, "valid_from": spec.term_start, "valid_to": None})
        # One office per person-seat: two aldermen share a ward division.
        office_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
                                   f"office:{ocd}:{slug(r.office_title)}:{slug(r.name)}"))
        out["offices"].append({
            "office_id": office_id, "ocd_id": ocd,
            # ponytail: at large = executive holds for a mayor; an at-large
            # council seat would need a branch on the row.
            "branch": "executive" if r.seat_label is None else "legislative",
            "chamber": None if r.seat_label is None else spec.chamber,
            "role": r.office_title})
        out["persons"].append({"person_id": pid, "full_name": r.name, "given_name": None,
                               "family_name": None, "birth_year": None, "wikidata_qid": None})
        out["person_identifiers"].append({"person_id": pid,
                                          "id_scheme": f"local:{spec.source.source_key}",
                                          "id_value": slug(r.name), "is_primary": True})
        start = r.term_start or spec.term_start
        out["terms"].append({
            "term_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"term:{pid}:{office_id}:{start}")),
            "person_id": pid, "office_id": office_id,
            "party": r.party or PARTY_NOT_PUBLISHED,
            "start_date": start, "end_date": None, "is_vacant_marker": False,
            # build reads these keys back (image / source_url / source_key /
            # contact / term_ends / office_display) — no new read path.
            "meta": {"seat": r.seat_label, "image": r.photo_url,
                     "source_url": r.source_row_url, "source_key": spec.source.source_key,
                     "contact": r.contact or None, "social": None,
                     "term_ends": r.term_end, "office_display": office_display(spec, r)}})
    return out


# ── Publish hints (read by jobs/publish.py's stale rule) ────────────────────

def hints(raw_dir: str | Path, manifest: dict) -> dict:
    """{"live": keys of withheld localities, "migrated": old key -> new key|None}.

    live: a withheld locality's objects are not stale, whatever this build
    produced (§8.8). migrated: the seat-keyed ids published before WO-22b, so a
    stale listing names them as id changes rather than as officials who left."""
    live: set[str] = set()
    migrated: dict[str, str | None] = {}
    for spec in specs():
        rows, reason = load(spec, raw_dir, manifest)
        if rows is None:
            continue
        legacy = ADAPTERS[spec.source.adapter].legacy_person_id
        for r in rows:
            pid = person_id(spec, r.name)
            if reason:
                live.add(f"dossiers/{pid}.json")
            if legacy:
                old = legacy(r)
                migrated[f"dossiers/{old}.json"] = f"dossiers/{pid}.json"
                migrated[f"graph/neighborhood/{old}.json"] = None   # no edges: no graph doc
    return {"live": sorted(live), "migrated": dict(sorted(migrated.items()))}
