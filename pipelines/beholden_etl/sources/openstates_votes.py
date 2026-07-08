"""OpenStates API v3 client + parsers for state bills, sponsorships and
roll-call votes (WO-17).

Same source FAMILY as sources/openstates.py (the people CSVs): everything here
publishes under the one `openstates` registry entry, so freshness/SLA/coverage
stay a single row. The people crawl is bulk CSV against data.openstates.org;
bills+votes are only available through the keyed v3 API
(`GET /bills?include=votes` — the bulk session-CSV path is login-walled, see
docs/research/state-votes-evaluation.md §1a), so this module carries its own
keyed, throttled, retrying client in the congress_gov.py / fec.py mold.

Crawl design (research doc §4, verified against the v3 OpenAPI spec):
  * One paged crawl per state: `/bills?jurisdiction={ocd-jurisdiction}` with
    `include=sponsorships,votes,actions,sources`, bounded to the current
    biennium via `created_since` (no per-state session discovery needed —
    special sessions are covered too, and each record carries its own
    `session` for id construction).
  * Incremental: `sort=updated_desc` + an `updated_since` cursor persisted in
    the raw lake (raw/openstates/votes/{state}.json). Nightly runs fetch only
    the delta and merge it into the prior snapshot by ocd-bill id. `--full`
    skips lake hydration entirely, so no prior snapshot exists and the crawl
    is naturally full — no separate bypass flag.
  * The next cursor is the crawl's own START time minus a small skew lap, not
    the max updated_at seen: any record that moves between pages mid-crawl
    does so because its updated_at bumped past our start, so the next night's
    window is guaranteed to re-cover it (no silent misses).

Join discipline (rule: never name-match): votes and sponsorships join to
persons ONLY by exact `ocd-person/<uuid>` equality against
person_identifiers(id_scheme='openstates'). A record whose person reference is
absent or unknown is skipped and counted (and unknown ids are quarantined by
the transform) — never guessed.

Fail-closed vs honest-absent: a state whose crawl fails entirely publishes
nothing new for that state (its legislators keep identity-only dossiers) and
the run continues. But a PRESENT record missing a required field is schema
drift — parse_bill raises SchemaDriftError and the transform lets it halt the
run rather than publish a half-parsed state.
"""
from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

# The v3 API host. Deliberately NOT config.SOURCES['openstates'].base_url —
# that is the bulk-CSV host (data.openstates.org) the people crawl uses; both
# hosts publish under the same `openstates` source key / SLA row.
API_BASE = "https://v3.openstates.org"
PER_PAGE = 20            # spec default 10, no documented max — 20 is the research
                         # doc's conservative choice (state-votes-evaluation §2)
# VERIFIED LIVE 2026-07-07: the OpenStates v3 tiers are per-minute AND per-day
# capped — default/free 10/min·500/day, bronze 40/min·5k/day, silver
# 80/min·50k/day (openstates/issues#205). The original 1.1s guess (~54/min)
# exceeded even bronze and 429-stormed every state on the first live run. Pace
# to the LOWEST paid tier by default (bronze, 40/min ⇒ ≥1.5s) with headroom, so
# a granted key of any tier works out of the box; OPENSTATES_MIN_INTERVAL_S
# overrides it (drop toward 0.8s on silver+ to backfill faster). Free/default
# keys (500/day) still can't cold-start a full-biennium multi-state backfill —
# an approved tier key is the intended path (see the WO-17 live-validation note).
def _min_interval_s() -> float:
    try:
        return max(float(os.environ.get("OPENSTATES_MIN_INTERVAL_S") or 0) or 1.6, 0.25)
    except ValueError:
        return 1.6
# Everything the transform needs and nothing more (documents/versions/
# abstracts stay out — they dominate payload size and feed nothing).
INCLUDE = ("sponsorships", "votes", "actions", "sources")
# Next-cursor skew lap: covers clock skew between our runner and the API's
# updated_at stamps. Costs a few re-fetched bills per night, never correctness.
CURSOR_SKEW = timedelta(hours=1)

_RETRYABLE = (httpx.HTTPStatusError, httpx.TransportError)


