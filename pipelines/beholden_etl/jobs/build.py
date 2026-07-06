"""Stage 3 — DuckDB spine -> serving artifacts in dist/data (contracts §3/§5).

Emits, for the current federal legislature:
  stylefeeds/{cd,states,sldu,sldl}.json
                          ocd_id -> {party, ideology_dim1, vacant}   (colors each layer;
                          states = Senate-delegation rule, WO-14)
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

from ..config import CONGRESS, FEC_CYCLE, PAGES_DIST, SOURCES, pipeline_version
from ..build import dossiers, graph, key_votes, stylefeeds
from ..sources import congress_gov, house_clerk, voteview, wikidata
from ..sources import legislators as L
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


def _federal_contact_map(raw_dir: Path) -> dict[str, dict]:
    """bioguide -> {phone?, website?, contact_form?, dc_office_address?} from
    the current term of the landed legislators-current.json (WO-15). Reads the
    same file _photo_map's sibling sources already load; kept separate here so
    a caller that only needs contact doesn't have to re-derive current_term."""
    f = raw_dir / "unitedstates_legislators" / "legislators-current.json"
    if not f.exists():
        return {}
    out = {}
    for leg in json.loads(f.read_text(encoding="utf-8")):
        bio = (leg.get("id") or {}).get("bioguide")
        term = L.current_term(leg)
        if not bio or not term:
            continue
        contact = L.contact_from_term(term)
        if contact:
            out[bio] = contact
    return out


def _district_offices_map(raw_dir: Path) -> dict[str, list[dict]]:
    """bioguide -> [{address, city, state, zip, phone, latitude, longitude}]
    from the landed legislators-district-offices.json (WO-15, federal only)."""
    f = raw_dir / "unitedstates_legislators" / "legislators-district-offices.json"
    if not f.exists():
        return {}
    return L.district_offices_by_bioguide(json.loads(f.read_text(encoding="utf-8")))


def _social_media_map(raw_dir: Path) -> dict[str, dict]:
    """bioguide -> {twitter?, facebook?, instagram?, youtube?, mastodon?} from
    the landed legislators-social-media.json (WO-15, federal only)."""
    f = raw_dir / "unitedstates_legislators" / "legislators-social-media.json"
    if not f.exists():
        return {}
    return L.social_media_by_bioguide(json.loads(f.read_text(encoding="utf-8")))


def _member_detail_map(raw_dir: Path) -> dict[str, dict]:
    """bioguide -> the landed congress.gov member-detail record (WO-15): source
    for birth_year, previous_roles' leadership/partyHistory augmentation, and a
    second (fresher) DC office/phone. Absent for a member the fetch skipped —
    honest absence, same as every other optional dossier fact."""
    d = raw_dir / "congress.gov" / "member-detail"
    if not d.exists():
        return {}
    out = {}
    for f in d.glob("*.json"):
        out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return out


def _education_map(raw_dir: Path) -> dict[str, list[dict]]:
    """wikidata_qid -> [{institution, degree?, year?}] (WO-15, federal only).
    Reads the landed per-person P69 claims + the batched label resolution and
    joins them at build time (claims carry item ids; labels are the id->label
    map) so a person with claims but an unresolved label never publishes a
    blank institution (education_rows already drops those)."""
    claims_f = raw_dir / "wikidata" / "claims" / "educated_at.json"
    labels_f = raw_dir / "wikidata" / "labels.json"
    if not claims_f.exists() or not labels_f.exists():
        return {}
    claims_by_qid = json.loads(claims_f.read_text(encoding="utf-8"))
    labels = json.loads(labels_f.read_text(encoding="utf-8"))
    return {qid: wikidata.education_rows(claims, labels)
            for qid, claims in claims_by_qid.items() if claims}


