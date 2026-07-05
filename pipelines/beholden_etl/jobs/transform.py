"""Stage 2 — raw snapshots -> DuckDB spine, with fail-closed quality gates.

Builds identity (persons + crosswalk), geography (divisions), office-holding
(offices + terms) from the unitedstates crosswalk, and ideology from Voteview
(joined through ICPSR). Two gates FAIL the whole run rather than publish partial:
  1. crosswalk resolution  (in legislators.to_spine_rows)  >= SPINE_RESOLUTION_MIN
  2. current-term resolution (members that got an office/term) >= SPINE_RESOLUTION_MIN

Output: a DuckDB file the build stage queries. Nothing here touches the network.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from ..config import CONGRESS, RAW_DIST, SPINE_RESOLUTION_MIN
from ..sources import congress_gov
from ..sources import fec
from ..sources import legislators as L
from ..sources import openstates
from ..sources import voteview
from .. import divisions as D
from .. import store

DEFAULT_DB = "dist/warehouse.duckdb"
# Convening date of the configured congress (the 119th convened 2025-01-03);
# used when a term omits a start date. Derived so a CONGRESS bump can't drift.
_CONGRESS_START = f"{2025 + (CONGRESS - 119) * 2}-01-03"


def _office_id(ocd_id: str, seat: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"office:{ocd_id}:{seat}"))


def _term_id(person_id: str, office_id: str, start: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"term:{person_id}:{office_id}:{start}"))


def _office_and_division(term: dict):
    """(division_row, parent_division_row|None, office_row, seat_key) for a term,
    or None if it isn't a federal House/Senate seat we map to geography."""
    usps = term.get("state")
    if not usps:
        return None
    ttype = term.get("type")
    if ttype == "rep":
        ocd, at_large = D.house_ocd(usps, term.get("district"))
        num = 1 if at_large else (int(term["district"]) if str(term.get("district")).isdigit() else 1)
        division = {"ocd_id": ocd, "parent_ocd": D.state_ocd(usps), "level": "cd",
                    "name": f"{usps}-{'AL' if at_large else num}", "geoid": None,
                    "valid_from": term.get("start") or _CONGRESS_START}
        parent = {"ocd_id": D.state_ocd(usps), "parent_ocd": None, "level": "state",
                  "name": usps, "geoid": None, "valid_from": term.get("start") or _CONGRESS_START}
        office = {"office_id": _office_id(ocd, "representative"), "ocd_id": ocd,
                  "branch": "legislative", "chamber": "house", "role": "representative"}
        return division, parent, office, "representative"
    if ttype == "sen":
        ocd = D.state_ocd(usps)
        seat = f"senator-class{term.get('class', '?')}"     # 2 seats/state need distinct offices
        division = {"ocd_id": ocd, "parent_ocd": None, "level": "state",
                    "name": usps, "geoid": None, "valid_from": term.get("start") or _CONGRESS_START}
        office = {"office_id": _office_id(ocd, seat), "ocd_id": ocd,
                  "branch": "legislative", "chamber": "senate", "role": "senator"}
        return division, None, office, seat
    return None


