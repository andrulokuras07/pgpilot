"""Detector D11 — Índice no usado por mismatch de tipo.

Detecta cuando el filtro de un nodo scan contiene un cast explícito
sobre una columna del tipo `((col)::tipo = valor)`. Este patrón indica
que Postgres aplicó una conversión sobre la columna (no sobre el
literal), lo que impide usar el índice btree existente sobre esa
columna: el planner no puede evaluar el predicado indexado sin
transformar cada valor del índice primero.

Ejemplo canónico: columna `status VARCHAR`, query `WHERE status::int = 1`.
El plan muestra `Filter: ((status)::integer = 1)` y el planner hace
Seq Scan aunque exista `idx_posts_status (status)`.

Firma extendida: acepta `sql: str | None = None` como keyword-only
siguiendo la convención establecida por D9 (`select_star`). Cuando se
pase el SQL, el detector podría en el futuro validar el mismatch
contra el tipo declarado en el snapshot. Hoy la detección es puramente
estructural sobre `node.filter`.

Cumple R1, R2 (opera sobre el campo `filter` emitido por Postgres,
no sobre el SQL crudo del usuario), R9, R14.
"""

from __future__ import annotations

import re
from typing import Any

from motor.detection import Detection
from motor.nodes import find_nodes
from motor.parser import ExplainResult, PlanNode

# Regex sobre el campo `node.filter` que Postgres emite.
# Postgres representa un cast sobre columna como `((col)::tipo` en el
# texto del filtro. El patrón captura el nombre de columna y el tipo
# destino, que son los datos necesarios para cruzar contra el snapshot.
#
# Ejemplos que captura:
#   ((status)::integer = 1)      → col="status", cast_type="integer"
#   ((author_id)::text = '5')    → col="author_id", cast_type="text"
#   ((price)::numeric > 100)     → col="price", cast_type="numeric"
#
# No captura casts sobre literales (ej. `status = '5'::integer`): en
# ese caso Postgres cast el literal, no la columna, y el índice SÍ
# puede usarse. Este es el caso correcto y no queremos reportarlo.
_CAST_ON_COLUMN_RE = re.compile(r"\(\((\w+)\)::(\w+)")

# Tipos de nodo donde un Seq Scan por type mismatch es problemático.
# Incluye Bitmap Heap Scan para capturar el caso donde el planner
# intentó usar un bitmap pero aún necesitó el cast.
_SCAN_NODE_TYPES = ("Seq Scan", "Bitmap Heap Scan", "Bitmap Index Scan")


def detect_type_mismatch(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
    *,
    sql: str | None = None,  # noqa: ARG001  — reservado para extensión futura
) -> Detection:
    """Detecta casts implícitos sobre columnas que impiden uso de índice.

    Busca nodos scan cuyo `filter` contiene el patrón `((col)::tipo`
    y verifica si la tabla tiene un índice btree sobre esa columna.
    Si el índice existe pero el cast lo vuelve inusable → detección.

    Args:
        plan: árbol del plan parseado por `motor.parse_explain`.
        snapshot: SchemaSnapshot del conector. Se usa para verificar
            que existe un índice btree sobre la columna con cast.
        sql: query del usuario (keyword-only, opcional). No se usa hoy;
            reservado para validación adicional contra el tipo declarado
            en el schema (`snapshot["schema"][table]["columns"]`).

    Returns:
        Detection con un match por columna con cast + índice existente.
    """
    schema = snapshot.get("schema", {})
    matches: list[dict[str, Any]] = []

    for node in find_nodes(plan, _SCAN_NODE_TYPES):
        if node.filter is None:
            continue

        for m in _CAST_ON_COLUMN_RE.finditer(node.filter):
            col, cast_type = m.group(1), m.group(2)
            table_key = _resolve_table_key(schema, node.relation_name)
            index_meta = _find_btree_index_on_column(schema.get(table_key), col)

            if index_meta is None:
                # Sin índice, el cast no impide nada — sería D16 (falta
                # de índice), no D11. No reportar aquí.
                continue

            matches.append(
                {
                    "table": table_key or node.relation_name,
                    "column": col,
                    "cast_type": cast_type,
                    "filter": node.filter,
                    "node_type": node.node_type,
                    "index_name": index_meta.get("name"),
                }
            )

    return Detection(
        found=bool(matches),
        confidence=0.9 if matches else 0.0,
        evidence={"matches": matches},
    )


def _resolve_table_key(schema: dict[str, Any], relation: str | None) -> str | None:
    """Traduce 'posts' (del plan) a 'public.posts' (clave del snapshot)."""
    if relation is None:
        return None
    suffix = f".{relation}"
    for key in schema:
        if key.endswith(suffix) or key == relation:
            return key
    return None


def _find_btree_index_on_column(
    table_meta: dict[str, Any] | None,
    column: str,
) -> dict[str, Any] | None:
    """Devuelve el primer índice btree cuya primera columna sea `column`."""
    if table_meta is None:
        return None
    for idx in table_meta.get("indexes", []):
        if idx.get("method", "").lower() != "btree":
            continue
        cols = idx.get("columns", [])
        if cols and cols[0] == column:
            return idx
    return None
