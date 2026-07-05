"""House Clerk financial disclosures — STOCK Act filings (E-money slice).

The Clerk publishes an annual index ZIP of every financial-disclosure filing.
We surface the Periodic Transaction Reports (FilingType 'P' — the stock-trade
disclosures) as links to the OFFICIAL PDFs. The itemized trades live inside each
PDF; rather than OCR them (unverifiable), we cite the filing itself — provenance
over polish. Itemized ticker/amount data would come from a vendor feed later.
"""
from __future__ import annotations

import io
import zipfile

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import SOURCES

BASE = SOURCES["house_clerk"].base_url
DISCLOSURE_URL = f"{BASE}/FinancialDisclosure"


def ptr_pdf_url(year: int, doc_id: str) -> str:
    return f"{BASE}/public_disc/ptr-pdfs/{year}/{doc_id}.pdf"


def _iso(m_d_y: str) -> str | None:
    """FilingDate is M/D/YYYY -> ISO, or None if unparseable."""
    try:
        m, d, y = m_d_y.split("/")
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    except ValueError:
        return None


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=60))
def ptr_filings(year: int) -> list[dict]:
    """Every Periodic Transaction Report filed in `year` (tab-delimited index)."""
    r = httpx.get(f"{BASE}/public_disc/financial-pdfs/{year}FD.zip",
                  timeout=90, follow_redirects=True)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    name = next((n for n in z.namelist() if n.lower().endswith(".txt")), None)
    if not name:
        return []
    # Columns: Prefix, Last, First, Suffix, FilingType, StateDst, Year, FilingDate, DocID
    out = []
    for line in z.read(name).decode("utf-8", "replace").splitlines()[1:]:
        c = line.split("\t")
        if len(c) < 9 or c[4] != "P":
            continue
        out.append({
            "last": c[1].strip(), "first": c[2].strip(), "suffix": c[3].strip(),
            "state_dst": c[5].strip(), "filed_on": _iso(c[7].strip()),
            "doc_id": c[8].strip(), "year": int(year),
        })
    return out
