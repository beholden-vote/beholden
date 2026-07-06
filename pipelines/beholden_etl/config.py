"""Source registry + SLAs. Mirrors data-contracts v1 §6 — adding a source here
requires a methodology entry and a coverage-dashboard row (enforced in CI)."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Source:
    key: str                 # provenance enum value
    base_url: str
    freshness_sla_hours: int # alert threshold, mirrors PRD G2
    requires_api_key: bool = False

# freshness_sla_hours is BOTH the coverage-dashboard alert threshold AND (WO-10) the
# incremental re-fetch threshold: a hydrated snapshot younger than its SLA is reused
# rather than re-fetched. With a ~24h nightly cadence, an SLA of X hours re-fetches
# that source roughly every ceil(X/24) nights — so fast movers stay ≤24-48h fresh
# while the parallel + resume-on-failure win comes without starving refreshes.
SOURCES: dict[str, Source] = {
    "congress.gov": Source("congress.gov", "https://api.congress.gov/v3", 24, True),   # bills/sponsors daily
    "unitedstates_legislators": Source(
        "unitedstates_legislators",
        "https://raw.githubusercontent.com/unitedstates/congress-legislators/main", 36),  # roster/committees rarely change
    "voteview": Source("voteview", "https://voteview.com/static/data/out", 36),   # votes/ideology: every other night, not 60 days
    "openstates": Source("openstates", "https://data.openstates.org", 72, True),  # state legislators change slowly
    "fec": Source("fec", "https://api.open.fec.gov/v1", 72, True),   # donor filings post periodically
    "house_clerk": Source("house_clerk", "https://disclosures-clerk.house.gov", 24),   # new trades daily
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
TILE_VINTAGE = "2025"  # Census cartographic-boundary release (GENZ2025); bump on new vintage
FEC_CYCLE = 2026     # two-year campaign-finance cycle covering the 119th Congress

# WO-9 WA PDC pilot readiness. OFF: the itemized↔summary control-total gate does
# not reconcile on real current-cycle data — the two Socrata feeds use different
# filer_id formats (itemized "EWINS 258" vs summary "EWINS2 258") and the summary
# has coverage gaps, so the (correct) fail-closed gate rejects dozens of groups.
# This is a readiness switch for a not-yet-surfaced experimental source, NOT a gate
# bypass: when enabled the gate still runs and still halts on any mismatch. Re-enable
# once the itemized↔summary join is fixed (WO-9 reconciliation follow-up).
WA_PDC_ENABLED = False


def pipeline_version() -> str:
    """git tag of the ETL release, stamped into every provenance envelope.
    CI sets PIPELINE_VERSION from the etl-<year.week.hhmm> tag; falls back to
    the package version for local runs."""
    import os
    from . import __version__
    return os.environ.get("PIPELINE_VERSION") or f"dev-{__version__}"
