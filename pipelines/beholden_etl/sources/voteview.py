"""Voteview DW-NOMINATE loader (ticket E2-6). Joins via ICPSR through the crosswalk."""
from __future__ import annotations
import csv, io
import httpx
from ..config import SOURCES, IDEOLOGY_MIN_VOTES

def members_url(congress: int) -> str:
    # Voteview groups outputs by kind; member tables live under /members/.
    return f"{SOURCES['voteview'].base_url}/members/HS{congress}_members.csv"


def member_scores_csv(congress: int) -> str:
    r = httpx.get(members_url(congress), timeout=120, follow_redirects=True)
    r.raise_for_status()
    return r.text

def to_score_rows(csv_text: str, congress: int, icpsr_to_person: dict[str, str]):
    """Yield ideology_scores rows. Members with too few votes -> status pending."""
    for row in csv.DictReader(io.StringIO(csv_text)):
        person_id = icpsr_to_person.get(str(int(float(row["icpsr"]))))
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
            "computed_as_of": row.get("congress_end_date") or f"{2025 + (congress-119)*2}-01-03",
        }
