"""Stage 4 — push serving artifacts (dist/data) + raw lake (dist/raw) to R2.

The CDN is the database: every serving file lands at the bucket root so the
client reads `https://data.beholden.vote/{stylefeeds,pins,dossiers}/…` directly.
Raw snapshots land under `raw/{date}/{source}/…` — immutable, so any published
fact stays reproducible from the lake (contracts §7). Tiles are published
separately (spike/publish_tiles.sh) and are immutable per vintage; serving JSON
refreshes daily, so it carries a short max-age.

Serving files are written only when their bytes actually changed: R2's ETag is
the content MD5 for these (all single-part), so a HEAD decides it. Class-A
operations — PUT, COPY — are the scarce free-tier resource at 1M/month, and
re-writing ~16k identical objects nightly spends about half of that on nothing.
Reads are class-B with a 10M/month budget, so the check is effectively free.
Pass --force-all to write unconditionally.

Runs in dry-run automatically when R2 credentials are absent (local builds),
listing what *would* upload without needing the network.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from ..config import PAGES_DIST, R2_BUCKET, RAW_DIST

# Independent per-file PUTs (and, for the latest/ mirror, server-side copies) —
# a thread pool trades wall-clock for nothing but connection count, and R2/S3
# handles far more than this concurrently.
_UPLOAD_WORKERS = 16

# Daily-refreshed JSON: cache briefly at the edge; the client always sees today's.
CACHE_CONTROL = "public, max-age=300, s-maxage=300"
# Raw snapshots are write-once per run date: safe to cache forever.
RAW_CACHE_CONTROL = "public, max-age=31536000, immutable"
# WO-10 last-good pointer: a mirror of the newest good raw lake, overwritten each
# successful run. fetch hydrates dist/raw from here to resume incrementally, so it
# must NOT be cached — the fetcher always needs the current pointer.
LATEST_PREFIX = "raw/latest/"
LATEST_CACHE_CONTROL = "no-cache, max-age=0"
REQUIRED_ENV = ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")

# Public-record data read cross-origin by the SPA (beholden.vote -> data.beholden.vote,
# a different origin). The bucket must send Access-Control-Allow-Origin or the browser
# blocks every fetch — including the PMTiles Range requests, which preflight on `range`.
CORS_CONFIG = {
    "CORSRules": [{
        "AllowedOrigins": ["*"],                 # public data; also covers *.pages.dev previews
        "AllowedMethods": ["GET", "HEAD"],
        "AllowedHeaders": ["*"],                 # allow the Range preflight
        "ExposeHeaders": ["ETag", "Content-Length", "Content-Range", "Accept-Ranges"],
        "MaxAgeSeconds": 3600,
    }]
}


def _client():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def _content_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _ensure_cors(client) -> None:
    """Set the bucket CORS policy so the SPA can read cross-origin. Non-fatal:
    the Object-R/W R2 token used here cannot manage bucket config (PutBucketCors
    needs admin scope), so on AccessDenied we warn and continue — the policy is
    then a one-time dashboard step (Settings → CORS Policy)."""
    from botocore.exceptions import ClientError
    try:
        client.put_bucket_cors(Bucket=R2_BUCKET, CORSConfiguration=CORS_CONFIG)
        print("publish: bucket CORS ensured")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "?")
        print(f"publish: WARNING could not set bucket CORS ({code}); set it once in "
              "the R2 dashboard (Settings → CORS Policy). Object-R/W tokens can't "
              "manage bucket config.")


def _raw_batch(raw_dir: Path) -> list[tuple[Path, str]]:
    """(file, bucket_key) pairs landing the raw lake at raw/{date}/{source}/…
    (immutable, arch §3) — the date comes from the fetch manifest so the lake
    partition matches the snapshot, not the upload clock."""
    if not raw_dir.is_dir():
        return []
    manifest = raw_dir / "manifest.json"
    date = None
    if manifest.exists():
        date = (json.loads(manifest.read_text()).get("generated_at") or "")[:10]
    date = date or datetime.now(timezone.utc).date().isoformat()
    return [(p, f"raw/{date}/{p.relative_to(raw_dir).as_posix()}")
            for p in sorted(raw_dir.rglob("*")) if p.is_file()]


def _latest_batch(raw_dir: Path) -> list[tuple[Path, str]]:
    """(file, bucket_key) pairs mirroring the raw lake at raw/latest/… (WO-10) —
    the last-good pointer the next fetch hydrates from. Same files as _raw_batch,
    keyed under the stable latest/ prefix instead of the dated partition."""
    if not raw_dir.is_dir():
        return []
    return [(p, f"{LATEST_PREFIX}{p.relative_to(raw_dir).as_posix()}")
            for p in sorted(raw_dir.rglob("*")) if p.is_file()]


def _already_stored(client, key: str, body: bytes) -> bool:
    """True when R2 already holds exactly these bytes under this key.

    R2 returns the content MD5 as the ETag for single-part uploads, which every
    serving artifact is — the largest is orders of magnitude under the multipart
    threshold.

    Fails OPEN, deliberately: any error — object missing, permission, network,
    a malformed ETag — returns False and the file uploads. The asymmetry is the
    point. Skipping a file that actually changed publishes stale data, which is
    a data-honesty failure; uploading a file that did not change costs one
    class-A operation. Never trade the first to save the second.
    """
    from botocore.exceptions import ClientError
    try:
        etag = client.head_object(Bucket=R2_BUCKET, Key=key)["ETag"].strip('"')
    except ClientError:
        return False                        # absent, or we cannot tell -> upload
    # A multipart ETag is '{md5-of-part-digests}-{partcount}' — not a digest of
    # the content, so it must never be read as one. Belt-and-braces: the equality
    # below already cannot match a suffixed ETag. It is here so that anyone who
    # later "fixes" the comparison to be laxer has to delete this line first.
    if "-" in etag:
        return False
    return etag == hashlib.md5(body, usedforsecurity=False).hexdigest()


def _put_batch(client, batch: list[tuple[Path, str]], cache_control: str,
               *, skip_unchanged: bool = False) -> int:
    """Upload one batch concurrently — every file is an independent PUT to its
    own key, so a thread pool is a direct win over one-at-a-time. Fail closed:
    the first exception (from any file, in completion order) propagates rather
    than being swallowed, same as the old serial loop's unguarded put_object.

    With skip_unchanged, a HEAD (class-B, effectively free against a 10M/mo
    budget) replaces the PUT (class-A, 1M/mo) whenever the stored bytes already
    match. The nightly re-publishes ~16k serving files of which almost none
    change on a given day, so this is the difference between spending roughly
    half the class-A budget every month and spending a rounding error.

    Returns the number of objects actually uploaded.
    """
    if not batch:
        return 0

    def _put_one(p: Path, key: str) -> bool:
        body = p.read_bytes()
        if skip_unchanged and _already_stored(client, key, body):
            return False
        client.put_object(
            Bucket=R2_BUCKET, Key=key, Body=body,
            ContentType=_content_type(p), CacheControl=cache_control)
        return True

    with ThreadPoolExecutor(max_workers=_UPLOAD_WORKERS) as pool:
        futures = [pool.submit(_put_one, p, key) for p, key in batch]
        # sum() consumes the futures in completion order and still raises on the
        # first failure, so the fail-closed contract above is unchanged.
        return sum(fut.result() for fut in as_completed(futures))


def _copy_batch_to_latest(client, raw_batch: list[tuple[Path, str]],
                           latest_batch: list[tuple[Path, str]]) -> None:
    """WO-10 last-good pointer: mirror the just-uploaded raw/{date}/… objects to
    raw/latest/… via a server-side R2 CopyObject instead of re-uploading the same
    bytes from the runner a second time (raw_batch and latest_batch are built by
    walking dist/raw in the same sorted order, so they line up 1:1 by position).
    MetadataDirective='REPLACE' is required: without it CopyObject inherits the
    SOURCE object's immutable, 1-year CacheControl, which would leave the
    incrementally-hydrated pointer cached instead of always-fresh."""
    if not raw_batch:
        return

    def _copy_one(p: Path, raw_key: str, latest_key: str) -> None:
        client.copy_object(
            Bucket=R2_BUCKET, CopySource={"Bucket": R2_BUCKET, "Key": raw_key},
            Key=latest_key, ContentType=_content_type(p),
            CacheControl=LATEST_CACHE_CONTROL, MetadataDirective="REPLACE")

    with ThreadPoolExecutor(max_workers=_UPLOAD_WORKERS) as pool:
        futures = [pool.submit(_copy_one, p, raw_key, latest_key)
                   for (p, raw_key), (_, latest_key) in zip(raw_batch, latest_batch)]
        for fut in as_completed(futures):
            fut.result()


def run(data_dir: str | Path = PAGES_DIST, raw_dir: str | Path = RAW_DIST,
        dry_run: bool | None = None, force_all: bool = False) -> int:
    data_dir = Path(data_dir)
    serving = [(p, p.relative_to(data_dir).as_posix())              # bucket-root keys
               for p in sorted(data_dir.rglob("*")) if p.is_file()]
    raw = _raw_batch(Path(raw_dir))
    if dry_run is None:
        dry_run = not all(os.environ.get(k) for k in REQUIRED_ENV)

    latest = _latest_batch(Path(raw_dir))                  # WO-10 last-good pointer
    if dry_run:
        total = 0
        for p, key in serving + raw:
            total += p.stat().st_size
            print(f"publish[dry-run] {key:52} {p.stat().st_size:>8} B  {_content_type(p)}")
        for _, key in latest:
            print(f"publish[dry-run] {key:52} (server-side copy, no re-upload)")
        print(f"publish[dry-run]: {len(serving)} serving + {len(raw)} raw "
              f"+ {len(latest)} latest-pointer (server-side copy) files, {total} B "
              f"(set {'/'.join(REQUIRED_ENV)} to upload to r2://{R2_BUCKET})")
        return len(serving) + len(raw)

    client = _client()
    _ensure_cors(client)
    # Serving artifacts are rewritten identically most nights, so they are the
    # one batch worth checking before writing. The raw lake is not: its keys are
    # date-partitioned, so every object is a new key and a HEAD would only ever
    # 404. --force-all restores the unconditional write for a full rebuild, when
    # the point is to overwrite whatever is there regardless of what it says.
    sent = _put_batch(client, serving, CACHE_CONTROL, skip_unchanged=not force_all)
    _put_batch(client, raw, RAW_CACHE_CONTROL)              # immutable lake partition
    # --- WO-10: write the last-good pointer AFTER the run's raw lake is uploaded.
    # A server-side copy of the just-uploaded raw/{date}/… objects to raw/latest/…
    # (overwritten each successful run) — the next fetch hydrates from it to
    # resume incrementally. Run last so the pointer only ever names a
    # fully-landed lake; a copy (not a re-upload) since R2 already has the bytes.
    _copy_batch_to_latest(client, raw, latest)
    print(f"publish: {sent}/{len(serving)} serving "
          f"({len(serving) - sent} unchanged, skipped) + {len(raw)} raw "
          f"+ {len(latest)} latest-pointer (server-side copy) -> r2://{R2_BUCKET}/")
    return len(serving) + len(raw)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force-all", action="store_true",
                    help="re-upload every serving file even when R2 already "
                         "holds identical bytes (use with a full rebuild)")
    run(force_all=ap.parse_args().force_all)
