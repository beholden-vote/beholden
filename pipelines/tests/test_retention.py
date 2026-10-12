"""WO-41: skip-unchanged raw uploads and the dated-raw retention pass.

Two failures matter, and both are the dangerous direction:
  * a raw file whose bytes changed is skipped -> that night cannot be rebuilt;
  * retention deletes a copy some kept night still resolves to, or anything
    under raw/latest/, tiles/ or fonts/.
Everything runs offline against the in-memory bucket from the WO-33 suite.
"""
from __future__ import annotations

import hashlib
import json
import random
from datetime import date, timedelta

import pytest
from botocore.exceptions import EndpointConnectionError
from test_publish_stability import Bucket, _raw, _tree

from beholden_etl.jobs import publish, retention


class SizedBucket(Bucket):
    """The WO-33 fake, with listing Size like R2 returns."""

    def paginate(self, Bucket, Prefix):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        for i in range(0, max(len(keys), 1), 1000):
            self.lists += 1
            yield {"Contents": [{"Key": k, "Size": len(self.objects[k]["body"])}
                                for k in keys[i:i + 1000]]}


@pytest.fixture
def bucket(monkeypatch):
    b = SizedBucket()
    monkeypatch.setattr(publish, "_client", lambda: b)
    return b


def _manifest(d: str) -> bytes:
    return json.dumps({"generated_at": f"{d}T06:00:00+00:00"}).encode()


def _night_of(bucket, night: str) -> dict[str, bytes]:
    """Rebuild night D from the bucket alone: per path, the newest dated copy
    at or before D. This is the reproducibility contract retention preserves."""
    best: dict[str, tuple[str, bytes]] = {}
    for key, obj in bucket.objects.items():
        hit = retention._night(key)
        if hit and hit[0] <= night and (hit[1] not in best or best[hit[1]][0] < hit[0]):
            best[hit[1]] = (hit[0], obj["body"])
    return {rel: body for rel, (_, body) in best.items()}


# --- skip-unchanged ----------------------------------------------------------

def test_any_byte_change_uploads_and_only_a_stored_equal_hash_skips(tmp_path):
    """Byte-for-byte: flip each byte, append one, drop one -> never skipped.
    No stored hash (every object before WO-41), an absent object, or a HEAD that
    errors -> never skipped. Only the exact stored SHA-256 skips."""
    body = b'{"bill":"hr-1","text":"a,b\\n"}'
    f = tmp_path / "x.json"
    b = SizedBucket()
    b.seed("raw/latest/x.json", body, {publish.RAW_META: hashlib.sha256(body).hexdigest()})

    f.write_bytes(body)
    assert publish._raw_unchanged(b, "raw/latest/x.json", f)
    variants = [body[:i] + bytes([body[i] ^ 1]) + body[i + 1:] for i in range(len(body))]
    variants += [body + b" ", body[:-1], b""]
    for v in variants:
        f.write_bytes(v)
        assert not publish._raw_unchanged(b, "raw/latest/x.json", f), v

    f.write_bytes(body)
    assert not publish._raw_unchanged(b, "raw/latest/absent.json", f)
    b.seed("raw/latest/legacy.json", body)                 # pre-WO-41: no hash stored
    assert not publish._raw_unchanged(b, "raw/latest/legacy.json", f)
    b.seed("raw/latest/blank.json", body, {publish.RAW_META: ""})
    assert not publish._raw_unchanged(b, "raw/latest/blank.json", f)
    b.head_error = EndpointConnectionError(endpoint_url="https://r2.invalid")
    assert not publish._raw_unchanged(b, "raw/latest/x.json", f)


