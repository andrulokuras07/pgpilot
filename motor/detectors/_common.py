"""Helpers compartidos entre detectores.

Extraídos de `seq_scan_on_large_table.py` para evitar duplicación
cuando llegó D16 (mismo razonamiento de "Seq Scan sobre tabla grande
con filtro inferible"). C1 y D16 comparten ~80% de la prelógica:
identificación de la tabla, umbral de tamaño, extracción de la
columna del filtro y resolución del índice btree.

Nada de esto opera sobre el SQL del usuario (R2): los regex viven
sobre texto que emite Postgres en el campo `Filter`/`Index Cond`,
que es estable y documentado.
"""

from __future__ import annotations

import re
from typing import Any

# Umbral compartido por C1 y D16. Centralizado para que un cambio
# futuro (ej. >500k) se aplique a ambos sin desincronizarse.
LARGE_TABLE_MIN_ROWS = 100_000

# Captura la primera columna comparada en un Filter típico de Postgres:
# "(col = X)", "(col > X)", "((col)::tipo = X)" → "col".
_FILTER_COLUMN_RE = re.compile(r"\(?\(?([a-zA-Z_][a-zA-Z0-9_]*)\s*[=<>!]")


def column_from_filter(filter_expr: str | None) -> str | None:
    """Devuelve la primera columna del filtro, o None si no se puede inferir."""
    if not filter_expr:
        return None
    match = _FILTER_COLUMN_RE.search(filter_expr)
    return match.group(1) if match else None


def has_btree_index_on_column(
    table_meta: dict[str, Any] | None,
    column: str,
) -> tuple[bool, str | None]:
    """¿Hay un btree cuya PRIMERA columna sea `column`?

    Solo cuenta la primera porque un índice `(a, b)` no acelera
    `WHERE b = X` — así funciona el planner de Postgres.
    """
    if table_meta is None:
        return (False, None)
    for idx in table_meta.get("indexes", []):
        if idx.get("method") != "btree":
            continue
        cols = idx.get("columns", [])
        if cols and cols[0] == column:
            return (True, idx.get("name"))
    return (False, None)


def resolve_table_key(
    keyed_dict: dict[str, Any],
    relation_name: str,
) -> str | None:
    """Traduce "posts" (del plan) a "public.posts" (clave del snapshot).

    Funciona con cualquiera de los sub-dicts del snapshot
    (`schema`, `sizes`, `stats`) porque todos usan la misma convención
    de claves `"<schema>.<tabla>"`.
    """
    suffix = f".{relation_name}"
    for key in keyed_dict:
        if key.endswith(suffix) or key == relation_name:
            return key
    return None
