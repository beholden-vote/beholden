"""Stage 4 — push serving artifacts (dist/data) + raw lake (dist/raw) to R2.

The CDN is the database: every serving file lands at the bucket root so the
client reads `https://data.beholden.vote/{stylefeeds,pins,dossiers}/…` directly.
Raw snapshots land under `raw/{date}/{source}/…` — immutable, so any published
fact stays reproducible from the lake (contracts §7). Tiles are published
separately (spike/publish_tiles.sh) and are immutable per vintage; serving JSON
refreshes daily, so it carries a short max-age.

Runs in dry-run automatically when R2 credentials are absent (local builds),
listing what *would* upload without needing the network.
"""
from __future__ import annotations

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


def _put_batch(client, batch: list[tuple[Path, str]], cache_control: str) -> None:
    """Upload one batch concurrently — every file is an independent PUT to its
    own key, so a thread pool is a direct win over one-at-a-time. Fail closed:
    the first exception (from any file, in completion order) propagates rather
    than being swallowed, same as the old serial loop's unguarded put_object."""
    if not batch:
        return

    def _put_one(p: Path, key: str) -> None:
        client.put_object(
            Bucket=R2_BUCKET, Key=key, Body=p.read_bytes(),
            ContentType=_content_type(p), CacheControl=cache_control)

    with ThreadPoolExecutor(max_workers=_UPLOAD_WORKERS) as pool:
        futures = [pool.submit(_put_one, p, key) for p, key in batch]
        for fut in as_completed(futures):
            fut.result()


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
        dry_run: bool | None = None) -> int:
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
    _put_batch(client, serving, CACHE_CONTROL)
    _put_batch(client, raw, RAW_CACHE_CONTROL)              # immutable lake partition
    # --- WO-10: write the last-good pointer AFTER the run's raw lake is uploaded.
    # A server-side copy of the just-uploaded raw/{date}/… objects to raw/latest/…
    # (overwritten each successful run) — the next fetch hydrates from it to
    # resume incrementally. Run last so the pointer only ever names a
    # fully-landed lake; a copy (not a re-upload) since R2 already has the bytes.
    _copy_batch_to_latest(client, raw, latest)
    print(f"publish: {len(serving)} serving + {len(raw)} raw "
          f"+ {len(latest)} latest-pointer (server-side copy) -> r2://{R2_BUCKET}/")
    return len(serving) + len(raw)


if __name__ == "__main__":
    run()
