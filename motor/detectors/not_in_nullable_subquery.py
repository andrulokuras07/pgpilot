"""Detector D21 — NOT IN con subquery sobre columna nullable.

Detecta el patrón `WHERE col NOT IN (SELECT inner_col FROM t ...)`
cuando `inner_col` admite NULL en el schema. Este patrón tiene **dos**
problemas:

1. **Bug silencioso por semántica NULL.** En SQL trivaluado,
   `x NOT IN (a, b, NULL)` se evalúa a `x <> a AND x <> b AND x <> NULL`.
   La última comparación devuelve UNKNOWN, y el AND con UNKNOWN nunca
   es TRUE — así que si la subquery devuelve aunque sea un solo NULL,
   el resultado completo de la query externa es vacío. Es el bug
   clásico de "mi reporte aparece en blanco después de un deploy" sin
   error visible.

2. **Performance.** Postgres no puede convertir `NOT IN` a `Anti Join`
   cuando la columna interna es nullable; típicamente se materializa
   la lista interna entera vía `SubPlan` o `hashed SubPlan` y se
   compara fila por fila (sin short-circuit posible por la regla #1).

`NOT EXISTS` resuelve ambos: tiene semántica binaria (un row match
satisface), permite Anti Join, y deja al planner cortar en cuanto
encuentra la primera coincidencia.

Ejemplo:
    -- Ineficiente + bug silencioso:
    SELECT id FROM users
    WHERE id NOT IN (SELECT author_id FROM posts)
    --                       ^^^^^^^^^ posts.author_id es nullable

    -- Recomendado:
    SELECT id FROM users
    WHERE NOT EXISTS (
      SELECT 1 FROM posts WHERE posts.author_id = users.id
    )

Señal de detección (toda en SQL + snapshot, el plan no se usa):
  1. SQL contiene `col NOT IN (SELECT inner_col FROM table ...)`.
  2. La subquery NO es correlacionada (las correlacionadas las cubre
     D7 vía `SubPlan`).
  3. `snapshot["schema"][<schema>.<table>]["columns"][i]["is_nullable"]`
     es True para `inner_col`. Sin schema, o si la columna es
     NOT NULL, D21 se abstiene (no es bug ni anti-pattern; el
     planner puede optimizar libremente).

Frontera con detectores hermanos:
  - **D7 (correlated_subquery):** Postgres emite `SubPlan` para
    resolver NOT IN no correlacionado también — D7 dispara en Q19 a
    nivel plan. D21 es complementario: aporta la prosa específica del
    NULL trap, que D7 (genérico) no conoce.
  - **D20 (in_subquery_to_exists):** D20 cubre `IN`, D21 cubre
    `NOT IN`. Mutuamente excluyentes por el chequeo `_is_negated`.

Excepción legítima a R2: sqlglot opera sobre el AST del SQL, no sobre
texto crudo (mismo patrón que D9/D19/D20). El campo del snapshot
`is_nullable` viene del catálogo de Postgres vía B2 (no del usuario).

Cumple R1, R9, R14.
"""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from motor.detection import Detection
from motor.parser import ExplainResult, PlanNode


def detect_not_in_nullable_subquery(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
    *,
    sql: str | None = None,
) -> Detection:
    """Encuentra NOT IN (SELECT ...) sobre columnas nullable.

    Args:
        plan: árbol del plan parseado. No se usa directamente — el
            argumento existe por uniformidad de firma con el resto
            de detectores. La señal estructural vive 100% en SQL +
            snapshot.
        snapshot: SchemaSnapshot del conector. Se usa para verificar
            `is_nullable` de la columna del subquery interno.
        sql: query sanitizada con placeholders. Sin SQL devuelve
            found=False (igual que D9/D19/D20).

    Returns:
        Detection con un match por NOT IN no correlacionado cuya
        columna interna es nullable. Cada match incluye `column` (la
        columna del NOT IN en el outer), `inner_table`, `inner_column`,
        `inner_is_nullable` (True por construcción del match),
        `null_trap` (siempre True; señal para la capa de prosa de que
        es bug silencioso y no solo performance) y `suggested_rewrite`
        (SQL completo con NOT EXISTS correlacionado).
    """
    if sql is None:
        return Detection(found=False, confidence=0.0, evidence={"matches": []})

    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except sqlglot.errors.ParseError:
        return Detection(found=False, confidence=0.0, evidence={"matches": []})

    schema = snapshot.get("schema", {}) if isinstance(snapshot, dict) else {}

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

            if not _is_negated(in_expr):
                # IN (no NOT IN) — territorio de D20, no de D21.
                continue

            subquery_node = in_expr.args.get("query")
            if subquery_node is None:
                # NOT IN (literal_list) — la trampa NULL aplica
                # teóricamente, pero el detector se enfoca en
                # subqueries (donde el bug es mucho más común y el
                # rewrite a NOT EXISTS es claro). Listas literales
                # no son anti-pattern estructural; abstención.
                continue

            inner_select = (
                subquery_node.this
                if isinstance(subquery_node, exp.Subquery)
                else subquery_node
            )

            if _is_correlated(inner_select, outer_tables):
                # Subquery correlacionada — D7 ya la cubre vía SubPlan.
                continue

            inner_table = _first_from_table(inner_select)
            inner_column = _first_projected_column(inner_select)
            if inner_table is None or inner_column is None:
                continue

            # Verificación de nullability contra el snapshot.
            # Sin schema o tabla/columna desconocida → abstención
            # (evita FP).
            is_nullable = _column_is_nullable(schema, inner_table, inner_column)
            if is_nullable is not True:
                continue

            outer_col = in_expr.this
            outer_col_name = (
                outer_col.name if isinstance(outer_col, exp.Column) else None
            )

            suggested_rewrite = _build_rewrite(select, in_expr, inner_select)

            matches.append(
                {
                    "column": outer_col_name,
                    "inner_table": inner_table,
                    "inner_column": inner_column,
                    "inner_is_nullable": True,
                    "null_trap": True,
                    "suggested_rewrite": suggested_rewrite,
                }
            )

    return Detection(
        found=bool(matches),
        confidence=0.95 if matches else 0.0,
        evidence={"matches": matches},
    )


