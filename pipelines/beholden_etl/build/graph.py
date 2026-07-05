"""Entity graph — neighborhood emitter (WO-4, contract §4).

Materializes the §4 entity graph: for every current member, a neighborhood
document of typed, evidence-carrying edges to the members they are connected to.

    /graph/neighborhood/{person_id}.json

THE rule of this file: **an edge with no receipts is a bug.** Every edge is
derived from a DETERMINISTIC key already in the warehouse — never a probabilistic
name/employer match (the trap that deferred Shor-McCarty; TRUSTED-EXTRACTION §9).
The deterministic key per edge type:

  cosponsorship  shared bill_id (deterministic bills-spine id) where both members
                 are role='sponsor' in the window. Evidence: up to 25 bill refs.
  co_voting      shared roll_call_id (deterministic) where both cast yea/nay;
                 agreement = matched / shared over >= MIN_SHARED_VOTES. Evidence:
                 sample of 25 shared roll-call refs. method string stated inline.
  shared_donor   identical contributor_name (verbatim FEC employer rollup string,
                 exact match) in both members' top contributors for the same cycle.
                 Evidence: the FEC aggregate rows. Carries its verbatim caveat.
  committee      shared committee_id (deterministic thomas/openstates code) in the
                 current congress. Evidence: the shared committee refs.

Every rule is symmetric by construction (rule #3): the same formula, the same
truncation, the same ordering for every member regardless of party. Edges are
pairwise WITHIN a chamber/jurisdiction bucket (a House member never links to a
senator here) and capped to the ~25 strongest per person, strongest-first, by a
single deterministic key applied to everyone.
"""
from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

# Co-voting needs a real shared-vote base before a percentage is honest; below
# this a handful of shared votes would over-state precision (mirrors the
# key_votes MIN_AGREEMENT_VOTES gate, one notch higher for a pairwise base).
MIN_SHARED_VOTES = 50
# Inline evidence cap per edge (contract §4: "capped at 25 inline"); the count of
# all supporting facts rides along as evidence_total.
EVIDENCE_CAP = 25
# Strongest edges kept per person's neighborhood (contract §4: "top ~25 edges").
EDGES_PER_PERSON = 25

# Verbatim caveat for shared_donor edges — part of the contract, must render in
# the UI wherever the edge appears (correlation edges always carry their caveat).
SHARED_DONOR_CAVEAT = (
    "shared top contributors are reported-employer aggregates; no coordination is implied")
# The co-voting agreement formula, stated in the payload so a reader can
# reproduce it (arithmetic on public votes — no caveat required, but the method
# is disclosed).
CO_VOTING_METHOD = (
    "agreement = shared yea/nay roll calls where both cast the same position, "
    "divided by shared yea/nay roll calls (min 50 shared)")


def _pair_key(a: str, b: str) -> tuple[str, str]:
    """Canonical, order-independent pair key. Sorting both ids means the edge is
    computed once and is identical whichever member's neighborhood asks for it
    (symmetric by construction)."""
    return (a, b) if a <= b else (b, a)


def cosponsorship_edges(
    members: list[str],
    sponsorships: dict[str, list[dict]],
    window: str,
) -> list[dict]:
    """Shared-bill edges. `sponsorships` is person_id -> [{bill_id, url}] of bills
    that member sponsored. An edge exists when two members sponsored the SAME
    bill_id (exact, deterministic id) — evidence is the intersecting bill set,
    capped at 25, weight = the true total count."""
    member_set = set(members)
    by_bill: dict[str, list[str]] = {}
    ref_by_bill: dict[str, dict] = {}
    for pid, bills in sponsorships.items():
        if pid not in member_set:
            continue
        for b in bills:
            by_bill.setdefault(b["bill_id"], []).append(pid)
            ref_by_bill[b["bill_id"]] = {"kind": "bill", "id": b["bill_id"], "url": b.get("url")}
    shared: dict[tuple[str, str], list[str]] = {}
    for bill_id, pids in by_bill.items():
        for a, b in combinations(sorted(set(pids)), 2):
            shared.setdefault(_pair_key(a, b), []).append(bill_id)
    edges = []
    for (a, b), bill_ids in shared.items():
        bill_ids = sorted(bill_ids)             # deterministic evidence order
        edges.append({
            "type": "cosponsorship", "a": a, "b": b,
            "weight": len(bill_ids), "window": window,
            "evidence": [ref_by_bill[bid] for bid in bill_ids[:EVIDENCE_CAP]],
            "evidence_total": len(bill_ids),
        })
    return edges


