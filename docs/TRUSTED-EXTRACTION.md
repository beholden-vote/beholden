# Trusted extraction — turning bulk public records into cited facts without hallucinating

**Status:** design (2026-07-05). Governs any pipeline that ingests bulk government
disclosure (state SOS campaign finance, lobbying, procurement, and similar) into
published dossier facts.

This document exists because the obvious tool — "point a model at the documents and
ask it what they say" — is the exact wrong tool. A model that can parse anything can
invent anything. Trust here does not come from a clever universal parser; it comes from
**per-source contracts** plus **fail-closed gates**. We trade breadth for verifiability,
on purpose.

It is a direct application of the three inviolable rules (`AGENTS.md`) to a new class of
source: *no provenance, no publish · fail closed · symmetric by construction.*

---

## 1. The one principle

> **Extraction copies verbatim values from a known cell in a known file. It never
> infers, computes, interprets, or generates.**

A fact that lands on a dossier must be reproducible by re-running a deterministic parser
over an immutable, content-hashed snapshot — with **no model in the loop**. If a value
cannot be traced to an exact location in an exact versioned file, it does not publish.

"Hallucination" is defined operationally as **any published fact not deterministically
traceable to a source cell.** The framework's whole job is to make that condition
impossible to reach, not merely unlikely.

## 2. What is eligible (tiering)

| Tier | Shape | Example | Extraction | v1? |
|------|-------|---------|-----------|-----|
| **A — Structured** | Documented CSV/TSV/fixed-width/XML/JSON with a published record layout | WA PDC Socrata feeds, TX TEC bulk, CA CAL-ACCESS | Deterministic parse against a pinned contract. **Zero ML.** | ✅ Yes |
| **B — Semi-structured** | Consistent form PDFs / HTML tables with stable anchors | State disclosure form PDFs | Grounded extractive + deterministic verifier (§7). Gated, later. | ⛔ Later |
| **C — Unstructured** | Scanned images, free text, OCR | Handwritten filings | **Out of scope.** No trustworthy path today. | ❌ No |

Tier A covers the large majority of the value. We build only Tier A first. Tier B is a
separately-gated add-on that never touches the Tier A path. Tier C is not attempted —
consistent with the earlier decision to reject PTR PDF OCR.

## 3. The Source Contract (pinned, versioned)

Every source is described by a committed, versioned contract before a single row is
ingested. Drift from the contract halts the pipeline (§5).

```
SourceContract:
  source_id           # e.g. "wa_pdc_contributions"
  jurisdiction        # OCD division the source covers, e.g. "ocd-division/country:us/state:wa"
  layout_doc_url      # official record-layout / data-dictionary URL (human reference)
  retrieval           # how to fetch: url(s), format, pagination
  fields[]            # name, type, value-domain (enum/range/format), nullable, is_key
  control_totals      # field(s) + companion source that must reconcile (§5)
  record_locator      # how a single fact points back (row id / byte offset / native id + url)
  license             # verbatim terms + public-domain determination (§8)
  contract_version    # bumped when the layout changes; old versions retained
```

The contract is the trust boundary. Everything downstream trusts the contract, and the
contract is small, human-readable, and reviewed.

## 4. Pipeline stages

Mirrors the existing `fetch → transform → build` spine; reuses `store`, the provenance
envelope, and the gate machinery.

1. **Fetch → snapshot + hash.** Download to the raw lake, record a SHA-256 of the exact
   bytes, and the retrieval timestamp. Snapshots are immutable. If the source silently
   re-releases a same-named file with different content, the hash mismatch **forces a
   re-review** — it can never become a silent data change.
2. **Parse → contract-validated, deterministic.** Validate header/shape against the
   pinned contract; copy values only; attach a per-row provenance envelope (§6). No
   destructive normalization, no computed fields, no interpretation.
3. **Reconcile → fail-closed gates (§5).** Nothing proceeds to `build` until every gate
   passes. A failed gate halts the run.
