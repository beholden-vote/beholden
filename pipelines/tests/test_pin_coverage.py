"""Every seat a roster lists is a pin (found 2026-10-10: council members of MTAS cities got
none because their chamber had no map layer). Offline; all four fixture lanes in one build."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from beholden_etl.jobs import build, transform
from beholden_etl.sources import roster, tn_ctas, tn_mtas
from test_pipeline import LEGS, MANIFEST, land_local_rosters
from test_tn_ctas import COMMISSIONERS, EXECUTIVES
from test_tn_mtas import EXPORT
from test_tn_mtas import SPECS as MTAS_FIXTURE_SPECS

AS_OF = "2026-10-08T06:00:00+00:00"
BODIES = {tn_ctas.COMMISSIONERS_CSV: COMMISSIONERS, tn_ctas.EXECUTIVES_CSV: EXECUTIVES,
          tn_mtas.EXPORT_URL: EXPORT}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    tmp = tmp_path_factory.mktemp("pins")
    raw = tmp / "raw"
    try:
        mp.setattr(roster, "_get", lambda url: BODIES[url])
        mp.setattr(roster, "SHARED_PAUSE_S", 0)
        mp.setattr(roster, "_shared_memo", {})
        manifest = json.loads(json.dumps(MANIFEST))
        land_local_rosters(raw, manifest)
        for s in [*tn_ctas.SPECS, *MTAS_FIXTURE_SPECS]:
            if (frag := roster.fetch(s, raw, {})) is not None:
                manifest["sources"][s.source.source_key] = {**frag, "retrieved_at": AS_OF}
        (raw / "unitedstates_legislators").mkdir(parents=True, exist_ok=True)
        (raw / "unitedstates_legislators" / "legislators-current.json").write_text(
            json.dumps(LEGS), encoding="utf-8")
        (raw / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        db = str(tmp / "wh.duckdb")
        transform.run(raw_dir=raw, db_path=db)
        build.run(db_path=db, out_dir=tmp / "data", raw_dir=raw)
        return tmp / "data"
    finally:
        mp.undo()


def _load(data: Path, name: str):
    return json.loads((data / name).read_text(encoding="utf-8"))


def test_pins_per_division_equal_the_seats_coverage_lists_for_every_registered_lane(built):
    cov = _load(built, "coverage/tn.json")["divisions"]
    pins = Counter(p["ocd_id"] for layer in ("county", "place")
                   for p in _load(built, f"pins/{layer}/tn.json"))
    assert len(cov) >= 14                     # CTAS + MTAS fixture localities + the two
    for ocd, c in cov.items():
        assert pins[ocd] == c["seats_listed"], (ocd, pins[ocd], c["seats_listed"])
    assert sum(pins.values()) == sum(c["seats_listed"] for c in cov.values())


def test_every_member_of_an_mtas_body_has_its_own_office_id(built):
    raw = built.parent / "raw"
    checked = 0
    for spec in MTAS_FIXTURE_SPECS:
        rows = roster.load(spec, raw, {})[0]
        if rows:
            ids = [o["office_id"] for o in roster.spine_rows(spec, rows)["offices"]]
            assert len(ids) == len(rows) == len(set(ids)), spec.name
            checked += 1
    assert checked >= 6
