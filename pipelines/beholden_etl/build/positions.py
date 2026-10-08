"""Position profile: published measures, never a score (WO-36; DATA-CONTRACTS 8.7).

    positions/house.json   positions/senate.json

One file per chamber, one entry per sitting member, every entry the same
fields: Voteview's two DW-NOMINATE dimensions verbatim, the four measures of
build/measures.py each with its own formula, and a 2-D similarity layout of the
co-voting agreement matrix build/graph.py already computes.

There is no composite. Nothing here sums, averages, weights or ranks measures
into one value, and the gate below refuses any key that would name one.

The layout is classical multidimensional scaling of the distance
1 - agreement (agreement over shared decided roll calls, graph.agreement_matrix).
Pure Python - no numpy in the pipeline, and a chamber of 435 is small: the top
two eigenvectors come from power iteration from a fixed start, so a rebuild on
the same data gives the same bytes. Each axis is oriented by a rule that never
looks at party (the first placed member by person_id lands on the positive
side) and scaled into [-1, 1]. The axes carry no meaning and nothing is
labelled.
"""
from __future__ import annotations

import math
import operator
import re
from datetime import datetime, timezone

from .. import store
from ..config import CONGRESS
from . import dossiers, graph, key_votes, measures
from . import votes as V
from .context import BuildContext

CHAMBERS = ("house", "senate")
# Anchors on /methodology (web/src/ui/Methodology.tsx). The envelope cites the
# section; each measure cites its own entry.
METHODOLOGY_PROFILE = "position-profile"
METHODOLOGY_IDS = {"with_own_party": "with-own-party", "with_other_party": "with-other-party",
                   "missed": "missed-votes", "party_line": "party-line",
                   "layout": "similarity-layout"}
# A member is placed on the layout only with at least this many decided votes:
# the same base graph.py requires before it publishes a pairwise agreement.
LAYOUT_MIN_VOTES = graph.MIN_SHARED_VOTES
LAYOUT_DECIMALS = 3
_POWER_ITERATIONS = 5000
_POWER_TOLERANCE = 1e-12
# Keys that would name a composite. Checked over the whole document except the
# provenance envelope, whose `grade` is the 1.1 credibility grade of how the
# source was obtained - required by rule #1, and not a judgement of a member.
_COMPOSITE_KEY = re.compile(r"score|rating|rank|grade", re.I)


# --- layout -------------------------------------------------------------------
def _matvec(m: list[list[float]], v: list[float]) -> list[float]:
    return [sum(map(operator.mul, row, v)) for row in m]


def _top_eigenvector(m: list[list[float]], orthogonal_to: list[list[float]]):
    """(eigenvalue, unit eigenvector) for the LARGEST eigenvalue of symmetric m,
    by power iteration from a fixed start, kept orthogonal to `orthogonal_to`.
    Iterates on m + cI with c the Gershgorin bound, so every eigenvalue is
    non-negative and a large negative one (a non-Euclidean distance) can never
    win over the largest positive one."""
    n = len(m)
    c = max(math.fsum(abs(x) for x in row) for row in m)
    v = [math.sin(i + 1.0) for i in range(n)]       # fixed, non-constant start
    for _ in range(_POWER_ITERATIONS):
        for u in orthogonal_to:
            d = math.fsum(a * b for a, b in zip(v, u))
            v = [a - d * b for a, b in zip(v, u)]
        norm = math.sqrt(math.fsum(a * a for a in v))
        if norm == 0.0:
            return 0.0, [0.0] * n
        v = [a / norm for a in v]
        w = [a + c * b for a, b in zip(_matvec(m, v), v)]
        wn = math.sqrt(math.fsum(a * a for a in w))
        if wn == 0.0:
            return 0.0, [0.0] * n
        w = [a / wn for a in w]
        done = math.fsum((a - b) ** 2 for a, b in zip(w, v)) < _POWER_TOLERANCE
        v = w
        if done:
            break
    return math.fsum(a * b for a, b in zip(v, _matvec(m, v))), v


