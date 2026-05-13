"""Detector D8 — Nested Loop con tabla externa grande.

Detecta cuando el plan contiene un nodo `Nested Loop` cuyo hijo
externo (Outer) emite >10k filas. Un Nested Loop ejecuta el lado
interno una vez por cada fila del externo: cuando el externo es
grande, casi siempre debería ser `Hash Join` o `Merge Join`.

Recomendación: revisar `work_mem` (puede estar forzando Nested Loop
por falta de memoria para el hash), revisar estadísticas
(`ANALYZE`), o reescribir la condición de join para que el planner
considere alternativas.

Cumple R1 (motor decide), R2 (estructura del plan, no SQL crudo),
R9 (función pura), R14 (sin literales hardcoded).
"""

from __future__ import annotations

from typing import Any

from motor.detection import Detection
from motor.nodes import find_nodes
from motor.parser import ExplainResult, PlanNode

# Umbral del backlog (D8). Por encima de 10k filas, un Nested Loop
# casi siempre es subóptimo frente a Hash/Merge Join.
LARGE_OUTER_MIN_ROWS = 10_000


def detect_nested_loop_large_outer(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
) -> Detection:
    """Encuentra Nested Loops con outer grande.

    Args:
        plan: árbol del plan parseado por `motor.parse_explain`.
        snapshot: SchemaSnapshot del conector (no se usa hoy, se
            recibe por uniformidad con el resto de detectores).

    Returns:
        Detection con un match por Nested Loop problemático.
    """
    matches: list[dict[str, Any]] = []

    for node in find_nodes(plan, "Nested Loop"):
        outer = _outer_child(node)
        if outer is None:
            continue

        outer_rows = _effective_rows(outer)
        if outer_rows < LARGE_OUTER_MIN_ROWS:
            continue

        matches.append(
            {
                "outer_table": _scanned_relation(outer),
                "outer_node_type": outer.node_type,
                "outer_rows": outer_rows,
                "outer_rows_source": ("actual" if outer.actual_rows is not None else "plan"),
                "join_type": node.join_type,
            }
        )

    return Detection(
        found=bool(matches),
        confidence=0.8 if matches else 0.0,
        evidence={"matches": matches},
    )


def _outer_child(node: PlanNode) -> PlanNode | None:
    """Devuelve el hijo Outer del nodo, o el primer hijo si no está marcado."""
    if not node.children:
        return None
    for child in node.children:
        if child.parent_relationship == "Outer":
            return child
    # Postgres a veces no marca `Parent Relationship`. En esos casos
    # el primer hijo del Nested Loop es el outer por convención.
    return node.children[0]


def _effective_rows(node: PlanNode) -> int:
    """Filas reales si EXPLAIN ANALYZE las trae, si no las estimadas."""
    if node.actual_rows is not None:
        return node.actual_rows
    return node.plan_rows


def _scanned_relation(node: PlanNode) -> str | None:
    """Encuentra la primera relación escaneada bajo el subárbol."""
    if node.relation_name:
        return node.relation_name
    for child in node.children:
        result = _scanned_relation(child)
        if result:
            return result
    return None
