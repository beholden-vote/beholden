"""The full federal voting record, down to the bill (WO-23a; DATA-CONTRACTS 8.3).

Three artifacts, each keyed by an id the warehouse already uses, written under
prefixes this module owns:

  votes/{person_id}.json        one sitting member's complete record
  rollcalls/{roll_call_id}.json one vote, every current member's position
  bills/{bill_id}.json          one bill that reached a roll call, + bills/index.json

What is deliberately NOT done here, because each would be an invented fact:

  * A member is never "not voting" on a roll call held before they took office.
    Voteview codes that as "not a member" and the transform never lands it, so a
    record lists only the roll calls the member holds a position row for.
  * `totals` is the chamber's official tally. `positions` and `by_party` cover
    only members in office today - the only positions the warehouse holds - so
    they legitimately do not sum to it. Nothing is scaled or inferred to make
    them agree; `positions_cover` says why they differ.
  * A sponsor or cosponsor who has left office publishes by name with
    `person_id: null`. A person_id is linked by bioguide id only, never by name.
  * A bill whose congress.gov record never landed has no page. It is absent
    tonight and fetched tomorrow, not published from the fields we happen to hold.

Symmetric by construction: party breakdowns are ordered alphabetically by party
code, never by size, and every member's file carries the same fields.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .. import store
from ..config import CONGRESS
from ..sources import congress_gov
from . import dossiers, key_votes
from .context import BuildContext

# Roll calls in scope. A state or local roll call flows through everything below
# unchanged; widening this prefix (and the member filter in publish) is the whole
# of admitting one (WO-17b / WO-39).
SCOPE_PREFIX = f"us/{CONGRESS}/"
POSITIONS = ("yea", "nay", "present", "not_voting")
# Ids are used as object keys verbatim (rollcalls/us/119/house/312.json). One
# character outside this set and the object is unreachable, so it fails the
# build rather than publishing a key nobody can fetch.
_KEY_RE = re.compile(r"[a-z0-9/._-]+")


def _natural(key: str) -> list:
    """Sort key that orders 'us/119/house/9' before 'us/119/house/10'."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", key)]


def _newest_first(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (r["held_at"], _natural(r["roll_call_id"])),
                  reverse=True)


def summarize(votes: list[dict]) -> dict:
    """A member's summary from their vote rows ({position, party_position}).

    with_party / against_party use the published party-agreement rule
    (key_votes.agreement_pct, /methodology#co-voting) and nothing else: only the
    member's yea/nay votes count, and only on roll calls where their party had a
    majority position. So with_party + against_party == party_decided always,
    and with_party / party_decided is the dossier's party_agreement_pct."""
    cast = Counter(v["position"] for v in votes)
    decided = [v for v in votes if v["position"] in ("yea", "nay") and v["party_position"]]
    with_party = sum(1 for v in decided if v["position"] == v["party_position"])
    return {"total": len(votes), **{p: cast.get(p, 0) for p in POSITIONS},
            "party_decided": len(decided), "with_party": with_party,
            "against_party": len(decided) - with_party}


def _legislator(item: dict, person_by_bioguide: dict[str, str]) -> dict:
    """A sponsor or cosponsor exactly as congress.gov names them. The same four
    fields for everyone; person_id is null for anyone not in office today."""
    name = " ".join(p for p in (item.get("firstName"), item.get("lastName")) if p)
    return {"person_id": person_by_bioguide.get(item.get("bioguideId")),
            "name": name or item.get("fullName"),
            "party": item.get("party"), "state": item.get("state")}


def _write(out: Path, prefix: str, key: str, doc: dict) -> None:
    if not _KEY_RE.fullmatch(key):
        raise ValueError(f"{prefix} id {key!r} is not a servable object key "
                         "(allowed: [a-z0-9/._-]) - refusing to publish it")
    # Rule #1: the same validator the dossier builder uses, on every document.
    dossiers._check_provenance({"person_id": f"{prefix}/{key}", "doc": doc}, "doc")
    path = out / prefix / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")