def co_voting_edges(
    members: list[str],
    positions: dict[str, dict[str, str]],
    rc_refs: dict[str, dict],
    window: str,
) -> list[dict]:
    """Co-voting agreement edges. `positions` is person_id -> {roll_call_id ->
    'yea'|'nay'} (decided votes only). Two members share a roll call when both
    cast a decided position on the SAME roll_call_id (deterministic). weight is
    the agreement percentage over their shared decided votes, published only at
    or above MIN_SHARED_VOTES. Evidence is a sample of shared roll-call refs."""
    member_set = [m for m in members if m in positions]
    edges = []
    for a, b in combinations(sorted(member_set), 2):
        pa, pb = positions[a], positions[b]
        shared = sorted(set(pa) & set(pb))      # deterministic sample order
        if len(shared) < MIN_SHARED_VOTES:
            continue
        agree = sum(1 for rc in shared if pa[rc] == pb[rc])
        pct = round(100.0 * agree / len(shared), 1)
        edges.append({
            "type": "co_voting", "a": a, "b": b,
            "weight": pct, "window": window,
            "method": CO_VOTING_METHOD,
            "evidence": [rc_refs[rc] for rc in shared[:EVIDENCE_CAP] if rc in rc_refs],
            "evidence_total": len(shared),
        })
    return edges


def shared_donor_edges(
    members: list[str],
    contributors: dict[str, list[dict]],
    cycle: int | None,
    window: str,
) -> list[dict]:
    """Shared-donor edges. `contributors` is person_id -> [{name, total_cents}] of
    a member's top contributors (FEC employer rollups). An edge exists when the
    SAME contributor_name string (verbatim, exact match — never fuzzy) appears in
    both members' lists. Evidence is the FEC aggregate rows for each side; carries
    the verbatim caveat. weight = number of shared contributor names."""
    member_set = set(members)
    totals: dict[str, dict[str, int]] = {}      # person -> name -> total_cents
    for pid, rows in contributors.items():
        if pid not in member_set:
            continue
        for r in rows:
            totals.setdefault(pid, {})[r["name"]] = r["total_cents"]
    edges = []
    for a, b in combinations(sorted(totals), 2):
        ta, tb = totals[a], totals[b]
        shared = sorted(set(ta) & set(tb))      # deterministic order
        if not shared:
            continue
        evidence = [{
            "kind": "fec_employer", "name": name,
            "a_total_cents": ta[name], "b_total_cents": tb[name],
        } for name in shared[:EVIDENCE_CAP]]
        edge = {
            "type": "shared_donor", "a": a, "b": b,
            "weight": len(shared), "window": window,
            "evidence": evidence, "evidence_total": len(shared),
            "caveat": SHARED_DONOR_CAVEAT,
        }
        if cycle is not None:
            edge["cycle"] = cycle
        edges.append(edge)
    return edges


