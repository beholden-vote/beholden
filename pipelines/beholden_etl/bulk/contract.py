"""SourceContract — the pinned, versioned trust boundary for a Tier-A source
(docs/TRUSTED-EXTRACTION.md §3). Everything downstream trusts the contract; the
contract is small, human-readable, and reviewed. A source adapter declares one
of these before a single row is ingested.

The contract also carries the schema-drift fingerprint: the exact, ordered set of
field names the parser was written against. `check_schema_drift` compares an
observed header against it and, on any mismatch, returns a SchemaDrift describing
the difference so the gate can halt (§5) — it never best-effort parses a changed
layout.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    """One declared column: its name, coarse type, and value-domain.

    domain, when set, is the closed set of legal values (used by the value-domain
    gate for enum columns). type is a coarse tag ("text"/"number"/"date"/"url")
    for human review; the parser does the actual coercion.
    """
    name: str
    type: str
    domain: tuple[str, ...] | None = None
    nullable: bool = True
    is_key: bool = False


@dataclass(frozen=True)
class ControlTotal:
    """Where the reconciliation control total comes from (§5 control-total gate).

    companion_source_id : the summary/companion feed's id (recorded, human ref)
    total_field         : the field on the companion feed that Σ(itemized) must equal
    group_by            : the columns the companion feed groups its total by; the
                          itemized sum is grouped identically before comparison
    sum_field           : the itemized field summed (dollars) before comparison
    epsilon_cents       : declared rounding tolerance, in integer cents
    """
    companion_source_id: str
    total_field: str
    group_by: tuple[str, ...]
    sum_field: str
    epsilon_cents: int = 0


@dataclass(frozen=True)
class SourceContract:
    source_id: str
    jurisdiction: str          # OCD division the source covers
    layout_doc_url: str        # official record-layout / metadata URL (human reference)
    retrieval: dict            # how to fetch: {"format","bulk_csv","json","paging",...}
    header: tuple[str, ...]    # exact, ordered field-name fingerprint (schema-drift gate)
    fields: tuple[Field, ...]  # the subset we read, with types + value-domains
    control_total: ControlTotal
    record_locator: str        # field that points a single fact back (native id)
    source_record_url: str     # field carrying the per-record official link
    license: str               # verbatim license terms
    license_is_public_domain: bool
    attribution: str
    contract_version: str      # bumped when the layout changes; old versions retained

    def field(self, name: str) -> Field | None:
        return next((f for f in self.fields if f.name == name), None)

    def domain(self, name: str) -> tuple[str, ...] | None:
        f = self.field(name)
        return f.domain if f else None


@dataclass(frozen=True)
class SchemaDrift:
    """A description of how an observed header diverged from the contract."""
    missing: tuple[str, ...]        # declared, but absent from the observed header
    unexpected: tuple[str, ...]     # present in the header, but not declared
    reordered: bool                 # same set, different order

    def message(self) -> str:
        parts = []
        if self.missing:
            parts.append(f"missing={list(self.missing)}")
        if self.unexpected:
            parts.append(f"unexpected={list(self.unexpected)}")
        if self.reordered and not (self.missing or self.unexpected):
            parts.append("fields reordered")
        return "; ".join(parts) or "unknown drift"


def check_schema_drift(contract: SourceContract, observed_header) -> SchemaDrift | None:
    """Compare an observed header against the contract's pinned fingerprint.

    Returns None when the header matches EXACTLY (same fields, same order), else a
    SchemaDrift. The match must be exact — a drifted layout is never parsed on a
    best-effort basis (docs/TRUSTED-EXTRACTION.md §5 schema-drift gate).
    """
    observed = tuple(observed_header)
    declared = contract.header
    if observed == declared:
        return None
    obs_set, dec_set = set(observed), set(declared)
    missing = tuple(f for f in declared if f not in obs_set)
    unexpected = tuple(f for f in observed if f not in dec_set)
    reordered = obs_set == dec_set          # same fields, only the order differs
    return SchemaDrift(missing=missing, unexpected=unexpected, reordered=reordered)
