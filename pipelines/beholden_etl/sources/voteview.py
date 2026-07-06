"""Voteview loaders: DW-NOMINATE members (ticket E2-6) + roll-call votes (WO-1).
All join to the spine via ICPSR through the person_identifiers crosswalk."""
from __future__ import annotations
import csv
import io
import re

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import SOURCES, IDEOLOGY_MIN_VOTES
from . import congress_gov

# First year of the 119th Congress; each congress spans two years.
_BASE_CONGRESS, _BASE_YEAR = 119, 2025


def members_url(congress: int) -> str:
    # Voteview groups outputs by kind; member tables live under /members/.
    return f"{SOURCES['voteview'].base_url}/members/HS{congress}_members.csv"


def votes_url(congress: int) -> str:
    # Per-member cast codes, one row per (rollnumber, icpsr) — ~500k rows/congress.
    return f"{SOURCES['voteview'].base_url}/votes/HS{congress}_votes.csv"


def rollcalls_url(congress: int) -> str:
    # One row per roll call: date, session, clerk number, tallies, question/result.
    return f"{SOURCES['voteview'].base_url}/rollcalls/HS{congress}_rollcalls.csv"


def congress_end_date(congress: int) -> str:
    """Final day of a congress (Jan 3 two years after it convenes)."""
    return f"{_BASE_YEAR + (congress - _BASE_CONGRESS) * 2 + 2}-01-03"


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=60))
def member_scores_csv(congress: int) -> str:
    """Retrying: unattended nightly — transient failures must not kill the run."""
    r = httpx.get(members_url(congress), timeout=120, follow_redirects=True)
    r.raise_for_status()
    return r.text


def member_icpsr_to_bioguide(csv_text: str) -> dict[str, str]:
    """{normalized_icpsr: bioguide_id} for House/Senate members of a Voteview
    members file. Voteview is the ICPSR authority and carries bioguide_id for every
    member, so this fills the ICPSR crosswalk for current members whose
    congress-legislators entry has no id.icpsr yet (freshmen lag). icpsr is
    normalized exactly as to_score_rows / to_position_rows key it, so the maps
    line up. Rows lacking either id (or non-legislator rows) are skipped."""
    out: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row.get("chamber") not in ("House", "Senate"):
            continue
        bio = (row.get("bioguide_id") or "").strip()
        raw_icpsr = (row.get("icpsr") or "").strip()
        if not bio or not raw_icpsr:
            continue
        try:
            out[str(int(float(raw_icpsr)))] = bio
        except ValueError:
            continue
    return out


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


# --- roll-call votes (WO-1) --------------------------------------------------
@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=60))
def votes_csv(congress: int) -> str:
    """Retrying: the votes table is ~9 MB, still a single static GET."""
    r = httpx.get(votes_url(congress), timeout=300, follow_redirects=True)
    r.raise_for_status()
    return r.text


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=60))
def rollcalls_csv(congress: int) -> str:
    """Retrying: unattended nightly — transient failures must not kill the run."""
    r = httpx.get(rollcalls_url(congress), timeout=120, follow_redirects=True)
    r.raise_for_status()
    return r.text


# Voteview cast_code families (codebook, documented at /methodology#roll-call-votes):
# 1-3 = yea variants (yea, paired-yea, announced-yea), 4-6 = nay variants,
# 7-8 = present, 9 = not voting, 0 = not a member of the chamber for this vote.
CAST_CODE_POSITION = {1: "yea", 2: "yea", 3: "yea",
                      4: "nay", 5: "nay", 6: "nay",
                      7: "present", 8: "present", 9: "not_voting"}

_BILL_NUMBER_RE = re.compile(r"^([A-Z]+)0*(\d+)$")


def roll_call_id(congress: int, chamber: str, rollnumber: int | str) -> str:
    """Stable spine id: 'us/{congress}/{house|senate}/{voteview rollnumber}'."""
    return f"us/{congress}/{chamber.lower()}/{rollnumber}"


def normalize_bill_id(bill_number: str, congress: int) -> str | None:
    """Voteview's 'HR4593' / 'HRES5' -> the bills-spine id ('us/119/hr/4593'),
    through the same congress_gov normalizer the bills table was keyed with.
    None when the token isn't letters+digits (speaker elections leave it blank);
    non-bill ids (Senate nominations, 'PN…') normalize but never match a bills
    row, so the transform links NULL — procedural votes are legitimate."""
    m = _BILL_NUMBER_RE.match((bill_number or "").strip().upper()
                              .replace(".", "").replace(" ", ""))
    if not m:
        return None
    return congress_gov.bill_id({"congress": congress, "type": m.group(1),
                                 "number": m.group(2)})