class SchemaDriftError(ValueError):
    """A present record is missing a required field — fail closed, never
    publish a half-parsed state (absent data is honest; drifted data is not)."""


def api_key_available() -> bool:
    return bool(os.environ.get("OPENSTATES_KEY"))


class OpenStatesVotesClient:
    """Keyed, rate-limited, retrying v3 client. Thread-safe throttle (the
    congress_gov.CongressGovClient._throttle lock pattern) so the per-state
    fan-out in fetch.py can share ONE client without bursting past the cap —
    threads buy overlap on per-request latency, not a higher dispatch rate."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("OPENSTATES_KEY") or ""
        if not self.api_key:
            raise RuntimeError("OPENSTATES_KEY is not set (see docs/SETUP.md §1)")
        self._last_call = 0.0
        self._min_interval = _min_interval_s()   # tier-safe pacing (see _min_interval_s)
        self._lock = threading.Lock()
        self._http = httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0))

    def _throttle(self):
        with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    @retry(stop=stop_after_attempt(8),
           wait=wait_exponential(multiplier=2, max=60),
           retry=retry_if_exception_type(_RETRYABLE))
    def get(self, path: str, **params) -> dict:
        self._throttle()
        r = self._http.get(f"{API_BASE}/{path.lstrip('/')}",
                           params=params, headers={"X-API-KEY": self.api_key})
        if r.status_code == 429:  # respect rate-limit responses explicitly
            time.sleep(float(r.headers.get("Retry-After", 60)))
        r.raise_for_status()
        return r.json()

    def bills(self, jurisdiction: str, created_since: str,
              updated_since: str | None = None):
        """Yield every bill record for one jurisdiction, current biennium,
        newest-updated first, votes/sponsorships/actions/sources embedded."""
        page = 1
        while True:
            params = {
                "jurisdiction": jurisdiction, "created_since": created_since,
                "sort": "updated_desc", "include": list(INCLUDE),
                "per_page": PER_PAGE, "page": page,
            }
            if updated_since:
                params["updated_since"] = updated_since
            data = self.get("bills", **params)
            yield from data.get("results") or []
            pagination = data.get("pagination") or {}
            if page >= int(pagination.get("max_page") or 1):
                return
            page += 1


# --- pure helpers (unit-tested; no network) ---------------------------------
def jurisdiction_id(state: str) -> str:
    """The ocd-jurisdiction id the /bills endpoint filters on. DC and PR use
    different division kinds than the 50 states."""
    slug = state.lower()
    if slug == "dc":
        return "ocd-jurisdiction/country:us/district:dc/government"
    if slug == "pr":
        return "ocd-jurisdiction/country:us/territory:pr/government"
    return f"ocd-jurisdiction/country:us/state:{slug}/government"


def biennium_start(congress: int) -> str:
    """created_since bound for the crawl — most state legislatures convene in
    January of the odd year; derived from CONGRESS (same arithmetic as
    transform.py's session_start) so a CONGRESS bump can't drift."""
    return f"{2025 + (congress - 119) * 2}-01-01"


def _slug(text: str) -> str:
    """bill_id path segment: lowercase, whitespace runs -> '-' (contracts §2
    additive note: state bill_id = '{state}/{session}/{identifier-slug}')."""
    return re.sub(r"\s+", "-", str(text).strip().lower())


def state_bill_id(state: str, session: str, identifier: str) -> str:
    """'tn' + '114' + 'SB 512' -> 'tn/114/sb-512' (federal stays
    'us/{congress}/{slug}/{num}'; both documented in DATA-CONTRACTS §2)."""
    return f"{state.lower()}/{_slug(session)}/{_slug(identifier)}"


def state_roll_call_id(state: str, session: str, chamber: str, vote_id: str) -> str:
    """'{state}/{session}/{chamber}/{ocd-vote uuid}' — deterministic and unique
    (the uuid tail of the API's own ocd-vote id), mirroring the federal
    'us/{congress}/{chamber}/{rollnumber}' shape."""
    return f"{state.lower()}/{_slug(session)}/{chamber}/{vote_id.rsplit('/', 1)[-1]}"


# PersonVote.option -> the vote_positions CHECK enum. Mapped values only; an
# option outside this table (e.g. 'paired', 'other') is skipped AND counted —
# never guessed into a side the member didn't take.
OPTION_POSITION = {
    "yes": "yea",
    "no": "nay",
    "abstain": "present",          # recorded present-not-voting
    "absent": "not_voting",
    "excused": "not_voting",
    "not voting": "not_voting",
}

# Action-classification tokens (OpenStates' own normalized vocabulary) -> the
# bills.status CHECK enum, checked in precedence order. Deliberately
# conservative: unknown -> 'introduced', never a stronger claim (mirror of
# congress_gov.derive_status).
_LAW = {"became-law", "executive-signature"}
_VETOED = {"executive-veto", "executive-veto-line-item"}
_FAILED = {"failure", "withdrawal"}
_COMMITTEE = {"referral-committee"}
# openstates-core canon is 'passage'; the v3 spec's example shows 'passed' —
# accept both (recognizing a token can only upgrade an honest default, never
# fabricate: unrecognized still falls through to 'introduced').
_PASSAGE = {"passage", "passed"}


def derive_status(actions: list[dict]) -> str:
    tokens: set[str] = set()
    passage_chambers: set[str] = set()
    for a in actions or []:
        cls = set(a.get("classification") or [])
        tokens |= cls
        if cls & _PASSAGE:
            org = (a.get("organization") or {}).get("classification") or "legislature"
            passage_chambers.add(org)
    if tokens & _LAW:
        return "law"
    if tokens & _VETOED:
        return "vetoed"
    if len(passage_chambers - {"legislature"}) >= 2:
        return "passed_both"
    if passage_chambers:
        return "passed_chamber"
    if tokens & _FAILED:
        return "failed"
    if tokens & _COMMITTEE:
        return "committee"
    return "introduced"


def _require(record: dict, field: str, context: str):
    value = record.get(field)
    if value in (None, ""):
        raise SchemaDriftError(
            f"openstates votes: required field '{field}' missing on {context} — "
            "schema drift, refusing to publish a half-parsed state (fail closed)")
    return value


def _first_source_url(obj: dict) -> str | None:
    for s in obj.get("sources") or []:
        if s.get("url"):
            return s["url"]
    return None


def _date(value: str | None) -> str | None:
    """ISO date (first 10 chars) or None — the spine columns are DATE."""
    return str(value)[:10] if value else None


def parse_bill(state: str, record: dict) -> dict:
    """One landed v3 bill record -> spine-shaped rows.

    Returns {bill, sponsorships, roll_calls, positions, bill_url, rc_urls,
    skipped}: `sponsorships` and `positions` still carry the raw `ocd_person`
    reference (or None) — the transform owns the crosswalk join and the
    quarantine of unknown ids. `skipped` counts records this parser dropped
    honestly (person-less sponsorships, unmapped vote options).

    Raises SchemaDriftError when a PRESENT record lacks a required field
    (bill id/identifier/session; vote id/motion_text/start_date/result/
    organization) — fail closed on drift, per the WO-17 rules.
    """
    ocd_bill = _require(record, "id", f"a bill record for state '{state}'")
    identifier = _require(record, "identifier", ocd_bill)
    session = str(_require(record, "session", ocd_bill))
    bill_id = state_bill_id(state, session, identifier)

    subjects = [s for s in (record.get("subject") or []) if s]
    bill = {
        "bill_id": bill_id,
        "jurisdiction": state.lower(),
        "session": session,
        # federal precedent (congress_gov.bill_row): a missing title publishes
        # the explicit placeholder, never an invented one.
        "title": record.get("title") or "(untitled)",
        "status": derive_status(record.get("actions") or []),
        "introduced_on": _date(record.get("first_action_date")),
        "latest_action_on": _date(record.get("latest_action_date")),
        "policy_areas": subjects or None,   # the state's own subject taxonomy, verbatim
    }
    # Citation link: prefer the legislature's own bill page (sources[]), else
    # the openstates.org bill page — both are real, source-provided URLs
    # (research doc §4); never a constructed pattern.
    bill_url = _first_source_url(record) or record.get("openstates_url") or None

    sponsorships, skipped_sponsors = [], 0
    for sp in record.get("sponsorships") or []:
        person = sp.get("person") or {}
        ocd_person = person.get("id")
        if not ocd_person:
            skipped_sponsors += 1     # org-sponsored or unresolved by the source:
            continue                  # no id -> no join -> skipped, never name-matched
        sponsorships.append({
            "bill_id": bill_id,
            "ocd_person": ocd_person,
            "role": "sponsor" if sp.get("primary") else "cosponsor",
        })

    roll_calls, positions, rc_urls = [], [], {}
    skipped_positions = 0
    for vote in record.get("votes") or []:
        vote_id = _require(vote, "id", f"a vote on {ocd_bill}")
        motion = _require(vote, "motion_text", vote_id)
        start_date = _require(vote, "start_date", vote_id)
        result = _require(vote, "result", vote_id)
        chamber = (vote.get("organization") or {}).get("classification")
        if not chamber:
            raise SchemaDriftError(
                f"openstates votes: vote {vote_id} has no organization "
                "classification — schema drift (fail closed)")
        rcid = state_roll_call_id(state, session, chamber, vote_id)
        yea = nay = None
        for c in vote.get("counts") or []:      # tallies verbatim; absent stays NULL
            if c.get("option") == "yes":
                yea = c.get("value")
            elif c.get("option") == "no":
                nay = c.get("value")
        roll_calls.append({
            "roll_call_id": rcid, "bill_id": bill_id, "chamber": chamber,
            "question": motion, "held_at": str(start_date), "result": str(result),
            "yea_count": yea, "nay_count": nay,
        })
        rc_urls[rcid] = _first_source_url(vote) or bill_url
        for pv in vote.get("votes") or []:
            position = OPTION_POSITION.get((pv.get("option") or "").lower())
            voter_id = (pv.get("voter") or {}).get("id")
            if not position or not voter_id:
                # No mapped side taken, or the SOURCE itself couldn't resolve
                # the voter to a person (voter=None, name only): skip honestly.
                skipped_positions += 1
                continue
            positions.append({
                "roll_call_id": rcid, "ocd_person": voter_id, "position": position})

    return {
        "bill": bill, "sponsorships": sponsorships, "roll_calls": roll_calls,
        "positions": positions, "bill_url": bill_url, "rc_urls": rc_urls,
        "skipped": {"sponsorships": skipped_sponsors, "positions": skipped_positions},
    }


def crawl_state(client: OpenStatesVotesClient, state: str, created_since: str,
                prior_doc: dict | None, *, now: datetime | None = None) -> dict:
    """Crawl one state's bills+votes, merging into the prior lake snapshot.

    Incremental when `prior_doc` (the hydrated raw/openstates/votes/{state}.json)
    exists for the SAME biennium window: only bills updated since the persisted
    cursor are fetched and merged in by ocd-bill id. A prior snapshot from a
    different `created_since` (new biennium) is discarded — full recrawl.
    """
    start = now or datetime.now(timezone.utc)
    bills: dict[str, dict] = {}
    cursor = None
    if prior_doc and prior_doc.get("created_since") == created_since:
        bills = dict(prior_doc.get("bills") or {})
        cursor = prior_doc.get("cursor") or None

    fetched = 0
    for record in client.bills(jurisdiction_id(state), created_since,
                               updated_since=cursor):
        ocd_bill = record.get("id")
        if not ocd_bill:
            raise SchemaDriftError(
                f"openstates votes: a bill record for state '{state}' has no id "
                "— schema drift (fail closed)")
        bills[ocd_bill] = record        # newest fetch wins by ocd-bill id
        fetched += 1

    return {
        "state": state.lower(),
        "created_since": created_since,
        "cursor": (start - CURSOR_SKEW).isoformat(timespec="seconds"),
        "retrieved_at": start.isoformat(timespec="seconds"),
        "fetched": fetched,
        "bills": bills,
    }
