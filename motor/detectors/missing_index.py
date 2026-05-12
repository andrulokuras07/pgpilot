"""Detector D16 — Seq Scan sobre tabla grande sin índice en columna del filtro.

Detecta el caso simétrico de C1: hay un Seq Scan sobre una tabla
≥100k filas, hay un filtro WHERE inferible, y **NO** existe un índice
btree cuya primera columna sea la del filtro. La recomendación natural
es `CREATE INDEX`.

Cubre Q01/Q06/Q08/Q09 del plan de AppDB v1 (todos `posts.author_id`
sin índice). Frontera explícita con C1: C1 = "índice existe y se
ignora" → recomendación `ANALYZE`; D16 = "índice falta" → recomendación
`CREATE INDEX`.

Cumple R1, R2, R9, R14.
"""

from __future__ import annotations

from typing import Any

from motor.detection import Detection
from motor.detectors._common import (
    LARGE_TABLE_MIN_ROWS,
    column_from_filter,
    has_btree_index_on_column,
    resolve_table_key,
)
from motor.nodes import find_nodes
from motor.parser import ExplainResult, PlanNode


def detect_missing_index(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
) -> Detection:
    """Encuentra Seq Scans sobre tablas grandes sin índice apuntable.

    Args:
        plan: árbol del plan parseado por `motor.parse_explain`.
        snapshot: SchemaSnapshot del conector (usa `schema` y `sizes`).

    Returns:
        Detection con un match por ocurrencia en `evidence["matches"]`.
        Cada match incluye la columna candidata a indexar y el SQL
        sugerido para que el recomendador lo enriquezca.
    """
    schema = snapshot.get("schema", {})
    sizes = snapshot.get("sizes", {})

    matches: list[dict[str, Any]] = []

    for node in find_nodes(plan, "Seq Scan"):
        relation = node.relation_name
        if relation is None:
            continue

        size_key = resolve_table_key(sizes, relation)
        if size_key is None:
            continue
        size_info = sizes[size_key]

        estimated_rows = size_info.get("estimated_rows", 0)
        if estimated_rows < LARGE_TABLE_MIN_ROWS:
            continue

        column = column_from_filter(node.filter)
        if column is None:
            continue

        # Frontera con C1: si ya hay un btree apuntable, NO disparamos.
        # Ese caso es "stats desactualizadas" — competencia de C1.
        table_meta = schema.get(size_key)
        has_index, _ = has_btree_index_on_column(table_meta, column)
        if has_index:
            continue

        # Nombre tentativo del índice. Sin schema prefix porque el SQL
        # final lo arma el recomendador con el nombre completo de tabla.
        table_name_only = size_key.split(".")[-1]
        suggested_index_name = f"idx_{table_name_only}_{column}"
        suggested_sql = f"CREATE INDEX {suggested_index_name} " f"ON {size_key} ({column});"

        matches.append(
            {
                "table": size_key,
                "column": column,
                "estimated_rows": estimated_rows,
                "rows_removed_by_filter": node.rows_removed_by_filter,
                "filter": node.filter,
                "suggested_index_name": suggested_index_name,
                "suggested_sql": suggested_sql,
            }
        )

    return Detection(
        found=bool(matches),
        confidence=0.95 if matches else 0.0,
        evidence={"matches": matches},
    )