def publish(ctx: BuildContext) -> dict[str, int]:
    # Imported here, not at module top: jobs.build imports this module to
    # register it, so a top-level import would be a cycle. These are build's own
    # helpers and constants, reused rather than copied.
    from ..jobs import build as B

    con = store.connect(ctx.db_path)
    try:
        # The date is rendered from the epoch, not held_at::VARCHAR: DuckDB
        # prints a TIMESTAMPTZ in the BUILDER'S time zone, so a midnight-UTC
        # vote would publish as the previous day on any machine west of it.
        roll_calls = [
            {"roll_call_id": rcid, "chamber": chamber, "question": question,
             "result": result, "bill_id": bill_id, "yea_count": yea,
             "nay_count": nay, "held_at": held_on}
            for rcid, chamber, question, result, bill_id, yea, nay, held_on in con.execute(
                """SELECT roll_call_id, chamber, question, result, bill_id,
                          yea_count, nay_count,
                          strftime(make_timestamp(epoch_us(held_at)), '%Y-%m-%d')
                   FROM roll_calls WHERE starts_with(roll_call_id, ?)
                   ORDER BY roll_call_id""", [SCOPE_PREFIX]).fetchall()]
        positions = con.execute(
            """SELECT roll_call_id, person_id::VARCHAR, position FROM vote_positions
               WHERE starts_with(roll_call_id, ?)
               ORDER BY roll_call_id, person_id""", [SCOPE_PREFIX]).fetchall()
        bills = {bill_id: {"title": title, "status": status, "introduced_on": introduced_on,
                           "policy_area": next((a for a in areas or [] if a), None)}
                 for bill_id, title, status, introduced_on, areas in con.execute(
                     """SELECT bill_id, title, status, introduced_on::VARCHAR, policy_areas
                        FROM bills WHERE bill_id IN (
                          SELECT bill_id FROM roll_calls WHERE starts_with(roll_call_id, ?))""",
                     [SCOPE_PREFIX]).fetchall()}
    finally:
        con.close()
    if not roll_calls:
        # No roll calls landed (the source was never fetched). A record of
        # "0 votes" for every member would be a fabricated zero - publish nothing.
        return {"votes": 0, "rollcalls": 0, "bills": 0}

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    people = {h["person_id"]: h for h in ctx.holders if not h["is_vacant_marker"]}
    meta = B._rollcall_meta(ctx.raw_dir)        # official record url + description
    majority = key_votes.party_majority_positions(
        [{"roll_call_id": rcid, "party": people[pid]["party"], "position": position}
         for rcid, pid, position in positions if pid in people])

    def bill_fields(rc: dict) -> dict:
        bill = bills.get(rc["bill_id"]) or {}
        return {"bill_id": rc["bill_id"], "bill_title": bill.get("title"),
                "policy_area": bill.get("policy_area")}

    cast_on: dict[str, list[tuple[str, str]]] = {}     # roll_call_id -> [(person_id, position)]
    cast_by: dict[str, list[tuple[str, str]]] = {}     # person_id -> [(roll_call_id, position)]
    for rcid, pid, position in positions:
        if pid in people:
            cast_on.setdefault(rcid, []).append((pid, position))
            cast_by.setdefault(pid, []).append((rcid, position))
    rc_by_id = {rc["roll_call_id"]: rc for rc in roll_calls}

    # --- rollcalls/{roll_call_id}.json ---
    for rc in roll_calls:
        rcid = rc["roll_call_id"]
        cast = sorted(cast_on.get(rcid, []), key=lambda c: (
            (people[c[0]]["family_name"] or people[c[0]]["full_name"] or "").casefold(),
            (people[c[0]]["given_name"] or "").casefold(), c[0]))
        tally: dict[str, Counter] = {}
        for pid, position in cast:
            tally.setdefault(people[pid]["party"], Counter())[position] += 1
        url = (meta.get(rcid) or {}).get("url")
        _write(ctx.out, "rollcalls", rcid, {
            "schema_version": dossiers.SCHEMA_VERSION, "roll_call_id": rcid,
            "generated_at": generated_at, "chamber": rc["chamber"],
            "held_at": rc["held_at"], "question": rc["question"],
            "description": (meta.get(rcid) or {}).get("description"),
            "result": rc["result"], "url": url, **bill_fields(rc),
            "totals": {"yea": rc["yea_count"], "nay": rc["nay_count"]},
            "by_party": [{"party": party, **{p: tally[party].get(p, 0) for p in POSITIONS}}
                         for party in sorted(tally)],
            "positions": [{"person_id": pid, "name": people[pid]["full_name"],
                           "party": people[pid]["party"],
                           "state": (B._state_from_ocd(people[pid]["ocd_id"]) or "").upper() or None,
                           "ocd_id": people[pid]["ocd_id"], "position": position}
                          for pid, position in cast],
            "positions_cover": "current_members",
            "provenance": ctx.provenance(
                "voteview", url or f"https://voteview.com/congress/{rc['chamber']}"),
        })

    # --- votes/{person_id}.json: every sitting member, identical fields ---
    members = [h for h in people.values() if h["chamber"] in B.FEDERAL_CHAMBERS]
    for h in members:
        votes = _newest_first([
            {"roll_call_id": rcid, "held_at": rc_by_id[rcid]["held_at"],
             "question": rc_by_id[rcid]["question"], "position": position,
             "party_position": majority.get(f"{rcid}\t{h['party']}"),
             "result": rc_by_id[rcid]["result"],
             "yea_count": rc_by_id[rcid]["yea_count"],
             "nay_count": rc_by_id[rcid]["nay_count"], **bill_fields(rc_by_id[rcid])}
            for rcid, position in cast_by.get(h["person_id"], [])])
        _write(ctx.out, "votes", h["person_id"], {
            "schema_version": dossiers.SCHEMA_VERSION, "person_id": h["person_id"],
            "generated_at": generated_at, "scope": B.IDEOLOGY_SCOPE,
            "summary": summarize(votes), "votes": votes,
            "provenance": ctx.provenance(
                "voteview", f"https://voteview.com/congress/{h['chamber']}",
                methodology_id=B.METHODOLOGY_AGREEMENT),
        })

    # --- bills/{bill_id}.json: only bills whose congress.gov record landed ---
    person_by_bioguide = {h["bioguide"]: pid for pid, h in people.items() if h.get("bioguide")}
    landed = congress_gov.landed_bills(ctx.raw_dir)
    votes_on: dict[str, list[dict]] = {}
    for rc in roll_calls:
        if rc["bill_id"]:
            votes_on.setdefault(rc["bill_id"], []).append(rc)
    index = []
    for bill_id in sorted(votes_on, key=_natural):
        record = landed.get(bill_id)
        if record is None or bill_id not in bills:
            continue                                  # not fetched: absent, never invented
        bill = bills[bill_id]
        cosponsors = sorted(
            (c for c in record.get("cosponsors") or [] if not c.get("sponsorshipWithdrawnDate")),
            key=lambda c: ((c.get("lastName") or "").casefold(),
                           (c.get("firstName") or "").casefold(), c.get("bioguideId") or ""))
        by_party = Counter(c.get("party") or "" for c in cosponsors)
        sponsors = (record.get("bill") or {}).get("sponsors") or []
        on_bill = _newest_first(votes_on[bill_id])
        url = congress_gov.bill_public_url(bill_id)
        number = congress_gov.bill_display_number(bill_id)
        _write(ctx.out, "bills", bill_id, {
            "schema_version": dossiers.SCHEMA_VERSION, "bill_id": bill_id,
            "generated_at": generated_at, "number": number, "title": bill["title"],
            "policy_area": bill["policy_area"], "introduced_on": bill["introduced_on"],
            "status": bill["status"], "url": url,
            "sponsor": _legislator(sponsors[0], person_by_bioguide) if sponsors else None,
            "cosponsors": {
                "total": len(cosponsors),
                "by_party": [{"party": party, "count": by_party[party]}
                             for party in sorted(by_party)],
                "members": [_legislator(c, person_by_bioguide) for c in cosponsors]},
            "roll_calls": [{k: rc[k] for k in ("roll_call_id", "held_at", "question",
                                               "result", "yea_count", "nay_count")}
                           for rc in on_bill],
            "provenance": ctx.provenance("congress.gov", url),
        })
        index.append({"bill_id": bill_id, "number": number, "title": bill["title"],
                      "policy_area": bill["policy_area"],
                      "last_vote_at": on_bill[0]["held_at"]})
    _write(ctx.out, "bills", "index", {
        "schema_version": dossiers.SCHEMA_VERSION, "generated_at": generated_at,
        "bills": index,
        "provenance": ctx.provenance("congress.gov", "https://www.congress.gov/"),
    })

    return {"votes": len(members), "rollcalls": len(roll_calls), "bills": len(index)}
