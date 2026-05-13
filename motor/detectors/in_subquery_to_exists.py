"""Detector D20 — IN con subquery debería ser EXISTS.

Detecta cuando el plan muestra un Semi Join (Hash Join o Nested Loop
con Join Type = "Semi") Y el SQL usa `col IN (SELECT ...)` con una
subquery no correlacionada. La reescritura con EXISTS es
semánticamente equivalente y permite al motor parar en cuanto
encuentra la primera fila que satisface la condición, lo que suele
ser más eficiente.

Ejemplo:
    -- Ineficiente:
    SELECT id FROM users
    WHERE id IN (SELECT author_id FROM posts WHERE ...)

    -- Recomendado:
    SELECT id FROM users
    WHERE EXISTS (SELECT 1 FROM posts WHERE author_id = id AND ...)

La detección requiere AMBAS señales:
  1. Plan: nodo Hash Join o Nested Loop con join_type="Semi".
  2. SQL: patrón `col IN (SELECT ...)` no correlacionado.

Esta dualidad evita falsos positivos con:
  - IN sobre listas literales (no tienen Semi Join en el plan).
  - Subqueries correlacionadas (D7 las detecta vía SubPlan; el plan
    no muestra Semi Join sino SubPlan → D20 no dispara).
  - NOT IN (D21, distinto anti-pattern con semántica NULL distinta).

Cumple R1, R2 (AST via sqlglot + atributos tipados del plan), R9, R14.
"""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from motor.detection import Detection
from motor.nodes import find_nodes
from motor.parser import ExplainResult, PlanNode

_JOIN_TYPES_WITH_SEMI = frozenset({"Hash Join", "Nested Loop", "Merge Join"})


def detect_in_subquery_to_exists(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
    *,
    sql: str | None = None,
) -> Detection:
    """Encuentra IN (SELECT ...) no correlacionados que deberían ser EXISTS.

    Args:
        plan: árbol del plan parseado. Se buscan nodos de Semi Join
            como señal estructural de la optimización del planner.
        snapshot: SchemaSnapshot del conector (no se usa directamente).
        sql: query sanitizada con placeholders. Sin SQL devuelve
            found=False.

    Returns:
        Detection con un match por IN subquery no correlacionado.
        Cada match incluye `column` (la columna del IN en el outer),
        `inner_table` (tabla de la subquery), `has_semi_join_in_plan`
        y `suggested_rewrite` (SQL completo reescrito con EXISTS).
    """
    if sql is None:
        return Detection(found=False, confidence=0.0, evidence={"matches": []})

    has_semi_join = _has_semi_join_in_plan(plan)

    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except sqlglot.errors.ParseError:
        return Detection(found=False, confidence=0.0, evidence={"matches": []})

    matches: list[dict[str, Any]] = []
    processed: set[int] = set()

    for select in tree.find_all(exp.Select):
        where = select.args.get("where")
        if where is None:
            continue

        outer_tables = _from_table_names(select)

        for in_expr in where.find_all(exp.In):
            if id(in_expr) in processed:
                continue
            processed.add(id(in_expr))

            subquery_node = in_expr.args.get("query")
            if subquery_node is None:
                continue

            if _is_negated(in_expr):
                continue

            # Desempaquetar el Subquery wrapper (sqlglot envuelve IN subqueries
            # en un nodo Subquery; el Select real está en subquery_node.this).
            inner_select = (
                subquery_node.this
                if isinstance(subquery_node, exp.Subquery)
                else subquery_node
            )

            if _is_correlated(subquery_node, outer_tables):
                continue

            outer_col = in_expr.this
            col_name = outer_col.name if isinstance(outer_col, exp.Column) else None

            suggested_rewrite = _build_rewrite(select, in_expr, inner_select)

            matches.append(
                {
                    "column": col_name,
                    "inner_table": _first_from_table(inner_select),
                    "has_semi_join_in_plan": has_semi_join,
                    "suggested_rewrite": suggested_rewrite,
                }
            )

    if not matches or not has_semi_join:
        return Detection(found=False, confidence=0.0, evidence={"matches": []})

    return Detection(
        found=True,
        confidence=0.9,
        evidence={"matches": matches},
    )


