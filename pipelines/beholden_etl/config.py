"""Source registry + SLAs. Mirrors data-contracts v1 §6 — adding a source here
requires a methodology entry and a coverage-dashboard row (enforced in CI)."""
from dataclasses import dataclass

# ── Credibility grades (WO-28) ───────────────────────────────────────────────
# A published grade tells the reader HOW a fact was obtained, so a dossier that
# mixes a bulk API with an OCR'd scan doesn't render as uniformly trustworthy.
#
# THE LINE THAT MAKES THIS DEFENSIBLE: a grade describes the extraction METHOD,
# never a failed validation. A control-total mismatch means the numbers are
# WRONG, not low-confidence — it still halts the pipeline and stays quarantined
# (rule #2, fail closed). If a failing gate could be downgraded instead of
# halted, the scale would launder bad data and rule #2 would be dead. Grades
# make us more permissive about SOURCE QUALITY, never about CORRECTNESS.
#
# A reason implies its grade — they are one registry, not two fields that can
# drift apart, so "grade A, extracted by OCR" is unrepresentable by construction.
GRADE_REASONS: dict[str, str] = {
    # A — official structured source, deterministic, no model in the path.
    "official_structured": "A",   # bulk API/CSV/YAML, or a link-out to an official filing
    # B — official document, born-digital text; deterministic parse + anchored
    #     verification, reconciling against a control total the document carries.
    "official_document_text": "B",
    # C — official document that required OCR; anchored verification passed and
    #     the document reconciled. The text layer is ours, the document is theirs.
    "official_document_ocr": "C",
    # B — an official government WEB PAGE with structured markup (microformats,
    #     one post per officeholder), parsed deterministically and reconciled
    #     against the body's own seat count. Below a bulk feed because we parse
    #     a document the government publishes for humans, not a dataset it
    #     publishes for machines — a real difference the reader should see.
    "official_web_roster": "B",
    # D — derived or inferred: the fact is our reasoning over official inputs,
    #     not a transcription of them.
    "derived_geometry": "D",      # e.g. district polygons dissolved from precincts
    "inferred_from_roster": "D",  # e.g. per-member positions from "unanimous" + present roster
    "crowd_edited": "D",          # e.g. Wikidata — official-adjacent, not official
}
GRADES = ("A", "B", "C", "D")


def grade_for(grade_reason: str) -> str:
    """Grade implied by a reason. Unregistered reason => fail closed, because an
    ungraded fact would render as though it were as good as a bulk API row."""
    try:
        return GRADE_REASONS[grade_reason]
    except KeyError:
        raise ValueError(
            f"unregistered grade_reason {grade_reason!r} — add it to "
            "config.GRADE_REASONS with its grade, and to the /methodology anchor"
        ) from None


@dataclass(frozen=True)
class Source:
    key: str                 # provenance enum value
    base_url: str
    freshness_sla_hours: int # alert threshold, mirrors PRD G2
    requires_api_key: bool = False
    # Default credibility reason for facts from this source. A source may emit a
    # LOWER grade per fact (build._provenance takes an override) — e.g. minutes
    # that are grade B for a printed roll call and D for an inferred position —
    # but it may never emit one without a registered reason.
    grade_reason: str = "official_structured"

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
    # WO-17: the openstates family now carries state bills/roll-call votes (v3
    # API, OPENSTATES_KEY) alongside the people CSVs — votes move daily, so the
    # SLA drops from 72h to 24h. One registry row for the whole family keeps
    # freshness/coverage honest for the fastest-moving fact it publishes; the
    # people CSVs it drags along nightly are cheap unauthenticated GETs.
    "openstates": Source("openstates", "https://data.openstates.org", 24, True),
    "fec": Source("fec", "https://api.open.fec.gov/v1", 72, True),   # donor filings post periodically
    "house_clerk": Source("house_clerk", "https://disclosures-clerk.house.gov", 24),   # new trades daily
    "senate_efd": Source("senate_efd", "https://efdsearch.senate.gov", 24),
    "census_tiger": Source("census_tiger", "https://www2.census.gov/geo/tiger", 24 * 365),
    # WO-15: crowd-edited encyclopedia, used ONLY for identity.education (P69
    # educated-at + P512/P582 qualifiers). Every education fact's provenance
    # envelope points at THIS source key (never unitedstates_legislators), and
    # the dossier carries a verbatim caveat alongside it — labeled trust, not
    # silent equivalence with official sources. Rarely changes -> a 30-day SLA.
    # WO-28: grade D. The education block already shipped a verbatim credibility
    # caveat; the grade makes that same judgement machine-readable and filterable
    # instead of prose the reader has to notice.
    "wikidata": Source("wikidata", "https://www.wikidata.org", 24 * 30,
                       grade_reason="crowd_edited"),
    # WO-9/WO-19: WA PDC bulk campaign finance (Tier A trusted extraction,
    # license Public Domain). Two Socrata feeds fetched as one coherent pair
    # (itemized + summary control totals) — fetch never freshness-skips this
    # source (see jobs/fetch._SLA_KEY), so the SLA here governs the coverage
    # dashboard only. New contributions post daily; summaries recalc in-step.
    "wa_pdc": Source("wa_pdc", "https://data.wa.gov", 36),
    # WO-22 local pilot. ONE REGISTRY ROW PER LOCALITY, deliberately: there is no
    # national local roster, so coverage, freshness and grade are only meaningful
    # per government. Rosters change at elections, not nightly — a 7-day SLA
    # keeps the dashboard honest without re-fetching a static page every night.
    "sumner_county": Source("sumner_county", "https://sumnercountytn.gov", 24 * 7,
                            grade_reason="official_web_roster"),
    "hendersonville": Source("hendersonville", "https://www.hvilletn.org", 24 * 7,
                             grade_reason="official_web_roster"),
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

# WO-17 pilot: states whose bills + roll-call votes are crawled from the
# OpenStates v3 API (sources/openstates_votes.py). Chosen from the research
# doc's best-coverage list (docs/research/state-votes-evaluation.md §3).
#
# FREE-TIER INTERIM (2026-07-08): the default OpenStates key is 10 req/min ·
# 500 req/day (verified live 2026-07-07 — a 5-state cold-start 429-stormed).
# TN's whole biennium is ~100-150 pages (~150 requests, votes/sponsorships
# embedded), which fits 500/day with room to spare, so we validate the full
# live path (auth, pacing, parse, exact ocd-person join, dossier Record tab,
# coverage) on TN alone now. The big states (ca/tx/ny/fl) can't fit the free
# daily cap and wait for the requested approved tier key; when it lands,
# restore ["ca","tx","ny","fl","tn"] and drop OPENSTATES_MIN_INTERVAL_S.
STATE_VOTES_SLUGS = ["tn"]
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
