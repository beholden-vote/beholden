"""FEC campaign-finance client (tickets E3 + WO-3). Keyed, throttled under the
default 1,000 req/hr key limit, retrying. E3 pulls candidate cycle totals; WO-3
resolves each candidate's principal committee and rolls up its itemized
individual contributions by employer (FEC's own aggregation) into top
contributors. Amounts arrive from FEC in dollars; the spine stores integer USD
cents (DATA-CONTRACTS §2), so every value crosses to_cents().
"""
from __future__ import annotations

import os
import time

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..config import SOURCES

BASE = SOURCES["fec"].base_url
# ~537 totals + ~537×2 contributor calls (committee resolve + by_employer) per
# run, still well under 1,000/hr; a 0.5s gap keeps us polite and leaves headroom
# for retries without ever approaching the cap.
MIN_INTERVAL_S = 0.5
_RETRYABLE = (httpx.HTTPStatusError, httpx.TransportError)


def to_cents(dollars) -> int | None:
    return None if dollars is None else round(float(dollars) * 100)


class FECClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("FEC_API_KEY") or ""
        if not self.api_key:
            raise RuntimeError("FEC_API_KEY is not set (see docs/SETUP.md §1)")
        self._last_call = 0.0
        self._http = httpx.Client(timeout=30)

    def _throttle(self):
        wait = MIN_INTERVAL_S - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    @retry(stop=stop_after_attempt(5),
           wait=wait_exponential(multiplier=2, max=120),
           retry=retry_if_exception_type(_RETRYABLE))
    def get(self, path: str, **params) -> dict:
        self._throttle()
        r = self._http.get(f"{BASE}/{path.lstrip('/')}",
                           params={"api_key": self.api_key, **params})
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 60)))
        r.raise_for_status()
        return r.json()

    def candidate_totals(self, candidate_id: str, cycle: int) -> dict | None:
        """Aggregate receipts/disbursements/cash-on-hand for a candidate in a
        cycle, or None when the candidate has no filings that cycle."""
        data = self.get(f"candidate/{candidate_id}/totals",
                        cycle=cycle, per_page=1, sort="-cycle")
        results = data.get("results") or []
        return results[0] if results else None

    def principal_committee(self, candidate_id: str, cycle: int) -> str | None:
        """Resolve the committee whose itemized contributions we roll up (WO-3):
        the candidate's principal campaign committee (designation P) for the
        cycle, falling back to any authorized committee if none is designated P.
        Returns None when the candidate has no committee that cycle — absent is
        not zero, so such a member simply gets no top_contributors."""
        data = self.get(f"candidate/{candidate_id}/committees",
                        designation="P", cycle=cycle, per_page=1)
        results = data.get("results") or []
        if results:
            return results[0].get("committee_id")
        # No principal committee this cycle: fall back to any authorized one.
        data = self.get(f"candidate/{candidate_id}/committees",
                        cycle=cycle, per_page=1)
        results = data.get("results") or []
        return results[0].get("committee_id") if results else None

    def top_contributors_by_employer(self, committee_id: str, cycle: int,
                                     per_page: int = 25) -> list[dict]:
        """FEC's own employer rollups of itemized individual contributions to a
        committee for a cycle, sorted by total descending (WO-3). Rows are FEC's
        {employer, total, count}; total is dollars (crosses to_cents at map).
        Returns [] when the committee has no itemized individual receipts."""
        data = self.get("schedules/schedule_a/by_employer",
                        committee_id=committee_id, cycle=cycle,
                        sort="-total", per_page=per_page)
        return data.get("results") or []


def cycle_row(person_id: str, candidate_id: str, cycle: int,
              totals: dict, as_of_fallback: str | None) -> dict | None:
    """FEC totals -> campaign_finance_cycles row (money in integer cents §2).
    as_of is NOT NULL in the spine; if FEC omits coverage_end_date we fall back
    to the fetch date, and drop the row (None) only if we have neither."""
    as_of = (totals.get("coverage_end_date") or "")[:10] or as_of_fallback
    if not as_of:
        return None
    return {
        "person_id": person_id,
        "cycle": cycle,
        "fec_committee_id": candidate_id,
        "total_raised_cents": to_cents(totals.get("receipts")),
        "total_spent_cents": to_cents(totals.get("disbursements")),
        "cash_on_hand_cents": to_cents(totals.get("last_cash_on_hand_end_period")),
        "as_of": as_of,
    }


def contributor_rows(person_id: str, cycle: int, by_employer: list[dict]) -> list[dict]:
    """FEC by_employer rollups -> top_contributors rows (money in integer cents
    §2). One row per employer, ranked 1..N by the order FEC returns (sorted by
    -total). contributor_name is the employer verbatim as FEC reports it —
    blank / 'NOT EMPLOYED' / 'RETIRED' are legitimate categories, kept as-is and
    never editorialized or filtered (WO-3 contract care). Rank is the only
    computed field, applied by one fixed rule identical for every candidate."""
    rows = []
    for rank, r in enumerate(by_employer, 1):
        cents = to_cents(r.get("total"))
        if cents is None:                       # FEC omitted a total: not publishable
            continue
        rows.append({
            "person_id": person_id,
            "cycle": cycle,
            "contributor_name": (r.get("employer") or "").strip(),
            "total_cents": cents,
            "rank": rank,
        })
    return rows