def layout(member_ids: list[str], decided: dict[str, dict[str, str]]) -> dict[str, dict]:
    """person_id -> {x, y} for every member placed; members below the vote floor,
    or without a published agreement to every other placed member, are absent."""
    placed = sorted(m for m in member_ids if len(decided.get(m, {})) >= LAYOUT_MIN_VOTES)
    matrix = graph.agreement_matrix(placed, decided)
    # Every placed pair needs a published agreement. Drop, one at a time, the
    # member missing the most pairs (ties: highest person_id) - a rule that
    # never looks at party - until the matrix is complete.
    while True:
        missing = {m: 0 for m in placed}
        for i, a in enumerate(placed):
            for b in placed[i + 1:]:
                if (a, b) not in matrix:
                    missing[a] += 1
                    missing[b] += 1
        worst = max(placed, key=lambda m: (missing[m], m), default=None)
        if worst is None or missing[worst] == 0:
            break
        placed.remove(worst)
    n = len(placed)
    if n == 0:
        return {}
    d2 = [[0.0] * n for _ in range(n)]
    for i, a in enumerate(placed):
        for j in range(i + 1, n):
            shared, agree = matrix[(a, placed[j])]
            d2[i][j] = d2[j][i] = (1.0 - agree / len(shared)) ** 2
    row = [math.fsum(r) / n for r in d2]
    grand = math.fsum(row) / n
    b = [[-0.5 * (d2[i][j] - row[i] - row[j] + grand) for j in range(n)] for i in range(n)]
    axes: list[list[float]] = []
    for _ in range(2):
        lam, vec = _top_eigenvector(b, axes)
        axes.append(vec if lam > 0 else [0.0] * n)
    coords = []
    for vec in axes:
        top = max(abs(c) for c in vec)
        vec = [c / top for c in vec] if top > 0 else vec
        # Orientation: the first placed member (by person_id) whose coordinate
        # is non-zero at the published precision sits on the positive side.
        lead = next((c for c in vec if round(c, LAYOUT_DECIMALS) != 0), 0.0)
        coords.append([(-c if lead < 0 else c) for c in vec])
    return {pid: {"x": round(coords[0][i], LAYOUT_DECIMALS) + 0.0,
                  "y": round(coords[1][i], LAYOUT_DECIMALS) + 0.0}
            for i, pid in enumerate(placed)}


# --- the document -------------------------------------------------------------
def chamber_members(members: list[dict], cast_by: dict[str, list[tuple[str, str]]],
                    majority: dict[str, str], rc_area: dict[str, str | None],
                    nominate: dict[str, tuple]) -> list[dict]:
    """The `members` array for one chamber. `members`: {person_id, name, party,
    state}; `cast_by`: person_id -> [(roll_call_id, position)]; `majority`:
    key_votes.party_majority_positions; `rc_area`: roll_call_id -> policy area;
    `nominate`: person_id -> (dim1, dim2)."""
    decided = {m["person_id"]: {rc: p for rc, p in cast_by.get(m["person_id"], [])
                                if p in ("yea", "nay")} for m in members}
    placed = layout([m["person_id"] for m in members], decided)
    out = []
    for m in sorted(members, key=lambda m: m["person_id"]):
        pid = m["person_id"]
        rows = [{"roll_call_id": rc, "position": p,
                 "party_position": majority.get(f"{rc}\t{m['party']}"),
                 "policy_area": rc_area.get(rc)} for rc, p in cast_by.get(pid, [])]
        _check_counts(pid, rows)
        dim1, dim2 = nominate.get(pid, (None, None))
        out.append({
            "person_id": pid, "name": m["name"], "party": m["party"], "state": m["state"],
            "nominate": {"dim1": dim1, "dim2": dim2},
            "measures": {
                "with_own_party": measures.with_own_party(rows),
                "with_other_party": measures.with_other_party(rows, m["party"], majority),
                "missed": measures.missed(rows),
                "party_line_by_policy_area": measures.party_line_by_policy_area(rows)},
            "layout": placed.get(pid)})
    return out


def _check_counts(pid: str, rows: list[dict]) -> None:
    """Control total (rule #2): the four positions sum to the record's total."""
    s = V.summarize(rows)
    if sum(s[p] for p in V.POSITIONS) != s["total"]:
        raise ValueError(f"positions: {pid} yea+nay+present+not_voting != total")