def _provenance(source: str, source_url: str, manifest: dict,
                methodology_id: str | None = None) -> dict:
    """Provenance envelope for a section. FAILS CLOSED (rule #1): if the fetch
    manifest can't vouch for when `source` was retrieved, we refuse to invent a
    timestamp — a fabricated retrieved_at is worse than no publish.

    `methodology_id` (WO-8) is the anchor on the public /methodology page that
    explains how this section's numbers are computed (e.g. 'key-votes',
    'donor-rollups'). It stays None for sections that are verbatim source facts
    with no Beholden-computed metric; a metric-bearing section points it at the
    matching /methodology anchor so "how is this computed?" is answerable from
    the UI. The values here MUST match the anchor ids the methodology page ships."""
    meta = manifest.get("sources", {}).get(source, {})
    retrieved_at = meta.get("retrieved_at")
    if not retrieved_at:
        raise dossiers.ProvenanceError(
            f"manifest has no retrieved_at for source '{source}' — refusing to "
            "fabricate freshness (no provenance, no publish)")
    return {"source": source, "source_url": source_url,
            "retrieved_at": retrieved_at,
            "pipeline_version": pipeline_version(), "methodology_id": methodology_id}


# WO-8: methodology anchor ids per computed metric. Each MUST match a section id
# on the public /methodology page (web/src/ui/chrome.tsx Methodology) and the
# formula it documents MUST match the code that produced the number. Verbatim
# source facts (identity, raw filings) carry no methodology id (None).
METHODOLOGY_IDEOLOGY = "dw-nominate"       # DW-NOMINATE ideology score (voteview.py)
METHODOLOGY_KEY_VOTES = "key-votes"        # key-vote selection formula (key_votes.py)
METHODOLOGY_AGREEMENT = "co-voting"        # party_agreement_pct (key_votes.py)
METHODOLOGY_DONORS = "donor-rollups"       # FEC by_employer top contributors (fec.py)


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
               p.wikidata_qid, p.birth_year,
               o.role, o.chamber, d.ocd_id,
               t.party, t.is_vacant_marker,
               t.meta->>'term_ends'        AS term_ends,
               t.meta->>'first_took_office' AS first_took_office,
               t.meta->>'image'            AS image_url,
               t.meta->>'source_url'       AS source_url,
               t.meta->>'contact'          AS state_contact_json,
               t.meta->>'social'           AS state_social_json,
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
        # WO-15: state contact/social ride in terms.meta as a JSON string
        # (DuckDB's ->> stringifies nested objects); parse back to a dict, or
        # {} when the state legislator's CSV row had none (honest absence).
        r["state_contact"] = json.loads(r.pop("state_contact_json") or "null") or {}
        r["state_social"] = json.loads(r.pop("state_social_json") or "null") or {}
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


def _previous_roles(con) -> dict[str, list[dict]]:
    """person_id -> [{role, chamber, start_date, end_date, party}] of a
    person's PAST terms (WO-15), most-recent-first, straight from OUR OWN
    warehoused `terms` table (transform.py now persists every historical term,
    not just the current one). end_date IS NOT NULL is exactly "past" here —
    the current term (end_date IS NULL) is excluded, it already publishes via
    identity.tenure/office."""
    out: dict[str, list[dict]] = {}
    for pid, role, chamber, start_date, end_date, party in con.execute(
        """SELECT t.person_id, o.role, o.chamber,
                  t.start_date::VARCHAR, t.end_date::VARCHAR, t.party
           FROM terms t JOIN offices o USING(office_id)
           WHERE t.end_date IS NOT NULL
           ORDER BY t.person_id, t.end_date DESC, t.start_date DESC""").fetchall():
        out.setdefault(str(pid), []).append({
            "role": role, "chamber": chamber,
            "start_date": start_date, "end_date": end_date, "party": party})
    return out


