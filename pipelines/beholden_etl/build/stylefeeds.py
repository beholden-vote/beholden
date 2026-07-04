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

def publish(feeds: dict[str, dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for layer, feed in feeds.items():
        (out_dir / f"{layer}.json").write_text(json.dumps(feed, separators=(",", ":")))
