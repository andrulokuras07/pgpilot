"""Montaje y limpieza de schemas temporales en el sandbox.

B15 del backlog: dado un `SchemaSnapshot` (de `/conector`), crea un
schema temporal en el sandbox con las tablas vacías y los índices
declarados, y falsea las estadísticas de tamaño para que el planner
de Postgres produzca planes equivalentes a los que produciría sobre
la BD real, sin copiar ni una sola fila (R6).

Convenciones críticas:

- **Nombre del schema:** `analysis_<uuid_hex>` por default, configurable
  para tests determinísticos. UUID4 hex (32 chars) → 41 chars totales,
  bajo el límite de 63 bytes que Postgres impone a identificadores.
- **Tablas se crean planas en el schema temporal.** Si el snapshot
  contiene tablas en distintos schemas (`public.posts`,
  `analytics.events`), se crean todas en el schema temporal con su
  nombre simple. Si dos tablas tuvieran el mismo nombre en schemas
  distintos hay colisión: para AppDB v1 no aplica (todo está en
  `public`); para multi-schema queda como extensión futura.
- **No se replican FOREIGN KEYs.** No afectan al planner de SELECTs y
  complican el orden de creación. El detector lee los FKs del snapshot
  cuando los necesita; el sandbox no.
- **Tipos vienen tal cual del snapshot** (output de `format_type` en
  `pg_catalog`). No los traducimos: si AppDB declaró `character
  varying(50)`, ese mismo string va al CREATE TABLE. Si en el futuro
  un cliente usa una extensión (postgis, vector, citext) habrá que
  instalarla en el sandbox o caer a `text` por columna.
- **Stats falseadas:** `pg_restore_relation_stats` (PG18+). Persiste
  `relpages` y `reltuples` en `pg_class` con su validación nativa.
  Limitación conocida: el planner de Postgres también consulta el
  tamaño físico del archivo (`RelationGetNumberOfBlocks`) y para
  tablas físicamente vacías ese override empuja los costos a ~0. Esto
  no afecta a B15/B16 (lo que validamos es la estructura del plan)
  pero sí va a importar en C3 (validación de recomendaciones por
  costo): se atenderá ahí, probablemente insertando filas sintéticas
  acotadas o ampliando la lógica para razonar sobre cambios de tipo
  de nodo (Seq → Index) en vez de magnitudes absolutas de costo.
  Decisión registrada en PROGRESS 2026-05-10. Stats por columna
  (`pg_restore_attribute_stats`) se difieren.
- **Categoría `unknown`:** si el snapshot reporta una tabla sin
  ANALYZE, no tocamos sus stats. El planner usa sus defaults internos.
  Es más honesto que inventar un número.

Cumple R6 (sandbox no copia datos), R9 (función pura modulo I/O al
sandbox) y prepara la infraestructura para C3 (validación de
recomendaciones de índice) y E5/E6 (cleanup de zombies y timeouts
endurecidos).
"""

import uuid

from psycopg.sql import SQL, Identifier
from psycopg_pool import ConnectionPool

from conector.types import SchemaSnapshot


def setup_sandbox_schema(
    pool: ConnectionPool,
    snapshot: SchemaSnapshot,
    *,
    schema_name: str | None = None,
    timeout_ms: int = 5000,
) -> str:
    """Monta un schema temporal con las tablas y stats del snapshot.

    Devuelve el nombre del schema creado para que el caller pueda
    apuntar `search_path` a él y luego dropearlo (`drop_sandbox_schema`).

    Si `schema_name` es `None`, se genera uno único. Pasarlo explícito
    es útil en tests deterministas o cuando el caller quiere un nombre
    legible.

    El schema queda creado y commiteado al volver. Si una de las
    sentencias falla, la transacción se revierte y no queda schema
    parcial. Timeout duro de 5s por transacción (E6).
    """
    schema_name = schema_name or f"analysis_{uuid.uuid4().hex}"

    with pool.connection() as conn:
        with conn.transaction():
            conn.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
            conn.execute(SQL("CREATE SCHEMA {}").format(Identifier(schema_name)))

            for table in snapshot["schema"].values():
                _create_table(conn, schema_name, table)
                _create_indexes(conn, schema_name, table)

            for table_key, size in snapshot.get("sizes", {}).items():
                if size["category"] == "unknown":
                    continue
                table_name = size["name"]
                _set_relation_stats(
                    conn,
                    schema_name,
                    table_name,
                    estimated_rows=size["estimated_rows"],
                )

    return schema_name


