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

from ..config import CONGRESS, RAW_DIST, SPINE_RESOLUTION_MIN, WA_PDC_ENABLED
from ..sources import congress_gov
from ..sources import fec
from ..sources import legislators as L
from ..sources import openstates
from ..sources import voteview
from ..sources import wa_pdc                                     # WO-9 (trusted extraction)
from ..bulk import reconcile as bulk_reconcile                  # WO-9 (fail-closed gates)
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


# ==== WO-9: WA PDC trusted-extraction ingest (self-contained) ================
# Parse -> value-domain quarantine -> fail-closed reconciliation -> insert. The
# whole path is copy-only (no model). All three run-ending gates live here:
# schema-drift (observed header vs pinned contract), control-total (Σ itemized ==
# summary contributions_amount per filer/year), and the no-silent-drop invariant
# (input == inserted + quarantined). A value-domain miss quarantines one row with a
# reason; it does not end the run, but is still accounted for by the invariant.
def ingest_wa_pdc(con, itemized_records, summary_records, observed_header,
                  file_sha256, retrieved_at) -> dict:
    """Ingest one WA PDC snapshot into disclosure_contributions/_quarantine under
    the fail-closed gates. Returns {input, inserted, quarantined}. Raises a
    bulk_reconcile.GateError (schema-drift / control-total / no-silent-drop) rather
    than publish anything unreconciled."""
    # Gate 1 — schema-drift: header must match the pinned contract exactly.
    bulk_reconcile.schema_drift_gate(wa_pdc.CONTRACT, observed_header)

    # Copy-only parse: every input row -> a contribution OR a quarantine (with reason).
    contributions, quarantined = [], []
    for rec in itemized_records:
        row, q = wa_pdc.map_row(rec, file_sha256=file_sha256, retrieved_at=retrieved_at)
        if row is not None:
            contributions.append(row)
        else:
            quarantined.append(q)

    # Gate 2 — control-total: Σ(inserted amount_cents) per (filer_id, election_year)
    # must equal the summary feed's contributions_amount for that group (epsilon 0).
    sums: dict = {}
    for row in contributions:
        key = wa_pdc.itemized_group_key(row)
        sums[key] = sums.get(key, 0) + row["amount_cents"]
    controls = wa_pdc.control_totals_cents(summary_records)
    bulk_reconcile.control_total_gate(
        sums, controls, wa_pdc.CONTRACT.control_total.epsilon_cents, wa_pdc.CONTRACT.source_id)

    # Gate 3 — no-silent-drop: input == inserted + quarantined, before we persist.
    bulk_reconcile.no_silent_drop_gate(
        len(itemized_records), len(contributions), len(quarantined), wa_pdc.CONTRACT.source_id)

    store.insert(con, "disclosure_contributions", contributions)
    store.insert(con, "disclosure_quarantine", quarantined)
    return {"input": len(itemized_records),
            "inserted": len(contributions), "quarantined": len(quarantined)}


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

    # --- WO-15: PAST terms -> the same `terms` table, end_date populated ---
    # identity.previous_roles reads this table directly (WHERE end_date IS NOT
    # NULL). Every term but the last (the current one, already inserted above)
    # is a past term; mapped through the SAME _office_and_division helper so a
    # since-redistricted seat or a since-vacated office still resolves to a
    # real division/office row. A term with no state (never a federal House/
    # Senate seat, e.g. a stray non-voting-delegate quirk) is skipped — never
    # invented. Deduped on the terms PK (person_id, office_id, start) so a
    # redundant/malformed re-election entry can't double-insert.
    past_terms: list[dict] = []
    for leg in legs:
        bio = (leg.get("id") or {}).get("bioguide")
        all_terms = leg.get("terms") or []
        if not bio or len(all_terms) < 2:
            continue
        pid = L.person_uuid(bio)
        for term in all_terms[:-1]:                       # every term except the current one
            mapped = _office_and_division(term)
            if not mapped:
                continue
            division, parent, office, _seat = mapped
            divisions.setdefault(division["ocd_id"], division)
            if parent:
                divisions.setdefault(parent["ocd_id"], parent)
            offices.setdefault(office["office_id"], office)
            start = term.get("start") or _CONGRESS_START
            end = term.get("end")
            if not end:
                continue                                   # an open-ended "past" term is honest-unknown, not published
            past_terms.append({
                "term_id": _term_id(pid, office["office_id"], start),
                "person_id": pid, "office_id": office["office_id"],
                "party": L.party_code(term.get("party")),
                "start_date": start, "end_date": end, "is_vacant_marker": False,
                "meta": None,
            })

    store.insert(con, "divisions", list(divisions.values()))
    store.insert(con, "offices", list(offices.values()))
    store.insert(con, "terms", terms)
    if past_terms:
        seen_term_ids = {t["term_id"] for t in terms}
        uniq_past, seen_past = [], set()
        for t in past_terms:
            if t["term_id"] in seen_term_ids or t["term_id"] in seen_past:
                continue                                    # PK dedupe (current term wins if start collides)
            seen_past.add(t["term_id"])
            uniq_past.append(t)
        store.insert(con, "terms", uniq_past)

    # --- ICPSR crosswalk: congress-legislators id.icpsr, AUGMENTED from Voteview ---
    # The congress-legislators YAML lags on ICPSR for freshmen (~217 of 537 members
    # lacked id.icpsr for the 119th), which would leave their votes + ideology dark.
    # Voteview IS the ICPSR authority and its members file carries bioguide_id for
    # every member, so fill the crosswalk by joining Voteview's icpsr<->bioguide
    # through our complete bioguide crosswalk. No fabrication — Voteview asserts the
    # pairing; the filled ids are persisted so the warehouse crosswalk is complete.
    bioguide_to_person = {r["id_value"]: r["person_id"]
                          for r in uniq_idents if r["id_scheme"] == "bioguide"}
    icpsr_to_person = {r["id_value"]: r["person_id"] for r in uniq_idents if r["id_scheme"] == "icpsr"}
    csv_path = raw / "voteview" / f"HS{CONGRESS}_members.csv"
    csv_text = csv_path.read_text(encoding="utf-8") if csv_path.exists() else ""   # matches fetch's write
    if csv_text:
        derived = [{"person_id": bioguide_to_person[bio], "id_scheme": "icpsr", "id_value": icpsr}
                   for icpsr, bio in voteview.member_icpsr_to_bioguide(csv_text).items()
                   if bio in bioguide_to_person and icpsr not in icpsr_to_person]
        for r in derived:
            icpsr_to_person[r["id_value"]] = r["person_id"]
        if derived:
            store.insert(con, "person_identifiers", derived)   # deduped on (scheme, value) PK

    # --- ideology: Voteview scores through the (now complete) ICPSR crosswalk ---
    if csv_text:
        # The fetch manifest's retrieved_at is the honest computed_as_of for a
        # continuously re-estimated score (see voteview.to_score_rows docstring).
        manifest_path = raw / "manifest.json"
        as_of = None
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            as_of = manifest.get("sources", {}).get("voteview", {}).get("retrieved_at")
        scores, seen_pk = [], set()
        for row in voteview.to_score_rows(csv_text, CONGRESS, icpsr_to_person,
                                          as_of=as_of):
            pk = (row["person_id"], row["scheme"], row["scope"])
            if pk not in seen_pk:
                seen_pk.add(pk)
                scores.append(row)
        store.insert(con, "ideology_scores", scores)

    # --- legislative: sponsored bills -> bills + sponsorships spine (E2) ---
    # Only sponsored rows land in the spine (walked in full); the cosponsored
    # total stays a per-member count in raw, read at build time. (bioguide_to_person
    # was built above for the ICPSR-crosswalk augmentation.)
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

    # --- committees (WO-6a) -> committees + committee_memberships ---
    # Roster first (parents before subcommittees so the self-referential
    # parent_id FK holds — the DuckDB shim drops that FK, but transform ordering
    # upholds integrity by construction), then memberships gated on both the
    # committee (FK) and the crosswalk person. bioguide_to_person is the same map
    # the sponsorships block built above.
    committees_f = raw / "unitedstates_legislators" / "committees-current.json"
    membership_f = raw / "unitedstates_legislators" / "committee-membership-current.json"
    if committees_f.exists() and membership_f.exists():
        roster = json.loads(committees_f.read_text(encoding="utf-8"))
        membership = json.loads(membership_f.read_text(encoding="utf-8"))
        committee_list, seen_cid = [], set()
        for row in L.committee_rows(roster):
            cid = row["committee_id"]
            if cid not in seen_cid:               # dedupe on the committee_id PK
                seen_cid.add(cid)
                committee_list.append(row)
        store.insert(con, "committees", committee_list)
        cm_rows, seen_cm = [], set()
        for row in L.membership_rows(membership, CONGRESS, seen_cid, bioguide_to_person):
            pk = (row["committee_id"], row["person_id"], row["congress"])
            if pk not in seen_cm:                 # dedupe on the composite PK
                seen_cm.add(pk)
                cm_rows.append(row)
        store.insert(con, "committee_memberships", cm_rows)

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
                    # WO-15: contact/social ride in meta (like image/source_url
                    # above) since they're per-term CSV columns, not a separate
                    # source — build.py reads them back out for identity.contact
                    # / identity.social. Empty dicts collapse to absent keys
                    # there, never a fabricated empty object.
                    "meta": {"image": r["image"], "source_url": r["source_url"],
                             "contact": r["contact"] or None, "social": r["social"] or None}})
        store.insert(con, "persons", os_persons)
        store.insert(con, "person_identifiers", os_idents)
        store.insert(con, "divisions", list(os_divs.values()))
        store.insert(con, "offices", list(os_offices.values()))
        store.insert(con, "terms", os_terms)

    # --- WO-9: WA PDC bulk disclosure (trusted extraction, fail-closed gates) ---
    # Reads the landed snapshot only (never the network); ingest_wa_pdc runs the
    # schema-drift, control-total, and no-silent-drop gates and raises rather than
    # publish anything unreconciled. Not surfaced in dossiers (explicit follow-on).
    wa_dir = raw / "wa_pdc"
    if WA_PDC_ENABLED and (wa_dir / "itemized.json").exists() and (wa_dir / "manifest.json").exists():
        wa_meta = json.loads((wa_dir / "manifest.json").read_text(encoding="utf-8"))
        itemized = json.loads((wa_dir / "itemized.json").read_text(encoding="utf-8"))
        summary = json.loads((wa_dir / "summary.json").read_text(encoding="utf-8"))
        ingest_wa_pdc(con, itemized, summary, wa_meta["header"],
                      wa_meta["file_sha256"], wa_meta["retrieved_at"])

    counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("persons", "divisions", "offices", "terms",
                        "ideology_scores", "bills", "sponsorships",
                        "roll_calls", "vote_positions",
                        "committees", "committee_memberships",
                        "campaign_finance_cycles", "top_contributors")}
    print("transform:", " ".join(f"{k}={v}" for k, v in counts.items()),
          f"(resolution {rate:.4f})")
    con.close()
    return db_path


if __name__ == "__main__":
    run()
