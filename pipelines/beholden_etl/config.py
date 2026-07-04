"""Source registry + SLAs. Mirrors data-contracts v1 §6 — adding a source here
requires a methodology entry and a coverage-dashboard row (enforced in CI)."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Source:
    key: str                 # provenance enum value
    base_url: str
    freshness_sla_hours: int # alert threshold, mirrors PRD G2
    requires_api_key: bool = False

SOURCES: dict[str, Source] = {
    "congress.gov": Source("congress.gov", "https://api.congress.gov/v3", 24, True),
    "unitedstates_legislators": Source(
        "unitedstates_legislators",
        "https://raw.githubusercontent.com/unitedstates/congress-legislators/main", 168),
    "voteview": Source("voteview", "https://voteview.com/static/data/out", 24 * 60),
    "openstates": Source("openstates", "https://data.openstates.org", 24 * 7, True),
    "fec": Source("fec", "https://api.open.fec.gov/v1", 24 * 7, True),
    "house_clerk": Source("house_clerk", "https://disclosures-clerk.house.gov", 24),
    "senate_efd": Source("senate_efd", "https://efdsearch.senate.gov", 24),
    "census_tiger": Source("census_tiger", "https://www2.census.gov/geo/tiger", 24 * 365),
}

# Quality gates (pipeline FAILS closed — nothing partial publishes)
SPINE_RESOLUTION_MIN = 0.995
EXTRACT_CONFIDENCE_PUBLISH_THRESHOLD = 0.98
IDEOLOGY_MIN_VOTES = 20

# Publish targets (free-tier architecture §1)
R2_BUCKET = "beholden"
PAGES_DIST = "dist/data"     # serving artifacts (dossiers/stylefeeds/pins/…)
RAW_DIST = "dist/raw"        # immutable landed snapshots, per source

# Current scope of the federal legislative slice.
CONGRESS = 119
TILE_VINTAGE = "2024"
FEC_CYCLE = 2026     # two-year campaign-finance cycle covering the 119th Congress


def pipeline_version() -> str:
    """git tag of the ETL release, stamped into every provenance envelope.
    CI sets PIPELINE_VERSION from the etl-<year.week.hhmm> tag; falls back to
    the package version for local runs."""
    import os
    from . import __version__
    return os.environ.get("PIPELINE_VERSION") or f"dev-{__version__}"
