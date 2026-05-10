"""Pool de conexiones al sandbox Postgres efímero.

Diferencias con `conector/pool.py`:

- **NO** se aplica `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`.
  El sandbox necesita CREATE SCHEMA, CREATE TABLE, CREATE INDEX,
  UPDATE pg_class y DROP SCHEMA. La regla R7 (read-only forzado)
  aplica sólo al pool del cliente — aquí estaríamos enmascarando
  bugs si la copiamos.
- Sí se aplica `SET statement_timeout`. El backlog (B16) y la regla
  operativa exigen timeout duro de 5s en cualquier interacción con
  el sandbox; el default de `SandboxConfig` ya es 5000.

El usuario del sandbox debe ser superuser en su BD: el setup falsea
estadísticas con `UPDATE pg_class`, lo cual requiere el rol superuser
(en el contenedor oficial de Postgres, `POSTGRES_USER` se crea con
SUPERUSER por defecto, así que el `sandbox_user` del compose cumple).
"""

from psycopg import Connection
from psycopg_pool import ConnectionPool

from sandbox.config import SandboxConfig


def create_sandbox_pool(config: SandboxConfig) -> ConnectionPool:
    """Crea un pool de conexiones al sandbox Postgres.

    Cada conexión queda con `statement_timeout` aplicado a nivel de
    sesión. NO se fuerza read-only: el sandbox necesita DDL para
    montar y desmontar schemas temporales.

    `open=True` para que un sandbox caído falle al instante en lugar
    de en la primera query, mismo criterio que `conector/pool.py`.
    """
    conninfo = (
        f"host={config.host} port={config.port} dbname={config.dbname} "
        f"user={config.user} password={config.password}"
    )

    def configure(conn: Connection) -> None:
        conn.execute(f"SET statement_timeout = {config.statement_timeout_ms}")
        conn.commit()

    return ConnectionPool(
        conninfo=conninfo,
        min_size=config.min_pool_size,
        max_size=config.max_pool_size,
        configure=configure,
        open=True,
    )
