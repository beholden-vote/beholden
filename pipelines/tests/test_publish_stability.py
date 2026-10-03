"""WO-33: publish only what changed (DATA-CONTRACTS section 8.1).

Publish skips an object when the digest of its content, stamps excluded, equals
the digest stored beside the object in R2. The failure these tests exist to
prevent is NOT an unnecessary upload -- that costs one class-A operation. It is
the opposite one: a field wrongly left out of the digest is a fact whose changes
are never published again. So the suite is built around the dangerous direction:

  * every leaf of every document the real build emits is mutated in turn, and
    the digest must move unless that leaf is one of the stamps in the closed
    section 8.1 list (restated here independently of the implementation);
  * every uncertain case -- no stored digest, a HEAD that errors, a body that
    does not parse -- must land on the upload side.

The first attempt at this (an ETag/MD5 comparison) passed its unit tests and
skipped 7 of 15,883 objects in production, because the tests fed it identical
bytes and the build never produces identical bytes. So the publish tests here
run against two REAL builds of one warehouse made the way two nights make them:
another pipeline version, another clock, every source re-checked.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from beholden_etl import store
from beholden_etl.build import dossiers
from beholden_etl.jobs import build, publish


# --- helpers -----------------------------------------------------------------

class Bucket:
    """In-memory stand-in for the boto3 S3 client bound to one R2 bucket.
    Capitalised kwargs mirror boto3's real signatures, which is what publish
    calls. It keeps what R2 keeps -- body and user metadata -- and answers HEAD
    the way R2 does: the ETag is the body's MD5, Metadata is whatever the PUT
    sent, and an absent key raises ClientError. Every write is recorded so a
    test can count class-A operations independently of publish's own tally."""

    def __init__(self):
        self.objects: dict[str, dict] = {}
        self.puts: list[str] = []
        self.copies: list[str] = []
        self.deleted: list[str] = []
        self.lists = 0
        self.head_error: Exception | None = None

    def seed(self, key: str, body: bytes = b"{}", meta: dict | None = None):
        self.objects[key] = {"body": body, "meta": dict(meta or {})}

    def writes(self) -> int:
        return len(self.puts) + len(self.copies) + len(self.deleted)

    def head_object(self, Bucket, Key):
        if self.head_error is not None:
            raise self.head_error
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        obj = self.objects[Key]
        etag = hashlib.md5(obj["body"], usedforsecurity=False).hexdigest()
        return {"ETag": f'"{etag}"', "Metadata": dict(obj["meta"])}

    def put_object(self, Bucket, Key, Body, ContentType, CacheControl, Metadata):
        self.objects[Key] = {"body": Body, "meta": dict(Metadata)}
        self.puts.append(Key)

    def copy_object(self, Bucket, CopySource, Key, ContentType, CacheControl,
                    MetadataDirective):
        self.objects[Key] = {"body": self.objects[CopySource["Key"]]["body"], "meta": {}}
        self.copies.append(Key)

    def put_bucket_cors(self, Bucket, CORSConfiguration):
        pass

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        for i in range(0, max(len(keys), 1), 1000):         # R2 pages at 1000 keys
            self.lists += 1
            yield {"Contents": [{"Key": k} for k in keys[i:i + 1000]]}

    def delete_objects(self, Bucket, Delete):
        for obj in Delete["Objects"]:
            del self.objects[obj["Key"]]
            self.deleted.append(obj["Key"])
        return {}


@pytest.fixture
def bucket(monkeypatch):
    b = Bucket()
    monkeypatch.setattr(publish, "_client", lambda: b)
    return b


LATER = datetime(2031, 3, 9, 4, 5, 6, tzinfo=timezone.utc)


def _next_night(slice_dirs, monkeypatch, name="night2"):
    """Build the SAME warehouse again the way a later night does: another
    PIPELINE_VERSION, another clock (another DAY, so a date-grained stamp moves
    too), and a manifest in which every source was re-checked and found
    unchanged. Returns the new serving root."""
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return LATER

    monkeypatch.setenv("PIPELINE_VERSION", "etl-2031.10.0405")
    monkeypatch.setattr(build, "datetime", Clock)
    monkeypatch.setattr(dossiers, "datetime", Clock)
    manifest_path = slice_dirs / "raw" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for meta in manifest["sources"].values():
        meta["retrieved_at"] = "2031-03-09T03:00:00+00:00"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    out = slice_dirs / name
    build.run(db_path=str(slice_dirs / "wh.duckdb"), out_dir=out, raw_dir=slice_dirs / "raw")
    return out


def _keys(root, *prefixes):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*.json")
                  if p.relative_to(root).as_posix().startswith(prefixes))


def _leaves(node, path=()):
    """Every leaf path in a JSON document. An empty container is a leaf too:
    `[]` becoming `[x]` is a change like any other."""
    if isinstance(node, dict) and node:
        for k, v in node.items():
            yield from _leaves(v, path + (k,))
    elif isinstance(node, list) and node:
        for i, v in enumerate(node):
            yield from _leaves(v, path + (i,))
    else:
        yield path


# The three envelope keys section 8.1 names. Restated, not imported, for the
# same reason as _is_stamp below.
ENVELOPE_KEYS = ("provenance", "votes_provenance", "committees_provenance")


