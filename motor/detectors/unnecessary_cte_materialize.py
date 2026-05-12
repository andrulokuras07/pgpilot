"""Detector D12 — CTE materializada innecesariamente.

Detecta cuando el plan contiene nodos `CTE Scan` — señal de que
Postgres materializó la CTE como una tabla temporal interna. Cuando la
CTE se referencia una sola vez y no es parte de una CTE recursiva,
la materialización es innecesaria: el planner puede inlinar la CTE
y optimizar la query completa en un solo paso.

Historia de versiones relevante:
- Postgres ≤ 11: las CTEs siempre se materializaban (optimization
  fence explícita). No hay nada que recomendar; era obligatorio.
- Postgres 12+: las CTEs simples pueden ser inlineadas. Solo se
  materializan si: (a) la query las referencia múltiples veces, (b)
  la CTE es recursiva (`WITH RECURSIVE`), o (c) tiene efectos
  secundarios (INSERT/UPDATE/DELETE). Si Postgres elige materializarla
  a pesar de no necesitarlo, `WITH ... AS NOT MATERIALIZED` fuerza el
  inline.

Recomendación: `WITH cte_name AS NOT MATERIALIZED (SELECT ...)`.

Nota: si Postgres 12+ materializa a pesar de no haber motivo explícito,
puede ser porque el planner estimó que el resultado sería reutilizado
internamente o que el cost-model favorece la materialización. Reportar
como oportunidad, no como bug seguro — la confianza es 0.85.

Cumple R1, R2 (estructura del plan — `node.cte_name` y búsqueda de
`Recursive Union`), R9, R14.
"""

from __future__ import annotations

from typing import Any

from motor.detection import Detection
from motor.nodes import find_nodes
from motor.parser import ExplainResult, PlanNode


def detect_unnecessary_cte_materialize(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
) -> Detection:
    """Detecta CTEs materializadas que podrían ser inlineadas.

    Una CTE materializada aparece en el plan como nodo `CTE Scan`.
    Se considera candidata a `NOT MATERIALIZED` si:
      1. Su `cte_name` aparece exactamente una vez en el plan
         (no se reutiliza la materialización múltiples veces).
      2. El plan no contiene ningún nodo `Recursive Union` (lo que
         indica que no hay CTEs recursivas en la query).

    Args:
        plan: árbol del plan parseado por `motor.parse_explain`.
        snapshot: SchemaSnapshot del conector (no se usa hoy; se
            recibe por uniformidad con el resto de detectores).

    Returns:
        Detection con un match por nombre de CTE candidata a inline.
    """
    cte_scan_nodes = find_nodes(plan, "CTE Scan")

    if not cte_scan_nodes:
        return Detection(found=False, confidence=0.0, evidence={"matches": []})

    # Si hay un Recursive Union en el plan, hay una CTE recursiva.
    # Las CTEs recursivas deben materializarse obligatoriamente;
    # no recomendar NOT MATERIALIZED en ese contexto.
    is_recursive = bool(find_nodes(plan, "Recursive Union"))

    # Contar cuántas veces aparece cada cte_name en el plan.
    # Un CTE referenciado más de una vez se materializa a propósito
    # para no recalcularlo; no reportar esos.
    cte_reference_count: dict[str, int] = {}
    for node in cte_scan_nodes:
        name = node.cte_name or ""
        cte_reference_count[name] = cte_reference_count.get(name, 0) + 1

    matches: list[dict[str, Any]] = []

    for node in cte_scan_nodes:
        cte_name = node.cte_name or ""
        ref_count = cte_reference_count.get(cte_name, 0)

        if is_recursive:
            # Plan tiene CTE recursiva: no reportar ningún CTE Scan.
            # No podemos distinguir cuál es la recursiva desde el plan
            # sin más contexto (Recursive Union puede ser de otra CTE),
            # así que preferimos no reportar y evitar FPs.
            continue

        if ref_count > 1:
            # Referenciado múltiples veces: la materialización es útil.
            continue

        matches.append(
            {
                "cte_name": cte_name,
                "reference_count": ref_count,
                "node_type": node.node_type,
                "plan_rows": node.plan_rows,
            }
        )

    # Deduplicar por cte_name: si por alguna razón hay dos nodos
    # CTE Scan con el mismo nombre (edge case del parser), reportar
    # solo una vez.
    seen: set[str] = set()
    unique_matches: list[dict[str, Any]] = []
    for m in matches:
        if m["cte_name"] not in seen:
            seen.add(m["cte_name"])
            unique_matches.append(m)

    return Detection(
        found=bool(unique_matches),
        confidence=0.85 if unique_matches else 0.0,
        evidence={"matches": unique_matches},
    )
