"""Style feeds: ocd_id -> {party, ideology_dim1, vacant} (data-contracts §5).
Tiles carry geometry+OCD only; this feed is what colors them — the mechanism that
keeps map state and dossier data from ever disagreeing."""
from __future__ import annotations
import json
from pathlib import Path

def build_layer_feed(rows: list[dict]) -> dict:
    """rows: current-term join of terms+offices+ideology per division."""
    return {r["ocd_id"]: {"party": r["party"],
                          "ideology_dim1": r.get("score"),
                          "vacant": bool(r.get("is_vacant_marker"))}
            for r in rows}


def build_senate_delegation_feed(senate_rows: list[dict]) -> dict:
    """states.json (WO-14): one row per STATE, keyed by the state's ocd_id, colored
    by its two-seat U.S. Senate DELEGATION. A senator is not a single polygon —
    both of a state's senators share the state division — so the state fill
    encodes the delegation under ONE fixed rule, identical for every state
    (symmetric by construction, rule #3):

      - both seated senators the same party -> that party code, vacant=false
      - seated senators from different parties -> the dedicated code "SPLIT",
        vacant=false (the order the senators arrive in never matters)
      - one seat vacant or absent from the warehouse -> the seated senator's
        party with vacant=true (we color what we know and flag what we don't —
        never inventing the second seat)
      - both seats vacant/absent -> "NP" with vacant=true

    `ideology_dim1` is always null: a two-member delegation has no single score,
    and we never average one into existence. Rows ride the standard StyleRow
    shape ({party, ideology_dim1, vacant}) — SPLIT travels in the existing
    `party` field, so the feed stays backward-compatible.

    `senate_rows`: current senate terms as {ocd_id (state division), party,
    is_vacant_marker}. Methodology-ready: this docstring is the canonical wording
    for the /methodology map-fills entry — if the rule changes here, that page
    must change with it.
    """
    by_state: dict[str, list[dict]] = {}
    for r in senate_rows:
        by_state.setdefault(r["ocd_id"], []).append(r)
    feed: dict[str, dict] = {}
    for ocd_id, rows in sorted(by_state.items()):
        seated = [r for r in rows if not r.get("is_vacant_marker")]
        parties = {r["party"] for r in seated}
        if len(seated) >= 2:
            party, vacant = (parties.pop(), False) if len(parties) == 1 else ("SPLIT", False)
        elif len(seated) == 1:
            party, vacant = seated[0]["party"], True
        else:
            party, vacant = "NP", True
        feed[ocd_id] = {"party": party, "ideology_dim1": None, "vacant": vacant}
    return feed

def publish(feeds: dict[str, dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for layer, feed in feeds.items():
        (out_dir / f"{layer}.json").write_text(json.dumps(feed, separators=(",", ":")))