4. **Link → deterministic-key crosswalk only (§9).** Attach filer records to the person
   spine on strong keys; everything probabilistic is quarantined, never published.

## 5. Fail-closed gates (the reconciliation stage)

Each gate halts the pipeline on failure — none may be softened to make a run pass.

- **Schema-drift gate.** The file's header/field fingerprint must match the pinned
  contract exactly. Mismatch → halt (do **not** best-effort parse a changed layout).
- **Control-total gate.** Σ(itemized values) must equal the source's own reported
  summary/control total, sourced from the companion feed named in the contract. Any
  mismatch beyond a declared rounding epsilon → halt. This single gate catches the
  majority of parse errors.
- **No-silent-drop invariant.** `input_rows == published + quarantined`, always. Every
  input row is accounted for — published, or quarantined **with a recorded reason**.
  Nothing is allowed to silently vanish.
- **Value-domain gate.** Values outside the contract's declared domain (bad enum, date,
  amount sign/format) are quarantined with a reason — **never coerced** into range.
- **Idempotence / golden-fixture gate (CI).** A committed real sample plus its expected
  output proves the parser is stable and re-parse is byte-identical. Runs in CI.

## 6. Provenance envelope (per extracted fact)

Every extracted value carries enough to reconstruct exactly where it came from:

```
{ source_id, contract_version, file_sha256, retrieved_at,
  record_locator,        # native record id / row / byte offset
  source_record_url,     # per-record official link where the source provides one
  raw_value }            # the verbatim cell, before any downstream normalization
```

The raw value is retained forever. Downstream normalization (name casing, entity links)
is a separate, reviewable layer that **never discards the raw value** and never claims
more confidence than it has.

## 7. Where LLMs are allowed — and where they are forbidden

**Forbidden:** emitting, or influencing the value of, any published fact in Tier A. The
extraction path has no model in it. Full stop.

**Allowed, confined to two roles:**

1. **Author-time tooling (offline, human-reviewed).** A model may read a record-layout
   document and *draft* a `SourceContract` or parser code. A human reviews and commits
   it. The model writes code and config, never data. Its output is reviewed like any PR.
2. **Tier B only — grounded extractive with a deterministic verifier.** If a field must
   be pulled from a consistent form PDF, the model proposes an **extractive span**, and a
   non-LLM verifier **rejects** it unless the string appears *verbatim* in the source at
   the expected anchor region. Model proposes, deterministic check disposes, fail closed.
   Abstractive/summarized output is rejected outright. This is out of v1 scope.

## 8. License / terms handling

SOS bulk data is usually public record and often explicitly public domain — which is the
whole reason it is the license-clean alternative to restrictive aggregators (see
`docs/research/state-money-evaluation.md` for why FollowTheMoney is a no-go). But terms
vary **per state** — some bulk feeds carry no-commercial-resale clauses. The contract
records the verbatim terms and an explicit public-domain determination; a source with
incompatible terms does not ship. (The WA PDC pilot source is explicitly Public Domain.)

## 9. Entity resolution — the actual hallucination risk

Parsing is the safe part. **Linking a donor/filer to a person in our spine is where
fabrication would enter**, and it is the same trap that made us defer Shor-McCarty
name-matching.

- **Publish only on deterministic keys** — native filer IDs, FEC IDs, OCD IDs.
- **Fuzzy name/employer matches → a scored candidate table, never auto-published.** They
  render as "unlinked," or require a reviewed allowlist to promote. Probabilistic linkage
  is quarantine, not publication.
- Aggregations (e.g. top contributors, employer rollups) are computed by a **fixed,
  symmetric rule applied identically regardless of party**, over the deterministically
  extracted rows only.

## 10. Repo layout

```
pipelines/beholden_etl/
  bulk/
    contract.py        # SourceContract type + load/validate
    reconcile.py       # the fail-closed gates (§5)
  sources/
    <state>_disclosure.py   # one adapter per source; declares its SourceContract
  jobs/                # fetch/transform/build wiring, mirroring existing verticals
db/migrations/
  00N_disclosure.sql   # disclosure_filings / disclosure_contributions / *_quarantine tables
```