def cleanup_zombie_schemas(
    pool: ConnectionPool,
    *,
    prefix: str = "analysis_",
) -> list[str]:
    """Dropea schemas zombies que quedaron de análisis anteriores.

    Un schema es zombie si matchea el prefijo `analysis_` y sigue
    existente — significa que un análisis previo crasheó entre el
    setup y el drop. Se llama al startup del backend (E5).

    Devuelve los nombres de schemas dropeados (para logging).
    """
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name LIKE %s",
            (f"{prefix}%",),
        ).fetchall()

    dropped: list[str] = []
    for (schema_name,) in rows:
        drop_sandbox_schema(pool, schema_name)
        dropped.append(schema_name)

    return dropped


def drop_sandbox_schema(
    pool: ConnectionPool,
    schema_name: str,
    *,
    timeout_ms: int = 5000,
) -> None:
    """Borra el schema temporal y todo su contenido.

    `IF EXISTS` para que un caller pueda llamarlo sin saber si el
    schema todavía está. `CASCADE` porque dentro hay tablas, índices
    y eventualmente constraints. Timeout duro de 5s (E6).
    """
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
            conn.execute(SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(Identifier(schema_name)))


def _create_table(conn, schema_name: str, table) -> None:
    """Crea una tabla vacía con sus columnas en el schema temporal.

    Tipos van tal cual los reportó `format_type` en el snapshot. La
    nullabilidad sí se respeta porque el planner la usa para optimizar
    LEFT JOINs y para descartar filtros tautológicos.
    """
    column_defs = []
    for col in table["columns"]:
        nullability = SQL("NULL") if col["is_nullable"] else SQL("NOT NULL")
        column_defs.append(
            SQL("{} {} {}").format(
                Identifier(col["name"]),
                SQL(col["data_type"]),
                nullability,
            )
        )

    stmt = SQL("CREATE TABLE {}.{} ({})").format(
        Identifier(schema_name),
        Identifier(table["name"]),
        SQL(", ").join(column_defs),
    )
    conn.execute(stmt)


def _create_indexes(conn, schema_name: str, table) -> None:
    """Recrea los índices de la tabla en el schema temporal.

    Tanto índices simples como los implícitos de PRIMARY KEY o UNIQUE
    constraints (todos llegan al snapshot en `indexes`). Los nombres
    de índice se conservan porque viven en el namespace del schema
    temporal — no colisionan con índices de otros schemas o de otra
    corrida concurrente.

    El método (`btree`, `gin`, `gist`, etc.) viene del snapshot. No
    sanitizamos: confiamos en `pg_catalog`.
    """
    for idx in table["indexes"]:
        unique = SQL("UNIQUE ") if idx["is_unique"] else SQL("")
        cols = SQL(", ").join(Identifier(c) for c in idx["columns"])
        stmt = SQL("CREATE {}INDEX {} ON {}.{} USING {} ({})").format(
            unique,
            Identifier(idx["name"]),
            Identifier(schema_name),
            Identifier(table["name"]),
            SQL(idx["method"]),
            cols,
        )
        conn.execute(stmt)


def _set_relation_stats(
    conn,
    schema_name: str,
    table_name: str,
    *,
    estimated_rows: int,
) -> None:
    """Falsea `reltuples` y `relpages` con `pg_restore_relation_stats`.

    Función nativa de Postgres 18+, pensada para el flujo
    `pg_dump --statistics-only` / `pg_restore --statistics-only`.
    Persiste los valores en `pg_class` con la validación interna
    apropiada.

    Limitación documentada en el docstring del módulo: el planner
    también consulta el tamaño físico del archivo y, para tablas
    físicamente vacías, los costos colapsan a ~0 aunque pg_class diga
    otra cosa. Esto se atenderá en C3 si la validación de
    recomendaciones lo requiere.

    `relpages` se aproxima a `rows / 100` (heurística de ~100 filas
    por página de 8KB). La densidad (rows/page) sí queda almacenada
    correctamente y es lo que importa el día que C3 razone sobre
    cambios de tipo de nodo en el plan.

    El usuario del sandbox debe poder ejecutar `pg_restore_relation_stats`
    — el rol `sandbox_user` del contenedor oficial lo es (superuser
    por default).
    """
    relpages = max(1, estimated_rows // 100)

    conn.execute(
        "SELECT pg_catalog.pg_restore_relation_stats("
        "  'schemaname'::text, %s::text, "
        "  'relname'::text, %s::text, "
        "  'relpages'::text, %s::int, "
        "  'reltuples'::text, %s::real"
        ")",
        (schema_name, table_name, int(relpages), float(estimated_rows)),
    )