def _legislative_stats(con) -> dict[str, dict]:
    """person_id -> {sponsored, became_law, recent_bills[]} from the bills spine."""
    stats: dict[str, dict] = {}
    for pid, sponsored, became_law in con.execute(
        """SELECT s.person_id, count(*) AS sponsored,
                  count(*) FILTER (WHERE b.status='law') AS became_law
           FROM sponsorships s JOIN bills b USING(bill_id)
           WHERE s.role='sponsor' GROUP BY s.person_id""").fetchall():
        stats[str(pid)] = {"sponsored": sponsored, "became_law": became_law, "recent_bills": []}
    # Dates are cast to VARCHAR in SQL (same reasoning as held_at in
    # _vote_records): the dossier needs the ISO date string, not a Python date.
    for pid, bill_id_, title, status, introduced_on, latest_action_on in con.execute(
        """SELECT s.person_id, b.bill_id, b.title, b.status,
                  b.introduced_on::VARCHAR, b.latest_action_on::VARCHAR
           FROM sponsorships s JOIN bills b USING(bill_id)
           WHERE s.role='sponsor'
           QUALIFY row_number() OVER (PARTITION BY s.person_id
                   ORDER BY b.latest_action_on DESC NULLS LAST, b.bill_id) <= 10""").fetchall():
        stats.setdefault(str(pid), {"sponsored": 0, "became_law": 0, "recent_bills": []})
        # WO-12: introduced_on / latest_action_on were already warehoused (used
        # for the recency sort above); published verbatim, null when the source
        # omitted them — honest absence, never an invented date.
        stats[str(pid)]["recent_bills"].append(
            {"bill_id": bill_id_, "title": title, "status": status,
             "url": congress_gov.bill_public_url(bill_id_),
             "introduced_on": introduced_on, "latest_action_on": latest_action_on})
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


def _bill_titles(con) -> dict[str, str]:
    """bill_id -> title straight from the bills spine (WO-12): lets a key vote
    show WHAT its decided bill is without a fetch to congress.gov. Titles are
    verbatim from the source; a roll call with no bills row (procedural votes,
    Senate nominations) has no entry, so bill_title publishes null — honest
    absence, never an invented title."""
    return {bill_id_: title for bill_id_, title in
            con.execute("SELECT bill_id, title FROM bills").fetchall()}


def _roll_call_tallies(con) -> dict[str, tuple]:
    """roll_call_id -> (yea_count, nay_count) from the roll_calls spine (WO-12,
    migration 005). Persisted verbatim from the Voteview rollcalls CSV by the
    transform; NULL tallies publish as null, never a fabricated 0. The key-vote
    closeness score keeps reading raw via _rollcall_meta — this map only feeds
    the published per-vote tally."""
    return {rcid: (yea, nay) for rcid, yea, nay in con.execute(
        "SELECT roll_call_id, yea_count, nay_count FROM roll_calls").fetchall()}


def _committee_urls(raw_dir: Path) -> dict[str, str]:
    """committee_id -> official committee site from the raw committees-current
    roster (WO-12). SOURCE-PROVIDED urls only — the yaml's own `url` field
    (sample urls verified live 2026-07-06), never a constructed pattern. A
    committee the source ships no url for (2 select committees today; every
    subcommittee) publishes committee_id only: honest absence over an
    unverified link. Keyed exactly like sources/legislators.committee_rows
    (subcommittee id = parent thomas_id + subcommittee thomas_id)."""
    f = raw_dir / "unitedstates_legislators" / "committees-current.json"
    if not f.exists():
        return {}
    out: dict[str, str] = {}
    for c in json.loads(f.read_text(encoding="utf-8")):
        tid = c.get("thomas_id")
        if not tid:
            continue
        if c.get("url"):
            out[tid] = c["url"]
        for sub in c.get("subcommittees") or []:
            if sub.get("thomas_id") and sub.get("url"):
                out[tid + sub["thomas_id"]] = sub["url"]
    return out


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


