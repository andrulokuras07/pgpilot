import psycopg
import pytest
from psycopg_pool import ConnectionPool


@pytest.mark.integration
def test_select_funciona(appdb_pool: ConnectionPool) -> None:
    with appdb_pool.connection() as conn:
        result = conn.execute("SELECT 1").fetchone()
    assert result == (1,)


@pytest.mark.integration
def test_insert_rechazado_por_read_only(appdb_pool: ConnectionPool) -> None:
    # Intento de escritura sobre una tabla real de AppDB. Postgres debe
    # rechazar con read_only_sql_transaction (SQLSTATE 25006) antes de
    # validar siquiera el contenido.
    with appdb_pool.connection() as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("INSERT INTO users (username, email) VALUES ('x', 'x@x.com')")


@pytest.mark.integration
def test_ddl_rechazado_por_read_only(appdb_pool: ConnectionPool) -> None:
    with appdb_pool.connection() as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("CREATE TABLE pgpilot_should_not_exist (id int)")


@pytest.mark.integration
def test_statement_timeout_aborta_query_lenta(appdb_pool: ConnectionPool) -> None:
    # statement_timeout está fijado a 5000ms en el configure del pool;
    # un pg_sleep(10) debe ser cancelado por Postgres.
    with appdb_pool.connection() as conn:
        with pytest.raises(psycopg.errors.QueryCanceled):
            conn.execute("SELECT pg_sleep(10)")