def committee_edges(
    members: list[str],
    memberships: dict[str, list[dict]],
    window: str,
) -> list[dict]:
    """Shared-committee edges. `memberships` is person_id -> [{committee_id,
    name}] of the committees a member sits on. An edge exists when both sit on the
    SAME committee_id (deterministic thomas/openstates code). Evidence is the
    shared committee refs; weight = number of shared committees."""
    member_set = set(members)
    by_committee: dict[str, list[str]] = {}
    ref_by_committee: dict[str, dict] = {}
    for pid, rows in memberships.items():
        if pid not in member_set:
            continue
        for r in rows:
            by_committee.setdefault(r["committee_id"], []).append(pid)
            ref_by_committee[r["committee_id"]] = {
                "kind": "committee", "id": r["committee_id"], "name": r.get("name")}
    shared: dict[tuple[str, str], list[str]] = {}
    for cid, pids in by_committee.items():
        for a, b in combinations(sorted(set(pids)), 2):
            shared.setdefault(_pair_key(a, b), []).append(cid)
    edges = []
    for (a, b), cids in shared.items():
        cids = sorted(cids)
        edges.append({
            "type": "committee", "a": a, "b": b,
            "weight": len(cids), "window": window,
            "evidence": [ref_by_committee[cid] for cid in cids[:EVIDENCE_CAP]],
            "evidence_total": len(cids),
        })
    return edges


# Strongest-first ordering key for truncation. Same rule for every person and
# both parties (rule #3): heavier weight first, then a deterministic tiebreak on
# type then the two ids, so the top-N cut is reproducible run to run.
_TYPE_ORDER = {"co_voting": 0, "cosponsorship": 1, "committee": 2, "shared_donor": 3}


def _strength(edge: dict) -> tuple:
    return (-float(edge["weight"]), _TYPE_ORDER.get(edge["type"], 9),
            edge["a"], edge["b"])


def neighborhoods(
    members: list[dict],
    edges: list[dict],
    as_of: str,
    edges_per_person: int = EDGES_PER_PERSON,
) -> dict[str, dict]:
    """Assemble one neighborhood document per member from the full edge list.
    `members` are node rows: {person_id, name, party, office_display,
    ideology_dim1}. Each member's document keeps its strongest `edges_per_person`
    edges (symmetric truncation — same formula for everyone), and its nodes are
    exactly the members those surviving edges touch, plus the center."""
    node_by_id = {m["person_id"]: m for m in members}
    incident: dict[str, list[dict]] = {m["person_id"]: [] for m in members}
    for e in edges:
        # An edge only enters a neighborhood if BOTH endpoints are current nodes
        # (a stale endpoint would be an edge with no renderable node).
        if e["a"] in node_by_id and e["b"] in node_by_id:
            incident[e["a"]].append(e)
            incident[e["b"]].append(e)
    out: dict[str, dict] = {}
    for center, es in incident.items():
        kept = sorted(es, key=_strength)[:edges_per_person]
        neighbor_ids = {center}
        for e in kept:
            neighbor_ids.add(e["a"])
            neighbor_ids.add(e["b"])
        nodes = [node_by_id[nid] for nid in sorted(neighbor_ids)]
        out[center] = {"center": center, "as_of": as_of, "nodes": nodes, "edges": kept}
    return out


def validate(doc: dict) -> None:
    """Fail-closed check mirroring the contract: every edge carries receipts, and
    every correlation edge (shared_donor) carries its caveat. An edge with no
    evidence is a bug — refuse to publish it (parallels dossiers.validate)."""
    node_ids = {n["person_id"] for n in doc["nodes"]}
    for e in doc["edges"]:
        if not e.get("evidence"):
            raise ValueError(f"edge {e.get('type')} {e.get('a')}~{e.get('b')} has no evidence")
        if not e.get("evidence_total"):
            raise ValueError(f"edge {e.get('type')} {e.get('a')}~{e.get('b')} has no evidence_total")
        if e["a"] not in node_ids or e["b"] not in node_ids:
            raise ValueError(f"edge endpoint not in nodes: {e.get('a')}~{e.get('b')}")
        if e["type"] == "shared_donor" and e.get("caveat") != SHARED_DONOR_CAVEAT:
            raise ValueError("shared_donor edge missing its verbatim caveat")


def publish(neighborhood_docs: dict[str, dict], out_dir: Path) -> int:
    """Write one document per member to graph/neighborhood/{person_id}.json,
    validating each first (no receipts, no publish)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for pid, doc in neighborhood_docs.items():
        validate(doc)
        (out_dir / f"{pid}.json").write_text(json.dumps(doc, separators=(",", ":")))
    return len(neighborhood_docs)