def _committees(con, committee_urls: dict[str, str]) -> dict[str, list[dict]]:
    """person_id -> [{committee_id, name, role, url?, subcommittees:[{committee_id,
    name, role, url?}]}] from committee_memberships joined to committees (WO-6a).
    Top-level committees are the entries; subcommittees (parent_id set) nest under
    the parent the member also sits on. Roles come straight from the source-stated
    title (member|chair|ranking|vice_chair). WO-12 adds the deterministic
    committee_id plus the SOURCE-PROVIDED official url (see _committee_urls) —
    the url key is present only when the source ships one, applied by the same
    lookup for every committee. Ordering is deterministic and party-agnostic
    (rule #3): committees alphabetical by name, subcommittees likewise —
    identical regardless of party or chamber majority."""
    rows = con.execute(
        """SELECT cm.person_id, c.committee_id, c.name, c.parent_id, cm.role
           FROM committee_memberships cm JOIN committees c USING(committee_id)
           WHERE cm.congress = ?
           ORDER BY c.name""", [CONGRESS]).fetchall()

    def item(cid: str, name: str, role: str) -> dict:
        e = {"committee_id": cid, "name": name, "role": role}
        url = committee_urls.get(cid)
        if url:                                   # source-provided only (WO-12)
            e["url"] = url
        return e

    # Index each person's top-level committee entries so subcommittees can attach
    # (parent_id is NULL for a top-level committee).
    parents: dict[str, dict[str, dict]] = {}     # person -> committee_id -> entry
    subs: list[tuple] = []                        # (person, parent_id, cid, name, role)
    for pid, cid, name, parent_id, role in rows:
        pid = str(pid)
        if parent_id is None:
            parents.setdefault(pid, {})[cid] = {**item(cid, name, role), "subcommittees": []}
        else:
            subs.append((pid, parent_id, cid, name, role))
    for pid, parent_id, cid, name, role in subs:
        parent = parents.get(pid, {}).get(parent_id)
        if parent is not None:                    # every real/fixture sub has its parent (0 orphans)
            parent["subcommittees"].append(item(cid, name, role))
    out: dict[str, list[dict]] = {}
    for pid, by_cid in parents.items():
        entries = []
        for entry in sorted(by_cid.values(), key=lambda e: e["name"]):
            e = {k: v for k, v in entry.items() if k != "subcommittees"}
            if entry["subcommittees"]:
                e["subcommittees"] = sorted(entry["subcommittees"], key=lambda s: s["name"])
            entries.append(e)
        out[pid] = entries
    return out


def _top_contributors(con) -> dict[str, list[dict]]:
    """person_id -> [{name, total_cents, rank}] employer rollups of itemized
    individual contributions, from top_contributors (WO-3), most-recent cycle
    first and ordered by rank. rank (WO-12) is the warehoused 1..N position in
    FEC's own -total order — published so the UI can show 10 and expand to the
    full list. Same FEC envelope as the cycle totals; the dossier caps the list
    at 25 (the aggregation rule is otherwise unchanged from WO-3)."""
    out: dict[str, list[dict]] = {}
    for pid, name, total, rank in con.execute(
        """SELECT person_id, contributor_name, total_cents, rank
           FROM top_contributors ORDER BY person_id, cycle DESC, rank""").fetchall():
        out.setdefault(str(pid), []).append({"name": name, "total_cents": total, "rank": rank})
    return out


def _bill_policy_areas(con) -> dict[str, list[str]]:
    """bill_id -> policy_areas[] straight from the bills spine (WO-8). These are
    congress.gov's OWN policy-area taxonomy (sources/congress_gov.bill_row reads
    item['policyArea']['name']) — Beholden adds no classification of its own. Used
    to chip a key vote's decided bill in the money-&-votes juxtaposition; a vote
    whose bill has no policy area (or a procedural vote with no bill) simply gets
    no chip (absent, never invented). Rows with a NULL/empty array are skipped."""
    out: dict[str, list[str]] = {}
    for bill_id_, areas in con.execute(
        "SELECT bill_id, policy_areas FROM bills WHERE policy_areas IS NOT NULL").fetchall():
        cleaned = [a for a in (areas or []) if a]
        if cleaned:
            out[bill_id_] = cleaned
    return out


def _all_sponsorships(con) -> dict[str, list[dict]]:
    """person_id -> [{bill_id, url}] of EVERY bill the member sponsored (the graph
    cosponsorship edge needs the full set, not the dossier's top-10). Keyed on the
    deterministic bills-spine bill_id, so a shared-bill edge is an exact id match,
    never a name guess."""
    out: dict[str, list[dict]] = {}
    for pid, bill_id_ in con.execute(
        """SELECT person_id, bill_id FROM sponsorships
           WHERE role='sponsor' ORDER BY person_id, bill_id""").fetchall():
        out.setdefault(str(pid), []).append(
            {"bill_id": bill_id_, "url": congress_gov.bill_public_url(bill_id_)})
    return out


