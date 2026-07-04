"""FEC campaign-finance client (ticket E3). Keyed, throttled under the default
1,000 req/hr key limit, retrying. Amounts arrive from FEC in dollars; the spine
stores integer USD cents (DATA-CONTRACTS §2), so every value crosses to_cents().
"""
from __future__ import annotations

import os
import time

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..config import SOURCES

BASE = SOURCES["fec"].base_url
# ~537 candidate calls per run, well under 1,000/hr; a small gap keeps us polite
# and leaves headroom for retries without ever approaching the cap.
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
