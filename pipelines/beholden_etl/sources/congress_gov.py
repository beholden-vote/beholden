"""Congress.gov v3 client (ticket E2-1).
Keyed, rate-limited (5,000 req/hr), paginated (max 250/page), retrying."""
from __future__ import annotations
import os
import time

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..config import SOURCES

BASE = SOURCES["congress.gov"].base_url
PAGE_LIMIT = 250
MIN_INTERVAL_S = 3600 / 5000 * 1.1  # stay 10% under the hourly cap

# Transient transport failures (resets, timeouts) retry just like HTTP 5xx —
# the nightly runs unattended, so a blip must not kill the whole pipeline.
_RETRYABLE = (httpx.HTTPStatusError, httpx.TransportError)


class CongressGovClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("CONGRESS_GOV_API_KEY") or ""
        if not self.api_key:
            raise RuntimeError("CONGRESS_GOV_API_KEY is not set (see docs/SETUP.md §1)")
        self._last_call = 0.0
        # 60s read timeout + generous connect: congress.gov can be slow to first
        # byte on the busier per-member endpoints; a monolithic ~2h fetch makes
        # thousands of calls, so a single slow response must not be fatal.
        self._http = httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0))

    def _throttle(self):
        wait = MIN_INTERVAL_S - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    @retry(stop=stop_after_attempt(8),
           wait=wait_exponential(multiplier=2, max=60),
           retry=retry_if_exception_type(_RETRYABLE))
    def get(self, path: str, **params) -> dict:
        self._throttle()
        r = self._http.get(f"{BASE}/{path.lstrip('/')}",
                           params={"api_key": self.api_key, "format": "json", **params})
        if r.status_code == 429:  # respect rate-limit responses explicitly
            time.sleep(float(r.headers.get("Retry-After", 60)))
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
        # NB: the value is "updateDate desc" (a space, urlencoded to %20) — the
        # `+` seen in API docs is already-encoded; passing it raw sends %2B.
        return self.paged(f"bill/{congress}", "bills",
                          fromDateTime=since_iso, sort="updateDate desc")

    def sponsored_legislation(self, bioguide: str) -> list[dict]:
        """Every bill this member sponsored (bounded — members sponsor tens to a
        few hundred). Walked fully so became-law counts are exact, not sampled."""
        return list(self.paged(f"member/{bioguide}/sponsored-legislation",
                               "sponsoredLegislation"))

    def cosponsored_count(self, bioguide: str) -> int:
        """Just the total — cosponsorships run to the thousands, and the dossier
        needs the count, not every row. One call via pagination.count."""
        data = self.get(f"member/{bioguide}/cosponsored-legislation", limit=1, offset=0)
        return int((data.get("pagination") or {}).get("count") or 0)

    def member_detail(self, bioguide: str) -> dict:
        """GET /member/{bioguide} (WO-15): the one extra call per member beyond
        current_members — carries birthYear, partyHistory[] (party-switch
        history), leadership[] (role + congress), and addressInformation (DC
        office/phone) that the roster-list endpoint omits. Uses the SAME
        throttled `get()` as every other call, so this ~537-call addition is
        governed by the one existing rate governor (no second limiter)."""
        return self.get(f"member/{bioguide}").get("member") or {}


# --- bill normalization (pure; unit-tested) --------------------------------
# congress.gov bill `type` -> the slug used in our bill_id 'us/{congress}/{slug}/{num}'.
_BILL_TYPE_SLUG = {"HR": "hr", "S": "s", "HRES": "hres", "SRES": "sres",
                   "HJRES": "hjres", "SJRES": "sjres", "HCONRES": "hconres",
                   "SCONRES": "sconres"}


def bill_id(item: dict) -> str:
    t = (item.get("type") or "").upper().replace(".", "")
    return f"us/{item['congress']}/{_BILL_TYPE_SLUG.get(t, t.lower())}/{item['number']}"