def _is_stamp(key: str, path: tuple) -> bool:
    """The closed stamp list of DATA-CONTRACTS section 8.1, written out here
    from the contract rather than imported from publish.py -- a test that asked
    the implementation which fields it ignores would agree with any bug in it."""
    if path == ("generated_at",):
        return True
    if key.startswith("graph/") and path == ("as_of",):
        return True
    return (len(path) >= 2 and path[-2] in ENVELOPE_KEYS
            and path[-1] in ("pipeline_version", "retrieved_at"))


def _with(doc, path, value):
    """A deep copy of `doc` with the leaf at `path` replaced by `value`."""
    doc = json.loads(json.dumps(doc))
    node = doc
    for step in path[:-1]:
        node = node[step]
    node[path[-1]] = value
    return doc


def _digest(key: str, doc) -> str:
    return publish.stable_digest(key, json.dumps(doc).encode("utf-8"))


def _moved(key: str, a, b, path=()):
    """Paths at which two documents differ, stamps excluded -- so a failure
    names the field that churns instead of printing two hashes."""
    if isinstance(a, dict) and isinstance(b, dict):
        return [hit for k in sorted(set(a) | set(b))
                for hit in _moved(key, a.get(k), b.get(k), path + (k,))]
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [hit for i, (x, y) in enumerate(zip(a, b)) for hit in _moved(key, x, y, path + (i,))]
    return [] if a == b or _is_stamp(key, path) else [(path, a, b)]


def _path_id(value):
    return ".".join(map(str, value)) if isinstance(value, tuple) else None


# --- 1. two nights, same facts: different bytes, same digest -------------------

def test_two_builds_of_one_warehouse_differ_in_bytes_and_agree_in_digest(slice_dirs, monkeypatch):
    """The exact production condition the first attempt never tested. Night two
    re-stamps everything -- generated_at, pipeline_version, every envelope's
    retrieved_at, every graph as_of -- and changes no fact. Every dossier and
    every graph document must come out with different bytes and the same stable
    digest; otherwise all ~16k of them are rewritten every night."""
    night1, night2 = slice_dirs / "data", _next_night(slice_dirs, monkeypatch)

    keys = _keys(night1, "dossiers/", "graph/")
    assert keys == _keys(night2, "dossiers/", "graph/")
    assert any(k.startswith("dossiers/") for k in keys)
    assert any(k.startswith("graph/") for k in keys)
    for key in keys:
        a, b = (night1 / key).read_bytes(), (night2 / key).read_bytes()
        assert a != b, f"{key}: night two did not re-stamp it -- the test proves nothing"
        assert publish.stable_digest(key, a) == publish.stable_digest(key, b),             f"{key} churns at {_moved(key, json.loads(a), json.loads(b))}"

    # And the stamps really are what moved.
    dossier = next(k for k in keys if k.startswith("dossiers/"))
    doc1 = json.loads((night1 / dossier).read_text(encoding="utf-8"))
    doc2 = json.loads((night2 / dossier).read_text(encoding="utf-8"))
    assert doc1["generated_at"] != doc2["generated_at"]
    for stamp in ("pipeline_version", "retrieved_at"):
        assert doc1["identity"]["provenance"][stamp] != doc2["identity"]["provenance"][stamp]
    neighborhood = next(k for k in keys if k.startswith("graph/"))
    assert json.loads((night1 / neighborhood).read_text(encoding="utf-8"))["as_of"] \
        != json.loads((night2 / neighborhood).read_text(encoding="utf-8"))["as_of"]

    # coverage.json is the home of "last checked" (section 8.1) and must be
    # rewritten every run: its per-source retrieved_at rows and its top-level
    # pipeline_version are NOT inside an envelope, so they are in the digest.
    assert publish.stable_digest("coverage.json", (night1 / "coverage.json").read_bytes()) \
        != publish.stable_digest("coverage.json", (night2 / "coverage.json").read_bytes())


def _dict_keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _dict_keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _dict_keys(v)


def test_every_provenance_key_the_build_emits_is_a_named_envelope(slice_dirs):
    """The envelope list is closed and matched by exact name. This is the alarm
    for the day build starts writing an envelope under a new key."""
    assert publish.ENVELOPE_KEYS == set(ENVELOPE_KEYS)
    root = slice_dirs / "data"
    seen: dict[str, str] = {}
    for key in _keys(root, ""):
        for k in _dict_keys(json.loads((root / key).read_text(encoding="utf-8"))):
            if k.endswith("provenance"):
                seen.setdefault(k, key)
    unknown = {k: where for k, where in seen.items() if k not in ENVELOPE_KEYS}
    assert not unknown, (
        f"build writes key(s) ending in 'provenance' that DATA-CONTRACTS section 8.1 does "
        f"not name: {unknown}. DECIDE, do not just make this pass. If it is a provenance "
        "envelope, its pipeline_version/retrieved_at re-stamp nightly and every document "
        "carrying it re-uploads every night until the key is added to section 8.1, to "
        "publish.ENVELOPE_KEYS and to ENVELOPE_KEYS in this file. If it is anything else, "
        "rename it: a key that looks like an envelope and is not one will be mistaken "
        "for one.")
    # The fixture exercises all three, so none of them is on the list untested.
    assert set(seen) == set(ENVELOPE_KEYS)


