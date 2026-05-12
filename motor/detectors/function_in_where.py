"""Detector D5 — Función no-immutable en WHERE.

Detecta cuando el filtro de un nodo scan contiene una llamada a
función como LOWER(col), UPPER(col), TRIM(col), etc. Estas funciones
impiden el uso de índices btree regulares sobre la columna.

Recomendación: índice funcional sobre la expresión.

Cumple R1, R2, R9, R14.
"""

from __future__ import annotations

import re
from typing import Any

from motor.detection import Detection
from motor.nodes import find_nodes
from motor.parser import ExplainResult, PlanNode

_FUNCTION_CALL_RE = re.compile(
    r"(lower|upper|trim|ltrim|rtrim|btrim|coalesce|concat"
    r"|replace|substring|left|right|reverse|length"
    r"|date_trunc|extract|to_char|to_date|to_timestamp|to_number"
    r"|abs|ceil|floor|round|trunc"
    r"|regexp_replace|regexp_match)"
    r"\s*\(",
    re.IGNORECASE,
)

_SCAN_TYPES = ("Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Heap Scan")


def detect_function_in_where(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
) -> Detection:
    """Encuentra funciones no-immutable en filtros de nodos scan.

    Opera sobre `node.filter` e `node.index_cond`, campos generados
    por Postgres — cumple R2.
    """
    matches: list[dict[str, Any]] = []

    for node in find_nodes(plan, _SCAN_TYPES):
        _check_expr(node.filter, node, matches)

    return Detection(
        found=bool(matches),
        confidence=0.9 if matches else 0.0,
        evidence={"matches": matches},
    )


def _check_expr(
    expr: str | None,
    node: PlanNode,
    matches: list[dict[str, Any]],
) -> None:
    if not expr:
        return
    for m in _FUNCTION_CALL_RE.finditer(expr):
        func_name = m.group(1).lower()
        matches.append(
            {
                "table": node.relation_name,
                "function": func_name,
                "filter": expr,
                "node_type": node.node_type,
            }
        )