Reuses `store.py` (schema loader + typed insert) and the existing `_provenance()` path —
no bypass of the dossier provenance validator is ever added.

## 11. Non-goals

- No universal document parser. Trust is per-contract; a "parse anything" component would
  be the opposite of trustworthy.
- No Tier C (scanned/free-text) extraction into published facts.
- No probabilistic entity links in published output.
- No lowering of any gate threshold to make a run pass.

---

## 12. Contract notes — the first real SourceContract

### `wa_pdc` — Washington PDC itemized contributions (Tier A, verified 2026-07-05)

The reference implementation (WO-9). Declared in `pipelines/beholden_etl/sources/wa_pdc.py`
as `CONTRACT`; the framework types live in `pipelines/beholden_etl/bulk/`
(`contract.py`, `reconcile.py`); rows land in `db/migrations/004_disclosure.sql`
(`disclosure_contributions` + `disclosure_quarantine`). Not surfaced in the dossier UI
yet — a deterministic filer↔legislator crosswalk is an explicit follow-on.

| Field | Value |
|---|---|
| `source_id` | `wa_pdc` |
| `contract_version` | `2026-07-05` |
| `jurisdiction` | `ocd-division/country:us/state:wa` |
| Itemized dataset | Socrata `kv7h-kjye` — "Contributions to Candidates and Political Committees" |
| Itemized JSON | `https://data.wa.gov/resource/kv7h-kjye.json` (`$limit`/`$offset`, `$order=id`) |
| Itemized bulk CSV | `https://data.wa.gov/api/views/kv7h-kjye/rows.csv?accessType=DOWNLOAD` |
| `record_locator` | `id` (native Socrata record id) |
| `source_record_url` | `url` (per-record link to the official filed report PDF) |
| **License** | **Public Domain** — attribution: Public Disclosure Commission (http://pdc.wa.gov) |
| Schema-drift fingerprint | the exact 37-field header (`wa_pdc.ITEMIZED_HEADER`); any add/drop/rename/reorder halts |

**Control total (the reconciliation basis actually used).** Companion dataset Socrata
`3h9x-7bvm` — "Campaign Finance Summary" (also Public Domain). The field is
**`contributions_amount`**, grouped by **`(filer_id, election_year)`** — one summary row
per group. Σ(itemized `amount`) for a group must equal that group's `contributions_amount`
**exactly** (`epsilon_cents = 0`). Verified live: filer `24THLD 362`, election_year 2025 —
six itemized cash contributions summing to $2,183.00, matching the summary total to the
cent. An itemized (filer, year) group with **no** matching summary total is a gate failure
(never ship itemized data without a reconciliation basis); a filer that reports a summary
total but itemizes nothing is simply out of scope for this dataset.

**Value domains.** `cash_or_in_kind ∈ {Cash, In-kind}` (verified exhaustive). `amount` is a
signed number — negatives (refunds/corrections) are legitimate and preserved, never clamped.
A bad enum, non-numeric amount, present-but-unparseable date, non-integer `election_year`,
or a missing key (`id`/`filer_id`/`url`) is **quarantined with a reason**, never coerced.

**Provenance envelope (per row).** `source_id`, `contract_version`, `file_sha256`,
`retrieved_at`, `record_locator` (native `id`), `source_record_url` (`url`), plus the
verbatim `raw_amount` and `raw_contributor_name` cells retained forever (§6).

**Entity resolution.** Rows are keyed by WA `filer_id` only — deliberately **not**
fuzzy-matched to the person spine. Unlinked is honest; a wrong link is not (§9).

**First implementation:** `docs/workplan/WO-9-sos-disclosure-pilot.md` — a single-state
Tier A pilot against WA PDC (public domain), proving the contract + gates end to end
before any second state is added.
