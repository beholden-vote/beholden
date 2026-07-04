"""Stage 3 — DuckDB spine -> serving artifacts in dist/data (contracts §3/§5).

Emits, for the current federal legislature:
  stylefeeds/cd.json      ocd_id -> {party, ideology_dim1, vacant}   (colors the CD layer)
  pins/{cd,states}.json   ocd_id -> office-holder (dossier discovery on tap)
  dossiers/{person_id}.json   identity + ideology + legislative, each provenanced
  coverage.json           per-source freshness vs SLA + artifact counts

Enforces the serving rule via dossiers.validate(): no provenance, no publish.
The legislative section carries real sponsored/cosponsored/became-law counts and
recent bills (E2); key votes and committees are the next slices.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from ..config import CONGRESS, PAGES_DIST, SOURCES, pipeline_version
from ..build import dossiers, stylefeeds
from ..sources import congress_gov
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
    if chamber == "house":
        seat = tail.split(":")[1] if tail.startswith("cd:") else tail
        return f"U.S. House · {state}-{seat}"
    return f"U.S. Senate · {state}"


def _current_holders(con) -> list[dict]:
    cur = con.execute(
        """
        SELECT p.person_id, p.full_name,
               o.role, o.chamber, d.ocd_id,
               t.party, t.is_vacant_marker,
               t.meta->>'term_ends'        AS term_ends,
               t.meta->>'first_took_office' AS first_took_office,
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


def _dossier(h: dict, photo: dict, manifest: dict, medians: dict,
             leg_spine: dict, cospon: dict, campaign: dict) -> dict:
    bio = h.get("bioguide")
    vacant = bool(h["is_vacant_marker"])
    score = None if h["ideology_score"] is None else float(h["ideology_score"])
    identity = {
        "full_name": h["full_name"],
        "photo_url": photo.get(bio),
        "office": {"role": h["role"], "ocd_id": h["ocd_id"],
                   "display": _office_display(h["chamber"], h["ocd_id"]),
                   "chamber": h["chamber"]},
        "party": {"code": h["party"], "display": PARTY_DISPLAY.get(h["party"], h["party"])},
        "tenure": {"first_took_office": h["first_took_office"],
                   "current_term_ends": h["term_ends"]},
        "next_election": None,
        "status": "vacant" if vacant else "incumbent",
        "official_links": ([{"type": "bioguide",
                             "url": f"https://bioguide.congress.gov/search/bio/{bio}"}] if bio else []),
        "provenance": _provenance(
            "unitedstates_legislators",
            f"https://bioguide.congress.gov/search/bio/{bio}" if bio else SOURCES["unitedstates_legislators"].base_url,
            manifest),
    }
    ideology = {
        "scheme": "dw_nominate_dim1", "score": score,
        "status": h["ideology_status"] or "pending_insufficient_votes",
        "context": {"party_median": medians["party"].get(h["party"]),
                    "chamber_median": medians["chamber"].get(h["chamber"])},
        "scope": IDEOLOGY_SCOPE, "explainer_url": "/methodology#dw-nominate",
        "provenance": _provenance("voteview",
                                  f"https://voteview.com/congress/{h['chamber']}", manifest),
    }
    stats = leg_spine.get(h["person_id"], {})
    legislative = {   # E2: sponsored/became-law + recent bills from the spine;
                      # cosponsored total from the landed snapshot; votes/committees follow.
        "counts": {"sponsored": stats.get("sponsored", 0),
                   "cosponsored": cospon.get(bio, 0),
                   "became_law": stats.get("became_law", 0)},
        "recent_bills": stats.get("recent_bills", []),
        "key_votes": [], "committees": [],
        "provenance": _provenance("congress.gov",
                                  f"https://www.congress.gov/member/{bio}" if bio else SOURCES["congress.gov"].base_url,
                                  manifest),
    }
    sections = {"identity": identity, "ideology": ideology, "legislative": legislative,
                "graph_ref": f"/graph/neighborhood/{h['person_id']}"}

    cf = campaign.get(h["person_id"])
    if cf and cf["cycles"]:
        # Money section publishes only when there's real FEC data; absent money
        # renders as an honest "pending", never a fabricated $0 (contracts §3).
        sections["money"] = {"campaign_finance": {
            "cycles": cf["cycles"],
            "provenance": _provenance(
                "fec", f"https://www.fec.gov/data/candidate/{cf['candidate_id']}/", manifest),
        }}

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
    con.close()
    medians = _medians(holders)
    cospon = _cosponsored_counts(raw_dir)

    # --- dossiers (all members) ---
    docs = [_dossier(h, photo, manifest, medians, leg_spine, cospon, campaign) for h in holders]
    dossiers.publish(docs, out / "dossiers")

    # --- style feed + pins for the CD layer (House) ---
    house = [h for h in holders if h["chamber"] == "house"]
    cd_feed = stylefeeds.build_layer_feed(
        [{"ocd_id": h["ocd_id"], "party": h["party"],
          "score": None if h["ideology_score"] is None else float(h["ideology_score"]),
          "is_vacant_marker": bool(h["is_vacant_marker"])} for h in house])
    # Every layer the client requests gets a feed; layers without data yet
    # (states colouring, state chambers) ship empty so the map loads 404-free
    # and lights up automatically once those verticals land.
    stylefeeds.publish({"cd": cd_feed, "states": {}, "sldu": {}, "sldl": {}}, out / "stylefeeds")

    def pins(rows):
        # Carries the display fields the map UI needs for hover/stack views so
        # the client never has to fan out dossier fetches just to label a
        # polygon (contract §3: pins = dossier discovery on tap).
        return [{"person_id": h["person_id"], "ocd_id": h["ocd_id"],
                 "full_name": h["full_name"],
                 "office": _office_display(h["chamber"], h["ocd_id"]),
                 "chamber": h["chamber"],
                 "vacant": bool(h["is_vacant_marker"]),
                 "lat": None, "lng": None, "photo_url": photo.get(h.get("bioguide")),
                 "party": h["party"]} for h in rows]
    (out / "pins").mkdir(parents=True, exist_ok=True)
    (out / "pins" / "cd.json").write_text(json.dumps(pins(house), separators=(",", ":")))
    senate = [h for h in holders if h["chamber"] == "senate"]
    (out / "pins" / "states.json").write_text(json.dumps(pins(senate), separators=(",", ":")))
    for empty in ("sldu", "sldl"):
        (out / "pins" / f"{empty}.json").write_text("[]")

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
                   "house": len(house), "senate": len(senate)},
        "sources": {k: _source_row(k) for k in manifest.get("sources", {})},
    }
    (out / "coverage.json").write_text(json.dumps(coverage, separators=(",", ":")))

    print(f"build: {len(docs)} dossiers, {len(cd_feed)} cd stylefeed, "
          f"{len(house)} house pins, {len(senate)} senate pins -> {out}")
    return coverage


if __name__ == "__main__":
    run()