def derive_status(item: dict) -> str:
    """Map latestAction free text to the bills.status enum (DATA-CONTRACTS §2).
    Deliberately conservative: unknown -> 'introduced', never a stronger claim."""
    text = ((item.get("latestAction") or {}).get("text") or "").lower()
    if "became public law" in text or "became law" in text:
        return "law"
    if "vetoed" in text or "veto message" in text:
        return "vetoed"
    if "presented to president" in text or "passed both" in text:
        return "passed_both"
    if "passed" in text and ("house" in text or "senate" in text):
        return "passed_chamber"
    if "failed" in text or "rejected" in text:
        return "failed"
    if "referred to" in text or "committee" in text:
        return "committee"
    return "introduced"


# bill_id slug -> the path segment congress.gov uses in public bill URLs.
_BILL_URL_PATH = {"hr": "house-bill", "s": "senate-bill",
                  "hres": "house-resolution", "sres": "senate-resolution",
                  "hjres": "house-joint-resolution", "sjres": "senate-joint-resolution",
                  "hconres": "house-concurrent-resolution", "sconres": "senate-concurrent-resolution"}


def bill_public_url(bill_id_str: str) -> str:
    """Public congress.gov page for a bill_id like 'us/119/hr/1234' (the citation
    link a dossier shows — every legislative fact must be traceable)."""
    _, cong, slug, num = bill_id_str.split("/")
    return f"https://www.congress.gov/bill/{cong}th-congress/{_BILL_URL_PATH.get(slug, 'bill')}/{num}"


def bill_row(item: dict) -> dict:
    pa = (item.get("policyArea") or {}).get("name")
    return {
        "bill_id": bill_id(item),
        "jurisdiction": "us",
        "session": str(item["congress"]),
        "title": item.get("title") or "(untitled)",
        "status": derive_status(item),
        "introduced_on": item.get("introducedDate") or None,
        "latest_action_on": (item.get("latestAction") or {}).get("actionDate") or None,
        "policy_areas": [pa] if pa else None,
    }


# --- WO-15: member-detail normalization (pure; unit-tested) -----------------
def birth_year(detail: dict) -> int | None:
    """member_detail's own `birthYear` (a string in the v3 schema), or None —
    this REPLACES any need for Wikidata on this one fact; absent -> absent,
    never a guessed/derived year."""
    y = detail.get("birthYear")
    try:
        return int(y) if y not in (None, "") else None
    except (TypeError, ValueError):
        return None


def leadership_roles(detail: dict) -> list[dict]:
    """member_detail's `leadership[]` -> [{role, congress}], verbatim, dropping
    only entries missing the role name (never invented)."""
    out = []
    for item in detail.get("leadership") or []:
        role = item.get("type")
        if not role:
            continue
        out.append({"role": role, "congress": item.get("congress")})
    return out


def party_history(detail: dict) -> list[dict]:
    """member_detail's `partyHistory[]` -> [{party, start_year, end_year}],
    verbatim (party switches over a member's whole career) — dropping only
    entries with neither a party name nor code (never invented)."""
    out = []
    for item in detail.get("partyHistory") or []:
        party = item.get("partyName") or item.get("partyAbbreviation")
        if not party:
            continue
        out.append({"party": party, "start_year": item.get("startYear"),
                    "end_year": item.get("endYear")})
    return out


def dc_office_from_detail(detail: dict) -> dict:
    """member_detail's `addressInformation` -> {dc_office_address, phone},
    verbatim, each key present only when the source populated it. A distinct
    (fresher) source of the same two facts as the congress-legislators term —
    the transform prefers whichever is present, never fabricating either."""
    addr = detail.get("addressInformation") or {}
    out = {}
    office = addr.get("officeAddress")
    city = addr.get("city")
    zip_code = addr.get("zipCode")
    if office:
        parts = [office]
        if city:
            parts.append(city)
        if zip_code:
            parts.append(str(zip_code))
        out["dc_office_address"] = ", ".join(parts)
    if addr.get("phoneNumber"):
        out["phone"] = addr["phoneNumber"]
    return out
