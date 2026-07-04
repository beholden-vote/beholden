#!/usr/bin/env python3
"""O6 spike: synthetic state-legislative geometry at realistic national density.

Real numbers this simulates:
  - SLDL (lower chambers): ~4,800 districts nationally
  - SLDU (upper chambers): ~1,900 districts
  - Cartographic-boundary (500k) polygons, simplified: ~100-250 vertices each

We generate a jittered hex grid over CONUS at those counts, with noisy edges to
mimic simplified real boundary complexity, stamped with OCD-ID properties exactly
per data-contracts §5. Output: newline-delimited GeoJSON for tippecanoe.

This intentionally OVERSTATES difficulty vs. real data in one way (uniform national
coverage; real SLDs are dense only in populated areas at high zoom) so a pass here
is a conservative pass.
"""
import json
import math
import random
import sys

random.seed(42)

# CONUS bounding box
LON_MIN, LON_MAX = -124.7, -66.9
LAT_MIN, LAT_MAX = 24.5, 49.4

VERTS_PER_EDGE = 20  # hexagon * 20 -> ~120 vertices/polygon (simplified-real density)


def hex_grid(n_target: int):
    """Yield (cx, cy, r) hex centers approximating n_target cells over CONUS."""
    area = (LON_MAX - LON_MIN) * (LAT_MAX - LAT_MIN)
    cell_area = area / n_target
    r = math.sqrt(cell_area / (1.5 * math.sqrt(3)))
    dx, dy = 1.5 * r, math.sqrt(3) * r
    row = 0
    y = LAT_MIN
    while y < LAT_MAX:
        offset = (dy / 2) if row % 2 else 0
        x = LON_MIN
        while x < LON_MAX:
            yield x, y + offset * 0 + (dy / 2 if row % 2 else 0) * 0 + (0), r  # centers
            x += dx * 2
        # interleave offset column
        x = LON_MIN + dx
        while x < LON_MAX:
            yield x, y + dy / 2, r
            x += dx * 2
        y += dy
        row += 1


def noisy_hexagon(cx, cy, r):
    """Hexagon with jittered, subdivided edges -> ~120 vertices."""
    corners = [(cx + r * math.cos(a), cy + r * math.sin(a))
               for a in (math.pi / 3 * i for i in range(6))]
    ring = []
    for i in range(6):
        x0, y0 = corners[i]
        x1, y1 = corners[(i + 1) % 6]
        for t in range(VERTS_PER_EDGE):
            f = t / VERTS_PER_EDGE
            jx = (random.random() - 0.5) * r * 0.15
            jy = (random.random() - 0.5) * r * 0.15
            ring.append([round(x0 + (x1 - x0) * f + jx, 6),
                         round(y0 + (y1 - y0) * f + jy, 6)])
    ring.append(ring[0])
    return [ring]


def emit_layer(path: str, count: int, chamber: str):
    states = ["al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il","in","ia","ks",
              "ky","la","me","md","ma","mi","mn","ms","mo","mt","ne","nv","nh","nj","nm","ny",
              "nc","nd","oh","ok","or","pa","ri","sc","sd","tn","tx","ut","vt","va","wa","wv","wi","wy"]
    written = 0
    with open(path, "w") as f:
        for cx, cy, r in hex_grid(count):
            if written >= count:
                break
            st = states[written % len(states)]
            dist = written // len(states) + 1
            feature = {
                "type": "Feature",
                "properties": {  # exactly the data-contracts §5 tile property set
                    "ocd_id": f"ocd-division/country:us/state:{st}/{chamber}:{dist}",
                    "state": st, "chamber": chamber, "district_num": dist,
                },
                "geometry": {"type": "Polygon", "coordinates": noisy_hexagon(cx, cy, r)},
            }
            f.write(json.dumps(feature, separators=(",", ":")) + "\n")
            written += 1
    print(f"{path}: {written} features (~{VERTS_PER_EDGE*6} verts each)")
    return written


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    emit_layer(f"{out}/synthetic_sldl.geojsonl", 4800, "sldl")
    emit_layer(f"{out}/synthetic_sldu.geojsonl", 1900, "sldu")
