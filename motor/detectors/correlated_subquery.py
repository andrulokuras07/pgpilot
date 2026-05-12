"""Detector D7 — Subquery correlacionada.

Detecta cuando el plan contiene un `SubPlan` que indica una subquery
correlacionada (se ejecuta una vez por cada fila de la query externa).
Estos aparecen en el plan como nodos con `parent_relationship = "SubPlan"`
o con `subplan_name` que contiene "SubPlan".

Recomendación: reescribir como JOIN o EXISTS.

Cumple R1, R2, R9, R14.
"""

from __future__ import annotations

from typing import Any

from motor.detection import Detection
from motor.parser import ExplainResult, PlanNode


def detect_correlated_subquery(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
) -> Detection:
    """Encuentra subqueries correlacionadas en el plan.

    Busca recursivamente nodos cuyo `subplan_name` indica un SubPlan
    (subquery correlacionada). Opera sobre la estructura del plan,
    cumple R2.
    """
    root = plan.root if isinstance(plan, ExplainResult) else plan
    matches: list[dict[str, Any]] = []
    _walk(root, matches)

    return Detection(
        found=bool(matches),
        confidence=0.95 if matches else 0.0,
        evidence={"matches": matches},
    )


def _walk(node: PlanNode, matches: list[dict[str, Any]]) -> None:
    if node.subplan_name and "SubPlan" in node.subplan_name:
        parent_table = _find_outer_table(node)
        matches.append(
            {
                "subplan_name": node.subplan_name,
                "node_type": node.node_type,
                "inner_table": node.relation_name,
                "outer_table": parent_table,
            }
        )

    for child in node.children:
        _walk(child, matches)


def _find_outer_table(node: PlanNode) -> str | None:
    """Intenta encontrar la tabla del nodo scan más profundo del subplan."""
    if node.relation_name:
        return node.relation_name
    for child in node.children:
        result = _find_outer_table(child)
        if result:
            return result
    return None