# --- 2 + 3. the dangerous direction ------------------------------------------

def test_every_field_the_build_emits_is_in_the_digest_unless_it_is_a_stamp(slice_dirs):
    """THE test of this work order. Take every JSON document the real build
    produced, change each leaf in turn, and require the digest to move -- unless
    the leaf is one of the section 8.1 stamps, in which case it must not.

    This is what makes a wrongly excluded fact impossible to ship quietly: a
    new field, in a new section, by a future work order, is covered the moment
    it appears in the fixture build, with no test to remember to write."""
    root = slice_dirs / "data"
    facts = stamps = 0
    seen_stamps = set()
    for key in _keys(root, ""):
        doc = json.loads((root / key).read_text(encoding="utf-8"))
        base = _digest(key, doc)
        for path in _leaves(doc):
            if not path:                       # the whole document is one empty container
                continue
            moved = _digest(key, _with(doc, path, "CHANGED-BY-TEST")) != base
            if _is_stamp(key, path):
                assert not moved, f"{key} {path}: a stamp is in the digest"
                stamps += 1
                seen_stamps.add(path[-1])
            else:
                assert moved, (f"{key} {path}: changing this field does not change the "
                               "digest, so a change to it would never be published")
                facts += 1
    # The fixture exercises every kind of stamp, and far more facts than stamps.
    assert seen_stamps == {"generated_at", "pipeline_version", "retrieved_at", "as_of"}
    assert facts > 10 * stamps > 0


ENVELOPE = {
    "source": "voteview", "source_url": "https://voteview.com/",
    "retrieved_at": "2026-09-12T06:00:00+00:00", "pipeline_version": "etl-2026.37.0600",
    "methodology_id": "dw-nominate", "grade": "A", "grade_reason": "bulk_official_api"}
DOSSIER = {
    "schema_version": "1.0", "person_id": "p1", "generated_at": "2026-09-12T06:10:00+00:00",
    "identity": {"full_name": "Jane Rep", "party": {"code": "D"}, "provenance": dict(ENVELOPE)},
    "ideology": {"score": 0.5, "provenance": dict(ENVELOPE)},
    "legislative": {"committees": [], "provenance": dict(ENVELOPE),
                    "votes_provenance": dict(ENVELOPE), "committees_provenance": dict(ENVELOPE)},
    "money": {"campaign_finance": {"cycles": [
        {"cycle": 2026, "total_raised_cents": 100, "as_of": "2026-06-30"}]}},
}
GRAPH = {"center": "p1", "as_of": "2026-09-12", "nodes": [{"person_id": "p1"}],
         "edges": [{"type": "committee", "a": "p1", "b": "p2", "weight": 1,
                    "evidence": [{"kind": "committee", "id": "HSAG", "as_of": "2026-01-03"}]}]}
COVERAGE = {"generated_at": "2026-09-12T06:10:00+00:00", "pipeline_version": "etl-2026.37.0600",
            "sources": {"voteview": {"retrieved_at": "2026-09-12T06:00:00+00:00"}}}
D, G, C = "dossiers/p1.json", "graph/neighborhood/p1.json", "coverage.json"


@pytest.mark.parametrize("key, doc, path", [
    (D, DOSSIER, ("identity", "full_name")),                       # a plain fact
    (D, DOSSIER, ("identity", "party", "code")),
    (D, DOSSIER, ("ideology", "score")),
    # Envelope fields that are NOT stamps: where a fact came from and how it
    # was graded are themselves published facts.
    (D, DOSSIER, ("ideology", "provenance", "source")),
    (D, DOSSIER, ("ideology", "provenance", "source_url")),
    (D, DOSSIER, ("ideology", "provenance", "methodology_id")),
    (D, DOSSIER, ("ideology", "provenance", "grade")),
    (D, DOSSIER, ("ideology", "provenance", "grade_reason")),
    (D, DOSSIER, ("legislative", "votes_provenance", "source")),
    (D, DOSSIER, ("legislative", "committees_provenance", "grade")),
    # Fact-bearing dates outside an envelope. An FEC total's as_of is the
    # filing's coverage date; if it were ignored, a new filing whose totals
    # happened to match would never show its new date.
    (D, DOSSIER, ("money", "campaign_finance", "cycles", 0, "as_of")),
    (G, GRAPH, ("edges", 0, "evidence", 0, "as_of")),              # as_of below the top level
    (C, COVERAGE, ("sources", "voteview", "retrieved_at")),        # the reader's "last checked"
    (C, COVERAGE, ("pipeline_version",)),                          # top level, not in an envelope
], ids=_path_id)
def test_changing_a_fact_changes_the_digest(key, doc, path):
    assert _digest(key, _with(doc, path, "2099-01-01")) != _digest(key, doc)


