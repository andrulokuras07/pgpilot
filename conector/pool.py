from psycopg import Connection
from psycopg_pool import ConnectionPool

from conector.config import ConnectionConfig


def create_pool(config: ConnectionConfig) -> ConnectionPool:
    """Crea un pool de conexiones psycopg forzadas a read-only.

    Cada conexión que entrega el pool tiene aplicado a nivel de sesión:
      - SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY
      - SET statement_timeout = config.statement_timeout_ms

    Postgres rechaza con SQLSTATE 25006 (read_only_sql_transaction)
    cualquier INSERT/UPDATE/DELETE/DDL/TRUNCATE en estas conexiones.

    Cumple R7 (las conexiones a la BD del cliente son siempre read-only)
    y la regla operativa de timeout duro de 5s.
    """
    conninfo = (
        f"host={config.host} port={config.port} dbname={config.dbname} "
        f"user={config.user} password={config.password}"
    )

    def configure(conn: Connection) -> None:
        conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        conn.execute(f"SET statement_timeout = {config.statement_timeout_ms}")
        conn.commit()

    return ConnectionPool(
        conninfo=conninfo,
        min_size=config.min_pool_size,
        max_size=config.max_pool_size,
        configure=configure,
        open=True,
    )
