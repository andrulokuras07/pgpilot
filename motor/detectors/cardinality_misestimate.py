"""Detector D18 — Error de cardinalidad por correlación entre columnas.

Detecta cuando un nodo de join (`Hash Join`, `Merge Join`, `Nested Loop`)
estima muy mal el número de filas que va a producir, **y** ese error
se origina en un scan descendiente cuyo filtro tiene un AND sobre dos o
más columnas de la misma tabla. Esa combinación es la firma clásica de
correlación estadística no capturada por Postgres por defecto.

Recomendación: `CREATE STATISTICS` multi-columna sobre las columnas
correlacionadas (Postgres almacenará dependencias funcionales y la
estimación del planner mejora).

Cubre Q13 de AppDB v1 (`posts JOIN users ON ... WHERE is_verified=true
AND is_active=true`).

Cumple R1, R2, R9, R14.
"""

from __future__ import annotations

import re
from typing import Any

from motor.detection import Detection
from motor.detectors._common import resolve_table_key
from motor.nodes import find_nodes
from motor.parser import ExplainResult, PlanNode

# Razón entre estimación y realidad para considerar "muy mal estimado".
# Backlog: 5x. Si Postgres se equivoca por menos, asumimos que las stats
# están razonablemente bien.
MISESTIMATE_RATIO = 5.0

_SCAN_TYPES = (
    "Seq Scan",
    "Bitmap Heap Scan",
    "Bitmap Index Scan",
    "Index Scan",
    "Index Only Scan",
)

_JOIN_TYPES = ("Hash Join", "Merge Join", "Nested Loop")

# Identificador SQL simple — se intersecta con columnas del schema
# para evitar contar palabras reservadas, operadores o literales.
_IDENT_RE = re.compile(r"\b([a-z_][a-z0-9_]+)\b")

# `AND` con bordes de palabra. Postgres lo emite en mayúsculas, pero
# por robustez (planners modificados, futuras versiones) se ignora case.
_AND_RE = re.compile(r"\bAND\b", re.IGNORECASE)


def detect_cardinality_misestimate(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
) -> Detection:
    """Encuentra joins mal estimados originados en filtros multi-columna.

    Args:
        plan: árbol del plan parseado por `motor.parse_explain`.
        snapshot: SchemaSnapshot del conector (usa `schema`).

    Returns:
        Detection con un match por join afectado. Cada match incluye la
        tabla, las columnas correlacionadas y el SQL sugerido para crear
        las estadísticas extendidas.
    """
    schema = snapshot.get("schema", {})
    matches: list[dict[str, Any]] = []

    for join in find_nodes(plan, _JOIN_TYPES):
        if not _is_misestimated(join):
            continue

        offender = _find_multi_col_and_scan(join, schema)
        if offender is None:
            continue

        table_key = offender["table"]
        cols = offender["columns"]
        table_name_only = table_key.split(".")[-1]
        stats_name = f"stats_{table_name_only}_{'_'.join(cols)}"
        cols_csv = ", ".join(cols)
        suggested_sql = f"CREATE STATISTICS {stats_name} " f"ON {cols_csv} FROM {table_key};"

        matches.append(
            {
                "join_node_type": join.node_type,
                "plan_rows": join.plan_rows,
                "actual_rows": join.actual_rows,
                "table": table_key,
                "columns": cols,
                "filter": offender["filter"],
                "scan_node_type": offender["node_type"],
                "suggested_statistics_name": stats_name,
                "suggested_sql": suggested_sql,
            }
        )

    return Detection(
        found=bool(matches),
        confidence=0.85 if matches else 0.0,
        evidence={"matches": matches},
    )


def _is_misestimated(node: PlanNode) -> bool:
    """¿La razón plan_rows vs actual_rows supera el umbral?

    Tolera `actual_rows = 0` (overestimación total): cuenta como
    "muy mal" si la estimación era > MISESTIMATE_RATIO. Requiere
    `actual_rows is not None` (EXPLAIN sin ANALYZE no aplica).
    """
    if node.actual_rows is None or node.plan_rows is None:
        return False
    if node.actual_rows == 0:
        return node.plan_rows > MISESTIMATE_RATIO
    if node.plan_rows <= 0:
        return False
    ratio = max(
        node.plan_rows / node.actual_rows,
        node.actual_rows / node.plan_rows,
    )
    return ratio >= MISESTIMATE_RATIO


def _find_multi_col_and_scan(
    root: PlanNode,
    schema: dict[str, Any],
) -> dict[str, Any] | None:
    """Recorre el subárbol y devuelve el primer scan con AND multi-col.

    "Multi-col" = ≥2 columnas distintas de la misma tabla, todas
    referenciadas en el `Filter` o `Recheck Cond` del scan, con al
    menos un `AND` separándolas.
    """
    for scan in find_nodes(root, _SCAN_TYPES):
        if scan.relation_name is None:
            continue
        table_key = resolve_table_key(schema, scan.relation_name)
        if table_key is None:
            continue

        predicates = " AND ".join(p for p in (scan.filter, scan.recheck_cond, scan.index_cond) if p)
        if not predicates or not _AND_RE.search(predicates):
            continue

        table_cols = {c["name"] for c in schema[table_key].get("columns", [])}
        cols_in_filter = _columns_referenced(predicates, table_cols)
        if len(cols_in_filter) < 2:
            continue

        return {
            "table": table_key,
            "columns": cols_in_filter,
            "filter": predicates,
            "node_type": scan.node_type,
        }
    return None


def _columns_referenced(
    text: str,
    known_columns: set[str],
) -> list[str]:
    """Identificadores del texto que coinciden con columnas conocidas,
    en orden de primera aparición, sin duplicar."""
    out: list[str] = []
    seen: set[str] = set()
    for m in _IDENT_RE.finditer(text):
        ident = m.group(1)
        if ident in seen:
            continue
        if ident in known_columns:
            out.append(ident)
            seen.add(ident)
    return out
