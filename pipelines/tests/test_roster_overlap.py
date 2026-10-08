"""Cross-lane: every registered roster spec (Sumner, Hendersonville, CTAS, MTAS) is distinct."""
from __future__ import annotations

from collections import Counter

from beholden_etl import config
from beholden_etl.sources import roster

SPECS = roster.specs()


def _dupes(values) -> list:
    return [v for v, n in Counter(values).items() if n > 1]


def test_no_two_specs_share_an_identity():
    assert _dupes(s.locality_id for s in SPECS) == []
    assert _dupes(s.ocd_id for s in SPECS) == []
    assert _dupes(s.source.source_key for s in SPECS) == []
    assert all(s.source.source_key in config.SOURCES for s in SPECS)


def test_the_overlapping_governments_appear_exactly_once():
    ocds = Counter(s.ocd_id for s in SPECS)
    for suffix in ("/county:sumner", "/place:hendersonville", "/place:nashville"):
        assert sum(n for o, n in ocds.items() if o.endswith(suffix)) == 1, suffix
    # Nashville-Davidson is one government: published via MTAS, not as a Davidson County body.
    assert not [o for o in ocds if o.endswith("/county:davidson")]


def test_no_person_id_is_produced_by_two_localities():
    ids = [roster.person_id(s, "Pat Example") for s in SPECS]
    assert _dupes(ids) == []
