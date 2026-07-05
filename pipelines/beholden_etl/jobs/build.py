"""Stage 3 — DuckDB spine -> serving artifacts in dist/data (contracts §3/§5).

Emits, for the current federal legislature:
  stylefeeds/cd.json      ocd_id -> {party, ideology_dim1, vacant}   (colors the CD layer)
  pins/{cd,states}.json   ocd_id -> office-holder (dossier discovery on tap)
  dossiers/{person_id}.json   identity + ideology + legislative, each provenanced
  coverage.json           per-source freshness vs SLA + artifact counts

Enforces the serving rule via dossiers.validate(): no provenance, no publish.
The legislative section carries real sponsored/cosponsored/became-law counts,
recent bills (E2), key votes (WO-1), and committee memberships (WO-6a).
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from ..config import CONGRESS, PAGES_DIST, SOURCES, pipeline_version
from ..build import dossiers, key_votes, stylefeeds
from ..sources import congress_gov, house_clerk, voteview
from .transform import DEFAULT_DB
from .. import store

PARTY_DISPLAY = {"D": "Democratic", "R": "Republican", "I": "Independent",
                 "L": "Libertarian", "G": "Green", "NP": "Nonpartisan"}
IDEOLOGY_SCOPE = f"{CONGRESS}th Congress"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_manifest(raw_dir: Path) -> dict:
    f = raw_dir / "manifest.json"
    return json.loads(f.read_text()) if f.exists() else {"sources": {}}


def _photo_map(raw_dir: Path) -> dict[str, str]:
    """bioguide -> headshot URL from the congress.gov snapshot (optional)."""
    f = raw_dir / "congress.gov" / f"members-{CONGRESS}.json"
    if not f.exists():
        return {}
    out = {}
    for m in json.loads(f.read_text()):
        bio = m.get("bioguideId") or m.get("bioguide")
        url = (m.get("depiction") or {}).get("imageUrl")
        if bio and url:
            out[bio] = url
    return out


def _provenance(source: str, source_url: str, manifest: dict) -> dict:
    """Provenance envelope for a section. FAILS CLOSED (rule #1): if the fetch
    manifest can't vouch for when `source` was retrieved, we refuse to invent a
    timestamp — a fabricated retrieved_at is worse than no publish."""
    meta = manifest.get("sources", {}).get(source, {})
    retrieved_at = meta.get("retrieved_at")
    if not retrieved_at:
        raise dossiers.ProvenanceError(
            f"manifest has no retrieved_at for source '{source}' — refusing to "
            "fabricate freshness (no provenance, no publish)")
    return {"source": source, "source_url": source_url,
            "retrieved_at": retrieved_at,
            "pipeline_version": pipeline_version(), "methodology_id": None}


def _office_display(chamber: str, ocd_id: str) -> str:
    tail = ocd_id.split("/")[-1]
    state = ocd_id.split("state:")[1].split("/")[0].upper() if "state:" in ocd_id else "?"
    seat = tail.split(":")[1] if ":" in tail else tail
    if chamber == "house":
        return f"U.S. House · {state}-{seat}"
    if chamber == "senate":
        return f"U.S. Senate · {state}"
    if chamber == "upper":
        return f"{state} State Senate · District {seat}"
    if chamber == "lower":
        return f"{state} State House · District {seat}"
    return f"{state} · {seat}"


# Federal chambers carry ideology + a legislative record; state chambers (E4)
# ship identity only for now, sourced from OpenStates.
FEDERAL_CHAMBERS = {"house", "senate"}


def _current_holders(con) -> list[dict]:
    cur = con.execute(
        """
        SELECT p.person_id, p.full_name, p.given_name, p.family_name,
               o.role, o.chamber, d.ocd_id,
               t.party, t.is_vacant_marker,
               t.meta->>'term_ends'        AS term_ends,
               t.meta->>'first_took_office' AS first_took_office,
               t.meta->>'image'            AS image_url,
               t.meta->>'source_url'       AS source_url,
               i.score  AS ideology_score,
               i.status AS ideology_status,
               (SELECT id_value FROM person_identifiers pi
                 WHERE pi.person_id = p.person_id AND pi.id_scheme='bioguide') AS bioguide
        FROM terms t
        JOIN persons p USING(person_id)
        JOIN offices o USING(office_id)
        JOIN divisions d ON d.ocd_id = o.ocd_id
        LEFT JOIN ideology_scores i
               ON i.person_id = p.person_id AND i.scheme='dw_nominate_dim1' AND i.scope = ?
        WHERE t.end_date IS NULL
        """, [str(CONGRESS)])
    cols = [c[0] for c in cur.description]
    out = []
    for row in cur.fetchall():
        r = dict(zip(cols, row))
        r["person_id"] = str(r["person_id"])          # DuckDB UUID -> str for JSON
        if r["ideology_score"] is not None:
            r["ideology_score"] = float(r["ideology_score"])   # Decimal -> float
        out.append(r)
    return out


def _medians(holders: list[dict]) -> dict:
    """Party and chamber DW-NOMINATE medians for dossier context."""
    def med(vals):
        vals = [float(v) for v in vals if v is not None]
        return round(statistics.median(vals), 4) if vals else None
    by_party, by_chamber = {}, {}
    for h in holders:
        if h["ideology_score"] is None:
            continue
        by_party.setdefault(h["party"], []).append(h["ideology_score"])
        by_chamber.setdefault(h["chamber"], []).append(h["ideology_score"])
    return {"party": {k: med(v) for k, v in by_party.items()},
            "chamber": {k: med(v) for k, v in by_chamber.items()}}


def _legislative_stats(con) -> dict[str, dict]:
    """person_id -> {sponsored, became_law, recent_bills[]} from the bills spine."""
    stats: dict[str, dict] = {}
    for pid, sponsored, became_law in con.execute(
        """SELECT s.person_id, count(*) AS sponsored,
                  count(*) FILTER (WHERE b.status='law') AS became_law
           FROM sponsorships s JOIN bills b USING(bill_id)
           WHERE s.role='sponsor' GROUP BY s.person_id""").fetchall():
        stats[str(pid)] = {"sponsored": sponsored, "became_law": became_law, "recent_bills": []}
    for pid, bill_id_, title, status in con.execute(
        """SELECT s.person_id, b.bill_id, b.title, b.status
           FROM sponsorships s JOIN bills b USING(bill_id)
           WHERE s.role='sponsor'
           QUALIFY row_number() OVER (PARTITION BY s.person_id
                   ORDER BY b.latest_action_on DESC NULLS LAST, b.bill_id) <= 10""").fetchall():
        stats.setdefault(str(pid), {"sponsored": 0, "became_law": 0, "recent_bills": []})
        stats[str(pid)]["recent_bills"].append(
            {"bill_id": bill_id_, "title": title, "status": status,
             "url": congress_gov.bill_public_url(bill_id_)})
    return stats


def _vote_records(con) -> dict[str, list[dict]]:
    """person_id -> [{roll_call_id, position, question, held_at, result, bill_id,
    party}] of every roll call the member cast a position on. party comes from
    the member's current term so agreement can be scored against their party."""
    out: dict[str, list[dict]] = {}
    # held_at is cast to VARCHAR in SQL: materializing a TIMESTAMPTZ into Python
    # pulls in DuckDB's timezone path (needs pytz, not a declared dep). We only
    # want the date for ordering/display, so a string keeps the query dep-free.
    for pid, rcid, position, party, question, result, held_at, bill_id in con.execute(
        """SELECT vp.person_id, vp.roll_call_id, vp.position, t.party,
                  rc.question, rc.result, rc.held_at::VARCHAR AS held_at, rc.bill_id
           FROM vote_positions vp
           JOIN roll_calls rc USING(roll_call_id)
           JOIN terms t ON t.person_id = vp.person_id AND t.end_date IS NULL
        """).fetchall():
        out.setdefault(str(pid), []).append({
            "roll_call_id": rcid, "position": position, "party": party,
            "question": question, "result": result,
            "held_at": held_at, "bill_id": bill_id})
    return out


def _rollcall_meta(raw_dir: Path) -> dict[str, dict]:
    """roll_call_id -> {yea, nay, date, url} from the raw rollcalls CSV — the
    closeness inputs + official record link that don't live in the spine table."""
    f = raw_dir / "voteview" / f"HS{CONGRESS}_rollcalls.csv"
    if not f.exists():
        return {}
    return voteview.to_rollcall_meta(f.read_text(encoding="utf-8"), CONGRESS)


def _cosponsored_counts(raw_dir: Path) -> dict[str, int]:
    """bioguide -> cosponsored total, read from the landed legislation snapshots."""
    out: dict[str, int] = {}
    d = raw_dir / "congress.gov" / "legislation"
    if d.exists():
        for f in d.glob("*.json"):
            rec = json.loads(f.read_text(encoding="utf-8"))
            if rec.get("bioguide"):
                out[rec["bioguide"]] = int(rec.get("cosponsored_count") or 0)
    return out


def _campaign_finance(con) -> dict[str, dict]:
    """person_id -> {candidate_id, cycles[]} from campaign_finance_cycles (E3)."""
    out: dict[str, dict] = {}
    for pid, cycle, cand, raised, spent, cash, as_of in con.execute(
        """SELECT person_id, cycle, fec_committee_id,
                  total_raised_cents, total_spent_cents, cash_on_hand_cents, as_of
           FROM campaign_finance_cycles ORDER BY cycle DESC""").fetchall():
        entry = out.setdefault(str(pid), {"candidate_id": cand, "cycles": []})
        entry["cycles"].append({
            "cycle": cycle, "total_raised_cents": raised, "total_spent_cents": spent,
            "cash_on_hand_cents": cash, "as_of": str(as_of)})
    return out


def _committees(con) -> dict[str, list[dict]]:
    """person_id -> [{name, role, subcommittees:[{name, role}]}] from
    committee_memberships joined to committees (WO-6a). Top-level committees are
    the entries; subcommittees (parent_id set) nest under the parent the member
    also sits on. Roles come straight from the source-stated title (member|chair|
    ranking|vice_chair). Ordering is deterministic and party-agnostic (rule #3):
    committees alphabetical by name, subcommittees likewise — identical regardless
    of party or chamber majority."""
    rows = con.execute(
        """SELECT cm.person_id, c.committee_id, c.name, c.parent_id, cm.role
           FROM committee_memberships cm JOIN committees c USING(committee_id)
           WHERE cm.congress = ?
           ORDER BY c.name""", [CONGRESS]).fetchall()
    # Index each person's top-level committee entries so subcommittees can attach
    # (parent_id is NULL for a top-level committee).
    parents: dict[str, dict[str, dict]] = {}     # person -> committee_id -> entry
    subs: list[tuple] = []                        # (person, parent_id, name, role)
    for pid, cid, name, parent_id, role in rows:
        pid = str(pid)
        if parent_id is None:
            parents.setdefault(pid, {})[cid] = {"name": name, "role": role, "subcommittees": []}
        else:
            subs.append((pid, parent_id, name, role))
    for pid, parent_id, name, role in subs:
        parent = parents.get(pid, {}).get(parent_id)
        if parent is not None:                    # every real/fixture sub has its parent (0 orphans)
            parent["subcommittees"].append({"name": name, "role": role})
    out: dict[str, list[dict]] = {}
    for pid, by_cid in parents.items():
        entries = []
        for entry in sorted(by_cid.values(), key=lambda e: e["name"]):
            e = {"name": entry["name"], "role": entry["role"]}
            if entry["subcommittees"]:
                e["subcommittees"] = sorted(entry["subcommittees"], key=lambda s: s["name"])
            entries.append(e)
        out[pid] = entries
    return out


def _top_contributors(con) -> dict[str, list[dict]]:
    """person_id -> [{name, total_cents}] employer rollups of itemized
    individual contributions, from top_contributors (WO-3), most-recent cycle
    first and ordered by rank. Same FEC envelope as the cycle totals; the
    dossier caps the list at 10."""
    out: dict[str, list[dict]] = {}
    for pid, name, total in con.execute(
        """SELECT person_id, contributor_name, total_cents
           FROM top_contributors ORDER BY person_id, cycle DESC, rank""").fetchall():
        out.setdefault(str(pid), []).append({"name": name, "total_cents": total})
    return out


def _disclosures(raw_dir: Path, holders: list[dict]) -> dict[str, list[dict]]:
    """person_id -> [{filed_on, filing_url}] of House PTR filings, matched by
    (family name, first given name). House-source, so House members only."""
    f = raw_dir / "house_clerk" / "ptr.json"
    if not f.exists():
        return {}

    def key(last: str, first: str):
        return (last.strip().lower(), (first.strip().split() or [""])[0].lower())

    name_map: dict[tuple, str] = {}
    for h in holders:
        if h["chamber"] == "house":
            name_map.setdefault(key(h.get("family_name") or "", h.get("given_name") or ""),
                                h["person_id"])
    out: dict[str, list[dict]] = {}
    for fil in json.loads(f.read_text(encoding="utf-8")):
        pid = name_map.get(key(fil.get("last", ""), fil.get("first", "")))
        if not pid or not fil.get("doc_id"):
            continue
        out.setdefault(pid, []).append({
            "filed_on": fil.get("filed_on"),
            "filing_url": house_clerk.ptr_pdf_url(fil["year"], fil["doc_id"])})
    for pid in out:
        out[pid].sort(key=lambda x: x["filed_on"] or "", reverse=True)
    return out


def _dossier(h: dict, photo: dict, manifest: dict, medians: dict,
             leg_spine: dict, cospon: dict, campaign: dict, contributors: dict,
             disclosures: dict, vote_records: dict, rc_meta: dict,
             party_majority: dict, committees: dict) -> dict:
    bio = h.get("bioguide")
    federal = h["chamber"] in FEDERAL_CHAMBERS
    vacant = bool(h["is_vacant_marker"])
    photo_url = h.get("image_url") or photo.get(bio)   # OpenStates image or congress.gov headshot

    if federal:
        identity_prov = _provenance(
            "unitedstates_legislators",
            f"https://bioguide.congress.gov/search/bio/{bio}" if bio else SOURCES["unitedstates_legislators"].base_url,
            manifest)
        links = [{"type": "bioguide", "url": f"https://bioguide.congress.gov/search/bio/{bio}"}] if bio else []
    else:
        src = h.get("source_url")
        identity_prov = _provenance("openstates", src or "https://openstates.org/", manifest)
        links = [{"type": "official", "url": src}] if src else []

    identity = {
        "full_name": h["full_name"],
        "photo_url": photo_url,
        "office": {"role": h["role"], "ocd_id": h["ocd_id"],
                   "display": _office_display(h["chamber"], h["ocd_id"]),
                   "chamber": h["chamber"]},
        "party": {"code": h["party"], "display": PARTY_DISPLAY.get(h["party"], h["party"])},
        "tenure": {"first_took_office": h["first_took_office"],
                   "current_term_ends": h["term_ends"]},
        "next_election": None,
        "status": "vacant" if vacant else "incumbent",
        "official_links": links,
        "provenance": identity_prov,
    }
    sections = {"identity": identity, "graph_ref": f"/graph/neighborhood/{h['person_id']}"}

    # Ideology + legislative record are federal-only for now; state dossiers
    # (E4) publish identity only, each fact still sourced (no provenance, no publish).
    if federal:
        score = None if h["ideology_score"] is None else float(h["ideology_score"])
        sections["ideology"] = {
            "scheme": "dw_nominate_dim1", "score": score,
            "status": h["ideology_status"] or "pending_insufficient_votes",
            "context": {"party_median": medians["party"].get(h["party"]),
                        "chamber_median": medians["chamber"].get(h["chamber"])},
            "scope": IDEOLOGY_SCOPE, "explainer_url": "/methodology#dw-nominate",
            "provenance": _provenance("voteview",
                                      f"https://voteview.com/congress/{h['chamber']}", manifest),
        }
        stats = leg_spine.get(h["person_id"], {})
        # Key votes + party agreement are Voteview-sourced (roll_calls /
        # vote_positions), so the legislative section carries a second provenance
        # envelope for its vote-derived facts — no provenance, no publish.
        my_votes = vote_records.get(h["person_id"], [])
        selected = key_votes.select_key_votes(my_votes, rc_meta)
        agreement = key_votes.agreement_pct(my_votes, h["party"], party_majority)
        for kv in selected:                        # link the citation to the bill page when known
            kv["bill_url"] = congress_gov.bill_public_url(kv["bill_id"]) if kv.get("bill_id") else None
        # Committee/subcommittee memberships come from the unitedstates
        # congress-legislators YAML, not the congress.gov API — so they carry a
        # dedicated committees_provenance envelope (like votes_provenance above),
        # stamped only when the member actually sits on a committee. No
        # provenance, no publish; absent (never on a committee) omits the stamp
        # and leaves committees as [].
        my_committees = committees.get(h["person_id"], [])
        sections["legislative"] = {
            "counts": {"sponsored": stats.get("sponsored", 0),
                       "cosponsored": cospon.get(bio, 0),
                       "became_law": stats.get("became_law", 0)},
            "recent_bills": stats.get("recent_bills", []),
            "key_votes": selected,
            "party_agreement_pct": agreement,
            "committees": my_committees,
            "provenance": _provenance("congress.gov",
                                      f"https://www.congress.gov/member/{bio}" if bio else SOURCES["congress.gov"].base_url,
                                      manifest),
            "votes_provenance": _provenance("voteview",
                                            f"https://voteview.com/congress/{h['chamber']}", manifest)
                                if selected or agreement is not None else None,
            "committees_provenance": _provenance(
                "unitedstates_legislators",
                "https://github.com/unitedstates/congress-legislators", manifest)
                if my_committees else None,
        }

    # Money publishes only where there's real data; absent renders as an honest
    # "pending", never a fabricated $0 (contracts §3).
    money: dict = {}
    cf = campaign.get(h["person_id"])
    if cf and cf["cycles"]:
        block = {
            "cycles": cf["cycles"],
            "provenance": _provenance(
                "fec", f"https://www.fec.gov/data/candidate/{cf['candidate_id']}/", manifest)}
        # Top contributors are FEC employer rollups of itemized individual
        # contributions (WO-3), capped at 10 for the dossier. Same FEC envelope;
        # absent (no committee/no itemized receipts) simply omits the block, so
        # the UI never renders a fabricated donor list.
        contribs = contributors.get(h["person_id"])
        if contribs:
            block["top_contributors"] = contribs[:10]
        money["campaign_finance"] = block
    filings = disclosures.get(h["person_id"])
    if filings:
        # STOCK Act: links to the official PTR filings (itemized trades live in
        # the PDF). Every filing carries its filing_url — no provenance, no publish.
        money["disclosures"] = {
            "filings": filings[:20], "count": len(filings),
            "provenance": _provenance("house_clerk",
                                      "https://disclosures-clerk.house.gov/FinancialDisclosure", manifest)}
    if money:
        sections["money"] = money

    return dossiers.build_one({"person_id": h["person_id"]}, sections, pipeline_version())


def run(db_path: str = DEFAULT_DB, out_dir: str | Path = PAGES_DIST,
        raw_dir: str | Path = "dist/raw") -> dict:
    raw_dir = Path(raw_dir)
    out = Path(out_dir)
    manifest = _load_manifest(raw_dir)
    photo = _photo_map(raw_dir)

    con = store.connect(db_path)
    holders = _current_holders(con)
    leg_spine = _legislative_stats(con)
    campaign = _campaign_finance(con)
    contributors = _top_contributors(con)
    vote_records = _vote_records(con)
    committees = _committees(con)
    con.close()
    medians = _medians(holders)
    cospon = _cosponsored_counts(raw_dir)
    disclosures = _disclosures(raw_dir, holders)
    rc_meta = _rollcall_meta(raw_dir)

    # Party-majority position per (roll_call, party), from every decided vote —
    # the reference each member's agreement is scored against (symmetric: same
    # rule for both parties). Built once across all members, not per dossier.
    party_majority = key_votes.party_majority_positions(
        [r for rows in vote_records.values() for r in rows])

    # --- dossiers (all members) ---
    docs = [_dossier(h, photo, manifest, medians, leg_spine, cospon, campaign,
                     contributors, disclosures, vote_records, rc_meta, party_majority,
                     committees)
            for h in holders]
    dossiers.publish(docs, out / "dossiers")

    # --- style feeds + pins, grouped by chamber -> map layer ---
    chamber_layer = {"house": "cd", "senate": "states", "upper": "sldu", "lower": "sldl"}
    by_layer: dict[str, list[dict]] = {"cd": [], "states": [], "sldu": [], "sldl": []}
    for h in holders:
        layer = chamber_layer.get(h["chamber"])
        if layer:
            by_layer[layer].append(h)

    def feed(rows):
        return stylefeeds.build_layer_feed(
            [{"ocd_id": h["ocd_id"], "party": h["party"],
              "score": None if h["ideology_score"] is None else float(h["ideology_score"]),
              "is_vacant_marker": bool(h["is_vacant_marker"])} for h in rows])

    # Colored polygon layers: House + both state chambers. (A U.S. senator isn't
    # a single polygon, so the states layer stays a discovery-only pin layer.)
    house, senate = by_layer["cd"], by_layer["states"]
    cd_feed = feed(house)
    stylefeeds.publish({"cd": cd_feed, "states": {},
                        "sldu": feed(by_layer["sldu"]), "sldl": feed(by_layer["sldl"])},
                       out / "stylefeeds")

    def pins(rows):
        # Display fields the map UI needs for hover/stack views, so the client
        # never fans out dossier fetches just to label a polygon (contract §3).
        return [{"person_id": h["person_id"], "ocd_id": h["ocd_id"],
                 "full_name": h["full_name"],
                 "office": _office_display(h["chamber"], h["ocd_id"]),
                 "chamber": h["chamber"], "vacant": bool(h["is_vacant_marker"]),
                 "lat": None, "lng": None,
                 "photo_url": h.get("image_url") or photo.get(h.get("bioguide")),
                 "party": h["party"]} for h in rows]
    (out / "pins").mkdir(parents=True, exist_ok=True)
    for layer in ("cd", "states", "sldu", "sldl"):
        (out / "pins" / f"{layer}.json").write_text(json.dumps(pins(by_layer[layer]), separators=(",", ":")))

    # --- coverage dashboard: freshness vs SLA, computed not just echoed (G2) ---
    def _source_row(k: str) -> dict:
        retrieved_at = manifest.get("sources", {}).get(k, {}).get("retrieved_at")
        sla = SOURCES[k].freshness_sla_hours if k in SOURCES else None
        age_hours = None
        if retrieved_at:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(retrieved_at)
            age_hours = round(age.total_seconds() / 3600, 2)
        return {"retrieved_at": retrieved_at, "sla_hours": sla, "age_hours": age_hours,
                "within_sla": (age_hours is not None and sla is not None
                               and age_hours <= sla)}

    coverage = {
        "generated_at": _now(), "pipeline_version": pipeline_version(),
        "counts": {"dossiers": len(docs), "cd_stylefeed": len(cd_feed),
                   "house": len(house), "senate": len(senate),
                   "state_senate": len(by_layer["sldu"]), "state_house": len(by_layer["sldl"])},
        "sources": {k: _source_row(k) for k in manifest.get("sources", {})},
    }
    (out / "coverage.json").write_text(json.dumps(coverage, separators=(",", ":")))

    print(f"build: {len(docs)} dossiers · house={len(house)} senate={len(senate)} "
          f"sldu={len(by_layer['sldu'])} sldl={len(by_layer['sldl'])} -> {out}")
    return coverage


if __name__ == "__main__":
    run()
