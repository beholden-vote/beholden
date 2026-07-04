"""DuckDB warehouse (free-tier arch §1.2): load the canonical Postgres DDL from
db/migrations with the documented shims, plus dumb typed insert helpers. The
transform/build jobs talk to this module, never to raw connections.

Shims (Postgres -> DuckDB), all mechanical and reversible:
  gen_random_uuid() -> uuid()      VECTOR(n) -> FLOAT[n]      JSONB -> JSON
  ON DELETE CASCADE -> (dropped)    partial-index WHERE -> (dropped)
  GENERATED ... STORED -> VIRTUAL   self-referential FKs -> (dropped)
DuckDB enforces the remaining PK/UNIQUE/CHECK/FK constraints, so insertion order
in transform still matters (persons/divisions/offices before their dependents).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

import duckdb

MIGRATIONS = Path(__file__).resolve().parents[1].parent / "db" / "migrations"


def _shim(sql: str) -> str:
    sql = sql.replace("gen_random_uuid()", "uuid()")
    sql = re.sub(r"VECTOR\((\d+)\)", r"FLOAT[\1]", sql)
    sql = re.sub(r"\bJSONB\b", "JSON", sql)
    sql = sql.replace(" ON DELETE CASCADE", "")
    sql = sql.replace(" STORED", "")                       # DuckDB generated cols are VIRTUAL
    sql = re.sub(r"\s+WHERE\s+end_date\s+IS\s+NULL", "", sql, flags=re.I)  # no partial indexes
    # Self-referential FKs (divisions.parent_ocd, committees.parent_id) — DuckDB
    # rejects a FK to the table being created. Integrity is upheld in transform.
    sql = re.sub(r"\s+REFERENCES\s+divisions\(ocd_id\)", "", sql)
    sql = re.sub(r"\s+REFERENCES\s+committees\(committee_id\)", "", sql)
    return sql


def _statements(sql: str) -> list[str]:
    """Split a migration into individual statements (strip line comments first)."""
    no_comments = "\n".join(re.sub(r"--.*$", "", ln) for ln in sql.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def connect(path: str = ":memory:") -> duckdb.DuckDBPyConnection:
    return duckdb.connect(path)


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    for f in sorted(MIGRATIONS.glob("*.sql")):
        for stmt in _statements(_shim(f.read_text())):
            con.execute(stmt)


# JSON-typed columns take a serialized string; TEXT[] columns take a Python list.
_JSON_COLUMNS = {"raw_payload", "llm_suggestion", "meta"}


def _coerce(col: str, val: Any) -> Any:
    if col in _JSON_COLUMNS and val is not None and not isinstance(val, str):
        return json.dumps(val)
    return val


def insert(con: duckdb.DuckDBPyConnection, table: str, rows: Iterable[dict],
           ignore_conflicts: bool = True) -> int:
    """Bulk INSERT. Columns are taken from the first row; every row must share
    them. ON CONFLICT DO NOTHING makes nightly re-runs idempotent."""
    rows = list(rows)
    if not rows:
        return 0
    cols = list(rows[0].keys())
    ph = ",".join("?" * len(cols))
    conflict = " ON CONFLICT DO NOTHING" if ignore_conflicts else ""
    con.executemany(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({ph}){conflict}",
        [[_coerce(c, r.get(c)) for c in cols] for r in rows],
    )
    return len(rows)