@pytest.mark.parametrize("key, doc, path", [
    (D, DOSSIER, ("generated_at",)),
    (D, DOSSIER, ("identity", "provenance", "retrieved_at")),
    (D, DOSSIER, ("ideology", "provenance", "retrieved_at")),
    (D, DOSSIER, ("ideology", "provenance", "pipeline_version")),
    (D, DOSSIER, ("legislative", "votes_provenance", "retrieved_at")),
    (D, DOSSIER, ("legislative", "votes_provenance", "pipeline_version")),
    (D, DOSSIER, ("legislative", "committees_provenance", "retrieved_at")),
    (D, DOSSIER, ("legislative", "committees_provenance", "pipeline_version")),
    (G, GRAPH, ("as_of",)),
    (C, COVERAGE, ("generated_at",)),
], ids=_path_id)
def test_changing_only_a_stamp_does_not_change_the_digest(key, doc, path):
    assert _digest(key, _with(doc, path, "2099-01-01")) == _digest(key, doc)


def test_a_stamp_name_is_only_a_stamp_in_its_one_place():
    """Stamps are matched by structure, never by finding the key name. Each of
    these puts a stamp's NAME somewhere the contract does not list, where it is
    an ordinary field and a change to it must publish."""
    def moves(key, doc, changed):
        return _digest(key, changed) != _digest(key, doc)

    # as_of at the top level is a stamp for graph/ only.
    assert moves(D, {"as_of": "a"}, {"as_of": "b"})
    assert moves("pins/cd.json", {"as_of": "a"}, {"as_of": "b"})
    assert moves("graphs/p1.json", {"as_of": "a"}, {"as_of": "b"})       # not under graph/
    # generated_at below the top level.
    assert moves(D, {"x": {"generated_at": "a"}}, {"x": {"generated_at": "b"}})
    assert moves(D, [{"generated_at": "a"}], [{"generated_at": "b"}])
    # retrieved_at / pipeline_version directly in a section, not in its envelope.
    assert moves(D, {"x": {"retrieved_at": "a"}}, {"x": {"retrieved_at": "b"}})
    assert moves(D, {"x": {"pipeline_version": "a"}}, {"x": {"pipeline_version": "b"}})
    # A key merely ENDING in "provenance" -- the list is closed, not a suffix
    # match -- or a provenance that is not a dict.
    for near_miss in ("x_provenance", "money_provenance", "provenances", "Provenance"):
        assert moves(D, {near_miss: {"retrieved_at": "a"}}, {near_miss: {"retrieved_at": "b"}})
    assert moves(D, {"provenance": [{"retrieved_at": "a"}]}, {"provenance": [{"retrieved_at": "b"}]})
    assert moves(D, {"provenance": "a"}, {"provenance": "b"})
    # One level below an envelope is no longer the envelope.
    assert moves(D, {"provenance": {"x": {"retrieved_at": "a"}}},
                 {"provenance": {"x": {"retrieved_at": "b"}}})
    # An envelope nested anywhere, including inside a list, IS one.
    assert not moves(D, {"a": [{"b": {"provenance": {"retrieved_at": "a", "source": "s"}}}]},
                     {"a": [{"b": {"provenance": {"retrieved_at": "b", "source": "s"}}}]})


def test_digest_is_canonical_but_never_lossy():
    # Key order and whitespace carry no fact; list order and values do.
    assert publish.stable_digest("x.json", b'{"a":1,"b":[1,2]}') \
        == publish.stable_digest("x.json", b'{ "b": [1, 2],\n "a": 1 }')
    assert publish.stable_digest("x.json", b'{"b":[1,2]}') != publish.stable_digest("x.json", b'{"b":[2,1]}')
    assert publish.stable_digest("x.json", b'{"a":null}') != publish.stable_digest("x.json", b'{}')
    assert publish.stable_digest("x.json", b'{"a":0}') != publish.stable_digest("x.json", b'{"a":false}')
    assert publish.stable_digest("x.json", b'{"a":"1"}') != publish.stable_digest("x.json", b'{"a":1}')
    # Adding or dropping an envelope key that is not a stamp is a change.
    assert _digest(D, {"provenance": {"source": "s"}}) != _digest(D, {"provenance": {}})


def test_non_json_objects_are_compared_on_their_raw_bytes():
    body = b'{"generated_at":"2026-09-12"}\n'
    assert publish.stable_digest("robots.txt", body) == hashlib.sha256(body).hexdigest()
    # No stamp handling outside .json: every byte counts.
    assert publish.stable_digest("robots.txt", body) \
        != publish.stable_digest("robots.txt", body.replace(b"12", b"13"))


def test_a_json_body_that_does_not_parse_has_no_digest():
    """None, not a fallback hash: publish will not vouch for what it cannot
    read, so such an object uploads every time."""
    assert publish.stable_digest("dossiers/p1.json", b'{"truncated": ') is None
    assert publish.stable_digest("dossiers/p1.json", b"\xff\xfe\x00not text") is None


# --- 4. publish against a bucket that stores metadata -------------------------

def _serving_puts(bucket):
    return sorted(k for k in bucket.puts if not k.startswith("raw/"))


