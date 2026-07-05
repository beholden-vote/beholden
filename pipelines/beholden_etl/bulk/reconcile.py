"""Fail-closed reconciliation gates (docs/TRUSTED-EXTRACTION.md §5).

Each gate HALTS the run on failure by raising a GateError — none may be softened
to make a run pass. Import these from the transform stage and call them around the
copy-only parse; nothing proceeds to build until every gate passes.

  - schema_drift_gate      : observed header must match the pinned contract exactly
  - control_total_gate     : Σ(itemized) per group == the companion feed's control total
  - no_silent_drop_gate    : input == inserted + quarantined, always
  - value-domain           : enforced per-row by the adapter's mappers, which
                             QUARANTINE (never coerce) an out-of-domain cell; this
                             module asserts the resulting invariant holds.

The value-domain check is deliberately row-level and non-raising: a single bad
enum/date/amount is quarantined with a reason (§5), not a run-ending event. The
run-ending gates are schema drift, an unreconciled control total, and any breach
of the no-silent-drop invariant.
"""
from __future__ import annotations

from .contract import SourceContract, check_schema_drift


class GateError(RuntimeError):
    """A fail-closed gate halted the run. Never caught to let a run proceed."""


class SchemaDriftError(GateError):
    pass


class ControlTotalError(GateError):
    pass


class SilentDropError(GateError):
    pass


def schema_drift_gate(contract: SourceContract, observed_header) -> None:
    """Halt unless the observed header matches the contract fingerprint exactly."""
    drift = check_schema_drift(contract, observed_header)
    if drift is not None:
        raise SchemaDriftError(
            f"schema-drift gate: {contract.source_id} header does not match "
            f"contract {contract.contract_version}: {drift.message()}")


def control_total_gate(itemized_sums_cents: dict, control_totals_cents: dict,
                       epsilon_cents: int, source_id: str) -> None:
    """Σ(itemized) per group must equal the companion feed's control total.

    itemized_sums_cents : {group_key: summed integer cents from the itemized rows}
    control_totals_cents: {group_key: the companion feed's reported total, in cents}
    Every itemized group MUST have a matching control total and reconcile within
    epsilon; a group present in the itemized data with no control total is itself a
    failure (no reconciliation basis -> halt, per the WO: never ship itemized data
    without a reconciliation basis). Groups that exist only in the control feed are
    ignored — a filer can report a summary total yet itemize nothing.
    """
    mismatches = []
    for group, got in sorted(itemized_sums_cents.items()):
        expected = control_totals_cents.get(group)
        if expected is None:
            mismatches.append(f"{group}: itemized sum {got}c has NO control total")
            continue
        if abs(got - expected) > epsilon_cents:
            mismatches.append(f"{group}: itemized {got}c vs control {expected}c "
                              f"(delta {got - expected}c > eps {epsilon_cents}c)")
    if mismatches:
        raise ControlTotalError(
            f"control-total gate: {source_id} failed for {len(mismatches)} group(s): "
            + " | ".join(mismatches[:20]))


def no_silent_drop_gate(input_rows: int, inserted: int, quarantined: int,
                        source_id: str) -> None:
    """Assert the no-silent-drop invariant: input == inserted + quarantined."""
    if input_rows != inserted + quarantined:
        raise SilentDropError(
            f"no-silent-drop gate: {source_id} input={input_rows} != "
            f"inserted={inserted} + quarantined={quarantined} "
            f"(unaccounted {input_rows - inserted - quarantined})")
