"""State-sharded local pins (WO-22b, DATA-CONTRACTS §8.11).

`/pins/county/{st}.json` and `/pins/place/{st}.json`: exactly the rows of the
monolithic `/pins/{layer}.json` whose division is in that state, in the same order.
They are cut FROM the monolithic file the build just wrote, so a shard can never
disagree with it. A state with no rows has no file (a client treats 404 as empty).
The monolithic files keep publishing until WO-37's loader ships.
"""
from __future__ import annotations

import json

from .context import BuildContext

SHARDED_LAYERS = ("county", "place")


def _state(ocd_id: str) -> str:
    return ocd_id.split("state:")[1].split("/")[0]


def publish(ctx: BuildContext) -> dict[str, int]:
    written = 0
    for layer in SHARDED_LAYERS:
        rows = json.loads((ctx.out / "pins" / f"{layer}.json").read_text(encoding="utf-8"))
        by_state: dict[str, list[dict]] = {}
        for r in rows:
            by_state.setdefault(_state(r["ocd_id"]), []).append(r)
        d = ctx.out / "pins" / layer
        d.mkdir(parents=True, exist_ok=True)
        for st, shard in sorted(by_state.items()):
            (d / f"{st}.json").write_text(json.dumps(shard, separators=(",", ":")),
                                          encoding="utf-8")
            written += 1
    return {"pin_shards": written}