def test_second_night_uploads_only_what_changed(slice_dirs, monkeypatch, bucket):
    """End to end, the live acceptance in miniature. Night one finds an empty
    bucket and writes everything. Night two is a full re-stamp with no fact
    changed: it must upload coverage.json and nothing else. Then one fact
    changes in one dossier, and exactly that dossier uploads."""
    raw = slice_dirs / "raw"
    night1 = slice_dirs / "data"
    serving = sorted(_keys(night1, "") + ["robots.txt"])

    publish.run(data_dir=night1, raw_dir=raw, dry_run=False)
    assert _serving_puts(bucket) == serving
    for key in serving:                                    # the digest rides with the body
        assert bucket.objects[key]["meta"] == {
            publish.STABLE_META: publish.stable_digest(key, (night1 / key).read_bytes())}

    bucket.puts.clear()
    night2 = _next_night(slice_dirs, monkeypatch)
    publish.run(data_dir=night2, raw_dir=raw, dry_run=False)
    assert _serving_puts(bucket) == ["coverage.json"]
    # What is served is still night one's document, stamps and all: "as of the
    # run in which this document last changed" (section 8.1).
    dossier = _keys(night1, "dossiers/")[0]
    assert bucket.objects[dossier]["body"] == (night1 / dossier).read_bytes()
    assert bucket.deleted == []

    bucket.puts.clear()
    doc = json.loads((night2 / dossier).read_text(encoding="utf-8"))
    doc["identity"]["party"]["display"] = "Changed Party"
    (night2 / dossier).write_text(json.dumps(doc), encoding="utf-8")
    publish.run(data_dir=night2, raw_dir=raw, dry_run=False)
    assert _serving_puts(bucket) == [dossier]
    served = json.loads(bucket.objects[dossier]["body"])
    assert served["identity"]["party"]["display"] == "Changed Party"
    assert served["generated_at"] == doc["generated_at"]   # and now carries night two's stamps


def _tree(tmp_path, files: dict[str, bytes]):
    root = tmp_path / "data"
    for key, body in files.items():
        (root / key).parent.mkdir(parents=True, exist_ok=True)
        (root / key).write_bytes(body)
    return root


def test_every_uncertain_case_uploads(tmp_path, bucket):
    """Skipping is only ever the answer when the digests positively match."""
    body = json.dumps(DOSSIER).encode("utf-8")
    root = _tree(tmp_path, {f"dossiers/{n}.json": body for n in
                            ("absent", "legacy", "wrong", "same")}
                 | {"dossiers/broken.json": b'{"truncated": '})
    good = publish.stable_digest("dossiers/same.json", body)
    bucket.seed("dossiers/same.json", body, {publish.STABLE_META: good})
    # Uploaded before digests existed: identical bytes, matching ETag, no
    # metadata. Publish cannot tell what it says without trusting bytes it has
    # not read, so it uploads -- this is every object on the first run.
    bucket.seed("dossiers/legacy.json", body)
    bucket.seed("dossiers/wrong.json", body, {publish.STABLE_META: "0" * 64})
    # Unparseable locally: uploads even though the bucket holds the same bytes.
    bucket.seed("dossiers/broken.json", b'{"truncated": ')

    publish.run(data_dir=root, raw_dir=tmp_path / "noraw", dry_run=False)
    assert sorted(bucket.puts) == ["dossiers/absent.json", "dossiers/broken.json",
                                   "dossiers/legacy.json", "dossiers/wrong.json"]
    assert bucket.objects["dossiers/legacy.json"]["meta"] == {publish.STABLE_META: good}
    assert bucket.objects["dossiers/broken.json"]["meta"] == {}       # nothing to vouch with

    bucket.puts.clear()                                    # ...and it never starts matching
    publish.run(data_dir=root, raw_dir=tmp_path / "noraw", dry_run=False)
    assert bucket.puts == ["dossiers/broken.json"]


@pytest.mark.parametrize("error", [
    ClientError({"Error": {"Code": "403"}}, "HeadObject"),
    ClientError({"Error": {"Code": "500"}}, "HeadObject"),
    EndpointConnectionError(endpoint_url="https://r2.invalid"),      # network, not an HTTP status
], ids=["forbidden", "server-error", "network"])
def test_a_head_error_uploads(tmp_path, bucket, error):
    body = json.dumps(DOSSIER).encode("utf-8")
    root = _tree(tmp_path, {"dossiers/p1.json": body})
    bucket.seed("dossiers/p1.json", body,
                {publish.STABLE_META: publish.stable_digest("dossiers/p1.json", body)})
    publish.run(data_dir=root, raw_dir=tmp_path / "noraw", dry_run=False)
    assert bucket.puts == []                               # the control: it would have skipped

    bucket.head_error = error
    publish.run(data_dir=root, raw_dir=tmp_path / "noraw", dry_run=False)
    assert bucket.puts == ["dossiers/p1.json"]


def test_force_all_writes_objects_whose_digest_already_matches(tmp_path, bucket):
    body = json.dumps(DOSSIER).encode("utf-8")
    root = _tree(tmp_path, {"dossiers/p1.json": body, "robots.txt": b"User-agent: *\n"})
    publish.run(data_dir=root, raw_dir=tmp_path / "noraw", dry_run=False)
    bucket.puts.clear()
    publish.run(data_dir=root, raw_dir=tmp_path / "noraw", dry_run=False)
    assert bucket.puts == []                               # nothing changed, nothing written
    publish.run(data_dir=root, raw_dir=tmp_path / "noraw", dry_run=False, force_all=True)
    assert sorted(bucket.puts) == ["dossiers/p1.json", "robots.txt"]