def run(raw_dir: str | Path = RAW_DIST, db_path: str = DEFAULT_DB) -> str:
    raw = Path(raw_dir)
    legs = json.loads((raw / "unitedstates_legislators" / "legislators-current.json").read_text())

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    if Path(db_path).exists():
        Path(db_path).unlink()                         # rebuild clean each run
    con = store.connect(db_path)
    store.init_schema(con)

    # --- identity: persons + crosswalk (gate 1 raises inside to_spine_rows) ---
    persons, idents, quarantine = [], [], []
    for person, id_rows, q in L.to_spine_rows(legs):
        if person:
            persons.append(person)
            idents.extend(id_rows)
        if q:
            quarantine.append({"raw_payload": q["raw_payload"], "source": q["source"]})
    store.insert(con, "persons", persons)
    # dedupe identifiers on (id_scheme, id_value) PK before insert
    seen, uniq_idents = set(), []
    for r in idents:
        k = (r["id_scheme"], r["id_value"])
        if k not in seen:
            seen.add(k)
            uniq_idents.append(r)
    store.insert(con, "person_identifiers", uniq_idents)
    store.insert(con, "quarantine_identities", quarantine)

    # --- geography + office-holding from each legislator's current term ---
    divisions: dict[str, dict] = {}
    offices: dict[str, dict] = {}
    terms: list[dict] = []
    matched = 0
    for leg in legs:
        bio = (leg.get("id") or {}).get("bioguide")
        term = L.current_term(leg)
        if not bio or not term:
            continue
        mapped = _office_and_division(term)
        if not mapped:
            continue
        division, parent, office, seat = mapped
        divisions.setdefault(division["ocd_id"], division)
        if parent:
            divisions.setdefault(parent["ocd_id"], parent)
        offices.setdefault(office["office_id"], office)
        pid = L.person_uuid(bio)
        start = term.get("start") or _CONGRESS_START
        terms.append({
            "term_id": _term_id(pid, office["office_id"], start),
            "person_id": pid, "office_id": office["office_id"],
            "party": L.party_code(term.get("party")),
            "start_date": start, "end_date": None, "is_vacant_marker": False,
            "meta": {"term_ends": term.get("end"),
                     "first_took_office": L.first_took_office(leg),
                     "seat": seat},
        })
        matched += 1

    # gate 2: (nearly) every legislator must resolve to a division/office/term
    rate = matched / max(len(legs), 1)
    if rate < SPINE_RESOLUTION_MIN:
        raise RuntimeError(f"current-term resolution {rate:.4f} < {SPINE_RESOLUTION_MIN}")

    store.insert(con, "divisions", list(divisions.values()))
    store.insert(con, "offices", list(offices.values()))
    store.insert(con, "terms", terms)

    # --- ideology: Voteview joined through the ICPSR crosswalk ---
    icpsr_to_person = {r["id_value"]: r["person_id"] for r in uniq_idents if r["id_scheme"] == "icpsr"}
    csv_path = raw / "voteview" / f"HS{CONGRESS}_members.csv"
    if csv_path.exists():
        # The fetch manifest's retrieved_at is the honest computed_as_of for a
        # continuously re-estimated score (see voteview.to_score_rows docstring).
        manifest_path = raw / "manifest.json"
        as_of = None
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            as_of = manifest.get("sources", {}).get("voteview", {}).get("retrieved_at")
        scores, seen_pk = [], set()
        csv_text = csv_path.read_text(encoding="utf-8")   # matches fetch's write
        for row in voteview.to_score_rows(csv_text, CONGRESS, icpsr_to_person,
                                          as_of=as_of):
            pk = (row["person_id"], row["scheme"], row["scope"])
            if pk not in seen_pk:
                seen_pk.add(pk)
                scores.append(row)
        store.insert(con, "ideology_scores", scores)

    # --- legislative: sponsored bills -> bills + sponsorships spine (E2) ---
    # Only sponsored rows land in the spine (walked in full); the cosponsored
    # total stays a per-member count in raw, read at build time.
    bioguide_to_person = {r["id_value"]: r["person_id"]
                          for r in uniq_idents if r["id_scheme"] == "bioguide"}
    leg_dir = raw / "congress.gov" / "legislation"
    if leg_dir.exists():
        bills: dict[str, dict] = {}
        sponsorships, seen_sp = [], set()
        for f in sorted(leg_dir.glob("*.json")):
            rec = json.loads(f.read_text(encoding="utf-8"))
            pid = bioguide_to_person.get(rec.get("bioguide"))
            if not pid:
                continue                              # member not in the crosswalk spine
            for item in rec.get("sponsored", []):
                if not (item.get("type") and item.get("number") and item.get("congress")):
                    continue                          # can't form a stable bill_id
                row = congress_gov.bill_row(item)
                bid = row["bill_id"]
                bills.setdefault(bid, row)
                pk = (bid, pid)
                if pk not in seen_sp:
                    seen_sp.add(pk)
                    sponsorships.append({"bill_id": bid, "person_id": pid, "role": "sponsor",
                                         "is_original": True,
                                         "sponsored_on": item.get("introducedDate") or None})
        store.insert(con, "bills", list(bills.values()))
        store.insert(con, "sponsorships", sponsorships)

    # --- roll-call votes (WO-1) -> roll_calls + vote_positions ---
    # rollcalls first (roll_calls rows + the valid-id set that gates positions on
    # the FK), then the ~500k votes table, streamed and chunk-inserted. bill_id
    # links only to a bills row that already exists (procedural votes stay NULL).
    rollcalls_csv = raw / "voteview" / f"HS{CONGRESS}_rollcalls.csv"
    votes_csv = raw / "voteview" / f"HS{CONGRESS}_votes.csv"
    if rollcalls_csv.exists() and votes_csv.exists():
        known_bill_ids = {r[0] for r in con.execute("SELECT bill_id FROM bills").fetchall()}
        rc_text = rollcalls_csv.read_text(encoding="utf-8")
        roll_calls, seen_rc = [], set()
        for row in voteview.to_roll_call_rows(rc_text, CONGRESS, known_bill_ids):
            rcid = row["roll_call_id"]
            if rcid not in seen_rc:               # dedupe on PK before insert
                seen_rc.add(rcid)
                roll_calls.append(row)
        store.insert(con, "roll_calls", roll_calls)

        # Positions: only for roll calls we actually ingested (FK integrity) and
        # ICPSRs in the crosswalk. Chunk-insert to keep memory + the transaction
        # bounded across ~500k rows.
        votes_text = votes_csv.read_text(encoding="utf-8")
        chunk, seen_vp = [], set()
        for row in voteview.to_position_rows(votes_text, CONGRESS, icpsr_to_person, seen_rc):
            pk = (row["roll_call_id"], row["person_id"])
            if pk in seen_vp:
                continue                          # dedupe on (roll_call_id, person_id) PK
            seen_vp.add(pk)
            chunk.append(row)
            if len(chunk) >= 10000:
                store.insert(con, "vote_positions", chunk)
                chunk = []
        store.insert(con, "vote_positions", chunk)

    # --- campaign finance: FEC totals -> campaign_finance_cycles (E3) ---
    fec_to_person = {r["id_value"]: r["person_id"]
                     for r in uniq_idents if r["id_scheme"] == "fec"}
    fec_dir = raw / "fec" / "totals"
    if fec_dir.exists():
        # Fall back to the fetch date when FEC omits coverage_end_date (as_of NOT NULL).
        manifest_path = raw / "manifest.json"
        fec_as_of = None
        if manifest_path.exists():
            meta = json.loads(manifest_path.read_text()).get("sources", {}).get("fec", {})
            fec_as_of = (meta.get("retrieved_at") or "")[:10] or None
        cf_rows, seen_cf = [], set()
        for f in sorted(fec_dir.glob("*.json")):
            rec = json.loads(f.read_text(encoding="utf-8"))
            cand = rec.get("candidate_id")
            pid = fec_to_person.get(cand)
            if not pid:
                continue
            row = fec.cycle_row(pid, cand, rec["cycle"], rec["totals"], fec_as_of)
            pk = (pid, rec["cycle"], cand)
            if row and pk not in seen_cf:
                seen_cf.add(pk)
                cf_rows.append(row)
        store.insert(con, "campaign_finance_cycles", cf_rows)

    # --- top contributors: FEC by_employer rollups -> top_contributors (WO-3) ---
    # One row per employer rollup, ranked 1..25 by the order FEC returns (-total).
    # Same fec source envelope as the totals above. A candidate without a
    # committee has no contributors file -> no rows (absent != zero).
    contrib_dir = raw / "fec" / "contributors"
    if contrib_dir.exists():
        tc_rows, seen_tc = [], set()
        for f in sorted(contrib_dir.glob("*.json")):
            rec = json.loads(f.read_text(encoding="utf-8"))
            pid = fec_to_person.get(rec.get("candidate_id"))
            if not pid:
                continue
            for row in fec.contributor_rows(pid, rec["cycle"], rec.get("by_employer") or []):
                pk = (pid, row["cycle"], row["rank"])   # dedupe on the (person,cycle,rank) PK
                if pk not in seen_tc:
                    seen_tc.add(pk)
                    tc_rows.append(row)
        store.insert(con, "top_contributors", tc_rows)

    # --- state legislators (OpenStates, E4) -> spine (sldu/sldl) ---
    os_dir = raw / "openstates" / "people"
    if os_dir.exists():
        # Most state legislatures convened early 2025; used as the term start
        # (individual first-took-office isn't in the bulk feed, so dossiers omit it).
        session_start = f"{2025 + (CONGRESS - 119) * 2}-01-01"
        os_persons, os_idents, os_divs, os_offices, os_terms = [], [], {}, {}, []
        seen_person: set[str] = set()
        for f in sorted(os_dir.glob("*.csv")):
            state = f.stem  # lowercase usps
            for r in openstates.to_person_rows(f.read_text(encoding="utf-8")):
                mapped = D.sld_ocd(state, r["chamber"], r["district"])
                if not mapped:
                    continue
                ocd, level = mapped
                pid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"openstates:{r['ocd_person']}"))
                if pid not in seen_person:
                    seen_person.add(pid)
                    os_persons.append({
                        "person_id": pid, "full_name": r["name"],
                        "given_name": r["given"], "family_name": r["family"],
                        "birth_year": int(r["birth_date"][:4]) if r.get("birth_date") else None})
                    os_idents.append({"person_id": pid, "id_scheme": "openstates",
                                      "id_value": r["ocd_person"]})
                os_divs.setdefault(ocd, {
                    "ocd_id": ocd, "parent_ocd": D.state_ocd(state), "level": level,
                    "name": f"{state.upper()} {level}:{r['district']}", "geoid": None,
                    "valid_from": session_start})
                role = "state_senator" if r["chamber"] == "upper" else "state_representative"
                office_id = _office_id(ocd, role)
                os_offices.setdefault(office_id, {
                    "office_id": office_id, "ocd_id": ocd, "branch": "legislative",
                    "chamber": r["chamber"], "role": role})
                os_terms.append({
                    "term_id": _term_id(pid, office_id, session_start),
                    "person_id": pid, "office_id": office_id, "party": L.party_code(r["party"]),
                    "start_date": session_start, "end_date": None, "is_vacant_marker": False,
                    "meta": {"image": r["image"], "source_url": r["source_url"]}})
        store.insert(con, "persons", os_persons)
        store.insert(con, "person_identifiers", os_idents)
        store.insert(con, "divisions", list(os_divs.values()))
        store.insert(con, "offices", list(os_offices.values()))
        store.insert(con, "terms", os_terms)

    counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("persons", "divisions", "offices", "terms",
                        "ideology_scores", "bills", "sponsorships",
                        "roll_calls", "vote_positions",
                        "campaign_finance_cycles", "top_contributors")}
    print("transform:", " ".join(f"{k}={v}" for k, v in counts.items()),
          f"(resolution {rate:.4f})")
    con.close()
    return db_path


if __name__ == "__main__":
    run()
