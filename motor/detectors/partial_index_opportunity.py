"""Detector D17 — Oportunidad de índice parcial.

Detecta el patrón "filtro compuesto donde una columna es booleana"
sobre nodos scan. El caso típico es `WHERE user_id = $1 AND read = false`
sobre tablas donde la mayoría de filas tienen `read = true`: un índice
parcial `(user_id) WHERE read = false` es mucho más selectivo que el
índice plano sobre `user_id`.

NO consulta `pg_stats.most_common_freqs` (sería extender B4). En su
lugar usa una heurística estructural: si hay un predicado sobre una
columna booleana junto con otro predicado sobre otra columna, el caso
es candidato a índice parcial. La decisión final (¿vale la pena?) la
toma el recomendador con stats reales.

Cubre Q11 de AppDB v1 (`notifications WHERE user_id = ? AND read = false`).
Postgres emite `(NOT read)` en el Filter cuando el SQL dice
`read = false`; los dos patrones se reconocen.

Cumple R1, R2, R9, R14.
"""

from __future__ import annotations

import re
from typing import Any

from motor.detection import Detection
from motor.detectors._common import resolve_table_key
from motor.nodes import find_nodes
from motor.parser import ExplainResult, PlanNode

# Nodos scan candidatos. Bitmap Heap Scan es el típico para Q11
# (el planner usa el índice sobre user_id y filtra `read` arriba).
_SCAN_TYPES = (
    "Seq Scan",
    "Bitmap Heap Scan",
    "Bitmap Index Scan",
    "Index Scan",
    "Index Only Scan",
)

# Patrones de predicado booleano emitidos por Postgres.
# Orden: más específicos primero para no perder el valor cuando aplica.
_BOOL_NOT_RE = re.compile(r"\bNOT\s+([a-z_][a-z0-9_]*)\b", re.IGNORECASE)
_BOOL_EQ_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\s*=\s*(true|false)\b", re.IGNORECASE)
_BOOL_IS_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\s+IS\s+(TRUE|FALSE)\b", re.IGNORECASE)

# Cualquier identificador en el filtro. Se intersecta con las columnas
# del schema para descartar ruido (operadores SQL, literales, etc.).
_IDENT_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\b")


def detect_partial_index_opportunity(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
) -> Detection:
    """Encuentra scans con filtro AND mezclando una bool y otra columna.

    Args:
        plan: árbol del plan parseado por `motor.parse_explain`.
        snapshot: SchemaSnapshot del conector (usa `schema`).

    Returns:
        Detection con un match por scan donde aplique. Cada match
        incluye la columna candidata a indexar, la columna bool y el
        valor esperado para la cláusula `WHERE` del índice parcial.
    """
    schema = snapshot.get("schema", {})
    matches: list[dict[str, Any]] = []

    for node in find_nodes(plan, _SCAN_TYPES):
        relation = node.relation_name
        if relation is None:
            continue

        table_key = resolve_table_key(schema, relation)
        if table_key is None:
            continue

        columns = _columns_by_name(schema[table_key])
        bool_cols = {c for c, dtype in columns.items() if _is_bool_type(dtype)}
        if not bool_cols:
            continue

        # Concatena todos los predicados estructurados del nodo. No
        # mezcla SQL del usuario: estos campos vienen del planner.
        predicates = " AND ".join(p for p in (node.filter, node.recheck_cond, node.index_cond) if p)
        if not predicates:
            continue

        bool_match = _find_bool_predicate(predicates, bool_cols)
        if bool_match is None:
            continue
        bool_col, bool_value = bool_match

        other_col = _find_other_referenced_column(predicates, columns.keys(), exclude=bool_col)
        if other_col is None:
            continue

        table_name_only = table_key.split(".")[-1]
        suggested_index_name = f"idx_{table_name_only}_{other_col}_partial"
        suggested_sql = (
            f"CREATE INDEX {suggested_index_name} "
            f"ON {table_key} ({other_col}) "
            f"WHERE {bool_col} = {bool_value};"
        )

        matches.append(
            {
                "table": table_key,
                "column": other_col,
                "bool_column": bool_col,
                "bool_value": bool_value,
                "node_type": node.node_type,
                "filter": predicates,
                "suggested_index_name": suggested_index_name,
                "suggested_sql": suggested_sql,
            }
        )

    return Detection(
        found=bool(matches),
        confidence=0.8 if matches else 0.0,
        evidence={"matches": matches},
    )


def _columns_by_name(table_meta: dict[str, Any]) -> dict[str, str]:
    """`{col_name: data_type_lower}` para las columnas de la tabla."""
    return {c["name"]: str(c.get("data_type", "")).lower() for c in table_meta.get("columns", [])}


def _is_bool_type(data_type: str) -> bool:
    """`boolean`, `bool` (alias Postgres). Tolerante a sufijos raros."""
    return data_type.startswith("bool")


def _find_bool_predicate(
    text: str,
    bool_cols: set[str],
) -> tuple[str, str] | None:
    """Devuelve `(columna, valor)` del primer predicado booleano detectado.

    Reconoce: `NOT col`, `col = true|false`, `col IS TRUE|FALSE`.
    `valor` se normaliza a `'true'` o `'false'` (lowercase) para que el
    recomendador genere SQL canónico.
    """
    for m in _BOOL_EQ_RE.finditer(text):
        col, value = m.group(1), m.group(2).lower()
        if col in bool_cols:
            return col, value
    for m in _BOOL_IS_RE.finditer(text):
        col, value = m.group(1), m.group(2).lower()
        if col in bool_cols:
            return col, value
    for m in _BOOL_NOT_RE.finditer(text):
        col = m.group(1)
        if col in bool_cols:
            return col, "false"
    return None


def _find_other_referenced_column(
    text: str,
    known_columns,
    exclude: str,
) -> str | None:
    """Primer identificador del texto que es columna conocida ≠ exclude."""
    seen: set[str] = set()
    for m in _IDENT_RE.finditer(text):
        ident = m.group(1)
        if ident == exclude or ident in seen:
            continue
        seen.add(ident)
        if ident in known_columns:
            return ident
    return None
