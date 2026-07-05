"""Stage 1 — land raw snapshots (immutable) into dist/raw/{source}/.

Pulls the federal legislative slice: the unitedstates crosswalk (identity), the
congress.gov current membership (party/state/district/photo), and the Voteview
DW-NOMINATE table (ideology). Writes a manifest.json recording, per source, the
retrieved_at + source_url that transform/build stamp into provenance envelopes.

Raw is write-once per run: transform reads only from here, never the network, so
a published fact is always reproducible from the lake (contracts §7).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..config import CONGRESS, FEC_CYCLE, RAW_DIST
from ..sources import congress_gov, fec, house_clerk, legislators, openstates, voteview

LEGISLATORS_URL = legislators.URL
VOTEVIEW_URL = voteview.members_url(CONGRESS)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":")))


def run(raw_dir: str | Path = RAW_DIST) -> dict:
    raw = Path(raw_dir)
    manifest: dict = {"generated_at": _now(), "congress": CONGRESS, "sources": {}}

    # --- identity crosswalk (unitedstates/congress-legislators) ---
    legs = legislators.fetch_current()
    _write_json(raw / "unitedstates_legislators" / "legislators-current.json", legs)
    manifest["sources"]["unitedstates_legislators"] = {
        "retrieved_at": _now(), "source_url": LEGISLATORS_URL, "count": len(legs)}

    # --- committee roster + current memberships (WO-6a): same source family, so
    # they land under the unitedstates_legislators envelope. Landed as JSON so
    # transform reads only from raw (contracts §7). ---
    committees = legislators.fetch_committees()
    membership = legislators.fetch_committee_membership()
    _write_json(raw / "unitedstates_legislators" / "committees-current.json", committees)
    _write_json(raw / "unitedstates_legislators" / "committee-membership-current.json", membership)
    manifest["sources"]["unitedstates_legislators"]["committees"] = len(committees)
    manifest["sources"]["unitedstates_legislators"]["committee_memberships"] = sum(
        len(v or []) for v in membership.values())

    # --- current membership (congress.gov): party, state, district, photo ---
    client = congress_gov.CongressGovClient()
    members = list(client.current_members(CONGRESS))
    _write_json(raw / "congress.gov" / f"members-{CONGRESS}.json", members)

    # --- legislative activity per member (E2): sponsored bills walked in full
    # (exact became-law counts) + cosponsored total. The long pole of the run. ---
    leg_dir = raw / "congress.gov" / "legislation"
    bioguides = [m["bioguideId"] for m in members if m.get("bioguideId")]
    for i, bio in enumerate(bioguides, 1):
        _write_json(leg_dir / f"{bio}.json", {
            "bioguide": bio,
            "sponsored": client.sponsored_legislation(bio),
            "cosponsored_count": client.cosponsored_count(bio)})
        if i % 100 == 0 or i == len(bioguides):
            print(f"fetch: legislation {i}/{len(bioguides)} members")

    manifest["sources"]["congress.gov"] = {
        "retrieved_at": _now(),
        "source_url": f"https://www.congress.gov/members?q=%7B%22congress%22%3A{CONGRESS}%7D",
        "count": len(members), "legislation_members": len(bioguides)}

    # --- ideology (Voteview DW-NOMINATE) ---
    csv_text = voteview.member_scores_csv(CONGRESS)
    (raw / "voteview").mkdir(parents=True, exist_ok=True)
    # Explicit UTF-8: bionames carry accents; platform-default cp1252 would corrupt.
    (raw / "voteview" / f"HS{CONGRESS}_members.csv").write_text(csv_text, encoding="utf-8")
    manifest["sources"]["voteview"] = {
        "retrieved_at": _now(), "source_url": VOTEVIEW_URL,
        "count": max(csv_text.count("\n") - 1, 0)}

    # --- roll-call votes (WO-1): rollcalls (metadata) + votes (per-member casts).
    # Same Voteview source envelope; landed alongside the members table so the
    # transform reads only from raw (contracts §7). votes is the ~9 MB long pole.
    rollcalls_text = voteview.rollcalls_csv(CONGRESS)
    (raw / "voteview" / f"HS{CONGRESS}_rollcalls.csv").write_text(rollcalls_text, encoding="utf-8")
    votes_text = voteview.votes_csv(CONGRESS)
    (raw / "voteview" / f"HS{CONGRESS}_votes.csv").write_text(votes_text, encoding="utf-8")
    manifest["sources"]["voteview"]["rollcalls"] = max(rollcalls_text.count("\n") - 1, 0)
    manifest["sources"]["voteview"]["votes"] = max(votes_text.count("\n") - 1, 0)

    # --- campaign finance (FEC, E3 + WO-3): candidate cycle totals + itemized
    # contributor rollups. Keyed via the crosswalk's fec candidate ids; per
    # candidate, one totals lookup (E3) then a principal-committee resolve +
    # by_employer rollup (WO-3). Contributors land per candidate so transform
    # reads only from raw (contracts §7); a member without a committee simply
    # gets no contributors file (absent != zero). ---
    fec_client = fec.FECClient()
    fec_dir = raw / "fec" / "totals"
    contrib_dir = raw / "fec" / "contributors"
    seen_cand: set[str] = set()
    for leg in legs:
        fec_ids = (leg.get("id") or {}).get("fec") or []
        cand = fec_ids[0] if fec_ids else None
        if not cand or cand in seen_cand:
            continue
        seen_cand.add(cand)
        totals = fec_client.candidate_totals(cand, FEC_CYCLE)
        if totals:
            _write_json(fec_dir / f"{cand}.json",
                        {"candidate_id": cand, "cycle": FEC_CYCLE, "totals": totals})
        committee_id = fec_client.principal_committee(cand, FEC_CYCLE)
        if committee_id:
            by_employer = fec_client.top_contributors_by_employer(committee_id, FEC_CYCLE)
            _write_json(contrib_dir / f"{cand}.json",
                        {"candidate_id": cand, "cycle": FEC_CYCLE,
                         "committee_id": committee_id, "by_employer": by_employer})
    fec_count = len(list(fec_dir.glob("*.json"))) if fec_dir.exists() else 0
    contrib_count = len(list(contrib_dir.glob("*.json"))) if contrib_dir.exists() else 0
    manifest["sources"]["fec"] = {
        "retrieved_at": _now(),
        "source_url": f"https://www.fec.gov/data/candidates/?cycle={FEC_CYCLE}",
        "count": fec_count, "contributors": contrib_count}

    # --- state legislators (OpenStates, E4): current people, bulk CSV per state ---
    os_dir = raw / "openstates" / "people"
    os_count = 0
    for state in openstates.STATE_SLUGS:
        try:
            csv_text = openstates.fetch_people_csv(state)
        except Exception as e:  # a single state hiccup shouldn't sink the run
            print(f"fetch: openstates {state} skipped ({type(e).__name__})")
            continue
        (os_dir).mkdir(parents=True, exist_ok=True)
        (os_dir / f"{state}.csv").write_text(csv_text, encoding="utf-8")
        os_count += max(csv_text.count("\n") - 1, 0)
    manifest["sources"]["openstates"] = {
        "retrieved_at": _now(), "source_url": "https://openstates.org/", "count": os_count}

    # --- STOCK Act disclosures (House Clerk Periodic Transaction Reports) ---
    hc_filings: list[dict] = []
    for yr in (2024, 2025, 2026):   # the current term, plus late-prior-year trades
        try:
            hc_filings.extend(house_clerk.ptr_filings(yr))
        except Exception as e:
            print(f"fetch: house_clerk {yr} skipped ({type(e).__name__})")
    _write_json(raw / "house_clerk" / "ptr.json", hc_filings)
    manifest["sources"]["house_clerk"] = {
        "retrieved_at": _now(), "source_url": house_clerk.DISCLOSURE_URL, "count": len(hc_filings)}

    _write_json(raw / "manifest.json", manifest)
    for src, meta in manifest["sources"].items():
        print(f"fetch: {src:28} {meta['count']:>5} records")
    return manifest


if __name__ == "__main__":
    run()
