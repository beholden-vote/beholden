"""Stage 5 (optional) — the bulk artifact sold at api.beholden.vote.

Nothing in here is secret. Every fact in the dump is already free, one object
at a time, at data.beholden.vote, and it stays that way. What is sold is the
PACKAGING: one download instead of ~8,000 requests, plus a manifest with
digests so a buyer re-pulls only what changed. Charging for the facts
themselves would be both wrong and unenforceable — they are public records.

Two structural decisions worth not undoing:

1. **A separate bucket, not a prefix.** The artifact goes to R2_BULK_BUCKET,
   which has no custom domain attached, so the only route to it is the Worker.
   A prefix inside the public bucket would be one careless path change away
   from publishing the product for free; a bucket with no public hostname
   cannot leak that way. It also costs nothing — R2's free storage tier is
   per-account.

2. **The redistribution gate.** A dossier enters the dump only when EVERY
   provenance envelope in it names a source the registry marks
   redistributable=True (TRUSTED-EXTRACTION §8). This is the same shape as
   "no provenance, no publish": the registry refuses, so an undetermined
   source cannot reach a paid artifact by anyone forgetting. Today that means
   the dump is EMPTY until a human records license determinations — which is
   the correct behaviour, not a bug to route around.

Writes to dist/bulk, which publish.py never walks, so the serving path is
untouched. Dry-runs when R2_BULK_BUCKET is unset, like publish does.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ..config import PAGES_DIST, SOURCES, pipeline_version

BULK_DIST = "dist/bulk"
BULK_PREFIX = "v1/"
# The artifact is regenerated nightly and bought by digest, so an intermediary
# holding a stale copy is worse than useless. The manifest is the only thing a
# client should be re-reading, and it is served free.
BULK_CACHE_CONTROL = "no-store"
BULK_BUCKET_ENV = "R2_BULK_BUCKET"
REQUIRED_ENV = ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", BULK_BUCKET_ENV)

# gzip, not zstd, deliberately: zstandard is a new dependency for ~10% on JSON
# that every HTTP client on earth already decodes as gzip.
# ponytail: revisit when the runtime reaches 3.14 and compression.zstd is stdlib.
_ARTIFACTS = (
    ("dossiers", "dossiers.ndjson.gz"),
    ("graph/neighborhood", "graph.ndjson.gz"),
)


def _sources_in(doc) -> set[str]:
    """Every source key named by any provenance envelope anywhere in the doc.

    Walks rather than reading known section names: provenance sits at varying
    depths (identity, ideology, legislative, money.disclosures, …) and a new
    section must not be able to smuggle an unlicensed source past this gate by
    virtue of being new. An envelope without a 'source' contributes the empty
    string, which is in no registry and therefore fails — the same fail-closed
    direction as everything else here.
    """
    found: set[str] = set()
    if isinstance(doc, dict):
        prov = doc.get("provenance")
        if isinstance(prov, dict):
            found.add(prov.get("source") or "")
        for v in doc.values():
            found |= _sources_in(v)
    elif isinstance(doc, list):
        for v in doc:
            found |= _sources_in(v)
    return found


def is_redistributable(doc) -> bool:
    """True when every source this document cites may enter a paid artifact.

    An unregistered source key is not redistributable — same rule the grade
    validator applies, for the same reason: an unknown source has made no
    promise about anything.
    """
    srcs = _sources_in(doc)
    if not srcs:
        return False              # a document citing nothing proves nothing
    return all(k in SOURCES and SOURCES[k].redistributable for k in srcs)


def _write_ndjson_gz(docs, out: Path) -> tuple[int, int, str]:
    """Write one JSON document per line, gzipped. Returns (count, bytes, sha256).

    mtime=0 so the same inputs produce byte-identical output: the sha256 in the
    manifest is then a real content identity a buyer can compare across pulls,
    not a number that changes every night because gzip stamped the clock.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with gzip.GzipFile(out, "wb", mtime=0) as fh:
        for doc in docs:
            fh.write(json.dumps(doc, separators=(",", ":"), sort_keys=True).encode())
            fh.write(b"\n")
            count += 1
    blob = out.read_bytes()
    return count, len(blob), hashlib.sha256(blob).hexdigest()


def _eligible(src_dir: Path):
    """Yield the documents under src_dir that clear the redistribution gate."""
    if not src_dir.is_dir():
        return
    for p in sorted(src_dir.glob("*.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        if is_redistributable(doc):
            yield doc


def run(data_dir: str | Path = PAGES_DIST, out_dir: str | Path = BULK_DIST,
        dry_run: bool | None = None) -> dict:
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    if dry_run is None:
        dry_run = not all(os.environ.get(k) for k in REQUIRED_ENV)

    artifacts = []
    for src, name in _ARTIFACTS:
        considered = len(list((data_dir / src).glob("*.json"))) if (data_dir / src).is_dir() else 0
        count, size, digest = _write_ndjson_gz(_eligible(data_dir / src), out_dir / name)
        artifacts.append({"key": f"{BULK_PREFIX}{name}", "count": count,
                          "bytes": size, "sha256": digest})
        print(f"bulk: {name} {count}/{considered} documents cleared the "
              f"redistribution gate ({size} B)")

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pipeline_version": pipeline_version(),
        "artifacts": artifacts,
        # Named so a buyer can see exactly what they are getting, and so an
        # empty dump reads as a deliberate licensing state rather than a bug.
        "redistributable_sources": sorted(k for k, s in SOURCES.items() if s.redistributable),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    if not any(a["count"] for a in artifacts):
        print("bulk: WARNING every document was withheld — no source in the "
              "registry that these documents cite is marked redistributable. "
              "Record license determinations in config.SOURCES (see "
              "TRUSTED-EXTRACTION §8) before selling access.")

    if dry_run:
        print(f"bulk[dry-run]: wrote {out_dir}/ "
              f"(set {'/'.join(REQUIRED_ENV)} to upload)")
        return manifest

    from .publish import _client
    client = _client()
    bucket = os.environ[BULK_BUCKET_ENV]
    for name in [a["key"].removeprefix(BULK_PREFIX) for a in artifacts] + ["manifest.json"]:
        p = out_dir / name
        client.put_object(Bucket=bucket, Key=f"{BULK_PREFIX}{name}", Body=p.read_bytes(),
                          ContentType="application/gzip" if name.endswith(".gz")
                          else "application/json",
                          CacheControl=BULK_CACHE_CONTROL)
    print(f"bulk: {len(artifacts) + 1} objects -> r2://{bucket}/{BULK_PREFIX}")
    return manifest


if __name__ == "__main__":
    run()
