"""Parser de pg_stat_statements (CSV y JSON).

E1 del backlog: recibe un export de la vista pg_stat_statements en CSV
o JSON y devuelve una lista de StatementEntry con los campos que el
scoring y el endpoint necesitan.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StatementEntry:
    query: str
    calls: int
    total_exec_time: float
    mean_exec_time: float
    rows: int


def parse_pg_stat_statements(raw: str) -> list[StatementEntry]:
    """Parsea un export de pg_stat_statements en CSV o JSON.

    Heurística de formato: si el contenido empieza con '[' (después de
    strip), se trata como JSON array. Si no, se trata como CSV.

    Columnas esperadas (case-insensitive):
    - query
    - calls
    - total_exec_time (o total_time para PG < 13)
    - mean_exec_time (o mean_time para PG < 13)
    - rows
    """
    stripped = raw.strip()
    if not stripped:
        return []

    if stripped.startswith("["):
        return _parse_json(stripped)
    return _parse_csv(stripped)


def _normalize_record(record: dict[str, Any]) -> StatementEntry | None:
    lower = {k.lower().strip(): v for k, v in record.items()}

    query = lower.get("query", "").strip()
    if not query:
        return None

    calls = int(lower.get("calls", 0))
    total_exec_time = float(lower.get("total_exec_time") or lower.get("total_time", 0))
    mean_exec_time = float(lower.get("mean_exec_time") or lower.get("mean_time", 0))
    rows = int(lower.get("rows", 0))

    return StatementEntry(
        query=query,
        calls=calls,
        total_exec_time=total_exec_time,
        mean_exec_time=mean_exec_time,
        rows=rows,
    )


def _parse_json(raw: str) -> list[StatementEntry]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("El JSON debe ser un array de objetos.")
    entries = []
    for record in data:
        entry = _normalize_record(record)
        if entry is not None:
            entries.append(entry)
    return entries


def _parse_csv(raw: str) -> list[StatementEntry]:
    reader = csv.DictReader(io.StringIO(raw))
    entries = []
    for row in reader:
        entry = _normalize_record(row)
        if entry is not None:
            entries.append(entry)
    return entries
