"""Raw-lake hydration + freshness + last-good fallback for the incremental fetch (WO-10).

`publish` uploads `dist/raw` to R2 under `raw/{date}/…` and writes a
`raw/latest/…` last-good pointer (a mirror of the newest successful run). At the
start of a fetch, `hydrate()` pulls that pointer back into `dist/raw` so a run
resumes from the last good lake instead of re-crawling the ~2-hour serial fetch.

Each source then decides whether to re-fetch by comparing its **hydrated**
snapshot's `retrieved_at` (recorded in the prior manifest) against its
`config.SOURCES[key].freshness_sla_hours`. A snapshot still within its SLA is
kept verbatim — carrying its ORIGINAL `retrieved_at`, never restamped (honesty:
cached data is not freshly fetched). A stale or absent snapshot is re-fetched.

Everything degrades gracefully to a full fetch when R2 is unreachable or a
snapshot is absent — local runs and the test suite have no R2 credentials, so
hydration is a no-op there and every source simply fetches live.

Nothing here changes the network behavior of any source client; it only decides
*whether* a client is called and supplies a correct-but-stale fallback when a
live call fails and a prior snapshot exists.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .config import R2_BUCKET, RAW_DIST, SOURCES

# The last-good pointer publish writes after every successful run. Kept in lock-step
# with jobs/publish.py's LATEST_PREFIX — a mirror of the newest good raw lake.
LATEST_PREFIX = "raw/latest/"
REQUIRED_ENV = ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
MANIFEST_NAME = "manifest.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def r2_available() -> bool:
    """True only when every R2 credential is present. Absent creds (local runs,
    CI unit tests) => hydration is skipped and the fetch runs full/live."""
    return all(os.environ.get(k) for k in REQUIRED_ENV)


def _client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def hydrate(raw_dir: str | Path = RAW_DIST, *, client=None) -> int:
    """Populate `raw_dir` from R2 `raw/latest/…` (the last-good lake) so a fetch
    resumes instead of restarting. Returns the number of objects hydrated.

    Degrades to a no-op (returns 0) when R2 is unreachable, the pointer is
    absent/empty, or boto3 isn't installed — the caller then fetches everything
    live. Never raises on a missing lake: a from-scratch run must always be
    possible.
    """
    raw = Path(raw_dir)
    if client is None:
        if not r2_available():
            print("rawlake: no R2 credentials — skipping hydration (full fetch)")
            return 0
        try:
            client = _client()
        except Exception as e:  # boto3 missing / bad config: fall back to full fetch
            print(f"rawlake: R2 client unavailable ({type(e).__name__}) — full fetch")
            return 0

    raw.mkdir(parents=True, exist_ok=True)
    count = 0
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=R2_BUCKET, Prefix=LATEST_PREFIX):
            for obj in page.get("Contents") or []:
                key = obj["Key"]
                rel = key[len(LATEST_PREFIX):]
                if not rel:                          # the prefix "directory" itself
                    continue
                dest = raw / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                body = client.get_object(Bucket=R2_BUCKET, Key=key)["Body"].read()
                dest.write_bytes(body)
                count += 1
    except Exception as e:  # unreachable mid-hydrate: keep whatever landed, fetch the rest
        print(f"rawlake: hydration interrupted ({type(e).__name__}); "
              f"{count} objects landed — remaining sources fetch live")
        return count
    print(f"rawlake: hydrated {count} objects from r2://{R2_BUCKET}/{LATEST_PREFIX}")
    return count


def hydrated_manifest(raw_dir: str | Path = RAW_DIST) -> dict:
    """The prior run's manifest (from the hydrated lake), or {} when none exists.
    Its per-source `retrieved_at` is the age basis for the freshness check and the
    value a reused snapshot carries forward unchanged."""
    path = Path(raw_dir) / MANIFEST_NAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def prior_source(prior: dict, source_key: str) -> dict | None:
    """The prior manifest's entry for a source, or None. Accepts the manifest dict
    (from `hydrated_manifest`) so a caller reads it once and reuses it."""
    return (prior.get("sources") or {}).get(source_key)


def _retrieved_at(entry: dict | None) -> str | None:
    return (entry or {}).get("retrieved_at")


def age_hours(retrieved_at: str | None, *, now: datetime | None = None) -> float | None:
    """Hours since an ISO `retrieved_at`, or None when it is missing/unparseable
    (an unknown age is treated as stale by `is_fresh`)."""
    if not retrieved_at:
        return None
    try:
        ts = datetime.fromisoformat(retrieved_at)
    except ValueError:
        return None
    if ts.tzinfo is None:                             # tolerate a naive stamp
        ts = ts.replace(tzinfo=timezone.utc)
    delta = (now or _now()) - ts
    return delta.total_seconds() / 3600.0


def is_fresh(source_key: str, retrieved_at: str | None, *,
             now: datetime | None = None) -> bool:
    """True when a source's hydrated snapshot is younger than its declared
    `freshness_sla_hours` (config.SOURCES) — i.e. the re-fetch may be skipped.
    Unknown source, missing/unparseable timestamp, or no SLA => not fresh (fetch).
    """
    src = SOURCES.get(source_key)
    if src is None:
        return False
    age = age_hours(retrieved_at, now=now)
    if age is None:
        return False
    return age < src.freshness_sla_hours


def source_is_fresh(prior: dict, source_key: str, *,
                    now: datetime | None = None) -> bool:
    """Convenience: read a source's prior `retrieved_at` and decide freshness in
    one call, given an already-loaded prior manifest."""
    return is_fresh(source_key, _retrieved_at(prior_source(prior, source_key)), now=now)


def last_good(raw_dir: str | Path, rel_path: str | Path) -> dict | None:
    """Return a single hydrated JSON item (the last-good snapshot) for the given
    lake-relative path, or None when it is absent — the per-item fail-closed vs
    honest-absence decision is the caller's, not the lake's."""
    path = Path(raw_dir) / Path(rel_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def has_snapshot(raw_dir: str | Path, rel_path: str | Path) -> bool:
    """Whether a last-good snapshot file exists in the hydrated lake."""
    return (Path(raw_dir) / Path(rel_path)).exists()
