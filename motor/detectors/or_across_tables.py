"""Detector D6 — OR sobre columnas de tablas distintas en JOIN.

Detecta cuando un nodo de join tiene un filtro con OR que referencia
columnas de tablas distintas. Este patrón impide que el planner use
índices en cualquiera de las tablas.

Recomendación: reescribir como UNION (o UNION ALL si aplica).

Cumple R1, R2, R9, R14.
"""

from __future__ import annotations

import re
from typing import Any

from motor.detection import Detection
from motor.nodes import find_nodes
from motor.parser import ExplainResult, PlanNode

_JOIN_TYPES = ("Nested Loop", "Hash Join", "Merge Join")

_OR_SPLIT_RE = re.compile(r"\bOR\b", re.IGNORECASE)

_TABLE_DOT_COL_RE = re.compile(r"(\w+)\.(\w+)")


def detect_or_across_tables(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
) -> Detection:
    """Encuentra filtros con OR que cruzan tablas distintas en JOINs.

    Opera sobre `node.filter` de nodos join — campo generado por
    Postgres, cumple R2.
    """
    matches: list[dict[str, Any]] = []

    for node in find_nodes(plan, _JOIN_TYPES):
        _check_filter(node.filter, node, matches)

    _check_scan_filters(plan, matches)

    return Detection(
        found=bool(matches),
        confidence=0.85 if matches else 0.0,
        evidence={"matches": matches},
    )


def _check_filter(
    expr: str | None,
    node: PlanNode,
    matches: list[dict[str, Any]],
) -> None:
    if not expr:
        return
    if not _OR_SPLIT_RE.search(expr):
        return

    parts = _OR_SPLIT_RE.split(expr)
    tables_per_part: list[set[str]] = []
    for part in parts:
        refs = _TABLE_DOT_COL_RE.findall(part)
        tables_per_part.append({t for t, _ in refs})

    all_tables: set[str] = set()
    for ts in tables_per_part:
        all_tables.update(ts)

    if len(all_tables) >= 2:
        matches.append(
            {
                "tables": sorted(all_tables),
                "filter": expr,
                "node_type": node.node_type,
            }
        )


def _check_scan_filters(
    plan: ExplainResult | PlanNode,
    matches: list[dict[str, Any]],
) -> None:
    """Also check Seq Scan nodes for OR filters with table-qualified columns."""
    for node in find_nodes(plan, "Seq Scan"):
        _check_filter(node.filter, node, matches)
