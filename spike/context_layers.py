#!/usr/bin/env python3
"""Basemap context for orientation: US city points and interstate-class roads.

Reads Natural Earth 10m GeoJSONSeq on stdin (as emitted by ogr2ogr), keeps the
US features that help a reader get their bearings, strips properties down to the
minimum, and writes GeoJSONSeq for tippecanoe. Two modes:

  context_layers.py places   ne_10m_populated_places_simple -> {name, rank}
  context_layers.py roads    ne_10m_roads                    -> {} (geometry only)

Natural Earth is public domain. These layers are *context only* — deliberately
subordinate to the district layers (see web DESIGN.md: the map answers "where").
"""
from __future__ import annotations

import json
import sys


def _get(props: dict, *names: str):
    lower = {k.lower(): v for k, v in props.items()}
    for n in names:
        v = lower.get(n.lower())
        if v not in (None, ""):
            return v
    return None


def keep_place(p: dict) -> dict | None:
    """US cities, biggest first: scalerank 0 (megacity) .. 7 (regional city)."""
    adm0 = str(_get(p, "adm0name", "adm0_a3", "sov0name") or "")
    if "united states" not in adm0.lower() and adm0 != "USA":
        return None
    rank = _get(p, "scalerank")
    try:
        rank = int(rank)
    except (TypeError, ValueError):
        return None
    if rank > 7:
        return None
    name = _get(p, "name", "nameascii")
    if not name:
        return None
    return {"name": str(name), "rank": rank}


def keep_road(p: dict) -> dict | None:
    """US interstate-class roads: expressways / major highways only."""
    sov = str(_get(p, "sov_a3", "adm0_a3") or "")
    if sov != "USA":
        return None
    expressway = _get(p, "expressway")
    rtype = str(_get(p, "type") or "").lower()
    if expressway in (1, "1") or "major highway" in rtype:
        return {}
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("places", "roads"):
        sys.stderr.write(__doc__ or "")
        return 2
    keep = keep_place if argv[0] == "places" else keep_road
    written = 0
    for raw in sys.stdin:
        raw = raw.strip().lstrip("\x1e")
        if not raw:
            continue
        feat = json.loads(raw)
        props = keep(feat.get("properties") or {})
        if props is None:
            continue
        feat["properties"] = props
        sys.stdout.write(json.dumps(feat, separators=(",", ":")) + "\n")
        written += 1
    sys.stderr.write(f"context_layers: wrote {written} {argv[0]} features\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