def test_quiet_night_writes_only_what_changed_and_hashes_ride_with_bytes(tmp_path, bucket):
    root = _tree(tmp_path, {"coverage.json": b"{}"})
    raw = _raw(tmp_path, {"manifest.json": _manifest("2026-09-12"),
                          "voteview/members.csv": b"a,b\n", "fec/totals/H1.json": b"{}"})
    publish.run(data_dir=root, raw_dir=raw, dry_run=False)
    for key, obj in bucket.objects.items():
        if key.startswith("raw/"):                          # dated AND latest carry the hash
            assert obj["meta"] == {publish.RAW_META: hashlib.sha256(obj["body"]).hexdigest()}

    bucket.puts.clear()
    bucket.copies.clear()
    (raw / "manifest.json").write_bytes(_manifest("2026-09-13"))
    (raw / "voteview" / "members.csv").write_bytes(b"a,b\nc,d\n")
    publish.run(data_dir=root, raw_dir=raw, dry_run=False)
    assert sorted(bucket.puts) == ["raw/2026-09-13/manifest.json",
                                   "raw/2026-09-13/voteview/members.csv"]
    assert sorted(bucket.copies) == ["raw/latest/manifest.json", "raw/latest/voteview/members.csv"]
    assert "raw/2026-09-13/fec/totals/H1.json" not in bucket.objects
    assert _night_of(bucket, "2026-09-13") == {
        "manifest.json": _manifest("2026-09-13"), "voteview/members.csv": b"a,b\nc,d\n",
        "fec/totals/H1.json": b"{}"}

    bucket.puts.clear()
    publish.run(data_dir=root, raw_dir=raw, dry_run=False, force_all=True)
    assert len([k for k in bucket.puts if k.startswith("raw/2026-09-13/")]) == 3


def test_every_night_rebuilds_exactly_before_and_after_retention(tmp_path, bucket, capsys):
    """Seventy nights of random edits, additions and no-ops: every night's lake
    must rebuild byte-for-byte from the bucket. Then retention deletes, and every
    KEPT night must still rebuild byte-for-byte, raw/latest/ untouched."""
    rng = random.Random(41)
    root = _tree(tmp_path, {"coverage.json": b"{}"})
    files = {f"src{i % 3}/f{i}.json": b"v0-%d" % i for i in range(12)}
    raw = _raw(tmp_path, files)
    history: dict[str, dict[str, bytes]] = {}
    start = date(2026, 7, 20)
    for n in range(70):
        night = (start + timedelta(days=n)).isoformat()
        for rel in rng.sample(sorted(files), rng.choice([0, 0, 1, 3])):
            files[rel] = b"v%d-%s" % (n, rel.encode())
        if rng.random() < 0.1:
            files[f"src9/new{n}.json"] = b"new"
        files["manifest.json"] = _manifest(night)
        raw = _raw(tmp_path, files)
        publish.run(data_dir=root, raw_dir=raw, dry_run=False)
        history[night] = dict(files)
    for night, tree in history.items():
        assert _night_of(bucket, night) == tree, night

    latest = {k: v for k, v in bucket.objects.items() if k.startswith("raw/latest/")}
    p = retention.plan(bucket, len(files))
    assert p["refusals"] == [] and p["doomed"]
    capsys.readouterr()
    assert retention.settle(bucket, p, delete=True) == len(p["doomed"])
    assert "deleting raw/2026-07-" in capsys.readouterr().out
    assert {k: v for k, v in bucket.objects.items() if k.startswith("raw/latest/")} == latest
    nights = sorted(history)
    kept = nights[-14:] + ["2026-07-31", "2026-08-31"]
    assert p["kept"] == sorted(kept)
    for night in kept:
        assert _night_of(bucket, night) == history[night], night


# --- retention windows and guards ---------------------------------------------

def _lake(bucket, nights: list[str], paths=("a/x.json", "b/y.csv")):
    """Full snapshots (the pre-WO-41 layout) for each night, plus raw/latest/."""
    for d in nights:
        for rel in paths:
            bucket.seed(f"raw/{d}/{rel}", d.encode())
        bucket.seed(f"raw/{d}/manifest.json", _manifest(d))
    for rel in (*paths, "manifest.json"):
        bucket.seed(f"raw/latest/{rel}", b"latest")


def test_keeps_last_14_nights_and_the_last_night_of_each_month(bucket):
    nights = [(date(2026, 7, 1) + timedelta(days=i)).isoformat() for i in range(100)]
    _lake(bucket, nights)
    for key in ("tiles/us.pmtiles", "fonts/a/0-255.pbf", "dossiers/a.json"):
        bucket.seed(key)
    p = retention.plan(bucket, 3)
    assert p["kept"] == sorted(set(nights[-14:]) | {"2026-07-31", "2026-08-31", "2026-09-30"})
    doomed_nights = {d for d, *_ in p["doomed"]}
    assert doomed_nights == set(nights) - set(p["kept"])
    retention.settle(bucket, p, delete=True)
    assert all(k.startswith(("tiles/", "fonts/", "dossiers/", "raw/latest/"))
               or retention._night(k)[0] in p["kept"] for k in bucket.objects)
    assert "tiles/us.pmtiles" in bucket.objects and "raw/latest/manifest.json" in bucket.objects


