"""Area facts: areas/county/{st}.json and areas/place/{st}.json (WO-34, contracts §8.4).

One file per state per level, keyed by Census GEOID, so the clicked polygon's own `geoid`
tile property is the join key. Two sources, two envelopes: the Gazetteer cites `name` and
`land_sqmi`; the ACS cites every {estimate, moe} pair. Both come from ctx.provenance(),
never by hand (rule #1), and are checked again with the dossier validator before a byte
is written.

Every gate runs here too, not only at fetch: a snapshot hydrated from the lake is
re-verified, and the cross-source row-count gate can only run once both sources are in
hand. A failure raises and halts the build (rule #2).

Output is deterministic: areas sorted by GEOID, keys sorted, and `generated_at` is the
snapshot's own retrieval time rather than the wall clock, so an unchanged snapshot is
byte-identical however many times it is built.
"""
from __future__ import annotations

import json

from ..sources import census_areas as C
from . import dossiers
from .context import BuildContext

SCHEMA_VERSION = "1.0"


def publish(ctx: BuildContext) -> dict[str, int]:
    sources = ctx.manifest.get("sources", {})
    if "census_acs" not in sources:
        # No survey was fetched (CENSUS_API_KEY unset). Nothing is published and the zero
        # counts say so in coverage.json; a half-built area file would be worse.
        print("areas: census_acs not in the fetch manifest - no area files this run")
        return {"area_counties": 0, "area_places": 0}
    for key, pinned in (("census_acs", C.ACS_YEAR), ("census_gazetteer", C.GAZETTEER_VINTAGE)):
        got = sources.get(key, {}).get("vintage")
        if got != pinned:
            raise C.CensusError(f"{key}: the snapshot is vintage {got!r} but the code pins "
                                f"{pinned}; re-run fetch with full=true after a vintage bump")

    acs_counties, acs_places, _ = C.load_acs(ctx.raw_dir)
    gaz_counties, gaz_places = C.load_gazetteer(ctx.raw_dir)
    C.check_row_counts("county", acs_counties, gaz_counties)
    C.check_row_counts("place", acs_places, gaz_places)

    geography = {"vintage": C.GAZETTEER_VINTAGE,
                 "provenance": ctx.provenance("census_gazetteer", C.GAZETTEER_SOURCE_URL)}
    survey = {"vintage": C.ACS_PERIOD,
              "provenance": ctx.provenance("census_acs", C.ACS_SOURCE_URL)}
    generated_at = max(sources["census_acs"]["retrieved_at"],
                       sources["census_gazetteer"]["retrieved_at"])

    counts = {"area_counties": 0, "area_places": 0}
    for level, acs, gaz, count_key in (("county", acs_counties, gaz_counties, "area_counties"),
                                       ("place", acs_places, gaz_places, "area_places")):
        # Incorporated places only: a census designated place is a statistical area with
        # no government (the Gazetteer's functional status says which is which).
        keep = [g for g in sorted(acs) if level == "county" or gaz[g]["active"]]
        for fips, st in C.STATES.items():
            areas = {g: {"name": gaz[g]["name"], "land_sqmi": gaz[g]["land_sqmi"],
                         **C.survey_fields(acs[g], g)}
                     for g in keep if g.startswith(fips)}
            doc = {"schema_version": SCHEMA_VERSION, "level": level, "state": st,
                   "generated_at": generated_at, "geography": geography,
                   "survey": survey, "areas": areas}
            for section in ("geography", "survey"):
                dossiers._check_provenance({"person_id": f"areas/{level}/{st}", **doc}, section)
            path = ctx.out / "areas" / level / f"{st}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")),
                            encoding="utf-8")
            counts[count_key] += len(areas)
    print(f"areas: {counts['area_counties']} counties, {counts['area_places']} places "
          f"(of {len(acs_places)} in the survey; census designated places and "
          f"non-governmental places excluded) -> {ctx.out / 'areas'}")
    return counts
