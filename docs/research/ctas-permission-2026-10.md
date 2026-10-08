# CTAS (UT County Technical Assistance Service) - written permission

**Status: PERMISSION RECEIVED for CTAS directory data. MTAS: not yet answered.**
Recorded 2026-10-08. Source: two replies from CTAS staff to the Beholden Maintainers'
request of 2026-10 (reply dated 2026-10-05). Names and addresses of individual staff are
deliberately not recorded here.

## Verbatim wording

> The information included in the CTAS Directory is public information and may be
> republished with appropriate credit and a link back to CTAS as the source.
>
> The directory also includes a public CSV export for each county office group. To access
> it, select Directory > County Offices, choose the appropriate office group, and click the
> orange CSV button in the upper-right corner of the list. [...]
>
> We do not provide an API or additional bulk data access beyond the publicly available
> CSV exports.

A second reply from a different CTAS staff member said the same about the CSV export and
added that they have no other options to download in bulk or keep the lists updated, and
that MTAS "has the same export options on its website".

## What this permits, and the conditions

- Republishing the CTAS directory's county-office information: **yes**, free site and
  paid dataset alike are *republication*; the reply states no restriction on either, but
  it does not mention redistribution as a priced bulk product. Treat the paid dataset as
  covered only to the same conditions until CTAS is asked.
- **Condition 1:** every published record carries credit to CTAS and a link back to
  the CTAS directory page it came from (source envelope `source_url`, and visible credit
  in the dossier and on the Sources page).
- **Condition 2:** use only the public per-office-group CSV exports. No API or bulk feed
  exists; fetch politely (one export per group, cached, no more than nightly).
- **Not covered:** MTAS (cities). Its staff were not the authors of these replies. The
  statement that MTAS offers the same exports is not MTAS's own permission. Ask MTAS
  directly, in writing, before any MTAS-derived record ships.

## Source quality (grade)

Government-published directory maintained by a public university; the data is entered by
county offices, so currency varies. Publish as grade B (official, structured, not
authoritative for term dates) and show "as reported by CTAS" with the retrieval date.

## How the pipeline applies it (WO-22b Part B)

This file is the `terms_ref` of the 94 county specs in
`pipelines/beholden_etl/sources/tn_ctas.py`; Sumner County is left to its own roster.

- **Fetch:** the County Commissioners and the County Executives and Mayors CSV exports, each
  once per run, 1s apart, and only when a county's 7-day SLA is due. The User-Agent names the
  project contact. A 403 or 429 stops the fetch with no retry, and the counties keep their
  last good roster.
- **Credit and link back:** every record's source envelope links to its county's CTAS
  directory page (`/county/{name}`), and the provenance line reads "as reported by UT County
  Technical Assistance Service (CTAS), retrieved <date>". The Sources page names CTAS.
- **Published fields (owner decision 2026-10-08):** name, office title and county, and an
  email only when its domain is a government domain (`*.gov`, `*.tn.us`, or the county's
  own website domain as CTAS lists it). Street addresses, fax, phone and personal mailboxes
  are dropped before anything is stored. No photos. Party is "U".
- **Expected size:** "Number of Commissioners" on each county's CTAS page, read once on
  2026-10-08 and fixed in the spec. These pages were read to set the expected sizes only;
  nothing is republished from them.
