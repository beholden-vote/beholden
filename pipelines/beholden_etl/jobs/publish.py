"""Stage 4 — push serving artifacts (dist/data) to R2 (free-tier arch §1).

The CDN is the database: every file lands at the bucket root so the client reads
`https://data.beholden.vote/{stylefeeds,pins,dossiers}/…` directly. Tiles are
published separately (spike/publish_tiles.sh) and are immutable per vintage;
these JSON artifacts refresh daily, so they carry a short max-age.

Runs in dry-run automatically when R2 credentials are absent (local builds),
listing what *would* upload without needing the network.
"""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from ..config import PAGES_DIST, R2_BUCKET

# Daily-refreshed JSON: cache briefly at the edge; the client always sees today's.
CACHE_CONTROL = "public, max-age=300, s-maxage=300"
REQUIRED_ENV = ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")


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


def run(data_dir: str | Path = PAGES_DIST, dry_run: bool | None = None) -> int:
    data_dir = Path(data_dir)
    files = sorted(p for p in data_dir.rglob("*") if p.is_file())
    if dry_run is None:
        dry_run = not all(os.environ.get(k) for k in REQUIRED_ENV)

    if dry_run:
        total = sum(p.stat().st_size for p in files)
        for p in files:
            print(f"publish[dry-run] {p.relative_to(data_dir).as_posix():40} "
                  f"{p.stat().st_size:>8} B  {_content_type(p)}")
        print(f"publish[dry-run]: {len(files)} files, {total} B "
              f"(set {'/'.join(REQUIRED_ENV)} to upload to r2://{R2_BUCKET})")
        return len(files)

    client = _client()
    for p in files:
        key = p.relative_to(data_dir).as_posix()          # bucket-root keys
        client.put_object(
            Bucket=R2_BUCKET, Key=key, Body=p.read_bytes(),
            ContentType=_content_type(p), CacheControl=CACHE_CONTROL)
    print(f"publish: {len(files)} files -> r2://{R2_BUCKET}/")
    return len(files)


if __name__ == "__main__":
    run()
