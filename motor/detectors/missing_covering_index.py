"""Detector D10 — Falta de índice cubriente.

Detecta cuando el plan contiene un `Index Scan` (no `Index Only
Scan`) sobre una tabla. Cada fila devuelta por un `Index Scan`
obliga a Postgres a hacer un heap fetch para resolver las columnas
no indexadas; si todas las columnas que la query realmente necesita
cupieran en el índice, ese trabajo desaparece y el plan pasa a
`Index Only Scan`.

Recomendación: agregar las columnas usadas en `SELECT`/`WHERE` como
`INCLUDE` del índice existente, o crear un índice nuevo que las
cubra. La detección es estructural; la lista exacta de columnas para
el `INCLUDE` la propone el recomendador (que cruza con el SQL
sanitizado y el snapshot).

Cumple R1, R2, R9, R14.
"""

from __future__ import annotations

from typing import Any

from motor.detection import Detection
from motor.nodes import find_nodes
from motor.parser import ExplainResult, PlanNode

# Umbral de filas por debajo del cual D10 no reporta. Un Index Scan
# que devuelve poquitas filas (lookup por PK, filtro muy selectivo)
# casi nunca se beneficia de un cubriente: el heap fetch ahorrado es
# despreciable y el INCLUDE solo hace el índice más caro y lento de
# mantener. Filtrar aquí elimina la mayoría de FPs estructurales
# obvios. Por encima del umbral, el recomendador (con sandbox)
# decide si el cubriente realmente ayuda.
INDEX_SCAN_MIN_ROWS = 50


def detect_missing_covering_index(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
) -> Detection:
    """Encuentra Index Scans donde un INCLUDE habilitaría Index Only Scan.

    Args:
        plan: árbol del plan parseado.
        snapshot: SchemaSnapshot del conector. Se usa para reportar
            el índice existente que se podría extender.

    Returns:
        Detection con un match por Index Scan candidato (descarta los
        que devuelven <INDEX_SCAN_MIN_ROWS filas).
    """
    schema = snapshot.get("schema", {})

    matches: list[dict[str, Any]] = []

    for node in find_nodes(plan, "Index Scan"):
        if node.relation_name is None:
            continue

        # Index Scans que devuelven poquitas filas: el heap fetch
        # ahorrado es despreciable, no vale la pena un cubriente.
        rows = node.actual_rows if node.actual_rows is not None else node.plan_rows
        if rows < INDEX_SCAN_MIN_ROWS:
            continue

        table_key = _resolve_table_key(schema, node.relation_name)
        existing_index = _find_index_meta(schema.get(table_key), node.index_name)

        matches.append(
            {
                "table": table_key or node.relation_name,
                "index_name": node.index_name,
                "index_cond": node.index_cond,
                "indexed_columns": (
                    list(existing_index.get("columns", []))
                    if existing_index
                    else None
                ),
                "include_columns": (
                    list(existing_index.get("include", []))
                    if existing_index
                    else None
                ),
            }
        )

    return Detection(
        found=bool(matches),
        confidence=0.7 if matches else 0.0,
        evidence={"matches": matches},
    )


def _resolve_table_key(schema: dict[str, Any], relation: str) -> str | None:
    """Traduce 'posts' (del plan) a 'public.posts' (clave del snapshot)."""
    suffix = f".{relation}"
    for key in schema:
        if key.endswith(suffix) or key == relation:
            return key
    return None


def _find_index_meta(
    table_meta: dict[str, Any] | None,
    index_name: str | None,
) -> dict[str, Any] | None:
    """Devuelve el dict del índice cuyo nombre coincida, si existe."""
    if table_meta is None or index_name is None:
        return None
    for idx in table_meta.get("indexes", []):
        if idx.get("name") == index_name:
            return idx
    return None
