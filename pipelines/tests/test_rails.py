"""WO-32: the rails later work orders build on — the artifact-writer registry
and the additive pins field. Kept out of test_pipeline.py on purpose; see
conftest.py."""
from __future__ import annotations

import json

import pytest

from beholden_etl.build import dossiers
from beholden_etl.jobs import build


def _rebuild(slice_dirs, monkeypatch, writers):
    monkeypatch.setattr(build, "ARTIFACT_WRITERS", writers)
    return build.run(db_path=str(slice_dirs / "wh.duckdb"),
                     out_dir=slice_dirs / "data", raw_dir=slice_dirs / "raw")


def test_registered_writer_runs_and_its_counts_reach_coverage(slice_dirs, monkeypatch):
    """A writer is one registry line: it gets the context, writes under the
    serving root, and whatever it counts lands in coverage.json — no edit to
    build.run(), which is the whole point of the registry."""
    seen = {}

    def publish(ctx):
        seen["holders"] = len(ctx.holders)
        prov = ctx.provenance("congress.gov", "https://www.congress.gov/")
        (ctx.out / "probe").mkdir(parents=True, exist_ok=True)
        (ctx.out / "probe" / "x.json").write_text(json.dumps({"provenance": prov}))
        return {"probe_docs": 1}

    coverage = _rebuild(slice_dirs, monkeypatch, [("probe", publish)])

    assert seen["holders"] > 0
    assert coverage["counts"]["probe_docs"] == 1
    assert json.loads((slice_dirs / "data" / "coverage.json").read_text())["counts"]["probe_docs"] == 1
    # The context's provenance factory is build's own, so the envelope carries
    # every required key and a grade that matches its reason.
    prov = json.loads((slice_dirs / "data" / "probe" / "x.json").read_text())["provenance"]
    assert dossiers.REQUIRED_PROVENANCE <= set(prov)


def test_writer_cannot_publish_an_unregistered_source(slice_dirs, monkeypatch):
    """Rule #1 holds for writers too. The context hands out build's provenance
    factory precisely so a new artifact cannot invent an envelope for a source
    nobody registered or the manifest cannot vouch for."""
    def publish(ctx):
        ctx.provenance("a_site_we_scraped", "https://example.invalid/")
        return {}

    with pytest.raises(dossiers.ProvenanceError):
        _rebuild(slice_dirs, monkeypatch, [("bad", publish)])


def test_failing_writer_halts_the_build(slice_dirs, monkeypatch):
    """Rule #2: a writer that raises takes the build down with it. A missing
    artifact is a gate failure, never something to log and carry on past."""
    def publish(ctx):
        raise RuntimeError("control total mismatch")

    with pytest.raises(RuntimeError, match="control total mismatch"):
        _rebuild(slice_dirs, monkeypatch, [("boom", publish)])


def test_pins_carry_term_end_or_an_honest_null(slice_dirs):
    """Every pin has the key; the value is the source's own term end or null.
    Never inferred — an official whose source publishes no end date shows none."""
    pins = json.loads((slice_dirs / "data" / "pins" / "cd.json").read_text())
    assert pins and all("term_ends" in p for p in pins)
    assert any(p["term_ends"] for p in pins)          # the federal fixture has real ends
