"""WO-41 — retention for the dated raw lake (`raw/{YYYY-MM-DD}/…`).

Since WO-41 publish uploads a raw file to `raw/{date}/` only when its bytes differ
from `raw/latest/`, so a dated night holds only what changed that night. Night D's
lake is, for each path, the newest dated copy with date <= D. This pass keeps:

  * the last KEEP_NIGHTS nights present, plus the last night of every month;
  * for every path, the copy each kept night resolves to (the newest one at or
    before it) — so a kept night stays fully reproducible, whether it was written
    whole (before WO-41) or as a delta. The newest copy of every path is always
    kept, because the newest night always is.

Everything else under `raw/{date}/` is deletable. Guards, all fail-closed:

  * never `raw/latest/` (the hydration source), `tiles/`, `fonts/` — re-checked
    at the point of deletion, and only keys matching `raw/YYYY-MM-DD/…` qualify;
  * refuse when `raw/latest/manifest.json` is missing, or `raw/latest/` holds
    fewer files than the lake this run just published (`expected_latest`);
  * refuse on any key under `raw/` that is neither `raw/latest/` nor a dated
    night — an unrecognised layout is doubt, and doubt deletes nothing;
  * at most DELETE_CAP objects a run, oldest first; the log says when capped;
  * every dated prefix with deletable objects is printed with its count and
    bytes, whether or not this run deletes.

Deletion happens only with `delete=True` (publish --raw-retention-delete). The
nightly runs without it: the listing is printed and nothing is removed.
"""
from __future__ import annotations

import re
from bisect import bisect_right
from collections import defaultdict
from datetime import date

from ..config import R2_BUCKET

RAW_PREFIX = "raw/"
LATEST_PREFIX = "raw/latest/"
LATEST_MANIFEST = LATEST_PREFIX + "manifest.json"
DATED = re.compile(r"raw/(\d{4}-\d{2}-\d{2})/(.+)")
# Hard refusal, whatever the plan says. Only DATED keys are ever deletable; this
# list is the second lock on the same door.
NEVER_DELETE = ("raw/latest/", "tiles/", "fonts/")
KEEP_NIGHTS = 14
DELETE_CAP = 50_000


def _night(key: str) -> tuple[str, str] | None:
    """(date, path) for a dated-partition key, else None."""
    m = DATED.fullmatch(key)
    if not m:
        return None
    try:
        date.fromisoformat(m.group(1))
    except ValueError:
        return None
    return m.group(1), m.group(2)


def plan(client, expected_latest: int, *, keep_nights: int = KEEP_NIGHTS) -> dict:
    """List `raw/` (read-only) and decide what retention would delete.

    Returns a dict: lists (LIST pages, class-A), latest/dated sizes, per-source
    totals, kept nights, refusals, and `doomed` — (date, key, size), oldest first.
    A listing error propagates: no listing, no plan, no delete.
    """
    lists, latest_n, latest_b = 0, 0, 0
    has_manifest = False
    copies: dict[str, dict[str, tuple[str, int]]] = defaultdict(dict)  # path -> date -> (key, size)
    unexpected: list[str] = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=R2_BUCKET,
                                                                  Prefix=RAW_PREFIX):
        lists += 1
        for obj in page.get("Contents") or []:
            key, size = obj["Key"], obj.get("Size", 0)
            if key.startswith(LATEST_PREFIX):
                latest_n += 1
                latest_b += size
                has_manifest = has_manifest or key == LATEST_MANIFEST
            elif (hit := _night(key)) is not None:
                copies[hit[1]][hit[0]] = (key, size)
            else:
                unexpected.append(key)

    refusals = []
    if not has_manifest:
        refusals.append(f"{LATEST_MANIFEST} is missing")
    if latest_n < expected_latest:
        refusals.append(f"{LATEST_PREFIX} holds {latest_n} objects, fewer than the "
                        f"{expected_latest} files this run published")
    if unexpected:
        refusals.append(f"{len(unexpected)} key(s) under {RAW_PREFIX} are neither "
                        f"{LATEST_PREFIX} nor a dated night: {unexpected[:5]}")

    nights = sorted({d for by_date in copies.values() for d in by_date})
    month_ends = {}
    for d in nights:
        month_ends[d[:7]] = d                         # sorted: the last one wins
    kept = sorted(set(nights[max(0, len(nights) - keep_nights):]) | set(month_ends.values()))

    doomed, by_source = [], defaultdict(lambda: [0, 0])
    for path, by_date in copies.items():
        dates = sorted(by_date)
        keep = {dates[i - 1] for k in kept if (i := bisect_right(dates, k))}
        src = by_source[path.split("/", 1)[0]]
        for d in dates:
            key, size = by_date[d]
            src[0] += 1
            src[1] += size
            if d not in keep:
                doomed.append((d, key, size))
    doomed.sort()
    return {"lists": lists, "latest": (latest_n, latest_b),
            "dated": (sum(map(len, copies.values())),
                      sum(s for b in copies.values() for _, s in b.values())),
            "nights": nights, "kept": kept, "by_source": dict(by_source),
            "refusals": refusals, "doomed": doomed}


