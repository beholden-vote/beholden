"""Washington PDC itemized contributions — first Tier-A trusted-extraction source
(docs/TRUSTED-EXTRACTION.md, WO-9; reconciliation fixed in WO-19). No API key;
license is Public Domain.

Two Socrata datasets on data.wa.gov, verified live 2026-07-05 and 2026-07-07:
  - kv7h-kjye  "Contributions to Candidates and Political Committees" (itemized)
  - 3h9x-7bvm  "Campaign Finance Summary" (the reconciliation control totals)

This module is the WHOLE extraction path and there is NO MODEL in it. It:
  1. declares the pinned SourceContract (CONTRACT below),
  2. fetches paged snapshots + records their exact-bytes SHA-256,
  3. copies verbatim cells into rows carrying the §6 provenance envelope, and
  4. quarantines — never coerces — any cell outside the contract's value domain.

Copy-only means: the ONLY transforms are `amount` dollars -> integer cents and
`receipt_date` -> a date. No name normalization, no inference, no computed fields.
The verbatim `amount` and `contributor_name` cells are retained forever (§6).

Reconciliation key (WO-19). The control-total grouping is `fund_id`, NOT
(filer_id, election_year). PDC's own data dictionary for BOTH datasets
(https://data.wa.gov/api/views/kv7h-kjye.json · .../3h9x-7bvm.json) documents:
  - fund_id — "The unique identifier for all reporting and finance records
    associated with a single campaign. This can be used to correlate records
    across different datasets."
  - filer_id — NOT stable per person/campaign: "an individual running for a
    second office in the same election year will receive a second filer id."
    Verified live 2026-07-07: itemized filer_id 'EWINS2 258' vs summary
    'EWINS  258' for the SAME campaign, fund_id 26142 — which reconciles to the
    cent on fund_id ($1,570.00). A filer can also run several funds in one
    election year (two 2025 summary rows for 'EWINS  258'), so (filer, year) is
    not even a well-defined group. See docs/research/wa-pdc-reconciliation-findings.md.

Entity resolution stays deterministic-only: rows land keyed by PDC ids. We do
NOT fuzzy-match filer_name to the person spine (unlinked is honest; a wrong link
is not). The filer<->person crosswalk (bulk/crosswalk.py) publishes only through
a human-reviewed exact-id allowlist; name matches are quarantined (§9).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..bulk.contract import ControlTotal, Field, SourceContract
from ..bulk.reconcile import ControlTotalError

_HOST = "https://data.wa.gov"
ITEMIZED_DATASET = "kv7h-kjye"
SUMMARY_DATASET = "3h9x-7bvm"
HISTORY_DATASET = "7qr9-q2c9"   # "Campaign Finance Reporting History" (per-report registry)

# Exact, ordered CSV/SoQL header of kv7h-kjye (verified live 2026-07-05). This is
# the schema-drift fingerprint: the header must match this list EXACTLY or the run
# halts. `contributor_location` (a Socrata point) trails the record but is not read.
ITEMIZED_HEADER = (
    "id", "report_number", "origin", "committee_id", "fund_id", "filer_id", "type",
    "filer_name", "office", "legislative_district", "position", "party",
    "ballot_number", "for_or_against", "jurisdiction", "jurisdiction_county",
    "jurisdiction_type", "election_year", "amount", "cash_or_in_kind",
    "receipt_date", "description", "memo", "primary_general", "code",
    "contributor_category", "contributor_name", "contributor_address",
    "contributor_city", "contributor_state", "contributor_zip",
    "contributor_occupation", "contributor_employer_name",
    "contributor_employer_city", "contributor_employer_state", "url",
    "contributor_location",
)

# cash_or_in_kind value domain, verified live: the feed contains exactly these two.
CASH_OR_IN_KIND_DOMAIN = ("Cash", "In-kind")

CONTRACT = SourceContract(
    source_id="wa_pdc",
    jurisdiction="ocd-division/country:us/state:wa",
    layout_doc_url=f"{_HOST}/d/{ITEMIZED_DATASET}",
    retrieval={
        "format": "socrata_json",
        "itemized_json": f"{_HOST}/resource/{ITEMIZED_DATASET}.json",
        "itemized_bulk_csv":
            f"{_HOST}/api/views/{ITEMIZED_DATASET}/rows.csv?accessType=DOWNLOAD",
        # The dataset's own metadata (columns[].fieldName) — the observed header
        # the schema-drift gate compares against the pinned fingerprint.
        "itemized_metadata": f"{_HOST}/api/views/{ITEMIZED_DATASET}.json",
        "summary_json": f"{_HOST}/resource/{SUMMARY_DATASET}.json",
        # Per-report registry: which filed reports exist per fund. Consulted by
        # the deferral rule (deferred_funds_missing_reports) so a control total
        # that already counts a report the itemized mirror has not materialized
        # yet defers that fund instead of failing the whole run.
        "history_json": f"{_HOST}/resource/{HISTORY_DATASET}.json",
        "paging": "$limit/$offset",
        # WO-19: the itemized window is FUND-COMPLETE — after the election_year
        # window pass, a completion pass fetches every remaining row of each fund
        # already seen, so no reconciliation group is ever split by the window.
        "window": "fund-complete (see fetch_itemized)",
    },
    header=ITEMIZED_HEADER,
    fields=(
        Field("id", "text", is_key=True, nullable=False),
        Field("report_number", "text"),
        Field("committee_id", "text"),
        # fund_id is the reconciliation group AND PDC's documented cross-dataset
        # correlation key ("can be used to correlate records across different
        # datasets" — dataset data dictionary, both feeds). Never absent live
        # (verified 2026-07-07); a row without one has no reconciliation basis
        # and is quarantined.
        Field("fund_id", "text", is_key=True, nullable=False),
        Field("filer_id", "text", is_key=True, nullable=False),
        Field("filer_name", "text"),
        Field("office", "text"),
        Field("party", "text"),
        Field("legislative_district", "text"),
        Field("election_year", "number", nullable=False),
        Field("amount", "number", nullable=False),   # signed: refunds/corrections < 0
        Field("cash_or_in_kind", "text", domain=CASH_OR_IN_KIND_DOMAIN, nullable=False),
        Field("receipt_date", "date"),
        Field("contributor_name", "text"),
        Field("contributor_city", "text"),
        Field("contributor_state", "text"),
        Field("contributor_occupation", "text"),
        Field("contributor_employer_name", "text"),
        Field("url", "url", nullable=False),
    ),
    # Σ(itemized amount) per fund_id must equal the summary feed's
    # `contributions_amount` for that fund (one summary row per fund — PDC
    # documents fund_id as the unique id of a single campaign's finance records).
    # Verified live 2026-07-07: 2,670/2,670 fund-complete groups reconcile to the
    # cent, including the filer_id-format mismatch pair ('EWINS2 258' itemized vs
    # 'EWINS  258' summary, fund 26142). epsilon 0 — exact match required.
    control_total=ControlTotal(
        companion_source_id="wa_pdc_summary",
        total_field="contributions_amount",
        group_by=("fund_id",),
        sum_field="amount",
        epsilon_cents=0,
    ),
    record_locator="id",
    source_record_url="url",
    license="Public Domain",
    license_is_public_domain=True,
    attribution="Public Disclosure Commission (http://pdc.wa.gov)",
    # Changelog:
    #   2026-07-05  initial contract; control total grouped by (filer_id,
    #               election_year) — rejected by the gate on real data (correct:
    #               the two feeds disagree on filer_id format and a filer can run
    #               several funds per year).
    #   2026-07-07  WO-19: reconciliation regrouped by fund_id (PDC-documented
    #               cross-dataset key); + committee_id/fund_id fields read;
    #               fund-complete fetch window; summary fetched whole with the
    #               registry columns (person_id, filer_type, expenditures, url).
    #               Layout fingerprint (header) unchanged.
    contract_version="2026-07-07",
)

_RETRYABLE = (httpx.HTTPStatusError, httpx.TransportError)


# --- fetch: paged snapshots + exact-bytes SHA-256 --------------------------
@retry(stop=stop_after_attempt(5),
       wait=wait_exponential(multiplier=2, max=60),
       retry=retry_if_exception_type(_RETRYABLE))
def _get_json(url: str, **params) -> list[dict]:
    r = httpx.get(url, params=params, timeout=120, follow_redirects=True)
    r.raise_for_status()
    return r.json()


# The itemized feed is ~6.3M rows of ALL-TIME WA contributions — loading it whole
# OOM-kills the runner (~30 GB). This Tier-A pilot ingests the CURRENT CYCLE only
# (election_year >= PILOT_MIN_ELECTION_YEAR, ~380k rows), a bounded, memory-safe
# window that still exercises the full contract + reconciliation gates end to end.
# The window is recorded in the snapshot manifest so the slice is explicit, never
# passed off as all-time. Widening it is a WO-9 follow-on (stream to disk instead
# of accumulating in memory, so the SHA-256 doesn't need the whole set resident).
PILOT_MIN_ELECTION_YEAR = 2025


def fetch_metadata() -> dict:
    """The itemized dataset's OBSERVED metadata, from Socrata's own endpoint:
      header           — columns[].fieldName in dataset order; what the
                         schema-drift gate compares against the pinned
                         ITEMIZED_HEADER (a real observation of the live layout,
                         never an echo of the contract), and
      rows_updated_at  — the mirror's last-refresh instant (UTC ISO), the
                         reference point for the stale-control deferral rule
                         (see stale_control_funds).
    """
    r = httpx.get(CONTRACT.retrieval["itemized_metadata"], timeout=120,
                  follow_redirects=True)
    r.raise_for_status()
    meta = r.json()
    return {
        "header": [c["fieldName"] for c in meta["columns"]],
        "rows_updated_at": datetime.fromtimestamp(
            meta["rowsUpdatedAt"], tz=timezone.utc).isoformat(timespec="seconds"),
    }


def _fetch_paged(url: str, where: str, page_size: int, max_pages: int,
                 select: str | None = None, order: str = "id") -> list[dict]:
    """$limit/$offset paging ordered by a stable native column, hard-capped at
    max_pages so an unbounded fetch can never recur. Records come back verbatim."""
    rows: list[dict] = []
    offset, page = 0, 0
    while True:
        params = {"$limit": page_size, "$offset": offset, "$order": order,
                  "$where": where}
        if select:
            params["$select"] = select
        batch = _get_json(url, **params)
        if not batch:
            break
        rows.extend(batch)
        offset += page_size
        page += 1
        if page >= max_pages:                 # hard safety net (~1M-row ceiling)
            break
    return rows


def _batched(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def fetch_itemized(page_size: int = 50000, max_pages: int = 20,
                   min_election_year: int = PILOT_MIN_ELECTION_YEAR) -> list[dict]:
    """Fetch a FUND-COMPLETE current-cycle slice of the itemized feed.

    Pass 1 pages election_year >= min_election_year (the bounded pilot window,
    ~380k rows). Pass 2 (WO-19) completes every fund seen in pass 1: a campaign's
    rows can carry mixed election_year labels (verified live 2026-07-07 — e.g.
    fund 27811 has 42 rows labeled 2026 plus 13 labeled 2024), and the summary
    control total always covers the WHOLE fund, so a year-sliced fund can never
    reconcile. The completion pass fetches the out-of-window remainder of each
    seen fund (a handful of rows in practice), making every reconciliation group
    complete by construction. Returns the raw records verbatim."""
    url = CONTRACT.retrieval["itemized_json"]
    rows = _fetch_paged(url, f"election_year >= {int(min_election_year)}",
                        page_size, max_pages)
    funds = sorted({r["fund_id"] for r in rows if r.get("fund_id")})
    for batch in _batched(funds, 150):        # bounded $where length per request
        quoted = ",".join("'" + f.replace("'", "''") + "'" for f in batch)
        rows.extend(_fetch_paged(
            url, f"fund_id in({quoted}) AND election_year < {int(min_election_year)}",
            page_size, max_pages))
    return rows


# The summary registry columns we read: reconciliation control total + the PDC
# filer/person registry fields the deterministic crosswalk needs (§9). person_id
# is PDC's "preferred id for identifying a natural person" (their data dictionary).
SUMMARY_SELECT = ("id,filer_id,election_year,committee_id,fund_id,person_id,"
                  "filer_name,filer_type,contributions_amount,expenditures_amount,"
                  "updated_at,url")


def fetch_summary() -> list[dict]:
    """The companion control-total + filer-registry feed (3h9x-7bvm), fetched
    WHOLE (~58k rows — small) so every fund seen in the itemized slice finds its
    control row regardless of how the two feeds label election_year. One row per
    fund. Returns raw records verbatim."""
    url = CONTRACT.retrieval["summary_json"]
    rows: list[dict] = []
    offset = 0
    while True:
        batch = _get_json(url, **{"$limit": 50000, "$offset": offset, "$order": "id",
                                  "$select": SUMMARY_SELECT})
        if not batch:
            break
        rows.extend(batch)
        offset += 50000
    return rows


# The per-report registry columns the deferral rule reads (7qr9-q2c9).
HISTORY_SELECT = "report_number,fund_id,origin,amended_by_report,receipt_date"


def fetch_history(fund_ids: list[str], page_size: int = 50000,
                  max_pages: int = 20) -> list[dict]:
    """The Reporting History rows for exactly the funds seen in the itemized
    slice (batched fund_id IN queries, ~96k small rows for the current window).
    Returns raw records verbatim."""
    url = CONTRACT.retrieval["history_json"]
    rows: list[dict] = []
    for batch in _batched(sorted(set(fund_ids)), 150):
        quoted = ",".join("'" + f.replace("'", "''") + "'" for f in batch)
        rows.extend(_fetch_paged(url, f"fund_id in({quoted})", page_size, max_pages,
                                 select=HISTORY_SELECT, order="report_number"))
    return rows


def snapshot_bytes(records: list[dict]) -> bytes:
    """Canonical, deterministic serialization of a fetched snapshot, so its SHA-256
    is stable and a silent re-release with different content forces a re-review
    (§4.1). Sorted keys + compact separators make the bytes reproducible."""
    return json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- copy-only mappers -----------------------------------------------------
def to_cents(dollars) -> int | None:
    """Verbatim dollars -> integer cents. Returns None (never 0) when the cell is
    absent or non-numeric, so the caller quarantines rather than coerces."""
    if dollars is None:
        return None
    try:
        return round(float(dollars) * 100)
    except (TypeError, ValueError):
        return None


def parse_date(value) -> str | None:
    """Socrata calendar_date ('YYYY-MM-DDT00:00:00[.000]') -> 'YYYY-MM-DD', or None
    when absent/unparseable (receipt_date is nullable, so None is legal here; a
    present-but-unparseable date is a value-domain quarantine, handled by caller)."""
    if not value:
        return None
    try:
        text = str(value)
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _record_url(rec: dict) -> str | None:
    """The per-record official link. Socrata's `url` column serializes either as a
    bare string or as {"url": "..."}; both are copied verbatim, neither is invented."""
    url = rec.get("url")
    if isinstance(url, dict):
        return url.get("url")
    return url if isinstance(url, str) else None


def provenance(rec: dict, *, file_sha256: str, retrieved_at: str) -> dict:
    """The §6 envelope for one extracted fact — everything needed to reconstruct
    exactly where the value came from. No value is derived here; these are copies."""
    return {
        "source_id": CONTRACT.source_id,
        "contract_version": CONTRACT.contract_version,
        "file_sha256": file_sha256,
        "retrieved_at": retrieved_at,
        "record_locator": rec.get("id"),                 # native record id
        "source_record_url": _record_url(rec),           # per-record official link
        "raw_amount": None if rec.get("amount") is None else str(rec.get("amount")),
        "raw_contributor_name": rec.get("contributor_name"),
    }


def _quarantine(rec: dict, reason: str, *, file_sha256: str) -> dict:
    return {
        "source_id": CONTRACT.source_id,
        "contract_version": CONTRACT.contract_version,
        "file_sha256": file_sha256,
        "record_locator": rec.get("id"),
        "reason": reason,
        "raw_payload": rec,
    }


def map_row(rec: dict, *, file_sha256: str, retrieved_at: str):
    """Copy one itemized record into either a disclosure_contributions row or a
    quarantine row. Returns (contribution|None, quarantine|None) — exactly one is
    non-None, so every input row is accounted for (no-silent-drop, §5).

    Value-domain enforcement (§5): a bad `cash_or_in_kind` enum, a non-numeric
    `amount`, a present-but-unparseable `receipt_date`, or a missing key (id /
    filer_id / fund_id / election_year / url) is QUARANTINED WITH A REASON —
    never coerced into range. Everything else is a verbatim copy.
    """
    rid = rec.get("id")
    if not rid:
        return None, _quarantine(rec, "missing native id", file_sha256=file_sha256)

    filer_id = rec.get("filer_id")
    if not filer_id:
        return None, _quarantine(rec, "missing filer_id", file_sha256=file_sha256)

    # WO-19: fund_id is the reconciliation group — a row without one has no
    # reconciliation basis (never observed live; quarantined if it ever appears).
    fund_id = rec.get("fund_id")
    if not fund_id:
        return None, _quarantine(rec, "missing fund_id", file_sha256=file_sha256)

    url = _record_url(rec)
    if not url:
        return None, _quarantine(rec, "missing source_record_url", file_sha256=file_sha256)

    year_raw = rec.get("election_year")
    try:
        election_year = int(year_raw)
    except (TypeError, ValueError):
        return None, _quarantine(
            rec, f"election_year not an integer: {year_raw!r}", file_sha256=file_sha256)

    cents = to_cents(rec.get("amount"))
    if cents is None:
        return None, _quarantine(
            rec, f"amount not numeric: {rec.get('amount')!r}", file_sha256=file_sha256)

    cik = rec.get("cash_or_in_kind")
    if cik not in CASH_OR_IN_KIND_DOMAIN:
        return None, _quarantine(
            rec, f"cash_or_in_kind out of domain: {cik!r}", file_sha256=file_sha256)

    receipt_raw = rec.get("receipt_date")
    receipt_date = parse_date(receipt_raw)
    if receipt_raw and receipt_date is None:
        return None, _quarantine(
            rec, f"receipt_date unparseable: {receipt_raw!r}", file_sha256=file_sha256)

    prov = provenance(rec, file_sha256=file_sha256, retrieved_at=retrieved_at)
    row = {
        "id": str(rid),
        "source_id": prov["source_id"],
        "contract_version": prov["contract_version"],
        "file_sha256": prov["file_sha256"],
        "retrieved_at": prov["retrieved_at"],
        "source_record_url": url,
        "report_number": rec.get("report_number"),
        "committee_id": rec.get("committee_id"),          # WO-19: PDC committee id
        "fund_id": str(fund_id),                          # WO-19: reconciliation group
        "filer_id": filer_id,
        "filer_name": rec.get("filer_name"),
        "office": rec.get("office"),
        "party": rec.get("party"),
        "legislative_district": rec.get("legislative_district"),
        "election_year": election_year,
        "amount_cents": cents,
        "cash_or_in_kind": cik,
        "receipt_date": receipt_date,
        "contributor_name": rec.get("contributor_name"),
        "contributor_city": rec.get("contributor_city"),
        "contributor_state": rec.get("contributor_state"),
        "contributor_occupation": rec.get("contributor_occupation"),
        "contributor_employer_name": rec.get("contributor_employer_name"),
        "raw_amount": prov["raw_amount"],
        "raw_contributor_name": prov["raw_contributor_name"],
    }
    return row, None


def control_totals_cents(summary_records: list[dict]) -> dict:
    """The companion feed's control totals keyed by fund_id (WO-19), in integer
    cents. PDC documents fund_id as the unique id of a single campaign's finance
    records, so one summary row per fund (verified live: zero duplicates); if two
    summary rows ever DISAGREE on a fund's total, that is a reconciliation-basis
    integrity failure and the run halts — never a silent last-writer-wins. A
    summary row with a non-numeric/absent total or no fund_id is skipped — the
    control-total gate then treats an itemized group with no control total as a
    failure (never a silent pass)."""
    totals: dict[str, int] = {}
    for rec in summary_records:
        fund_id = rec.get("fund_id")
        cents = to_cents(rec.get(CONTRACT.control_total.total_field))
        if not fund_id or cents is None:
            continue
        fund_id = str(fund_id)
        if fund_id in totals and totals[fund_id] != cents:
            raise ControlTotalError(
                f"control-total basis: {CONTRACT.source_id} summary feed carries "
                f"conflicting totals for fund {fund_id}: {totals[fund_id]}c vs "
                f"{cents}c — fund_id uniqueness violated upstream, halting")
        totals[fund_id] = cents
    return totals


def itemized_group_key(row: dict) -> str:
    """The reconciliation group for an inserted contribution row: its fund_id
    (WO-19 — PDC's documented cross-dataset correlation key)."""
    return row["fund_id"]


# The report origin that carries itemized contributions: C3, the cash-receipts
# deposit report. (The itemized feed also carries B.1/AU/C.1/C.3 rows, but the
# Reporting History registry tracks only C3/C4 report filings — verified live
# 2026-07-07 across all 2,670 window funds — so C3 presence is the completeness
# signal the registry can actually attest to.)
CONTRIBUTION_REPORT_ORIGIN = "C3"


def deferred_funds_missing_reports(history_records: list[dict],
                                   itemized_records: list[dict]) -> dict[str, list[str]]:
    """Funds whose control total CANNOT verify this snapshot pair, because a
    freshly filed contribution report exists in PDC's own Reporting History but
    the itemized mirror has not materialized its line items yet. Observed live
    2026-07-07: the summary mirror recalculates continuously while the itemized
    mirror refreshes in batches — fund 27194's control exceeded the itemized sum
    by exactly the deposits of report 110370630, received that same day.

    The rule, fully derived from the snapshot pair (no wall clock):
      cutoff  = the newest `receipt_date` among history reports that ARE present
                in the itemized snapshot (how far the mirror's content reaches);
      deferred = funds with an unamended C3 report ABSENT from the snapshot and
                received on/after that cutoff (not yet mirrored, day-granular).
    Older absent C3s are legitimately line-item-free (440 such funds reconcile
    exactly, verified live) and do not defer. Returns {fund_id: [missing
    report_numbers]}. Deferral only ever NARROWS what publishes: the deferred
    fund's rows are quarantined whole with a recorded reason, and the unchanged
    control-total gate still halts on any mismatch among the remaining funds.
    """
    present: dict[str, set] = {}
    for rec in itemized_records:
        fund = rec.get("fund_id")
        if fund is not None and rec.get("report_number"):
            present.setdefault(str(fund), set()).add(str(rec["report_number"]))

    cutoff = None
    for h in history_records:
        fund, num = h.get("fund_id"), h.get("report_number")
        date = h.get("receipt_date")
        if date and fund is not None and str(num) in present.get(str(fund), set()):
            cutoff = date if cutoff is None or date > cutoff else cutoff
    if cutoff is None:                       # nothing attested -> no deferral basis;
        return {}                            # the gate stays fully strict

    missing: dict[str, list[str]] = {}
    for h in history_records:
        if (h.get("origin") == CONTRIBUTION_REPORT_ORIGIN
                and not h.get("amended_by_report")
                and h.get("receipt_date") and h["receipt_date"] >= cutoff
                and h.get("fund_id") is not None):
            fund, num = str(h["fund_id"]), str(h.get("report_number"))
            if num not in present.get(fund, set()):
                missing.setdefault(fund, []).append(num)
    return {f: sorted(nums) for f, nums in missing.items()}


def quarantine_record(rec: dict, reason: str, *, file_sha256: str) -> dict:
    """A quarantine row for one verbatim input record (public wrapper used by
    the transform's stale-control deferral path)."""
    return _quarantine(rec, reason, file_sha256=file_sha256)
