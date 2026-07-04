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
from datetime import datetime, timezone
from pathlib import Path

from ..config import PAGES_DIST, R2_BUCKET, RAW_DIST

# Daily-refreshed JSON: cache briefly at the edge; the client always sees today's.
CACHE_CONTROL = "public, max-age=300, s-maxage=300"
# Raw snapshots are write-once per run date: safe to cache forever.
RAW_CACHE_CONTROL = "public, max-age=31536000, immutable"
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


def run(data_dir: str | Path = PAGES_DIST, raw_dir: str | Path = RAW_DIST,
        dry_run: bool | None = None) -> int:
    data_dir = Path(data_dir)
    serving = [(p, p.relative_to(data_dir).as_posix())              # bucket-root keys
               for p in sorted(data_dir.rglob("*")) if p.is_file()]
    raw = _raw_batch(Path(raw_dir))
    if dry_run is None:
        dry_run = not all(os.environ.get(k) for k in REQUIRED_ENV)

    if dry_run:
        total = 0
        for p, key in serving + raw:
            total += p.stat().st_size
            print(f"publish[dry-run] {key:52} {p.stat().st_size:>8} B  {_content_type(p)}")
        print(f"publish[dry-run]: {len(serving)} serving + {len(raw)} raw files, {total} B "
              f"(set {'/'.join(REQUIRED_ENV)} to upload to r2://{R2_BUCKET})")
        return len(serving) + len(raw)

    client = _client()
    _ensure_cors(client)
    for p, key in serving:
        client.put_object(
            Bucket=R2_BUCKET, Key=key, Body=p.read_bytes(),
            ContentType=_content_type(p), CacheControl=CACHE_CONTROL)
    for p, key in raw:                                    # immutable lake partition
        client.put_object(
            Bucket=R2_BUCKET, Key=key, Body=p.read_bytes(),
            ContentType=_content_type(p), CacheControl=RAW_CACHE_CONTROL)
    print(f"publish: {len(serving)} serving + {len(raw)} raw -> r2://{R2_BUCKET}/")
    return len(serving) + len(raw)


if __name__ == "__main__":
    run()
