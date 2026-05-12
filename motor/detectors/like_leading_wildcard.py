"""Detector D4 — LIKE con wildcard al inicio.

Detecta cuando el plan contiene un nodo con filtro tipo
`column LIKE '%texto'` o `column ~~ '%texto'`. Este patrón impide
el uso de índices btree regulares.

Recomendación: índice de trigrams (pg_trgm) o búsqueda full-text.

Cumple R1 (motor decide), R2 (estructura del plan, no SQL crudo),
R9 (función pura), R14 (sin literales hardcoded).
"""

from __future__ import annotations

import re
from typing import Any

from motor.detection import Detection
from motor.nodes import find_nodes
from motor.parser import ExplainResult, PlanNode

_LIKE_LEADING_WILDCARD_RE = re.compile(
    r"\(?\(?(\w+)\)?" r"(?:::(?:character varying|text))?" r"\s+~~\s+" r"'%"
)

_SCAN_TYPES = ("Seq Scan", "Bitmap Heap Scan", "Bitmap Index Scan")


def detect_like_leading_wildcard(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
) -> Detection:
    """Encuentra filtros LIKE con wildcard al inicio ('%texto').

    Opera sobre el campo `filter` de nodos scan del plan. El campo
    es texto generado por Postgres (estable entre versiones), no el
    SQL del usuario — cumple R2.
    """
    matches: list[dict[str, Any]] = []

    for node in find_nodes(plan, _SCAN_TYPES):
        _check_expr(node.filter, node, matches)
        _check_expr(node.recheck_cond, node, matches)
        _check_expr(node.index_cond, node, matches)

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
    for m in _LIKE_LEADING_WILDCARD_RE.finditer(expr):
        column = m.group(1)
        matches.append(
            {
                "table": node.relation_name,
                "column": column,
                "filter": expr,
                "node_type": node.node_type,
            }
        )
