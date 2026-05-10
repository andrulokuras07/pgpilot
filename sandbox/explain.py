"""Ejecución de EXPLAIN sobre el sandbox montado.

B16 del backlog: monta un schema temporal con `setup_sandbox_schema`,
corre `EXPLAIN (FORMAT JSON)` sobre la query del usuario apuntando
`search_path` al schema temporal, parsea la respuesta con
`motor.parse_explain` y dropea el schema antes de devolver el plan.

Diseño:

- **EXPLAIN sin ANALYZE.** Las tablas están vacías; con ANALYZE el
  plan refleja la realidad (todo escanea 0 filas) y pierde valor. Sin
  ANALYZE, el planner usa `pg_class.reltuples`/`relpages` (que
  falsificamos en `setup_sandbox_schema`) y produce el mismo plan
  estimado que produciría sobre la BD real.

- **`search_path` se setea con `SET LOCAL`** dentro de una transacción,
  así no hay que resetearlo manualmente: al cerrar la transacción
  Postgres lo descarta y la conexión queda limpia para el siguiente
  caller del pool.

- **Timeout duro.** El pool ya aplica `statement_timeout` por sesión
  (default 5s, configurable en `SandboxConfig`). `explain_in_sandbox`
  permite overridearlo per-call con `timeout_seconds`, útil para
  tests que quieren forzar un timeout corto. Si excede, Postgres
  aborta con `QueryCanceled`/SQLSTATE `57014` y el `try/finally`
  garantiza que el schema temporal igual se dropea.

- **Cleanup en `finally`.** Si el EXPLAIN falla (query inválida,
  timeout, tabla no existe), igual se dropea el schema. Si el drop
  también falla (sandbox caído), la excepción del EXPLAIN se preserva
  como causa principal.

Cumple R6 (no copia datos), R9 (idempotente desde la perspectiva del
caller: cada llamada es self-contained) y prepara la base para C3
(validación de recomendaciones de índice antes/después).
"""

from psycopg.sql import SQL, Identifier
from psycopg_pool import ConnectionPool

from conector.types import SchemaSnapshot
from motor import ExplainResult, parse_explain
from sandbox.setup import drop_sandbox_schema, setup_sandbox_schema


def explain_in_sandbox(
    pool: ConnectionPool,
    snapshot: SchemaSnapshot,
    query: str,
    *,
    timeout_seconds: float = 5.0,
    schema_name: str | None = None,
) -> ExplainResult:
    """Monta sandbox, corre EXPLAIN, devuelve plan parseado, dropea sandbox.

    Parámetros:
    - `pool`: pool del sandbox (no del cliente). Debe permitir DDL.
    - `snapshot`: schema + sizes + stats del cliente. Cualquier fuente
      válida — extracción viva (`extract_snapshot`), cache local, o
      bundle offline.
    - `query`: el SELECT a analizar. NO se sanitiza ni se reescribe.
      Se asume que el caller ya validó el SQL si era necesario; aquí
      sólo se ejecuta dentro de `EXPLAIN`, que no corre la query (sin
      ANALYZE) — incluso un DELETE pasaría sin tocar datos, pero el
      contrato del módulo es "EXPLAIN de SELECT".
    - `timeout_seconds`: límite duro para el EXPLAIN. 5s por default
      (regla operativa). Aplicado vía `SET LOCAL statement_timeout`.
    - `schema_name`: opcional. Si se provee, se usa ese nombre de
      schema temporal (útil para tests deterministas). Si no, se
      genera con UUID.

    Devuelve un `motor.ExplainResult` listo para los detectores.
    """
    schema_name = setup_sandbox_schema(pool, snapshot, schema_name=schema_name)
    timeout_ms = max(1, int(timeout_seconds * 1000))

    try:
        with pool.connection() as conn:
            with conn.transaction():
                # SET LOCAL no admite parámetros por placeholder en psycopg,
                # pero el valor es un int controlado por nosotros — sin
                # superficie de inyección.
                conn.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
                conn.execute(
                    SQL("SET LOCAL search_path = {}, public").format(Identifier(schema_name))
                )
                cur = conn.execute(f"EXPLAIN (FORMAT JSON) {query}")
                row = cur.fetchone()

        if row is None:
            raise RuntimeError("EXPLAIN no devolvió filas (caso imposible en Postgres)")

        return parse_explain(row[0])
    finally:
        drop_sandbox_schema(pool, schema_name)