def _has_semi_join_in_plan(plan: ExplainResult | PlanNode) -> bool:
    """True si el plan contiene algún nodo de join con join_type='Semi'."""
    for node in find_nodes(plan, _JOIN_TYPES_WITH_SEMI):
        if node.join_type == "Semi":
            return True
    return False


def _is_negated(in_expr: exp.In) -> bool:
    """True si el IN está negado (NOT IN). NOT IN = exp.Not(this=exp.In(...))."""
    return isinstance(in_expr.parent, exp.Not)


def _from_table_names(select: exp.Select) -> set[str]:
    """Nombres y aliases de las tablas en el FROM del SELECT dado.

    Nota: sqlglot almacena la cláusula FROM bajo la clave `"from_"`
    (no `"from"`) porque `from` es palabra reservada de Python.
    """
    names: set[str] = set()
    from_clause = select.args.get("from_")
    if from_clause is None:
        return names
    for table in from_clause.find_all(exp.Table):
        if table.alias:
            names.add(table.alias.lower())
        if table.name:
            names.add(table.name.lower())
    return names


def _is_correlated(subquery: exp.Select, outer_tables: set[str]) -> bool:
    """True si la subquery referencia columnas de las tablas externas.

    Un IN correlacionado referencia la tabla outer con calificador:
    `col IN (SELECT x FROM t WHERE t.fk = outer.pk)`.
    Sin calificador no podemos saber si la columna es de la tabla inner
    o de la outer, así que solo marcamos correlación con calificador.
    """
    for col in subquery.find_all(exp.Column):
        table_qualifier = col.table
        if table_qualifier and table_qualifier.lower() in outer_tables:
            return True
    return False


def _first_from_table(inner_select: exp.Select) -> str | None:
    """Nombre de la primera tabla del FROM del SELECT interior, o None."""
    from_clause = inner_select.args.get("from_")
    if from_clause is None:
        return None
    tables = list(from_clause.find_all(exp.Table))
    return tables[0].name if tables else None


def _build_rewrite(
    outer_select: exp.Select,
    in_expr: exp.In,
    inner_select: exp.Select,
) -> str:
    """Genera el SELECT reescrito con EXISTS reemplazando IN (SELECT ...).

    Estrategia:
    1. Clona el SELECT interior, reemplaza su lista de proyección por
       `1` (literal) y añade la condición de correlación al WHERE.
    2. Envuelve en EXISTS.
    3. Construye el outer SELECT reemplazando el WHERE completo con
       EXISTS. Si el WHERE tiene solo la condición IN, el resultado es
       exacto; si tiene más condiciones (AND/OR), el EXISTS reemplaza
       toda la cláusula WHERE — limitación documentada.

    El SQL resultante es sintácticamente válido y parseable con sqlglot.

    Nota: `inner_select` es el Select ya desenvuelto del Subquery wrapper
    (sqlglot envuelve `IN (SELECT ...)` en un nodo Subquery).
    """
    outer_col = in_expr.this

    if not inner_select.expressions:
        return ""

    inner_col_expr = inner_select.expressions[0]

    # Condición de correlación: inner_col = outer_col
    corr = exp.EQ(this=inner_col_expr.copy(), expression=outer_col.copy())

    # Clonar inner_select: SELECT 1 FROM ... WHERE corr [AND existing_where]
    exists_sel = inner_select.copy()
    exists_sel.set("expressions", [exp.Literal.number(1)])
    inner_where = exists_sel.args.get("where")
    if inner_where:
        exists_sel.set(
            "where",
            exp.Where(
                this=exp.And(this=corr, expression=inner_where.this.copy())
            ),
        )
    else:
        exists_sel.set("where", exp.Where(this=corr))

    exists_node = exp.Exists(this=exists_sel)

    # Reconstruir el outer SELECT con EXISTS en el WHERE
    outer_copy = outer_select.copy()
    outer_copy.set("where", exp.Where(this=exists_node))
    return outer_copy.sql(dialect="postgres")