# --- raw/latest mirror ---------------------------------------------------------

def _raw(tmp_path, files: dict[str, bytes]):
    raw = tmp_path / "raw"
    for rel, body in files.items():
        (raw / rel).parent.mkdir(parents=True, exist_ok=True)
        (raw / rel).write_bytes(body)
    return raw


def test_latest_mirror_copies_only_files_whose_bytes_changed(tmp_path, bucket):
    """raw/latest/ is compared on raw bytes (ETag vs local MD5): there are no
    stamps to look past in a source snapshot. The dated partition is the
    reproducibility record and is written whole every run, as before."""
    root = _tree(tmp_path, {"coverage.json": b"{}"})
    raw = _raw(tmp_path, {"manifest.json": b'{"generated_at":"2026-09-12T06:00:00+00:00"}',
                          "voteview/members.csv": b"a,b\n", "fec/totals/H1.json": b"{}"})

    publish.run(data_dir=root, raw_dir=raw, dry_run=False)
    assert sorted(bucket.copies) == ["raw/latest/fec/totals/H1.json", "raw/latest/manifest.json",
                                     "raw/latest/voteview/members.csv"]
    assert "raw/2026-09-12/voteview/members.csv" in bucket.objects

    bucket.copies.clear()
    bucket.puts.clear()
    (raw / "manifest.json").write_bytes(b'{"generated_at":"2026-09-13T06:00:00+00:00"}')
    publish.run(data_dir=root, raw_dir=raw, dry_run=False)
    assert bucket.copies == ["raw/latest/manifest.json"]              # only what moved
    assert sorted(k for k in bucket.puts if k.startswith("raw/")) == [  # the lake: as before
        "raw/2026-09-13/fec/totals/H1.json", "raw/2026-09-13/manifest.json",
        "raw/2026-09-13/voteview/members.csv"]
    assert bucket.objects["raw/latest/manifest.json"]["body"] == (raw / "manifest.json").read_bytes()

    bucket.copies.clear()
    publish.run(data_dir=root, raw_dir=raw, dry_run=False, force_all=True)
    assert len(bucket.copies) == 3


def test_latest_mirror_never_reads_a_multipart_etag_as_a_digest(tmp_path):
    f = tmp_path / "x.csv"
    f.write_bytes(b"a,b\n")
    md5 = hashlib.md5(b"a,b\n", usedforsecurity=False).hexdigest()

    class Head:
        def __init__(self, resp):
            self.resp = resp

        def head_object(self, Bucket, Key):
            return self.resp

    assert publish._same_bytes(Head({"ETag": f'"{md5}"'}), "raw/latest/x.csv", f)
    assert not publish._same_bytes(Head({"ETag": f'"{md5}-4"'}), "raw/latest/x.csv", f)
    assert not publish._same_bytes(Head({"ETag": '"0"'}), "raw/latest/x.csv", f)
    assert not publish._same_bytes(Head({}), "raw/latest/x.csv", f)       # no ETag at all


# --- 5. stale objects ----------------------------------------------------------

def test_stale_deletion_removes_only_managed_keys_absent_locally(tmp_path, bucket):
    """An official who left office must stop being served. Everything else in
    the bucket is somebody else's: the raw lake, the tiles, the fonts, root
    objects, and any prefix this build did not write into."""
    root = _tree(tmp_path, {
        "dossiers/here.json": b"{}", "graph/neighborhood/here.json": b"{}",
        "pins/cd.json": b"[]", "coverage.json": b"{}", "robots.txt": b"x",
        # A build that one day writes under a protected name still cannot
        # make that prefix deletable.
        "tiles/readme.json": b"{}", "fonts/readme.json": b"{}"})
    keep = ["raw/2020-01-01/voteview/members.csv", "raw/latest/voteview/members.csv",
            "tiles/us-cd-2025.pmtiles", "fonts/Noto Sans Regular/0-255.pbf",
            "orphan-at-root.json", "areas/47165.json", "dossiers-backup/old.json"]
    gone = ["dossiers/left-office.json", "graph/neighborhood/left-office.json",
            "pins/retired-layer.json"]
    for key in keep + gone:
        bucket.seed(key)

    publish.run(data_dir=root, raw_dir=tmp_path / "noraw", dry_run=False, delete_stale=True)

    assert sorted(bucket.deleted) == sorted(gone)
    for key in keep:
        assert key in bucket.objects, f"{key} was deleted"
    assert "dossiers/here.json" in bucket.objects
    assert not any(k.startswith(("raw/", "tiles/", "fonts/")) for k in bucket.deleted)


