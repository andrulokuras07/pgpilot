"""Extracción de tamaños de tabla.

B3 del backlog. Devuelve para cada tabla:
- `estimated_rows`: `pg_class.reltuples` (estimado del último ANALYZE).
  Postgres pone -1 cuando la tabla nunca tuvo ANALYZE; en ese caso lo
  reportamos como 0 y la categoría queda `"unknown"`.
- `total_bytes`: `pg_total_relation_size` (heap + índices + toast).
- `category`: `"small" | "medium" | "large" | "unknown"`.

Los thresholds de categoría salen del backlog (B3) y los consume el
detector de seq scan en `/motor` para decidir si un Seq Scan es
problemático.
"""

from typing import Literal, TypedDict

from psycopg_pool import ConnectionPool

SMALL_ROWS_THRESHOLD = 100_000
LARGE_ROWS_THRESHOLD = 1_000_000

SizeCategory = Literal["small", "medium", "large", "unknown"]


class TableSize(TypedDict):
    schema: str
    name: str
    estimated_rows: int
    total_bytes: int
    category: SizeCategory


_SIZES_QUERY = """
SELECT
    n.nspname AS schema_name,
    c.relname AS table_name,
    c.reltuples AS estimated_rows,
    pg_total_relation_size(c.oid) AS total_bytes
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r' AND n.nspname = ANY(%s)
ORDER BY n.nspname, c.relname
"""


def categorize(estimated_rows: int) -> SizeCategory:
    """Clasifica una tabla por número estimado de filas.

    `-1` significa "Postgres no tiene estadísticas" (nunca corrió
    ANALYZE). En ese caso devolvemos `"unknown"` para que el motor no
    asuma cardinalidades inventadas.
    """
    if estimated_rows < 0:
        return "unknown"
    if estimated_rows < SMALL_ROWS_THRESHOLD:
        return "small"
    if estimated_rows < LARGE_ROWS_THRESHOLD:
        return "medium"
    return "large"


def get_table_sizes(
    pool: ConnectionPool,
    schemas: tuple[str, ...] = ("public",),
) -> dict[str, TableSize]:
    """Devuelve tamaño y categoría de cada tabla en los schemas indicados.

    Las claves del dict tienen la forma `"<schema>.<tabla>"` (mismo
    convenio que `get_schema`).
    """
    schemas_list = list(schemas)
    sizes: dict[str, TableSize] = {}

    with pool.connection() as conn:
        for row in conn.execute(_SIZES_QUERY, (schemas_list,)):
            schema_name, table_name, raw_rows, total_bytes = row
            estimated_rows = int(raw_rows)
            category = categorize(estimated_rows)
            key = f"{schema_name}.{table_name}"
            sizes[key] = TableSize(
                schema=schema_name,
                name=table_name,
                estimated_rows=max(estimated_rows, 0),
                total_bytes=int(total_bytes),
                category=category,
            )

    return sizes
