"""Dossier JSON builder + provenance validator (ticket E5-2).
THE rule of the serving layer: no provenance, no publish."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0"
REQUIRED_PROVENANCE = {"source", "source_url", "retrieved_at", "pipeline_version"}
SECTIONS_REQUIRING_PROVENANCE = ("identity", "ideology", "legislative")


class ProvenanceError(ValueError):
    pass


def validate(dossier: dict) -> None:
    for section in SECTIONS_REQUIRING_PROVENANCE:
        prov = dossier.get(section, {}).get("provenance")
        if not prov or not REQUIRED_PROVENANCE.issubset(prov):
            raise ProvenanceError(f"{dossier.get('person_id')}: section '{section}' missing provenance")
    money = dossier.get("money", {})
    for trade in (money.get("trades", {}) or {}).get("items", []):
        if not trade.get("filing_url"):
            raise ProvenanceError("trade row without filing_url — contract violation")
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