def test_stale_keys_are_listed_on_every_run_and_deleted_only_on_request(tmp_path, bucket, capsys,
                                                                       monkeypatch):
    """Deletion is opt-in. A run without --delete-stale reports the exact count
    under each managed prefix and the keys up to the cap, and removes nothing --
    not even past the tripwire, which guards a delete and so has nothing to
    stop here. It is reported instead of raised."""
    monkeypatch.setattr(publish, "STALE_LIST_CAP", 3)
    root = _tree(tmp_path, {"dossiers/here.json": b"{}", "pins/cd.json": b"[]"})
    for i in range(30):                                    # past max(25, 2%)
        bucket.seed(f"dossiers/gone-{i:02}.json")
    bucket.seed("pins/retired-layer.json")

    publish.run(data_dir=root, raw_dir=tmp_path / "noraw", dry_run=False)
    out = capsys.readouterr().out
    assert bucket.deleted == []
    assert "publish: 30 stale under dossiers/ (listed only" in out
    assert "publish: 1 stale under pins/ (listed only" in out
    assert "  - dossiers/gone-02.json" in out and "gone-03" not in out
    assert "… and 27 more" in out
    assert "  - pins/retired-layer.json" in out
    assert "TRIPWIRE dossiers/: 30 of 31" in out and "deleted 3" not in out

    bucket.seed("unlisted/x.json")                         # nothing stale -> says so
    for key in [k for k in bucket.objects if "gone" in k or "retired" in k]:
        del bucket.objects[key]
    publish.run(data_dir=root, raw_dir=tmp_path / "noraw", dry_run=False)
    assert "no stale objects under any managed prefix" in capsys.readouterr().out


def test_managed_prefixes_come_from_the_build_and_never_include_the_protected_ones():
    keys = {"dossiers/a.json", "graph/neighborhood/a.json", "coverage.json", "robots.txt",
            "raw/x.json", "tiles/x.pmtiles", "fonts/a/0-255.pbf"}
    assert publish._managed_prefixes(keys) == ["dossiers/", "graph/"]


def test_delete_refuses_a_protected_key_whoever_asks(bucket):
    """The refusal is checked again at the point of deletion, not only where the
    managed set is derived, so no caller can route around it."""
    for key in ("dossiers/a.json", "raw/latest/a.json", "tiles/a.pmtiles", "fonts/a.pbf"):
        bucket.seed(key)
    for bad in ("raw/latest/a.json", "tiles/a.pmtiles", "fonts/a.pbf"):
        with pytest.raises(RuntimeError, match="refusing to delete"):
            publish._delete(bucket, ["dossiers/a.json", bad])
    assert bucket.deleted == []                            # not even the legitimate key


