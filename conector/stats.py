"""Extracción de estadísticas por columna desde `pg_stats`.

B4 del backlog. Para cada columna de cada tabla devuelve:
- `n_distinct`: número de valores distintos. Postgres usa convención
  ambigua: positivo = conteo absoluto, negativo = ratio respecto a
  filas totales (ej. -0.5 = 50% de filas tienen valor distinto).
- `null_frac`: fracción de filas con NULL en esa columna (0..1).
- `most_common_vals`: lista de valores más frecuentes como strings.
  Postgres devuelve `anyarray`; lo casteamos a `text[]` para que
  psycopg lo entregue como `list[str]`. Casos exóticos (composites,
  bytea) podrían perder fidelidad — aceptable para el motor que solo
  usa la longitud y la presencia.
- `correlation`: correlación física vs lógica del valor con el orden
  en disco (-1..1). Crítica para evaluar si un Index Scan será
  secuencial o aleatorio.

Una tabla recién creada o nunca `ANALYZE`-ada NO tiene fila en
`pg_stats`. Esas columnas se reportan con `has_stats=False` y todos
los campos numéricos en `None`. El consumidor debe distinguir
"sin estadísticas" de "estadísticas que dicen 0".
"""

from typing import TypedDict

from psycopg_pool import ConnectionPool


class ColumnStats(TypedDict):
    schema: str
    table: str
    column: str
    has_stats: bool
    n_distinct: float | None
    null_frac: float | None
    most_common_vals: list[str] | None
    correlation: float | None


# LEFT JOIN contra pg_stats: las columnas que nunca tuvieron ANALYZE
# aparecen con todos los campos de `s` en NULL. Discriminamos con
# `s.attname IS NOT NULL` para no confundir "sin stats" con "stats que
# legítimamente reportan null_frac=0".
#
# `inherited = false` evita las stats agregadas de tablas particionadas
# padre, que duplicarían filas y romperían el lookup por columna.
_STATS_QUERY = """
SELECT
    n.nspname AS schema_name,
    c.relname AS table_name,
    a.attname AS column_name,
    s.attname IS NOT NULL AS has_stats,
    s.n_distinct,
    s.null_frac,
    s.most_common_vals::text::text[] AS most_common_vals,
    s.correlation
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_stats s
    ON s.schemaname = n.nspname
   AND s.tablename = c.relname
   AND s.attname = a.attname
   AND COALESCE(s.inherited, false) = false
WHERE c.relkind = 'r'
  AND n.nspname = ANY(%s)
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY n.nspname, c.relname, a.attnum
"""


def get_column_stats(
    pool: ConnectionPool,
    schemas: tuple[str, ...] = ("public",),
) -> dict[str, dict[str, ColumnStats]]:
    """Devuelve estadísticas por columna para cada tabla en los schemas.

    Estructura del resultado:
    `{"<schema>.<tabla>": {"<columna>": ColumnStats, ...}, ...}`

    Las claves de tabla coinciden con las de `get_schema` y
    `get_table_sizes`, lo que permite intersecciones triviales en
    `/motor`.
    """
    schemas_list = list(schemas)
    result: dict[str, dict[str, ColumnStats]] = {}

    with pool.connection() as conn:
        for row in conn.execute(_STATS_QUERY, (schemas_list,)):
            (
                schema_name,
                table_name,
                column_name,
                has_stats,
                n_distinct,
                null_frac,
                most_common_vals,
                correlation,
            ) = row
            key = f"{schema_name}.{table_name}"
            table_stats = result.setdefault(key, {})
            table_stats[column_name] = ColumnStats(
                schema=schema_name,
                table=table_name,
                column=column_name,
                has_stats=bool(has_stats),
                n_distinct=float(n_distinct) if n_distinct is not None else None,
                null_frac=float(null_frac) if null_frac is not None else None,
                most_common_vals=list(most_common_vals) if most_common_vals is not None else None,
                correlation=float(correlation) if correlation is not None else None,
            )

    return result