def roll_call_public_url(chamber: str, congress: int, session: int | str,
                         clerk_rollnumber: int | str, date: str) -> str:
    """Official roll-call record URL (both patterns verified live 2026-07-05).
    Both chambers number votes per *session* (Voteview's rollnumber is
    congress-cumulative), so the official sites key on clerk_rollnumber."""
    if chamber == "house":
        return f"https://clerk.house.gov/Votes/{date[:4]}{int(clerk_rollnumber)}"
    return ("https://www.senate.gov/legislative/LIS/roll_call_votes/"
            f"vote{congress}{session}/vote_{congress}_{session}_{int(clerk_rollnumber):05d}.htm")


def to_roll_call_rows(csv_text: str, congress: int, known_bill_ids: set[str]):
    """Yield roll_calls rows from the rollcalls CSV. held_at is the vote date at
    midnight UTC (the CSV carries no time of day). Rows missing a date or any
    question/description are skipped — a placeholder question would be an
    invented fact — and their positions drop with them via the FK id set."""
    for row in csv.DictReader(io.StringIO(csv_text)):
        chamber = (row.get("chamber") or "").lower()
        if str(row.get("congress")) != str(congress) or chamber not in ("house", "senate"):
            continue
        question = (row.get("vote_question") or "").strip() or (row.get("vote_desc") or "").strip()
        if not (row.get("rollnumber") and row.get("date") and question):
            continue
        bill_id = normalize_bill_id(row.get("bill_number") or "", congress)
        yield {
            "roll_call_id": roll_call_id(congress, chamber, row["rollnumber"]),
            "bill_id": bill_id if bill_id in known_bill_ids else None,
            "chamber": chamber,
            "question": question,
            "held_at": f"{row['date']} 00:00:00+00",
            "result": (row.get("vote_result") or "").strip() or "(not recorded)",
        }


def to_position_rows(csv_text: str, congress: int, icpsr_to_person: dict[str, str],
                     valid_roll_call_ids: set[str]):
    """Yield vote_positions rows, joined through the ICPSR crosswalk. cast_code
    0 (not a member for this vote) and unknown codes are skipped, as are ICPSRs
    outside the crosswalk (the President votes in Voteview's House files) and
    roll calls the transform didn't ingest (FK integrity)."""
    for row in csv.DictReader(io.StringIO(csv_text)):
        if str(row.get("congress")) != str(congress):
            continue
        try:
            cast = int(float(row.get("cast_code") or ""))
            icpsr = str(int(float(row.get("icpsr") or "")))
        except ValueError:
            continue  # malformed row: a data gap, not an outage
        position = CAST_CODE_POSITION.get(cast)
        person_id = icpsr_to_person.get(icpsr)
        if not position or not person_id:
            continue
        rcid = roll_call_id(congress, row.get("chamber") or "", row.get("rollnumber") or "")
        if rcid not in valid_roll_call_ids:
            continue
        yield {"roll_call_id": rcid, "person_id": person_id, "position": position}


def to_rollcall_meta(csv_text: str, congress: int) -> dict[str, dict]:
    """roll_call_id -> {yea, nay, date, url}: the salience inputs (tallies for the
    closeness score) + the official record link. These live only in the raw
    rollcalls CSV — the spine table keeps the contract columns, and build reads
    raw for the rest (same pattern as cosponsored counts read at build time)."""
    meta: dict[str, dict] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        chamber = (row.get("chamber") or "").lower()
        if str(row.get("congress")) != str(congress) or chamber not in ("house", "senate"):
            continue
        if not (row.get("rollnumber") and row.get("date")
                and row.get("session") and row.get("clerk_rollnumber")):
            continue
        meta[roll_call_id(congress, chamber, row["rollnumber"])] = {
            "yea": int(float(row.get("yea_count") or 0)),
            "nay": int(float(row.get("nay_count") or 0)),
            "date": row["date"],
            "url": roll_call_public_url(chamber, congress, row["session"],
                                        row["clerk_rollnumber"], row["date"]),
        }
    return meta