@pytest.mark.parametrize("live, stale, trips", [
    (100, 25, False),         # at the floor: max(25, 2% of 125) = 25
    (100, 26, True),
    (4000, 81, False),        # 2% of 4081 = 81.62
    (4000, 82, True),         # 2% of 4082 = 81.64
])
def test_stale_tripwire_boundary(bucket, live, stale, trips):
    serving = {f"dossiers/{i}.json" for i in range(live)}
    for key in serving:
        bucket.seed(key)
    for i in range(stale):
        bucket.seed(f"dossiers/gone-{i}.json")
    found, tripped, lists = publish._find_stale(bucket, serving)
    assert len(found["dossiers/"]) == stale
    assert bool(tripped) is trips
    assert lists == -(-(live + stale) // 1000)             # one LIST per page of 1000


def test_tripwire_raises_and_deletes_nothing_anywhere(tmp_path, bucket, capsys):
    """A build bug that dropped half the dossiers must not be able to empty the
    bucket. One prefix over the line stops deletion under EVERY prefix -- and
    the run's own uploads have already landed, so only the deletion is lost."""
    root = _tree(tmp_path, {"dossiers/here.json": b'{"a":1}', "pins/cd.json": b"[]"})
    for i in range(26):
        bucket.seed(f"dossiers/gone-{i}.json")
    bucket.seed("pins/retired-layer.json")                 # 1 stale: under its own tripwire

    with pytest.raises(RuntimeError, match="tripwire"):
        publish.run(data_dir=root, raw_dir=tmp_path / "noraw", dry_run=False, delete_stale=True)
    assert bucket.deleted == []
    assert "pins/retired-layer.json" in bucket.objects
    assert sorted(bucket.puts) == ["dossiers/here.json", "pins/cd.json"]
    out = capsys.readouterr().out
    assert "class-A this run" in out                       # the budget line survives the raise
    assert "26 stale under dossiers/ (NOT deleted: tripwire)" in out   # ...and so does the list

    # --allow-mass-delete widens a delete; it is not itself a request to delete.
    publish.run(data_dir=root, raw_dir=tmp_path / "noraw", dry_run=False, allow_mass_delete=True)
    assert bucket.deleted == []

    publish.run(data_dir=root, raw_dir=tmp_path / "noraw", dry_run=False, delete_stale=True,
                allow_mass_delete=True)
    assert len(bucket.deleted) == 27
    assert sorted(bucket.objects) == ["dossiers/here.json", "pins/cd.json"]


def test_dry_run_prints_what_would_be_deleted_and_writes_nothing(tmp_path, bucket, monkeypatch, capsys):
    for k in publish.REQUIRED_ENV:                         # dry-run WITH credentials
        monkeypatch.setenv(k, "test")
    root = _tree(tmp_path, {"dossiers/here.json": b"{}"})
    raw = _raw(tmp_path, {"manifest.json": b'{"generated_at":"2026-09-12T06:00:00+00:00"}'})
    bucket.seed("dossiers/left-office.json")

    publish.run(data_dir=root, raw_dir=raw, dry_run=True, delete_stale=True)
    out = capsys.readouterr().out
    assert "1 stale under dossiers/ (would delete)\n  - dossiers/left-office.json" in out
    assert "would upload dossiers/here.json" in out
    assert bucket.writes() == 0
    assert "dossiers/left-office.json" in bucket.objects

    publish.run(data_dir=root, raw_dir=raw, dry_run=True)   # and without the flag
    out = capsys.readouterr().out
    assert "1 stale under dossiers/ (listed only" in out and "would delete" not in out
    assert bucket.writes() == 0


def test_dry_run_without_credentials_needs_no_network(tmp_path, monkeypatch, capsys):
    for k in publish.REQUIRED_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(publish, "_client", lambda: pytest.fail("dry-run touched the network"))
    root = _tree(tmp_path, {"dossiers/here.json": b"{}"})
    assert publish.run(data_dir=root, raw_dir=tmp_path / "noraw") == 1
    assert "publish[dry-run] dossiers/here.json" in capsys.readouterr().out


# --- write budget ---------------------------------------------------------------

def test_class_a_line_counts_puts_copies_and_lists(tmp_path, bucket, capsys):
    root = _tree(tmp_path, {"dossiers/a.json": b"{}", "pins/cd.json": b"[]", "coverage.json": b"{}"})
    raw = _raw(tmp_path, {"manifest.json": b'{"generated_at":"2026-09-12T06:00:00+00:00"}',
                          "voteview/members.csv": b"a,b\n"})
    publish.run(data_dir=root, raw_dir=raw, dry_run=False)
    n = len(bucket.puts) + len(bucket.copies) + bucket.lists      # the bucket's own count
    assert n == 3 + 2 + 2 + 2          # serving PUTs, raw PUTs, mirror COPYs, LISTs (2 prefixes)
    out = capsys.readouterr().out
    assert f"publish: class-A this run = {n} (≈ {n * 30} per month of 1,000,000 free)" in out
    assert "::warning::" not in out

    publish.run(data_dir=root, raw_dir=raw, dry_run=False)        # a quiet night
    n = 2 + 0 + 2                      # raw PUTs (dated partition), no copies, LISTs
    assert f"publish: class-A this run = {n} " in capsys.readouterr().out


def test_budget_warning_when_the_month_projects_past_700k(capsys):
    assert publish.CLASS_A_WARN_PER_MONTH == 700_000
    assert publish.CLASS_A_FREE_PER_MONTH == 1_000_000
    publish._budget_line(23_333)                           # 699,990 a month
    assert "::warning::" not in capsys.readouterr().out
    publish._budget_line(23_334)                           # 700,020 a month
    assert "::warning::" in capsys.readouterr().out


def test_bulk_write_limit_raises_before_anything_is_written(tmp_path, bucket, monkeypatch):
    """A run that would make more writes than the whole bucket holds several
    times over is a bug. It must be caught while it is still only a plan."""
    assert publish.BULK_WRITE_LIMIT == 200_000
    monkeypatch.setattr(publish, "BULK_WRITE_LIMIT", 3)
    root = _tree(tmp_path, {f"dossiers/{i}.json": b"{}" for i in range(4)})
    bucket.seed("dossiers/left-office.json")

    with pytest.raises(RuntimeError, match="single-run limit"):
        publish.run(data_dir=root, raw_dir=tmp_path / "noraw", dry_run=False)
    assert bucket.writes() == 0 and bucket.lists == 0

    publish.run(data_dir=root, raw_dir=tmp_path / "noraw", dry_run=False, allow_bulk_writes=True)
    assert len(bucket.puts) == 4

    bucket.puts.clear()
    publish.run(data_dir=root, raw_dir=tmp_path / "noraw", dry_run=False, force_all=True)
    assert len(bucket.puts) == 4                           # --force-all is its own permission


# --- 6. deterministic ordering ---------------------------------------------------

def test_index_files_are_byte_identical_across_builds(slice_dirs, monkeypatch):
    """pins, style feeds and the people index carry no stamps at all, so their
    only source of churn is row order. Two builds of one warehouse must produce
    the same bytes -- these are compared, and skipped, like any other object."""
    night1, night2 = slice_dirs / "data", _next_night(slice_dirs, monkeypatch)
    keys = _keys(night1, "pins/", "stylefeeds/", "search/")
    assert "search/people.json" in keys
    assert sum(k.startswith("pins/") for k in keys) == len(build.SERVED_LAYERS)
    assert sum(k.startswith("stylefeeds/") for k in keys) == len(build.SERVED_LAYERS)
    for key in keys:
        assert (night1 / key).read_bytes() == (night2 / key).read_bytes(), key


def test_holders_and_recent_bills_have_a_total_order(slice_dirs):
    """Byte-identity above holds on a small fixture whatever the query says;
    this pins the ORDER BY itself, which is what makes it hold in production."""
    con = store.connect(str(slice_dirs / "wh.duckdb"))
    holders = build._current_holders(con)
    stats = build._legislative_stats(con, {})
    con.close()
    order = [(h["ocd_id"], h["person_id"]) for h in holders]
    assert len(order) > 3 and order == sorted(order)

    bills = max((s["recent_bills"] for s in stats.values()), key=len)
    dates = [b["latest_action_on"] for b in bills]
    assert len(bills) >= 2 and all(dates)
    assert dates == sorted(dates, reverse=True)            # newest action first
