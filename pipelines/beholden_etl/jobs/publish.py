"""Stage 4 — push serving artifacts (dist/data) + raw lake (dist/raw) to R2.

The CDN is the database: every serving file lands at the bucket root so the
client reads `https://data.beholden.vote/{stylefeeds,pins,dossiers}/…` directly.
Raw snapshots land under `raw/{date}/{source}/…` — immutable, so any published
fact stays reproducible from the lake (contracts §7). Tiles are published
separately (spike/publish_tiles.sh) and are immutable per vintage; serving JSON
refreshes daily, so it carries a short max-age.

A served object is rewritten only when its content, EXCLUDING STAMPS, changed
(DATA-CONTRACTS §8.1). Build stamps every document fresh on every run — a
`generated_at`, and a `pipeline_version` in every provenance envelope — so no
document is ever byte-identical to last night's. Comparing bytes (the first
attempt: R2's ETag against the local MD5) was correct and skipped 7 objects of
15,883. Publish instead digests each document with exactly the §8.1 stamps
removed, stores that digest as object metadata on upload, and skips the write
when a HEAD returns the same digest. An object that is not rewritten keeps the
stamps it had when it last changed, which is what §8.1 says a stamp means.

Class-A operations — PUT, COPY, LIST — are the scarce free-tier resource at
1M/month. Reads are class-B with a 10M/month budget, so the HEAD is effectively
free. Pass --force-all to write unconditionally.

After the uploads, objects under a managed prefix that this build did not
produce are deleted — an official who left office must stop being served as an
incumbent — behind a tripwire that refuses a mass delete.

Runs in dry-run automatically when R2 credentials are absent (local builds),
listing what *would* upload without needing the network. With credentials,
--dry-run also reports what would be skipped and deleted, and writes nothing.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from ..config import PAGES_DIST, R2_BUCKET, RAW_DIST

# Independent per-file requests — a thread pool trades wall-clock for nothing
# but connection count, and R2/S3 handles far more than this concurrently.
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

# ── What "unchanged" means (DATA-CONTRACTS §8.1) ─────────────────────────────
# Object-metadata key holding the stamp-insensitive digest of the stored body.
STABLE_META = "stable-sha256"
# THE STAMP LIST IS CLOSED. A field left out of the digest is a field whose
# changes are never published: right for a stamp, silent staleness for a fact.
# So nothing here is matched by name alone. These two keys are stamps ONLY
# inside a dict stored under the key "provenance"; a `retrieved_at` anywhere
# else (coverage.json's per-source rows are the reader's "last checked") is a
# fact and stays in. `generated_at` and a graph document's `as_of` are handled
# in stable_digest, at the top level only. Adding a stamp is a contract change
# to §8.1, never a refactor here.
_ENVELOPE_STAMPS = frozenset({"pipeline_version", "retrieved_at"})

# ── Stale objects ────────────────────────────────────────────────────────────
# Prefixes publish never deletes from, whatever the local tree looks like. The
# managed set is derived from what this build wrote; this refusal is hard-coded
# on top of that so an artifact that one day writes dist/data/tiles/… cannot
# widen it. raw/ is the reproducibility record; tiles/ and fonts/ are published
# by other tools and are never present in a build's output.
NEVER_DELETE = ("raw/", "tiles/", "fonts/")
# A bug in build must not be able to empty the bucket: more stale keys under one
# prefix than max(STALE_FLOOR, STALE_FRACTION of that prefix) raises instead.
STALE_FLOOR = 25
STALE_FRACTION = 0.02

# ── Write budget ─────────────────────────────────────────────────────────────
CLASS_A_FREE_PER_MONTH = 1_000_000
CLASS_A_WARN_PER_MONTH = 700_000
# One run writing more than this is a bug, not a release (the whole bucket is
# ~20k objects). Checked BEFORE the first write.
BULK_WRITE_LIMIT = 200_000

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


def _strip_envelope_stamps(node):
    """`node` with the two per-run keys removed from every provenance envelope.
    An envelope is recognised STRUCTURALLY — a dict stored under the key
    "provenance", at any depth — never by finding the key names somewhere."""
    if isinstance(node, list):
        return [_strip_envelope_stamps(v) for v in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        v = _strip_envelope_stamps(v)
        if k == "provenance" and isinstance(v, dict):
            v = {kk: vv for kk, vv in v.items() if kk not in _ENVELOPE_STAMPS}
        out[k] = v
    return out


def stable_digest(key: str, body: bytes) -> str | None:
    """SHA-256 of what the object SAYS, ignoring when it was stamped (§8.1).

    For a `.json` key: parse, remove exactly the §8.1 stamps, serialise
    canonically, hash. Exactly these and nothing else:
      - `generated_at` at the top level of the document;
      - `pipeline_version` and `retrieved_at` inside a provenance envelope;
      - `as_of` at the top level, for keys under graph/ only.
    Every other field is in the digest, including dates that look like stamps
    and are facts: a finance total's `as_of`, coverage.json's `retrieved_at`
    rows, a `generated_at` nested anywhere below the top level.

    Any other key: SHA-256 of the raw bytes.

    Returns None for a `.json` body that does not parse. None never matches a
    stored digest, so such an object always uploads — publish cannot vouch for
    what it cannot read.
    """
    if not key.endswith(".json"):
        return hashlib.sha256(body).hexdigest()
    try:
        doc = json.loads(body)
    except ValueError:                      # JSONDecodeError and UnicodeDecodeError
        return None
    doc = _strip_envelope_stamps(doc)
    if isinstance(doc, dict):
        doc.pop("generated_at", None)
        if key.startswith("graph/"):
            doc.pop("as_of", None)
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _pool(fn, items: list) -> list:
    """fn(*item) for every item, concurrently; results in input order. Fail
    closed: the first exception propagates rather than being swallowed."""
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=_UPLOAD_WORKERS) as pool:
        return list(pool.map(lambda item: fn(*item), items))


def _already_stored(client, key: str, path: Path) -> bool:
    """True only when R2 positively vouches that the object under `key` says
    what the local file says: the digest stored with it equals the local one.

    Fails OPEN, deliberately: an absent object, a HEAD that errors for any
    reason, an object uploaded before digests existed (no metadata), a local
    body that does not parse — all return False and the file uploads. The
    asymmetry is the point. Skipping a file that actually changed publishes
    stale data, which is a data-honesty failure; uploading a file that did not
    change costs one class-A operation. Never trade the first to save the second.
    """
    from botocore.exceptions import BotoCoreError, ClientError
    digest = stable_digest(key, path.read_bytes())
    if digest is None:
        return False
    try:
        meta = client.head_object(Bucket=R2_BUCKET, Key=key).get("Metadata") or {}
    except (BotoCoreError, ClientError):
        return False                        # absent, or we cannot tell -> upload
    return meta.get(STABLE_META) == digest


def _same_bytes(client, key: str, path: Path) -> bool:
    """True when R2 already holds exactly these bytes under `key` — for the raw
    mirror, where there are no stamps to look past. R2 returns the content MD5
    as the ETag of a single-part upload, which every raw file is (put_object
    never splits, and a server-side copy of a single-part object keeps its ETag).
    Fails open like _already_stored."""
    from botocore.exceptions import BotoCoreError, ClientError
    try:
        etag = client.head_object(Bucket=R2_BUCKET, Key=key)["ETag"].strip('"')
    except (BotoCoreError, ClientError, KeyError):
        return False
    # A multipart ETag is '{md5-of-part-digests}-{partcount}' — not a digest of
    # the content, so it must never be read as one. Belt-and-braces: the equality
    # below already cannot match a suffixed ETag. It is here so that anyone who
    # later "fixes" the comparison to be laxer has to delete this line first.
    if "-" in etag:
        return False
    return etag == hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def _put_batch(client, batch: list[tuple[Path, str]], cache_control: str,
               *, with_digest: bool = False) -> int:
    """Upload one batch concurrently — every file is an independent PUT to its
    own key. Fail closed: the first exception propagates.

    with_digest stores the stable digest of the bytes actually sent as object
    metadata, in the same PUT, so the digest R2 hands back on a later HEAD can
    only ever describe the body it sits beside. Returns the number uploaded.
    """
    def _put_one(p: Path, key: str) -> None:
        body = p.read_bytes()
        digest = stable_digest(key, body) if with_digest else None
        client.put_object(
            Bucket=R2_BUCKET, Key=key, Body=body,
            ContentType=_content_type(p), CacheControl=cache_control,
            Metadata={STABLE_META: digest} if digest else {})

    _pool(_put_one, batch)
    return len(batch)


def _copy_batch_to_latest(client, mirror: list[tuple[Path, str, str]]) -> int:
    """WO-10 last-good pointer: mirror raw/{date}/… objects to raw/latest/… via a
    server-side R2 CopyObject instead of re-uploading the same bytes from the
    runner a second time. `mirror` is (file, raw_key, latest_key).
    MetadataDirective='REPLACE' is required: without it CopyObject inherits the
    SOURCE object's immutable, 1-year CacheControl, which would leave the
    incrementally-hydrated pointer cached instead of always-fresh."""
    def _copy_one(p: Path, raw_key: str, latest_key: str) -> None:
        client.copy_object(
            Bucket=R2_BUCKET, CopySource={"Bucket": R2_BUCKET, "Key": raw_key},
            Key=latest_key, ContentType=_content_type(p),
            CacheControl=LATEST_CACHE_CONTROL, MetadataDirective="REPLACE")

    _pool(_copy_one, mirror)
    return len(mirror)


def _managed_prefixes(serving_keys: set[str]) -> list[str]:
    """The top-level directories this build wrote into (`dossiers/`, `graph/`,
    `pins/`, …) — the only places a stale object is ever looked for. Derived
    from the files actually produced, so a directory the build left empty
    manages nothing. Root-level objects (coverage.json, robots.txt) are outside
    every prefix and are never candidates."""
    return sorted({k.split("/", 1)[0] + "/" for k in serving_keys if "/" in k}
                  - set(NEVER_DELETE))


def _find_stale(client, serving_keys: set[str]) -> tuple[dict[str, list[str]], list[str], int]:
    """List the bucket under each managed prefix and return
    ({prefix: stale keys}, tripwire messages, LIST calls made).

    A key is stale when it sits under a managed prefix and the current build
    did not produce it. Each page of a listing is one class-A operation.
    """
    stale: dict[str, list[str]] = {}
    tripped: list[str] = []
    lists = 0
    paginator = client.get_paginator("list_objects_v2")
    for prefix in _managed_prefixes(serving_keys):
        remote: list[str] = []
        for page in paginator.paginate(Bucket=R2_BUCKET, Prefix=prefix):
            lists += 1
            remote += [obj["Key"] for obj in page.get("Contents") or []]
        gone = sorted(k for k in remote if k not in serving_keys)
        if not gone:
            continue
        stale[prefix] = gone
        limit = max(STALE_FLOOR, STALE_FRACTION * len(remote))
        if len(gone) > limit:
            tripped.append(f"{prefix}: {len(gone)} of {len(remote)} objects are not in "
                           f"this build (tripwire {limit:g})")
    return stale, tripped, lists


def _delete(client, keys: list[str]) -> None:
    """Delete `keys`. Refuses outright if any key is under a NEVER_DELETE prefix
    — checked again here, at the point of no return, rather than trusted from
    the caller. A partial failure raises (fail closed)."""
    forbidden = [k for k in keys if k.startswith(NEVER_DELETE)]
    if forbidden:
        raise RuntimeError(f"publish: refusing to delete under {NEVER_DELETE}: {forbidden[:5]}")
    for i in range(0, len(keys), 1000):                    # DeleteObjects cap
        resp = client.delete_objects(
            Bucket=R2_BUCKET,
            Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]], "Quiet": True})
        if resp.get("Errors"):
            raise RuntimeError(f"publish: stale delete failed: {resp['Errors'][:5]}")


def _budget_line(class_a: int, tag: str = "publish") -> None:
    monthly = class_a * 30
    print(f"{tag}: class-A this run = {class_a} "
          f"(≈ {monthly} per month of {CLASS_A_FREE_PER_MONTH:,} free)")
    if monthly > CLASS_A_WARN_PER_MONTH:
        print(f"::warning::publish wrote {class_a} class-A operations this run — "
              f"about {monthly:,} a month against {CLASS_A_FREE_PER_MONTH:,} free")


def run(data_dir: str | Path = PAGES_DIST, raw_dir: str | Path = RAW_DIST,
        dry_run: bool | None = None, force_all: bool = False,
        allow_mass_delete: bool = False, allow_bulk_writes: bool = False) -> int:
    data_dir = Path(data_dir)
    serving = [(p, p.relative_to(data_dir).as_posix())              # bucket-root keys
               for p in sorted(data_dir.rglob("*")) if p.is_file()]
    raw = _raw_batch(Path(raw_dir))
    # WO-10 last-good pointer. raw and latest are built by walking dist/raw in
    # the same sorted order, so they line up 1:1 by position.
    mirror = [(p, raw_key, latest_key)
              for (p, raw_key), (_, latest_key) in zip(raw, _latest_batch(Path(raw_dir)))]
    online = all(os.environ.get(k) for k in REQUIRED_ENV)
    if dry_run is None:
        dry_run = not online

    if dry_run and not online:
        total = 0
        for p, key in serving + raw:
            total += p.stat().st_size
            print(f"publish[dry-run] {key:52} {p.stat().st_size:>8} B  {_content_type(p)}")
        for _, _, key in mirror:
            print(f"publish[dry-run] {key:52} (server-side copy, no re-upload)")
        print(f"publish[dry-run]: {len(serving)} serving + {len(raw)} raw "
              f"+ {len(mirror)} latest-pointer (server-side copy) files, {total} B "
              f"(set {'/'.join(REQUIRED_ENV)} to upload to r2://{R2_BUCKET}; "
              "what would be skipped or deleted is only knowable with them)")
        return len(serving) + len(raw)

    client = _client()
    # ── Plan: reads only. Decide every write before making the first one. ──
    # Serving artifacts are compared on their stable digest; the raw mirror on
    # its bytes. The dated raw partition is not compared at all: its keys are
    # date-partitioned, so every object is a new key and a HEAD would only ever
    # 404. --force-all skips the comparison — the point of a full rebuild is to
    # replace whatever is in the bucket regardless of what the bucket says.
    if force_all:
        to_put, to_copy = serving, mirror
    else:
        same = _pool(lambda p, key: _already_stored(client, key, p), serving)
        to_put = [item for item, hit in zip(serving, same) if not hit]
        same = _pool(lambda p, _raw_key, latest_key: _same_bytes(client, latest_key, p), mirror)
        to_copy = [item for item, hit in zip(mirror, same) if not hit]
    writes = len(to_put) + len(raw) + len(to_copy)
    if writes > BULK_WRITE_LIMIT and not (force_all or allow_bulk_writes):
        raise RuntimeError(
            f"publish: this run would make {writes} writes ({len(to_put)} serving + "
            f"{len(raw)} raw + {len(to_copy)} latest-pointer), over the "
            f"{BULK_WRITE_LIMIT} single-run limit. Nothing was written. If this is "
            "intended, pass --allow-bulk-writes.")
    serving_keys = {key for _, key in serving}
    skipped = len(serving) - len(to_put)

    if dry_run:
        stale, tripped, lists = _find_stale(client, serving_keys)
        for _, key in to_put:
            print(f"publish[dry-run] would upload {key}")
        for key in (k for keys in stale.values() for k in keys):
            print(f"publish[dry-run] would delete {key}")
        for msg in tripped:
            print(f"publish[dry-run] TRIPWIRE {msg} — a real run raises and deletes "
                  "nothing without --allow-mass-delete")
        print(f"publish[dry-run]: {len(to_put)}/{len(serving)} serving ({skipped} unchanged, "
              f"skipped) + {len(raw)} raw + {len(to_copy)}/{len(mirror)} latest-pointer; "
              f"{sum(map(len, stale.values()))} stale would be deleted. Nothing written.")
        _budget_line(writes + lists, "publish[dry-run]")
        return len(serving) + len(raw)

    _ensure_cors(client)
    _put_batch(client, to_put, CACHE_CONTROL, with_digest=True)
    _put_batch(client, raw, RAW_CACHE_CONTROL)              # immutable lake partition
    # --- WO-10: write the last-good pointer AFTER the run's raw lake is uploaded,
    # so it only ever names a fully-landed lake. A file whose bytes raw/latest/
    # already holds is not copied again.
    _copy_batch_to_latest(client, to_copy)
    print(f"publish: {len(to_put)}/{len(serving)} serving "
          f"({skipped} unchanged, skipped) + {len(raw)} raw "
          f"+ {len(to_copy)}/{len(mirror)} latest-pointer (server-side copy) "
          f"-> r2://{R2_BUCKET}/")

    # ── Stale objects: last, so everything this run produced is already live
    # and a tripwire stops only the deletion.
    stale, tripped, lists = _find_stale(client, serving_keys)
    _budget_line(writes + lists)
    doomed = [k for keys in stale.values() for k in keys]
    if tripped and not allow_mass_delete:
        raise RuntimeError(
            "publish: stale-object tripwire — " + "; ".join(tripped) + ". Nothing was "
            "deleted. If the build is right (not a bug that dropped documents), re-run "
            "with --allow-mass-delete. First stale keys: " + ", ".join(doomed[:10]))
    _delete(client, doomed)
    print(f"publish: deleted {len(doomed)} stale object(s)"
          + "".join(f"\n  - {k}" for k in doomed[:50])
          + (f"\n  … and {len(doomed) - 50} more" if len(doomed) > 50 else ""))
    return len(serving) + len(raw)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force-all", action="store_true",
                    help="re-upload every serving file even when R2 already "
                         "holds the same content (use with a full rebuild)")
    ap.add_argument("--dry-run", action="store_true", default=None,
                    help="write and delete nothing; report what would change")
    ap.add_argument("--allow-mass-delete", action="store_true",
                    help="delete stale objects even when their number trips the "
                         "mass-delete tripwire")
    ap.add_argument("--allow-bulk-writes", action="store_true",
                    help=f"permit more than {BULK_WRITE_LIMIT} writes in one run")
    args = ap.parse_args()
    run(dry_run=args.dry_run, force_all=args.force_all,
        allow_mass_delete=args.allow_mass_delete,
        allow_bulk_writes=args.allow_bulk_writes)
