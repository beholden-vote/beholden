#!/usr/bin/env python3
"""Report per-zoom tile-size stats from PMTiles archives (spike pass/fail)."""
import sys
from collections import defaultdict
from pmtiles.reader import Reader, MmapSource, all_tiles

LIMIT_KB = 500

for path in sys.argv[1:]:
    with open(path, "rb") as f:
        reader = Reader(MmapSource(f))
        stats = defaultdict(lambda: [0, 0, 0])  # z -> [count, total, max]
        for (z, x, y), data in all_tiles(reader.get_bytes):
            s = stats[z]
            s[0] += 1; s[1] += len(data); s[2] = max(s[2], len(data))
        print(f"\n{path}")
        print(f"{'z':>3} {'tiles':>7} {'avg KB':>8} {'max KB':>8}")
        worst = 0
        for z in sorted(stats):
            c, tot, mx = stats[z]
            worst = max(worst, mx)
            print(f"{z:>3} {c:>7} {tot/c/1024:>8.1f} {mx/1024:>8.1f}")
        verdict = "PASS" if worst <= LIMIT_KB * 1024 else "FAIL"
        print(f"largest tile: {worst/1024:.1f} KB -> {verdict} (limit {LIMIT_KB} KB)")
