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

from ..config import CONGRESS, RAW_DIST
from ..sources import congress_gov, legislators, voteview

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

    # --- current membership (congress.gov): party, state, district, photo ---
    client = congress_gov.CongressGovClient()
    members = list(client.current_members(CONGRESS))
    _write_json(raw / "congress.gov" / f"members-{CONGRESS}.json", members)
    manifest["sources"]["congress.gov"] = {
        "retrieved_at": _now(),
        "source_url": f"https://www.congress.gov/members?q=%7B%22congress%22%3A{CONGRESS}%7D",
        "count": len(members)}

    # --- ideology (Voteview DW-NOMINATE) ---
    csv_text = voteview.member_scores_csv(CONGRESS)
    (raw / "voteview").mkdir(parents=True, exist_ok=True)
    # Explicit UTF-8: bionames carry accents; platform-default cp1252 would corrupt.
    (raw / "voteview" / f"HS{CONGRESS}_members.csv").write_text(csv_text, encoding="utf-8")
    manifest["sources"]["voteview"] = {
        "retrieved_at": _now(), "source_url": VOTEVIEW_URL,
        "count": max(csv_text.count("\n") - 1, 0)}

    _write_json(raw / "manifest.json", manifest)
    for src, meta in manifest["sources"].items():
        print(f"fetch: {src:28} {meta['count']:>5} records")
    return manifest


if __name__ == "__main__":
    run()