# ---------------------------------------------------------------------------
# Helpers — mismas convenciones que D20
# ---------------------------------------------------------------------------


def _is_negated(in_expr: exp.In) -> bool:
    """True si el IN está negado (NOT IN). NOT IN = exp.Not(this=exp.In(...))."""
    return isinstance(in_expr.parent, exp.Not)


def _from_table_names(select: exp.Select) -> set[str]:
    """Nombres y aliases de las tablas en el FROM del SELECT dado.

    Nota de compatibilidad sqlglot: versiones distintas almacenan la
    cláusula FROM bajo `"from"` o `"from_"` (este último porque `from`
    es palabra reservada de Python en versiones viejas). Probamos
    ambas para ser robustos a la versión instalada.
    """
    names: set[str] = set()
    from_clause = select.args.get("from") or select.args.get("from_")
    if from_clause is None:
        return names
    for table in from_clause.find_all(exp.Table):
        if table.alias:
            names.add(table.alias.lower())
        if table.name:
            names.add(table.name.lower())
    return names


def _is_correlated(subquery: exp.Select, outer_tables: set[str]) -> bool:
    """True si la subquery referencia columnas calificadas de las tablas
    externas. Sin calificador no podemos decidir, así que solo marcamos
    correlación con calificador explícito (mismo criterio que D20)."""
    for col in subquery.find_all(exp.Column):
        qualifier = col.table
        if qualifier and qualifier.lower() in outer_tables:
            return True
    return False


def _first_from_table(inner_select: exp.Select) -> str | None:
    """Nombre de la primera tabla del FROM del SELECT interior.

    Compatibilidad sqlglot: clave `"from"` (>=25) o `"from_"` (legado).
    """
    from_clause = inner_select.args.get("from") or inner_select.args.get("from_")
    if from_clause is None:
        return None
    tables = list(from_clause.find_all(exp.Table))
    return tables[0].name if tables else None


def _first_projected_column(inner_select: exp.Select) -> str | None:
    """Nombre de la primera columna proyectada por el SELECT interior.

    Solo nos interesan proyecciones que son columnas simples — si el
    SELECT proyecta una expresión (`COALESCE(col, 0)`, `col + 1`),
    no podemos razonar sobre nullability estructural; abstención.
    """
    if not inner_select.expressions:
        return None
    first = inner_select.expressions[0]
    if isinstance(first, exp.Column):
        return first.name
    return None


def _column_is_nullable(
    schema: dict[str, Any],
    table_name: str,
    column_name: str,
) -> bool | None:
    """Lee `is_nullable` del snapshot.

    Devuelve:
      - True  → columna existe y admite NULL (D21 dispara).
      - False → columna existe y es NOT NULL (D21 NO dispara: no hay
        trampa, NOT IN se puede convertir a Anti Join).
      - None  → tabla o columna no encontrada en el snapshot
        (D21 se abstiene para evitar FP).

    Resuelve la tabla por nombre corto buscando en todas las claves
    `<schema>.<tabla>` del snapshot. Si hay ambigüedad (mismo nombre
    en varios schemas), prefiere `public.<tabla>`; si tampoco existe,
    devuelve None.
    """
    target_key = None
    short = column_name.lower()
    for key in schema.keys():
        if "." in key:
            _, table_part = key.split(".", 1)
        else:
            table_part = key
        if table_part.lower() == table_name.lower():
            if key.lower() == f"public.{table_name.lower()}":
                target_key = key
                break
            if target_key is None:
                target_key = key

    if target_key is None:
        return None

    table_meta = schema.get(target_key, {})
    for col in table_meta.get("columns", []):
        if col.get("name", "").lower() == short:
            return bool(col.get("is_nullable", False))
    return None


def _build_rewrite(
    outer_select: exp.Select,
    in_expr: exp.In,
    inner_select: exp.Select,
) -> str:
    """Reescribe `col NOT IN (SELECT inner_col FROM t)` como
    `NOT EXISTS (SELECT 1 FROM t WHERE t.inner_col = col)`.

    Estrategia (espejo de D20):
    1. Clona el SELECT interior, reemplaza su proyección por `1`.
    2. Añade la condición de correlación `inner_col = outer_col` al
       WHERE interior (preservando un WHERE pre-existente con AND).
    3. Envuelve en `NOT EXISTS` y reemplaza todo el WHERE del outer.
       Si el WHERE original tenía AND/OR adicionales se pierden — la
       misma limitación que D20 (documentada).

    El SQL resultante es parseable con sqlglot.
    """
    outer_col = in_expr.this
    if not inner_select.expressions:
        return ""

    inner_col_expr = inner_select.expressions[0]
    corr = exp.EQ(this=inner_col_expr.copy(), expression=outer_col.copy())

    exists_sel = inner_select.copy()
    exists_sel.set("expressions", [exp.Literal.number(1)])
    inner_where = exists_sel.args.get("where")
    if inner_where:
        exists_sel.set(
            "where",
            exp.Where(this=exp.And(this=corr, expression=inner_where.this.copy())),
        )
    else:
        exists_sel.set("where", exp.Where(this=corr))

    not_exists_node = exp.Not(this=exp.Exists(this=exists_sel))

    outer_copy = outer_select.copy()
    outer_copy.set("where", exp.Where(this=not_exists_node))
    return outer_copy.sql(dialect="postgres")