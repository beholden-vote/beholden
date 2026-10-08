"""The four position measures (WO-36, DATA-CONTRACTS 8.7) as pure functions.

Each takes one member's vote rows, shaped as votes/{person_id}.json publishes
them ({roll_call_id, position, party_position, policy_area}), and returns
{n, of, pct}. Each is published on its own with its own /methodology entry.
Nothing here combines, weights, averages or ranks measures into one value, and
nothing ever will: a single number would be a choice of weights presented as a
fact.

The party-agreement rule is not restated here. `party_position` comes from
key_votes.party_majority_positions and the counts from votes.summarize - the
same code that writes votes/{person_id}.json - so with_own_party equals that
file's with_party / party_decided by construction.
"""
from __future__ import annotations

from .key_votes import MIN_AGREEMENT_VOTES
from .votes import summarize

# The two parties whose majorities define with_other_party. Named for what the
# measure needs (two sides to compare), and every rule below treats them
# identically: swap the labels and every measure is unchanged.
MAJOR_PARTIES = ("D", "R")


def _measure(n: int, of: int) -> dict:
    """{n, of, pct}. n and of are always exact; pct is withheld (None) below
    the published floor so a small denominator cannot state false precision."""
    return {"n": n, "of": of,
            "pct": None if of < MIN_AGREEMENT_VOTES else round(100.0 * n / of, 1)}


def with_own_party(votes: list[dict]) -> dict:
    """Decided votes matching the member's own party majority, of the decided
    votes where that party had one (votes.summarize: with_party / party_decided)."""
    s = summarize(votes)
    return _measure(s["with_party"], s["party_decided"])


def with_other_party(votes: list[dict], party: str | None,
                     majority: dict[str, str]) -> dict | None:
    """Of the roll calls where both major parties had a majority and the two
    majorities differed, the member's decided votes that matched the OTHER
    party's majority. None for a member of neither major party: there is no
    single "other" party to compare with, and none is imputed.

    `majority` is key_votes.party_majority_positions output."""
    if party not in MAJOR_PARTIES:
        return None
    other = MAJOR_PARTIES[1 - MAJOR_PARTIES.index(party)]
    n = of = 0
    for v in votes:
        if v["position"] not in ("yea", "nay"):
            continue
        own = majority.get(f"{v['roll_call_id']}\t{party}")
        theirs = majority.get(f"{v['roll_call_id']}\t{other}")
        if own is None or theirs is None or own == theirs:
            continue
        of += 1
        n += v["position"] == theirs
    return _measure(n, of)


def missed(votes: list[dict]) -> dict:
    """not_voting, of every roll call the member was eligible for (8.3)."""
    s = summarize(votes)
    return _measure(s["not_voting"], s["total"])


def party_line_by_policy_area(votes: list[dict]) -> list[dict]:
    """with_own_party per bill policy area, alphabetical by area. Roll calls
    with no policy area are left out here (and nowhere else); an area whose
    `of` is below the floor is omitted for this member."""
    by_area: dict[str, list[dict]] = {}
    for v in votes:
        if v.get("policy_area"):
            by_area.setdefault(v["policy_area"], []).append(v)
    out = []
    for area in sorted(by_area):
        m = with_own_party(by_area[area])
        if m["pct"] is not None:
            out.append({"policy_area": area, **m})
    return out
