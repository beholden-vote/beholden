"""Washington PDC itemized contributions — first Tier-A trusted-extraction source
(docs/TRUSTED-EXTRACTION.md, WO-9). No API key; license is Public Domain.

Two Socrata datasets on data.wa.gov, verified live 2026-07-05:
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

Entity resolution is deliberately deferred: rows land keyed by WA `filer_id`
only. We do NOT fuzzy-match filer_name to the person spine (unlinked is honest; a
wrong link is not). A deterministic filer<->person crosswalk is a follow-on.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..bulk.contract import ControlTotal, Field, SourceContract

_HOST = "https://data.wa.gov"
ITEMIZED_DATASET = "kv7h-kjye"
SUMMARY_DATASET = "3h9x-7bvm"

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
        "summary_json": f"{_HOST}/resource/{SUMMARY_DATASET}.json",
        "paging": "$limit/$offset",
    },
    header=ITEMIZED_HEADER,
    fields=(
        Field("id", "text", is_key=True, nullable=False),
        Field("report_number", "text"),
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
    # Σ(itemized amount) per (filer_id, election_year) must equal the summary feed's
    # `contributions_amount` for that filer/year (one summary row per group; verified
    # 24THLD 362 / 2025 reconciles to the cent). epsilon 0 — exact match required.
    control_total=ControlTotal(
        companion_source_id="wa_pdc_summary",
        total_field="contributions_amount",
        group_by=("filer_id", "election_year"),
        sum_field="amount",
        epsilon_cents=0,
    ),
    record_locator="id",
    source_record_url="url",
    license="Public Domain",
    license_is_public_domain=True,
    attribution="Public Disclosure Commission (http://pdc.wa.gov)",
    contract_version="2026-07-05",
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


def fetch_itemized(page_size: int = 50000, max_pages: int | None = None) -> list[dict]:
    """Page the itemized feed via $limit/$offset, ordered by the native id so paging
    is stable across the run. Returns the raw records verbatim (no transformation)."""
    url = CONTRACT.retrieval["itemized_json"]
    rows: list[dict] = []
    offset, page = 0, 0
    while True:
        batch = _get_json(url, **{"$limit": page_size, "$offset": offset, "$order": "id"})
        if not batch:
            break
        rows.extend(batch)
        offset += page_size
        page += 1
        if max_pages is not None and page >= max_pages:
            break
    return rows


def fetch_summary() -> list[dict]:
    """The companion control-total feed (3h9x-7bvm), fetched whole. Small: one row
    per (filer, election_year). Returns raw records verbatim."""
    url = CONTRACT.retrieval["summary_json"]
    rows: list[dict] = []
    offset = 0
    while True:
        batch = _get_json(url, **{"$limit": 50000, "$offset": offset, "$order": "id",
                                  "$select": "filer_id,election_year,contributions_amount"})
        if not batch:
            break
        rows.extend(batch)
        offset += 50000
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
    filer_id / election_year / url) is QUARANTINED WITH A REASON — never coerced
    into range. Everything else is a verbatim copy.
    """
    rid = rec.get("id")
    if not rid:
        return None, _quarantine(rec, "missing native id", file_sha256=file_sha256)

    filer_id = rec.get("filer_id")
    if not filer_id:
        return None, _quarantine(rec, "missing filer_id", file_sha256=file_sha256)

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
    """The companion feed's control totals keyed by (filer_id, election_year), in
    integer cents. One summary row per group (verified). A summary row with a
    non-numeric/absent total or key is skipped — the control-total gate then treats
    an itemized group with no control total as a failure (never a silent pass)."""
    totals: dict[tuple[str, int], int] = {}
    for rec in summary_records:
        filer_id = rec.get("filer_id")
        year_raw = rec.get("election_year")
        cents = to_cents(rec.get(CONTRACT.control_total.total_field))
        if not filer_id or cents is None:
            continue
        try:
            year = int(year_raw)
        except (TypeError, ValueError):
            continue
        totals[(filer_id, year)] = cents
    return totals


def itemized_group_key(row: dict) -> tuple[str, int]:
    """The reconciliation group for an inserted contribution row: (filer_id, year)."""
    return (row["filer_id"], row["election_year"])
