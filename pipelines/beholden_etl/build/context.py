"""What an artifact writer is handed by the build stage (WO-32).

`jobs/build.py` grew by one hand-wired block per feature until every new
artifact meant editing the same 1,200-line function. That is survivable with one
author and unworkable with several working at once: two lanes adding two
unrelated artifacts collide in the same forty lines.

A writer is now a module under `beholden_etl/build/` exposing

    def publish(ctx: BuildContext) -> dict[str, int]

registered by ONE line in `jobs/build.ARTIFACT_WRITERS`. It receives this
context, writes under `ctx.out`, and returns counts that land in
`coverage.json`. It opens its own warehouse connection from `ctx.db_path` —
the build's own connection is closed before writers run, deliberately, so a
writer cannot depend on build-internal query state.

This type lives here, not in `jobs/build.py`, so writers can import it without
importing the build job (which imports them — a cycle).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class BuildContext:
    db_path: str            # DuckDB warehouse; open your own connection
    raw_dir: Path           # landed raw snapshots (dist/raw)
    out: Path               # serving root (dist/data); write under a prefix you own
    manifest: dict          # fetch manifest: per-source retrieved_at etc.
    holders: list[dict]     # current officeholders, as build._current_holders returns them
    # Build's provenance factory, already bound to the manifest. Writers MUST
    # use it rather than assembling an envelope by hand: it is the one place
    # that refuses an unregistered source or a missing retrieved_at (rule #1),
    # and a hand-built envelope would bypass both checks.
    _provenance: Callable[..., dict]

    def provenance(self, source: str, source_url: str,
                   methodology_id: str | None = None,
                   grade_reason: str | None = None) -> dict:
        return self._provenance(source, source_url, self.manifest,
                                methodology_id, grade_reason)