def test_a_kept_delta_night_keeps_the_older_copy_it_resolves_to(bucket):
    """Night 07-01 wrote x; nothing changed x afterwards. Every kept night
    resolves x to the 07-01 copy, so it stays though 07-01 itself is not kept."""
    nights = [(date(2026, 7, 1) + timedelta(days=i)).isoformat() for i in range(40)]
    bucket.seed("raw/2026-07-01/a/x.json", b"x")
    for d in nights:
        bucket.seed(f"raw/{d}/manifest.json", _manifest(d))
    bucket.seed("raw/latest/a/x.json", b"x")
    bucket.seed("raw/latest/manifest.json", b"m")
    p = retention.plan(bucket, 2)
    assert "raw/2026-07-01/a/x.json" not in {k for _, k, _ in p["doomed"]}
    assert "raw/2026-07-01/manifest.json" in {k for _, k, _ in p["doomed"]}


@pytest.mark.parametrize("break_it, why", [
    (lambda b: b.objects.pop("raw/latest/manifest.json"), "is missing"),
    (lambda b: [b.objects.pop(k) for k in list(b.objects) if k.startswith("raw/latest/")],
     "is missing"),
    (lambda b: b.objects.pop("raw/latest/a/x.json"), "fewer than the 3 files"),
    (lambda b: b.seed("raw/2026-07-01-old/x.json"), "neither raw/latest/ nor a dated night"),
    (lambda b: b.seed("raw/stray.json"), "neither raw/latest/ nor a dated night"),
    (lambda b: b.seed("raw/2026-13-40/x.json"), "neither raw/latest/ nor a dated night"),
])
def test_doubt_refuses_and_deletes_nothing(bucket, capsys, break_it, why):
    _lake(bucket, [(date(2026, 7, 1) + timedelta(days=i)).isoformat() for i in range(30)])
    break_it(bucket)
    p = retention.plan(bucket, 3)
    assert any(why in r for r in p["refusals"])
    assert retention.settle(bucket, p, delete=False) == 0         # dry-run: reported
    assert "REFUSED" in capsys.readouterr().out
    with pytest.raises(RuntimeError, match="refused"):            # deleting: raises
        retention.settle(bucket, p, delete=True)
    assert bucket.deleted == []


def test_delete_refuses_anything_but_a_dated_key(bucket):
    for bad in ("raw/latest/a.json", "tiles/a.pmtiles", "fonts/a.pbf", "dossiers/a.json",
                "raw/2026-7-1/a.json", "raw/a.json"):
        bucket.seed(bad)
        with pytest.raises(RuntimeError, match="refusing to delete"):
            retention._delete(bucket, ["raw/2026-07-01/a.json", bad])
    assert bucket.deleted == []


def test_cap_deletes_oldest_first_and_says_so(bucket, capsys):
    _lake(bucket, [(date(2026, 7, 1) + timedelta(days=i)).isoformat() for i in range(20)])
    p = retention.plan(bucket, 3)
    assert retention.settle(bucket, p, delete=True, cap=4) == 4
    out = capsys.readouterr().out
    assert "capped at 4 of" in out
    assert sorted(bucket.deleted) == sorted(k for _, k, _ in p["doomed"][:4])
    assert all(k.startswith("raw/2026-07-01/") or k.startswith("raw/2026-07-02/")
               for k in bucket.deleted)


def test_nightly_default_is_a_dry_run_listing(tmp_path, bucket, capsys):
    """publish.run without --raw-retention-delete lists every prefix it would
    delete and deletes nothing — the shape the first merge ships in."""
    _lake(bucket, [(date(2026, 7, 1) + timedelta(days=i)).isoformat() for i in range(20)],
          paths=("voteview/members.csv",))
    root = _tree(tmp_path, {"coverage.json": b"{}"})
    raw = _raw(tmp_path, {"manifest.json": _manifest("2026-07-21"),
                          "voteview/members.csv": b"a,b\n"})
    publish.run(data_dir=root, raw_dir=raw, dry_run=False)
    out = capsys.readouterr().out
    assert bucket.deleted == []
    assert "retention: would delete (dry-run) raw/2026-07-01/: 2 objects" in out
    assert "retention:   voteview: " in out
    assert "nothing deleted (dry-run" in out

    publish.run(data_dir=root, raw_dir=raw, dry_run=False, raw_retention_delete=True)
    assert bucket.deleted and all(retention._night(k) for k in bucket.deleted)
