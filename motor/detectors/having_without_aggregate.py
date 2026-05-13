"""Detector D19 — HAVING que debería ser WHERE.

Detecta cuando la cláusula HAVING de un SELECT solo contiene referencias
a columnas del GROUP BY y ninguna función de agregación. En ese caso el
filtro puede moverse a WHERE antes de la agregación, lo que reduce las
filas que llegan al Aggregate y puede habilitar el uso de índices.

Ejemplo:
    -- Ineficiente:
    SELECT author_id, count(*) FROM posts
    GROUP BY author_id HAVING author_id = 1000

    -- Recomendado:
    SELECT author_id, count(*) FROM posts
    WHERE author_id = 1000 GROUP BY author_id

Requiere el SQL original porque el plan no distingue si un Filter
sobre un nodo Aggregate proviene de HAVING o de una reescritura
interna del planner. Usa la firma extendida keyword-only `sql=` igual
que D9 y D11.

Excepción legítima a R2: el parser sqlglot opera sobre el AST del SQL,
no sobre el texto crudo (mismo patrón que D9). El plan se recibe pero
no se usa directamente — la señal estructural está en el SQL.

Cumple R1, R9, R14.
"""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from motor.detection import Detection
from motor.parser import ExplainResult, PlanNode


def detect_having_without_aggregate(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
    *,
    sql: str | None = None,
) -> Detection:
    """Encuentra HAVING clauses que deberían ser WHERE.

    Args:
        plan: árbol del plan parseado (no se usa directamente — la
            señal está en el SQL; argumento presente por convención).
        snapshot: SchemaSnapshot del conector (no se usa directamente).
        sql: query sanitizada con placeholders. Sin SQL devuelve
            found=False en lugar de levantar.

    Returns:
        Detection con un match por SELECT con HAVING movible a WHERE.
        Cada match incluye `having_expr` (la condición original),
        `group_by_cols` (columnas del GROUP BY implicadas),
        `from_table` (primera tabla del FROM) y `suggested_rewrite`
        (SQL completo reescrito con WHERE en lugar de HAVING).
    """
    if sql is None:
        return Detection(found=False, confidence=0.0, evidence={"matches": []})

    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except sqlglot.errors.ParseError:
        return Detection(found=False, confidence=0.0, evidence={"matches": []})

    matches: list[dict[str, Any]] = []

    for select in tree.find_all(exp.Select):
        having = select.args.get("having")
        if having is None:
            continue

        group = select.args.get("group")
        if group is None:
            continue

        group_cols: set[str] = {
            expr.name.lower() for expr in group.expressions if isinstance(expr, exp.Column)
        }
        if not group_cols:
            continue

        if not _having_moveable_to_where(having, group_cols):
            continue

        suggested_rewrite = _build_rewrite(select, having)

        matches.append(
            {
                "from_table": _first_table(select),
                "having_expr": having.this.sql(dialect="postgres"),
                "group_by_cols": sorted(group_cols),
                "suggested_rewrite": suggested_rewrite,
            }
        )

    return Detection(
        found=bool(matches),
        confidence=0.9 if matches else 0.0,
        evidence={"matches": matches},
    )


def _having_moveable_to_where(having: exp.Having, group_cols: set[str]) -> bool:
    """True si el HAVING no usa funciones de agregación y solo referencia
    columnas del GROUP BY.

    Dos condiciones deben cumplirse:
    1. Ningún nodo en el árbol del HAVING es una función de agregación
       (subclase de exp.AggFunc: Count, Sum, Avg, Min, Max, etc.).
    2. Toda referencia a columna en el HAVING existe en group_cols.
    """
    for node in having.walk():
        if isinstance(node, exp.AggFunc):
            return False
    for col in having.find_all(exp.Column):
        if col.name.lower() not in group_cols:
            return False
    return True


def _build_rewrite(select: exp.Select, having: exp.Having) -> str:
    """Genera el SQL reescrito moviendo la condición del HAVING al WHERE.

    Si ya existía un WHERE, la condición del HAVING se une con AND.
    El HAVING queda eliminado del SELECT resultante.
    """
    rewritten = select.copy()
    having_cond = having.this.copy()

    existing_where = rewritten.args.get("where")
    if existing_where is not None:
        combined = exp.And(this=existing_where.this.copy(), expression=having_cond)
        rewritten.set("where", exp.Where(this=combined))
    else:
        rewritten.set("where", exp.Where(this=having_cond))

    rewritten.set("having", None)
    return rewritten.sql(dialect="postgres")


def _first_table(select: exp.Select) -> str | None:
    """Devuelve el nombre de la primera tabla del FROM, o None.

    Compatibilidad sqlglot: la cláusula FROM se almacena bajo
    `"from"` (>=25) o `"from_"` (versiones legacy donde `from` era
    palabra reservada). Probamos ambas. `Table.name` devuelve el
    nombre sin schema.
    """
    from_expr = select.args.get("from") or select.args.get("from_")
    if from_expr is None:
        return None
    tables = list(from_expr.find_all(exp.Table))
    return tables[0].name if tables else None
