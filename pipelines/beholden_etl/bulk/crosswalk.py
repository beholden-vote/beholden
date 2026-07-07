"""Deterministic filer<->person crosswalk for Tier-A disclosure sources
(docs/TRUSTED-EXTRACTION.md §9; WO-19). First user: WA PDC (sources/wa_pdc.py).

Entity resolution is where fabrication would enter, so this module is built
around one rule: **publish only on deterministic keys**. WA PDC and OpenStates
share no native identifier (verified 2026-07-07 — Wikidata has no WA PDC
property, the OpenStates people CSV carries no PDC id, and PDC publishes no
external ids; see docs/research/wa-pdc-reconciliation-findings.md §4), so the
only deterministic key is a committed, HUMAN-REVIEWED allowlist mapping PDC's
person_id to an ocd-person id already in the spine (wa_pdc_allowlist.json).

Everything name-shaped goes the other way: `score_candidates` emits rows for the
disclosure_link_candidates QUARANTINE table — per state-legislative candidacy
fund, the seat's current spine holder plus a deterministic name-equality flag as
review context. The build stage never reads that table; a human promotes a
verified candidate by adding an allowlist entry. Model-free throughout.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_ALLOWLIST = Path(__file__).with_name("wa_pdc_allowlist.json")

# PDC itemized `office` values that are WA state-legislative seats, mapped to our
# spine chamber. Anything else (statewide, county, city, judicial) is not a
# legislator candidacy and produces no candidate row. Verified against the live
# office value-domain 2026-07-07.
OFFICE_CHAMBER = {"STATE SENATOR": "upper", "STATE REPRESENTATIVE": "lower"}

_ENTRY_KEYS = ("wa_pdc_person_id", "ocd_person", "evidence_url", "reviewed_on")


class AllowlistError(ValueError):
    """The committed allowlist is malformed — fail closed, never guess."""


def load_allowlist(path: Path | str = DEFAULT_ALLOWLIST) -> list[dict]:
    """Load + strictly validate the reviewed allowlist. A malformed file or a
    duplicate/conflicting mapping raises (config error -> halt); an empty
    entries list is the honest steady state until a human promotes candidates."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = doc.get("entries")
    if not isinstance(entries, list):
        raise AllowlistError(f"{path}: 'entries' must be a list")
    seen: dict[str, str] = {}
    for e in entries:
        if not isinstance(e, dict) or not all(e.get(k) for k in _ENTRY_KEYS):
            raise AllowlistError(
                f"{path}: every entry needs non-empty {list(_ENTRY_KEYS)}, got {e!r}")
        pdc_id = str(e["wa_pdc_person_id"])
        if seen.get(pdc_id, e["ocd_person"]) != e["ocd_person"]:
            raise AllowlistError(
                f"{path}: conflicting ocd_person mappings for wa_pdc_person_id {pdc_id}")
        seen[pdc_id] = e["ocd_person"]
    return entries


def candidate_funds(summary_records: list[dict]) -> list[dict]:
    """The candidate-filer registry slice of the summary feed: one dict per fund
    whose filer_type is 'CA' (candidate). Values are verbatim copies; a row
    without a fund_id has nothing to correlate and is skipped (it can never
    match ingested itemized rows, which always carry one)."""
    out = []
    for rec in summary_records:
        if rec.get("filer_type") != "CA" or not rec.get("fund_id"):
            continue
        url = rec.get("url")
        if isinstance(url, dict):
            url = url.get("url")
        out.append({
            "fund_id": str(rec["fund_id"]),
            "filer_id": rec.get("filer_id"),
            "committee_id": rec.get("committee_id"),
            "wa_pdc_person_id": (None if rec.get("person_id") is None
                                 else str(rec.get("person_id"))),
            "election_year": rec.get("election_year"),
            "filer_name": rec.get("filer_name"),
            "contributions_amount": rec.get("contributions_amount"),
            "expenditures_amount": rec.get("expenditures_amount"),
            "updated_at": rec.get("updated_at"),
            "url": url if isinstance(url, str) else None,
        })
    return out


