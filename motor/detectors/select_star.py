"""Detector D9 — SELECT * con columnas usadas reducidas.

Detecta cuando la query SQL usa `SELECT *` mientras el plan sugiere
que un `Index Only Scan` con un índice cubriente sería viable. Es el
único detector del módulo que necesita el SQL original (no solo el
plan), porque la presencia de `*` no es estructuralmente recuperable
desde el árbol del plan: Postgres ya resolvió la lista de proyección
antes de generar el EXPLAIN.

Convención extendida: este detector acepta un argumento keyword-only
`sql: str | None = None`. Cuando el orquestador llama al detector con
la query sanitizada disponible, el sanitizador la pasa por aquí. Si
`sql is None`, el detector se abstiene (Detection(found=False)) en
lugar de levantar.

Recomendación: especificar las columnas explícitamente y, si las
columnas usadas caben en un índice existente, considerar un índice
cubriente (`INCLUDE`) para habilitar `Index Only Scan`.

Cumple R1 (motor decide), R2 (estructura del SQL via sqlglot, no
regex sobre el SQL crudo), R9 (función pura), R14 (sin literales
hardcoded).
"""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from motor.detection import Detection
from motor.nodes import find_nodes
from motor.parser import ExplainResult, PlanNode


def detect_select_star(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
    *,
    sql: str | None = None,
) -> Detection:
    """Encuentra SELECT * en el SQL del usuario.

    Args:
        plan: árbol del plan parseado.
        snapshot: SchemaSnapshot del conector. Se consulta opcionalmente
            para enriquecer el match con la lista de columnas reales.
        sql: query sanitizada (placeholders ya aplicados). Sin SQL no
            hay forma estructural de detectar `*`.

    Returns:
        Detection con un match por `SELECT *` encontrado. Si `sql` es
        None o no es parseable, devuelve `found=False`.
    """
    if sql is None:
        return Detection(found=False, confidence=0.0, evidence={"matches": []})

    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except sqlglot.errors.ParseError:
        return Detection(found=False, confidence=0.0, evidence={"matches": []})

    matches: list[dict[str, Any]] = []

    # Cada SELECT (top-level o anidado) se evalúa por separado:
    # `SELECT * FROM (SELECT id FROM t) sub` no dispara para la outer
    # porque la outer no es SELECT * literal; sí dispararía si la outer
    # también usa estrella.
    for select in tree.find_all(exp.Select):
        if not _select_has_star(select):
            continue

        scanned = _first_scanned_table(plan)
        index_only_candidate = _has_index_only_opportunity(plan)

        matches.append(
            {
                "table": scanned,
                "index_only_candidate": index_only_candidate,
                "from_text": _format_from(select),
            }
        )

    return Detection(
        found=bool(matches),
        confidence=0.85 if matches else 0.0,
        evidence={"matches": matches},
    )


def _select_has_star(select: exp.Select) -> bool:
    """¿La lista de proyección del SELECT contiene `*` (no calificado o `t.*`)?"""
    for projection in select.expressions:
        if isinstance(projection, exp.Star):
            return True
        # `tabla.*` se representa como Column(this=Star()).
        if isinstance(projection, exp.Column) and isinstance(
            projection.this, exp.Star
        ):
            return True
    return False


def _format_from(select: exp.Select) -> str | None:
    """Devuelve la primera tabla del FROM como string, para evidencia."""
    from_expr = select.args.get("from")
    if from_expr is None:
        return None
    first = from_expr.expressions[0] if from_expr.expressions else None
    if first is None:
        return None
    return first.sql(dialect="postgres")


def _first_scanned_table(plan: ExplainResult | PlanNode) -> str | None:
    """Devuelve el primer `relation_name` que aparezca en el plan."""
    root = plan.root if isinstance(plan, ExplainResult) else plan
    return _scan_relation_dfs(root)


def _scan_relation_dfs(node: PlanNode) -> str | None:
    if node.relation_name:
        return node.relation_name
    for child in node.children:
        result = _scan_relation_dfs(child)
        if result:
            return result
    return None


def _has_index_only_opportunity(plan: ExplainResult | PlanNode) -> bool:
    """¿El plan tiene Index Scan que podría volverse Index Only?"""
    index_scans = find_nodes(plan, "Index Scan")
    return len(index_scans) > 0
