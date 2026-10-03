"""Coverage state per division (WO-22b, DATA-CONTRACTS §8.10), and the publish hints.

`/coverage/{st}.json`: one file per state with at least one roster locality attempted,
keyed by ocd_id. `covered` = the gate passed this run; `withheld` = it failed and the
last good roster is still served (`reason` says which gate); no last good at all = the
division is absent. `partial` is never emitted yet: neither source declares a vacant seat.

It also writes `publish_hints.json` BESIDE the serving tree (never inside it, so it is
not uploaded): the keys of withheld localities, which publish's stale rule treats as
live, and the one-time id migration map, so old seat-keyed ids are reported as id
changes rather than as officials who left.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ..sources import roster
from .context import BuildContext

HINTS_FILE = "publish_hints.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def publish(ctx: BuildContext) -> dict[str, int]:
    by_state: dict[str, dict] = {}
    counts = {"localities_covered": 0, "localities_partial": 0, "localities_withheld": 0}
    for spec in roster.specs():
        divisions = by_state.setdefault(spec.state, {})
        rows, reason = roster.load(spec, ctx.raw_dir, ctx.manifest)
        if rows is None:
            continue                    # never had a good roster: absent, not withheld
        state = "withheld" if reason else "covered"
        counts[f"localities_{state}"] += 1
        retrieved = (ctx.manifest.get("sources", {}).get(spec.source.source_key) or {}) \
            .get("retrieved_at")
        divisions[spec.ocd_id] = {
            "state": state, "seats_listed": len(rows), "seats_expected": spec.seats[1],
            "roster_as_of": retrieved[:10] if retrieved else None,
            "reason": reason, "source": spec.source.source_key, "votes": False}
    d = ctx.out / "coverage"
    d.mkdir(parents=True, exist_ok=True)
    for st, divisions in sorted(by_state.items()):
        doc = {"schema_version": "1.0", "state": st, "generated_at": _now(),
               "divisions": divisions}
        (d / f"{st}.json").write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")),
                                      encoding="utf-8")
    (ctx.out.parent / HINTS_FILE).write_text(
        json.dumps(roster.hints(ctx.raw_dir, ctx.manifest), indent=1), encoding="utf-8")
    return {**counts, "coverage_states": len(by_state)}