def validate(doc: dict, sitting: set[str]) -> None:
    """Fail closed: every sitting member present exactly once, every pct within
    [0, 100], and no key anywhere that names a composite."""
    ids = [m["person_id"] for m in doc["members"]]
    if len(ids) != len(set(ids)) or set(ids) != sitting:
        raise ValueError(f"positions/{doc['chamber']}: members do not match the sitting chamber")
    for m in doc["members"]:
        ms = m["measures"]
        for x in [ms["with_own_party"], ms["with_other_party"], ms["missed"],
                  *ms["party_line_by_policy_area"]]:
            if x is not None and x["pct"] is not None and not 0 <= x["pct"] <= 100:
                raise ValueError(f"positions: {m['person_id']} pct out of range: {x}")

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "provenance":
                    continue
                if _COMPOSITE_KEY.search(k):
                    raise ValueError(f"positions: key {k!r} names a composite - refusing")
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(doc)


def publish(ctx: BuildContext) -> dict[str, int]:
    from ..jobs import build as B           # cycle: jobs.build imports this module

    con = store.connect(ctx.db_path)
    try:
        landed = con.execute(
            "SELECT count(*) FROM roll_calls WHERE starts_with(roll_call_id, ?)",
            [V.SCOPE_PREFIX]).fetchone()[0]
        positions = con.execute(
            """SELECT roll_call_id, person_id::VARCHAR, position FROM vote_positions
               WHERE starts_with(roll_call_id, ?)
               ORDER BY roll_call_id, person_id""", [V.SCOPE_PREFIX]).fetchall()
        # The same policy area votes/{person_id}.json publishes for a roll call.
        rc_area = {rcid: next((a for a in areas or [] if a), None)
                   for rcid, areas in con.execute(
                       """SELECT r.roll_call_id, b.policy_areas FROM roll_calls r
                          JOIN bills b USING(bill_id)
                          WHERE starts_with(r.roll_call_id, ?)""", [V.SCOPE_PREFIX]).fetchall()}
        nominate = {str(pid): (None if d1 is None else float(d1), None if d2 is None else float(d2))
                    for pid, d1, d2 in con.execute(
                        """SELECT person_id, score, nominate_dim2 FROM ideology_scores
                           WHERE scheme = 'dw_nominate_dim1' AND scope = ?""",
                        [str(CONGRESS)]).fetchall()}
    finally:
        con.close()
    if not landed:
        # No roll calls landed: a profile of zeros would be fabricated. Same rule
        # as votes.publish.
        return {f"positions_{c}": 0 for c in CHAMBERS}

    people = {h["person_id"]: h for h in ctx.holders if not h["is_vacant_marker"]}
    # Exactly the majority votes.publish computes, so with_own_party equals the
    # published with_party / party_decided.
    majority = key_votes.party_majority_positions(
        [{"roll_call_id": rcid, "party": people[pid]["party"], "position": position}
         for rcid, pid, position in positions if pid in people])
    cast_by: dict[str, list[tuple[str, str]]] = {}
    for rcid, pid, position in positions:
        if pid in people:
            cast_by.setdefault(pid, []).append((rcid, position))

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    counts = {}
    for chamber in CHAMBERS:
        members = [{"person_id": pid, "name": h["full_name"], "party": h["party"],
                    "state": (B._state_from_ocd(h["ocd_id"]) or "").upper() or None}
                   for pid, h in people.items() if h["chamber"] == chamber]
        # A member's whole record, exactly as votes/{person_id}.json counts it.
        doc = {
            "schema_version": dossiers.SCHEMA_VERSION, "chamber": chamber,
            "generated_at": generated_at, "scope": B.IDEOLOGY_SCOPE,
            "members": chamber_members(members, cast_by, majority, rc_area, nominate),
            "methodology_ids": dict(METHODOLOGY_IDS),
            "provenance": ctx.provenance("voteview", f"https://voteview.com/congress/{chamber}",
                                         methodology_id=METHODOLOGY_PROFILE),
        }
        validate(doc, {m["person_id"] for m in members})
        V._write(ctx.out, "positions", chamber, doc)
        counts[f"positions_{chamber}"] = len(members)
    return counts