def _mib(b: int) -> str:
    return f"{b / 2**20:.1f} MiB"


def _delete(client, keys: list[str]) -> None:
    """Delete dated-partition keys only. Any other key — raw/latest/, tiles/,
    fonts/, anything not raw/YYYY-MM-DD/… — refuses the whole batch."""
    bad = [k for k in keys if k.startswith(NEVER_DELETE) or _night(k) is None]
    if bad:
        raise RuntimeError(f"retention: refusing to delete outside raw/YYYY-MM-DD/: {bad[:5]}")
    for i in range(0, len(keys), 1000):                    # DeleteObjects cap
        resp = client.delete_objects(
            Bucket=R2_BUCKET,
            Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]], "Quiet": True})
        if resp.get("Errors"):
            raise RuntimeError(f"retention: delete failed: {resp['Errors'][:5]}")


def settle(client, p: dict, *, delete: bool, cap: int = DELETE_CAP,
           tag: str = "retention") -> int:
    """Print the measurement and the deletion listing; delete only when asked.
    A refusal raises on a deleting run and is reported (as a warning) otherwise.
    Returns the number of objects deleted."""
    (ln, lb), (dn, db) = p["latest"], p["dated"]
    print(f"{tag}: raw/latest/ {ln} objects ({_mib(lb)}); raw/{{date}}/ {dn} objects "
          f"({_mib(db)}) over {len(p['nights'])} nights; {p['lists']} LIST (class-A)")
    for src, (n, b) in sorted(p["by_source"].items()):
        print(f"{tag}:   {src}: {n} dated objects ({_mib(b)})")
    print(f"{tag}: keeping {len(p['kept'])} nights: {', '.join(p['kept'])}")
    if p["refusals"]:
        for msg in p["refusals"]:
            print(f"::warning::{tag}: REFUSED — {msg}. Nothing is deleted.")
        if delete:
            raise RuntimeError(f"{tag}: refused — " + "; ".join(p["refusals"]))
        return 0

    doomed = p["doomed"]
    act = doomed[:cap]
    verb = "deleting" if delete else "would delete (dry-run)"
    per_night: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for d, _, size in act:
        per_night[d][0] += 1
        per_night[d][1] += size
    for d, (n, b) in sorted(per_night.items()):
        print(f"{tag}: {verb} raw/{d}/: {n} objects ({_mib(b)})")
    if len(doomed) > cap:
        print(f"{tag}: capped at {cap} of {len(doomed)} deletable objects this run "
              "(oldest first); the rest wait for later runs")
    size = _mib(sum(s for *_, s in act))
    if not delete:
        print(f"{tag}: {len(act)} objects ({size}) would be deleted; nothing deleted "
              "(dry-run: enable --raw-retention-delete to act)")
        return 0
    _delete(client, [k for _, k, _ in act])
    print(f"{tag}: deleted {len(act)} objects ({size})")
    return len(act)
