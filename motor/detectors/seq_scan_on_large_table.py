"""Detector C1 — Seq Scan sobre tabla grande con índice btree disponible.

Detecta cuando Postgres hace Seq Scan sobre una tabla >100k filas
existiendo un índice btree sobre la columna del filtro WHERE.

NO cubre: tabla grande sin índice (eso es C2), Seq Scan por cast
implícito (eso es D11).

Cumple R1 (motor decide), R2 (estructura, no strings), R9 (función
pura), R14 (sin literales hardcoded).
"""

from __future__ import annotations

import re
from typing import Any

from motor.detection import Detection
from motor.nodes import find_nodes
from motor.parser import ExplainResult, PlanNode

# Umbral del backlog. Local en vez de importado de conector para no
# acoplar motor a constantes configurables de otro módulo.
LARGE_TABLE_MIN_ROWS = 100_000

# Saca el nombre de la primera columna del campo `Filter` del nodo.
# No viola R2: opera sobre texto generado por Postgres (estable),
# no sobre el SQL del usuario.
_FILTER_COLUMN_RE = re.compile(r"\(?\(?([a-zA-Z_][a-zA-Z0-9_]*)\s*[=<>!]")


def _column_from_filter(filter_expr: str | None) -> str | None:
    """Devuelve la primera columna del filtro, o None si no se puede inferir."""
    if not filter_expr:
        return None
    match = _FILTER_COLUMN_RE.search(filter_expr)
    return match.group(1) if match else None


def _has_btree_index_on_column(
    table_meta: dict[str, Any] | None,
    column: str,
) -> tuple[bool, str | None]:
    """¿Hay un btree cuya PRIMERA columna sea `column`?

    Solo cuenta la primera porque un índice (a, b) no acelera
    WHERE b = X — así funciona el planner de Postgres.
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


def detect_seq_scan_on_large_table(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
) -> Detection:
    """Encuentra Seq Scans sobre tablas grandes con índice ignorado.

    Args:
        plan: árbol del plan parseado por `motor.parse_explain`.
        snapshot: SchemaSnapshot del conector (usa `schema` y `sizes`).

    Returns:
        Detection con un match por ocurrencia en `evidence["matches"]`.
    """
    schema = snapshot.get("schema", {})
    sizes = snapshot.get("sizes", {})

    matches: list[dict[str, Any]] = []

    for node in find_nodes(plan, "Seq Scan"):
        # Sin tabla identificada (ej. Seq Scan sobre VALUES) no aplica.
        relation = node.relation_name
        if relation is None:
            continue

        # El plan trae "posts"; el snapshot lo guarda como "public.posts".
        size_key = _resolve_table_key(sizes, relation)
        if size_key is None:
            continue
        size_info = sizes[size_key]

        # Tabla pequeña → Seq Scan probablemente es óptimo, ignoramos.
        estimated_rows = size_info.get("estimated_rows", 0)
        if estimated_rows < LARGE_TABLE_MIN_ROWS:
            continue

        # Sin filtro o columna no inferible → no hay nada que indexar.
        column = _column_from_filter(node.filter)
        if column is None:
            continue

        # Frontera con C2: si no hay índice, NO disparamos C1.
        # C1 = "índice existe y se ignora". "Índice falta" lo cubre C2.
        table_meta = schema.get(size_key)
        has_index, index_name = _has_btree_index_on_column(table_meta, column)
        if not has_index:
            continue

        matches.append(
            {
                "table": size_key,
                "column": column,
                "estimated_rows": estimated_rows,
                "rows_removed_by_filter": node.rows_removed_by_filter,
                "index_name": index_name,
                "filter": node.filter,
            }
        )

    return Detection(
        found=bool(matches),
        confidence=1.0 if matches else 0.0,
        evidence={"matches": matches} if matches else {},
    )


def _resolve_table_key(
    sizes: dict[str, Any],
    relation_name: str,
) -> str | None:
    """Traduce "posts" (del plan) a "public.posts" (clave del snapshot)."""
    suffix = f".{relation_name}"
    for key in sizes:
        if key.endswith(suffix) or key == relation_name:
            return key
    return None
