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

SHARED FILES. Some publishers export one file covering many localities (a statewide
directory). A spec whose `SourceRef.shared` names a `SharedSource` gets its page from
that file: it is downloaded ONCE per run (whatever the number of localities), split
into one slice per locality, and each slice is then gated, landed and kept as last
good exactly like a page of its own. If the shared file itself cannot be fetched or
split, every locality it feeds is withheld (last good served) and the run continues:
that, and only that, is how a shared fetch differs from a page fetch.

AT-LARGE MEMBERS. A row with no seat label is either the executive (one per title) or,
with `at_large=True`, a member of the body whose seat is not separately labelled
(elected at large, or the source lists no seat). Several of those under one title are
separate people, not a duplicate seat; the person check still applies.
"""
from __future__ import annotations

import json
import re
import threading
import time
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
    # A member of the body with no seat label (see the module doc). False with no
    # seat label = the executive.
    at_large: bool = False


@dataclass(frozen=True)
class SourceRef:
    source_key: str                   # the config.SOURCES key this spec generates
    url: str                          # the roster page
    adapter: str                      # an ADAPTERS id
    shared: str | None = None         # a SHARED id: the page is a slice of that file


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
    reported_by: str                  # the publishing government, as a reader names it
    term_start: str                   # date the current body took office; never today
    seat_size: int = 1                # members elected per seat label (2 per ward)
    # Photos publish only where the terms determination allows them (an explicit
    # "All rights reserved" site gets none). Off unless a spec turns it on.
    photos: bool = False
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
    # A plain source note for a locality that PASSED its gate but where the
    # source disagrees with itself (e.g. more members listed than its stated
    # size). Carried as the coverage entry's `reason` on `covered` (§8.10).
    note: Callable[[RosterSpec, list[RosterRow]], str | None] | None = None


@dataclass(frozen=True)
class SharedSource:
    """One file (or a few, fetched together) that carries many localities."""
    key: str                             # stable id (logs, the memo)
    files: tuple[tuple[str, str], ...]   # (name, url), each fetched once per run
    # {name: bytes} -> {locality_id: slice bytes}. Raises on a file it cannot read.
    split: Callable[[dict[str, bytes]], dict[str, bytes]]


ADAPTERS: dict[str, Adapter] = {}
SHARED: dict[str, SharedSource] = {}


# Modules (under sources/) whose SPECS list registers localities. One line each,
# append-only, so parallel additions stay one-line diffs.
SPEC_MODULES = (
    "tn_local",
    "tn_ctas",
    "tn_mtas",
)


def specs() -> list[RosterSpec]:
    """Every registered locality, in a stable order."""
    import importlib
    return [s for m in SPEC_MODULES
            for s in importlib.import_module(f"{__package__}.{m}").SPECS]


def reported_by(source_key: str) -> str | None:
    """The government a roster-built fact is "as reported by" (shown on the
    provenance line), or None for a source that is not a roster."""
    return next((s.reported_by for s in specs() if s.source.source_key == source_key), None)


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
    # At-large members are told apart by person (checked above), not by seat.
    seats = Counter((r.office_title, r.seat_label) for r in rows if not r.at_large)
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


def note(spec: RosterSpec, rows: list[RosterRow]) -> str | None:
    fn = ADAPTERS[spec.source.adapter].note
    return fn(spec, rows) if fn else None


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

USER_AGENT = "Beholden roster fetch, maintainers@beholden.vote (+https://beholden.vote)"
SHARED_PAUSE_S = 1.0                  # between the files of one shared source


def _get(url: str) -> bytes:
    import httpx
    r = httpx.get(url, timeout=60.0, follow_redirects=True,
                  headers={"User-Agent": USER_AGENT})
    r.raise_for_status()                # a 403 / 429 stops here: no retry, no workaround
    return r.content


# One download per shared source per run, however many localities (threads) ask.
# ponytail: memo keyed on (source, raw dir) for the life of the process; one
# process is one run. A long-lived caller would clear _shared_memo per run.
_shared_lock = threading.Lock()
_shared_memo: dict[tuple[str, str], dict[str, bytes] | RosterError] = {}


def _shared_slices(shared: SharedSource, raw: Path) -> dict[str, bytes]:
    memo_key = (shared.key, str(Path(raw).resolve()))
    with _shared_lock:
        if memo_key not in _shared_memo:
            try:
                files = {}
                for i, (name, url) in enumerate(shared.files):
                    if i:
                        time.sleep(SHARED_PAUSE_S)
                    files[name] = _get(url)
                # Only the slices are kept (landed per locality): a statewide export
                # can carry fields we never publish, so the whole file is not stored.
                _shared_memo[memo_key] = shared.split(files)
            # Approved scope (WO-22b): a shared file that cannot be fetched or
            # split withholds every locality it feeds, and only those.
            except Exception as e:  # noqa: BLE001
                print(f"fetch: shared source {shared.key} FAILED: {type(e).__name__}: {e}")
                _shared_memo[memo_key] = RosterError(
                    f"the shared source file could not be read ({type(e).__name__})")
        got = _shared_memo[memo_key]
    if isinstance(got, RosterError):
        raise got
    return got


def _page(spec: RosterSpec, raw: Path) -> bytes:
    if not spec.source.shared:
        return _get(spec.source.url)
    slices = _shared_slices(SHARED[spec.source.shared], raw)
    if spec.locality_id not in slices:
        raise RosterError(f"{spec.name} {spec.body}: not listed in the shared source file")
    return slices[spec.locality_id]


def _restore_last_good(spec: RosterSpec, raw: Path) -> dict | None:
    """Pull this locality's last good page and manifest row from the lake's
    raw/latest/ pointer. None when there are no R2 credentials or the lake has
    neither; any other error propagates."""
    from botocore.exceptions import ClientError

    from .. import rawlake
    if not rawlake.r2_available():
        return None
    client = rawlake._client()
    key = spec.source.source_key
    try:
        manifest = json.loads(client.get_object(
            Bucket=rawlake.R2_BUCKET, Key=f"{rawlake.LATEST_PREFIX}manifest.json")["Body"].read())
        page = client.get_object(Bucket=rawlake.R2_BUCKET,
                                 Key=f"{rawlake.LATEST_PREFIX}{key}/roster.html")["Body"].read()
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return None
        raise
    last = (manifest.get("sources") or {}).get(key)
    if not (last and last.get("retrieved_at")):
        return None
    landed(spec, raw).write_bytes(page)
    print(f"fetch: roster {spec.locality_id} restored its last good page from the lake")
    return {k: v for k, v in last.items() if k != "withheld"}


def fetch(spec: RosterSpec, raw: Path, prior: dict) -> dict | None:
    """Land the page only if it passes its gate. A gate failure withholds the
    locality: the last good page stays landed and the manifest row keeps its
    ORIGINAL retrieved_at, plus the reason. Any other error propagates."""
    key = spec.source.source_key
    d = Path(raw) / key
    d.mkdir(parents=True, exist_ok=True)
    page = None
    try:
        page = _page(spec, Path(raw))   # raises RosterError only for a shared source
        rows = parse(spec, page)
        check(spec, rows)
    except RosterError as e:
        if page is not None:
            (d / "rejected.html").write_bytes(page)
        print(f"fetch: roster {spec.locality_id} WITHHELD: {e}")
        last = (prior.get("sources") or {}).get(key)
        if not last or not landed(spec, raw).exists():
            # A full rebuild skips hydration, so the last good page is not on
            # disk. It is still in the lake: restore it, so the locality is
            # served (and kept live for publish) exactly as on any other night.
            last = _restore_last_good(spec, Path(raw))
        if not last:
            return None                 # nothing good ever landed anywhere: absent
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
    if row.at_large:
        return f"{spec.name} {spec.body}"
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
        executive = r.seat_label is None and not r.at_large
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
            # No seat label and not at large = the executive (a mayor).
            "branch": "executive" if executive else "legislative",
            "chamber": None if executive else spec.chamber,
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
            "meta": {"seat": r.seat_label, "image": r.photo_url if spec.photos else None,
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
