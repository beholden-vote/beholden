"""Voteview DW-NOMINATE loader (ticket E2-6). Joins via ICPSR through the crosswalk."""
from __future__ import annotations
import csv
import io

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import SOURCES, IDEOLOGY_MIN_VOTES

# First year of the 119th Congress; each congress spans two years.
_BASE_CONGRESS, _BASE_YEAR = 119, 2025


def members_url(congress: int) -> str:
    # Voteview groups outputs by kind; member tables live under /members/.
    return f"{SOURCES['voteview'].base_url}/members/HS{congress}_members.csv"


def congress_end_date(congress: int) -> str:
    """Final day of a congress (Jan 3 two years after it convenes)."""
    return f"{_BASE_YEAR + (congress - _BASE_CONGRESS) * 2 + 2}-01-03"


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=60))
def member_scores_csv(congress: int) -> str:
    """Retrying: unattended nightly — transient failures must not kill the run."""
    r = httpx.get(members_url(congress), timeout=120, follow_redirects=True)
    r.raise_for_status()
    return r.text


def to_score_rows(csv_text: str, congress: int, icpsr_to_person: dict[str, str],
                  as_of: str | None = None):
    """Yield ideology_scores rows. Members with too few votes -> status pending.

    computed_as_of precedence: the snapshot's retrieval date (`as_of`, from the
    fetch manifest — DW-NOMINATE is re-estimated as votes accrue, so retrieval
    time IS the honest as-of) > a congress_end_date column if Voteview ever
    ships one > the congress's end boundary. Never the congress start: a score
    can't be "as of" a date before the votes it summarizes.
    """
    for row in csv.DictReader(io.StringIO(csv_text)):
        raw_icpsr = (row.get("icpsr") or "").strip()
        try:
            icpsr = str(int(float(raw_icpsr)))
        except ValueError:
            continue  # malformed/blank icpsr: a data gap, not an outage — the
            #           spine-resolution gate still fails closed on systemic loss
        person_id = icpsr_to_person.get(icpsr)
        if not person_id:
            continue  # non-member rows (e.g., President) or crosswalk gap -> quarantine handled upstream
        n_votes = int(row.get("nominate_number_of_votes") or 0)
        pending = n_votes < IDEOLOGY_MIN_VOTES or not row.get("nominate_dim1")
        yield {
            "person_id": person_id,
            "scheme": "dw_nominate_dim1",
            "score": None if pending else float(row["nominate_dim1"]),
            "status": "pending_insufficient_votes" if pending else "ok",
            "scope": str(congress),
            "computed_as_of": (as_of or "")[:10] or row.get("congress_end_date")
                              or congress_end_date(congress),
        }
