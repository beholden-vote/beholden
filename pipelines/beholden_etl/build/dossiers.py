"""Dossier JSON builder + provenance validator (ticket E5-2).
THE rule of the serving layer: no provenance, no publish."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

from ..config import GRADE_REASONS

SCHEMA_VERSION = "1.0"
# WO-28: grade/grade_reason are REQUIRED, not decorative. An ungraded section
# would render indistinguishably from a bulk-API one, so the absence of a grade
# is itself a provenance failure — same treatment as a null retrieved_at.
REQUIRED_PROVENANCE = {"source", "source_url", "retrieved_at", "pipeline_version",
                       "grade", "grade_reason"}
# identity is universal; the rest are published only where the data exists (a
# state legislator has no DW-NOMINATE or federal bill record). The rule is "no
# provenance, no publish" per SECTION — not "every dossier has every section".
REQUIRED_SECTIONS = ("identity",)
OPTIONAL_PROVENANCED_SECTIONS = ("ideology", "legislative")


class ProvenanceError(ValueError):
    pass


def _check_provenance(dossier: dict, section: str) -> None:
    prov = dossier.get(section, {}).get("provenance")
    # Keys must be present AND truthy — a null retrieved_at is no provenance.
    if not prov or not all(prov.get(k) for k in REQUIRED_PROVENANCE):
        raise ProvenanceError(f"{dossier.get('person_id')}: section '{section}' missing provenance")
    # WO-28: the grade must be the one its reason implies. Checking the pair
    # (rather than just "grade in GRADES") is what stops a caller hand-writing an
    # envelope that claims grade A for an OCR'd fact.
    reason, grade = prov["grade_reason"], prov["grade"]
    if reason not in GRADE_REASONS:
        raise ProvenanceError(
            f"{dossier.get('person_id')}: section '{section}' has unregistered "
            f"grade_reason {reason!r}")
    if grade != GRADE_REASONS[reason]:
        raise ProvenanceError(
            f"{dossier.get('person_id')}: section '{section}' claims grade {grade!r} "
            f"but reason {reason!r} implies {GRADE_REASONS[reason]!r}")


def validate(dossier: dict) -> None:
    for section in REQUIRED_SECTIONS:
        _check_provenance(dossier, section)
    for section in OPTIONAL_PROVENANCED_SECTIONS:
        if dossier.get(section) is not None:      # published => must be sourced
            _check_provenance(dossier, section)
    money = dossier.get("money", {})
    for trade in (money.get("trades", {}) or {}).get("items", []):
        if not trade.get("filing_url"):
            raise ProvenanceError("trade row without filing_url — contract violation")
    disc = money.get("disclosures")
    if disc:
        _check_provenance(dossier["money"], "disclosures")
        for f in disc.get("filings", []):
            if not f.get("filing_url"):
                raise ProvenanceError("disclosure filing without filing_url — contract violation")
    nw = money.get("net_worth")
    if nw and ("band" not in nw or nw["band"]["max_cents"] < nw["band"]["min_cents"]):
        raise ProvenanceError("net worth must be a valid band, never a point")


def build_one(person: dict, sections: dict, pipeline_version: str) -> dict:
    dossier = {
        "schema_version": SCHEMA_VERSION,
        "person_id": person["person_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **sections,
    }
    validate(dossier)
    return dossier


def publish(dossiers: list[dict], out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    for d in dossiers:
        (out_dir / f"{d['person_id']}.json").write_text(json.dumps(d, separators=(",", ":")))
    return len(dossiers)