def _committee_ids(con) -> dict[str, list[dict]]:
    """person_id -> [{committee_id, name}] of the committees a member sits on, for
    the graph committee edge. Keyed on the deterministic committee_id (thomas/
    openstates code) — a shared-committee edge is an exact id match."""
    out: dict[str, list[dict]] = {}
    for pid, cid, name in con.execute(
        """SELECT cm.person_id, c.committee_id, c.name
           FROM committee_memberships cm JOIN committees c USING(committee_id)
           WHERE cm.congress = ? ORDER BY cm.person_id, c.committee_id""",
        [CONGRESS]).fetchall():
        out.setdefault(str(pid), []).append({"committee_id": cid, "name": name})
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
             party_majority: dict, committees: dict,
             policy_areas: dict[str, list[str]], bill_titles: dict[str, str],
             rc_tallies: dict[str, tuple], district_offices: dict, social_media: dict,
             member_detail: dict, education: dict, previous_roles: dict,
             federal_contact: dict) -> dict:
    bio = h.get("bioguide")
    federal = h["chamber"] in FEDERAL_CHAMBERS
    vacant = bool(h["is_vacant_marker"])
    photo_url = h.get("image_url") or photo.get(bio)   # OpenStates image or congress.gov headshot
    detail = member_detail.get(bio) if bio else None

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

    # --- WO-15: contact (federal: congress-legislators current-term fields,
    # via federal_contact keyed by bioguide; state: OpenStates CSV columns,
    # already folded into h by _current_holders). Congress publishes no direct
    # member email — contact_form/website is the closest federal equivalent
    # (never fabricated). Absent entirely -> key omitted, never null. ---
    if federal:
        contact = dict(federal_contact.get(bio) or {}) if bio else {}
        # congress.gov member-detail's own DC office/phone as a second (often
        # fresher) source when the legislators-YAML term lacked them.
        if detail:
            for k, v in congress_gov.dc_office_from_detail(detail).items():
                contact.setdefault(k, v)
    else:
        contact = dict(h.get("state_contact") or {})
    if contact:
        identity["contact"] = contact

    if federal and bio and district_offices.get(bio):
        identity["district_offices"] = district_offices[bio]

    social = social_media.get(bio, {}) if federal and bio else (h.get("state_social") or {})
    if social:
        identity["social"] = social

    roles = previous_roles.get(h["person_id"])
    if roles:
        identity["previous_roles"] = roles

    # birth_year: congress.gov member-detail's own field REPLACES the need for
    # Wikidata on this one fact (WO-15); falls back to the warehoused value
    # (unitedstates-legislators bio.birthday, already on `persons`) when
    # member-detail is absent for this run. Published only when present.
    by = congress_gov.birth_year(detail) if detail else None
    if by is None:
        by = h.get("birth_year")
    if by is not None:
        identity["birth_year"] = int(by)

    # education (federal only, Wikidata): a DEDICATED envelope + the verbatim
    # crowd-sourced caveat, published ONLY alongside the array itself — never
    # under identity.provenance, and never presented with the same unqualified
    # trust as the official sources above (docs/workplan/README.md WO-15).
    edu = education.get(h.get("wikidata_qid")) if federal and h.get("wikidata_qid") else None
    if edu:
        identity["education"] = {
            "items": edu,
            "credibility_note": wikidata.CREDIBILITY_NOTE,
            "provenance": _provenance(
                "wikidata", wikidata.entity_url(h["wikidata_qid"]), manifest),
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
                                      f"https://voteview.com/congress/{h['chamber']}", manifest,
                                      methodology_id=METHODOLOGY_IDEOLOGY),
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
            # WO-12: the decided bill's warehoused title, so the drill-down shows
            # what the vote decided. Null for procedural votes with no bill —
            # honest absence, never an invented title.
            kv["bill_title"] = bill_titles.get(kv["bill_id"]) if kv.get("bill_id") else None
            # WO-8: attach congress.gov's policy-area taxonomy for the decided bill
            # (the money-&-votes juxtaposition's only "relatedness" chip). Absent
            # for procedural votes (no bill) or bills with no classified area —
            # never invented, and never a Beholden-drawn link.
            kv["policy_areas"] = policy_areas.get(kv["bill_id"]) if kv.get("bill_id") else None
            # WO-12: Voteview's secondary vote text, verbatim, only when it adds
            # information beyond `question` (voteview.question_and_description).
            kv["description"] = (rc_meta.get(kv["roll_call_id"]) or {}).get("description")
            # WO-12: chamber-wide tallies, persisted on roll_calls (migration
            # 005) and published verbatim; null when the source lacked a tally.
            kv["yea_count"], kv["nay_count"] = rc_tallies.get(kv["roll_call_id"], (None, None))
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
                                            f"https://voteview.com/congress/{h['chamber']}", manifest,
                                            methodology_id=(METHODOLOGY_AGREEMENT if agreement is not None
                                                            else METHODOLOGY_KEY_VOTES))
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
        # Top contributors are FEC employer rollups of itemized individual
        # contributions (WO-3), capped at 25 for the dossier (WO-12; the UI
        # shows 10 and expands via rank). Same FEC envelope; absent (no
        # committee/no itemized receipts) simply omits the block, so the UI
        # never renders a fabricated donor list.
        contribs = contributors.get(h["person_id"])
        # WO-8: the FEC envelope points at the donor-rollups methodology only when
        # the block actually carries the aggregated top-contributor metric; the
        # cycle totals alone are verbatim FEC facts (no Beholden-computed metric).
        block = {
            "cycles": cf["cycles"],
            "provenance": _provenance(
                "fec", f"https://www.fec.gov/data/candidate/{cf['candidate_id']}/", manifest,
                methodology_id=METHODOLOGY_DONORS if contribs else None)}
        if contribs:
            block["top_contributors"] = contribs[:25]
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


