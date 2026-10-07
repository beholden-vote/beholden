"""WO-22b roster framework (DATA-CONTRACTS §8.8, §8.10, §8.11). Offline.

The two governments that already ship run through the framework from their real
pages (tests/fixtures/roster, fetched 2026-10-03), and must reproduce what main
published from those same pages (golden_main.json), ids aside.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import httpx
import pytest

from beholden_etl.build import coverage_divisions, pin_shards
from beholden_etl.jobs import build, publish, transform
from beholden_etl.sources import roster, tn_local
from test_pipeline import LEGS, MANIFEST, ROSTER_FIXTURES, land_local_rosters
from test_publish_stability import Bucket

REPO = Path(__file__).resolve().parents[2]
AS_OF = "2026-10-02T06:00:00+00:00"
SUMNER, HVILLE = tn_local.SPECS


def _pipeline(tmp: Path, out: str = "data") -> Path:
    """Federal fixture + both real roster pages, through the real transform/build."""
    raw = tmp / "raw"
    if not raw.exists():
        (raw / "unitedstates_legislators").mkdir(parents=True)
        (raw / "unitedstates_legislators" / "legislators-current.json").write_text(
            json.dumps(LEGS), encoding="utf-8")
        manifest = json.loads(json.dumps(MANIFEST))
        land_local_rosters(raw, manifest)
        for spec in tn_local.SPECS:
            manifest["sources"][spec.source.source_key]["retrieved_at"] = AS_OF
        (raw / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    db = str(tmp / "wh.duckdb")
    transform.run(raw_dir=raw, db_path=db)
    build.run(db_path=db, out_dir=tmp / out, raw_dir=raw)
    return tmp / out


def _local(data: Path) -> dict[str, dict]:
    out = {}
    for f in (data / "dossiers").glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d["identity"]["provenance"]["source"] in ("sumner_county", "hendersonville"):
            out[d["person_id"]] = d
    return out


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    return _pipeline(tmp_path_factory.mktemp("roster"))


@pytest.fixture(scope="module")
def broken(tmp_path_factory):
    """A deliberately broken spec: Sumner's seat count is wrong (25, the page
    lists 24). Exactly that locality must be withheld; everything else builds."""
    mp = pytest.MonkeyPatch()
    mp.setattr(tn_local, "SPECS", [dataclasses.replace(SUMNER, seats=(25, 25)), HVILLE])
    try:
        return _pipeline(tmp_path_factory.mktemp("broken"))
    finally:
        mp.undo()


# --- the spec ----------------------------------------------------------------

def test_a_spec_without_terms_ref_does_not_load():
    for bad in ("", None, "README.md"):
        with pytest.raises(ValueError, match="terms_ref"):
            dataclasses.replace(SUMNER, terms_ref=bad)


def test_every_spec_names_a_terms_document_and_a_sources_row():
    chrome = (REPO / "web" / "src" / "ui" / "chrome.tsx").read_text(encoding="utf-8")
    for spec in tn_local.SPECS:
        assert (REPO / spec.terms_ref).is_file(), spec.terms_ref
        place = f"{spec.name}{' County' if spec.level == 'county' else ''}, {spec.state.upper()}"
        assert place in chrome, f"no Sources page row for {place}"


def test_sources_registry_is_generated_from_the_specs():
    from beholden_etl.config import SOURCES
    for spec in tn_local.SPECS:
        src = SOURCES[spec.source.source_key]
        assert src.grade_reason == "official_web_roster" and src.freshness_sla_hours == 168
        assert spec.source.url.startswith(src.base_url)


def test_generic_gates():
    rows = [roster.RosterRow(name=f"P {n}", office_title="County Commissioner",
                             seat_label=f"District {n}") for n in range(1, 25)]
    for bad, msg in (
        (rows[:-1], "23 seats listed"),
        (rows[:-1] + [dataclasses.replace(rows[0], name=" ")], "no name"),
        (rows[:-1] + [dataclasses.replace(rows[0], seat_label="District 99")], "same person"),
        (rows[:-1] + [dataclasses.replace(rows[1], name="Q")], "more times than they exist"),
    ):
        with pytest.raises(roster.RosterError, match=msg):
            roster.check(SUMNER, bad)


# --- both localities reproduce their previous rows ---------------------------

def test_real_pages_reproduce_mains_output_ids_aside(real):
    golden = json.loads((ROSTER_FIXTURES / "golden_main.json").read_text(encoding="utf-8"))
    docs = []
    for d in _local(real).values():
        d = json.loads(json.dumps(d))
        for k in ("person_id", "graph_ref", "generated_at"):
            d.pop(k, None)
        for k in ("pipeline_version", "retrieved_at"):
            d["identity"]["provenance"].pop(k)
        docs.append(d)
    docs.sort(key=lambda d: (d["identity"]["office"]["display"], d["identity"]["full_name"]))
    assert docs == golden["dossiers"]

    def strip(rows):
        return sorted(({k: v for k, v in r.items() if k != "person_id"} for r in rows),
                      key=lambda r: json.dumps(r, sort_keys=True))
    for layer in ("county", "place"):
        rows = json.loads((real / "pins" / f"{layer}.json").read_text(encoding="utf-8"))
        assert strip(rows) == golden["pins"][layer]


def test_party_is_not_published_never_inferred(real):
    assert {d["identity"]["party"]["code"] for d in _local(real).values()} == {"U"}


# --- person-keyed ids and the one-time migration -----------------------------

def test_ids_are_keyed_on_the_person_not_the_seat():
    row = roster.RosterRow(name="Ada Example", office_title="County Commissioner",
                           seat_label="District 3")
    moved = dataclasses.replace(row, seat_label="District 9")
    assert roster.person_id(SUMNER, row.name) == roster.person_id(SUMNER, moved.name)
    # ...and namespaced by locality, so two governments' namesakes never collide.
    assert roster.person_id(SUMNER, row.name) != roster.person_id(HVILLE, row.name)


def test_migration_maps_every_id_main_published(real):
    legacy = json.loads((ROSTER_FIXTURES / "legacy_ids_main.json").read_text(encoding="utf-8"))
    hints = json.loads((real.parent / "publish_hints.json").read_text(encoding="utf-8"))
    new = {d["identity"]["full_name"]: pid for pid, d in _local(real).items()}
    assert len(legacy) == len(new) == 37
    for name, old in legacy.items():
        assert hints["migrated"][f"dossiers/{old}.json"] == f"dossiers/{new[name]}.json"
        assert hints["migrated"][f"graph/neighborhood/{old}.json"] is None
    assert hints["live"] == []                        # nothing withheld


def test_old_ids_are_listed_as_migrations_not_departures(real, tmp_path, bucket, capsys):
    """The first publish after this change finds main's 37 seat-keyed dossiers in
    the bucket. They are stale, but they did not leave office: the listing says so.
    A key outside the map is still a plain stale departure."""
    legacy = json.loads((ROSTER_FIXTURES / "legacy_ids_main.json").read_text(encoding="utf-8"))
    old = sorted(f"dossiers/{pid}.json" for pid in legacy.values())
    for k in old + ["dossiers/really-left.json"]:
        bucket.seed(k)
    publish.run(data_dir=real, raw_dir=tmp_path / "noraw", dry_run=False)
    log = capsys.readouterr().out
    for k in old:
        assert f"{k}  (id migration, not a departure)" in log
    assert "- dossiers/really-left.json\n" in log + "\n"
    assert "really-left.json  (id migration" not in log


@pytest.fixture
def bucket(monkeypatch):
    b = Bucket()
    monkeypatch.setattr(publish, "_client", lambda: b)
    return b


# --- withholding ---------------------------------------------------------------

def test_broken_spec_withholds_exactly_one_locality(broken, real):
    cov = json.loads((broken / "coverage" / "tn.json").read_text(encoding="utf-8"))["divisions"]
    assert cov[SUMNER.ocd_id]["state"] == "withheld"
    assert "24 seats listed, expected 25" in cov[SUMNER.ocd_id]["reason"]
    assert cov[HVILLE.ocd_id]["state"] == "covered"
    counts = json.loads((broken / "coverage.json").read_text(encoding="utf-8"))["counts"]
    assert (counts["localities_covered"], counts["localities_withheld"]) == (1, 1)
    # Every other artifact still built: the same file set as the healthy run.
    def tree(root):
        return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert tree(broken) == tree(real)


def test_last_good_is_served_for_a_withheld_locality(broken, real):
    """Withheld is not removed: the last good roster keeps its dossiers and pins,
    byte for byte the objects the healthy run serves (stamps aside)."""
    for name in ("pins/county.json", "pins/county/tn.json"):
        assert (broken / name).read_bytes() == (real / name).read_bytes()
    for pid in _local(real):
        key = f"dossiers/{pid}.json"
        assert publish.stable_digest(key, (broken / key).read_bytes()) == \
            publish.stable_digest(key, (real / key).read_bytes())
    hints = json.loads((broken.parent / "publish_hints.json").read_text(encoding="utf-8"))
    sumner = {pid for pid, d in _local(real).items()
              if d["identity"]["provenance"]["source"] == "sumner_county"}
    assert hints["live"] == sorted(f"dossiers/{pid}.json" for pid in sumner)


def test_stale_deletion_spares_a_withheld_locality(tmp_path, bucket):
    """Even if a build did not produce a withheld locality's objects, publish
    treats them as live; an official who really left is still deleted."""
    data = tmp_path / "data"
    (data / "dossiers").mkdir(parents=True)
    (data / "dossiers" / "here.json").write_text("{}", encoding="utf-8")
    (tmp_path / publish.HINTS_FILE).write_text(json.dumps(
        {"live": ["dossiers/withheld-member.json"], "migrated": {}}), encoding="utf-8")
    for k in ("dossiers/withheld-member.json", "dossiers/really-left.json"):
        bucket.seed(k)
    publish.run(data_dir=data, raw_dir=tmp_path / "noraw", dry_run=False, delete_stale=True)
    assert bucket.deleted == ["dossiers/really-left.json"]
    assert "dossiers/withheld-member.json" in bucket.objects


def _fake_page(monkeypatch, body: bytes):
    monkeypatch.setattr(roster, "_get", lambda url: body)


def test_fetch_gate_failure_withholds_and_keeps_the_last_good_page(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    good = (ROSTER_FIXTURES / "sumner_county.html").read_bytes()
    _fake_page(monkeypatch, good)
    frag = roster.fetch(SUMNER, raw, {})
    assert frag["count"] == 24 and "withheld" not in frag

    # The page mislabels a seat (no District 3, a District 99): the gate fails
    # and this locality alone is withheld.
    _fake_page(monkeypatch, good.replace(b"	3rd District	", b"	99th District	", 1))
    prior = {"sources": {"sumner_county": frag}}
    again = roster.fetch(SUMNER, raw, prior)
    assert again["retrieved_at"] == frag["retrieved_at"]      # never restamped
    assert "missing districts [3]" in again["withheld"]
    assert roster.landed(SUMNER, raw).read_bytes() == good    # last good kept
    assert (raw / "sumner_county" / "rejected.html").exists()
    rows, reason = roster.load(SUMNER, raw, {"sources": {"sumner_county": again}})
    assert len(rows) == 24 and reason == again["withheld"]

    # No last good at all: absent, not withheld.
    assert roster.fetch(SUMNER, tmp_path / "empty", {}) is None


def test_only_gate_failures_are_isolated(tmp_path, monkeypatch):
    def down(url):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(roster, "_get", down)
    with pytest.raises(httpx.ConnectError):
        roster.fetch(SUMNER, tmp_path, {})
    monkeypatch.setattr(roster, "_get", lambda url: b"\xff\xfe not utf-8")
    with pytest.raises(UnicodeDecodeError):
        roster.fetch(SUMNER, tmp_path, {})


# --- writers ---------------------------------------------------------------------

def test_coverage_file_matches_the_contract_byte_for_byte(real, monkeypatch):
    monkeypatch.setattr(coverage_divisions, "_now", lambda: "2026-10-03T00:00:00+00:00")
    ctx = build.BuildContext(db_path="", raw_dir=real.parent / "raw", out=real,
                             manifest=json.loads((real.parent / "raw" / "manifest.json")
                                                 .read_text(encoding="utf-8")),
                             holders=[], _provenance=build._provenance)
    assert coverage_divisions.publish(ctx) == {
        "localities_covered": 2, "localities_partial": 0, "localities_withheld": 0,
        "coverage_states": 1}
    expected = (
        '{"divisions":{'
        '"ocd-division/country:us/state:tn/county:sumner":{"reason":null,'
        '"roster_as_of":"2026-10-02","seats_expected":24,"seats_listed":24,'
        '"source":"sumner_county","state":"covered","votes":false},'
        '"ocd-division/country:us/state:tn/place:hendersonville":{"reason":null,'
        '"roster_as_of":"2026-10-02","seats_expected":13,"seats_listed":13,'
        '"source":"hendersonville","state":"covered","votes":false}},'
        '"generated_at":"2026-10-03T00:00:00+00:00","schema_version":"1.0","state":"tn"}')
    assert (real / "coverage" / "tn.json").read_text(encoding="utf-8") == expected


def test_pin_shards_are_the_monolithic_rows_of_that_state_in_order(real):
    for layer in pin_shards.SHARDED_LAYERS:
        mono = json.loads((real / "pins" / f"{layer}.json").read_text(encoding="utf-8"))
        shards = sorted((real / "pins" / layer).glob("*.json"))
        assert [p.name for p in shards] == ["tn.json"]     # no rows, no file
        want = [r for r in mono if "/state:tn/" in r["ocd_id"]]
        assert shards[0].read_bytes() == json.dumps(want, separators=(",", ":")).encode()
    # Non-local layers stay monolithic.
    assert not (real / "pins" / "cd").exists()


def test_no_graph_document_for_a_roster_official(real):
    for pid in _local(real):
        assert not (real / "graph" / "neighborhood" / f"{pid}.json").exists()
    # Officials with edges, or outside the roster tier, are untouched.
    assert any((real / "graph" / "neighborhood").glob("*.json"))


def test_two_builds_are_identical(real):
    """The framework's own rebuild is byte-identical once §8.1's stamps are set
    aside. coverage.json is excluded: its per-source age_hours is a reading of
    the clock on every run by design (WO-33)."""
    again = _pipeline(real.parent, "again")
    files = sorted(p.relative_to(real).as_posix() for p in real.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(again).as_posix() for p in again.rglob("*") if p.is_file())
    for key in files:
        if key == "coverage.json":
            continue
        assert publish.stable_digest(key, (real / key).read_bytes()) == \
            publish.stable_digest(key, (again / key).read_bytes()), key


# --- photo/name pairing (regression: each commissioner showed the NEXT one's photo) ---

def _surname(name: str) -> str:
    return name.split(",")[0].split()[-1]


def test_sumner_photos_belong_to_their_commissioner():
    """The county page renders each post's image BEFORE its title widget, so the
    photo is the last <img> before the title, not the first one after it. Every
    filename carries the commissioner's surname (first names vary: 'Darrel' for
    Darrell Rogers, 'Dan' for Daniel Bristol)."""
    rows = tn_local.parse_sumner((ROSTER_FIXTURES / "sumner_county.html").read_text(encoding="utf-8"))
    assert len(rows) == 24
    for r in rows:
        filename = r["photo_url"].rsplit("/", 1)[-1].lower()
        assert _surname(r["full_name"]).lower() in filename, (r["full_name"], filename)


def test_hendersonville_photos_belong_to_their_member():
    """The h-card puts the u-photo inside the member's own card; the image's alt
    text names the member ('D.Ward', 'M.Evans' for two of them)."""
    import re
    page = (ROSTER_FIXTURES / "hendersonville.html").read_text(encoding="utf-8")
    alt = dict(re.findall(r'<img src="([^"]+)" alt="([^"]*)"[^>]*class="field u-photo"', page))
    rows = tn_local.parse_hendersonville(page)
    assert len(rows) == 13
    for r in rows:
        assert _surname(r["full_name"]).lower() in alt[r["photo_url"]].lower(), r["full_name"]
