"""Congress.gov v3 client (ticket E2-1).
Keyed, rate-limited (5,000 req/hr), paginated (max 250/page), retrying."""
from __future__ import annotations
import os, time
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..config import SOURCES

BASE = SOURCES["congress.gov"].base_url
PAGE_LIMIT = 250
MIN_INTERVAL_S = 3600 / 5000 * 1.1  # stay 10% under the hourly cap


class CongressGovClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ["CONGRESS_GOV_API_KEY"]
        self._last_call = 0.0
        self._http = httpx.Client(timeout=30)

    def _throttle(self):
        wait = MIN_INTERVAL_S - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    @retry(stop=stop_after_attempt(5),
           wait=wait_exponential(multiplier=2, max=120),
           retry=retry_if_exception_type(httpx.HTTPStatusError))
    def get(self, path: str, **params) -> dict:
        self._throttle()
        r = self._http.get(f"{BASE}/{path.lstrip('/')}",
                           params={"api_key": self.api_key, "format": "json", **params})
        if r.status_code == 429:  # respect rate-limit responses explicitly
            time.sleep(60)
        r.raise_for_status()
        return r.json()

    def paged(self, path: str, list_key: str, **params):
        """Yield every item across pagination."""
        offset = 0
        while True:
            data = self.get(path, limit=PAGE_LIMIT, offset=offset, **params)
            items = data.get(list_key, [])
            yield from items
            if len(items) < PAGE_LIMIT:
                return
            offset += PAGE_LIMIT

    # --- typed convenience wrappers used by sync jobs ---
    def current_members(self, congress: int):
        return self.paged(f"member/congress/{congress}", "members", currentMember="true")

    def bills_updated_since(self, congress: int, since_iso: str):
        return self.paged(f"bill/{congress}", "bills",
                          fromDateTime=since_iso, sort="updateDate+desc")
