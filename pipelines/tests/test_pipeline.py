"""Offline regression suite for the federal ETL slice. Runs with no network,
no API keys, and no GDAL — synthetic fixtures exercise the real code paths.

    cd pipelines && pytest        # or: pytest pipelines/tests
"""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from beholden_etl import store
from beholden_etl.build import dossiers
from beholden_etl.jobs import build, transform
from beholden_etl.sources import legislators

REPO = Path(__file__).resolve().parents[2]


# --- tile OCD stamper (lives in spike/, imported by path) -------------------
def _load_stamper():
    spec = importlib.util.spec_from_file_location("stamp_ocd_ids", REPO / "spike" / "stamp_ocd_ids.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_stamp_ocd_ids_conventions():
    s = _load_stamper()
    assert s.feature_props("states", {"STATEFP": "47", "NAME": "Tennessee", "GEOID": "47"}) == {
        "ocd_id": "ocd-division/country:us/state:tn", "name": "Tennessee", "geoid": "47"}
    # at-large (CDFP 00) and delegate (98) both collapse to cd:1 -> matches the ETL key
    assert s.feature_props("cd", {"STATEFP": "02", "CD119FP": "00"})["ocd_id"] == \
        "ocd-division/country:us/state:ak/cd:1"
    assert s.feature_props("cd", {"STATEFP": "47", "CD119FP": "06"})["ocd_id"] == \
        "ocd-division/country:us/state:tn/cd:6"
    assert s.feature_props("sldl", {"STATEFP": "48", "SLDLST": "ZZZ"}) is None   # undefined dropped
    assert s.feature_props("states", {"STATEFP": "99"}) is None                  # foreign FIPS dropped


def test_stamp_cli_entrypoint():
    """Exercise the actual CLI (stdin->stdout) as build_pmtiles.sh invokes it."""
    import subprocess
    import sys
    feat = '{"type":"Feature","properties":{"STATEFP":"47","NAME":"Tennessee","GEOID":"47"},"geometry":null}\n'
    r = subprocess.run([sys.executable, str(REPO / "spike" / "stamp_ocd_ids.py"), "states"],
                       input=feat, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert '"ocd-division/country:us/state:tn"' in r.stdout


# --- DuckDB warehouse -------------------------------------------------------
def test_schema_loads_with_generated_column():
    con = store.connect()
    store.init_schema(con)
    store.insert(con, "persons", [{"person_id": "11111111-1111-1111-1111-111111111111", "full_name": "X"}])
    store.insert(con, "trades", [{
        "trade_id": "44444444-4444-4444-4444-444444444444",
        "person_id": "11111111-1111-1111-1111-111111111111", "filing_id": "F", "filing_url": "http://x",
        "asset_name": "A", "txn_type": "purchase", "amount": "15k_50k",
        "transacted_on": "2026-01-01", "filed_on": "2026-03-20", "source": "internal"}])
    assert con.execute("SELECT late_by_days FROM trades").fetchone()[0] == 33  # 78 days - 45


# --- transform + build vertical slice ---------------------------------------
LEGS = [
    {"id": {"bioguide": "R000001", "icpsr": "11"}, "name": {"official_full": "Jane Rep"},
     "bio": {"birthday": "1970-05-01"},
     "terms": [{"type": "rep", "start": "2025-01-03", "end": "2027-01-03", "state": "TN", "district": 6, "party": "Republican"}]},
    {"id": {"bioguide": "A000002", "icpsr": "22"}, "name": {"official_full": "Al Large"},
     "terms": [{"type": "rep", "start": "2025-01-03", "end": "2027-01-03", "state": "AK", "district": 0, "party": "Democrat"}]},
    {"id": {"bioguide": "S000003", "icpsr": "33"}, "name": {"official_full": "Sam Sen"},
     "terms": [{"type": "sen", "start": "2021-01-03", "end": "2027-01-03", "state": "TN", "party": "Republican", "class": 1}]},
]
# Mirrors real Voteview columns: no congress_end_date exists in HSxxx_members.csv,
# so computed_as_of must come from the fetch manifest (or the congress boundary).
VOTEVIEW = ("congress,chamber,icpsr,nominate_dim1,nominate_number_of_votes\n"
            "119,House,11,0.512,300\n"
            "119,House,22,-0.301,250\n"
            "119,Senate,33,0.488,5\n"               # Sam: <20 votes -> pending
            "119,President,,0.9,10\n")              # blank icpsr: skipped, never crashes

# Dynamic (1h ago) so within_sla assertions never rot as wall-clock advances.
RETRIEVED_AT = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
MANIFEST = {"generated_at": RETRIEVED_AT, "congress": 119, "sources": {
    "unitedstates_legislators": {"retrieved_at": RETRIEVED_AT, "source_url": "https://x", "count": 3},
    "congress.gov": {"retrieved_at": RETRIEVED_AT, "source_url": "https://x", "count": 3},
    "voteview": {"retrieved_at": RETRIEVED_AT, "source_url": "https://x", "count": 4},
}}


@pytest.fixture
def slice_dirs(tmp_path):
    raw = tmp_path / "raw"
    (raw / "unitedstates_legislators").mkdir(parents=True)
    (raw / "voteview").mkdir(parents=True)
    (raw / "unitedstates_legislators" / "legislators-current.json").write_text(json.dumps(LEGS))
    (raw / "voteview" / "HS119_members.csv").write_text(VOTEVIEW)
    (raw / "manifest.json").write_text(json.dumps(MANIFEST))   # fetch always writes one
    db = str(tmp_path / "wh.duckdb")
    transform.run(raw_dir=raw, db_path=db)
    build.run(db_path=db, out_dir=tmp_path / "data", raw_dir=raw)
    return tmp_path


def test_stylefeed_keys_match_cd_ocd(slice_dirs):
    feed = json.loads((slice_dirs / "data" / "stylefeeds" / "cd.json").read_text())
    assert feed["ocd-division/country:us/state:tn/cd:6"]["party"] == "R"
    assert feed["ocd-division/country:us/state:ak/cd:1"]["party"] == "D"  # at-large joins cd:1


def test_pins_carry_display_fields(slice_dirs):
    """Pins label polygons on hover/stack views without dossier fan-out."""
    cd = json.loads((slice_dirs / "data" / "pins" / "cd.json").read_text())
    jane = next(p for p in cd if p["full_name"] == "Jane Rep")
    assert jane["office"] == "U.S. House · TN-6"
    assert jane["party"] == "R" and jane["vacant"] is False
    states = json.loads((slice_dirs / "data" / "pins" / "states.json").read_text())
    assert {p["chamber"] for p in states} == {"senate"}


def test_every_dossier_is_contract_valid(slice_dirs):
    files = list((slice_dirs / "data" / "dossiers").glob("*.json"))
    assert len(files) == 3
    for f in files:
        d = json.loads(f.read_text())
        dossiers.validate(d)                       # no provenance, no publish
        assert d["schema_version"] == "1.0"
        assert set(d["identity"]["party"]) == {"code", "display"}


def test_pending_ideology_when_insufficient_votes(slice_dirs):
    sam = next(json.loads(f.read_text()) for f in (slice_dirs / "data" / "dossiers").glob("*.json")
               if json.loads(f.read_text())["identity"]["full_name"] == "Sam Sen")
    assert sam["ideology"]["status"] == "pending_insufficient_votes"
    assert sam["ideology"]["score"] is None


def test_spine_gate_fails_closed():
    """Below SPINE_RESOLUTION_MIN the crosswalk raises rather than publish partial."""
    bad = [{"id": {}, "name": {"first": "No", "last": "Id"}} for _ in range(10)]
    with pytest.raises(RuntimeError, match="spine resolution"):
        list(legislators.to_spine_rows(bad))


def test_ideology_computed_as_of_is_retrieval_date(slice_dirs):
    """DW-NOMINATE is re-estimated as votes accrue: the manifest's retrieved_at
    (not the congress start) is the honest as-of for a published score."""
    jane = next(json.loads(f.read_text()) for f in (slice_dirs / "data" / "dossiers").glob("*.json")
                if json.loads(f.read_text())["identity"]["full_name"] == "Jane Rep")
    assert jane["ideology"]["provenance"]["retrieved_at"] == RETRIEVED_AT
    assert jane["ideology"]["score"] == 0.512


def test_build_provenance_fails_closed_without_manifest(tmp_path):
    """No manifest = no vouched retrieval time: build must refuse to fabricate
    freshness (rule #1: no provenance, no publish)."""
    raw = tmp_path / "raw"
    (raw / "unitedstates_legislators").mkdir(parents=True)
    (raw / "unitedstates_legislators" / "legislators-current.json").write_text(json.dumps(LEGS))
    db = str(tmp_path / "wh.duckdb")
    transform.run(raw_dir=raw, db_path=db)
    with pytest.raises(dossiers.ProvenanceError, match="retrieved_at"):
        build.run(db_path=db, out_dir=tmp_path / "data", raw_dir=raw)


def test_coverage_reports_freshness_vs_sla(slice_dirs):
    """coverage.json computes age_hours/within_sla, not just echoed timestamps
    (SETUP §6: 'all sources within SLA' must be checkable from the dashboard)."""
    cov = json.loads((slice_dirs / "data" / "coverage.json").read_text())
    for k, row in cov["sources"].items():
        assert row["retrieved_at"] == RETRIEVED_AT
        assert isinstance(row["age_hours"], (int, float))
        assert isinstance(row["within_sla"], bool)
    # snapshot is 1h old — within every registered SLA (tightest is 24h)
    assert all(row["within_sla"] for row in cov["sources"].values())