def links_from_allowlist(allowlist: list[dict], funds: list[dict],
                         resolve_ocd_person) -> tuple[list[dict], list[dict]]:
    """Join the reviewed allowlist to the candidate-fund registry on the exact
    PDC person_id, resolving ocd_person -> spine person_id via the caller's
    lookup (person_identifiers, id_scheme='openstates').

    Returns (links, unresolved): `links` is one dict per (person, fund) ready
    for disclosure_filer_links (minus the provenance envelope, which the caller
    stamps from the snapshot manifest); `unresolved` records allowlist entries
    that matched nothing — surfaced to the quarantine table so a stale entry is
    visible, never silently inert.
    """
    by_person: dict[str, list[dict]] = {}
    for f in funds:
        if f["wa_pdc_person_id"]:
            by_person.setdefault(f["wa_pdc_person_id"], []).append(f)

    links, unresolved = [], []
    for entry in allowlist:
        pdc_id = str(entry["wa_pdc_person_id"])
        spine_person = resolve_ocd_person(entry["ocd_person"])
        person_funds = by_person.get(pdc_id, [])
        if spine_person is None or not person_funds:
            reason = ("ocd_person not in spine" if spine_person is None
                      else "wa_pdc_person_id has no candidate funds in this slice")
            unresolved.append({"entry": entry, "reason": reason})
            continue
        for f in person_funds:
            links.append({"person_id": spine_person, "evidence_url": entry["evidence_url"],
                          **{k: f[k] for k in ("fund_id", "filer_id", "committee_id",
                                               "wa_pdc_person_id", "election_year",
                                               "filer_name", "contributions_amount",
                                               "expenditures_amount", "updated_at", "url")}})
    return links, unresolved


def _name_variants(filer_name: str | None) -> list[str]:
    """The PDC filer_name's comparable variants: the whole cell, the part before
    a trailing parenthetical, and the parenthetical alias itself — e.g.
    'Robert D. Hicks (Robert (Chili) Hicks)' -> all three, casefolded. Pure
    string mechanics on the verbatim cell; used ONLY as review context for the
    quarantine table, never for publication."""
    if not filer_name:
        return []
    text = str(filer_name).strip()
    variants = [text]
    if text.endswith(")") and "(" in text:
        head, _, tail = text.partition("(")
        variants += [head.strip(), tail[:-1].strip()]
    return [v.casefold() for v in variants if v]


def score_candidates(candidacies: list[dict], seat_index: dict,
                     funds_by_id: dict) -> list[dict]:
    """Rows for the disclosure_link_candidates quarantine table (§9 — scored,
    never auto-published). `candidacies` are the distinct state-legislative
    candidacy funds observed in the ingested itemized rows ({fund_id, filer_id,
    filer_name, office, legislative_district}); `seat_index` maps
    (chamber, district:str) -> {person_id, ocd_person, full_name} for the
    jurisdiction's current spine holders; `funds_by_id` is the summary registry
    (candidate_funds) keyed by fund_id, supplying PDC's person_id and the
    campaign's election_year.

    The match basis is descriptive review context: the seat's current holder by
    exact (chamber, district), plus whether the spine full_name equals one of the
    filer_name's verbatim variants (case-insensitive). Deterministic, symmetric,
    and quarantined either way."""
    rows = []
    for c in sorted(candidacies, key=lambda c: c["fund_id"]):
        chamber = OFFICE_CHAMBER.get(c.get("office") or "")
        if not chamber:
            continue
        district = str(c.get("legislative_district") or "").strip()
        district = str(int(district)) if district.isdigit() else district
        seat = seat_index.get((chamber, district))
        reg = funds_by_id.get(c["fund_id"], {})
        name_exact = bool(seat) and (
            (seat["full_name"] or "").casefold() in _name_variants(c.get("filer_name")))
        try:
            year = int(reg.get("election_year"))
        except (TypeError, ValueError):
            year = None
        rows.append({
            "wa_pdc_person_id": reg.get("wa_pdc_person_id"),
            "filer_id": c.get("filer_id"),
            "fund_id": c["fund_id"],
            "election_year": year,
            "filer_name": c.get("filer_name"),
            "office": c.get("office"),
            "legislative_district": c.get("legislative_district"),
            "matched_person_id": seat["person_id"] if seat else None,
            "matched_ocd_person": seat["ocd_person"] if seat else None,
            "matched_name": seat["full_name"] if seat else None,
            "match_basis": (f"seat:{chamber}/{district} name_exact={str(name_exact).lower()}"
                            if seat else f"seat:{chamber}/{district} no current holder"),
        })
    return rows