def _build_graph(out: Path, holders: list[dict], all_sponsorships: dict,
                 vote_records: dict, rc_meta: dict, contributors: dict,
                 committee_ids: dict) -> int:
    """Compute the §4 entity graph and write graph/neighborhood/{person_id}.json.

    Nodes are the current holders (keyed on the deterministic person_id). Edges
    are computed pairwise WITHIN each chamber bucket from deterministic keys only
    (bill_id / roll_call_id / verbatim contributor_name / committee_id) — no fuzzy
    matching enters here (TRUSTED-EXTRACTION §9). Returns the number of
    neighborhood documents written. An empty warehouse yields zero edges and still
    emits a valid (edge-free) neighborhood per node."""
    as_of = datetime.now(timezone.utc).date().isoformat()
    node_by_id = {}
    for h in holders:
        node_by_id[h["person_id"]] = {
            "person_id": h["person_id"], "name": h["full_name"],
            "party": h["party"],
            "office_display": _office_display(h["chamber"], h["ocd_id"]),
            "ideology_dim1": h["ideology_score"]}
    members = list(node_by_id.values())

    # Bucket members by chamber so edges never cross chambers (a House rep and a
    # senator share no roll calls/bills here). Same rule for every party.
    by_chamber: dict[str, list[str]] = {}
    window_by_chamber: dict[str, str] = {}
    for h in holders:
        by_chamber.setdefault(h["chamber"], []).append(h["person_id"])
        window_by_chamber[h["chamber"]] = f"{CONGRESS}th Congress"

    # Decided (yea/nay) positions per member for the co-voting edge, and the
    # roll-call ref (official record URL) for its evidence — both from data the
    # dossier build already loads.
    positions: dict[str, dict[str, str]] = {}
    for pid, rows in vote_records.items():
        decided = {r["roll_call_id"]: r["position"] for r in rows
                   if r["position"] in ("yea", "nay")}
        if decided:
            positions[pid] = decided
    rc_refs = {rc: {"kind": "roll_call", "id": rc, "url": m["url"]}
               for rc, m in rc_meta.items()}

    edges: list[dict] = []
    for chamber, ids in by_chamber.items():
        window = window_by_chamber[chamber]
        edges += graph.cosponsorship_edges(ids, all_sponsorships, window)
        edges += graph.co_voting_edges(ids, positions, rc_refs, window)
        edges += graph.shared_donor_edges(ids, contributors, FEC_CYCLE, window)
        edges += graph.committee_edges(ids, committee_ids, window)

    docs = graph.neighborhoods(members, edges, as_of)
    return graph.publish(docs, out / "graph" / "neighborhood")


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
    committees = _committees(con, _committee_urls(raw_dir))
    all_sponsorships = _all_sponsorships(con)     # graph: full sponsor set (WO-4)
    committee_ids = _committee_ids(con)           # graph: committee_id refs (WO-4)
    policy_areas = _bill_policy_areas(con)        # WO-8: bill_id -> policy-area chips
    bill_titles = _bill_titles(con)               # WO-12: key-vote bill_title join
    rc_tallies = _roll_call_tallies(con)          # WO-12: persisted yea/nay tallies
    previous_roles = _previous_roles(con)         # WO-15: past terms (our own warehouse)
    con.close()
    medians = _medians(holders)
    cospon = _cosponsored_counts(raw_dir)
    disclosures = _disclosures(raw_dir, holders)
    rc_meta = _rollcall_meta(raw_dir)
    federal_contact = _federal_contact_map(raw_dir)     # WO-15
    district_offices = _district_offices_map(raw_dir)   # WO-15
    social_media = _social_media_map(raw_dir)           # WO-15
    member_detail = _member_detail_map(raw_dir)         # WO-15
    education = _education_map(raw_dir)                 # WO-15

    # Party-majority position per (roll_call, party), from every decided vote —
    # the reference each member's agreement is scored against (symmetric: same
    # rule for both parties). Built once across all members, not per dossier.
    party_majority = key_votes.party_majority_positions(
        [r for rows in vote_records.values() for r in rows])

    # --- dossiers (all members) ---
    docs = [_dossier(h, photo, manifest, medians, leg_spine, cospon, campaign,
                     contributors, disclosures, vote_records, rc_meta, party_majority,
                     committees, policy_areas, bill_titles, rc_tallies,
                     district_offices, social_media, member_detail, education,
                     previous_roles, federal_contact)
            for h in holders]
    dossiers.publish(docs, out / "dossiers")

    # --- entity graph (WO-4): neighborhood docs per member, every edge cited ---
    graph_docs = _build_graph(out, holders, all_sponsorships, vote_records,
                              rc_meta, contributors, committee_ids)

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

    # Colored polygon layers: House, both state chambers, AND states (WO-14). A
    # U.S. senator isn't a single polygon, so the states layer encodes the
    # two-seat Senate DELEGATION per state — one fixed, party-symmetric rule; see
    # stylefeeds.build_senate_delegation_feed (mirrored on /methodology).
    house, senate = by_layer["cd"], by_layer["states"]
    cd_feed = feed(house)
    states_feed = stylefeeds.build_senate_delegation_feed(
        [{"ocd_id": h["ocd_id"], "party": h["party"],
          "is_vacant_marker": bool(h["is_vacant_marker"])} for h in senate])
    stylefeeds.publish({"cd": cd_feed, "states": states_feed,
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

    # --- people search index (WO-5): flat name index for the topbar search, so a
    # name query jumps straight to a dossier without fanning out dossier fetches.
    # One row per current officeholder across every layer — the same fields for
    # every official (symmetric by construction). Lazy-loaded client-side. ---
    people = [{"person_id": h["person_id"], "full_name": h["full_name"],
               "office": _office_display(h["chamber"], h["ocd_id"]),
               "party": h["party"], "ocd_id": h["ocd_id"]}
              for h in holders if h["full_name"]]
    people.sort(key=lambda r: r["full_name"])
    (out / "search").mkdir(parents=True, exist_ok=True)
    (out / "search" / "people.json").write_text(json.dumps(people, separators=(",", ":")))

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
        "counts": {"dossiers": len(docs), "graph_neighborhoods": graph_docs,
                   "cd_stylefeed": len(cd_feed), "states_stylefeed": len(states_feed),
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
