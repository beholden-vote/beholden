"""Key-vote selection + co-voting agreement (WO-1).

Both stats are computed by fixed formula from the roll_calls / vote_positions
spine — no hand-picking, no topic weighting, no per-party tuning (rule #3:
symmetric by construction). The formulas live here and are surfaced verbatim via
/methodology so a reader can reproduce every published number.

KEY-VOTE SELECTION (per member, only roll calls where they voted yea/nay):
    salience = closeness + recency_bonus
      closeness      = 1 - |yea - nay| / (yea + nay)      # 1.0 == a tie
      recency_bonus  = 0.25 * (rank / n)                  # newest vote -> 0.25
    Take the top 10 by salience. Ties break on held_at (newer first) then
    roll_call_id, so selection is deterministic across runs.

PARTY AGREEMENT (per member, only roll calls where they voted yea/nay):
    party_agreement_pct = 100 * (# votes matching the member's party's majority
                                 position on that roll call) / (# such votes)
    Omitted (None) below MIN_AGREEMENT_VOTES so a handful of votes can't produce
    a misleadingly precise percentage.
"""
from __future__ import annotations

# Below this many yea/nay votes we don't publish an agreement percentage —
# a small denominator would over-state precision (mirrors IDEOLOGY_MIN_VOTES).
MIN_AGREEMENT_VOTES = 20
RECENCY_WEIGHT = 0.25
KEY_VOTES_PER_MEMBER = 10


def _closeness(yea: int, nay: int) -> float:
    total = yea + nay
    if total <= 0:
        return 0.0
    return 1.0 - abs(yea - nay) / total


def select_key_votes(votes: list[dict], meta: dict[str, dict],
                     limit: int = KEY_VOTES_PER_MEMBER) -> list[dict]:
    """Top-`limit` most salient yea/nay votes for one member.

    `votes` are that member's rows: {roll_call_id, position, question, held_at,
    result, bill_id}. `meta` is roll_call_id -> {yea, nay, date, url} from the raw
    rollcalls CSV. Present/not_voting positions are excluded from key votes (the
    member took no side). Returns contract-shaped key_votes[] items, newest first
    within the selected set.
    """
    decided = [v for v in votes
               if v["position"] in ("yea", "nay") and v["roll_call_id"] in meta]
    if not decided:
        return []
    # Recency rank: oldest -> 0, newest -> n-1, by held_at then id (deterministic).
    ordered = sorted(decided, key=lambda v: (v["held_at"] or "", v["roll_call_id"]))
    n = len(ordered)
    for rank, v in enumerate(ordered):
        m = meta[v["roll_call_id"]]
        v["_salience"] = _closeness(m["yea"], m["nay"]) + RECENCY_WEIGHT * (rank / n)
    top = sorted(ordered, key=lambda v: (v["_salience"], v["held_at"] or "", v["roll_call_id"]),
                 reverse=True)[:limit]
    top.sort(key=lambda v: (v["held_at"] or "", v["roll_call_id"]), reverse=True)
    return [{
        "roll_call_id": v["roll_call_id"],
        "question": v["question"],
        "position": v["position"],
        "result": v["result"],
        "held_at": v["held_at"],
        "bill_id": v["bill_id"],
        "url": meta[v["roll_call_id"]]["url"],
    } for v in top]


def party_majority_positions(rows: list[dict]) -> dict[str, str]:
    """roll_call_id -> the majority yea/nay position of each party, keyed as
    '{roll_call_id}\\t{party}'. `rows` are all decided (yea/nay) positions with a
    party attached: {roll_call_id, party, position}. A party with an equal split
    on a roll call has no majority and is omitted (that roll call simply doesn't
    count toward its members' agreement)."""
    tally: dict[tuple[str, str], list[int]] = {}
    for r in rows:
        if r["position"] not in ("yea", "nay") or not r.get("party"):
            continue
        yn = tally.setdefault((r["roll_call_id"], r["party"]), [0, 0])
        yn[0 if r["position"] == "yea" else 1] += 1
    out: dict[str, str] = {}
    for (rcid, party), (yea, nay) in tally.items():
        if yea == nay:
            continue                              # no majority -> excluded
        out[f"{rcid}\t{party}"] = "yea" if yea > nay else "nay"
    return out


def agreement_pct(member_rows: list[dict], party: str,
                  majority: dict[str, str]) -> float | None:
    """% of a member's decided votes that match their party's majority position.
    None below MIN_AGREEMENT_VOTES. `member_rows`: this member's decided rows
    {roll_call_id, position}; `majority` from party_majority_positions."""
    matched = considered = 0
    for r in member_rows:
        if r["position"] not in ("yea", "nay"):
            continue
        maj = majority.get(f"{r['roll_call_id']}\t{party}")
        if maj is None:
            continue                              # party had no majority here
        considered += 1
        if r["position"] == maj:
            matched += 1
    if considered < MIN_AGREEMENT_VOTES:
        return None
    return round(100.0 * matched / considered, 1)
