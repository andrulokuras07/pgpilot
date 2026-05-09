"""Extracción de schema (tablas, columnas, índices, foreign keys).

B2 del backlog. Lee metadata de `pg_catalog` y devuelve un dict
estructurado por (schema, tabla). NO incluye estadísticas (B4) ni
tamaños (B3).

Las consultas se hacen sobre `pg_catalog` (no `information_schema`)
porque pg_catalog tiene representación canónica para FKs compuestos
y orden de columnas en índices, datos que information_schema pierde
o representa de forma frágil.
"""

from typing import TypedDict

from psycopg_pool import ConnectionPool


class ColumnInfo(TypedDict):
    name: str
    data_type: str
    is_nullable: bool
    ordinal_position: int


class IndexInfo(TypedDict):
    name: str
    columns: list[str]
    method: str
    is_unique: bool
    is_primary: bool


class ForeignKeyInfo(TypedDict):
    name: str
    columns: list[str]
    referenced_schema: str
    referenced_table: str
    referenced_columns: list[str]


class TableSchema(TypedDict):
    schema: str
    name: str
    columns: list[ColumnInfo]
    indexes: list[IndexInfo]
    foreign_keys: list[ForeignKeyInfo]


_COLUMNS_QUERY = """
SELECT
    n.nspname AS schema_name,
    c.relname AS table_name,
    a.attname AS column_name,
    format_type(a.atttypid, a.atttypmod) AS data_type,
    NOT a.attnotnull AS is_nullable,
    a.attnum AS ordinal_position
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r'
  AND n.nspname = ANY(%s)
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY n.nspname, c.relname, a.attnum
"""

_INDEXES_QUERY = """
WITH idx_cols AS (
    SELECT
        ix.indexrelid,
        ix.indrelid,
        ix.indisunique,
        ix.indisprimary,
        a.attname,
        u.ord
    FROM pg_index ix
    JOIN unnest(ix.indkey::int[]) WITH ORDINALITY AS u(attnum, ord) ON TRUE
    JOIN pg_attribute a
      ON a.attrelid = ix.indrelid
     AND a.attnum = u.attnum
    WHERE u.attnum > 0
)
SELECT
    n.nspname AS schema_name,
    t.relname AS table_name,
    i.relname AS index_name,
    am.amname AS method,
    bool_or(ic.indisunique) AS is_unique,
    bool_or(ic.indisprimary) AS is_primary,
    array_agg(ic.attname ORDER BY ic.ord) AS columns
FROM idx_cols ic
JOIN pg_class i ON i.oid = ic.indexrelid
JOIN pg_class t ON t.oid = ic.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
JOIN pg_am am ON am.oid = i.relam
WHERE n.nspname = ANY(%s)
GROUP BY ic.indexrelid, n.nspname, t.relname, i.relname, am.amname
ORDER BY n.nspname, t.relname, i.relname
"""

_FKS_QUERY = """
SELECT
    n.nspname AS schema_name,
    t.relname AS table_name,
    c.conname AS fk_name,
    array_agg(a.attname ORDER BY u.ord) AS columns,
    nf.nspname AS referenced_schema,
    tf.relname AS referenced_table,
    array_agg(af.attname ORDER BY u.ord) AS referenced_columns
FROM pg_constraint c
JOIN pg_class t ON t.oid = c.conrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
JOIN pg_class tf ON tf.oid = c.confrelid
JOIN pg_namespace nf ON nf.oid = tf.relnamespace
JOIN unnest(c.conkey, c.confkey) WITH ORDINALITY AS u(conkey, confkey, ord) ON TRUE
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = u.conkey
JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = u.confkey
WHERE c.contype = 'f' AND n.nspname = ANY(%s)
GROUP BY n.nspname, t.relname, c.conname, nf.nspname, tf.relname
ORDER BY n.nspname, t.relname, c.conname
"""


def get_schema(
    pool: ConnectionPool,
    schemas: tuple[str, ...] = ("public",),
) -> dict[str, TableSchema]:
    """Devuelve el schema de las tablas en los schemas indicados.

    Las claves del dict resultante tienen la forma `"<schema>.<tabla>"`
    para evitar colisiones cuando hay tablas con el mismo nombre en
    schemas diferentes.

    El pool debe ser read-only (lo es por construcción de `create_pool`).
    """
    schemas_list = list(schemas)
    tables: dict[str, TableSchema] = {}

    with pool.connection() as conn:
        for row in conn.execute(_COLUMNS_QUERY, (schemas_list,)):
            schema_name, table_name, col_name, data_type, is_nullable, pos = row
            key = f"{schema_name}.{table_name}"
            table = tables.setdefault(
                key,
                TableSchema(
                    schema=schema_name,
                    name=table_name,
                    columns=[],
                    indexes=[],
                    foreign_keys=[],
                ),
            )
            table["columns"].append(
                ColumnInfo(
                    name=col_name,
                    data_type=data_type,
                    is_nullable=is_nullable,
                    ordinal_position=pos,
                )
            )

        for row in conn.execute(_INDEXES_QUERY, (schemas_list,)):
            schema_name, table_name, idx_name, method, is_unique, is_primary, cols = row
            key = f"{schema_name}.{table_name}"
            if key not in tables:
                continue
            tables[key]["indexes"].append(
                IndexInfo(
                    name=idx_name,
                    columns=list(cols),
                    method=method,
                    is_unique=is_unique,
                    is_primary=is_primary,
                )
            )

        for row in conn.execute(_FKS_QUERY, (schemas_list,)):
            (
                schema_name,
                table_name,
                fk_name,
                cols,
                ref_schema,
                ref_table,
                ref_cols,
            ) = row
            key = f"{schema_name}.{table_name}"
            if key not in tables:
                continue
            tables[key]["foreign_keys"].append(
                ForeignKeyInfo(
                    name=fk_name,
                    columns=list(cols),
                    referenced_schema=ref_schema,
                    referenced_table=ref_table,
                    referenced_columns=list(ref_cols),
                )
            )

    return tables
